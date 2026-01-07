#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Results Structure Restructuring Module - Simplified Version

This module provides functionality to restructure the complex nested results
into a more manageable, flat structure with clearly separated concerns.
"""

from typing import Dict, List, Any
import pandas as pd
from datetime import datetime


class AnalysisStats:
    """Overall analysis statistics"""
    def __init__(self):
        self.total_periods = 0
        self.successful_periods = 0
        self.success_rate = 0.0
        self.combined_months = []
        self.combined_data_points = 0


class BacktestMetrics:
    """Backtest performance metrics"""
    def __init__(self):
        self.total_return = 0.0
        self.annual_return = 0.0
        self.volatility = 0.0
        self.sharpe_ratio = 0.0
        self.max_drawdown = 0.0
        self.win_rate = 0.0
        self.profit_factor = 0.0
        self.win_loss_ratio = 0.0
        self.num_trades = 0


class BacktestData:
    """Backtest data and results"""
    def __init__(self):
        self.strategy_returns = None
        self.cumulative_returns = None
        self.positions = None
        self.actual_returns = None
        self.predictions = None
        self.actual_close_prices = None
        self.predicted_close_prices = None


class PeriodResult:
    """Individual period analysis result"""
    def __init__(self):
        self.month = ""
        self.status = ""
        self.error = None
        self.selected_factors = []
        self.factor_metrics = {}
        self.selected_factor_metrics = {}  # New: IC scores for selected factors
        self.factor_timeseries = {}
        self.data_points = 0
        self.positions = None
        self.signal_strength = None
        self.predictions = None
        self.trained_model = None  # New: trained model with coefficients


class FactorAnalysisResults:
    """Restructured factor analysis results with clear separation of concerns"""
    
    def __init__(self):
        # Analysis metadata
        self.stats = AnalysisStats()
        self.status = 'failed'
        
        # Individual period results
        self.period_results = []
        
        # Combined backtest results
        self.backtest_data = None
        self.backtest_metrics = None
        
        # Model configuration
        self.model_config = None
        
        # Execution info
        self.execution_time = None
        self.timestamp = None


def restructure_results(original_results: Dict) -> FactorAnalysisResults:
    """
    Convert complex nested results structure into clean, structured format.
    
    Args:
        original_results: The original complex results dictionary
        
    Returns:
        FactorAnalysisResults: Restructured results with clear data organization
    """
    
    restructured = FactorAnalysisResults()
    
    # Extract analysis statistics
    restructured.stats.total_periods = original_results.get('total_periods', 0)
    restructured.stats.successful_periods = original_results.get('successful_periods', 0)
    restructured.stats.success_rate = original_results.get('success_rate', 0.0)
    restructured.stats.combined_months = original_results.get('combined_months', [])
    restructured.stats.combined_data_points = original_results.get('combined_data_points', 0)
    
    # Extract individual period results
    if 'results' in original_results:
        for result_entry in original_results['results']:
            month = result_entry.get('month', 'Unknown')
            result_data = result_entry.get('result', {})
            
            period_result = PeriodResult()
            period_result.month = month
            period_result.status = result_data.get('status', 'failed')
            period_result.error = result_data.get('error')
            period_result.selected_factors = result_data.get('selected_factors', [])
            period_result.factor_metrics = result_data.get('selected_factor_metrics', {})
            period_result.selected_factor_metrics = result_data.get('selected_factor_metrics', {})  # New field
            period_result.factor_timeseries = result_data.get('factor_timeseries', {})
            period_result.data_points = result_data.get('data_points', 0)
            period_result.positions = result_data.get('positions')
            period_result.signal_strength = result_data.get('signal_strength')
            period_result.predictions = result_data.get('predictions')
            period_result.trained_model = result_data.get('trained_model')  # New field
            
            restructured.period_results.append(period_result)
    
    # Extract backtest data and metrics
    if 'whole_period_backtest' in original_results:
        bt_data = original_results['whole_period_backtest']
        
        # Backtest data
        restructured.backtest_data = BacktestData()
        restructured.backtest_data.strategy_returns = bt_data.get('strategy_returns')
        restructured.backtest_data.cumulative_returns = bt_data.get('cumulative_returns')
        restructured.backtest_data.positions = bt_data.get('positions')
        restructured.backtest_data.actual_returns = bt_data.get('actual_returns')
        restructured.backtest_data.predictions = bt_data.get('predictions')
        restructured.backtest_data.actual_close_prices = bt_data.get('actual_close_prices')
        restructured.backtest_data.predicted_close_prices = bt_data.get('predicted_close_prices')
        
        # Backtest metrics
        restructured.backtest_metrics = BacktestMetrics()
        restructured.backtest_metrics.total_return = bt_data.get('total_return', 0.0)
        restructured.backtest_metrics.annual_return = bt_data.get('annual_return', 0.0)
        restructured.backtest_metrics.volatility = bt_data.get('annual_volatility', 0.0)  # Fixed: was 'volatility'
        restructured.backtest_metrics.sharpe_ratio = bt_data.get('sharpe_ratio', 0.0)
        restructured.backtest_metrics.max_drawdown = bt_data.get('max_drawdown', 0.0)
        restructured.backtest_metrics.win_rate = bt_data.get('win_rate', 0.0)
        restructured.backtest_metrics.profit_factor = bt_data.get('profit_factor', 0.0)
        restructured.backtest_metrics.win_loss_ratio = bt_data.get('win_loss_ratio', 0.0)
        restructured.backtest_metrics.num_trades = bt_data.get('num_trades', 0)
    
    # Set final status and timestamp
    restructured.status = original_results.get('status', 'failed')
    restructured.timestamp = datetime.now()
    
    return restructured


def print_results_summary(results):
    """Print comprehensive analysis summary."""
    if not results or results.status != 'completed':
        return

    print(f"\n✅ Analysis Summary:")

    # Performance metrics
    if results.backtest_metrics:
        m = results.backtest_metrics
        print(f"📈 Performance: {m.total_return:.2%} return, {m.sharpe_ratio:.3f} Sharpe")
        print(f"📊 Risk: {m.volatility:.2%} volatility, {m.max_drawdown:.2%} max drawdown")
        print(f"🎯 Trading: {m.win_rate:.1%} win rate, {m.num_trades} trades")

    # Period information
    if results.period_results:
        successful = [p for p in results.period_results if p.status == 'success']
        print(f"🕐 Periods: {len(successful)} successful")

        if successful:
            last = successful[-1]
            print(f"📅 Latest ({last.month}): {len(last.selected_factors)} factors")
            if last.selected_factors:
                print(f"📊 Factors: {', '.join(last.selected_factors)}")


def generate_plots(results):
    """Generate plots with error handling."""
    try:
        backtest_result, _, analysis_summary = get_plotting_data(results)
        if backtest_result:
            # print("🎨 Generating plots...")
            from analysis.plots import plot_results
            plot_results(backtest_result, analysis_summary)
            # print("📊 Plots generated successfully")
        else:
            print("⚠️ No backtest result for plotting")
    except Exception as e:
        print(f"⚠️ Plotting failed: {e}")



def display_summary(results: FactorAnalysisResults) -> None:
    """
    Display summary of restructured results in a clean format.
    
    Args:
        results: FactorAnalysisResults object
    """
    print(f"\n{'=' * 60}")
    # print("🔧 RESTRUCTURED FACTOR ANALYSIS RESULTS")
    print("RESTRUCTURED FACTOR ANALYSIS RESULTS")
    print(f"{'=' * 60}")
    
    # Analysis overview
    print(f"\n📊 Analysis Overview:")
    print(f"   Status: {'✅ Completed' if results.status == 'completed' else '❌ Failed'}")
    print(f"   Success Rate: {results.stats.success_rate:.1f}%")
    print(f"   Periods: {results.stats.successful_periods}/{results.stats.total_periods}")
    print(f"   Combined Data Points: {results.stats.combined_data_points}")
    
    # Backtest performance
    if results.backtest_metrics:
        bm = results.backtest_metrics
        print(f"\n🏆 Backtest Performance:")
        print(f"   📈 Total Return: {bm.total_return:.2%}")
        print(f"   📊 Annual Return: {bm.annual_return:.2%}")
        print(f"   📉 Volatility: {bm.volatility:.2%}")
        print(f"   ⚡ Sharpe Ratio: {bm.sharpe_ratio:.3f}")
        print(f"   🎯 Win Rate: {bm.win_rate:.1%}")
        print(f"   💰 Profit Factor: {bm.profit_factor:.3f}")
        print(f"   🔢 Number of Trades: {bm.num_trades}")
    
    # Period results summary
    if results.period_results:
        successful_periods = [p for p in results.period_results if p.status == 'success']
        print(f"\n📋 Period Results Summary:")
        
        if successful_periods:
            # Show last successful period details
            last_period = successful_periods[-1]
            print(f"   Last Period: {last_period.month}")
            print(f"   Selected Factors: {len(last_period.selected_factors)} factors")
            if last_period.selected_factors:
                factor_names = ', '.join(last_period.selected_factors[:3])
                if len(last_period.selected_factors) > 3:
                    factor_names += '...'
                print(f"   Factor Names: {factor_names}")
        
        # Show failed periods if any
        failed_periods = [p for p in results.period_results if p.status != 'success']
        if failed_periods:
            print(f"   Failed Periods: {len(failed_periods)} periods")
    
    print(f"{'=' * 60}")


def get_plotting_data(results: FactorAnalysisResults):
    """
    Extract data needed for plotting from restructured results.
    
    Args:
        results: FactorAnalysisResults object
        
    Returns:
        tuple: (backtest_result_dict, test_returns, analysis_summary_dict)
    """
    # Convert back to format expected by plotting function
    backtest_result = {}
    analysis_summary = {}
    test_returns = pd.Series()

    if results.backtest_data:
        bd = results.backtest_data
        backtest_result = {
            'strategy_returns': bd.strategy_returns,
            'positions': bd.positions,
            'actual_close_prices': bd.actual_close_prices,
            'predicted_close_prices': bd.predicted_close_prices
        }
        
        # Use actual returns as test returns for benchmark
        if bd.actual_returns is not None:
            test_returns = bd.actual_returns

    # Reconstruct analysis summary for plotting
    if results.period_results:
        analysis_summary = {
            'results': [
                {
                    'month': period.month,
                    'result': {
                        'status': period.status,
                        'selected_factors': period.selected_factors or [],
                        'factor_timeseries': period.factor_timeseries or {},
                        'selected_factor_metrics': getattr(period, 'selected_factor_metrics', {}),
                        'trained_model': getattr(period, 'trained_model', None)
                    }
                }
                for period in results.period_results
            ]
        }
        
        # Also add to backtest_result for fallback access
        if results.period_results:
            last_period = results.period_results[-1]
            if hasattr(last_period, 'selected_factor_metrics'):
                backtest_result['selected_factor_metrics'] = last_period.selected_factor_metrics
            if hasattr(last_period, 'trained_model'):
                backtest_result['trained_model'] = last_period.trained_model
  
    
    return backtest_result, test_returns, analysis_summary


def demo_restructuring():
    """Demonstrate the restructuring functionality"""
    
    # print("🔧 Results Restructuring Demo")
    print("Results Restructuring Demo")
    print("=" * 50)
    # print("✅ Original complex nested structure → Clean structured data")
    # print("✅ Reduced nesting levels from 4+ to 2")
    # print("✅ Separated concerns: stats, periods, backtest, metrics")
    # print("✅ Clear class definitions with explicit field organization")
    # print("✅ Easy data access: results.backtest_metrics.sharpe_ratio")
    # print("✅ Plotting data extraction: get_plotting_data(results)")
    print("Original complex nested structure -> Clean structured data")
    print("Reduced nesting levels from 4+ to 2")
    print("Separated concerns: stats, periods, backtest, metrics")
    print("Clear class definitions with explicit field organization")
    print("Easy data access: results.backtest_metrics.sharpe_ratio")
    print("Plotting data extraction: get_plotting_data(results)")


def convert_summary_to_structured_results(summary: Dict) -> FactorAnalysisResults:
    """
    Convert analysis summary to structured results format.
    
    Args:
        summary: Analysis summary dictionary from run_analysis
        
    Returns:
        FactorAnalysisResults: Structured analysis results ready for use
    """
    from datetime import datetime
    
    # Convert to structured results format
    agg_result = FactorAnalysisResults()
    
    # Extract analysis stats
    agg_result.stats.total_periods = summary.get('total_periods', 0)
    agg_result.stats.successful_periods = summary.get('successful_periods', 0)
    agg_result.stats.success_rate = summary.get('success_rate', 0.0)
    agg_result.stats.combined_months = summary.get('combined_months', [])
    agg_result.stats.combined_data_points = summary.get('combined_data_points', 0)
    
    # Extract period results
    if 'results' in summary:
        for result_entry in summary['results']:
            period_result = PeriodResult()
            period_result.month = result_entry.get('month', 'Unknown')
            result_data = result_entry.get('result', {})
            period_result.status = result_data.get('status', 'failed')
            period_result.error = result_data.get('error')
            period_result.selected_factors = result_data.get('selected_factors', [])
            period_result.factor_metrics = result_data.get('selected_factor_metrics', {})
            period_result.selected_factor_metrics = result_data.get('selected_factor_metrics', {})
            period_result.factor_timeseries = result_data.get('factor_timeseries', {})
            period_result.data_points = result_data.get('data_points', 0)
            period_result.positions = result_data.get('positions')
            period_result.signal_strength = result_data.get('signal_strength')
            period_result.predictions = result_data.get('predictions')
            period_result.trained_model = result_data.get('trained_model')
            agg_result.period_results.append(period_result)
    
    # Extract backtest data and metrics
    if 'whole_period_backtest' in summary:
        bt_data = summary['whole_period_backtest']
        agg_result.backtest_data = BacktestData()
        agg_result.backtest_data.strategy_returns = bt_data.get('strategy_returns')
        agg_result.backtest_data.cumulative_returns = bt_data.get('cumulative_returns')
        agg_result.backtest_data.positions = bt_data.get('positions')
        agg_result.backtest_data.actual_returns = bt_data.get('actual_returns')
        agg_result.backtest_data.predictions = bt_data.get('predictions')
        agg_result.backtest_data.actual_close_prices = bt_data.get('actual_close_prices')
        agg_result.backtest_data.predicted_close_prices = bt_data.get('predicted_close_prices')
        
        agg_result.backtest_metrics = BacktestMetrics()
        agg_result.backtest_metrics.total_return = bt_data.get('total_return', 0.0)
        agg_result.backtest_metrics.annual_return = bt_data.get('annual_return', 0.0)
        agg_result.backtest_metrics.volatility = bt_data.get('annual_volatility', 0.0)  # Fixed: was 'volatility'
        agg_result.backtest_metrics.sharpe_ratio = bt_data.get('sharpe_ratio', 0.0)
        agg_result.backtest_metrics.max_drawdown = bt_data.get('max_drawdown', 0.0)
        agg_result.backtest_metrics.win_rate = bt_data.get('win_rate', 0.0)
        agg_result.backtest_metrics.profit_factor = bt_data.get('profit_factor', 0.0)
        agg_result.backtest_metrics.win_loss_ratio = bt_data.get('win_loss_ratio', 0.0)
        agg_result.backtest_metrics.num_trades = bt_data.get('num_trades', 0)
    
    agg_result.status = summary.get('status', 'failed')
    agg_result.timestamp = datetime.now()
    return agg_result


if __name__ == "__main__":
    demo_restructuring()
