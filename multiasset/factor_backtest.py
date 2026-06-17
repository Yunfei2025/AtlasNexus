# -*- coding: utf-8 -*-
"""
Factor-level backtest engine for yield-based risk factors.

Generates factor yield series from the deterministic model (IRDL, IRSL, IRCV,
SPDL, SPSL, FXDL, CMDL), converts yield changes to duration-adjusted returns,
runs close-only technical strategies, and persists results.

Output files (in DIR_INPUT):
  factor-rates.pkl  – DataFrame of factor yield/price levels (index=date)
  factor-backtest.pkl – dict of {factor: DataFrame with columns
                         signal, returns, strategy_returns, cumulative_returns}
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from pathlib import Path

from multiasset.pca_analyzer import DeterministicRiskFactorAnalyzer
from multiasset.risk_loader import RiskFactorLoader
from settings.paths import DIR_INPUT


def get_factor_duration(factor_code: str) -> float:
    """Return the effective yield-to-price conversion scale for a factor.

    For deterministic synthetic yield/spread portfolios, the physical position
    uses notionals proportional to ``w_i / D_i``. That makes the factor return:

      r_t = -sum(w_i * dy_i) / 100 = -d_factor / 100

    so all yield/spread factors map to price return with effective scale 1.0.
    Price-based factors (FX, commodities) do not use duration conversion.
    """
    return 1.0 if _is_yield_factor(factor_code) else 0.0


# Approximate modified durations (years) for par government bonds at standard tenors.
# Used to compute the tenor-weighted duration of IRDL/IRSL/IRCV factor portfolios.
_TENOR_YEARS = [1, 2, 5, 10, 30]
_TENOR_MOD_DUR = {1: 0.95, 2: 1.90, 5: 4.60, 10: 8.80, 30: 20.0}

# Deterministic factor weights (from multiasset/pca_analyzer.py)
# IRDL: equal-weight level  |  IRSL: antisymmetric slope  |  IRCV: butterfly curvature
_IR_WEIGHTS = {
    'IRDL': [0.20,  0.20,  0.20,  0.20,  0.20],   # equal weight, sum=1 → long-only
    'IRSL': [-0.40, -0.20,  0.00,  0.20,  0.40],   # steepener, sum=0
    'IRCV': [0.25, -0.25,  0.00, -0.25,  0.25],    # butterfly, sum=0
}


def get_factor_weighted_duration(factor_code: str) -> float:
    """Tenor-weighted modified duration of an IR factor portfolio.

    Computed as ``Σ w_i × D_i`` where ``w_i`` are the deterministic factor
    weights and ``D_i`` are approximate modified durations for each tenor.

    Returns ``None`` for non-IR factors (FX, commodity, spread).
    """
    prefix = factor_code.split('.')[0]
    weights = _IR_WEIGHTS.get(prefix)
    if weights is None:
        return None
    return sum(w * _TENOR_MOD_DUR[t] for w, t in zip(weights, _TENOR_YEARS))


def _is_yield_factor(factor_code: str) -> bool:
    """Return True if this factor is yield/spread-based (needs duration conversion)."""
    prefix = factor_code.split('.')[0]
    return prefix in ('IRDL', 'IRSL', 'IRCV', 'SPDL', 'SPSL', 'SPCV')


def factor_level_to_price_return(
    series: pd.Series,
    factor_code: str,
    output_in_percent: bool = False,
) -> pd.Series:
    """Convert a factor level series into factor portfolio price returns.

    Returns are emitted in decimal form by default for backtests, and in percent
    form when ``output_in_percent=True`` for dashboards/optimizer reporting.
    """
    if _is_yield_factor(factor_code):
        returns_pct = -get_factor_duration(factor_code) * series.diff()
    else:
        returns_pct = series.pct_change() * 100.0
    if output_in_percent:
        return returns_pct
    return returns_pct / 100.0


def get_factor_price_beta(factor_code: str, raw_sensitivity: float) -> float:
    """Convert a raw factor sensitivity into beta to factor price returns."""
    if not _is_yield_factor(factor_code):
        return raw_sensitivity
    scale = get_factor_duration(factor_code)
    if scale == 0:
        return 0.0
    return -raw_sensitivity / scale


def compute_ewma_factor_vols(
    factor_levels: pd.DataFrame,
    ewma_lambda: float = 0.94,
) -> Dict[str, float]:
    """Compute annualized EWMA vol in non-dimensionalized price-return space."""
    alpha = 1.0 - ewma_lambda
    vol_map: Dict[str, float] = {}

    for factor in factor_levels.columns:
        levels = factor_levels[factor].dropna()
        if len(levels) < 5:
            continue

        returns = factor_level_to_price_return(
            levels,
            factor,
            output_in_percent=True,
        ).dropna()
        if len(returns) < 5:
            continue

        ewma_var = returns.ewm(alpha=alpha, adjust=False).var().dropna()
        if ewma_var.empty:
            continue

        vol_map[factor] = float(np.sqrt(ewma_var.iloc[-1]) * np.sqrt(252))

    return vol_map


def compute_ewma_factor_covariance(
    factor_levels: pd.DataFrame,
    ewma_lambda: float = 0.94,
) -> pd.DataFrame:
    """Compute annualized EWMA factor covariance matrix in price-return % space.

    Returns a (n_factors × n_factors) DataFrame.  Off-diagonal terms capture
    inter-factor correlations so the optimizer can use the full ``Σ = B C_f Bᵀ``
    asset covariance instead of the diagonal-only approximation.
    """
    alpha = 1.0 - ewma_lambda
    returns: Dict[str, pd.Series] = {}

    for factor in factor_levels.columns:
        levels = factor_levels[factor].dropna()
        if len(levels) < 5:
            continue
        ret = factor_level_to_price_return(levels, factor, output_in_percent=True).dropna()
        if len(ret) >= 5:
            returns[factor] = ret

    if not returns:
        return pd.DataFrame()

    ret_df = pd.DataFrame(returns).dropna()
    if len(ret_df) < 5:
        return pd.DataFrame()

    # pandas ewm().cov() returns a MultiIndex DataFrame; pick the last date slice
    ewm_cov_full = ret_df.ewm(alpha=alpha, adjust=False).cov()
    last_date = ewm_cov_full.index.get_level_values(0)[-1]
    cov_matrix = ewm_cov_full.loc[last_date]          # shape: (n_factors, n_factors)
    return cov_matrix * 252                            # annualise (daily → annual)


# ── Factor series generation ────────────────────────────────────────────────

def generate_factor_rates(
    input_dir: Union[str, Path] = DIR_INPUT,
    save: bool = True,
) -> pd.DataFrame:
    """Generate and optionally save the factor yield/price level series.

    Reuses ``RiskFactorLoader`` (deterministic mode) to produce a DataFrame
    indexed by date with columns ``IRDL.CN``, ``IRSL.US``, ``FXDL.USDCNY``, etc.

    Saves to ``<input_dir>/factor-rates.pkl``.
    """
    loader = RiskFactorLoader(str(input_dir), use_deterministic=True)
    factor_levels = loader.load_risk_factors(use_cache=False)

    if factor_levels is None or factor_levels.empty:
        raise ValueError("RiskFactorLoader returned empty factor levels")

    if save:
        out_path = os.path.join(str(input_dir), 'factor-rates.pkl')
        factor_levels.to_pickle(out_path)
        print(f"Saved factor-rates.pkl  ({factor_levels.shape[1]} factors, "
              f"{len(factor_levels)} days)")

    return factor_levels


def load_factor_rates(input_dir: Union[str, Path] = DIR_INPUT) -> pd.DataFrame:
    """Load factor-rates.pkl; regenerate if missing."""
    pkl_path = os.path.join(str(input_dir), 'factor-rates.pkl')
    if os.path.exists(pkl_path):
        return pd.read_pickle(pkl_path)
    return generate_factor_rates(input_dir, save=True)


def update_factor_rates(
    input_dir: Union[str, Path] = DIR_INPUT,
) -> Tuple[pd.DataFrame, int]:
    """Incrementally append new daily rows to factor-rates.pkl.

    Loads the full fresh series from RiskFactorLoader and merges it with any
    existing pkl, keeping old rows intact and appending only dates that are newer
    than the last saved date.  Falls back to a full regenerate when the pkl does
    not exist yet.

    Returns ``(updated_df, n_new_rows)`` so callers can show the user how many
    days were added.
    """
    pkl_path = os.path.join(str(input_dir), 'factor-rates.pkl')

    # Load current fresh series from source data
    loader = RiskFactorLoader(str(input_dir), use_deterministic=True)
    fresh = loader.load_risk_factors(use_cache=False)
    if fresh is None or fresh.empty:
        raise ValueError("RiskFactorLoader returned empty factor levels")

    if not os.path.exists(pkl_path):
        fresh.to_pickle(pkl_path)
        print(f"factor-rates.pkl created ({fresh.shape[1]} factors, {len(fresh)} days)")
        return fresh, len(fresh)

    existing = pd.read_pickle(pkl_path)
    if not isinstance(existing.index, pd.DatetimeIndex):
        existing.index = pd.to_datetime(existing.index)
    if not isinstance(fresh.index, pd.DatetimeIndex):
        fresh.index = pd.to_datetime(fresh.index)

    last_saved = existing.index.max()
    new_rows = fresh[fresh.index > last_saved]
    n_new = len(new_rows)

    if n_new == 0:
        print(f"factor-rates.pkl already up to date (last date: {last_saved.date()})")
        return existing, 0

    # Combine: existing rows + new rows; use fresh values where columns overlap
    merged = pd.concat([existing, new_rows])
    # Drop duplicates on index (keep last = fresh data wins on overlapping dates)
    merged = merged[~merged.index.duplicated(keep='last')].sort_index()
    merged.to_pickle(pkl_path)
    print(f"factor-rates.pkl updated: +{n_new} days (now {len(merged)} days total, "
          f"through {merged.index.max().date()})")
    return merged, n_new


# ── Yield-aware strategy wrappers ───────────────────────────────────────────
# Each accepts a Series of yield (or price) levels and returns a DataFrame
# with at least: signal, returns, strategy_returns, cumulative_returns.

def _yield_to_return(series: pd.Series, mod_dur: float) -> pd.Series:
    """Convert yield level series to approximated bond return series.

    r_t ≈ -D_mod × Δy_t / 100  (Δy in percentage points → bond %return)
    """
    return -mod_dur * series.diff() / 100.0


def _price_to_return(series: pd.Series) -> pd.Series:
    """Simple percentage return for price-based factors (FX, Cmdty)."""
    return series.pct_change()


def run_ma_yield_strategy(
    levels: pd.Series,
    mod_dur: float,
    is_yield: bool,
    short_window: int = 10,
    long_window: int = 30,
) -> pd.DataFrame:
    """MA crossover on the factor level series.

    For yield series the signal is **inverted**: MA-short > MA-long means yields
    are trending UP → bond prices falling → SHORT.
    """
    df = pd.DataFrame({'level': levels})
    df['ma_short'] = df['level'].rolling(window=short_window).mean()
    df['ma_long'] = df['level'].rolling(window=long_window).mean()

    if is_yield:
        # Yield rising → SHORT bonds; yield falling → LONG bonds
        df['signal'] = np.where(df['ma_short'] < df['ma_long'], 1, -1)
    else:
        df['signal'] = np.where(df['ma_short'] > df['ma_long'], 1, -1)

    df.iloc[:long_window, df.columns.get_loc('signal')] = 0

    if is_yield:
        df['returns'] = _yield_to_return(levels, mod_dur)
    else:
        df['returns'] = _price_to_return(levels)

    df['strategy_returns'] = df['signal'].shift(1) * df['returns']
    df['cumulative_returns'] = (1 + df['strategy_returns'].fillna(0)).cumprod()
    return df


def run_bollinger_yield_strategy(
    levels: pd.Series,
    mod_dur: float,
    is_yield: bool,
    window: int = 20,
    num_std: float = 1.5,
) -> pd.DataFrame:
    """Bollinger band strategy on the factor level series.

    For yield series: yield above upper band → mean-revert → LONG (expect yield to fall).
    """
    df = pd.DataFrame({'level': levels})
    df['ma'] = df['level'].rolling(window=window).mean()
    df['std'] = df['level'].rolling(window=window).std()
    df['upper'] = df['ma'] + num_std * df['std']
    df['lower'] = df['ma'] - num_std * df['std']

    position = 0
    signals = []
    lev = df['level'].values
    upper = df['upper'].values
    lower = df['lower'].values
    ma_arr = df['ma'].values

    for i in range(len(df)):
        if np.isnan(upper[i]):
            signals.append(0)
            continue
        c = lev[i]
        if is_yield:
            # yield above upper → expect reversion down → LONG bonds
            if c > upper[i]:
                position = 1
            elif c < lower[i]:
                position = -1
            elif position == 1 and c < ma_arr[i]:
                position = 0
            elif position == -1 and c > ma_arr[i]:
                position = 0
        else:
            if c < lower[i]:
                position = 1
            elif c > upper[i]:
                position = -1
        signals.append(position)

    df['signal'] = signals

    if is_yield:
        df['returns'] = _yield_to_return(levels, mod_dur)
    else:
        df['returns'] = _price_to_return(levels)

    df['strategy_returns'] = df['signal'].shift(1) * df['returns']
    df['cumulative_returns'] = (1 + df['strategy_returns'].fillna(0)).cumprod()
    return df


def run_momentum_yield_strategy(
    levels: pd.Series,
    mod_dur: float,
    is_yield: bool,
    window: int = 20,
) -> pd.DataFrame:
    """Momentum (rate-of-change) strategy.

    For yield series: negative momentum in yield (yield falling) → LONG.
    """
    df = pd.DataFrame({'level': levels})
    roc = df['level'].diff(window)

    if is_yield:
        df['signal'] = np.where(roc < 0, 1, -1)
    else:
        df['signal'] = np.where(roc > 0, 1, -1)

    df.iloc[:window, df.columns.get_loc('signal')] = 0

    if is_yield:
        df['returns'] = _yield_to_return(levels, mod_dur)
    else:
        df['returns'] = _price_to_return(levels)

    df['strategy_returns'] = df['signal'].shift(1) * df['returns']
    df['cumulative_returns'] = (1 + df['strategy_returns'].fillna(0)).cumprod()
    return df


def run_zscore_yield_strategy(
    levels: pd.Series,
    mod_dur: float,
    is_yield: bool,
    window: int = 60,
    entry_z: float = 1.5,
    exit_z: float = 0.5,
) -> pd.DataFrame:
    """Z-score mean-reversion strategy.

    For yield series: z > entry → yield is high → LONG bonds (expect revert).
    """
    df = pd.DataFrame({'level': levels})
    ma = df['level'].rolling(window=window).mean()
    std = df['level'].rolling(window=window).std()
    df['zscore'] = (df['level'] - ma) / std.replace(0, np.nan)

    position = 0
    signals = []
    z_arr = df['zscore'].values

    for i in range(len(df)):
        z = z_arr[i]
        if np.isnan(z):
            signals.append(0)
            continue
        if is_yield:
            if z > entry_z:
                position = 1
            elif z < -entry_z:
                position = -1
            elif abs(z) < exit_z:
                position = 0
        else:
            if z < -entry_z:
                position = 1
            elif z > entry_z:
                position = -1
            elif abs(z) < exit_z:
                position = 0
        signals.append(position)

    df['signal'] = signals

    if is_yield:
        df['returns'] = _yield_to_return(levels, mod_dur)
    else:
        df['returns'] = _price_to_return(levels)

    df['strategy_returns'] = df['signal'].shift(1) * df['returns']
    df['cumulative_returns'] = (1 + df['strategy_returns'].fillna(0)).cumprod()
    return df


# ── Strategy registry ───────────────────────────────────────────────────────

STRATEGY_REGISTRY = {
    'MA': run_ma_yield_strategy,
    'Bollinger': run_bollinger_yield_strategy,
    'Momentum': run_momentum_yield_strategy,
    'Z-Score': run_zscore_yield_strategy,
    'FactorModel': None,  # handled specially via multiasset.factor_model
}

STRATEGY_DEFAULTS = {
    'MA': {'short_window': 10, 'long_window': 30},
    'Bollinger': {'window': 20, 'num_std': 1.5},
    'Momentum': {'window': 20},
    'Z-Score': {'window': 60, 'entry_z': 1.5, 'exit_z': 0.5},
    'FactorModel': {'train_months': 12, 'test_months': 1,
                    'ic_threshold': 0.05, 'top_n': 8},
}


# ── Batch backtest runner ───────────────────────────────────────────────────

def run_factor_backtest(
    factors: List[str],
    strategy: str = 'MA',
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    input_dir: Union[str, Path] = DIR_INPUT,
    save: bool = True,
    save_latest_only: bool = False,
    **strategy_kwargs,
) -> Tuple[Dict[str, pd.DataFrame], Optional[Dict]]:
    """Run a single strategy across multiple factors and save results.

    Parameters
    ----------
    factors : list of str
        Factor codes to backtest (e.g. ``['IRDL.CN', 'FXDL.USDCNY']``).
    strategy : str
        Strategy name (key in ``STRATEGY_REGISTRY``).
    start_date, end_date : str or None
        Optional date filters (YYYY-MM-DD).
    input_dir : path
        Data directory containing ``factor-rates.pkl``.
    save : bool
        Whether to persist results to ``factor-backtest.pkl``.
    save_latest_only : bool
        When True (Factor-tab daily-train mode) only the most-recent monthly
        model artifact is written to disk instead of all walk-forward snapshots.
    **strategy_kwargs
        Override default strategy parameters.

    Returns
    -------
    (results, latest_artifact)
        results         : {factor_code: DataFrame}
        latest_artifact : artifact dict for the latest month, or None.
    """
    factor_levels = load_factor_rates(input_dir)

    # Ensure index is DatetimeIndex for consistent slicing
    if not isinstance(factor_levels.index, pd.DatetimeIndex):
        factor_levels.index = pd.to_datetime(factor_levels.index)
    factor_levels = factor_levels.sort_index()

    # ── Factor Model strategy: delegate to dedicated engine ─────────────
    if strategy == 'FactorModel':
        from multiasset.factor_model import run_factor_model_batch, FactorModelConfig
        fm_cfg = FactorModelConfig()
        # Apply overrides from kwargs
        for k, v in strategy_kwargs.items():
            if hasattr(fm_cfg, k):
                setattr(fm_cfg, k, type(getattr(fm_cfg, k))(v))
        results, latest_artifact = run_factor_model_batch(
            factors=factors,
            start_date=start_date,
            end_date=end_date,
            input_dir=input_dir,
            config=fm_cfg,
            save=save,
            save_latest_only=save_latest_only,
        )
        return results, latest_artifact

    # ── Technical indicator strategies ──────────────────────────────────
    if start_date:
        factor_levels = factor_levels.loc[factor_levels.index >= pd.Timestamp(start_date)]
    if end_date:
        factor_levels = factor_levels.loc[factor_levels.index <= pd.Timestamp(end_date)]

    strategy_fn = STRATEGY_REGISTRY.get(strategy)
    if strategy_fn is None:
        raise ValueError(f"Unknown strategy '{strategy}'. Available: {list(STRATEGY_REGISTRY)}")

    defaults = STRATEGY_DEFAULTS.get(strategy, {}).copy()
    defaults.update(strategy_kwargs)

    results: Dict[str, pd.DataFrame] = {}

    for factor in factors:
        if factor not in factor_levels.columns:
            print(f"Skipping {factor}: not in factor-rates")
            continue

        series = factor_levels[factor].dropna()
        if len(series) < 60:
            print(f"Skipping {factor}: insufficient data ({len(series)} days)")
            continue

        is_yield = _is_yield_factor(factor)
        mod_dur = get_factor_duration(factor)

        result_df = strategy_fn(
            levels=series,
            mod_dur=mod_dur,
            is_yield=is_yield,
            **defaults,
        )
        results[factor] = result_df

    if save and results:
        # Load existing backtest results if present, merge
        pkl_path = os.path.join(str(input_dir), 'factor-backtest.pkl')
        existing: Dict[str, Dict[str, pd.DataFrame]] = {}
        if os.path.exists(pkl_path):
            try:
                existing = pd.read_pickle(pkl_path)
            except Exception:
                existing = {}

        if strategy not in existing:
            existing[strategy] = {}
        existing[strategy].update(results)

        pd.to_pickle(existing, pkl_path)
        print(f"Saved factor-backtest.pkl  (strategy={strategy}, "
              f"{len(results)} factors)")

    # Non-FactorModel strategies have no model artifact
    return results, None


def load_factor_backtest(
    input_dir: Union[str, Path] = DIR_INPUT,
) -> Dict[str, Dict[str, pd.DataFrame]]:
    """Load factor-backtest.pkl.

    Returns
    -------
    dict  {strategy_name: {factor_code: DataFrame}}
    """
    pkl_path = os.path.join(str(input_dir), 'factor-backtest.pkl')
    if os.path.exists(pkl_path):
        return pd.read_pickle(pkl_path)
    return {}


def compute_metrics(
    result_df: pd.DataFrame,
    returns_col: str = 'strategy_returns',
    risk_free_rate: float = 0.0,
    geometric_annualisation: bool = False,
) -> Dict[str, float]:
    """Compute performance metrics from a return series.

    Args:
        result_df: DataFrame containing daily returns.
        returns_col: Column name for the daily return series.
        risk_free_rate: Annualised risk-free rate for Sharpe calculation (decimal).
        geometric_annualisation: If True, use compound (geometric) annualisation
            ``(1+r_total)^(252/N) - 1``; otherwise arithmetic ``mean * 252``.
            The geometric form is preferred for multi-year series.
    """
    rets = result_df[returns_col].dropna()
    if rets.empty:
        return {}

    n = len(rets)
    total_return = float((1 + rets).prod() - 1)
    if geometric_annualisation and n > 0:
        ann_return = float((1 + total_return) ** (252.0 / n) - 1)
    else:
        ann_return = float(rets.mean() * 252)
    ann_vol = float(rets.std() * np.sqrt(252))
    excess = ann_return - risk_free_rate
    sharpe = excess / ann_vol if ann_vol > 0 else np.nan

    cum = (1 + rets).cumprod()
    running_max = cum.cummax()
    dd = (cum / running_max - 1)
    max_dd = float(dd.min())

    win_rate = float((rets > 0).sum() / n) if n > 0 else 0.0

    return {
        'Total Return': total_return,
        'Ann. Return': ann_return,
        'Ann. Vol': ann_vol,
        'Sharpe': sharpe,
        'Max Drawdown': max_dd,
        'Win Rate': win_rate,
        'Days': n,
    }


def compute_portfolio_metrics(
    portfolio_values: pd.Series,
    risk_free_rate: float = 0.0,
) -> Dict[str, float]:
    """Compute performance metrics from a portfolio NAV/value series.

    Args:
        portfolio_values: Series of portfolio values (not returns) indexed by date.
        risk_free_rate: Annualised risk-free rate for Sharpe (decimal).
    """
    daily_rets = portfolio_values.pct_change().dropna()
    if daily_rets.empty:
        return {}
    df = daily_rets.rename('strategy_returns').to_frame()
    return compute_metrics(
        df,
        returns_col='strategy_returns',
        risk_free_rate=risk_free_rate,
        geometric_annualisation=True,
    )
