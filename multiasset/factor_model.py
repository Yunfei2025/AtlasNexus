# -*- coding: utf-8 -*-
"""
Factor-model predictor for risk-factor returns.

Unlike the technical-indicator approach (MA, Bollinger, …), this module
generates *predictive features* (carry, value, momentum, macro, yield-curve
shape) for each risk factor and trains an IC-weighted model to forecast the
next-period factor return.  The pipeline mirrors ``factors/`` but is adapted
for yield/price series that lack OHLCV data.

Pipeline per risk factor:
  1. build_features()    – generate carry / value / momentum / macro features
  2. calculate_metrics() – IC / IR of each feature vs future factor return
  3. select_factors()    – filter by IC ≥ threshold, diversification, top-N
  4. train_model()       – IC-weighted (or ridge) coefficients on train window
  5. predict()           – out-of-sample predicted return → sign = signal

Reuses:
  - ``factors.analysis.metrics.calculate_metrics`` (IC / IR)
  - ``factors.engine.selector.FactorSelector``     (IC + VIF filtering)
  - ``factors.engine.predictor.train_model``        (IC-weighted / ridge)
  - ``factors.engine.predictor.predict_returns``    (OOS prediction)
  - ``factors.generator.macro.MacroFactors``        (macro feature set)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from pathlib import Path

from settings.paths import DIR_INPUT, DIR_DATA

# ── Reused components from factors/ ─────────────────────────────────────────
from factors.engine.selector import FactorSelector
from scipy.stats import spearmanr

from multiasset.factor_backtest import (
    load_factor_rates,
    _yield_to_return,
    _price_to_return,
    _is_yield_factor,
    get_factor_duration,
    compute_metrics,
)


# ═══════════════════════════════════════════════════════════════════════════
#  1. Configuration (light-weight dataclass, no OOP hierarchy)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class FactorModelConfig:
    """Minimal config consumed by FactorSelector and train_model."""
    # Selection
    ic_threshold: float = 0.05
    ir_threshold: float = 0.4
    filtering_method: str = 'significance'  # use t-test on IC
    top_n: int = 8
    use_vif_filtering: bool = True
    vif_threshold: float = 5.0
    vif_fallback_threshold: float = 10.0
    use_factor_diversification: bool = True
    max_factor_correlation: float = 0.7
    use_significance_test: bool = True      # require p < 0.05
    min_observations: int = 60
    confidence_level: float = 0.05
    # Training
    weighting_method: str = 'ic_weighted'
    model_type: str = 'ic_weighted'
    ic_weighting_method: str = 'ic_signed'   # signed preserves direction of IC
    scale_ic_predictions: bool = True
    # Walk-forward
    train_months: int = 12
    test_months: int = 1
    # Signal smoothing
    signal_smooth_days: int = 5              # smooth predicted returns before sign()
    # Target horizon
    target_horizon: int = 1                  # predict N-day forward return


# ═══════════════════════════════════════════════════════════════════════════
#  2. Feature generators (yield-adapted, no OHLCV needed)
# ═══════════════════════════════════════════════════════════════════════════

def _rolling_zscore(s: pd.Series, window: int) -> pd.Series:
    mu = s.rolling(window, min_periods=max(window // 2, 20)).mean()
    sigma = s.rolling(window, min_periods=max(window // 2, 20)).std()
    return ((s - mu) / sigma.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)


def _rolling_percentile(s: pd.Series, window: int) -> pd.Series:
    rmin = s.rolling(window, min_periods=max(window // 2, 20)).min()
    rmax = s.rolling(window, min_periods=max(window // 2, 20)).max()
    rng = rmax - rmin
    mid = (rmax + rmin) / 2.0
    return ((s - mid) / rng.replace(0, np.nan) * 2.0).clip(-1, 1)


# ── Momentum features ───────────────────────────────────────────────────
def _momentum_features(level: pd.Series, name: str) -> Dict[str, pd.Series]:
    """Rate-of-change at multiple horizons + trend strength."""
    feats: Dict[str, pd.Series] = {}
    for w in [5, 10, 20, 60]:
        feats[f'{name}_Mom{w}'] = level.diff(w)
    # EMA crossover
    ema_fast = level.ewm(span=10, adjust=False).mean()
    ema_slow = level.ewm(span=30, adjust=False).mean()
    feats[f'{name}_EMACross'] = ema_fast - ema_slow
    return feats


# ── Value / mean-reversion features ─────────────────────────────────────
def _value_features(level: pd.Series, name: str) -> Dict[str, pd.Series]:
    feats: Dict[str, pd.Series] = {}
    for w in [60, 120, 252]:
        feats[f'{name}_ZScore{w}'] = _rolling_zscore(level, w)
    feats[f'{name}_PctRank252'] = _rolling_percentile(level, 252)
    # Short z − long z  (contrarian distance)
    z20 = _rolling_zscore(level, 20)
    z252 = _rolling_zscore(level, 252)
    feats[f'{name}_ValueMom'] = z20 - z252
    return feats


# ── Volatility features (realised vol of changes) ──────────────────────
def _volatility_features(level: pd.Series, name: str) -> Dict[str, pd.Series]:
    chg = level.diff()
    feats: Dict[str, pd.Series] = {}
    for w in [10, 20, 60]:
        feats[f'{name}_Vol{w}'] = chg.rolling(w).std()
    # Vol ratio (short / long)
    feats[f'{name}_VolRatio'] = (
        chg.rolling(10).std() / chg.rolling(60).std().replace(0, np.nan)
    )
    return feats


# ── Carry features (for yield factors only) ─────────────────────────────
def _carry_features(
    factor_code: str,
    curve_data: Optional[pd.DataFrame],
) -> Dict[str, pd.Series]:
    """Build carry / roll-down features from the underlying curve data.

    Works only for IR and SP factors where we can access the raw tenor yields.
    """
    if curve_data is None or curve_data.empty:
        return {}

    feats: Dict[str, pd.Series] = {}
    cols = list(curve_data.columns)
    prefix = factor_code.split('.')[0]

    if len(cols) >= 2:
        # Slope = longest − shortest tenor
        slope = curve_data.iloc[:, -1] - curve_data.iloc[:, 0]
        feats[f'{factor_code}_Slope'] = slope
        feats[f'{factor_code}_SlopeMom20'] = slope.diff(20)
        feats[f'{factor_code}_SlopeZ60'] = _rolling_zscore(slope, 60)

    if len(cols) >= 3:
        # Curvature = mid − average(short, long)
        mid_idx = len(cols) // 2
        curv = curve_data.iloc[:, mid_idx] - (curve_data.iloc[:, 0] + curve_data.iloc[:, -1]) / 2
        feats[f'{factor_code}_Curv'] = curv
        feats[f'{factor_code}_CurvZ60'] = _rolling_zscore(curv, 60)

    # Roll-down proxy: adjacent tenor spread ≈ carry for level factor
    if prefix in ('IRDL', 'SPDL') and len(cols) >= 2:
        for i in range(len(cols) - 1):
            spread = curve_data.iloc[:, i + 1] - curve_data.iloc[:, i]
            feats[f'{factor_code}_Carry_{i}'] = spread

    return feats


# ── Cross-factor features ──────────────────────────────────────────────
def _cross_factor_features(
    factor_code: str,
    all_factor_levels: pd.DataFrame,
) -> Dict[str, pd.Series]:
    """Relative momentum / correlation features from other factors."""
    feats: Dict[str, pd.Series] = {}
    if factor_code not in all_factor_levels.columns:
        return feats

    own = all_factor_levels[factor_code]
    prefix = factor_code.split('.')[0]

    # Diff vs related factors
    for col in all_factor_levels.columns:
        if col == factor_code:
            continue
        other_prefix = col.split('.')[0]
        # Only include factors from same asset class
        same_class = (
            (prefix in ('IRDL', 'IRSL', 'IRCV') and other_prefix in ('IRDL', 'IRSL', 'IRCV'))
            or (prefix in ('SPDL', 'SPSL') and other_prefix in ('SPDL', 'SPSL'))
            or (prefix == 'FXDL' and other_prefix == 'FXDL')
            or (prefix == 'CMDL' and other_prefix == 'CMDL')
        )
        if same_class:
            diff = own - all_factor_levels[col]
            feats[f'{factor_code}_vs_{col}_20'] = diff.rolling(20).mean()

    return feats


# ── Macro features (shared, loaded once) ────────────────────────────────
_MACRO_CACHE: Optional[pd.DataFrame] = None


def _load_macro_features() -> pd.DataFrame:
    global _MACRO_CACHE
    if _MACRO_CACHE is not None:
        return _MACRO_CACHE

    try:
        from factors.generator.macro import MacroFactors
        macro = MacroFactors()
        _MACRO_CACHE = macro.calculate_all()
    except Exception as e:
        print(f"Warning: macro features unavailable: {e}")
        _MACRO_CACHE = pd.DataFrame()
    return _MACRO_CACHE


# ── Load raw curve data for a factor ────────────────────────────────────
def _load_curve_data(factor_code: str, input_dir: str) -> Optional[pd.DataFrame]:
    """Load raw tenor yield data for the factor's underlying curve."""
    from multiasset.config import CURVE_CONFIG, SPREAD_CONFIG

    prefix = factor_code.split('.')[0]
    suffix = factor_code.split('.')[1] if '.' in factor_code else ''

    try:
        if prefix in ('IRDL', 'IRSL', 'IRCV'):
            cfg = CURVE_CONFIG.get(suffix)
            if cfg is None:
                # Foreign curves from fxcurve_ts.pkl
                fxcurve_path = os.path.join(input_dir, 'fxcurve_ts.pkl')
                if os.path.exists(fxcurve_path):
                    fxcurve = pd.read_pickle(fxcurve_path)
                    if suffix in fxcurve:
                        return fxcurve[suffix]
                return None
            pkl_file, pkl_key, columns = cfg
            data = pd.read_pickle(os.path.join(input_dir, pkl_file))
            if pkl_key and isinstance(data, dict):
                data = data[pkl_key]
            if columns:
                data = data[[c for c in columns if c in data.columns]]
            return data

        elif prefix in ('SPDL', 'SPSL'):
            cfg = SPREAD_CONFIG.get(suffix)
            if cfg is None:
                return None
            pkl_file, pkl_key, columns = cfg
            data = pd.read_pickle(os.path.join(input_dir, pkl_file))
            if pkl_key and isinstance(data, dict):
                data = data[pkl_key]
            if columns:
                data = data[[c for c in columns if c in data.columns]]
            return data

    except Exception as e:
        print(f"Warning: could not load curve data for {factor_code}: {e}")

    return None


# ── Master feature builder ──────────────────────────────────────────────

def build_features(
    factor_code: str,
    factor_levels: pd.DataFrame,
    input_dir: Union[str, Path] = DIR_INPUT,
    include_macro: bool = True,
    include_cross: bool = True,
) -> pd.DataFrame:
    """Build all predictive features for a single risk factor.

    Returns a DataFrame (index = date) of named features.
    """
    if factor_code not in factor_levels.columns:
        raise ValueError(f"{factor_code} not in factor_levels")

    level = factor_levels[factor_code].dropna()
    feats: Dict[str, pd.Series] = {}

    # Self-based features
    feats.update(_momentum_features(level, factor_code))
    feats.update(_value_features(level, factor_code))
    feats.update(_volatility_features(level, factor_code))

    # Carry features from raw curve data
    is_yield = _is_yield_factor(factor_code)
    if is_yield:
        curve_data = _load_curve_data(factor_code, str(input_dir))
        feats.update(_carry_features(factor_code, curve_data))

    # Cross-factor features
    if include_cross:
        feats.update(_cross_factor_features(factor_code, factor_levels))

    # Macro features (shared across all factors)
    if include_macro:
        macro_df = _load_macro_features()
        if not macro_df.empty:
            for col in macro_df.columns:
                feats[f'MACRO_{col}'] = macro_df[col]

    # Assemble and clean
    result = pd.DataFrame(feats)
    # Drop columns with >50% NaN
    nan_pct = result.isnull().sum() / len(result)
    result = result.loc[:, nan_pct < 0.5]

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  3. Self-contained IC model (avoids shift issues in shared functions)
# ═══════════════════════════════════════════════════════════════════════════

def _compute_ic_metrics(
    features: pd.DataFrame,
    forward_returns: pd.Series,
    min_obs: int = 60,
) -> pd.DataFrame:
    """Compute Spearman IC of each feature vs already-aligned forward returns.

    Unlike ``factors.analysis.metrics.calculate_metrics`` this does **not**
    shift returns internally — caller must supply properly aligned fwd returns.
    """
    common = features.index.intersection(forward_returns.dropna().index)
    if len(common) < min_obs:
        return pd.DataFrame()

    feat = features.loc[common]
    ret = forward_returns.loc[common]

    rows = []
    for col in feat.columns:
        valid = feat[col].notna()
        if valid.sum() < min_obs:
            continue
        ic, p = spearmanr(feat[col].loc[valid], ret.loc[valid])
        if np.isnan(ic):
            continue
        rows.append({
            'factor': col,
            'IC': ic,
            'IC_abs': abs(ic),
            'IR': 0.0,          # rolling IR not needed for selection
            'count': int(valid.sum()),
            'p_value': p,
            'is_significant': p < 0.05,
        })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index('factor')


def _train_ic_model(
    features: pd.DataFrame,
    forward_returns: pd.Series,
    selected_features: List[str],
) -> Dict:
    """Train IC-weighted model: weight_i = signed Spearman IC(feature_i, fwd_ret)."""
    from sklearn.preprocessing import StandardScaler

    avail = [f for f in selected_features if f in features.columns]
    if not avail:
        return {'error': 'No available features'}

    X = features[avail].ffill().fillna(0)
    y = forward_returns.reindex(X.index)

    valid = y.notna() & X.notna().all(axis=1)
    X, y = X.loc[valid], y.loc[valid]
    if len(X) < 30:
        return {'error': 'Insufficient data'}

    scaler = StandardScaler()
    Xs = pd.DataFrame(scaler.fit_transform(X), index=X.index, columns=X.columns)

    weights = pd.Series(0.0, index=avail)
    for col in avail:
        ic, _ = spearmanr(Xs[col], y)
        weights[col] = ic if not np.isnan(ic) else 0.0

    preds = (Xs * weights).sum(axis=1)
    mean_abs_a = abs(y).mean()
    mean_abs_p = abs(preds).mean()
    scale = mean_abs_a / mean_abs_p if mean_abs_p > 1e-10 else 1.0

    return {
        'coefficients': weights,
        'scaling_factor': scale,
        'scaler': scaler,
        'feature_names': avail,
    }


def _predict_ic_model(
    features: pd.DataFrame,
    model: Dict,
) -> pd.Series:
    """Apply IC-weighted model to (test) features."""
    avail = [f for f in model['feature_names'] if f in features.columns]
    if not avail:
        return pd.Series(dtype=float)

    X = features[avail].ffill().fillna(0)
    Xs = pd.DataFrame(
        model['scaler'].transform(X), index=X.index, columns=X.columns,
    )
    w = model['coefficients'].reindex(avail, fill_value=0)
    return (Xs * w).sum(axis=1) * model.get('scaling_factor', 1.0)


# ═══════════════════════════════════════════════════════════════════════════
#  4. Walk-forward factor model engine
# ═══════════════════════════════════════════════════════════════════════════

def _compute_target_returns(
    factor_code: str,
    factor_levels: pd.DataFrame,
) -> pd.Series:
    """Compute daily returns for a factor (duration-adjusted for yields)."""
    level = factor_levels[factor_code].dropna()
    is_yield = _is_yield_factor(factor_code)
    mod_dur = get_factor_duration(factor_code)

    if is_yield:
        return _yield_to_return(level, mod_dur)
    else:
        return _price_to_return(level)


def run_factor_model_backtest(
    factor_code: str,
    factor_levels: pd.DataFrame,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    input_dir: Union[str, Path] = DIR_INPUT,
    config: Optional[FactorModelConfig] = None,
) -> pd.DataFrame:
    """Run walk-forward factor model backtest for a single risk factor.

    Parameters
    ----------
    factor_code : str
        Risk factor code (e.g. ``'IRDL.CN'``).
    factor_levels : pd.DataFrame
        Full factor-rates DataFrame (all factors, full history).
    start_date, end_date : str or None
        Backtest date range (YYYY-MM-DD).
    input_dir : path
        Data directory.
    config : FactorModelConfig or None
        Model parameters; uses defaults if None.

    Returns
    -------
    pd.DataFrame
        Columns: signal, returns, strategy_returns, cumulative_returns,
                 predicted_return, n_features
    """
    cfg = config or FactorModelConfig()

    # Ensure DatetimeIndex
    if not isinstance(factor_levels.index, pd.DatetimeIndex):
        factor_levels.index = pd.to_datetime(factor_levels.index)
    factor_levels = factor_levels.sort_index()

    # Date filter
    if start_date:
        ts = pd.Timestamp(start_date)
    else:
        ts = factor_levels.index.min()
    if end_date:
        te = pd.Timestamp(end_date)
    else:
        te = factor_levels.index.max()

    # Build features once (full history)
    print(f"  [{factor_code}] Building features (horizon={cfg.target_horizon}d) ...")
    all_features = build_features(factor_code, factor_levels, input_dir)

    # Daily returns and N-day forward returns
    daily_returns = _compute_target_returns(factor_code, factor_levels)
    # forward_ret[t] = sum of daily_returns[t+1 … t+H]  (return from day t to t+H)
    H = max(cfg.target_horizon, 1)
    forward_returns = daily_returns.rolling(H).sum().shift(-H)

    # Align features and forward returns
    common = all_features.index.intersection(forward_returns.dropna().index)
    all_features = all_features.loc[common]
    forward_returns = forward_returns.loc[common]

    # Walk-forward periods
    from dateutil.relativedelta import relativedelta

    # First train window must end before start_date
    train_months = cfg.train_months
    test_months = cfg.test_months

    # Generate test windows
    periods = []
    cursor = ts
    while cursor <= te:
        period_end = min(cursor + relativedelta(months=test_months) - pd.Timedelta(days=1), te)
        train_start = cursor - relativedelta(months=train_months)
        train_end = cursor - pd.Timedelta(days=1)
        periods.append((train_start, train_end, cursor, period_end))
        cursor = period_end + pd.Timedelta(days=1)

    if not periods:
        print(f"  [{factor_code}] No valid walk-forward periods")
        return pd.DataFrame()

    # Walk-forward loop
    all_predictions = []
    selector = FactorSelector(cfg)

    for train_start, train_end, test_start, test_end in periods:
        # Slice train / test
        train_mask = (all_features.index >= train_start) & (all_features.index <= train_end)
        test_mask = (all_features.index >= test_start) & (all_features.index <= test_end)

        train_feat = all_features.loc[train_mask].copy()
        test_feat = all_features.loc[test_mask].copy()
        train_fwd = forward_returns.loc[train_mask].copy()

        if len(train_feat) < cfg.min_observations or len(test_feat) == 0:
            continue

        # Forward-fill then zero-fill NaN in features
        train_feat = train_feat.ffill().fillna(0)
        test_feat = test_feat.ffill().fillna(0)

        # Step 1: Compute IC metrics (no internal shift; fwd returns already aligned)
        metrics = _compute_ic_metrics(train_feat, train_fwd, cfg.min_observations)
        if metrics.empty:
            continue

        # Step 2: Select features via FactorSelector (IC + VIF + diversification)
        selected = selector.select_factors(metrics, train_feat)
        if not selected:
            if not metrics.empty:
                selected = metrics.nlargest(min(3, len(metrics)), 'IC_abs').index.tolist()
            if not selected:
                continue

        # Step 3: Train IC-weighted model on aligned fwd returns
        trained = _train_ic_model(train_feat, train_fwd, selected)
        if 'error' in trained:
            continue

        # Step 4: Predict out-of-sample
        preds = _predict_ic_model(test_feat, trained)
        if preds.empty:
            continue

        pred_df = pd.DataFrame({
            'predicted_return': preds,
            'n_features': len(selected),
        })
        all_predictions.append(pred_df)

    if not all_predictions:
        print(f"  [{factor_code}] No predictions generated")
        return pd.DataFrame()

    # Concatenate predictions
    pred_full = pd.concat(all_predictions).sort_index()
    # Remove duplicate indices (overlapping windows)
    pred_full = pred_full[~pred_full.index.duplicated(keep='first')]

    # Build result DataFrame
    level = factor_levels[factor_code].dropna()
    if not isinstance(level.index, pd.DatetimeIndex):
        level.index = pd.to_datetime(level.index)

    result = pd.DataFrame({'level': level})
    result = result.loc[result.index.intersection(pred_full.index)]

    result['predicted_return'] = pred_full['predicted_return']
    result['n_features'] = pred_full['n_features']

    # Signal: sign of (smoothed) predicted return
    if cfg.signal_smooth_days > 1:
        smoothed = result['predicted_return'].rolling(
            cfg.signal_smooth_days, min_periods=1
        ).mean()
    else:
        smoothed = result['predicted_return']
    result['signal'] = np.sign(smoothed).fillna(0).astype(int)

    # Actual daily returns (for PnL, always use 1-day returns)
    result['returns'] = daily_returns.reindex(result.index)

    result['strategy_returns'] = result['signal'].shift(1) * result['returns']
    result['cumulative_returns'] = (1 + result['strategy_returns'].fillna(0)).cumprod()

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  5. Batch runner (mirrors run_factor_backtest in factor_backtest.py)
# ═══════════════════════════════════════════════════════════════════════════

def run_factor_model_batch(
    factors: List[str],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    input_dir: Union[str, Path] = DIR_INPUT,
    config: Optional[FactorModelConfig] = None,
    save: bool = True,
) -> Dict[str, pd.DataFrame]:
    """Run factor-model backtest across multiple risk factors.

    Saves results to ``factor-backtest.pkl`` under the key ``'FactorModel'``.

    Returns
    -------
    dict  {factor_code: DataFrame}
    """
    factor_levels = load_factor_rates(input_dir)
    if not isinstance(factor_levels.index, pd.DatetimeIndex):
        factor_levels.index = pd.to_datetime(factor_levels.index)
    factor_levels = factor_levels.sort_index()

    results: Dict[str, pd.DataFrame] = {}

    for factor in factors:
        if factor not in factor_levels.columns:
            print(f"Skipping {factor}: not in factor-rates")
            continue

        series = factor_levels[factor].dropna()
        if len(series) < 120:
            print(f"Skipping {factor}: insufficient data ({len(series)} days)")
            continue

        try:
            df = run_factor_model_backtest(
                factor_code=factor,
                factor_levels=factor_levels,
                start_date=start_date,
                end_date=end_date,
                input_dir=input_dir,
                config=config,
            )
            if not df.empty:
                results[factor] = df
        except Exception as e:
            print(f"Error backtesting {factor}: {e}")
            import traceback
            traceback.print_exc()

    if save and results:
        pkl_path = os.path.join(str(input_dir), 'factor-backtest.pkl')
        existing: Dict = {}
        if os.path.exists(pkl_path):
            try:
                existing = pd.read_pickle(pkl_path)
            except Exception:
                existing = {}

        existing['FactorModel'] = results
        pd.to_pickle(existing, pkl_path)
        print(f"Saved factor-backtest.pkl  (strategy=FactorModel, {len(results)} factors)")

    return results
