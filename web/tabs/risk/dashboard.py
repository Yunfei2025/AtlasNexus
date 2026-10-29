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

from web.tabs.beta.data import THEME
from web.tabs.beta.callbacks._common import (
    _SUMMARY_ALPHA_PARQUET,
    _SUMMARY_BETA_PARQUET,
    _BETA_BOOK_POSITIONS_PARQUET,
)
from .charts import (
    build_net_position_fig,
    build_gross_position_fig,
    build_dv01_ladder_fig,
    build_dv01_ladder_gross_fig,
    build_factor_risk_fig,
    build_kpi_cards,
    build_kpi_strip,
    build_inventory_summary,
    build_short_substitution_panel,
    build_substituted_position_fig,
)
from .short_substitution import build_short_substitutions
from .beta_factor_risk import stored_beta_factor_risk
from settings.general import DEFAULT_ALPHA_BOND_MARGIN_RATE, DEFAULT_ALPHA_SWAP_MARGIN_RATE
from .helpers import (
    beta_direction,
    normalize_risk_ticker,
    _load_leg_data,
    _resolve_legs,
    _parse_repo_spread_legs,
    _tenor_str_to_years,
    _leg_duration_years,
    _leg_volume_ratio,
)
from web.tabs.alpha.data.legs import fly_leg_dv01_ratios, fly_leg_durations, fly_leg_tenor_years, resolve_legs3


def build_risk_positions() -> dict:
    """Load Beta + Alpha positions and net them per instrument.

    Shared by Summary > Risk (charts, ladders, inventory) and Summary >
    Tickets (short-constraint substitutes), so both net the combined book
    the same way. The Beta side is always the saved book
    (summary_beta_portfolio.parquet), never an unsaved Run Analysis result.
    """
    # ── Tenor bucket helper ───────────────────────────────────────────────
    _TENOR_ORDER = ['3M', '6M', '9M', '1Y', '2Y', '5Y', '10Y', '20Y', '30Y']
    _TENOR_BOUNDS = [
        (0.0, 0.375),
        (0.375, 0.625),
        (0.625, 0.875),
        (0.875, 1.5),
        (1.5, 3.5),
        (3.5, 7.0),
        (7.0, 12.0),
        (12.0, 17.0),
        (17.0, 9999.0),
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
    # Beta Book positions are long-short (negative capital = short); Alpha Book legs are
    # long/short per the BUY/SELL direction of the spread (BUY → +leg1 / -leg2).
    net_pos: dict = {}
    # GROSS view: the same positions with long and short kept apart (never netted).
    # gross_pos[code][f'{source}Long'|f'{source}Short'] = capital (short is negative);
    # gross_pos[code][f'{source}DV01Long'|f'{source}DV01Short'] = DV01 likewise.
    gross_pos: dict = {}

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
        g = gross_pos.setdefault(code, {f'{b}{k}': 0.0 for b in ('Beta', 'Alpha')
                                        for k in ('Long', 'Short', 'DV01Long', 'DV01Short')})
        g[f"{source}{'Long' if cap_mm > 0 else 'Short'}"] += cap_mm
        if dv01_mm:
            g[f"{source}DV01{'Long' if dv01_mm > 0 else 'Short'}"] += dv01_mm

    # ── Load Beta positions (saved book; legacy positions file fallback) ──
    beta_rows, kt_grid = [], {t: {c: 0.0 for c in _KT_COLS} for t in _TENOR_ORDER}
    # Separate book-specific risk ladders for dropdown filtering.
    kt_grid_beta = {t: {c: 0.0 for c in _KT_COLS} for t in _TENOR_ORDER}
    kt_grid_alpha = {t: {c: 0.0 for c in _KT_COLS} for t in _TENOR_ORDER}
    # long / short DV01 kept apart for the GROSS ladder: kt_split[book][side][tenor][col]
    kt_split = {b: {sd: {t: {c: 0.0 for c in _KT_COLS} for t in _TENOR_ORDER}
                    for sd in ('long', 'short')} for b in ('beta', 'alpha')}

    def _kt_gross(book: str, tenor: str, col: str, val: float):
        side = kt_split[book]['long' if val > 0 else 'short'][tenor]
        side[col] = round(side[col] + val, 4)
    try:
        # Saved book only -- not the Run Analysis store, whose unsaved last run
        # made Risk describe a different Beta book than the one saved (and the
        # stored-book Factor Risk chart). Unit of 'Capital (CNY)' by source:
        # the legacy positions file holds MM CNY strings ("4,930.00"), but
        # summary_beta_portfolio.parquet holds raw CNY (4930000000).
        _cap_div = 1.0
        if _os.path.exists(_SUMMARY_BETA_PARQUET):
            # Same priority as Summary > Books' Portfolio Allocation
            # Snapshot (web/tabs/risk/books/beta_table.py): the canonical
            # snapshot (Sector/Capital (CNY)/DV01 (MM CNY) schema, same
            # as the legacy file below) takes precedence over the legacy
            # beta_book_positions.parquet export — falling straight to
            # the legacy file here let Net Position by Instrument show
            # stale rows (e.g. an old MTN5Y sleeve) that the current
            # snapshot had already dropped. _SUMMARY_BETA_DISPLAY_PARQUET
            # is skipped: it uses a different schema (Capital (MM CNY),
            # no Sector/DV01 columns) this loop doesn't read.
            bdf = pd.read_parquet(_SUMMARY_BETA_PARQUET)
            _cap_div = 1_000_000.0
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
            if _cap_div != 1.0:
                try:
                    cap_str = f"{float(cap_str.replace(',', '')) / _cap_div:,.2f}"
                except (ValueError, TypeError):
                    cap_str = ''
            dv01_val = r.get('DV01 (MM CNY)', 0)
            try:
                dv01_mm = float(str(dv01_val).replace(',', '')) if dv01_val else 0.0
            except (ValueError, TypeError):
                dv01_mm = 0.0

            instrument = str(r.get('Instrument', ''))
            instrument = normalize_risk_ticker(instrument)
            beta_rows.append({
                'Book': 'Beta', 'Name': name,
                'Leg1': instrument,  # For Beta, Leg1 is the instrument itself
                'Leg2': '', 'Leg3': '',
                'Capital (MM)': cap_str, 'DV01 (MM/bp)': f"{dv01_mm:.4f}",
                'Direction': beta_direction(cap_str),   # SELL for a short (negative capital)
            })
            try:
                cap_mm = float(cap_str.replace(',', '')) if cap_str else 0.0
            except (ValueError, TypeError):
                cap_mm = 0.0
            _add_net(instrument, cap_mm, 'Beta', dv01_mm)  # signed: a short reduces the net position

            # Key Term: rate-tenor Beta positions are bond duration; non-rate sectors → Other
            tenor = _SECTOR_TO_TENOR.get(sector)
            if tenor is None and re.fullmatch(r'\d+(\.\d+)?[MYmy]', sector or ''):
                # numeric tenor with no explicit bucket (e.g. LGB3Y's '3Y', or '7Y'): bucket it
                # by duration (~0.92 x tenor) so its DV01 is not dropped from the ladder / KPI
                tenor = _dur_to_tenor(_tenor_str_to_years(sector.upper()) * 0.92)
            if tenor and dv01_mm != 0.0:
                col = 'Bonds'
                kt_grid[tenor][col] = round(kt_grid[tenor][col] + dv01_mm, 4)
                kt_grid_beta[tenor][col] = round(kt_grid_beta[tenor][col] + dv01_mm, 4)
                _kt_gross('beta', tenor, col, dv01_mm)
    except Exception:
        pass

    # ── Load Alpha positions ──────────────────────────────────────────────
    _ld = _load_leg_data()   # instrument data for leg resolution
    _alpha_snap_cache: dict = {}

    def _leg_bucket(leg_code: str, spread_type: str) -> str:
        return 'Swaps' if _irs_tenor_from_leg(leg_code) else _ALPHA_COL.get(spread_type, 'Other')

    alpha_rows = []
    alpha_trade_legs: list = []        # per trade: [(leg code, signed notional)], for Alpha margin
    alpha_rates = (DEFAULT_ALPHA_BOND_MARGIN_RATE, DEFAULT_ALPHA_SWAP_MARGIN_RATE)
    if _os.path.exists(_SUMMARY_ALPHA_PARQUET):
        try:
            adf = pd.read_parquet(_SUMMARY_ALPHA_PARQUET)

            # Keep only the latest optimization snapshot batch. The Alpha
            # snapshot file is upserted and may retain older trades that are
            # not part of the current portfolio, which would otherwise leak
            # into Net Position by Instrument after a Risk refresh.
            if '_timestamp' in adf.columns:
                _ts = pd.to_datetime(adf['_timestamp'], errors='coerce')
                if _ts.notna().any():
                    _latest_ts = _ts[_ts.notna()].max()
                    adf = adf.loc[_ts.eq(_latest_ts)].copy()
            # margin rates this book was sized with (saved by Run Optimization); older
            # snapshots do not carry them, so the defaults apply
            for _i, _col in enumerate(('_bond_margin_rate', '_swap_margin_rate')):
                if _col in adf.columns:
                    _rate = pd.to_numeric(adf[_col], errors='coerce').dropna()
                    if not _rate.empty and _rate.iloc[-1] > 0:
                        alpha_rates = (_rate.iloc[-1], alpha_rates[1]) if _i == 0 else (alpha_rates[0], _rate.iloc[-1])

            for _, r in adf.iterrows():
                tid = str(r.get('ID', ''))
                if tid in ('', 'TOTAL'):
                    continue
                notional  = abs(float(r.get('notional_mm', 0) or 0))   # magnitude; sign comes from direction
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
                dir_sign  = -1.0 if direction.strip().upper() in ('SELL', 'SHORT') else 1.0

                # Prefer the legs Alpha Portfolio's Run Optimization actually
                # saved (same rule as the Alpha snapshot table); the local
                # resolver is only a fallback for older snapshots. It returns
                # no legs for e.g. TenorSpread Repo7d-3m1y / NCDRepo7d-*, which
                # silently dropped FR007S3M.IR etc. from Net Position / DV01.
                _sl1, _sl2, _sl3 = r.get('Leg1'), r.get('Leg2'), r.get('Leg3')
                _has = lambda v: v not in (None, '') and pd.notna(v)
                # 3-tenor fly (belly=Leg1, short wing=Leg2, long wing=Leg3):
                # read all three legs. The old 2-leg read dropped the long
                # wing and hedged the belly's full DV01 with the short wing,
                # which misstated Net Position (e.g. CGB-2s5s10s showed no
                # 10Y leg and twice the 2Y). A blank saved wing (OTR not
                # resolved at optimization time) is re-resolved here.
                _fly_years = fly_leg_tenor_years(stype, tid)
                leg3 = ''
                if _fly_years is not None:
                    _r1, _r2, _r3 = resolve_legs3(stype, tid, duration, _ld)
                    leg1 = str(_sl1) if _has(_sl1) else _r1
                    leg2 = str(_sl2) if _has(_sl2) else _r2
                    leg3 = str(_sl3) if _has(_sl3) else (_r3 or '')
                elif _has(_sl1) and _has(_sl2):
                    leg1, leg2 = str(_sl1), str(_sl2)
                else:
                    leg1, leg2 = _resolve_legs(stype, tid, duration, _ld)

                leg1 = normalize_risk_ticker(leg1)
                leg2 = normalize_risk_ticker(leg2)
                leg3 = normalize_risk_ticker(leg3) if leg3 else ''

                # Accurate leg volumes: leg1 carries the full target
                # notional; leg2 is duration-matched via Ratio (V2/V1) =
                # Dur(leg1)/Dur(leg2), rounded to the nearest 10MM tick —
                # matching the Alpha Portfolio Allocation Snapshot's
                # Target Volume Leg2 column. Falls back to a 1:1 ratio
                # when either leg's duration cannot be resolved. A fly's
                # wings each take half the belly DV01 (fly_leg_dv01_ratios,
                # the same ratios the optimizer sizes and margins with).
                _abs_notional = abs(notional)
                _fly_legs = (leg1, leg2, leg3)
                _fly_ratios = fly_leg_dv01_ratios(stype, tid, legs=_fly_legs) if _fly_years is not None else None
                leg3_volume_mag = 0.0
                if _fly_ratios is not None:
                    leg2_volume_mag = round(_abs_notional * _fly_ratios[0] / 10.0) * 10.0
                    leg3_volume_mag = round(_abs_notional * _fly_ratios[1] / 10.0) * 10.0
                    # same durations the ratios were built from (actual bond / swap
                    # durations; one nominal triple if any leg's is unavailable)
                    leg1_duration, leg2_duration, leg3_duration = fly_leg_durations(stype, tid, _fly_legs)
                else:
                    leg_ratio = _leg_volume_ratio(leg1, leg2, stype, tid, duration, _alpha_snap_cache)
                    leg2_volume_mag = (
                        round(_abs_notional * leg_ratio / 10.0) * 10.0 if leg_ratio else _abs_notional
                    )
                    leg1_duration = _leg_duration_years(leg1, stype, tid, duration, _alpha_snap_cache) or duration
                    leg2_duration = _leg_duration_years(leg2, stype, tid, duration, _alpha_snap_cache) or duration
                    leg3_duration = 0.0

                leg1_signed = _abs_notional * dir_sign
                leg2_signed = -leg2_volume_mag * dir_sign
                leg3_signed = -leg3_volume_mag * dir_sign   # both wings opposite the belly

                leg1_dv01 = round(leg1_signed * leg1_duration / 10000.0, 4) if leg1 else 0.0
                leg2_dv01 = round(leg2_signed * leg2_duration / 10000.0, 4) if leg2 else 0.0
                leg3_dv01 = round(leg3_signed * leg3_duration / 10000.0, 4) if leg3 else 0.0

                _add_net(leg1, leg1_signed, 'Alpha', leg1_dv01)
                _add_net(leg2, leg2_signed, 'Alpha', leg2_dv01)
                alpha_trade_legs.append([(leg1, leg1_signed), (leg2, leg2_signed), (leg3, leg3_signed)])
                if leg3:
                    _add_net(leg3, leg3_signed, 'Alpha', leg3_dv01)

                alpha_rows.append({
                    'Book': 'Alpha', 'Name': tid,
                    'Leg1': leg1, 'Leg2': leg2, 'Leg3': leg3,
                    'Capital (MM)': f"{leg1_signed:.1f}",   # BUY +, SELL - (leg 1); legs 2/3 are opposite
                    'DV01 (MM/bp)': f"{(leg1_dv01 + leg2_dv01 + leg3_dv01):.4f}",
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
                    if leg3 and leg3_dv01 != 0.0:
                        tenor3 = _irs_tenor_from_leg(leg3) or _dur_to_tenor(leg3_duration)
                        leg_entries.append((tenor3, leg3_dv01, _leg_bucket(leg3, stype)))
                    if not leg_entries:
                        col = _ALPHA_COL.get(stype, 'Other')
                        leg_entries.append((_dur_to_tenor(duration), dv01_mm * dir_sign, col))

                    for tenor, contrib, col in leg_entries:
                        kt_grid[tenor][col] = round(kt_grid[tenor][col] + contrib, 4)
                        kt_grid_alpha[tenor][col] = round(kt_grid_alpha[tenor][col] + contrib, 4)
                        _kt_gross('alpha', tenor, col, contrib)
        except Exception:
            pass

    # Alpha is funded by margin, not notional: book-level netted TRS margin per leg, the
    # same calculation Run Optimization checks Total Capital against (long/short by the
    # sign of each leg's netted exposure). Lazy import: the alpha callbacks import risk.helpers.
    try:
        from web.tabs.alpha.callbacks.portfolio import netted_trs_margin_by_leg
        alpha_margin = netted_trs_margin_by_leg(alpha_trade_legs, alpha_rates[0], alpha_rates[1])
    except Exception:
        alpha_margin = {}

    return {
        'beta_rows': beta_rows, 'alpha_rows': alpha_rows, 'alpha_margin': alpha_margin,
        'net_pos': net_pos, 'gross_pos': gross_pos,
        'kt_grid': kt_grid, 'kt_grid_beta': kt_grid_beta, 'kt_grid_alpha': kt_grid_alpha,
        'kt_split': kt_split, 'tenor_order': _TENOR_ORDER, 'kt_cols': _KT_COLS,
        'otr_cgb': _ld.get('otr_cgb', {}),
    }


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
         Input('risk-inventory-expanded', 'data'),
         Input('risk-netpos-view', 'value'),
         Input('risk-dv01-view', 'value')],
        prevent_initial_call=False,
    )
    def update_risk_tables(tab_value, _n_clicks, allocation_results_data, netpos_filter, dv01_filter, inventory_expanded,
                           netpos_view='net', dv01_view='net'):
        if tab_value != 'risk':
            raise dash.exceptions.PreventUpdate

        _triggered = dash.ctx.triggered_id
        _chart_only_trigger = _triggered in {'risk-netpos-book-filter', 'risk-dv01-book-filter',
                                             'risk-netpos-view', 'risk-dv01-view'}

        def _no_data_div(msg):
            return html.Div(msg, style={'color': THEME['text_sub'], 'fontStyle': 'italic',
                                        'padding': '20px', 'textAlign': 'center', 'fontSize': '13px'})

        _pos = build_risk_positions()
        beta_rows, alpha_rows = _pos['beta_rows'], _pos['alpha_rows']
        net_pos, gross_pos = _pos['net_pos'], _pos['gross_pos']
        kt_grid, kt_grid_beta, kt_grid_alpha = _pos['kt_grid'], _pos['kt_grid_beta'], _pos['kt_grid_alpha']
        kt_split, _TENOR_ORDER, _KT_COLS = _pos['kt_split'], _pos['tenor_order'], _pos['kt_cols']

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
                     ['Book', 'Name', 'Leg1', 'Leg2', 'Leg3',
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

        # Short-constraint note + substitutes: always the combined (mixed) book,
        # since execution nets Beta and Alpha whatever the chart filter shows.
        try:
            _short_subs = build_short_substitutions(net_pos, _pos['otr_cgb'])
        except Exception:
            _short_subs = []

        _view = (netpos_view or 'net').lower()
        if _view == 'substitute':
            # Executable book: combined net with disallowed shorts moved to their
            # substitutes (book filter ignored -- substitution is combined-only).
            netpos_fig = build_substituted_position_fig(net_pos, _short_subs)
        elif _view == 'gross':
            # GROSS: long and short kept apart per instrument (beta / alpha / mixed per the book filter)
            def _g(vals, key):
                if _netpos_mode == 'beta':
                    return vals.get(f'Beta{key}', 0.0)
                if _netpos_mode == 'alpha':
                    return vals.get(f'Alpha{key}', 0.0)
                return vals.get(f'Beta{key}', 0.0) + vals.get(f'Alpha{key}', 0.0)
            gross_view = {
                code: {'Long': _g(v, 'Long'), 'Short': _g(v, 'Short'),
                       'DV01Long': _g(v, 'DV01Long'), 'DV01Short': _g(v, 'DV01Short')}
                for code, v in gross_pos.items()
            }
            netpos_fig = build_gross_position_fig(gross_view)
        else:
            netpos_fig = build_net_position_fig(net_pos_view)
        netpos_graph = html.Div([
            dcc.Graph(figure=netpos_fig, config={'displayModeBar': False}),
            build_short_substitution_panel(_short_subs),
        ])

        # ── Factor Risk (stored Beta book only, no SPDL/SPSL) ────────────────
        # Recomputed from summary_beta_portfolio.parquet, not the Run Analysis
        # store: that is the last session run's pre-tilt RP attribution, not
        # the book that was saved (see beta_factor_risk.py).
        try:
            factor_risk_df = stored_beta_factor_risk()
        except Exception:
            factor_risk_df = None

        # ── DV01 Duration Ladder chart (book-filtered) ───────────────────────
        _dv01_mode = (dv01_filter or 'mixed').lower()
        if _dv01_mode == 'beta':
            kt_grid_view = kt_grid_beta
        elif _dv01_mode == 'alpha':
            kt_grid_view = kt_grid_alpha
        else:
            kt_grid_view = kt_grid

        if (dv01_view or 'net').lower() == 'gross':
            def _kt_side(side):
                books = ['beta'] if _dv01_mode == 'beta' else ['alpha'] if _dv01_mode == 'alpha' else ['beta', 'alpha']
                return {t: {c: sum(kt_split[b][side][t][c] for b in books) for c in _KT_COLS} for t in _TENOR_ORDER}
            dv01_fig = build_dv01_ladder_gross_fig(_kt_side('long'), _kt_side('short'), _TENOR_ORDER)
        else:
            dv01_fig = build_dv01_ladder_fig(kt_grid_view, _TENOR_ORDER)
        dv01_graph = dcc.Graph(figure=dv01_fig, config={'displayModeBar': False})

        # ── Factor Risk Attribution chart (sqrt-scale, from factor_risk_df) ────
        factor_fig = build_factor_risk_fig(factor_risk_df)
        factor_graph = dcc.Graph(figure=factor_fig, config={'displayModeBar': False})

        # ── KPI strip ───────────────────────────────────────────────────────────
        kpis = build_kpi_cards(net_pos, kt_grid, _TENOR_ORDER, kt_split, alpha_margin=_pos['alpha_margin'])
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
