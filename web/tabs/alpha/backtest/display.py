# -*- coding: utf-8 -*-
"""Backtest results display: metrics, instrument chart, score chart, PnL chart, trade table."""

from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from dash import dcc, html, dash_table

from ..data import THEME


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
