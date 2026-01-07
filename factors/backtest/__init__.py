"""
Backtesting package for factor analysis.
"""

try:
    from .runner import display_summary, run_backtest
except ImportError:
    from backtest.runner import display_summary, run_backtest

__all__ = ['display_summary', 'run_backtest']