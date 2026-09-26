# -*- coding: utf-8 -*-
"""
Factor-level backtest engine for yield-based risk factors.

Generates factor yield series from the deterministic model (IRDL, IRSL, IRCV,
CRDL, CRSL, CRCV, FXDL, CMDL), converts yield changes to duration-adjusted
returns, runs close-only technical strategies, and persists results.

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
from multiasset.pca_analyzer import (
    get_deterministic_ir_tenors,
    get_deterministic_ir_weights,
)
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


_CR_FACTOR_TO_LEVEL_NAME = {'CRDL': 'Level', 'CRSL': 'Slope', 'CRCV': 'Curvature'}


def _credit_weighted_duration(factor_code: str) -> Optional[float]:
    """Tenor-weighted modified duration for a CRDL/CRSL/CRCV credit factor.

    Mirrors get_factor_weighted_duration's IR logic, but uses each credit
    universe's own (uneven) tenor grid and log-tenor-space weights from
    multiasset.config.get_credit_weights, with approximate modified
    durations from multiasset.utils.get_default_sensitivities.
    """
    from multiasset.config import CREDIT_CONFIG, get_credit_weights, CREDIT_NO_CURVATURE
    from multiasset.utils import get_default_sensitivities

    prefix, _, universe = factor_code.partition('.')
    level_name = _CR_FACTOR_TO_LEVEL_NAME.get(prefix)
    if level_name is None or universe not in CREDIT_CONFIG:
        return None

    tenor_cols = CREDIT_CONFIG[universe][2]
    tenor_years = [t for _, _, t in tenor_cols]
    include_curvature = universe not in CREDIT_NO_CURVATURE
    weights_by_factor = get_credit_weights(tenor_years, include_curvature=include_curvature)
    weights = weights_by_factor.get(level_name)
    if weights is None:
        return None

    durations = [get_default_sensitivities(f"{t:g}Y" if t >= 1 else f"{int(t * 12)}M").get('IRDL', 0.0)
                 for t in tenor_years]
    return sum(w * d for w, d in zip(weights, durations))


def get_factor_weighted_duration(factor_code: str) -> Optional[float]:
    """Tenor-weighted modified duration of an IR or credit factor portfolio.

    Computed as ``Σ w_i × D_i`` where ``w_i`` are the deterministic factor
    weights and ``D_i`` are approximate modified durations for each tenor.

    Returns ``None`` for non-yield factors (FX, commodity).
    """
    prefix, _, country = factor_code.partition('.')
    ir_factor_to_basis = {'IRDL': 'Level', 'IRSL': 'Slope', 'IRCV': 'Curvature'}
    basis_name = ir_factor_to_basis.get(prefix)
    if basis_name is not None:
        from multiasset.utils import get_default_sensitivities

        tenors = get_deterministic_ir_tenors(country)
        weights = get_deterministic_ir_weights(country)[basis_name]
        durations = [get_default_sensitivities(tenor).get('IRDL', 0.0) for tenor in tenors]
        return sum(w * d for w, d in zip(weights, durations))
    if prefix in _CR_FACTOR_TO_LEVEL_NAME:
        return _credit_weighted_duration(factor_code)
    return None


def _is_yield_factor(factor_code: str) -> bool:
    """Return True if this factor is yield/spread-based (needs duration conversion).

    'SP*' (SPDL/SPSL/SPCV) is the retired naming for what CRDL/CRSL/CRCV
    now cover under a broader universe (LGB, MTN added) and full Curvature
    coverage — the data-generation pipeline (risk_loader._load_sp_factors)
    was removed, so no live factor should carry that prefix, but it's kept
    recognised here for compatibility with any stale saved artifact still
    referencing it.
    """
    prefix = factor_code.split('.')[0]
    return prefix in ('IRDL', 'IRSL', 'IRCV', 'SPDL', 'SPSL', 'SPCV', 'CRDL', 'CRSL', 'CRCV')


# 'DL' (Level) factors are equal-weighted (sum=1) portfolios of outright
# tenor yields — see DETERMINISTIC_WEIGHTS / CN_DETERMINISTIC_WEIGHTS in
# pca_analyzer.py. The factor level *is* a genuine yield, so daily accrual
# (carry) is unambiguous in principle: level/100/252.
#
# 'SL' (Slope) and 'CV' (Curvature) factors are long-short (weights sum to
# 0) contrasts across tenors — the level has no accrual interpretation on
# its own (e.g. a negative slope reading is not "negative carry" the way a
# negative yield level would be; it depends on the actual long/short leg
# notionals). Their carry is the *difference* of each leg's own carry+roll,
# which needs the per-tenor data and loading weights this module doesn't
# currently thread through (see multiasset.rolldown.carry_rolldown for the
# per-tenor carry+roll-down calc used elsewhere, in tenor-selection tilt —
# not yet wired into the Slope/Curvature *level* return series). Left as a
# documented gap rather than guessed at.
_LEVEL_FACTOR_PREFIXES: frozenset = frozenset({'IRDL', 'SPDL', 'CRDL'})


def _is_level_factor(factor_code: str) -> bool:
    """Return True if this is a Level-type yield factor (has unambiguous carry)."""
    return factor_code.split('.')[0] in _LEVEL_FACTOR_PREFIXES


# IRDL is the raw government-bond yield level for a country, held on a
# funded (repo/reverse-repo) basis. The funding/repo cost is NOT netted
# into carry — gross yield/252 is the return the position actually earns,
# and financing cost is a leverage decision, not part of the asset's own
# return. Instead, the funding cost is deducted from 'strategy_returns' as
# a daily, position-scaled cost — see funding_cost_series() /
# _apply_funding_cost() — charged only on the days, and to the extent, the
# position actually held duration exposure.
#
# Scoped to IRDL only for now: SPDL/CRDL (credit/swap spread levels — CDB
# vs Treasury, IRS spread, LGB, etc.) are already spreads over a
# risk-free curve, so it's not established that the same funding-rate
# deduction applies to them the same way without double-netting an
# already-embedded funding cost — left as a separate question rather than
# assumed here.
_IRDL_FUNDING_RATE_MACRO_COL = {
    'CN': 'FR007',   # 7-day reverse repo rate — CN onshore funding cost
    'US': 'SOFR',
    'DE': 'ESTR',
    'UK': 'SONIA',
    'JP': 'TONAR',
}

_funding_rate_cache: Dict[str, pd.Series] = {}


def _load_funding_rate(country: str) -> Optional[pd.Series]:
    """Load the daily funding-rate series (percent) for an IRDL country.

    Reads macro-px.pkl directly rather than importing multiasset.factor_model
    (which itself imports this module — would be circular). Cached per
    country code since this is called once per factor per backtest.
    """
    if country in _funding_rate_cache:
        return _funding_rate_cache[country]

    macro_col = _IRDL_FUNDING_RATE_MACRO_COL.get(country)
    if macro_col is None:
        return None

    try:
        macro_path = os.path.join(str(DIR_INPUT), 'macro-px.pkl')
        raw = pd.read_pickle(macro_path)
        macro_df = pd.concat(raw, axis=1).droplevel(0, axis=1)
        macro_df.columns = [c.split('.')[0] for c in macro_df.columns]
        if macro_col not in macro_df.columns:
            _funding_rate_cache[country] = None
            return None
        rate = macro_df[macro_col].dropna()
        # Same index-type defect fixed in factors.generator.macro._load_macro:
        # the source pickle's index is plain datetime.date, not Timestamp.
        rate.index = pd.to_datetime(rate.index)
        _funding_rate_cache[country] = rate
    except Exception as e:
        print(f"Warning: could not load funding rate for {country} ({macro_col}): {e}")
        _funding_rate_cache[country] = None

    return _funding_rate_cache[country]


def _yield_carry(level: pd.Series, factor_code: str) -> pd.Series:
    """Daily accrual (carry) for a Level-type yield factor, in return space.

    Always GROSS: ``carry_t = yield_{t-1} / 100 / 252``. Funding/repo cost
    is a financing choice, not part of the bond's own return, so it is
    never netted into the return series here — see funding_cost_series()
    for where the funding cost is deducted instead (from strategy_returns,
    as a daily position-scaled cost, not from the underlying P&L itself).

    Returns an all-zero series for non-Level factors (Slope/Curvature —
    see _is_level_factor) so callers can add this unconditionally without
    an extra branch, until Slope/Curvature carry is implemented.
    """
    if not _is_level_factor(factor_code):
        return pd.Series(0.0, index=level.index)

    return level.shift(1) / 100.0 / 252.0


def funding_cost_series(position: pd.Series, level: pd.Series, factor_code: str) -> pd.Series:
    """Daily funding/repo cost of holding ``position`` in an IRDL factor.

    IRDL is the raw government-bond yield level for a country, held on a
    funded (repo/reverse-repo) basis — the real risk-adjusted return of
    holding it is the spread earned over the cost of financing it. Gross
    carry (see ``_yield_carry``) never nets this out of the return/P&L
    series (funding is a financing choice, not part of the asset's own
    return — the book's return convention elsewhere doesn't deduct
    financing cost from return figures either).

    Instead, funding cost is charged only on the days, and to the extent,
    the position actually holds duration exposure:

        cost_t = position_{t-1} * funding_rate_{t-1} / 100 / 252

    matching how ``strategy_returns`` itself is built from
    ``position.shift(1) * returns``. A flat annualised deduction applied
    regardless of position size (an earlier version of this function)
    overcharges a strategy that is flat or lightly positioned most of the
    time, and — because strategy-return vol scales down with position size
    while a flat-rate deduction doesn't — can swing Sharpe by many points
    off a tiny vol denominator. Charging it on the actual (signed, scaled)
    exposure keeps the deduction proportionate to the risk actually run.

    ``position`` may be a signal in {-1, 0, 1} (MA/Bollinger/Momentum/
    Z-Score's ``signal`` column) or continuous in [-1, 1] (FactorModel's
    ``position`` column) — either way the caller passes whichever column
    it built ``strategy_returns`` from, so the funding charge is levied on
    the same exposure that earned the carry.

    Scoped to IRDL only: SPDL/CRDL (credit/swap spread levels — CDB vs
    Treasury, IRS spread, LGB, etc.) are already spreads over a risk-free
    curve, so it's not established that the same funding-rate deduction
    applies to them without double-netting an already-embedded funding
    cost — left as a separate question rather than assumed here. Returns
    an all-zero series for any non-IRDL factor code.
    """
    prefix, _, suffix = factor_code.partition('.')
    if prefix != 'IRDL':
        return pd.Series(0.0, index=level.index)

    funding_rate = _load_funding_rate(suffix)
    if funding_rate is None:
        return pd.Series(0.0, index=level.index)

    funding_aligned = funding_rate.reindex(level.index).ffill()
    daily_rate = funding_aligned.shift(1) / 100.0 / 252.0
    pos_aligned = position.reindex(level.index).shift(1).fillna(0.0)
    return (pos_aligned * daily_rate).fillna(0.0)


def factor_level_to_price_return(
    series: pd.Series,
    factor_code: str,
    output_in_percent: bool = False,
) -> pd.Series:
    """Convert a factor level series into factor portfolio returns.

    Despite the name (kept for backward compatibility with existing
    callers), this now includes carry for Level-type yield factors — see
    _yield_carry — not price return alone. Returns are emitted in decimal
    form by default for backtests, and in percent form when
    ``output_in_percent=True`` for dashboards/optimizer reporting.
    """
    if _is_yield_factor(factor_code):
        returns_pct = -get_factor_duration(factor_code) * series.diff()
        returns_pct = returns_pct + _yield_carry(series, factor_code) * 100.0
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

    # Backfill any columns that exist in fresh but not in existing (e.g. a new
    # factor was added to RiskFactorLoader since the pkl was last fully
    # regenerated) using fresh's full history — otherwise those columns would
    # be all-NaN for every pre-existing row and only populated for new_rows.
    new_cols = [c for c in fresh.columns if c not in existing.columns]
    if new_cols:
        existing = existing.join(fresh.loc[existing.index.intersection(fresh.index), new_cols], how='left')
        print(f"factor-rates.pkl: backfilling {len(new_cols)} new column(s) across history: {new_cols}")

    if n_new == 0 and not new_cols:
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


def _compute_credit_factor_levels(input_dir: Union[str, Path]) -> pd.DataFrame:
    """Compute CRDL/CRSL/CRCV columns directly via the analyzer (bypasses the
    full RiskFactorLoader so refreshing credit doesn't recompute IR/FX/commodity)."""
    analyzer = DeterministicRiskFactorAnalyzer(str(input_dir))
    det_scores = analyzer.calculate_full_history_deterministic_credit_scores()
    if det_scores.empty:
        return det_scores

    factor_to_cr_map = {'Level': 'CRDL', 'Slope': 'CRSL', 'Curvature': 'CRCV'}
    out = pd.DataFrame(index=det_scores.index)
    for col in det_scores.columns:
        factor_name, universe = col.split('.')
        if factor_name in factor_to_cr_map:
            out[f"{factor_to_cr_map[factor_name]}.{universe}"] = det_scores[col]

    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index)
    return out.sort_index()


def generate_factor_credit(
    input_dir: Union[str, Path] = DIR_INPUT,
    save: bool = True,
) -> pd.DataFrame:
    """Generate and optionally save the credit spread factor level series.

    Produces a DataFrame indexed by date with columns ``CRDL.CDB``, ``CRSL.LGB``,
    ``CRCV.MTN``, ``CRDL.NCD``/``CRSL.NCD`` (no curvature for NCD — see
    ``CREDIT_NO_CURVATURE``), etc.

    Saves to ``<input_dir>/factor-credit.pkl``, kept separate from
    ``factor-rates.pkl`` so credit can be refreshed on its own cadence.
    """
    factor_levels = _compute_credit_factor_levels(input_dir)
    if factor_levels is None or factor_levels.empty:
        raise ValueError("No credit factor levels computed")

    if save:
        out_path = os.path.join(str(input_dir), 'factor-credit.pkl')
        factor_levels.to_pickle(out_path)
        print(f"Saved factor-credit.pkl  ({factor_levels.shape[1]} factors, "
              f"{len(factor_levels)} days)")

    return factor_levels


def load_factor_credit(input_dir: Union[str, Path] = DIR_INPUT) -> pd.DataFrame:
    """Load factor-credit.pkl; regenerate if missing."""
    pkl_path = os.path.join(str(input_dir), 'factor-credit.pkl')
    if os.path.exists(pkl_path):
        return pd.read_pickle(pkl_path)
    return generate_factor_credit(input_dir, save=True)


def update_factor_credit(
    input_dir: Union[str, Path] = DIR_INPUT,
) -> Tuple[pd.DataFrame, int]:
    """Incrementally append new daily rows to factor-credit.pkl.

    Mirrors ``update_factor_rates``: merges freshly computed credit factor
    levels with any existing pkl, appending only dates newer than the last
    saved date. Falls back to a full regenerate when the pkl does not exist.
    """
    pkl_path = os.path.join(str(input_dir), 'factor-credit.pkl')

    fresh = _compute_credit_factor_levels(input_dir)
    if fresh is None or fresh.empty:
        raise ValueError("No credit factor levels computed")

    if not os.path.exists(pkl_path):
        fresh.to_pickle(pkl_path)
        print(f"factor-credit.pkl created ({fresh.shape[1]} factors, {len(fresh)} days)")
        return fresh, len(fresh)

    existing = pd.read_pickle(pkl_path)
    if not isinstance(existing.index, pd.DatetimeIndex):
        existing.index = pd.to_datetime(existing.index)

    last_saved = existing.index.max()
    new_rows = fresh[fresh.index > last_saved]
    n_new = len(new_rows)

    # Backfill any columns that exist in fresh but not in existing (e.g. a new
    # credit universe was added since the pkl was last fully regenerated).
    new_cols = [c for c in fresh.columns if c not in existing.columns]
    if new_cols:
        existing = existing.join(fresh.loc[existing.index.intersection(fresh.index), new_cols], how='left')
        print(f"factor-credit.pkl: backfilling {len(new_cols)} new column(s) across history: {new_cols}")

    if n_new == 0 and not new_cols:
        print(f"factor-credit.pkl already up to date (last date: {last_saved.date()})")
        return existing, 0

    merged = pd.concat([existing, new_rows])
    merged = merged[~merged.index.duplicated(keep='last')].sort_index()
    merged.to_pickle(pkl_path)
    print(f"factor-credit.pkl updated: +{n_new} days (now {len(merged)} days total, "
          f"through {merged.index.max().date()})")
    return merged, n_new


# ── Yield-aware strategy wrappers ───────────────────────────────────────────
# Each accepts a Series of yield (or price) levels and returns a DataFrame
# with at least: signal, returns, strategy_returns, cumulative_returns.

def _yield_to_return(
    series: pd.Series,
    mod_dur: float,
    factor_code: Optional[str] = None,
) -> pd.Series:
    """Convert yield level series to approximated bond TOTAL return series.

    r_t ≈ -D_mod × Δy_t / 100 + carry_t

    The price-return term (-D×Δy/100) was previously the whole formula —
    it captures only mark-to-market from yield changes and omits the
    coupon/carry accrual a bond actually earns while held. On IRDL.CN this
    understated the full-history annualised return by ~2.8 percentage
    points (0.17% price-only vs ~3.0% price+carry, against a ~2.8% average
    yield level) — carry, not price movement, is most of a duration
    factor's real return.
    ``factor_code`` is optional and, when omitted or not a Level-type
    factor (see _is_level_factor), the carry term is exactly zero — the
    pre-fix behaviour, and the current state for Slope/Curvature factors
    pending their own (leg-difference, not level-based) carry formula.

    Carry here is always GROSS of funding/repo cost (see _yield_carry) —
    funding is a financing choice, not part of the bond's own return, and
    is never netted into the P&L. For IRDL, the funding-rate cost is
    instead deducted from strategy_returns as a daily position-scaled cost
    — see funding_cost_series() / _apply_funding_cost().
    """
    price_return = -mod_dur * series.diff() / 100.0
    if factor_code is None:
        return price_return
    return price_return + _yield_carry(series, factor_code)


def _price_to_return(series: pd.Series) -> pd.Series:
    """Simple percentage return for price-based factors (FX, Cmdty)."""
    return series.pct_change()


def _apply_funding_cost(
    strategy_returns: pd.Series,
    position: pd.Series,
    levels: pd.Series,
    factor_code: Optional[str],
) -> pd.Series:
    """Subtract IRDL's position-scaled daily funding cost from strategy_returns.

    No-op (returns ``strategy_returns`` unchanged) for any non-IRDL factor,
    or when ``factor_code`` is None — see funding_cost_series().
    """
    if factor_code is None:
        return strategy_returns
    cost = funding_cost_series(position, levels, factor_code)
    return strategy_returns - cost.reindex(strategy_returns.index).fillna(0.0)


def run_ma_yield_strategy(
    levels: pd.Series,
    mod_dur: float,
    is_yield: bool,
    short_window: int = 10,
    long_window: int = 30,
    factor_code: Optional[str] = None,
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
        df['returns'] = _yield_to_return(levels, mod_dur, factor_code)
    else:
        df['returns'] = _price_to_return(levels)

    df['strategy_returns_gross'] = df['signal'].shift(1) * df['returns']
    df['strategy_returns'] = _apply_funding_cost(
        df['strategy_returns_gross'], df['signal'], levels, factor_code)
    df['cumulative_returns'] = (1 + df['strategy_returns'].fillna(0)).cumprod()
    return df


def run_bollinger_yield_strategy(
    levels: pd.Series,
    mod_dur: float,
    is_yield: bool,
    window: int = 20,
    num_std: float = 1.5,
    factor_code: Optional[str] = None,
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
        df['returns'] = _yield_to_return(levels, mod_dur, factor_code)
    else:
        df['returns'] = _price_to_return(levels)

    df['strategy_returns_gross'] = df['signal'].shift(1) * df['returns']
    df['strategy_returns'] = _apply_funding_cost(
        df['strategy_returns_gross'], df['signal'], levels, factor_code)
    df['cumulative_returns'] = (1 + df['strategy_returns'].fillna(0)).cumprod()
    return df


def run_momentum_yield_strategy(
    levels: pd.Series,
    mod_dur: float,
    is_yield: bool,
    window: int = 20,
    factor_code: Optional[str] = None,
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
        df['returns'] = _yield_to_return(levels, mod_dur, factor_code)
    else:
        df['returns'] = _price_to_return(levels)

    df['strategy_returns_gross'] = df['signal'].shift(1) * df['returns']
    df['strategy_returns'] = _apply_funding_cost(
        df['strategy_returns_gross'], df['signal'], levels, factor_code)
    df['cumulative_returns'] = (1 + df['strategy_returns'].fillna(0)).cumprod()
    return df


def run_zscore_yield_strategy(
    levels: pd.Series,
    mod_dur: float,
    is_yield: bool,
    window: int = 60,
    entry_z: float = 1.5,
    exit_z: float = 0.5,
    factor_code: Optional[str] = None,
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
        df['returns'] = _yield_to_return(levels, mod_dur, factor_code)
    else:
        df['returns'] = _price_to_return(levels)

    df['strategy_returns_gross'] = df['signal'].shift(1) * df['returns']
    df['strategy_returns'] = _apply_funding_cost(
        df['strategy_returns_gross'], df['signal'], levels, factor_code)
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
) -> Tuple[Dict[str, pd.DataFrame], Optional[Dict], Optional[Dict]]:
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
    (results, latest_artifact, models_by_month)
        results         : {factor_code: DataFrame}
        latest_artifact : artifact dict for the latest month, or None.
        models_by_month : {month_key: {factor_code: model_artifact}} for the
                          ``'FactorModel'`` strategy (populated regardless of
                          ``save`` — lets a caller defer the disk write via
                          ``multiasset.factor_model.save_factor_model_results``
                          without re-running the backtest); ``None`` for the
                          technical-indicator strategies, which have no
                          trained-model concept.
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
        results, latest_artifact, models_by_month = run_factor_model_batch(
            factors=factors,
            start_date=start_date,
            end_date=end_date,
            input_dir=input_dir,
            config=fm_cfg,
            save=save,
            save_latest_only=save_latest_only,
        )
        return results, latest_artifact, models_by_month

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
            factor_code=factor,
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

    # Non-FactorModel strategies have no model artifact / trained-model concept
    return results, None, None


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
