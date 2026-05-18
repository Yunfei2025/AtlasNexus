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
    _ALPHA_POSITIONS_PARQUET,
    _get_beta_close_prices,
    _load_cr_ts,
)


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
            if not _os.path.exists(_SUMMARY_BETA_PARQUET):
                return _no_data(
                    "No Beta snapshot found. Click RUN ANALYSIS in the Beta Book → Portfolio tab first."
                )
            try:
                df = pd.read_parquet(_SUMMARY_BETA_PARQUET)
                ts = df['_timestamp'].iloc[0] if '_timestamp' in df.columns else "unknown"

                # Close Price: look up last factor level for each asset's primary factor
                close_prices = _get_beta_close_prices()

                def _close_price_for(asset_name: str) -> float | None:
                    """Match asset name prefix to a factor-level proxy."""
                    for prefix, price in close_prices.items():
                        if asset_name.upper().startswith(prefix.upper()):
                            return price
                    return None

                capital_col = '_capital_cny' if '_capital_cny' in df.columns else 'Capital (CNY)'
                display_rows = []
                for _, row in df.iterrows():
                    asset = str(row.get('Asset Name', ''))
                    if asset == 'TOTAL':
                        continue
                    cap_cny = float(row.get(capital_col, 0) or 0)
                    cap_mm  = round(cap_cny / 1e6, 2)
                    wt      = round(float(row.get('Weight (%)', 0) or 0), 2)
                    cp      = _close_price_for(asset)
                    mv_mm   = cap_mm   # bonds at ~par → market value ≈ notional

                    display_rows.append({
                        'Asset Type':        row.get('Asset Type', ''),
                        'Universe':          row.get('Universe', ''),
                        'Asset Name':        asset,
                        'Close Price (%)':   f"{cp:.4f}" if cp is not None else 'N/A',
                        'Capital (MM CNY)':  f"{cap_mm:,.2f}",
                        'Market Value (MM)': f"{mv_mm:,.2f}",
                        'Weight (%)':        f"{wt:.2f}%",
                    })

                if not display_rows:
                    return _no_data("Beta snapshot is empty.")

                table = dash_table.DataTable(
                    data=display_rows,
                    columns=[{'name': c, 'id': c} for c in display_rows[0].keys()],
                    style_cell={
                        'textAlign': 'center', 'padding': '8px',
                        'backgroundColor': THEME['table_row_odd'],
                        'color': THEME['text_main'], 'border': 'none',
                        'fontSize': '12px',
                    },
                    style_header={
                        'backgroundColor': THEME['table_header'],
                        'color': THEME['text_main'],
                        'fontWeight': 'bold', 'border': 'none',
                    },
                    style_data_conditional=[
                        {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']},
                    ],
                    style_table={'overflowX': 'auto'},
                    sort_action='native',
                    page_size=20,
                )
                status = f"Beta snapshot from {ts[:19]}"
                return table, status

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
                    # spread is in annual % (e.g. 0.01 = 1bp) → convert to bp for display
                    cp_bp      = round(float(spread_val) * 100, 4) if pd.notna(spread_val) else None
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
                    mtm_carry_mm = None
                    mtm_total_mm = None
                    try:
                        open_price_bp = float(open_price_str) if open_price_str else None
                        volume_mm     = float(volume_str)     if volume_str     else None

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
                        'Suggested size (MM CNY)':f"{notional:,.1f}",
                        'DV01 (k CNY/bp)':        f"{dv01_k:.1f}",
                        'MtM Price (MM CNY)':     f"{mtm_price_mm:,.4f}" if mtm_price_mm is not None else '',
                        'MtM Carry (MM CNY)':     f"{mtm_carry_mm:,.4f}" if mtm_carry_mm is not None else '',
                        'MtM Value (MM CNY)':     f"{mtm_total_mm:,.4f}" if mtm_total_mm is not None else '',
                        'Weight (%)':             f"{float(row.get('weight', 0) or 0) * 100:.2f}%",
                    })

                if not display_rows:
                    return _no_data("Alpha snapshot is empty.")

                _editable_cols = {'Open price (bp)', 'Volume (mm)', 'Open date'}
                columns = [
                    {'name': c, 'id': c, 'editable': c in _editable_cols}
                    for c in display_rows[0].keys()
                ]

                dir_styles = [
                    {'if': {'filter_query': '{Direction} = "BUY"'},
                     'backgroundColor': 'rgba(0, 204, 150, 0.12)'},
                    {'if': {'filter_query': '{Direction} = "SELL"'},
                     'backgroundColor': 'rgba(239, 85, 59, 0.12)'},
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
                        'MtM Price (MM CNY)':'Volume × Duration × (Close − Open) / 10000',
                        'MtM Carry (MM CNY)':'Volume × cumulative carry+roll since open date',
                        'MtM Value (MM CNY)':'MtM Price + MtM Carry',
                    },
                    tooltip_delay=0,
                    tooltip_duration=None,
                )
                status = (
                    f"Alpha snapshot from {ts[:19]}"
                    + (" — saved" if is_refresh else "")
                )
                return table, status

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
        if not rows:
            raise dash.exceptions.PreventUpdate
        try:
            records = [{
                'spread_type':   str(r.get('Spread Type', '')),
                'ID':            str(r.get('ID', '')),
                'open_price_bp': r.get('Open price (bp)', ''),
                'volume_mm':     r.get('Volume (mm)', ''),
                'open_date':     str(r.get('Open date', '')),
            } for r in rows]
            pd.DataFrame(records).to_parquet(_ALPHA_POSITIONS_PARQUET, index=False)
            return f"Edits saved at {datetime.now().strftime('%H:%M:%S')}"
        except Exception as exc:
            return f"Save failed: {exc}"

