#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Curve generation initialisation module.

This module runs the complete curve generation workflow independently.
It orchestrates various generators for financial curve processing.

Author: Yunfei Ma
"""

import datetime
import pathlib
import sys
import traceback

# Minimal bootstrap for direct execution: add project root so absolute
# package imports work when running `python curves\initialise.py`.
if __name__ == "__main__":
    _PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))

# Clean imports - all absolute paths
from curves.utils.generator_utils import get_mtime_date
from curves.utils.retrieve import updateInstrumentDef, retrieveCNBDTS, retrieveFuturesTS
from settings.fixed_income import BondConfig
from settings.paths import DIR_INPUT

# Import generators dynamically to avoid dependency issues at module load time
import importlib
def run_data_updates() -> None:
    """Run database updates if needed (INFO/WARNING logging only)."""
    try:
        t = datetime.datetime.today()

        print("INFO: Checking data updates...")

        # Update instrument definitions if needed
        futures_file = DIR_INPUT / "futures-InstrumentInfo.pkl"
        if t.date() != get_mtime_date(futures_file):
            print("INFO: Updating instrument definitions...")
            updateInstrumentDef()

        # Update bond database if needed
        bond_file = DIR_INPUT / "database-px.pkl"
        if t.date() != get_mtime_date(bond_file):
            print("INFO: Updating bond database...")
            retrieveCNBDTS()

        # Update futures database if needed
        futures_px_file = DIR_INPUT / "futures-px.pkl"
        if t.date() != get_mtime_date(futures_px_file):
            print("INFO: Updating futures database...")
            retrieveFuturesTS()

    except Exception as e:
        print(f"WARNING: Data updates failed: {e}")

def main() -> None:
    """Main curve generation workflow (INFO/WARNING only)."""
    print("INFO: Starting curve generation...")
    print(f"INFO: curves package path: {pathlib.Path(__file__).resolve().parent}")
    
    try:
        # Step 1: Update databases
        run_data_updates()
        
        # Step 2: Run generators in order
        generators = [
            ("TrendGenerator", "trend"),
            ("BondCurveGenerator", "rates"), 
            ("CreditSpreadGenerator", "credit"),
            ("IRSGenerator", "irs"),
            ("StatGenerator", "stat"),
        ]
        
        success_count = 0
        for generator_name, module_name in generators:
            try:
                print(f"INFO: Running {generator_name}...")
                
                # Import generator dynamically to avoid dependency issues
                spec = importlib.import_module(f"curves.generators.{module_name}")
                generator_class = getattr(spec, generator_name)

                if generator_name == "BondCurveGenerator":
                    for bond_type in ['TBond', 'CBond']:
                        print(f"INFO: Generating {bond_type} curve...")
                        generator_class.main(bond_type=bond_type)
                elif generator_name == "CreditSpreadGenerator":
                    for bond_type in BondConfig.INCLUDE_FILTERS.keys():
                        print(f"INFO: Generating {bond_type} curve...")
                        generator_class.main(bond_type=bond_type)
                else:
                    generator_class.main()
                
                print(f"INFO: {generator_name} completed successfully")
                success_count += 1

            except ImportError as e:
                print(f"WARNING: Could not import {generator_name}: {e}")
            except Exception as e:
                print(f"ERROR: Error running {generator_name}: {e}")
                
        print(f"INFO: Summary: {success_count}/{len(generators)} generators completed successfully")
        
        from curves.generators.pairs import main
        main(min_cr=30.0, lookback_days=60, write_to_excel=True)
        print(f"INFO: Top CR pairs generated.")
        
        if success_count == len(generators):
            print("INFO: All curve generation tasks completed!")
        else:
            print("WARNING: Some generators failed - check logs above for details")
              
    except Exception as e:
        print(f"CRITICAL: Fatal error: {e}")
        traceback.print_exc()
        sys.exit(1)
#%%
if __name__ == "__main__":
    main()
  