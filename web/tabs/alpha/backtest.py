# -*- coding: utf-8 -*-
"""Backtest engine and results display for the Alpha Book tabs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from dash import dcc, html, dash_table

from .data import THEME


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
    # Select the correct timeseries based on position
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
            # borrow_cost is in bp; divide by 100 to convert to % (same unit as carry_income)
            carry_income -= abs(borrow_cost) / 100.0 * days_held / 365.0

    return carry_income


def run_spread_backtest(
    spread_ts: pd.Series,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
    stop_z: float = 4.0,
    max_hold: int = 60,
    trade_style: str = 'mr',
    carry_roll_ts: Optional[pd.Series] = None,
    carry_roll_bp: float = 0.0,
    duration_mult: float = 1.0,
    borrow_cost_long_bp: float = 0.0,
    borrow_cost_short_bp: float = 0.0,
    spread_type: Optional[str] = None,
    tenor_ratio: float = 1.0,
    carry_roll_sell_ts: Optional[pd.Series] = None,
) -> Dict[str, Any]:
    """Run backtest on a single spread time series."""
    if spread_ts is None or len(spread_ts) < 130:
        return {'error': 'Insufficient data'}

    spread_ts = spread_ts.dropna()

    if not isinstance(spread_ts.index, pd.DatetimeIndex):
        spread_ts = spread_ts.copy()
        spread_ts.index = pd.to_datetime(spread_ts.index)

    lookback = 120
    rolling_mean = spread_ts.rolling(lookback).mean()
    rolling_std = spread_ts.rolling(lookback).std()
    zscore = (spread_ts - rolling_mean) / rolling_std

    _score_horizon = 30
    try:
        _cr_fallback = carry_roll_bp if np.isfinite(carry_roll_bp) else 0.0
        _cr_aligned = pd.Series(_cr_fallback, index=spread_ts.index, dtype=float)
        if carry_roll_ts is not None and len(carry_roll_ts) > 0:
            _ts_cr = carry_roll_ts.copy()
            if hasattr(_ts_cr.index, 'tz') and _ts_cr.index.tz is not None:
                _ts_cr.index = _ts_cr.index.tz_localize(None)
            _cr_aligned = _ts_cr.reindex(spread_ts.index, method='ffill').fillna(_cr_fallback)
        _safe_std = rolling_std.replace(0, np.nan).fillna(1.0)
        carry_sigma_ts = (_cr_aligned * _score_horizon / 90.0) / _safe_std
        carry_sigma_ts = carry_sigma_ts.clip(-1.5, 1.5)
        composite_signal = zscore - carry_sigma_ts
    except Exception:
        composite_signal = zscore.copy()

    # Pre-align carry series to spread index once — avoids O(n²) re-slicing in the loop.
    _cr_fallback_val = (carry_roll_bp or 0.0) / 100.0  # convert bp scalar to %
    def _align_cr(ts):
        if ts is None:
            return None
        t = ts.copy()
        if hasattr(t.index, 'tz') and t.index.tz is not None:
            t.index = t.index.tz_localize(None)
        return t.reindex(spread_ts.index, method='ffill')

    _cr_long_aligned = _align_cr(carry_roll_ts)
    _cr_sell_aligned = _align_cr(carry_roll_sell_ts)

    def _cr_val_at(i: int, pos: int) -> float:
        ts = _cr_sell_aligned if (pos == -1 and _cr_sell_aligned is not None) else _cr_long_aligned
        if ts is None:
            return _cr_fallback_val
        v = ts.iloc[i]
        return float(v) if np.isfinite(v) else 0.0

    trades = []
    position = 0
    entry_date = None
    entry_price = None
    entry_zscore = None
    realized_pnl = 0.0
    realized_capital = 0.0   # bp: closed-trade capital component
    realized_carry = 0.0     # bp: closed-trade carry component
    open_cr_sum = 0.0        # running sum of daily cr values for the open trade (in %)
    equity_dates: List[pd.Timestamp] = []
    equity_values: List[float] = []
    capital_values: List[float] = []
    carry_values: List[float] = []

    for i in range(lookback, len(spread_ts)):
        date = spread_ts.index[i]
        price = spread_ts.iloc[i]
        z = zscore.iloc[i]

        cs_raw = composite_signal.iloc[i]
        cs = cs_raw if np.isfinite(cs_raw) else z

        if np.isnan(z):
            continue

        if position != 0:
            days_held = (date - entry_date).days if entry_date else 0

            exit_signal = False
            exit_reason = None

            if position == 1 and cs >= -exit_z:
                exit_signal = True
                exit_reason = 'target'
            elif position == -1 and cs <= exit_z:
                exit_signal = True
                exit_reason = 'target'

            if not exit_signal:
                if position == 1 and z < -stop_z:
                    exit_signal = True
                    exit_reason = 'stop_loss'
                elif position == -1 and z > stop_z:
                    exit_signal = True
                    exit_reason = 'stop_loss'

            if days_held >= max_hold:
                exit_signal = True
                if exit_reason is None:
                    exit_reason = 'max_hold'

            if exit_signal:
                price_pnl = (price - entry_price) * position * duration_mult
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
                    'exit_price': price,
                    'entry_z': entry_zscore,
                    'exit_z': z,
                    'spd_chg': (price - entry_price) * position * 100.0,
                    'cr_acc': carry_income * 100.0,
                    'duration': duration_mult,
                    'days_held': days_held,
                    'exit_reason': exit_reason,
                })
                position = 0
                entry_date = None
                entry_price = None
                entry_zscore = None

        if position == 0:
            if trade_style == 'mr':
                if cs <= -entry_z:
                    position = 1
                    entry_date = date
                    entry_price = price
                    entry_zscore = cs
                elif cs >= entry_z:
                    position = -1
                    entry_date = date
                    entry_price = price
                    entry_zscore = cs
            else:
                if cs <= -entry_z:
                    position = 1
                    entry_date = date
                    entry_price = price
                    entry_zscore = cs
                elif cs >= entry_z:
                    position = -1
                    entry_date = date
                    entry_price = price
                    entry_zscore = cs

        # Incremental daily MTM — O(n) total, no per-day _carry_accrual call.
        if position != 0 and entry_price is not None:
            open_cr_sum += _cr_val_at(i, position)
            open_carry_pct = position * open_cr_sum / 90.0
            # Borrow cost for types where it is not already embedded in the ts
            if spread_type not in ('TenorSpread', 'BondCurve', 'BondSwap', 'TBondCurve', 'CBondCurve', 'TBondSwap', 'CBondSwap'):
                bc = borrow_cost_long_bp if position == 1 else borrow_cost_short_bp
                days_open = (date - entry_date).days if entry_date else 0
                open_carry_pct -= abs(bc) / 100.0 * days_open / 365.0
            open_cap_pct = (price - entry_price) * position * duration_mult
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

    if not trades:
        return {
            'trades': [],
            'n_trades': 0,
            'total_pnl': 0,
            'win_rate': 0,
            'avg_pnl': 0,
            'avg_hold': 0,
            'sharpe': 0,
            'max_drawdown': 0,
            'spread_ts': spread_ts,
            'zscore_ts': zscore,
            'composite_signal_ts': composite_signal,
            'equity_ts': equity_ts,
            'carry_roll_ts': carry_roll_ts,
            'entry_z': entry_z,
            'exit_z': exit_z,
            'stop_z': stop_z,
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

    n_trades = len(trades)
    total_pnl = pnls.sum()
    win_rate = (pnls > 0).sum() / n_trades * 100
    avg_pnl = pnls.mean()
    avg_hold = trades_df['days_held'].mean()

    if pnls.std() > 0:
        sharpe = (pnls.mean() / pnls.std()) * np.sqrt(min(n_trades, 20))
    else:
        sharpe = 0

    cum_pnl = np.cumsum(pnls)
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
        'spread_ts': spread_ts,
        'zscore_ts': zscore,
        'composite_signal_ts': composite_signal,
        'cum_pnl': cum_pnl,
        'equity_ts': equity_ts,
        'capital_ts': capital_ts,
        'carry_ts': carry_ts,
        'carry_roll_ts': carry_roll_ts,
        'entry_z': entry_z,
        'exit_z': exit_z,
        'stop_z': stop_z,
    }


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
            elif allow_short and st < 0 and mom_ok and px <= -carry_buffer:
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

    if not trades:
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
    }


def build_backtest_results_display(results: Dict[str, Any], title: str = "Backtest Results") -> html.Div:
    """Build the display for backtest results."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    if 'error' in results:
        return html.Div(f"Error: {results['error']}", style={'color': THEME['warning'], 'padding': '20px'})

    if results['n_trades'] == 0:
        return html.Div("No trades generated with current parameters.", style={'color': THEME['warning'], 'padding': '20px'})

    metrics_div = html.Div([
        html.H6(title, style={'color': THEME['text_main'], 'marginBottom': '15px'}),
        html.Div([
            html.Div([html.Strong("Total Trades: ", style={'color': THEME['text_sub']}), html.Span(f"{results['n_trades']}", style={'color': THEME['text_main']})], style={'marginRight': '25px'}),
            html.Div([html.Strong("Win Rate: ", style={'color': THEME['text_sub']}), html.Span(f"{results['win_rate']:.1f}%", style={'color': THEME['success'] if results['win_rate'] > 50 else THEME['danger']})], style={'marginRight': '25px'}),
            html.Div([html.Strong("Total PnL: ", style={'color': THEME['text_sub']}), html.Span(f"{results['total_pnl']:.1f} bp", style={'color': THEME['success'] if results['total_pnl'] > 0 else THEME['danger']})], style={'marginRight': '25px'}),
            html.Div([html.Strong("Avg PnL: ", style={'color': THEME['text_sub']}), html.Span(f"{results['avg_pnl']:.2f} bp", style={'color': THEME['text_main']})], style={'marginRight': '25px'}),
            html.Div([html.Strong("Avg Hold: ", style={'color': THEME['text_sub']}), html.Span(f"{results['avg_hold']:.0f} days", style={'color': THEME['text_main']})], style={'marginRight': '25px'}),
            html.Div([html.Strong("Sharpe: ", style={'color': THEME['text_sub']}), html.Span(f"{results['sharpe']:.2f}", style={'color': THEME['success'] if results['sharpe'] > 1 else THEME['text_main']})], style={'marginRight': '25px'}),
            html.Div([html.Strong("Max DD: ", style={'color': THEME['text_sub']}), html.Span(f"{results['max_drawdown']:.1f} bp", style={'color': THEME['danger']})]),
        ], style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '10px', 'marginBottom': '20px'}),
    ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px', 'marginBottom': '15px'})

    is_trend = 'trend_state_ts' in results
    trades_df = results.get('trades_df')

    _score_raw = results.get('norm_mom_ts') if is_trend else results.get('zscore_ts')
    _equity_raw = results.get('equity_ts')
    x_start = None
    if _score_raw is not None and len(_score_raw.dropna()) > 0:
        x_start = _score_raw.dropna().index[0]
    elif isinstance(_equity_raw, pd.Series) and len(_equity_raw.dropna()) > 0:
        x_start = _equity_raw.dropna().index[0]

    x_end = None
    _last_src = _score_raw if _score_raw is not None else _equity_raw
    if _last_src is not None and len(_last_src.dropna()) > 0:
        x_end = _last_src.dropna().index[-1]

    if x_start is not None:
        x_start = pd.Timestamp(x_start)
    if x_end is not None:
        x_end = pd.Timestamp(x_end)

    _xaxis_range = dict(range=[x_start, x_end]) if x_start is not None else {}

    _cr_ts = results.get('carry_roll_ts')
    _cr_sell_ts = results.get('carry_roll_sell_ts')
    _has_cr = _cr_ts is not None or _cr_sell_ts is not None

    # Use 2-row subplot when carry+roll data exists so the CR panel has its own
    # independent y-axis and doesn't visually overlap the spread line.
    if _has_cr:
        instrument_fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True,
            row_heights=[0.68, 0.32], vertical_spacing=0.06,
        )
    else:
        instrument_fig = go.Figure()

    def _add_to_fig(trace, row=None):
        if _has_cr:
            instrument_fig.add_trace(trace, row=row, col=1)
        else:
            instrument_fig.add_trace(trace)

    if 'spread_ts' in results and results['spread_ts'] is not None:
        spread_ts = results['spread_ts'].dropna()
        if x_start is not None:
            spread_ts = spread_ts.loc[spread_ts.index >= x_start]
        if len(spread_ts) > 0:
            spread_ts_bp = spread_ts * 100.0
            _add_to_fig(go.Scatter(
                x=spread_ts_bp.index, y=spread_ts_bp.values,
                mode='lines', name='Spread (bp)',
                line=dict(color=THEME['accent'], width=1.5),
                showlegend=False,
            ), row=1)

    if trades_df is not None and len(trades_df) > 0:
        long_entries = trades_df[trades_df['direction'] == 'LONG']
        short_entries = trades_df[trades_df['direction'] == 'SHORT']
        # Color exits by actual P&L sign so trend exits (flip/max_hold/trailing)
        # are not all shown as losses when they may be profitable.
        _pnl_col = trades_df.get('pnl_trade', pd.Series(0.0, index=trades_df.index))
        profit_exits = trades_df[_pnl_col > 0]
        loss_exits = trades_df[_pnl_col <= 0]
        if len(long_entries) > 0:
            _add_to_fig(go.Scatter(x=long_entries['entry_date'], y=long_entries['entry_price'] * 100.0, mode='markers', name='Long Entry', marker=dict(symbol='triangle-up', size=10, color=THEME['success'], line=dict(width=1, color='white')), showlegend=True), row=1)
        if len(short_entries) > 0:
            _add_to_fig(go.Scatter(x=short_entries['entry_date'], y=short_entries['entry_price'] * 100.0, mode='markers', name='Short Entry', marker=dict(symbol='triangle-down', size=10, color=THEME['danger'], line=dict(width=1, color='white')), showlegend=True), row=1)
        if len(profit_exits) > 0:
            _add_to_fig(go.Scatter(x=profit_exits['exit_date'], y=profit_exits['exit_price'] * 100.0, mode='markers', name='Exit (profit)', marker=dict(symbol='circle', size=7, color=THEME['success'], opacity=0.85), showlegend=True), row=1)
        if len(loss_exits) > 0:
            _add_to_fig(go.Scatter(x=loss_exits['exit_date'], y=loss_exits['exit_price'] * 100.0, mode='markers', name='Exit (loss)', marker=dict(symbol='x', size=9, color=THEME['danger'], opacity=0.85), showlegend=True), row=1)

    def _add_cr_trace(cr_ts, label, color, dash='dot'):
        if cr_ts is None or len(cr_ts) == 0:
            return
        cr_plot = cr_ts.copy()
        if not isinstance(cr_plot.index, pd.DatetimeIndex):
            cr_plot.index = pd.to_datetime(cr_plot.index)
        elif hasattr(cr_plot.index, 'tz') and cr_plot.index.tz is not None:
            cr_plot.index = cr_plot.index.tz_localize(None)
        if x_start is not None:
            cr_plot = cr_plot.loc[cr_plot.index >= x_start]
        if len(cr_plot) > 0:
            cr_plot_bp = cr_plot * 100.0
            _add_to_fig(go.Scatter(
                x=cr_plot_bp.index, y=cr_plot_bp.values,
                mode='lines', name=label,
                line=dict(color=color, width=1, dash=dash),
                showlegend=True,
            ), row=2)

    if _cr_sell_ts is not None:
        _add_cr_trace(_cr_ts, 'CR+Roll BUY (3m,bp)', 'rgba(0,204,150,0.85)')
        _add_cr_trace(_cr_sell_ts, 'CR+Roll SELL (3m,bp)', 'rgba(239,85,59,0.85)')
    elif _cr_ts is not None:
        _add_cr_trace(_cr_ts, 'Carry+Roll (3m, bp)', 'rgba(243,156,18,0.85)')

    # Zero reference line in the CR panel
    if _has_cr and x_start is not None and x_end is not None:
        instrument_fig.add_trace(go.Scatter(
            x=[x_start, x_end], y=[0, 0],
            mode='lines', name='Zero',
            line=dict(color='rgba(180,180,180,0.4)', width=1, dash='dot'),
            showlegend=False,
        ), row=2, col=1)

    _chart_height = 420 if _has_cr else 300
    _common_layout = dict(
        title='Instrument History', height=_chart_height,
        margin=dict(l=50, r=20, t=40, b=40),
        plot_bgcolor=THEME['bg_main'], paper_bgcolor=THEME['bg_main'],
        font=dict(color=THEME['text_main']),
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1, font=dict(size=10), bgcolor='rgba(0,0,0,0)'),
    )
    if _has_cr:
        instrument_fig.update_layout(
            **_common_layout,
            xaxis=dict(gridcolor=THEME['bg_card'], showticklabels=False, **_xaxis_range),
            xaxis2=dict(gridcolor=THEME['bg_card'], tickformat='%b\n%Y', hoverformat='%Y-%m-%d', **_xaxis_range),
            yaxis=dict(title='Spread (bp)', gridcolor=THEME['bg_card']),
            yaxis2=dict(title='CR+Roll 3m (bp)', gridcolor=THEME['bg_card']),
        )
    else:
        instrument_fig.update_layout(
            **_common_layout,
            xaxis=dict(gridcolor=THEME['bg_card'], tickformat='%b\n%Y', hoverformat='%Y-%m-%d', **_xaxis_range),
            yaxis=dict(title='Spread (bp)', gridcolor=THEME['bg_card']),
        )
    instrument_div = html.Div([dcc.Graph(figure=instrument_fig, style={'height': f'{_chart_height}px'})], style={'marginBottom': '15px'})

    score_div = html.Div()
    _composite = results.get('composite_signal_ts')
    _raw_score = results.get('norm_mom_ts') if is_trend else (_composite if _composite is not None else results.get('zscore_ts'))
    if _raw_score is not None and len(_raw_score.dropna()) > 0:
        score_ts_display = _raw_score.dropna()
        if is_trend:
            score_label = 'Norm Momentum (σ)'
        else:
            if _composite is not None:
                score_label = 'Composite Signal (Z - Carry) (120d)'
            else:
                score_label = 'Z-Score (120d)'

        signal_fig = go.Figure()

        if is_trend and 'trend_state_ts' in results and results['trend_state_ts'] is not None:
            _tst = results['trend_state_ts'].reindex(score_ts_display.index).ffill().fillna(0.0)
            signal_fig.add_trace(go.Scatter(
                x=score_ts_display.index, y=(_tst * 2.0).values,
                mode='lines', name='Trend State (×2)',
                line=dict(color='rgba(255,165,0,0.45)', width=1, shape='hv'),
                fill='tozeroy', fillcolor='rgba(255,165,0,0.07)', showlegend=False,
            ))

        score_plot = score_ts_display.clip(-4, 4) if is_trend else score_ts_display
        signal_fig.add_trace(go.Scatter(x=score_plot.index, y=score_plot.values, mode='lines', name=score_label, line=dict(color=THEME['accent'], width=1.2), showlegend=False))
        signal_fig.add_hline(y=0, line_dash='dot', line_color=THEME['text_sub'])

        if is_trend:
            signal_fig.add_hline(y=0.5,  line_dash='dash', line_color='rgba(0,204,150,0.55)', annotation_text='+0.5σ entry')
            signal_fig.add_hline(y=-0.5, line_dash='dash', line_color='rgba(239,85,59,0.55)',  annotation_text='-0.5σ entry')
        else:
            _ez = float(results.get('entry_z', 2.0))
            _sz = float(results.get('stop_z', 4.0))
            _xz = float(results.get('exit_z', 0.5))
            signal_fig.add_hline(y=_ez,  line_dash='dash', line_color=THEME['danger'],              annotation_text=f'+{_ez}σ entry')
            signal_fig.add_hline(y=-_ez, line_dash='dash', line_color=THEME['success'],             annotation_text=f'-{_ez}σ entry')
            signal_fig.add_hline(y=_sz,  line_dash='dot',  line_color='rgba(239,85,59,0.5)',        annotation_text=f'+{_sz}σ stop')
            signal_fig.add_hline(y=-_sz, line_dash='dot',  line_color='rgba(239,85,59,0.5)',        annotation_text=f'-{_sz}σ stop')
            signal_fig.add_hline(y=_xz,  line_dash='dot',  line_color='rgba(0,204,150,0.4)',        annotation_text=f'+{_xz}σ exit')
            signal_fig.add_hline(y=-_xz, line_dash='dot',  line_color='rgba(0,204,150,0.4)',        annotation_text=f'-{_xz}σ exit')

        if trades_df is not None and len(trades_df) > 0:
            def _score_at(df, date_col):
                dates = pd.DatetimeIndex(pd.to_datetime(df[date_col]))
                return score_ts_display.clip(-4, 4).reindex(dates, method='nearest').values

            long_e  = trades_df[trades_df['direction'] == 'LONG']
            short_e = trades_df[trades_df['direction'] == 'SHORT']
            _pnl_score = trades_df.get('pnl_trade', pd.Series(0.0, index=trades_df.index))
            prof_x = trades_df[_pnl_score > 0]
            loss_x = trades_df[_pnl_score <= 0]

            if len(long_e) > 0:
                signal_fig.add_trace(go.Scatter(x=long_e['entry_date'], y=_score_at(long_e, 'entry_date'), mode='markers', marker=dict(symbol='triangle-up', size=9, color=THEME['success'], line=dict(width=1, color='white')), showlegend=False))
            if len(short_e) > 0:
                signal_fig.add_trace(go.Scatter(x=short_e['entry_date'], y=_score_at(short_e, 'entry_date'), mode='markers', marker=dict(symbol='triangle-down', size=9, color=THEME['danger'], line=dict(width=1, color='white')), showlegend=False))
            if len(prof_x) > 0:
                signal_fig.add_trace(go.Scatter(x=prof_x['exit_date'], y=_score_at(prof_x, 'exit_date'), mode='markers', marker=dict(symbol='circle', size=7, color=THEME['success'], opacity=0.8), showlegend=False))
            if len(loss_x) > 0:
                signal_fig.add_trace(go.Scatter(x=loss_x['exit_date'], y=_score_at(loss_x, 'exit_date'), mode='markers', marker=dict(symbol='x', size=8, color=THEME['danger'], opacity=0.8), showlegend=False))

        yaxis_label = 'Norm Mom (σ)' if is_trend else ('Composite Signal' if _composite is not None else 'Z-Score')
        signal_fig.update_layout(
            title=f'Score History ({score_label})', height=230,
            margin=dict(l=50, r=20, t=40, b=40),
            plot_bgcolor=THEME['bg_main'], paper_bgcolor=THEME['bg_main'],
            font=dict(color=THEME['text_main']),
            xaxis=dict(gridcolor=THEME['bg_card'], tickformat='%b\n%Y', hoverformat='%Y-%m-%d', **_xaxis_range),
            yaxis=dict(title=yaxis_label, gridcolor=THEME['bg_card']),
            showlegend=False,
        )
        score_div = html.Div([dcc.Graph(figure=signal_fig, style={'height': '230px'})], style={'marginBottom': '15px'})

    equity_fig = go.Figure()
    equity_ts  = results.get('equity_ts')
    capital_ts = results.get('capital_ts')
    carry_ts   = results.get('carry_ts')

    def _trim(ts):
        if not isinstance(ts, pd.Series) or len(ts.dropna()) == 0:
            return None
        if x_start is not None:
            ts = ts[ts.index >= x_start]
        return ts if len(ts) > 0 else None

    _eq  = _trim(equity_ts)
    _cap = _trim(capital_ts)
    _cr  = _trim(carry_ts)

    if _cap is not None and _cr is not None:
        # Daily breakdown: capital and carry as continuous daily series
        equity_fig.add_trace(go.Scatter(
            x=_cap.index, y=_cap.values,
            mode='lines', name='Capital G/L (Daily MtM)',
            line=dict(color=THEME['accent'], width=1.5, dash='dash'),
        ))
        equity_fig.add_trace(go.Scatter(
            x=_cr.index, y=_cr.values,
            mode='lines', name='Carry (Daily Accrual)',
            line=dict(color='rgba(243,156,18,0.85)', width=1.5, dash='dot'),
        ))
        if _eq is not None:
            equity_fig.add_trace(go.Scatter(
                x=_eq.index, y=_eq.values,
                mode='lines', name='Total PnL',
                line=dict(color=THEME['success'], width=2),
                fill='tozeroy', fillcolor='rgba(0, 204, 150, 0.06)',
            ))
        equity_fig.add_hline(y=0, line_dash='dot', line_color=THEME['text_sub'])
    elif _eq is not None:
        equity_fig.add_trace(go.Scatter(
            x=_eq.index, y=_eq.values,
            mode='lines', name='Cumulative PnL (Daily MtM)',
            line=dict(color=THEME['success'], width=2),
            fill='tozeroy', fillcolor='rgba(0, 204, 150, 0.08)',
        ))
        equity_fig.add_hline(y=0, line_dash='dot', line_color=THEME['text_sub'])

    equity_fig.update_layout(
        title='Cumulative PnL Breakdown (bp)', height=250,
        margin=dict(l=50, r=20, t=40, b=40),
        plot_bgcolor=THEME['bg_main'], paper_bgcolor=THEME['bg_main'],
        font=dict(color=THEME['text_main']),
        xaxis=dict(gridcolor=THEME['bg_card'], tickformat='%b\n%Y', hoverformat='%Y-%m-%d', **_xaxis_range),
        yaxis=dict(title='bp', gridcolor=THEME['bg_card']),
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1, font=dict(size=10), bgcolor='rgba(0,0,0,0)'),
    )
    equity_div = html.Div([dcc.Graph(figure=equity_fig, style={'height': '250px'})], style={'marginBottom': '15px'})

    trades_table = html.Div()
    if 'trades_df' in results and results['trades_df'] is not None and len(results['trades_df']) > 0:
        df = results['trades_df'].copy()
        df['entry_date'] = pd.to_datetime(df['entry_date']).dt.strftime('%Y-%m-%d')
        df['exit_date'] = pd.to_datetime(df['exit_date']).dt.strftime('%Y-%m-%d')
        # entry_price / exit_price: convert % → bp
        for col in ['entry_price', 'exit_price']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce') * 100.0
        # Round all numeric columns to 2 dp
        for col in ['entry_price', 'exit_price', 'spd_chg', 'cr_acc', 'pnl_trade', 'capital_cum', 'carry_cum', 'pnl_cum', 'entry_z', 'exit_z', 'duration']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').round(2)

        # Reorder columns for readability
        cols = list(df.columns)
        desired = ['entry_date', 'exit_date', 'direction', 'entry_price', 'exit_price',
                   'spd_chg', 'cr_acc', 'pnl_trade', 'capital_cum', 'carry_cum', 'pnl_cum',
                   'duration', 'days_held', 'exit_reason']
        new_cols = [c for c in desired if c in cols] + [c for c in cols if c not in desired]
        df = df.reindex(columns=new_cols)

        trades_table = html.Div([
            html.H6("Trade History (unit: bp)", style={'color': THEME['text_main'], 'marginBottom': '10px'}),
            dash_table.DataTable(
                columns=[{'name': c, 'id': c} for c in df.columns],
                data=df.to_dict('records'),
                style_table={'overflowX': 'auto', 'maxHeight': '250px', 'overflowY': 'auto'},
                style_header={'backgroundColor': THEME['table_header'], 'color': THEME['text_main'], 'fontWeight': 'bold'},
                style_cell={'backgroundColor': THEME['bg_card'], 'color': THEME['text_main'], 'fontSize': '11px', 'padding': '5px'},
                style_data_conditional=[
                    {'if': {'filter_query': '{pnl_trade} > 0'}, 'backgroundColor': 'rgba(0, 204, 150, 0.1)'},
                    {'if': {'filter_query': '{pnl_trade} < 0'}, 'backgroundColor': 'rgba(239, 85, 59, 0.1)'},
                ],
                page_size=10,
                sort_action='native',
            ),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px'})

    return html.Div([metrics_div, instrument_div, score_div, equity_div, trades_table])
