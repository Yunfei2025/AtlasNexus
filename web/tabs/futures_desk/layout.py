# -*- coding: utf-8 -*-
"""Futures Desk layout: Today / Research / Monitor."""

from __future__ import annotations

from dash import dcc, html

from web.tabs.beta.layouts.backtest import build_factor_backtest_layout, build_pool_correlation_card
from web.tabs.ui.styles import summary_subtabs_style, summary_subtabs_colors

SUBTABS = [("Today", "today"), ("Research", "research"), ("Monitor", "monitor")]


def _placeholder(title, lines):
    return html.Div([
        html.Div(title, style={'fontSize': '13px', 'fontWeight': '600', 'color': 'var(--text-primary)',
                               'marginBottom': '6px'}),
        *[html.Div(t, style={'fontSize': '11px', 'color': 'var(--text-muted)', 'lineHeight': '1.6'}) for t in lines],
    ], style={'border': '1px solid var(--border-strong)', 'borderRadius': '8px', 'padding': '14px 16px'})


def build_futures_desk_layout():
    _lbl = {'fontSize': '9px', 'fontWeight': '600', 'textTransform': 'uppercase', 'letterSpacing': '0.06em',
            'color': 'var(--text-muted)', 'display': 'block', 'marginBottom': '3px'}
    _inp = {'background': 'var(--surface-input)', 'color': 'var(--text-primary)', 'fontSize': '11px',
            'border': '1px solid var(--border-default)', 'borderRadius': '4px', 'padding': '4px 8px', 'width': '110px'}
    _btn = {'padding': '5px 12px', 'fontSize': '10px', 'fontWeight': '600', 'cursor': 'pointer',
            'background': 'var(--surface-input)', 'color': 'var(--text-secondary)',
            'border': '1px solid var(--border-default)', 'borderRadius': '4px'}
    _card = {'border': '1px solid var(--border-strong)', 'borderRadius': '8px', 'overflow': 'hidden'}
    _head = {'padding': '10px 16px', 'background': 'var(--surface-panel)', 'fontSize': '13px', 'fontWeight': '600',
             'color': 'var(--text-primary)', 'borderBottom': '1px solid var(--border-strong)'}

    def _field(label, id_, value, step):
        return html.Div([html.Label(label, style=_lbl),
                         dcc.Input(id=id_, type='number', value=value, min=0, step=step, debounce=True,
                                   persistence=True, persistence_type='local', style=_inp)])

    controls = html.Div([
        _field("Capital (CNY)", 'fd-capital', 1000000, 10000),
        _field("Risk / product (%)", 'fd-risk-pct', 0.25, 0.05),
        _field("Stop (× daily σ)", 'fd-stop-mult', 0.5, 0.1),
        _field("Daily loss limit (%)", 'fd-loss-limit', 1.0, 0.1),
        html.Button("↻ Reload data", id='fd-today-refresh', n_clicks=0, style={**_btn, 'alignSelf': 'flex-end'}, title=(
            "Re-read the local data files and recompute the screen, book and heat map. Nothing is fetched: "
            "daily and intraday files are updated by your other data apps.")),
        html.Button("⇪ Sync bar cache", id='fd-sync', n_clicks=0, style={**_btn, 'alignSelf': 'flex-end'}, title=(
            "Write 1-minute bars of every intraday tick file to input/futures_desk/bars (~0.2 MB per contract), "
            "so another computer that shares input/ can run Research, Today and Monitor without database/futures. "
            "Only contracts whose tick file changed are rebuilt.")),
        html.Div(id='fd-today-status', style={'fontSize': '10px', 'color': 'var(--text-muted)', 'alignSelf': 'flex-end'}),
    ], style={**_card, 'display': 'flex', 'gap': '16px', 'alignItems': 'flex-start', 'padding': '12px 16px',
              'flexWrap': 'wrap', 'overflow': 'visible'})

    today = html.Div([
        dcc.Store(id='fd-data-stamp'),
        controls,
        html.Div([
            html.Div([html.Div("Today's book", style=_head),
                      dcc.Loading(type='circle', color='var(--accent-blue)', style={'minHeight': '80px'},
                                  children=html.Div(id='fd-book-container', style={'padding': '12px 16px'}))],
                     style={**_card, 'minWidth': '0'}),
            html.Div(build_pool_correlation_card(), style={'minWidth': '0'}),
        ], style={'display': 'grid', 'gridTemplateColumns': 'minmax(0, 1.6fr) minmax(360px, 1fr)', 'gap': '10px',
                  'alignItems': 'start'}),
        html.Div([html.Div("Pool screen", style=_head),
                  dcc.Loading(type='circle', color='var(--accent-blue)', style={'minHeight': '80px'},
                              children=html.Div(id='fd-screen-container', style={'padding': '12px 16px'}))],
                 style=_card),
    ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '10px', 'padding': '16px', 'margin': '10px'})

    monitor = html.Div([
        html.Div([
            _field("Watch below (σ)", 'fd-mon-watch', 1.0, 0.5),
            _field("Halt below (σ)", 'fd-mon-halt', 2.0, 0.5),
            _field("Halt after N losing days", 'fd-mon-losses', 5, 1),
            html.Button("Apply statuses", id='fd-mon-apply', n_clicks=0, style={**_btn, 'alignSelf': 'flex-end'}, title=(
                "Write the computed Watch / Halted statuses to the approvals file. Halted products leave today's "
                "book and only return through a fresh walk-forward and approval.")),
            html.Div([dcc.Dropdown(id='fd-mon-pick', placeholder="Halt a product now", clearable=True,
                                   style={'width': '200px', 'fontSize': '10px'}),
                      html.Button("Halt now", id='fd-mon-halt-now', n_clicks=0, style=_btn)],
                     style={'display': 'flex', 'gap': '8px', 'alignSelf': 'flex-end', 'alignItems': 'center'}),
            html.Div(id='fd-mon-note', style={'fontSize': '10px', 'color': 'var(--text-muted)', 'alignSelf': 'flex-end'}),
        ], style={**_card, 'display': 'flex', 'gap': '16px', 'alignItems': 'flex-start', 'padding': '12px 16px',
                  'flexWrap': 'wrap', 'overflow': 'visible'}),
        html.Div([html.Div("Approved strategies: forward paper P&L vs expected", style=_head),
                  dcc.Loading(type='circle', color='var(--accent-blue)', style={'minHeight': '80px'},
                              children=html.Div(id='fd-mon-container', style={'padding': '12px 16px'}))],
                 style=_card),
    ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '10px', 'padding': '16px', 'margin': '10px'})

    return html.Div([
        dcc.Tabs(
            id="fd-subtabs", value="research",
            children=[dcc.Tab(label=label, value=value, className="an-subtab",
                              selected_className="an-subtab--selected an-subtab--amber")
                      for label, value in SUBTABS],
            style={**summary_subtabs_style, "marginTop": "8px"}, colors=summary_subtabs_colors,
        ),
        html.Div([
            html.Div(id="fd-today-div", children=today, style={"display": "none"}),
            html.Div(id="fd-research-div", children=build_factor_backtest_layout(), style={"display": "block"}),
            html.Div(id="fd-monitor-div", children=monitor, style={"display": "none"}),
        ], style={"position": "relative"}),
    ], className="an-tab-pane")
