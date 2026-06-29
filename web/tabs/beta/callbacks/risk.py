# -*- coding: utf-8 -*-
"""Risk / Summary tab callbacks: subtab show/hide, books table refresh."""

from __future__ import annotations

import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State, ALL
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
from ...alpha.data import load_spread_data as _load_alpha_spread_data
from ._common import (
    _SUMMARY_BETA_PARQUET,
    _SUMMARY_ALPHA_PARQUET,
    _BETA_BOOK_POSITIONS_PARQUET,
    _BETA_BOOK_USER_PARQUET,
    _ALPHA_POSITIONS_PARQUET,
    _get_beta_close_prices,
    _load_cr_ts,
    _allocation_bar,
    _price_progress_bar,
    _dir_badge,
    _style_badge,
    _signed_value_style,
    _zscore_cell_style,
    _sortable_header,
    _apply_sort,
)
from ._risk_charts import (
    build_net_position_fig,
    build_dv01_ladder_fig,
    build_factor_risk_fig,
    build_kpi_cards,
    build_kpi_strip,
    build_inventory_summary,
)


def _coerce_float(value) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return float(str(value).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None


def _row_key(row: dict, default: int = -1) -> int:
    """Parse a row's `__row_key` as int, falling back on non-numeric values
    (e.g. the synthetic TOTAL row, whose `__row_key` is '')."""
    try:
        return int(row.get('__row_key', default))
    except (TypeError, ValueError):
        return default


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

    # ── Portfolio Combination strip: collapse/expand ───────────────────────────
    @app.callback(
        [Output('summary-combo-detail', 'style'),
         Output('summary-combo-chevron', 'children')],
        Input('summary-combo-toggle', 'n_clicks'),
        prevent_initial_call=True,
    )
    def _toggle_combo_detail(n_clicks):
        is_open = bool(n_clicks and n_clicks % 2 == 1)
        style = {'overflow': 'hidden'}
        style['display'] = 'block' if is_open else 'none'
        return style, ('▲ collapse' if is_open else '▼ details')

    # ── Beta / Alpha book toggle ────────────────────────────────────────────────
    _ACCENT = THEME['accent']
    _WARN = THEME['warning']

    def _book_btn_style(active: bool, accent: str):
        base = {
            'padding': '7px 18px', 'fontSize': '13px', 'fontWeight': '500',
            'cursor': 'pointer', 'border': f'1px solid {THEME["table_header"]}',
            'transition': 'all 100ms',
        }
        if active:
            base.update({'backgroundColor': THEME['bg_input'], 'color': accent, 'borderColor': accent})
        else:
            base.update({'backgroundColor': 'transparent', 'color': THEME['text_sub']})
        return base

    def _col_pill_style(active: bool):
        style = {
            'display': 'inline-flex', 'alignItems': 'center', 'gap': '5px',
            'padding': '3px 9px', 'borderRadius': '20px', 'fontSize': '10px',
            'fontWeight': '600', 'letterSpacing': '.05em', 'cursor': 'pointer',
            'border': f'1px solid {THEME["table_header"]}',
        }
        if active:
            style.update({'backgroundColor': 'rgba(61,139,212,0.25)', 'color': THEME['text_main'], 'borderColor': THEME['accent']})
        else:
            style.update({'color': THEME['text_sub']})
        return style

    def _col_pills_row(book: str, col_vis: dict):
        col_vis = col_vis or {}
        label = html.Span("Columns", style={
            'fontSize': '10px', 'fontWeight': '600', 'letterSpacing': '.07em',
            'textTransform': 'uppercase', 'color': THEME['text_sub'], 'marginRight': '4px',
        })
        names = {'open_date': 'Open Date', 'volume': 'Volume', 'score': 'Score'}
        # Always render all three pills (even 'score' on the Beta book) and hide
        # the irrelevant one via style instead of omitting it — a static-id pill
        # missing from the live layout breaks its callback's Input resolution
        # client-side, which silently disables the other pills sharing that callback.
        pills = []
        for k in ('open_date', 'volume', 'score'):
            style = _col_pill_style(bool(col_vis.get(k)))
            if k == 'score' and book == 'beta':
                style = {**style, 'display': 'none'}
            pills.append(html.Button(names[k], id=f'summary-col-pill-{k}', n_clicks=0, style=style))
        return [label, *pills]

    @app.callback(
        [Output('summary-book-active', 'data'),
         Output('summary-book-beta-btn', 'style'),
         Output('summary-book-alpha-btn', 'style'),
         Output('summary-beta-table-container', 'style'),
         Output('summary-alpha-table-container', 'style'),
         Output('summary-col-pills-row', 'children')],
        [Input('summary-book-beta-btn', 'n_clicks'),
         Input('summary-book-alpha-btn', 'n_clicks'),
         Input('summary-col-visibility', 'data')],
        State('summary-book-active', 'data'),
        prevent_initial_call=True,
    )
    def _toggle_book(_beta_clicks, _alpha_clicks, col_vis, current_book):
        triggered = dash.ctx.triggered_id
        if triggered == 'summary-book-alpha-btn':
            book = 'alpha'
        elif triggered == 'summary-book-beta-btn':
            book = 'beta'
        else:
            book = current_book or 'beta'

        return (
            book,
            _book_btn_style(book == 'beta', _ACCENT),
            _book_btn_style(book == 'alpha', _WARN),
            {'minHeight': '60px', 'display': 'block' if book == 'beta' else 'none'},
            {'minHeight': '60px', 'display': 'block' if book == 'alpha' else 'none'},
            _col_pills_row(book, col_vis),
        )

    # ── Column-visibility pills ─────────────────────────────────────────────────
    @app.callback(
        Output('summary-col-visibility', 'data'),
        [Input('summary-col-pill-open_date', 'n_clicks'),
         Input('summary-col-pill-volume', 'n_clicks'),
         Input('summary-col-pill-score', 'n_clicks')],
        State('summary-col-visibility', 'data'),
        prevent_initial_call=True,
    )
    def _toggle_col_visibility(_od_clicks, _vol_clicks, _score_clicks, col_vis):
        col_vis = dict(col_vis or {})
        triggered = dash.ctx.triggered_id
        key = {
            'summary-col-pill-open_date': 'open_date',
            'summary-col-pill-volume': 'volume',
            'summary-col-pill-score': 'score',
        }.get(triggered)
        if key is None:
            raise dash.exceptions.PreventUpdate
        col_vis[key] = not col_vis.get(key, False)
        return col_vis

    @app.callback(
        [Output('summary-beta-table-container', 'children'),
         Output('summary-refresh-status', 'children'),
         Output('summary-beta-rows-store', 'data')],
        [Input('summary-refresh-btn', 'n_clicks'),
         Input('summary-col-visibility', 'data'),
         Input('summary-beta-sort', 'data')],
        State('summary-beta-active-date-row', 'data'),
        prevent_initial_call=False,
    )
    def update_summary_book_table(_n_clicks, col_vis, sort_state, active_date_row):
        """Render Beta Book allocation table."""
        col_vis = col_vis or {}
        sort_state = sort_state or {'col': None, 'dir': 'asc'}
        import os as _os
        from dash import ctx as _ctx

        def _no_data(msg: str):
            return (
                html.Div(msg, style={
                    'color': THEME['text_sub'], 'fontStyle': 'italic',
                    'padding': '30px', 'textAlign': 'center', 'fontSize': '13px',
                }),
                "",
                [],
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
            _ASSET_TYPE_COLOR = {
                'FX':           'rgba(34,211,238,0.55)',
                'Rates':        'rgba(61,139,212,0.55)',
                'Commodities':  'rgba(224,162,60,0.55)',
                'Equities':     'rgba(168,107,214,0.55)',
                'Credit':       'rgba(52,211,153,0.55)',
            }
            _ASSET_TYPE_BADGE_BG = {
                'FX':           'rgba(34,211,238,0.15)',
                'Rates':        'rgba(61,139,212,0.15)',
                'Commodities':  'rgba(224,162,60,0.15)',
                'Equities':     'rgba(168,107,214,0.15)',
                'Credit':       'rgba(52,211,153,0.15)',
            }
            _ASSET_TYPE_TEXT = {
                'FX':           '#22d3ee',
                'Rates':        '#3d8bd4',
                'Commodities':  '#e0a23c',
                'Equities':     '#a86bd6',
                'Credit':       '#34d399',
            }
            display_rows = []
            for _row_idx, (_, row) in enumerate(df.iterrows()):
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
                    '__row_key':        str(_row_idx),
                    'Asset Type':       asset_type,
                    'Universe':         str(row.get('Universe', '')),
                    'Asset Name':       asset_name,
                    'Instrument':       instrument,
                    'Duration':         duration_str,
                    'Capital (MM CNY)': cap_mm_str,
                    'Weight (%)':       weight_str,
                    'Allocation':       weight_str,
                    'Open Price':       open_price_str,
                    'Open Date':        open_date_str,
                    'Volume (MM)':      volume_str,
                    'Close Price':      close_price_str,
                    'MtM (MM CNY)':     mtm_str,
                    '_asset_color':     _ASSET_TYPE_COLOR.get(asset_type, 'rgba(61,139,212,0.55)'),
                    '_asset_badge_bg':  _ASSET_TYPE_BADGE_BG.get(asset_type, 'rgba(61,139,212,0.15)'),
                    '_asset_text':      _ASSET_TYPE_TEXT.get(asset_type, '#3d8bd4'),
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

            _visible_cols = []
            if col_vis.get('open_date'):
                _visible_cols.append('Open Date')
            if col_vis.get('volume'):
                _visible_cols.append('Volume (MM)')

            body_rows  = [r for r in display_rows if r.get('Asset Type') != 'TOTAL']
            total_rows = [r for r in display_rows if r.get('Asset Type') == 'TOTAL']
            _numeric_cols = {'Duration', 'Capital (MM CNY)', 'Weight (%)', 'Allocation',
                              'Open Price', 'Volume (MM)', 'Close Price', 'MtM (MM CNY)'}
            body_rows = _apply_sort(body_rows, sort_state, _numeric_cols)

            _ALL_COLS = [
                ('Asset Type', 'left'), ('Universe', 'left'), ('Instrument', 'left'),
                ('Duration', 'right'), ('Capital (MM CNY)', 'right'), ('Weight (%)', 'right'),
                ('Allocation', 'left'), ('Open Price', 'right'), ('Open Date', 'right'),
                ('Volume (MM)', 'right'), ('Close Price', 'right'), ('MtM (MM CNY)', 'right'),
            ]
            _cols = [(c, a) for c, a in _ALL_COLS
                     if c not in ('Open Date', 'Volume (MM)') or c in _visible_cols]

            header_row = html.Tr([
                _sortable_header(c, c, 'beta', sort_state, align=a) for c, a in _cols
            ], style={'background': THEME['table_header'], 'borderBottom': f"1px solid {THEME['accent']}"})

            def _editable_cell(row_idx: int, col: str, value: str, kind: str = 'text'):
                if kind == 'date':
                    return html.Td([
                        html.Button(
                            value or '—',
                            id={'type': 'beta-date-trigger', 'row': row_idx},
                            n_clicks=0,
                            className='an-date-trigger-btn',
                            style={
                                'background': 'rgba(99,179,237,0.08)',
                                'border': f'1px solid {THEME["accent"]}', 'borderRadius': '3px',
                                'color': THEME['text_main'], 'fontSize': '13px', 'padding': '5px 8px',
                                'cursor': 'pointer', 'width': '100%', 'minWidth': '92px',
                                'whiteSpace': 'nowrap',
                            },
                        ),
                    ], style={'padding': '5px 10px', 'textAlign': 'right', 'minWidth': '92px'})
                return html.Td(
                    dcc.Input(
                        id={'type': 'beta-cell-input', 'row': row_idx, 'col': col},
                        type='text', value=value, debounce=True,
                        style={
                            'background': 'rgba(99,179,237,0.08)', 'border': f'1px solid {THEME["accent"]}',
                            'borderRadius': '3px', 'color': THEME['text_main'], 'fontSize': '11px',
                            'padding': '3px 6px', 'width': '64px', 'textAlign': 'right',
                        },
                    ),
                    style={'padding': '5px 10px', 'textAlign': 'right'},
                )

            def _cell(row_idx: int, col: str, row: dict, align: str):
                val = row.get(col, '')
                base_style = {'padding': '5px 10px', 'textAlign': align, 'color': THEME['text_main']}
                if col == 'Asset Type':
                    return html.Td(html.Span(val, style={
                        'padding': '2px 6px', 'borderRadius': '3px', 'fontSize': '9px', 'fontWeight': '600',
                        'background': row.get('_asset_badge_bg', 'rgba(61,139,212,0.15)'),
                        'color': row.get('_asset_text', '#3d8bd4'),
                    }), style=base_style)
                if col == 'Universe':
                    return html.Td(val, style={**base_style, 'color': THEME['text_sub'], 'fontSize': '11px'})
                if col == 'Instrument':
                    return html.Td(val, style={**base_style, 'fontWeight': '500'})
                if col == 'Open Price':
                    return _editable_cell(row_idx, col, val, 'text')
                if col == 'Volume (MM)':
                    return _editable_cell(row_idx, col, val, 'text')
                if col == 'Open Date':
                    return _editable_cell(row_idx, col, val, 'date')
                if col == 'MtM (MM CNY)':
                    try:
                        signed = float(str(val).replace(',', '').replace('+', '')) if val else None
                    except (TypeError, ValueError):
                        signed = None
                    return html.Td(val, style={**base_style, **_signed_value_style(signed)})
                if col == 'Allocation':
                    try:
                        pct = float(str(val).replace('%', '').replace(',', '')) if val else 0.0
                    except (TypeError, ValueError):
                        pct = 0.0
                    color = row.get('_asset_color', 'rgba(61,139,212,0.55)')
                    return html.Td(_allocation_bar(pct, color), style={**base_style, 'minWidth': '100px'})
                return html.Td(val, style=base_style)

            body_trs = []
            for i, row in enumerate(body_rows):
                row_idx = _row_key(row, i)
                row_bg = THEME['bg_card'] if i % 2 == 1 else 'transparent'
                body_trs.append(html.Tr(
                    [_cell(row_idx, c, row, a) for c, a in _cols],
                    style={'background': row_bg, 'borderBottom': '1px solid rgba(255,255,255,0.04)'},
                ))
            for trow in total_rows:
                body_trs.append(html.Tr(
                    [html.Td(trow.get(c, ''), style={
                        'padding': '5px 10px', 'textAlign': a, 'fontWeight': 'bold',
                        'color': THEME['text_main'],
                    }) for c, a in _cols],
                    style={'background': THEME['table_header'], 'borderTop': f"1px solid {THEME['accent']}"},
                ))

            table = html.Div(
                html.Table([
                    html.Thead(header_row),
                    html.Tbody(body_trs),
                ], style={'width': '100%', 'borderCollapse': 'collapse', 'fontSize': '11px'}),
                style={'overflowX': 'auto'},
            )

            _active_target = next((r for r in display_rows if _row_key(r, -1) == active_date_row), None) \
                if active_date_row is not None else None
            if _active_target is not None:
                _parsed_active = pd.to_datetime(_active_target.get('Open Date', ''), errors='coerce')
                _picker_date = _parsed_active.date().isoformat() if pd.notna(_parsed_active) else None
                _picker_disabled = False
                _picker_label = f"Editing {_active_target.get('Asset Name', '')}"
            else:
                _picker_date = None
                _picker_disabled = True
                _picker_label = 'Click an Open Date cell to edit with the calendar.'

            content = html.Div([
                html.Div([
                    html.Span('Open Date calendar:',
                              style={'color': THEME['text_sub'], 'fontSize': '11px'}),
                    dcc.DatePickerSingle(
                        id='summary-beta-open-date-picker',
                        date=_picker_date,
                        display_format='YYYY-MM-DD',
                        clearable=True,
                        disabled=_picker_disabled,
                        placeholder='Select an Open Date cell',
                        style={'backgroundColor': THEME['bg_input']},
                    ),
                    html.Span(
                        id='summary-beta-open-date-target',
                        children=_picker_label,
                        style={'color': THEME['text_sub'], 'fontSize': '11px', 'fontStyle': 'italic'},
                    ),
                ], style={'display': 'flex', 'alignItems': 'center', 'gap': '10px',
                          'marginBottom': '10px', 'flexWrap': 'wrap',
                          'position': 'relative', 'zIndex': '1001'}),
                table,
            ])
            status = f"Beta snapshot from {ts[:19]}"
            return content, status, display_rows

        except Exception as exc:
            return _no_data(f"Error loading Beta snapshot: {exc}")

    # ── Alpha Book table ──────────────────────────────────────────────────────
    @app.callback(
        [Output('summary-alpha-table-container', 'children'),
         Output('summary-refresh-status', 'children', allow_duplicate=True),
         Output('summary-alpha-rows-store', 'data')],
        [Input('summary-refresh-btn', 'n_clicks'),
         Input('summary-col-visibility', 'data'),
         Input('summary-alpha-sort', 'data')],
        State('summary-alpha-active-date-row', 'data'),
        prevent_initial_call='initial_duplicate',
    )
    def update_summary_alpha_table(_n_clicks, col_vis, sort_state, active_date_row):
        """Render Alpha Book allocation table."""
        import os as _os
        sort_state = sort_state or {'col': None, 'dir': 'asc'}
        from dash import ctx as _ctx
        col_vis = col_vis or {}

        def _no_data(msg: str):
            return (
                html.Div(msg, style={
                    'color': THEME['text_sub'], 'fontStyle': 'italic',
                    'padding': '30px', 'textAlign': 'center', 'fontSize': '13px',
                }),
                "",
                [],
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

        # Load leg data once for all spread types (used by _resolve_legs below)
        _ld = None

        def _resolve_bondcurve_legs(spread_type: str, trade_id: str, duration: float) -> tuple[str, str]:
            """Resolve leg1/leg2 for all spread types using the canonical leg resolver."""
            nonlocal _ld
            if _ld is None:
                try:
                    _ld = _load_leg_data()
                except Exception:
                    _ld = {}
            return _resolve_legs(spread_type, trade_id, duration, _ld)

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
            for _row_idx, (_, row) in enumerate(df.iterrows()):
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

                # Resolve leg1/leg2 for all spread types
                leg1, leg2 = _resolve_bondcurve_legs(spread_type, trade_id, duration)

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

                # Stop/Target are stored as bp *distances* from entry, signed by
                # direction (BUY: stop below entry, target above; SELL: reversed).
                _direction_u = str(row.get('direction', '')).strip().upper()
                _stop_mag   = row.get('stop_loss')
                _target_mag = row.get('profit_target')
                stop_level = target_level = None
                try:
                    _sl_mag = float(_stop_mag) if _stop_mag not in (None, '') else None
                    _tp_mag = float(_target_mag) if _target_mag not in (None, '') else None
                    if open_price_bp is not None:
                        if _sl_mag is not None:
                            stop_level = open_price_bp - _sl_mag if _direction_u == 'BUY' else open_price_bp + _sl_mag
                        if _tp_mag is not None:
                            target_level = open_price_bp + _tp_mag if _direction_u == 'BUY' else open_price_bp - _tp_mag
                except (ValueError, TypeError):
                    pass

                display_rows.append({
                    '__row_key':              str(_row_idx),
                    'ID':                     trade_id,
                    'Leg 1':                  leg1,
                    'Leg 2':                  leg2,
                    'Spread Type':            spread_type,
                    'Style':                  row.get('style', ''),
                    'Direction':              row.get('direction', ''),
                    'Duration':               f"{duration:.2f}" if duration else 'N/A',
                    'Open price (bp)':        open_price_str,
                    'Volume (mm)':            volume_str,
                    'Open date':              open_date_str,
                    'Z-Score':                f"{float(row.get('Zscore', 0) or 0):.2f}",
                    'Close Price (bp)':       f"{cp_bp:.4f}" if cp_bp is not None else 'N/A',
                    'Progress':               '',
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
                    '_entry_level':           open_price_str,
                    '_current_level':         f"{cp_bp:.4f}" if cp_bp is not None else '',
                    '_stop_level':            f"{stop_level:.4f}" if stop_level is not None else '',
                    '_target_level':          f"{target_level:.4f}" if target_level is not None else '',
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

            _visible_cols = []
            if col_vis.get('open_date'):
                _visible_cols.append('Open date')
            if col_vis.get('volume'):
                _visible_cols.append('Volume (mm)')
            if col_vis.get('score'):
                _visible_cols.append('Z-Score')

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

            _alert_severity = {}
            for _tid in _alert_ids['stop']:
                _alert_severity[_tid] = 'stop'
            for _tid in _alert_ids['target']:
                _alert_severity[_tid] = 'target'
            for _tid in _alert_ids['hold']:
                _alert_severity[_tid] = 'hold'
            _row_alert_bg = {
                'stop':   'rgba(239,85,59,0.22)',
                'target': 'rgba(0,204,150,0.22)',
                'hold':   'rgba(255,165,0,0.14)',
            }

            body_rows  = [r for r in display_rows if r.get('ID') != 'TOTAL']
            total_rows = [r for r in display_rows if r.get('ID') == 'TOTAL']
            _numeric_cols = {
                'Duration', 'Open price (bp)', 'Volume (mm)', 'Z-Score', 'Close Price (bp)',
                'Target Volume (MM CNY)', 'DV01 (k CNY/bp)', 'Carry+Roll (3m,bp)',
                'Breakeven (3m,bp)', 'Stop (bp)', 'Target (bp)', 'MTM spd (bp)',
                'MtM Carry (MM CNY)', 'MtM Value (MM CNY)', 'Target Weight (%)', 'Weight (%)',
            }
            body_rows = _apply_sort(body_rows, sort_state, _numeric_cols)

            _ALL_COLS = [
                ('ID', 'left'), ('Leg 1', 'left'), ('Leg 2', 'left'),
                ('Style', 'left'), ('Direction', 'center'), ('Duration', 'right'),
                ('Open price (bp)', 'right'), ('Volume (mm)', 'right'), ('Open date', 'right'),
                ('Z-Score', 'right'), ('Close Price (bp)', 'right'), ('Progress', 'left'),
                ('Target Volume (MM CNY)', 'right'), ('DV01 (k CNY/bp)', 'right'),
                ('Carry+Roll (3m,bp)', 'right'), ('Breakeven (3m,bp)', 'right'),
                ('Stop (bp)', 'right'), ('Target (bp)', 'right'), ('MTM spd (bp)', 'right'),
                ('MtM Carry (MM CNY)', 'right'), ('MtM Value (MM CNY)', 'right'),
                ('Target Weight (%)', 'right'), ('Weight (%)', 'right'),
            ]
            _cols = [(c, a) for c, a in _ALL_COLS
                     if c not in ('Open date', 'Volume (mm)', 'Z-Score') or c in _visible_cols]
            _cols = [('__delete', 'center')] + _cols

            header_row = html.Tr([
                (html.Th('', style={'padding': '7px 6px', 'width': '24px'}) if c == '__delete'
                 else _sortable_header(c, c, 'alpha', sort_state, align=a))
                for c, a in _cols
            ], style={'background': THEME['table_header'], 'borderBottom': f"1px solid {THEME['accent']}"})

            def _editable_cell(row_idx: int, col: str, value: str, kind: str = 'text'):
                input_id = {'type': 'alpha-cell-input', 'row': row_idx, 'col': col}
                if kind == 'date':
                    return html.Td([
                        html.Button(
                            value or '—',
                            id={'type': 'alpha-date-trigger', 'row': row_idx},
                            n_clicks=0,
                            className='an-date-trigger-btn',
                            style={
                                'background': 'rgba(99,179,237,0.08)',
                                'border': f'1px solid {THEME["accent"]}', 'borderRadius': '3px',
                                'color': THEME['text_main'], 'fontSize': '13px', 'padding': '5px 8px',
                                'cursor': 'pointer', 'width': '100%', 'minWidth': '92px',
                                'whiteSpace': 'nowrap',
                            },
                        ),
                    ], style={'padding': '5px 10px', 'textAlign': 'right', 'minWidth': '92px'})
                return html.Td(
                    dcc.Input(
                        id=input_id, type='text', value=value, debounce=True,
                        style={
                            'background': 'rgba(99,179,237,0.08)', 'border': f'1px solid {THEME["accent"]}',
                            'borderRadius': '3px', 'color': THEME['text_main'], 'fontSize': '9px',
                            'padding': '3px 6px', 'width': '64px', 'textAlign': 'right',
                        },
                    ),
                    style={'padding': '5px 10px', 'textAlign': 'right'},
                )

            def _cell(row_idx: int, col: str, row: dict, align: str):
                val = row.get(col, '')
                base_style = {'padding': '5px 10px', 'textAlign': align, 'color': THEME['text_main']}
                if col == 'ID':
                    return html.Td(val, style={**base_style, 'fontWeight': '600', 'whiteSpace': 'nowrap'})
                if col in ('Leg 1', 'Leg 2'):
                    return html.Td(val, style={**base_style, 'color': THEME['text_sub'], 'fontSize': '9px'})
                if col == 'Style':
                    return html.Td(_style_badge(val) if val else '', style=base_style)
                if col == 'Direction':
                    return html.Td(_dir_badge(val) if val else '', style=base_style)
                if col == 'Open price (bp)':
                    return _editable_cell(row_idx, col, val, 'text')
                if col == 'Volume (mm)':
                    return _editable_cell(row_idx, col, val, 'text')
                if col == 'Open date':
                    return _editable_cell(row_idx, col, val, 'date')
                if col == 'Z-Score':
                    try:
                        z = float(val) if val not in ('', 'N/A') else None
                    except (TypeError, ValueError):
                        z = None
                    return html.Td(val, style={**base_style, **_zscore_cell_style(z)})
                if col in ('MTM spd (bp)', 'MtM Value (MM CNY)'):
                    try:
                        signed = float(str(val).replace(',', '')) if val else None
                    except (TypeError, ValueError):
                        signed = None
                    return html.Td(val, style={**base_style, **_signed_value_style(signed)})
                if col == 'Target (bp)':
                    return html.Td(val, style={**base_style, 'color': '#34d399'})
                if col == 'Stop (bp)':
                    return html.Td(val, style={**base_style, 'color': '#f87171'})
                if col == 'Progress':
                    try:
                        entry  = float(row.get('_entry_level', '') or '')
                        cur    = float(row.get('_current_level', '') or '')
                        target = float(row.get('_target_level', '') or '')
                        stop   = float(row.get('_stop_level', '') or '')
                    except (TypeError, ValueError):
                        return html.Td('', style=base_style)
                    direction = str(row.get('Direction', '')).strip().upper()
                    return html.Td(_price_progress_bar(entry, cur, target, stop, direction),
                                    style={**base_style, 'minWidth': '90px'})
                if col == '__delete':
                    return html.Td(
                        html.Button('×', id={'type': 'alpha-row-delete', 'row': row_idx}, n_clicks=0, style={
                            'background': 'none', 'border': 'none', 'color': THEME['text_sub'],
                            'cursor': 'pointer', 'fontSize': '14px', 'padding': '0 4px',
                        }),
                        style={'padding': '5px 6px', 'textAlign': 'center'},
                    )
                return html.Td(val, style=base_style)

            body_trs = []
            for i, row in enumerate(body_rows):
                tid = row.get('ID', '')
                sev = _alert_severity.get(tid)
                row_bg = _row_alert_bg.get(sev) if sev else (
                    THEME['bg_card'] if i % 2 == 1 else 'transparent')
                row_idx = _row_key(row, i)
                body_trs.append(html.Tr(
                    [_cell(row_idx, c, row, a) for c, a in _cols],
                    style={'background': row_bg, 'borderBottom': '1px solid rgba(255,255,255,0.04)'},
                ))
            for trow in total_rows:
                body_trs.append(html.Tr(
                    [html.Td(trow.get(c, '') if c != '__delete' else '', style={
                        'padding': '5px 10px', 'textAlign': a, 'fontWeight': 'bold',
                        'color': THEME['text_main'],
                    }) for c, a in _cols],
                    style={'background': THEME['table_header'], 'borderTop': f"1px solid {THEME['accent']}"},
                ))

            table = html.Div(
                html.Table([
                    html.Thead(header_row),
                    html.Tbody(body_trs),
                ], style={'width': '100%', 'borderCollapse': 'collapse', 'fontSize': '9px'}),
                style={'overflowX': 'auto'},
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

            _active_target = next((r for r in display_rows if _row_key(r, -1) == active_date_row), None) \
                if active_date_row is not None else None
            if _active_target is not None:
                _parsed_active = pd.to_datetime(_active_target.get('Open date', ''), errors='coerce')
                _picker_date = _parsed_active.date().isoformat() if pd.notna(_parsed_active) else None
                _picker_disabled = False
                _picker_label = f"Editing {_active_target.get('ID', '')}"
            else:
                _picker_date = None
                _picker_disabled = True
                _picker_label = 'Click an Open date cell to edit with the calendar.'

            content = html.Div([
                html.Div([
                    html.Span('Open date calendar:', style={'color': THEME['text_sub'], 'fontSize': '11px'}),
                    dcc.DatePickerSingle(
                        id='summary-alpha-open-date-picker',
                        date=_picker_date, display_format='YYYY-MM-DD', clearable=True,
                        disabled=_picker_disabled,
                        placeholder='Select an Open date cell',
                        style={'backgroundColor': THEME['bg_input']},
                    ),
                    html.Span(
                        id='summary-alpha-open-date-target',
                        children=_picker_label,
                        style={'color': THEME['text_sub'], 'fontSize': '11px', 'fontStyle': 'italic'},
                    ),
                ], style={'display': 'flex', 'alignItems': 'center', 'gap': '10px',
                          'marginBottom': '10px', 'flexWrap': 'wrap', 'position': 'relative', 'zIndex': '1001'}),
                *([_reminder_banner] if _reminder_banner else []),
                table,
            ], id='summary-alpha-table-wrapper')
            status = f"Alpha snapshot from {ts[:19]}" + (" — saved" if is_refresh else "")
            return content, status, display_rows

        except Exception as exc:
            return _no_data(f"Error loading Alpha snapshot: {exc}")

    # ── Tickets subtab: derive opening tickets from Beta/Alpha positions ───────
    # There is no order/fill pipeline in this engine — a "ticket" here is the
    # opening trade implied by a position's Open Date/Price/Volume fields.
    # FILLED  = open_date + volume both set
    # PENDING = volume set but open_date missing (sized, not yet booked)
    # OPEN    = neither set (candidate in the book, no trade yet) — excluded
    _TICKET_STATUS_STYLE = {
        'FILLED':  {'bg': 'rgba(52,211,153,0.12)', 'color': '#34d399'},
        'PENDING': {'bg': 'rgba(224,162,60,0.15)', 'color': THEME['warning']},
    }

    def _build_tickets() -> list[dict]:
        import os as _os
        tickets: list[dict] = []

        # ── Beta book: positions + user-entered open price/date/volume ────────
        if _os.path.exists(_BETA_BOOK_POSITIONS_PARQUET):
            try:
                bdf = pd.read_parquet(_BETA_BOOK_POSITIONS_PARQUET)
                user_data: dict = {}
                if os.path.exists(_BETA_BOOK_USER_PARQUET):
                    udf = pd.read_parquet(_BETA_BOOK_USER_PARQUET)
                    for _, r in udf.iterrows():
                        key = (str(r.get('asset_name', '')), str(r.get('instrument', '')))
                        user_data[key] = {
                            'open_price': str(r.get('open_price', '')).strip(),
                            'open_date':  str(r.get('open_date', '')).strip(),
                            'volume':     str(r.get('volume', '')).strip(),
                        }

                for _, row in bdf.iterrows():
                    if str(row.get('Asset Type', '')) == 'TOTAL':
                        continue
                    asset_name = str(row.get('Asset Name', ''))
                    instrument = str(row.get('Instrument', ''))
                    saved = user_data.get((asset_name, instrument), {})
                    volume_str = saved.get('volume', '')
                    open_date_str = saved.get('open_date', '')
                    if not volume_str:
                        continue  # no sized trade — nothing to ticket yet
                    try:
                        qty = float(volume_str)
                    except (TypeError, ValueError):
                        continue
                    status = 'FILLED' if open_date_str else 'PENDING'
                    try:
                        price = float(saved.get('open_price', '') or 0) or None
                    except (TypeError, ValueError):
                        price = None
                    tickets.append({
                        'id': f"BETA-{instrument}",
                        'date': open_date_str or '—',
                        'book': 'Beta',
                        'spread': instrument or asset_name,
                        'action': 'BUY',
                        'qty': qty,
                        'price': price,
                        'status': status,
                    })
            except Exception:
                pass

        # ── Alpha book: positions + open price/volume/date ─────────────────────
        if _os.path.exists(_ALPHA_POSITIONS_PARQUET):
            try:
                adf = pd.read_parquet(_ALPHA_POSITIONS_PARQUET)
                for _, row in adf.iterrows():
                    trade_id = str(row.get('ID', ''))
                    if trade_id in ('', 'TOTAL'):
                        continue
                    volume_str = str(row.get('volume_mm', '') or '').strip()
                    open_date_str = str(row.get('open_date', '') or '').strip()
                    if not volume_str:
                        continue
                    try:
                        qty = float(volume_str)
                    except (TypeError, ValueError):
                        continue
                    status = 'FILLED' if open_date_str else 'PENDING'
                    try:
                        price = float(row.get('open_price_bp', '') or 0) or None
                    except (TypeError, ValueError):
                        price = None
                    tickets.append({
                        'id': f"ALPHA-{trade_id}",
                        'date': open_date_str or '—',
                        'book': 'Alpha',
                        'spread': trade_id,
                        'action': str(row.get('direction', 'BUY')).upper() or 'BUY',
                        'qty': qty,
                        'price': price,
                        'status': status,
                    })
            except Exception:
                pass

        tickets.sort(key=lambda t: t['date'], reverse=True)
        return tickets

    def _tickets_filter_pills(active: str) -> list:
        def _pill_style(is_active: bool):
            style = {
                'padding': '5px 10px', 'fontSize': '10px', 'fontWeight': '600',
                'border': 'none', 'borderRadius': '3px', 'cursor': 'pointer',
                'fontFamily': 'var(--font-mono)', 'transition': 'all 100ms',
            }
            if is_active:
                style.update({'backgroundColor': THEME['accent'], 'color': '#ffffff'})
            else:
                style.update({'backgroundColor': 'transparent', 'color': THEME['text_sub']})
            return style
        return [
            html.Button(label, id=f'tickets-filter-{label}', n_clicks=0, style=_pill_style(active == label))
            for label in ('All', 'FILLED', 'PENDING')
        ]

    @app.callback(
        Output('tickets-filter-row', 'children'),
        Input('tickets-filter', 'data'),
    )
    def _render_tickets_filter_pills(active):
        return _tickets_filter_pills(active or 'All')

    @app.callback(
        Output('tickets-filter', 'data'),
        [Input('tickets-filter-All', 'n_clicks'),
         Input('tickets-filter-FILLED', 'n_clicks'),
         Input('tickets-filter-PENDING', 'n_clicks')],
        prevent_initial_call=True,
    )
    def _set_tickets_filter(_n_all, _n_filled, _n_pending):
        triggered = dash.ctx.triggered_id
        return {
            'tickets-filter-All': 'All',
            'tickets-filter-FILLED': 'FILLED',
            'tickets-filter-PENDING': 'PENDING',
        }.get(triggered, 'All')

    @app.callback(
        [Output('tickets-kpi-container', 'children'),
         Output('tickets-table-container', 'children'),
         Output('tickets-subtitle', 'children')],
        [Input('an-summary-subtabs', 'value'),
         Input('tickets-filter', 'data'),
         Input('summary-refresh-btn', 'n_clicks')],
        prevent_initial_call=False,
    )
    def update_tickets(tab_value, ticket_filter, _n_refresh):
        if tab_value != 'tickets':
            raise dash.exceptions.PreventUpdate

        all_tickets = _build_tickets()
        filled = [t for t in all_tickets if t['status'] == 'FILLED']
        pending = [t for t in all_tickets if t['status'] == 'PENDING']

        subtitle = f"{len(all_tickets)} opening tickets · derived from Beta + Alpha book positions"

        kpis = [
            ("Total Tickets", str(len(all_tickets)), THEME['text_main']),
            ("Filled", str(len(filled)), THEME['success']),
            ("Pending", str(len(pending)), THEME['warning']),
            ("Fill Rate", f"{(len(filled) / len(all_tickets) * 100):.0f}%" if all_tickets else "—", THEME['accent']),
        ]
        kpi_strip = html.Div([
            html.Div([
                html.Div(label, className='risk-kpi-label'),
                html.Div(value, className='risk-kpi-value', style={'color': color}),
            ], className='risk-kpi-card')
            for label, value, color in kpis
        ], className='risk-kpi-strip')

        ticket_filter = ticket_filter or 'All'
        rows = all_tickets if ticket_filter == 'All' else [t for t in all_tickets if t['status'] == ticket_filter]

        if not rows:
            table = html.Div(
                "No tickets yet — set Open Date and Volume on a Beta/Alpha position to create one.",
                style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'textAlign': 'center', 'padding': '30px'},
            )
            return kpi_strip, table, subtitle

        status_styles = [
            {'if': {'filter_query': f'{{Status}} = "{status}"', 'column_id': 'Status'},
             'backgroundColor': style['bg'], 'color': style['color'], 'fontWeight': 'bold'}
            for status, style in _TICKET_STATUS_STYLE.items()
        ]
        book_styles = [
            {'if': {'filter_query': '{Book} = "Beta"', 'column_id': 'Book'}, 'color': THEME['accent'], 'fontWeight': 'bold'},
            {'if': {'filter_query': '{Book} = "Alpha"', 'column_id': 'Book'}, 'color': THEME['warning'], 'fontWeight': 'bold'},
        ]
        action_styles = [
            {'if': {'filter_query': '{Action} = "BUY"', 'column_id': 'Action'}, 'color': THEME['success']},
            {'if': {'filter_query': '{Action} = "SELL"', 'column_id': 'Action'}, 'color': THEME['danger']},
        ]

        table_data = [{
            'Ticket ID': t['id'],
            'Open Date': t['date'],
            'Book': t['book'],
            'Spread / Instrument': t['spread'],
            'Action': t['action'],
            'Qty (MM)': f"{t['qty']:,.1f}",
            'Price': f"{t['price']:,.4f}" if t['price'] is not None else '—',
            'Status': t['status'],
        } for t in rows]

        table = dash_table.DataTable(
            data=table_data,
            columns=[{'name': c, 'id': c} for c in
                     ['Ticket ID', 'Open Date', 'Book', 'Spread / Instrument', 'Action', 'Qty (MM)', 'Price', 'Status']],
            style_cell={'textAlign': 'center', 'padding': '6px 10px', 'fontSize': '12px',
                        'backgroundColor': THEME['table_row_odd'], 'color': THEME['text_main'], 'border': 'none'},
            style_header={'backgroundColor': THEME['table_header'], 'color': THEME['text_main'],
                          'fontWeight': 'bold', 'border': 'none'},
            style_data_conditional=[
                {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']},
                *status_styles, *book_styles, *action_styles,
            ],
            style_table={'overflowX': 'auto'},
            sort_action='native',
            page_size=30,
        )
        return kpi_strip, table, subtitle

    # ── Alpha Book: header sort clicks ─────────────────────────────────────────
    @app.callback(
        Output('summary-alpha-sort', 'data'),
        Input({'type': 'alpha-sort-th', 'col': ALL}, 'n_clicks'),
        State('summary-alpha-sort', 'data'),
        prevent_initial_call=True,
    )
    def _sort_alpha_table(_n_clicks_list, sort_state):
        triggered = dash.ctx.triggered_id
        if not triggered or not any(_n_clicks_list):
            raise dash.exceptions.PreventUpdate
        col = triggered['col']
        sort_state = sort_state or {'col': None, 'dir': 'asc'}
        if sort_state.get('col') == col:
            return {'col': col, 'dir': 'desc' if sort_state.get('dir') == 'asc' else 'asc'}
        return {'col': col, 'dir': 'asc'}

    # ── Alpha Book: inline edits on Open price (bp) / Volume (mm) ─────────────
    @app.callback(
        Output('summary-refresh-status', 'children', allow_duplicate=True),
        Input({'type': 'alpha-cell-input', 'row': ALL, 'col': ALL}, 'value'),
        State({'type': 'alpha-cell-input', 'row': ALL, 'col': ALL}, 'id'),
        State('summary-alpha-rows-store', 'data'),
        prevent_initial_call=True,
    )
    def _edit_alpha_cell(values, ids, rows):
        triggered = dash.ctx.triggered_id
        if not triggered or not rows:
            raise dash.exceptions.PreventUpdate
        row_idx, col = triggered['row'], triggered['col']
        updated_rows = [dict(r) for r in rows]
        target = next((r for r in updated_rows if _row_key(r, -1) == row_idx), None)
        if target is None:
            raise dash.exceptions.PreventUpdate
        new_value = next((v for v, i in zip(values, ids) if i['row'] == row_idx and i['col'] == col), None)
        target[col] = new_value or ''
        target.update(_refresh_alpha_display_row(target))
        try:
            _persist_alpha_summary_rows(updated_rows)
            return f"Edits saved at {datetime.now().strftime('%H:%M:%S')}"
        except Exception as exc:
            return f"Save failed: {exc}"

    # ── Alpha Book: delete a row from the positions table ─────────────────────
    @app.callback(
        [
            Output('summary-refresh-status', 'children', allow_duplicate=True),
            Output('summary-refresh-btn', 'n_clicks', allow_duplicate=True),
        ],
        Input({'type': 'alpha-row-delete', 'row': ALL}, 'n_clicks'),
        State('summary-alpha-rows-store', 'data'),
        State('summary-refresh-btn', 'n_clicks'),
        prevent_initial_call=True,
    )
    def _delete_alpha_row(_n_clicks_list, rows, refresh_clicks):
        triggered = dash.ctx.triggered_id
        if not triggered or not any(_n_clicks_list) or not rows:
            raise dash.exceptions.PreventUpdate
        row_idx = triggered['row']
        updated_rows = [r for r in rows if _row_key(r, -1) != row_idx]
        try:
            _persist_alpha_summary_rows(updated_rows)
            return (f"Position removed at {datetime.now().strftime('%H:%M:%S')}",
                    (refresh_clicks or 0) + 1)
        except Exception as exc:
            return f"Delete failed: {exc}", dash.no_update

    # ── Alpha Book: Open date — click cell to open calendar, pick to apply ────
    # The highlight on the clicked date button is pure CSS (className toggle,
    # see assets/an_date_trigger_highlight.js), so this callback only updates
    # the store that drives the calendar picker — it does not re-render the table.
    @app.callback(
        Output('summary-alpha-active-date-row', 'data'),
        Input({'type': 'alpha-date-trigger', 'row': ALL}, 'n_clicks'),
        prevent_initial_call=True,
    )
    def _activate_alpha_date_row(_n_clicks_list):
        triggered = dash.ctx.triggered_id
        if not triggered or not any(_n_clicks_list):
            raise dash.exceptions.PreventUpdate
        return triggered['row']

    @app.callback(
        [
            Output('summary-alpha-open-date-picker', 'date'),
            Output('summary-alpha-open-date-picker', 'disabled'),
            Output('summary-alpha-open-date-target', 'children'),
        ],
        Input('summary-alpha-active-date-row', 'data'),
        State('summary-alpha-rows-store', 'data'),
        prevent_initial_call=False,
    )
    def _sync_alpha_open_date_picker(active_row, rows):
        if active_row is None or not rows:
            return None, True, 'Click an Open date cell to edit with the calendar.'
        target = next((r for r in rows if _row_key(r, -1) == active_row), None)
        if target is None:
            return None, True, 'Click an Open date cell to edit with the calendar.'
        parsed = pd.to_datetime(target.get('Open date', ''), errors='coerce')
        label = f"Editing {target.get('ID', '')}"
        return (
            parsed.date().isoformat() if pd.notna(parsed) else None,
            False,
            label,
        )

    @app.callback(
        [
            Output('summary-refresh-status', 'children', allow_duplicate=True),
            Output('summary-alpha-active-date-row', 'data', allow_duplicate=True),
            Output('summary-alpha-rows-store', 'data', allow_duplicate=True),
            Output('summary-refresh-btn', 'n_clicks', allow_duplicate=True),
        ],
        Input('summary-alpha-open-date-picker', 'date'),
        State('summary-alpha-active-date-row', 'data'),
        State('summary-alpha-rows-store', 'data'),
        State('summary-refresh-btn', 'n_clicks'),
        prevent_initial_call=True,
    )
    def _apply_alpha_open_date(date_value, active_row, rows, refresh_clicks):
        if active_row is None or not rows:
            raise dash.exceptions.PreventUpdate

        updated_rows = [dict(r) for r in rows]
        target = next((r for r in updated_rows if _row_key(r, -1) == active_row), None)
        if target is None:
            raise dash.exceptions.PreventUpdate

        target['Open date'] = date_value or ''
        target.update(_refresh_alpha_display_row(target))

        _persist_alpha_summary_rows(updated_rows)
        return (
            f"Open date saved at {datetime.now().strftime('%H:%M:%S')}",
            active_row,
            updated_rows,
            (refresh_clicks or 0) + 1,
        )

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

    # ── Beta Book: header sort clicks ──────────────────────────────────────────
    @app.callback(
        Output('summary-beta-sort', 'data'),
        Input({'type': 'beta-sort-th', 'col': ALL}, 'n_clicks'),
        State('summary-beta-sort', 'data'),
        prevent_initial_call=True,
    )
    def _sort_beta_table(_n_clicks_list, sort_state):
        triggered = dash.ctx.triggered_id
        if not triggered or not any(_n_clicks_list):
            raise dash.exceptions.PreventUpdate
        col = triggered['col']
        sort_state = sort_state or {'col': None, 'dir': 'asc'}
        if sort_state.get('col') == col:
            return {'col': col, 'dir': 'desc' if sort_state.get('dir') == 'asc' else 'asc'}
        return {'col': col, 'dir': 'asc'}

    # ── Beta Book: inline edits on Open Price / Volume (MM) ───────────────────
    @app.callback(
        Output('summary-refresh-status', 'children', allow_duplicate=True),
        Input({'type': 'beta-cell-input', 'row': ALL, 'col': ALL}, 'value'),
        State({'type': 'beta-cell-input', 'row': ALL, 'col': ALL}, 'id'),
        State('summary-beta-rows-store', 'data'),
        prevent_initial_call=True,
    )
    def _edit_beta_cell(values, ids, rows):
        triggered = dash.ctx.triggered_id
        if not triggered or not rows:
            raise dash.exceptions.PreventUpdate
        row_idx, col = triggered['row'], triggered['col']
        updated_rows = [dict(r) for r in rows]
        target = next((r for r in updated_rows if _row_key(r, -1) == row_idx), None)
        if target is None:
            raise dash.exceptions.PreventUpdate
        new_value = next((v for v, i in zip(values, ids) if i['row'] == row_idx and i['col'] == col), None)
        target[col] = new_value or ''
        try:
            _persist_beta_user_rows(updated_rows)
            return f"Beta edits saved at {datetime.now().strftime('%H:%M:%S')}"
        except Exception as exc:
            return f"Save failed: {exc}"

    # ── Beta Book: Open Date — click cell to open calendar, pick to apply ─────
    @app.callback(
        Output('summary-beta-active-date-row', 'data'),
        Input({'type': 'beta-date-trigger', 'row': ALL}, 'n_clicks'),
        prevent_initial_call=True,
    )
    def _activate_beta_date_row(_n_clicks_list):
        triggered = dash.ctx.triggered_id
        if not triggered or not any(_n_clicks_list):
            raise dash.exceptions.PreventUpdate
        return triggered['row']

    @app.callback(
        [
            Output('summary-beta-open-date-picker', 'date'),
            Output('summary-beta-open-date-picker', 'disabled'),
            Output('summary-beta-open-date-target', 'children'),
        ],
        Input('summary-beta-active-date-row', 'data'),
        State('summary-beta-rows-store', 'data'),
        prevent_initial_call=False,
    )
    def _sync_beta_open_date_picker(active_row, rows):
        if active_row is None or not rows:
            return None, True, 'Click an Open Date cell to edit with the calendar.'
        target = next((r for r in rows if _row_key(r, -1) == active_row), None)
        if target is None:
            return None, True, 'Click an Open Date cell to edit with the calendar.'
        parsed = pd.to_datetime(target.get('Open Date', ''), errors='coerce')
        label = f"Editing {target.get('Asset Name', '')}"
        return (
            parsed.date().isoformat() if pd.notna(parsed) else None,
            False,
            label,
        )

    @app.callback(
        [
            Output('summary-refresh-status', 'children', allow_duplicate=True),
            Output('summary-beta-active-date-row', 'data', allow_duplicate=True),
            Output('summary-beta-rows-store', 'data', allow_duplicate=True),
            Output('summary-refresh-btn', 'n_clicks', allow_duplicate=True),
        ],
        Input('summary-beta-open-date-picker', 'date'),
        State('summary-beta-active-date-row', 'data'),
        State('summary-beta-rows-store', 'data'),
        State('summary-refresh-btn', 'n_clicks'),
        prevent_initial_call=True,
    )
    def _apply_beta_open_date(date_value, active_row, rows, refresh_clicks):
        if active_row is None or not rows:
            raise dash.exceptions.PreventUpdate
        updated_rows = [dict(r) for r in rows]
        target = next((r for r in updated_rows if _row_key(r, -1) == active_row), None)
        if target is None:
            raise dash.exceptions.PreventUpdate
        target['Open Date'] = date_value or ''
        _persist_beta_user_rows(updated_rows)
        return (
            f"Open date saved at {datetime.now().strftime('%H:%M:%S')}",
            active_row,
            updated_rows,
            (refresh_clicks or 0) + 1,
        )

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
        """Parse 'Repo7d-1y2y' → ('FR007S2Y.IR', 'FR007S1Y.IR') or
        'Shi3M-1y4y' → ('SHI3MS4Y.IR', 'SHI3MS1Y.IR').

        Leg1 is the longer (second) tenor, leg2 the shorter (first) tenor —
        matches the +1/-1 quote weights in irs._irs_quote_spread_weights.
        """
        import re
        _TENOR_MAP = {'3m': '3M', '6m': '6M', '9m': '9M', '1y': '1Y',
                      '2y': '2Y', '3y': '3Y', '5y': '5Y', '10y': '10Y'}

        for prefix, ir_prefix in [('repo7d', 'FR007S'), ('shi3m', 'SHI3MS')]:
            m = re.match(rf'{prefix}-(.+)', spread_id.lower())
            if m:
                remainder = m.group(1)
                pairs = re.findall(r'(\d+[a-z])', remainder)
                if len(pairs) >= 2:
                    t1 = _TENOR_MAP.get(pairs[0], pairs[0].upper())
                    t2 = _TENOR_MAP.get(pairs[1], pairs[1].upper())
                    return (f'{ir_prefix}{t2}.IR', f'{ir_prefix}{t1}.IR')

        return ('', '')

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

        # Duration → nearest on-the-run bond (same selection as the Market
        # Monitor "ON-THE-RUN BONDS" card: highest-turnover bond per tenor band).
        def _nearest_otr(dur: float, otr: dict) -> str:
            return otr.get(_t_label(dur), '')

        # Duration → FR007 IRS tenor code (for Bond-Swap trades)
        def _duration_to_fr007_tenor(dur: float) -> str:
            if dur <= 1.5:
                return 'FR007S1Y.IR'
            elif dur <= 2.0:
                return 'FR007S2Y.IR'
            elif dur <= 3.0:
                return 'FR007S3Y.IR'
            elif dur <= 4.0:
                return 'FR007S4Y.IR'
            else:
                return 'FR007S5Y.IR'

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
                    return (otr_cgb.get(_t_label(float(m.group(2))), ''),
                            otr_cgb.get(_t_label(float(m.group(1))), ''))
            elif upper.startswith('CDB-'):
                m = _re.search(r'(\d+)S(\d+)S', upper)
                if m:
                    return (otr_cdb.get(_t_label(float(m.group(2))), ''),
                            otr_cdb.get(_t_label(float(m.group(1))), ''))
            return ('', '')

        elif stype == 'TBondCurve':
            return (tid, _nearest_otr(duration, otr_cgb))

        elif stype == 'CBondCurve':
            return (tid, _nearest_otr(duration, otr_cdb))

        elif stype == 'TBondSwap':
            return (tid, _duration_to_fr007_tenor(duration))

        elif stype == 'CBondSwap':
            return (tid, _duration_to_fr007_tenor(duration))

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
        [Output('risk-kpi-container', 'children'),
         Output('risk-netpos-container', 'children'),
         Output('risk-dv01-container', 'children'),
         Output('risk-factor-container', 'children'),
         Output('risk-inventory-container', 'children'),
         Output('risk-refresh-status', 'children')],
        [Input('an-summary-subtabs', 'value'),
         Input('risk-refresh-btn', 'n_clicks'),
         Input('allocation-results-store', 'data'),
         Input('risk-inventory-expanded', 'data')],
        prevent_initial_call=False,
    )
    def update_risk_tables(tab_value, _n_clicks, allocation_results_data, inventory_expanded):
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

        def _add_net(code: str, cap_mm: float, source: str):
            if not code or abs(cap_mm) < 1e-9:
                return
            e = net_pos.setdefault(code, {'Beta': 0.0, 'Alpha': 0.0})
            e[source] = round(e[source] + cap_mm, 4)

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
                    _add_net(instrument, cap_mm, 'Beta')  # Beta Book positions are always long

                    # Key Term: rate-tenor Beta positions are bond duration; non-rate sectors → Other
                    tenor = _SECTOR_TO_TENOR.get(sector)
                    if tenor and dv01_mm != 0.0:
                        col = 'Bonds' if sector in _SECTOR_TO_TENOR else 'Other'
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

                    # Net capital per leg: BUY → long leg1 / short leg2 (and vice
                    # versa for SELL), at full notional on each side.
                    _abs_notional = abs(notional)
                    _add_net(leg1, _abs_notional * dir_sign, 'Alpha')
                    _add_net(leg2, -_abs_notional * dir_sign, 'Alpha')

                    alpha_rows.append({
                        'Book': 'Alpha', 'Name': tid,
                        'Leg1': leg1, 'Leg2': leg2,
                        'Capital (MM)': f"{notional:.1f}",
                        'DV01 (MM/bp)': f"{dv01_mm * dir_sign:.4f}",
                        'Direction': direction,
                    })

                    # Key Term ladder: IRS spreads (any Repo7d-XyYy ID) get split
                    # across both tenor legs; everything else goes to a single bucket.
                    col = _ALPHA_COL.get(stype, 'Other')
                    if dv01_mm != 0.0:
                        _l1, _l2 = _parse_repo_spread_legs(tid)
                        _m1 = re.search(r'FR007S([^.]+)\.IR', _l1)
                        _m2 = re.search(r'FR007S([^.]+)\.IR', _l2)
                        if _m1 and _m2:
                            # Two-leg IRS: +DV01 at long-tenor leg, −DV01 at short-tenor leg
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

        # ── Net position by instrument chart (Beta long + Alpha legs combined) ─
        netpos_fig = build_net_position_fig(net_pos)
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

        # ── DV01 Duration Ladder chart (Beta + Alpha combined, from kt_grid) ───
        dv01_fig = build_dv01_ladder_fig(kt_grid, _TENOR_ORDER)
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

