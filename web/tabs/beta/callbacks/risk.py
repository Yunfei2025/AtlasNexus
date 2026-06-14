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
import warnings
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
        'style': str(r.get('Style', '')),
        'direction': str(r.get('Direction', '')),
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

    # ── Summary Books: Beta and Alpha tables rendered independently ───────────
    # Each column gets its own callback so they can be refreshed independently.
    # The show/hide of Books/Risk/Tickets is handled by the app-level
    # _make_tab_switcher (an-summary-subtabs → summary-{books,risk,tickets}-div).

    @app.callback(
        [Output('summary-beta-table-container', 'children'),
         Output('summary-refresh-status', 'children')],
        [Input('summary-refresh-btn', 'n_clicks')],
        prevent_initial_call=False,
    )
    def update_summary_book_table(_n_clicks):
        """Render Beta Book allocation table."""
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

        if not _os.path.exists(_SUMMARY_BETA_PARQUET) and not _os.path.exists(_BETA_BOOK_POSITIONS_PARQUET):
            return _no_data(
                "No Beta snapshot found. Click RUN ANALYSIS in the Beta Book → Portfolio tab first."
            )
        try:
            if _os.path.exists(_SUMMARY_BETA_PARQUET):
                df = pd.read_parquet(_SUMMARY_BETA_PARQUET)
            else:
                df = pd.read_parquet(_BETA_BOOK_POSITIONS_PARQUET)

            if df.empty:
                return _no_data("Beta snapshot is empty.")

            ts = "unknown"
            if _os.path.exists(_SUMMARY_BETA_PARQUET):
                try:
                    snap = pd.read_parquet(_SUMMARY_BETA_PARQUET)
                    ts = snap['_timestamp'].iloc[0] if '_timestamp' in snap.columns else "unknown"
                except Exception:
                    ts = "unknown"

            user_data: dict = {}
            if _os.path.exists(_BETA_BOOK_USER_PARQUET):
                try:
                    udf = pd.read_parquet(_BETA_BOOK_USER_PARQUET)
                    for _, r in udf.iterrows():
                        key = (str(r.get('asset_name', '')), str(r.get('instrument', '')))
                        user_data[key] = {
                            'open_price': str(r.get('open_price', r.get('open_yld', ''))),
                            'open_date':  str(r.get('open_date', '')),
                            'volume':     str(r.get('volume', '')),
                        }
                except Exception:
                    pass

            close_prices = _get_beta_close_prices()
            _RATES_TYPE = 'Rates'
            display_rows = []
            for _, row in df.iterrows():
                asset_type = str(row.get('Asset Type', ''))
                if asset_type == 'TOTAL':
                    continue
                is_rates   = (asset_type == _RATES_TYPE)
                asset_name = str(row.get('Asset Name', ''))
                instrument = str(row.get('Instrument', ''))
                key = (asset_name, instrument)
                saved = user_data.get(key, {})

                open_price_str = str(saved.get('open_price', ''))
                open_date_str  = str(saved.get('open_date', ''))
                volume_str     = str(saved.get('volume', ''))

                _dur = None
                if is_rates:
                    _dur_raw = row.get('Duration', None)
                    try:
                        _dur = float(str(_dur_raw).replace(',', '')) if _dur_raw not in (None, '', 'N/A') else None
                        duration_str = f"{_dur:.2f}" if _dur is not None else ''
                    except (ValueError, TypeError):
                        duration_str = ''
                else:
                    duration_str = ''

                try:
                    _cap_raw = float(str(row.get('Capital (CNY)', 0) or 0).replace(',', ''))
                    cap_mm_str = f"{_cap_raw / 1e6:,.2f}" if _cap_raw else ''
                except (ValueError, TypeError):
                    cap_mm_str = ''

                try:
                    _wt_raw = str(row.get('Weight (%)', '') or '').replace('%', '').replace(',', '').strip()
                    weight_str = f"{float(_wt_raw):.2f}%" if _wt_raw else ''
                except (ValueError, TypeError):
                    weight_str = ''

                prefix = asset_name[:2]
                close_yld = close_prices.get(prefix) if is_rates else None
                close_price_str = f"{close_yld:.4f}%" if close_yld is not None else ''

                mtm_str = ''
                if is_rates:
                    try:
                        _vol  = float(volume_str) if volume_str else None
                        _open = float(open_price_str) if open_price_str else None
                        if _dur and _vol and _open and close_yld is not None:
                            mtm = round(_vol * _dur * (close_yld - _open) / 10000.0, 4)
                            mtm_str = f"{mtm:+.4f}"
                    except (ValueError, TypeError):
                        pass

                display_rows.append({
                    'Asset Type':       asset_type,
                    'Universe':         str(row.get('Universe', '')),
                    'Asset Name':       asset_name,
                    'Instrument':       instrument,
                    'Duration':         duration_str,
                    'Capital (MM CNY)': cap_mm_str,
                    'Weight (%)':       weight_str,
                    'Open Price':       open_price_str,
                    'Open Date':        open_date_str,
                    'Volume (MM)':      volume_str,
                    'Close Price':      close_price_str,
                    'MtM (MM CNY)':     mtm_str,
                })

            if not display_rows:
                return _no_data("Beta snapshot is empty.")

            def _sum_num(col):
                t, any_ = 0.0, False
                for r in display_rows:
                    v = str(r.get(col, '')).replace(',', '').replace('%', '').replace('+', '').strip()
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

            _editable_cols = {'Open Price', 'Open Date', 'Volume (MM)'}
            _display_col_ids = [c for c in display_rows[0].keys() if c != 'Asset Name']
            columns = [
                {
                    'name': c,
                    'id': c,
                    'editable': c in _editable_cols,
                    **({'type': 'datetime'} if c == 'Open Date' else {}),
                }
                for c in _display_col_ids
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
                    'Open Price':   'User-editable: entry yield (%) for Rates, price for others',
                    'Open Date':    'User-editable: trade open date (YYYY-MM-DD)',
                    'Volume (MM)':  'User-editable: position size in MM CNY',
                    'Close Price':  'Latest yield (%) from factor levels — Rates only',
                    'MtM (MM CNY)': 'Rates only: Volume × Duration × (Close − Open) / 10000',
                },
                tooltip_delay=0,
                tooltip_duration=None,
            )

            content = html.Div([
                html.Div([
                    html.Span('Open Date calendar:',
                              style={'color': THEME['text_sub'], 'fontSize': '11px'}),
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
                        style={'color': THEME['text_sub'], 'fontSize': '11px', 'fontStyle': 'italic'},
                    ),
                ], style={'display': 'flex', 'alignItems': 'center', 'gap': '10px',
                          'marginBottom': '10px', 'flexWrap': 'wrap',
                          'position': 'relative', 'zIndex': '1001'}),
                table,
            ])
            status = f"Beta snapshot from {ts[:19]}"
            return content, status

        except Exception as exc:
            return _no_data(f"Error loading Beta snapshot: {exc}")

    # ── Alpha Book table ──────────────────────────────────────────────────────
    @app.callback(
        [Output('summary-alpha-table-container', 'children'),
         Output('summary-refresh-status', 'children', allow_duplicate=True)],
        [Input('summary-refresh-btn', 'n_clicks')],
        prevent_initial_call='initial_duplicate',
    )
    def update_summary_alpha_table(_n_clicks):
        """Render Alpha Book allocation table."""
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

        def _load_positions() -> dict:
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

        def _compute_carry_mtm(spread_type: str, instrument_id: str,
                               open_date_str: str, volume_mm: float) -> float | None:
            if _load_cr_ts is None or not open_date_str or not volume_mm:
                return None
            try:
                cr_ts = _load_cr_ts(spread_type)
                if cr_ts is None or instrument_id not in cr_ts.columns:
                    return None
                series = cr_ts[instrument_id].dropna()
                open_dt = pd.to_datetime(open_date_str)
                today   = pd.Timestamp.today().normalize()
                mask = (series.index >= open_dt) & (series.index <= today)
                carry_cum_pct = float(series[mask].sum()) / 90.0
                return round(volume_mm * carry_cum_pct / 100.0, 4)
            except Exception:
                return None

        if not _os.path.exists(_SUMMARY_ALPHA_PARQUET):
            return _no_data(
                "No Alpha snapshot found. Click RUN OPTIMIZATION in the Alpha Book → Portfolio tab first."
            )
        try:
            is_refresh = bool(_n_clicks and _ctx.triggered_id == 'summary-refresh-btn')
            df  = pd.read_parquet(_SUMMARY_ALPHA_PARQUET)
            ts  = df['_timestamp'].iloc[0] if '_timestamp' in df.columns else "unknown"
            pos = _load_positions()

            def _fmt1(v):
                try:
                    f = float(v)
                    return f"{f:.1f}" if pd.notna(f) else ''
                except (TypeError, ValueError):
                    return ''

            display_rows = []
            for _, row in df.iterrows():
                trade_id = str(row.get('ID', ''))
                if trade_id in ('TOTAL', ''):
                    continue
                spread_type    = str(row.get('spread_type', ''))
                key            = (spread_type, trade_id)
                saved          = pos.get(key, {})
                open_price_str = str(saved.get('open_price_bp', ''))
                volume_str     = str(saved.get('volume_mm', ''))
                open_date_str  = str(saved.get('open_date', ''))

                spread_val = row.get('spread', None)
                cp_bp      = round(float(spread_val), 4) if pd.notna(spread_val) else None
                notional   = float(row.get('notional_mm', 0) or 0)
                dv01_k     = float(row.get('DV01_k', 0) or 0)
                _dur_raw   = row.get('_duration', None)
                if _dur_raw is not None and pd.notna(_dur_raw):
                    duration = float(_dur_raw)
                elif notional > 0:
                    duration = round(dv01_k * 10.0 / notional, 2)
                else:
                    duration = 0.0

                mtm_price_mm = mtm_spd_bp = mtm_carry_mm = mtm_total_mm = None
                try:
                    open_price_bp = float(open_price_str) if open_price_str else None
                    volume_mm_f   = float(volume_str)     if volume_str     else None
                    direction     = row.get('direction', '').upper()
                    if open_price_bp is not None and cp_bp is not None:
                        if spread_type in ['TBondCurve', 'TBondSpread']:
                            mtm_spd_bp = open_price_bp - cp_bp
                        elif spread_type == 'TenorSpread':
                            mtm_spd_bp = cp_bp - open_price_bp
                        else:
                            mtm_spd_bp = (open_price_bp - cp_bp) if direction == 'SELL' else (cp_bp - open_price_bp)
                    if mtm_spd_bp is not None and volume_mm_f is not None:
                        mtm_price_mm = round(mtm_spd_bp * duration * volume_mm_f / 10000.0, 4)
                    if volume_mm_f is not None:
                        mtm_carry_mm = _compute_carry_mtm(spread_type, trade_id, open_date_str, volume_mm_f)
                    if mtm_price_mm is not None or mtm_carry_mm is not None:
                        mtm_total_mm = round((mtm_price_mm or 0.0) + (mtm_carry_mm or 0.0), 4)
                except (ValueError, TypeError):
                    pass

                display_rows.append({
                    'ID':                     trade_id,
                    'Spread Type':            spread_type,
                    'Style':                  row.get('style', ''),
                    'Direction':              row.get('direction', ''),
                    'Duration':               f"{duration:.2f}" if duration else 'N/A',
                    'Open price (bp)':        open_price_str,
                    'Volume (mm)':            volume_str,
                    'Open date':              open_date_str,
                    'Z-Score':                f"{float(row.get('Zscore', 0) or 0):.2f}",
                    'Close Price (bp)':       f"{cp_bp:.4f}" if cp_bp is not None else 'N/A',
                    'Target Volume (MM CNY)': f"{notional:,.1f}",
                    'DV01 (k CNY/bp)':        f"{dv01_k:.1f}",
                    'Carry+Roll (3m,bp)':     _fmt1(-float(row.get('carry_roll', 0) or 0) if str(row.get('direction', '')).strip().upper() == 'SELL' else row.get('carry_roll')),
                    'Breakeven (3m,bp)':      _fmt1(row.get('breakeven_3m')),
                    'Stop (bp)':              _fmt1(row.get('stop_loss')),
                    'Target (bp)':            _fmt1(row.get('profit_target')),
                    'MTM spd (bp)':           f"{mtm_spd_bp:,.4f}" if mtm_spd_bp is not None else '',
                    'MtM Carry (MM CNY)':     f"{mtm_carry_mm:,.4f}" if mtm_carry_mm is not None else '',
                    'MtM Value (MM CNY)':     f"{mtm_total_mm:,.4f}" if mtm_total_mm is not None else '',
                    'Target Weight (%)':      f"{float(row.get('weight', 0) or 0) * 100:.2f}%",
                    'Weight (%)':             '',
                })

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

            _BOND_OUTRIGHT_TYPES = {'TBondCurve', 'CBondCurve', 'TBondSwap', 'CBondSwap'}

            def _sum_col(col, filter_types=None):
                total, has_any = 0.0, False
                for r in display_rows:
                    if filter_types and r.get('Spread Type', '') not in filter_types:
                        continue
                    v = str(r.get(col, '')).replace(',', '').replace('%', '').strip()
                    if v:
                        try:
                            total += float(v); has_any = True
                        except (ValueError, TypeError):
                            pass
                return total if has_any else None

            _s_vol    = _sum_col('Volume (mm)',            _BOND_OUTRIGHT_TYPES)
            _s_tvol   = _sum_col('Target Volume (MM CNY)', _BOND_OUTRIGHT_TYPES)
            _s_dv01   = _sum_col('DV01 (k CNY/bp)')
            _s_carry  = _sum_col('MtM Carry (MM CNY)')
            _s_mtm    = _sum_col('MtM Value (MM CNY)')
            _s_tgt_wt = _sum_col('Target Weight (%)')
            _s_wt     = _sum_col('Weight (%)')

            total_row = {c: '' for c in display_rows[0].keys()}
            total_row['ID']                     = 'TOTAL'
            total_row['Volume (mm)']            = f"{_s_vol:,.1f}"    if _s_vol    is not None else ''
            total_row['Target Volume (MM CNY)'] = f"{_s_tvol:,.1f}"   if _s_tvol   is not None else ''
            total_row['DV01 (k CNY/bp)']        = f"{_s_dv01:.1f}"    if _s_dv01   is not None else ''
            total_row['MtM Carry (MM CNY)']     = f"{_s_carry:,.4f}"  if _s_carry  is not None else ''
            total_row['MtM Value (MM CNY)']     = f"{_s_mtm:,.4f}"    if _s_mtm    is not None else ''
            total_row['Target Weight (%)']      = f"{_s_tgt_wt:.2f}%" if _s_tgt_wt is not None else ''
            total_row['Weight (%)']             = f"{_s_wt:.2f}%"     if _s_wt     is not None else ''
            display_rows.append(total_row)

            _editable_cols = {'Open price (bp)', 'Volume (mm)', 'Open date'}
            columns = [
                {'name': c, 'id': c, 'editable': c in _editable_cols,
                 **({'type': 'datetime'} if c == 'Open date' else {})}
                for c in display_rows[0].keys()
            ]

            dir_styles = [
                {'if': {'filter_query': '{Direction} = "BUY"'},  'backgroundColor': 'rgba(0, 204, 150, 0.12)'},
                {'if': {'filter_query': '{Direction} = "SELL"'}, 'backgroundColor': 'rgba(239, 85, 59, 0.12)'},
                {'if': {'filter_query': '{ID} = "TOTAL"'},
                 'backgroundColor': THEME['table_header'], 'fontWeight': 'bold',
                 'borderTop': f"1px solid {THEME['accent']}"},
            ]
            editable_style = [
                {'if': {'column_id': c}, 'border': f'1px solid {THEME["accent"]}',
                 'backgroundColor': 'rgba(99,179,237,0.08)'}
                for c in _editable_cols
            ]

            _today = pd.Timestamp.today().normalize()
            _alert_rows: list = []
            _alert_ids: dict = {'stop': set(), 'target': set(), 'hold': set()}
            for r in display_rows:
                if r.get('ID') == 'TOTAL':
                    continue
                _tid  = r.get('ID', '')
                _dir  = str(r.get('Direction', '')).strip().upper()
                _op_s = str(r.get('Open price (bp)', '') or '').strip()
                _cp_s = str(r.get('Close Price (bp)', '') or '').strip()
                _sl_s = str(r.get('Stop (bp)', '') or '').strip()
                _tp_s = str(r.get('Target (bp)', '') or '').strip()
                _od_s = str(r.get('Open date', '') or '').strip()
                try:
                    _op = float(_op_s) if _op_s else None
                    _cp = float(_cp_s) if _cp_s else None
                    _sl = float(_sl_s) if _sl_s else None
                    _tp = float(_tp_s) if _tp_s else None
                except (ValueError, TypeError):
                    _op = _cp = _sl = _tp = None
                _days = None
                if _od_s:
                    try:
                        _od = pd.to_datetime(_od_s, errors='coerce')
                        if pd.notna(_od):
                            _days = (_today - _od.normalize()).days
                    except Exception:
                        pass
                if _op is not None and _cp is not None:
                    _spd_chg = _cp - _op
                    _pnl_dir = _spd_chg if _dir == 'BUY' else -_spd_chg
                    if _sl is not None and _pnl_dir <= -abs(_sl):
                        _alert_rows.append((_tid, f"Stop loss hit  (Δ={_pnl_dir:+.1f} bp, stop=−{abs(_sl):.1f} bp)", 'stop'))
                        _alert_ids['stop'].add(_tid)
                    elif _tp is not None and _pnl_dir >= abs(_tp):
                        _alert_rows.append((_tid, f"Target reached (Δ={_pnl_dir:+.1f} bp, target=+{abs(_tp):.1f} bp)", 'target'))
                        _alert_ids['target'].add(_tid)
                if _days is not None and _days >= 21 and _tid not in _alert_ids['stop'] and _tid not in _alert_ids['target']:
                    _alert_rows.append((_tid, f"Long hold: {_days}d — review if signal or carry has changed", 'hold'))
                    _alert_ids['hold'].add(_tid)

            for _tid in _alert_ids['stop']:
                dir_styles.append({'if': {'filter_query': f'{{ID}} = "{_tid}"'}, 'backgroundColor': 'rgba(239,85,59,0.22)'})
            for _tid in _alert_ids['target']:
                dir_styles.append({'if': {'filter_query': f'{{ID}} = "{_tid}"'}, 'backgroundColor': 'rgba(0,204,150,0.22)'})
            for _tid in _alert_ids['hold']:
                dir_styles.append({'if': {'filter_query': f'{{ID}} = "{_tid}"'}, 'backgroundColor': 'rgba(255,165,0,0.14)'})

            table = dash_table.DataTable(
                id='summary-alpha-table',
                data=display_rows,
                columns=columns,
                editable=True,
                row_deletable=True,
                style_cell={'textAlign': 'center', 'padding': '6px 8px',
                            'backgroundColor': THEME['table_row_odd'],
                            'color': THEME['text_main'], 'border': 'none', 'fontSize': '12px'},
                style_header={'backgroundColor': THEME['table_header'], 'color': THEME['text_main'],
                              'fontWeight': 'bold', 'border': 'none', 'whiteSpace': 'normal', 'height': 'auto'},
                style_data_conditional=[
                    {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']},
                    *dir_styles, *editable_style,
                ],
                style_table={'overflowX': 'auto'},
                sort_action='native',
                page_size=30,
                tooltip_header={
                    'Open price (bp)':    'User-editable: entry spread in bp',
                    'Volume (mm)':        'User-editable: position size in MM CNY',
                    'Open date':          'User-editable: trade open date (YYYY-MM-DD)',
                    'MTM spd (bp)':       'User-entered open spread shown in bp',
                    'MtM Carry (MM CNY)': 'Volume × cumulative carry+roll since open date',
                    'MtM Value (MM CNY)': 'MtM Price + MtM Carry',
                },
                tooltip_delay=0,
                tooltip_duration=None,
            )

            _reminder_banner = None
            if _alert_rows:
                _sev_style = {
                    'stop':   {'color': THEME['danger'],  'icon': '🛑'},
                    'target': {'color': THEME['success'], 'icon': '✅'},
                    'hold':   {'color': THEME['warning'], 'icon': '⏰'},
                }
                _items = []
                for _tid, _msg, _sev in _alert_rows:
                    _st = _sev_style[_sev]
                    _items.append(html.Div([
                        html.Span(f"{_st['icon']} ", style={'fontSize': '13px'}),
                        html.Span(_tid, style={'fontWeight': 'bold', 'color': _st['color'], 'marginRight': '6px'}),
                        html.Span(_msg, style={'color': THEME['text_main']}),
                    ], style={'marginBottom': '4px', 'fontSize': '12px'}))
                _reminder_banner = html.Div([
                    html.Div("Exit Reminders", style={
                        'fontWeight': 'bold', 'color': THEME['text_main'], 'fontSize': '13px',
                        'marginBottom': '6px', 'borderBottom': f"1px solid {THEME['table_header']}",
                        'paddingBottom': '4px',
                    }),
                    *_items,
                ], style={'backgroundColor': 'rgba(239,85,59,0.08)', 'border': f"1px solid {THEME['danger']}",
                          'borderRadius': '5px', 'padding': '10px 14px', 'marginBottom': '12px'})

            content = html.Div([
                html.Div([
                    html.Span('Open date calendar:', style={'color': THEME['text_sub'], 'fontSize': '11px'}),
                    dcc.DatePickerSingle(
                        id='summary-alpha-open-date-picker',
                        date=None, display_format='YYYY-MM-DD', clearable=True, disabled=True,
                        placeholder='Select an Open date cell',
                        style={'backgroundColor': THEME['bg_input']},
                    ),
                    html.Span(
                        id='summary-alpha-open-date-target',
                        children='Click an Open date cell to edit with the calendar.',
                        style={'color': THEME['text_sub'], 'fontSize': '11px', 'fontStyle': 'italic'},
                    ),
                ], style={'display': 'flex', 'alignItems': 'center', 'gap': '10px',
                          'marginBottom': '10px', 'flexWrap': 'wrap', 'position': 'relative', 'zIndex': '1001'}),
                *([_reminder_banner] if _reminder_banner else []),
                table,
            ])
            status = f"Alpha snapshot from {ts[:19]}" + (" — saved" if is_refresh else "")
            return content, status

        except Exception as exc:
            return _no_data(f"Error loading Alpha snapshot: {exc}")

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
        """Persist user-editable fields (open_price, open_date, volume) to parquet."""
        records = [
            {
                'asset_name':  str(r.get('Asset Name', '')),
                'instrument':  str(r.get('Instrument', '')),
                'open_price':  str(r.get('Open Price', '')),
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

    def _tenor_str_to_years(tenor: str) -> float:
        """Convert tenor string like '1Y', '6M', '10Y' to fractional years."""
        import re as _re
        m = _re.match(r'(\d+)([MY])', tenor.upper())
        if not m:
            return 0.0
        n, unit = float(m.group(1)), m.group(2)
        return n / 12.0 if unit == 'M' else n

    def _load_leg_data() -> dict:
        """Load instrument data needed for alpha position leg resolution (called once per refresh)."""
        ld: dict = {
            'otr_cgb': {}, 'otr_cdb': {},
            'ref_cgb': pd.Series(dtype=object), 'ref_cdb': pd.Series(dtype=object),
            'nb': {}, 'tb_stat': None, 'futs_def': pd.DataFrame(),
            'fs_irs': {'TS': 'FR007S2Y.IR', 'TF': 'FR007S5Y.IR',
                       'T': 'FR007S10Y.IR', 'TL': 'FR007S10Y.IR'},
        }
        _OTR_BANDS = {
            '1Y': (0.9, 1.2), '2Y': (1.6, 2.5), '5Y': (4.0, 6.0),
            '10Y': (8.5, 10.0), '20Y': (15.0, 25.0), '30Y': (25.0, 30.0),
        }

        def _pick_otr(btype: str) -> dict:
            try:
                bi = pd.read_pickle(str(DIR_INPUT / f'{btype}-InstrumentInfo.pkl'))
            except Exception:
                return {}
            if not isinstance(bi, pd.DataFrame) or bi.empty:
                return {}
            need = ['起息日期', '到期日期', '证券全称', '成交量', '债券余额:亿']
            if not all(c in bi.columns for c in need):
                return {}
            today = pd.Timestamp.today().normalize()
            vol = pd.to_numeric(bi['成交量'], errors='coerce')
            bal = pd.to_numeric(bi['债券余额:亿'], errors='coerce')
            tr  = (vol / bal / 1e4).replace([np.inf, -np.inf], 0).fillna(0)
            mat = pd.to_datetime(bi['到期日期'], errors='coerce')
            sdt = pd.to_datetime(bi['起息日期'], errors='coerce')
            ttm = (mat - today).dt.days / 365.0
            kw  = '国债' if btype == 'TBond' else '国家开发银行'
            nm  = bi['证券全称'].astype(str).str.contains(kw, na=False)
            res = {}
            for tenor, (lo, hi) in _OTR_BANDS.items():
                mask = (ttm.notna() & sdt.notna() & (sdt < today) & (mat > today)
                        & (ttm > lo) & (ttm <= hi) & nm & (bal > 0) & (vol > 0))
                bkt = tr[mask]
                res[tenor] = bkt.idxmax() if not bkt.empty and (bkt > 0).any() else ''
            return res

        ld['otr_cgb'] = _pick_otr('TBond')
        ld['otr_cdb'] = _pick_otr('CBond')

        for key, fname in [('ref_cgb', 'TBond-cvref.pkl'), ('ref_cdb', 'CBond-cvref.pkl')]:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    cv = pd.read_pickle(str(DIR_INPUT / fname))
                rb = cv.get('RefBond', pd.DataFrame()) if isinstance(cv, dict) else pd.DataFrame()
                ld[key] = rb.iloc[-1] if not rb.empty else pd.Series(dtype=object)
            except Exception:
                pass

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fspds = pd.read_pickle(str(DIR_INPUT / 'futures-spds.pkl'))
            ld['nb']      = fspds.get('NetBasis', {})
            ld['tb_stat'] = fspds.get('TermBasis', {}).get('StatInfo')
        except Exception:
            pass

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fi = pd.read_pickle(str(DIR_INPUT / 'futures-InstrumentInfo.pkl'))
            ld['futs_def'] = fi.get('Def', pd.DataFrame())
        except Exception:
            pass

        return ld

    def _resolve_legs(stype: str, tid: str, duration: float, ld: dict) -> tuple:
        """Return (leg1, leg2) bond/contract codes for a given spread type and position ID."""
        import re as _re

        otr_cgb  = ld.get('otr_cgb', {})
        otr_cdb  = ld.get('otr_cdb', {})
        ref_cgb  = ld.get('ref_cgb', pd.Series(dtype=object))
        ref_cdb  = ld.get('ref_cdb', pd.Series(dtype=object))
        nb       = ld.get('nb', {})
        futs_def = ld.get('futs_def', pd.DataFrame())
        fs_irs   = ld.get('fs_irs', {})

        # Integer tenor → OTR tenor label
        _T_MAP = {1: '1Y', 2: '2Y', 5: '5Y', 10: '10Y', 20: '20Y', 30: '30Y'}
        def _t_label(n: float) -> str:
            ni = int(round(n))
            if ni in _T_MAP:
                return _T_MAP[ni]
            return min(_T_MAP.values(), key=lambda v: abs(int(v[:-1]) - n))

        # Duration → nearest reference bond from cvref series
        _REF_TENORS = [(0.3,'0.3Y'),(0.5,'0.5Y'),(0.7,'0.7Y'),(1.0,'1Y'),(1.5,'1.5Y'),
                       (2.0,'2Y'),(3.0,'3Y'),(5.0,'5Y'),(7.0,'7Y'),(10.0,'10Y'),
                       (20.0,'20Y'),(30.0,'30Y')]
        def _nearest_ref(dur: float, ref_s: pd.Series) -> str:
            best = min(_REF_TENORS, key=lambda x: abs(x[0] - dur))
            v = ref_s.get(f'Term near {best[1]}', '')
            return str(v) if v and str(v) not in ('nan', 'None', '—') else ''

        # Front and next futures contract codes for a given contract type
        def _futs_front_next(ctype: str) -> tuple:
            if futs_def.empty:
                return ('', '')
            parsed = []
            for idx in futs_def.index:
                m = _re.match(r'^([A-Z]+)\d', str(idx).replace('.CFE', ''))
                parsed.append(m.group(1) if m else '')
            sub = futs_def[[t == ctype for t in parsed]]
            if sub.empty:
                return ('', '')
            sub_s = sub.sort_values('LASTTRADE_DATE')
            front = str(sub_s.index[0]).replace('.CFE', '') if len(sub_s) >= 1 else ''
            nxt   = str(sub_s.index[1]).replace('.CFE', '') if len(sub_s) >= 2 else ''
            return (front, nxt)

        if stype == 'TenorSpread':
            upper = tid.upper()
            if upper.startswith('CDBCGB-'):
                m = _re.match(r'CDBCGB-(\d+)Y$', upper)
                if m:
                    t = _t_label(float(m.group(1)))
                    return (otr_cdb.get(t, ''), otr_cgb.get(t, ''))
            elif upper.startswith('CGB-'):
                m = _re.search(r'(\d+)S(\d+)S', upper)
                if m:
                    return (otr_cgb.get(_t_label(float(m.group(1))), ''),
                            otr_cgb.get(_t_label(float(m.group(2))), ''))
            elif upper.startswith('CDB-'):
                m = _re.search(r'(\d+)S(\d+)S', upper)
                if m:
                    return (otr_cdb.get(_t_label(float(m.group(1))), ''),
                            otr_cdb.get(_t_label(float(m.group(2))), ''))
            return ('', '')

        elif stype in ('TBondCurve', 'TBondSwap'):
            return (tid, _nearest_ref(duration, ref_cgb))

        elif stype in ('CBondCurve', 'CBondSwap'):
            return (tid, _nearest_ref(duration, ref_cdb))

        elif stype == 'NetBasis':
            ctype = tid.split('-')[0]
            si = nb.get(ctype, {}).get('StatInfo')
            if si is not None and not si.empty:
                ctd = str(si['ctd_code'].iloc[0]) if 'ctd_code' in si.columns else ''
                fut = str(si['futures'].iloc[0]).replace('.CFE', '') if 'futures' in si.columns else ''
                return (ctd, fut)
            return ('', '')

        elif stype == 'TermBasis':
            return _futs_front_next(tid)

        elif stype == 'FuturesSwap':
            front, _ = _futs_front_next(tid)
            return (front, fs_irs.get(tid, ''))

        elif stype == 'SwapSpread':
            return _parse_repo_spread_legs(tid)

        elif stype == 'IRS':
            return _parse_repo_spread_legs(tid)

        return ('', '')

    # ── Risk subtab: inventory + factor exposure + key-term DV01 ladder ─────────
    @app.callback(
        [Output('risk-inventory-container', 'children'),
         Output('risk-exposure-container', 'children'),
         Output('risk-refresh-status', 'children')],
        [Input('an-summary-subtabs', 'value'),
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
            'TBondCurve':  'CGB',   'TBondSwap':  'CGB',
            'CBondCurve':  'PBB',   'CBondSwap':  'PBB',
            'TenorSpread': 'CGB',   # CGB leg is always present in tenor spreads
            'IRS':         'Repo7d',
            'SwapSpread':  'Repo7d',  # Repo7d-XyYy IRS spreads stored as SwapSpread
            'CDB':         'PBB',
            'ICP':         'Shi3M',
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
        _ld = _load_leg_data()   # instrument data for leg resolution
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

                    alpha_rows.append({
                        'Book': 'Alpha', 'Name': tid, 'Instrument': tid,
                        'Leg1': leg1, 'Leg2': leg2,
                        'Sector': stype,
                        'Capital (MM)': f"{notional:.1f}",
                        'DV01 (MM/bp)': f"{dv01_mm * dir_sign:.4f}",
                        'Direction': direction,
                    })

                    # Key Term ladder: IRS spreads (any Repo7d-XyYy ID) get split
                    # across both tenor legs; everything else goes to a single bucket.
                    col = _ALPHA_COL.get(stype, 'Others')
                    if dv01_mm != 0.0:
                        _l1, _l2 = _parse_repo_spread_legs(tid)
                        _m1 = re.search(r'FR007S([^.]+)\.IR', _l1)
                        _m2 = re.search(r'FR007S([^.]+)\.IR', _l2)
                        if _m1 and _m2:
                            # Two-leg IRS: +DV01 at short-tenor leg, −DV01 at long-tenor leg
                            tenor1 = _dur_to_tenor(_tenor_str_to_years(_m1.group(1)))
                            tenor2 = _dur_to_tenor(_tenor_str_to_years(_m2.group(1)))
                            kt_grid[tenor1][col] = round(kt_grid[tenor1][col] + dv01_mm * dir_sign, 4)
                            kt_grid[tenor2][col] = round(kt_grid[tenor2][col] - dv01_mm * dir_sign, 4)
                        else:
                            tenor = _dur_to_tenor(duration)
                            kt_grid[tenor][col] = round(kt_grid[tenor][col] + dv01_mm * dir_sign, 4)
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

        # ── Bar-in-cell helper ────────────────────────────────────────────────
        def _make_bar_styles(rows: list, cols: list, shared_max: bool = True) -> list:
            """Return style_data_conditional entries for gradient bar-in-cell effect."""
            col_vals: dict = {}
            for c in cols:
                vals = []
                for row in rows:
                    try:
                        vals.append(float(str(row.get(c, '')).replace(',', '').replace('+', '').strip()))
                    except (ValueError, TypeError):
                        vals.append(None)
                col_vals[c] = vals
            if shared_max:
                max_abs = max((abs(v) for cv in col_vals.values() for v in cv if v is not None), default=0.0)
            styles = []
            for c in cols:
                if not shared_max:
                    max_abs = max((abs(v) for v in col_vals[c] if v is not None), default=0.0)
                if max_abs < 1e-10:
                    continue
                for i, v in enumerate(col_vals[c]):
                    if v is None or abs(v) < 1e-10:
                        continue
                    pct = min(abs(v) / max_abs * 100, 100)
                    if v > 0:
                        bg = f"linear-gradient(90deg, rgba(39,174,96,0.22) {pct:.1f}%, transparent {pct:.1f}%)"
                    else:
                        bg = f"linear-gradient(270deg, rgba(231,76,60,0.22) {pct:.1f}%, transparent {pct:.1f}%)"
                    styles.append({'if': {'row_index': i, 'column_id': c}, 'background': bg})
            return styles

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
                _exp_bar_styles = _make_bar_styles(fr_rows, ['Exposure'])
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
                        *_exp_bar_styles,
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
        _kt_bar_styles = _make_bar_styles(
            kt_display, ['CGB', 'PBB', 'Others', 'Repo7d', 'Shi3M', 'Total'],
            shared_max=True,
        ) if kt_display else []

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
                    *_kt_pos_style, *_kt_neg_style, *_kt_bar_styles,
                ],
                style_table={'overflowX': 'auto', 'maxWidth': '700px'},
            )
            if kt_display
            else _no_data_div("No rate positions found for Key Term Exposure.")
        )

        # ── Assemble second panel: Factor Exposure + Key Term side-by-side ────
        exposure_panel = html.Div([
            html.Div([
                html.H6("Beta book",
                        style={'color': THEME['warning'], 'fontSize': '12px', 'marginBottom': '4px'}),
                html.Div(
                    "Exposure: portfolio beta to factor (signed, dimensionless = Bᵀw)",
                    style={'color': THEME['text_sub'], 'fontSize': '10px', 'marginBottom': '6px',
                           'fontStyle': 'italic'},
                ),
                factor_exp_table,
            ], style={'flex': '1', 'minWidth': '280px', 'marginRight': '20px'}),
            html.Div([
                html.H6("Beta + Alpha: DV01 (MM/bp)",
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

