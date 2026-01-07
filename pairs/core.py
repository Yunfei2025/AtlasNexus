# -*- coding: utf-8 -*-
"""
Core Pair Module for Pair Analysis

This module contains the main Pair class with core functionality.
"""
from typing import Optional, Tuple
import pandas as pd
import xlwings as xw
from .data import DataCache
from .stats import RegressionResults, StatisticalAnalyzer
from .visualization import PlotGenerator
from .excel import ExcelHandler


class Pair:
    """
    Class representing a trading pair with two legs and associated analytics
    """
    def __init__(self, name: str, leg1: str, leg2: str, window: int = 30):
        self.name = name
        self.leg1 = leg1
        self.leg2 = leg2
        self.window = window
        self._data_cache = DataCache()
        
        # Data storage
        self._leg1_data: Optional[pd.Series] = None
        self._leg2_data: Optional[pd.Series] = None
        self._spread_data: Optional[pd.DataFrame] = None
        self._regression_result: Optional[RegressionResults] = None
        
    @property
    def leg1_type(self) -> str:
        """Determine the type of leg1 instrument"""
        if 'IB' in self.leg1:
            return 'TBond' if '00' in self.leg1 else 'CBond'
        elif 'IR' in self.leg1:
            return 'IRS'
        else:
            return 'Unknown'
    
    @property
    def leg2_type(self) -> str:
        """Determine the type of leg2 instrument"""
        if 'IB' in self.leg2:
            return 'TBond' if '00' in self.leg2 else 'CBond'
        elif 'IR' in self.leg2:
            return 'IRS'
        else:
            return 'Unknown'
    
    def load_data(self) -> Tuple[pd.Series, pd.Series]:
        """Load historical data for both legs"""
        if self._leg1_data is not None and self._leg2_data is not None:
            return self._leg1_data, self._leg2_data
        
        # Load data for leg1
        leg1_dataset = self._data_cache.get_cached_data(self.leg1_type)
        if leg1_dataset is None or self.leg1 not in leg1_dataset.columns:
            raise ValueError(f"Could not find data for leg1: {self.leg1}")
        self._leg1_data = leg1_dataset[self.leg1].dropna()
        
        # Load data for leg2
        leg2_dataset = self._data_cache.get_cached_data(self.leg2_type)
        if leg2_dataset is None or self.leg2 not in leg2_dataset.columns:
            raise ValueError(f"Could not find data for leg2: {self.leg2}")
        self._leg2_data = leg2_dataset[self.leg2].dropna()
        
        return self._leg1_data, self._leg2_data
    
    def calculate_spread(self) -> pd.DataFrame:
        """Calculate spread between the two legs"""
        if self._spread_data is not None:
            return self._spread_data
        
        leg1_data, leg2_data = self.load_data()
        spread_data = StatisticalAnalyzer.calculate_spread(leg1_data, leg2_data)

        # Apply window filtering
        if len(spread_data) > self.window:
            end_date = spread_data["date"].max()
            start_date = end_date - pd.Timedelta(days=self.window + 7)
            spread_data = spread_data[spread_data["date"] >= start_date]
            spread_data = spread_data.tail(self.window)
        
        self._spread_data = spread_data
        return self._spread_data
    
    def run_regression(self) -> RegressionResults:
        """Run regression analysis on the spread"""
        if self._regression_result is not None:
            return self._regression_result
        
        spread_df = self.calculate_spread()
        self._regression_result = StatisticalAnalyzer.run_regression(spread_df)
        return self._regression_result
    
    # def write_results_to_excel(self, sht_out: xw.Sheet, start_row) -> int:
    #     """Write pair results to Excel sheet"""
    #     regression_result = self.run_regression()
    #     ExcelHandler.write_pair_results(
    #         sht_out, self.name, self.leg1, self.leg2, regression_result, start_row
    #     )
    
    def create_plot(self, sht_out: xw.Sheet, top_left_cell: str = "D1", 
                   pic_name: str = None) -> None:
        """Create and insert interactive Plotly plot for the pair"""
        if pic_name is None:
            pic_name = f"SpreadPlot_{self.name}"
        
        spread_df = self.calculate_spread()
        regression_result = self.run_regression()
        PlotGenerator.create_excel_plot(
            spread_df, regression_result, self.leg1, self.leg2, 
            sht_out, top_left_cell, pic_name
        )
    
    def save_interactive_plot(self, output_path: str = None) -> str:
        """Save interactive Plotly plot as HTML file"""
        if output_path is None:
            output_path = f"spread_analysis_{self.name}.html"
        
        spread_df = self.calculate_spread()
        regression_result = self.run_regression()

        return PlotGenerator.create_interactive_plot(
            spread_df, regression_result, self.leg1, self.leg2, 
            self.name, output_path
        )
    
    def __str__(self) -> str:
        return f"Pair({self.name}: {self.leg1} vs {self.leg2}, window={self.window})"
    
    def __repr__(self) -> str:
        return self.__str__()