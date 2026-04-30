"""
Dashboard callbacks module
Contains all Dash application callback logic
"""

from dash import Input, Output, State, html, dcc
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dateutil.relativedelta import relativedelta

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
    run_atr_mean_reversion_strategy,
    run_sar_strategy,
    run_demark_strategy,
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
        [Output('oos-split-date', 'date'),
         Output('insample-lookback', 'options'),
         Output('insample-lookback', 'value')],
        [Input('trading-mode', 'value')]
    )
    def set_oos_defaults_and_lookback_options(trading_mode):
        """Set sensible defaults for split date and lookback based on trading mode."""
        today = pd.Timestamp.now().normalize()

        if trading_mode == 'intraday':
            # Monday of the present week
            oos_date = (today - pd.Timedelta(days=today.weekday())).date()
            options = [
                {'label': '1 Week', 'value': '1W'},
                {'label': '2 Weeks', 'value': '2W'},
                {'label': '1 Month', 'value': '1M'},
                {'label': '3 Months', 'value': '3M'},
            ]
            value = '1M'
        else:
            # First day of the present year
            oos_date = pd.Timestamp(year=today.year, month=1, day=1).date()
            options = [
                {'label': '6 Months', 'value': '6M'},
                {'label': '1 Year', 'value': '1Y'},
                {'label': '2 Years', 'value': '2Y'},
            ]
            value = '1Y'

        return oos_date, options, value
    
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
            State('atr-mult', 'value'),
         State('sar-af', 'value'),
         State('sar-max-af', 'value'),
            State('mr-trending-strategy', 'value'),
            State('mr-meanrev-strategy', 'value'),
         State('oos-split-date', 'date'),
         State('insample-lookback', 'value')]
    )
    def update_dashboard(n_clicks, source, trading_mode, wind_code, local_symbol, start_date, end_date, tf, 
                         selected_strategies,
                        ma_s, ma_l, boll_w, boll_std, boll_exit, vwap_w, mom_w, atr_ema_w, atr_w, atr_mult,
                         sar_af, sar_max_af,
                        mr_trending_strategy, mr_meanrev_strategy,
                         oos_split_date, insample_lookback):
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

        # --- User-configurable in-sample / out-of-sample split ---
        # - Daily default: Jan 1 of current year, lookback 1Y
        # - Intraday default: Monday of current week, lookback 1M
        # Defaults are set by set_oos_defaults_and_lookback_options().
        def _parse_lookback(value: str):
            if not value:
                return relativedelta(years=1)
            s = str(value).strip().upper()
            try:
                n = int(s[:-1])
                unit = s[-1]
            except Exception:
                return relativedelta(years=1)

            if unit == 'Y':
                return relativedelta(years=n)
            if unit == 'M':
                return relativedelta(months=n)
            if unit == 'W':
                return pd.Timedelta(weeks=n)
            if unit == 'D':
                return pd.Timedelta(days=n)
            return relativedelta(years=1)

        today = pd.Timestamp.now().normalize()
        oos_start_target = pd.to_datetime(oos_split_date).normalize() if oos_split_date else today
        lookback_delta = _parse_lookback(insample_lookback)

        if isinstance(lookback_delta, pd.Timedelta):
            insample_start_target = oos_start_target - lookback_delta
            rolling_best_lookback_months = max(1, int(round(lookback_delta.days / 30)))
        else:
            insample_start_target = oos_start_target - lookback_delta
            months = int(getattr(lookback_delta, 'months', 0) or 0) + int(getattr(lookback_delta, 'years', 0) or 0) * 12
            rolling_best_lookback_months = max(1, months if months else (12 if trading_mode == 'daily' else 1))

        # Clamp the in-sample start to available data
        min_ts = df_resampled.index.min()
        max_ts = df_resampled.index.max()
        insample_start_ts = max(insample_start_target, min_ts)
        # If the desired OOS start is beyond the data, fall back to the last date (still labels it)
        oos_start_ts = min(oos_start_target, max_ts)

        # Keep only the 1Y/1M window before the split + all data after
        df_resampled = df_resampled.loc[df_resampled.index >= insample_start_ts].copy()

        # Align OOS start to an actual index point (first timestamp >= target)
        oos_candidates = df_resampled.index[df_resampled.index >= oos_start_ts]
        if len(oos_candidates) == 0:
            return html.Div("No out-of-sample data available after split date", style={'color': 'red'})
        oos_start_idx = oos_candidates[0]

        # --- Market Regime Detection (fit on in-sample, predict full) ---
        regime_series = pd.Series(index=df_resampled.index, dtype=float)
        regime_label_series = pd.Series('trending', index=df_resampled.index, dtype=object)
        try:
            detector = RegimeDetector(n_states=2)
            features_all = detector.calculate_features(df_resampled, window=20)

            features_train = features_all.loc[(features_all.index >= insample_start_ts) & (features_all.index < oos_start_idx)]
            if len(features_train) < 30:
                features_train = features_all.loc[features_all.index < oos_start_idx]
            if len(features_train) < 10:
                features_train = features_all

            detector.fit(features_train)
            # Use prediction with confidence filtering and short-run smoothing
            try:
                labels, states, probs = detector.predict_with_confidence(features_all, prob_threshold=0.6, min_run_length=3)
                regime_series.loc[features_all.index] = states
                regime_label_series.loc[features_all.index] = labels.values
            except Exception as e:
                # Fallback to plain predict if new method fails for any reason
                states, _ = detector.predict(features_all)
                regime_map = detector.get_state_regime_map()
                regime_series.loc[features_all.index] = states
                regime_label_series.loc[features_all.index] = [regime_map.get(int(s), 'unknown') for s in states]
        except Exception as e:
            print(f"Regime detection error: {e}")
            
        # Run strategies
        results = {}
        
        if 'MA' in selected_strategies:
            results['MA'] = run_ma_strategy(df_resampled, ma_s, ma_l)
            
        mr_enabled = 'MarketRegime' in selected_strategies
        mr_trending = mr_trending_strategy or 'SAR'
        mr_meanrev = mr_meanrev_strategy or 'Boll'

        need_ma = ('MA' in selected_strategies) or (mr_enabled and mr_trending == 'MA')
        need_sar = ('SAR' in selected_strategies) or (mr_enabled and mr_trending == 'SAR')
        need_vwap = ('VWAP' in selected_strategies) or (mr_enabled and mr_trending == 'VWAP')
        need_mom = ('Momentum' in selected_strategies) or (mr_enabled and mr_trending == 'Momentum')
        need_boll = ('Boll' in selected_strategies) or (mr_enabled and mr_meanrev == 'Boll')
        need_atr = ('ATR' in selected_strategies) or (mr_enabled and mr_meanrev == 'ATR')
        need_demark = 'DeMark' in selected_strategies

        if need_ma:
            results['MA'] = run_ma_strategy(df_resampled, ma_s, ma_l)

        if need_sar:
            results['SAR'] = run_sar_strategy(df_resampled, sar_af, sar_max_af)

        if need_demark:
            results['DeMark'] = run_demark_strategy(df_resampled)

        if need_boll:
            exit_at_ma = 'exit' in (boll_exit or [])
            results['Boll'] = run_bollinger_strategy(df_resampled, boll_w, boll_std, exit_at_ma)
            
        if need_vwap:
            results['VWAP'] = run_vwap_strategy(df_resampled, vwap_w)
            
        if need_mom:
            results['Momentum'] = run_intraday_momentum_strategy(df_resampled, mom_w, vwap_w)
            
        if need_atr:
            results['ATR'] = run_atr_mean_reversion_strategy(df_resampled, atr_ema_w, atr_w, atr_mult=atr_mult)

        # Market Regime Based strategy: SAR in trending regime, Bollinger in mean-reverting
        if mr_enabled:
            if mr_trending not in results:
                return html.Div(f"Market Regime (Trending) strategy '{mr_trending}' is not available.", style={'color': 'red'})
            if mr_meanrev not in results:
                return html.Div(f"Market Regime (Mean-reverting) strategy '{mr_meanrev}' is not available.", style={'color': 'red'})

            trending_signal = results[mr_trending]['signal'].reindex(df_resampled.index).fillna(0)
            meanrev_signal = results[mr_meanrev]['signal'].reindex(df_resampled.index).fillna(0)

            use_trending = regime_label_series.reindex(df_resampled.index).fillna('trending').eq('trending')
            combined_signal = np.where(use_trending, trending_signal.values, meanrev_signal.values)
            active_substrategy = np.where(use_trending, mr_trending, mr_meanrev)

            df_mr = df_resampled.copy()
            df_mr['active_substrategy'] = active_substrategy
            df_mr['signal'] = combined_signal
            df_mr['position'] = df_mr['signal'].astype(float).diff()
            df_mr['returns'] = df_mr['close'].pct_change()
            df_mr['strategy_returns'] = df_mr['signal'].astype(float).shift(1) * df_mr['returns']
            df_mr['cumulative_returns'] = (1 + df_mr['strategy_returns'].fillna(0)).cumprod()

            results['MarketRegime'] = df_mr
        
        # Calculate metrics and build cards
        metric_cards = []
        
        # Define display order and titles
        strategy_meta = [
            ('MA', "MA Crossover"),
            ('SAR', "SAR"),
            ('DeMark', "DeMark TD Sequential"),
            ('Boll', "Bollinger Bands"),
            ('ATR', "ATR"),
            ('MarketRegime', "Market Regime Based"),
            ('VWAP', "VWAP"),
            ('Momentum', "Intraday Momentum"),
        ]
        
        for key, title in strategy_meta:
            if key in results and key in selected_strategies:
                # Out-of-sample metrics: start at OOS split date
                oos_df = results[key].loc[results[key].index >= oos_start_idx].copy()
                if not oos_df.empty:
                    oos_df['cumulative_returns'] = (1 + oos_df['strategy_returns'].fillna(0)).cumprod()
                    metrics = calculate_metrics(oos_df)
                else:
                    metrics = {}
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
        split_label = oos_start_idx.strftime('%Y-%m-%d<br>%H:%M')
        
        # Row 1: Price & Indicators
        fig.add_trace(go.Scatter(x=x_index, y=df_resampled['close'], name='Close Price', line=dict(color='black', width=2)), row=1, col=1)
        
        if 'MA' in results:
            df_ma = results['MA']
            fig.add_trace(go.Scatter(x=x_index, y=df_ma['ma_short'], name=f'MA{ma_s}', line=dict(color='orange', width=1), visible='legendonly'), row=1, col=1)
            fig.add_trace(go.Scatter(x=x_index, y=df_ma['ma_long'], name=f'MA{ma_l}', line=dict(color='blue', width=1), visible='legendonly'), row=1, col=1)

        if 'SAR' in results and 'SAR' in selected_strategies:
            df_sar = results['SAR']
            fig.add_trace(go.Scatter(x=x_index, y=df_sar['sar'], name='SAR', mode='markers', marker=dict(color='gray', size=3), visible='legendonly'), row=1, col=1)

        if 'DeMark' in results and 'DeMark' in selected_strategies:
            df_demark = results['DeMark']
            for col, color in [('tdst_support', '#2ecc71'), ('tdst_resistance', '#e74c3c')]:
                series = df_demark[col].dropna()
                if not series.empty:
                    fig.add_trace(go.Scatter(
                        x=series.index.strftime('%Y-%m-%d<br>%H:%M'),
                        y=series.values,
                        name='TDST Support' if col == 'tdst_support' else 'TDST Resistance',
                        line=dict(color=color, width=1.2, dash='dot')
                    ), row=1, col=1)

            marker_map = [
                ('buy_setup_complete', 'TD Buy Setup 9', 'triangle-up', '#27ae60', 'low'),
                ('sell_setup_complete', 'TD Sell Setup 9', 'triangle-down', '#c0392b', 'high'),
                ('buy_countdown_complete', 'TD Buy Countdown 13', 'star', '#2ecc71', 'low'),
                ('sell_countdown_complete', 'TD Sell Countdown 13', 'star', '#e74c3c', 'high'),
            ]
            for flag_col, name, symbol, color, price_col in marker_map:
                mask = df_demark[flag_col].eq(1)
                if mask.any():
                    fig.add_trace(go.Scatter(
                        x=df_demark.index[mask].strftime('%Y-%m-%d<br>%H:%M'),
                        y=df_demark.loc[mask, price_col],
                        name=name,
                        mode='markers',
                        marker=dict(symbol=symbol, color=color, size=10),
                    ), row=1, col=1)
            
        if 'Boll' in results and 'Boll' in selected_strategies:
            df_boll = results['Boll']
            fig.add_trace(go.Scatter(x=x_index, y=df_boll['upper_band'], name='Bollinger Upper', line=dict(color='green', width=1, dash='dot'), visible='legendonly'), row=1, col=1)
            fig.add_trace(go.Scatter(x=x_index, y=df_boll['lower_band'], name='Bollinger Lower', line=dict(color='red', width=1, dash='dot'), visible='legendonly'), row=1, col=1)

        if 'ATR' in results and 'ATR' in selected_strategies:
            df_atr = results['ATR']
            if 'atr_upper' in df_atr.columns and 'atr_lower' in df_atr.columns:
                # Show ATR bands by default (user requested visibility)
                fig.add_trace(go.Scatter(x=x_index, y=df_atr['atr_upper'], name='ATR Upper', line=dict(color='red', width=1, dash='solid')), row=1, col=1)
                fig.add_trace(go.Scatter(x=x_index, y=df_atr['atr_lower'], name='ATR Lower', line=dict(color='green', width=1, dash='solid')), row=1, col=1)
            
        if 'VWAP' in results:
            df_vwap = results['VWAP']
            fig.add_trace(go.Scatter(x=x_index, y=df_vwap['vwap'], name='VWAP', line=dict(color='purple', width=1, dash='dash'), visible='legendonly'), row=1, col=1)
            
        if 'Momentum' in results:
            df_mom = results['Momentum']
            fig.add_trace(go.Scatter(x=x_index, y=df_mom['upper_limit'], name='Momentum Upper', line=dict(color='cyan', width=1, dash='dashdot'), visible='legendonly'), row=1, col=1)
            fig.add_trace(go.Scatter(x=x_index, y=df_mom['lower_limit'], name='Momentum Lower', line=dict(color='magenta', width=1, dash='dashdot'), visible='legendonly'), row=1, col=1)

        # Row 2: Market Regime
        fig.add_trace(go.Scatter(
            x=x_index,
            y=regime_series,
            name='Regime State',
            mode='lines',
            line=dict(color='blue', width=2, shape='hv'),
            fill='tozeroy',
            fillcolor='rgba(100, 150, 200, 0.3)',
            customdata=regime_label_series,
            hovertemplate='Time: %{x}<br>State: %{y}<br>Regime: %{customdata}<extra></extra>'
        ), row=2, col=1)

        # Mark OOS split date on the regime subplot
        fig.add_vline(
            x=split_label,
            line_width=2,
            line_dash='dash',
            line_color='black',
            row=2,
            col=1
        )
        fig.add_annotation(
            x=split_label,
            y=1,
            xref='x2',
            yref='y2',
            text='OOS Start',
            showarrow=True,
            arrowhead=2,
            ax=20,
            ay=-30,
            font=dict(color='black'),
            bgcolor='rgba(255,255,255,0.7)'
        )

        # Row 3: Cumulative Returns
        colors = {'MA': 'blue', 'Boll': 'orange', 'VWAP': 'purple', 'Momentum': 'cyan', 'ATR': 'brown', 'SAR': 'pink', 'DeMark': '#16a085', 'MarketRegime': 'red'}
        widths = {'MarketRegime': 3}
        
        for key, title in strategy_meta:
            if key in results and key in selected_strategies:
                df_res = results[key]
                width = widths.get(key, 1)
                fig.add_trace(
                    go.Scatter(
                        x=x_index,
                        y=df_res['cumulative_returns'],
                        name=f'{title} Returns',
                        line=dict(color=colors.get(key, 'gray'), width=width)
                    ),
                    row=3,
                    col=1
                )
        
        # Row 4: Aggregated Position & Best Strategy Position
        agg_signal = pd.Series(0, index=df_resampled.index)
        for key in (selected_strategies or []):
            if key in results and key != 'MarketRegime':
                agg_signal += results[key]['signal']
                 
        fig.add_trace(go.Scatter(
            x=x_index, y=agg_signal, name='Aggregated Position', 
            line=dict(color='rgba(50, 50, 50, 0.8)', width=1.5, shape='hv'),
            fill='tozeroy', fillcolor='rgba(100, 100, 100, 0.2)'
        ), row=4, col=1)
        
        if 'MarketRegime' in results and 'MarketRegime' in selected_strategies:
            fig.add_trace(go.Scatter(
                x=x_index,
                y=results['MarketRegime']['signal'],
                name='Market Regime Based Position',
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
