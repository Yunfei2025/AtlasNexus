# -*- coding: utf-8 -*-
"""
Main Execution Script

Runs the complete futures portfolio strategy analysis.

@author: CMBC
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import pandas as pd

# Add project path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from settings.paths import DIR_INPUT
from futures.daily import (
    FuturesPortfolioSelector,
    TrendFollowingStrategy,
    MeanReversionStrategy,
    StrategyBacktester,
    StrategyBlender,
)


def main():
    """Execute the complete analysis pipeline."""
    
    # Load data
    file_path = os.path.join(DIR_INPUT, 'futures-dailyK_con.pkl')
    data = pd.read_pickle(file_path)
    
    print("="*80)
    print("FUTURES PORTFOLIO STRATEGY SYSTEM")
    print("="*80)
    
    # 1. Portfolio Selection
    print("\n1. DIVERSIFIED PORTFOLIO SELECTION")
    print("-" * 80)
    
    selector = FuturesPortfolioSelector(data, lookback_months=12)
    
    # Find a suitable date from the data
    sample_ticker = list(data.keys())[0]
    available_dates = data[sample_ticker].index
    rebalance_date = available_dates[-252]  # 1 year before end
    
    selected_tickers = selector.select_diversified_portfolio(
        rebalance_date=rebalance_date,
        n_assets=5
    )
    
    print(f"Selected tickers (as of {rebalance_date}):")
    for ticker in selected_tickers:
        print(f"  - {ticker}")
    
    # Show correlation matrix
    corr_matrix = selector.get_correlation_matrix(selected_tickers, rebalance_date)
    if not corr_matrix.empty:
        print(f"\nCorrelation Matrix:")
        print(corr_matrix.round(3))
    
    # 2. Strategy Design & 3. Backtesting (using first selected ticker)
    print(f"\n2-3. STRATEGY BACKTESTING (Ticker: {selected_tickers[0]})")
    print("-" * 80)
    
    test_ticker = selected_tickers[0]
    test_data = data[test_ticker].copy()
    
    # Filter to last 5 years
    end_date = test_data.index.max()
    start_date = end_date - pd.DateOffset(years=5)
    test_data = test_data[test_data.index >= start_date]
    
    print(f"Backtest period: {test_data.index.min().date()} to {test_data.index.max().date()}")
    print(f"Total trading days: {len(test_data)}")
    
    # Initialize strategies
    trend_strategy = TrendFollowingStrategy(fast_period=20, slow_period=60)
    mr_strategy = MeanReversionStrategy(period=20, num_std=2.0)
    
    # Calculate strategy returns
    trend_returns = trend_strategy.calculate_returns(test_data)
    mr_returns = mr_strategy.calculate_returns(test_data)
    buy_hold_returns = test_data['close'].pct_change().fillna(0)
    
    # Backtest
    backtester = StrategyBacktester(test_data)
    
    strategies = {
        'Trend Following': trend_returns,
        'Mean Reversion': mr_returns,
        'Buy & Hold': buy_hold_returns
    }
    
    comparison = backtester.compare_strategies(strategies)
    print(f"\nStrategy Performance Comparison:")
    print(comparison)
    
    # 4. Strategy Combination
    print(f"\n4. STRATEGY COMBINATION OPTIMIZATION")
    print("-" * 80)
    
    blender = StrategyBlender({
        'Trend': trend_returns,
        'MeanRev': mr_returns
    })
    
    # Optimize for maximum Sharpe ratio
    optimal_weights_sharpe = blender.optimize_weights(objective='sharpe')
    print(f"\nOptimal Weights (Max Sharpe):")
    for strategy, weight in optimal_weights_sharpe.items():
        print(f"  {strategy}: {weight:.3f}")
    
    # Optimize with drawdown constraint
    optimal_weights_dd = blender.optimize_weights(
        objective='sharpe',
        max_drawdown_constraint=0.15  # Max 15% drawdown
    )
    print(f"\nOptimal Weights (Max Sharpe with 15% DD constraint):")
    for strategy, weight in optimal_weights_dd.items():
        print(f"  {strategy}: {weight:.3f}")
    
    # Backtest blended strategy
    blended_returns_sharpe = blender.get_blended_returns(optimal_weights_sharpe)
    blended_returns_dd = blender.get_blended_returns(optimal_weights_dd)
    
    strategies_with_blend = {
        'Trend Following': trend_returns,
        'Mean Reversion': mr_returns,
        'Blended (Max Sharpe)': blended_returns_sharpe,
        'Blended (DD Constrained)': blended_returns_dd,
        'Buy & Hold': buy_hold_returns
    }
    
    final_comparison = backtester.compare_strategies(strategies_with_blend)
    print(f"\nFinal Performance Comparison (Including Blended):")
    print(final_comparison)
    
    print("\n" + "="*80)
    print("ANALYSIS COMPLETE")
    print("="*80)


def run_with_summary() -> dict | None:
    """Same computation as main() but returns a structured summary dict.

    Returns a dict with keys:
      symbol       – first selected ticker
      period_start / period_end – ISO date strings of the backtest window
      strategies   – {strategy_name: {total_return, ann_return, ann_vol,
                                       sharpe, max_drawdown, equity_curve, dates}}

    Returns None on any error (data missing, etc.) so callers can treat
    the result as optional without crashing the pipeline.
    """
    try:
        file_path = os.path.join(DIR_INPUT, 'futures-dailyK_con.pkl')
        if not os.path.exists(file_path):
            return None

        data = pd.read_pickle(file_path)
        sample_ticker = list(data.keys())[0]
        available_dates = data[sample_ticker].index
        rebalance_date = available_dates[-252]

        selector = FuturesPortfolioSelector(data, lookback_months=12)
        selected_tickers = selector.select_diversified_portfolio(
            rebalance_date=rebalance_date, n_assets=5
        )

        test_ticker = selected_tickers[0]
        test_data = data[test_ticker].copy()
        end_date = test_data.index.max()
        start_date = end_date - pd.DateOffset(years=5)
        test_data = test_data[test_data.index >= start_date]

        trend_returns = TrendFollowingStrategy(fast_period=20, slow_period=60).calculate_returns(test_data)
        mr_returns = MeanReversionStrategy(period=20, num_std=2.0).calculate_returns(test_data)
        buy_hold_returns = test_data['close'].pct_change().fillna(0)

        blender = StrategyBlender({'Trend': trend_returns, 'MeanRev': mr_returns})
        optimal_weights = blender.optimize_weights(objective='sharpe')
        blended_returns = blender.get_blended_returns(optimal_weights)

        backtester = StrategyBacktester(test_data)
        all_strategies = {
            'Trend Following': trend_returns,
            'Mean Reversion': mr_returns,
            'Blended (Max Sharpe)': blended_returns,
            'Buy & Hold': buy_hold_returns,
        }

        strategies_out: dict = {}
        for name, returns in all_strategies.items():
            r = backtester.run_backtest(returns)
            equity = r.get('cum_returns')
            strategies_out[name] = {
                'total_return': float(r.get('total_return', 0)),
                'ann_return': float(r.get('annualized_return', 0)),
                'ann_vol': float(r.get('annualized_volatility', 0)),
                'sharpe': float(r.get('sharpe_ratio', 0)),
                'max_drawdown': float(r.get('max_drawdown', 0)),
                'equity_curve': equity.tolist() if equity is not None else None,
                'dates': [d.isoformat() for d in equity.index] if equity is not None else None,
            }

        return {
            'symbol': test_ticker,
            'period_start': test_data.index.min().date().isoformat(),
            'period_end': test_data.index.max().date().isoformat(),
            'strategies': strategies_out,
        }
    except Exception:
        return None


if __name__ == "__main__":
    main()
