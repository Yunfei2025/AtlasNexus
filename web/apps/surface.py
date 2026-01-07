"""Yield surface dashboard entry point.

This module serves as the entry point for the yield surface visualization.
The actual implementation is in the 'surface' package at the project root.
"""

from __future__ import annotations

# Add project root to Python path
from pathlib import Path
import sys
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Import from the surface package at project root
from surface import app, server, run

__all__ = ["app", "server", "run"]


if __name__ == "__main__":
    run()
