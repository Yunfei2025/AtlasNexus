# -*- coding: utf-8 -*-
"""Sorting, editing, deletion, and snapshot-persistence callbacks for Books."""

from __future__ import annotations

import pathlib
from datetime import datetime

import dash
from dash.dependencies import Input, Output, State, ALL
import pandas as pd

from web.tabs.beta.callbacks._common import _SUMMARY_BETA_DISPLAY_PARQUET, _SUMMARY_ALPHA_DISPLAY_PARQUET
from ..helpers import _row_key, _refresh_alpha_display_row, _persist_alpha_summary_rows, _beta_user_row_key, _load_beta_user_overrides, _persist_beta_user_rows


def register_risk_book_interaction_callbacks(app):
    """Register the Summary > Books interaction and persistence callbacks."""
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
