# -*- coding: utf-8 -*-
"""
Dashboard Layout Components
Contains all UI layout definitions for the bond option pricing dashboard

@author: CMBC
Created: Oct 29, 2025
"""
from dash import dcc, html


def create_header():
    """Create dashboard header"""
    return html.Div([
        html.H1("Bond Option Pricing Dashboard", 
               style={'textAlign': 'center', 'color': '#2c3e50', 'marginBottom': 20}),
        html.Hr(),
    ], style={'padding': '20px'})


def create_input_panel():
    """Create input parameters panel"""
    return html.Div([
        html.H3("Input Parameters", style={'color': '#34495e'}),
        
        # Option Type Dropdown
        html.Div([
            html.Label("Option Type:", style={'fontWeight': 'bold'}),
            dcc.Dropdown(
                id='option-type-dropdown',
                options=[
                    {'label': 'Bond Option (Price-based)', 'value': 'bond'},
                    {'label': 'Interest Rate Option (Yield-based)', 'value': 'interest_rate'}
                ],
                value='bond',
                clearable=False,
                style={'width': '100%'}
            )
        ], style={'marginBottom': 15}),
        
        # Call/Put Dropdown
        html.Div([
            html.Label("Call/Put:", style={'fontWeight': 'bold'}),
            dcc.Dropdown(
                id='call-put-dropdown',
                options=[
                    {'label': 'Call', 'value': 'call'},
                    {'label': 'Put', 'value': 'put'}
                ],
                value='call',
                clearable=False,
                style={'width': '100%'}
            )
        ], style={'marginBottom': 15}),
        
        # Exercise Date
        html.Div([
            html.Label("Exercise Date (YYYYMMDD):", style={'fontWeight': 'bold'}),
            dcc.Input(
                id='exercise-date-input',
                type='text',
                value='20250211',
                style={'width': '100%', 'padding': '8px'}
            )
        ], style={'marginBottom': 15}),
        
        # Expiry Date
        html.Div([
            html.Label("Expiry Date (YYYYMMDD):", style={'fontWeight': 'bold'}),
            dcc.Input(
                id='expiry-date-input',
                type='text',
                value='20250511',
                style={'width': '100%', 'padding': '8px'}
            )
        ], style={'marginBottom': 15}),
        
        # Evaluation Date
        html.Div([
            html.Label("Evaluation Date (YYYYMMDD):", style={'fontWeight': 'bold'}),
            dcc.Input(
                id='eval-date-input',
                type='text',
                value='20250211',
                style={'width': '100%', 'padding': '8px'}
            )
        ], style={'marginBottom': 15}),
        
        # Strike Price (for Bond Option)
        html.Div([
            html.Label("Strike Price:", style={'fontWeight': 'bold'}),
            dcc.Input(
                id='strike-price-input',
                type='number',
                value=105.524,
                step=0.001,
                style={'width': '100%', 'padding': '8px'}
            )
        ], id='strike-price-div', style={'marginBottom': 15}),
        
        # Strike Yield (for Interest Rate Option)
        html.Div([
            html.Label("Strike Yield (%):", style={'fontWeight': 'bold'}),
            dcc.Input(
                id='strike-yield-input',
                type='number',
                value=1.6265,
                step=0.0001,
                style={'width': '100%', 'padding': '8px'}
            )
        ], id='strike-yield-div', style={'marginBottom': 15, 'display': 'none'}),
        
        # Notional
        html.Div([
            html.Label("Notional:", style={'fontWeight': 'bold'}),
            dcc.Input(
                id='notional-input',
                type='number',
                value=20000000,
                step=1000000,
                style={'width': '100%', 'padding': '8px'}
            )
        ], style={'marginBottom': 15}),
        
        # Calculate Button
        html.Button(
            'Calculate',
            id='calculate-button',
            n_clicks=0,
            style={
                'width': '100%',
                'padding': '12px',
                'backgroundColor': '#3498db',
                'color': 'white',
                'border': 'none',
                'borderRadius': '4px',
                'fontSize': '16px',
                'fontWeight': 'bold',
                'cursor': 'pointer',
                'marginTop': '10px'
            }
        ),
        
        # Status Message
        html.Div(id='status-message', style={'marginTop': 15, 'color': '#27ae60'})
        
    ], style={
        'padding': '20px',
        'backgroundColor': '#ecf0f1',
        'borderRadius': '8px',
        'height': '100%'
    })


def create_results_panel():
    """Create results table panel"""
    return html.Div([
        html.H3("Results", style={'color': '#34495e'}),
        
        # Results Table
        html.Div(id='results-table-div', style={'marginTop': 20}),
        
        # Error message
        html.Div(id='error-message', style={'color': 'red', 'marginTop': 20})
        
    ], style={
        'padding': '20px',
        'backgroundColor': '#ffffff',
        'borderRadius': '8px',
        'boxShadow': '0 2px 4px rgba(0,0,0,0.1)'
    })


def create_chart_panel():
    """Create payoff chart panel"""
    return html.Div([
        html.H3("Payoff Diagram", style={'color': '#34495e'}),
        
        # Payoff Chart
        dcc.Graph(id='payoff-chart', style={'marginTop': 20})
        
    ], style={
        'padding': '20px',
        'backgroundColor': '#ffffff',
        'borderRadius': '8px',
        'boxShadow': '0 2px 4px rgba(0,0,0,0.1)'
    })


def create_footer():
    """Create dashboard footer"""
    return html.Div([
        html.Hr(),
        html.P("Bond Option Pricing System | CMBC Financial Engineering", 
              style={'textAlign': 'center', 'color': '#7f8c8d'})
    ], style={'padding': '20px'})


def create_main_layout():
    """Create the complete dashboard layout"""
    return html.Div([
        create_header(),
        
        # Main content area
        html.Div([
            # Sidebar (Left)
            html.Div(create_input_panel(), style={'flex': '0 0 300px', 'marginRight': '20px'}),
            
            # Payoff Diagram (Middle)
            html.Div(create_chart_panel(), style={'flex': '0 0 50%', 'marginRight': '20px', 'minWidth': '0'}),
            
            # Results Panel (Right)
            html.Div(create_results_panel(), style={'flex': '1'})
            
        ], style={'display': 'flex', 'padding': '20px', 'alignItems': 'flex-start', 'backgroundColor': '#f5f6fa'}),
        
        create_footer()
        
    ], style={'fontFamily': 'Arial, sans-serif', 'margin': '0 auto'})
