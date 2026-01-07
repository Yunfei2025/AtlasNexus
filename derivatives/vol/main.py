# -*- coding: utf-8 -*-
"""
Volatility Trading Strategy for AU.SHF Gold Futures (Refactored with OOP)
Created on Tue Oct 28 23:35:55 2025
Refactored on Oct 29, 2025

@author: CMBC
"""
import os
import sys
import pathlib
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Local library imports
PATH = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(PATH))

# -----------------------------------------------------------------------------
# Compatibility shim
# Some legacy pickles in this project were created when numpy exposed
# "numpy._core"; newer numpy versions do not. Alias it so unpickling works.
try:
    import numpy as _np
    import numpy.core as _np_core
    sys.modules.setdefault("numpy._core", _np_core)
except Exception:
    # Best-effort: if numpy import fails, later code will raise a clearer error.
    pass

from derivatives.vol.retrieve import retrieveFuturesVol
from derivatives.vol.vol import VolatilityData, StrategyConfig
from derivatives.vol.strategies import StrategyFactory
from derivatives.vol.backtest import StrategyBacktester
from derivatives.vol.visualizer import VolatilityVisualizer
from settings.paths import DIR_INPUT


class VolatilityTradingEngine:
    """
    Main engine for volatility trading strategy analysis
    """
    
    def __init__(self, code: str = "AU.SHF", start_date: Optional[str] = None, end_date: Optional[str] = None):
        """
        Initialize the volatility trading engine
        
        Parameters:
        -----------
        code : str
            Futures contract code
        start_date : str, optional
            Start date for analysis
        end_date : str, optional
            End date for analysis
        """
        self.code = code
        self.start_date = start_date
        self.end_date = end_date
        self.vol_data = None
        self.strategies = None
        self.combined_strategy = None
        self.backtester = None
        self.visualizer = None
        
    def load_data(self, file_path: str = None):
        """
        Load volatility data from file
        
        Parameters:
        -----------
        file_path : str, optional
            Path to data file. If None, uses default path
        """
        if file_path is None:
            file_path = os.path.join(DIR_INPUT, 'futures-volpx.pkl')
        
        print("=" * 80)
        print(f"📊 Loading Volatility Data: {self.code}")
        print("=" * 80)
        
        vol_ts = pd.read_pickle(file_path)[self.code]
        self.vol_data = VolatilityData(vol_ts, self.code)
        
        print(f"\n{self.vol_data}")
        print(f"Latest Volatility Levels:")
        latest = self.vol_data.get_latest()
        for col in ['IV_1M', 'IV_2M', 'IV_3M']:
            if col in latest.index:
                print(f"  {col}: {latest[col]:.4f}")
        
    def create_strategies(self, custom_params: dict = None):
        """
        Create only the mean reversion strategy
        
        Parameters:
        -----------
        custom_params : dict, optional
            Custom parameters for strategy
        """
        print("\n" + "=" * 80)
        print("🔧 Creating Mean Reversion Strategy")
        print("=" * 80)
        
        # Create only mean reversion strategy
        from derivatives.vol.strategies import MeanReversionStrategy
        
        params = custom_params.get('mean_reversion') if custom_params else None
        mean_reversion = MeanReversionStrategy(params)
        
        self.strategies = [mean_reversion]
        self.combined_strategy = None  # No combined strategy needed
        
        print(f"\nCreated strategy:")
        print(f"  - {mean_reversion.name}")
        
    def run_strategies(self):
        """Execute mean reversion strategy"""
        if self.vol_data is None:
            raise ValueError("Data not loaded. Call load_data() first.")
        
        if self.strategies is None:
            self.create_strategies()
        
        print("\n" + "=" * 80)
        print("🚀 Running Mean Reversion Strategy")
        print("=" * 80)
        
        # Run only mean reversion strategy
        for strategy in self.strategies:
            strategy.run(self.vol_data)
            strategy.print_stats()
        
    def backtest(self, transaction_cost: float = 0.0):
        """
        Run backtest for mean reversion strategy only
        
        Parameters:
        -----------
        transaction_cost : float
            Transaction cost per trade
        """
        if self.strategies is None:
            raise ValueError("Strategy not created. Call run_strategies() first.")
        
        print("\n" + "=" * 80)
        print("📈 Backtesting Mean Reversion Strategy")
        print("=" * 80)
        
        self.backtester = StrategyBacktester(self.vol_data)
        
        # Backtest only mean reversion strategy
        self.backtester.backtest_multiple(self.strategies, transaction_cost)
        
        # Print metrics
        self.backtester.print_metrics()
        
    def visualize(self):
        """
        Generate visualizations for mean reversion strategy
        """
        if self.backtester is None:
            print("Warning: No backtest results available. Run backtest() first for complete visualizations.")
        
        print("\n" + "=" * 80)
        print("📊 Generating Visualizations")
        print("=" * 80)
        
        self.visualizer = VolatilityVisualizer(self.vol_data, self.backtester)
        
        # Generate charts for mean reversion strategy only
        self.visualizer.generate_all_charts(self.strategies, ".")
        
    def print_recommendation(self):
        """Print the latest trading recommendation for mean reversion strategy"""
        if self.strategies is None or len(self.strategies) == 0:
            print("No trading strategy available")
            return
        
        mean_reversion_strategy = self.strategies[0]
        if mean_reversion_strategy.signals is None:
            print("No trading signals generated yet")
            return
        
        print("\n" + "=" * 80)
        print("💡 Latest Trading Recommendation (Mean Reversion Strategy)")
        print("=" * 80)
        
        latest_data = self.vol_data.get_latest()
        latest_signal = mean_reversion_strategy.get_latest_signal()
        
        print(f"\nDate: {latest_data.name.strftime('%Y-%m-%d')}")
        print(f"\nVolatility Levels:")
        for col in ['IV_1M', 'IV_2M', 'IV_3M']:
            if col in latest_data.index:
                print(f"  {col}: {latest_data[col]:.4f}")
        
        if 'IV_1M_MA' in latest_data.index:
            print(f"\nBollinger Bands:")
            print(f"  Moving Average: {latest_data['IV_1M_MA']:.4f}")
            if 'IV_1M_Upper' in latest_data.index and 'IV_1M_Lower' in latest_data.index:
                print(f"  Upper Band: {latest_data['IV_1M_Upper']:.4f}")
                print(f"  Lower Band: {latest_data['IV_1M_Lower']:.4f}")
        
        print(f"\n📍 Final Signal: ", end="")
        if latest_signal == 1:
            print("🟢 LONG Volatility (Buy Straddle/Long Volatility)")
            print("   IV below lower band - expect mean reversion higher")
        elif latest_signal == -1:
            print("🔴 SHORT Volatility (Sell Straddle/Short Volatility)")
            print("   IV above upper band - expect mean reversion lower")
        else:
            print("⚪ NEUTRAL (No Position)")
            print("   IV within bands - no mean reversion signal")
    
    def run_full_analysis(self):
        """
        Run complete analysis pipeline
        """
        self.load_data()
        self.create_strategies()
        self.run_strategies()
        self.backtest()
        self.print_recommendation()
        self.visualize()
        

# Main execution
if __name__ == "__main__":
    # Configuration variables (set them directly here)
    start_date = "2025-01-01"
    end_date = "2025-10-28"
    
    # retrieve data (keeps original behavior)
    retrieveFuturesVol()
    
    # Create and run the volatility trading engine
    engine = VolatilityTradingEngine(
        code="AU.SHF",
        start_date=start_date,
        end_date=end_date
    )

    try:
        engine.run_full_analysis()

        print("\n" + "=" * 80)
        print("✅ Analysis Complete!")
        print("=" * 80)

    except FileNotFoundError as e:
        print(f"❌ Data file not found: {e}")
    except Exception as e:
        print(f"❌ Analysis error: {e}")
        import traceback
        traceback.print_exc()
