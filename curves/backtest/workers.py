# -*- coding: utf-8 -*-
"""
Worker functions for backtest multiprocessing.

This module contains the worker functions and context for parallel backtest execution.
Separated from main modules to avoid circular imports.
"""

import logging

logger = logging.getLogger(__name__)

# ===== Module-level worker context for multiprocessing (Windows-safe) =====
# These globals are set once per worker process via the pool initializer.
_WORKER_BOND_TYPE = None
_WORKER_CACHE = None
_WORKER_ENV = None
_WORKER_PRANGE = None
_PRICE_BOND_TYPE = None
_PRICE_DICT_CURVE = None
_PRICE_ENV = None

def _init_worker_curves(bond_type, cache, env=None, prange=None):
    """Initializer for worker processes to set shared, picklable context."""
    global _WORKER_BOND_TYPE, _WORKER_CACHE, _WORKER_ENV, _WORKER_PRANGE
    _WORKER_BOND_TYPE = bond_type
    _WORKER_CACHE = cache
    _WORKER_ENV = env
    _WORKER_PRANGE = prange

def _init_curves_chunk_worker(date_chunk):
    """Top-level worker function to create curves for a chunk of dates."""
    from curves.backtest.core import CurveManager  # local import inside worker
    
    # Build a lightweight manager and attach precomputed cache
    worker_manager = CurveManager(_WORKER_BOND_TYPE)
    worker_manager._cache = _WORKER_CACHE
    
    chunk_curves = {}
    for date in date_chunk:
        try:
            if _WORKER_BOND_TYPE == 'IRS':
                chunk_curves[date] = worker_manager._create_irs_curve(_WORKER_ENV, date, _WORKER_PRANGE)
            else:
                chunk_curves[date] = worker_manager._create_bond_curve(date)
        except Exception as e:
            logger.warning(f"{e}")  
        logger.info(f"Created curve for {date}.")
    return chunk_curves

def _init_worker_pricing(bond_type, dict_curve, env):
    """Initializer for pricing workers to set shared dict_curve and env."""
    global _PRICE_BOND_TYPE, _PRICE_DICT_CURVE, _PRICE_ENV
    _PRICE_BOND_TYPE = bond_type
    _PRICE_DICT_CURVE = dict_curve
    _PRICE_ENV = env

def _price_chunk_worker(period_chunk):
    """Top-level pricing worker that prices instruments for a chunk period."""
    from curves.backtest.core import PricingEngine  # import inside worker
    engine = PricingEngine(_PRICE_BOND_TYPE)
    
    # Convert period_chunk (list of dates) to [start, end] format expected by price_instruments
    if len(period_chunk) == 0:
        return {}
    elif len(period_chunk) == 1:
        price_range = period_chunk  # Single date
    else:
        # Multiple dates: use first and last as range
        price_range = [period_chunk[0], period_chunk[-1]]
    
    return engine.price_instruments(_PRICE_DICT_CURVE, _PRICE_ENV, price_range)