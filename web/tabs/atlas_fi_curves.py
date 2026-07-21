"""Curves tab (Market > Curves).

Provides `build_curves_layout()` and `register_curves_callbacks(app)` for the
legacy "Curves" dashboard content, migrated from `web.core.content` onto the
AtlasNexus Dash app instance.
"""

from __future__ import annotations

from dash import dcc, html, dash_table
from dash.dependencies import Input, Output


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


def register_curves_callbacks(app) -> None:
    """Register the callbacks required by `build_curves_layout()` onto `app`."""
    # Import plotting dependencies at function level to catch errors early
    try:
        import plotly.graph_objs as go
        PLOTTING_AVAILABLE = True
    except Exception as e:
        print(f"Warning: Plotting dependencies not available: {e}")
        PLOTTING_AVAILABLE = False
        go = None

    # Try to import web.core modules (they might fail if data files are missing)
    try:
        from web.core.graphs import curves_graph as orig_curves
        GRAPHS_AVAILABLE = True
    except Exception as e:
        print(f"Warning: web.core.graphs not available (data files may be missing): {e}")
        GRAPHS_AVAILABLE = False
        orig_curves = None

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
