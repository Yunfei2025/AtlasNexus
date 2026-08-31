# -*- coding: utf-8 -*-
"""Regime-aware Alpha backtest that switches between MR and trend signals."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from curves.calibration.regime import compute_regime_features_series

from ._carry import _carry_accrual
from ._metrics import annualized_sharpe, per_trade_sharpe
from .engine_trend import _dc_trend_state


def _stabilize_regime_scores(
    scores: pd.Series,
    *,
    threshold: float = 0.5,
    persistence: int = 5,
) -> pd.Series:
    """Require persistent, high-confidence evidence before changing regime."""
    stable = pd.Series('uncertain', index=scores.index, dtype=object)
    current = 'uncertain'
    candidate = 'uncertain'
    candidate_days = 0
    exit_days = 0

    for date, score in scores.items():
        desired = (
            'trending' if score >= threshold
            else 'mean_reverting' if score <= -threshold
            else 'uncertain'
        )
        if desired == current:
            exit_days = 0
            candidate = 'uncertain'
            candidate_days = 0
        elif current != 'uncertain':
            # Require the same persistence to leave an active regime as to
            # enter one. This prevents one conflicted daily vote from
            # interrupting an otherwise established strategy allocation.
            exit_days += 1
            candidate = 'uncertain'
            candidate_days = 0
            if exit_days >= persistence:
                current = 'uncertain'
                exit_days = 0
        elif desired == 'uncertain':
            candidate = 'uncertain'
            candidate_days = 0
        elif desired == candidate:
            candidate_days += 1
        else:
            candidate = desired
            candidate_days = 1

        if candidate_days >= persistence:
            current = candidate
            candidate = 'uncertain'
            candidate_days = 0
            exit_days = 0
        stable.loc[date] = current

    stable.name = 'regime'
    return stable


def run_regime_hybrid_backtest(
    spread_ts: pd.Series,
    *,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
    stop_z: float = 4.0,
    theta: float = 0.02,
    mom_window: int = 20,
    vol_window: int = 60,
    trailing_mult: float = 1.5,
    carry_buffer: float = 0.0,
    allow_short: bool = True,
    min_hold: int = 7,
    regime_window: int = 60,
    regime_threshold: float = 0.5,
    regime_persistence: int = 5,
    carry_roll_ts: Optional[pd.Series] = None,
    carry_roll_bp: float = 0.0,
    duration_mult: float = 1.0,
    borrow_cost_long_bp: float = 0.0,
    borrow_cost_short_bp: float = 0.0,
    spread_type: Optional[str] = None,
    tenor_ratio: float = 1.0,
    carry_roll_sell_ts: Optional[pd.Series] = None,
) -> Dict[str, Any]:
    """Backtest MR and trend rules with a point-in-time, persistent regime gate."""
    if spread_ts is None or len(spread_ts) < max(130, regime_window + 5):
        return {'error': 'Insufficient data'}

    s = pd.to_numeric(spread_ts, errors='coerce').dropna().copy()
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.to_datetime(s.index)
    if len(s) < max(130, regime_window + 5, vol_window + 5, mom_window + 5):
        return {'error': 'Insufficient data'}

    rolling_mean = s.rolling(120).mean()
    rolling_std = s.rolling(120).std()
    zscore = (s - rolling_mean) / rolling_std.replace(0, np.nan)
    carry_sigma = pd.Series(0.0, index=s.index)
    if carry_roll_ts is not None and len(carry_roll_ts) > 0:
        carry_aligned = carry_roll_ts.reindex(s.index, method='ffill').fillna(0.0)
        carry_sigma = ((carry_aligned * 30.0 / 90.0) / rolling_std.replace(0, np.nan)).clip(-1.5, 1.5).fillna(0.0)
    composite_signal = zscore - carry_sigma

    trend_state = _dc_trend_state(s, theta=float(theta)).reindex(s.index).ffill().fillna(0.0)
    sigma = s.diff().rolling(vol_window).std()
    norm_mom = s.diff(mom_window) / sigma.replace(0, np.nan)

    regime_features = compute_regime_features_series(s, window=regime_window)
    regime_scores = regime_features['regime_score'].reindex(s.index).fillna(0.0)
    regime_ts = _stabilize_regime_scores(
        regime_scores,
        threshold=regime_threshold,
        persistence=regime_persistence,
    )

    def _align_carry(series: Optional[pd.Series]) -> Optional[pd.Series]:
        if series is None:
            return None
        aligned = series.copy()
        if getattr(aligned.index, 'tz', None) is not None:
            aligned.index = aligned.index.tz_localize(None)
        return aligned.reindex(s.index, method='ffill')

    carry_long = _align_carry(carry_roll_ts)
    carry_short = _align_carry(carry_roll_sell_ts)

    def _carry_value(index: int, position: int) -> float:
        series = carry_short if position == -1 and carry_short is not None else carry_long
        if series is None:
            return 0.0
        value = series.iloc[index]
        return float(value) if np.isfinite(value) else 0.0

    trades: List[Dict[str, Any]] = []
    position = 0
    active_style: Optional[str] = None
    entry_date = None
    entry_price = None
    entry_score = None
    best_fav = None
    open_carry_sum = 0.0
    realized_pnl = realized_capital = realized_carry = 0.0
    equity_dates: List[pd.Timestamp] = []
    equity_values: List[float] = []
    capital_values: List[float] = []
    carry_values: List[float] = []

    def _close_trade(date: pd.Timestamp, price: float, reason: str) -> None:
        nonlocal position, active_style, entry_date, entry_price, entry_score
        nonlocal best_fav, open_carry_sum, realized_pnl, realized_capital, realized_carry
        days_held = (date - entry_date).days if entry_date is not None else 0
        price_pnl = (price - entry_price) * position * duration_mult
        carry_income = _carry_accrual(
            position, entry_date, date, days_held,
            carry_roll_ts, carry_roll_bp, borrow_cost_long_bp, borrow_cost_short_bp,
            spread_type, tenor_ratio, carry_roll_sell_ts,
        )
        realized_pnl += price_pnl + carry_income
        realized_capital += price_pnl * 100.0
        realized_carry += carry_income * 100.0
        trades.append({
            'entry_date': entry_date,
            'exit_date': date,
            'direction': 'LONG' if position == 1 else 'SHORT',
            'entry_price': entry_price,
            'exit_price': price,
            'entry_z': entry_score if active_style == 'mean_reverting' else np.nan,
            'exit_z': zscore.loc[date] if active_style == 'mean_reverting' else np.nan,
            'strategy': active_style,
            'spd_chg': price_pnl * 100.0 / duration_mult if duration_mult else 0.0,
            'cr_acc': carry_income * 100.0,
            'duration': duration_mult,
            'days_held': days_held,
            'exit_reason': reason,
        })
        position = 0
        active_style = None
        entry_date = entry_price = entry_score = best_fav = None
        open_carry_sum = 0.0

    start = max(120, vol_window, mom_window, regime_window) + 1
    for index in range(start, len(s)):
        date = s.index[index]
        price = float(s.iloc[index])
        regime = regime_ts.iloc[index]
        switched = False

        if position != 0:
            if regime != active_style:
                _close_trade(date, price, 'regime_switch')
                switched = True
            else:
                days_held = (date - entry_date).days if entry_date is not None else 0
                if active_style == 'mean_reverting':
                    score = composite_signal.iloc[index]
                    exit_signal = days_held >= min_hold and (
                        (position == 1 and score >= -exit_z) or
                        (position == -1 and score <= exit_z)
                    )
                    stop = (position == 1 and zscore.iloc[index] < -stop_z) or (
                        position == -1 and zscore.iloc[index] > stop_z
                    )
                    if exit_signal or stop:
                        _close_trade(date, price, 'target' if exit_signal else 'stop_loss')
                else:
                    best_fav = max(best_fav, price) if position == 1 else min(best_fav, price)
                    vol = sigma.iloc[index]
                    trailing = np.isfinite(vol) and vol > 0 and (
                        (position == 1 and best_fav - price >= trailing_mult * vol) or
                        (position == -1 and price - best_fav >= trailing_mult * vol)
                    )
                    flip = (position == 1 and trend_state.iloc[index] < 0) or (
                        position == -1 and trend_state.iloc[index] > 0
                    )
                    carry_bad = (position == 1 and price < carry_buffer) or (
                        position == -1 and price > -carry_buffer
                    )
                    if trailing or (days_held >= min_hold and (flip or carry_bad)):
                        _close_trade(date, price, 'trailing' if trailing else ('flip' if flip else 'carry'))

        if position == 0 and not switched:
            if regime == 'mean_reverting':
                score = composite_signal.iloc[index]
                if np.isfinite(score) and score <= -entry_z:
                    position, active_style, entry_date, entry_price, entry_score, best_fav = 1, regime, date, price, score, price
                elif np.isfinite(score) and score >= entry_z and allow_short:
                    position, active_style, entry_date, entry_price, entry_score, best_fav = -1, regime, date, price, score, price
            elif regime == 'trending':
                state = trend_state.iloc[index]
                momentum = norm_mom.iloc[index]
                if state > 0 and np.isfinite(momentum) and momentum >= 0.5 and price >= carry_buffer:
                    position, active_style, entry_date, entry_price, entry_score, best_fav = 1, regime, date, price, momentum, price
                elif state < 0 and np.isfinite(momentum) and momentum <= -0.5 and allow_short:
                    position, active_style, entry_date, entry_price, entry_score, best_fav = -1, regime, date, price, momentum, price

        if position != 0 and entry_price is not None:
            open_carry_sum += _carry_value(index, position)
            open_carry = position * open_carry_sum / 90.0
            open_capital = (price - entry_price) * position * duration_mult
            mtm = realized_pnl + open_capital + open_carry
            capital = realized_capital + open_capital * 100.0
            carry = realized_carry + open_carry * 100.0
        else:
            mtm, capital, carry = realized_pnl, realized_capital, realized_carry
        equity_dates.append(date)
        equity_values.append(float(mtm))
        capital_values.append(float(capital))
        carry_values.append(float(carry))

    trades_df = pd.DataFrame(trades)
    if not trades_df.empty:
        trades_df['pnl_trade'] = trades_df['duration'] * trades_df['spd_chg'] + trades_df['cr_acc']
        trades_df['capital_cum'] = (trades_df['duration'] * trades_df['spd_chg']).cumsum()
        trades_df['carry_cum'] = trades_df['cr_acc'].cumsum()
        trades_df['pnl_cum'] = trades_df['pnl_trade'].cumsum()
    pnls = trades_df['pnl_trade'].to_numpy() if not trades_df.empty else np.array([])
    equity_ts = pd.Series(equity_values, index=pd.DatetimeIndex(equity_dates), name='equity_bp') * 100.0
    max_drawdown = float((np.maximum.accumulate(equity_ts) - equity_ts).max()) if not equity_ts.empty else 0.0

    open_trade = None
    if position != 0 and entry_price is not None and equity_dates:
        last_price = float(s.iloc[-1])
        open_capital = (last_price - entry_price) * position * duration_mult * 100.0
        open_carry = open_carry_sum * position / 90.0 * 100.0
        open_trade = {
            'entry_date': entry_date, 'direction': 'LONG' if position == 1 else 'SHORT',
            'entry_price': entry_price, 'current_date': s.index[-1],
            'current_price': last_price, 'days_held': (s.index[-1] - entry_date).days,
            'capital_open': open_capital, 'carry_open': open_carry,
            'pnl_open': open_capital + open_carry, 'status': 'OPEN', 'strategy': active_style,
        }

    return {
        'trades': trades_df.to_dict('records'), 'trades_df': trades_df,
        'n_trades': len(trades_df), 'total_pnl': float(np.nansum(pnls)),
        'win_rate': float((pnls > 0).mean() * 100.0) if len(pnls) else 0.0,
        'avg_pnl': float(np.nanmean(pnls)) if len(pnls) else 0.0,
        'avg_hold': float(trades_df['days_held'].mean()) if not trades_df.empty else 0.0,
        'sharpe': annualized_sharpe(equity_ts),
        'sharpe_per_trade': per_trade_sharpe(pnls, len(pnls)),
        'max_drawdown': max_drawdown, 'spread_ts': s, 'zscore_ts': zscore,
        'composite_signal_ts': composite_signal, 'trend_state_ts': trend_state,
        'norm_mom_ts': norm_mom, 'regime_ts': regime_ts, 'regime_score_ts': regime_scores,
        'hybrid': True, 'equity_ts': equity_ts,
        'capital_ts': pd.Series(capital_values, index=pd.DatetimeIndex(equity_dates), name='capital_bp'),
        'carry_ts': pd.Series(carry_values, index=pd.DatetimeIndex(equity_dates), name='carry_bp'),
        'carry_roll_ts': carry_roll_ts, 'open_trade': open_trade,
    }