# -*- coding: utf-8 -*-
"""Futures backtest callbacks: data source toggle, symbol selection, run backtest."""

from __future__ import annotations

from dash import html, dcc
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

from ..data import THEME, FUTURES_AVAILABLE

try:
    from futures.backtest.data_loader import (
        load_wind_data, load_local_data_processed, resample_data, get_local_file_path,
    )
    from futures.backtest.strategies import (
        run_ma_strategy, run_bollinger_strategy, run_vwap_strategy,
        run_intraday_momentum_strategy, run_atr_band_strategy, run_sar_strategy,
        run_demark_strategy,
    )
    from futures.backtest.metrics import calculate_metrics
    from settings.futures import FuturesConfig
except ImportError:
    pass


def register_backtest_futures_callbacks(app):
    """Register Futures backtest callbacks."""

    # 6. Futures Backtest Callbacks
    @app.callback(
        [Output('bf-wind-inputs', 'style'), Output('bf-local-inputs', 'style')],
        [Input('bf-data-source', 'value')]
    )
    def bf_toggle_inputs(source):
        if source == 'wind':
            return {'display': 'block'}, {'display': 'none'}
        return {'display': 'none'}, {'display': 'block'}
    
    @app.callback(
        Output('bf-timeframe-container', 'style'),
        [Input('bf-trading-mode', 'value')]
    )
    def bf_toggle_timeframe(mode):
        if mode == 'daily':
            return {'display': 'none'}
        return {'display': 'block'}
    
    @app.callback(
        [Output('bf-wind-code', 'options'), Output('bf-wind-code', 'value')],
        [Input('bf-trading-mode', 'value')]
    )
    def bf_update_wind_options(mode):
        if not FUTURES_AVAILABLE: return [], None
        try:
            if mode == 'daily':
                opts = [{'label': s, 'value': s} for s in FuturesConfig.SYMBOLS]
                def_val = 'TL.CFE' if 'TL.CFE' in FuturesConfig.SYMBOLS else FuturesConfig.SYMBOLS[0]
            else:
                contract_list = FuturesConfig.get_contract_no()
                opts = [{'label': c, 'value': c} for c in contract_list]
                def_val = contract_list[0] if contract_list else None
            return opts, def_val
        except Exception:
             return [], None

    @app.callback(
        [Output('bf-local-symbol', 'options'),
         Output('bf-local-symbol', 'value')],
        [Input('bf-trading-mode', 'value')]
    )
    def bf_update_local_symbol_options(mode):
        if not FUTURES_AVAILABLE: return [], None
        try:
            if mode == 'daily':
                opts = [{'label': s, 'value': s} for s in FuturesConfig.SYMBOLS]
                def_val = 'TL.CFE' if 'TL.CFE' in FuturesConfig.SYMBOLS else FuturesConfig.SYMBOLS[0]
            else:
                contract_list = FuturesConfig.get_contract_no()
                opts = [{'label': c, 'value': c} for c in contract_list]
                def_val = contract_list[0] if contract_list else None
            return opts, def_val
        except Exception:
             return [], None

    @app.callback(
        [Output('bf-results-container', 'children'),
         Output('bf-perf-results-container', 'children')],
        [Input('bf-run-button', 'n_clicks'),
         Input('bf-local-symbol', 'value')],
        [State('bf-data-source', 'value'),
         State('bf-trading-mode', 'value'),
         State('bf-wind-code', 'value'),
         State('bf-date-range', 'start_date'),
         State('bf-date-range', 'end_date'),
         State('bf-timeframe', 'value'),
         State('bf-strategy-selector', 'value'),
         State('bf-ma-short', 'value'),
         State('bf-ma-long', 'value'),
         State('bf-boll-window', 'value'),
         State('bf-boll-std', 'value'),
         State('bf-boll-exit', 'value'),
         State('bf-vwap-window', 'value'),
         State('bf-mom-window', 'value'),
         State('bf-atr-ema-window', 'value'),
         State('bf-atr-window', 'value'),
         State('bf-sar-af', 'value'),
         State('bf-sar-max-af', 'value')]
    )
    def bf_update_dashboard(n_clicks, local_symbol, source, trading_mode, wind_code, start_date, end_date, tf,
                            selected_strategies,
                            ma_s, ma_l, boll_w, boll_std, boll_exit, vwap_w, mom_w, atr_ema_w, atr_w,
                            sar_af, sar_max_af):
        is_default_load = not n_clicks
        # On default load: show price chart only; on button click: run strategies
        run_strategies = not is_default_load
        
        if not FUTURES_AVAILABLE:
            return html.Div("Modules not loaded.", style={'color': THEME['danger']}), None

        selected_strategies = selected_strategies or []
        effective_tf = '1D' if trading_mode == 'daily' else tf

        # Load Data
        df = None
        err_msg = None

        try:
            if source == 'wind':
                if not wind_code: return html.Div("Please enter Wind symbol", style={'color': THEME['danger']}), None
                s_str = f"{start_date} 00:00:00"
                e_str = f"{end_date} 23:59:59"
                df, err_msg = load_wind_data(wind_code, s_str, e_str)
            else:
                if not local_symbol: return html.Div("Please select a symbol", style={'color': THEME['text_sub'], 'textAlign': 'center', 'marginTop': '50px'}), None
                file_path = get_local_file_path(local_symbol, effective_tf)
                if not file_path:
                    return html.Div("Unable to construct file path", style={'color': THEME['danger']}), None

                contract_key = local_symbol if trading_mode == 'daily' else None
                df, err_msg = load_local_data_processed(file_path, contract_key)
                if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
                    s_ts = pd.to_datetime(start_date)
                    e_ts = pd.to_datetime(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
                    df = df[(df.index >= s_ts) & (df.index <= e_ts)]

            if err_msg:
                return html.Div(f"Data loading error: {err_msg}", style={'color': THEME['danger']}), None
            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                return html.Div("Data is empty (please check date range)", style={'color': THEME['danger']}), None

            # Resample
            if effective_tf == '1D':
                if not isinstance(df.index, pd.DatetimeIndex):
                    df.index = pd.to_datetime(df.index, errors='coerce')
                df_resampled = df.copy()
                df_resampled = df_resampled[~df_resampled.index.duplicated(keep='last')]
            else:
                df_resampled = resample_data(df, effective_tf)
                
            if df_resampled.empty:
                return html.Div("Data is empty after resampling", style={'color': THEME['danger']}), None
                
            # Run strategies (only on explicit button click, not on default load)
            results = {}
            if run_strategies:
                if 'MA' in selected_strategies:
                    results['MA'] = run_ma_strategy(df_resampled, ma_s, ma_l)
                if 'DeMark' in selected_strategies:
                    results['DeMark'] = run_demark_strategy(df_resampled)
                if 'Boll' in selected_strategies:
                    exit_at_ma = 'exit' in (boll_exit or [])
                    results['Boll'] = run_bollinger_strategy(df_resampled, boll_w, boll_std, exit_at_ma)
                if 'VWAP' in selected_strategies:
                    results['VWAP'] = run_vwap_strategy(df_resampled, vwap_w)
                if 'Mom' in selected_strategies:
                    results['Mom'] = run_intraday_momentum_strategy(df_resampled, mom_w)
                if 'ATR' in selected_strategies:
                    results['ATR'] = run_atr_band_strategy(df_resampled, atr_ema_w, atr_w)
                if 'SAR' in selected_strategies:
                    results['SAR'] = run_sar_strategy(df_resampled, sar_af, sar_max_af)

            # Create Plotly Chart — 2 rows when strategies present, 1 row for default price view
            if results:
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                    vertical_spacing=0.03, row_heights=[0.7, 0.3])
            else:
                fig = make_subplots(rows=1, cols=1)

            # Candlestick
            fig.add_trace(go.Candlestick(
                x=df_resampled.index,
                open=df_resampled['open'], high=df_resampled['high'],
                low=df_resampled['low'], close=df_resampled['close'],
                name='Price'
            ), row=1, col=1)

            if 'DeMark' in results:
                df_demark = results['DeMark']
                for col, color, name in [
                    ('tdst_support', '#2ecc71', 'TDST Support'),
                    ('tdst_resistance', '#e74c3c', 'TDST Resistance'),
                ]:
                    series = df_demark[col].dropna()
                    if not series.empty:
                        fig.add_trace(go.Scatter(
                            x=series.index,
                            y=series.values,
                            mode='lines',
                            name=name,
                            line=dict(color=color, width=1.2, dash='dot')
                        ), row=1, col=1)

                for flag_col, name, symbol, color, price_col in [
                    ('buy_setup_complete', 'TD Buy Setup 9', 'triangle-up', '#27ae60', 'low'),
                    ('sell_setup_complete', 'TD Sell Setup 9', 'triangle-down', '#c0392b', 'high'),
                    ('buy_countdown_complete', 'TD Buy Countdown 13', 'star', '#2ecc71', 'low'),
                    ('sell_countdown_complete', 'TD Sell Countdown 13', 'star', '#e74c3c', 'high'),
                ]:
                    mask = df_demark[flag_col].eq(1)
                    if mask.any():
                        fig.add_trace(go.Scatter(
                            x=df_demark.index[mask],
                            y=df_demark.loc[mask, price_col],
                            mode='markers',
                            name=name,
                            marker=dict(symbol=symbol, color=color, size=10)
                        ), row=1, col=1)
            
            # Strategy Equity Curves (only when strategies were run)
            for name, res in results.items():
                fig.add_trace(go.Scatter(
                    x=res.index,
                    y=res['cumulative_returns'],
                    mode='lines', name=f'{name} Equity'
                ), row=2, col=1)

            fig.update_layout(
                height=560,
                template=THEME['chart_template'],
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font={'color': '#e9eef8'},
                margin=dict(l=50, r=20, t=30, b=40),
                legend=dict(orientation="h", y=1.04, x=0.5, xanchor="center"),
                xaxis_rangeslider_visible=False
            )
            fig.update_xaxes(gridcolor='rgba(100,140,200,0.12)')
            fig.update_yaxes(gridcolor='rgba(100,140,200,0.12)')

            # ── Strategy Performance table (matches BetaFutures.jsx METRIC rows) ──
            strategy_metrics = {name: calculate_metrics(res) for name, res in results.items()}

            def _is_positive(v):
                return not str(v).strip().startswith('-')

            _th_style = {
                'padding': '7px 12px', 'textAlign': 'right', 'fontSize': '8px',
                'color': 'var(--text-muted)', 'letterSpacing': '0.05em', 'textTransform': 'uppercase',
            }
            _td_label_style = {'padding': '7px 12px', 'color': 'var(--text-secondary)', 'fontSize': '10px'}

            def _metric_row(label, key, color_fn=None, fmt=None):
                cells = [html.Td(label, style=_td_label_style)]
                for name in strategy_metrics:
                    val = strategy_metrics[name].get(key, 'N/A')
                    display_val = fmt(val) if fmt else val
                    color = color_fn(val) if color_fn else 'var(--text-secondary)'
                    cells.append(html.Td(display_val, style={
                        'padding': '7px 12px', 'textAlign': 'right', 'fontWeight': '600',
                        'fontSize': '10px', 'color': color,
                    }))
                return html.Tr(cells, style={'borderBottom': '1px solid rgba(255,255,255,0.04)'})

            if strategy_metrics:
                strategy_table = html.Div(style={'overflowX': 'auto'}, children=[
                    html.Table([
                        html.Thead(html.Tr(
                            [html.Th("METRIC", style={**_th_style, 'textAlign': 'left'})] +
                            [html.Th(name.upper(), style=_th_style) for name in strategy_metrics]
                        , style={'background': 'var(--surface-panel)', 'borderBottom': '1px solid var(--border-strong)'})),
                        html.Tbody([
                            _metric_row("Return", "Total Return",
                                        color_fn=lambda v: '#34d399' if _is_positive(v) else '#f87171'),
                            _metric_row("Max DD", "Max Drawdown",
                                        color_fn=lambda v: '#f87171'),
                            _metric_row("Sharpe", "Sharpe Ratio",
                                        color_fn=lambda v: '#34d399' if not str(v).strip().startswith('-') else '#f87171'),
                            _metric_row("Trades", "Trades"),
                        ]),
                    ], style={'width': '100%', 'borderCollapse': 'collapse'}),
                ])
            else:
                strategy_table = html.Div(
                    "No results. Click ▶ Run Backtest to start.",
                    style={'color': 'var(--text-muted)', 'fontSize': '10px', 'padding': '4px 0'},
                )

            return dcc.Graph(figure=fig), strategy_table

        except Exception as e:
            import traceback
            traceback.print_exc()
            return html.Div(f"Error running backtest: {str(e)}", style={'color': THEME['danger']}), None

