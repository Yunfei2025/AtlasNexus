# -*- coding: utf-8 -*-
"""Pickle loading, mtime-keyed caching, and Repo-label normalization."""

from __future__ import annotations

import pickle
import re
from pathlib import Path
from typing import Any, Optional

import pandas as pd


def _get_input_dir() -> Path:
    try:
        from settings.paths import DIR_INPUT
        return Path(DIR_INPUT)
    except ImportError:
        return Path(__file__).parent.parent.parent.parent / 'input'


# ---------------------------------------------------------------------------
# Repo-label normalizer (applied once per file load, not per call site)
# ---------------------------------------------------------------------------

def _normalize_repo_label(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r'^Repo-', 'Repo7d-', value, flags=re.IGNORECASE)
    return value


def _normalize_repo_obj(obj: Any) -> Any:
    if isinstance(obj, pd.DataFrame):
        out = obj.copy()
        if out.index.dtype == object:
            out.index = out.index.map(_normalize_repo_label)
        if out.columns.dtype == object:
            out.columns = out.columns.map(_normalize_repo_label)
        return out
    if isinstance(obj, pd.Series):
        out = obj.copy()
        if out.index.dtype == object:
            out.index = out.index.map(_normalize_repo_label)
        out.name = _normalize_repo_label(out.name)
        return out
    if isinstance(obj, dict):
        return {_normalize_repo_label(k): _normalize_repo_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize_repo_obj(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_normalize_repo_obj(v) for v in obj)
    return obj


# ---------------------------------------------------------------------------
# mtime-keyed pickle cache  (module-level, shared across all callers)
# ---------------------------------------------------------------------------

_PICKLE_CACHE: dict[str, tuple[float, Any]] = {}


def _load_pickle_cached(filepath: Path) -> Optional[Any]:
    """Load a pickle file, caching the result keyed by file mtime.

    The Repo-label normalization is applied once per file load and the
    normalized object is stored in the cache, so callers never pay for it.
    """
    path_str = str(filepath)
    try:
        mtime = filepath.stat().st_mtime
    except FileNotFoundError:
        return None

    cached = _PICKLE_CACHE.get(path_str)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    try:
        with open(filepath, 'rb') as f:
            obj = pickle.load(f)
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        try:
            obj = pd.read_pickle(filepath)
        except Exception as e2:
            print(f"Fallback also failed for {filepath}: {e2}")
            return None

    obj = _normalize_repo_obj(obj)
    _PICKLE_CACHE[path_str] = (mtime, obj)
    return obj


def _load_pickle_safe(filepath: Path) -> Optional[Any]:
    """Thin wrapper kept for call-site compatibility; delegates to the mtime cache."""
    return _load_pickle_cached(filepath)


def _normalize_repo_frame(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if not isinstance(df, pd.DataFrame):
        return df
    out = df.copy()
    if out.index.dtype == object:
        out.index = out.index.map(lambda x: re.sub(r'^Repo-', 'Repo7d-', str(x), flags=re.IGNORECASE))
    if out.columns.dtype == object:
        out.columns = out.columns.map(lambda x: re.sub(r'^Repo-', 'Repo7d-', str(x), flags=re.IGNORECASE))
    return out
