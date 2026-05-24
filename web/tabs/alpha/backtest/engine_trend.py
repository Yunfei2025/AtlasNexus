# -*- coding: utf-8 -*-
"""Trend / carry backtest engine using directional-change trend confirmation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ._carry import _carry_accrual


def _dc_trend_state(series: pd.Series, theta: float) -> pd.Series:
    """Compute trend state (+1/-1) from directional-change events."""
    try:
        from curves.calibration.trend import generate as dc_generate
    except Exception:
        dc_generate = None

    s = pd.to_numeric(series, errors='coerce').dropna().copy()
    if s.empty:
        return pd.Series(dtype=float)

    if dc_generate is None:
        st = np.sign(s.diff()).replace(0, np.nan).ffill().fillna(0.0)
        st.name = 'trend_state'
        return st

    events = dc_generate(s, float(theta))
    state = pd.Series(index=s.index, dtype=float)
    cur = 0.0
    for dt, ev in events.items():
        if ev == 'Upward Trend Confirmed':
            cur = 1.0
        elif ev == 'Downward Trend Confirmed':
            cur = -1.0
        state.loc[dt] = cur
    state = state.ffill().fillna(0.0)
    state.name = 'trend_state'
    return state


def run_trend_backtest_dc(
    spread_ts: pd.Series,
    theta: float = 0.02,
    mom_window: int = 20,
    vol_window: int = 60,
    trailing_mult: float = 1.5,
    carry_buffer: float = 0.0,
    max_hold: int = 60,
    allow_short: bool = True,
    carry_roll_ts: Optional[pd.Series] = None,
    carry_roll_bp: float = 0.0,
    duration_mult: float = 1.0,
    borrow_cost_long_bp: float = 0.0,
    borrow_cost_short_bp: float = 0.0,
    spread_type: Optional[str] = None,
    tenor_ratio: float = 1.0,
    carry_roll_sell_ts: Optional[pd.Series] = None,
) -> Dict[str, Any]:
    """Trend/carry backtest using directional-change trend confirmation."""
    if spread_ts is None or len(spread_ts) < 60:
        return {'error': 'Insufficient data'}

    s = pd.to_numeric(spread_ts, errors='coerce').dropna().copy()
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.to_datetime(s.index)
    if len(s) < max(60, vol_window + 5, mom_window + 5):
        return {'error': 'Insufficient data'}

    trend_state = _dc_trend_state(s, theta=float(theta)).reindex(s.index).ffill().fillna(0.0)
    mom = s.diff(mom_window)
    sigma = s.diff().rolling(vol_window).std()
    norm_mom = mom / sigma.replace(0, np.nan)

    # Pre-align carry series to spread index once — avoids O(n²) re-slicing in the loop.
    def _align_cr_trend(ts):
        if ts is None:
            return None
        t = ts.copy()
        if hasattr(t.index, 'tz') and t.index.tz is not None:
            t.index = t.index.tz_localize(None)
        return t.reindex(s.index, method='ffill')

    _cr_long_al = _align_cr_trend(carry_roll_ts)
    _cr_sell_al = _align_cr_trend(carry_roll_sell_ts)

    def _cr_val_trend(i: int, pos: int) -> float:
        ts = _cr_sell_al if (pos == -1 and _cr_sell_al is not None) else _cr_long_al
        if ts is None:
            return 0.0
        v = ts.iloc[i]
        return float(v) if np.isfinite(v) else 0.0

    trades: List[Dict[str, Any]] = []
    position = 0
    entry_date = None
    entry_price = None
    best_fav = None
    realized_pnl = 0.0
    realized_capital = 0.0
    realized_carry = 0.0
    open_cr_sum = 0.0
    equity_dates: List[pd.Timestamp] = []
    equity_values: List[float] = []
    capital_values: List[float] = []
    carry_values: List[float] = []

    start_i = max(vol_window, mom_window) + 1
    for i in range(start_i, len(s)):
        date = s.index[i]
        px = float(s.iloc[i])
        st = float(trend_state.iloc[i])
        m = float(norm_mom.iloc[i]) if not np.isnan(norm_mom.iloc[i]) else 0.0
        vol = float(sigma.iloc[i]) if not np.isnan(sigma.iloc[i]) else np.nan

        if position != 0:
            days_held = (date - entry_date).days if entry_date is not None else 0

            if best_fav is None:
                best_fav = px
            if position == 1:
                best_fav = max(best_fav, px)
            else:
                best_fav = min(best_fav, px)

            trailing_stop = False
            if not np.isnan(vol) and vol > 0 and trailing_mult > 0:
                if position == 1:
                    trailing_stop = (best_fav - px) >= trailing_mult * vol
                else:
                    trailing_stop = (px - best_fav) >= trailing_mult * vol

            carry_bad = False
            if position == 1:
                carry_bad = px < carry_buffer
            else:
                carry_bad = px > -carry_buffer

            flip = (position == 1 and st < 0) or (position == -1 and st > 0)
            time_stop = days_held >= max_hold

            if trailing_stop or carry_bad or flip or time_stop:
                price_pnl = (px - entry_price) * position * duration_mult
                carry_income = _carry_accrual(
                    position, entry_date, date, days_held,
                    carry_roll_ts, carry_roll_bp,
                    borrow_cost_long_bp, borrow_cost_short_bp,
                    spread_type, tenor_ratio,
                    carry_roll_sell_ts,
                )
                pnl = price_pnl + carry_income
                realized_pnl += pnl
                realized_capital += price_pnl * 100.0
                realized_carry += carry_income * 100.0
                open_cr_sum = 0.0
                trades.append({
                    'entry_date': entry_date,
                    'exit_date': date,
                    'direction': 'LONG' if position == 1 else 'SHORT',
                    'entry_price': entry_price,
                    'exit_price': px,
                    'spd_chg': (px - entry_price) * position * 100.0,
                    'cr_acc': carry_income * 100.0,
                    'duration': duration_mult,
                    'days_held': days_held,
                    'exit_reason': 'trailing' if trailing_stop else ('carry' if carry_bad else ('flip' if flip else 'max_hold')),
                })
                position = 0
                entry_date = None
                entry_price = None
                best_fav = None

        if position == 0:
            mom_ok = (st > 0 and m >= 0.5) or (st < 0 and m <= -0.5)
            if st > 0 and mom_ok and px >= carry_buffer:
                position = 1
                entry_date = date
                entry_price = px
                best_fav = px
            elif allow_short and st < 0 and mom_ok:
                position = -1
                entry_date = date
                entry_price = px
                best_fav = px

        if position != 0 and entry_price is not None:
            open_cr_sum += _cr_val_trend(i, position)
            open_carry_pct = position * open_cr_sum / 90.0
            if spread_type not in ('TenorSpread', 'BondCurve', 'BondSwap', 'TBondCurve', 'CBondCurve', 'TBondSwap', 'CBondSwap'):
                bc = borrow_cost_long_bp if position == 1 else borrow_cost_short_bp
                days_open = (date - entry_date).days if entry_date else 0
                open_carry_pct -= abs(bc) / 100.0 * days_open / 365.0
            open_cap_pct = (px - entry_price) * position * duration_mult
            mtm = realized_pnl + open_cap_pct + open_carry_pct
            cap_daily = realized_capital + open_cap_pct * 100.0
            cr_daily = realized_carry + open_carry_pct * 100.0
        else:
            mtm = realized_pnl
            cap_daily = realized_capital
            cr_daily = realized_carry
        equity_dates.append(pd.Timestamp(date))
        equity_values.append(float(mtm))
        capital_values.append(float(cap_daily))
        carry_values.append(float(cr_daily))

    equity_ts = pd.Series(equity_values, index=pd.DatetimeIndex(equity_dates), name='equity_bp')

    open_trade = None
    if position != 0 and entry_price is not None and equity_dates:
        last_date = equity_dates[-1]
        last_price = float(s.loc[last_date])
        days_open = (last_date - entry_date).days if entry_date else 0
        open_cap_bp = (last_price - entry_price) * position * duration_mult * 100.0
        open_carry_bp = open_cr_sum * position / 90.0 * 100.0
        open_trade = {
            'entry_date': entry_date,
            'direction': 'LONG' if position == 1 else 'SHORT',
            'entry_price': entry_price,
            'current_date': last_date,
            'current_price': last_price,
            'days_held': days_open,
            'capital_open': open_cap_bp,
            'carry_open': open_carry_bp,
            'pnl_open': open_cap_bp + open_carry_bp,
            'status': 'OPEN',
        }

    if not trades and open_trade is None:
        return {
            'trades': [],
            'trades_df': pd.DataFrame(),
            'n_trades': 0,
            'total_pnl': 0.0,
            'win_rate': 0.0,
            'avg_pnl': 0.0,
            'avg_hold': 0.0,
            'sharpe': 0.0,
            'max_drawdown': 0.0,
            'spread_ts': s,
            'trend_state_ts': trend_state,
            'norm_mom_ts': norm_mom,
            'cum_pnl': np.array([]),
            'equity_ts': equity_ts,
            'carry_roll_ts': carry_roll_ts,
            'open_trade': None,
        }

    trades_df = pd.DataFrame(trades)
    if not trades_df.empty:
        trades_df['spd_chg'] = trades_df['spd_chg'].astype(float)
        trades_df['cr_acc'] = trades_df['cr_acc'].astype(float)
        trades_df['duration'] = trades_df['duration'].astype(float)
        # pnl_trade = duration * spd_chg + cr_acc  (all in bp)
        trades_df['pnl_trade'] = trades_df['duration'] * trades_df['spd_chg'] + trades_df['cr_acc']
        trades_df['capital_cum'] = (trades_df['duration'] * trades_df['spd_chg']).cumsum()
        trades_df['carry_cum'] = trades_df['cr_acc'].cumsum()
        trades_df['pnl_cum'] = trades_df['pnl_trade'].cumsum()
    pnls = trades_df['pnl_trade'].values if not trades_df.empty else np.array([])
    n_trades = int(len(trades_df))
    total_pnl = float(np.nansum(pnls)) if pnls.size > 0 else 0.0
    win_rate = float((pnls > 0).sum() / n_trades * 100.0) if n_trades > 0 else 0.0
    avg_pnl = float(np.nanmean(pnls)) if pnls.size > 0 else 0.0
    avg_hold = float(trades_df['days_held'].mean()) if 'days_held' in trades_df.columns else 0.0
    sharpe = float((np.nanmean(pnls) / np.nanstd(pnls)) * np.sqrt(min(n_trades, 20))) if (pnls.size > 0 and np.nanstd(pnls) > 0) else 0.0

    cum_pnl = np.nancumsum(pnls) if pnls.size > 0 else np.array([])
    trades_out = trades_df.to_dict('records') if not trades_df.empty else []

    equity_ts = equity_ts * 100.0
    capital_ts = pd.Series(capital_values, index=pd.DatetimeIndex(equity_dates), name='capital_bp')
    carry_ts   = pd.Series(carry_values,   index=pd.DatetimeIndex(equity_dates), name='carry_bp')

    # Max drawdown from daily equity curve (captures intra-trade peaks/troughs)
    eq_vals = equity_ts.dropna().values
    if len(eq_vals) > 0:
        running_max = np.maximum.accumulate(eq_vals)
        max_drawdown = float((running_max - eq_vals).max())
    else:
        max_drawdown = 0.0

    return {
        'trades': trades_out,
        'trades_df': trades_df,
        'n_trades': n_trades,
        'total_pnl': total_pnl,
        'win_rate': win_rate,
        'avg_pnl': avg_pnl,
        'avg_hold': avg_hold,
        'sharpe': sharpe,
        'max_drawdown': max_drawdown,
        'spread_ts': s,
        'trend_state_ts': trend_state,
        'norm_mom_ts': norm_mom,
        'cum_pnl': cum_pnl,
        'equity_ts': equity_ts,
        'capital_ts': capital_ts,
        'carry_ts': carry_ts,
        'carry_roll_ts': carry_roll_ts,
        'open_trade': open_trade,
    }
