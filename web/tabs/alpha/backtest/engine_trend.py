# -*- coding: utf-8 -*-
"""Trend / carry backtest engine using z-momentum hysteresis trend confirmation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ._carry import _carry_accrual
from ._metrics import annualized_sharpe, per_trade_sharpe


def _robust_daily_scale(diff_s: pd.Series, window: int) -> pd.Series:
    """EWMA(span=window) scale of daily changes (same units as diff_s).

    Matches the ewm_vol convention used for spread-level Zscore elsewhere
    (OU_calibrate / alpha_snapshot.py / alpha_scoring.py's momentum zscore),
    so the trend backtest engine's entry-signal scale is consistent with the
    live Candidates scanner's momentum Zscore for the same instrument.
    """
    d = pd.to_numeric(diff_s, errors='coerce')
    span = max(int(window), 2)
    return d.ewm(span=span, min_periods=min(span, max(d.dropna().shape[0], 2))).std()


def _z_momentum_state(
    series: pd.Series,
    *,
    theta_z: float = 1.25,
    mom_window: int = 20,
    vol_window: int = 60,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Compute hysteresis trend state from z-scored medium-horizon momentum.

    Returns:
        trend_state: +1 / -1 / 0 state series
        z_mom: z-scored momentum series
        sigma_ewm: rolling EWMA volatility scale used for normalization
    """
    s = pd.to_numeric(series, errors='coerce').dropna().copy()
    if s.empty:
        empty = pd.Series(dtype=float)
        return empty, empty, empty

    k = max(int(mom_window), 1)
    w = max(int(vol_window), 20)
    z_thr = abs(float(theta_z)) if np.isfinite(theta_z) else 1.25

    momentum = s.diff(k)
    sigma_ewm = _robust_daily_scale(momentum, w)
    z_mom = momentum / sigma_ewm.replace(0, np.nan)
    z_mom = z_mom.replace([np.inf, -np.inf], np.nan)

    raw = pd.Series(np.nan, index=s.index, dtype=float)
    raw[z_mom >= z_thr] = 1.0
    raw[z_mom <= -z_thr] = -1.0
    state = raw.ffill().fillna(0.0)
    state.name = 'trend_state'
    z_mom.name = 'z_mom'
    sigma_ewm.name = 'sigma_ewm'
    return state, z_mom, sigma_ewm


def run_trend_backtest(
    spread_ts: pd.Series,
    theta_z: float = 1.25,
    mom_window: int = 20,
    vol_window: int = 60,
    trailing_mult: float = 1.5,
    allow_short: bool = True,
    carry_roll_ts: Optional[pd.Series] = None,
    carry_roll_bp: float = 0.0,
    duration_mult: float = 1.0,
    borrow_cost_long_bp: float = 0.0,
    borrow_cost_short_bp: float = 0.0,
    spread_type: Optional[str] = None,
    tenor_ratio: float = 1.0,
    carry_roll_sell_ts: Optional[pd.Series] = None,
    min_hold: int = 7,
    reentry_cooldown: int = 3,
) -> Dict[str, Any]:
    """Trend/carry backtest using z-momentum hysteresis trend confirmation."""
    if spread_ts is None or len(spread_ts) < 60:
        return {'error': 'Insufficient data'}

    s = pd.to_numeric(spread_ts, errors='coerce').dropna().copy()
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.to_datetime(s.index)
    if len(s) < max(60, vol_window + 5, mom_window + 5):
        return {'error': 'Insufficient data'}

    trend_state, z_mom, sigma_ewm = _z_momentum_state(
        s,
        theta_z=float(theta_z),
        mom_window=int(mom_window),
        vol_window=int(vol_window),
    )
    trend_state = trend_state.reindex(s.index).ffill().fillna(0.0)
    z_mom = z_mom.reindex(s.index)
    sigma = s.diff().rolling(vol_window).std()

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

    # Numpy views of the per-day series used inside the trade loop — plain array
    # indexing avoids per-step pandas .iloc overhead over long histories.
    s_arr = s.to_numpy(dtype=float)
    idx_arr = s.index
    trend_arr = trend_state.to_numpy(dtype=float)
    sigma_arr = sigma.to_numpy(dtype=float)
    _cr_long_arr = _cr_long_al.to_numpy(dtype=float) if _cr_long_al is not None else None
    _cr_sell_arr = _cr_sell_al.to_numpy(dtype=float) if _cr_sell_al is not None else None

    def _cr_val_trend(i: int, pos: int) -> float:
        arr = _cr_sell_arr if (pos == -1 and _cr_sell_arr is not None) else _cr_long_arr
        if arr is None:
            return 0.0
        v = arr[i]
        return float(v) if np.isfinite(v) else 0.0

    trades: List[Dict[str, Any]] = []
    position = 0
    entry_date = None
    entry_price = None
    best_fav = None
    cooldown = max(int(reentry_cooldown), 0)
    last_exit_index = -10**9
    last_exit_dir = 0
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
        date = idx_arr[i]
        px = float(s_arr[i])
        st = float(trend_arr[i])
        vol = float(sigma_arr[i])

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

            flip = (position == 1 and st < 0) or (position == -1 and st > 0)

            # Trailing stop always fires; signal-based exits (trend flip) respect min_hold.
            signal_exit = days_held >= min_hold and flip
            if trailing_stop or signal_exit:
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
                    'exit_reason': 'trailing' if trailing_stop else 'flip',
                })
                last_exit_index = i
                last_exit_dir = position
                position = 0
                entry_date = None
                entry_price = None
                best_fav = None

        if position == 0:
            can_reenter_long = not (last_exit_dir == 1 and (i - last_exit_index) <= cooldown)
            can_reenter_short = not (last_exit_dir == -1 and (i - last_exit_index) <= cooldown)
            if st > 0 and can_reenter_long:
                position = 1
                entry_date = date
                entry_price = px
                best_fav = px
            elif allow_short and st < 0 and can_reenter_short:
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
        last_price = float(s_arr[-1])
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
            'sharpe_per_trade': 0.0,
            'max_drawdown': 0.0,
            'spread_ts': s,
            'trend_state_ts': trend_state,
            'norm_mom_ts': z_mom,
            'theta_z': float(theta_z),
            'reentry_cooldown': cooldown,
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
    sharpe_pt = per_trade_sharpe(pnls, n_trades)

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
        'sharpe': annualized_sharpe(equity_ts),
        'sharpe_per_trade': sharpe_pt,
        'max_drawdown': max_drawdown,
        'spread_ts': s,
        'trend_state_ts': trend_state,
        'norm_mom_ts': z_mom,
        'theta_z': float(theta_z),
        'reentry_cooldown': cooldown,
        'cum_pnl': cum_pnl,
        'equity_ts': equity_ts,
        'capital_ts': capital_ts,
        'carry_ts': carry_ts,
        'carry_roll_ts': carry_roll_ts,
        'open_trade': open_trade,
    }


def _dc_trend_state(series: pd.Series, theta: float, theta_ts: Optional[pd.Series] = None) -> pd.Series:
    """Deprecated compatibility wrapper.

    Keeps legacy callers/tests alive while routing to the new z-momentum state.
    ``theta_ts`` is ignored and retained only for call compatibility.
    """
    _ = theta_ts
    st, _, _ = _z_momentum_state(
        series,
        theta_z=float(theta) if np.isfinite(theta) else 1.25,
        mom_window=1,
        vol_window=20,
    )
    return st


def run_trend_backtest_dc(
    spread_ts: pd.Series,
    theta: float = 1.25,
    mom_window: int = 20,
    vol_window: int = 60,
    trailing_mult: float = 1.5,
    carry_buffer: float = 0.0,
    allow_short: bool = True,
    carry_roll_ts: Optional[pd.Series] = None,
    carry_roll_bp: float = 0.0,
    duration_mult: float = 1.0,
    borrow_cost_long_bp: float = 0.0,
    borrow_cost_short_bp: float = 0.0,
    spread_type: Optional[str] = None,
    tenor_ratio: float = 1.0,
    carry_roll_sell_ts: Optional[pd.Series] = None,
    min_hold: int = 7,
    adaptive_theta: bool = True,
    theta_min_mult: float = 0.5,
    theta_max_mult: float = 2.5,
) -> Dict[str, Any]:
    """Compatibility wrapper for legacy callers.

    Parameters tied to the old DC implementation are accepted but ignored.
    """
    _ = carry_buffer
    _ = adaptive_theta
    _ = theta_min_mult
    _ = theta_max_mult

    # Legacy callers pass DC spread-unit thresholds (typically 0.02/0.03).
    # Map those to practical z-threshold defaults during migration.
    theta_legacy = float(theta) if np.isfinite(theta) else 1.25
    if theta_legacy < 0.2:
        theta_legacy = 1.5 if theta_legacy >= 0.03 else 1.25

    return run_trend_backtest(
        spread_ts=spread_ts,
        theta_z=theta_legacy,
        mom_window=mom_window,
        vol_window=vol_window,
        trailing_mult=trailing_mult,
        allow_short=allow_short,
        carry_roll_ts=carry_roll_ts,
        carry_roll_bp=carry_roll_bp,
        duration_mult=duration_mult,
        borrow_cost_long_bp=borrow_cost_long_bp,
        borrow_cost_short_bp=borrow_cost_short_bp,
        spread_type=spread_type,
        tenor_ratio=tenor_ratio,
        carry_roll_sell_ts=carry_roll_sell_ts,
        min_hold=min_hold,
    )
