#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Factor Analysis Engine - Simplified Version
"""

import sys
import os
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import pandas as pd
import numpy as np
import multiprocessing as mp
from multiprocessing import Pool

# Environment setup
os.environ['NUMPY_EXPERIMENTAL_DTYPE_API'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
sys.path.insert(0, str(Path(__file__).parent.parent))

# Try relative imports first (when run as module)
from ..config import config_manager
from ..analysis.metrics import calculate_metrics
from ..backtest import display_summary
from ..processing.loader import prepare_factor_data, split_data_by_periods
from .selector import create_factor_selector
from ..processing.position import create_simple_portfolio, create_intensity_portfolio, create_smooth_portfolio, create_smooth_portfolio_qp, create_portfolio_by_method
from ..utils.helpers import extract_factor_timeseries, save_factor_analysis_results, create_analysis_summary, generate_analysis_periods, save_final_model
from .predictor import predict_returns, train_model

def load_and_prepare_factors(ticker: str, include_macro: bool = True):
    """Load data and generate factors for prediction or training (without scaling).
    
    Returns:
        Tuple[pd.DataFrame, pd.DataFrame]: (data, factors) - data for portfolio creation, factors for analysis
    """
    from ..processing.loader import getDailyTS
    from ..generator.factory import FactorCalculatorFactory
    
    data_all = getDailyTS(ticker)
    
    if data_all is None or data_all.empty:
        raise ValueError(f"No data available for {ticker}")
    
    # Apply data preparation
    data_all = prepare_factor_data(data_all, 'pct_change')

    # Use FactorCalculatorFactory for comprehensive factor generation
    factory = FactorCalculatorFactory(data_all)

    all_factors = factory.generate_factors(
        max_high_order_factors=100,
    )
    return data_all, all_factors

class FactorEngine:
    """Simplified Factor Analysis Engine"""
    
    def __init__(self, config=None, num_cores=4):
        self.config = config or config_manager.model_config
        self.factor_selector = create_factor_selector(self.config)
        self.num_cores = min(num_cores, mp.cpu_count())
        print(f"🔧 FactorEngine initialized with {self.num_cores} cores")

    def analyze_single_period(self, data: pd.DataFrame, train_end: datetime, 
                             test_start: datetime, test_end: datetime, precomputed_factors: pd.DataFrame = None) -> Dict:
        """Analyze a single time period with train/test split."""
        try:
            print(f"\n{'-' * 60}")
            print(f"Test period: {test_start} to {test_end}")
            
            # Use precomputed factors if available, otherwise generate them
            if precomputed_factors is not None:
                print(f"🔄 Using precomputed factors: {precomputed_factors.shape[1]} factors")
                all_factors = precomputed_factors.copy()

                # Apply scaling in the parallel loop using train_end
                from ..generator.factory import scale_factors_rolling
                print(f"🔧 Scaling factors (ending: {train_end.strftime('%Y-%m-%d')})")
                all_factors = scale_factors_rolling(all_factors, train_end)
                print(f"✅ Factors scaled: {all_factors.shape[1]} factors")
            else:
                # Fallback to generating factors on-the-fly
                # Generate factors using the factory
                from ..generator.factory import FactorCalculatorFactory
                factory = FactorCalculatorFactory(data)
                all_factors = factory.generate_factors(max_high_order_factors=100)

            if all_factors.empty:
                return {'status': 'failed', 'error': 'No factors generated'}
            
            all_factors = all_factors.loc[data.index.intersection(all_factors.index)]
            
            # Split data into train/test periods
            train_data, test_data = split_data_by_periods(
                data, train_end, test_start, test_end, self.config.lookback_window
            )
            train_factors, test_factors = split_data_by_periods(
                all_factors, train_end, test_start, test_end, self.config.lookback_window
            )
            
            if any(df.empty for df in [train_data, test_data, train_factors, test_factors]):
                return {'status': 'failed', 'error': 'Empty train/test data or factors'}
            
            # Calculate metrics and select factors
            metrics = calculate_metrics(train_factors, train_data['Returns'])
            if metrics.empty:
                return {'status': 'failed', 'error': 'No metrics calculated'}
            
            selected_factors = self.factor_selector.select_factors(metrics, train_factors)
            if not selected_factors:
                return {'status': 'failed', 'error': 'No factors selected'}
            
            # Train model and predict
            model_type, ic_weighting = self.config.get_model_parameters()
            print(f"🔧 Using model: {model_type}, IC weighting: {ic_weighting}")
            
            trained_model = train_model(
                train_factors, train_data['Returns'], selected_factors,
                model_type=model_type,
                ic_weighting_method=ic_weighting,
                scale_ic_predictions=self.config.scale_ic_predictions,
                pre_calculated_metrics=metrics
            )
            
            if not trained_model:
                return {'status': 'failed', 'error': 'Model training failed'}
            
            predictions = predict_returns(test_factors, trained_model, selected_factors)
            if predictions.empty:
                return {'status': 'failed', 'error': 'Return prediction failed'}

            # Apply signal smoothing if enabled
            if getattr(self.config, 'signal_smoothing', False):
                try:
                    from ..processing.smoothing import apply_signal_smoothing
                    predictions = apply_signal_smoothing(predictions, self.config)
                    # print(f"✅ Applied signal smoothing to {len(predictions)} predictions")
                except Exception as e:
                    print(f"⚠️ Signal smoothing failed: {e}. Using raw predictions...")
            else:
                # print("📊 Signal smoothing disabled, using raw predictions")
                pass

            # Note: QP portfolio creation moved to run_analysis() for concatenated predictions

            # Extract factor time series for plotting
            factor_timeseries = extract_factor_timeseries(
                selected_factors, all_factors, train_data, test_data
            )
            
            return {
                'status': 'success',
                'selected_factors': selected_factors,
                'trained_model': trained_model,
                'predictions': predictions,
                'factor_timeseries': factor_timeseries,
                'selected_factor_metrics': {f: metrics.loc[f].to_dict() for f in selected_factors if f in metrics.index}
            }
            
        except Exception as e:
            print(f"❌ Period analysis failed: {e}")
            import traceback
            traceback.print_exc()
            return {'status': 'failed', 'error': str(e)}

def _execute_parallel_analysis(periods_to_analyze: list, num_cores: int) -> list:
    """Execute parallel analysis of periods with a top-level worker (Windows-safe)."""
    print(f"🚀 Analyzing {len(periods_to_analyze)} periods using {num_cores} cores...")
    if mp.get_start_method(allow_none=True) != 'spawn':
        mp.set_start_method('spawn', force=True)
    with Pool(processes=num_cores) as pool:
        results = pool.map(_analyze_period_worker, periods_to_analyze)
    successful_count = sum(1 for r in results if r['result']['status'] == 'success')
    print(f"📊 Completed {len(results)} periods, {successful_count} successful")
    return results


def _analyze_period_worker(args):
    """Top-level worker function to avoid pickling issues on Windows."""
    try:
        month_str, train_end, test_start, test_end, ticker, config = args
        engine = FactorEngine(config, num_cores=1)

        # Get precomputed data and factors from config
        data = getattr(config, '_precomputed_data', None)
        precomputed_factors = getattr(config, '_precomputed_factors', None)

        if data is None or data.empty:
            return {'month': month_str, 'result': {'status': 'failed', 'error': 'No precomputed data available'}}

        result = engine.analyze_single_period(data, train_end, test_start, test_end, precomputed_factors)
        return {'month': month_str, 'result': result}

    except Exception as e:
        return {'month': args[0] if args else 'unknown', 'result': {'status': 'failed', 'error': str(e)}}


def _process_predictions_and_portfolios(results: list, config, data: pd.DataFrame) -> tuple:
    """Process predictions and create portfolios."""
    all_predictions = [r['result']['predictions'] for r in results 
                      if r['result']['status'] == 'success' and 
                      r['result'].get('predictions') is not None and 
                      not r['result']['predictions'].empty]
    
    if not all_predictions:
        print("⚠️ No predictions available for processing")
        return None, None
    
    print(f"🔄 Processing {len(all_predictions)} prediction series...")
    concatenated_predictions = pd.concat(all_predictions).sort_index()
    print(f"✅ Concatenated predictions: {len(concatenated_predictions)} total data points")
    # Create portfolio using selected method
    portfolio_method = getattr(config, 'portfolio_method', 'simple')
    print(f"🎨 Creating {portfolio_method} portfolio from {len(concatenated_predictions)} concatenated predictions...")
    
    concatenated_portfolios = create_portfolio_by_method(
        portfolio_method, concatenated_predictions, config, data
    )
    
    # Distribute portfolio positions back to individual period results
    for result_entry in results:
        if result_entry['result']['status'] == 'success':
            period_predictions = result_entry['result']['predictions']
            if period_predictions is not None and not period_predictions.empty:
                period_portfolio = concatenated_portfolios.loc[
                    concatenated_portfolios.index.intersection(period_predictions.index)
                ]
                result_entry['result']['portfolio'] = period_portfolio
                result_entry['result']['positions'] = period_portfolio
    
    return concatenated_predictions, concatenated_portfolios


def run_analysis(start_date: str = None, end_date: str = None, ticker: str = None, num_cores: int = 4):
    """Simplified integrated factor analysis function."""
    from ..analysis.aggresults import convert_summary_to_structured_results
    
    try:
        # Setup
        config = config_manager.model_config
        if ticker:
            config.ticker = ticker
        
        start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
        engine = FactorEngine(config, num_cores=num_cores)
        
        # Pre-generate data and factors (including macro) once for efficiency
        data, all_factors = load_and_prepare_factors(config.ticker)
        start_dt = max(start_dt, data.index[0])
        end_dt = min(end_dt, data.index[-1])
        
        print(f"✅ Generated {all_factors.shape[1]} factors (including macro factors)")
        
        # Store both data and factors for use by worker threads
        config._precomputed_data = data
        config._precomputed_factors = all_factors
        
        # Generate analysis periods and execute analysis
        periods_to_analyze, _, _ = generate_analysis_periods(start_dt, end_dt, config.ticker, config)
        results = _execute_parallel_analysis(periods_to_analyze, engine.num_cores)
        successful_count = sum(1 for r in results if r['result']['status'] == 'success')
        import pdb; pdb.set_trace()
        # Process predictions and create portfolios
        concatenated_predictions, concatenated_portfolios = _process_predictions_and_portfolios(
            results, config, data
        )
        
        # Save results and run backtest
        save_final_model(results, periods_to_analyze, config, end_dt)
        csv_filename = f"factor_analysis_{start_dt.strftime('%Y%m%d')}_{end_dt.strftime('%Y%m%d')}.csv"
        save_factor_analysis_results(results, csv_filename)

        from ..backtest import run_backtest
        backtest_results = run_backtest(results, data['Close'], periods_to_analyze, concatenated_predictions)
        summary = create_analysis_summary(results, successful_count, backtest_results)
        
        # Add predictions to summary
        if summary.get('whole_period_backtest') and concatenated_predictions is not None:
            if 'backtest_result' in backtest_results and 'strategy_returns' in backtest_results['backtest_result']:
                summary['whole_period_backtest']['actual_returns'] = backtest_results['backtest_result']['strategy_returns']
            summary['whole_period_backtest']['predictions'] = concatenated_predictions
            print(f"✅ Added {len(concatenated_predictions)} processed predictions to summary")
        
        display_summary(summary)
        
        if not summary or summary.get('status') == 'failed':
            raise ValueError(f"Analysis failed: {summary.get('error', 'Unknown error')}")
        
        return convert_summary_to_structured_results(summary)
        
    except Exception as e:
        print(f"❌ Analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    print("FactorEngine module loaded. Use 'factors/main.py' for main execution.")