# -*- coding: utf-8 -*-
"""
Dashboard Callbacks
Contains all callback functions for the bond option pricing dashboard

@author: CMBC
Created: Oct 29, 2025
"""
import sys
import pathlib
from dash import dash_table
from dash.dependencies import Input, Output, State

# Local libraries
PATH = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(PATH))

from derivatives.pricer.pricer import BondOption, InterestRateOption
from derivatives.pricer.utils import format_results_to_dataframe, create_payoff_chart, create_empty_chart


def register_callbacks(app, default_bond):
    """
    Register all dashboard callbacks
    
    Parameters:
    -----------
    app : dash.Dash
        Dash application instance
    default_bond : object
        Default bond object for pricing
    """
    
    @app.callback(
        [Output('strike-price-div', 'style'),
         Output('strike-yield-div', 'style')],
        [Input('option-type-dropdown', 'value')]
    )
    def toggle_strike_input(option_type):
        """Toggle visibility of strike price vs strike yield inputs"""
        if option_type == 'bond':
            return {'marginBottom': 15}, {'marginBottom': 15, 'display': 'none'}
        else:
            return {'marginBottom': 15, 'display': 'none'}, {'marginBottom': 15}
    
    @app.callback(
        [Output('results-table-div', 'children'),
         Output('payoff-chart', 'figure'),
         Output('status-message', 'children'),
         Output('error-message', 'children')],
        [Input('calculate-button', 'n_clicks')],
        [State('option-type-dropdown', 'value'),
         State('call-put-dropdown', 'value'),
         State('exercise-date-input', 'value'),
         State('expiry-date-input', 'value'),
         State('eval-date-input', 'value'),
         State('strike-price-input', 'value'),
         State('strike-yield-input', 'value'),
         State('notional-input', 'value')]
    )
    def calculate_option(n_clicks, option_type, call_put, exercise_date, 
                        expiry_date, eval_date, strike_price, strike_yield, notional):
        """Main calculation callback - prices option and generates outputs"""
        if n_clicks == 0:
            # Return empty chart on initial load
            empty_fig = create_empty_chart("Click Calculate to generate payoff diagram")
            return None, empty_fig, "", ""
        
        try:
            # Create option based on type
            kwargs = {
                'underlying': default_bond,
                'exercise_date': exercise_date,
                'expiry_date': expiry_date,
                'eval_date': eval_date,
                'notional': notional,
                'option_type': call_put
            }
            
            if option_type == 'bond':
                kwargs['strike'] = strike_price
                option = BondOption(**kwargs)
                strike_value = strike_price
            else:
                kwargs['strike_yield'] = strike_yield
                option = InterestRateOption(**kwargs)
                strike_value = strike_yield
            
            # Price the option
            results = option.price_option()
            
            # Format results as DataFrame
            results_df = format_results_to_dataframe(results, option_type)
            
            # Create table
            table = dash_table.DataTable(
                data=results_df.to_dict('records'),
                columns=[{'name': col, 'id': col} for col in results_df.columns],
                style_cell={
                    'textAlign': 'left',
                    'padding': '12px',
                    'fontFamily': 'Arial, sans-serif',
                    'fontSize': '14px'
                },
                style_header={
                    'backgroundColor': '#3498db',
                    'color': 'white',
                    'fontWeight': 'bold',
                    'border': '1px solid #2c3e50'
                },
                style_data={
                    'border': '1px solid #bdc3c7'
                },
                style_data_conditional=[
                    {
                        'if': {'row_index': 'odd'},
                        'backgroundColor': '#ecf0f1'
                    }
                ]
            )
            
            # Create payoff chart
            payoff_fig = create_payoff_chart(
                strike_value, 
                call_put, 
                option_type,
                results.get('underlying_price', strike_value),
                results.get('price', 0),
                notional
            )
            
            status_msg = f"✅ Calculation completed successfully! ({option_type.replace('_', ' ').title()})"
            return table, payoff_fig, status_msg, ""
            
        except Exception as e:
            import traceback
            error_msg = f"❌ Error: {str(e)}"
            error_detail = traceback.format_exc()
            print(error_detail)
            
            # Return empty chart on error
            empty_fig = create_empty_chart("Error occurred")
            return None, empty_fig, "", error_msg
