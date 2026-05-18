# -*- coding: utf-8 -*-
"""Risk-factor backtest (RFBT) callbacks: parameter panels, generate factor-rates.pkl,
and run the factor-model backtest."""

from __future__ import annotations

import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import os
import traceback
import pathlib
from datetime import datetime

from multiasset.risk_loader import RiskFactorLoader
from multiasset.factor_optimizer import FactorRiskParityOptimizer
from multiasset.factor_backtest import compute_ewma_factor_vols
from multiasset.config import RiskModelConfig
from settings.paths import DIR_INPUT, DIR_MODELS, DIR_OUTPUT

from ..data import THEME, SELECTED_FACTOR_POOL


def register_backtest_rfbt_callbacks(app):
    """Register Risk Factor Backtest (BACKTEST subtab) callbacks."""

    # ================================================================
    # Risk Factor Backtest callbacks (BACKTEST subtab)
    # ================================================================

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
        flex = {'display': 'flex', 'alignItems': 'center'}
        hide = {'display': 'none', 'alignItems': 'center'}
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
        [State('rfbt-factor-selector', 'value'),
         State('rfbt-strategy-selector', 'data'),
         State('rfbt-date-range', 'start_date'),
         State('rfbt-date-range', 'end_date'),
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
         State('rfbt-fm-topn', 'value')],
        prevent_initial_call=True,
    )
    def run_risk_factor_backtest(
        n_clicks, factors, strategy, start_date, end_date,
        ma_short, ma_long, boll_window, boll_std,
        mom_window, zscore_window, zscore_entry, zscore_exit,
        fm_train, fm_ic, fm_topn,
    ):
        if not n_clicks or not factors:
            raise dash.exceptions.PreventUpdate

        try:
            from multiasset.factor_backtest import (
                run_factor_backtest, compute_metrics, get_factor_duration,
                _is_yield_factor,
            )

            # Build strategy-specific kwargs – always FactorModel
            strategy = 'FactorModel'
            kwargs = {'train_months': int(fm_train or 12),
                      'ic_threshold': float(fm_ic or 0.05),
                      'top_n': int(fm_topn or 8)}

            results = run_factor_backtest(
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

            # ── Build summary metrics table ─────────────────────────────
            metric_rows = []
            for factor, df in results.items():
                m = compute_metrics(df)
                dur = get_factor_duration(factor)
                is_y = _is_yield_factor(factor)
                metric_rows.append({
                    'Factor': factor,
                    'Type': 'Yield' if is_y else 'Price',
                    'Scale': f'{dur:.1f}' if dur > 0 else '—',
                    'Total Ret': f"{m.get('Total Return', 0):.2%}",
                    'Ann Ret': f"{m.get('Ann. Return', 0):.2%}",
                    'Ann Vol': f"{m.get('Ann. Vol', 0):.2%}",
                    'Sharpe': f"{m.get('Sharpe', 0):.2f}",
                    'Max DD': f"{m.get('Max Drawdown', 0):.2%}",
                    'Win': f"{m.get('Win Rate', 0):.1%}",
                    'Days': int(m.get('Days', 0)),
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
                    {'if': {'row_index': 'odd'},
                     'backgroundColor': THEME['table_row_even']},
                ],
                style_table={'overflowX': 'auto', 'marginBottom': '16px'},
            )

            # ── Build cumulative return chart ───────────────────────────
            fig = go.Figure()
            colors = ['#3498db', '#e74c3c', '#2ecc71', '#f39c12',
                      '#9b59b6', '#1abc9c', '#e67e22', '#34495e',
                      '#E91E63', '#00BCD4']
            for i, (factor, df) in enumerate(results.items()):
                cum = df['cumulative_returns'].dropna()
                fig.add_trace(go.Scatter(
                    x=cum.index, y=cum.values, mode='lines',
                    name=factor, line={'color': colors[i % len(colors)]},
                ))

            fig.update_layout(
                title=f'Cumulative Returns — {strategy} Strategy',
                xaxis_title='Date', yaxis_title='Cumulative Return',
                hovermode='x unified',
                template=THEME['chart_template'], height=420,
                paper_bgcolor=THEME['bg_main'],
                plot_bgcolor=THEME['bg_main'],
                font={'color': THEME['text_main']},
                legend=dict(orientation='h', yanchor='bottom', y=1.02,
                            xanchor='right', x=1,
                            font={'color': THEME['text_main']}),
                xaxis=dict(gridcolor=THEME['table_header']),
                yaxis=dict(gridcolor=THEME['table_header']),
            )

            # ── Build signals chart (subplots per factor) ──────────────
            n_factors = len(results)
            signal_fig = make_subplots(
                rows=n_factors, cols=1, shared_xaxes=True,
                subplot_titles=list(results.keys()),
                vertical_spacing=0.04,
            )
            for i, (factor, df) in enumerate(results.items(), start=1):
                sig = df['signal'].dropna()
                signal_fig.add_trace(
                    go.Scatter(
                        x=sig.index, y=sig.values, mode='lines',
                        name=f'{factor} sig',
                        line={'color': colors[(i - 1) % len(colors)], 'width': 1},
                    ),
                    row=i, col=1,
                )

            signal_fig.update_layout(
                title='Positions / Signals',
                height=max(200, 120 * n_factors),
                template=THEME['chart_template'],
                paper_bgcolor=THEME['bg_main'],
                plot_bgcolor=THEME['bg_main'],
                font={'color': THEME['text_main']},
                showlegend=False,
            )

            status_msg = (f"✅ Backtest complete — {strategy} on "
                          f"{len(results)} factors, saved to factor-backtest.pkl")

            return (
                html.Div([
                    metrics_table,
                    dcc.Graph(figure=fig),
                    dcc.Graph(figure=signal_fig),
                ]),
                status_msg,
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            return (
                html.Div(f"Error: {e}",
                         style={'color': THEME['danger'], 'padding': '20px'}),
                f"❌ {e}",
            )

