# -*- coding: utf-8 -*-
"""
Created on Wed Jan 11 10:42:19 2023

@author: 马云飞
"""
import os
import sys
import numpy as np
import pandas as pd
import pickle
import datetime as dt
from settings.paths import DIR_INPUT, DIR_DATA
from settings.fixed_income import BondConfig
from settings.wind import WindConfig
from curves.utils.calendar import getCalendar, is_cn_workday
from dateutil.relativedelta import relativedelta     

sys.modules.setdefault('numpy._core', np.core)


class LegacyPickleCompatibilityError(RuntimeError):
    pass


def _read_pickle_compat(file_path, label=None):
    try:
        return pd.read_pickle(file_path)
    except Exception as e:
        msg = str(e)
        legacy_layout = (
            "Number of manager items must equal union of block items" in msg
            or "manager items" in msg
            or "block items" in msg
            or "BlockManager" in msg
        )
        if not legacy_layout:
            display = label or file_path
            print(f"Warning: Error loading {display} with pd.read_pickle: {e}")
            print("Falling back to pickle.load...")
        try:
            with open(file_path, 'rb') as f:
                return pickle.load(f)
        except Exception:
            if legacy_layout:
                raise LegacyPickleCompatibilityError(label or file_path) from e
            raise

def loadWorkday(start,end,update=False):
    date_range = pd.date_range(start=start, end=end, freq='D')
    workdays = [d.date() for d in date_range if is_cn_workday(d.date())]
    return pd.Index(workdays)

def loadCNBDTS():
    file_path = os.path.join(DIR_INPUT, 'database-px.pkl')
    # file_path = os.path.join(DIR_DATA, 'CNDBCurve-px.pkl')
    ts = _read_pickle_compat(file_path)
    env = {}
    env['SwapTS'] = ts['IRS']
    env['CGB'] = ts['CGB']
    env['SOFR'] = ts['sofr']
    env['FX'] = ts['fx']
    env['FXSwap'] = ts['fxswap']
    file_path = os.path.join(DIR_INPUT, 'TBond-cvref.pkl')
    # Direct load to avoid unnecessary rewrite
    ref = _read_pickle_compat(file_path)
    env['Factors'] = ref['Factors']
    return env

def loadInstrumentDefinition(btype):
    env = {}
    file_path = os.path.join(DIR_INPUT, btype + '-InstrumentInfo.pkl')
    loaded = _read_pickle_compat(file_path, f"{btype}-InstrumentInfo.pkl")
    if btype == 'futures':
        env = loaded
    else:
        env['Def'] = loaded

    if btype in ['TBond','CBond']:
        env['Def']['成交量:万元'] = env['Def']['成交量'].replace(np.nan,0)/1e4
    return env

def loadRefData(btype):
    """Load reference data using pandas read_pickle for better compatibility"""
    return _read_pickle_compat(os.path.join(DIR_INPUT, btype+'-cvref.pkl'), f"{btype}-cvref.pkl")
    
def loadStatData(btype):
    env_st = {}
    file_path = os.path.join(DIR_INPUT, btype+'-spds.pkl')

    def _rebuild_misc_spreads():
        print("Info: Rebuilding Misc-spds.pkl ...")
        from curves.generators.stat import StatGenerator
        StatGenerator.main()

    try:
        spd = _read_pickle_compat(file_path, f"{btype}-spds.pkl")
    except LegacyPickleCompatibilityError:
        if btype == 'Misc':
            _rebuild_misc_spreads()
            spd = _read_pickle_compat(file_path, f"{btype}-spds.pkl")
        else:
            raise
    if btype == 'Misc':
        required = {'PCASpread', 'BinarySpread'}
        if not required.issubset(spd.keys()):
            _rebuild_misc_spreads()
            spd = _read_pickle_compat(file_path, f"{btype}-spds.pkl")
    if btype in ['TBond','CBond']:
        env_st['BondCurve'] = spd['BondCurve']['StatInfo']
        env_st['BondSwap']  = spd['BondSwap']['StatInfo']
    elif btype == 'IRS':
        env_st['SwapSpread'] = spd['StatInfo']
    elif btype in BondConfig.INCLUDE_FILTERS.keys():
        env_st[btype+'Spread'] = spd[btype+'Spread']['StatInfo']
    elif btype == 'Misc':
        env_st['PCASpread'] = spd['PCASpread']['StatInfo']
        env_st['SpotTS'] = spd['PCASpread']['Spot']
        env_st['SpreadTS'] = spd['PCASpread']['Spread']
        env_st['BinarySpread'] = spd['BinarySpread']['StatInfo']
        env_st['BinaryAnchor'] = spd['BinarySpread']['Anchor']
    elif btype == 'futures':
        env_st['NetBasis'] = {}
        for b in spd['NetBasis'].keys():
            env_st['NetBasis'][b] = spd['NetBasis'][b]['StatInfo']
        env_st['TermBasis'] = spd['TermBasis']['StatInfo']
    else:
        pass
    return env_st

def loadBacktestingInputs(btype,prange,database):
    env = {}
    env['Def'] = _read_pickle_compat(os.path.join(DIR_DATA, btype+r'-bondpool.pkl'), f"{btype}-bondpool.pkl")

    # start = (dt.datetime.strptime(curt_period[0],'%Y-%m-%d') - relativedelta(years=1)).date()
    # end = (dt.datetime.strptime(curt_period[1],'%Y-%m-%d')).date()
    start = prange[0] - relativedelta(years=1)
    end = prange[-1]
    common = env['Def'].index
    for k in database.keys():
        if k in WindConfig.DATATYPE:
            common = common.intersection(database[k].columns)
            env[k] = database[k].loc[start:end,common].dropna(how='all',axis=1)
            common = env[k].columns
        else:
            env[k] = database[k].loc[start:end]
    return env

def loadCurvePxTS(btype,adjust=False):
    """Load curve price time series using pandas read_pickle for better compatibility"""
    file_path = os.path.join(DIR_INPUT, btype+'-cvpx.pkl')
    return _read_pickle_compat(file_path, f"{btype}-cvpx.pkl")