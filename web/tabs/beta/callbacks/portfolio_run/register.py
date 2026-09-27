# -*- coding: utf-8 -*-
"""Dash callback registration for the Portfolio (Allocation) tab. Thin
wrapper: risk-budget row/header construction lives in _risk_budget_panel.py,
Run Analysis orchestration lives in _run_analysis.py, and the hedge ticket
table lives in _irdl_hedge.py — this module only wires Input/Output/State."""

from __future__ import annotations

import pathlib
import traceback
from datetime import datetime

import dash
import pandas as pd
from dash import html, ALL
from dash.dependencies import Input, Output, State
from dateutil.relativedelta import relativedelta

from settings.paths import DIR_INPUT

from ...data import THEME, ALLOCATION_RESULTS
from .._common import _SUMMARY_BETA_PARQUET, _upsert_snapshot
from ._risk_budget_panel import build_risk_budget_rows, build_risk_budget_header
from ._run_analysis import (
    build_risk_budgets, run_optimization, apply_factor_scaling,
    build_portfolio_table, build_rp_budgets_out, build_allocation_results,
)
from ._irdl_hedge import build_irdl_hedge_ticket


def register_portfolio_run_callbacks(app):
    """Register Run Analysis & IRDL Hedge callbacks for the Portfolio tab."""

    # 3.6 Risk Factor Budget Input Generator
    @app.callback(
        Output('risk-budget-container', 'children'),
        [Input('asset-pool-store', 'data'),
         Input('rp-budget-store', 'data'),
         Input('factor-signals-snapshot-store', 'data'),
         Input('allocation-mode', 'value'),
         Input('capital-input', 'value'),
         Input('capital-unit', 'value')],
    )
    def update_risk_budget_inputs(asset_pool, rp_budgets, snapshot_data, allocation_mode, capital, capital_unit):
        return build_risk_budget_rows(asset_pool, rp_budgets, snapshot_data, allocation_mode,
                                       capital, capital_unit)

    # ── 3.7b Risk Budget Header (dynamic based on allocation mode) ────────
    @app.callback(
        Output('risk-budget-header-row', 'children'),
        [Input('allocation-mode', 'value')],
    )
    def render_risk_budget_header(allocation_mode):
        return build_risk_budget_header(allocation_mode)

    # ── 3.8  Mode status hint ─────────────────────────────────────────
    @app.callback(
        Output('factor-signals-toggle-status', 'children'),
        [Input('allocation-mode', 'value')],
        [State('factor-signals-snapshot-store', 'data'),
         State('asset-pool-store', 'data')],
    )
    def autofill_risk_budgets_status(allocation_mode, snapshot_data, asset_pool):
        """Show a one-line hint for the selected allocation mode."""
        if allocation_mode == 'risk_parity':
            return "RP Max = inv-vol weights · same result on every run"
        if allocation_mode == 'user_defined':
            return "Edit Exposure inputs directly · re-runs preserve your values"
        # factor_scaling
        if not snapshot_data:
            return "⚠ No signal snapshot — click 'Predict' in the Candidates tab first."
        return f"✓ {len(snapshot_data)} factor signals loaded from Candidates tab."

    # ── 3.9  Max DV01 display hint ────────────────────────────────────────────
    @app.callback(
        Output('max-dv01-display', 'children'),
        [Input('max-duration-input', 'value'),
         Input('capital-input', 'value'),
         Input('capital-unit', 'value')],
    )
    def update_max_dv01_display(max_dur, capital, unit):
        try:
            mult = 1e9 if unit == 'billion' else 1e6
            cap = float(capital or 10) * mult
            limit = cap * float(max_dur or 5) / 1e10
            return f"→ max DV01 {limit:.1f} MM"
        except Exception:
            return ""

    # ── 3.9b  Best rolldown term hint (CGB, informational only) ────────────────
    @app.callback(
        Output('rolldown-best-term-display', 'children'),
        Input('capital-input', 'id'),  # static id; callback fires once on page load
        prevent_initial_call=False,
    )
    def show_best_rolldown_term(_):
        """Current best risk-adjusted carry+rolldown tenor on the CGB curve.

        Informational only — this note does not currently feed run_analysis;
        the Rolldown Tilt % input is a placeholder for a future CGB-aware
        allocation step (multiasset/rolldown.py).
        """
        try:
            from multiasset.pca_analyzer import CN_IR_TENORS
            from multiasset.rolldown import cn_loading_matrix, carry_rolldown, select_t_star
            from multiasset.config import CURVE_CONFIG

            pkl_file, pkl_key, cols = CURVE_CONFIG['CN']
            data = pd.read_pickle(DIR_INPUT / pkl_file)[pkl_key][cols]
            data = data.rename(columns=dict(zip(cols, CN_IR_TENORS))).dropna()
            data.index = pd.to_datetime(data.index)

            tenors = list(CN_IR_TENORS)
            asof_row = data.iloc[-1]
            lookback = data.loc[data.index >= asof_row.name - relativedelta(years=1), tenors]
            dy = lookback.diff().dropna()

            B = cn_loading_matrix()
            level_vol = (dy.values @ B).std(axis=0)[0]
            cr = carry_rolldown(asof_row[tenors], tenors=tuple(tenors))
            t_star = select_t_star(cr, level_vol=level_vol)
            asof_str = asof_row.name.strftime('%Y-%m-%d')
            return f"→ Best rolldown term (CGB): {t_star} (as of {asof_str})"
        except Exception:
            return ""

    # 4. Run Analysis (Portfolio Tab -> Results)
    @app.callback(
        [Output('portfolio-table-container', 'children'),
         Output('status-message', 'children'),
         Output('timestamp-display', 'children'),
         Output('portfolio-data-store', 'data'),
         Output('rp-budget-store', 'data'),
         Output('allocation-results-store', 'data')],
        [Input('beta-run-button', 'n_clicks')],
        [State('capital-input', 'value'),
         State('capital-unit', 'value'),
         State('asset-pool-store', 'data'),
         State({'type': 'risk-budget-input', 'index': ALL}, 'value'),
         State({'type': 'risk-budget-input', 'index': ALL}, 'id'),
         State('allocation-mode', 'value'),
         State('factor-signals-snapshot-store', 'data'),
         State('max-duration-input', 'value')]
    )
    def run_analysis(n_clicks, total_capital, capital_unit, asset_pool,
                     budget_values, budget_ids, allocation_mode, signal_snapshot,
                     max_duration):
        if n_clicks == 0:
            return (html.Div("No data available. Click 'Run Analysis' to start.", style={'color': THEME['text_sub']}),
                    "", "", {}, {}, {})

        try:
            # Validate asset pool
            if not asset_pool or len(asset_pool) == 0:
                error_msg = html.Span("⚠ Please add assets to the pool before running analysis",
                                    style={'color': THEME['warning'], 'fontWeight': 'bold'})
                return (html.Div("No assets in pool.", style={'color': THEME['warning']}),
                        error_msg, "", {}, {}, {})

            # Convert capital to CNY
            multiplier = 1e9 if capital_unit == 'billion' else 1e6
            total_capital_cny = float(total_capital) * multiplier

            # Get selected assets
            selected_asset_names = [asset['name'] for asset in asset_pool]

            # Build risk budgets based on allocation mode
            factor_names_in_pool = [id_dict['index'] for id_dict in (budget_ids or [])]
            total_capital_m = total_capital_cny / 1e6
            risk_budgets, rp_budgets_out = build_risk_budgets(allocation_mode, budget_ids, budget_values)

            # Run optimization (capture convergence warnings to surface in UI)
            summary, returns, vols, factor_exp, factor_risk, portfolio, _opt_warnings = run_optimization(
                total_capital_cny, selected_asset_names, risk_budgets,
            )

            if summary.empty:
                error_msg = html.Span("⚠ No matching assets found in optimization results",
                                    style={'color': THEME['warning'], 'fontWeight': 'bold'})
                return (html.Div("No matching assets found.", style={'color': THEME['warning']}),
                        error_msg, "", {}, {}, {})

            # ── Factor Scaling: post-hoc signal tilt + class caps (mirrors backtest) ──
            if allocation_mode == 'factor_scaling':
                summary = apply_factor_scaling(summary, signal_snapshot, factor_names_in_pool, total_capital_cny)

            _run_timestamp = datetime.now()
            # Update global state (kept for legacy consumers; new code should use the store)
            ALLOCATION_RESULTS.update({
                'summary': summary, 'factor_exposures': factor_exp,
                'factor_risk': factor_risk, 'portfolio': portfolio,
                'timestamp': _run_timestamp,
            })

            table_result = build_portfolio_table(summary, factor_exp, portfolio, total_capital_cny, max_duration)
            portfolio_df = table_result['portfolio_df']
            portfolio_table_df = table_result['portfolio_table_df']
            total_dv01 = table_result['total_dv01']
            dv01_cap_msg = table_result['dv01_cap_msg']
            portfolio_table = html.Div([table_result['positions_table']])

            _dv01_info = f"  ·  DV01 {total_dv01:.2f} MM / max {total_capital_cny * float(max_duration or 5) / 1e10:.2f} MM{dv01_cap_msg}"
            _status_children = [html.Span(f"✓ Analysis completed!{_dv01_info}", style={'color': '#34d399', 'fontWeight': '700'})]
            for _ow in _opt_warnings:
                _status_children.append(html.Span(
                    f"  ⚠ Optimizer: {_ow[:120]}",
                    style={'color': '#f87171', 'fontSize': '10px', 'marginLeft': '12px'},
                ))
            status_msg = html.Div(_status_children, style={'display': 'flex', 'alignItems': 'center', 'flexWrap': 'wrap', 'gap': '4px'})
            timestamp_msg = f"Last updated: {_run_timestamp.strftime('%Y-%m-%d %H:%M:%S')}"

            rp_budgets_out = build_rp_budgets_out(allocation_mode, rp_budgets_out, factor_risk, vols, total_capital_m)

            # ── Build Beta snapshot (saved to Summary tab only via "Add to
            # Portfolio", not automatically on every Run Analysis) ───────────
            _allocation_results, _store_factor_risk = build_allocation_results(
                summary, factor_exp, factor_risk, portfolio,
                portfolio_df, portfolio_table_df,
                allocation_mode, total_capital_cny, max_duration,
                _run_timestamp,
            )
            return (portfolio_table, status_msg, timestamp_msg,
                    {'status': 'success', 'factor_risk': _store_factor_risk},
                    rp_budgets_out,
                    _allocation_results)

        except Exception as e:
            # Print full traceback for debugging
            print(f"\n{'='*80}")
            print("ERROR in run_analysis callback:")
            print(f"{'='*80}")
            traceback.print_exc()
            print(f"{'='*80}\n")

            error_msg = html.Span(f"✗ Error: {str(e)}", style={'color': THEME['danger'], 'fontWeight': 'bold'})
            return (html.Div(f"Error: {str(e)}", style={'color': THEME['danger']}),
                    error_msg, "", {}, {}, {})

    # ── Add to Portfolio (Beta Book Summary snapshot) ──────────────────────
    @app.callback(
        Output('beta-add-to-portfolio-status', 'children'),
        Input('beta-add-to-portfolio-btn', 'n_clicks'),
        State('allocation-results-store', 'data'),
        prevent_initial_call=True,
    )
    def add_beta_to_portfolio(n_clicks, allocation_results):
        if not n_clicks:
            return dash.no_update
        try:
            records = (allocation_results or {}).get('beta_snapshot') or []
            if not records:
                return html.Span("⚠ Run analysis first — no results to add.",
                                  style={'color': THEME['warning'], 'fontWeight': 'bold'})

            _snap = pd.DataFrame(records)
            pathlib.Path(_SUMMARY_BETA_PARQUET).parent.mkdir(parents=True, exist_ok=True)
            _id_cols = ['Asset Name'] if 'Asset Name' in _snap.columns else []
            merged = _upsert_snapshot(_snap, _SUMMARY_BETA_PARQUET, _id_cols)
            print(f"✓ Beta snapshot saved → {_SUMMARY_BETA_PARQUET} ({len(merged)} rows)")
            return html.Span(f"✓ Added to Portfolio Summary ({len(_snap)} rows)",
                              style={'color': '#34d399', 'fontWeight': '700'})
        except Exception as e:
            traceback.print_exc()
            return html.Span(f"✗ Error adding to portfolio: {e}", style={'color': THEME['danger'], 'fontWeight': 'bold'})

    # ── IRDL Hedge Overlay callback ───────────────────────────────────────────
    @app.callback(
        Output('irdl-hedge-ticket-container', 'children'),
        [
            Input('portfolio-data-store', 'data'),
            Input('irdl-hedge-ratio', 'value'),
            Input('irdl-hedge-instrument', 'value'),
            Input('irdl-hedge-irs-maturity', 'value'),
            Input({'type': 'irdl-dv01-override', 'index': ALL}, 'value'),
        ],
        [
            State({'type': 'irdl-dv01-override', 'index': ALL}, 'id'),
            State('capital-input', 'value'),
            State('capital-unit', 'value'),
        ],
        prevent_initial_call=True,
    )
    def update_irdl_hedge_ticket(
        store_data, hedge_ratio_pct, instrument, irs_maturity,
        dv01_values, dv01_ids, capital_value, capital_unit,
    ):
        _fr_records = (store_data or {}).get('factor_risk', [])
        factor_risk = pd.DataFrame(_fr_records) if _fr_records else pd.DataFrame()
        return build_irdl_hedge_ticket(
            factor_risk, hedge_ratio_pct, instrument, irs_maturity,
            dv01_values, dv01_ids, capital_value, capital_unit,
        )
