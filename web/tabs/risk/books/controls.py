# -*- coding: utf-8 -*-
"""Book toggle and column-visibility callbacks for Summary > Books."""

from __future__ import annotations

import dash
from dash import html
from dash.dependencies import Input, Output, State

from web.tabs.beta.data import THEME


def register_risk_book_control_callbacks(app):
    """Register the Summary > Books control callbacks."""
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
