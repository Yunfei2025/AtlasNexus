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
import pandas as pd

# Add project root to path
PATH = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(PATH))

from pairs.manager import PairManager

# Suppress warnings for better performance
warnings.filterwarnings('ignore')


def _console(message: str) -> None:
    """Print messages safely on Windows consoles with legacy encodings."""
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, 'encoding', None) or 'utf-8'
        safe = message.encode(encoding, errors='replace').decode(encoding, errors='replace')
        print(safe)


def _load_pairs_from_generated_candidates(pair_manager: PairManager, max_pairs: int = 4, window: int = 30) -> bool:
    """Populate pairs from generated carry-roll candidates for standalone mode."""
    from curves.generators.pairs import PairsGenerator

    cr_df = PairsGenerator().generate()
    if not isinstance(cr_df, pd.DataFrame) or cr_df.empty:
        return False

    candidates = cr_df[['Long', 'Short']].dropna().drop_duplicates().head(max_pairs)
    for idx, row in enumerate(candidates.itertuples(index=False), start=1):
        pair_manager.add_pair(f"pair{idx}", str(row.Long), str(row.Short), window=window)

    return len(pair_manager) > 0


def main(excel_mode=True, excel_path=None):
    """Main function using OOP approach for better organization and performance.

    Parameters
    ----------
    excel_mode : bool
        If True, use Excel interface (requires xlwings). If False, run in standalone mode.
    excel_path : str or Path, optional
        Path to Excel file when not using Book.caller().
    """
    start_time = datetime.now()

    try:
        if excel_mode:
            try:
                wb = xw.Book.caller()
                sht_cfg = wb.sheets["Main"]
                sht_out = wb.sheets["Main"]
                use_excel_output = True
            except Exception as exc:
                _console(f"⚠ Book.caller() failed: {exc}")
                if excel_path:
                    wb = xw.Book(excel_path)
                    wb.set_mock_caller()
                    sht_cfg = wb.sheets["Main"]
                    sht_out = wb.sheets["Main"]
                    use_excel_output = True
                else:
                    _console("ℹ Falling back to non-Excel mode (no Excel output)")
                    use_excel_output = False
        else:
            use_excel_output = False

        _console("🚀 Starting Pair Analysis with modular OOP approach...")

        config_start = datetime.now()
        pair_manager = PairManager()

        if use_excel_output and 'sht_cfg' in locals():
            pair_manager.load_pairs_from_excel(sht_cfg)
        else:
            if excel_path:
                try:
                    excel_path_str = str(excel_path)
                    existing_wb = None

                    for wb in xw.books:
                        if pathlib.Path(wb.fullname).resolve() == pathlib.Path(excel_path_str).resolve():
                            existing_wb = wb
                            break

                    if existing_wb:
                        _console(f"ℹ Using already-open Excel workbook: {existing_wb.name}")
                        temp_sht = existing_wb.sheets["Main"]
                        pair_manager.load_pairs_from_excel(temp_sht)
                    else:
                        temp_wb = xw.Book(excel_path)
                        temp_sht = temp_wb.sheets["Main"]
                        pair_manager.load_pairs_from_excel(temp_sht)
                        temp_wb.close()
                except Exception as exc:
                        _console(f"⚠ Could not load from Excel file: {exc}")
                        _console("ℹ Falling back to generated standalone pair candidates")
                        _load_pairs_from_generated_candidates(pair_manager)
            else:
                _console("ℹ Running in standalone mode - using generated pair candidates")
                _load_pairs_from_generated_candidates(pair_manager)

        config_time = (datetime.now() - config_start).total_seconds()
        _console(f"✓ Configuration loading time: {config_time:.3f}s")
        _console(f"✓ Loaded {len(pair_manager)} pairs")

        if len(pair_manager) == 0:
            _console("⚠ No pair configurations available; skipping pairs refresh")
            return {}

        analysis_start = datetime.now()
        analyses = pair_manager.prepare_analysis()
        analysis_time = (datetime.now() - analysis_start).total_seconds()
        _console(f"✓ Analysis computation time: {analysis_time:.3f}s")

        results = pair_manager.get_results(analyses)
        _console(f"✓ Analysis results prepared: {len(results)} pairs")

        if len(results) == 0:
            _console("⚠ No pair analyses available; skipping dashboard refresh")
            return {}

        if use_excel_output and 'sht_out' in locals():
            write_start = datetime.now()
            pair_manager.write_to_excel(sht_out, analyses)
            write_time = (datetime.now() - write_start).total_seconds()
            _console(f"✓ Results writing time: {write_time:.3f}s")

            plot_start = datetime.now()
            pair_manager.create_excel_plots(sht_out, analyses)
            plot_time = (datetime.now() - plot_start).total_seconds()
            _console(f"✓ Chart generation time: {plot_time:.3f}s")

        interactive_start = datetime.now()
        try:
            import os

            dashboard_path = pair_manager.create_dashboard(os.path.join("pairs", "regression_plots.html"), analyses)
            interactive_time = (datetime.now() - interactive_start).total_seconds()
            _console(f"✓ Dashboard created: {interactive_time:.3f}s")
            _console(f"✓ Access dashboard at: {dashboard_path}")
        except Exception as exc:
            _console(f"⚠ Dashboard generation failed: {exc}")

        total_time = (datetime.now() - start_time).total_seconds()
        _console("\n📊 Performance Summary:")
        _console(f"   Total execution time: {total_time:.3f}s")

        _console(f"\n✅ Successfully processed {len(results)} pairs:")
        for name, result in results.items():
            pair = pair_manager.pairs[name]
            _console(f"   • {name}: {pair.leg1} vs {pair.leg2} (R²={result.r_squared:.4f})")

    except Exception as exc:
        _console(f"❌ Error occurred during execution: {exc}")
        if 'use_excel_output' in locals() and use_excel_output and 'sht_out' in locals():
            try:
                sht_out["A1"].value = f"Error: {str(exc)}"
            except Exception:
                pass
        raise


# For local testing without VBA
if __name__ == "__main__":
    try:
        main(excel_mode=False)
    except Exception as e:
        _console(f"❌ Test failed: {e}")
