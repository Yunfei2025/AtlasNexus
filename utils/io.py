# -*- coding: utf-8 -*-
"""
utils/io.py — Unified DataFrame I/O helpers.

save_frame / load_frame provide a Parquet-first, pickle-fallback strategy:
  - DataFrames are written as <base>.parquet (pyarrow engine).
  - Any other Python object (dict-of-DataFrames, custom class, …) is kept as
    pickle, unchanged.  This means existing dict-valued .pkl files continue to
    work without any migration.
  - load_frame tries the companion .parquet file first; if absent it falls back
    to pd.read_pickle (covering both old-format and dict files).

Usage
-----
    from utils.io import save_frame, load_frame

    save_frame(df, '/path/to/file.pkl')    # writes /path/to/file.parquet
    save_frame(my_dict, '/path/to/x.pkl') # writes /path/to/x.pkl  (unchanged)

    obj = load_frame('/path/to/file.pkl') # reads .parquet if present, else .pkl
"""

from __future__ import annotations

import os
import pickle
import pandas as pd


def _parquet_path(path: str) -> str:
    """Return the .parquet companion path for a given (typically .pkl) path."""
    base, _ = os.path.splitext(str(path))
    return base + '.parquet'


def save_frame(obj, path: str) -> None:
    """Save *obj* to disk.

    * ``pd.DataFrame`` → written as Parquet at ``<stem>.parquet``.
    * Any other type   → written as pickle at *path* unchanged.
    """
    if isinstance(obj, pd.DataFrame):
        obj.to_parquet(_parquet_path(path), engine='pyarrow')
    else:
        with open(path, 'wb') as fh:
            pickle.dump(obj, fh)


def load_frame(path: str):
    """Load from disk, preferring Parquet when available.

    Resolution order:
    1. ``<stem>.parquet`` (fast, typed, columnar) — if the file exists.
    2. *path* as-is via ``pd.read_pickle`` (backward-compatible fallback).

    Returns whatever was stored: a ``pd.DataFrame`` for Parquet files, or the
    original Python object for pickle files.
    """
    parquet = _parquet_path(path)
    if os.path.exists(parquet):
        return pd.read_parquet(parquet, engine='pyarrow')
    return pd.read_pickle(path)
