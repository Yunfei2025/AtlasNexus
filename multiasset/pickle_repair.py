# -*- coding: utf-8 -*-
"""Recovery for pickles whose DataFrames trip pandas's BlockManager integrity
check on unpickle.

Observed on ``fxcurve_ts.pkl`` under pandas 3.0.2: one of its DataFrames
unpickles with a BlockManager whose blocks' column-location pointers
(``mgr_locs``) sum to more slots than the frame has columns -- i.e. two
blocks claim the same column position. Pandas 3.0's ``_verify_integrity``
catches this and raises ``AssertionError`` where older pandas would have
silently loaded it (and, worse, returned different values depending on
whether you sliced the frame as a whole or accessed one column at a time --
see ``repair_dataframe`` for why per-column reconstruction is what actually
fixes it, not just what silences the check).

This is a genuine defect in how the pickle's producer built that DataFrame,
not a pandas-version quirk to shrug off: the block-location aliasing means
whole-frame operations (``.tail()``, ``.iloc[:, i:j]``, …) can read the wrong
column's data through the aliased block. ``repair_dataframe`` sidesteps that
by rebuilding the frame one column at a time via ``frame[col]``, which
resolves through pandas's column-name lookup rather than the broken block
layout, and is verified (see module tests / manual check in the fix commit)
to agree with ``.loc``/``.iloc`` single-column access -- only whole-frame
multi-column slicing was ever wrong.
"""

from __future__ import annotations

import warnings
from typing import Any

import pandas as pd
from pandas.core.internals.managers import BlockManager


def _repair_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Rebuild ``df`` one column at a time.

    Only DataFrames whose BlockManager actually fails integrity go through
    this (see ``_repair_any``); a per-column rebuild is a cheap, safe no-op
    for a healthy frame and the only known fix for the aliased-block case.
    """
    return pd.DataFrame({col: df[col] for col in df.columns}, index=df.index)


def _repair_any(obj: Any) -> Any:
    """Recursively rebuild every DataFrame found inside ``obj``.

    ``fxcurve_ts.pkl`` is a ``dict[str, DataFrame]``; this also handles a
    bare DataFrame or a list/tuple of them, in case another artifact using
    this loader has a different container shape.
    """
    if isinstance(obj, pd.DataFrame):
        return _repair_dataframe(obj)
    if isinstance(obj, dict):
        return {k: _repair_any(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(_repair_any(v) for v in obj)
    return obj


def load_pickle_with_blockmanager_repair(file_path: str) -> Any:
    """Load a pickle, recovering from a BlockManager integrity failure.

    Tries a normal ``pd.read_pickle`` first. If that raises
    ``AssertionError`` from ``BlockManager._verify_integrity`` (the signature
    of the aliased-block corruption described in the module docstring),
    retries with the integrity check disabled just for the duration of the
    load -- restored in a ``finally`` regardless of outcome, so this doesn't
    weaken validation for any other pickle loaded elsewhere in the process --
    then rebuilds every DataFrame found column-by-column so no aliased block
    can produce silently-wrong values downstream.

    Any other exception (missing file, unrelated corruption, wrong pickle
    protocol, ...) is left to propagate unchanged; this only handles the one
    specific, understood failure mode.
    """
    try:
        return pd.read_pickle(file_path)
    except AssertionError as exc:
        if 'manager items' not in str(exc):
            raise  # a different assertion; don't mask it as this known case

    orig_verify = BlockManager._verify_integrity
    BlockManager._verify_integrity = lambda self: None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            obj = pd.read_pickle(file_path)
    finally:
        BlockManager._verify_integrity = orig_verify

    return _repair_any(obj)
