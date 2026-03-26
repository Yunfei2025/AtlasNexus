# -*- coding: utf-8 -*-
"""
Created on Tue Nov 25 20:22:40 2025

@author: CMBC
"""
import os
import pandas as pd
import datetime
import pathlib


CURVE_ARTIFACT_NAMES = ("curve_ts.pkl", "fxcurve_ts.pkl")

def get_mtime_date(path_obj: pathlib.Path):
    """Get modification date of a file, return None if file doesn't exist."""
    try:
        p = pathlib.Path(path_obj)
        return datetime.datetime.fromtimestamp(p.stat().st_mtime).date()
    except FileNotFoundError:
        return None

def retrieveFXIRCurves():
    from settings.paths import DIR_INPUT
    file_paths = [os.path.join(DIR_INPUT, name) for name in CURVE_ARTIFACT_NAMES]
    t = datetime.datetime.today()
    mtimes = [get_mtime_date(pathlib.Path(path)) for path in file_paths]
    valid_mtimes = [mtime for mtime in mtimes if mtime is not None]
    latest_mtime = max(valid_mtimes) if valid_mtimes else None
    if latest_mtime != t.date() or any(not os.path.exists(path) for path in file_paths):
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
        for file_path in file_paths:
            updatePKL(curves_ts, file_path)
