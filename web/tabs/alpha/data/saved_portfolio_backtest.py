# -*- coding: utf-8 -*-
"""Persisted portfolio-level backtest result, for combining with the beta book.

Written by the Portfolio Backtest panel's "Save Result" action. Distinct from
``saved_state.py`` (per-instrument params/regime, read back into every
portfolio run) -- this is the *output* of one portfolio run: the combined
daily equity curve plus the instrument/weight snapshot that produced it, so a
later beta+alpha combination reads a fixed, known result instead of
recomputing (expensive: a full risk-parity + per-instrument backtest sweep)
or silently picking up whatever the live snapshot contains that day.

Schema (single pickle, ``DIR_ALPHA_PARAMS / 'alpha_portfolio_backtest.pkl'``):
    {
        'asof': pd.Timestamp,           # when this result was saved
        'portfolio_source': str,        # 'client' | 'default_tenor_spread'
        'equity_ts': pd.Series,         # daily cumulative PnL, bp, DatetimeIndex
        'sharpe': float,
        'total_pnl_bp': float,
        'max_drawdown_bp': float,
        'total_return_pct': float,      # bp/100 -- the curve is already DV01-
        'max_drawdown_pct': float,      # scaled, so 100bp = 1% of notional
        'roa_annual_pct': float,        # mean daily PnL x 252, in %
        'roe_annual_pct': Optional[float],       # roa_annual_pct / margin_ratio_per_notional
        'margin_ratio_per_notional': float,      # DV01-proxy margin, see estimate_margin_mm
        'instruments': list[dict],      # [{ID, spread_type, direction, weight, ...}]
        'lookback_days': int,
    }
"""

from __future__ import annotations

import pickle
from typing import Any, Optional

import pandas as pd

from .io import _get_input_dir, _load_pickle_cached

_RESULT_FILENAME = 'alpha_portfolio_backtest.pkl'


def _result_path():
    try:
        from settings.paths import DIR_ALPHA_PARAMS
        base = DIR_ALPHA_PARAMS
    except ImportError:
        base = _get_input_dir() / 'alpha_params'
        base.mkdir(parents=True, exist_ok=True)
    return base / _RESULT_FILENAME


def save_portfolio_backtest_result(
    portfolio_source: str,
    equity_ts: pd.Series,
    sharpe: float,
    total_pnl_bp: float,
    max_drawdown_bp: float,
    instruments: list[dict],
    lookback_days: int,
    total_return_pct: float = float('nan'),
    max_drawdown_pct: float = float('nan'),
    roa_annual_pct: float = float('nan'),
    roe_annual_pct: Optional[float] = None,
    margin_ratio_per_notional: float = float('nan'),
) -> None:
    """Persist one portfolio backtest run's result, overwriting any prior save."""
    payload = {
        'asof': pd.Timestamp.now().normalize(),
        'portfolio_source': portfolio_source,
        'equity_ts': equity_ts.copy(),
        'sharpe': float(sharpe),
        'total_pnl_bp': float(total_pnl_bp),
        'max_drawdown_bp': float(max_drawdown_bp),
        'total_return_pct': float(total_return_pct),
        'max_drawdown_pct': float(max_drawdown_pct),
        'roa_annual_pct': float(roa_annual_pct),
        'roe_annual_pct': float(roe_annual_pct) if roe_annual_pct is not None else None,
        'margin_ratio_per_notional': float(margin_ratio_per_notional),
        'instruments': list(instruments),
        'lookback_days': int(lookback_days),
    }
    with open(_result_path(), 'wb') as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)


def load_portfolio_backtest_result() -> Optional[dict]:
    """Return the last-saved portfolio backtest result, or None if never saved."""
    data = _load_pickle_cached(_result_path())
    return data if isinstance(data, dict) and 'equity_ts' in data else None
