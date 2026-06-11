# -*- coding: utf-8 -*-
"""Mean-reversion backtest engine using z-score / composite signal entries."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ._carry import _carry_accrual


def run_spread_backtest(
    spread_ts: pd.Series,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
    stop_z: float = 4.0,
    min_hold: int = 7,
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
    realized_capital = 0.0
    realized_carry = 0.0
    open_cr_sum = 0.0
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

            # Only allow signal-based exits after the minimum holding period.
            if days_held >= min_hold:
                if position == 1 and cs >= -exit_z:
                    exit_signal = True
                    exit_reason = 'target'
                elif position == -1 and cs <= exit_z:
                    exit_signal = True
                    exit_reason = 'target'

            # Stop-loss always fires regardless of min_hold.
            if not exit_signal:
                if position == 1 and z < -stop_z:
                    exit_signal = True
                    exit_reason = 'stop_loss'
                elif position == -1 and z > stop_z:
                    exit_signal = True
                    exit_reason = 'stop_loss'

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

    open_trade = None
    if position != 0 and entry_price is not None and equity_dates:
        last_date = equity_dates[-1]
        last_price = float(spread_ts.loc[last_date])
        days_open = (last_date - entry_date).days if entry_date else 0
        open_cap_bp = (last_price - entry_price) * position * duration_mult * 100.0
        open_carry_bp = open_cr_sum * position / 90.0 * 100.0
        open_trade = {
            'entry_date': entry_date,
            'direction': 'LONG' if position == 1 else 'SHORT',
            'entry_price': entry_price,
            'entry_z': entry_zscore,
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

    n_trades = len(trades)
    total_pnl = pnls.sum()
    win_rate = (pnls > 0).sum() / n_trades * 100 if n_trades > 0 else 0
    avg_pnl = pnls.mean() if n_trades > 0 else 0
    avg_hold = trades_df['days_held'].mean() if not trades_df.empty else 0

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
        'open_trade': open_trade,
    }
