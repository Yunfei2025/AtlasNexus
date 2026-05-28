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
btype = "TBond"
# Update flags: list of strings from ['pool', 'bonds', 'cbts']
update_list = ['pool', ]

# Default date window: most recent 3 months ending on previous CN workday
from settings.general import DateConfig
from dateutil.relativedelta import relativedelta
end_dt = DateConfig.get_date_mappings()['dp'].date()
start_dt = end_dt - relativedelta(months=3)
start = '2025-03-31'#start_dt.strftime('%Y-%m-%d')
end = '2025-06-30'#end_dt.strftime('%Y-%m-%d')

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