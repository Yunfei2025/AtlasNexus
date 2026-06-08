# -*- coding: utf-8 -*-
"""Risk-factor backtest (RFBT) callbacks: parameter panels, generate factor-rates.pkl,
and run the factor-model backtest."""

from __future__ import annotations

import dash
import numpy as np
from dash import html, dcc, dash_table
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from settings.paths import DIR_INPUT

from ..data import THEME
from ._rfbt_train_helpers import (
    _config_matches,
    _compute_factor_stats,
    _render_signal_cards,
    _build_results_from_saved_artifact,
    _build_top_drivers,
)


def register_backtest_rfbt_callbacks(app):
    """Register Risk Factor Backtest (BACKTEST subtab) callbacks."""

    # ================================================================
    # Risk Factor Backtest callbacks (BACKTEST subtab)
    # ================================================================

    # Factor options grouped by asset class (mirrors the Factor History sidebar)
    _RFBT_FACTOR_OPTIONS = {
        'Rates': [
            {'label': 'IRDL.CN — China Level',       'value': 'IRDL.CN'},
            {'label': 'IRSL.CN — China Slope',        'value': 'IRSL.CN'},
            {'label': 'IRCV.CN — China Curvature',    'value': 'IRCV.CN'},
            {'label': 'IRDL.US — US Level',           'value': 'IRDL.US'},
            {'label': 'IRSL.US — US Slope',           'value': 'IRSL.US'},
            {'label': 'IRDL.DE — Europe Level',       'value': 'IRDL.DE'},
            {'label': 'IRDL.JP — Japan Level',        'value': 'IRDL.JP'},
            {'label': 'IRDL.UK — UK Level',           'value': 'IRDL.UK'},
        ],
        'Spread': [
            {'label': 'SPDL.IRS — IRS Level',        'value': 'SPDL.IRS'},
            {'label': 'SPSL.IRS — IRS Slope',         'value': 'SPSL.IRS'},
            {'label': 'SPDL.CDB — CDB Level',         'value': 'SPDL.CDB'},
            {'label': 'SPSL.CDB — CDB Slope',         'value': 'SPSL.CDB'},
            {'label': 'SPDL.ICP — ICP Level',         'value': 'SPDL.ICP'},
        ],
        'FX': [
            {'label': 'FXDL.USDCNY',                 'value': 'FXDL.USDCNY'},
            {'label': 'FXDL.EURCNY',                 'value': 'FXDL.EURCNY'},
            {'label': 'FXDL.JPYCNY',                 'value': 'FXDL.JPYCNY'},
            {'label': 'FXDL.GBPCNY',                 'value': 'FXDL.GBPCNY'},
        ],
        'Commodities': [
            {'label': 'CMDL.AU — Gold',              'value': 'CMDL.AU'},
            {'label': 'CMDL.CU — Copper',            'value': 'CMDL.CU'},
            {'label': 'CMDL.AL — Aluminium',         'value': 'CMDL.AL'},
            {'label': 'CMDL.SC — Crude Oil',         'value': 'CMDL.SC'},
        ],
    }

    @app.callback(
        [Output('rfbt-factor', 'options'),
         Output('rfbt-factor', 'value')],
        Input('rfbt-asset-class', 'value'),
    )
    def update_rfbt_factor_options(asset_class):
        """Cascade: populate the Factor dropdown when Asset Class changes."""
        opts = _RFBT_FACTOR_OPTIONS.get(asset_class, [])
        default = opts[0]['value'] if opts else None
        return opts, default

    @app.callback(
        [Output('rfbt-ma-params', 'style'),
         Output('rfbt-boll-params', 'style'),
         Output('rfbt-mom-params', 'style'),
         Output('rfbt-zscore-params', 'style'),
         Output('rfbt-fm-params', 'style')],
        Input('rfbt-strategy-selector', 'data'),
    )
    def toggle_rfbt_strategy_params(strategy):
        """Show/hide strategy-specific parameter inputs."""
        flex = {'display': 'flex', 'alignItems': 'center', 'flexWrap': 'wrap', 'gap': '8px'}
        hide = {'display': 'none'}
        return (hide, hide, hide, hide, flex)

    @app.callback(
        Output('rfbt-status', 'children', allow_duplicate=True),
        Input('rfbt-generate-btn', 'n_clicks'),
        prevent_initial_call=True,
    )
    def generate_factor_rates_click(n_clicks):
        """Generate (or regenerate) factor-rates.pkl."""
        if not n_clicks:
            raise dash.exceptions.PreventUpdate
        try:
            from multiasset.factor_backtest import generate_factor_rates
            df = generate_factor_rates(DIR_INPUT, save=True)
            return f"✅ factor-rates.pkl saved ({df.shape[1]} factors, {len(df)} days)"
        except Exception as e:
            return f"❌ Error: {e}"

    @app.callback(
        [Output('rfbt-results-container', 'children'),
         Output('rfbt-status', 'children')],
        Input('rfbt-run-btn', 'n_clicks'),
        [State('rfbt-factor', 'value'),
         State('rfbt-strategy-selector', 'data'),
         State('rfbt-period-years', 'value'),
         State('rfbt-custom-start', 'date'),
         State('rfbt-custom-end', 'date'),
         State('rfbt-ma-short', 'value'),
         State('rfbt-ma-long', 'value'),
         State('rfbt-boll-window', 'value'),
         State('rfbt-boll-std', 'value'),
         State('rfbt-mom-window', 'value'),
         State('rfbt-zscore-window', 'value'),
         State('rfbt-zscore-entry', 'value'),
         State('rfbt-zscore-exit', 'value'),
         State('rfbt-fm-train', 'value'),
         State('rfbt-fm-ic', 'value'),
         State('rfbt-fm-topn', 'value'),
         State('rfbt-fm-sizing', 'value'),
         State('rfbt-fm-possmooth', 'value')],
        prevent_initial_call=True,
    )
    def run_risk_factor_backtest(
        n_clicks, factor_val, strategy, period_years,
        custom_start, custom_end,
        ma_short, ma_long, boll_window, boll_std,
        mom_window, zscore_window, zscore_entry, zscore_exit,
        fm_train, fm_ic, fm_topn, fm_sizing, fm_possmooth,
    ):
        if not n_clicks or not factor_val:
            raise dash.exceptions.PreventUpdate

        # Custom date pickers override the lookback dropdown when set
        factors = [factor_val]
        from datetime import date as _date_cls, timedelta
        end_date   = custom_end   if custom_end   else _date_cls.today().isoformat()
        if custom_start:
            start_date = custom_start
        else:
            years      = int(period_years or 2)
            start_date = (_date_cls.today() - timedelta(days=years * 365)).isoformat()

        try:
            from multiasset.factor_backtest import (
                run_factor_backtest, compute_metrics, get_factor_duration,
                _is_yield_factor, get_factor_weighted_duration,
            )

            strategy = 'FactorModel'
            kwargs = {'train_months': int(fm_train or 12),
                      'ic_threshold': float(fm_ic or 0.05),
                      'top_n': int(fm_topn or 8),
                      'sizing_mode': fm_sizing or 'discrete',
                      'position_smooth_window': int(fm_possmooth or 10)}

            results, _ = run_factor_backtest(
                factors=factors,
                strategy=strategy,
                start_date=start_date,
                end_date=end_date,
                input_dir=DIR_INPUT,
                save=True,
                **kwargs,
            )

            if not results:
                return (
                    html.Div("No results — check that factor-rates.pkl exists and factors have data.",
                             style={'color': THEME['warning'], 'padding': '20px'}),
                    "⚠️ No factors produced results",
                )

            # ── Compute IC statistics and current signal state per factor ──
            colors = ['#3498db', '#e74c3c', '#2ecc71', '#f39c12',
                      '#9b59b6', '#1abc9c', '#e67e22', '#34495e',
                      '#E91E63', '#00BCD4']

            factor_stats = {}
            for factor, df in results.items():
                pred = df['predicted_return'].dropna()
                sig  = df['signal'].dropna()

                last_signal   = float(sig.iloc[-1]) if not sig.empty  else 0.0
                last_pred_val = float(pred.iloc[-1]) if not pred.empty else 0.0

                # Z-score of latest prediction vs trailing 252 days
                pred_hist = pred.tail(252)
                z_score = ((last_pred_val - pred_hist.mean()) / (pred_hist.std() + 1e-8)
                           if len(pred_hist) > 5 else 0.0)
                scalar = max(0.5, min(2.0, abs(z_score)))

                # IC: 60-day rolling correlation(predicted_return_t, return_{t+1})
                # 60-day window (≈3 months) reduces noise vs 20-day; EWMA added to chart
                actual_fwd = df['returns'].shift(-1).reindex(df.index)
                ic_rolling = df['predicted_return'].rolling(60).corr(actual_fwd).dropna()
                mean_ic  = float(ic_rolling.mean()) if len(ic_rolling) > 0 else 0.0
                ic_std   = float(ic_rolling.std())  if len(ic_rolling) > 1 else 1.0
                icir     = mean_ic / (ic_std + 1e-8)
                ic_hit   = float((ic_rolling > 0).mean()) if len(ic_rolling) > 0 else 0.0
                n_ic     = len(ic_rolling)
                ic_tstat = mean_ic / (ic_std / (n_ic ** 0.5) + 1e-8) if n_ic > 1 else 0.0

                factor_stats[factor] = {
                    'last_signal': last_signal,
                    'z_score':     z_score,
                    'scalar':      scalar,
                    'mean_ic':     mean_ic,
                    'icir':        icir,
                    'ic_hit':      ic_hit,
                    'ic_tstat':    ic_tstat,
                    'ic_rolling':  ic_rolling,
                }

            # ── Section 2: Performance + IC statistics table ────────────
            metric_rows = []
            for factor, df in results.items():
                m   = compute_metrics(df)
                if 'strategy_returns_gross' in df.columns:
                    m_gross = compute_metrics(df.assign(strategy_returns=df['strategy_returns_gross']))
                else:
                    m_gross = m
                avg_turnover = float(df['turnover'].abs().mean()) if 'turnover' in df.columns else 0.0
                # Max daily position move in B/day (position ±1 = ±10B → ×10). Feasibility check.
                if 'position' in df.columns:
                    max_dpos_b = float(df['position'].diff().abs().max()) * 10.0
                else:
                    max_dpos_b = 0.0
                s   = factor_stats[factor]
                # Weighted duration — rates factors only (IRDL/IRSL/IRCV)
                w_dur = get_factor_weighted_duration(factor)
                dur_str = f"{w_dur:.2f}y" if w_dur is not None else '—'
                metric_rows.append({
                    'Factor':    factor,
                    'Duration':  dur_str,
                    'Ann Ret':   f"{m.get('Ann. Return', 0):.2%}",
                    'Ann Vol':   f"{m.get('Ann. Vol', 0):.2%}",
                    'Sharpe':    f"{m.get('Sharpe', 0):.2f}",
                    'Sharpe(gr)':f"{m_gross.get('Sharpe', 0):.2f}",
                    'Avg Turn':  f"{avg_turnover:.2f}",
                    'Max ΔPos (B/day)': f"{max_dpos_b:.2f}",
                    'Max DD':    f"{m.get('Max Drawdown', 0):.2%}",
                    'Win%':      f"{m.get('Win Rate', 0):.1%}",
                    'Mean IC':   f"{s['mean_ic']:.4f}",
                    'ICIR':      f"{s['icir']:.2f}",
                    'IC t-stat': f"{s['ic_tstat']:.2f}",
                    'IC Hit%':   f"{s['ic_hit']:.1%}",
                })

            metrics_table = dash_table.DataTable(
                data=metric_rows,
                columns=[{'name': c, 'id': c} for c in metric_rows[0].keys()],
                style_cell={'textAlign': 'center', 'padding': '6px 8px',
                            'backgroundColor': THEME['bg_input'],
                            'color': THEME['text_main'], 'border': 'none',
                            'fontSize': '11px'},
                style_header={'backgroundColor': THEME['table_header'],
                              'fontWeight': 'bold', 'color': THEME['accent'],
                              'border': 'none'},
                style_data_conditional=[
                    {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['table_row_even']},
                ],
                style_table={'overflowX': 'auto', 'marginBottom': '16px'},
            )

            # ── Sections 3+: Per-factor stacked 5-panel charts ──────────
            # One figure per factor, 5 rows with shared x-axis so all panels
            # are vertically aligned: Level | Signal | Position | IC | PnL.
            # signal is now a continuous target in [-1,1]; colour bars by sign
            def _sig_color(v):
                if v > 0:
                    return THEME['success']
                if v < 0:
                    return THEME['danger']
                return THEME['text_sub']
            _panel_base = dict(
                template=THEME['chart_template'],
                paper_bgcolor=THEME['bg_main'],
                plot_bgcolor=THEME['bg_main'],
                font={'color': THEME['text_main']},
                hovermode='x unified',
                margin=dict(l=60, r=30, t=50, b=30),
            )

            per_factor_divs = []
            for factor, df in results.items():
                s = factor_stats[factor]
                ic_s = s['ic_rolling']
                pos_col = 'position' if 'position' in df.columns else 'signal'

                fig = make_subplots(
                    rows=5, cols=1,
                    shared_xaxes=True,
                    vertical_spacing=0.04,
                    row_heights=[0.22, 0.16, 0.16, 0.22, 0.24],
                    subplot_titles=[
                        'Historical Level',
                        'Signal Level  (−1 … +1, 0.2 tick)',
                        'Position  (smoothed · ≤2B/day)',
                        'Rolling 60-day IC',
                        'Cumulative PnL',
                    ],
                )

                # Row 1: factor level
                if 'level' in df.columns:
                    fig.add_trace(go.Scatter(
                        x=df.index, y=df['level'].values, mode='lines',
                        line={'color': THEME['accent'], 'width': 1.5},
                        name='Level', showlegend=False,
                    ), row=1, col=1)

                # Row 2: signal bar chart
                sig = df['signal'].dropna()
                bar_colors = [_sig_color(v) for v in sig.values]
                fig.add_trace(go.Bar(
                    x=sig.index, y=sig.values,
                    marker_color=bar_colors,
                    name='Signal', showlegend=False,
                ), row=2, col=1)

                # Row 3: continuous position
                pos = df[pos_col].dropna()
                fig.add_trace(go.Scatter(
                    x=pos.index, y=pos.values, mode='lines',
                    line={'color': '#f39c12', 'width': 1.5},
                    name='Position', showlegend=False,
                    fill='tozeroy', fillcolor='rgba(243,156,18,0.10)',
                ), row=3, col=1)
                # zero line for position panel
                fig.add_hline(y=0, line_width=0.8, line_dash='dash',
                              line_color='gray', row=3, col=1)

                # Row 4: rolling IC (raw dotted + EWMA solid) + zero line
                if ic_s is not None and len(ic_s) > 0:
                    fig.add_trace(go.Scatter(
                        x=ic_s.index, y=ic_s.values, mode='lines',
                        line={'color': '#9b59b6', 'width': 1, 'dash': 'dot'},
                        opacity=0.55, name='IC (raw)', showlegend=False,
                    ), row=4, col=1)
                    ic_ewma = ic_s.ewm(span=20, min_periods=10).mean()
                    fig.add_trace(go.Scatter(
                        x=ic_ewma.index, y=ic_ewma.values, mode='lines',
                        line={'color': '#9b59b6', 'width': 2},
                        name='IC EWMA-20', showlegend=False,
                    ), row=4, col=1)
                    fig.add_hline(y=0, line_width=0.8, line_dash='dash',
                                  line_color='gray', row=4, col=1)

                # Row 5: cumulative PnL (net) + gross if available
                cum = df['cumulative_returns'].dropna()
                fig.add_trace(go.Scatter(
                    x=cum.index, y=cum.values, mode='lines',
                    line={'color': THEME['success'], 'width': 2},
                    name='PnL (net)', showlegend=False,
                ), row=5, col=1)
                if 'strategy_returns_gross' in df.columns:
                    cum_gr = (1 + df['strategy_returns_gross'].fillna(0)).cumprod().reindex(cum.index)
                    fig.add_trace(go.Scatter(
                        x=cum_gr.index, y=cum_gr.values, mode='lines',
                        line={'color': THEME['success'], 'width': 1, 'dash': 'dot'},
                        opacity=0.55, name='PnL (gross)', showlegend=False,
                    ), row=5, col=1)

                grid = dict(gridcolor=THEME['table_header'])
                fig.update_xaxes(**grid)
                fig.update_yaxes(**grid)
                fig.update_layout(
                    height=900,
                    title=dict(text=factor, font={'size': 14, 'color': THEME['accent']}),
                    bargap=0,
                    **_panel_base,
                )

                per_factor_divs.append(
                    html.Div([
                        dcc.Graph(figure=fig,
                                  config={'displayModeBar': False},
                                  style={'width': '100%'}),
                    ], style={
                        'backgroundColor': THEME['bg_card'],
                        'border': f'1px solid {THEME["table_header"]}',
                        'borderRadius': '8px',
                        'padding': '12px',
                        'marginBottom': '20px',
                    })
                )

            mean_icir = (sum(s['icir'] for s in factor_stats.values()) /
                         len(factor_stats)) if factor_stats else 0.0
            # Surface incremental-save info: joblib merges, other factors are retained
            try:
                from multiasset.factor_model import load_latest_factor_model
                art, mkey = load_latest_factor_model()
                n_total = len([k for k in (art or {}) if k != 'metadata'])
                n_new   = len(results)
                n_kept  = n_total - n_new
                save_note = (f"model {mkey}: {n_new} updated + {n_kept} retained = "
                             f"{n_total} total factors in .joblib")
            except Exception:
                save_note = f"{len(results)} factor(s) saved"
            status_msg = (f"✅ {save_note} · Mean ICIR: {mean_icir:.2f}")

            result_children = [
                html.H6("Performance & IC Statistics",
                        style={'color': THEME['accent'], 'marginBottom': '8px'}),
                metrics_table,
                html.H6("Factor Detail  —  Historical · Signal · Position · IC · PnL",
                        style={'color': THEME['accent'],
                               'marginBottom': '12px', 'marginTop': '8px'}),
                html.Div(per_factor_divs),
            ]

            return html.Div(result_children), status_msg

        except Exception as e:
            import traceback
            traceback.print_exc()
            return (
                html.Div(f"Error: {e}",
                         style={'color': THEME['danger'], 'padding': '20px'}),
                f"❌ {e}",
            )

    # ================================================================
    # Factor tab: Train Model (Latest Signal) callback
    # ================================================================

    @app.callback(
        [Output('factor-signal-container', 'children'),
         Output('factor-train-status', 'children'),
         Output('factor-signals-snapshot-store', 'data', allow_duplicate=True)],
        [Input('factor-train-btn', 'n_clicks'),
         Input('factor-predict-btn', 'n_clicks')],
        [State('factor-selection-store', 'data'),
         State('factor-fm-train', 'value'),
         State('factor-fm-ic', 'value'),
         State('factor-fm-topn', 'value')],
        prevent_initial_call=True,
    )
    def train_factor_model_for_factor_tab(train_clicks, predict_clicks, store_data, fm_train, fm_ic, fm_topn):
        from datetime import date as _date

        if not train_clicks and not predict_clicks:
            raise dash.exceptions.PreventUpdate

        trigger_id = getattr(dash.callback_context, 'triggered_id', None)
        action = 'predict' if trigger_id == 'factor-predict-btn' else 'train'

        store_data = store_data or {}
        factors = list(dict.fromkeys(
            store_data.get('ir', []) +
            store_data.get('fx', []) +
            store_data.get('cmd', [])
        ))
        if not factors:
            return (
                html.Div("No factors selected. Please select factors in the Factor Selection Pool.",
                         style={'color': THEME['warning'], 'padding': '12px'}),
                "⚠️ No factors selected",
                dash.no_update,
            )

        end_date = _date.today().replace(day=1).isoformat()

        current_cfg = {
            'train_months': int(fm_train or 12),
            'ic_threshold': float(fm_ic or 0.05),
            'top_n': int(fm_topn or 8),
            'signal_smooth_days': 5,
            'sizing_mode': 'discrete',
            'position_smooth_window': 10,
        }

        try:
            from multiasset.factor_backtest import run_factor_backtest, compute_metrics
            from multiasset.factor_model import load_latest_factor_model

            results = {}
            latest_artifact = None
            persist_note = None

            if action == 'predict':
                latest_artifact, latest_month_key = load_latest_factor_model()
                if not latest_artifact:
                    return (
                        html.Div(
                            "No saved model found. Click Train Model first to create the latest .joblib snapshot.",
                            style={'color': THEME['warning'], 'padding': '20px'}
                        ),
                        "⚠️ No saved model found",
                        dash.no_update,
                    )
                saved_cfg = latest_artifact.get('metadata', {}).get('config', {})
                if not _config_matches(saved_cfg, current_cfg):
                    return (
                        html.Div(
                            "Saved model parameters do not match the current settings. Click Train Model to refresh the snapshot.",
                            style={'color': THEME['warning'], 'padding': '20px'}
                        ),
                        "⚠️ Saved model does not match current parameters",
                        dash.no_update,
                    )
                smooth_days = int(saved_cfg.get('signal_smooth_days', current_cfg['signal_smooth_days']))

                # ── Split: factors already in artifact vs newly selected ──
                artifact_factors = {k for k in latest_artifact if k != 'metadata'}
                covered_factors = [f for f in factors if f in artifact_factors]
                missing_factors = [f for f in factors if f not in artifact_factors]

                # Predict covered factors from saved artifact (fast, no retrain)
                results = _build_results_from_saved_artifact(
                    latest_artifact, smooth_days, factors, factor_subset=covered_factors
                )
                active_artifact = latest_artifact  # passed to _build_top_drivers

                # Train-and-merge any newly selected factors
                if missing_factors:
                    results_new, merged_artifact = run_factor_backtest(
                        factors=missing_factors,
                        strategy='FactorModel',
                        start_date=None,
                        end_date=end_date,
                        input_dir=DIR_INPUT,
                        save=True,           # merges into existing .joblib on disk
                        save_latest_only=True,
                        **current_cfg,
                    )
                    results.update(results_new)
                    if merged_artifact:
                        # merged_artifact already contains old + new factors
                        active_artifact = merged_artifact
                        n_cached = len(covered_factors)
                        n_new = len(missing_factors)
                        persist_note = (
                            f"saved model: {latest_month_key} · "
                            f"{n_cached} from cache + {n_new} newly trained & merged"
                        )
                        header_note = (
                            f"🔮 {n_cached} factor(s) predicted from saved model · "
                            f"🆕 {n_new} new factor(s) trained, saved & merged: "
                            f"{', '.join(missing_factors)}"
                        )
                    else:
                        persist_note = (
                            f"saved model: {latest_month_key} · "
                            f"warning: new factors may not have saved correctly"
                        )
                        header_note = (
                            f"🔮 Predicted from saved model; some new factors may be "
                            f"missing (insufficient data or error)."
                        )
                else:
                    n_cached = len(covered_factors)
                    persist_note = (
                        f"saved model: {latest_month_key} · "
                        f"all {n_cached} factor(s) from cache (no new factors)"
                    )
                    header_note = (
                        f"🔮 Predicted from saved model through {latest_month_key} "
                        f"(no retrain — all {n_cached} factors already trained)."
                    )
                latest_artifact = active_artifact
            else:
                results, latest_artifact = run_factor_backtest(
                    factors=factors,
                    strategy='FactorModel',
                    start_date=None,
                    end_date=end_date,
                    input_dir=DIR_INPUT,
                    save=True,
                    save_latest_only=True,
                    **current_cfg,
                )
                if latest_artifact and latest_artifact.get('metadata'):
                    persist_note = f"saved model: {latest_artifact['metadata'].get('train_end_date', '?')}"
                else:
                    persist_note = "model save not found"
                header_note = (
                    f"⚡ Model trained on data through {end_date} (month-start cutoff — "
                    "no recent daily data used to avoid overfitting)."
                )

            if not results:
                return (
                    html.Div(
                        "No results — check that factor-rates.pkl exists and selected factors have sufficient history.",
                        style={'color': THEME['warning'], 'padding': '20px'}
                    ),
                    "⚠️ No factors produced results",
                    dash.no_update,
                )

            factor_stats = _compute_factor_stats(results)
            signal_status_row = _render_signal_cards(factor_stats)
            top_alpha_div = _build_top_drivers(latest_artifact, factors)

            signal_notes = html.Div(
                [
                    html.Div([
                        html.Span('Signal Z: ', style={'color': THEME['text_sub']}),
                        html.Span('latest prediction vs trailing 252d mean/std',
                                  style={'color': THEME['text_main']}),
                    ]),
                    html.Div([
                        html.Span('Scale: ', style={'color': THEME['text_sub']}),
                        html.Span('clipped |Z| used for sizing',
                                  style={'color': THEME['text_main']}),
                    ]),
                    html.Div([
                        html.Span('ICIR: ', style={'color': THEME['text_sub']}),
                        html.Span('mean rolling IC / IC std',
                                  style={'color': THEME['text_main']}),
                    ]),
                    html.Div([
                        html.Span('Conf: ', style={'color': THEME['text_sub']}),
                        html.Span('ICIR bucket: low / medium / high',
                                  style={'color': THEME['text_main']}),
                    ]),
                ],
                style={'marginTop': '10px', 'fontSize': '11px',
                       'color': THEME['text_sub'], 'lineHeight': '1.4'},
            )

            mean_icir = (sum(s['icir'] for s in factor_stats.values()) /
                         len(factor_stats)) if factor_stats else 0.0
            train_children = [
                html.Div(
                    header_note,
                    style={'color': THEME['accent'], 'fontSize': '11px',
                           'fontStyle': 'italic', 'padding': '8px 12px',
                           'backgroundColor': THEME['bg_input'],
                           'border': '1px solid #7B68EE',
                           'borderRadius': '6px', 'marginBottom': '12px'},
                ),
                html.H6("Current Signal State",
                        style={'color': THEME['accent'], 'marginBottom': '10px'}),
                signal_status_row,
                signal_notes,
                top_alpha_div,
            ]
            status_prefix = "🔮 Model predicted" if action == 'predict' else "⚡ Model trained"
            status_msg = (f"{status_prefix} · {persist_note} · Mean ICIR: {mean_icir:.2f}")

            # Build snapshot records for the Portfolio tab's factor-signals-snapshot-store.
            # With discrete sizing the 'signal' column IS the quantised target in [-1,1],
            # so last_signal is the exact level the backtest holds — use it as the scalar
            # directly so the portfolio factor_scaling exposure matches the backtest.
            def _bucket_label(c):
                if c == 0:
                    return 'Neutral'
                mag = abs(c)
                strength = 'Strong ' if mag >= 0.8 else ('' if mag >= 0.4 else 'Mild ')
                return f"{strength}{'Long' if c > 0 else 'Short'}"
            snapshot_records = []
            for _f, _s in factor_stats.items():
                _z = _s.get('z_score', 0.0)
                _ls = _s.get('last_signal', 0.0)
                _icir = _s.get('icir', 0.0)
                _scalar = float(_ls)   # quantised target in [-1,1]
                _bucket = _bucket_label(_scalar)
                _conf = (abs(_icir) >= 0.5) and 1.0 or (abs(_icir) >= 0.25) and 0.5 or 0.2
                snapshot_records.append({
                    'risk_factor': _f,
                    'scalar': _scalar,
                    'signal': float(_z),
                    'bucket_label': _bucket,
                    'confidence': _conf,
                    'risk_budget': 0.0,
                })

            return html.Div(train_children), status_msg, snapshot_records

        except Exception as e:
            import traceback
            traceback.print_exc()
            return (
                html.Div(f"Error: {e}",
                         style={'color': THEME['danger'], 'padding': '20px'}),
                f"❌ {e}",
                dash.no_update,
            )

