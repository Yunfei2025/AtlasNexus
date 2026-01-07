# -*- coding: utf-8 -*-
"""
Pair Manager Module for Pair Analysis

This module manages multiple pairs and orchestrates batch operations.
Optimized for performance and simplified structure.
"""
import os
from typing import Any, Dict, Optional, List, Union
import xlwings as xw
from .core import Pair
from .stats import RegressionResults
from .excel import ExcelHandler
from .visualization import DashboardGenerator


class PairManager:
    """Optimized manager class for handling multiple pairs"""
    
    __slots__ = ('pairs', '_analysis_cache', '_is_analysis_prepared')
    
    def __init__(self):
        self.pairs: Dict[str, Pair] = {}
        self._analysis_cache: Dict[str, Dict[str, Any]] = {}
        self._is_analysis_prepared: bool = False
    
    def add_pair(self, name: str, leg1: str, leg2: str, window: int = 30) -> Pair:
        """Add a new pair to the manager"""
        pair = Pair(name, leg1, leg2, window)
        self.pairs[name] = pair
        self._invalidate_cache()
        return pair
    
    def load_pairs_from_excel(self, sht_cfg: xw.Sheet) -> None:
        """Load pair configurations from Excel sheet"""
        pairs_config = ExcelHandler.read_pair_config(sht_cfg)
        for name, config in pairs_config.items():
            self.add_pair(name, config['leg1'], config['leg2'], config['window'])
    
    def prepare_analysis(self, force: bool = False) -> Dict[str, Dict[str, Any]]:
        """Compute analysis results for all pairs once and cache them."""
        if force or not self._is_analysis_prepared:
            self._analysis_cache.clear()
            
            for name, pair in self.pairs.items():
                try:
                    spread_df = pair.calculate_spread()
                    regression_result = pair.run_regression()
                    self._analysis_cache[name] = {
                        'spread_df': spread_df,
                        'regression_result': regression_result,
                        'leg1': pair.leg1,
                        'leg2': pair.leg2,
                        'window': pair.window
                    }
                except Exception as e:
                    print(f"Failed to analyze pair {name}: {e}")
                    continue
            
            self._is_analysis_prepared = True
        
        return self._analysis_cache
    def _invalidate_cache(self) -> None:
        """Invalidate analysis cache when pairs change"""
        self._analysis_cache.clear()
        self._is_analysis_prepared = False
    
    def get_results(self, analyses: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, RegressionResults]:
        """Get regression results for all pairs"""
        if analyses is None:
            analyses = self.prepare_analysis()
        
        return {name: data['regression_result'] for name, data in analyses.items()}
    
    def write_to_excel(self, sht_out: xw.Sheet, analyses: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        """Write all results to Excel efficiently"""
        if analyses is None:
            analyses = self.prepare_analysis()
        
        current_row = 23
        for name, pair in self.pairs.items():
            if name in analyses:
                try:
                    ExcelHandler.write_pair_results(
                        sht_out, name, pair.leg1, pair.leg2,
                        analyses[name]['regression_result'], current_row
                    )
                except Exception as e:
                    print(f"Failed to write results for pair {name}: {e}")
    
    def create_excel_plots(self, sht_out: xw.Sheet, analyses: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        """Create Excel plots for all pairs"""
        if analyses is None:
            analyses = self.prepare_analysis()
        
        from .visualization import PlotGenerator
        plot_positions = ["D1", "D25", "D49"]
        
        for i, (name, pair) in enumerate(self.pairs.items()):
            if i < len(plot_positions) and name in analyses:
                try:
                    PlotGenerator.create_excel_plot(
                        analyses[name]['spread_df'],
                        analyses[name]['regression_result'],
                        pair.leg1, pair.leg2, sht_out,
                        plot_positions[i], f"SpreadPlot_{name}"
                    )
                except Exception as e:
                    print(f"Failed to create plot for pair {name}: {e}")
    
    def create_dashboard(self, output_path: str = "unified_dashboard.html", 
                        analyses: Optional[Dict[str, Dict[str, Any]]] = None) -> str:
        """Create unified dashboard with all pair data"""
        if analyses is None:
            analyses = self.prepare_analysis()
        
        pairs_data = {}
        for name, pair in self.pairs.items():
            if name in analyses:
                pairs_data[name] = {
                    'name': name, 'leg1': pair.leg1, 'leg2': pair.leg2,
                    'spread_df': analyses[name]['spread_df'],
                    'regression_result': analyses[name]['regression_result']
                }
        
        dashboard_gen = DashboardGenerator()
        return dashboard_gen.create_unified_dashboard(pairs_data, output_path)
    
    def get_summary(self, analyses: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Dict[str, Union[str, float]]]:
        """Get performance summary for all pairs"""
        if analyses is None:
            analyses = self.prepare_analysis()
        
        summary = {}
        for name in self.pairs:
            if name in analyses:
                try:
                    result = analyses[name]['regression_result']
                    summary[name] = {
                        'r_squared': result.r_squared,
                        'slope': result.slope,
                        'residual_std': result.residual_std,
                        'n_obs': result.n_obs
                    }
                except Exception as e:
                    summary[name] = {'error': str(e)}
        
        return summary
    
    def __len__(self) -> int:
        return len(self.pairs)
    
    def __iter__(self):
        return iter(self.pairs.values())
    
    def __contains__(self, name: str) -> bool:
        return name in self.pairs
    
    def __getitem__(self, name: str) -> Pair:
        return self.pairs[name]