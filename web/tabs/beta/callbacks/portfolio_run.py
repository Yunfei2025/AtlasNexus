# -*- coding: utf-8 -*-
"""Portfolio (Allocation) tab — analysis & risk callbacks.

Contains:
  3.6 Risk Factor Budget Input Generator
  3.7 Factor Model Signals refresh & render
  3.8 Mode status hint
  4.  Run Analysis (Portfolio Tab → Results) — the main optimisation callback
  IRDL Hedge Overlay
"""

from __future__ import annotations

import dash
from dash import dcc, html, dash_table, ALL, Patch
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import os
import traceback
import pathlib
from datetime import datetime
from dateutil.relativedelta import relativedelta

from multiasset.data import (
    load_raw_market_data, calculate_daily_returns_series,
    get_asset_type, get_universe, get_sector,
)
from multiasset.layout import prepare_portfolio_table
from multiasset.main import run_risk_parity_allocation, create_custom_portfolio, compute_irdl_hedge
from multiasset.risk_loader import RiskFactorLoader
from multiasset.factor_optimizer import FactorRiskParityOptimizer
from multiasset.factor_backtest import compute_ewma_factor_vols
from multiasset.config import RiskModelConfig
from settings.paths import DIR_INPUT

from ..data import (
    THEME,
    ALLOCATION_RESULTS,
    SELECTED_FACTOR_POOL,
    RISK_BUDGET_VOL_LOOKBACK_YEARS,
    RISK_BUDGET_EWMA_LAMBDA,
    FACTOR_TO_ASSET_MAP,
    compute_factor_vol_map,
    get_assets_from_factors,
)
from ._common import _SUMMARY_BETA_PARQUET, _upsert_snapshot


def register_portfolio_run_callbacks(app):
    """Register Run Analysis & IRDL Hedge callbacks for the Portfolio tab."""

    # 3.6 Risk Factor Budget Input Generator
    @app.callback(
        Output('risk-budget-container', 'children'),
        [Input('asset-pool-store', 'data'),
         Input('rp-budget-store', 'data'),
         Input('factor-signals-snapshot-store', 'data'),
         Input('allocation-mode', 'value')],
        [State('capital-input', 'value'),
         State('capital-unit', 'value')],
    )
    def update_risk_budget_inputs(asset_pool, rp_budgets, snapshot_data, allocation_mode, capital, capital_unit):
        if not asset_pool:
             return [html.Div("Add assets to see risk factors", style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'fontSize': '12px', 'textAlign': 'center'})]

        active_factors = set()
        
        # Mappings based on MultiAsset logic
        rates_map = {'CN': 'CN', 'US': 'US', 'EU': 'DE', 'UK': 'UK', 'JP': 'JP'}
        comm_map = {'Gold': 'AU', 'Aluminium': 'AL', 'Copper': 'CU', 'Crude Oil': 'SC', 'Crude_Oil': 'SC'}

        for asset in asset_pool:
            a_type = asset.get('type')
            
            if a_type == 'Rates':
                asset_name = asset.get('name', '')
                prefix = asset_name[:2]
                rf_country = rates_map.get(prefix)
                if rf_country:
                    active_factors.add(f"IRDL.{rf_country}")
                    active_factors.add(f"IRSL.{rf_country}")
                    active_factors.add(f"IRCV.{rf_country}")
            
            elif a_type == 'Spread':
                 asset_name = asset.get('name', '')
                 if asset_name.startswith('IRS'): code = 'IRS'
                 elif asset_name.startswith('CDB'): code = 'CDB'
                 elif asset_name.startswith('ICP'): code = 'ICP'
                 else: code = None
                 if code:
                     active_factors.add(f"SPDL.{code}")
                     if code != 'ICP':
                         active_factors.add(f"SPSL.{code}")
            
            elif a_type == 'Commodities':
                 asset_name = asset.get('name', '')
                 code = comm_map.get(asset_name)
                 if code:
                     active_factors.add(f"CMDL.{code}")

        if not active_factors:
             return [html.Div("No risk factors identified.", style={'color': THEME['text_sub'], 'fontSize': '12px'})]

        sorted_factors = sorted(list(active_factors))
        n_factors = len(sorted_factors)

        # ── Compute RP Max per factor ──────────────────────────────────────────
        # Use post-run RP budgets if available; else fall back to equal capital share
        try:
            cap_val = float(capital or 100)
            cap_mult = 1e9 if (capital_unit == 'billion') else 1e6
            total_capital_m = cap_val * cap_mult / 1e6
        except (TypeError, ValueError):
            total_capital_m = 100.0
        equal_share = round(total_capital_m / n_factors, 2) if n_factors else 1.0

        # ── Factor model signal lookup (scalar + colour) ───────────────────────
        SCALAR_META = {
            -1.5: ('Strong Short', THEME.get('danger', '#e74c3c')),
            -1.0: ('Short',        '#e74c3c'),
            -0.5: ('Mild Short',   '#e67e22'),
             0.0: ('Neutral',      THEME.get('text_sub', '#aaa')),
             0.5: ('Mild Long',    '#27ae60'),
             1.0: ('Long',         THEME.get('success', '#2ecc71')),
             1.5: ('Strong Long',  '#2ecc71'),
        }
        snapshot_by_rf = {}
        if snapshot_data:
            for rec in snapshot_data:
                rf = rec.get('risk_factor')
                if rf:
                    snapshot_by_rf[rf] = rec

        def get_coeff(factor):
            rec = snapshot_by_rf.get(factor)
            if rec is not None:
                return float(rec.get('scalar', 1.0))
            return 1.0  # default: full long — placeholder until factor model is run

        # ── Factor vol lookup (live 1Y EWMA) ─────────────────────────────────
        _vol_map = compute_factor_vol_map(sorted_factors)

        # ── Inverse-vol proportional RP Max (stable base for risk_parity / factor_scaling) ─
        _inv_vols = {}
        for _f in sorted_factors:
            _v = _vol_map.get(_f)
            if _v is not None and pd.notna(_v) and _v > 0:
                _inv_vols[_f] = 1.0 / _v
        _total_inv_vol = sum(_inv_vols.values())
        if _total_inv_vol > 0:
            _inv_vol_budgets = {
                _f: round(total_capital_m * _inv_vols.get(_f, 0.0) / _total_inv_vol, 2)
                for _f in sorted_factors
            }
        else:
            _inv_vol_budgets = {_f: equal_share for _f in sorted_factors}

        def get_rp_max(factor):
            if allocation_mode == 'user_defined':
                # User Defined: preserve what the user last stored (or equal share on first load)
                return float(rp_budgets[factor]) if (rp_budgets and factor in rp_budgets) else equal_share
            # risk_parity and factor_scaling: always deterministic inverse-vol proportional
            return _inv_vol_budgets.get(factor, equal_share)

        # ── Build rows ─────────────────────────────────────────────────────────
        rows = []
        for factor in sorted_factors:
            rp_max = get_rp_max(factor)
            coeff  = get_coeff(factor)
            # factor_scaling: scale exposure by signal coeff; other modes: exposure = RP Max
            suggested = round(rp_max * coeff, 2) if allocation_mode == 'factor_scaling' else rp_max
            label, color = SCALAR_META.get(coeff, (f'{coeff:+.1f}×', THEME.get('text_main', '#fff')))
            is_default_coeff = factor not in snapshot_by_rf

            vol_val = _vol_map.get(factor)
            vol_str = f"{vol_val:.2f}%" if vol_val is not None and pd.notna(vol_val) else "–"

            rows.append(
                html.Div([
                    html.Span(factor, style={
                        'color': THEME['text_main'], 'fontSize': '12px',
                        'width': '80px', 'fontWeight': 'bold', 'flexShrink': '0',
                    }),
                    html.Span(vol_str, style={
                        'color': THEME.get('text_sub', '#aaa'), 'fontSize': '12px',
                        'width': '62px', 'textAlign': 'right', 'flexShrink': '0',
                        'fontFamily': 'monospace',
                    }),
                    html.Span(f"{rp_max:.1f}M", style={
                        'color': THEME['text_sub'], 'fontSize': '12px',
                        'width': '54px', 'textAlign': 'right', 'flexShrink': '0',
                    }),
                    html.Span(
                        f"×{coeff:+.1f}",
                        title=f"{label}{' (default)' if is_default_coeff else ''}",
                        style={
                            'color': THEME.get('text_sub', '#aaa') if is_default_coeff else color,
                            'fontSize': '12px', 'width': '44px', 'textAlign': 'center',
                            'flexShrink': '0', 'fontWeight': 'bold',
                            'fontStyle': 'italic' if is_default_coeff else 'normal',
                        }
                    ),
                    dcc.Input(
                        id={'type': 'risk-budget-input', 'index': factor},
                        type='number',
                        value=suggested,
                        step=0.1,
                        style={
                            'width': '52px', 'fontSize': '12px', 'padding': '2px 4px',
                            'backgroundColor': '#fff', 'color': '#000',
                            'border': f'1px solid {THEME["table_header"]}',
                            'borderRadius': '2px', 'textAlign': 'right',
                        }
                    ),
                    html.Span("M", style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginLeft': '2px'}),
                ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '4px', 'gap': '4px'})
            )
        
        return rows

    # ── 3.7  Factor Model Signals – refresh & render ──────────────────
    @app.callback(
        [Output('factor-signals-table-container', 'children'),
         Output('factor-signals-status', 'children'),
         Output('factor-signals-snapshot-store', 'data')],
        [Input('refresh-factor-signals-btn', 'n_clicks')],
        prevent_initial_call=True,
    )
    def refresh_factor_signals(n_clicks):
        """Compute signal snapshot from the factor prediction engine and
        render as a colour-coded table in the Factor tab.

        Signal sources (merged, risk-factor models take priority):
        1. Contract-level ``trained_model_*.joblib`` from ``factors/``
           → decomposed to risk factors via exposure profiles.
        2. Risk-factor-level ``factor_model_*.joblib`` from ``input/models/``
           → direct risk-factor predictions (override contract-based).
        """
        try:
            from factors.processing.exposure_mapper import (
                BucketConfig, compute_signal_snapshot,
            )
            from factors.processing.risk_factor_mapper import (
                CONTRACT_RISK_PROFILES, decompose_signal_series,
            )
            import joblib, os, glob
            from settings.paths import PATH

            rf_signals: dict = {}  # risk_factor → signal Series
            source_info: list = []  # human-readable summary

            # --- Source 1: contract-level models (factors/) --------------------
            model_dir = os.path.join(str(PATH), 'factors')
            model_files = glob.glob(os.path.join(model_dir, 'trained_model_*.joblib'))

            if model_files:
                from factors.processing.loader import getDailyTS, ensure_returns_column
                from factors.generator.factory import FactorCalculatorFactory
                from factors.engine.predictor import predict_returns

                n_contracts = 0
                for mf in model_files:
                    basename = os.path.basename(mf)
                    parts = basename.replace('trained_model_', '').replace('.joblib', '').split('_')
                    contract = parts[0] if parts else None
                    if contract not in CONTRACT_RISK_PROFILES:
                        continue
                    artifact = joblib.load(mf)
                    trained_model  = artifact.get('trained_model', {})
                    selected_factors = artifact.get('selected_factors', [])
                    ticker = artifact.get('config', {}).get('ticker', contract)
                    if not trained_model or not selected_factors:
                        continue
                    try:
                        raw_data = getDailyTS(ticker)
                        raw_data = ensure_returns_column(raw_data)
                        factory  = FactorCalculatorFactory(raw_data)
                        all_factors = factory.generate_factors()
                        predictions = predict_returns(all_factors, trained_model, selected_factors)
                        predictions = predictions.dropna()
                        predictions = predictions[predictions != 0]
                    except Exception:
                        continue
                    if predictions is None or (hasattr(predictions, 'empty') and predictions.empty):
                        continue
                    decomposed = decompose_signal_series(predictions, contract)
                    for col in decomposed.columns:
                        if col in rf_signals:
                            rf_signals[col] = rf_signals[col].add(decomposed[col], fill_value=0)
                        else:
                            rf_signals[col] = decomposed[col].copy()
                    n_contracts += 1

                if n_contracts:
                    source_info.append(f"{n_contracts} contracts")

            # --- Source 2: risk-factor-level models (input/models/) -----------
            try:
                from multiasset.factor_model import predict_factor_signals
                rf_model_signals = predict_factor_signals(DIR_INPUT, DIR_MODELS)
                if rf_model_signals:
                    for rf, series in rf_model_signals.items():
                        rf_signals[rf] = series  # override contract-derived
                    source_info.append(f"{len(rf_model_signals)} risk-factor models")
            except Exception as e:
                print(f"Warning: risk-factor model signals unavailable: {e}")

            if not rf_signals:
                return (
                    html.Div("No signal series could be computed from trained models.",
                             style={'color': THEME['text_sub']}),
                    "No signals",
                    {},
                )

            # --- bucket mapping ------------------------------------------------
            cfg = BucketConfig()
            snapshot = compute_signal_snapshot(rf_signals, cfg)

            if snapshot.empty:
                return (
                    html.Div("Signal snapshot is empty.", style={'color': THEME['text_sub']}),
                    "Empty",
                    {},
                )

            # --- render table --------------------------------------------------
            def _bucket_color(label):
                label_lower = str(label).lower()
                if 'strong long' in label_lower: return THEME['success']
                if 'long' in label_lower: return '#27ae60'
                if 'strong short' in label_lower: return THEME['danger']
                if 'short' in label_lower: return '#c0392b'
                return THEME['text_sub']

            rows = [
                html.Tr([
                    html.Td(r['risk_factor'], style={'fontWeight': 'bold'}),
                    html.Td(f"{r['signal']:.4f}"),
                    html.Td(r['bucket_label'],
                             style={'color': _bucket_color(r['bucket_label']),
                                    'fontWeight': 'bold'}),
                    html.Td(f"{r['scalar']:+.1f}×"),
                    html.Td(f"{r['risk_budget']:+.2f} M"),
                    html.Td(f"{r['confidence']:.0%}"),
                ], style={'fontSize': '12px'})
                for r in snapshot.to_dict('records')
            ]

            table = html.Table(
                [html.Thead(html.Tr([
                    html.Th(c, style={'padding': '4px 8px', 'color': THEME['text_sub'],
                                      'borderBottom': f'1px solid {THEME["table_header"]}'})
                    for c in ['Risk Factor', 'Signal', 'Bucket', 'Scalar',
                              'Risk Budget', 'Confidence']
                ]))] + [html.Tbody(rows)],
                style={'width': '100%', 'color': THEME['text_main'],
                       'fontSize': '12px', 'borderCollapse': 'collapse'},
            )

            # Store snapshot as serialisable dict for Portfolio tab
            snapshot_data = snapshot.to_dict(orient='records')

            source_str = ' + '.join(source_info) if source_info else 'unknown'

            return (
                table,
                f"Updated ({len(snapshot)} factors · {source_str})",
                snapshot_data,
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            return (
                html.Div(f"Error: {e}", style={'color': THEME['danger']}),
                "Error",
                {},
            )

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
            return "⚠ No signal snapshot — click 'Refresh Signals' in the Factor tab first."
        return f"✓ {len(snapshot_data)} factor signals scale RP Max at run time."

    # 4. Run Analysis (Portfolio Tab -> Results)
    @app.callback(
        [Output('portfolio-table-container', 'children'),
         Output('status-message', 'children'),
         Output('timestamp-display', 'children'),
         Output('portfolio-data-store', 'data'),
         Output('rp-budget-store', 'data')],
        [Input('run-button', 'n_clicks')],
        [State('capital-input', 'value'),
         State('capital-unit', 'value'),
         State('asset-pool-store', 'data'),
         State({'type': 'risk-budget-input', 'index': ALL}, 'value'),
         State({'type': 'risk-budget-input', 'index': ALL}, 'id'),
         State('allocation-mode', 'value'),
         State('factor-signals-snapshot-store', 'data')]
    )
    def run_analysis(n_clicks, total_capital, capital_unit, asset_pool,
                     budget_values, budget_ids, allocation_mode, signal_snapshot):
        if n_clicks == 0:
            return (html.Div("No data available. Click 'Run Analysis' to start.", style={'color': THEME['text_sub']}),
                    "", "", {}, {})

        try:
            # Validate asset pool
            if not asset_pool or len(asset_pool) == 0:
                error_msg = html.Span("⚠ Please add assets to the pool before running analysis", 
                                    style={'color': THEME['warning'], 'fontWeight': 'bold'})
                return (html.Div("No assets in pool.", style={'color': THEME['warning']}),
                        error_msg, "", {}, {})
            
            # Convert capital to CNY
            multiplier = 1e9 if capital_unit == 'billion' else 1e6
            total_capital_cny = float(total_capital) * multiplier
            
            # Get selected assets
            selected_asset_names = [asset['name'] for asset in asset_pool]
            
            # Build risk budgets based on allocation mode
            risk_budgets = None
            rp_budgets_out = {}
            factor_names_in_pool = [id_dict['index'] for id_dict in (budget_ids or [])]
            total_capital_m = total_capital_cny / 1e6

            if allocation_mode == 'risk_parity':
                # Pure Risk Parity: optimizer runs unconstrained ERC — always deterministic.
                # rp_budgets_out will be filled from optimizer factor vols after the run.
                risk_budgets = None

            elif allocation_mode == 'factor_scaling':
                # Factor Model Scaling: inverse-vol base budgets, scaled by signal scalar.
                _vm = compute_factor_vol_map(factor_names_in_pool) if factor_names_in_pool else {}
                _iv = {f: 1.0 / _vm[f] for f in factor_names_in_pool
                       if _vm.get(f) and pd.notna(_vm[f]) and _vm[f] > 0}
                _tot = sum(_iv.values())
                n_pool = len(factor_names_in_pool) or 1
                _base = (
                    {f: round(total_capital_m * _iv.get(f, 0.0) / _tot, 2) for f in factor_names_in_pool}
                    if _tot > 0
                    else {f: round(total_capital_m / n_pool, 2) for f in factor_names_in_pool}
                )
                if signal_snapshot:
                    _snap = {rec['risk_factor']: rec for rec in signal_snapshot if rec.get('risk_factor')}
                    risk_budgets = {}
                    scaled_count = 0
                    for f, base_val in _base.items():
                        rec = _snap.get(f)
                        if rec is not None:
                            risk_budgets[f] = round(base_val * float(rec.get('scalar', 1.0)), 2)
                            scaled_count += 1
                        else:
                            risk_budgets[f] = base_val
                    print(f"📡 Factor model scaling applied to {scaled_count} risk budgets")
                else:
                    risk_budgets = _base
                # Store unscaled base budgets — same signals → same result → idempotent
                rp_budgets_out = _base

            else:  # user_defined
                # User Defined: use input-box values exactly; write them back unchanged.
                if budget_ids and budget_values:
                    risk_budgets = {}
                    for val, id_dict in zip(budget_values, budget_ids):
                        factor_name = id_dict['index']
                        try:
                            risk_budgets[factor_name] = float(val) if val is not None else 1.0
                        except (ValueError, TypeError):
                            pass
                rp_budgets_out = dict(risk_budgets) if risk_budgets else {}

            # Run optimization
            summary, returns, vols, factor_exp, factor_risk, portfolio = run_risk_parity_allocation(
                total_capital=total_capital_cny, use_cache=True, selected_assets=selected_asset_names,
                risk_budgets=risk_budgets, use_deterministic=True
            )
            
            if summary.empty:
                error_msg = html.Span("⚠ No matching assets found in optimization results", 
                                    style={'color': THEME['warning'], 'fontWeight': 'bold'})
                return (html.Div("No matching assets found.", style={'color': THEME['warning']}),
                        error_msg, "", {}, {})
            
            # Update global state
            ALLOCATION_RESULTS.update({
                'summary': summary, 'factor_exposures': factor_exp,
                'factor_risk': factor_risk, 'portfolio': portfolio,
                'timestamp': datetime.now()
            })
            
            # Prepare portfolio table
            portfolio_df = prepare_portfolio_table(summary, factor_exp, portfolio)
            portfolio_enhanced = []
            total_rounded_capital = 0.0
            
            if not portfolio_df.empty:
                _units = np.where(
                    portfolio_df['Asset Type'].isin(('Rates', 'Spread')),
                    10_000_000.0,
                    1_000_000.0,
                )
                _rounded = np.floor(portfolio_df['Capital (CNY)'].values / _units) * _units
                total_rounded_capital = float(_rounded.sum())
                _display_df = portfolio_df.copy()
                _display_df['Capital (CNY)'] = [f"{v / 1_000_000:,.2f}" for v in _rounded]
                _display_df['Weight (%)'] = portfolio_df['Weight (%)'].map(lambda v: f"{v:.2f}%")
                portfolio_enhanced = _display_df.to_dict('records')
            
            portfolio_table_df = pd.DataFrame(portfolio_enhanced)
            
            # Add totals row
            if not portfolio_table_df.empty:
                totals = {
                    'Asset Type': 'TOTAL', 'Universe': '', 'Sector': '', 'Asset Name': '',
                    'Capital (CNY)': f"{total_rounded_capital / 1_000_000:,.2f}",
                    'Weight (%)': f"{summary['Weight (%)'].sum():.2f}%"
                }
                portfolio_table_df = pd.concat([portfolio_table_df, pd.DataFrame([totals])], ignore_index=True)
            
            # Create table
            portfolio_table = dash_table.DataTable(
                data=portfolio_table_df.to_dict('records'),
                columns=[
                    {'name': 'Asset Type', 'id': 'Asset Type'},
                    {'name': 'Universe', 'id': 'Universe'},
                    {'name': 'Sector', 'id': 'Sector'},
                    {'name': 'Asset Name', 'id': 'Asset Name'},
                    {'name': 'Capital (Million CNY)', 'id': 'Capital (CNY)'},
                    {'name': 'Weight', 'id': 'Weight (%)'},
                ],
                style_cell={
                    'textAlign': 'center', 
                    'padding': '10px', 
                    'fontFamily': 'Arial, sans-serif',
                    'backgroundColor': THEME['table_row_odd'],
                    'color': THEME['text_main'],
                    'border': 'none'
                },
                style_header={
                    'backgroundColor': THEME['table_header'], 
                    'color': THEME['text_main'], 
                    'fontWeight': 'bold', 
                    'textAlign': 'center',
                    'border': 'none'
                },
                style_data_conditional=[
                    {'if': {'filter_query': '{Asset Type} = "TOTAL"'}, 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'], 'fontWeight': 'bold'},
                    {'if': {'row_index': 'even'}, 'backgroundColor': THEME['table_row_even']}
                ],
                style_table={'overflowX': 'auto'}
            )
            
            status_msg = html.Span("✓ Analysis completed successfully!", style={'color': THEME['success'], 'fontWeight': 'bold'})
            timestamp_msg = f"Last updated: {ALLOCATION_RESULTS['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}"

            # For Pure Risk Parity: derive RP Max from actual factor risk contributions
            # returned by the full-covariance optimizer (proper ERC attribution).
            if allocation_mode == 'risk_parity':
                factor_risk = ALLOCATION_RESULTS.get('factor_risk', pd.DataFrame())
                if (not factor_risk.empty
                        and 'Risk Factor' in factor_risk.columns
                        and 'Risk Contribution (%)' in factor_risk.columns):
                    _valid_rc = factor_risk[pd.notna(factor_risk['Risk Contribution (%)'])]
                    rc_map = dict(zip(_valid_rc['Risk Factor'], _valid_rc['Risk Contribution (%)']))
                    total_rc = sum(v for v in rc_map.values() if v > 0)
                    if total_rc > 1e-6:
                        rp_budgets_out = {
                            f: round(total_capital_m * v / total_rc, 2)
                            for f, v in rc_map.items() if v > 0
                        }
                    else:
                        # Fallback: inv-vol proportional
                        _fnames_erc = list(vols.index) if hasattr(vols, 'index') else []
                        _iv = {f: 1.0/float(vols[f]) for f in _fnames_erc
                               if pd.notna(vols.get(f)) and float(vols[f]) > 0}
                        _tot = sum(_iv.values()) or 1.0
                        rp_budgets_out = {f: round(total_capital_m * v / _tot, 2) for f, v in _iv.items()}
                else:
                    # Fallback: inv-vol proportional
                    _fnames_erc = list(vols.index) if hasattr(vols, 'index') else []
                    _iv = {f: 1.0/float(vols[f]) for f in _fnames_erc
                           if pd.notna(vols.get(f)) and float(vols[f]) > 0}
                    _tot = sum(_iv.values()) or 1.0
                    rp_budgets_out = {f: round(total_capital_m * v / _tot, 2) for f, v in _iv.items()}
            # factor_scaling and user_defined already have rp_budgets_out set above

            # ── Save Beta snapshot for Summary tab ────────────────────────────
            try:
                import pathlib
                pathlib.Path(_SUMMARY_BETA_PARQUET).parent.mkdir(parents=True, exist_ok=True)
                _snap = portfolio_df.copy()
                _snap['_timestamp'] = datetime.now().isoformat()
                _snap['_capital_cny'] = _snap['Capital (CNY)']
                # Ensure all factor-sensitivity columns are float (serialisable)
                for _c in _snap.columns:
                    if _c not in ('Asset Type', 'Universe', 'Sector', 'Asset Name',
                                  '_timestamp', '_capital_cny'):
                        _snap[_c] = pd.to_numeric(_snap[_c], errors='coerce')
                # Upsert by Asset Name: keeps prior assets that aren't in this run,
                # replaces values for assets that re-appear, adds new ones.
                _id_cols = ['Asset Name'] if 'Asset Name' in _snap.columns else []
                merged = _upsert_snapshot(_snap, _SUMMARY_BETA_PARQUET, _id_cols)
                print(f"✓ Beta snapshot merged → {_SUMMARY_BETA_PARQUET} ({len(merged)} rows after upsert)")
            except Exception as _se:
                print(f"Warning: Could not save Beta snapshot: {_se}")

            return (portfolio_table, status_msg, timestamp_msg, {'status': 'success'}, rp_budgets_out)
            
        except Exception as e:
            # Print full traceback for debugging
            print(f"\n{'='*80}")
            print("ERROR in run_analysis callback:")
            print(f"{'='*80}")
            traceback.print_exc()
            print(f"{'='*80}\n")
            
            error_msg = html.Span(f"✗ Error: {str(e)}", style={'color': THEME['danger'], 'fontWeight': 'bold'})
            return (html.Div(f"Error: {str(e)}", style={'color': THEME['danger']}),
                    error_msg, "", {}, {})


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
        factor_risk = ALLOCATION_RESULTS.get('factor_risk')
        if factor_risk is None or factor_risk.empty:
            return html.Div(
                "Run Analysis first to compute portfolio exposures.",
                style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'fontSize': '12px'},
            )
        if 'Net Exposure' not in factor_risk.columns:
            return html.Div(
                "Net Exposure column not available — re-run Analysis.",
                style={'color': THEME['warning'], 'fontSize': '12px'},
            )

        try:
            # Build capital
            multiplier = 1e9 if capital_unit == 'billion' else 1e6
            total_capital = float(capital_value or 10) * multiplier

            # Build DV01 overrides dict
            dv01_overrides = {}
            for val, id_dict in zip(dv01_values or [], dv01_ids or []):
                cty = id_dict['index']
                if val is not None:
                    try:
                        dv01_overrides[cty] = float(val)
                    except (ValueError, TypeError):
                        pass

            hedge_ratio = (hedge_ratio_pct or 0) / 100.0

            tickets = compute_irdl_hedge(
                factor_risk_records=factor_risk.to_dict('records'),
                total_capital=total_capital,
                hedge_ratio=hedge_ratio,
                instrument=instrument or 'futures',
                dv01_overrides=dv01_overrides if dv01_overrides else None,
                irs_maturity=irs_maturity or '10Y',
            )

            if not tickets:
                return html.Div(
                    "No IRDL factors found in current allocation.",
                    style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'fontSize': '12px'},
                )

            _dir_color = {
                'SHORT':     THEME.get('danger', '#e74c3c'),
                'PAY FIXED': THEME.get('danger', '#e74c3c'),
                'LONG':      THEME.get('success', '#27ae60'),
                'RCV FIXED': THEME.get('success', '#27ae60'),
            }

            return html.Div([
                html.Div(
                    f"Hedge ratio: {hedge_ratio_pct}%  ·  Instrument: "
                    f"{'Bond Futures' if instrument == 'futures' else 'Pay-fixed IRS'}  ·  "
                    f"Capital: {float(capital_value or 10):,.0f} {capital_unit}",
                    style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginBottom': '8px'},
                ),
                dash_table.DataTable(
                    data=tickets,
                    columns=[
                        {'name': 'Country',            'id': 'Country'},
                        {'name': 'Net IRDL Exp (DY)',  'id': 'Net IRDL Exp (DY)'},
                        {'name': 'Port DV01 (CNY/bp)', 'id': 'Port DV01 (CNY/bp)'},
                        {'name': 'Hedge DV01 (CNY/bp)', 'id': 'Hedge DV01 (CNY/bp)'},
                        {'name': 'Quantity',           'id': 'Quantity'},
                        {'name': 'Direction',          'id': 'Direction'},
                        {'name': 'Instrument',         'id': 'Instrument'},
                    ],
                    style_cell={
                        'textAlign': 'center', 'padding': '8px 10px',
                        'fontSize': '12px',
                        'backgroundColor': THEME['table_row_odd'],
                        'color': THEME['text_main'], 'border': 'none',
                    },
                    style_header={
                        'backgroundColor': THEME['table_header'],
                        'color': THEME['text_main'],
                        'fontWeight': 'bold', 'border': 'none',
                    },
                    style_data_conditional=[
                        {'if': {'row_index': 'even'}, 'backgroundColor': THEME['table_row_even']},
                        *[
                            {'if': {'filter_query': f'{{Direction}} = "{d}"', 'column_id': 'Direction'},
                             'color': c, 'fontWeight': 'bold'}
                            for d, c in _dir_color.items()
                        ],
                        {'if': {'filter_query': '{Net IRDL Exp (DY)} > 0', 'column_id': 'Net IRDL Exp (DY)'},
                         'color': THEME.get('success', '#27ae60')},
                        {'if': {'filter_query': '{Net IRDL Exp (DY)} < 0', 'column_id': 'Net IRDL Exp (DY)'},
                         'color': THEME.get('danger', '#e74c3c')},
                    ],
                    style_table={'overflowX': 'auto'},
                ),
            ])

        except Exception as exc:
            return html.Div(
                f"Error computing hedge: {exc}",
                style={'color': THEME['danger'], 'fontSize': '12px'},
            )
