# -*- coding: utf-8 -*-
"""
Created on Tue Sep 30 19:59:20 2025

@author: CMBC
"""
import os
import pandas as pd
import sys
import pathlib

# Add project root to path
PATH = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(PATH))

from settings.paths import DIR_INPUT, DIR_DATA
from data.providers.retrieve import _wsd, _wset, _wss, _edb
from settings.general import GeneralConfig, DateConfig
from settings.wind import WindConfig
from curves.utils.file import updatePKL 

def data_remedy(bondlist,key,file_path):
    database = updatePKL({},file_path)
    data_update = _wsd(bondlist, WindConfig.DATAMAP[key], dps, ds, "credibility=1").dropna()
    union = database[key].index.union(data_update.index)
    database[key] = database[key].reindex(union)
    database[key].loc[data_update.index,bondlist] = data_update.values
    database = updatePKL(database,file_path)

#%%
if __name__ == "__main__":
    btype = "CBond"
    file = btype +'-px.pkl'
    key = 'Close'
    dps = '2024-12-01'
    ds = '2025-04-01'
    bondlist = ['257702.IB']

    file_path = os.path.join(DIR_DATA, file)
    data_remedy(bondlist,key,file_path)

    file1 = btype +'-px.pkl'
    file2 = btype +'-cvpx.pkl'
    key1 = 'Close'
    key2 = 'ytm_act'

    file_path1 = os.path.join(DIR_DATA, file1)
    df_price = pd.read_pickle(file_path1)


    bond_px = {}
    bond_px[key2] = df_price[key1][bondlist]

    file_path2 = os.path.join(DIR_INPUT, file2)
    bond_px = updatePKL(bond_px,file_path2)
    af = bond_px[key2][bondlist]
