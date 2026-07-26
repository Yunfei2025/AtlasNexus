# -*- coding: utf-8 -*-
"""Compatibility entry point for Summary > Books callbacks.

Implementation is split by responsibility into controls, Beta rendering, Alpha
rendering, and interaction modules in this package. This module retains the
original public registration function for existing callers.
"""

from .alpha_table import register_alpha_book_table_callbacks
from .beta_table import register_beta_book_table_callbacks
from .controls import register_risk_book_control_callbacks
from .interactions import register_risk_book_interaction_callbacks


def register_risk_books_callbacks(app):
    """Register all callbacks used by the Summary > Books subtab."""
    register_risk_book_control_callbacks(app)
    register_beta_book_table_callbacks(app)
    register_alpha_book_table_callbacks(app)
    register_risk_book_interaction_callbacks(app)


__all__ = ['register_risk_books_callbacks']
