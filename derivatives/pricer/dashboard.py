# -*- coding: utf-8 -*-
"""
Bond Option Pricing Dashboard using Plotly Dash
Interactive web-based interface for bond option pricing

@author: CMBC
Created: Oct 29, 2025
"""
import sys
import pathlib

import dash

# Local libraries
PATH = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(PATH))

from curves.utils.loader import loadInstrumentDefinition
from derivatives.pricer.layout import create_main_layout
from derivatives.pricer.callbacks import register_callbacks


class BondOptionDashboard:
    """Interactive dashboard for bond option pricing"""
    
    def __init__(self, port=8050, debug=False):
        """
        Initialize the dashboard
        
        Parameters:
        -----------
        port : int
            Port to run the dashboard on
        debug : bool
            Enable debug mode
        """
        self.port = port
        self.debug = debug
        self.app = dash.Dash(__name__, suppress_callback_exceptions=True)
        self.bond_env = None
        self.default_bond = None
        
        # Load environment
        self._load_environment()
        
        # Setup layout and callbacks
        self._setup_layout()
        self._setup_callbacks()
    
    def _load_environment(self):
        """Load bond environment data"""
        try:
            print("Loading bond environment...")
            self.bond_env = loadInstrumentDefinition("TBond")
            self.default_bond = self.bond_env['Def'].loc['240011.IB']
            print("✅ Environment loaded successfully")
        except Exception as e:
            print(f"❌ Failed to load environment: {e}")
            raise
    
    def _setup_layout(self):
        """Setup dashboard layout"""
        self.app.layout = create_main_layout()
    
    def _setup_callbacks(self):
        """Setup dashboard callbacks"""
        register_callbacks(self.app, self.default_bond)
    
    def run(self):
        """Run the dashboard"""
        print(f"\n{'='*60}")
        print(f"🚀 Starting Bond Option Pricing Dashboard")
        print(f"{'='*60}")
        print(f"\n📊 Dashboard will be available at: http://localhost:{self.port}")
        print(f"💡 Press Ctrl+C to stop the server\n")
        
        self.app.run(host='127.0.0.1', port=self.port, debug=self.debug, use_reloader=False)


def main(port=8050, debug=False):
    """
    Launch the dashboard
    
    Parameters:
    -----------
    port : int
        Port to run the dashboard on (default: 8050)
    debug : bool
        Enable debug mode (default: False)
    """
    dashboard = BondOptionDashboard(port=port, debug=debug)
    dashboard.run()


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Bond Option Pricing Dashboard')
    parser.add_argument('--port', type=int, default=8058, help='Port to run dashboard on')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    args = parser.parse_args()
    
    main(port=args.port, debug=args.debug)
