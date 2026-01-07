# -*- coding: utf-8 -*-
"""
Created on Mon Dec  8 22:53:04 2025

@author: CMBC
"""

import datetime as dt
import os

from utils.file import updatePKL, get_mtime_date
from settings.paths import DIR_INPUT

def retrieveSurface():
    d = dt.datetime.today()
    file_path = os.path.join(DIR_INPUT, "surface-ts.pkl")
    surface_dict = {}
    
    if d.date() != get_mtime_date(file_path):
        print("INFO: Updating time series...")
        from settings.general import DateConfig
        from WindPy import w
        w.start()
        _dates_strs = DateConfig.get_date_mappings()
        _dates_strs = DateConfig.get_date_strings()
        dps = _dates_strs['d7d']
        ds = _dates_strs['dp']
        
        from surface.config import cn_id_list, cn_id_name, us_id_list, us_id_name
        df0 = w.edb(cn_id_list, dps, ds, "Fill=Previous", usedf=True)[1]
        df0.columns = cn_id_name
        surface_dict["CN"] = df0
        
        df1 = w.edb(us_id_list, dps, ds, "Fill=Previous", usedf=True)[1]
        df1.columns = us_id_name
        surface_dict["US"] = df1
        
        surface_dict = updatePKL(surface_dict, file_path)