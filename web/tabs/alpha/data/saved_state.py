# -*- coding: utf-8 -*-
"""Persisted per-instrument backtest parameters and monthly regime schedules.

Written by the individual-spread backtest panel's "Save Parameters" action and
read back by the portfolio backtest loop, so a manually-reviewed instrument can
use its own tuned entry/exit/stop thresholds and its own month-by-month
MR/trend regime schedule instead of the book-wide default. An instrument that
has never been saved is unaffected: callers fall back to today's behaviour.

Schema (single pickle, ``DIR_ALPHA_PARAMS / 'saved_alpha_state.pkl'``):
    {spread_type: {instrument: {
        'params': {entry_z, exit_z, stop_z, min_hold, theta, vol_window,
                   trailing_mult, mom_window, allow_short,
                   carry_z_weight},  # composite z-score carry blend, default 0.5
        'regime': {'month_to_style': {pd.Period('M'): 'mr'|'trend'},
                   'schedule': pd.DataFrame,   # build_monthly_style_schedule output
                   'asof': pd.Timestamp},      # last date the schedule computed
    }}}
"""

from __future__ import annotations

import pickle
from typing import Any, Optional

import pandas as pd

from .io import _get_input_dir, _load_pickle_cached

_STATE_FILENAME = 'saved_alpha_state.pkl'


def _state_path():
    try:
        from settings.paths import DIR_ALPHA_PARAMS
        base = DIR_ALPHA_PARAMS
    except ImportError:
        base = _get_input_dir() / 'alpha_params'
        base.mkdir(parents=True, exist_ok=True)
    return base / _STATE_FILENAME


def _load_state() -> dict:
    state = _load_pickle_cached(_state_path())
    return state if isinstance(state, dict) else {}


def _write_instrument_entry(spread_type: str, instrument: str, entry_updates: dict) -> None:
    """Read-modify-write a single {spread_type: {instrument: {...}}} leaf.

    Not routed through ``utils.file.updatePKL``: that helper's generic
    DataFrame-merge assumes a wide numeric time-series shape (union index and
    columns, assign in place), which doesn't fit the mixed-dtype ``schedule``
    frame or the plain-dict ``params``/``regime`` payloads stored here. This
    file is a small nested dict of independent per-instrument leaves, so a
    read-modify-write that replaces only the touched leaf is both correct and
    sufficient -- other instruments' entries are left untouched.
    """
    path = _state_path()
    try:
        with open(path, 'rb') as f:
            state = pickle.load(f)
        if not isinstance(state, dict):
            state = {}
    except FileNotFoundError:
        state = {}

    inst_map = state.setdefault(spread_type, {})
    entry = inst_map.setdefault(instrument, {})
    entry.update(entry_updates)

    with open(path, 'wb') as f:
        pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)


def save_instrument_params(spread_type: str, instrument: str, params: dict) -> None:
    """Persist a reviewed instrument's backtest parameters (entry_z, exit_z, ...)."""
    _write_instrument_entry(spread_type, instrument, {'params': dict(params)})


def save_monthly_regime(
    spread_type: str,
    instrument: str,
    month_to_style: dict,
    schedule: Optional[pd.DataFrame] = None,
) -> None:
    """Persist a reviewed instrument's monthly MR/trend regime schedule."""
    regime = {
        'month_to_style': dict(month_to_style),
        'asof': pd.Timestamp.now().normalize(),
    }
    if schedule is not None:
        regime['schedule'] = schedule
    _write_instrument_entry(spread_type, instrument, {'regime': regime})


def save_instrument_state(
    spread_type: str,
    instrument: str,
    params: dict,
    month_to_style: dict,
    schedule: Optional[pd.DataFrame] = None,
) -> None:
    """Persist both params and monthly regime schedule for an instrument in one write."""
    regime = {
        'month_to_style': dict(month_to_style),
        'asof': pd.Timestamp.now().normalize(),
    }
    if schedule is not None:
        regime['schedule'] = schedule
    _write_instrument_entry(spread_type, instrument, {'params': dict(params), 'regime': regime})


def load_instrument_params(spread_type: str, instrument: str) -> Optional[dict]:
    """Return the saved params dict for this instrument, or None if never saved."""
    entry = _load_state().get(spread_type, {}).get(instrument, {})
    params = entry.get('params')
    return dict(params) if isinstance(params, dict) else None


def load_monthly_regime(spread_type: str, instrument: str) -> Optional[dict]:
    """Return the saved {'month_to_style', 'schedule', 'asof'} dict, or None if never saved."""
    entry = _load_state().get(spread_type, {}).get(instrument, {})
    regime = entry.get('regime')
    return regime if isinstance(regime, dict) and regime.get('month_to_style') else None


def has_saved_state(spread_type: str, instrument: str) -> bool:
    """True if this instrument has any reviewed/saved params or regime schedule."""
    entry = _load_state().get(spread_type, {}).get(instrument, {})
    return bool(entry.get('params')) or bool(
        isinstance(entry.get('regime'), dict) and entry['regime'].get('month_to_style')
    )
