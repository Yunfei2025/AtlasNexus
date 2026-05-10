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
) -> float:
    """Compute carry accrual for a trade.

    Accumulates daily carry by summing each observed daily carry rate over the
    window [entry_date, exit_date] and dividing by 90 (3m convention).
    Falls back to 0.0 if no time-series data is available in the window.
    """
    if carry_roll_ts is not None and len(carry_roll_ts) > 0:
        try:
            ts = carry_roll_ts
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
                return position * float(window.sum()) / 90.0
        except Exception:
            pass
    return 0.0


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

    trades = []
    position = 0
    entry_date = None
    entry_price = None
    entry_zscore = None
    realized_pnl = 0.0
    equity_dates: List[pd.Timestamp] = []
    equity_values: List[float] = []

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

            if trade_style == 'mr':
                if position == 1 and cs >= -exit_z:
                    exit_signal = True
                    exit_reason = 'target'
                elif position == -1 and cs <= exit_z:
                    exit_signal = True
                    exit_reason = 'target'
            else:
                if position == 1 and cs > entry_zscore + 1:
                    exit_signal = True
                    exit_reason = 'reversal'
                elif position == -1 and cs < entry_zscore - 1:
                    exit_signal = True
                    exit_reason = 'reversal'

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
                )
                pnl = price_pnl + carry_income
                realized_pnl += pnl
                trades.append({
                    'entry_date': entry_date,
                    'exit_date': date,
                    'direction': 'LONG' if position == 1 else 'SHORT',
                    'entry_price': entry_price,
                    'exit_price': price,
                    'entry_z': entry_zscore,
                    'exit_z': z,
                    'pnl_bp': pnl,
                    'carry_bp': carry_income,
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

        if position != 0 and entry_price is not None:
            days_open = (date - entry_date).days if entry_date else 0
            daily_carry = _carry_accrual(
                position, entry_date, date, days_open,
                carry_roll_ts, carry_roll_bp,
            )
            mtm = realized_pnl + (price - entry_price) * position * duration_mult + daily_carry
        else:
            mtm = realized_pnl
        equity_dates.append(pd.Timestamp(date))
        equity_values.append(float(mtm))

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
            'entry_z': entry_z,
            'exit_z': exit_z,
            'stop_z': stop_z,
        }

    trades_df = pd.DataFrame(trades)
    if not trades_df.empty:
        trades_df['pnl_bp'] = trades_df['pnl_bp'].astype(float) * 100.0
        trades_df['carry_bp'] = trades_df.get('carry_bp', 0.0).astype(float) * 100.0
    pnls = trades_df['pnl_bp'].values

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
    running_max = np.maximum.accumulate(cum_pnl)
    drawdowns = running_max - cum_pnl
    max_drawdown = drawdowns.max() if len(drawdowns) > 0 else 0

    trades_out = trades_df.to_dict('records') if not trades_df.empty else []

    try:
        equity_ts = equity_ts * 100.0
    except Exception:
        pass

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

    trades: List[Dict[str, Any]] = []
    position = 0
    entry_date = None
    entry_price = None
    best_fav = None
    realized_pnl = 0.0
    equity_dates: List[pd.Timestamp] = []
    equity_values: List[float] = []

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
                )
                pnl = price_pnl + carry_income
                realized_pnl += pnl
                trades.append({
                    'entry_date': entry_date,
                    'exit_date': date,
                    'direction': 'LONG' if position == 1 else 'SHORT',
                    'entry_price': entry_price,
                    'exit_price': px,
                    'pnl_bp': pnl,
                    'carry_bp': carry_income,
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
            mtm = realized_pnl + (px - entry_price) * position * duration_mult
        else:
            mtm = realized_pnl
        equity_dates.append(pd.Timestamp(date))
        equity_values.append(float(mtm))

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
        }

    trades_df = pd.DataFrame(trades)
    if not trades_df.empty:
        trades_df['pnl_bp'] = trades_df['pnl_bp'].astype(float) * 100.0
        trades_df['carry_bp'] = trades_df.get('carry_bp', 0.0).astype(float) * 100.0
    pnls = trades_df['pnl_bp'].values
    n_trades = int(len(trades_df))
    total_pnl = float(np.nansum(pnls))
    win_rate = float((pnls > 0).sum() / n_trades * 100.0)
    avg_pnl = float(np.nanmean(pnls))
    avg_hold = float(trades_df['days_held'].mean())
    sharpe = float((np.nanmean(pnls) / np.nanstd(pnls)) * np.sqrt(min(n_trades, 20))) if np.nanstd(pnls) > 0 else 0.0

    cum_pnl = np.nancumsum(pnls)
    running_max = np.maximum.accumulate(cum_pnl)
    drawdowns = running_max - cum_pnl
    max_drawdown = float(drawdowns.max()) if len(drawdowns) > 0 else 0.0

    trades_out = trades_df.to_dict('records') if not trades_df.empty else []
    try:
        equity_ts = equity_ts * 100.0
    except Exception:
        pass

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
    }


def build_backtest_results_display(results: Dict[str, Any], title: str = "Backtest Results") -> html.Div:
    """Build the display for backtest results."""
    import plotly.graph_objects as go

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

    instrument_fig = go.Figure()
    if 'spread_ts' in results and results['spread_ts'] is not None:
        spread_ts = results['spread_ts'].dropna()
        if x_start is not None:
            spread_ts = spread_ts.loc[spread_ts.index >= x_start]
        if len(spread_ts) > 0:
            instrument_fig.add_trace(go.Scatter(
                x=spread_ts.index, y=spread_ts.values,
                mode='lines', name='Spread',
                line=dict(color=THEME['accent'], width=1.5),
                showlegend=False,
            ))

    if trades_df is not None and len(trades_df) > 0:
        long_entries = trades_df[trades_df['direction'] == 'LONG']
        short_entries = trades_df[trades_df['direction'] == 'SHORT']
        _exit_reason_inst = trades_df.get('exit_reason', pd.Series([''] * len(trades_df), index=trades_df.index))
        profit_exits = trades_df[_exit_reason_inst.isin(['target', 'reversal'])]
        loss_exits = trades_df[_exit_reason_inst.isin(['stop_loss', 'max_hold'])]
        if len(long_entries) > 0:
            instrument_fig.add_trace(go.Scatter(x=long_entries['entry_date'], y=long_entries['entry_price'], mode='markers', name='Long Entry', marker=dict(symbol='triangle-up', size=10, color=THEME['success'], line=dict(width=1, color='white')), showlegend=True))
        if len(short_entries) > 0:
            instrument_fig.add_trace(go.Scatter(x=short_entries['entry_date'], y=short_entries['entry_price'], mode='markers', name='Short Entry', marker=dict(symbol='triangle-down', size=10, color=THEME['danger'], line=dict(width=1, color='white')), showlegend=True))
        if len(profit_exits) > 0:
            instrument_fig.add_trace(go.Scatter(x=profit_exits['exit_date'], y=profit_exits['exit_price'], mode='markers', name='Exit (profit)', marker=dict(symbol='circle', size=7, color=THEME['success'], opacity=0.85), showlegend=True))
        if len(loss_exits) > 0:
            instrument_fig.add_trace(go.Scatter(x=loss_exits['exit_date'], y=loss_exits['exit_price'], mode='markers', name='Exit (stop/loss)', marker=dict(symbol='x', size=9, color=THEME['danger'], opacity=0.85), showlegend=True))

    _cr_ts = results.get('carry_roll_ts')
    if _cr_ts is not None and len(_cr_ts) > 0:
        cr_plot = _cr_ts.copy()
        if not isinstance(cr_plot.index, pd.DatetimeIndex):
            cr_plot.index = pd.to_datetime(cr_plot.index)
        elif hasattr(cr_plot.index, 'tz') and cr_plot.index.tz is not None:
            cr_plot.index = cr_plot.index.tz_localize(None)
        if x_start is not None:
            cr_plot = cr_plot.loc[cr_plot.index >= x_start]
        if len(cr_plot) > 0:
            instrument_fig.add_trace(go.Scatter(
                x=cr_plot.index, y=cr_plot.values,
                mode='lines', name='Carry+Roll (3m)',
                line=dict(color='rgba(243,156,18,0.75)', width=1, dash='dot'),
                yaxis='y2', showlegend=True,
            ))

    instrument_fig.update_layout(
        title='Instrument History', height=300,
        margin=dict(l=50, r=20, t=40, b=40),
        plot_bgcolor=THEME['bg_main'], paper_bgcolor=THEME['bg_main'],
        font=dict(color=THEME['text_main']),
        xaxis=dict(gridcolor=THEME['bg_card'], tickformat='%b\n%Y', hoverformat='%Y-%m-%d', **_xaxis_range),
        yaxis=dict(title='Spread', gridcolor=THEME['bg_card']),
        yaxis2=dict(title=dict(text='Carry+Roll (3m)', font=dict(color='rgba(243,156,18,0.85)')), overlaying='y', side='right', showgrid=False, tickfont=dict(color='rgba(243,156,18,0.85)')),
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1, font=dict(size=10), bgcolor='rgba(0,0,0,0)'),
    )
    instrument_div = html.Div([dcc.Graph(figure=instrument_fig, style={'height': '300px'})], style={'marginBottom': '15px'})

    score_div = html.Div()
    _composite = results.get('composite_signal_ts')
    _raw_score = results.get('norm_mom_ts') if is_trend else (_composite if _composite is not None else results.get('zscore_ts'))
    if _raw_score is not None and len(_raw_score.dropna()) > 0:
        score_ts_display = _raw_score.dropna()
        score_label = 'Norm Momentum (σ)' if is_trend else ('Carry-Adj Z (120d)' if _composite is not None else 'Z-Score (120d)')

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
            _exit_reason = trades_df.get('exit_reason', pd.Series([''] * len(trades_df), index=trades_df.index))
            prof_x = trades_df[_exit_reason.isin(['target', 'reversal'])]
            loss_x = trades_df[_exit_reason.isin(['stop_loss', 'max_hold'])]

            if len(long_e) > 0:
                signal_fig.add_trace(go.Scatter(x=long_e['entry_date'], y=_score_at(long_e, 'entry_date'), mode='markers', marker=dict(symbol='triangle-up', size=9, color=THEME['success'], line=dict(width=1, color='white')), showlegend=False))
            if len(short_e) > 0:
                signal_fig.add_trace(go.Scatter(x=short_e['entry_date'], y=_score_at(short_e, 'entry_date'), mode='markers', marker=dict(symbol='triangle-down', size=9, color=THEME['danger'], line=dict(width=1, color='white')), showlegend=False))
            if len(prof_x) > 0:
                signal_fig.add_trace(go.Scatter(x=prof_x['exit_date'], y=_score_at(prof_x, 'exit_date'), mode='markers', marker=dict(symbol='circle', size=7, color=THEME['success'], opacity=0.8), showlegend=False))
            if len(loss_x) > 0:
                signal_fig.add_trace(go.Scatter(x=loss_x['exit_date'], y=_score_at(loss_x, 'exit_date'), mode='markers', marker=dict(symbol='x', size=8, color=THEME['danger'], opacity=0.8), showlegend=False))

        signal_fig.update_layout(
            title=f'Score History ({score_label})', height=230,
            margin=dict(l=50, r=20, t=40, b=40),
            plot_bgcolor=THEME['bg_main'], paper_bgcolor=THEME['bg_main'],
            font=dict(color=THEME['text_main']),
            xaxis=dict(gridcolor=THEME['bg_card'], tickformat='%b\n%Y', hoverformat='%Y-%m-%d', **_xaxis_range),
            yaxis=dict(title='Norm Mom (σ)' if is_trend else 'Z-Score', gridcolor=THEME['bg_card']),
            showlegend=False,
        )
        score_div = html.Div([dcc.Graph(figure=signal_fig, style={'height': '230px'})], style={'marginBottom': '15px'})

    equity_fig = go.Figure()
    equity_ts = results.get('equity_ts')
    if isinstance(equity_ts, pd.Series) and len(equity_ts.dropna()) > 0:
        if x_start is not None:
            equity_ts = equity_ts[equity_ts.index >= x_start]
        equity_fig.add_trace(go.Scatter(x=equity_ts.index, y=equity_ts.values, mode='lines', name='Cumulative PnL (Daily MtM)', line=dict(color=THEME['success'], width=2), fill='tozeroy', fillcolor='rgba(0, 204, 150, 0.08)'))
        equity_fig.add_hline(y=0, line_dash='dot', line_color=THEME['text_sub'])
    elif 'cum_pnl' in results and len(results['cum_pnl']) > 0 and trades_df is not None and len(trades_df) > 0:
        exit_dates = pd.to_datetime(trades_df['exit_date']).tolist()
        cum_vals = list(results['cum_pnl'])
        first_entry = pd.to_datetime(trades_df['entry_date'].iloc[0])
        equity_fig.add_trace(go.Scatter(x=[first_entry] + exit_dates, y=[0.0] + cum_vals, mode='lines', name='Cumulative PnL', line=dict(color=THEME['success'], width=2), fill='tozeroy', fillcolor='rgba(0, 204, 150, 0.08)'))
        equity_fig.add_hline(y=0, line_dash='dot', line_color=THEME['text_sub'])

    equity_fig.update_layout(
        title='Cumulative PnL (bp)', height=230,
        margin=dict(l=50, r=20, t=40, b=40),
        plot_bgcolor=THEME['bg_main'], paper_bgcolor=THEME['bg_main'],
        font=dict(color=THEME['text_main']),
        xaxis=dict(gridcolor=THEME['bg_card'], tickformat='%b\n%Y', hoverformat='%Y-%m-%d', **_xaxis_range),
        yaxis=dict(title='Cumulative PnL (bp)', gridcolor=THEME['bg_card']),
    )
    equity_div = html.Div([dcc.Graph(figure=equity_fig, style={'height': '230px'})], style={'marginBottom': '15px'})

    trades_table = html.Div()
    if 'trades_df' in results and results['trades_df'] is not None and len(results['trades_df']) > 0:
        df = results['trades_df'].copy()
        df['entry_date'] = pd.to_datetime(df['entry_date']).dt.strftime('%Y-%m-%d')
        df['exit_date'] = pd.to_datetime(df['exit_date']).dt.strftime('%Y-%m-%d')
        for col in ['entry_price', 'exit_price', 'pnl_bp', 'carry_bp', 'entry_z', 'exit_z']:
            if col in df.columns:
                df[col] = df[col].round(4)

        trades_table = html.Div([
            html.H6("Trade History", style={'color': THEME['text_main'], 'marginBottom': '10px'}),
            dash_table.DataTable(
                columns=[{'name': c, 'id': c} for c in df.columns],
                data=df.to_dict('records'),
                style_table={'overflowX': 'auto', 'maxHeight': '250px', 'overflowY': 'auto'},
                style_header={'backgroundColor': THEME['table_header'], 'color': THEME['text_main'], 'fontWeight': 'bold'},
                style_cell={'backgroundColor': THEME['bg_card'], 'color': THEME['text_main'], 'fontSize': '11px', 'padding': '5px'},
                style_data_conditional=[
                    {'if': {'filter_query': '{pnl_bp} > 0'}, 'backgroundColor': 'rgba(0, 204, 150, 0.1)'},
                    {'if': {'filter_query': '{pnl_bp} < 0'}, 'backgroundColor': 'rgba(239, 85, 59, 0.1)'},
                ],
                page_size=10,
                sort_action='native',
            ),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px'})

    return html.Div([metrics_div, instrument_div, score_div, equity_div, trades_table])
