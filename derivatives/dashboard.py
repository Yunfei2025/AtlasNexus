# -*- coding: utf-8 -*-
"""
Integrated Derivatives Dashboard
Combines Volatility Trading Dashboard and Bond Option Pricing Dashboard

@author: GitHub Copilot
"""
import os
import sys
import pathlib
import dash
from dash import html, dcc
from flask import send_file

# Local libraries
PATH = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(PATH))

from curves.utils.loader import loadInstrumentDefinition
from derivatives.pricer.layout import create_main_layout as create_pricer_layout
from derivatives.pricer.callbacks import register_callbacks as register_pricer_callbacks
from derivatives.vol.main import VolatilityTradingEngine, retrieveFuturesVol

class IntegratedDashboard:
    """Integrated dashboard for derivatives"""
    
    def __init__(self, port=8060, debug=False):
        self.port = port
        self.debug = debug
        self.app = dash.Dash(__name__, suppress_callback_exceptions=True)
        self.server = self.app.server
        
        # Initialize data
        self.bond_env = None
        self.default_bond = None
        
        # Ensure vol report exists
        self._ensure_vol_report()
        
        # Load pricer environment
        # NOTE: Disabled due to data loading issues (numpy/pickle incompatibility)
        # self._load_pricer_environment()
        
        # Setup routes, layout and callbacks
        self._setup_routes()
        self._setup_layout()
        self._setup_callbacks()
    
    def _load_pricer_environment(self):
        """Load bond environment data for pricer"""
        try:
            print("Loading bond environment...")
            self.bond_env = loadInstrumentDefinition("TBond")
            self.default_bond = self.bond_env['Def'].loc['240011.IB']
            print("✅ Pricer environment loaded successfully")
        except Exception as e:
            print(f"❌ Failed to load pricer environment: {e}")
            # We don't raise here to allow the dashboard to start even if pricer fails, 
            # though callbacks might fail later.
            
    def _ensure_vol_report(self):
        """Ensure the volatility report HTML exists"""
        try:
            html_path = os.path.join(os.path.dirname(__file__), 'vol', 'vol_strategy_analysis.html')
            if not os.path.exists(html_path):
                print("Generating volatility report...")
                try:
                    retrieveFuturesVol()
                    engine = VolatilityTradingEngine(
                        code="AU.SHF",
                        start_date="2025-01-01",
                        end_date="2025-10-28"
                    )
                    engine.run_full_analysis()
                    print("✅ Volatility report generated")
                except Exception as e:
                    print(f"❌ Failed to generate volatility report: {e}")
        except Exception as e:
            print(f"Error ensuring vol report: {e}")

    def _setup_routes(self):
        """Setup Flask routes for static files"""
        @self.server.route('/vol_report')
        def serve_vol_report():
            html_path = os.path.join(os.path.dirname(__file__), 'vol', 'vol_strategy_analysis.html')
            if os.path.exists(html_path):
                return send_file(html_path)
            return "Report not found", 404

    def _setup_layout(self):
        """Setup integrated dashboard layout"""
        self.app.layout = html.Div([
            # Header
            html.Div([
                html.H1("Derivatives Integrated Dashboard", 
                       style={'textAlign': 'center', 'color': '#2c3e50', 'marginBottom': 20}),
                html.Hr(),
            ], style={'padding': '20px'}),

            # Volatility Trading Section
            html.Div([
                html.H2("Volatility Trading Strategy", style={'padding': '0 20px', 'color': '#34495e'}),
                html.Iframe(
                    src='/vol_report',
                    style={
                        'width': '100%',
                        'height': '800px',
                        'border': 'none',
                        'marginBottom': '40px'
                    }
                )
            ]),
            
            # Bond Option Pricing Section
            html.Div([
                html.H2("Bond Option Pricing", style={'padding': '0 20px', 'color': '#34495e'}),
                create_pricer_layout()
            ], style={'borderTop': '2px solid #ecf0f1', 'paddingTop': '20px'})
            
        ], style={'fontFamily': 'Arial, sans-serif', 'margin': '0 auto'})

    def _setup_callbacks(self):
        """Setup callbacks"""
        if self.default_bond is not None:
            register_pricer_callbacks(self.app, self.default_bond)

    def run(self):
        """Run the dashboard"""
        print(f"\n{'='*60}")
        print(f"🚀 Starting Integrated Derivatives Dashboard")
        print(f"{'='*60}")
        print(f"\n📊 Dashboard will be available at: http://localhost:{self.port}")
        
        self.app.run(host='127.0.0.1', port=self.port, debug=self.debug)

if __name__ == '__main__':
    dashboard = IntegratedDashboard(port=8060, debug=True)
    dashboard.run()
