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
from multiasset.factor_backtest import compute_ewma_factor_vols, get_factor_weighted_duration
from multiasset.budget import derive_vol_sqrt_budgets
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
from ._common import _BETA_BOOK_POSITIONS_PARQUET
from multiasset.layout import get_cgb_otr_map


def _prepare_summary_table_data(portfolio_df: pd.DataFrame) -> pd.DataFrame:
    """Transform portfolio table into Beta Book Summary table format.

    Converts portfolio allocation data to the format expected by the Summary tab,
    with editable fields for Open Price, Open Date, and Volume (MM).
    Preserves existing user-entered data for positions being carried over.
    """
    if portfolio_df.empty:
        return portfolio_df

    summary_df = portfolio_df.copy()

    # Load existing user-entered data to preserve it
    user_data_map: dict = {}
    from ._common import _BETA_BOOK_USER_PARQUET
    if os.path.exists(_BETA_BOOK_USER_PARQUET):
        try:
            udf = pd.read_parquet(_BETA_BOOK_USER_PARQUET)
            for _, r in udf.iterrows():
                key = (str(r.get('asset_name', '')), str(r.get('instrument', '')))
                user_data_map[key] = {
                    'open_price': str(r.get('open_price', r.get('open_yld', ''))),
                    'open_date': str(r.get('open_date', '')),
                    'volume': str(r.get('volume', '')),
                }
        except Exception:
            pass

    # Ensure Capital is in MM CNY format (as string with commas)
    if 'Capital (CNY)' in summary_df.columns:
        capital_vals = []
        for val in summary_df['Capital (CNY)']:
            try:
                # Convert from string to float, then to MM
                if isinstance(val, str):
                    capital_cny = float(val.replace(',', ''))
                else:
                    capital_cny = float(val)
                capital_mm = capital_cny / 1e6
                capital_vals.append(f"{capital_mm:,.2f}")
            except (ValueError, TypeError):
                capital_vals.append(str(val))
        summary_df['Capital (MM CNY)'] = capital_vals
        summary_df = summary_df.drop(columns=['Capital (CNY)'], errors='ignore')

    # Ensure Weight (%) is formatted correctly
    if 'Weight (%)' in summary_df.columns:
        weight_vals = []
        for val in summary_df['Weight (%)']:
            val_str = str(val).replace('%', '').strip()
            try:
                weight_vals.append(f"{float(val_str):.2f}%")
            except (ValueError, TypeError):
                weight_vals.append(str(val))
        summary_df['Weight (%)'] = weight_vals

    # Add editable fields, preserving existing user-entered data
    open_prices = []
    open_dates = []
    volumes = []
    for _, row in summary_df.iterrows():
        asset_name = str(row.get('Asset Name', ''))
        instrument = str(row.get('Instrument', ''))
        key = (asset_name, instrument)
        saved = user_data_map.get(key, {})
        open_prices.append(saved.get('open_price', ''))
        open_dates.append(saved.get('open_date', ''))
        volumes.append(saved.get('volume', ''))

    summary_df['Open Price'] = open_prices
    summary_df['Open Date'] = open_dates
    summary_df['Volume (MM)'] = volumes

    # Add read-only columns - initialize as empty
    for col in ['Close Price', 'MtM (MM CNY)']:
        if col not in summary_df.columns:
            summary_df[col] = ''

    # Remove DV01 column if present (not needed in Summary tab)
    summary_df = summary_df.drop(columns=['DV01 (MM CNY)', 'Sector'], errors='ignore')

    # Add timestamp for tracking when the summary was last updated
    summary_df['_timestamp'] = datetime.now().isoformat()

    return summary_df


def _merge_with_existing_positions(new_portfolio_df: pd.DataFrame) -> pd.DataFrame:
    """Update Rates bond codes to the latest on-the-run instruments.

    Only substitutes OTR bond codes for Rates assets in the new portfolio.
    Does not carry over positions from previous runs — allocation is fully
    determined by today's signals each time.
    """
    if new_portfolio_df.empty:
        return new_portfolio_df

    result_df = new_portfolio_df.copy()
    otr_map = get_cgb_otr_map()

    for idx, row in result_df.iterrows():
        if row.get('Asset Type') == 'Rates':
            sector = row.get('Sector', '')
            if sector and sector in otr_map:
                result_df.at[idx, 'Instrument'] = otr_map[sector]

    return result_df


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

            elif a_type == 'FX':
                 asset_name = asset.get('name', '')
                 # Map asset names to FX factors: USDCNY → FXDL.USDCNY
                 fx_map = {'USDCNY': 'USDCNY', 'EURCNY': 'EURCNY', 'JPYCNY': 'JPYCNY', 'GBPCNY': 'GBPCNY'}
                 if asset_name in fx_map:
                     active_factors.add(f"FXDL.{fx_map[asset_name]}")

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
        # Discrete target in [-1,1] (0.2 tick) from the Beta-book factor backtest.
        # Derive a label + colour from the sign and magnitude of the scalar.
        def _scalar_meta(c):
            if c == 0:
                return ('Neutral', THEME.get('text_sub', '#aaa'))
            mag = abs(c)
            strength = 'Strong ' if mag >= 0.8 else ('' if mag >= 0.4 else 'Mild ')
            if c > 0:
                return (f'{strength}Long', THEME.get('success', '#2ecc71'))
            return (f'{strength}Short', THEME.get('danger', '#e74c3c'))
        snapshot_by_rf = {}
        if snapshot_data:
            for rec in snapshot_data:
                rf = rec.get('risk_factor')
                if rf:
                    snapshot_by_rf[rf] = rec

        _missing_signals = [f for f in sorted_factors if f not in snapshot_by_rf]

        def get_coeff(factor):
            rec = snapshot_by_rf.get(factor)
            if rec is not None:
                return float(rec.get('scalar', 1.0))
            return 0.0  # neutral — no signal yet; run Predict first

        # ── Factor vol lookup (live 1Y EWMA) ─────────────────────────────────
        _vol_map = compute_factor_vol_map(sorted_factors)

        # ── Vol^0.5 Risk Parity budgets ───────────────────────────────────────
        _vol_sqrt_allocations, _missing_vols = derive_vol_sqrt_budgets(
            sorted_factors, _vol_map, total_capital_m=total_capital_m
        )
        if _missing_vols:
            import logging
            logging.getLogger(__name__).warning(
                "Missing vol data for %d factor(s): %s — using fallback vol",
                len(_missing_vols), _missing_vols,
            )

        def get_rp_max(factor):
            if allocation_mode == 'user_defined':
                # User Defined: preserve what the user last stored (or equal share on first load)
                return float(rp_budgets[factor]) if (rp_budgets and factor in rp_budgets) else equal_share
            # risk_parity and factor_scaling: vol^0.5 weighted allocation
            return _vol_sqrt_allocations.get(factor, equal_share)

        # ── Build rows ─────────────────────────────────────────────────────────
        rows = []
        for factor in sorted_factors:
            rp_max = get_rp_max(factor)
            coeff  = get_coeff(factor)
            # Exposure = RP Max in all modes; coeff is shown for reference only
            suggested = rp_max
            label, color = _scalar_meta(coeff)
            is_default_coeff = factor not in snapshot_by_rf

            vol_val = _vol_map.get(factor)
            has_missing_vol = vol_val is None or pd.isna(vol_val) or vol_val <= 0
            if has_missing_vol:
                vol_str = f"– (est. 15%)"  # Show that we're using estimate
                vol_color = THEME.get('warning', '#f39c12')
            else:
                vol_str = f"{vol_val:.2f}%"
                vol_color = THEME['text_main']

            # Compute DV01 for IR factors (IRDL, IRSL, IRCV, SPDL, SPSL)
            dv01_str = ""
            factor_prefix = factor.split('.')[0]
            if factor_prefix in ('IRDL', 'IRSL', 'IRCV', 'SPDL', 'SPSL'):
                dur = get_factor_weighted_duration(factor)
                if dur is not None and dur > 0:
                    dv01 = round(rp_max * dur / 10_000, 2)
                    dv01_str = f"{dv01:.2f}"

            rows.append(
                html.Div([
                    html.Span(factor, style={
                        'color': THEME['text_main'], 'fontSize': '12px',
                        'width': '80px', 'fontWeight': 'bold', 'flexShrink': '0',
                    }),
                    html.Span(vol_str, style={
                        'color': vol_color, 'fontSize': '12px',
                        'width': '62px', 'textAlign': 'right', 'flexShrink': '0',
                        'fontFamily': 'monospace',
                        'fontWeight': 'bold' if has_missing_vol else 'normal',
                    }, title='Volatility: if missing data, estimated at 15% (typical commodity vol)'),
                    html.Span(f"{round(rp_max)}", style={
                        'color': THEME['text_sub'], 'fontSize': '12px',
                        'width': '105px', 'textAlign': 'right', 'flexShrink': '0',
                        'fontFamily': 'monospace',
                    }, title='Vol√ allocation: from factor volatility weighted by sqrt(vol)'),
                    html.Span(dv01_str, style={
                        'color': THEME['text_sub'], 'fontSize': '12px',
                        'width': '85px', 'textAlign': 'right', 'flexShrink': '0',
                        'fontFamily': 'monospace',
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
                        value=round(suggested),
                        step=1,
                        style={
                            'flex': '1', 'minWidth': '100px', 'fontSize': '12px', 'padding': '4px 6px',
                            'backgroundColor': '#ffffff', 'color': '#000000',
                            'border': f'1px solid {THEME["table_header"]}',
                            'borderRadius': '3px', 'textAlign': 'right',
                            'fontFamily': 'monospace', 'fontWeight': 'normal',
                            'appearance': 'textfield',  # Remove spinner arrows on number input
                        }
                    ),
                ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '4px', 'gap': '4px'})
            )

        return rows


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
         State('factor-signals-snapshot-store', 'data'),
         State('max-duration-input', 'value')]
    )
    def run_analysis(n_clicks, total_capital, capital_unit, asset_pool,
                     budget_values, budget_ids, allocation_mode, signal_snapshot,
                     max_duration):
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
            _missing_signals: list[str] = []
            _opt_warnings: list[str] = []

            if allocation_mode == 'risk_parity':
                # Pure Risk Parity: optimizer runs unconstrained ERC — always deterministic.
                # rp_budgets_out will be filled from optimizer factor vols after the run.
                risk_budgets = None

            elif allocation_mode == 'factor_scaling':
                # Factor Model Scaling: vol^0.5 base budgets, scaled by signal scalar.
                _vm = compute_factor_vol_map(factor_names_in_pool) if factor_names_in_pool else {}
                _iv = {f: np.sqrt(_vm[f]) for f in factor_names_in_pool
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
                    _IR_PREFIXES = ('IRDL', 'IRSL', 'IRCV', 'SPDL', 'SPSL')
                    for f, base_val in _base.items():
                        rec = _snap.get(f)
                        if rec is not None:
                            scalar = float(rec.get('scalar', 1.0))
                            # Carry floor for bond factors: a neutral signal does NOT mean
                            # zero position — bond PMs always hold a carry position.
                            # Mirror the backtest's _CAP_NEUTRAL floor: scalar=0 maps to
                            # 25% of the RP base budget (same as the weakest long signal tick).
                            is_bond = f.split('.')[0] in _IR_PREFIXES
                            if scalar == 0.0 and is_bond:
                                effective_budget = round(base_val * 0.25, 2)
                            else:
                                effective_budget = round(base_val * abs(scalar), 2)
                            risk_budgets[f] = effective_budget
                            scaled_count += 1
                        else:
                            risk_budgets[f] = base_val
                    print(f"📡 Factor model scaling applied to {scaled_count} risk budgets")
                    _snap_keys = {rec['risk_factor'] for rec in signal_snapshot if rec.get('risk_factor')}
                    _missing_signals = [f for f in factor_names_in_pool if f not in _snap_keys]
                else:
                    risk_budgets = _base
                    _missing_signals = factor_names_in_pool  # no snapshot at all
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

            # Run optimization (capture convergence warnings to surface in UI)
            import warnings as _warnings
            _opt_warnings: list[str] = []
            with _warnings.catch_warnings(record=True) as _caught:
                _warnings.simplefilter("always", RuntimeWarning)
                summary, returns, vols, factor_exp, factor_risk, portfolio = run_risk_parity_allocation(
                    total_capital=total_capital_cny, use_cache=True, selected_assets=selected_asset_names,
                    risk_budgets=risk_budgets, use_deterministic=True
                )
                _opt_warnings = [str(w.message) for w in _caught if issubclass(w.category, RuntimeWarning)]

            if summary.empty:
                error_msg = html.Span("⚠ No matching assets found in optimization results", 
                                    style={'color': THEME['warning'], 'fontWeight': 'bold'})
                return (html.Div("No matching assets found.", style={'color': THEME['warning']}),
                        error_msg, "", {}, {})
            
            _run_timestamp = datetime.now()
            # Update global state (kept for legacy consumers; new code should use the store)
            ALLOCATION_RESULTS.update({
                'summary': summary, 'factor_exposures': factor_exp,
                'factor_risk': factor_risk, 'portfolio': portfolio,
                'timestamp': _run_timestamp,
            })
            
            # Prepare portfolio table
            portfolio_df = prepare_portfolio_table(summary, factor_exp, portfolio)

            # Merge with existing positions and update bond codes for Rates assets
            portfolio_df = _merge_with_existing_positions(portfolio_df)

            portfolio_enhanced = []
            total_rounded_capital = 0.0
            dv01_cap_msg = ""
            total_dv01 = 0.0           # safe default — overwritten below when table is non-empty
            _durations = np.array([])  # safe default
            _rounded   = np.array([])

            if not portfolio_df.empty:
                _units = np.where(
                    portfolio_df['Asset Type'].isin(('Rates', 'Spread')),
                    10_000_000.0,
                    1_000_000.0,
                )
                _rounded = np.floor(portfolio_df['Capital (CNY)'].values / _units) * _units

                # ── DV01 cap: scale down if portfolio DV01 exceeds max_duration limit ──
                _durations = portfolio_df['Duration'].values
                _raw_dv01_mm = float(sum(v * d / 1e10 for v, d in zip(_rounded, _durations)))
                _max_dur = float(max_duration or 5)
                _max_dv01_mm = total_capital_cny * _max_dur / 1e10
                if _raw_dv01_mm > _max_dv01_mm and _raw_dv01_mm > 0:
                    _scale = _max_dv01_mm / _raw_dv01_mm
                    _rounded = np.floor(_rounded * _scale / _units) * _units
                    dv01_cap_msg = (f"  ·  DV01 capped: {_raw_dv01_mm:.2f}→{_max_dv01_mm:.2f} MM "
                                    f"(scale {_scale:.2%})")

                total_rounded_capital = float(_rounded.sum())
                _display_df = portfolio_df.copy()
                _display_df['Capital (CNY)'] = [f"{v / 1_000_000:,.2f}" for v in _rounded]
                _display_df['Weight (%)'] = portfolio_df['Weight (%)'].map(lambda v: f"{v:.2f}%")
                # Recompute DV01 on (possibly capped) rounded capital
                _display_df['DV01 (MM CNY)'] = [
                    round(v * d / 1e10, 4)
                    for v, d in zip(_rounded, _durations)
                ]
                portfolio_enhanced = _display_df.to_dict('records')

            portfolio_table_df = pd.DataFrame(portfolio_enhanced)

            # Add totals row
            if not portfolio_table_df.empty:
                total_dv01 = round(
                    sum(v * d / 1e10 for v, d in zip(_rounded, _durations)), 4
                )
                totals = {
                    'Asset Type': 'TOTAL', 'Universe': '', 'Sector': '', 'Asset Name': '',
                    'Instrument': '', 'Duration': None,   # None → NaN, avoids mixed-type parquet issue
                    'Capital (CNY)': f"{total_rounded_capital / 1_000_000:,.2f}",
                    'DV01 (MM CNY)': total_dv01,
                    'Weight (%)': f"{summary['Weight (%)'].sum():.2f}%"
                }
                portfolio_table_df = pd.concat([portfolio_table_df, pd.DataFrame([totals])], ignore_index=True)

            # Save positions parquet for reference (coerce object columns so pyarrow doesn't choke)
            # The Beta Book Summary parquet is written once below via _upsert_snapshot.
            try:
                _save_df = portfolio_table_df.copy()
                for _c in _save_df.columns:
                    if _save_df[_c].dtype == object:
                        _save_df[_c] = _save_df[_c].fillna('').astype(str)
                pathlib.Path(_BETA_BOOK_POSITIONS_PARQUET).parent.mkdir(parents=True, exist_ok=True)
                _save_df.to_parquet(_BETA_BOOK_POSITIONS_PARQUET, index=False)
                print(f"✓ beta_book_positions.parquet saved ({len(_save_df)} rows) → {_BETA_BOOK_POSITIONS_PARQUET}")
            except Exception as _se:
                print(f"Warning: Could not save Beta book positions: {_se}")
            
            # Create table
            portfolio_table = dash_table.DataTable(
                data=portfolio_table_df.to_dict('records'),
                columns=[
                    {'name': 'Asset Type',           'id': 'Asset Type'},
                    {'name': 'Universe',              'id': 'Universe'},
                    {'name': 'Sector',                'id': 'Sector'},
                    {'name': 'Asset Name',            'id': 'Asset Name'},
                    {'name': 'Instrument',            'id': 'Instrument'},
                    {'name': 'Duration',              'id': 'Duration'},
                    {'name': 'Capital (Million CNY)', 'id': 'Capital (CNY)'},
                    {'name': 'DV01 (MM CNY)',         'id': 'DV01 (MM CNY)'},
                    {'name': 'Weight',                'id': 'Weight (%)'},
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
            
            _dv01_info = f"  ·  DV01 {total_dv01:.2f} MM / max {total_capital_cny * float(max_duration or 5) / 1e10:.2f} MM{dv01_cap_msg}"
            _status_children = [html.Span(f"✓ Analysis completed!{_dv01_info}", style={'color': THEME['success'], 'fontWeight': 'bold'})]
            if _missing_signals:
                _status_children.append(html.Span(
                    f"  ⚠ {len(_missing_signals)} factor(s) have no signal — held at neutral (0): "
                    + ", ".join(_missing_signals),
                    style={'color': THEME.get('warning', '#f39c12'), 'fontSize': '12px', 'marginLeft': '12px'},
                ))
            for _ow in _opt_warnings:
                _status_children.append(html.Span(
                    f"  ⚠ Optimizer: {_ow[:120]}",
                    style={'color': THEME.get('danger', '#ef553b'), 'fontSize': '11px', 'marginLeft': '12px'},
                ))
            status_msg = html.Div(_status_children, style={'display': 'flex', 'alignItems': 'center', 'flexWrap': 'wrap', 'gap': '4px'})
            timestamp_msg = f"Last updated: {_run_timestamp.strftime('%Y-%m-%d %H:%M:%S')}"

            # For Pure Risk Parity: derive RP Max from actual factor risk contributions
            # returned by the full-covariance optimizer (proper ERC attribution).
            if allocation_mode == 'risk_parity':
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
                pathlib.Path(_SUMMARY_BETA_PARQUET).parent.mkdir(parents=True, exist_ok=True)
                _keep_cols = [c for c in [
                    'Asset Type', 'Universe', 'Sector', 'Asset Name', 'Instrument',
                    'Duration', 'Capital (CNY)', 'DV01 (MM CNY)', 'Weight (%)',
                ] if c in portfolio_df.columns]
                _snap = portfolio_df[_keep_cols].copy()
                _snap['_timestamp'] = datetime.now().isoformat()
                for _c in ('Duration', 'Capital (CNY)', 'DV01 (MM CNY)'):
                    if _c in _snap.columns:
                        _snap[_c] = pd.to_numeric(_snap[_c], errors='coerce')
                _id_cols = ['Asset Name'] if 'Asset Name' in _snap.columns else []
                merged = _upsert_snapshot(_snap, _SUMMARY_BETA_PARQUET, _id_cols)
                print(f"✓ Beta snapshot saved → {_SUMMARY_BETA_PARQUET} ({len(merged)} rows)")
            except Exception as _se:
                print(f"Warning: Could not save Beta snapshot: {_se}")
                traceback.print_exc()

            _store_factor_risk = (
                factor_risk.to_dict('records')
                if isinstance(factor_risk, pd.DataFrame) and not factor_risk.empty
                else []
            )
            return (portfolio_table, status_msg, timestamp_msg,
                    {'status': 'success', 'factor_risk': _store_factor_risk},
                    rp_budgets_out)
            
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
        _fr_records = (store_data or {}).get('factor_risk', [])
        factor_risk = pd.DataFrame(_fr_records) if _fr_records else pd.DataFrame()
        if factor_risk.empty:
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
