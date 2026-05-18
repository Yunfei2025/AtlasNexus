# -*- coding: utf-8 -*-
"""Futures backtest callbacks: data source toggle, symbol selection, run backtest."""

from __future__ import annotations

from dash import html
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
        Output('bf-results-container', 'children'),
        [Input('bf-run-button', 'n_clicks')],
        [State('bf-data-source', 'value'),
         State('bf-trading-mode', 'value'),
         State('bf-wind-code', 'value'),
         State('bf-local-symbol', 'value'),
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
    def bf_update_dashboard(n_clicks, source, trading_mode, wind_code, local_symbol, start_date, end_date, tf, 
                         selected_strategies,
                         ma_s, ma_l, boll_w, boll_std, boll_exit, vwap_w, mom_w, atr_ema_w, atr_w,
                         sar_af, sar_max_af):
        if n_clicks == 0:
            return html.Div('Please configure parameters and click "Start Backtest"', style={'text-align': 'center', 'marginTop': '50px', 'color': THEME['text_sub']})
        
        if not FUTURES_AVAILABLE:
            return html.Div("Modules not loaded.", style={'color': THEME['danger']})

        selected_strategies = selected_strategies or []
        effective_tf = '1D' if trading_mode == 'daily' else tf
        
        # Load Data
        df = None
        err_msg = None
        
        try:
            if source == 'wind':
                if not wind_code: return html.Div("Please enter Wind symbol", style={'color': THEME['danger']})
                s_str = f"{start_date} 00:00:00"
                e_str = f"{end_date} 23:59:59"
                df, err_msg = load_wind_data(wind_code, s_str, e_str)
            else:
                if not local_symbol: return html.Div("Please enter symbol", style={'color': THEME['danger']})
                file_path = get_local_file_path(local_symbol, effective_tf)
                if not file_path:
                    return html.Div("Unable to construct file path", style={'color': THEME['danger']})
                
                contract_key = local_symbol if trading_mode == 'daily' else None
                df, err_msg = load_local_data_processed(file_path, contract_key)
                if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
                    s_ts = pd.to_datetime(start_date)
                    e_ts = pd.to_datetime(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
                    df = df[(df.index >= s_ts) & (df.index <= e_ts)]
                
            if err_msg:
                return html.Div(f"Data loading error: {err_msg}", style={'color': THEME['danger']})
            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                return html.Div("Data is empty (please check date range)", style={'color': THEME['danger']})

            # Resample
            if effective_tf == '1D':
                if not isinstance(df.index, pd.DatetimeIndex):
                    df.index = pd.to_datetime(df.index, errors='coerce')
                df_resampled = df.copy()
                df_resampled = df_resampled[~df_resampled.index.duplicated(keep='last')]
            else:
                df_resampled = resample_data(df, effective_tf)
                
            if df_resampled.empty:
                return html.Div("Data is empty after resampling", style={'color': THEME['danger']})
                
            # Run strategies
            results = {}
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

            # Create Plotly Chart
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                                vertical_spacing=0.03, row_heights=[0.7, 0.3])

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
            
            # Strategy Equity Curves
            for name, res in results.items():
                fig.add_trace(go.Scatter(
                    x=res.index, 
                    y=res['cumulative_returns'],
                    mode='lines', name=f'{name} Equity'
                ), row=2, col=1)

            fig.update_layout(
                height=600, 
                title="Backtest Results",
                template=THEME['chart_template'],
                paper_bgcolor=THEME['bg_card'],
                plot_bgcolor=THEME['bg_card'],
                font={'color': THEME['text_main']},
                margin=dict(l=50, r=50, t=50, b=50),
                legend=dict(orientation="h", y=1.02, x=0.5, xanchor="center"),
                xaxis_rangeslider_visible=False
            )
            fig.update_xaxes(gridcolor=THEME['table_header'])
            fig.update_yaxes(gridcolor=THEME['table_header'])

            # Helper for local Metric Card (redefined here or duplicated logic)
            def create_metric_card_local(title, metrics):
                return html.Div([
                    html.H6(title, style={'color': THEME['text_sub'], 'marginBottom': '5px', 'fontSize': '14px'}),
                    html.Div([
                        html.Div(f"Ret: {metrics.get('Total Return', 'N/A')}", style={'fontWeight': 'bold', 'color': THEME['success'] if str(metrics.get('Total Return')).startswith('+') else THEME['text_main']}),
                        html.Div(f"DD: {metrics.get('Max Drawdown', 'N/A')}", style={'color': THEME['danger']}),
                        html.Div(f"Sharpe: {metrics.get('Sharpe Ratio', 'N/A')}"),
                        html.Div(f"Trades: {metrics.get('Trades', 'N/A')}"),
                    ], style={'fontSize': '12px', 'lineHeight': '1.5', 'display': 'grid', 'gridTemplateColumns': '1fr 1fr', 'gap': '5px'})
                ], style={'backgroundColor': THEME['bg_input'], 'padding': '10px', 'borderRadius': '4px', 'marginBottom': '10px', 'flex': '1', 'minWidth': '150px'})

            # Card Display
            cards = []
            
            for name, res in results.items():
                m = calculate_metrics(res)
                cards.append(create_metric_card_local(name, m))
                
            return html.Div([
                html.Div(cards, style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '10px', 'marginBottom': '15px'}),
                dcc.Graph(figure=fig)
            ])

        except Exception as e:
            import traceback
            traceback.print_exc()
            return html.Div(f"Error running backtest: {str(e)}", style={'color': THEME['danger']})

