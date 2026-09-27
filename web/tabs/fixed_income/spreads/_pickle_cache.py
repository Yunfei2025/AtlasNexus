# -*- coding: utf-8 -*-
"""Shared mtime-based pickle cache used by the spread figure builders to
avoid redundant file loads across callbacks."""

from __future__ import annotations

import os
import pickle

_PICKLE_CACHE: dict[str, tuple[float, object]] = {}


def load_pickle_cached(path_obj):
    """Load pickle with caching based on file mtime."""
    path = str(path_obj)
    try:
        mtime = os.path.getmtime(path)
    except FileNotFoundError:
        return None

    cached = _PICKLE_CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1]

    try:
        with open(path, "rb") as f:
            obj = pickle.load(f)
        _PICKLE_CACHE[path] = (mtime, obj)
        return obj
    except Exception as e:
        print(f"Error loading {path}: {e}")
        return None
