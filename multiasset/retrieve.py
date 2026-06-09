# -*- coding: utf-8 -*-
"""
Created on Tue Nov 25 20:22:40 2025

@author: CMBC
"""
import os
import sys
import pandas as pd
import datetime
import pathlib
from pathlib import Path

# Add project root to Python path FIRST
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Remove local 'data' module from cache to avoid shadowing root-level data package
if 'data' in sys.modules:
    del sys.modules['data']

from data.providers.retrieve import _is_trading_hours


CURVE_ARTIFACT_NAME = "fxcurve_ts.pkl"

def get_mtime_date(path_obj: pathlib.Path):
    """Get modification date of a file, return None if file doesn't exist."""
    try:
        p = pathlib.Path(path_obj)
        return datetime.datetime.fromtimestamp(p.stat().st_mtime).date()
    except FileNotFoundError:
        return None

def retrieveFXIRCurves():
    from settings.paths import DIR_INPUT
    file_path = os.path.join(DIR_INPUT, CURVE_ARTIFACT_NAME)
    t = datetime.datetime.today()
    mtime = get_mtime_date(pathlib.Path(file_path))
    if mtime != t.date() or not os.path.exists(file_path):
        if not _is_trading_hours():
            return
        from settings.general import DateConfig
        from multiasset.config import ticker_dict, tenorlist
        from multiasset.utils import updatePKL
        from WindPy import w
        w.start()
        _dates_strs = DateConfig.get_date_mappings()
        _dates_strs = DateConfig.get_date_strings()
        dps = _dates_strs['d7d']
        ds = _dates_strs['dp']
        curves_ts = {}
        for country, codes in ticker_dict.items():
            a = ",".join(codes)
            data = w.edb(a, dps, ds,"Fill=Previous",usedf=True)[1]
            df = pd.DataFrame(data, columns=codes)
            curves_ts[country] = df
            curves_ts[country].columns = [ country+t for t in tenorlist ]
        # Write single artifact with regenerated data
        updatePKL(curves_ts, file_path, rewrite=True)
