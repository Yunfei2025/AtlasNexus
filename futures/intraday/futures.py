"""Bond futures dashboard entry point (modular)."""

from __future__ import annotations

from .app import app, run
from .layout import build_layout

# Register layout and callbacks (import side-effect registers callbacks)
app.layout = build_layout(app)
from . import callbacks  # noqa: F401

if __name__ == "__main__":
    run()
