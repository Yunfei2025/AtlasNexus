# -*- coding: utf-8 -*-
"""
Generate Portfolio Dashboard HTML

Creates interactive HTML dashboard for portfolio backtesting results.

@author: CMBC
"""
import sys
import pathlib
from datetime import date

# Add project root to path
PATH = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(PATH))

from settings.general import DateConfig
from backtest.portfolio import PortfolioBacktester
from backtest.visualization import plot_backtest_dashboard


def generate_portfolio_dashboard(
    bond: str = "190408.IB",
    irs: str = "FR007S1Y.IR",
    bond_notional: float = 100,
    irs_notional: float = -100,
    start_date: date = None,
    end_date: date = None,
    output_file: str = "portfolio_dashboard.html"
):
    """
    Generate portfolio dashboard HTML file.
    
    Parameters:
    -----------
    bond : str
        Bond identifier (e.g., "190408.IB")
    irs : str
        IRS instrument identifier (e.g., "FR007S1Y.IR")
    bond_notional : float
        Bond position notional in millions (positive for long, negative for short)
    irs_notional : float
        IRS position notional in millions (positive for receive-fixed, negative for pay-fixed)
    start_date : date, optional
        Backtest start date (defaults to 3 months ago)
    end_date : date, optional
        Backtest end date (defaults to today)
    output_file : str
        Output HTML filename
    """
    # Get default dates if not provided
    if start_date is None or end_date is None:
        date_map = DateConfig.get_date_mappings()
        end_date = end_date or date_map['dp'].date()
        start_date = start_date or date_map['d3m'].date()
    
    print("=" * 80)
    print("GENERATING PORTFOLIO DASHBOARD")
    print("=" * 80)
    print(f"\nPortfolio Positions:")
    print(f"  Bond: {bond} ({bond_notional:+.0f}M)")
    print(f"  IRS: {irs} ({irs_notional:+.0f}M)")
    print(f"\nPeriod: {start_date} to {end_date}")
    print(f"Output: {output_file}\n")
    
    # Create and run portfolio backtest
    portfolio = PortfolioBacktester(start_date, end_date)
    portfolio.add_bond_position(bond, bond_notional)
    portfolio.add_irs_position(irs, irs_notional)
    portfolio.run()
    
    # Get results
    results = portfolio.get_results()
    
    # Create dashboard visualization
    print("\nGenerating dashboard visualization...")
    
    # Prepare comparison data (portfolio vs components)
    # Each entry needs to be a dict with 'pnl' and 'metrics' keys
    comparison_data = {
        'Portfolio': {
            'pnl': results['pnl'],
            'metrics': results['metrics']
        }
    }
    
    # Add individual components with proper structure
    rate_data_dict = {}
    for key, comp in results['components'].items():
        # Create readable name for component
        comp_type = comp['type'].upper()
        instrument = key.split('_', 1)[1]
        comp_name = f"{comp_type} {instrument}"
        
        comparison_data[comp_name] = {
            'pnl': comp['scaled_pnl'],
            'metrics': comp['backtester'].metrics
        }
        
        # Collect rate/ytm data for rate_data parameter
        if comp_type == 'BOND':
            rate_data_dict[f'{instrument}_ytm'] = {
                'data': comp['backtester'].yields,
                'name': f'{instrument} YTM'
            }
        elif comp_type == 'IRS':
            rate_data_dict[f'{instrument}_rate'] = {
                'data': comp['backtester'].quotes,
                'name': f'{instrument} Rate'
            }
    
    # Create dashboard figure
    fig = plot_backtest_dashboard(
        pnl=results['pnl'],
        attribution=results['attribution'],
        metrics=results['metrics'],
        capital=results['total_capital'],
        title=f"Portfolio Dashboard: {bond} ({bond_notional:+.0f}M) + {irs} ({irs_notional:+.0f}M)",
        comparison_data=comparison_data,
        rate_data=rate_data_dict if rate_data_dict else None
    )
    
    # Save to HTML
    fig.write_html(output_file)
    
    print(f"\n✅ Dashboard saved to: {output_file}")
    print("\n" + "=" * 80)
    print("PORTFOLIO SUMMARY")
    print("=" * 80)
    print(f"\nTotal Capital: {results['total_capital']:,.2f}")
    print(f"\nPerformance Metrics:")
    print(results['metrics'].to_string())
    print("\n" + "=" * 80)
    
    return results


if __name__ == "__main__":
    # Example: Long 100M bond, Short 100M IRS (pay fixed)
    results = generate_portfolio_dashboard(
        bond="190408.IB",
        irs="FR007S1Y.IR",
        bond_notional=100,    # Long 100 million
        irs_notional=0,#-100,    # Short 100 million (pay fixed rate)
        output_file="portfolio_dashboard.html"
    )
