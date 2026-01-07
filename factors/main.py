#!/usr/bin/env python3
"""
Updated main.py for factors with proper imports
"""
import sys
from pathlib import Path

# Ensure parent directory (containing the `factors` package) is on sys.path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

def main():
    from factors.utils.retrieve import (futuresDailyK, retrieveMarcoPx)
    # futuresDailyK()
    retrieveMarcoPx()
    # print("🚀 Factor Analysis Engine")
    # print("=" * 50)

    import importlib
    fe = importlib.import_module('factors.engine.factor_engine')
    cfg = importlib.import_module('factors.config')
    run_analysis = fe.run_analysis
    config_manager = cfg.config_manager
    # print("✅ Successfully imported from factors package")

    date_config = config_manager.date_config
    model_config = config_manager.model_config

    # Run analysis
    results = run_analysis(
        start_date=date_config.day_data_start_date,
        end_date=date_config.day_data_end_date,
        ticker=model_config.ticker
    )

    from analysis.aggresults import display_summary, print_results_summary,generate_plots
    display_summary(results)
    print_results_summary(results)
    generate_plots(results)

    if results:
        # print("✅ Factor analysis completed successfully")
        return results
    else:
        # print("❌ Factor analysis failed")
        return None

if __name__ == "__main__":
    main()