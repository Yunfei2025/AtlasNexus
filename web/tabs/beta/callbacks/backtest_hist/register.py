# -*- coding: utf-8 -*-
"""Dash callback registration for the Backtest tab. Thin wrapper: all
orchestration logic lives in orchestrator.py (no Dash import there), all
chart/table construction lives in _figures.py — this module only wires Input/
Output/State and translates orchestrator exceptions into the same
user-facing error figures the original single-file callback produced."""

from __future__ import annotations

import traceback

import pandas as pd
from dash import html
from dash.dependencies import Input, Output, State

from ...data import THEME
from ._ui_callbacks import register_ui_callbacks
from .orchestrator import run_historical_allocation, NoSignalsAvailable, BacktestInputError
from ._figures import (
    empty_figure, error_figure, warning_figure,
    build_allocation_figure, build_pnl_figure, build_metrics_kpis, build_holdings_table,
)


def register_backtest_hist_callbacks(app):
    """Register historical-allocation backtest callbacks."""

    register_ui_callbacks(app)

    # 5. Historical Analysis (Backtest Tab) - Correlation-Based Strategy
    @app.callback(
        [Output('historical-allocation-chart', 'figure'),
         Output('pnl-attribution-chart', 'figure'),
         Output('performance-metrics-container', 'children'),
         Output('asset-changes-container', 'children'),
         Output('backtest-results-store', 'data')],
        [Input('run-history-button', 'n_clicks')],
        [State('backtest-capital-input', 'value'),
         State('backtest-capital-unit', 'value'),
         State('history-date-range', 'start_date'),
         State('history-date-range', 'end_date'),
         State('backtest-corr-lookback', 'value'),
         State('backtest-top-pairs', 'value'),
         State('backtest-alloc-mode', 'value')]
    )
    def update_historical_allocation(n_clicks, total_capital, capital_unit, start_date, end_date,
                                     corr_lookback, top_pairs, alloc_mode):
        if n_clicks == 0:
            fig = empty_figure()
            return fig, fig, None, None, None

        # Refresh factor-rates.pkl incrementally before backtesting so that
        # any data gap since the last "Predict" run is filled automatically.
        try:
            from multiasset.factor_backtest import update_factor_rates
            from settings.paths import DIR_INPUT
            _, n_new = update_factor_rates(DIR_INPUT)
            if n_new:
                print(f"Portfolio backtest: factor-rates.pkl +{n_new} new day(s) appended")
        except Exception as ufr_exc:
            print(f"Warning: factor-rates incremental update failed: {ufr_exc}")

        try:
            result = run_historical_allocation(
                total_capital, capital_unit, start_date, end_date,
                corr_lookback, top_pairs, alloc_mode,
            )
        except NoSignalsAvailable as e:
            unavail_fig = warning_figure(
                "Factor Model Scaling — no signals available",
                str(e) + "<br>Run the Individual Factors backtest first to generate signals.",
            )
            return unavail_fig, unavail_fig, None, html.Div(
                "Factor Model Scaling needs factor signals — run the Individual Factors "
                "backtest to populate factor-backtest.pkl, then retry.",
                style={'color': THEME['warning'], 'padding': '20px', 'textAlign': 'center'},
            ), None
        except BacktestInputError as e:
            err_fig = warning_figure(e.fig_title, themed=e.themed)
            div_style = ({'color': THEME['warning'], 'padding': '20px', 'textAlign': 'center'}
                        if e.themed else {'color': THEME['warning']})
            return err_fig, err_fig, None, html.Div(e.div_message, style=div_style), None
        except Exception as e:
            traceback.print_exc()
            err_fig = error_figure(str(e))
            return err_fig, err_fig, None, html.Div(f"Error: {str(e)}", style={'color': THEME['danger']}), None

        fig_alloc = build_allocation_figure(
            result['df_history'], result['all_assets_ever'],
            result['display_start'], result['display_end'],
        )
        fig_pnl = build_pnl_figure(
            result['df_pnl'], result['all_assets_ever'],
            result['display_start'], result['display_end'],
            nav_series=result['nav_series'], nav_net_series=result['nav_net_series'],
        )
        metrics_table = build_metrics_kpis(result['metrics']) if result['metrics'] is not None else None
        asset_changes_table = build_holdings_table(result['asset_holdings_rows'])

        return fig_alloc, fig_pnl, metrics_table, asset_changes_table, result['results_payload']

    # 6. Save Result — persist the last run so the beta+alpha combination
    # panel (web/tabs/risk/books/combination_callbacks.py) reads a fixed,
    # known beta result via multiasset.storage.load_last_backtest_result
    # instead of nothing (that panel never re-runs this backtest itself).
    @app.callback(
        Output('save-history-backtest-status', 'children'),
        Input('save-history-backtest-button', 'n_clicks'),
        State('backtest-results-store', 'data'),
        prevent_initial_call=True,
    )
    def save_historical_backtest_result(n_clicks, results_payload):
        if not n_clicks:
            return ""
        if not results_payload or 'equity_series' not in results_payload:
            return "Run the historical analysis first — nothing to save."
        try:
            from multiasset.storage import save_backtest_result
            save_backtest_result(
                equity_series=results_payload['equity_series'],
                sharpe=results_payload.get('sharpe', 0.0),
                annualized_return=results_payload.get('annualized_return', 0.0),
                max_drawdown=results_payload.get('max_drawdown', 0.0),
                asset_pool=results_payload.get('asset_pool', []),
                total_capital=results_payload.get('total_capital', 0.0),
                start_date=results_payload.get('start_date'),
                end_date=results_payload.get('end_date'),
            )
            return f"✅ Saved at {pd.Timestamp.now().strftime('%H:%M:%S')}"
        except Exception as e:
            traceback.print_exc()
            return f"⚠️ Save failed: {e}"
