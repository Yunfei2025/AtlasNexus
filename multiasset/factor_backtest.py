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
from typing import Dict, List, Optional, Union

import numpy as np
import pandas as pd
from pathlib import Path

from multiasset.pca_analyzer import (
    DeterministicRiskFactorAnalyzer,
    DETERMINISTIC_WEIGHTS,
    DETERMINISTIC_SPREAD_WEIGHTS,
)
from multiasset.risk_loader import RiskFactorLoader
from settings.paths import DIR_INPUT


# ── Representative modified durations for factor portfolios ─────────────────
# These map factor codes → approximate portfolio modified duration (years).
# Yield factors: duration is the portfolio-weighted duration given the
# deterministic weight vector across tenors [1Y, 2Y, 5Y, 10Y, 30Y].
# Tenor durations: [0.97, 1.90, 4.60, 8.80, 20.0]
_TENOR_DURATIONS = np.array([0.97, 1.90, 4.60, 8.80, 20.0])

_FACTOR_MOD_DURATION: Dict[str, float] = {}
for _factor_name, _weights in DETERMINISTIC_WEIGHTS.items():
    _d = float(np.dot(np.abs(_weights), _TENOR_DURATIONS))
    _prefix = {'Level': 'IRDL', 'Slope': 'IRSL', 'Curvature': 'IRCV'}[_factor_name]
    _FACTOR_MOD_DURATION[_prefix] = _d

# Spread durations (approximate)
_SPREAD_TENOR_DURATIONS = {
    'CDB': np.array([0.97, 1.90, 4.60, 8.80, 20.0]),
    'IRS': np.array([0.97, 1.90, 4.60]),
    'ICP': np.array([0.97]),
}
for _sp_type, _sp_weights in DETERMINISTIC_SPREAD_WEIGHTS.items():
    _dur_vec = _SPREAD_TENOR_DURATIONS.get(_sp_type, np.array([1.0]))
    for _f_name, _w in _sp_weights.items():
        _d = float(np.dot(np.abs(_w), _dur_vec[:len(_w)]))
        _prefix = {'Level': 'SPDL', 'Slope': 'SPSL'}[_f_name]
        _FACTOR_MOD_DURATION[f"{_prefix}.{_sp_type}"] = _d


def get_factor_duration(factor_code: str) -> float:
    """Return the representative modified duration for a factor code.

    Lookup order:
      1. Exact match  (e.g. "SPDL.CDB")
      2. Prefix match (e.g. "IRDL" matches "IRDL.CN")
    Falls back to 1.0 for price-based factors (FX, Commodities).
    """
    if factor_code in _FACTOR_MOD_DURATION:
        return _FACTOR_MOD_DURATION[factor_code]
    prefix = factor_code.split('.')[0]
    # Check for spread-type factors like SPDL.CDB -> key "SPDL.CDB"
    if '.' in factor_code:
        suffix = factor_code.split('.')[1]
        key = f"{prefix}.{suffix}"
        if key in _FACTOR_MOD_DURATION:
            return _FACTOR_MOD_DURATION[key]
    if prefix in _FACTOR_MOD_DURATION:
        return _FACTOR_MOD_DURATION[prefix]
    # FX and Commodities: use pct_change, not duration
    return 0.0


def _is_yield_factor(factor_code: str) -> bool:
    """Return True if this factor is yield/spread-based (needs duration conversion)."""
    prefix = factor_code.split('.')[0]
    return prefix in ('IRDL', 'IRSL', 'IRCV', 'SPDL', 'SPSL')


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
    **strategy_kwargs,
) -> Dict[str, pd.DataFrame]:
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
    **strategy_kwargs
        Override default strategy parameters.

    Returns
    -------
    dict  {factor_code: DataFrame}
    """
    factor_levels = load_factor_rates(input_dir)

    # Ensure index is DatetimeIndex for consistent slicing
    if not isinstance(factor_levels.index, pd.DatetimeIndex):
        factor_levels.index = pd.to_datetime(factor_levels.index)

    # ── Factor Model strategy: delegate to dedicated engine ─────────────
    if strategy == 'FactorModel':
        from multiasset.factor_model import run_factor_model_batch, FactorModelConfig
        fm_cfg = FactorModelConfig()
        # Apply overrides from kwargs
        for k, v in strategy_kwargs.items():
            if hasattr(fm_cfg, k):
                setattr(fm_cfg, k, type(getattr(fm_cfg, k))(v))
        results = run_factor_model_batch(
            factors=factors,
            start_date=start_date,
            end_date=end_date,
            input_dir=input_dir,
            config=fm_cfg,
            save=save,
        )
        return results

    # ── Technical indicator strategies ──────────────────────────────────
    if start_date:
        factor_levels = factor_levels.loc[pd.Timestamp(start_date):]
    if end_date:
        factor_levels = factor_levels.loc[:pd.Timestamp(end_date)]

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

    return results


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


def compute_metrics(result_df: pd.DataFrame) -> Dict[str, float]:
    """Compute performance metrics from a single factor backtest result."""
    rets = result_df['strategy_returns'].dropna()
    if rets.empty:
        return {}

    total_return = float((1 + rets).prod() - 1)
    ann_return = float(rets.mean() * 252)
    ann_vol = float(rets.std() * np.sqrt(252))
    sharpe = ann_return / ann_vol if ann_vol > 0 else np.nan

    cum = (1 + rets).cumprod()
    running_max = cum.cummax()
    dd = (cum / running_max - 1)
    max_dd = float(dd.min())

    win_rate = float((rets > 0).sum() / len(rets)) if len(rets) > 0 else 0.0

    return {
        'Total Return': total_return,
        'Ann. Return': ann_return,
        'Ann. Vol': ann_vol,
        'Sharpe': sharpe,
        'Max Drawdown': max_dd,
        'Win Rate': win_rate,
        'Days': len(rets),
    }
