"""
Engine package for factor analysis.
"""

# Import the main function from factor_engine
try:
    from .factor_engine import run_analysis, load_and_prepare_factors
except ImportError:
    # Fallback if relative imports don't work
    import sys
    import os
    sys.path.append(os.path.dirname(__file__))
    from factor_engine import run_analysis, load_and_prepare_factors

__all__ = ['run_analysis', 'load_and_prepare_factors']