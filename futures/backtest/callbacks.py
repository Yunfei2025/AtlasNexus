"""
Dashboard callbacks module
Contains all Dash application callback logic
"""

from dash import Input, Output, State, html, dcc
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from data_loader import (
    get_file_structure, 
    load_wind_data, 
    load_local_data_processed,
    resample_data,
    get_local_file_path
)
from strategies import (
    run_ma_strategy,
    run_bollinger_strategy,
    run_vwap_strategy,
    run_intraday_momentum_strategy,
    run_atr_band_strategy,
    run_sar_strategy
)
from metrics import calculate_metrics, run_rolling_best_strategy
from layout import create_metric_card, CARD_STYLE
from regime import RegimeDetector
import sys
import os
# Add parent directories to path to import from settings
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from settings.futures import FuturesConfig


def register_callbacks(app):
    """Register all callback functions"""
    
    @app.callback(
        [Output('wind-inputs', 'style'), Output('local-inputs', 'style')],
        [Input('data-source', 'value')]
    )
    def toggle_inputs(source):
        """Toggle data source input interface"""
        if source == 'wind':
            return {'display': 'block'}, {'display': 'none'}
        return {'display': 'none'}, {'display': 'block'}
    
    @app.callback(
        Output('timeframe-container', 'style'),
        [Input('trading-mode', 'value')]
    )
    def toggle_timeframe(mode):
        """Show/hide timeframe selector based on trading mode"""
        if mode == 'daily':
            return {'display': 'none'}
        return {'display': 'block'}
    
    @app.callback(
        [Output('wind-code', 'options'),
         Output('wind-code', 'value')],
        [Input('trading-mode', 'value')]
    )
    def update_wind_symbol_options(mode):
        """Update Wind symbol dropdown options based on trading mode"""
        if mode == 'daily':
            options = [{'label': s, 'value': s} for s in FuturesConfig.SYMBOLS]
            default_value = 'TL.CFE' if 'TL.CFE' in FuturesConfig.SYMBOLS else FuturesConfig.SYMBOLS[0]
        else:
            try:
                contract_list = FuturesConfig.get_contract_no()
                options = [{'label': c, 'value': c} for c in contract_list]
                default_value = contract_list[0] if contract_list else None
            except Exception as e:
                # Fallback if get_contract_no() fails
                print(f"Warning: Failed to get contract numbers: {e}")
                options = [{'label': s, 'value': s} for s in FuturesConfig.SYMBOLS]
                default_value = 'TL.CFE' if 'TL.CFE' in FuturesConfig.SYMBOLS else FuturesConfig.SYMBOLS[0]
        return options, default_value
    
    @app.callback(
        [Output('local-symbol', 'options'),
         Output('local-symbol', 'value')],
        [Input('trading-mode', 'value')]
    )
    def update_local_symbol_options(mode):
        """Update Local symbol dropdown options based on trading mode"""
        if mode == 'daily':
            options = [{'label': s, 'value': s} for s in FuturesConfig.SYMBOLS]
            default_value = 'TL.CFE' if 'TL.CFE' in FuturesConfig.SYMBOLS else FuturesConfig.SYMBOLS[0]
        else:
            try:
                contract_list = FuturesConfig.get_contract_no()
                options = [{'label': c, 'value': c} for c in contract_list]
                default_value = contract_list[0] if contract_list else None
            except Exception as e:
                # Fallback if get_contract_no() fails
                print(f"Warning: Failed to get contract numbers: {e}")
                options = [{'label': s, 'value': s} for s in FuturesConfig.SYMBOLS]
                default_value = 'TL.CFE' if 'TL.CFE' in FuturesConfig.SYMBOLS else FuturesConfig.SYMBOLS[0]
        return options, default_value

    @app.callback(
        Output('results-container', 'children'),
        [Input('run-button', 'n_clicks')],
        [State('data-source', 'value'),
         State('trading-mode', 'value'),
         State('wind-code', 'value'),
         State('local-symbol', 'value'),
         State('date-range', 'start_date'),
         State('date-range', 'end_date'),
         State('timeframe', 'value'),
         State('strategy-selector', 'value'),
         State('ma-short', 'value'),
         State('ma-long', 'value'),
         State('boll-window', 'value'),
         State('boll-std', 'value'),
         State('boll-exit', 'value'),
         State('vwap-window', 'value'),
         State('mom-window', 'value'),
         State('atr-ema-window', 'value'),
         State('atr-window', 'value'),
         State('sar-af', 'value'),
         State('sar-max-af', 'value')]
    )
    def update_dashboard(n_clicks, source, trading_mode, wind_code, local_symbol, start_date, end_date, tf, 
                         selected_strategies,
                         ma_s, ma_l, boll_w, boll_std, boll_exit, vwap_w, mom_w, atr_ema_w, atr_w,
                         sar_af, sar_max_af):
        """Main callback function: Update backtest results"""
        if n_clicks == 0:
            return html.Div('Please configure parameters and click "Start Backtest"', style={'text-align': 'center', 'margin-top': '50px', 'color': '#888'})
        
        selected_strategies = selected_strategies or []
        
        # Determine effective timeframe based on trading mode
        effective_tf = '1D' if trading_mode == 'daily' else tf
        
        # Load data
        df = None
        err_msg = None
        
        if source == 'wind':
            if not wind_code: return html.Div("Please enter Wind symbol", style={'color': 'red'})
            # Convert date format
            s_str = f"{start_date} 00:00:00"
            e_str = f"{end_date} 23:59:59"
            df, err_msg = load_wind_data(wind_code, s_str, e_str)
        else:
            if not local_symbol: return html.Div("Please enter symbol", style={'color': 'red'})
            # Construct file path based on trading mode and symbol
            file_path = get_local_file_path(local_symbol, effective_tf)
            if not file_path:
                return html.Div("Unable to construct file path", style={'color': 'red'})
            
            # For daily data, symbol is the key; for intraday, the file itself is the data
            contract_key = local_symbol if trading_mode == 'daily' else None
            df, err_msg = load_local_data_processed(file_path, contract_key)
            # Filter local data by date range to match UI selection
            if df is not None and not df.empty:
                s_ts = pd.to_datetime(start_date)
                e_ts = pd.to_datetime(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
                df = df[(df.index >= s_ts) & (df.index <= e_ts)]
            
        if err_msg:
            return html.Div(f"Data loading error: {err_msg}", style={'color': 'red'})
        if df is None or df.empty:
            return html.Div("Data is empty (please check date range)", style={'color': 'red'})
            
        # Resample
        # If already daily data (effective_tf='1D') and data itself looks like daily, skip resampling or simple processing
        # Simple check: if data rows are few, or user selected daily mode
        if effective_tf == '1D':
            # Ensure index is datetime
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index, errors='coerce')
            
            # If daily, no need for resample('1D').ohlc() as it changes column structure if original data is already OHLC
            # Use original data directly, but ensure necessary columns exist
            df_resampled = df.copy()
            # Remove daily duplicates (if any)
            df_resampled = df_resampled[~df_resampled.index.duplicated(keep='last')]
        else:
            df_resampled = resample_data(df, effective_tf)
            
        if df_resampled.empty:
            return html.Div("Data is empty after resampling", style={'color': 'red'})
            
        # Run strategies
        results = {}
        
        if 'MA' in selected_strategies:
            results['MA'] = run_ma_strategy(df_resampled, ma_s, ma_l)
            
        if 'Boll' in selected_strategies:
            exit_at_ma = 'exit' in (boll_exit or [])
            results['Boll'] = run_bollinger_strategy(df_resampled, boll_w, boll_std, exit_at_ma)
            
        if 'VWAP' in selected_strategies:
            results['VWAP'] = run_vwap_strategy(df_resampled, vwap_w)
            
        if 'Momentum' in selected_strategies:
            results['Momentum'] = run_intraday_momentum_strategy(df_resampled, mom_w, vwap_w)
            
        if 'ATR' in selected_strategies:
            results['ATR'] = run_atr_band_strategy(df_resampled, atr_ema_w, atr_w)
            
        if 'SAR' in selected_strategies:
            results['SAR'] = run_sar_strategy(df_resampled, sar_af, sar_max_af)
        
        # Run rolling best strategy
        # Only run when RollingBest is selected
        # It depends on results from other strategies.
        # Logic: If RollingBest is selected, it will select the best from already calculated strategies in results.
        # If results is empty (no other strategies selected), it cannot run.
        if 'RollingBest' in selected_strategies:
            # Filter out RollingBest itself, keep only base strategies
            base_strategies = {k: v for k, v in results.items() if k != 'RollingBest'}
            if base_strategies:
                results['RollingBest'] = run_rolling_best_strategy(df_resampled, base_strategies, lookback_months=6)

        # Unified processing: For all strategies except RollingBest, remove first 6 months of returns for fair comparison
        # Calculate start trading date (consistent with run_rolling_best_strategy logic)
        month_starts = df_resampled.resample('MS').first().index
        lookback_months = 6
        
        if len(month_starts) > lookback_months:
            first_trade_date = month_starts[lookback_months]
            
            for name, res_df in results.items():
                if name == 'RollingBest':
                    continue
                    
                # Set first 6 months signal to 0
                res_df.loc[res_df.index < first_trade_date, 'signal'] = 0
                
                # Recalculate position (optional, mainly for plotting)
                res_df['position'] = res_df['signal'].diff()
                
                # Recalculate strategy_returns
                res_df['strategy_returns'] = res_df['signal'].shift(1) * res_df['returns']
                
                # Force zero again (handle boundary cases)
                res_df.loc[res_df.index < first_trade_date, 'strategy_returns'] = 0
                
                # Recalculate cumulative returns
                res_df['cumulative_returns'] = (1 + res_df['strategy_returns']).cumprod()
        
        # Calculate metrics and build cards
        metric_cards = []
        
        # Define display order and titles
        strategy_meta = [
            ('MA', "MA Crossover"),
            ('Boll', "Bollinger Bands"),
            ('VWAP', "VWAP"),
            ('Momentum', "Intraday Momentum"),
            ('ATR', "ATR Bands"),
            ('SAR', "SAR"),
            ('RollingBest', "🏆 Rolling Best")
        ]
        
        for key, title in strategy_meta:
            if key in results:
                metrics = calculate_metrics(results[key])
                metric_cards.append(create_metric_card(title, metrics))
        
        metrics_row = html.Div(metric_cards, style={'display': 'flex', 'flex-wrap': 'wrap'})
        
        # Plot charts
        fig = make_subplots(
            rows=4, cols=1, 
            shared_xaxes=False, 
            vertical_spacing=0.06,
            row_heights=[0.4, 0.15, 0.25, 0.2],
            subplot_titles=("Price & Technical Indicators", "Market Regime", "Cumulative Returns Comparison", "Position Status")
        )
        
        x_index = df_resampled.index.strftime('%Y-%m-%d<br>%H:%M')
        
        # Row 1: Price & Indicators
        fig.add_trace(go.Scatter(x=x_index, y=df_resampled['close'], name='Close Price', line=dict(color='black', width=2)), row=1, col=1)
        
        if 'MA' in results:
            df_ma = results['MA']
            fig.add_trace(go.Scatter(x=x_index, y=df_ma['ma_short'], name=f'MA{ma_s}', line=dict(color='orange', width=1), visible='legendonly'), row=1, col=1)
            fig.add_trace(go.Scatter(x=x_index, y=df_ma['ma_long'], name=f'MA{ma_l}', line=dict(color='blue', width=1), visible='legendonly'), row=1, col=1)
            
        if 'Boll' in results:
            df_boll = results['Boll']
            fig.add_trace(go.Scatter(x=x_index, y=df_boll['upper_band'], name='Bollinger Upper', line=dict(color='green', width=1, dash='dot'), visible='legendonly'), row=1, col=1)
            fig.add_trace(go.Scatter(x=x_index, y=df_boll['lower_band'], name='Bollinger Lower', line=dict(color='red', width=1, dash='dot'), visible='legendonly'), row=1, col=1)
            
        if 'VWAP' in results:
            df_vwap = results['VWAP']
            fig.add_trace(go.Scatter(x=x_index, y=df_vwap['vwap'], name='VWAP', line=dict(color='purple', width=1, dash='dash'), visible='legendonly'), row=1, col=1)
            
        if 'Momentum' in results:
            df_mom = results['Momentum']
            fig.add_trace(go.Scatter(x=x_index, y=df_mom['upper_limit'], name='Momentum Upper', line=dict(color='cyan', width=1, dash='dashdot'), visible='legendonly'), row=1, col=1)
            fig.add_trace(go.Scatter(x=x_index, y=df_mom['lower_limit'], name='Momentum Lower', line=dict(color='magenta', width=1, dash='dashdot'), visible='legendonly'), row=1, col=1)
        
        if 'ATR' in results:
            df_atr = results['ATR']
            fig.add_trace(go.Scatter(x=x_index, y=df_atr['upper_3'], name='ATR Upper 3', line=dict(color='red', width=1, dash='solid'), visible='legendonly'), row=1, col=1)
            fig.add_trace(go.Scatter(x=x_index, y=df_atr['lower_3'], name='ATR Lower 3', line=dict(color='green', width=1, dash='solid'), visible='legendonly'), row=1, col=1)
        
        if 'SAR' in results:
            df_sar = results['SAR']
            fig.add_trace(go.Scatter(x=x_index, y=df_sar['sar'], name='SAR', mode='markers', marker=dict(color='gray', size=3), visible='legendonly'), row=1, col=1)

        # Row 2: Market Regime Detection
        try:
            detector = RegimeDetector(n_states=2)
            features = detector.calculate_features(df_resampled, window=20)
            detector.fit(features)
            states, probs = detector.predict(features)
            
            # Align regime data with full index
            regime_series = pd.Series(index=df_resampled.index, dtype=float)
            regime_series.loc[features.index] = states
            
            # Plot regime as colored background or line
            regime_colors = {0: 'rgba(0, 255, 0, 0.3)', 1: 'rgba(255, 0, 0, 0.3)'}  # Green: Low Vol/Mean-Rev, Red: High Vol/Trend
            
            # Create regime visualization as a line plot
            fig.add_trace(go.Scatter(
                x=x_index, 
                y=regime_series,
                name='Regime State',
                mode='lines',
                line=dict(color='blue', width=2, shape='hv'),
                fill='tozeroy',
                fillcolor='rgba(100, 150, 200, 0.3)'
            ), row=2, col=1)
            
        except Exception as e:
            # If regime detection fails, add a placeholder
            print(f"Regime detection error: {e}")
            fig.add_trace(go.Scatter(
                x=x_index,
                y=[0]*len(x_index),
                name='Regime (unavailable)',
                mode='lines',
                line=dict(color='gray', width=1, dash='dot')
            ), row=2, col=1)

        # Row 3: Cumulative Returns
        colors = {'MA': 'blue', 'Boll': 'orange', 'VWAP': 'purple', 'Momentum': 'cyan', 'ATR': 'brown', 'SAR': 'pink', 'RollingBest': 'red'}
        widths = {'RollingBest': 3}
        
        for key, title in strategy_meta:
            if key in results:
                df_res = results[key]
                width = widths.get(key, 1)
                fig.add_trace(go.Scatter(x=x_index, y=df_res['cumulative_returns'], name=f'{key} Returns', line=dict(color=colors.get(key, 'gray'), width=width)), row=3, col=1)
        
        # Row 4: Aggregated Position & Best Strategy Position
        agg_signal = pd.Series(0, index=df_resampled.index)
        for key in results:
            if key != 'RollingBest': # Aggregated position typically refers to the sum of base strategies
                 agg_signal += results[key]['signal']
                 
        fig.add_trace(go.Scatter(
            x=x_index, y=agg_signal, name='Aggregated Position', 
            line=dict(color='rgba(50, 50, 50, 0.8)', width=1.5, shape='hv'),
            fill='tozeroy', fillcolor='rgba(100, 100, 100, 0.2)'
        ), row=4, col=1)
        
        if 'RollingBest' in results:
            fig.add_trace(go.Scatter(
                x=x_index, y=results['RollingBest']['signal'], name='Best Strategy Position',
                line=dict(color='red', width=1.5, shape='hv', dash='dot')
            ), row=4, col=1)
        
        # Layout Config
        fig.update_layout(height=1200, hovermode="x unified", legend=dict(orientation="h", y=1.02, x=1, xanchor="right"))
        common_xaxis = dict(type='category', tickmode='auto', nticks=10, showgrid=True)
        fig.update_xaxes(row=1, col=1, **common_xaxis)
        fig.update_xaxes(row=2, col=1, showticklabels=False, **common_xaxis)
        fig.update_xaxes(row=3, col=1, showticklabels=False, **common_xaxis)
        fig.update_xaxes(row=4, col=1, matches='x2', **common_xaxis)
        fig.update_layout(xaxis2=dict(matches='x4'), xaxis3=dict(matches='x4'), xaxis4=dict(matches='x2'))
        
        return html.Div([
            metrics_row,
            html.Hr(),
            dcc.Graph(figure=fig)
        ])
