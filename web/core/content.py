"""Layout builders and callback wiring for the FI Engine dashboards."""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from dash import dcc, html, dash_table
from dash.dependencies import Input, Output

from settings.fixed_income import InstitutionConfig
from settings.futures import FuturesConfig
from pairs.main import main as pairs_main
from surface.layout import create_layout as create_surface_layout
from surface.callbacks import register_callbacks as register_surface_callbacks

from .server import app
from .styles import app_color
from .load import GRAPH_INTERVAL, GRAPH_INTERVAL1
from .scripts import initialise, autoruns1, refresh

# Register surface callbacks at module load time (not when tab is built)
# This ensures callbacks exist before the components are rendered
try:
    register_surface_callbacks(app)
except Exception as e:
    print(f"Note: Surface callbacks registration: {e}")
from .graphs import (
    bondcurve,
    irscurve,
    display_click_data,
    trend,
    statistics,
    spreadts,
)


def _interval_block(include_long: bool = False):
    blocks = [
        dcc.Interval(id="data-refresh", interval=int(GRAPH_INTERVAL), n_intervals=0),
    ]
    if include_long:
        blocks.append(
            dcc.Interval(
                id="data-refresh-long", interval=int(GRAPH_INTERVAL1), n_intervals=0
            )
        )
    return html.Div(blocks, className="graph__title")


def build_spread_tab():
    return html.Div([
            html.Div([
                _interval_block(include_long=True),
                html.Div([
                    html.H6("Spread Type"),
                    html.Div([
                        html.H6('Select Institution Type: ', style={"padding-left": "2px"}),
                        dcc.Dropdown(
                            options=InstitutionConfig.INSTITUTION_TYPES,
                            value=InstitutionConfig.INSTITUTION_TYPES[0],
                            id="select-inst",
                        ),
                        html.H6('Sectors', style={"padding-left": "2px", "padding-top": "20px"}),
                        dcc.RadioItems([
                            {'label': ['Institutional Behaviour'], 'value': 'InsPos'},
                            {'label': 'Assets PCA', 'value': 'AssetPCASpread'},
                            {'label': 'Sector PCA', 'value': 'SectorPCASpread'},
                            {'label': ['Spread Regression', html.H6('Bonds', style={"padding-top": "20px"})], 'value': 'BinarySpread'},
                            {'label': 'Treasury Bond', 'value': 'TBondCurve'},
                            {'label': 'Policybank Bond', 'value': 'CBondCurve'},
                            {'label': 'Local Treasury Bond', 'value': 'LBondSpread'},
                            {'label': 'Corporate Bank Bond', 'value': 'BBondSpread'},
                            {'label': 'Government-backed Bond', 'value': 'GBondSpread'},
                            {'label': ['Medium Term Note', html.H6('Swaps', style={"padding-top": "20px"})], 'value': 'MNoteSpread'},
                            {'label': 'Swaps', 'value': 'SwapSpread'},
                            {'label': 'Treasury BondSwap', 'value': 'TBondSwap'},
                            {'label': ['Policybank BondSwap', html.H6('Futures', style={"padding-top": "20px"})], 'value': 'CBondSwap'},
                            {'label': 'Futures Term Basis', 'value': 'TermBasis'},
                            {'label': ['Futures Net Basis'], 'value': 'NetBasis'},
                        ], id="spread-type", value='AssetPCASpread'),
                        dcc.Dropdown(
                            options=list(FuturesConfig.SEASONS.keys()),
                            value=list(FuturesConfig.SEASONS.keys())[0],
                            id="select-season",
                        ),
                    ], className="graph__title"),
                ], className="graph__title"),
            ], className="one-fourth column histogram__container"),
            html.Div([
                html.Div([html.H6("Daily Spread Statistics", className="graph__title")]),
                dcc.Graph(id="graph-spread-bar", figure=dict(layout=dict(
                    plot_bgcolor=app_color["graph_bg"], paper_bgcolor=app_color["graph_bg"],
                ))),
                html.Div([html.H6("Spread Time Series", className="graph__title")]),
                html.Div(id='ticker', className="graph__title"),
                dcc.Graph(id="graph-spread", figure=dict(layout=dict(
                    plot_bgcolor=app_color["graph_bg"], paper_bgcolor=app_color["graph_bg"],
                ))),
            ], className="three-fourths column futures__price__container"),
        ])


def build_curves_tab():
    """Combined Bond and IRS curves tab with dropdown selection."""
    return html.Div([
            html.Div([
                html.Div([
                    html.H6("Curve Type"),
                    dcc.Dropdown(
                        options=[
                            {'label': 'China Government Bond', 'value': 'TBond'},
                            {'label': 'China Policybank Bond', 'value': 'CBond'},
                            {'label': 'IRS Spot Curve', 'value': 'IRSSpot'},
                            {'label': 'IRS Forward Curve', 'value': 'IRSForward'},
                        ],
                        value='TBond',
                        id="curve-selection",
                        style={
                            'backgroundColor': '#082255',
                            'color': '#FFFFFF',
                        },
                        className='custom-dropdown'
                    ),
                    dcc.Interval(id="data-refresh", interval=int(GRAPH_INTERVAL), n_intervals=0),
                ], className="graph__title"),
                html.Div([
                    html.Div(id='ref-bonds', children='Reference Bonds'),
                    dash_table.DataTable(
                        id='ref-bonds-t',
                        style_data={
                            'height': 'auto', 'width': '60px', 'backgroundColor': '#082255', 'color': '#FFFFFF',
                            'textAlign': 'left', 'font-size': '1em',
                        },
                        style_header={
                            'backgroundColor': '#082255', 'color': '#FFFFFF', 'fontWeight': 'bold',
                            'textAlign': 'left', 'font-size': '1em',
                        },
                    ),
                ], className="graph__title", id='ref-bonds-container'),
            ], className="one-fourth column histogram__container"),
            html.Div([
                html.Div([html.H6(id="curves-title", children="Real Time Curves", className="graph__title")]),
                dcc.Graph(id="curves-graph", figure=dict(layout=dict(
                    plot_bgcolor=app_color["graph_bg"], paper_bgcolor=app_color["graph_bg"],
                ))),
            ], className="three-fourths column futures__price__container"),
        ])


def build_bond_tab():
    """Legacy bond tab - kept for backward compatibility."""
    return build_curves_tab()


def build_irs_tab():
    """Legacy IRS tab - kept for backward compatibility."""
    return build_curves_tab()


def build_trend_tab():
    return html.Div([
            html.Div([
                html.Div([
                    html.H6("Chinabond/IRS Trend Type"),
                    dcc.RadioItems([
                        {'label': '1Y Treasury', 'value': '中债国债到期收益率:1年'},
                        {'label': '5Y Treasury', 'value': '中债国债到期收益率:5年'},
                        {'label': '10Y Treasury', 'value': '中债国债到期收益率:10年'},
                        {'label': '30Y Treasury', 'value': '中债国债到期收益率:30年'},
                        {'label': '5Y-1Y Treasury', 'value': '中债国债到期收益率:5年-1年'},
                        {'label': '10Y-5Y Treasury', 'value': '中债国债到期收益率:10年-5年'},
                        {'label': '30Y-10Y Treasury', 'value': '中债国债到期收益率:30年-10年'},
                        {'label': '1Y FR007', 'value': 'FR007S1Y.IR'},
                        {'label': '2Y FR007', 'value': 'FR007S2Y.IR'},
                        {'label': '5Y FR007', 'value': 'FR007S5Y.IR'},
                        {'label': '2Y-1Y FR007', 'value': 'FR007:2Y-1Y'},
                        {'label': '5Y-2Y FR007', 'value': 'FR007:5Y-2Y'},
                        {'label': '5Y-1Y FR007', 'value': 'FR007:5Y-1Y'},
                        {'label': 'TBond-FR007:1Y', 'value': 'TBond-FR007:1Y'},
                        {'label': 'TBond-FR007:5Y', 'value': 'TBond-FR007:5Y'},
                    ], id="trend-type", value='中债国债到期收益率:10年'),
                    dcc.Interval(id="data-refresh", interval=int(GRAPH_INTERVAL), n_intervals=0),
                ], className="graph__title"),
            ], className="one-fourth column histogram__container"),
            html.Div([
                html.Div([html.H6("Trends", className="graph__title")]),
                dcc.Graph(id="trend-graph", figure=dict(layout=dict(
                    plot_bgcolor=app_color["graph_bg"], paper_bgcolor=app_color["graph_bg"],
                ))),
            ], className="three-fourths column futures__price__container"),
        ])


def build_pairs_tab():
    """Build the Pairs analysis tab with embedded regression plots."""
    return html.Div([
        html.Div([
            html.Div([
                html.H6("Pairs Analysis", className="graph__title"),
                html.P("Interactive spread analysis with confidence bands (in basis points)", 
                       style={"color": "#ffffff", "font-size": "14px", "margin": "10px 0"}),
                # Control panel for refresh
                html.Div([
                    html.Button("🔄 Refresh Plots", 
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
                                   "margin": "10px 0"
                               }),
                    html.Div(id="pairs-last-updated", 
                             children="Last updated: Loading...",
                             style={"color": "#ffffff", "font-size": "12px", "margin": "5px 0"})
                ], style={"margin": "15px 0"})
            ], className="graph__title")
        ], className="one-fourth column histogram__container"),
        
        # Main content area with pairs plots
        html.Div([
            # Load external CSS and JS for Plotly if needed
            html.Link(rel="stylesheet", href="https://cdn.plot.ly/plotly-latest.min.js"),
            
            html.Div([
                html.H6("Real-time Pair Analysis", className="graph__title",
                       style={"color": "#ffffff", "background": app_color["graph_bg"], "padding": "10px"})
            ]),
            
            # Container for the plots with appropriate styling
            html.Div(
                id="pairs-plots-container",
                style={
                    "background": app_color["graph_bg"],
                    "border-radius": "8px",
                    "padding": "20px",
                    "min-height": "600px"
                },
                children=[
                    html.Div([
                        html.H4("Loading Pairs Analysis...", 
                               style={"text-align": "center", "color": "#666", "margin": "50px 0"}),
                        html.P("Please wait while we load the regression plots.", 
                               style={"text-align": "center", "color": "#999"})
                    ])
                ]
            ),
            
            # Hidden component to trigger loading of external content
            html.Div(id="pairs-content-loader", style={"display": "none"})
            
        ], className="three-fourths column futures__price__container")
    ])


@app.callback(
    [Output('pairs-plots-container', 'children'),
     Output('pairs-last-updated', 'children')],
    [Input('pairs-content-loader', 'children'),
     Input('pairs-refresh-btn', 'n_clicks')]
)
def load_pairs_content(_, n_clicks):
    """Load the pairs regression plots content and handle refresh requests."""
    import datetime
    from dash import callback_context
    
    # Check if this was triggered by the refresh button
    if callback_context.triggered:
        trigger_id = callback_context.triggered[0]['prop_id']
        if 'pairs-refresh-btn' in trigger_id and n_clicks and n_clicks > 0:
            try:
                # Import and call the main function directly from pairs.main
                # Try to find Dashboard.xlsm for configuration
                dashboard_path = project_root.parent / "Dashboard.xlsm"
                
                if dashboard_path.exists():
                    # Call with Excel path for configuration loading, but in non-interactive mode
                    pairs_main(excel_mode=False, excel_path=str(dashboard_path))
                else:
                    # Try alternate location
                    alt_dashboard = project_root / "Dashboard.xlsm"
                    if alt_dashboard.exists():
                        pairs_main(excel_mode=False, excel_path=str(alt_dashboard))
                    else:
                        # Fall back to standalone mode without Excel
                        print("⚠ Dashboard.xlsm not found, running in standalone mode")
                        pairs_main(excel_mode=False, excel_path=None)
                
                last_updated = f"Last updated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            except ImportError as e:
                print(f"Error importing pairs.main: {e}")
                last_updated = f"Error: Could not import pairs.main at {datetime.datetime.now().strftime('%H:%M:%S')}"
            except Exception as e:
                print(f"Error running pairs analysis: {e}")
                import traceback
                traceback.print_exc()
                last_updated = f"Error: {str(e)[:100]} at {datetime.datetime.now().strftime('%H:%M:%S')}"
        else:
            last_updated = f"Last updated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    else:
        last_updated = "Last updated: Loading..."
    
    # Load the iframe content (same logic as before)
    try:
        pairs_html_path = project_root / "pairs" / "regression_plots.html"
        
        if pairs_html_path.exists():
            # Add a cache-busting parameter to force iframe reload
            cache_buster = f"?v={datetime.datetime.now().timestamp()}"
            iframe_content = html.Div([
                html.Iframe(
                    id="pairs-iframe",
                    src=f"/pairs/regression_plots.html{cache_buster}",
                    # Hide scrollbars within the iframe to avoid a left-side scroll next to subfigures
                    style={
                        "width": "100%",
                        "height": "720px",
                        "border": "1px solid #ddd",
                        "border-radius": "4px",
                        "overflow": "hidden"
                    }
                )
            ], style={"overflow": "hidden"})
        else:
            iframe_content = html.Div([
                html.H4("Pairs Analysis", style={"color": "#333", "margin-bottom": "20px"}),
                html.P("The pairs regression plots file is not available at the moment.", 
                       style={"color": "#666"}),
                html.P("Please ensure the pairs analysis has been run and the regression_plots.html file exists.",
                       style={"color": "#666", "font-size": "14px"})
            ])
    except Exception as e:
        iframe_content = html.Div([
            html.H4("Error Loading Pairs Content", style={"color": "#d32f2f"}),
            html.P(f"An error occurred: {str(e)}", style={"color": "#666"})
        ])
    
    return iframe_content, last_updated


def build_surfaces_tab():
    """Build the Surfaces tab with yield curve visualization."""
    # Return the surface layout directly (callbacks are registered at module level)
    return create_surface_layout()


@app.callback(Output('tabs-content-graph', 'children'),
              Input('tabs-graph', 'value'))
def content(tab):
    if tab == 'tab-1-graph':
        return build_spread_tab()
    elif tab == 'tab-2-graph':  # Combined CURVES tab
        return build_curves_tab()
    elif tab == 'tab-3-graph':
        return build_pairs_tab()
    elif tab == 'tab-4-graph':
        return build_surfaces_tab()
    elif tab == 'tab-5-graph':
        return build_trend_tab()
    return build_trend_tab()
