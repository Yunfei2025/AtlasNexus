# -*- coding: utf-8 -*-
"""
Dashboard Module for Pair Analysis

This module creates a single integrated dashboard with all plots and refresh functionality.
Refactored for better maintainability with separate style module.
"""
import os
from typing import Dict
import plotly.graph_objects as go
from .plot import PlotGenerator
from .stats import StatisticalAnalyzer, RegressionResults
from .style import get_dashboard_template


class Dashboard:
    """Dashboard that integrates all plots into a single HTML page with refresh functionality"""
    
    def __init__(self):
        self.plot_generator = PlotGenerator()
        
    def create_unified_dashboard(self, pairs_data: Dict, output_path: str = "unified_dashboard.html") -> str:
        """Create a single unified dashboard with all plots and refresh functionality."""

        output_dir = os.path.dirname(os.path.abspath(output_path)) or os.getcwd()
        plot_configs = []
        
        for idx, (pair_name, pair_info) in enumerate(pairs_data.items()):
            leg1 = pair_info['leg1']
            leg2 = pair_info['leg2']

            # Try to use provided html_path or detect existing standalone plot files
            html_path = pair_info.get('html_path')
            if not html_path:
                # Check in pairs folder
                pairs_dir = os.path.dirname(__file__)
                candidate = os.path.join(pairs_dir, f"spread_analysis_{pair_name}.html")
                if os.path.exists(candidate):
                    html_path = os.path.relpath(candidate, output_dir).replace('\\', '/')
                else:
                    # Check side-by-side with output (e.g., interactive_plots)
                    candidate2 = os.path.join(output_dir, f"spread_analysis_{pair_name}.html")
                    if os.path.exists(candidate2):
                        html_path = os.path.relpath(candidate2, output_dir).replace('\\', '/')

            if html_path:
                # Use iframe to embed exact standalone plot
                plot_configs.append({
                    'id': f'plot_{idx}',
                    'name': pair_name,
                    'leg1': leg1,
                    'leg2': leg2,
                    'mode': 'iframe',
                    'htmlPath': html_path,
                    'stats': pair_info.get('regression_result').stats if pair_info.get('regression_result') else {}
                })
            else:
                # Build Plotly figure from data as a fallback
                spread_df = pair_info['spread_df']
                regression_result = pair_info['regression_result']
                fig = self.plot_generator.create_base_figure(
                    spread_df, regression_result, leg1, leg2, pair_name
                )
                # Apply layout and serialize
                self.plot_generator.apply_interactive_layout(fig, leg1, leg2, regression_result)
                try:
                    plot_json = fig.to_json()
                except Exception as e:
                    print(f"Warning: Failed to serialize plot for {pair_name}: {e}")
                    plot_json = '{}'
                plot_configs.append({
                    'id': f'plot_{idx}',
                    'name': pair_name,
                    'leg1': leg1,
                    'leg2': leg2,
                    'mode': 'plotly',
                    'config': plot_json,
                    'stats': regression_result.stats
                })
        
        # Create the unified HTML using the style module
        html_content = get_dashboard_template(plot_configs)
        
        # Write to file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
            
        return output_path