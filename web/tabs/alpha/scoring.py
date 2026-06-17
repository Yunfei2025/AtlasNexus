# -*- coding: utf-8 -*-
"""Correlation, risk parity, and scoring functions for the Alpha Book tabs."""

from __future__ import annotations

from typing import Dict, List, Any, Optional, Tuple

import numpy as np
import pandas as pd

from .data import load_spread_timeseries


def compute_spread_correlation(
    spread_types: List[str],
    lookback_days: int = 252,
) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """Compute correlation matrix of spread changes across selected types."""
    all_spreads = {}

    for stype in spread_types:
        ts = load_spread_timeseries(stype)
        if ts is not None and isinstance(ts, pd.DataFrame):
            ts = ts.tail(lookback_days)
            for col in ts.columns:
                all_spreads[f"{stype}|{col}"] = ts[col]

    if len(all_spreads) < 2:
        return None, None

    df_spreads = pd.DataFrame(all_spreads)
    df_changes = df_spreads.diff().dropna()

    if df_changes.shape[0] < 20:
        return None, None

    corr_matrix = df_changes.corr()
    return corr_matrix, df_changes


def rank_low_correlation_pairs(
    corr_matrix: pd.DataFrame,
    top_n: int = 10,
) -> pd.DataFrame:
    """Rank pairs by lowest absolute correlation."""
    mask = np.triu(np.ones(corr_matrix.shape), k=1).astype(bool)
    corr_stacked = corr_matrix.where(mask).stack().reset_index()
    corr_stacked.columns = ['Asset A', 'Asset B', 'Correlation']
    corr_stacked['AbsCorr'] = corr_stacked['Correlation'].abs()
    return corr_stacked.sort_values('AbsCorr', ascending=True).head(top_n)


def risk_parity_weights(
    cov_matrix: pd.DataFrame,
    risk_budget: Optional[Dict[str, float]] = None,
) -> pd.Series:
    """Compute risk parity weights given covariance matrix."""
    n = cov_matrix.shape[0]
    assets = cov_matrix.columns.tolist()

    if risk_budget is None:
        target_rc = np.ones(n) / n
    else:
        target_rc = np.array([risk_budget.get(a, 1/n) for a in assets])
        target_rc = target_rc / target_rc.sum()

    cov = cov_matrix.values

    w = np.ones(n) / n
    for _ in range(100):
        port_var = w.T @ cov @ w
        if port_var < 1e-12:
            break
        marginal_risk = cov @ w
        risk_contrib = w * marginal_risk / np.sqrt(port_var)
        total_risk = np.sum(risk_contrib)
        if total_risk < 1e-12:
            break
        rc_pct = risk_contrib / total_risk
        adjustment = target_rc / (rc_pct + 1e-8)
        w = w * adjustment
        w = w / w.sum()

    return pd.Series(w, index=assets)


def _compute_risk_parity_weights(df_candidates: pd.DataFrame) -> Tuple[Dict[str, float], np.ndarray]:
    """Compute risk parity weights for alpha candidates using historical spread data."""
    from scipy.optimize import minimize

    spread_series: Dict[str, pd.Series] = {}
    ts_cache: Dict[str, Any] = {}

    for _, row in df_candidates.iterrows():
        trade_id = row['ID']
        spread_type = row.get('spread_type', '')
        try:
            if spread_type not in ts_cache:
                ts_cache[spread_type] = load_spread_timeseries(spread_type)
            ts = ts_cache[spread_type]
            if ts is not None and isinstance(ts, pd.DataFrame) and trade_id in ts.columns:
                spread_series[trade_id] = ts[trade_id].dropna().tail(252)
        except Exception as e:
            print(f"Warning: Could not load spread time-series for {trade_id}: {e}")

    if len(spread_series) < 2:
        print("⚠ Insufficient historical data for risk parity, using inverse volatility")
        n = len(df_candidates)
        weights = dict(zip(df_candidates['ID'], [1/n] * n))
        risk_contrib = np.ones(n) / n
        return weights, risk_contrib

    # Normalise index types (datetime.date vs str mismatch causes all rows to be NaN
    # after DataFrame alignment, triggering the equal-weight fallback).
    for _s in spread_series.values():
        _s.index = _s.index.astype(str)
    spread_df = pd.DataFrame(spread_series).dropna()

    if len(spread_df) < 20:
        print("⚠ Too few common dates for covariance, using inverse volatility")
        n = len(df_candidates)
        weights = dict(zip(df_candidates['ID'], [1/n] * n))
        risk_contrib = np.ones(n) / n
        return weights, risk_contrib

    returns = spread_df.diff().dropna()
    # Winsorise each column using Tukey fences (IQR-based) to remove bad-tick
    # spikes that would otherwise inflate the covariance matrix by orders of
    # magnitude and make all risk contributions collapse to near zero.
    for col in returns.columns:
        _q1 = returns[col].quantile(0.25)
        _q3 = returns[col].quantile(0.75)
        _iqr = _q3 - _q1
        if _iqr > 0:
            returns[col] = returns[col].clip(lower=_q1 - 5 * _iqr, upper=_q3 + 5 * _iqr)
    cov_matrix = returns.cov()
    cov = cov_matrix.values
    n = len(cov)

    def _risk_contribution(w, cov):
        port_var = w.T @ cov @ w
        if port_var < 1e-12:
            return np.ones(len(w)) / len(w)
        marginal_risk = cov @ w
        return (w * marginal_risk) / port_var

    def _objective(w, cov):
        rc = _risk_contribution(w, cov)
        target = 1.0 / len(w)
        return np.sum((rc - target) ** 2)

    constraints = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}]
    min_w = 1.0 / (3 * n)
    max_w = min(0.5, 1.0 - min_w * (n - 1))
    bounds = [(min_w, max_w) for _ in range(n)]
    w0 = np.ones(n) / n

    result = minimize(
        _objective,
        w0,
        args=(cov,),
        method='SLSQP',
        bounds=bounds,
        constraints=constraints,
        options={'maxiter': 1000, 'ftol': 1e-9}
    )

    if not result.success:
        print(f"⚠ Risk parity optimization did not converge: {result.message}")
        weights_array = np.ones(n) / n
    else:
        weights_array = result.x

    weights_array = np.clip(weights_array, min_w, max_w)
    weights_array = weights_array / weights_array.sum()
    risk_contrib = _risk_contribution(weights_array, cov)

    weights_dict = {col: w for col, w in zip(spread_df.columns, weights_array)}
    print(f"✓ Risk parity optimised: weight std={weights_array.std():.4f}, "
          f"RC std={risk_contrib.std():.4f}, min_w={weights_array.min():.4f}")

    return weights_dict, risk_contrib


def compute_candidate_scores(
    df: pd.DataFrame,
    weights: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """Compute composite scores for candidates."""
    if weights is None:
        weights = {
            'zscore': 0.40,
            'mr_conf': 0.30,
            'vol_adj': 0.15,
            'liquidity': 0.15,
        }

    df = df.copy()

    if 'Zscore' in df.columns:
        abs_z = df['Zscore'].abs()
        df['zscore_score'] = (abs_z / abs_z.max() * 100).clip(0, 100)
    else:
        df['zscore_score'] = 50

    if 'halflife' in df.columns and 'stationary' in df.columns:
        hl = df['halflife'].clip(1, 120)
        hl_score = (1 - hl / 120) * 100
        stat_score = (df['stationary'] == 'YES').astype(float) * 50
        df['mr_score'] = (hl_score * 0.5 + stat_score).fillna(25)
    else:
        df['mr_score'] = 50

    if 'vol' in df.columns:
        vol = df['vol'].abs()
        vol_norm = vol / vol.max()
        df['vol_score'] = ((1 - vol_norm) * 100).clip(0, 100)
    else:
        df['vol_score'] = 50

    df['liquidity_score'] = 50

    df['composite_score'] = (
        weights['zscore'] * df['zscore_score'] +
        weights['mr_conf'] * df['mr_score'] +
        weights['vol_adj'] * df['vol_score'] +
        weights['liquidity'] * df['liquidity_score']
    )

    return df


def compute_scan_score(
    df: pd.DataFrame,
    *,
    seasonal_data: "dict | None" = None,
    seasonal_month: "int | None" = None,
    seasonal_p_threshold: float = 0.10,
) -> pd.DataFrame:
    """Compute lightweight scan-time score for ranking and filtering.

    Parameters
    ----------
    df :
        Candidates DataFrame (requires columns: style, spread, mean, halflife,
        carry_roll, vol, direction; spread_type and ID for seasonal lookup).
    seasonal_data :
        Pre-loaded ``seasonal-spds.pkl`` dict
        ``{spread_type: DataFrame[instrument × month_key]}``.
        When provided together with *seasonal_month*, a
        ``seasonal_edge_bps`` column is added and included in the composite score.
    seasonal_month :
        Calendar month (1-12) for the seasonal edge lookup.
        Defaults to ``datetime.date.today().month`` when *seasonal_data* is given
        but *seasonal_month* is not supplied.
    seasonal_p_threshold :
        Only include the seasonal edge for cells whose binomial p-value is below
        this threshold (one-sided, no FDR correction). Default 0.10.
    """
    import datetime as _dt

    df = df.copy()

    style = (
        df['style'].astype(str).str.strip().str.lower()
        if 'style' in df.columns
        else pd.Series('', index=df.index, dtype=str)
    )
    is_mr = style.eq('meanreversion')

    spread = (
        pd.to_numeric(df['spread'], errors='coerce')
        if 'spread' in df.columns
        else pd.Series(np.nan, index=df.index, dtype=float)
    )
    mean = (
        pd.to_numeric(df['mean'], errors='coerce')
        if 'mean' in df.columns
        else pd.Series(np.nan, index=df.index, dtype=float)
    )
    halflife = (
        pd.to_numeric(df['halflife'], errors='coerce')
        if 'halflife' in df.columns
        else pd.Series(np.nan, index=df.index, dtype=float)
    )
    carry = (
        pd.to_numeric(df['carry_roll'], errors='coerce')
        if 'carry_roll' in df.columns
        else pd.Series(np.nan, index=df.index, dtype=float)
    )
    vol = (
        pd.to_numeric(df['vol'], errors='coerce').abs()
        if 'vol' in df.columns
        else pd.Series(np.nan, index=df.index, dtype=float)
    )

    risk = vol.replace(0, np.nan)
    fallback_risk = float(risk.median(skipna=True)) if not risk.dropna().empty else 1.0
    if not np.isfinite(fallback_risk) or fallback_risk <= 0:
        fallback_risk = 1.0
    risk = risk.fillna(fallback_risk)

    hl = halflife.replace(0, np.nan).abs()
    kappa_mr = (np.log(2) / hl).replace([np.inf, -np.inf], np.nan)
    reversion_factor = (1.0 - np.exp(-kappa_mr * 30.0)).fillna(0.0).clip(0.0, 1.0)
    expected_mr = (spread - mean).abs() * reversion_factor

    direction = (
        df['direction'].astype(str).str.strip().str.upper()
        if 'direction' in df.columns
        else pd.Series('', index=df.index, dtype=str)
    )
    dir_sign = pd.Series(1.0, index=df.index, dtype=float)
    dir_sign.loc[direction.eq('SELL')] = -1.0
    carry_basis_days = (
        pd.to_numeric(df['carry_basis_days'], errors='coerce')
        if 'carry_basis_days' in df.columns
        else pd.Series(90.0, index=df.index, dtype=float)
    )
    carry_basis_days = carry_basis_days.where(carry_basis_days.gt(0) & np.isfinite(carry_basis_days), 90.0)
    expected_tc = (carry.fillna(0.0) / 100.0) * dir_sign * (30.0 / carry_basis_days)

    expected_move = expected_tc.where(~is_mr, expected_mr)
    edge = expected_move.fillna(0.0)

    # ── Seasonal edge term ─────────────────────────────────────────────────────
    seasonal_edge = pd.Series(0.0, index=df.index, dtype=float)
    if seasonal_data and isinstance(seasonal_data, dict):
        month = int(seasonal_month or _dt.date.today().month)
        month_key = f'm{month}'
        has_stype = 'spread_type' in df.columns
        has_id    = 'ID' in df.columns
        if has_stype and has_id:
            for idx in df.index:
                stype = str(df.at[idx, 'spread_type'])
                inst  = str(df.at[idx, 'ID'])
                sdf   = seasonal_data.get(stype)
                if not isinstance(sdf, pd.DataFrame) or inst not in sdf.index:
                    continue
                if month_key not in sdf.columns:
                    continue
                cell = sdf.at[inst, month_key]
                if not isinstance(cell, dict):
                    continue
                p_val = float(cell.get('p_value', 1.0))
                if p_val >= seasonal_p_threshold:
                    continue
                avg_chg = float(cell.get('avg_chg_bp', 0.0))
                seas_dir = str(cell.get('direction', 'neutral'))
                # Sign the edge by trade direction vs seasonal direction.
                # BUY profits when spread widens (up); SELL profits when spread narrows (down).
                trade_dir = direction.at[idx]
                dir_match = (
                    (trade_dir == 'BUY'  and seas_dir == 'up')
                    or (trade_dir == 'SELL' and seas_dir == 'down')
                )
                signed_edge = abs(avg_chg) if dir_match else -abs(avg_chg)
                seasonal_edge.at[idx] = signed_edge

    df['seasonal_edge_bps'] = seasonal_edge

    # ── Seasonal label (independent of p-value gate) ───────────────────────────
    # Uses consistency + direction alignment only so the label works even when
    # n_years is too small for statistical significance.
    # Labels: 'strong' | 'weak' | 'against' | '' (no data)
    seasonal_label = pd.Series('', index=df.index, dtype=str)
    if seasonal_data and isinstance(seasonal_data, dict):
        month = int(seasonal_month or _dt.date.today().month)
        month_key = f'm{month}'
        if 'spread_type' in df.columns and 'ID' in df.columns:
            for idx in df.index:
                stype = str(df.at[idx, 'spread_type'])
                inst  = str(df.at[idx, 'ID'])
                sdf   = seasonal_data.get(stype)
                if not isinstance(sdf, pd.DataFrame) or inst not in sdf.index:
                    continue
                if month_key not in sdf.columns:
                    continue
                cell = sdf.at[inst, month_key]
                if not isinstance(cell, dict):
                    continue
                cons     = float(cell.get('consistency', 0.0))
                seas_dir = str(cell.get('direction', 'neutral'))
                trade_dir = direction.at[idx]
                tailwind = (
                    (trade_dir == 'BUY'  and seas_dir == 'up')
                    or (trade_dir == 'SELL' and seas_dir == 'down')
                )
                if cons >= 0.75:
                    seasonal_label.at[idx] = 'strong' if tailwind else 'against'
                elif cons >= 0.60:
                    seasonal_label.at[idx] = 'weak' if tailwind else 'against'
    df['seasonal_label'] = seasonal_label

    total_edge = edge + seasonal_edge / 100.0  # seasonal edge is in bp; edge is in price units
    df['edge_preview'] = total_edge
    df['composite_score_preview'] = (total_edge / risk).replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0)

    return df


def compute_unified_edge_vol_score(
    df: pd.DataFrame,
    *,
    mom_window: int = 20,
    mom_k: float = 1.0,
) -> pd.DataFrame:
    """Compute a unified, weightless score across MR and Carry/Trend."""
    from .data import _get_input_dir

    df = df.copy()

    style = (
        df['style'].astype(str).str.strip().str.lower()
        if 'style' in df.columns
        else pd.Series('', index=df.index, dtype=str)
    )
    is_mr = style.eq('meanreversion')

    spread = (
        pd.to_numeric(df['spread'], errors='coerce')
        if 'spread' in df.columns
        else pd.Series(np.nan, index=df.index, dtype=float)
    )
    mean = (
        pd.to_numeric(df['mean'], errors='coerce')
        if 'mean' in df.columns
        else pd.Series(np.nan, index=df.index, dtype=float)
    )
    halflife = (
        pd.to_numeric(df['halflife'], errors='coerce')
        if 'halflife' in df.columns
        else pd.Series(np.nan, index=df.index, dtype=float)
    )
    carry = (
        pd.to_numeric(df['carry_roll'], errors='coerce')
        if 'carry_roll' in df.columns
        else pd.Series(np.nan, index=df.index, dtype=float)
    )
    vol = (
        pd.to_numeric(df['vol'], errors='coerce').abs()
        if 'vol' in df.columns
        else pd.Series(np.nan, index=df.index, dtype=float)
    )

    risk = vol.replace(0, np.nan)
    fallback_risk = float(risk.median(skipna=True)) if not risk.dropna().empty else 1.0
    if not np.isfinite(fallback_risk) or fallback_risk <= 0:
        fallback_risk = 1.0
    risk = risk.fillna(fallback_risk)

    carry_basis_days = (
        pd.to_numeric(df['carry_basis_days'], errors='coerce')
        if 'carry_basis_days' in df.columns
        else pd.Series(90.0, index=df.index, dtype=float)
    )
    carry_basis_days = carry_basis_days.where(carry_basis_days.gt(0) & np.isfinite(carry_basis_days), 90.0)
    carry_per_day = carry / carry_basis_days
    df['carry_per_day'] = carry_per_day

    mom_window_i = int(mom_window) if mom_window is not None else 20
    if mom_window_i < 1:
        mom_window_i = 1
    try:
        mom_k_f = float(mom_k) if mom_k is not None else 1.0
    except Exception:
        mom_k_f = 1.0

    momentum_per_day = pd.Series(np.nan, index=df.index, dtype=float)
    if 'momentum_per_day' in df.columns:
        momentum_per_day = pd.to_numeric(df['momentum_per_day'], errors='coerce')
    elif 'mom_per_day' in df.columns:
        momentum_per_day = pd.to_numeric(df['mom_per_day'], errors='coerce')
    elif {'spread_type', 'ID'}.issubset(df.columns):
        try:
            from curves.refreshers.alpha import load_historical_spread_series

            dir_input = _get_input_dir()
            df_tc = df.loc[~is_mr, ['spread_type', 'ID']].copy()
            for stype, grp in df_tc.groupby('spread_type'):
                ids = grp['ID'].astype(str).tolist()
                series_map = load_historical_spread_series(
                    str(stype),
                    ids,
                    dir_input=dir_input,
                    lookback_days=max(252, mom_window_i + 5),
                )
                for row_idx, cid in grp['ID'].astype(str).items():
                    s = series_map.get(f"{stype}|{cid}")
                    if isinstance(s, pd.Series) and len(s) > mom_window_i:
                        try:
                            mom_val = float(pd.to_numeric(s, errors='coerce').diff(mom_window_i).dropna().iloc[-1]) / float(mom_window_i)
                            momentum_per_day.at[row_idx] = mom_val
                        except Exception:
                            continue
        except Exception:
            pass

    df['momentum_per_day'] = momentum_per_day

    direction_in = (
        df['direction'].astype(str).str.strip().str.upper()
        if 'direction' in df.columns
        else pd.Series('', index=df.index, dtype=str)
    )

    z = pd.to_numeric(df['Zscore'], errors='coerce') if 'Zscore' in df.columns else pd.Series(np.nan, index=df.index)
    mr_dir = pd.Series('SELL', index=df.index, dtype=str)
    mr_dir.loc[z.gt(0)] = 'BUY'

    tc_dir = direction_in.copy()
    mom = momentum_per_day
    tc_dir = tc_dir.where(~(tc_dir.eq('') & mom.gt(0)), 'BUY')
    tc_dir = tc_dir.where(~(tc_dir.eq('') & mom.lt(0)), 'SELL')

    direction_score = tc_dir.where(~is_mr, mr_dir)
    df['direction_score'] = direction_score

    dir_sign = pd.Series(1.0, index=df.index, dtype=float)
    dir_sign.loc[direction_score.eq('SELL')] = -1.0
    df['dir_sign_score'] = dir_sign

    hl = halflife.replace(0, np.nan).abs()
    mr_reversion_pnl_per_day = ((spread - mean) / hl).replace([np.inf, -np.inf], np.nan)
    expected_mr = (dir_sign * mr_reversion_pnl_per_day).fillna(0.0) + (carry_per_day.fillna(0.0) * dir_sign)

    tc_raw = carry_per_day.fillna(0.0) + (mom_k_f * momentum_per_day.fillna(0.0))

    trend_confirm = pd.Series(1.0, index=df.index, dtype=float)
    has_mom = momentum_per_day.notna() & (momentum_per_day.abs() > 0)
    trend_confirm.loc[has_mom] = (momentum_per_day.loc[has_mom] * dir_sign.loc[has_mom] > 0).astype(float)
    df['trend_confirm'] = trend_confirm

    expected_tc = tc_raw * dir_sign * trend_confirm

    expected_move_per_day = expected_tc.where(~is_mr, expected_mr)
    df['expected_move_per_day'] = expected_move_per_day

    edge = expected_move_per_day.fillna(0.0)
    df['edge'] = edge
    df['risk'] = risk
    df['composite_score'] = (edge / risk).replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0)
    return df


def select_diversified_trades(
    candidates: List[Dict],
    max_trades: int = 10,
) -> List[Dict]:
    """Select diversified trades using greedy low-correlation selection."""
    if not candidates or len(candidates) == 0:
        return []

    df = pd.DataFrame(candidates)

    df = df[
        (df.get('score', pd.Series([0] * len(df))) > 0) &
        (df.get('vol', pd.Series([np.nan] * len(df))).notna()) &
        (df.get('Zscore', pd.Series([np.nan] * len(df))).notna())
    ].copy()

    if len(df) == 0:
        return []

    score_col = 'score'
    if score_col in df.columns:
        df = df.sort_values(score_col, ascending=False)

    selected = []
    seen_types = set()

    for _, row in df.iterrows():
        if len(selected) >= max_trades:
            break
        spread_type = row.get('spread_type', '')
        if spread_type not in seen_types:
            selected.append(row.to_dict())
            seen_types.add(spread_type)

    for _, row in df.iterrows():
        if len(selected) >= max_trades:
            break
        if row.to_dict() not in selected:
            selected.append(row.to_dict())

    return selected[:max_trades]
