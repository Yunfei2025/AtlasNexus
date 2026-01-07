#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration file for FIEngine - Financial Engineering System

Created on Sun Jan 15 16:09:22 2023
@author: mayunfei

This module contains all configuration constants and settings for the FIEngine system.
"""

# When this file is executed directly (e.g. from an IDE), relative imports like
# `from .paths import ...` fail with:
#   ImportError: attempted relative import with no known parent package
# This bootstrap makes direct execution behave like `python -m settings.settings`.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path

    _this_file = _Path(__file__).resolve()
    _project_root = _this_file.parent.parent  # .../bin-v3.0
    if str(_project_root) not in _sys.path:
        _sys.path.insert(0, str(_project_root))
    __package__ = "settings"

from typing import Dict, List
import warnings
warnings.simplefilter("ignore")

from .paths import PATH, DIR_INPUT, DIR_OUTPUT, DIR_DATA
from .general import app_color, GeneralConfig, DateConfig
from .fixed_income import BondConfig, IRSConfig, InstitutionConfig
from .futures import FuturesConfig
from .wind import WindConfig

# Backward compatibility exports
__all__ = [
    'PATH', 'DIR_INPUT', 'DIR_OUTPUT', 'DIR_DATA',
    'app_color', 'GeneralConfig', 'DateConfig',
    'BondConfig', 'IRSConfig', 'InstitutionConfig', 'FuturesConfig', 'WindConfig'
]

# Convenience import: keep legacy function name available
import pandas as _pd
import os as _os
import pickle as _pickle

def load_calendar():
    try:
        return _pd.read_pickle(_os.path.join(DIR_INPUT, 'Calendar.pkl'))
    except Exception:
        with open(_os.path.join(DIR_INPUT, 'Calendar.pkl'), 'rb') as f:
            return _pickle.load(f)



