# -*- coding: utf-8 -*-
"""Risk Factor Budget Input Generator (Portfolio tab, section 3.6/3.7b):
derives the active risk-factor set from the asset pool, computes RP Max /
DV01 / signal-coefficient columns per factor, and renders the editable
budget-row panel plus its header. Split out of the ~285-line
update_risk_budget_inputs callback body in portfolio_run.py."""

from __future__ import annotations

import logging

import pandas as pd
from dash import dcc, html

from multiasset.factor_backtest import get_factor_weighted_duration
from multiasset.budget import derive_vol_sqrt_budgets
from multiasset.backtest_cache import scalar_to_coeff

from ...data import THEME, compute_factor_vol_map

_IR_LABEL_PREFIXES = ('IRDL', 'IRSL', 'IRCV', 'CRDL', 'CRSL', 'CRCV')
_IR_PREFIXES = ('IRDL', 'IRSL', 'IRCV')

_RATES_MAP = {'CN': 'CN', 'US': 'US', 'EU': 'DE', 'UK': 'UK', 'JP': 'JP'}
_COMM_MAP = {
    'Gold': 'AU', 'Silver': 'AG', 'Aluminium': 'AL',
    'Copper': 'CU', 'Zinc': 'ZN', 'Crude_Oil': 'SC', 'Crude Oil': 'SC',
}


def collect_active_factors(asset_pool) -> set:
    """Derive the set of risk factors implied by the current asset pool
    (mirrors MultiAsset's asset→factor mapping conventions)."""
    active_factors = set()

    for asset in asset_pool:
        a_type = asset.get('type')

        if a_type == 'Rates':
            asset_name = asset.get('name', '')
            prefix = asset_name[:2]
            rf_country = _RATES_MAP.get(prefix)
            if rf_country:
                active_factors.add(f"IRDL.{rf_country}")
                active_factors.add(f"IRSL.{rf_country}")
                active_factors.add(f"IRCV.{rf_country}")

        elif a_type == 'Spread':
            asset_name = asset.get('name', '')
            code = 'IRS' if asset_name.startswith('IRS') else None
            if code:
                active_factors.add(f"SPDL.{code}")
                active_factors.add(f"SPSL.{code}")

        elif a_type == 'Credit':
            asset_name = asset.get('name', '')
            if asset_name.startswith('CDB'): code = 'CDB'
            elif asset_name.startswith('LGB'): code = 'LGB'
            elif asset_name.startswith('MTN'): code = 'MTN'
            elif asset_name.startswith('NCD'): code = 'NCD'
            else: code = None
            if code:
                active_factors.add(f"CRDL.{code}")
                active_factors.add(f"CRSL.{code}")
                if code != 'NCD':
                    active_factors.add(f"CRCV.{code}")

        elif a_type == 'Commodities':
            asset_name = asset.get('name', '')
            code = _COMM_MAP.get(asset_name)
            if code:
                active_factors.add(f"CMDL.{code}")

        elif a_type == 'FX':
            asset_name = asset.get('name', '')
            fx_map = {'USDCNY': 'USDCNY', 'EURCNY': 'EURCNY', 'JPYCNY': 'JPYCNY', 'GBPCNY': 'GBPCNY'}
            if asset_name in fx_map:
                active_factors.add(f"FXDL.{fx_map[asset_name]}")

        elif a_type == 'Equities':
            asset_name = asset.get('name', '')
            eq_map = {'IF': 'IF', 'IC': 'IC', 'IH': 'IH', 'IM': 'IM'}
            if asset_name in eq_map:
                active_factors.add(f"EQDL.{eq_map[asset_name]}")

    return active_factors


def scalar_meta(c, factor):
    """Derive a (label, colour) pair for a risk-factor signal scalar.

    IMPORTANT: the snapshot stores IRSL with its sign flipped (positive =
    steepener) so scalar_to_coeff()'s generic directional formula keeps
    the "up = risk-on" convention for the exposure calc — see the flip
    in backtest_rfbt.py's snapshot-record builder. That flip must be
    undone here before deriving the label, and the label vocabulary
    (Steepener/Flattener, Bullish/Bearish, Concave/Convex, Long/Short)
    must mirror _sc() in _rfbt_train_helpers.py exactly — otherwise this
    column disagrees with the direction shown on the Candidates tab.
    """
    prefix = factor.split('.')[0]
    raw = -c if prefix == 'IRSL' else c  # undo the storage-time flip
    if raw == 0:
        return ('Neutral', THEME.get('text_sub', '#aaa'))
    mag = abs(raw)
    strength = 'Strong ' if mag >= 0.8 else ('' if mag >= 0.4 else 'Mild ')
    is_slope = prefix in ('IRSL', 'CRSL')
    is_curve = prefix in ('IRCV', 'CRCV')
    is_yield = prefix in _IR_LABEL_PREFIXES and not is_slope and not is_curve
    if raw > 0:
        if is_slope:
            return (f'{strength}Steepener', THEME.get('success', '#2ecc71'))
        if is_curve:
            return (f'{strength}Concave', THEME.get('success', '#2ecc71'))
        if is_yield:
            return (f'{strength}Bullish', THEME.get('success', '#2ecc71'))
        return (f'{strength}Long', THEME.get('success', '#2ecc71'))
    if is_slope:
        return (f'{strength}Flattener', THEME.get('danger', '#e74c3c'))
    if is_curve:
        return (f'{strength}Convex', THEME.get('danger', '#e74c3c'))
    if is_yield:
        return (f'{strength}Bearish', THEME.get('danger', '#e74c3c'))
    return (f'{strength}Short', THEME.get('danger', '#e74c3c'))


def build_risk_budget_rows(asset_pool, rp_budgets, snapshot_data, allocation_mode,
                            capital, capital_unit):
    """Build the editable per-factor risk-budget row list (section 3.6)."""
    if not asset_pool:
        return [html.Div("Add assets to see risk factors",
                          style={'color': 'var(--text-muted)', 'fontStyle': 'italic',
                                 'fontSize': '11px', 'textAlign': 'center'})]

    active_factors = collect_active_factors(asset_pool)
    if not active_factors:
        return [html.Div("No risk factors identified.",
                          style={'color': 'var(--text-muted)', 'fontSize': '11px'})]

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
    snapshot_by_rf = {}
    if snapshot_data:
        for rec in snapshot_data:
            rf = rec.get('risk_factor')
            if rf:
                snapshot_by_rf[rf] = rec

    def get_raw_scalar(factor):
        rec = snapshot_by_rf.get(factor)
        return float(rec.get('scalar', 0.0)) if rec is not None else 0.0

    def get_coeff(factor, raw_scalar):
        # Mirror run_analysis's factor_scaling tilt exactly: raw scalar →
        # scalar_to_coeff() (long-only factors clip to [0,2] around 1+scalar;
        # directional factors clip to [-1.5,1.5] as-is).
        return scalar_to_coeff(raw_scalar, factor)

    # ── Factor vol lookup (live 1Y EWMA) ─────────────────────────────────
    _vol_map = compute_factor_vol_map(sorted_factors)

    # ── Vol^0.5 budgets — IR factors only ────────────────────────────────
    # IRDL/IRSL/IRCV capital is constrained to be ∝ √vol.
    # CMDL/FXDL/SPDL/CRDL/CRSL/CRCV are free in the min-vol optimizer —
    # display equal share (credit spreads get the same treatment as the
    # existing SPDL/SPSL spread factors, not IR's duration-scaled budget).
    ir_factors = [f for f in sorted_factors if f.split('.')[0] in _IR_PREFIXES]
    non_ir_factors = [f for f in sorted_factors if f.split('.')[0] not in _IR_PREFIXES]

    n_ir = len(ir_factors)
    n_non_ir = len(non_ir_factors)
    # Split capital: IR and non-IR each get an equal-per-factor share of total
    ir_capital = total_capital_m * n_ir / n_factors if n_factors else 0.0
    non_ir_capital = total_capital_m * n_non_ir / n_factors if n_factors else 0.0

    _ir_sqrt_allocations, _missing_vols = derive_vol_sqrt_budgets(
        ir_factors, _vol_map, total_capital_m=ir_capital
    )
    if _missing_vols:
        logging.getLogger(__name__).warning(
            "Missing vol data for %d IR factor(s): %s — using fallback vol",
            len(_missing_vols), _missing_vols,
        )

    _non_ir_equal = round(non_ir_capital / n_non_ir, 2) if n_non_ir else 0.0

    def get_rp_max(factor):
        if allocation_mode == 'user_defined':
            return float(rp_budgets[factor]) if (rp_budgets and factor in rp_budgets) else equal_share
        if factor.split('.')[0] in _IR_PREFIXES:
            return _ir_sqrt_allocations.get(factor, equal_share)
        # CMDL/FXDL/SPDL: equal share within non-IR capital envelope
        return _non_ir_equal if n_non_ir else equal_share

    # ── Build rows ─────────────────────────────────────────────────────────
    rows = []
    for factor in sorted_factors:
        rp_max = get_rp_max(factor)
        raw_scalar = get_raw_scalar(factor)
        coeff = get_coeff(factor, raw_scalar)
        # In factor_scaling mode, exposure = RP Max × signal coefficient
        # In risk_parity & user_defined modes, exposure = RP Max (coeff is display-only)
        if allocation_mode == 'factor_scaling' and coeff != 0:
            suggested = rp_max * coeff
        else:
            suggested = rp_max
        label, color = scalar_meta(raw_scalar, factor)
        is_default_coeff = factor not in snapshot_by_rf

        vol_val = _vol_map.get(factor)
        has_missing_vol = vol_val is None or pd.isna(vol_val) or vol_val <= 0
        if has_missing_vol:
            vol_str = f"– (est. 15%)"  # Show that we're using estimate
            vol_color = THEME.get('warning', '#f39c12')
        else:
            vol_str = f"{vol_val:.2f}%"
            vol_color = THEME['text_main']

        # Compute DV01 for IR/credit factors (IRDL, IRSL, IRCV, SPDL, SPSL, CRDL, CRSL, CRCV)
        dv01_str = ""
        factor_prefix = factor.split('.')[0]
        if factor_prefix in ('IRDL', 'IRSL', 'IRCV', 'SPDL', 'SPSL', 'CRDL', 'CRSL', 'CRCV'):
            dur = get_factor_weighted_duration(factor)
            if dur is not None and dur > 0:
                dv01 = round(rp_max * dur / 10_000, 2)
                dv01_str = f"{dv01:.2f}"

        # Build row content — coeff column only shown in factor_scaling mode
        row_content = [
            html.Span(factor, style={
                'color': 'var(--accent-blue)', 'fontSize': '11px',
                'width': '130px', 'fontWeight': '600', 'flexShrink': '0',
            }),
            html.Span(vol_str, style={
                'color': vol_color if has_missing_vol else 'var(--text-secondary)', 'fontSize': '11px',
                'width': '80px', 'textAlign': 'right', 'flexShrink': '0',
                'fontFamily': 'monospace',
                'fontWeight': '700' if has_missing_vol else '400',
            }, title='Volatility: if missing data, estimated at 15% (typical commodity vol)'),
            html.Span(f"{round(rp_max)}", style={
                'color': 'var(--text-primary)', 'fontSize': '11px',
                'width': '100px', 'textAlign': 'right', 'flexShrink': '0',
                'fontFamily': 'monospace',
            }, title='Vol√ allocation: from factor volatility weighted by sqrt(vol)'),
            html.Span(dv01_str, style={
                'color': 'var(--text-muted)', 'fontSize': '11px',
                'width': '90px', 'textAlign': 'right', 'flexShrink': '0',
                'fontFamily': 'monospace',
            }),
        ]

        # Add coeff column only in factor_scaling mode
        if allocation_mode == 'factor_scaling':
            row_content.append(
                html.Span(
                    f"×{coeff:+.1f}",
                    title=f"{label}{' (default)' if is_default_coeff else ''}",
                    style={
                        'color': 'var(--text-muted)' if is_default_coeff else color,
                        'fontSize': '11px', 'width': '70px', 'textAlign': 'center',
                        'flexShrink': '0', 'fontWeight': '700',
                        'fontStyle': 'italic' if is_default_coeff else 'normal',
                    }
                )
            )

        # Exposure input: in user_defined mode, allow editing; otherwise read-only
        is_disabled = allocation_mode != 'user_defined'
        row_content.append(
            dcc.Input(
                id={'type': 'risk-budget-input', 'index': factor},
                type='number',
                value=round(suggested),
                step=1,
                disabled=is_disabled,
                className='no-spinner',
                style={
                    'width': '110px', 'flexShrink': '0', 'fontSize': '12px', 'padding': '5px 8px',
                    'background': 'var(--surface-panel)', 'color': 'var(--text-primary)',
                    'border': '1px solid var(--border-strong)',
                    'borderRadius': '3px', 'textAlign': 'right',
                    'fontFamily': 'monospace', 'fontWeight': '400',
                    'opacity': '0.6' if is_disabled else '1.0',
                    'cursor': 'not-allowed' if is_disabled else 'text',
                }
            )
        )

        rows.append(
            html.Div(row_content, style={'display': 'flex', 'alignItems': 'center',
                                          'marginBottom': '4px', 'gap': '4px'})
        )

    return rows


def build_risk_budget_header(allocation_mode):
    """Render column headers; conditionally show Coeff only in factor_scaling mode."""
    _hdr = {'color': 'var(--text-muted)', 'fontSize': '9px', 'fontWeight': '600',
            'textTransform': 'uppercase', 'letterSpacing': '0.05em', 'flexShrink': '0'}
    header_items = [
        html.Span("Factor",          style={**_hdr, 'width': '130px'}),
        html.Span("Vol %ann",        style={**_hdr, 'width': '80px', 'textAlign': 'right'}),
        html.Span("RP Max (MM CNY)", style={**_hdr, 'width': '100px', 'textAlign': 'right'},
                  title='Risk Parity Max allocation in millions CNY'),
        html.Span("DV01 (MM/bp)",    style={**_hdr, 'width': '90px', 'textAlign': 'right'},
                  title='Duration risk in MM CNY per basis point (IR factors only; blank for commodities/FX)'),
    ]

    # Add Coeff column only in factor_scaling mode
    if allocation_mode == 'factor_scaling':
        header_items.append(
            html.Span("Coeff", style={**_hdr, 'width': '70px', 'textAlign': 'center'})
        )

    header_items.append(
        html.Span("Exposure (MM CNY)", style={**_hdr, 'width': '110px', 'textAlign': 'right'})
    )

    return header_items
