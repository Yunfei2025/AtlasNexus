# -*- coding: utf-8 -*-
"""
Interactive Web Dashboard Server for Portfolio Backtesting

Provides a web interface for selecting instruments and running portfolio analysis.

@author: CMBC
"""
from flask import Flask, render_template, request, jsonify, send_file
import pandas as pd
from datetime import date, datetime, timedelta
from pathlib import Path
import sys
import os
import traceback

PATH = Path(__file__).parent.parent
sys.path.insert(0, str(PATH))

from settings.general import DateConfig
from backtest.portfolio import PortfolioBacktester
from backtest.visualization import plot_backtest_dashboard

app = Flask(__name__)

# Available instruments catalog
INSTRUMENTS = {
    'CBond': { "<=1Y":[
        '190408.IB', '190209.IB', '230203.IB', '210215.IB',
        '200210.IB', '180019.IB', '170025.IB'],
    },
    'R7D': { "All":[
        'FR007S1Y.IR', 'FR007S2Y.IR', 'FR007S3Y.IR', 
        'FR007S5Y.IR', 'FR007S7Y.IR', 'FR007S10Y.IR'],
    }
}


def get_default_dates():
    """Get default date range (last 3 months)"""
    date_map = DateConfig.get_date_mappings()
    return date_map['d3m'].date(), date_map['dp'].date()


@app.route('/')
def index():
    """Serve the main dashboard page"""
    return render_template('portfolio_dashboard.html', instruments=INSTRUMENTS)


@app.route('/run_backtest', methods=['POST'])
def run_backtest():
    """Run portfolio backtest with selected positions"""
    try:
        data = request.json
        positions = data.get('positions', [])
        start_date = datetime.strptime(data.get('start_date'), '%Y-%m-%d').date()
        end_date = datetime.strptime(data.get('end_date'), '%Y-%m-%d').date()
        
        if not positions:
            return jsonify({'status': 'error', 'message': 'No positions selected'}), 400

        # Normalize and validate positions (ensure numeric sizes)
        norm_positions = []
        for pos in positions:
            btype = pos.get('btype') if isinstance(pos, dict) else None
            code = pos.get('code') if isinstance(pos, dict) else None
            size_raw = pos.get('size') if isinstance(pos, dict) else None
            if code is None or btype is None:
                continue
            try:
                size_val = float(size_raw)
            except (TypeError, ValueError):
                return jsonify({'status': 'error', 'message': f'Invalid notional for {code}: {size_raw}'}), 400
            norm_positions.append({'btype': btype, 'code': code, 'size': size_val})
        positions = norm_positions
        
        print("\n" + "=" * 80)
        print("RUNNING PORTFOLIO BACKTEST")
        print("=" * 80)
        print(f"\nPeriod: {start_date} to {end_date}")
        print(f"\nPositions:")
        for pos in positions:
            print(f"  - {pos['btype']} {pos['code']}: {pos['size']:+,.0f}")
        
        # Create portfolio
        portfolio = PortfolioBacktester(start_date, end_date)
        
        # Add positions
        for pos in positions:
            btype = pos['btype']
            instrument = pos['code']
            notional = pos['size']
            
            # Determine if bond or IRS based on btype
            if btype in ['CBond', 'TBonds']:  # Bond types
                portfolio.add_bond_position(instrument, btype, notional)
            elif btype in ['R7D', 'S3M']:  # IRS types
                portfolio.add_irs_position(instrument, btype, notional)
        
        # Run backtest
        portfolio.run()
        results = portfolio.get_results()
        
        # Prepare comparison data
        comparison_data = {
            'Portfolio': {
                'pnl': results['pnl'],
                'metrics': results['metrics']
            }
        }
        
        rate_data_dict = {}
        for key, comp in results['components'].items():
            comp_type = comp['type'].upper()
            instrument = key.split('_', 1)[1]
            comp_name = f"{comp_type} {instrument}"
            
            comparison_data[comp_name] = {
                'pnl': comp['scaled_pnl'],
                'metrics': comp['backtester'].metrics
            }
            
            if comp_type == 'BOND':
                rate_data_dict[f'{instrument}_ytm'] = {
                    'data': comp['backtester'].yields,
                    'name': f'{instrument} YTM'
                }
            elif comp_type == 'IRS':
                rate_data_dict[f'{instrument}_rate'] = {
                    'data': comp['backtester'].quotes,
                    'name': f'{instrument} Rate'
                }
        
        # Generate visualization
        position_str = ', '.join([f"{p['code']} ({p['size']:+,.0f})" for p in positions])
        fig = plot_backtest_dashboard(
            pnl=results['pnl'],
            attribution=results['attribution'],
            metrics=results['metrics'],
            capital=results['total_capital'],
            title=f"Portfolio Dashboard: {position_str}",
            comparison_data=comparison_data,
            rate_data=rate_data_dict if rate_data_dict else None
        )
        
        # Save HTML
        output_file = os.path.join(os.path.dirname(__file__), 'portfolio_dashboard_output.html')
        fig.write_html(output_file)
        
        # Return metrics summary
        metrics_dict = {k: float(v) for k, v in results['metrics'].items()}
        
        print("\n✅ Backtest complete!")
        print(f"Total Capital: {results['total_capital']:,.2f}")
        print("=" * 80 + "\n")
        
        return jsonify({
            'status': 'success',
            'metrics': metrics_dict,
            'total_capital': float(results['total_capital']),
            'output_file': 'portfolio_dashboard_output.html'
        })
        
    except Exception as e:
        import traceback
        print(f"\n❌ Error: {str(e)}")
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/get_output')
def get_output():
    """Serve the generated dashboard HTML"""
    output_file = os.path.join(os.path.dirname(__file__), 'portfolio_dashboard_output.html')
    if os.path.exists(output_file):
        return send_file(output_file)
    else:
        return "No results available yet. Run a backtest first.", 404


if __name__ == '__main__':
    print("=" * 80)
    print("🚀 Starting Portfolio Dashboard Server")
    print("=" * 80)
    print("\n📊 Access dashboard at: http://localhost:5001")
    print("\nAvailable instruments:")
    for category, instruments in INSTRUMENTS.items():
        print(f"\n  {category}:")
        for inst in instruments:
            print(f"    - {inst}")
    print("\n" + "=" * 80)
    
    # Create templates directory if it doesn't exist
    templates_dir = os.path.join(os.path.dirname(__file__), 'templates')
    os.makedirs(templates_dir, exist_ok=True)
    
    # Run without reloader to avoid watchdog issues
    app.run(debug=True, port=5001, threaded=True, use_reloader=False)
