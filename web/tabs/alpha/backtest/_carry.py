# -*- coding: utf-8 -*-
"""Carry accrual helper shared by both backtest engines."""

from __future__ import annotations

from typing import Optional

import pandas as pd


def _carry_accrual(
    position: int,
    entry_date: pd.Timestamp,
    exit_date: pd.Timestamp,
    days_held: int,
    carry_roll_ts: Optional[pd.Series],
    carry_roll_bp: float,
    borrow_cost_long_bp: float = 0.0,
    borrow_cost_short_bp: float = 0.0,
    spread_type: Optional[str] = None,
    tenor_ratio: float = 1.0,
    carry_roll_sell_ts: Optional[pd.Series] = None,
) -> float:
    """Compute carry accrual for a trade including direction-dependent borrow cost.

    For TenorSpread: carry_roll_ts = cr_buy (BUY borrow cost embedded),
    carry_roll_sell_ts = cr_sell (SELL borrow cost embedded).
    SELL trades use carry_roll_sell_ts when provided.
    For other spread types, carry_roll_ts is used for both directions.
    """
    ts_to_use = carry_roll_ts
    if position == -1 and carry_roll_sell_ts is not None:
        ts_to_use = carry_roll_sell_ts

    carry_income = 0.0
    if ts_to_use is not None and len(ts_to_use) > 0:
        try:
            ts = ts_to_use
            if not isinstance(ts.index, pd.DatetimeIndex):
                ts = ts.copy()
                ts.index = pd.to_datetime(ts.index)
            elif hasattr(ts.index, 'tz') and ts.index.tz is not None:
                ts = ts.copy()
                ts.index = ts.index.tz_localize(None)
            t0 = pd.Timestamp(entry_date)
            t1 = pd.Timestamp(exit_date)
            if t0.tzinfo is not None:
                t0 = t0.tz_localize(None)
            if t1.tzinfo is not None:
                t1 = t1.tz_localize(None)
            window = ts.loc[t0:t1].dropna()
            if len(window) > 0:
                # window contains daily carry rates in % (3m convention from load_carry_roll_timeseries).
                # Return in % (same unit as spread_ts) so it can be combined with price_pnl.
                # Divide by 90 to scale 3m rate to actual holding period fraction.
                # Caller (trade record) multiplies by 100 to convert to bp for display.
                carry_income = position * float(window.sum()) / 90.0
        except Exception:
            pass

    # For TenorSpread, BondCurve, and BondSwap, borrow costs are already included in carry_roll_ts
    # (adjusted in callback). For other spread types, deduct borrow costs based on days held.
    if days_held > 0 and spread_type not in ['TenorSpread', 'BondCurve', 'BondSwap', 'TBondCurve', 'CBondCurve', 'TBondSwap', 'CBondSwap']:
        borrow_cost = borrow_cost_long_bp if position == 1 else borrow_cost_short_bp
        if borrow_cost != 0.0:
            carry_income -= abs(borrow_cost) / 100.0 * days_held / 365.0

    return carry_income
