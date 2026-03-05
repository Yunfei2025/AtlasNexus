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
            # Hidden store for realtime data
            dcc.Store(id="realtime-data"),
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
                                className="custom-dropdown",
                                style={'color': '#000'}
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
            # Top Section: Configuration
            html.Div(
                [
                    html.Div(
                        [
                            html.H6("Pairs Analysis", className="graph__title"),
                            html.P(
                                "Interactive spread analysis with confidence bands (in basis points)",
                                style={"color": "#ffffff", "font-size": "14px", "margin": "10px 0"},
                            ),
                            
                            # Pairs configuration table
                            html.Div([
                                html.Table([
                                    html.Thead(html.Tr([
                                        html.Th("", style={"color": "#ffffff", "padding": "8px", "text-align": "left", "min-width": "50px"}),
                                        html.Th("Pair 1", style={"color": "#ffffff", "padding": "8px", "text-align": "center", "min-width": "120px"}),
                                        html.Th("Pair 2", style={"color": "#ffffff", "padding": "8px", "text-align": "center", "min-width": "120px"}),
                                        html.Th("Pair 3", style={"color": "#ffffff", "padding": "8px", "text-align": "center", "min-width": "120px"}),
                                        html.Th("Pair 4", style={"color": "#ffffff", "padding": "8px", "text-align": "center", "min-width": "120px"}),
                                    ])),
                                    html.Tbody([
                                        html.Tr([
                                            html.Td("Leg1", style={"color": "#ffffff", "padding": "8px", "font-weight": "bold"}),
                                            html.Td(dcc.Input(id='pairs-leg1-1', value='250211.IB', type='text', 
                                                             style={"width": "100%", "padding": "6px", "background": "#1e3a5f", "color": "#fff", "border": "1px solid #007ACE", "border-radius": "3px"})),
                                            html.Td(dcc.Input(id='pairs-leg1-2', value='250020.IB', type='text',
                                                             style={"width": "100%", "padding": "6px", "background": "#1e3a5f", "color": "#fff", "border": "1px solid #007ACE", "border-radius": "3px"})),
                                            html.Td(dcc.Input(id='pairs-leg1-3', value='250215.IB', type='text',
                                                             style={"width": "100%", "padding": "6px", "background": "#1e3a5f", "color": "#fff", "border": "1px solid #007ACE", "border-radius": "3px"})),
                                            html.Td(dcc.Input(id='pairs-leg1-4', value='2500006.IB', type='text',
                                                             style={"width": "100%", "padding": "6px", "background": "#1e3a5f", "color": "#fff", "border": "1px solid #007ACE", "border-radius": "3px"})),
                                        ]),
                                        html.Tr([
                                            html.Td("Leg2", style={"color": "#ffffff", "padding": "8px", "font-weight": "bold"}),
                                            html.Td(dcc.Input(id='pairs-leg2-1', value='240024.IB', type='text',
                                                             style={"width": "100%", "padding": "6px", "background": "#1e3a5f", "color": "#fff", "border": "1px solid #007ACE", "border-radius": "3px"})),
                                            html.Td(dcc.Input(id='pairs-leg2-2', value='FR007S5Y.IR', type='text',
                                                             style={"width": "100%", "padding": "6px", "background": "#1e3a5f", "color": "#fff", "border": "1px solid #007ACE", "border-radius": "3px"})),
                                            html.Td(dcc.Input(id='pairs-leg2-3', value='250018.IB', type='text',
                                                             style={"width": "100%", "padding": "6px", "background": "#1e3a5f", "color": "#fff", "border": "1px solid #007ACE", "border-radius": "3px"})),
                                            html.Td(dcc.Input(id='pairs-leg2-4', value='210005.IB', type='text',
                                                             style={"width": "100%", "padding": "6px", "background": "#1e3a5f", "color": "#fff", "border": "1px solid #007ACE", "border-radius": "3px"})),
                                        ]),
                                    ])
                                ], style={"width": "100%", "border-collapse": "collapse", "margin": "10px 0"}),
                                
                                html.Div([
                                    html.Label("Days:", style={"color": "#ffffff", "margin-right": "10px", "font-weight": "bold"}),
                                    dcc.Input(
                                        id='pairs-days-input',
                                        type='number',
                                        value=90,
                                        min=1,
                                        style={"width": "80px", "padding": "6px", "background": "#1e3a5f", "color": "#fff", "border": "1px solid #007ACE", "border-radius": "3px"}
                                    ),
                                ], style={"margin": "10px 0", "display": "flex", "align-items": "center"}),
                            ], style={"margin": "15px 0", "padding": "15px", "background": "#0f2847", "border-radius": "5px"}),
                            
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
                                            "padding": "10px 20px",
                                            "border-radius": "4px",
                                            "cursor": "pointer",
                                            "font-size": "14px",
                                            "margin": "10px 0",
                                            "font-weight": "bold",
                                        },
                                    ),
                                    html.Div(
                                        id="pairs-last-updated",
                                        children="Last updated: Loading...",
                                        style={"color": "#ffffff", "font-size": "12px", "margin": "10px 0"},
                                    ),
                                ],
                                style={"margin": "15px 0"},
                            ),
                        ],
                        className="graph__title",
                    )
                ],
                style={
                    "background": app_color["graph_bg"],
                    "border-radius": "8px",
                    "padding": "20px",
                    "margin-bottom": "20px",
                },
            ),
            
            # Bottom Section: Real-time Pair Analysis Results
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
                style={
                    "width": "100%",
                },
            ),
        ]
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
    from settings.general import DIR_INPUT
    from settings.fixed_income import BondConfig
    
    # Import plotting dependencies at function level to catch errors early
    try:
        import plotly.graph_objs as go
        from web.core.styles import app_color
        PLOTTING_AVAILABLE = True
    except Exception as e:
        print(f"Warning: Plotting dependencies not available: {e}")
        PLOTTING_AVAILABLE = False
        app_color = {"graph_bg": "#082255", "graph_line": "#007ACE"}
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
        [Input("pairs-content-loader", "children"), Input("pairs-refresh-btn", "n_clicks")],
        [State("pairs-leg1-1", "value"), State("pairs-leg2-1", "value"),
         State("pairs-leg1-2", "value"), State("pairs-leg2-2", "value"),
         State("pairs-leg1-3", "value"), State("pairs-leg2-3", "value"),
         State("pairs-leg1-4", "value"), State("pairs-leg2-4", "value"),
         State("pairs-days-input", "value")],
    )
    def _load_pairs_content(_, n_clicks, leg1_1, leg2_1, leg1_2, leg2_2, leg1_3, leg2_3, leg1_4, leg2_4, window_days):
        # Re-run pairs analysis using input parameters when refresh clicked
        if callback_context.triggered:
            trigger_id = callback_context.triggered[0]["prop_id"]
            if "pairs-refresh-btn" in trigger_id and n_clicks and n_clicks > 0:
                try:
                    from pairs.manager import PairManager
                    from pairs.dashboard import Dashboard
                    
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
                    
                    # Generate dashboard HTML
                    project_root = Path(__file__).resolve().parents[1]
                    output_path = project_root / "pairs" / "regression_plots.html"
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    dashboard_gen = Dashboard()
                    pairs_data = {}
                    for pair_name, pair in manager.pairs.items():
                        if pair_name in analyses:
                            pairs_data[pair_name] = {
                                'name': pair_name,
                                'leg1': pair.leg1,
                                'leg2': pair.leg2,
                                'spread_df': analyses[pair_name]['spread_df'],
                                'regression_result': analyses[pair_name]['regression_result']
                            }
                    
                    dashboard_gen.create_unified_dashboard(pairs_data, str(output_path))

                    last_updated = f"Last updated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                except Exception as e:
                    import traceback
                    error_msg = f"Error: {str(e)}"
                    print(f"Pairs analysis error: {error_msg}")
                    print(traceback.format_exc())
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

    # Spreads callbacks
    @app.callback(
        Output("graph-spread-bar", "figure"),
        Input("data-refresh", "n_intervals"),
        Input("realtime-data", "data"),
        Input("spread-type", "value"),
        Input("select-inst", "value"),
        Input("select-season", "value"),
    )
    def _update_spread_bar(interval, data_rt_js, stype, inst, season):
        """Update the spread bar chart."""
        if not PLOTTING_AVAILABLE or go is None:
            # Return a simple dict-based figure if plotly isn't available
            return {"data": [], "layout": {"title": "Plotting not available"}}
        
        if not GRAPHS_AVAILABLE or orig_statistics is None:
            return go.Figure(data=[], layout=dict(
                plot_bgcolor=app_color["graph_bg"],
                paper_bgcolor=app_color["graph_bg"],
                title="Data files not loaded. Please run EOD job to generate data."
            ))
        
        try:
            # Check if key exists in data to avoid KeyError
            if data_rt_js:
                data_rt = json.loads(data_rt_js)
                # Handle special cases consistent with web.core.graphs.statistics
                if stype == 'InsPos':
                    if 'InsPos' not in data_rt:
                        raise KeyError(f"Data not available for {stype}")
                elif stype == 'NetBasis':
                    if 'NetBasis' not in data_rt:
                        raise KeyError(f"Data not available for {stype}")
                elif stype not in data_rt:
                    # Return a friendly empty chart instead of crashing
                    return go.Figure(data=[], layout=dict(
                        plot_bgcolor=app_color["graph_bg"],
                        paper_bgcolor=app_color["graph_bg"],
                        title=f"Waiting for data: {stype}..."
                    ))

            # Forward real data to original implementation
            return orig_statistics(interval, data_rt_js, stype, inst, season)
        except Exception as e:
            print(f"Error in _update_spread_bar: {e}")
            import traceback
            traceback.print_exc()
            empty_figure = go.Figure(data=[], layout=dict(
                plot_bgcolor=app_color["graph_bg"],
                paper_bgcolor=app_color["graph_bg"],
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

    @app.callback(
        Output("graph-spread", "figure"),
        Input("spread-type", "value"),
        Input("select-inst", "value"),
        Input("select-season", "value"),
        Input("ticker", "children"),
    )
    def _update_spread_ts(stype, inst, season, ticker):
        """Update the spread time series chart."""
        if not PLOTTING_AVAILABLE or go is None:
            return {"data": [], "layout": {"title": "Plotting not available"}}
        
        if not GRAPHS_AVAILABLE or orig_spreadts is None:
            return go.Figure(data=[], layout=dict(
                plot_bgcolor=app_color["graph_bg"],
                paper_bgcolor=app_color["graph_bg"],
                title="Data files not loaded. Please run EOD job to generate data."
            ))
        
        try:
            # Handle empty/None ticker gracefully
            if not ticker:
                return go.Figure(data=[], layout=dict(
                    plot_bgcolor=app_color["graph_bg"],
                    paper_bgcolor=app_color["graph_bg"],
                    title="Please select a ticker from the bar chart above"
                ))
            return orig_spreadts(stype, inst, season, ticker)
        except Exception as e:
            print(f"Error in _update_spread_ts: {e}")
            import traceback
            traceback.print_exc()
            empty_figure = go.Figure(data=[], layout=dict(
                plot_bgcolor=app_color["graph_bg"],
                paper_bgcolor=app_color["graph_bg"],
                title=f"Error: {str(e)[:100]}"
            ))
            return empty_figure

    # Curves callbacks
    @app.callback(
        [
            Output("curves-graph", "figure"),
            Output("curves-title", "children"),
            Output("ref-bonds-container", "style"),
        ],
        Input("data-refresh", "n_intervals"),
        Input("curve-selection", "value"),
    )
    def _update_curves(interval, curve_type):
        """Update the curves chart."""
        if not PLOTTING_AVAILABLE or go is None:
            return {"data": [], "layout": {"title": "Plotting not available"}}, "Error", {"display": "none"}
        
        if not GRAPHS_AVAILABLE or orig_curves is None:
            empty_figure = go.Figure(data=[], layout=dict(
                plot_bgcolor=app_color["graph_bg"],
                paper_bgcolor=app_color["graph_bg"],
                title="Data files not loaded. Please run EOD job to generate data."
            ))
            return empty_figure, "Data Not Available", {"display": "none"}
        
        try:
            return orig_curves(interval, curve_type)
        except Exception as e:
            print(f"Error in _update_curves: {e}")
            import traceback
            traceback.print_exc()
            empty_figure = go.Figure(data=[], layout=dict(
                plot_bgcolor=app_color["graph_bg"],
                paper_bgcolor=app_color["graph_bg"],
                title=f"Error: {str(e)[:100]}"
            ))
            return empty_figure, "Error Loading Curves", {"display": "none"}

