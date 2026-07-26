# -*- coding: utf-8 -*-
"""Beta allocation-table renderer for Summary > Books."""

from __future__ import annotations

from datetime import datetime

import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State
import pandas as pd

from web.tabs.beta.data import THEME
from web.tabs.beta.callbacks._common import (
    _SUMMARY_BETA_PARQUET,
    _SUMMARY_BETA_DISPLAY_PARQUET,
    _BETA_BOOK_POSITIONS_PARQUET,
    _ALPHA_POSITIONS_PARQUET,
    _get_beta_close_prices,
    _allocation_bar,
    _signed_value_style,
    _sortable_header,
    _apply_sort,
)
from ..helpers import _row_key, _load_beta_user_overrides


def register_beta_book_table_callbacks(app):
    """Register the Beta allocation-table renderer."""
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
