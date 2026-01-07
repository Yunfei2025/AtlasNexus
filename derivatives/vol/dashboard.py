# -*- coding: utf-8 -*-
"""
Web Server for Volatility Trading Strategy Dashboard
Created on Nov 18, 2025

@author: CMBC
"""
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import sys
import pathlib
import threading

# Local library imports
PATH = pathlib.Path(__file__).parent#.parent
sys.path.insert(0, str(PATH))

from main import VolatilityTradingEngine, retrieveFuturesVol

app = Flask(__name__)
# CORS(app)  # Temporarily disable CORS to test

# Global lock to prevent concurrent analysis runs
analysis_lock = threading.Lock()


def initialize_dashboard():
    """Initialize dashboard if it doesn't exist"""
    html_path = os.path.join(os.path.dirname(__file__), 'vol_strategy_analysis.html')
    
    if os.path.exists(html_path):
        print("✅ Dashboard already initialized")
        return True
    
    print("\n" + "=" * 80)
    print("🚀 Initializing Dashboard (First Time Setup)")
    print("=" * 80)
    print("\nGenerating initial dashboard with AU.SHF data...")
    
    try:
        # Retrieve data
        print("1. Retrieving futures volatility data...")
        retrieveFuturesVol()
        
        # Create engine with default ticker
        print("2. Creating analysis engine...")
        engine = VolatilityTradingEngine(
            code="AU.SHF",
            start_date="2025-01-01",
            end_date="2025-10-28"
        )
        
        # Run full analysis
        print("3. Running initial analysis...")
        engine.run_full_analysis()
        
        print("\n" + "=" * 80)
        print("✅ Dashboard initialized successfully!")
        print("=" * 80)
        return True
        
    except Exception as e:
        print(f"\n❌ Error initializing dashboard: {e}")
        import traceback
        traceback.print_exc()
        return False


@app.route('/test')
def test():
    """Simple test route"""
    return "Server is working!"


@app.route('/')
def index():
    """Serve the dashboard HTML with no-cache headers"""
    try:
        html_path = os.path.join(os.path.dirname(__file__), 'vol_strategy_analysis.html')
        if os.path.exists(html_path):
            from flask import make_response
            with open(html_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            response = make_response(html_content)
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            return response
        else:
            return render_error_page()
    except Exception as e:
        print(f"ERROR in index route: {e}")
        import traceback
        traceback.print_exc()
        return f"<h1>Error loading dashboard</h1><pre>{traceback.format_exc()}</pre>", 500

def render_error_page():
        return """
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }
                h1 { color: #333; }
                .info { background: #f0f0f0; padding: 15px; border-radius: 5px; margin: 20px 0; }
                button { background: #667eea; color: white; padding: 10px 20px; border: none; 
                        border-radius: 5px; cursor: pointer; font-size: 16px; }
                button:hover { background: #764ba2; }
            </style>
        </head>
        <body>
            <h1>📊 Volatility Trading Dashboard</h1>
            <div class="info">
                <p><strong>Dashboard not initialized yet.</strong></p>
                <p>Click the button below to initialize the dashboard with default data (AU.SHF).</p>
                <p>This is a one-time setup that will take a moment.</p>
            </div>
            <button onclick="window.location.href='/initialize'">Initialize Dashboard</button>
        </body>
        </html>
        """


@app.route('/initialize')
def initialize_route():
    """Initialize dashboard via web interface"""
    if initialize_dashboard():
        return """
        <html>
        <head>
            <meta http-equiv="refresh" content="2;url=/" />
            <style>
                body { font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; 
                       padding: 20px; text-align: center; }
                .success { color: #4CAF50; font-size: 24px; margin: 20px 0; }
            </style>
        </head>
        <body>
            <div class="success">✅ Dashboard initialized successfully!</div>
            <p>Redirecting to dashboard...</p>
        </body>
        </html>
        """
    else:
        return """
        <html>
        <body>
            <h1>❌ Initialization Failed</h1>
            <p>Check the console for error details.</p>
            <a href="/">Go back</a>
        </body>
        </html>
        """


@app.route('/run_analysis', methods=['POST'])
def run_analysis():
    """Run analysis for selected ticker"""
    
    # Check if another analysis is running
    if not analysis_lock.acquire(blocking=False):
        return jsonify({
            'success': False,
            'error': 'Another analysis is currently running. Please wait.'
        }), 409
    
    try:
        # Get ticker from request
        data = request.get_json()
        ticker = data.get('ticker', 'AU.SHF')
        
        print(f"\n{'='*80}")
        print(f"Starting analysis for {ticker}...")
        print(f"{'='*80}\n")
        
        # Retrieve data
        retrieveFuturesVol()
        
        # Create engine
        engine = VolatilityTradingEngine(
            code=ticker,
            start_date="2025-01-01",
            end_date="2025-10-28"
        )
        
        # Run analysis
        engine.run_full_analysis()
        
        print(f"\n{'='*80}")
        print("✅ Analysis Complete!")
        print(f"{'='*80}\n")
        
        return jsonify({
            'success': True,
            'ticker': ticker,
            'message': 'Analysis completed successfully'
        })
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
        
    finally:
        analysis_lock.release()


@app.route('/status')
def status():
    """Check server status"""
    return jsonify({
        'status': 'running',
        'version': '1.0.0'
    })


def main():
    """Start the web server"""
    print("=" * 80)
    print("🌐 Starting Volatility Trading Strategy Web Server")
    print("=" * 80)
    
    # Check and initialize dashboard if needed
    html_path = os.path.join(os.path.dirname(__file__), 'vol_strategy_analysis.html')
    if not os.path.exists(html_path):
        print("\n⚠️  Dashboard not found. Initializing with default data...")
        initialize_dashboard()
    
    print("\n" + "=" * 80)
    print("🌐 Server ready at: http://localhost:5000")
    print("=" * 80)
    print("\nPress Ctrl+C to stop the server")
    # print("\nOpening browser...")
    
    # Open browser automatically
    # import webbrowser
    # import time
    # threading.Timer(1.5, lambda: webbrowser.open('http://localhost:5000')).start()
    
    try:
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=True, use_reloader=False)
    except Exception as e:
        print(f"\n❌ Server error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
