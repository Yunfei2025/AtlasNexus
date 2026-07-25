# -*- coding: utf-8 -*-
"""Summary > Books subtab callbacks: Beta and Alpha allocation tables.

Covers the Beta/Alpha book toggle, column-visibility pills, the Beta and
Alpha table renderers themselves, and their inline edit / delete / open-date
callbacks.
"""

from __future__ import annotations

import pathlib
from datetime import datetime

import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State, ALL
import pandas as pd

from settings.paths import DIR_INPUT
from ..data import THEME
from ...alpha.data import load_spread_data as _load_alpha_spread_data
from ._common import (
    _SUMMARY_BETA_PARQUET,
    _SUMMARY_ALPHA_PARQUET,
    _SUMMARY_BETA_DISPLAY_PARQUET,
    _SUMMARY_ALPHA_DISPLAY_PARQUET,
    _BETA_BOOK_POSITIONS_PARQUET,
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
from .risk_helpers import (
    _row_key,
    _coerce_float,
    _refresh_alpha_display_row,
    _persist_alpha_summary_rows,
    _beta_user_row_key,
    _load_beta_user_overrides,
    _persist_beta_user_rows,
    _load_leg_data,
    _resolve_legs,
    _leg_volume_ratio,
)


def register_risk_books_callbacks(app):
    """Register Summary > Books subtab callbacks (Beta + Alpha tables)."""

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
        names = {'open_date': 'Open Date', 'volume': 'Volume'}
        pills = []
        for k in ('open_date', 'volume'):
            style = _col_pill_style(bool(col_vis.get(k)))
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
         Input('summary-col-pill-volume', 'n_clicks')],
        State('summary-col-visibility', 'data'),
        prevent_initial_call=True,
    )
    def _toggle_col_visibility(_od_clicks, _vol_clicks, col_vis):
        col_vis = dict(col_vis or {})
        triggered = dash.ctx.triggered_id
        key = {
            'summary-col-pill-open_date': 'open_date',
            'summary-col-pill-volume': 'volume',
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
         Input('allocation-results-store', 'data'),
         Input('summary-col-visibility', 'data'),
         Input('summary-beta-sort', 'data')],
        State('summary-beta-active-date-row', 'data'),
        prevent_initial_call=False,
    )
    def update_summary_book_table(_n_clicks, allocation_results_data, col_vis, sort_state, active_date_row):
        """Render Beta Book allocation table."""
        col_vis = col_vis or {}
        sort_state = sort_state or {'col': None, 'dir': 'asc'}
        import os as _os

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

        def _fmt_file_ts(path: str) -> str:
            try:
                return datetime.fromtimestamp(_os.path.getmtime(path)).isoformat()
            except Exception:
                return 'unknown'

        def _load_persisted_beta_snapshot() -> tuple[list[dict], str, str]:
            """Load the Beta allocation snapshot — always from disk.

            The Summary > Books subtab is file-backed: Run Analysis and the
            Refresh button both write to these files, and every render here
            reads back from them (never from the in-session dcc.Store), so a
            fresh page load always shows the last saved state.

            Priority:
            1) summary_beta_display.parquet (render-ready snapshot)
            2) summary_beta_portfolio.parquet (canonical snapshot source)
            3) beta_book_positions.parquet (legacy/UI table export)
            """
            if _os.path.exists(_SUMMARY_BETA_DISPLAY_PARQUET):
                try:
                    bdf = pd.read_parquet(_SUMMARY_BETA_DISPLAY_PARQUET)
                    if not bdf.empty:
                        ts = 'unknown'
                        if '_timestamp' in bdf.columns and bdf['_timestamp'].notna().any():
                            ts = str(bdf['_timestamp'].dropna().astype(str).iloc[-1])
                        else:
                            ts = _fmt_file_ts(_SUMMARY_BETA_DISPLAY_PARQUET)
                        return bdf.to_dict('records'), ts, 'saved beta display snapshot'
                except Exception:
                    pass

            if _os.path.exists(_SUMMARY_BETA_PARQUET):
                try:
                    bdf = pd.read_parquet(_SUMMARY_BETA_PARQUET)
                    if not bdf.empty:
                        ts = 'unknown'
                        if '_timestamp' in bdf.columns and bdf['_timestamp'].notna().any():
                            ts = str(bdf['_timestamp'].dropna().astype(str).iloc[-1])
                        else:
                            ts = _fmt_file_ts(_SUMMARY_BETA_PARQUET)
                        return bdf.to_dict('records'), ts, 'saved beta snapshot'
                except Exception:
                    pass

            if _os.path.exists(_BETA_BOOK_POSITIONS_PARQUET):
                try:
                    bdf = pd.read_parquet(_BETA_BOOK_POSITIONS_PARQUET)
                    if not bdf.empty:
                        # Legacy fallback stores capital in MM CNY under column
                        # name "Capital (CNY)"; normalize back to CNY here.
                        if 'Capital (CNY)' in bdf.columns:
                            _cap = pd.to_numeric(
                                bdf['Capital (CNY)'].astype(str).str.replace(',', ''),
                                errors='coerce',
                            )
                            bdf['Capital (CNY)'] = _cap * 1_000_000.0
                        return bdf.to_dict('records'), _fmt_file_ts(_BETA_BOOK_POSITIONS_PARQUET), 'saved beta positions'
                except Exception:
                    pass

            return [], 'unknown', ''

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

        try:
            # Source of truth is always the file-backed snapshot — reading the
            # in-session `allocation-results-store` here would mask file
            # updates (e.g. from another session) whenever this callback fires
            # only for reactivity (its Input still triggers this re-render
            # immediately after Run Analysis writes the file).
            _records, ts, source_label = _load_persisted_beta_snapshot()

            if not _records:
                return _no_data(
                    "No Beta allocation results found. Run analysis in Beta Portfolio once to generate saved snapshot files."
                )
            df = pd.DataFrame(_records)

            if df.empty:
                return _no_data("Beta snapshot is empty.")

            user_data, deleted_keys = _load_beta_user_overrides()

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
                if key in deleted_keys:
                    continue
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
            _cols = [('__delete', 'center')] + _cols

            header_row = html.Tr([
                (html.Th('', style={'padding': '7px 6px', 'width': '24px'}) if c == '__delete'
                 else _sortable_header(c, c, 'beta', sort_state, align=a))
                for c, a in _cols
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
                if col == '__delete':
                    return html.Td(
                        html.Button('×', id={'type': 'beta-row-delete', 'row': row_idx}, n_clicks=0, style={
                            'background': 'none', 'border': 'none', 'color': THEME['text_sub'],
                            'cursor': 'pointer', 'fontSize': '14px', 'padding': '0 4px',
                        }),
                        style={'padding': '5px 6px', 'textAlign': 'center'},
                    )
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
            status = f"Beta snapshot from {ts[:19]} ({source_label})"
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
        col_vis = col_vis or {}

        def _fmt_file_ts(path: str) -> str:
            try:
                return datetime.fromtimestamp(_os.path.getmtime(path)).isoformat()
            except Exception:
                return 'unknown'

        def _load_persisted_alpha_display() -> tuple[list[dict], str, str]:
            """Load saved Alpha display snapshot rows, excluding helper columns.

            Priority:
            1) summary_alpha_display.parquet (render-ready snapshot)
            2) none -> caller falls back to canonical alpha snapshot rebuild
            """
            if _os.path.exists(_SUMMARY_ALPHA_DISPLAY_PARQUET):
                try:
                    adf = pd.read_parquet(_SUMMARY_ALPHA_DISPLAY_PARQUET)
                    if not adf.empty:
                        ts = 'unknown'
                        if '_timestamp' in adf.columns and adf['_timestamp'].notna().any():
                            ts = str(adf['_timestamp'].dropna().astype(str).iloc[-1])
                        else:
                            ts = _fmt_file_ts(_SUMMARY_ALPHA_DISPLAY_PARQUET)
                        records = adf.to_dict('records')
                        records = [{k: v for k, v in r.items() if not str(k).startswith('_')} for r in records]
                        return records, ts, 'saved alpha display snapshot'
                except Exception:
                    pass
            return [], 'unknown', ''

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

        _alpha_spread_cache: dict[str, pd.DataFrame | None] = {}
        _irs_close_yield_df: pd.DataFrame | None = None

        def _resolve_alpha_metric(
            spread_type: str,
            trade_id: str,
            metric: str,
            fallback: float | None = None,
            *,
            scale_to_bp: bool = False,
        ) -> float | None:
            if not spread_type or not trade_id:
                return fallback
            if spread_type not in _alpha_spread_cache:
                try:
                    _alpha_spread_cache[spread_type] = _load_alpha_spread_data(spread_type)
                except Exception:
                    _alpha_spread_cache[spread_type] = None
            df = _alpha_spread_cache.get(spread_type)
            if df is None or trade_id not in df.index:
                return fallback
            try:
                if metric not in df.columns:
                    return fallback
                raw_value = df.loc[trade_id, metric]
                if raw_value is None or pd.isna(raw_value):
                    return fallback
                value = float(raw_value)
                if scale_to_bp and spread_type in {
                    'TBondCurve', 'CBondCurve', 'SwapSpread', 'TenorSpread', 'TermBasis'
                }:
                    value *= 100.0
                return round(value, 4)
            except (TypeError, ValueError, KeyError):
                return fallback

        def _resolve_alpha_close_price_bp(
            spread_type: str,
            trade_id: str,
            leg1: str,
            leg2: str,
            fallback: float | None,
        ) -> float | None:
            nonlocal _irs_close_yield_df

            # BondCurve close price should be the live leg1-leg2 close yield spread in bp.
            if spread_type in {'TBondCurve', 'CBondCurve'} and leg1 and leg2:
                if spread_type not in _alpha_spread_cache:
                    try:
                        _alpha_spread_cache[spread_type] = _load_alpha_spread_data(spread_type)
                    except Exception:
                        _alpha_spread_cache[spread_type] = None
                _df = _alpha_spread_cache.get(spread_type)
                if isinstance(_df, pd.DataFrame) and 'CloseYield' in _df.columns and leg1 in _df.index and leg2 in _df.index:
                    try:
                        y1 = float(_df.loc[leg1, 'CloseYield'])
                        y2 = float(_df.loc[leg2, 'CloseYield'])
                        return round((y1 - y2) * 100.0, 4)
                    except (TypeError, ValueError, KeyError):
                        pass

            # Repo swap spreads should use latest daily IRS leg close yields when available.
            if spread_type == 'SwapSpread' and leg1.endswith('.IR') and leg2.endswith('.IR'):
                if _irs_close_yield_df is None:
                    try:
                        _irs_px = pd.read_pickle(str(DIR_INPUT / 'IRS-pxspds.pkl'))
                        _cy = _irs_px.get('CloseYield') if isinstance(_irs_px, dict) else None
                        _irs_close_yield_df = _cy if isinstance(_cy, pd.DataFrame) else pd.DataFrame()
                    except Exception:
                        _irs_close_yield_df = pd.DataFrame()
                if not _irs_close_yield_df.empty and leg1 in _irs_close_yield_df.columns and leg2 in _irs_close_yield_df.columns:
                    try:
                        y1 = float(_irs_close_yield_df[leg1].dropna().iloc[-1])
                        y2 = float(_irs_close_yield_df[leg2].dropna().iloc[-1])
                        return round((y1 - y2) * 100.0, 4)
                    except (TypeError, ValueError, IndexError):
                        pass

            return fallback

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

        _alpha_duration_snap_cache: dict[str, pd.DataFrame | None] = {}

        try:
            _saved_rows, ts_saved, source_saved = _load_persisted_alpha_display()
            if _saved_rows:
                display_rows = [dict(r) for r in _saved_rows]
                ts = ts_saved
                source_label = source_saved
            else:
                if not _os.path.exists(_SUMMARY_ALPHA_PARQUET):
                    return _no_data(
                        "No Alpha snapshot found. Click RUN OPTIMIZATION in the Alpha Book -> Portfolio tab first."
                    )
                df  = pd.read_parquet(_SUMMARY_ALPHA_PARQUET)
                ts  = df['_timestamp'].iloc[0] if '_timestamp' in df.columns else "unknown"
                source_label = 'saved alpha snapshot'
                pos = _load_positions()

            def _fmt1(v):
                try:
                    f = float(v)
                    return f"{f:.1f}" if pd.notna(f) else ''
                except (TypeError, ValueError):
                    return ''

            if not _saved_rows:
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
                    zscore_val = _resolve_alpha_metric(spread_type, trade_id, 'Zscore', fallback=_coerce_float(row.get('Zscore')))
                    carry_roll_val = _resolve_alpha_metric(spread_type, trade_id, 'carry_roll', fallback=_coerce_float(row.get('carry_roll')))
                    breakeven_val = _resolve_alpha_metric(spread_type, trade_id, 'breakeven_3m', fallback=_coerce_float(row.get('breakeven_3m')))
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
                    leg_ratio_val = _leg_volume_ratio(leg1, leg2, spread_type, trade_id, duration, _alpha_duration_snap_cache)
                    leg_ratio = f"{leg_ratio_val:.2f}" if leg_ratio_val is not None else ''
                    leg2_target_volume = (
                        round(notional * leg_ratio_val / 10.0) * 10.0 if leg_ratio_val is not None else None
                    )

                    cp_fallback_bp = _resolve_alpha_metric(
                        spread_type, trade_id, 'spread',
                        fallback=round(float(spread_val), 4) if pd.notna(spread_val) else None,
                        scale_to_bp=True,
                    )
                    cp_bp = _resolve_alpha_close_price_bp(
                        spread_type,
                        trade_id,
                        leg1,
                        leg2,
                        cp_fallback_bp,
                    )

                    # Carry+Roll is shown as a 3m value in the table.
                    # Use the live spread-based annual proxy when available and convert annual -> quarterly.
                    # This keeps borrow-cost drag out of the displayed carry for bond shorts.
                    carry_roll_3m_val = None
                    base_annual_bp = cp_bp if cp_bp is not None else carry_roll_val
                    if base_annual_bp is not None:
                        carry_roll_3m_val = base_annual_bp / 4.0

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
                        'Ratio (V2/V1)':          leg_ratio,
                        'Target Volume Leg2 (MM CNY)': f"{leg2_target_volume:,.1f}" if leg2_target_volume is not None else '',
                        'Spread Type':            spread_type,
                        'Style':                  row.get('style', ''),
                        'Direction':              row.get('direction', ''),
                        'Duration':               f"{duration:.2f}" if duration else 'N/A',
                        'Open price (bp)':        open_price_str,
                        'Volume (mm)':            volume_str,
                        'Open date':              open_date_str,
                        'Z-Score':                f"{zscore_val:.2f}" if zscore_val is not None else '',
                        'Close Price (bp)':       f"{cp_bp:.4f}" if cp_bp is not None else 'N/A',
                        'Progress':               '',
                        'Target Volume (MM CNY)': f"{notional:,.1f}",
                        'DV01 (k CNY/bp)':        f"{dv01_k:.1f}",
                        'Carry+Roll (3m,bp)':     _fmt1(-carry_roll_3m_val if str(row.get('direction', '')).strip().upper() == 'SELL' else carry_roll_3m_val),
                        'Breakeven (3m,bp)':      _fmt1(breakeven_val),
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
                'Target Volume (MM CNY)', 'Target Volume Leg2 (MM CNY)', 'DV01 (k CNY/bp)', 'Carry+Roll (3m,bp)',
                'Breakeven (3m,bp)', 'Stop (bp)', 'Target (bp)', 'MTM spd (bp)',
                'MtM Carry (MM CNY)', 'MtM Value (MM CNY)', 'Target Weight (%)', 'Weight (%)',
            }
            body_rows = _apply_sort(body_rows, sort_state, _numeric_cols)

            _ALL_COLS = [
                ('ID', 'left'), ('Leg 1', 'left'), ('Leg 2', 'left'), ('Ratio (V2/V1)', 'right'),
                ('Style', 'left'), ('Direction', 'center'), ('Duration', 'right'),
                ('Open price (bp)', 'right'), ('Volume (mm)', 'right'), ('Open date', 'right'),
                ('Z-Score', 'right'), ('Close Price (bp)', 'right'), ('Progress', 'left'),
                ('Target Volume (MM CNY)', 'right'), ('Target Volume Leg2 (MM CNY)', 'right'),
                ('DV01 (k CNY/bp)', 'right'),
                ('Carry+Roll (3m,bp)', 'right'), ('Breakeven (3m,bp)', 'right'),
                ('Stop (bp)', 'right'), ('Target (bp)', 'right'), ('MTM spd (bp)', 'right'),
                ('MtM Carry (MM CNY)', 'right'), ('MtM Value (MM CNY)', 'right'),
                ('Target Weight (%)', 'right'), ('Weight (%)', 'right'),
            ]
            _cols = [(c, a) for c, a in _ALL_COLS
                     if c not in ('Open date', 'Volume (mm)') or c in _visible_cols]
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
            status = f"Alpha snapshot from {ts[:19]} ({source_label})"
            return content, status, display_rows

        except Exception as exc:
            return _no_data(f"Error loading Alpha snapshot: {exc}")

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

    # ── Beta Book: delete a row from the positions table ──────────────────────
    @app.callback(
        [
            Output('summary-refresh-status', 'children', allow_duplicate=True),
            Output('summary-refresh-btn', 'n_clicks', allow_duplicate=True),
        ],
        Input({'type': 'beta-row-delete', 'row': ALL}, 'n_clicks'),
        State('summary-beta-rows-store', 'data'),
        State('summary-refresh-btn', 'n_clicks'),
        prevent_initial_call=True,
    )
    def _delete_beta_row(_n_clicks_list, rows, refresh_clicks):
        triggered = dash.ctx.triggered_id
        if not triggered or not any(_n_clicks_list) or not rows:
            raise dash.exceptions.PreventUpdate
        row_idx = triggered['row']
        target = next((r for r in rows if _row_key(r, -1) == row_idx), None)
        if target is None or str(target.get('Asset Type', '')) in ('', 'TOTAL'):
            raise dash.exceptions.PreventUpdate

        updated_rows = [r for r in rows if _row_key(r, -1) != row_idx]
        _, deleted_keys = _load_beta_user_overrides()
        deleted_keys.add(_beta_user_row_key(target))
        try:
            _persist_beta_user_rows(updated_rows, deleted_keys=deleted_keys)
            return (f"Position removed at {datetime.now().strftime('%H:%M:%S')}",
                    (refresh_clicks or 0) + 1)
        except Exception as exc:
            return f"Delete failed: {exc}", dash.no_update

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

    # ── Summary Refresh: force-persist both Book snapshot tables ─────────────
    @app.callback(
        Output('summary-refresh-status', 'children', allow_duplicate=True),
        Input('summary-refresh-btn', 'n_clicks'),
        State('summary-beta-rows-store', 'data'),
        State('summary-alpha-rows-store', 'data'),
        prevent_initial_call=True,
    )
    def _persist_books_snapshots_on_refresh(_n_clicks, beta_rows, alpha_rows):
        if not _n_clicks:
            raise dash.exceptions.PreventUpdate

        def _write_rows(rows, out_path: str, total_key: str, total_value: str) -> bool:
            if not isinstance(rows, list) or not rows:
                return False
            clean_rows = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if str(row.get(total_key, '')) == total_value:
                    continue
                clean_rows.append({k: v for k, v in row.items() if not str(k).startswith('_')})
            if not clean_rows:
                return False
            out_df = pd.DataFrame(clean_rows)
            out_df['_timestamp'] = datetime.now().isoformat()
            pathlib.Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            out_df.to_parquet(out_path, index=False)
            return True

        saved = []
        try:
            if _write_rows(beta_rows, _SUMMARY_BETA_DISPLAY_PARQUET, 'Asset Type', 'TOTAL'):
                saved.append('beta')
        except Exception as exc:
            print(f"Warning: Could not persist Beta display snapshot on refresh: {exc}")

        try:
            if _write_rows(alpha_rows, _SUMMARY_ALPHA_DISPLAY_PARQUET, 'ID', 'TOTAL'):
                saved.append('alpha')
        except Exception as exc:
            print(f"Warning: Could not persist Alpha display snapshot on refresh: {exc}")

        if saved:
            return f"Refresh saved snapshots: {', '.join(saved)} at {datetime.now().strftime('%H:%M:%S')}"
        return dash.no_update
