#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backtest Functions Module

This module contains functions for backtesting factor positions, 
calculating performance metrics, and generating visualization plots.
"""

import pandas as pd
import numpy as np
import os
import pickle
from typing import Dict, Optional, List
from datetime import datetime
try:
    from ..config import config_manager
    from ..analysis.plots import plot_results
except ImportError:
    from config import config_manager
    from analysis.plots import plot_results


def run_backtest(results, actual_price, periods_to_analyze, smoothed_predictions=None) -> Dict:
    """
    Run backtest on factor positions using pre-calculated absolute returns.
    Integrates combined backtest functionality with proper handling of multiple test periods.
    s
    Args:
        positions_or_results: Either position weights/signals from factor analysis (pd.Series)
                             or list of analysis results for integrated processing (List[Dict])
        actual_price: Actual price series for backtesting
        all_predictions: All test period predictions for calculating predicted close prices
        periods_to_analyze: List of test periods (e.g., ['2025-01', '2025-02']) to find proper starting prices
        
    Returns:
        Dictionary containing backtest results with actual and predicted close prices
    """
    try:        # Check if we're doing integrated backtest (multiple results) or single backtest
        # Integrated backtest mode - prepare data from multiple results
        successful_results = [r for r in results if r['result']['status'] == 'success']

        if not successful_results:
            return {
                'backtest_result': {
                    'total_return': 0.0,
                    'annual_return': 0.0, 
                    'annual_volatility': 0.0,
                    'sharpe_ratio': 0.0,
                    'max_drawdown': 0.0,
                    'win_rate': 0.0,
                    'profit_factor': 0.0,
                    'num_trades': 0,
                    'strategy_returns': pd.Series(),
                    'cumulative_returns': pd.Series(),
                    'positions': pd.Series(),
                    'actual_close_prices': pd.Series(),
                    'predicted_close_prices': pd.Series()
                },
                'successful_months': periods_to_analyze
            }

        # Combine data from all successful periods
        all_predictions = pd.concat([r['result']['predictions'] for r in successful_results if r['result'].get('predictions') is not None])
        positions = pd.concat([r['result']['positions'] for r in successful_results])

        # Store reference to successful results for later use
        _successful_results = successful_results        # Calculate returns at t+1 to align with prediction horizon
        # Since factor(t) predicts return(t+1), position(t) should earn return(t+1)
        absolute_returns = actual_price.diff(1).shift(-1).loc[all_predictions.index]  # Shift returns forward by 1 day
        
        common_idx = positions.index.intersection(absolute_returns.index)

        positions_aligned = positions.loc[common_idx]
        returns_aligned = absolute_returns.loc[common_idx]

        print(f"📊 Using look-ahead bias corrected returns ({len(returns_aligned)} points)")
        print(f"📊 Position timing: factors(t) → predictions(t+1) → positions(t) → returns(t+1)")

        common_dates = returns_aligned.index.intersection(actual_price.index)
        aligned_prices = actual_price.loc[common_dates]

        # Calculate predicted close prices for all test periods
        predicted_close_prices = pd.Series(index=all_predictions.index, dtype=float)
        for i in periods_to_analyze:
            test_start = i[2]
            test_end = i[3]
            # Find the last trading day before the first test period
            idx = actual_price.index.get_indexer([test_start],method="bfill")[0]
            starting_price = actual_price.iloc[idx]
            # Calculate predicted close prices iteratively for all predictions
            # all_predictions contains relative returns, so we need cumulative product of (1 + returns)
            period_predictions = all_predictions.loc[test_start:test_end]
            predicted_close_prices.loc[test_start:test_end] = starting_price * (1 + period_predictions).cumprod()
            print(f"📊 Calculated predicted close prices for {len(period_predictions)} periods (from {test_start} to {test_end})")

        # Apply strategy positions to get strategy returns
        strategy_positions = positions_aligned.loc[common_dates]
        strategy_returns = strategy_positions * returns_aligned

        relative_returns = strategy_returns / aligned_prices.shift(1)
        print(f"📊 Strategy relative returns range: {relative_returns.min():.6f} to {relative_returns.max():.6f}, std: {relative_returns.std():.6f}")

        # Calculate performance metrics using relative returns
        # Cumulative return calculation
        cumulative_returns = (1 + relative_returns).cumprod()
        total_return = cumulative_returns.iloc[-1] - 1  # Final cumulative return minus 1

        # Volatility and other metrics
        mean_return = relative_returns.mean()
        volatility = relative_returns.std()

        # Annualized metrics (252 trading days)
        annual_return = (1 + mean_return) ** 252 - 1  # Compound annualization
        annual_volatility = volatility * np.sqrt(252)
        sharpe_ratio = annual_return / annual_volatility if annual_volatility > 0 else 0

        # Max drawdown calculation using cumulative returns
        running_max = cumulative_returns.expanding().max()
        drawdowns = (cumulative_returns - running_max) / running_max
        max_drawdown = drawdowns.min()

        # Use smoothed predictions if available, otherwise fall back to raw predictions
        predictions_for_win_rate = smoothed_predictions if smoothed_predictions is not None else all_predictions
        
        common_pred_idx = predictions_for_win_rate.index.intersection(returns_aligned.index)
        if len(common_pred_idx) > 0:
            predictions_aligned = predictions_for_win_rate.loc[common_pred_idx]
            actual_returns_aligned = returns_aligned.loc[common_pred_idx]
            
            # Win rate = percentage of times prediction and actual return have same sign
            correct_direction = (np.sign(predictions_aligned) == np.sign(actual_returns_aligned))
            win_rate = correct_direction.mean()
            prediction_type = "smoothed" if smoothed_predictions is not None else "raw"
            print(f"📊 Directional accuracy ({prediction_type}): {win_rate:.3f} ({len(common_pred_idx)} predictions)")
        else:
            win_rate = 0.0
            print(f"⚠️ No overlapping predictions and returns for win rate calculation")
        
        # Calculate profit factor (average gain / average loss) - use relative returns for proper calculation
        if len(relative_returns) > 0:
            wins = relative_returns[relative_returns > 0]
            losses = relative_returns[relative_returns < 0]
            
            if len(losses) > 0 and losses.mean() != 0:
                profit_factor = abs(wins.mean() / losses.mean())
            else:
                profit_factor = float('inf') if len(wins) > 0 else 0.0
        else:
            profit_factor = 0.0
            
        # Also calculate win-loss ratio for comparison
        win_loss_ratio = win_rate / (1 - win_rate) if win_rate < 1.0 else float('inf')
          # Build simplified backtest result with essential metrics only
        num_trades = len(relative_returns) if len(relative_returns) > 0 else len(strategy_returns)
        
        backtest_result = {
            # Core performance metrics
            'total_return': total_return,
            'annual_return': annual_return,
            'annual_volatility': annual_volatility,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            
            # Trading metrics
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'num_trades': num_trades,
            
            # Core data for plotting and analysis
            'strategy_returns': relative_returns,
            'cumulative_returns': cumulative_returns,
            'positions': positions_aligned,
            'actual_close_prices': actual_price.loc[predicted_close_prices.index],
            'predicted_close_prices': predicted_close_prices
        }
          # If this was an integrated backtest, format the results appropriately
        if _successful_results is not None:
            # Add trained_model from last successful result
            last_result = _successful_results[-1]['result']
            trained_model = last_result.get('trained_model', None)
            if trained_model is not None:
                backtest_result['trained_model'] = trained_model
            
            # Format positions for compatibility
            backtest_result['positions'] = (pd.DataFrame({'Asset_1': positions}) 
                                           if isinstance(positions, pd.Series) 
                                           else positions)
            
            # Simplified return structure - flatter with only essential data
            return {
                'backtest_result': backtest_result,
                'successful_months': periods_to_analyze
            }
        
        return backtest_result
            
    except Exception as e:
        print(f"❌ Backtest failed: {e}")
        return {'error': f'Backtest failed: {str(e)}'}


def display_summary(summary: Dict):
    """
    Display optimized summary of analysis results
    
    Args:
        summary: Dictionary containing analysis results
    """
    print(f"\n{'=' * 60}")
    # print("⚡ FAST FACTOR ANALYSIS RESULTS")
    print("FAST FACTOR ANALYSIS RESULTS")
    print(f"{'=' * 60}")

    # Results summary
    print(f"\n📊 Results:")
    print(f"   Success rate: {summary.get('success_rate', 0):.1f}%")
    print(f"   Successful periods: {summary.get('successful_periods', 0)}/{summary.get('total_periods', 0)}")

    if summary.get('successful_periods', 0) > 0:
        print(f"   Status: ✅ Completed")

        # Show whole period backtest results
        if 'whole_period_backtest' in summary and summary['whole_period_backtest']:
            bt = summary['whole_period_backtest']
            print(f"\n🏆 WHOLE PERIOD BACKTEST RESULTS:")
            print(f"   Data points: {summary.get('combined_data_points', 0)}")

            sharpe = bt.get('sharpe_ratio', 0)
            annual_ret = bt.get('annual_return', 0)
            volatility = bt.get('annual_volatility', 0)  # Fixed: was 'volatility', should be 'annual_volatility'
            total_ret = bt.get('total_return', 0)
            win_rate = bt.get('win_rate', 0)
            profit_factor = bt.get('profit_factor', 0)
            win_loss_ratio = bt.get('win_loss_ratio', 0)

            print(f"   📈 Total Return: {total_ret:.4f} ({total_ret * 100:.2f}%)")
            print(f"   📊 Annual Return: {annual_ret:.4f} ({annual_ret * 100:.2f}%)")
            print(f"   📉 Volatility: {volatility:.4f} ({volatility * 100:.2f}%)")
            print(f"   ⚡ Sharpe Ratio: {sharpe:.4f}")
            print(f"   🎯 Win Rate: {win_rate:.3f} ({win_rate * 100:.1f}%)")
            print(f"   💰 Profit Factor (Avg Gain/Avg Loss): {profit_factor:.3f}")
            print(f"   ⚖️ Win-Loss Ratio: {win_loss_ratio:.3f} (Win:Loss = {win_loss_ratio:.2f}:1)")
            print("    ✅ Backtest completed successfully")
        else:
            print(f"\n❌ Whole period backtest failed or unavailable")
            if 'concatenation_error' in summary:
                print(f"   Error: {summary['concatenation_error']}")

        # Show individual successful periods for reference
        successful_results = [r for r in summary.get('results', []) if r.get('result', {}).get('status') == 'success']
        if successful_results:
            print(f"\n📋 Individual successful periods:")
            for result in successful_results:
                result_data = result.get('result', {})
                print(f"   {result.get('month', 'Unknown')}: Positions created ({result_data.get('data_points', 0)} points)")
    else:
        print(f"   Status: ❌ Failed")

    print(f"{'=' * 60}")
