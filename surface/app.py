"""Main Dash application for yield surface visualization."""

from __future__ import annotations

import dash

from .layout import create_layout
from .callbacks import register_callbacks


# Initialize the Dash app
app = dash.Dash(
    __name__,
    meta_tags=[{"name": "viewport", "content": "width=device-width"}]
)
app.title = "Yield Curve Viewer"
server = app.server

# Set the layout
app.layout = create_layout()

# Register callbacks
register_callbacks(app)


def run(debug: bool = True, port: int = 8053) -> None:
    """Run the yield surface dashboard.
    
    Args:
        debug: Enable debug mode.
        port: Port number to run the server on.
    """
    app.run(port=port, debug=debug)


if __name__ == "__main__":
    run()
