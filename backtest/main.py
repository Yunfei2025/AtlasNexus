# -*- coding: utf-8 -*-
"""
Backtesting Module - Main Entry Point

Unified backtesting framework for bonds, IRS, and portfolios.

@author: CMBC
"""
import sys
import pathlib
from typing import Dict, Union
from datetime import date
import pandas as pd

# Add project root to path
PATH = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(PATH))

from settings.general import DateConfig
from backtest.base import Backtester
from backtest.bond import BondBacktester
from backtest.irs import IRSBacktester
from backtest.portfolio import PortfolioBacktester
from backtest.attribution import CampisiAttribution, BondAttribution, IRSAttribution
from backtest.metrics import PerformanceMetrics


# ============================================================
# CONVENIENCE FUNCTIONS
# ============================================================

def backtest_bond_irs_portfolio(bond: str, btype1: str, irs: str, btype2: str, bond_notional: float, irs_notional: float,
                               start: Union[pd.Timestamp, date], end: Union[pd.Timestamp, date]) -> Dict:
    """
    Backtest a portfolio with bond and IRS positions.
    
    Parameters:
    -----------
    bond : str
        Bond identifier (e.g., "190408.IB")
    btype : str
        Bond type (e.g., "TBonds", "R7D")
    irs : str
        IRS instrument identifier (e.g., "FR007S1Y.IR")
    bond_notional : float
        Bond position notional in millions (positive for long, negative for short)
    irs_notional : float
        IRS position notional in millions (positive for receive-fixed, negative for pay-fixed)
    start : date or pd.Timestamp
        Backtest start date
    end : date or pd.Timestamp
        Backtest end date
    
    Returns:
    --------
    Dict : Portfolio backtest results including PnL, attribution, and metrics
    
    Example:
    --------
    # Long 100M bond, short 100M IRS (pay fixed rate)
    results = backtest_bond_irs_portfolio(
        bond="190408.IB",
        btype="TBonds",
        irs="FR007S1Y.IR",
        bond_notional=100,      # Long 100M
        irs_notional=-100,      # Short 100M (pay fixed)
        start=date(2024, 1, 1),
        end=date(2024, 12, 31)
    )
    """
    portfolio = PortfolioBacktester(start, end)
    portfolio.add_bond_position(bond, btype1, bond_notional)
    portfolio.add_irs_position(irs, btype2, irs_notional)
    portfolio.run()
    
    return portfolio.get_results()


# ============================================================
# MAIN EXECUTION
# ============================================================

def main():
    """Main execution function demonstrating OOP backtesting framework."""
    # Get date mappings
    date_map = DateConfig.get_date_mappings()
    end = date_map['dp'].date()
    start = date_map['d3m'].date()
    
    print("=" * 80)
    print("BACKTESTING - BOND")
    print("=" * 80)
    
    # Example 1: Bond backtest using OOP
    bond = "190408.IB"
    btype = "CBond"
    bond_backtester = BondBacktester(bond, btype, start, end)
    bond_backtester.run()
    
    print(f"\nBond: {bond}")
    print(f"Period: {start} to {end}")
    print("\nPerformance Metrics:")
    print(bond_backtester.metrics.to_string())
    
    print("\n" + "=" * 80)
    print("BACKTESTING - IRS")
    print("=" * 80)
    
    # Example 2: IRS backtest using OOP
    irs = "FR007S1Y.IR"
    btype = "r7d"
    notional = 1.0
    irs_backtester = IRSBacktester(irs, btype, start, end, notional)
    irs_backtester.run()
    
    print(f"\nIRS: {irs}")
    print(f"Curve Type: {irs_backtester.metadata['curve_type']}")
    print(f"Contract Start: {irs_backtester.metadata['start']}")
    print(f"Contract Maturity: {irs_backtester.metadata['contract_end']}")
    print(f"Backtest Period: {irs_backtester.metadata['start']} to {irs_backtester.metadata['backtest_end']}")
    print(f"Term: {irs_backtester.metadata['term']:.2f} years")
    print(f"Notional: {irs_backtester.metadata['notional']}")
    print("\nPerformance Metrics:")
    print(irs_backtester.metrics.to_string())
    
    print("\n" + "-" * 80)
    print("CAMPISI ATTRIBUTION - Summary Statistics")
    print("-" * 80)
    print(irs_backtester.attribution[['Carry', 'Roll-down', 'Rate Change', 'Residual', 'Total Return']].describe().round(4))
    
    print("\n" + "-" * 80)
    print("CAMPISI ATTRIBUTION - Contribution Analysis")
    print("-" * 80)
    attr_sum, attr_pct = IRSAttribution(
        irs_backtester.pnl, irs_backtester.quotes, irs_backtester.durations,
        irs_backtester.carry, irs_backtester.rolldown
    ).get_contribution_analysis()
    
    print("\nTotal Contribution by Component:")
    print(attr_sum.to_string())
    print("\nPercentage Contribution:")
    print(attr_pct.to_string() + " %")
    
    print("\n" + "-" * 80)
    print("CAMPISI ATTRIBUTION - Last 5 Days")
    print("-" * 80)
    print(irs_backtester.attribution.tail().round(4).to_string())
    
    print("\n" + "=" * 80)
    print("BACKTESTING - PORTFOLIO (Long Bond + Short IRS)")
    print("=" * 80)
    
    # Example 3: Portfolio backtest - Long 100M bond, Short 100M IRS (pay fixed)
    portfolio_results = backtest_bond_irs_portfolio(
        bond="190408.IB",
        btype1="CBond",
        irs="FR007S1Y.IR",
        bond_notional=100,    # Long 100 million
        btype2="R7D",
        irs_notional=-100,    # Short 100 million (pay fixed rate)
        start=start,
        end=end
    )
    
    print("\n" + "-" * 80)
    print("PORTFOLIO POSITIONS")
    print("-" * 80)
    print(portfolio_results['position_summary'].to_string(index=False))
    
    print("\n" + "-" * 80)
    print("PORTFOLIO PERFORMANCE METRICS")
    print("-" * 80)
    print(portfolio_results['metrics'].to_string())
    
    print("\n" + "-" * 80)
    print("PORTFOLIO ATTRIBUTION - Last 5 Days")
    print("-" * 80)
    if portfolio_results['attribution'] is not None:
        print(portfolio_results['attribution'].tail().round(4).to_string())
    
    print("\n" + "-" * 80)
    print("PORTFOLIO VS INDIVIDUAL COMPONENTS")
    print("-" * 80)
    comparison = pd.DataFrame({
        'Portfolio': [
            portfolio_results['metrics']['Total Return'],
            portfolio_results['metrics']['Annualized Return'],
            portfolio_results['metrics']['Annualized Volatility'],
            portfolio_results['metrics']['Sharpe Ratio'],
            portfolio_results['metrics']['Max Drawdown']
        ],
        'Bond Only': [
            bond_backtester.metrics['Total Return'] * 100,  # Scale to 100M
            bond_backtester.metrics['Annualized Return'] * 100,
            bond_backtester.metrics['Annualized Volatility'] * 100,
            bond_backtester.metrics['Sharpe Ratio'],
            bond_backtester.metrics['Max Drawdown'] * 100
        ],
        'IRS Only': [
            irs_backtester.metrics['Total Return'] * -100,  # Scale to -100M (pay fixed)
            irs_backtester.metrics['Annualized Return'] * -100,
            irs_backtester.metrics['Annualized Volatility'] * 100,  # Vol is always positive
            -irs_backtester.metrics['Sharpe Ratio'],  # Flip sign for pay-fixed
            irs_backtester.metrics['Max Drawdown'] * -100  # Flip for pay-fixed
        ]
    }, index=['Total Return', 'Ann. Return', 'Ann. Volatility', 'Sharpe Ratio', 'Max Drawdown'])
    print(comparison.round(6).to_string())
    
    return {
        'bond': bond_backtester.get_results(),
        'irs': irs_backtester.get_results(),
        'portfolio': portfolio_results
    }


if __name__ == "__main__":
    results = main()
