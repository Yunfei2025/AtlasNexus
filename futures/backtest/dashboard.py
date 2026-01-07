"""
Quantitative Strategy Backtesting Dashboard - Main Entry Point
This is the refactored main file, with actual functionality split into separate modules
"""

import dash
from layout import create_layout
from callbacks import register_callbacks


# Create Dash application
app = dash.Dash(__name__, title="Strategy Backtesting Dashboard")

# Set layout
app.layout = create_layout()

# Register callbacks
register_callbacks(app)


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8054, debug=False, use_reloader=False)
