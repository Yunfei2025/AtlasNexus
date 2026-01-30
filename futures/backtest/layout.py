"""
Dashboard layout module
Contains Dash application UI layout definitions
"""

from dash import dcc, html
import dash_bootstrap_components as dbc
from datetime import datetime, timedelta
from data_loader import discover_pkl_files

# Style definitions
SIDEBAR_STYLE = {
    "position": "fixed",
    "top": 0,
    "left": 0,
    "bottom": 0,
    "width": "320px",
    "padding": "2rem 1rem",
    "background-color": "#082255",  # Dark blue background
    "color": "white",               # White text
    "overflow-y": "auto",
    "font-family": '"Open Sans", sans-serif' # Consistent font
}

CONTENT_STYLE = {
    "margin-left": "340px",
    "padding": "2rem 1rem",
    "font-family": '"Open Sans", sans-serif'
}

CARD_STYLE = {
    "border": "1px solid #e0e0e0",
    "border-radius": "5px",
    "padding": "10px",
    "margin": "5px",
    "background-color": "white",
    "box-shadow": "0 2px 4px rgba(0,0,0,0.05)",
    "flex": "1"
}

# Custom styles for dark theme components
DARK_CARD_STYLE = {
    "background-color": "#0f3174", 
    "border": "1px solid #007ACE",
    "color": "white"
}

DARK_INPUT_STYLE = {
    "background-color": "#061E44",
    "color": "white",
    "border": "1px solid #007ACE"
}


def create_metric_card(title, metrics):
    """Create metric card"""
    return html.Div([
        html.H4(title, style={'margin-bottom': '10px', 'font-size': '16px', 'color': '#555'}),
        html.Div([
            html.Div(f"Total Return: {metrics.get('Total Return', 'N/A')}", style={'font-weight': 'bold'}),
            html.Div(f"Drawdown: {metrics.get('Max Drawdown', 'N/A')}"),
            html.Div(f"Sharpe: {metrics.get('Sharpe Ratio', 'N/A')}"),
            html.Div(f"Trades: {metrics.get('Trades', 'N/A')}"),
        ])
    ], style=CARD_STYLE)


def create_sidebar():
    """Create sidebar layout"""
    # Get file list (supports input/ and data/futures/)
    pkl_options = discover_pkl_files()
    
    sidebar = html.Div(
        [
            html.H4("Strategy Config", className="display-6", style={'text-align': 'center', 'margin-bottom': '20px', 'color': 'white', 'letter-spacing': '0.1rem'}),
            
            # Data Settings Section
            dbc.Card([
                dbc.CardHeader("Data Settings", className="fw-bold", style={'padding': '5px 10px', 'background-color': '#007ACE', 'color': 'white'}),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Label("Source", style={'font-size': '0.9rem'}),
                            dcc.RadioItems(
                                id='data-source',
                                options=[{'label': ' Local', 'value': 'local'}, {'label': ' Wind', 'value': 'wind'}],
                                value='local',
                                labelStyle={'display': 'block', 'font-size': '0.9rem'},
                                inputStyle={"margin-right": "5px"}
                            )
                        ], width=6),
                        dbc.Col([
                            html.Label("Mode", style={'font-size': '0.9rem'}),
                            dcc.RadioItems(
                                id='trading-mode',
                                options=[{'label': ' Daily', 'value': 'daily'}, {'label': ' Intraday', 'value': 'intraday'}],
                                value='daily',
                                labelStyle={'display': 'block', 'font-size': '0.9rem'},
                                inputStyle={"margin-right": "5px"}
                            )
                        ], width=6),
                    ], className="mb-2"),

                    # Inputs container
                    html.Div(id='wind-inputs', children=[
                        dcc.Dropdown(
                            id='wind-code', 
                            placeholder="Select symbol", 
                            style={'font-size': '0.9rem', 'color': 'black'} # Dropdown text needs to be black
                        )
                    ], className="mb-2"),
                    html.Div(id='local-inputs', children=[
                        dcc.Dropdown(
                            id='local-symbol', 
                            options=pkl_options, 
                            placeholder="Select symbol", 
                            style={'font-size': '0.9rem', 'color': 'black'}
                        )
                    ], style={'display': 'none'}, className="mb-2"),
                    
                    html.Label("Date Range", style={'font-size': '0.9rem'}),
                    dcc.DatePickerRange(
                        id='date-range',
                        start_date=(datetime.now() - timedelta(days=30)),
                        end_date=datetime.now(),
                        display_format='YYYY-MM-DD',
                        style={'font-size': '0.9rem', 'width': '100%'},
                        className="mb-2"
                    ),

                    html.Label("OOS Split Date", style={'font-size': '0.9rem'}),
                    dcc.DatePickerSingle(
                        id='oos-split-date',
                        date=datetime.now(),
                        display_format='YYYY-MM-DD',
                        style={'font-size': '0.9rem', 'width': '100%'},
                        className="mb-2"
                    ),

                    html.Label("In-sample Lookback", style={'font-size': '0.9rem'}),
                    dcc.Dropdown(
                        id='insample-lookback',
                        options=[
                            {'label': '1 Year', 'value': '1Y'},
                            {'label': '6 Months', 'value': '6M'},
                            {'label': '2 Years', 'value': '2Y'},
                        ],
                        value='1Y',
                        clearable=False,
                        style={'font-size': '0.9rem', 'color': 'black'}
                    ),
                    
                    html.Div(id='timeframe-container', children=[
                        html.Label("Timeframe", style={'font-size': '0.9rem'}),
                        dcc.Dropdown(
                            id='timeframe',
                            options=[
                                {'label': '1 Min', 'value': '1T'},
                                {'label': '5 Min', 'value': '5T'},
                                {'label': '15 Min', 'value': '15T'},
                                {'label': '30 Min', 'value': '30T'},
                                {'label': '1 Hour', 'value': '1H'}
                            ],
                            value='5T',
                            style={'font-size': '0.9rem', 'color': 'black'}
                        ),
                    ]),
                ], style={'padding': '10px'})
            ], className="mb-3", style=DARK_CARD_STYLE),

            # Strategy Selection
            dbc.Card([
                dbc.CardHeader("Strategies", className="fw-bold", style={'padding': '5px 10px', 'background-color': '#007ACE', 'color': 'white'}),
                dbc.CardBody([
                    dcc.Checklist(
                        id='strategy-selector',
                        options=[
                            {'label': ' MA', 'value': 'MA'},
                            {'label': ' SAR', 'value': 'SAR'},
                            {'label': ' Bollinger', 'value': 'Boll'},
                            {'label': ' ATR', 'value': 'ATR'},
                            {'label': ' VWAP', 'value': 'VWAP'},
                            {'label': ' Momentum', 'value': 'Momentum'},
                            {'label': ' Market Regime Based', 'value': 'MarketRegime'},
                        ],
                        value=['MA', 'Boll', 'SAR', 'MarketRegime'],
                        labelStyle={'display': 'inline-block', 'margin-right': '10px', 'font-size': '0.9rem'},
                        inputStyle={"margin-right": "3px"}
                    )
                ], style={'padding': '10px'})
            ], className="mb-3", style=DARK_CARD_STYLE),

            # Market Regime Based strategy configuration
            dbc.Card([
                dbc.CardHeader("Market Regime", className="fw-bold", style={'padding': '5px 10px', 'background-color': '#007ACE', 'color': 'white'}),
                dbc.CardBody([
                    html.Label("Trending", style={'font-size': '0.9rem'}),
                    dcc.Dropdown(
                        id='mr-trending-strategy',
                        options=[
                            {'label': 'MA', 'value': 'MA'},
                            {'label': 'SAR', 'value': 'SAR'},
                            {'label': 'VWAP', 'value': 'VWAP'},
                            {'label': 'Momentum', 'value': 'Momentum'},
                        ],
                        value='SAR',
                        clearable=False,
                        style={'font-size': '0.9rem', 'color': 'black'}
                    ),
                    html.Div(style={'height': '8px'}),
                    html.Label("Mean-reverting", style={'font-size': '0.9rem'}),
                    dcc.Dropdown(
                        id='mr-meanrev-strategy',
                        options=[
                            {'label': 'Bollinger', 'value': 'Boll'},
                            {'label': 'ATR', 'value': 'ATR'},
                        ],
                        value='Boll',
                        clearable=False,
                        style={'font-size': '0.9rem', 'color': 'black'}
                    ),
                ], style={'padding': '10px'})
            ], className="mb-3", style=DARK_CARD_STYLE),

            # Parameters Accordion
            dbc.Accordion([
                dbc.AccordionItem([
                    dbc.Row([
                        dbc.Col([html.Label("Short", style={'font-size': '0.9rem'}), dcc.Input(id='ma-short', type='number', value=5, min=2, className="form-control form-control-sm", style=DARK_INPUT_STYLE)]),
                        dbc.Col([html.Label("Long", style={'font-size': '0.9rem'}), dcc.Input(id='ma-long', type='number', value=20, min=5, className="form-control form-control-sm", style=DARK_INPUT_STYLE)])
                    ])
                ], title="MA Params", style=DARK_CARD_STYLE),

                dbc.AccordionItem([
                    dbc.Row([
                        dbc.Col([html.Label("AF", style={'font-size': '0.9rem'}), dcc.Input(id='sar-af', type='number', value=0.02, step=0.01, className="form-control form-control-sm", style=DARK_INPUT_STYLE)]),
                        dbc.Col([html.Label("Max AF", style={'font-size': '0.9rem'}), dcc.Input(id='sar-max-af', type='number', value=0.2, step=0.01, className="form-control form-control-sm", style=DARK_INPUT_STYLE)])
                    ])
                ], title="SAR Params", style=DARK_CARD_STYLE),
                
                dbc.AccordionItem([
                    dbc.Row([
                        dbc.Col([html.Label("Period", style={'font-size': '0.9rem'}), dcc.Input(id='boll-window', type='number', value=20, className="form-control form-control-sm", style=DARK_INPUT_STYLE)]),
                        dbc.Col([html.Label("Std Dev", style={'font-size': '0.9rem'}), dcc.Input(id='boll-std', type='number', value=1.0, step=0.1, className="form-control form-control-sm", style=DARK_INPUT_STYLE)])
                    ]),
                    html.Div(style={'height': '5px'}),
                    dcc.Checklist(id='boll-exit', options=[{'label': ' Exit at MA', 'value': 'exit'}], value=[], labelStyle={'font-size': '0.9rem'})
                ], title="Bollinger Params", style=DARK_CARD_STYLE),

                dbc.AccordionItem([
                    html.Label("Window", style={'font-size': '0.9rem'}),
                    dcc.Input(id='vwap-window', type='number', value=20, className="form-control form-control-sm", style=DARK_INPUT_STYLE)
                ], title="VWAP Params", style=DARK_CARD_STYLE),

                dbc.AccordionItem([
                    html.Label("Lookback", style={'font-size': '0.9rem'}),
                    dcc.Input(id='mom-window', type='number', value=14, className="form-control form-control-sm", style=DARK_INPUT_STYLE)
                ], title="Momentum Params", style=DARK_CARD_STYLE),

                dbc.AccordionItem([
                    dbc.Row([
                        dbc.Col([html.Label("EMA", style={'font-size': '0.9rem'}), dcc.Input(id='atr-ema-window', type='number', value=11, className="form-control form-control-sm", style=DARK_INPUT_STYLE)]),
                        dbc.Col([html.Label("ATR", style={'font-size': '0.9rem'}), dcc.Input(id='atr-window', type='number', value=14, className="form-control form-control-sm", style=DARK_INPUT_STYLE)]),
                        dbc.Col([html.Label("Mult", style={'font-size': '0.9rem'}), dcc.Input(id='atr-mult', type='number', value=2.0, step=0.1, className="form-control form-control-sm", style=DARK_INPUT_STYLE)])
                    ])
                ], title="ATR Params", style=DARK_CARD_STYLE),
            ], start_collapsed=True, className="mb-3", flush=True, style={"background-color": "#082255"}), # Accordion container bg

            dbc.Button("Run Backtest", id='run-button', style={
                'width': '100%', 
                'padding': '12px', 
                'background-color': '#007ACE', 
                'color': 'white', 
                'border': 'none', 
                'cursor': 'pointer',
                'font-size': '1.1rem',
                'font-weight': 'bold',
                'letter-spacing': '0.1rem'
            })
        ],
        style=SIDEBAR_STYLE,
    )
    
    return sidebar


def create_content():
    """Create main content area layout"""
    content = html.Div(
        [
            html.H1("📊 Quantitative Strategy Backtest Dashboard", style={'text-align': 'center'}),
            dcc.Loading(
                id="loading-1",
                type="default",
                children=html.Div(id="results-container")
            )
        ],
        style=CONTENT_STYLE
    )
    
    return content


def create_layout():
    """Create complete application layout"""
    return html.Div([create_sidebar(), create_content()])
