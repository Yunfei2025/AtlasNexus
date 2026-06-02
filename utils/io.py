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
import re
import pandas as pd


_LEGACY_REPO_PREFIX = re.compile(r'^Repo-', re.IGNORECASE)


def _normalize_legacy_repo_label(value):
    if isinstance(value, str):
        return _LEGACY_REPO_PREFIX.sub('Repo7d-', value)
    return value


def _drop_legacy_repo_labels(labels):
    """Boolean mask: drop Repo- entries that have a Repo7d- equivalent."""
    repo7d = {str(v) for v in labels if isinstance(v, str) and v.startswith('Repo7d-')}
    return [
        not (isinstance(v, str) and v.startswith('Repo-')
             and v.replace('Repo-', 'Repo7d-', 1) in repo7d)
        for v in labels
    ]


def _normalize_legacy_repo_obj(obj):
    if isinstance(obj, pd.DataFrame):
        out = obj.copy()
        if out.index.dtype == object:
            keep = _drop_legacy_repo_labels(out.index)
            if not all(keep):
                out = out.loc[keep]
            out.index = out.index.map(_normalize_legacy_repo_label)
            if out.index.has_duplicates:
                out = out[~out.index.duplicated(keep='last')]
        if out.columns.dtype == object:
            keep = _drop_legacy_repo_labels(out.columns)
            if not all(keep):
                out = out.loc[:, keep]
            out.columns = out.columns.map(_normalize_legacy_repo_label)
            if out.columns.has_duplicates:
                out = out.loc[:, ~out.columns.duplicated(keep='last')]
        return out
    if isinstance(obj, pd.Series):
        out = obj.copy()
        if out.index.dtype == object:
            keep = _drop_legacy_repo_labels(out.index)
            if not all(keep):
                out = out.loc[keep]
            out.index = out.index.map(_normalize_legacy_repo_label)
            if out.index.has_duplicates:
                out = out[~out.index.duplicated(keep='last')]
        out.name = _normalize_legacy_repo_label(out.name)
        return out
    if isinstance(obj, dict):
        return {
            _normalize_legacy_repo_label(key): _normalize_legacy_repo_obj(value)
            for key, value in obj.items()
        }
    if isinstance(obj, list):
        return [_normalize_legacy_repo_obj(value) for value in obj]
    if isinstance(obj, tuple):
        return tuple(_normalize_legacy_repo_obj(value) for value in obj)
    return obj


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
        return _normalize_legacy_repo_obj(pd.read_parquet(parquet, engine='pyarrow'))
    return _normalize_legacy_repo_obj(pd.read_pickle(path))
