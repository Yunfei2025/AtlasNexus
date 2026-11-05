# -*- coding: utf-8 -*-
"""Futures backtest callbacks: data source toggle, symbol selection, run backtest."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime

from dash import html, dcc, ctx, no_update
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

from ..data import THEME, FUTURES_AVAILABLE
from settings.paths import DIR_INPUT

try:
    from futures.backtest.data_loader import (
        load_wind_data, load_local_data_processed, resample_data, get_local_file_path,
    )
    from futures.backtest.strategies import (
        run_ma_strategy, run_bollinger_strategy, run_vwap_strategy,
        run_intraday_momentum_strategy, run_atr_band_strategy, run_sar_strategy,
        run_demark_strategy,
    )
    from futures.backtest.metrics import calculate_metrics, calculate_metrics_numeric
    from futures.backtest.costs import apply_costs, default_cost_bp, per_bar_volume, trade_stats
    from futures.backtest.walkforward import DEFAULT_PARAMS
    from futures.backtest.minute_bars import (
        TICK_DIR, list_contracts, load_index, load_minute_bars, resample_minute_bars,
    )
    from settings.futures import FuturesConfig
except ImportError:
    pass


# Saved params + best strategy per product, e.g. {"intraday:IC": {...}, "daily:TL.CFE": {...}}
SAVED_PARAMS_PATH = DIR_INPUT / 'futures_backtest_best.json'

# Param input ids, in the order bf_update_dashboard receives them
PARAM_IDS = ['bf-ma-short', 'bf-ma-long', 'bf-boll-window', 'bf-boll-std', 'bf-boll-exit',
             'bf-vwap-window', 'bf-mom-window', 'bf-atr-ema-window', 'bf-atr-window',
             'bf-sar-af', 'bf-sar-max-af']


def _product_key(mode, symbol):
    """Intraday contracts are saved by product (IC2612 -> IC) so the setting survives rolls."""
    if not symbol:
        return None
    if mode != 'daily':
        m = re.match(r'[A-Za-z]+', symbol)
        symbol = m.group().upper() if m else symbol
    return f"{mode}:{symbol}"


def _load_saved():
    try:
        return json.loads(SAVED_PARAMS_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save_entry(key, entry):
    data = _load_saved()
    data[key] = entry
    tmp = SAVED_PARAMS_PATH.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    tmp.replace(SAVED_PARAMS_PATH)


def _saved_start(entry, mode, symbol):
    """Start date to backtest a saved entry from. Intraday entries are saved per product, so
    another contract (e.g. TL2609 under a TL2612 save) starts from its own first trading day."""
    if mode == 'daily' or symbol == entry.get('symbol'):
        return entry.get('start')
    try:
        bars = load_minute_bars(symbol)
        return str(bars.index.min().date()) if bars is not None and len(bars) else None
    except Exception:
        return None


def _saved_note(key, entry):
    if not entry:
        return "No saved params for this product."
    return (f"Saved {key.split(':', 1)[1]} · best {entry['best']} @ {entry['timeframe']} "
            f"(Sharpe {entry['sharpe']:.2f}) · {entry['saved_at']}")


def register_backtest_futures_callbacks(app):
    """Register Futures backtest callbacks."""
    if getattr(app, "_atlasnexus_backtest_futures_callbacks_registered", False):
        return
    app._atlasnexus_backtest_futures_callbacks_registered = True

    @app.callback(
        [Output('bf-saved-note', 'children'),
         Output('bf-timeframe', 'value'),
         Output('bf-strategy-selector', 'value'),
         Output('bf-date-range', 'start_date')] +
        [Output(pid, 'value') for pid in PARAM_IDS],
        [Input('bf-save-button', 'n_clicks'),
         Input('bf-local-symbol', 'value'),
         Input('bf-wind-code', 'value')],
        [State('bf-data-source', 'value'),
         State('bf-trading-mode', 'value'),
         State('bf-last-run', 'data')],
        prevent_initial_call=True,
    )
    def bf_save_or_restore_params(_n, local_symbol, wind_code, source, mode, last_run):
        skip = [no_update] * (3 + len(PARAM_IDS))
        if ctx.triggered_id == 'bf-save-button':
            if not last_run or not last_run.get('sharpe'):
                return ["Run a backtest first, then save."] + skip
            best = max(last_run['sharpe'], key=last_run['sharpe'].get)
            key = _product_key(last_run['mode'], last_run['symbol'])
            entry = {
                'best': best, 'sharpe': last_run['sharpe'][best],
                'timeframe': last_run['timeframe'], 'strategies': last_run['strategies'],
                'params': last_run['params'], 'symbol': last_run['symbol'],
                'start': last_run['start'], 'end': last_run['end'],
                'saved_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
            }
            old = _load_saved().get(key) or {}
            if old.get('tested'):  # keep the saved sweep grid when re-saving params
                entry['tested'] = old['tested']
            try:
                _save_entry(key, entry)
            except Exception as e:
                return [f"Save failed: {e}"] + skip
            return [_saved_note(key, entry)] + skip

        # Symbol changed: restore the saved params into the panel
        symbol = wind_code if source == 'wind' else local_symbol
        key = _product_key(mode, symbol)
        entry = _load_saved().get(key) if key else None
        if not entry:
            return [_saved_note(key, None) if key else ""] + skip
        tf = entry['timeframe'] if mode != 'daily' else no_update
        # Restore the saved start date (the 30-day default is too short for daily bars)
        return ([_saved_note(key, entry), tf, entry['strategies'],
                 _saved_start(entry, mode, symbol) or no_update] +
                [entry['params'].get(pid, no_update) for pid in PARAM_IDS])

    @app.callback(
        Output('bf-results-symbol', 'children'),
        [Input('bf-local-symbol', 'value'), Input('bf-wind-code', 'value'),
         Input('bf-data-source', 'value'), Input('bf-trading-mode', 'value')],
    )
    def bf_symbol_badges(local_symbol, wind_code, source, mode):
        symbol = wind_code if source == 'wind' else local_symbol
        return f"{symbol} · {mode}" if symbol else ""

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
                # Local source lists the tick files here plus the shared minute-bar cache (no Wind
                # lookup); the Wind source keeps its own dropdown. Default = the most recent data.
                contract_list = list_contracts()
                idx = load_index()

                def _recency(c):
                    tick = TICK_DIR / f'{c}.pkl'
                    return idx.get(c, {}).get('last') or '', tick.stat().st_mtime if tick.exists() else 0, c

                opts = [{'label': c, 'value': c} for c in contract_list]
                def_val = max(contract_list, key=_recency) if contract_list else None
            return opts, def_val
        except Exception:
             return [], None

    @app.callback(
        [Output('bf-results-container', 'children'),
         Output('bf-perf-results-container', 'children'),
         Output('bf-last-run', 'data')],
        [Input('bf-run-button', 'n_clicks'),
         Input('bf-local-symbol', 'value'),
         Input('bf-drill', 'data')],
        [State('bf-data-source', 'value'),
         State('bf-trading-mode', 'value'),
         State('bf-wind-code', 'value'),
         State('bf-date-range', 'start_date'),
         State('bf-date-range', 'end_date'),
         State('bf-timeframe', 'value'),
         State('bf-strategy-selector', 'value'),
         State('bf-cost-bp', 'value'),
         State('bf-legacy', 'value')] +
        [State(pid, 'value') for pid in PARAM_IDS]
    )
    def bf_update_dashboard(n_clicks, local_symbol, drill, source, trading_mode, wind_code, start_date, end_date, tf,
                            selected_strategies, cost_bp, legacy, *param_values):
        if ctx.triggered_id == 'bf-drill':
            # A walk-forward candidate was clicked: that strategy at default parameters, on that contract's
            # whole history, with the same cost and flat-at-close accounting the walk-forward used.
            out = _bf_dashboard('local', 'intraday', drill['contract'], None, drill['start'], drill['end'],
                                drill['timeframe'], [drill['strategy']], dict(DEFAULT_PARAMS), True, None,
                                drill['cost_bp'], False)
            return out if len(out) == 3 else (*out, no_update)
        params = dict(zip(PARAM_IDS, param_values))
        # Run button: run the selected strategies. Symbol load: run all saved strategies
        # with their saved params (saved best marked ★) if there is one, else show price only.
        run_strategies = ctx.triggered_id == 'bf-run-button'
        symbol = wind_code if source == 'wind' else local_symbol
        key = _product_key(trading_mode, symbol)
        saved = _load_saved().get(key) if key else None
        saved_best = None
        if not run_strategies:
            if saved:
                run_strategies = True
                selected_strategies = saved['strategies']
                saved_best = saved['best']
                params.update(saved['params'])
                start_date = _saved_start(saved, trading_mode, symbol) or start_date
                if trading_mode != 'daily':
                    tf = saved['timeframe']
        # Blank cost = the product's measured default; legacy = the old gross, overnight-held accounting
        legacy = bool(legacy)
        cost_bp = 0.0 if legacy else (default_cost_bp(symbol) if cost_bp is None else float(cost_bp))
        out = _bf_dashboard(source, trading_mode, local_symbol, wind_code, start_date, end_date, tf,
                            selected_strategies, params, run_strategies, saved_best, cost_bp, legacy)
        out = out if len(out) == 3 else (*out, no_update)
        return out

    def _bf_dashboard(source, trading_mode, local_symbol, wind_code, start_date, end_date, tf,
                      selected_strategies, params, run_strategies, saved_best=None, cost_bp=0.0, legacy=True):
        (ma_s, ma_l, boll_w, boll_std, boll_exit, vwap_w, mom_w, atr_ema_w, atr_w,
         sar_af, sar_max_af) = (params[pid] for pid in PARAM_IDS)

        if not FUTURES_AVAILABLE:
            return html.Div("Modules not loaded.", style={'color': THEME['danger']}), None

        selected_strategies = selected_strategies or []
        effective_tf = '1D' if trading_mode == 'daily' else tf

        # Load Data
        df = None
        err_msg = None
        from_minutes = False

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

                # Intraday: minute bars (tick file, or the shared cache when the ticks are on another
                # computer). Legacy keeps the old tick path when the tick file is here.
                from_minutes = trading_mode != 'daily' and not (legacy and os.path.exists(file_path))
                if from_minutes:
                    df = load_minute_bars(local_symbol)
                    err_msg = None if df is not None else f"no tick file or cached minute bars for {local_symbol}"
                else:
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
            elif source != 'wind' and from_minutes:
                df_resampled = resample_minute_bars(df, effective_tf)
            else:
                if not legacy:
                    df = df.assign(volume=per_bar_volume(df))
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
                if 'Momentum' in selected_strategies:
                    results['Momentum'] = run_intraday_momentum_strategy(df_resampled, mom_w, vwap_w)
                if 'ATR' in selected_strategies:
                    results['ATR'] = run_atr_band_strategy(df_resampled, atr_ema_w, atr_w)
                if 'SAR' in selected_strategies:
                    results['SAR'] = run_sar_strategy(df_resampled, sar_af, sar_max_af)

            if not legacy:
                results = {name: apply_costs(res, cost_bp, flat_at_close=effective_tf != '1D')
                           for name, res in results.items()}

            # Create Plotly Chart — 2 rows when strategies present, 1 row for default price view
            if results:
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                    vertical_spacing=0.03, row_heights=[0.7, 0.3])
            else:
                fig = make_subplots(rows=1, cols=1)

            # Intraday: plot on a category axis so lunch breaks, overnight,
            # weekends and holidays collapse and trading-hour bars sit side by side.
            intraday = effective_tf != '1D'

            def _x(index):
                return index.strftime('%Y-%m-%d %H:%M') if intraday else index

            # Candlestick
            fig.add_trace(go.Candlestick(
                x=_x(df_resampled.index),
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
                            x=_x(series.index),
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
                            x=_x(df_demark.index[mask]),
                            y=df_demark.loc[mask, price_col],
                            mode='markers',
                            name=name,
                            marker=dict(symbol=symbol, color=color, size=10)
                        ), row=1, col=1)
            
            # Best strategy = highest Sharpe (same figure as the Performance table)
            strategy_metrics = {name: calculate_metrics(res) for name, res in results.items()}
            for name, res in results.items():
                ts = trade_stats(res, cost_bp)
                strategy_metrics[name].update({
                    'Win Rate': '—' if ts['win'] != ts['win'] else f"{ts['win'] * 100:.0f}%",
                    'Payoff': '—' if ts['payoff'] != ts['payoff'] else f"{ts['payoff']:.2f}",
                    'Exp/Trade': '—' if ts['expectancy_bp'] != ts['expectancy_bp'] else f"{ts['expectancy_bp']:+.1f}bp",
                    'Round Trips': ts['trades'],
                })
            sharpes = {}
            for name, m in strategy_metrics.items():
                try:
                    sharpes[name] = float(m['Sharpe Ratio'])
                except (KeyError, TypeError, ValueError):
                    pass
            best = max(sharpes, key=sharpes.get) if sharpes else None
            if saved_best in results:  # on load, ★ marks the saved choice
                best = saved_best

            # Strategy Equity Curves (only when strategies were run)
            for name, res in results.items():
                fig.add_trace(go.Scatter(
                    x=_x(res.index),
                    y=res['cumulative_returns'],
                    mode='lines', name=f'★ {name} Equity' if name == best else f'{name} Equity',
                    line=dict(width=3 if name == best else 1.5),
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
            if intraday:
                # One tick per trading day (thinned to ~8 labels) on the first bar of the day
                labels = _x(df_resampled.index)
                day_starts = labels[~df_resampled.index.normalize().duplicated()]
                step = max(1, len(day_starts) // 8)
                fig.update_xaxes(
                    type='category', categoryorder='array', categoryarray=list(labels),
                    tickmode='array', tickvals=list(day_starts[::step]),
                    ticktext=[t[:10] for t in day_starts[::step]], tickangle=0, tickfont={'size': 10},
                )
            fig.update_yaxes(gridcolor='rgba(100,140,200,0.12)')

            # ── Strategy Performance table (matches BetaFutures.jsx METRIC rows) ──
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
                acct = ("Legacy accounting: no costs, positions held overnight." if legacy else
                        f"Net of {cost_bp:.2f}bp per side" + (", flat at each close." if intraday else "."))
                strategy_table = html.Div(style={'overflowX': 'auto'}, children=[
                    html.Div(acct, style={'fontSize': '9px', 'color': 'var(--text-muted)', 'marginBottom': '4px'}),
                    html.Table([
                        html.Thead(html.Tr(
                            [html.Th("METRIC", style={**_th_style, 'textAlign': 'left'})] +
                            [html.Th(f"★ {name.upper()}" if name == best else name.upper(),
                                     style={**_th_style, 'color': 'var(--accent-blue)'} if name == best else _th_style)
                             for name in strategy_metrics]
                        , style={'background': 'var(--surface-panel)', 'borderBottom': '1px solid var(--border-strong)'})),
                        html.Tbody([
                            _metric_row("Return", "Total Return",
                                        color_fn=lambda v: '#34d399' if _is_positive(v) else '#f87171'),
                            _metric_row("Max DD", "Max Drawdown",
                                        color_fn=lambda v: '#f87171'),
                            _metric_row("Sharpe", "Sharpe Ratio",
                                        color_fn=lambda v: '#34d399' if not str(v).strip().startswith('-') else '#f87171'),
                            _metric_row("Trades", "Trades"),
                            _metric_row("Round trips", "Round Trips"),
                            _metric_row("Win rate", "Win Rate"),
                            _metric_row("Payoff", "Payoff"),
                            _metric_row("Exp / trade", "Exp/Trade",
                                        color_fn=lambda v: '#34d399' if str(v).startswith('+') else '#f87171'),
                        ]),
                    ], style={'width': '100%', 'borderCollapse': 'collapse'}),
                ])
            else:
                strategy_table = html.Div(
                    "No results. Click ▶ Run Backtest to start.",
                    style={'color': 'var(--text-muted)', 'fontSize': '10px', 'padding': '4px 0'},
                )

            last_run = {
                'symbol': wind_code if source == 'wind' else local_symbol, 'mode': trading_mode,
                'timeframe': effective_tf, 'strategies': list(selected_strategies), 'params': params,
                'sharpe': sharpes, 'start': str(start_date)[:10], 'end': str(end_date)[:10],
            } if sharpes else no_update
            return dcc.Graph(figure=fig, config={'displayModeBar': False}), strategy_table, last_run

        except Exception as e:
            import traceback
            traceback.print_exc()
            return html.Div(f"Error running backtest: {str(e)}", style={'color': THEME['danger']}), None

