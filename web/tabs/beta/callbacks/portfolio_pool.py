# -*- coding: utf-8 -*-
"""Portfolio (Allocation) tab — asset pool management callbacks.

Contains:
  1. UI Toggles for Asset Type Selection (Rates / Spread / Commodities)
  2. Asset Pool Management (add / clear)
  3. Add Diversified Assets to Pool (from correlation results)
"""

from __future__ import annotations

import dash
from dash import html
from dash.dependencies import Input, Output, State

from multiasset.storage import save_asset_pool

from ..data import THEME, DIVERSIFICATION_RECOMMENDATIONS
from ...atlas_components import asset_pool_item


def register_portfolio_pool_callbacks(app):
    """Register asset-pool management callbacks for the Portfolio tab."""


    # 1. UI Toggles for Asset Type Selection
    @app.callback(
        [Output('universe-selection-row', 'style'),
         Output('sector-selection-row', 'style'),
         Output('commodities-confirm-row', 'style'),
         Output('universe-selector', 'options'),
         Output('universe-selector', 'value'),
         Output('sector-selector', 'value'),
         Output('commodities-selector', 'value')],
        [Input('asset-type-selector', 'value')]
    )
    def toggle_selection_rows(asset_type):
        if asset_type == 'Rates':
            universe_options = [
                {'label': 'China Gov Bond', 'value': 'China Gov Bond'},
                {'label': 'US Gov Bond', 'value': 'US Gov Bond'},
                {'label': 'DE Gov Bond', 'value': 'DE Gov Bond'},
                {'label': 'UK Gov Bond', 'value': 'UK Gov Bond'},
                {'label': 'Japan Gov Bond', 'value': 'Japan Gov Bond'},
            ]
            return (
                {'display': 'flex', 'alignItems': 'center', 'marginBottom': '12px'},
                {'display': 'none'},
                {'display': 'none'},
                universe_options, None, [], []
            )
        elif asset_type == 'Spread':
            universe_options = [
                {'label': 'Interest Rate Swap', 'value': 'Interest Rate Swap'},
                {'label': 'China Development Bond', 'value': 'China Development Bond'},
                {'label': 'Interbank Commercial Paper', 'value': 'Interbank Commercial Paper'},
            ]
            return (
                {'display': 'flex', 'alignItems': 'center', 'marginBottom': '12px'},
                {'display': 'none'},
                {'display': 'none'},
                universe_options, None, [], []
            )
        elif asset_type == 'Commodities':
            return (
                {'display': 'none'},
                {'display': 'none'},
                {'display': 'flex', 'alignItems': 'flex-start', 'marginBottom': '12px'},
                [], None, [], []
            )
        else:
            return (
                {'display': 'none'},
                {'display': 'none'},
                {'display': 'none'},
                [], None, [], []
            )

    @app.callback(
        Output('sector-selection-row', 'style', allow_duplicate=True),
        [Input('universe-selector', 'value')],
        prevent_initial_call=True
    )
    def show_sector_selection(universe):
        if universe:
            return {'display': 'flex', 'alignItems': 'flex-start', 'marginBottom': '12px'}
        return {'display': 'none'}

    # 2. Asset Pool Management
    @app.callback(
        [Output('asset-pool-store', 'data'),
         Output('asset-pool-display', 'children'),
         Output('pool-count', 'children')],
        [Input('add-to-pool-btn', 'n_clicks'),
         Input('add-commodities-btn', 'n_clicks'),
         Input('clear-pool-btn', 'n_clicks')],
        [State('asset-type-selector', 'value'),
         State('universe-selector', 'value'),
         State('sector-selector', 'value'),
         State('commodities-selector', 'value'),
         State('asset-pool-store', 'data')],
        prevent_initial_call=True
    )
    def manage_asset_pool(add_rates_clicks, add_comm_clicks, clear_clicks, asset_type, universe, sectors, commodities, current_pool):
        ctx = dash.callback_context
        if not ctx.triggered:
            return current_pool, dash.no_update, dash.no_update
        
        button_id = ctx.triggered[0]['prop_id'].split('.')[0]
        
        if button_id == 'clear-pool-btn':
            return [], [html.Div("No assets.", style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'padding': '10px'})], "(0)"
        
        if current_pool is None:
            current_pool = []
        
        if button_id == 'add-to-pool-btn' and asset_type in ['Rates', 'Spread']:
            if not universe or not sectors:
                return current_pool, dash.no_update, dash.no_update
            
            universe_code_map = {
                'China Gov Bond': 'CN', 'US Gov Bond': 'US', 'DE Gov Bond': 'EU',
                'UK Gov Bond': 'UK', 'Japan Gov Bond': 'JP',
                'China Credit': 'CN-Credit', 'China Urban': 'CN-Urban'
            }
            universe_code = universe_code_map.get(universe, 'XX')
            
            for sector in sectors:
                asset_name = f"{universe_code}{sector}"
                asset_info = {'name': asset_name, 'type': asset_type, 'universe': universe, 'sector': sector}
                if not any(a['name'] == asset_name for a in current_pool):
                    current_pool.append(asset_info)
        
        elif button_id == 'add-commodities-btn' and asset_type == 'Commodities':
            if not commodities:
                return current_pool, dash.no_update, dash.no_update
            
            for comm in commodities:
                asset_info = {'name': comm, 'type': 'Commodities', 'universe': comm, 'sector': 'N/A'}
                if not any(a['name'] == comm for a in current_pool):
                    current_pool.append(asset_info)
        
        # Update display
        if not current_pool:
            display = [html.Div("No assets selected.", style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'padding': '10px'})]
            count_text = "(0)"
        else:
            display = [
                asset_pool_item(asset['name'], f"({asset.get('universe','')} — {asset.get('sector','')})")
                for asset in current_pool
            ]
            count_text = f"({len(current_pool)})"
        
        # Save to persistent storage
        try:
            save_asset_pool(current_pool)
        except Exception as e:
            print(f"Error saving asset pool: {e}")

        return current_pool, display, count_text


    # 3.55 Add Diversified Assets to Pool Callback
    # Uses global variable instead of dcc.Store because dcc.Store data doesn't persist across tab switches
    @app.callback(
        [Output('add-diversified-status', 'children'),
         Output('asset-pool-store', 'data', allow_duplicate=True),
         Output('asset-pool-display', 'children', allow_duplicate=True),
         Output('pool-count', 'children', allow_duplicate=True)],
        Input('add-diversified-assets-btn', 'n_clicks'),
        prevent_initial_call=True
    )
    def add_diversified_assets_to_pool(n_clicks):
        """
        Replace the asset pool with recommended diversified assets.
        Updates asset-pool-store directly so the Portfolio tab sees the change
        immediately without requiring a page reload.
        """
        no_change = (dash.no_update, dash.no_update, dash.no_update)
        if not n_clicks or n_clicks == 0:
            return ("",) + no_change

        # Get assets from global variable (set by correlation analysis)
        recommended_assets = DIVERSIFICATION_RECOMMENDATIONS.get('assets', [])

        if not recommended_assets:
            return ("⚠ No recommended assets available. Please run correlation analysis first.",) + no_change

        # REPLACE the entire asset pool with recommended assets
        new_pool = [asset.copy() for asset in recommended_assets]

        # Save to persistent storage
        try:
            save_asset_pool(new_pool)
        except Exception as e:
            print(f"Error saving asset pool: {e}")
            return (f"✗ Error saving: {str(e)}",) + no_change

        # Build display items (same style as manage_asset_pool)
        display = [
            asset_pool_item(asset['name'], f"({asset.get('universe', '')} — {asset.get('sector', '')})")
            for asset in new_pool
        ]

        count_text = f"({len(new_pool)})"

        # Count assets by type for status message
        type_counts: dict = {}
        for asset in new_pool:
            a_type = asset.get('type', 'Other')
            type_counts[a_type] = type_counts.get(a_type, 0) + 1
        type_summary = ", ".join([f"{count} {t}" for t, count in type_counts.items()])
        status_msg = f"✓ {len(new_pool)} assets added to pool ({type_summary})."

        return status_msg, new_pool, display, count_text

