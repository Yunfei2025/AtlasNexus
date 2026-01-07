# -*- coding: utf-8 -*-
"""
Pair Analysis Module - Optimized Version

A streamlined OOP system for financial pair spread analysis with unified dashboard.

Main Components:
- data: Data loading and caching functionality
- stats: Regression analysis and statistical calculations  
- plot: Core Plotly figure generation with responsive sizing
- dashboard: Unified HTML dashboard with refresh functionality
- visualization: Simplified visualization entry point
- excel: Excel I/O operations
- core: Core Pair class with trading pair logic
- manager: Optimized multi-pair orchestration (single analysis computation)
- main: Application entry point and workflow

Usage:
    from pairs import PairManager
    
    manager = PairManager()
    manager.load_pairs_from_excel(excel_sheet)
    analyses = manager.prepare_analysis()  # Single computation
    manager.write_to_excel(sheet, analyses)
    manager.create_dashboard("dashboard.html", analyses)  # Reuse analysis
"""

# Import main classes for easy access
try:
    from .core import Pair
    from .manager import PairManager
    from .stats import RegressionResults, StatisticalAnalyzer
    from .data import DataCache
    from .visualization import PlotGenerator, DashboardGenerator
    from .plot import PlotGenerator as CorePlotGenerator
    from .dashboard import Dashboard
    from .excel import ExcelHandler
    from .main import main
except ImportError as e:
    # Fallback imports for development
    print(f"Warning: Import error in pairs module: {e}")
    import traceback
    traceback.print_exc()

__version__ = "2.2.0"  # Updated version for optimized release
__author__ = "CMBC"

__all__ = [
    'Pair', 'PairManager', 'RegressionResults', 'StatisticalAnalyzer',
    'DataCache', 'PlotGenerator', 'DashboardGenerator', 'CorePlotGenerator',
    'Dashboard', 'ExcelHandler', 'main'
]