# -*- coding: utf-8 -*-
"""Dash callback registration for Risk Factor Backtest (BACKTEST subtab) and
the Factor tab's Train/Predict action. Thin wrapper: run/train orchestration
logic lives in _run_backtest.py / _train_predict.py (no Dash import there),
chart/table construction lives in _figures.py — this module only wires
Input/Output/State and turns orchestrator results/exceptions into Dash
outputs."""

from __future__ import annotations

import dash
from dash import html
from dash.dependencies import Input, Output, State

from ...data import THEME
from ._rfbt_train_helpers import _compute_factor_stats, _render_signal_cards
from ._ui_toggles import register_ui_toggle_callbacks
from ._run_backtest import (
    resolve_date_range, build_factor_model_kwargs, run_rfbt_backtest,
    build_run_config, compute_factor_stats_and_ic, save_rfbt_result,
)
from ._figures import build_run_results_children
from ._train_predict import (
    NoModelForCurrentMonth, SavedModelParamsMismatch,
    FactorsNotInSavedModel, maybe_refresh_factor_data, build_stale_data_warning,
    collect_selected_factors, build_current_config, run_predict, run_train,
    build_snapshot_records, build_status_message,
)

# In-process cache for the "Run Backtest" / "Save" split: holds the results
# and models_by_month from the most recent unsaved run of
# run_risk_factor_backtest, so the Save button can persist them without
# re-running the (~seconds-to-minutes) walk-forward backtest. Single-slot —
# a new Run Backtest click overwrites it; Save always acts on the latest run.
_LAST_RFBT_RUN: dict = {}


def register_backtest_rfbt_callbacks(app):
    """Register Risk Factor Backtest (BACKTEST subtab) callbacks."""

    register_ui_toggle_callbacks(app)

    @app.callback(
        [Output('rfbt-results-container', 'children'),
         Output('rfbt-status', 'children'),
         Output('rfbt-save-btn', 'disabled')],
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
         State('rfbt-fm-possmooth', 'value'),
         State('rfbt-fm-tiltbase', 'value'),
         State('rfbt-fm-tiltamp', 'value')],
        prevent_initial_call=True,
    )
    def run_risk_factor_backtest(
        n_clicks, factor_val, strategy, period_years,
        custom_start, custom_end,
        ma_short, ma_long, boll_window, boll_std,
        mom_window, zscore_window, zscore_entry, zscore_exit,
        fm_train, fm_ic, fm_topn, fm_sizing, fm_possmooth,
        fm_tiltbase, fm_tiltamp,
    ):
        if not n_clicks or not factor_val:
            raise dash.exceptions.PreventUpdate

        start_date, end_date = resolve_date_range(period_years, custom_start, custom_end)

        # A fresh run invalidates any previously cached (unsaved) result —
        # Save must never persist a stale run under new parameters.
        _LAST_RFBT_RUN.clear()

        try:
            kwargs = build_factor_model_kwargs(
                fm_train, fm_ic, fm_topn, fm_sizing, fm_possmooth, fm_tiltbase, fm_tiltamp,
            )
            results, models_by_month, from_cache = run_rfbt_backtest(
                factor_val, start_date, end_date, kwargs,
            )

            if results and models_by_month is not None:
                _LAST_RFBT_RUN.update({
                    'results': results,
                    'models_by_month': models_by_month,
                    'config': build_run_config(kwargs),
                })

            if not results:
                return (
                    html.Div("No results — check that factor-rates.pkl exists and factors have data.",
                             style={'color': THEME['warning'], 'padding': '20px'}),
                    "⚠️ No factors produced results",
                    True,  # keep Save disabled — nothing to save
                )

            factor_stats = compute_factor_stats_and_ic(results)
            result_children = build_run_results_children(results, factor_stats)

            mean_icir = (sum(s['icir'] for s in factor_stats.values()) /
                         len(factor_stats)) if factor_stats else 0.0
            # This run is a preview only — nothing has been written to disk yet.
            # Click Save to persist it to factor-backtest.pkl + the monthly .joblib.
            cache_note = "⚡ loaded from cache" if from_cache else "👁 Preview only (not saved)"
            status_msg = (f"{cache_note} — {len(results)} factor(s) run · "
                          f"Mean ICIR: {mean_icir:.2f} · click Save to persist")

            return result_children, status_msg, False  # enable Save

        except Exception as e:
            import traceback
            traceback.print_exc()
            _LAST_RFBT_RUN.clear()
            return (
                html.Div(f"Error: {e}",
                         style={'color': THEME['danger'], 'padding': '20px'}),
                f"❌ {e}",
                True,  # keep Save disabled
            )

    # ================================================================
    # Save the last Run Backtest result — persists to factor-backtest.pkl
    # and the monthly .joblib WITHOUT re-running the backtest.
    # ================================================================

    @app.callback(
        Output('rfbt-status', 'children', allow_duplicate=True),
        Output('rfbt-save-btn', 'disabled', allow_duplicate=True),
        Input('rfbt-save-btn', 'n_clicks'),
        prevent_initial_call=True,
    )
    def save_risk_factor_backtest(n_clicks):
        if not n_clicks:
            raise dash.exceptions.PreventUpdate

        if not _LAST_RFBT_RUN:
            return "⚠️ Nothing to save — click Run Backtest first", True

        try:
            save_note = save_rfbt_result(
                _LAST_RFBT_RUN['results'],
                _LAST_RFBT_RUN['models_by_month'],
                _LAST_RFBT_RUN['config'],
            )
            # Keep the cache so repeated Save clicks (or a page refresh of this
            # tab) don't silently no-op — only a fresh Run Backtest clears it.
            return f"✅ {save_note}", False
        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"❌ Save failed: {e}", False

    # ================================================================
    # Factor tab: Train Model (Latest Signal) callback
    # ================================================================

    @app.callback(
        [Output('factor-signal-container', 'children'),
         Output('factor-train-status', 'children'),
         Output('factor-signals-snapshot-store', 'data')],
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

        maybe_refresh_factor_data()
        stale_data_warning = build_stale_data_warning()

        factors = collect_selected_factors(store_data)
        if not factors:
            return (
                html.Div("No factors selected. Please select factors in the Factor Selection Pool.",
                         style={'color': THEME['warning'], 'padding': '12px'}),
                "⚠️ No factors selected",
                dash.no_update,
            )

        end_date = _date.today().replace(day=1).isoformat()
        current_cfg = build_current_config(fm_train, fm_ic, fm_topn)

        try:
            if action == 'predict':
                try:
                    results, latest_artifact, persist_note, header_note = run_predict(
                        factors, current_cfg, end_date,
                    )
                except NoModelForCurrentMonth as exc:
                    expected_key = exc.expected_key
                    return (
                        html.Div([
                            *([stale_data_warning] if stale_data_warning is not None else []),
                            html.Div(
                                f"No model found for the current month (expected: "
                                f"factor_model_{expected_key}.joblib).",
                                style={'marginBottom': '8px'},
                            ),
                            html.Div(
                                "Click Train Model to calibrate the model on data "
                                f"through {expected_key[:4]}-{expected_key[4:6]}-{expected_key[6:]}. "
                                "Note: if the factor data cache is stale (see warning above), "
                                "Train Model will train on the stale cache and still not produce "
                                f"this month's key — refresh the data first.",
                            ),
                        ], style={'color': THEME['warning'], 'padding': '20px'}),
                        f"⚠️ No model for {expected_key[:6]} — click Train Model",
                        dash.no_update,
                    )
                except SavedModelParamsMismatch:
                    return (
                        html.Div(
                            "Saved model parameters do not match the current settings. Click Train Model to refresh the snapshot.",
                            style={'color': THEME['warning'], 'padding': '20px'}
                        ),
                        "⚠️ Saved model does not match current parameters",
                        dash.no_update,
                    )
                except FactorsNotInSavedModel as exc:
                    missing_list = ', '.join(exc.missing_factors)
                    return (
                        html.Div([
                            html.Div("⚠️  Selected factors not found in the saved model:",
                                     style={'fontWeight': 'bold', 'marginBottom': '6px',
                                            'fontSize': '14px'}),
                            html.Div(missing_list,
                                     style={'fontFamily': 'monospace', 'marginBottom': '10px',
                                            'color': '#f0c040', 'fontSize': '13px'}),
                            html.Div(
                                "These factors have not been trained yet. "
                                "Please click Train Model to retrain and include them "
                                "before running predictions.",
                                style={'lineHeight': '1.5'},
                            ),
                        ], style={
                            'color': THEME['warning'],
                            'backgroundColor': 'rgba(240, 120, 40, 0.12)',
                            'border': '1px solid rgba(240, 120, 40, 0.5)',
                            'borderRadius': '6px',
                            'padding': '16px',
                            'margin': '12px 0',
                        }),
                        f"⚠️ {len(exc.missing_factors)} factor(s) not in saved model — retrain required",
                        dash.no_update,
                    )
            else:
                results, latest_artifact, persist_note, header_note = run_train(
                    factors, current_cfg, end_date,
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
            signal_status_row = _render_signal_cards(factor_stats, artifact=latest_artifact)

            signal_notes = html.Div(
                [
                    html.Div([
                        html.Span('Signal Z: ', style={'color': 'var(--text-muted)'}),
                        html.Span('latest prediction vs trailing 252d mean/std',
                                  style={'color': 'var(--text-secondary)'}),
                    ]),
                    html.Div([
                        html.Span('Scale: ', style={'color': 'var(--text-muted)'}),
                        html.Span('clipped |Z| used for sizing',
                                  style={'color': 'var(--text-secondary)'}),
                    ]),
                    html.Div([
                        html.Span('ICIR: ', style={'color': 'var(--text-muted)'}),
                        html.Span('mean rolling IC / IC std',
                                  style={'color': 'var(--text-secondary)'}),
                    ]),
                    html.Div([
                        html.Span('Conf: ', style={'color': 'var(--text-muted)'}),
                        html.Span('ICIR bucket: low / medium / high',
                                  style={'color': 'var(--text-secondary)'}),
                    ]),
                ],
                style={'marginTop': '10px', 'fontSize': '9px',
                       'color': 'var(--text-muted)', 'lineHeight': '1.5'},
            )

            mean_icir = (sum(s['icir'] for s in factor_stats.values()) /
                         len(factor_stats)) if factor_stats else 0.0
            train_children = [
                *([stale_data_warning] if stale_data_warning is not None else []),
                html.Div(
                    header_note,
                    style={'color': 'var(--accent-purple, #9b8cf0)', 'fontSize': '11px',
                           'fontStyle': 'italic', 'padding': '8px 12px',
                           'background': 'var(--surface-input)',
                           'border': '1px solid var(--accent-purple, #7c70d6)',
                           'borderRadius': '6px', 'marginBottom': '12px'},
                ),
                html.Div([
                    html.Span(f"Mean ICIR: {mean_icir:.2f}", style={
                        'fontSize': '9px', 'color': 'var(--text-muted)',
                        'background': 'var(--surface-input)', 'padding': '2px 7px',
                        'borderRadius': '3px', 'border': '1px solid var(--border-default)',
                    }),
                ], style={'marginBottom': '10px'}),
                signal_status_row,
                signal_notes,
            ]
            status_msg = build_status_message(action, factor_stats, persist_note)
            snapshot_records = build_snapshot_records(factor_stats)

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
