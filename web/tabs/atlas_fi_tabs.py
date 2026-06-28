"""Lightweight access to the legacy FI dashboard tab content.

Goal:
- Reuse the proven tab UIs from `web.core.content` (Spread Info / Curves / Pairs)
  inside the new AtlasNexus Daily console.
- Avoid importing `web.core` at module import time because `web.core.__init__`
  triggers heavy data loads.

Design:
- Provide small wrapper functions returning layout components.
- Provide a `register_callbacks(app)` function so callbacks used by these layouts
  are registered onto the *AtlasNexus app instance*.

Notes:
- `web.core.content` defines callbacks at import time using `web.core.server.app`.
  That app is a different Dash instance than AtlasNexus.
- We cannot safely import that module and expect callbacks to bind to our app.
  Instead, we re-implement only the required callbacks here, by copying minimal
  logic and switching decorators to use `app.callback`.

This file intentionally keeps imports local to functions and tries hard to avoid
triggering heavy data loads from `web.core.load`.
"""

from __future__ import annotations

from pathlib import Path

from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State


def _fi_card_header(title: str, badge_text: str | None = None) -> html.Div:
    """Card header row — title + optional meta badge. Matches the Alpha Book card pattern."""
    children_left = [
        html.Span(title, style={'fontSize': '13px', 'fontWeight': '600', 'color': 'var(--text-primary)'}),
    ]
    if badge_text:
        children_left.append(html.Span(badge_text, style={
            'fontSize': '9px', 'color': 'var(--text-muted)', 'background': 'var(--surface-input)',
            'padding': '2px 7px', 'borderRadius': '3px', 'border': '1px solid var(--border-default)',
        }))
    return html.Div(
        children_left,
        style={'display': 'flex', 'alignItems': 'center', 'gap': '10px',
               'padding': '11px 16px', 'background': 'var(--surface-panel)',
               'borderBottom': '1px solid var(--border-strong)'},
    )


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
        {"label": "Sector PCA",             "value": "SectorPCASpread"},
        {"label": "Spread Regression",      "value": "BinarySpread"},
        {"label": "Curve & Cross-Asset Spreads", "value": "TenorSpread"},
        {"label": "— Bonds —",             "value": "__bonds__",    "disabled": True},
        {"label": "Treasury Bond",          "value": "TBondCurve"},
        {"label": "Policybank Bond",        "value": "CBondCurve"},
        {"label": "Local Treasury Bond",    "value": "LBondSpread"},
        {"label": "Corporate Bank Bond",    "value": "BBondSpread"},
        {"label": "Government-backed Bond", "value": "GBondSpread"},
        {"label": "Medium Term Note",       "value": "MNoteSpread"},
        {"label": "— Swaps —",             "value": "__swaps__",    "disabled": True},
        {"label": "Swaps",                  "value": "SwapSpread"},
        {"label": "Treasury BondSwap",      "value": "TBondSwap"},
        {"label": "Policybank BondSwap",    "value": "CBondSwap"},
        {"label": "— Futures —",           "value": "__futures__",  "disabled": True},
        {"label": "Bond Futures Basis",     "value": "NetBasis"},
        {"label": "Futures Term Basis",     "value": "TermBasis"},
        {"label": "Futures Swap",           "value": "FuturesSwap"},
    ]

    _DD_STYLE = {"fontSize": "11px", "color": "var(--text-primary)"}

    return html.Div([
        dcc.Store(id="realtime-data"),
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
                            value="SectorPCASpread",
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
                        style={'padding': '8px', 'height': '350px'},
                    ),
                ], style={'border': '1px solid var(--border-strong)', 'borderRadius': '8px', 'overflow': 'hidden',
                          'backgroundColor': 'transparent', 'flex': '1'}),
            ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '10px', 'flex': '1', 'minWidth': '0'}),
        ], style={'display': 'flex', 'gap': '12px', 'alignItems': 'flex-start'}),

        # ── Seasonal Pattern (right) + Monthly Statistics (left, narrower) ─────
        html.Div([
            # Monthly Statistics — left, narrower
            html.Div([
                _fi_card_header("Monthly Statistics", badge_text="Directional bias"),
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


_CURVE_LBL = {
    "color": "var(--text-muted)",
    "fontSize": "9px",
    "textTransform": "uppercase",
    "letterSpacing": "0.07em",
    "fontWeight": "600",
    "marginBottom": "6px",
    "display": "block",
}


def build_curves_layout():
    """Build the 'Curves' tab layout (Market > Curves), styled per guide/MarketCurves.jsx."""
    from curves.utils.plot import CURVE_THEME

    return html.Div(
        [
            html.Div(
                [
                    # ── Left sidebar: Curve Type panel + Reference Bonds panel ──
                    html.Div(
                        [
                            # Curve Type panel (top)
                            html.Div(
                                [
                                    html.Div("Curve Type", style=_CURVE_LBL),
                                    dcc.Dropdown(
                                        options=[
                                            {"label": "China Government Bond", "value": "TBond"},
                                            {"label": "China Policybank Bond", "value": "CBond"},
                                            {"label": "IRS Spot Curve", "value": "IRSSpot"},
                                            {"label": "IRS Forward Curve", "value": "IRSForward"},
                                        ],
                                        value="TBond",
                                        id="curve-selection",
                                        clearable=False,
                                        optionHeight=28,
                                        style={"fontSize": "11px"},
                                    ),
                                ],
                                style={
                                    "background": "var(--surface-panel)",
                                    "border": "1px solid var(--border-strong)",
                                    "borderRadius": "6px 6px 0 0",
                                    "borderBottom": "none",
                                    "padding": "10px 12px",
                                },
                            ),
                            # Reference Bonds panel (bottom, flex to fill remaining height)
                            html.Div(
                                [
                                    html.Div("Reference Bonds", style=_CURVE_LBL),
                                    dash_table.DataTable(
                                        id="ref-bonds-t",
                                        # style_data/style_header removed — CSS .dash-cell/.dash-header
                                        # rules in design.css own colors; keep only sizing here.
                                        style_cell={
                                            "height": "auto",
                                            "width": "60px",
                                            "textAlign": "left",
                                            "border": "1px solid #061E44",
                                        },
                                    ),
                                ],
                                id="ref-bonds-container",
                                style={
                                    "background": "var(--surface-panel)",
                                    "border": "1px solid var(--border-strong)",
                                    "borderRadius": "0 0 6px 6px",
                                    "borderTop": "1px solid var(--border-default)",
                                    "padding": "10px 12px",
                                    "flex": "1",
                                    "minHeight": "0",
                                },
                            ),
                        ],
                        style={
                            "width": "200px",
                            "minWidth": "200px",
                            "flexShrink": "0",
                            "display": "flex",
                            "flexDirection": "column",
                            "alignSelf": "stretch",
                        },
                    ),

                    # ── Center: header + legend + chart ──────────────────────
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Span(
                                        id="curves-title",
                                        children="Real Time Bond Curves",
                                        style={"fontSize": "13px", "fontWeight": "600", "color": "var(--text-primary)"},
                                    ),
                                    html.Span(" · ", style={"color": "var(--text-faint)", "margin": "0 8px"}),
                                    html.Span(
                                        id="curves-chart-subtitle",
                                        style={"fontSize": "11px", "color": "var(--text-muted)"},
                                    ),
                                ],
                                style={
                                    "display": "flex",
                                    "alignItems": "baseline",
                                    "marginBottom": "10px",
                                },
                            ),
                            dcc.Graph(
                                id="curves-graph",
                                style={"height": "660px"},
                                config={
                                    "displayModeBar": "hover",
                                    "displaylogo": False,
                                    "scrollZoom": True,
                                    "modeBarButtonsToRemove": [
                                        "select2d", "lasso2d", "autoScale2d",
                                        "zoomIn2d", "zoomOut2d", "toggleSpikelines",
                                        "hoverClosestCartesian", "hoverCompareCartesian",
                                    ],
                                    "toImageButtonOptions": {
                                        "format": "svg",
                                        "filename": "curves_chart",
                                    },
                                },
                                figure=dict(
                                    layout=dict(
                                        plot_bgcolor=CURVE_THEME["bg"], paper_bgcolor=CURVE_THEME["bg"]
                                    )
                                ),
                                className="an-card",
                            ),
                        ],
                        style={"flex": "1", "display": "flex", "flexDirection": "column", "minWidth": "0"},
                    ),

                    # ── Right: Curve Snapshot rail ───────────────────────────
                    html.Div(
                        id="curves-snapshot",
                        className="curve-snapshot",
                        style={
                            "width": "200px",
                            "minWidth": "200px",
                            "flexShrink": "0",
                            "alignSelf": "stretch",
                            "borderRadius": "6px",
                            "border": "1px solid var(--border-strong)",
                        },
                    ),
                ],
                style={
                    "display": "flex",
                    "flexDirection": "row",
                    "gap": "16px",
                    "alignItems": "flex-start",
                },
            ),
        ],
        style={"padding": "16px", "margin": "10px"},
    )


def build_pairs_layout():
    """Build the optimized 'Pairs' tab layout with smart cards and live stats."""
    from web.core.styles import app_color
    from web.tabs.alpha.data import THEME

    _label_style = {
        'color': THEME['text_sub'], 'fontSize': '9px', 'fontWeight': '600',
        'textTransform': 'uppercase', 'letterSpacing': '0.06em',
        'marginBottom': '4px', 'display': 'block',
    }
    _pair_input_style = {
        "width": "100%", "padding": "4px", "fontSize": "11px",
        "backgroundColor": THEME["bg_input"], "color": THEME["text_main"],
        "border": f"1px solid {THEME['border']}", "borderRadius": "2px", "boxSizing": "border-box",
    }

    def _pair_config_cell(title, leg1_id, leg1_val, leg2_id, leg2_val, hint):
        return html.Div([
            html.Div(title, style={"fontSize": "10px", "fontWeight": "600", "color": THEME["text_sub"], "marginBottom": "4px"}),
            html.Div([
                dcc.Input(id=leg1_id, type='text', value=leg1_val, style=_pair_input_style),
                dcc.Input(id=leg2_id, type='text', value=leg2_val, style={**_pair_input_style, "marginTop": "3px"}),
                html.Div(hint, style={"fontSize": "10px", "color": THEME["text_sub"], "marginTop": "4px", "fontStyle": "italic"}),
            ]),
        ])

    return html.Div([
        html.Div([
            html.H1("Pairs Analysis", style={
                'margin': '0 0 3px', 'fontSize': '20px', 'fontWeight': '600',
                'color': 'var(--text-primary)',
            }),
            html.Div(
                "Relative value spreads with OLS trends and confidence bands",
                style={'fontSize': '11px', 'color': 'var(--text-muted)'},
            ),
        ], style={'marginBottom': '4px'}),

        # ── Main layout: Controls (left) + Charts (right) ──────────────────────
        html.Div([
            # Controls card — narrow, fixed width
            html.Div([
                _fi_card_header("Controls"),
                html.Div([
                    html.Div([
                        html.Label("Lookback Days", style=_label_style),
                        dcc.Input(
                            id='pairs-days-input', type='number', value=90, min=1,
                            style={"width": "100%", "padding": "6px 8px", "boxSizing": "border-box",
                                   "backgroundColor": THEME["bg_input"], "color": THEME["text_main"],
                                   "border": f"1px solid {THEME['border']}", "borderRadius": "4px",
                                   "fontSize": "11px", "textAlign": "right"},
                        ),
                    ]),

                    html.Details([
                        html.Summary("⚙ Configure", style={
                            'padding': '6px 12px', 'background': 'var(--surface-panel)',
                            'color': 'var(--text-secondary)', 'border': '1px solid var(--border-default)',
                            'borderRadius': '4px', 'fontSize': '10px', 'cursor': 'pointer', 'listStyle': 'none',
                        }),
                        html.Div([
                            _pair_config_cell("Pair 1", 'pairs-leg1-1', '260010.IB', 'pairs-leg2-1', '260008.IB', "CGB-5s10s"),
                            _pair_config_cell("Pair 2", 'pairs-leg1-2', '2600002.IB', 'pairs-leg2-2', '260010.IB', "CGB-10s30s"),
                            _pair_config_cell("Pair 3", 'pairs-leg1-3', '260205.IB', 'pairs-leg2-3', '260010.IB', "CDBCGB-10y"),
                            _pair_config_cell("Pair 4", 'pairs-leg1-4', '260008.IB', 'pairs-leg2-4', 'FR007S5Y.IR', "CGBRepo7d-5y"),
                        ], style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "10px",
                                  "padding": "10px", "marginTop": "6px",
                                  "backgroundColor": THEME["bg_input"], "borderRadius": "4px",
                                  "border": f"1px solid {THEME['border']}"}),
                    ]),

                    html.Button(
                        "↻ Refresh", id="pairs-refresh-btn", n_clicks=0,
                        style={'padding': '6px 12px', 'background': THEME['accent'], 'color': 'var(--navy-950)',
                               'border': 'none', 'borderRadius': '4px', 'fontSize': '10px', 'fontWeight': '700',
                               'cursor': 'pointer', 'width': '100%'},
                    ),
                    html.Span(
                        id="pairs-last-updated", children="—",
                        style={"color": THEME["text_sub"], "fontSize": "8px", "fontFamily": "monospace"},
                    ),

                    # ── Z-Score Thresholds (moved to bottom, vertically stacked) ──
                    html.Div([
                        html.Div("Z-Score Thresholds", style={'fontSize': '10px', 'fontWeight': '600', 'color': THEME['text_sub'], 'marginBottom': '8px'}),
                        html.Div([
                            html.Div([
                                html.Span(style={'width': '8px', 'height': '8px', 'borderRadius': '50%',
                                                 'background': color, 'display': 'inline-block', 'flexShrink': '0'}),
                                html.Span([
                                    html.Span(label, style={'color': 'var(--text-secondary)', 'fontWeight': '600', 'display': 'block', 'fontSize': '9px'}),
                                    html.Span(rng, style={'color': 'var(--text-muted)', 'fontSize': '8px'}),
                                ], style={'minWidth': '0', 'flex': '1'}),
                            ], style={'display': 'flex', 'alignItems': 'flex-start', 'gap': '6px'})
                            for color, rng, label in [
                                ('#a4b6d2', '|z| < 1.5', 'Neutral'),
                                (THEME['accent'], '1.5 ≤ |z| < 2.0', 'Watch'),
                                ('#e06060', '|z| ≥ 2.0', 'Signal'),
                            ]
                        ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '6px', 'fontSize': '9px'}),
                    ], style={'padding': '10px', 'background': THEME['bg_input'], 'borderRadius': '4px',
                              'border': f"1px solid {THEME['border_sub']}"}),
                ], style={'padding': '12px 14px', 'display': 'flex', 'flexDirection': 'column', 'gap': '12px'}),
            ], style={'width': '220px', 'flexShrink': '0', 'border': '1px solid var(--border-strong)',
                      'borderRadius': '8px', 'overflow': 'hidden'}),

            # ── Results panel: 2x2 grid for pair cards (right side) ──────────
            html.Div(
                id="pairs-plots-container",
                style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "10px", "flex": "1", "minWidth": "0"},
                children=[
                    html.Div([
                        html.Div(
                            "Click Refresh to generate pair analysis",
                            style={"textAlign": "center", "color": THEME["text_sub"],
                                   "padding": "40px 20px", "fontSize": "12px"}
                        )
                    ])
                ],
            ),
        ], style={'display': 'flex', 'gap': '12px', 'alignItems': 'flex-start'}),

        # ── Hidden loader for triggering updates ────────────────────────────
        html.Div(id="pairs-content-loader", style={"display": "none"}),
    ], style={'padding': '10px', 'display': 'flex', 'flexDirection': 'column', 'gap': '10px'})


def _z_score_color(z):
    """Return hex color for a z-score value based on statistical thresholds.

    Color thresholds:
    - |z| ≥ 2.0:       Red (#e06060)      — Signal: statistically extreme
    - 1.5 ≤ |z| < 2.0: Amber (#e8a13f)   — Watch: elevated deviation
    - |z| < 1.5:       Muted (#a4b6d2)   — Neutral: within noise

    Args:
        z: Z-score value (float)

    Returns:
        str: Hex color code
    """
    az = abs(z)
    if az >= 2.0:
        return '#e06060'  # red — signal
    elif az >= 1.5:
        return '#e8a13f'  # amber — watch
    else:
        return '#a4b6d2'  # muted — neutral


def _build_pair_card(leg1, leg2, stats, figure=None):
    """Build a pair card with smart header showing live stats.

    Header displays:
    - Pair names: bold instrument codes
    - last: current spread in basis points
    - β (beta): slope (change per day)
    - z (z-score): deviation from mean, color-coded by _z_score_color()

    Args:
        leg1, leg2: Instrument names (strings)
        stats: Dict with keys: last_bp, slope (beta), last_z (z-score)
        figure: Plotly figure object (optional)

    Returns:
        html.Div: Card component with header and chart
    """
    from web.tabs.alpha.data import THEME

    z = stats.get('last_z', 0.0)
    slope = stats.get('slope', 0.0)
    last_bp = stats.get('last_bp', 0.0)

    # Determine z-score color based on thresholds (see _z_score_color docs)
    z_color = _z_score_color(z)

    sign_z = '+' if z >= 0 else ''
    sign_slope = '+' if slope >= 0 else ''

    # Build header with stats
    header = html.Div(
        [
            html.Div([
                html.B(leg1, style={'color': '#e9eef8'}),
                html.Span(' vs ', style={'color': '#4a5d7c'}),
                html.B(leg2, style={'color': '#e9eef8'}),
            ], style={
                'fontSize': '11px',
                'fontWeight': '700',
                'letterSpacing': '0.09em',
                'textTransform': 'uppercase',
                'color': '#6f83a3',
            }),
            html.Div([
                html.Span(['last ', html.B(f'{last_bp:.1f} bp')]),
                html.Span(['β ', html.B(f'{sign_slope}{slope:.3f}/d')]),
                html.Span([
                    'z ',
                    html.Span(f'{sign_z}{z:.1f}σ', style={'color': z_color, 'fontWeight': '700'}),
                ]),
            ], style={
                'display': 'flex',
                'gap': '16px',
                'fontSize': '12px',
                'color': '#6f83a3',
            }),
        ],
        style={
            'padding': '13px 18px',
            'borderBottom': '1px solid rgba(255,255,255,0.06)',
            'display': 'flex',
            'alignItems': 'baseline',
            'justifyContent': 'space-between',
            'gap': '12px',
            'background': '#17345c',
        },
        className='pair-card__header',
    )

    # Build chart section
    if figure:
        chart = dcc.Graph(
            figure=figure,
            config={'displayModeBar': 'hover', 'displaylogo': False, 'responsive': True},
            style={'height': '430px'},
        )
    else:
        chart = html.Div(
            'Loading chart...',
            style={'height': '430px', 'display': 'flex', 'alignItems': 'center', 'justifyContent': 'center', 'color': THEME['text_sub']},
        )

    # Build card
    return html.Div(
        [header, chart],
        className='pair-card',
        style={
            'background': '#0e1d3a',
            'border': '1px solid #1e3a5f',
            'borderRadius': '7px',
            'overflow': 'hidden',
        },
    )


def build_surface_layout():
    """Build the legacy 'SURFACE' (Yield Surface) layout."""
    # Import locally from the surface package in root
    from surface.layout import create_layout

    return create_layout()


def register_callbacks(app) -> None:
    """Register the callbacks required by the migrated layouts onto `app`."""
    # --- Register Surface callbacks ---
    try:
        from surface.callbacks import register_callbacks as register_surface_callbacks
        register_surface_callbacks(app)
    except Exception as e:
        print(f"Failed to register surface callbacks: {e}")

    from dash import callback_context
    import datetime
    import json
    import os
    import pickle
    import pandas as pd
    from settings.paths import DIR_INPUT
    from settings.fixed_income import BondConfig
    
    # Import plotting dependencies at function level to catch errors early
    try:
        import plotly.graph_objs as go
        from web.core.styles import app_color
        PLOTTING_AVAILABLE = True
    except Exception as e:
        print(f"Warning: Plotting dependencies not available: {e}")
        PLOTTING_AVAILABLE = False
        from settings.general import app_color
        go = None
    
    # Try to import web.core modules (they might fail if data files are missing)
    try:
        from web.core.graphs import statistics as orig_statistics
        from web.core.graphs import spreadts as orig_spreadts
        from web.core.graphs import curves_graph as orig_curves
        from web.core.scripts import refresh as orig_refresh
        GRAPHS_AVAILABLE = True
    except Exception as e:
        print(f"Warning: web.core.graphs not available (data files may be missing): {e}")
        GRAPHS_AVAILABLE = False
        orig_statistics = None
        orig_spreadts = None
        orig_curves = None
        orig_refresh = None

    # Pickle cache to avoid redundant file loads
    _PICKLE_CACHE: dict[str, tuple[float, object]] = {}

    def _load_pickle_cached(path_obj):
        """Load pickle with caching based on file mtime."""
        path = str(path_obj)
        try:
            mtime = os.path.getmtime(path)
        except FileNotFoundError:
            return None

        cached = _PICKLE_CACHE.get(path)
        if cached and cached[0] == mtime:
            return cached[1]

        try:
            with open(path, "rb") as f:
                obj = pickle.load(f)
            _PICKLE_CACHE[path] = (mtime, obj)
            return obj
        except Exception as e:
            print(f"Error loading {path}: {e}")
            return None

    # ── Futures spread rendering (Bond-Futures / Term Basis / Futures-Swap) ──────
    # These three read directly from futures-spds.pkl (derived from
    # futures-analytics.pkl by StatGenerator.compute_futures_stats).  Their spreads
    # are already in their natural units (bp for IRR−Repo and FYTM−IRS, price
    # points for the calendar Term Basis), so we render them here instead of the
    # legacy season-keyed graphs path which assumes %-stored spreads (×100 → bp).
    _FUT_SPREADS = {"NetBasis", "TermBasis", "FuturesSwap"}
    _FUT_UNIT = {"NetBasis": "bp", "FuturesSwap": "bp", "TermBasis": "pts"}
    _FUT_TITLE = {
        "NetBasis":    "Bond Futures Basis (IRR − Repo)",
        "FuturesSwap": "Futures Swap (FYTM − IRS)",
        "TermBasis":   "Futures Term Basis (Front − Next)",
    }
    _FUT_ZTHD = 2.0

    def _fnum(v):
        try:
            f = float(v)
            return f if f == f else None
        except (TypeError, ValueError):
            return None

    def _fut_stat_bucket(stype):
        """Return {ticker: (spread_series, mean, vol, max, min)} for a futures type."""
        spd = _load_pickle_cached(os.path.join(DIR_INPUT, "futures-spds.pkl")) or {}
        out = {}
        if stype in ("NetBasis", "FuturesSwap"):
            bucket = spd.get(stype, {})
            if isinstance(bucket, dict):
                for tk, d in bucket.items():
                    if not isinstance(d, dict):
                        continue
                    si, sp = d.get("StatInfo"), d.get("Spread")
                    if not isinstance(si, pd.DataFrame) or not isinstance(sp, pd.DataFrame):
                        continue
                    if si.empty or sp.empty or tk not in si.index:
                        continue
                    s = pd.to_numeric(sp.iloc[:, 0], errors="coerce").dropna()
                    if s.empty:
                        continue
                    out[tk] = (s, _fnum(si.loc[tk, "mean"]), _fnum(si.loc[tk, "vol"]),
                               _fnum(si.loc[tk, "max"]), _fnum(si.loc[tk, "min"]))
        elif stype == "TermBasis":
            tb = spd.get("TermBasis", {})
            si = tb.get("StatInfo") if isinstance(tb, dict) else None
            sp = tb.get("Spread") if isinstance(tb, dict) else None
            if isinstance(si, pd.DataFrame) and isinstance(sp, pd.DataFrame) and not si.empty:
                for tk in si.index:
                    if tk not in sp.columns:
                        continue
                    s = pd.to_numeric(sp[tk], errors="coerce").dropna()
                    if s.empty:
                        continue
                    out[tk] = (s, _fnum(si.loc[tk, "mean"]), _fnum(si.loc[tk, "vol"]),
                               _fnum(si.loc[tk, "max"]), _fnum(si.loc[tk, "min"]))
        return out

    def _fut_empty(title):
        return go.Figure(data=[], layout=dict(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            title=title,
        ))

    def _futures_bar_figure(stype):
        bucket = _fut_stat_bucket(stype)
        if not bucket:
            return _fut_empty(f"Waiting for data: {stype}...")
        unit = _FUT_UNIT[stype]
        rows = []
        for tk in sorted(bucket):
            s, mean, vol, _, _ = bucket[tk]
            last = float(s.iloc[-1])
            z = (last - mean) / vol if (mean is not None and vol) else None
            color = "grey"
            if z is not None and z >= _FUT_ZTHD:
                color = "green"
            elif z is not None and z <= -_FUT_ZTHD:
                color = "red"
            rows.append((tk, last, z, color))
        trace = go.Bar(
            x=[r[0] for r in rows],
            y=[r[2] for r in rows],
            marker=dict(color=[r[3] for r in rows]),
            hovertext=[f"Spread: {r[1]:.2f}{unit}" for r in rows],
            name="Zscore",
        )
        try:
            from web.core.styles import layout_stat
            layout = layout_stat("Z-score")
        except Exception:
            layout = dict(plot_bgcolor="rgba(0,0,0,0)",
                          paper_bgcolor="rgba(0,0,0,0)",
                          font=dict(color="#ffffff"), yaxis=dict(title="Z-score"))
        fig = go.Figure(data=[trace], layout=layout)
        fig.update_layout(clickmode="event+select")
        return fig

    def _futures_ts_figure(stype, ticker):
        from dateutil.relativedelta import relativedelta
        from settings.general import GeneralConfig
        bucket = _fut_stat_bucket(stype)
        if not bucket:
            return _fut_empty(f"Waiting for data: {stype}...")
        if ticker not in bucket:
            ticker = sorted(bucket)[0]   # default to first when none clicked yet
        s, mean, vol, vmax, vmin = bucket[ticker]
        unit = _FUT_UNIT[stype]
        window = getattr(GeneralConfig, "STAT_WINDOW", 12)
        start = s.index[-1] - relativedelta(months=window)

        traces = [go.Scatter(
            name="Spread (bp)", x=s.index, y=s.values,
            line={"width": 3, "color": "#2a6fd3"},
        )]

        # For NetBasis: overlay IRR and Repo (%) on a secondary y-axis
        _yaxis2 = None
        if stype == "NetBasis":
            try:
                from settings.futures import FuturesConfig
                _ana = _load_pickle_cached(os.path.join(DIR_INPUT, "futures-analytics.pkl")) or {}
                _dbpx = _load_pickle_cached(os.path.join(DIR_INPUT, "database-px.pkl")) or {}
                _df_ana = _ana.get(ticker)
                if isinstance(_df_ana, pd.DataFrame) and "irr" in _df_ana.columns:
                    _irr = pd.to_numeric(_df_ana["irr"], errors="coerce")
                    _irr = _irr.where(_irr >= -0.5).dropna()
                    _irr.index = pd.DatetimeIndex(_irr.index)
                    _irr = _irr.loc[start:]
                    if not _irr.empty:
                        traces.append(go.Scatter(
                            name="IRR (%)", x=_irr.index, y=_irr.values,
                            line={"width": 1.5, "color": "#f39c12", "dash": "dot"},
                            yaxis="y2",
                        ))
                _irs_df = _dbpx.get("IRS") if isinstance(_dbpx, dict) else None
                if isinstance(_irs_df, pd.DataFrame) and "FR007.IR" in _irs_df.columns:
                    _funding = FuturesConfig.FUNDING_BASIS_BP / 100.0
                    _repo = pd.to_numeric(_irs_df["FR007.IR"], errors="coerce").dropna()
                    _repo.index = pd.DatetimeIndex(_repo.index)
                    _repo = (_repo + _funding).loc[start:]
                    if not _repo.empty:
                        traces.append(go.Scatter(
                            name=f"Repo FR007+{FuturesConfig.FUNDING_BASIS_BP:.0f}bp (%)",
                            x=_repo.index, y=_repo.values,
                            line={"width": 1.5, "color": "#2ecc71", "dash": "dot"},
                            yaxis="y2",
                        ))
                _yaxis2 = dict(title="%", overlaying="y", side="right",
                               showgrid=False, zeroline=False,
                               tickfont=dict(color="#aaaaaa"), title_font=dict(color="#aaaaaa"))
            except Exception:
                pass

        fig = go.Figure(data=traces)
        if mean is not None:
            bands = [(mean, "mean", "solid", "#aaaaaa")]
            if vol:
                bands += [
                    (mean + vol, "+1σ", "dot", "#f39c12"),
                    (mean - vol, "-1σ", "dot", "#f39c12"),
                    (mean + 2 * vol, "+2σ", "dash", "#ef553b"),
                    (mean - 2 * vol, "-2σ", "dash", "#ef553b"),
                ]
            for val, label, dash, color in bands:
                fig.add_hline(y=val, line_dash=dash, line_color=color,
                              annotation_text=label, annotation_position="right")
        _fmt = lambda v: f"{v:.2f}{unit}" if v is not None else "NA"
        title = (f"<b>{_FUT_TITLE[stype]} — {ticker}</b><br>"
                 f"Latest: {_fmt(float(s.iloc[-1]))}, Mean: {_fmt(mean)}, "
                 f"Vol: {_fmt(vol)}, Max: {_fmt(vmax)}, Min: {_fmt(vmin)}")
        layout_kwargs = dict(
            plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
            font=dict(color="#ffffff"), title=title,
            xaxis=dict(range=[start, s.index[-1]]),
            yaxis=dict(title=unit),
            showlegend=(_yaxis2 is not None),
            legend=dict(orientation="h", x=0, y=1.08, font=dict(size=11)),
            margin=dict(l=50, r=50, t=60, b=40),
            hovermode='x unified',
        )
        if _yaxis2 is not None:
            layout_kwargs["yaxis2"] = _yaxis2
        fig.update_layout(**layout_kwargs)
        return fig

    # Realtime data refresh callback
    @app.callback(
        Output("realtime-data", "data"),
        Input("data-refresh", "n_intervals"),
    )
    def _refresh_realtime_data(interval):
        """Load realtime spread data using the core script."""
        if not GRAPHS_AVAILABLE or orig_refresh is None:
            print("Realtime data refresh skipped: web.core.scripts not available")
            return "{}"
        try:
            return orig_refresh(interval)
        except Exception as e:
            print(f"Error refreshing realtime data via core script: {e}")
            import traceback
            traceback.print_exc()
            return "{}"

    @app.callback(
        [Output("pairs-plots-container", "children"), Output("pairs-last-updated", "children")],
        [Input("pairs-content-loader", "children"), Input("pairs-refresh-btn", "n_clicks"),
         Input("pairs-leg1-1", "value"), Input("pairs-leg2-1", "value"),
         Input("pairs-leg1-2", "value"), Input("pairs-leg2-2", "value"),
         Input("pairs-leg1-3", "value"), Input("pairs-leg2-3", "value"),
         Input("pairs-leg1-4", "value"), Input("pairs-leg2-4", "value"),
         Input("pairs-days-input", "value")],
    )
    def _load_pairs_content(_, n_clicks, leg1_1, leg2_1, leg1_2, leg2_2, leg1_3, leg2_3, leg1_4, leg2_4, window_days):
        """Build pair cards with Plotly figures and smart headers showing live stats."""
        from web.tabs.alpha.data import THEME
        import numpy as np

        # Determine if we should recompute pairs analysis
        trigger_id = None
        cards = []
        last_updated = "Last updated: Loading..."

        if callback_context.triggered:
            trigger_id = callback_context.triggered[0]["prop_id"].split(".")[0]
            if trigger_id == "pairs-refresh-btn" and n_clicks and n_clicks > 0:
                try:
                    from pairs.manager import PairManager

                    # Validate window_days
                    if not window_days or window_days < 1:
                        window_days = 90

                    # Create PairManager and add pairs based on user inputs
                    manager = PairManager()

                    # Add pairs if both legs are provided
                    pairs_config = [
                        ("Pair 1", leg1_1, leg2_1),
                        ("Pair 2", leg1_2, leg2_2),
                        ("Pair 3", leg1_3, leg2_3),
                        ("Pair 4", leg1_4, leg2_4),
                    ]

                    for name, leg1, leg2 in pairs_config:
                        if leg1 and leg2 and leg1.strip() and leg2.strip():
                            manager.add_pair(name, leg1.strip(), leg2.strip(), window=int(window_days))

                    if len(manager) == 0:
                        raise ValueError("No valid pairs configured. Please provide at least one pair.")

                    # Prepare analysis for all pairs
                    analyses = manager.prepare_analysis()

                    # Build cards with Plotly figures
                    for pair_name, pair in manager.pairs.items():
                        if pair_name not in analyses:
                            continue

                        analysis = analyses[pair_name]
                        spread_df = analysis.get('spread_df')
                        reg_result = analysis.get('regression_result')

                        if spread_df is None or len(spread_df) == 0:
                            continue

                        # Extract numeric spread values properly
                        if isinstance(spread_df, pd.DataFrame):
                            # Try to get 'spread' column first, fallback to first numeric column
                            if 'spread' in spread_df.columns:
                                spread = pd.to_numeric(spread_df['spread'], errors='coerce').values
                            else:
                                # Find first numeric column
                                for col in spread_df.columns:
                                    try:
                                        spread = pd.to_numeric(spread_df[col], errors='coerce').values
                                        if not np.all(np.isnan(spread)):
                                            break
                                    except:
                                        continue

                            # Extract dates: try 'date' column or use index
                            if 'date' in spread_df.columns:
                                dates = pd.to_datetime(spread_df['date']).values
                            else:
                                dates = spread_df.index
                        else:
                            # If it's a Series
                            spread = pd.to_numeric(spread_df, errors='coerce').values
                            dates = spread_df.index

                        # Remove NaN values
                        valid_idx = ~np.isnan(spread)
                        spread = spread[valid_idx]
                        if isinstance(dates, np.ndarray):
                            dates = dates[valid_idx]
                        else:
                            dates = dates[valid_idx] if hasattr(dates, '__getitem__') else dates

                        if len(spread) < 2:
                            continue

                        # OLS fit
                        xs = np.arange(len(spread), dtype=float)
                        slope, intercept = np.polyfit(xs, spread, 1)
                        trend = intercept + slope * xs
                        resid = spread - trend
                        sigma = resid.std()
                        last_z = resid[-1] / sigma if sigma > 0 else 0.0

                        stats = {
                            'last_bp': float(spread[-1]),
                            'slope': float(slope),
                            'last_z': float(last_z),
                        }

                        # Build Plotly figure
                        fig = go.Figure()

                        # Upper and lower bands (±1σ)
                        upper = trend + sigma
                        lower = trend - sigma

                        fig.add_trace(go.Scatter(
                            x=dates, y=upper,
                            mode='lines',
                            line=dict(width=0),
                            showlegend=False,
                            hoverinfo='skip',
                        ))
                        fig.add_trace(go.Scatter(
                            x=dates, y=lower,
                            mode='lines',
                            line=dict(width=0),
                            fill='tonexty',
                            fillcolor='rgba(69,182,230,0.10)',
                            name='±1σ confidence',
                            hoverinfo='skip',
                        ))

                        # Spread points
                        fig.add_trace(go.Scatter(
                            x=dates, y=spread,
                            mode='markers',
                            name='Spread',
                            marker=dict(color='#7fd1c0', size=5, opacity=0.85),
                        ))

                        # Trend line (cyan hero)
                        fig.add_trace(go.Scatter(
                            x=dates, y=trend,
                            mode='lines',
                            name='Trend (OLS)',
                            line=dict(color='#45b6e6', width=2.5),
                        ))

                        # Update layout with AtlasNexus theme
                        fig.update_layout(
                            paper_bgcolor='#0e1d3a',
                            plot_bgcolor='#0e1d3a',
                            font=dict(family='-apple-system,system-ui,sans-serif', color='#6f83a3', size=12),
                            margin=dict(l=48, r=16, t=30, b=36),
                            hovermode='x unified',
                            xaxis=dict(
                                gridcolor='rgba(255,255,255,0.06)',
                                zeroline=False,
                                linecolor='rgba(255,255,255,0.18)',
                                ticks='outside',
                                tickcolor='rgba(255,255,255,0.18)',
                                tickfont=dict(size=11, color='#6f83a3'),
                                nticks=7,
                            ),
                            yaxis=dict(
                                title=dict(text='Spread (bp)', font=dict(size=11, color='#6f83a3')),
                                gridcolor='rgba(255,255,255,0.06)',
                                zeroline=False,
                                linecolor='rgba(255,255,255,0.18)',
                                ticks='outside',
                                tickcolor='rgba(255,255,255,0.18)',
                                tickfont=dict(size=11, color='#6f83a3'),
                            ),
                            legend=dict(
                                orientation='h', x=0, y=1.06,
                                xanchor='left', yanchor='bottom',
                                bgcolor='rgba(0,0,0,0)', borderwidth=0,
                                font=dict(size=11, color='#6f83a3'),
                            ),
                            showlegend=True,
                        )

                        # Build card
                        card = _build_pair_card(pair.leg1, pair.leg2, stats, fig)
                        cards.append(card)

                    last_updated = f"Last updated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

                except Exception as e:
                    import traceback
                    print(f"Pairs analysis error: {str(e)}")
                    traceback.print_exc()
                    last_updated = f"Error: {str(e)[:100]} at {datetime.datetime.now().strftime('%H:%M:%S')}"
                    cards = [html.Div(f"Error: {str(e)[:120]}", style={'color': THEME['text_sub']})]

            elif trigger_id in {
                "pairs-leg1-1", "pairs-leg2-1",
                "pairs-leg1-2", "pairs-leg2-2",
                "pairs-leg1-3", "pairs-leg2-3",
                "pairs-leg1-4", "pairs-leg2-4",
                "pairs-days-input",
            }:
                last_updated = "Pending changes - click Refresh Plots"
                cards = [html.Div("Waiting for refresh...", style={'color': THEME['text_sub'], 'padding': '40px', 'textAlign': 'center'})]
            else:
                last_updated = f"Last updated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        else:
            last_updated = "Last updated: Loading..."

        # Return cards or placeholder. NOTE: pairs-plots-container is a CSS
        # grid (2x2); the children list must be the cards themselves, not a
        # single wrapper html.Div, otherwise the grid only has one child and
        # the 4 cards stack 4x1 inside it instead of tiling 2x2.
        if not cards:
            content = [html.Div(
                "Click 'Refresh' to generate pair analysis",
                style={'color': THEME['text_sub'], 'padding': '40px', 'textAlign': 'center'},
            )]
        else:
            content = cards

        return content, last_updated

    # Spreads callbacks
    @app.callback(
        Output("alpha-spread-updated-at", "children"),
        Input("data-refresh", "n_intervals"),
        Input("spread-type", "value"),
        Input("alpha-spread-refresh-btn", "n_clicks"),
    )
    def _update_spread_timestamp(_interval, _stype, _refresh_clicks):
        return f"Updated: {datetime.datetime.now().strftime('%H:%M:%S')}"

    @app.callback(
        Output("graph-spread-bar", "figure"),
        Input("data-refresh", "n_intervals"),
        Input("realtime-data", "data"),
        Input("spread-type", "value"),
        Input("alpha-spread-refresh-btn", "n_clicks"),
    )
    def _update_spread_bar(interval, data_rt_js, stype, _refresh_clicks):
        """Update the spread bar chart."""
        if not PLOTTING_AVAILABLE or go is None:
            # Return a simple dict-based figure if plotly isn't available
            return {"data": [], "layout": {"title": "Plotting not available"}}
        
        if not GRAPHS_AVAILABLE or orig_statistics is None:
            return go.Figure(data=[], layout=dict(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                title="Data files not loaded. Please run EOD job to generate data."
            ))
        
        try:
            # Futures spreads render directly from futures-spds.pkl (new pipeline).
            if stype in _FUT_SPREADS:
                return _futures_bar_figure(stype)

            # Check if key exists in data to avoid KeyError
            if data_rt_js:
                data_rt = json.loads(data_rt_js)
                # Handle special cases consistent with web.core.graphs.statistics
                if stype == 'NetBasis':
                    if 'NetBasis' not in data_rt:
                        raise KeyError(f"Data not available for {stype}")
                elif stype not in data_rt or data_rt.get(stype) is None:
                    _misc_spd_key = {'BinarySpread': 'BinarySpread', 'SectorPCASpread': 'PCASpread'}.get(stype)
                    if _misc_spd_key:
                        try:
                            import pandas as pd
                            import re as _re
                            _misc_static = _load_pickle_cached(os.path.join(DIR_INPUT, "Misc-spds.pkl"))
                            if isinstance(_misc_static, Mapping):
                                _bucket = _misc_static.get(_misc_spd_key, {})
                                if isinstance(_bucket, dict):
                                    _spread = _bucket.get('Spread')
                                    _stat = _bucket.get('StatInfo')
                                    if isinstance(_spread, pd.DataFrame) and isinstance(_stat, pd.DataFrame) and not _spread.empty:
                                        _current = _spread.iloc[-1].rename('spread').to_frame()
                                        _current = _current.join(_stat[['mean', 'vol']], how='inner')
                                        _current['Zscore'] = (_current['spread'] - _current['mean']) / _current['vol']
                                        _current['color'] = 'grey'
                                        if stype == 'SectorPCASpread':
                                            _current.index = [_re.sub(r'(-\d+)\.0(Y)$', r'\1\2', idx) for idx in _current.index]
                                        data_rt[stype] = _current.to_dict()
                                        data_rt_js = json.dumps(data_rt)
                        except Exception:
                            pass
                    if stype == 'TenorSpread':
                        try:
                            import pandas as pd
                            _tenor_static = _load_pickle_cached(os.path.join(DIR_INPUT, 'Tenor-spds.pkl'))
                            if isinstance(_tenor_static, Mapping) and 'TenorSpread' in _tenor_static:
                                _ts = _tenor_static['TenorSpread']
                                if isinstance(_ts, dict):
                                    _spread = _ts.get('Spread')
                                    _stat = _ts.get('StatInfo')
                                    if (isinstance(_spread, pd.DataFrame) and not _spread.empty
                                            and isinstance(_stat, pd.DataFrame) and not _stat.empty):
                                        _current = _spread.iloc[-1].rename('spread').to_frame()
                                        _current = _current.join(_stat[['mean', 'vol']], how='inner')
                                        _vol = pd.to_numeric(_current['vol'], errors='coerce').replace(0, float('nan'))
                                        _mean = pd.to_numeric(_current['mean'], errors='coerce')
                                        _current['Zscore'] = (pd.to_numeric(_current['spread'], errors='coerce') - _mean) / _vol
                                        _current['color'] = 'grey'
                                        data_rt['TenorSpread'] = _current.to_dict()
                                        data_rt_js = json.dumps(data_rt)
                        except Exception:
                            pass
                    if stype not in data_rt or data_rt.get(stype) is None:
                        # Return a friendly empty chart instead of crashing
                        return go.Figure(data=[], layout=dict(
                            plot_bgcolor="rgba(0,0,0,0)",
                            paper_bgcolor="rgba(0,0,0,0)",
                            title=f"Waiting for data: {stype}..."
                        ))

            # Forward real data to original implementation
            return orig_statistics(interval, data_rt_js, stype, None)
        except Exception as e:
            print(f"Error in _update_spread_bar: {e}")
            import traceback
            traceback.print_exc()
            empty_figure = go.Figure(data=[], layout=dict(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                title=f"Error: {str(e)[:100]}"
            ))
            return empty_figure

    @app.callback(
        Output("ticker", "children", allow_duplicate=True),
        Input("graph-spread-bar", "clickData"),
        prevent_initial_call=True,
    )
    def _display_click_data(clickData):
        """Handle click events on spread bar chart."""
        from dash.exceptions import PreventUpdate
        if not clickData or "points" not in clickData or not clickData["points"]:
            raise PreventUpdate
        return clickData["points"][0]["label"]

    def _fit_to_frame(fig):
        """Strip any hardcoded height/width so the graph fills its container
        (dcc.Graph has responsive=True + height:100% on the Spread Time Series card).
        Accepts either a go.Figure or a plain {data, layout} dict (spreadts() returns the latter)."""
        try:
            if isinstance(fig, dict):
                layout = fig.setdefault("layout", {})
                layout["height"] = None
                layout["width"] = None
                layout["autosize"] = True
                layout["margin"] = dict(l=50, r=20, t=40, b=40)
            else:
                fig.update_layout(height=None, width=None, autosize=True,
                                   margin=dict(l=50, r=20, t=40, b=40))
        except Exception:
            pass
        return fig

    @app.callback(
        Output("graph-spread", "figure"),
        Input("spread-type", "value"),
        Input("ticker", "children"),
    )
    def _update_spread_ts(stype, ticker):
        """Update the spread time series chart."""
        if not PLOTTING_AVAILABLE or go is None:
            return {"data": [], "layout": {"title": "Plotting not available"}}

        if not GRAPHS_AVAILABLE or orig_spreadts is None:
            return _fit_to_frame(go.Figure(data=[], layout=dict(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                title="Data files not loaded. Please run EOD job to generate data."
            )))

        try:
            # Futures spreads render directly from futures-spds.pkl (new pipeline).
            # These default to the first contract type when no bar is clicked yet.
            if stype in _FUT_SPREADS:
                return _fit_to_frame(_futures_ts_figure(stype, ticker))

            # Handle empty/None ticker gracefully
            if not ticker:
                return _fit_to_frame(go.Figure(data=[], layout=dict(
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    title="Please select a ticker from the bar chart above"
                )))
            return _fit_to_frame(orig_spreadts(stype, None, ticker))
        except Exception as e:
            print(f"Error in _update_spread_ts: {e}")
            import traceback
            traceback.print_exc()
            empty_figure = go.Figure(data=[], layout=dict(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                title=f"Error: {str(e)[:100]}"
            ))
            return _fit_to_frame(empty_figure)

    # Seasonal overlay callback
    @app.callback(
        [
            Output("graph-spread-seasonal", "figure"),
            Output("spread-seasonal-stats", "children"),
        ],
        Input("spread-type", "value"),
        Input("ticker", "children"),
        Input("seasonal-highlight-month", "value"),
        Input("seasonal-years", "value"),
    )
    def _update_seasonal(stype, ticker, highlight_month, n_years):
        from dash.exceptions import PreventUpdate
        from web.tabs.alpha.seasonal import (
            seasonal_pivot,
            monthly_seasonal_stats,
            build_seasonal_overlay_figure,
        )

        _empty_fig = go.Figure(layout=dict(
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            font=dict(color="#ffffff"),
        ))

        if not ticker or not stype:
            return _empty_fig, html.Div()

        n_years = int(n_years or 5)

        # --- Acquire the spread series ---
        series: pd.Series | None = None
        try:
            if stype in _FUT_SPREADS:
                bucket = _fut_stat_bucket(stype)
                if ticker in bucket:
                    series = bucket[ticker][0]  # (series, mean, vol, max, min)
                elif bucket:
                    series = next(iter(bucket.values()))[0]
            else:
                from web.tabs.alpha.data import load_spread_timeseries
                spd_df = load_spread_timeseries(stype)
                if isinstance(spd_df, pd.DataFrame) and not spd_df.empty:
                    if ticker in spd_df.columns:
                        series = spd_df[ticker]
                    elif spd_df.columns.size:
                        series = spd_df.iloc[:, 0]
        except Exception as e:
            print(f"[seasonal] series load error for {stype}/{ticker}: {e}")

        if series is None or series.dropna().empty:
            return _empty_fig, html.Div(
                f"No data for {ticker or stype}",
                style={"color": "#8fb3d9", "fontSize": "11px", "padding": "4px"},
            )

        # --- Compute seasonal statistics ---
        try:
            pivot = seasonal_pivot(series, years=n_years)
            stats = monthly_seasonal_stats(series, min_years=3)
        except Exception as e:
            print(f"[seasonal] compute error: {e}")
            return _empty_fig, html.Div()

        # --- Build overlay figure ---
        try:
            fig = build_seasonal_overlay_figure(
                pivot,
                highlight_month=int(highlight_month) if highlight_month else None,
                stats=stats,
                title=f"{ticker} — seasonal year overlay",
                raw_series=series,
                spread_type=stype,
            )
        except Exception as e:
            print(f"[seasonal] figure error: {e}")
            fig = _empty_fig

        # --- Build stats mini-table ---
        stats_children = html.Div()
        if stats is not None and not stats.empty:
            try:
                _arrow = {"up": "↑", "down": "↓", "neutral": "—"}
                _dir_color = {
                    "up":      "#00cc96",
                    "down":    "#ef553b",
                    "neutral": "#aab0c0",
                }
                rows = []
                for month, row in stats.iterrows():
                    p = row["p_value"]
                    sig = "**" if p < 0.05 else ("*" if p < 0.10 else "")
                    is_hl = (highlight_month and int(month) == int(highlight_month))
                    row_style = {
                        "background": "#1a3a7a" if is_hl else "transparent",
                        "display": "flex",
                        "gap": "12px",
                        "padding": "2px 6px",
                        "borderRadius": "3px",
                    }
                    cell_style = {"fontSize": "11px", "color": "#ffffff", "minWidth": "34px"}
                    sub_style  = {"fontSize": "11px", "color": "#aab0c0", "minWidth": "34px"}
                    dir_c = _dir_color[row["direction"]]
                    rows.append(html.Div([
                        html.Span(row["month_name"], style={**cell_style, "minWidth": "28px"}),
                        html.Span(
                            f"{_arrow[row['direction']]}",
                            style={**cell_style, "color": dir_c, "minWidth": "16px"}
                        ),
                        html.Span(f"{row['consistency']*100:.0f}%{sig}", style={**cell_style, "minWidth": "44px"}),
                        html.Span(f"{row['avg_chg_bp']:+.1f}", style={**cell_style, "minWidth": "44px"}),
                        html.Span(f"n={row['n_years']}", style={**sub_style}),
                        html.Span(f"p={p:.2f}", style={**sub_style}),
                    ], style=row_style))

                header = html.Div([
                    html.Span("Month", style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "28px"}),
                    html.Span("Dir",   style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "16px"}),
                    html.Span("Cons%", style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "44px"}),
                    html.Span("AvgΔ",  style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "44px"}),
                    html.Span("Obs",   style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "34px"}),
                    html.Span("p-val", style={"fontSize": "10px", "color": "#8fb3d9"}),
                ], style={"display": "flex", "gap": "12px", "padding": "2px 6px",
                           "borderBottom": "1px solid #1a3a7a", "marginBottom": "2px"})

                note = html.Div(
                    "* p<0.10  ** p<0.05  (one-sided binomial; no FDR correction applied)",
                    style={"fontSize": "9px", "color": "#8fb3d9", "marginTop": "4px", "padding": "0 6px"},
                )
                stats_children = html.Div([header] + rows + [note],
                                          style={"background": "transparent", "borderRadius": "4px",
                                                 "padding": "6px 0", "marginBottom": "8px"})
            except Exception as e:
                print(f"[seasonal] stats table error: {e}")

        return fig, stats_children

    # Curves callbacks
    @app.callback(
        [
            Output("curves-graph", "figure"),
            Output("curves-title", "children"),
            Output("ref-bonds-container", "style"),
            Output("ref-bonds-t", "data"),
            Output("ref-bonds-t", "columns"),
            Output("curves-chart-subtitle", "children"),
            Output("curves-snapshot", "children"),
        ],
        Input("data-refresh", "n_intervals"),
        Input("curve-selection", "value"),
    )
    def _update_curves(interval, curve_type):
        """Update the curves chart."""
        if not PLOTTING_AVAILABLE or go is None:
            return {"data": [], "layout": {"title": "Plotting not available"}}, "Error", {"display": "none"}, [], [], "", []

        if not GRAPHS_AVAILABLE or orig_curves is None:
            empty_figure = go.Figure(data=[], layout=dict(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                title="Data files not loaded. Please run EOD job to generate data."
            ))
            return empty_figure, "Data Not Available", {"display": "none"}, [], [], "", []

        try:
            return orig_curves(interval, curve_type)
        except Exception as e:
            print(f"Error in _update_curves: {e}")
            import traceback
            traceback.print_exc()
            empty_figure = go.Figure(data=[], layout=dict(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                title=f"Error: {str(e)[:100]}"
            ))
            return empty_figure, "Error Loading Curves", {"display": "none"}, [], [], "", []

