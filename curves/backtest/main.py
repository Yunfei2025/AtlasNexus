# -*- coding: utf-8 -*-
"""
Created on Wed Nov 29 16:24:33 2023

@author: 马云飞
"""
import sys
import pathlib
import logging

# local libraries
PATH = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(PATH))

from curves.backtest.backtestor import Backtestor

# Configure logging using centralized setup
from utils.log_window import get_logger
logger = get_logger(__name__)

# Instrument type: 'TBond', 'CBond', or 'IRS'
btype = "CBond"
# Update flags: list of strings from ['pool', 'bonds', 'cbts']
update_list = ['pool']

start = '2026-03-01'  # Backtest start date
end = '2026-04-16'    # Backtest end date

# Performance settings
processes = 4   # Number of parallel workers
serial = False   # Force serial run (for debugging)

def main():
    """Main entry point."""
    # Use global configuration variables defined above
    global btype, start, end, update_list, processes, serial
    
    try:
        # Create and run backtestor
        backtestor = Backtestor(
            btype=btype,
            start=start,
            end=end,
            update_list=update_list,
            processes=processes,
            serial=serial
        )
        backtestor.run()
        
        logger.info("✅ Backtesting completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Backtesting failed: {e}")
        raise
        
if __name__ == '__main__':
    main()