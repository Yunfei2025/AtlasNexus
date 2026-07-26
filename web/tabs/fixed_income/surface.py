"""Surface tab (Market > Surface).

Provides `build_surface_layout()` and `register_surface_callbacks(app)` for
the legacy yield-surface dashboard content, migrated onto the AtlasNexus Dash
app instance.
"""

from __future__ import annotations


def build_surface_layout():
    """Build the legacy 'SURFACE' (Yield Surface) layout."""
    # Import locally from the surface package in root
    from surface.layout import create_layout

    return create_layout()


def register_surface_callbacks(app) -> None:
    """Register the callbacks required by `build_surface_layout()` onto `app`."""
    try:
        from surface.callbacks import register_callbacks as register_surface_callbacks
        register_surface_callbacks(app)
    except Exception as e:
        print(f"Failed to register surface callbacks: {e}")
