# -*- coding: utf-8 -*-
"""
Created on Wed Oct 29 00:26:32 2025

@author: CMBC
"""
import os
import datetime
from data.providers.retrieve import _wsd
from curves.utils.file import updatePKL
from settings.general import DateConfig
from settings.paths import DIR_INPUT
from settings.futures import FuturesConfig
from curves.utils.generator_utils import get_mtime_date

# Localized new-config convenience variables
_dates = DateConfig.get_date_mappings()
_dates_strs = DateConfig.get_date_strings()


def _force_update_requested(cfg=None) -> bool:
    return bool(getattr(cfg, "params", {}).get("force_update", False))


def retrieveFuturesVol(cfg=None):
    t = datetime.datetime.today()
    futures_file = DIR_INPUT / 'futures-volpx.pkl'
    force_update = _force_update_requested(cfg)
    if force_update or t.date() != get_mtime_date(futures_file):
        print("INFO: Updating vol time series...")
        dps = _dates_strs['d7d']
        ds = _dates_strs['dp']
        field = "iv_1m1000_n,iv_2m1000_n,iv_3m1000_n"  # 1M, 2M, 3M implied volatility
        # Fetch data
        data = {}
        for fut in FuturesConfig.VOL_SYMBOLS:
            data[fut] = _wsd(fut, field, dps, ds, "model=1")
            
        file_path = os.path.join(DIR_INPUT, 'futures-volpx.pkl')
        data = updatePKL(data, file_path)
    else:
        print(f"{futures_file} was updated today, skipping retrieveFuturesVol().")