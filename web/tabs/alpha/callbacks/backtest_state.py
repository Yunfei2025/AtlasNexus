# -*- coding: utf-8 -*-
"""Latest backtest position state for a single TenorSpread instrument.

Runs the same monthly-style backtest the Backtest tab's "Run Individual
Backtest" button runs (same presets, saved per-instrument params, carry/OU
anchor and sign handling) so the Candidates tab's Open Positions card can
reflect what the backtest actually holds on the latest date instead of the
saved Risk-tab positions file.
"""
from __future__ import annotations

import re
from typing import Optional

import numpy as np
import pandas as pd

from ..data import (
    YIELD_BASED_SPREAD_TYPES,
    load_spread_data, load_spread_timeseries, load_carry_roll_timeseries,
    _get_duration_mult, _get_borrow_cost_annual_bp, load_instrument_params,
)

# Mirrors backtest_tab.preset_backtest_params / bt-period default (504 days).
_PERIOD = 504
_TENOR_PRESET = dict(entry_z=2.5, exit_z=0.25, stop_z=3.0, min_hold=10, theta=1.50,
                     mom_window=30, vol_window=90, trailing_mult=2.0,
                     carry_z_weight=0.5, mr_lookback=120)
_DEFAULT_PRESET = dict(entry_z=2.0, exit_z=0.5, stop_z=3.0, min_hold=7, theta=1.25,
                       mom_window=20, vol_window=60, trailing_mult=1.5,
                       carry_z_weight=0.5, mr_lookback=120)


# Backtests carry raw carry+roll only. Financing is deducted at portfolio level
# and borrow cost is partly netted against the Beta book, so neither is charged
# per-instrument here (decided 2026-10-25). Flip to True to charge borrow cost.
BACKTEST_INCLUDE_BORROW_COST = False


def backtest_borrow_cost_bp(spread_type: str, instrument: str) -> tuple[float, float]:
    if not BACKTEST_INCLUDE_BORROW_COST:
        return 0.0, 0.0
    return _get_borrow_cost_annual_bp(spread_type, instrument)


# Spreads with a credit-bond leg that cannot be borrowed/shorted (LGB, MTN, NCD):
# the SELL side would short that bond, so these are BUY-only everywhere --
# backtests, the Core card and the candidate pool (user 2026-10-25).
NO_SHORT_PREFIXES = ('LGB', 'MTN', 'NCD')


def short_allowed(instrument: str) -> bool:
    return not str(instrument or '').strip().upper().startswith(NO_SHORT_PREFIXES)


def carry_needs_negate(spread_type: str, instrument: str) -> bool:
    """Whether stored carry must be flipped to the engine's LONG orientation.

    Yield-based spreads are backtested on the inverted series, so their stored
    carry is flipped -- except TenorSpread flies (NsMsLs) and cross-curve names
    (CDBCGB-*, *Repo7d-*), which are already stored as BUY = engine LONG.
    """
    if spread_type != 'TenorSpread':
        return spread_type in YIELD_BASED_SPREAD_TYPES
    if len(re.findall(r'\d+s', instrument, re.IGNORECASE)) >= 3:
        return False  # fly
    return bool(re.search(r'\d+s\d+', instrument, re.IGNORECASE))  # XsYs; cross-curve -> False


def latest_position(results) -> str:
    """'BUY'/'SELL'/'FLAT' for a backtest result dict's open trade on the last date."""
    open_trade = results.get('open_trade') if isinstance(results, dict) else None
    if not open_trade:
        return 'FLAT'
    # Engines see the sign-normalised series: LONG = BUY, SHORT = SELL.
    return 'BUY' if str(open_trade.get('direction', '')).upper() == 'LONG' else 'SELL'


def run_instrument_backtest(spread_type: str, instrument: str, period: int = _PERIOD) -> Optional[dict]:
    """Run the Backtest tab's individual monthly-style backtest for one instrument
    with its saved params (preset fills gaps). Single source of truth shared by
    the Candidates reconcile and the Portfolio backtest, so both hold the same
    position for the same name. Returns the engine result dict, or None if it
    could not be run."""
    from .backtest_tab import _run_monthly_style_switch_backtest, _allow_trend_style_for
    try:
        spread_ts = load_spread_timeseries(spread_type)
        if spread_ts is None or instrument not in spread_ts.columns:
            return None
        ts = spread_ts[instrument].tail(period)
        if len(ts.dropna()) < 60:
            return None

        params = dict(_TENOR_PRESET if spread_type == 'TenorSpread' else _DEFAULT_PRESET)
        saved = load_instrument_params(spread_type, instrument) or {}
        for k in params:
            if saved.get(k) is not None:
                params[k] = saved[k]
        allow_short = bool(saved['allow_short']) if saved.get('allow_short') is not None else True
        allow_short = allow_short and short_allowed(instrument)

        is_yield_based = spread_type in YIELD_BASED_SPREAD_TYPES
        carry_ts: Optional[pd.Series] = None
        carry_bp = 0.0
        ou_mean: Optional[float] = None
        cr_df = load_carry_roll_timeseries(spread_type)
        if isinstance(cr_df, pd.DataFrame) and not cr_df.empty and instrument in cr_df.columns:
            carry_ts = cr_df[instrument].dropna()
        snap = load_spread_data(spread_type)
        if isinstance(snap, pd.DataFrame) and instrument in snap.index:
            row = snap.loc[instrument]
            for c in ('carry_roll', 'carry', 'CarryRoll3m', 'CarryRoll', 'Carry', 'carry_roll_3m'):
                if c in row.index and row.get(c) is not None and np.isfinite(float(row.get(c))):
                    carry_bp = float(row.get(c))
                    break
            if str(row.get('stationary', '')).strip().upper() == 'YES' and 'mean' in row.index:
                m = row.get('mean')
                if m is not None and np.isfinite(float(m)):
                    ou_mean = float(m)

        # Carry sign convention (see backtest_tab): XsYs names are stored flipped.
        negate_carry = carry_needs_negate(spread_type, instrument)
        if negate_carry:
            carry_ts = -carry_ts if carry_ts is not None else None
            carry_bp = -carry_bp
        if ou_mean is not None and is_yield_based:
            ou_mean = -ou_mean

        bc_long, bc_short = backtest_borrow_cost_bp(spread_type, instrument)
        results = _run_monthly_style_switch_backtest(
            ts=-ts if is_yield_based else ts,
            spread_type=spread_type,
            entry_z=params['entry_z'], exit_z=params['exit_z'], stop_z=params['stop_z'],
            min_hold=int(params['min_hold']), theta=float(params['theta']),
            vol_window=int(params['vol_window']), trailing_mult=float(params['trailing_mult']),
            carry_roll_ts=carry_ts, carry_roll_bp=carry_bp,
            duration_mult=_get_duration_mult(instrument, spread_type),
            borrow_cost_long_bp=bc_long, borrow_cost_short_bp=bc_short,
            allow_short=allow_short, carry_roll_sell_ts=None,
            mom_window=int(params['mom_window']), ou_mean=ou_mean,
            carry_z_weight=float(params['carry_z_weight']),
            mr_lookback=int(params['mr_lookback']),
            allow_trend_style=_allow_trend_style_for(spread_type, instrument),
        )
        return results if isinstance(results, dict) and 'error' not in results else None
    except Exception:
        return None


def backtest_open_direction(spread_type: str, instrument: str) -> Optional[str]:
    """Return 'BUY'/'SELL' if the backtest is in a position on the latest date,
    'FLAT' if it is not, or None if the backtest could not be run."""
    results = run_instrument_backtest(spread_type, instrument)
    return None if results is None else latest_position(results)
