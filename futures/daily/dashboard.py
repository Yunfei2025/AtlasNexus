# -*- coding: utf-8 -*-
"""
Futures Portfolio Strategy Dashboard

Interactive web dashboard for portfolio analysis and strategy monitoring.

@author: CMBC
"""
import os
import sys
from pathlib import Path
import pandas as pd


# Add project path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from settings.paths import DIR_INPUT
from futures.daily import FuturesPortfolioDashboard

def main():
    """Main entry point."""
    # Load data
    file_path = os.path.join(DIR_INPUT, 'futures-dailyK_con.pkl')
    print(f"Loading data from: {file_path}")
    data = pd.read_pickle(file_path)
    print(f"Loaded {len(data)} futures contracts")
    
    # Create and run dashboard
    dashboard = FuturesPortfolioDashboard(data)
    dashboard.run(host='127.0.0.1', port=8050, debug=True)


if __name__ == "__main__":
    main()
