# -*- coding: utf-8 -*-
"""
Created on Wed Jan 11 10:42:19 2023

@author: 马云飞
"""
import os
import numpy as np
import pandas as pd
import pickle
import datetime as dt
from settings.paths import DIR_INPUT, DIR_DATA
from settings.fixed_income import BondConfig
from settings.wind import WindConfig
from curves.utils.calendar import getCalendar
from dateutil.relativedelta import relativedelta     

def loadWorkday(start,end,update=False):
    if update:
        cal_dict = {}
        for y in range(2016,2040):
            cal_dict[y] = getCalendar(y)  
        Cal = pd.concat(cal_dict,axis=0).droplevel(0)
        Cal.index = [ dt.date(d.year,d.month,d.day) for d in Cal.index ]
        with open(os.path.join(DIR_INPUT,'Calendar.pkl'), 'wb') as file:
            pickle.dump(Cal, file, protocol=pickle.HIGHEST_PROTOCOL)
    else:
        Cal = pd.read_pickle(os.path.join(DIR_INPUT,'Calendar.pkl'))
        if Cal is None:
            raise FileNotFoundError("Calendar.pkl is missing or corrupted and update=False")
    wd = Cal[Cal==False].loc[start:end].index
    return wd

def loadCNBDTS():
    file_path = os.path.join(DIR_INPUT, 'database-px.pkl')
    # file_path = os.path.join(DIR_DATA, 'CNDBCurve-px.pkl')
    try:
        ts = pd.read_pickle(file_path)
    except Exception as e:
        print(f"Warning: Error loading {file_path} with pd.read_pickle: {e}")
        with open(file_path, 'rb') as f:
            ts = pickle.load(f)
    env = {}
    env['SwapTS'] = ts['IRS']
    env['CGB'] = ts['CGB']
    env['SOFR'] = ts['sofr']
    env['FX'] = ts['fx']
    env['FXSwap'] = ts['fxswap']
    file_path = os.path.join(DIR_INPUT, 'TBond-cvref.pkl')
    # Direct load to avoid unnecessary rewrite
    try:
        ref = pd.read_pickle(file_path)
    except Exception as e:
        print(f"Warning: Error loading {file_path} with pd.read_pickle: {e}")
        with open(file_path, 'rb') as f:
            ref = pickle.load(f)
    env['Factors'] = ref['Factors']
    return env

def loadInstrumentDefinition(btype):
    env = {}
    try:
        if btype == 'futures':
            env = pd.read_pickle(os.path.join(DIR_INPUT, btype + '-InstrumentInfo.pkl'))
        else:
            env['Def'] = pd.read_pickle(os.path.join(DIR_INPUT, btype + '-InstrumentInfo.pkl'))
    except Exception as e:
        print(f"Warning: Error loading {btype}-InstrumentInfo.pkl with pd.read_pickle: {e}")
        print("Falling back to pickle.load...")
        with open(os.path.join(DIR_INPUT, btype + '-InstrumentInfo.pkl'), 'rb') as file:
            if btype == 'futures':
                env = pickle.load(file)
            else:
                env['Def'] = pickle.load(file)

    if btype in ['TBond','CBond']:
        env['Def']['成交量:万元'] = env['Def']['成交量'].replace(np.nan,0)/1e4
    return env

def loadRefData(btype):
    """Load reference data using pandas read_pickle for better compatibility"""
    try:
        curve_ref = pd.read_pickle(os.path.join(DIR_INPUT,btype+'-cvref.pkl'))
        return curve_ref
    except Exception as e:
        print(f"Warning: Error loading {btype}-cvref.pkl with pd.read_pickle: {e}")
        print("Falling back to pickle.load...")
        with open(os.path.join(DIR_INPUT,btype+'-cvref.pkl'), 'rb') as files:
            curve_ref = pickle.load(files)
        return curve_ref
    
def loadStatData(btype):
    env_st = {}
    try:
        spd = pd.read_pickle(os.path.join(DIR_INPUT,btype+'-spds.pkl'))
    except Exception as e:
        print(f"Warning: Error loading {btype}-spds.pkl with pd.read_pickle: {e}")
        print("Falling back to pickle.load...")
        with open(os.path.join(DIR_INPUT,btype+'-spds.pkl'), 'rb') as files:
            spd = pickle.load(files)
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
    try:
        env['Def'] = pd.read_pickle(os.path.join(DIR_DATA,btype+r'-bondpool.pkl'))
    except Exception as e:
        print(f"Warning: Error loading {btype}-bondpool.pkl with pd.read_pickle: {e}")
        print("Falling back to pickle.load...")
        with open(os.path.join(DIR_INPUT,btype+r'-bondpool.pkl'), 'rb') as filed:
            env['Def'] = pickle.load(filed)

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
    try:
        file_path = os.path.join(DIR_INPUT, btype+'-cvpx.pkl')
        return pd.read_pickle(file_path)
    except Exception as e:
        print(f"Warning: Error loading {btype}-cvpx.pkl with pd.read_pickle: {e}")
        print("Falling back to direct file path loading...")
        return pd.read_pickle(os.path.join(DIR_INPUT, btype+'-cvpx.pkl'))