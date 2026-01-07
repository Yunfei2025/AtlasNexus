# -*- coding: utf-8 -*-
"""
Main Application Module for Pair Analysis

This module contains the main application logic and entry point.
"""
import warnings
from datetime import datetime
import xlwings as xw
import sys
import pathlib

# Add project root to path
PATH = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(PATH))

from pairs.manager import PairManager

# Suppress warnings for better performance
warnings.filterwarnings('ignore')


def main(excel_mode=True, excel_path=None):
    """Main function using OOP approach for better organization and performance
    
    Parameters
    ----------
    excel_mode : bool
        If True, use Excel interface (requires xlwings). If False, run in standalone mode.
    excel_path : str or Path, optional
        Path to Excel file when not using Book.caller()
    """
    start_time = datetime.now()

    try:
        # Initialize Excel connection based on mode
        if excel_mode:
            try:
                wb = xw.Book.caller()
                sht_cfg = wb.sheets["Main"]
                sht_out = wb.sheets["Main"]
                use_excel_output = True
            except Exception as e:
                # If Book.caller() fails, try to open the workbook directly
                print(f"⚠ Book.caller() failed: {e}")
                if excel_path:
                    wb = xw.Book(excel_path)
                    wb.set_mock_caller()
                    sht_cfg = wb.sheets["Main"]
                    sht_out = wb.sheets["Main"]
                    use_excel_output = True
                else:
                    print("ℹ Falling back to non-Excel mode (no Excel output)")
                    use_excel_output = False
        else:
            use_excel_output = False

        print("🚀 Starting Pair Analysis with modular OOP approach...")

        # Initialize Pair Manager
        config_start = datetime.now()
        pair_manager = PairManager()
        
        # Load pairs from Excel if available, otherwise use defaults or config file
        if use_excel_output and 'sht_cfg' in locals():
            pair_manager.load_pairs_from_excel(sht_cfg)
        else:
            # For non-Excel mode, you may want to load from a config file or use defaults
            print("ℹ Running in standalone mode - loading pairs from default configuration")
            # This will need to be implemented in PairManager if not already available
            # For now, try to load from Excel if path is provided
            if excel_path:
                try:
                    # Check if the workbook is already open to avoid closing user's file
                    excel_path_str = str(excel_path)
                    existing_wb = None

                    # Search for already-open workbook
                    for wb in xw.books:
                        if pathlib.Path(wb.fullname).resolve() == pathlib.Path(excel_path_str).resolve():
                            existing_wb = wb
                            break

                    if existing_wb:
                        # Use the already-open workbook WITHOUT closing it
                        print(f"ℹ Using already-open Excel workbook: {existing_wb.name}")
                        temp_sht = existing_wb.sheets["Main"]
                        pair_manager.load_pairs_from_excel(temp_sht)
                        # DO NOT close - user has it open
                    else:
                        # Only open and close if not already open
                        temp_wb = xw.Book(excel_path)
                        temp_sht = temp_wb.sheets["Main"]
                        pair_manager.load_pairs_from_excel(temp_sht)
                        temp_wb.close()
                except Exception as e:
                    print(f"⚠ Could not load from Excel file: {e}")
                    raise ValueError("Pairs configuration could not be loaded. Please provide valid Excel file or implement alternative config loading.")
            else:
                raise ValueError("No configuration source available. Please provide excel_path or ensure Excel is available.")
        
        config_time = (datetime.now() - config_start).total_seconds()
        print(f"✓ Configuration loading time: {config_time:.3f}s")
        print(f"✓ Loaded {len(pair_manager)} pairs")

        # Prepare analysis once for all operations
        analysis_start = datetime.now()
        analyses = pair_manager.prepare_analysis()
        analysis_time = (datetime.now() - analysis_start).total_seconds()
        print(f"✓ Analysis computation time: {analysis_time:.3f}s")

        # Get analysis results (using pre-computed analyses)
        results = pair_manager.get_results(analyses)
        print(f"✓ Analysis results prepared: {len(results)} pairs")

        # Write results to Excel (using pre-computed analyses) - only if Excel is available
        if use_excel_output and 'sht_out' in locals():
            write_start = datetime.now()
            pair_manager.write_to_excel(sht_out, analyses)
            write_time = (datetime.now() - write_start).total_seconds()
            print(f"✓ Results writing time: {write_time:.3f}s")

            # Create plots (using pre-computed analyses)
            plot_start = datetime.now()
            pair_manager.create_excel_plots(sht_out, analyses)
            plot_time = (datetime.now() - plot_start).total_seconds()
            print(f"✓ Chart generation time: {plot_time:.3f}s")
        # else:
        #     write_time = 0
        #     plot_time = 0
        #     print("ℹ Skipping Excel output (running in standalone mode)")

        # Create unified dashboard (using pre-computed analyses)
        interactive_start = datetime.now()
        try:
            import os
            # import pdb; pdb.set_trace()
            dashboard_path = pair_manager.create_dashboard(os.path.join("pairs","regression_plots.html"), analyses)
            interactive_time = (datetime.now() - interactive_start).total_seconds()
            print(f"✓ Dashboard created: {interactive_time:.3f}s")
            print(f"✓ Access dashboard at: {dashboard_path}")
        except Exception as e:
            print(f"⚠ Dashboard generation failed: {e}")
            interactive_time = 0

        # Performance summary
        total_time = (datetime.now() - start_time).total_seconds()
        print(f"\n📊 Performance Summary:")
        print(f"   Total execution time: {total_time:.3f}s")

        # Success summary
        print(f"\n✅ Successfully processed {len(results)} pairs:")
        for name, result in results.items():
            pair = pair_manager.pairs[name]
            print(f"   • {name}: {pair.leg1} vs {pair.leg2} (R²={result.r_squared:.4f})")
        
    except Exception as e:
        print(f"❌ Error occurred during execution: {e}")
        # Write error to output sheet if Excel is available
        if 'use_excel_output' in locals() and use_excel_output and 'sht_out' in locals():
            try:
                sht_out["A1"].value = f"Error: {str(e)}"
            except:
                pass  # Silently ignore Excel write errors in non-Excel mode
        raise


# For local testing without VBA
if __name__ == "__main__":
    try:
        # Mock Excel environment for testing
        xw.Book(r"Dashboard.xlsm").set_mock_caller()
        main()
    except Exception as e:
        print(f"❌ Test failed: {e}")
