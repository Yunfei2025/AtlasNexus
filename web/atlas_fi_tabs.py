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
from dash.dependencies import Input, Output


def build_spreads_layout():
    """Build the legacy 'Spread Info' layout."""
    # Local imports to keep module import light
    from settings.fixed_income import InstitutionConfig
    from settings.futures import FuturesConfig
    from web.core.styles import app_color  # styles only; ok

    # Import intervals from web.core.load is heavy (loads pickles). Avoid.
    # Use reasonable defaults for refresh intervals.
    GRAPH_INTERVAL = 60_000
    GRAPH_INTERVAL_LONG = 300_000

    def _interval_block(include_long: bool = False):
        blocks = [dcc.Interval(id="data-refresh", interval=int(GRAPH_INTERVAL), n_intervals=0)]
        if include_long:
            blocks.append(
                dcc.Interval(id="data-refresh-long", interval=int(GRAPH_INTERVAL_LONG), n_intervals=0)
            )
        return html.Div(blocks, className="graph__title")

    return html.Div(
        [
            html.Div(
                [
                    _interval_block(include_long=True),
                    html.Div(
                        [
                            html.H6("Spread Type"),
                            html.Div(
                                [
                                    html.H6("Select Institution Type: ", style={"padding-left": "2px"}),
                                    dcc.Dropdown(
                                        options=InstitutionConfig.INSTITUTION_TYPES,
                                        value=InstitutionConfig.INSTITUTION_TYPES[0],
                                        id="select-inst",
                                    ),
                                    html.H6("Sectors", style={"padding-left": "2px", "padding-top": "20px"}),
                                    dcc.RadioItems(
                                        [
                                            {"label": ["Institutional Behaviour"], "value": "InsPos"},
                                            {"label": "Assets PCA", "value": "AssetPCASpread"},
                                            {"label": "Sector PCA", "value": "SectorPCASpread"},
                                            {
                                                "label": [
                                                    "Spread Regression",
                                                    html.H6("Bonds", style={"padding-top": "20px"}),
                                                ],
                                                "value": "BinarySpread",
                                            },
                                            {"label": "Treasury Bond", "value": "TBondCurve"},
                                            {"label": "Policybank Bond", "value": "CBondCurve"},
                                            {"label": "Local Treasury Bond", "value": "LBondSpread"},
                                            {"label": "Corporate Bank Bond", "value": "BBondSpread"},
                                            {"label": "Government-backed Bond", "value": "GBondSpread"},
                                            {
                                                "label": [
                                                    "Medium Term Note",
                                                    html.H6("Swaps", style={"padding-top": "20px"}),
                                                ],
                                                "value": "MNoteSpread",
                                            },
                                            {"label": "Swaps", "value": "SwapSpread"},
                                            {"label": "Treasury BondSwap", "value": "TBondSwap"},
                                            {
                                                "label": [
                                                    "Policybank BondSwap",
                                                    html.H6("Futures", style={"padding-top": "20px"}),
                                                ],
                                                "value": "CBondSwap",
                                            },
                                            {"label": "Futures Term Basis", "value": "TermBasis"},
                                            {"label": ["Futures Net Basis"], "value": "NetBasis"},
                                        ],
                                        id="spread-type",
                                        value="AssetPCASpread",
                                    ),
                                    dcc.Dropdown(
                                        options=list(FuturesConfig.SEASONS.keys()),
                                        value=list(FuturesConfig.SEASONS.keys())[0],
                                        id="select-season",
                                    ),
                                ],
                                className="graph__title",
                            ),
                        ],
                        className="graph__title",
                    ),
                ],
                className="one-fourth column histogram__container",
            ),
            html.Div(
                [
                    html.Div([html.H6("Daily Spread Statistics", className="graph__title")]),
                    dcc.Graph(
                        id="graph-spread-bar",
                        figure=dict(
                            layout=dict(
                                plot_bgcolor=app_color["graph_bg"], paper_bgcolor=app_color["graph_bg"]
                            )
                        ),
                    ),
                    html.Div([html.H6("Spread Time Series", className="graph__title")]),
                    html.Div(id="ticker", className="graph__title"),
                    dcc.Graph(
                        id="graph-spread",
                        figure=dict(
                            layout=dict(
                                plot_bgcolor=app_color["graph_bg"], paper_bgcolor=app_color["graph_bg"]
                            )
                        ),
                    ),
                ],
                className="three-fourths column futures__price__container",
            ),
        ]
    )


def build_curves_layout():
    """Build the legacy 'CURVES' tab layout."""
    from web.core.styles import app_color

    GRAPH_INTERVAL = 60_000

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.H6("Curve Type"),
                            dcc.Dropdown(
                                options=[
                                    {"label": "China Government Bond", "value": "TBond"},
                                    {"label": "China Policybank Bond", "value": "CBond"},
                                    {"label": "IRS Spot Curve", "value": "IRSSpot"},
                                    {"label": "IRS Forward Curve", "value": "IRSForward"},
                                ],
                                value="TBond",
                                id="curve-selection",
                                style={
                                    "backgroundColor": "#082255",
                                    "color": "#FFFFFF",
                                },
                                className="custom-dropdown",
                            ),
                            dcc.Interval(id="data-refresh", interval=int(GRAPH_INTERVAL), n_intervals=0),
                        ],
                        className="graph__title",
                    ),
                    html.Div(
                        [
                            html.Div(id="ref-bonds", children="Reference Bonds"),
                            dash_table.DataTable(
                                id="ref-bonds-t",
                                style_data={
                                    "height": "auto",
                                    "width": "60px",
                                    "backgroundColor": "#082255",
                                    "color": "#FFFFFF",
                                    "textAlign": "left",
                                    "font-size": "1em",
                                },
                                style_header={
                                    "backgroundColor": "#082255",
                                    "color": "#FFFFFF",
                                    "fontWeight": "bold",
                                    "textAlign": "left",
                                    "font-size": "1em",
                                },
                            ),
                        ],
                        className="graph__title",
                        id="ref-bonds-container",
                    ),
                ],
                className="one-fourth column histogram__container",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.H6(
                                id="curves-title",
                                children="Real Time Curves",
                                className="graph__title",
                            )
                        ]
                    ),
                    dcc.Graph(
                        id="curves-graph",
                        figure=dict(
                            layout=dict(
                                plot_bgcolor=app_color["graph_bg"], paper_bgcolor=app_color["graph_bg"]
                            )
                        ),
                    ),
                ],
                className="three-fourths column futures__price__container",
            ),
        ]
    )


def build_pairs_layout():
    """Build the legacy 'Pairs' tab layout."""
    from web.core.styles import app_color

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.H6("Pairs Analysis", className="graph__title"),
                            html.P(
                                "Interactive spread analysis with confidence bands (in basis points)",
                                style={"color": "#ffffff", "font-size": "14px", "margin": "10px 0"},
                            ),
                            html.Div(
                                [
                                    html.Button(
                                        "🔄 Refresh Plots",
                                        id="pairs-refresh-btn",
                                        n_clicks=0,
                                        style={
                                            "background": "#007ACE",
                                            "color": "white",
                                            "border": "none",
                                            "padding": "8px 16px",
                                            "border-radius": "4px",
                                            "cursor": "pointer",
                                            "font-size": "14px",
                                            "margin": "10px 0",
                                        },
                                    ),
                                    html.Div(
                                        id="pairs-last-updated",
                                        children="Last updated: Loading...",
                                        style={"color": "#ffffff", "font-size": "12px", "margin": "5px 0"},
                                    ),
                                ],
                                style={"margin": "15px 0"},
                            ),
                        ],
                        className="graph__title",
                    )
                ],
                className="one-fourth column histogram__container",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.H6(
                                "Real-time Pair Analysis",
                                className="graph__title",
                                style={"color": "#ffffff", "background": app_color["graph_bg"], "padding": "10px"},
                            )
                        ]
                    ),
                    html.Div(
                        id="pairs-plots-container",
                        style={
                            "background": app_color["graph_bg"],
                            "border-radius": "8px",
                            "padding": "20px",
                            "min-height": "600px",
                        },
                        children=[
                            html.Div(
                                [
                                    html.H4(
                                        "Loading Pairs Analysis...",
                                        style={"text-align": "center", "color": "#666", "margin": "50px 0"},
                                    ),
                                    html.P(
                                        "Please wait while we load the regression plots.",
                                        style={"text-align": "center", "color": "#999"},
                                    ),
                                ]
                            )
                        ],
                    ),
                    html.Div(id="pairs-content-loader", style={"display": "none"}),
                ],
                className="three-fourths column futures__price__container",
            ),
        ]
    )


def register_callbacks(app) -> None:
    """Register the callbacks required by the migrated layouts onto `app`."""

    @app.callback(
        [Output("pairs-plots-container", "children"), Output("pairs-last-updated", "children")],
        [Input("pairs-content-loader", "children"), Input("pairs-refresh-btn", "n_clicks")],
    )
    def _load_pairs_content(_, n_clicks):
        import datetime
        from dash import callback_context

        # Optional: re-run pairs analysis when refresh clicked
        if callback_context.triggered:
            trigger_id = callback_context.triggered[0]["prop_id"]
            if "pairs-refresh-btn" in trigger_id and n_clicks and n_clicks > 0:
                try:
                    from pairs.main import main as pairs_main

                    # Try to find Dashboard.xlsm for configuration
                    project_root = Path(__file__).resolve().parents[1]
                    dashboard_path = project_root / "Dashboard.xlsm"
                    if dashboard_path.exists():
                        pairs_main(excel_mode=False, excel_path=str(dashboard_path))
                    else:
                        pairs_main(excel_mode=False, excel_path=None)

                    last_updated = f"Last updated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                except Exception as e:
                    last_updated = f"Error: {str(e)[:120]} at {datetime.datetime.now().strftime('%H:%M:%S')}"
            else:
                last_updated = f"Last updated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        else:
            last_updated = "Last updated: Loading..."

        # Prefer local file if available
        try:
            project_root = Path(__file__).resolve().parents[1]
            pairs_html_path = project_root / "pairs" / "regression_plots.html"
            if pairs_html_path.exists():
                cache_buster = f"?v={datetime.datetime.now().timestamp()}"
                iframe_content = html.Div(
                    [
                        html.Iframe(
                            id="pairs-iframe",
                            src=f"/pairs/regression_plots.html{cache_buster}",
                            style={
                                "width": "100%",
                                "height": "720px",
                                "border": "1px solid #ddd",
                                "border-radius": "4px",
                                "overflow": "hidden",
                            },
                        )
                    ],
                    style={"overflow": "hidden"},
                )
            else:
                iframe_content = html.Div(
                    [
                        html.H4("Pairs Analysis", style={"color": "#333", "margin-bottom": "20px"}),
                        html.P(
                            "The pairs regression plots file is not available at the moment.",
                            style={"color": "#666"},
                        ),
                        html.P(
                            "Please ensure the pairs analysis has been run and the regression_plots.html file exists.",
                            style={"color": "#666", "font-size": "14px"},
                        ),
                    ]
                )
        except Exception as e:
            iframe_content = html.Div(
                [
                    html.H4("Error Loading Pairs Content", style={"color": "#d32f2f"}),
                    html.P(f"An error occurred: {str(e)}", style={"color": "#666"}),
                ]
            )

        return iframe_content, last_updated
