#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Factor Analysis Utilities

This module contains utility functions for factor analysis results processing,
CSV export, and data aggregation to keep the main FactorEngine clean.
"""

import pandas as pd
import csv
import joblib
from typing import Dict, List, Tuple
from datetime import datetime
from dateutil.relativedelta import relativedelta

def generate_analysis_periods(start_dt: datetime, end_dt: datetime, ticker: str, config) -> Tuple[List[Tuple], datetime, datetime]:
    """
    Generate periods for analysis with train/test splits.
    
    Args:
        start_dt: Analysis start datetime
        end_dt: Analysis end datetime
        ticker: Instrument ticker
        config: Model configuration object
        
    Returns:
        Tuple of (periods_to_analyze, last_test_start, last_test_end)
    """
    periods_to_analyze = []
    current_month = datetime(start_dt.year, start_dt.month, 1).date()
    last_test_start = None
    last_test_end = None
    
    while current_month < end_dt:
        train_end = current_month - relativedelta(days=1)
        test_start = current_month
        test_end = current_month + relativedelta(months=1) - relativedelta(days=1)
        
        # Track the last period dates for filename
        last_test_start = test_start
        last_test_end = test_end
        
        period_args = (
            current_month.strftime('%Y-%m-%d'),
            train_end,
            test_start,
            test_end,
            ticker,
            config
        )
        
        periods_to_analyze.append(period_args)
        current_month += relativedelta(months=1)
    
    return periods_to_analyze, last_test_start, last_test_end


def save_factor_analysis_results(results: List[Dict], output_file: str = "factor_analysis_results.csv"):
    """Save selected factors and their metrics to CSV file - only for the last test period."""
    try:
        # Find the last successful period
        successful_results = [r for r in results if r['result']['status'] == 'success']
        if not successful_results:
            print("⚠️ No successful factor selections to save")
            return
        
        # Get the last period (assuming results are in chronological order)
        last_result = successful_results[-1]
        last_month = last_result['month']
        selected_factors = last_result['result'].get('selected_factors', [])
        selected_metrics = last_result['result'].get('selected_factor_metrics', {})
        
        # print(f"📅 Saving results for last test period: {last_month}")
        
        if not selected_factors:
            print("⚠️ No factors selected in the last period")
            return
        
        # Prepare data for the last period only
        factor_data = []
        for factor in selected_factors:
            factor_info = {
                'factor_name': factor,
                'test_period': last_month,
                'selected': True
            }
            
            # Add metrics if available
            if factor in selected_metrics:
                factor_metrics = selected_metrics[factor]
                factor_info.update(factor_metrics)
            
            factor_data.append(factor_info)
        
        # Save to CSV
        with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
            if factor_data:
                # Get all possible fieldnames
                fieldnames = ['factor_name', 'test_period', 'selected']
                # Add metric fieldnames
                for item in factor_data:
                    for key in item.keys():
                        if key not in fieldnames:
                            fieldnames.append(key)
                
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(factor_data)
        
        # print(f"📊 Last period factor results saved to: {output_file}")
        print(f"   Test period: {last_month}")
        print(f"   Selected factors: {len(selected_factors)}")
        
        # Show all selected factors for the last period
        print(f"\n� Selected Factors for Last Period ({last_month}):")
        for i, factor_info in enumerate(factor_data, 1):
            metrics_info = ""
            # Show IC metric if available
            ic_metric = factor_info.get('IC', factor_info.get('ic', None))
            if ic_metric is not None:
                metrics_info = f" (IC: {ic_metric:.3f})"
            print(f"   {i}. {factor_info['factor_name']}{metrics_info}")
            
    except Exception as e:
        print(f"❌ Failed to save factor analysis results: {e}")


def create_analysis_summary(results: List[Dict], successful_count: int, backtest_results: Dict) -> Dict:
    """Create simplified analysis summary with essential data only."""
    total_periods = len(results)
    success_rate = (successful_count / total_periods * 100) if total_periods > 0 else 0
    
    summary = {
        'total_periods': total_periods,
        'successful_periods': successful_count,
        'success_rate': success_rate,
        'results': results,
        'status': 'completed' if successful_count > 0 else 'failed'
    }
    
    # Add simplified backtest data without unnecessary nesting
    if backtest_results.get('backtest_result'):
        bt_result = backtest_results['backtest_result']
        summary['whole_period_backtest'] = bt_result
        summary['combined_months'] = backtest_results.get('successful_months', [])
        # Calculate data points from actual positions data
        if 'positions' in bt_result and bt_result['positions'] is not None:
            summary['combined_data_points'] = len(bt_result['positions'])
        else:
            summary['combined_data_points'] = 0
    
    return summary


def extract_factor_timeseries(selected_factors: List[str], all_factors: pd.DataFrame, 
                             train_data: pd.DataFrame, test_data: pd.DataFrame) -> Dict[str, pd.Series]:
    """
    Extract selected factor time series for plotting over the combined train+test period.
    
    Args:
        selected_factors: List of selected factor names
        all_factors: DataFrame containing all factor data
        train_data: Training data DataFrame
        test_data: Test data DataFrame
        
    Returns:
        Dictionary mapping factor names to their time series
    """
    selected_factor_timeseries = {}
    
    if selected_factors and not all_factors.empty:
        # Get the combined train+test period for selected factors
        combined_period_start = train_data.index[0] if not train_data.empty else test_data.index[0]
        combined_period_end = test_data.index[-1] if not test_data.empty else train_data.index[-1]
        
        # Extract time series for selected factors over the combined period
        period_mask = (all_factors.index >= combined_period_start) & (all_factors.index <= combined_period_end)
        for factor in selected_factors:
            if factor in all_factors.columns:
                factor_series = all_factors.loc[period_mask, factor].dropna()
                if not factor_series.empty:
                    selected_factor_timeseries[factor] = factor_series
        
        # print(f"🎨 Extracted {len(selected_factor_timeseries)} factor time series for plotting")
        if selected_factor_timeseries:
            first_factor = list(selected_factor_timeseries.keys())[0]
            sample_series = selected_factor_timeseries[first_factor]
            # print(f"   📊 Sample: {first_factor} ({len(sample_series)} points, {sample_series.index[0]} to {sample_series.index[-1]})")
    
    return selected_factor_timeseries


def save_final_model(results: List[Dict], periods_to_analyze: List[Tuple], config, end_dt: datetime) -> bool:
    """
    Save model from the final successful period for daily predictions.
    
    Args:
        results: List of analysis results
        periods_to_analyze: List of analysis periods 
        config: Model configuration object
        end_dt: End datetime for filename
        
    Returns:
        Boolean indicating if model was saved successfully
    """
    successful_count = sum(1 for r in results if r['result']['status'] == 'success')
    
    if successful_count == 0:
        print("⚠️ No model saved - no successful periods found")
        return False
    
    # Find the last successful result (final test period)
    successful_results = [r for r in results if r['result']['status'] == 'success']
    final_result = successful_results[-1]
    
    if not final_result['result'].get('trained_model'):
        print("⚠️ No model saved - final period has no trained model")
        return False
    
    model_filename = f"trained_model_{config.ticker}_{end_dt.strftime('%Y%m%d')}.joblib"
    
    # Create comprehensive model package
    model_package = {
        'trained_model': final_result['result']['trained_model'],
        'selected_factors': final_result['result']['selected_factors'],
        'config': {
            'ticker': config.ticker,
            'weighting_method': config.weighting_method,
            'factor_return_method': config.factor_return_method,
            'normalization_method': config.normalization_method,
            'intensity_method': config.intensity_method,
            'position_method': config.position_method,
            'lookback_window': config.lookback_window,
            'max_position': config.max_position,
            'threshold': config.threshold
        },
        'model_metadata': {
            'train_end_date': periods_to_analyze[-1][1].strftime('%Y-%m-%d'),
            'test_start_date': periods_to_analyze[-1][2].strftime('%Y-%m-%d'),
            'test_end_date': periods_to_analyze[-1][3].strftime('%Y-%m-%d'),
            'created_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'num_factors': len(final_result['result']['selected_factors'])
        }
    }
    
    try:
        joblib.dump(model_package, model_filename)
        print(f"💾 Model saved to: {model_filename}")
        return True
    except Exception as e:
        print(f"⚠️ Failed to save model: {e}")
        return False
