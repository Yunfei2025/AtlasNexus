# -*- coding: utf-8 -*-
"""
Visualization Module for Pair Analysis

This module provides simplified visualization classes with backward compatibility.
"""
from .dashboard import Dashboard
from .plot import PlotGenerator as CorePlotGenerator
from typing import Dict
import pandas as pd
import xlwings as xw


class DashboardGenerator:
    """Simplified dashboard generator"""
    
    def __init__(self):
        self.dashboard = Dashboard()
    
    def create_unified_dashboard(self, pairs_data: Dict, output_path: str = "unified_dashboard.html") -> str:
        """Create unified dashboard with all pair data"""
        return self.dashboard.create_unified_dashboard(pairs_data, output_path)


class PlotGenerator:
    """Legacy plot generator with backward compatibility for Excel integration"""
    
    def __init__(self):
        self.dashboard_gen = DashboardGenerator()
        self.core_plot_gen = CorePlotGenerator()
    
    def create_plots(self, pairs_data: Dict, output_path: str = "unified_dashboard.html") -> str:
        return self.dashboard_gen.create_unified_dashboard(pairs_data, output_path)
    
    @staticmethod
    def create_excel_plot(spread_df: pd.DataFrame, regression_result, leg1: str, leg2: str, 
                         sht_out: xw.Sheet, top_left_cell: str, pic_name: str) -> None:
        """Create Excel plot - legacy compatibility method"""
        try:
            print(f"📊 Excel plot requested for {leg1} vs {leg2} at {top_left_cell}")
            print(f"   Spread data: {len(spread_df)} points")
            print(f"   R²: {regression_result.r_squared:.4f}")
        except Exception as e:
            print(f"⚠️ Excel plot creation failed: {e}")
    
    @staticmethod 
    def create_interactive_plot(spread_df: pd.DataFrame, regression_result, leg1: str, leg2: str,
                              pair_name: str, output_path: str) -> str:
        """Create interactive plot - legacy compatibility method"""
        try:
            core_gen = CorePlotGenerator()
            fig = core_gen.create_base_figure(spread_df, regression_result, leg1, leg2, pair_name)
            core_gen.apply_interactive_layout(fig, leg1, leg2, regression_result)
            
            fig.write_html(
                output_path,
                include_plotlyjs='cdn',
                config={
                    'responsive': True,
                    'displayModeBar': True,
                    'modeBarButtonsToAdd': ['pan2d', 'lasso2d'],
                    'displaylogo': False
                }
            )
            print(f"✓ Interactive plot saved: {output_path}")
            return output_path
            
        except Exception as e:
            print(f"⚠️ Interactive plot creation failed: {e}")
            return ""

