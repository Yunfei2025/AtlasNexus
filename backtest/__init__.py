# -*- coding: utf-8 -*-
"""
Backtest Module

Object-oriented backtesting framework for bonds, IRS, and portfolios.

Architecture:
- Attribution: Campisi attribution model for return decomposition
- Metrics: Performance metrics calculator
- Backtesters: Bond, IRS, and Portfolio backtesting engines
- Base: Abstract base class for all backtesters

@author: CMBC
"""

# Base class
from backtest.base import Backtester

# Attribution classes
from backtest.attribution import (
    CampisiAttribution,
    BondAttribution,
    IRSAttribution
)

# Metrics
from backtest.metrics import PerformanceMetrics

# Backtester implementations
from backtest.bond import BondBacktester
from backtest.irs import IRSBacktester
from backtest.portfolio import PortfolioBacktester

# Convenience functions
from backtest.main import backtest_bond_irs_portfolio

# Visualization functions
from backtest.visualization import (
    plot_pnl_curve,
    plot_drawdown,
    plot_attribution,
    plot_metrics_table,
    plot_backtest_dashboard,
    plot_portfolio_comparison,
    plot_rate_timeseries
)


__all__ = [
    # Base
    'Backtester',
    
    # Attribution
    'CampisiAttribution',
    'BondAttribution',
    'IRSAttribution',
    
    # Metrics
    'PerformanceMetrics',
    
    # Backtesters
    'BondBacktester',
    'IRSBacktester',
    'PortfolioBacktester',
    
    # Convenience
    'backtest_bond_irs_portfolio',
    
    # Visualization
    'plot_pnl_curve',
    'plot_drawdown',
    'plot_attribution',
    'plot_metrics_table',
    'plot_backtest_dashboard',
    'plot_portfolio_comparison',
    'plot_rate_timeseries'
]
