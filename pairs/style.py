# -*- coding: utf-8 -*-
"""
Dashboard Style Module

This module contains HTML templates and CSS styles for the dashboard.
Separated for better maintainability and cleaner code structure.
"""
from datetime import datetime
from typing import List, Dict
import json


def get_dashboard_template(plot_configs: List[Dict]) -> str:
    """Generate the complete HTML template for the dashboard"""
    
    return f"""<!DOCTYPE html>
<html>
<head>
    <title> Pair Analysis </title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        {get_dashboard_css()}
    </style>
</head>
<body>
    <div class="dashboard-container">
        <div class="plots-container">
            <div class="plots-grid">
                {get_plots_html(plot_configs)}
            </div>
        </div>
    </div>

    <script>
        {get_dashboard_javascript(plot_configs)}
    </script>
</body>
</html>"""


def get_dashboard_css() -> str:
    """Get the CSS styles for the dashboard"""
    
    return """
        body {
            font-family: 'Open Sans', sans-serif;
            font-size: 12px;
            margin: 0;
            padding: 10px;
            background: #082255;
            min-height: 100vh;
        }
        
        .dashboard-container {
            max-width: 1400px;
            margin: 0 auto;
            background: #082255;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            overflow: hidden;
        }
        
        .controls {
            background: #2a3241;
            padding: 20px;
            border-bottom: 1px solid #3a4251;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 15px;
        }
        
        .control-group {
            display: flex;
            align-items: center;
            gap: 15px;
        }
        
        .refresh-btn {
            background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 16px;
            font-weight: 600;
            transition: all 0.3s ease;
            box-shadow: 0 4px 15px rgba(40, 167, 69, 0.3);
        }
        
        .refresh-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(40, 167, 69, 0.4);
        }
        
        .refresh-btn:active {
            transform: translateY(0);
        }
        
        .auto-refresh {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .auto-refresh input[type="checkbox"] {
            transform: scale(1.2);
        }
        
        .interval-select {
            padding: 8px 12px;
            border: 2px solid #3a4251;
            border-radius: 6px;
            background: #082255;
            color: #a8b2bf;
            font-size: 14px;
        }
        
        .auto-refresh label {
            color: #a8b2bf;
        }
        
        #refreshStatus {
            color: #a8b2bf;
        }
        
        .last-updated {
            color: #a8b2bf;
            font-size: 14px;
        }
        
        .plots-container {
            padding: 15px;
            background: #082255;
        }

        /* Two-column grid for plots */
        .plots-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
            align-items: start;
        }

        /* Ensure grid children can shrink and do not overflow their columns */
        .plots-grid > .plot-section {
            min-width: 0;
        }

        .plot-section {
            margin-bottom: 0;
            border: 1px solid #1a3a7a;
            border-radius: 6px;
            overflow: hidden;
            background: #082255;
            box-shadow: 0 2px 6px rgba(0,0,0,0.3);
        }

        .plot-header {
            background: #0c2b64;
            color: white;
            padding: 8px 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #1a3a7a;
        }

        .plot-title {
            font-size: 13px;
            font-weight: 600;
            margin: 0;
        }

        .plot-stats {
            font-size: 11px;
            opacity: 0.9;
        }

        .plot-container {
            padding: 0;
            min-height: 280px;
            box-sizing: border-box;
            overflow: hidden; /* avoid content bleeding outside container */
            position: relative;
        }

        /* Make embedded content respect container width */
        .plot-container iframe,
        .plot-container > div {
            display: block;
            width: 100% !important;
            height: 300px !important;
            max-width: 100%;
            border: none;
        }
        
        .loading {
            text-align: center;
            padding: 50px;
            color: #6c757d;
        }
        
        .loading::after {
            content: '';
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid #f3f3f3;
            border-top: 3px solid #3498db;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-left: 10px;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .status-indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 8px;
        }
        
        .status-active { background-color: #28a745; }
        .status-inactive { background-color: #dc3545; }
    """


def get_plots_html(plot_configs: List[Dict]) -> str:
    """Generate HTML for all plots"""
    
    plots_html = ""
    for i, config in enumerate(plot_configs):
        html_link = ''
        if config.get('mode') == 'iframe' and config.get('htmlPath'):
            href = config['htmlPath']
            html_link = f"<a href='{href}' target='_blank' style='color: #fff; text-decoration: underline; margin-left: 15px;'>Open standalone</a>"
        
        # Build the inner HTML (iframe or placeholder div)
        if config.get('mode') == 'iframe':
            elem_html = f"<iframe id='iframe_{i}' src='{config.get('htmlPath','')}' style='width:100%;height:300px;border:none;'></iframe>"
        else:
            # Give Plotly container a fixed height and full width
            elem_html = f"<div id='{config['id']}' style='width:100%;height:300px;'></div>"

        plots_html += f"""
            <div class="plot-section">
                <div class="plot-header">
                    <h3 class="plot-title">{config['name'].upper()}: {config['leg1']} vs {config['leg2']}</h3>
                    <div class="plot-stats">
                        {html_link}
                    </div>
                </div>
                <div class="plot-container">
                    {elem_html}
                </div>
            </div>
"""
    
    return plots_html


def get_dashboard_javascript(plot_configs: List[Dict]) -> str:
    """Generate JavaScript for dashboard functionality"""
    
    return f"""
        // Plot configurations
        const plotConfigs = {json.dumps(plot_configs)};
        
        // Initialize all plots
        function initializePlots() {{
            plotConfigs.filter(c => c.mode === 'plotly').forEach(config => {{
                const plotData = JSON.parse(config.config);
                // Force responsive sizing for plots
                if (plotData.layout) {{
                    plotData.layout.autosize = true;
                    plotData.layout.responsive = true;
                    delete plotData.layout.width;
                    delete plotData.layout.height;
                    plotData.layout.margin = {{ l: 60, r: 60, t: 40, b: 60 }};
                }}
                Plotly.newPlot(config.id, plotData.data, plotData.layout, {{
                    responsive: true,
                    displayModeBar: true,
                    modeBarButtonsToAdd: ['pan2d', 'lasso2d'],
                    displaylogo: false
                }}).then(() => {{
                    Plotly.Plots.resize(config.id);
                }});
            }});
            
            // Add window resize listener to update all plots
            window.addEventListener('resize', function() {{
                plotConfigs.filter(c => c.mode === 'plotly').forEach(config => {{
                    Plotly.Plots.resize(config.id);
                }});
            }});
        }}
        
        // Initialize on page load
        document.addEventListener('DOMContentLoaded', function() {{
            initializePlots();
            console.log('Dashboard initialized with {{}} plots'.replace('{{}}', plotConfigs.length));
        }});
    """