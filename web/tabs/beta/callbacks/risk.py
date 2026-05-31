# -*- coding: utf-8 -*-
"""Risk / Summary tab callbacks: subtab show/hide, books table refresh."""

from __future__ import annotations

import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import os
import traceback
import pathlib
from datetime import datetime

from multiasset.layout import prepare_portfolio_table
from settings.paths import DIR_INPUT

from ..data import THEME, ALLOCATION_RESULTS
from ._common import (
    _SUMMARY_BETA_PARQUET,
    _SUMMARY_ALPHA_PARQUET,
    _BETA_BOOK_POSITIONS_PARQUET,
    _BETA_BOOK_USER_PARQUET,
    _ALPHA_POSITIONS_PARQUET,
    _get_beta_close_prices,
    _load_cr_ts,
)


def _coerce_float(value) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return float(str(value).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None


def _compute_alpha_carry_mtm(
    spread_type: str,
    instrument_id: str,
    open_date_str: str,
    volume_mm: float | None,
) -> float | None:
    if _load_cr_ts is None or not open_date_str or not volume_mm:
        return None
    try:
        cr_ts = _load_cr_ts(spread_type)
        if cr_ts is None or instrument_id not in cr_ts.columns:
            return None
        series = cr_ts[instrument_id].dropna()
        open_dt = pd.to_datetime(open_date_str)
        today = pd.Timestamp.today().normalize()
        mask = (series.index >= open_dt) & (series.index <= today)
        carry_cum_pct = float(series[mask].sum()) / 90.0
        return round(volume_mm * carry_cum_pct / 100.0, 4)
    except Exception:
        return None


def _refresh_alpha_display_row(row: dict) -> dict:
    updated = dict(row)
    open_price_bp = _coerce_float(updated.get('Open price (bp)'))
    volume_mm = _coerce_float(updated.get('Volume (mm)'))
    duration = _coerce_float(updated.get('Duration'))
    close_price_bp = _coerce_float(updated.get('Close Price (bp)'))

    mtm_price_mm = None
    if None not in (open_price_bp, volume_mm, duration, close_price_bp):
        mtm_price_mm = round(
            volume_mm * duration * (close_price_bp - open_price_bp) / 10000.0,
            4,
        )

    mtm_carry_mm = _compute_alpha_carry_mtm(
        str(updated.get('Spread Type', '')),
        str(updated.get('ID', '')),
        str(updated.get('Open date', '')),
        volume_mm,
    )

    mtm_total_mm = None
    if mtm_price_mm is not None or mtm_carry_mm is not None:
        mtm_total_mm = round((mtm_price_mm or 0.0) + (mtm_carry_mm or 0.0), 4)

    updated['MTM spd (bp)'] = f"{open_price_bp:,.4f}" if open_price_bp is not None else ''
    updated['MtM Carry (MM CNY)'] = f"{mtm_carry_mm:,.4f}" if mtm_carry_mm is not None else ''
    updated['MtM Value (MM CNY)'] = f"{mtm_total_mm:,.4f}" if mtm_total_mm is not None else ''
    return updated


def _persist_alpha_summary_rows(rows: list[dict]) -> None:
    # Skip the synthetic TOTAL row — it is not a real position.
    records = [{
        'spread_type': str(r.get('Spread Type', '')),
        'ID': str(r.get('ID', '')),
        'open_price_bp': r.get('Open price (bp)', ''),
        'volume_mm': r.get('Volume (mm)', ''),
        'open_date': str(r.get('Open date', '')),
    } for r in rows if str(r.get('ID', '')) != 'TOTAL']
    pd.DataFrame(records).to_parquet(_ALPHA_POSITIONS_PARQUET, index=False)

    if not os.path.exists(_SUMMARY_ALPHA_PARQUET):
        return

    snapshot = pd.read_parquet(_SUMMARY_ALPHA_PARQUET)
    if snapshot.empty or 'ID' not in snapshot.columns:
        snapshot.to_parquet(_SUMMARY_ALPHA_PARQUET, index=False)
        return

    current_keys = {
        (str(r.get('Spread Type', '')), str(r.get('ID', '')))
        for r in rows
        if str(r.get('ID', '')) not in ('', 'TOTAL')
    }

    spread_type_series = snapshot['spread_type'].fillna('').astype(str) if 'spread_type' in snapshot.columns else pd.Series('', index=snapshot.index)
    id_series = snapshot['ID'].fillna('').astype(str)
    row_keys = pd.Series(list(zip(spread_type_series, id_series)), index=snapshot.index)
    keep_mask = id_series.isin(['', 'TOTAL']) | row_keys.isin(current_keys)
    snapshot.loc[keep_mask].to_parquet(_SUMMARY_ALPHA_PARQUET, index=False)


def register_risk_callbacks(app):
    """Register Risk / Summary tab callbacks."""

    # ── Summary tab: show/hide Books / Risk / Tickets subtabs ────────────────
    @app.callback(
        [Output('summary-tab-books',   'style'),
         Output('summary-tab-risk',    'style'),
         Output('summary-tab-tickets', 'style')],
        Input('summary-main-tabs', 'value'),
    )
    def _show_summary_subtab(tab: str):
        show = {'display': 'block'}
        hide = {'display': 'none'}
        return (
            show if tab == 'books'   else hide,
            show if tab == 'risk'    else hide,
            show if tab == 'tickets' else hide,
        )

    # ── Summary tab: Beta / Alpha portfolio table callback ────────────────────
    # NOTE: The State on 'summary-alpha-table' was removed because that component
    # is *created* by this callback — referencing it as State caused Dash to fail
    # to register the callback in some browser sessions, leaving the Alpha tab blank.
    # User edits are persisted by `_autosave_alpha_table` below, not by this callback.
    @app.callback(
        [Output('summary-book-table-container', 'children'),
         Output('summary-refresh-status', 'children')],
        [Input('summary-book-tabs', 'value'),
         Input('summary-refresh-btn', 'n_clicks')],
        prevent_initial_call=False,
    )
    def update_summary_book_table(tab_value, _n_clicks):
        """Load the saved parquet snapshot and render a styled table with
        Close Price and Market Value columns.  Alpha table includes editable
        fields (Open price, Volume, Open date) persisted to a separate parquet."""
        import os as _os
        from dash import ctx as _ctx

        def _no_data(msg: str):
            return (
                html.Div(msg, style={
                    'color': THEME['text_sub'], 'fontStyle': 'italic',
                    'padding': '30px', 'textAlign': 'center', 'fontSize': '13px',
                }),
                "",
            )

        # ─── helpers ──────────────────────────────────────────────────────────
        def _load_positions() -> dict:
            """Return {(spread_type, id): {open_price_bp, volume_mm, open_date}} from persisted parquet."""
            if _os.path.exists(_ALPHA_POSITIONS_PARQUET):
                try:
                    pos = pd.read_parquet(_ALPHA_POSITIONS_PARQUET)
                    result = {}
                    for _, r in pos.iterrows():
                        key = (str(r.get('spread_type', '')), str(r.get('ID', '')))
                        result[key] = {
                            'open_price_bp': r.get('open_price_bp', ''),
                            'volume_mm':     r.get('volume_mm', ''),
                            'open_date':     str(r.get('open_date', '')),
                        }
                    return result
                except Exception:
                    pass
            return {}

        def _save_positions(rows: list[dict], spread_type_col: str = 'Spread Type'):
            """Persist user-editable fields from the current table to parquet."""
            if not rows:
                return
            records = []
            for r in rows:
                records.append({
                    'spread_type':   str(r.get(spread_type_col, '')),
                    'ID':            str(r.get('ID', '')),
                    'open_price_bp': r.get('Open price (bp)', ''),
                    'volume_mm':     r.get('Volume (mm)', ''),
                    'open_date':     str(r.get('Open date', '')),
                })
            try:
                pd.DataFrame(records).to_parquet(_ALPHA_POSITIONS_PARQUET, index=False)
            except Exception:
                pass

        def _compute_carry_mtm(spread_type: str, instrument_id: str,
                               open_date_str: str, volume_mm: float) -> float | None:
            """Compute cumulative carry+roll MTM from open_date to today (MM CNY)."""
            if _load_cr_ts is None or not open_date_str or not volume_mm:
                return None
            try:
                cr_ts = _load_cr_ts(spread_type)  # DataFrame: dates × instruments (3m carry in %)
                if cr_ts is None or instrument_id not in cr_ts.columns:
                    return None
                series = cr_ts[instrument_id].dropna()
                open_dt = pd.to_datetime(open_date_str)
                today   = pd.Timestamp.today().normalize()
                mask = (series.index >= open_dt) & (series.index <= today)
                carry_cum_pct = float(series[mask].sum()) / 90.0  # cumulative carry fraction in %
                return round(volume_mm * carry_cum_pct / 100.0, 4)
            except Exception:
                return None

        # ── Beta tab ──────────────────────────────────────────────────────────
        if tab_value == 'beta':
            if not _os.path.exists(_BETA_BOOK_POSITIONS_PARQUET) and not _os.path.exists(_SUMMARY_BETA_PARQUET):
                return _no_data(
                    "No Beta snapshot found. Click RUN ANALYSIS in the Beta Book → Portfolio tab first."
                )
            try:
                if _os.path.exists(_BETA_BOOK_POSITIONS_PARQUET):
                    df = pd.read_parquet(_BETA_BOOK_POSITIONS_PARQUET)
                else:
                    df = pd.read_parquet(_SUMMARY_BETA_PARQUET)

                if df.empty:
                    return _no_data("Beta snapshot is empty.")

                ts = "unknown"
                if _os.path.exists(_SUMMARY_BETA_PARQUET):
                    try:
                        snap = pd.read_parquet(_SUMMARY_BETA_PARQUET)
                        ts = snap['_timestamp'].iloc[0] if '_timestamp' in snap.columns else "unknown"
                    except Exception:
                        ts = "unknown"

                # Load user-editable fields (open_yld, open_date, volume) keyed by asset_name+instrument
                user_data: dict = {}
                if _os.path.exists(_BETA_BOOK_USER_PARQUET):
                    try:
                        udf = pd.read_parquet(_BETA_BOOK_USER_PARQUET)
                        for _, r in udf.iterrows():
                            key = (str(r.get('asset_name', '')), str(r.get('instrument', '')))
                            user_data[key] = {
                                'open_yld':  str(r.get('open_yld', '')),
                                'open_date': str(r.get('open_date', '')),
                                'volume':    str(r.get('volume', '')),
                            }
                    except Exception:
                        pass

                # Get latest close yields from factor levels
                close_prices = _get_beta_close_prices()  # {prefix: yield_pct}

                display_rows = []
                for _, row in df.iterrows():
                    asset_type = str(row.get('Asset Type', ''))
                    if asset_type == 'TOTAL':
                        continue
                    asset_name = str(row.get('Asset Name', ''))
                    instrument = str(row.get('Instrument', ''))
                    key = (asset_name, instrument)
                    saved = user_data.get(key, {})

                    open_yld_str  = str(saved.get('open_yld', ''))
                    open_date_str = str(saved.get('open_date', ''))
                    volume_str    = str(saved.get('volume', ''))

                    # Close yield: look up by asset-name prefix (e.g. 'CN' → IRDL.CN)
                    prefix = asset_name[:2]
                    close_yld = close_prices.get(prefix)
                    close_yld_str = f"{close_yld:.4f}%" if close_yld is not None else ''

                    # MtM price P&L: Volume × Duration × (Close - Open) / 10000  (MM CNY)
                    mtm_str = ''
                    try:
                        _dur_raw = row.get('Duration', None)
                        _dur = float(str(_dur_raw).replace(',', '')) if _dur_raw not in (None, '', 'N/A') else None
                        _vol = float(volume_str) if volume_str else None
                        _open_y = float(open_yld_str) if open_yld_str else None
                        if _dur and _vol and _open_y and close_yld is not None:
                            mtm = round(_vol * _dur * (close_yld - _open_y) / 10000.0, 4)
                            mtm_str = f"{mtm:+.4f}"
                    except (ValueError, TypeError):
                        pass

                    display_rows.append({
                        'Asset Type':       asset_type,
                        'Universe':         str(row.get('Universe', '')),
                        'Sector':           str(row.get('Sector', '')),
                        'Asset Name':       asset_name,
                        'Instrument':       instrument,
                        'Duration':         str(row.get('Duration', '')),
                        'Capital (MM CNY)': str(row.get('Capital (CNY)', '')),
                        'Weight (%)':       str(row.get('Weight (%)', '')),
                        'Open Yld (%)':     open_yld_str,
                        'Open Date':        open_date_str,
                        'Volume (MM)':      volume_str,
                        'Close Yld (%)':    close_yld_str,
                        'MtM (MM CNY)':     mtm_str,
                    })

                if not display_rows:
                    return _no_data("Beta snapshot is empty.")

                # TOTAL row
                def _sum_num(col):
                    t, any_ = 0.0, False
                    for r in display_rows:
                        v = str(r.get(col, '')).replace(',', '').replace('+', '').strip()
                        if v:
                            try:
                                t += float(v); any_ = True
                            except (ValueError, TypeError):
                                pass
                    return t if any_ else None

                total_row = {c: '' for c in display_rows[0].keys()}
                total_row['Asset Type'] = 'TOTAL'
                _s_cap = _sum_num('Capital (MM CNY)')
                _s_vol = _sum_num('Volume (MM)')
                _s_mtm = _sum_num('MtM (MM CNY)')
                if _s_cap is not None:
                    total_row['Capital (MM CNY)'] = f"{_s_cap:,.2f}"
                if _s_vol is not None:
                    total_row['Volume (MM)'] = f"{_s_vol:,.1f}"
                if _s_mtm is not None:
                    total_row['MtM (MM CNY)'] = f"{_s_mtm:+.4f}"
                display_rows.append(total_row)

                _editable_cols = {'Open Yld (%)', 'Open Date', 'Volume (MM)'}
                columns = [
                    {
                        'name': c,
                        'id': c,
                        'editable': c in _editable_cols,
                        **({'type': 'datetime'} if c == 'Open Date' else {}),
                    }
                    for c in display_rows[0].keys()
                ]

                _editable_style = [
                    {'if': {'column_id': c},
                     'border': f'1px solid {THEME["accent"]}',
                     'backgroundColor': 'rgba(99,179,237,0.08)'}
                    for c in _editable_cols
                ]
                _mtm_styles = [
                    {'if': {'filter_query': '{MtM (MM CNY)} contains "+"', 'column_id': 'MtM (MM CNY)'},
                     'color': THEME.get('success', '#27ae60')},
                    {'if': {'filter_query': '{MtM (MM CNY)} contains "-"', 'column_id': 'MtM (MM CNY)'},
                     'color': THEME.get('danger', '#e74c3c')},
                ]

                table = dash_table.DataTable(
                    id='summary-beta-table',
                    data=display_rows,
                    columns=columns,
                    editable=True,
                    style_cell={
                        'textAlign': 'center', 'padding': '6px 8px',
                        'backgroundColor': THEME['table_row_odd'],
                        'color': THEME['text_main'], 'border': 'none',
                        'fontSize': '12px',
                    },
                    style_header={
                        'backgroundColor': THEME['table_header'],
                        'color': THEME['text_main'],
                        'fontWeight': 'bold', 'border': 'none',
                        'whiteSpace': 'normal', 'height': 'auto',
                    },
                    style_data_conditional=[
                        {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']},
                        {'if': {'filter_query': '{Asset Type} = "TOTAL"'},
                         'backgroundColor': THEME['table_header'], 'fontWeight': 'bold',
                         'borderTop': f"1px solid {THEME['accent']}"},
                        *_editable_style,
                        *_mtm_styles,
                    ],
                    style_table={'overflowX': 'auto'},
                    sort_action='native',
                    page_size=30,
                    tooltip_header={
                        'Open Yld (%)':   'User-editable: yield at which position was opened (%)',
                        'Open Date':      'User-editable: trade open date (YYYY-MM-DD)',
                        'Volume (MM)':    'User-editable: position size in MM CNY',
                        'Close Yld (%)':  'Latest yield from factor levels',
                        'MtM (MM CNY)':   'Volume × Duration × (Close Yld − Open Yld) / 10000',
                    },
                    tooltip_delay=0,
                    tooltip_duration=None,
                )

                content = html.Div([
                    html.Div([
                        html.Span(
                            'Open Date calendar:',
                            style={'color': THEME['text_sub'], 'fontSize': '11px'},
                        ),
                        dcc.DatePickerSingle(
                            id='summary-beta-open-date-picker',
                            date=None,
                            display_format='YYYY-MM-DD',
                            clearable=True,
                            disabled=True,
                            placeholder='Select an Open Date cell',
                            style={'backgroundColor': THEME['bg_input']},
                        ),
                        html.Span(
                            id='summary-beta-open-date-target',
                            children='Click an Open Date cell to edit with the calendar.',
                            style={'color': THEME['text_sub'], 'fontSize': '11px',
                                   'fontStyle': 'italic'},
                        ),
                    ], style={'display': 'flex', 'alignItems': 'center', 'gap': '10px',
                              'marginBottom': '10px', 'flexWrap': 'wrap'}),
                    table,
                ])
                status = f"Beta snapshot from {ts[:19]}"
                return content, status

            except Exception as exc:
                return _no_data(f"Error loading Beta snapshot: {exc}")

        # ── Alpha tab ─────────────────────────────────────────────────────────
        elif tab_value == 'alpha':
            if not _os.path.exists(_SUMMARY_ALPHA_PARQUET):
                return _no_data(
                    "No Alpha snapshot found. Click RUN OPTIMIZATION in the Alpha Book → Portfolio tab first."
                )
            try:
                # Edits are auto-persisted by `_autosave_alpha_table` below.
                is_refresh = (_ctx.triggered_id == 'summary-refresh-btn' and _n_clicks)
                df  = pd.read_parquet(_SUMMARY_ALPHA_PARQUET)
                ts  = df['_timestamp'].iloc[0] if '_timestamp' in df.columns else "unknown"
                pos = _load_positions()  # persisted user-editable fields

                display_rows = []
                for _, row in df.iterrows():
                    trade_id = str(row.get('ID', ''))
                    if trade_id in ('TOTAL', ''):
                        continue

                    spread_type = str(row.get('spread_type', ''))
                    key         = (spread_type, trade_id)

                    # Saved user-editable fields (default empty)
                    saved          = pos.get(key, {})
                    open_price_str = str(saved.get('open_price_bp', ''))
                    volume_str     = str(saved.get('volume_mm', ''))
                    open_date_str  = str(saved.get('open_date', ''))

                    spread_val = row.get('spread', None)
                    # spread is already stored in bp in the Alpha portfolio snapshot
                    cp_bp      = round(float(spread_val), 4) if pd.notna(spread_val) else None
                    notional   = float(row.get('notional_mm', 0) or 0)
                    dv01_k     = float(row.get('DV01_k', 0) or 0)
                    # Use saved _duration if available, else reconstruct from DV01_k and notional
                    # DV01_k = notional_mm * duration / 10  →  duration = DV01_k * 10 / notional
                    _dur_raw   = row.get('_duration', None)
                    if _dur_raw is not None and pd.notna(_dur_raw):
                        duration = float(_dur_raw)
                    elif notional > 0:
                        duration = round(dv01_k * 10.0 / notional, 2)
                    else:
                        duration = 0.0

                    # MTM calculation when user has filled in open_price and volume
                    mtm_price_mm = None
                    mtm_spd_bp = None
                    mtm_carry_mm = None
                    mtm_total_mm = None
                    try:
                        open_price_bp = float(open_price_str) if open_price_str else None
                        volume_mm     = float(volume_str)     if volume_str     else None
                        mtm_spd_bp    = open_price_bp

                        if open_price_bp is not None and volume_mm is not None and cp_bp is not None:
                            # Price P&L: Volume × Duration × ΔSpread / 10000  (MM CNY)
                            mtm_price_mm = round(
                                volume_mm * duration * (cp_bp - open_price_bp) / 10000.0, 4
                            )
                        if volume_mm is not None:
                            mtm_carry_mm = _compute_carry_mtm(
                                spread_type, trade_id, open_date_str, volume_mm
                            )
                        if mtm_price_mm is not None or mtm_carry_mm is not None:
                            mtm_total_mm = round(
                                (mtm_price_mm or 0.0) + (mtm_carry_mm or 0.0), 4
                            )
                    except (ValueError, TypeError):
                        pass

                    display_rows.append({
                        'ID':                       trade_id,
                        'Spread Type':              spread_type,
                        'Style':                    row.get('style', ''),
                        'Direction':                row.get('direction', ''),
                        'Duration':                 f"{duration:.2f}" if duration else 'N/A',
                        'Open price (bp)':          open_price_str,
                        'Volume (mm)':              volume_str,
                        'Open date':                open_date_str,
                        'Z-Score':                  f"{float(row.get('Zscore', 0) or 0):.2f}",
                        'Close Price (bp)':         f"{cp_bp:.4f}" if cp_bp is not None else 'N/A',
                        'Target Volume (MM CNY)':   f"{notional:,.1f}",
                        'DV01 (k CNY/bp)':          f"{dv01_k:.1f}",
                        'MTM spd (bp)':             f"{mtm_spd_bp:,.4f}" if mtm_spd_bp is not None else '',
                        'MtM Carry (MM CNY)':       f"{mtm_carry_mm:,.4f}" if mtm_carry_mm is not None else '',
                        'MtM Value (MM CNY)':       f"{mtm_total_mm:,.4f}" if mtm_total_mm is not None else '',
                        'Target Weight (%)':        f"{float(row.get('weight', 0) or 0) * 100:.2f}%",
                        'Weight (%)':               '',  # filled below after summing volumes
                    })

                # Compute actual Weight (%) = Volume (mm) / sum(Volume (mm))
                total_vol = 0.0
                for r in display_rows:
                    try:
                        total_vol += float(r['Volume (mm)']) if r['Volume (mm)'] else 0.0
                    except (ValueError, TypeError):
                        pass
                for r in display_rows:
                    try:
                        v = float(r['Volume (mm)']) if r['Volume (mm)'] else None
                        r['Weight (%)'] = f"{v / total_vol * 100:.2f}%" if (v is not None and total_vol > 0) else ''
                    except (ValueError, TypeError):
                        r['Weight (%)'] = ''

                if not display_rows:
                    return _no_data("Alpha snapshot is empty.")

                # ── TOTAL row ────────────────────────────────────────────────
                # Volume and Target Volume only sum for outright bond types
                # (BondCurve / BondSwap); spread trades are DV01-neutral.
                _BOND_OUTRIGHT_TYPES = {
                    'TBondCurve', 'CBondCurve', 'TBondSwap', 'CBondSwap',
                }

                def _sum_col(col, filter_types=None):
                    """Return numeric sum of col, or None if no non-empty values."""
                    total, has_any = 0.0, False
                    for r in display_rows:
                        if filter_types and r.get('Spread Type', '') not in filter_types:
                            continue
                        v = str(r.get(col, '')).replace(',', '').replace('%', '').strip()
                        if v:
                            try:
                                total += float(v)
                                has_any = True
                            except (ValueError, TypeError):
                                pass
                    return total if has_any else None

                _s_vol     = _sum_col('Volume (mm)',            _BOND_OUTRIGHT_TYPES)
                _s_tvol    = _sum_col('Target Volume (MM CNY)', _BOND_OUTRIGHT_TYPES)
                _s_carry   = _sum_col('MtM Carry (MM CNY)')
                _s_mtm     = _sum_col('MtM Value (MM CNY)')
                _s_tgt_wt  = _sum_col('Target Weight (%)')
                _s_wt      = _sum_col('Weight (%)')

                total_row = {c: '' for c in display_rows[0].keys()}
                total_row['ID']                     = 'TOTAL'
                total_row['Volume (mm)']            = f"{_s_vol:,.1f}"    if _s_vol    is not None else ''
                total_row['Target Volume (MM CNY)'] = f"{_s_tvol:,.1f}"   if _s_tvol   is not None else ''
                total_row['MtM Carry (MM CNY)']     = f"{_s_carry:,.4f}"  if _s_carry  is not None else ''
                total_row['MtM Value (MM CNY)']     = f"{_s_mtm:,.4f}"    if _s_mtm    is not None else ''
                total_row['Target Weight (%)']      = f"{_s_tgt_wt:.2f}%" if _s_tgt_wt is not None else ''
                total_row['Weight (%)']             = f"{_s_wt:.2f}%"     if _s_wt     is not None else ''
                display_rows.append(total_row)
                # ── end TOTAL row ─────────────────────────────────────────────

                _editable_cols = {'Open price (bp)', 'Volume (mm)', 'Open date'}
                columns = [
                    {
                        'name': c,
                        'id': c,
                        'editable': c in _editable_cols,
                        **({'type': 'datetime'} if c == 'Open date' else {}),
                    }
                    for c in display_rows[0].keys()
                ]

                dir_styles = [
                    {'if': {'filter_query': '{Direction} = "BUY"'},
                     'backgroundColor': 'rgba(0, 204, 150, 0.12)'},
                    {'if': {'filter_query': '{Direction} = "SELL"'},
                     'backgroundColor': 'rgba(239, 85, 59, 0.12)'},
                    {'if': {'filter_query': '{ID} = "TOTAL"'},
                     'backgroundColor': THEME['table_header'],
                     'fontWeight': 'bold',
                     'borderTop': f"1px solid {THEME['accent']}"},
                ]
                editable_style = [
                    {'if': {'column_id': c},
                     'border': f'1px solid {THEME["accent"]}',
                     'backgroundColor': 'rgba(99,179,237,0.08)'}
                    for c in _editable_cols
                ]

                table = dash_table.DataTable(
                    id='summary-alpha-table',
                    data=display_rows,
                    columns=columns,
                    editable=True,
                    row_deletable=True,
                    style_cell={
                        'textAlign': 'center', 'padding': '6px 8px',
                        'backgroundColor': THEME['table_row_odd'],
                        'color': THEME['text_main'], 'border': 'none',
                        'fontSize': '12px',
                    },
                    style_header={
                        'backgroundColor': THEME['table_header'],
                        'color': THEME['text_main'],
                        'fontWeight': 'bold', 'border': 'none',
                        'whiteSpace': 'normal', 'height': 'auto',
                    },
                    style_data_conditional=[
                        {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']},
                        *dir_styles,
                        *editable_style,
                    ],
                    style_table={'overflowX': 'auto'},
                    sort_action='native',
                    page_size=30,
                    tooltip_header={
                        'Open price (bp)':   'User-editable: entry spread in bp',
                        'Volume (mm)':       'User-editable: position size in MM CNY',
                        'Open date':         'User-editable: trade open date (YYYY-MM-DD)',
                        'MTM spd (bp)':      'User-entered open spread shown in bp',
                        'MtM Carry (MM CNY)':'Volume × cumulative carry+roll since open date',
                        'MtM Value (MM CNY)':'MtM Price + MtM Carry',
                    },
                    tooltip_delay=0,
                    tooltip_duration=None,
                )
                content = html.Div([
                    html.Div([
                        html.Span(
                            'Open date calendar:',
                            style={'color': THEME['text_sub'], 'fontSize': '11px'}
                        ),
                        dcc.DatePickerSingle(
                            id='summary-alpha-open-date-picker',
                            date=None,
                            display_format='YYYY-MM-DD',
                            clearable=True,
                            disabled=True,
                            placeholder='Select an Open date cell',
                            style={'backgroundColor': THEME['bg_input']},
                        ),
                        html.Span(
                            id='summary-alpha-open-date-target',
                            children='Click an Open date cell to edit with the calendar.',
                            style={
                                'color': THEME['text_sub'],
                                'fontSize': '11px',
                                'fontStyle': 'italic',
                            },
                        ),
                    ], style={
                        'display': 'flex',
                        'alignItems': 'center',
                        'gap': '10px',
                        'marginBottom': '10px',
                        'flexWrap': 'wrap',
                    }),
                    table,
                ])
                status = (
                    f"Alpha snapshot from {ts[:19]}"
                    + (" — saved" if is_refresh else "")
                )
                return content, status

            except Exception as exc:
                return _no_data(f"Error loading Alpha snapshot: {exc}")

        return _no_data("Select a tab above.")

    # ── Auto-save edits on the Alpha positions table ──────────────────────────
    # Fires whenever the user edits a cell in the summary-alpha-table.
    # Persists the editable columns (Open price / Volume / Open date) to parquet.
    @app.callback(
        Output('summary-refresh-status', 'children', allow_duplicate=True),
        Input('summary-alpha-table', 'data_timestamp'),
        State('summary-alpha-table', 'data'),
        prevent_initial_call=True,
    )
    def _autosave_alpha_table(_ts, rows):
        if rows is None:
            raise dash.exceptions.PreventUpdate
        try:
            _persist_alpha_summary_rows(rows)
            return f"Edits saved at {datetime.now().strftime('%H:%M:%S')}"
        except Exception as exc:
            return f"Save failed: {exc}"

    @app.callback(
        [
            Output('summary-alpha-open-date-picker', 'date'),
            Output('summary-alpha-open-date-picker', 'disabled'),
            Output('summary-alpha-open-date-target', 'children'),
        ],
        Input('summary-alpha-table', 'active_cell'),
        State('summary-alpha-table', 'data'),
        prevent_initial_call=False,
    )
    def _sync_alpha_open_date_picker(active_cell, rows):
        if not rows or not active_cell or active_cell.get('column_id') != 'Open date':
            return None, True, 'Click an Open date cell to edit with the calendar.'

        row_index = active_cell.get('row')
        if row_index is None or row_index >= len(rows):
            return None, True, 'Click an Open date cell to edit with the calendar.'

        current_value = rows[row_index].get('Open date', '')
        parsed = pd.to_datetime(current_value, errors='coerce')
        label = f"Editing {rows[row_index].get('ID', '')}"
        return (
            parsed.date().isoformat() if pd.notna(parsed) else None,
            False,
            label,
        )

    @app.callback(
        [
            Output('summary-alpha-table', 'data', allow_duplicate=True),
            Output('summary-refresh-status', 'children', allow_duplicate=True),
        ],
        Input('summary-alpha-open-date-picker', 'date'),
        State('summary-alpha-table', 'active_cell'),
        State('summary-alpha-table', 'data'),
        prevent_initial_call=True,
    )
    def _apply_alpha_open_date(date_value, active_cell, rows):
        if not rows or not active_cell or active_cell.get('column_id') != 'Open date':
            raise dash.exceptions.PreventUpdate

        row_index = active_cell.get('row')
        if row_index is None or row_index >= len(rows):
            raise dash.exceptions.PreventUpdate

        updated_rows = [dict(row) for row in rows]
        updated_rows[row_index]['Open date'] = date_value or ''
        updated_rows[row_index] = _refresh_alpha_display_row(updated_rows[row_index])

        _persist_alpha_summary_rows(updated_rows)
        return updated_rows, f"Open date saved at {datetime.now().strftime('%H:%M:%S')}"

    # ── Auto-save edits on the Beta positions table ───────────────────────────
    def _persist_beta_user_rows(rows: list[dict]) -> None:
        """Persist user-editable fields (open_yld, open_date, volume) to parquet."""
        records = [
            {
                'asset_name':  str(r.get('Asset Name', '')),
                'instrument':  str(r.get('Instrument', '')),
                'open_yld':    str(r.get('Open Yld (%)', '')),
                'open_date':   str(r.get('Open Date', '')),
                'volume':      str(r.get('Volume (MM)', '')),
            }
            for r in rows
            if str(r.get('Asset Type', '')) not in ('', 'TOTAL')
        ]
        try:
            import pathlib as _pl
            _pl.Path(_BETA_BOOK_USER_PARQUET).parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(records).to_parquet(_BETA_BOOK_USER_PARQUET, index=False)
        except Exception:
            pass

    @app.callback(
        Output('summary-refresh-status', 'children', allow_duplicate=True),
        Input('summary-beta-table', 'data_timestamp'),
        State('summary-beta-table', 'data'),
        prevent_initial_call=True,
    )
    def _autosave_beta_table(_ts, rows):
        if rows is None:
            raise dash.exceptions.PreventUpdate
        try:
            _persist_beta_user_rows(rows)
            return f"Beta edits saved at {datetime.now().strftime('%H:%M:%S')}"
        except Exception as exc:
            return f"Save failed: {exc}"

    @app.callback(
        [
            Output('summary-beta-open-date-picker', 'date'),
            Output('summary-beta-open-date-picker', 'disabled'),
            Output('summary-beta-open-date-target', 'children'),
        ],
        Input('summary-beta-table', 'active_cell'),
        State('summary-beta-table', 'data'),
        prevent_initial_call=False,
    )
    def _sync_beta_open_date_picker(active_cell, rows):
        if not rows or not active_cell or active_cell.get('column_id') != 'Open Date':
            return None, True, 'Click an Open Date cell to edit with the calendar.'
        row_index = active_cell.get('row')
        if row_index is None or row_index >= len(rows):
            return None, True, 'Click an Open Date cell to edit with the calendar.'
        current_value = rows[row_index].get('Open Date', '')
        parsed = pd.to_datetime(current_value, errors='coerce')
        label = f"Editing {rows[row_index].get('Asset Name', '')}"
        return (
            parsed.date().isoformat() if pd.notna(parsed) else None,
            False,
            label,
        )

    @app.callback(
        [
            Output('summary-beta-table', 'data', allow_duplicate=True),
            Output('summary-refresh-status', 'children', allow_duplicate=True),
        ],
        Input('summary-beta-open-date-picker', 'date'),
        State('summary-beta-table', 'active_cell'),
        State('summary-beta-table', 'data'),
        prevent_initial_call=True,
    )
    def _apply_beta_open_date(date_value, active_cell, rows):
        if not rows or not active_cell or active_cell.get('column_id') != 'Open Date':
            raise dash.exceptions.PreventUpdate
        row_index = active_cell.get('row')
        if row_index is None or row_index >= len(rows):
            raise dash.exceptions.PreventUpdate
        updated_rows = [dict(row) for row in rows]
        updated_rows[row_index]['Open Date'] = date_value or ''
        _persist_beta_user_rows(updated_rows)
        return updated_rows, f"Open date saved at {datetime.now().strftime('%H:%M:%S')}"

    # ── Helper: duration → tenor mapping ────────────────────────────────────────
    def _dur_to_tenor_label(dur: float) -> str:
        """Map duration (years) to nearest tenor label."""
        _TENOR_BOUNDS = [(0.0, 1.5, '1Y'), (1.5, 3.5, '2Y'), (3.5, 7.0, '5Y'),
                         (7.0, 12.0, '10Y'), (12.0, 17.0, '20Y'), (17.0, 9999.0, '30Y')]
        for lo, hi, label in _TENOR_BOUNDS:
            if lo <= dur < hi:
                return label
        return '30Y'

    def _parse_repo_spread_legs(spread_id: str) -> tuple[str, str]:
        """Parse 'Repo7d-6m1y' → ('FR007S6M.IR', 'FR007S1Y.IR')."""
        import re
        _TENOR_MAP = {'3m': '3M', '6m': '6M', '9m': '9M', '1y': '1Y',
                      '2y': '2Y', '3y': '3Y', '5y': '5Y', '10y': '10Y'}
        m = re.match(r'repo7d-(.+)', spread_id.lower())
        if not m:
            return ('', '')
        remainder = m.group(1)
        pairs = re.findall(r'(\d+[a-z])', remainder)
        if len(pairs) < 2:
            return ('', '')
        t1 = _TENOR_MAP.get(pairs[0], pairs[0].upper())
        t2 = _TENOR_MAP.get(pairs[1], pairs[1].upper())
        return (f'FR007S{t1}.IR', f'FR007S{t2}.IR')

    def _find_reference_bond(bond_isin: str, instrument_info_df: pd.DataFrame,
                            target_tenor: str) -> str:
        """Find a reference bond with target tenor from instrument info.

        For now, returns the bond code (ISIN) as the leg name.
        In practice, would filter by tenor and return the first match.
        """
        return bond_isin  # Placeholder: just use the original ISIN

    # ── Risk subtab: inventory + factor exposure + key-term DV01 ladder ─────────
    @app.callback(
        [Output('risk-inventory-container', 'children'),
         Output('risk-exposure-container', 'children'),
         Output('risk-refresh-status', 'children')],
        [Input('summary-main-tabs', 'value'),
         Input('risk-refresh-btn', 'n_clicks')],
        prevent_initial_call=False,
    )
    def update_risk_tables(tab_value, _n_clicks):
        import os as _os
        import re

        if tab_value != 'risk':
            raise dash.exceptions.PreventUpdate

        def _no_data_div(msg):
            return html.Div(msg, style={'color': THEME['text_sub'], 'fontStyle': 'italic',
                                        'padding': '20px', 'textAlign': 'center', 'fontSize': '13px'})

        # ── Tenor bucket helper ───────────────────────────────────────────────
        _TENOR_ORDER = ['1Y', '2Y', '5Y', '10Y', '20Y', '30Y']
        _TENOR_BOUNDS = [(0.0, 1.5), (1.5, 3.5), (3.5, 7.0),
                         (7.0, 12.0), (12.0, 17.0), (17.0, 9999.0)]

        def _dur_to_tenor(dur: float) -> str:
            for label, (lo, hi) in zip(_TENOR_ORDER, _TENOR_BOUNDS):
                if lo <= dur < hi:
                    return label
            return '30Y'

        _SECTOR_TO_TENOR = {'1Y': '1Y', '2Y': '2Y', '5Y': '5Y',
                            '10Y': '10Y', '20Y': '20Y', '30Y': '30Y'}

        # ── Alpha spread-type → Key Term column ──────────────────────────────
        _ALPHA_COL = {
            'TBondCurve': 'CGB',   'TBondSwap':  'CGB',
            'CBondCurve': 'PBB',   'CBondSwap':  'PBB',
            'IRS':        'Repo7d',
            'CDB':        'PBB',
            'ICP':        'Shi3M',
        }
        _KT_COLS = ['CGB', 'PBB', 'Others', 'Repo7d', 'Shi3M']

        # ── Load Beta positions ───────────────────────────────────────────────
        beta_rows, kt_grid = [], {t: {c: 0.0 for c in _KT_COLS} for t in _TENOR_ORDER}
        if _os.path.exists(_BETA_BOOK_POSITIONS_PARQUET):
            try:
                bdf = pd.read_parquet(_BETA_BOOK_POSITIONS_PARQUET)
                for _, r in bdf.iterrows():
                    atype = str(r.get('Asset Type', ''))
                    if atype == 'TOTAL':
                        continue
                    name     = str(r.get('Asset Name', ''))
                    sector   = str(r.get('Sector', ''))
                    cap_str  = str(r.get('Capital (CNY)', ''))
                    dv01_val = r.get('DV01 (MM CNY)', 0)
                    try:
                        dv01_mm = float(str(dv01_val).replace(',', '')) if dv01_val else 0.0
                    except (ValueError, TypeError):
                        dv01_mm = 0.0

                    beta_rows.append({
                        'Book': 'Beta', 'Name': name,
                        'Instrument': str(r.get('Instrument', '')),
                        'Leg1': '', 'Leg2': '',  # Beta positions don't have legs
                        'Sector': sector,
                        'Capital (MM)': cap_str, 'DV01 (MM/bp)': f"{dv01_mm:.4f}",
                        'Direction': 'LONG',
                    })

                    # Key Term: CN bonds → CGB; others → Others
                    tenor = _SECTOR_TO_TENOR.get(sector)
                    if tenor and dv01_mm != 0.0:
                        col = 'CGB' if name.startswith('CN') else 'Others'
                        kt_grid[tenor][col] = round(kt_grid[tenor][col] + dv01_mm, 4)
            except Exception:
                pass

        # ── Load Alpha positions ──────────────────────────────────────────────
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

                    # Determine leg1, leg2 based on spread type and ID
                    leg1, leg2 = '', ''
                    if stype == 'SwapSpread':
                        # SwapSpread: parse "Repo7d-6m1y" style
                        leg1, leg2 = _parse_repo_spread_legs(tid)
                    elif stype == 'TBondCurve':
                        # TBondCurve: leg1=bond code, leg2=tenor reference (placeholder for now)
                        leg1 = tid
                        target_tenor = _dur_to_tenor_label(duration)
                        leg2 = f"CGB-{target_tenor}"  # Simplified: actual lookup would be from reference data
                    # Add more spread types as needed

                    alpha_rows.append({
                        'Book': 'Alpha', 'Name': tid, 'Instrument': tid,
                        'Leg1': leg1, 'Leg2': leg2,
                        'Sector': stype,
                        'Capital (MM)': f"{notional:.1f}",
                        'DV01 (MM/bp)': f"{dv01_mm * dir_sign:.4f}",
                        'Direction': direction,
                    })

                    # Key Term ladder
                    tenor = _dur_to_tenor(duration)
                    col   = _ALPHA_COL.get(stype, 'Others')
                    if dv01_mm != 0.0:
                        kt_grid[tenor][col] = round(
                            kt_grid[tenor][col] + dv01_mm * dir_sign, 4)
            except Exception:
                pass

        if not beta_rows and not alpha_rows:
            return (
                _no_data_div("No positions found — run analysis (Beta) or optimization (Alpha) first."),
                _no_data_div("No data."),
                "",
            )

        # ── Inventory table ───────────────────────────────────────────────────
        all_rows = beta_rows + alpha_rows
        _dir_style = [
            {'if': {'filter_query': '{Direction} = "LONG" or {Direction} = "BUY"'},
             'backgroundColor': 'rgba(0,204,150,0.08)'},
            {'if': {'filter_query': '{Direction} = "SHORT" or {Direction} = "SELL"'},
             'backgroundColor': 'rgba(239,85,59,0.08)'},
            {'if': {'filter_query': '{Book} = "Beta"', 'column_id': 'Book'},
             'color': THEME['accent'], 'fontWeight': 'bold'},
            {'if': {'filter_query': '{Book} = "Alpha"', 'column_id': 'Book'},
             'color': THEME['danger'], 'fontWeight': 'bold'},
        ]
        inventory_table = dash_table.DataTable(
            data=all_rows,
            columns=[{'name': c, 'id': c} for c in
                     ['Book', 'Name', 'Instrument', 'Leg1', 'Leg2', 'Sector',
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

        # ── Factor Risk Exposure (Beta only, no SPDL/SPSL, non-zero only) ────
        factor_risk_df = ALLOCATION_RESULTS.get('factor_risk')
        _SKIP_PREFIXES = ('SPDL', 'SPSL')
        if (factor_risk_df is not None and not factor_risk_df.empty
                and 'Risk Factor' in factor_risk_df.columns
                and 'Net Exposure' in factor_risk_df.columns):
            fr_rows = []
            for _, fr in factor_risk_df.iterrows():
                rf  = str(fr['Risk Factor'])
                if any(rf.startswith(p) for p in _SKIP_PREFIXES):
                    continue
                exp = float(fr.get('Net Exposure', 0) or 0)
                rc  = float(fr.get('Risk Contribution (%)', 0) or 0)
                vol = float(fr.get('Volatility (% ann.)', 0) or 0)
                if abs(exp) < 1e-8:          # skip truly-zero exposures
                    continue
                fr_rows.append({
                    'Risk Factor':  rf,
                    'Exposure':     f"{exp:+.4f}",
                    'Vol (% ann.)': f"{vol:.2f}%",
                    'RC (%)':       f"{rc:.1f}%",
                })
            if fr_rows:
                _exp_styles = [
                    {'if': {'filter_query': '{Exposure} contains "+"', 'column_id': 'Exposure'},
                     'color': THEME['success']},
                    {'if': {'filter_query': '{Exposure} contains "-"', 'column_id': 'Exposure'},
                     'color': THEME['danger']},
                ]
                factor_exp_table = dash_table.DataTable(
                    data=fr_rows,
                    columns=[{'name': c, 'id': c} for c in
                             ['Risk Factor', 'Exposure', 'Vol (% ann.)', 'RC (%)']],
                    style_cell={'textAlign': 'center', 'padding': '5px 10px', 'fontSize': '12px',
                                'backgroundColor': THEME['table_row_odd'],
                                'color': THEME['text_main'], 'border': 'none'},
                    style_header={'backgroundColor': THEME['table_header'],
                                  'color': THEME['text_main'], 'fontWeight': 'bold', 'border': 'none'},
                    style_data_conditional=[
                        {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']},
                        *_exp_styles,
                    ],
                    style_table={'overflowX': 'auto', 'maxWidth': '520px'},
                )
            else:
                factor_exp_table = _no_data_div(
                    "No non-zero IR/CMD/FX factor exposures found (run Beta Analysis first).")
        else:
            factor_exp_table = _no_data_div(
                "Beta factor risk not yet computed — run RUN ANALYSIS in Beta Book first.")

        # ── Key Term Exposure ladder ──────────────────────────────────────────
        # Compute row totals; skip entirely-zero rows
        kt_display = []
        for tenor in _TENOR_ORDER:
            row = kt_grid[tenor]
            total = round(sum(row.values()), 4)
            if all(abs(v) < 1e-8 for v in row.values()):
                continue
            kt_display.append({
                'Tenor': tenor,
                'CGB':    f"{row['CGB']:+.4f}" if abs(row['CGB']) > 1e-8 else '',
                'PBB':    f"{row['PBB']:+.4f}" if abs(row['PBB']) > 1e-8 else '',
                'Others': f"{row['Others']:+.4f}" if abs(row['Others']) > 1e-8 else '',
                'Repo7d': f"{row['Repo7d']:+.4f}" if abs(row['Repo7d']) > 1e-8 else '',
                'Shi3M':  f"{row['Shi3M']:+.4f}" if abs(row['Shi3M']) > 1e-8 else '',
                'Total':  f"{total:+.4f}" if abs(total) > 1e-8 else '',
            })

        _kt_pos_style = [
            {'if': {'filter_query': f'{{{c}}} contains "+"', 'column_id': c},
             'color': THEME['success']}
            for c in ['CGB', 'PBB', 'Others', 'Repo7d', 'Shi3M', 'Total']
        ]
        _kt_neg_style = [
            {'if': {'filter_query': f'{{{c}}} contains "-"', 'column_id': c},
             'color': THEME['danger']}
            for c in ['CGB', 'PBB', 'Others', 'Repo7d', 'Shi3M', 'Total']
        ]

        kt_table = (
            dash_table.DataTable(
                data=kt_display,
                columns=[{'name': c, 'id': c} for c in
                         ['Tenor', 'CGB', 'PBB', 'Others', 'Repo7d', 'Shi3M', 'Total']],
                style_cell={'textAlign': 'center', 'padding': '5px 10px', 'fontSize': '12px',
                            'backgroundColor': THEME['table_row_odd'],
                            'color': THEME['text_main'], 'border': 'none'},
                style_cell_conditional=[
                    {'if': {'column_id': 'Tenor'}, 'fontWeight': 'bold',
                     'color': THEME['accent'], 'textAlign': 'left'},
                ],
                style_header={'backgroundColor': THEME['table_header'],
                              'color': THEME['text_main'], 'fontWeight': 'bold', 'border': 'none'},
                style_data_conditional=[
                    {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']},
                    *_kt_pos_style, *_kt_neg_style,
                ],
                style_table={'overflowX': 'auto', 'maxWidth': '700px'},
            )
            if kt_display
            else _no_data_div("No rate positions found for Key Term Exposure.")
        )

        # ── Assemble second panel: Factor Exposure + Key Term side-by-side ────
        exposure_panel = html.Div([
            html.Div([
                html.H6("Factor Risk Exposure  (Beta book · IR/CMD/FX factors)",
                        style={'color': THEME['warning'], 'fontSize': '12px', 'marginBottom': '8px'}),
                factor_exp_table,
            ], style={'flex': '1', 'minWidth': '280px', 'marginRight': '20px'}),
            html.Div([
                html.H6("Key Term Exposure  DV01 ladder MM CNY/bp  (Beta + Alpha)",
                        style={'color': THEME['accent'], 'fontSize': '12px', 'marginBottom': '8px'}),
                html.Div(
                    "CGB = Gov Bond  ·  PBB = Policybank Bond  ·  Repo7d = FR007 IRS  ·  Shi3M = ICP/SHIBOR",
                    style={'color': THEME['text_sub'], 'fontSize': '10px', 'marginBottom': '6px',
                           'fontStyle': 'italic'},
                ),
                kt_table,
            ], style={'flex': '1', 'minWidth': '340px'}),
        ], style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '16px', 'alignItems': 'flex-start'})

        n_beta  = len(beta_rows)
        n_alpha = len(alpha_rows)
        status  = (f"{n_beta} beta · {n_alpha} alpha positions · "
                   f"updated {datetime.now().strftime('%H:%M:%S')}")
        return inventory_table, exposure_panel, status

