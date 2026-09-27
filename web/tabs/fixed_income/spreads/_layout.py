# -*- coding: utf-8 -*-
"""Layout for the Spread Analysis tab (Alpha Book > Spread subtab)."""

from __future__ import annotations

from dash import dcc, html

from ..common import _fi_card_header


def build_spreads_layout():
    """Build the 'Spread Analysis' layout (Alpha Book > Spread subtab)."""
    # Local imports to keep module import light
    from settings.fixed_income import InstitutionConfig
    from settings.futures import FuturesConfig
    from web.core.styles import app_color  # styles only; ok

    GRAPH_INTERVAL_LONG = 300_000

    _label_style = {
        'color': 'var(--text-muted)', 'fontSize': '9px', 'fontWeight': '600',
        'textTransform': 'uppercase', 'letterSpacing': '0.06em',
        'marginBottom': '4px', 'display': 'block',
    }

    # Dropdown options for spread type with disabled group headers
    _spread_options = [
        {"label": "— Sectors —",           "value": "__sectors__",  "disabled": True},
        {"label": "Curve & Cross-Asset Spreads", "value": "TenorSpread"},
        {"label": "Sector PCA",             "value": "SectorPCASpread"},
        {"label": "— Bonds —",             "value": "__bonds__",    "disabled": True},
        {"label": "Treasury Bond",          "value": "TBondCurve"},
        {"label": "Policybank Bond",        "value": "CBondCurve"},
        {"label": "New-Issue OTR/OFR Event", "value": "BondNewIssue"},
        {"label": "Local Treasury Bond",    "value": "LBondSpread"},
        {"label": "Corporate Bank Bond",    "value": "BBondSpread"},
        {"label": "Government-backed Bond", "value": "GBondSpread"},
        {"label": "Medium Term Note",       "value": "MNoteSpread"},
        {"label": "— Swaps —",             "value": "__swaps__",    "disabled": True},
        {"label": "Swaps",                  "value": "SwapSpread"},
        {"label": "Treasury BondSwap",      "value": "TBondSwap"},
        {"label": "Policybank BondSwap",    "value": "CBondSwap"},
        {"label": "— Futures —",           "value": "__futures__",  "disabled": True},
        {"label": "Cash-and-Carry",         "value": "NetBasis"},
        {"label": "Calendar Spread",        "value": "TermBasis"},
        {"label": "Futures Swap",           "value": "FuturesSwap"},
    ]

    _DD_STYLE = {"fontSize": "11px", "color": "var(--text-primary)"}

    return html.Div([
        dcc.Store(id="realtime-data"),
        # Holds the real (possibly pipe-delimited pair) instrument ID used for
        # all downstream lookups; #ticker's visible text may show a shortened
        # display label (e.g. dropping the OFR1 reference leg) that differs
        # from this value.
        dcc.Store(id="ticker-id"),
        dcc.Interval(id="data-refresh-long", interval=int(GRAPH_INTERVAL_LONG), n_intervals=0),

        html.Div([
            html.H1("Spread Analysis", style={
                'margin': '0 0 3px', 'fontSize': '20px', 'fontWeight': '600',
                'color': 'var(--text-primary)',
            }),
            html.Div(
                "Time series, seasonal patterns, and daily statistics",
                style={'fontSize': '11px', 'color': 'var(--text-muted)'},
            ),
        ], style={'marginBottom': '4px'}),

        # ── Top row: Controls (left) + Daily Spread Statistics + Spread Time Series (right) ──
        html.Div([
            # Controls card — narrow, fixed width
            html.Div([
                _fi_card_header("Controls"),
                html.Div([
                    html.Div([
                        html.Label("Spread Type", style=_label_style),
                        dcc.Dropdown(
                            options=_spread_options,
                            value="TenorSpread",
                            id="spread-type",
                            clearable=False,
                            style=_DD_STYLE,
                        ),
                    ]),
                    html.Div([
                        html.Label("Seasonal Highlight Month", style=_label_style),
                        dcc.Dropdown(
                            options=[
                                {"label": m, "value": i + 1}
                                for i, m in enumerate([
                                    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
                                ])
                            ],
                            value=__import__("datetime").date.today().month,
                            id="seasonal-highlight-month",
                            clearable=True,
                            placeholder="None",
                            style=_DD_STYLE,
                        ),
                    ]),
                    html.Div([
                        html.Label("Seasonal Years", style=_label_style),
                        dcc.Dropdown(
                            options=[
                                {"label": "3 years", "value": 3},
                                {"label": "5 years", "value": 5},
                                {"label": "8 years", "value": 8},
                                {"label": "All", "value": 20},
                            ],
                            value=5,
                            id="seasonal-years",
                            clearable=False,
                            style=_DD_STYLE,
                        ),
                    ]),
                    html.Button(
                        "↻ Refresh", id="alpha-spread-refresh-btn", n_clicks=0,
                        style={'padding': '6px 12px', 'background': 'var(--accent-amber)', 'color': 'var(--navy-950)',
                               'border': 'none', 'borderRadius': '4px', 'fontSize': '10px', 'fontWeight': '700',
                               'cursor': 'pointer', 'width': '100%'},
                    ),
                    html.Div(id="alpha-spread-updated-at", style={'fontSize': '8px', 'color': 'var(--text-muted)'}),
                ], style={'padding': '12px 14px', 'display': 'flex', 'flexDirection': 'column', 'gap': '12px'}),
            ], style={'width': '220px', 'flexShrink': '0', 'border': '1px solid var(--border-strong)',
                      'borderRadius': '8px', 'overflow': 'hidden'}),

            # Daily Spread Statistics + Spread Time Series (stacked vertically on right)
            html.Div([
                # Daily Spread Statistics
                html.Div([
                    _fi_card_header("Daily Spread Statistics", badge_text="Z-score distribution · pick spreads below"),
                    html.Div(
                        dcc.Graph(
                            id="graph-spread-bar",
                            figure=dict(layout=dict(
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                            )),
                            config={"displayModeBar": False},
                            style={'padding': '12px 16px', 'height': '350px'},
                        ),
                    ),
                ], style={'border': '1px solid var(--border-strong)', 'borderRadius': '8px', 'overflow': 'hidden',
                          'backgroundColor': 'transparent', 'flex': '1'}),

                # Spread Time Series
                html.Div([
                    _fi_card_header("Spread Time Series"),
                    html.Div(id="ticker", className="graph__title", style={'padding': '8px 16px 0'}),
                    html.Div(
                        dcc.Graph(
                            id="graph-spread",
                            figure=dict(layout=dict(
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                                autosize=True,
                            )),
                            config={"displayModeBar": False, "responsive": True},
                            style={'height': '100%', 'width': '100%'},
                        ),
                        # Now a 2-row subplot (Z-score + spread/overlays, each on
                        # its own axis — see _split_zscore_subplot in
                        # web/core/graphs.py); 350px was already tight for one
                        # panel, so two legible rows need more headroom.
                        style={'padding': '8px', 'height': '520px'},
                    ),
                ], style={'border': '1px solid var(--border-strong)', 'borderRadius': '8px', 'overflow': 'hidden',
                          'backgroundColor': 'transparent', 'flex': '1'}),
            ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '10px', 'flex': '1', 'minWidth': '0'}),
        ], style={'display': 'flex', 'gap': '12px', 'alignItems': 'flex-start'}),

        # ── Seasonal Pattern (right) + Monthly Statistics (left, narrower) ─────
        html.Div([
            # Monthly Statistics / Issuance Statistics (BondNewIssue) — left, narrower
            html.Div([
                html.Div([
                    html.Span(id="spread-seasonal-stats-title", children="Monthly Statistics",
                              style={'fontSize': '13px', 'fontWeight': '600', 'color': 'var(--text-primary)'}),
                    html.Span(id="spread-seasonal-stats-badge", children="Directional bias", style={
                        'fontSize': '9px', 'color': 'var(--text-muted)', 'background': 'var(--surface-input)',
                        'padding': '2px 7px', 'borderRadius': '3px', 'border': '1px solid var(--border-default)',
                    }),
                ], style={'display': 'flex', 'alignItems': 'center', 'gap': '10px',
                          'padding': '11px 16px', 'background': 'var(--surface-panel)',
                          'borderBottom': '1px solid var(--border-strong)'}),
                html.Div(id="spread-seasonal-stats", style={'padding': '12px 16px', 'overflow': 'auto', 'maxHeight': '340px'}),
            ], style={'flex': '0 0 300px', 'border': '1px solid var(--border-strong)', 'borderRadius': '8px',
                      'overflow': 'hidden', 'backgroundColor': 'transparent'}),

            # Seasonal Pattern — right, flex 1
            html.Div([
                _fi_card_header("Seasonal Pattern", badge_text="Year-over-year overlay"),
                dcc.Graph(
                    id="graph-spread-seasonal",
                    figure=dict(layout=dict(
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                    )),
                    config={"displayModeBar": False},
                    style={"height": "340px", 'padding': '8px'},
                ),
            ], style={'flex': '1', 'minWidth': '0', 'border': '1px solid var(--border-strong)',
                      'borderRadius': '8px', 'overflow': 'hidden', 'backgroundColor': 'transparent'}),
        ], style={'display': 'flex', 'gap': '12px', 'alignItems': 'stretch'}),

    ], style={'padding': '10px', 'display': 'flex', 'flexDirection': 'column', 'gap': '10px'})
