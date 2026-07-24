# -*- coding: utf-8 -*-
"""Summary > Risk subtab callbacks: KPI strip, Net Position by Instrument,
DV01 Duration Ladder, Factor Risk Attribution, and Position Inventory.
"""

from __future__ import annotations

import os as _os
import re

import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State
import pandas as pd
from datetime import datetime

from ..data import THEME, ALLOCATION_RESULTS
from ._common import (
    _SUMMARY_ALPHA_PARQUET,
    _BETA_BOOK_POSITIONS_PARQUET,
)
from ._risk_charts import (
    build_net_position_fig,
    build_dv01_ladder_fig,
    build_factor_risk_fig,
    build_kpi_cards,
    build_kpi_strip,
    build_inventory_summary,
)
from .risk_helpers import (
    _load_leg_data,
    _resolve_legs,
    _parse_repo_spread_legs,
    _tenor_str_to_years,
    _leg_duration_years,
    _leg_volume_ratio,
)


def register_risk_dashboard_callbacks(app):
    """Register Summary > Risk subtab callbacks."""

    @app.callback(
        [Output('risk-netpos-book-filter', 'value'),
         Output('risk-dv01-book-filter', 'value')],
        [Input('risk-netpos-book-filter', 'value'),
         Input('risk-dv01-book-filter', 'value')],
        prevent_initial_call=True,
    )
    def _sync_risk_book_filters(netpos_value, dv01_value):
        triggered = dash.ctx.triggered_id
        if triggered == 'risk-netpos-book-filter':
            value = (netpos_value or 'mixed').lower()
            return value, value
        if triggered == 'risk-dv01-book-filter':
            value = (dv01_value or 'mixed').lower()
            return value, value
        raise dash.exceptions.PreventUpdate

    # ── Risk subtab: inventory + factor exposure + key-term DV01 ladder ─────────
    @app.callback(
        [Output('risk-kpi-container', 'children'),
         Output('risk-netpos-container', 'children'),
         Output('risk-dv01-container', 'children'),
         Output('risk-factor-container', 'children'),
         Output('risk-inventory-container', 'children'),
         Output('risk-refresh-status', 'children')],
        [Input('an-summary-subtabs', 'value'),
         Input('risk-refresh-btn', 'n_clicks'),
         Input('allocation-results-store', 'data'),
         Input('risk-netpos-book-filter', 'value'),
         Input('risk-dv01-book-filter', 'value'),
         Input('risk-inventory-expanded', 'data')],
        prevent_initial_call=False,
    )
    def update_risk_tables(tab_value, _n_clicks, allocation_results_data, netpos_filter, dv01_filter, inventory_expanded):
        if tab_value != 'risk':
            raise dash.exceptions.PreventUpdate

        _triggered = dash.ctx.triggered_id
        _chart_only_trigger = _triggered in {'risk-netpos-book-filter', 'risk-dv01-book-filter'}

        def _no_data_div(msg):
            return html.Div(msg, style={'color': THEME['text_sub'], 'fontStyle': 'italic',
                                        'padding': '20px', 'textAlign': 'center', 'fontSize': '13px'})

        # ── Tenor bucket helper ───────────────────────────────────────────────
        _TENOR_ORDER = ['3M', '6M', '9M', '1Y', '2Y', '5Y', '10Y', '30Y', '20Y']
        _TENOR_BOUNDS = [
            (0.0, 0.375),
            (0.375, 0.625),
            (0.625, 0.875),
            (0.875, 1.5),
            (1.5, 3.5),
            (3.5, 7.0),
            (7.0, 12.0),
            (17.0, 9999.0),
            (12.0, 17.0),
        ]

        def _dur_to_tenor(dur: float) -> str:
            for label, (lo, hi) in zip(_TENOR_ORDER, _TENOR_BOUNDS):
                if lo <= dur < hi:
                    return label
            return '30Y'

        def _irs_tenor_from_leg(leg: str) -> str | None:
            match = re.search(r'(?:FR007S|SHI3MS)(\d+[MY])\.IR$', str(leg).upper())
            if not match:
                return None
            return _dur_to_tenor(_tenor_str_to_years(match.group(1)))

        _SECTOR_TO_TENOR = {'3M': '3M', '6M': '6M', '9M': '9M', '1Y': '1Y', '2Y': '2Y', '5Y': '5Y',
                    '10Y': '10Y', '20Y': '20Y', '30Y': '30Y'}

        # ── Alpha spread-type → Key Term column (Bonds/Swaps/Futures/Other) ───
        _ALPHA_COL = {
            'TBondCurve':  'Bonds', 'TBondSwap':  'Bonds',
            'CBondCurve':  'Bonds', 'CBondSwap':  'Bonds',
            'TenorSpread': 'Bonds',
            'IRS':         'Swaps',
            'SwapSpread':  'Swaps',  # Repo7d-XyYy IRS spreads stored as SwapSpread
            'CDB':         'Bonds',
            'ICP':         'Swaps',
            'NetBasis':    'Futures', 'TermBasis': 'Futures', 'FuturesSwap': 'Futures',
        }
        _KT_COLS = ['Bonds', 'Swaps', 'Futures', 'Other']

        # ── Net position by instrument: signed capital (MM CNY) per code ──────
        # Beta Book positions are always long. Alpha Book legs are long/short
        # per the BUY/SELL direction of the spread (BUY → +leg1 / -leg2).
        net_pos: dict = {}

        def _add_net(code: str, cap_mm: float, source: str, dv01_mm: float = 0.0):
            if not code or abs(cap_mm) < 1e-9:
                return
            e = net_pos.setdefault(code, {
                'Beta': 0.0, 'Alpha': 0.0,
                'BetaDV01': 0.0, 'AlphaDV01': 0.0,
            })
            e[source] = round(e[source] + cap_mm, 4)
            if source == 'Beta':
                e['BetaDV01'] = round(e['BetaDV01'] + dv01_mm, 4)
            else:
                e['AlphaDV01'] = round(e['AlphaDV01'] + dv01_mm, 4)

        # ── Load Beta positions (live store first, parquet fallback) ──────────
        beta_rows, kt_grid = [], {t: {c: 0.0 for c in _KT_COLS} for t in _TENOR_ORDER}
        # Separate book-specific risk ladders for dropdown filtering.
        kt_grid_beta = {t: {c: 0.0 for c in _KT_COLS} for t in _TENOR_ORDER}
        kt_grid_alpha = {t: {c: 0.0 for c in _KT_COLS} for t in _TENOR_ORDER}
        _beta_records = []
        if allocation_results_data and isinstance(allocation_results_data, dict):
            _beta_records = allocation_results_data.get('beta_snapshot_display', []) or []

        try:
            if _beta_records:
                bdf = pd.DataFrame(_beta_records)
            elif _os.path.exists(_BETA_BOOK_POSITIONS_PARQUET):
                bdf = pd.read_parquet(_BETA_BOOK_POSITIONS_PARQUET)
            else:
                bdf = pd.DataFrame()

            for _, r in bdf.iterrows():
                atype = str(r.get('Asset Type', ''))
                if atype == 'TOTAL':
                    continue
                name = str(r.get('Asset Name', ''))
                sector = str(r.get('Sector', ''))
                cap_str = str(r.get('Capital (CNY)', ''))
                dv01_val = r.get('DV01 (MM CNY)', 0)
                try:
                    dv01_mm = float(str(dv01_val).replace(',', '')) if dv01_val else 0.0
                except (ValueError, TypeError):
                    dv01_mm = 0.0

                instrument = str(r.get('Instrument', ''))
                beta_rows.append({
                    'Book': 'Beta', 'Name': name,
                    'Leg1': instrument,  # For Beta, Leg1 is the instrument itself
                    'Leg2': '',
                    'Capital (MM)': cap_str, 'DV01 (MM/bp)': f"{dv01_mm:.4f}",
                    'Direction': 'BUY',  # Beta positions are always BUY
                })
                try:
                    cap_mm = float(cap_str.replace(',', '')) if cap_str else 0.0
                except (ValueError, TypeError):
                    cap_mm = 0.0
                _add_net(instrument, cap_mm, 'Beta', dv01_mm)  # Beta Book positions are always long

                # Key Term: rate-tenor Beta positions are bond duration; non-rate sectors → Other
                tenor = _SECTOR_TO_TENOR.get(sector)
                if tenor and dv01_mm != 0.0:
                    col = 'Bonds' if sector in _SECTOR_TO_TENOR else 'Other'
                    kt_grid[tenor][col] = round(kt_grid[tenor][col] + dv01_mm, 4)
                    kt_grid_beta[tenor][col] = round(kt_grid_beta[tenor][col] + dv01_mm, 4)
        except Exception:
            pass

        # ── Load Alpha positions ──────────────────────────────────────────────
        _ld = _load_leg_data()   # instrument data for leg resolution
        _alpha_snap_cache: dict = {}

        def _leg_bucket(leg_code: str, spread_type: str) -> str:
            return 'Swaps' if _irs_tenor_from_leg(leg_code) else _ALPHA_COL.get(spread_type, 'Other')

        alpha_rows = []
        if _os.path.exists(_SUMMARY_ALPHA_PARQUET):
            try:
                adf = pd.read_parquet(_SUMMARY_ALPHA_PARQUET)
                for _, r in adf.iterrows():
                    tid = str(r.get('ID', ''))
                    if tid in ('', 'TOTAL'):
                        continue
                    notional  = float(r.get('notional_mm', 0) or 0)
                    dv01_k    = float(r.get('DV01_k', 0) or 0)
                    dv01_mm   = dv01_k / 1000.0          # k CNY → MM CNY
                    dur_raw   = r.get('_duration', None)
                    if dur_raw is not None and pd.notna(dur_raw):
                        duration = float(dur_raw)
                    elif notional > 0:
                        duration = dv01_k * 10.0 / notional
                    else:
                        duration = 0.0
                    direction = str(r.get('direction', 'BUY'))
                    stype     = str(r.get('spread_type', ''))
                    dir_sign  = -1.0 if direction in ('SELL', 'SHORT') else 1.0

                    leg1, leg2 = _resolve_legs(stype, tid, duration, _ld)

                    # Accurate leg volumes: leg1 carries the full target
                    # notional; leg2 is duration-matched via Ratio (V2/V1) =
                    # Dur(leg1)/Dur(leg2), rounded to the nearest 10MM tick —
                    # matching the Alpha Portfolio Allocation Snapshot's
                    # Target Volume Leg2 column. Falls back to a 1:1 ratio
                    # when either leg's duration cannot be resolved.
                    _abs_notional = abs(notional)
                    leg_ratio = _leg_volume_ratio(leg1, leg2, stype, tid, duration, _alpha_snap_cache)
                    leg2_volume_mag = (
                        round(_abs_notional * leg_ratio / 10.0) * 10.0 if leg_ratio else _abs_notional
                    )

                    leg1_signed = _abs_notional * dir_sign
                    leg2_signed = -leg2_volume_mag * dir_sign

                    leg1_duration = _leg_duration_years(leg1, stype, tid, duration, _alpha_snap_cache) or duration
                    leg2_duration = _leg_duration_years(leg2, stype, tid, duration, _alpha_snap_cache) or duration
                    leg1_dv01 = round(leg1_signed * leg1_duration / 10000.0, 4) if leg1 else 0.0
                    leg2_dv01 = round(leg2_signed * leg2_duration / 10000.0, 4) if leg2 else 0.0

                    _add_net(leg1, leg1_signed, 'Alpha', leg1_dv01)
                    _add_net(leg2, leg2_signed, 'Alpha', leg2_dv01)

                    alpha_rows.append({
                        'Book': 'Alpha', 'Name': tid,
                        'Leg1': leg1, 'Leg2': leg2,
                        'Capital (MM)': f"{notional:.1f}",
                        'DV01 (MM/bp)': f"{(leg1_dv01 + leg2_dv01):.4f}",
                        'Direction': direction,
                    })

                    # Key Term ladder: DV01 per leg = (accurate leg volume) ×
                    # (that leg's own duration), so mixed bond/swap trades
                    # (e.g. CGBRepo7d-5y) split accurately across the Bonds
                    # and Swaps buckets — consistent with net positions.
                    if dv01_mm != 0.0:

                        leg_entries: list[tuple[str, float, str]] = []
                        if leg1 and leg1_dv01 != 0.0:
                            tenor1 = _irs_tenor_from_leg(leg1) or _dur_to_tenor(leg1_duration)
                            leg_entries.append((tenor1, leg1_dv01, _leg_bucket(leg1, stype)))
                        if leg2 and leg2_dv01 != 0.0:
                            tenor2 = _irs_tenor_from_leg(leg2) or _dur_to_tenor(leg2_duration)
                            leg_entries.append((tenor2, leg2_dv01, _leg_bucket(leg2, stype)))
                        if not leg_entries:
                            col = _ALPHA_COL.get(stype, 'Other')
                            leg_entries.append((_dur_to_tenor(duration), dv01_mm * dir_sign, col))

                        for tenor, contrib, col in leg_entries:
                            kt_grid[tenor][col] = round(kt_grid[tenor][col] + contrib, 4)
                            kt_grid_alpha[tenor][col] = round(kt_grid_alpha[tenor][col] + contrib, 4)
            except Exception:
                pass

        if not beta_rows and not alpha_rows:
            _empty_msg = "No positions found — run analysis (Beta) or optimization (Alpha) first."
            return (
                build_kpi_strip({"long": 0.0, "short": 0.0, "net": 0.0, "dv01": 0.0}),
                _no_data_div(_empty_msg),
                _no_data_div("No data."),
                _no_data_div("No data."),
                _no_data_div(_empty_msg),
                "",
            )

        # ── Inventory table (full DataTable, shown when expanded) ─────────────
        all_rows = beta_rows + alpha_rows
        _dir_style = [
            {'if': {'filter_query': '{Direction} = "BUY"'},
             'backgroundColor': 'rgba(0,204,150,0.08)'},
            {'if': {'filter_query': '{Direction} = "SELL"'},
             'backgroundColor': 'rgba(239,85,59,0.08)'},
            {'if': {'filter_query': '{Book} = "Beta"', 'column_id': 'Book'},
             'color': THEME['accent'], 'fontWeight': 'bold'},
            {'if': {'filter_query': '{Book} = "Alpha"', 'column_id': 'Book'},
             'color': THEME['danger'], 'fontWeight': 'bold'},
        ]
        inventory_table = dash_table.DataTable(
            data=all_rows,
            columns=[{'name': c, 'id': c} for c in
                     ['Book', 'Name', 'Leg1', 'Leg2',
                      'Capital (MM)', 'DV01 (MM/bp)', 'Direction']],
            style_cell={'textAlign': 'center', 'padding': '5px 8px', 'fontSize': '12px',
                        'backgroundColor': THEME['table_row_odd'],
                        'color': THEME['text_main'], 'border': 'none'},
            style_header={'backgroundColor': THEME['table_header'], 'color': THEME['text_main'],
                          'fontWeight': 'bold', 'border': 'none'},
            style_data_conditional=[
                {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']},
                *_dir_style,
            ],
            style_table={'overflowX': 'auto'},
            sort_action='native', page_size=40,
        )

        inventory_content = (
            inventory_table if inventory_expanded
            else build_inventory_summary(beta_rows, alpha_rows)
        )

        # ── Net position by instrument chart (book-filtered) ─────────────────
        _netpos_mode = (netpos_filter or 'mixed').lower()
        if _netpos_mode == 'beta':
            net_pos_view = {
                code: {
                    'Beta': vals.get('Beta', 0.0),
                    'Alpha': 0.0,
                    'DV01': vals.get('BetaDV01', 0.0),
                    'BetaDV01': vals.get('BetaDV01', 0.0),
                    'AlphaDV01': 0.0,
                }
                for code, vals in net_pos.items()
            }
        elif _netpos_mode == 'alpha':
            net_pos_view = {
                code: {
                    'Beta': 0.0,
                    'Alpha': vals.get('Alpha', 0.0),
                    'DV01': vals.get('AlphaDV01', 0.0),
                    'BetaDV01': 0.0,
                    'AlphaDV01': vals.get('AlphaDV01', 0.0),
                }
                for code, vals in net_pos.items()
            }
        else:
            net_pos_view = {
                code: {
                    **vals,
                    'DV01': round(vals.get('BetaDV01', 0.0) + vals.get('AlphaDV01', 0.0), 4),
                }
                for code, vals in net_pos.items()
            }

        netpos_fig = build_net_position_fig(net_pos_view)
        netpos_graph = dcc.Graph(figure=netpos_fig, config={'displayModeBar': False})

        # ── Factor Risk (Beta only, no SPDL/SPSL) — feeds the Factor Risk chart ─
        # Try to get factor_risk from the store (updated by RUN ANALYSIS),
        # fall back to global ALLOCATION_RESULTS for backwards compatibility
        _factor_risk_records = None
        if allocation_results_data and isinstance(allocation_results_data, dict):
            _factor_risk_records = allocation_results_data.get('factor_risk')
        if not _factor_risk_records:
            _factor_risk_records = ALLOCATION_RESULTS.get('factor_risk')

        # Convert records list to DataFrame if needed
        if isinstance(_factor_risk_records, list) and _factor_risk_records:
            factor_risk_df = pd.DataFrame(_factor_risk_records)
        elif isinstance(_factor_risk_records, pd.DataFrame):
            factor_risk_df = _factor_risk_records
        else:
            factor_risk_df = None

        # ── DV01 Duration Ladder chart (book-filtered) ───────────────────────
        _dv01_mode = (dv01_filter or 'mixed').lower()
        if _dv01_mode == 'beta':
            kt_grid_view = kt_grid_beta
        elif _dv01_mode == 'alpha':
            kt_grid_view = kt_grid_alpha
        else:
            kt_grid_view = kt_grid

        dv01_fig = build_dv01_ladder_fig(kt_grid_view, _TENOR_ORDER)
        dv01_graph = dcc.Graph(figure=dv01_fig, config={'displayModeBar': False})

        # ── Factor Risk Attribution chart (sqrt-scale, from factor_risk_df) ────
        factor_fig = build_factor_risk_fig(factor_risk_df)
        factor_graph = dcc.Graph(figure=factor_fig, config={'displayModeBar': False})

        # ── KPI strip ───────────────────────────────────────────────────────────
        kpis = build_kpi_cards(net_pos, kt_grid, _TENOR_ORDER)
        kpi_strip = build_kpi_strip(kpis)

        n_beta  = len(beta_rows)
        n_alpha = len(alpha_rows)
        status  = (f"{n_beta} beta · {n_alpha} alpha positions · "
                   f"updated {datetime.now().strftime('%H:%M:%S')}")

        # Dropdown filter changes should only refresh the two charts, not the
        # whole Risk panel content.
        if _chart_only_trigger:
            return dash.no_update, netpos_graph, dv01_graph, dash.no_update, dash.no_update, dash.no_update

        return kpi_strip, netpos_graph, dv01_graph, factor_graph, inventory_content, status

    # ── Position Inventory: collapse/expand toggle ──────────────────────────────
    @app.callback(
        [Output('risk-inventory-expanded', 'data'),
         Output('risk-inventory-toggle-btn', 'children')],
        Input('risk-inventory-toggle-btn', 'n_clicks'),
        State('risk-inventory-expanded', 'data'),
        prevent_initial_call=True,
    )
    def _toggle_risk_inventory(_n_clicks, expanded):
        is_expanded = not bool(expanded)
        label = "▲ Collapse" if is_expanded else "▼ Expand table"
        return is_expanded, label
