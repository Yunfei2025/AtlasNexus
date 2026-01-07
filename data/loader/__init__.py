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
from tools.config import DIR_INPUT, BondConfig, WindConfig
import tools.calcn as cd
from dateutil.relativedelta import relativedelta     

def is_pickle_corrupted(file_path):
    """Check if a pickle file is corrupted by attempting to load it"""
    if not os.path.exists(file_path):
        return False
    
    try:
        # First check file size - if it's 0 bytes, it's definitely corrupted
        if os.path.getsize(file_path) == 0:
            return True
            
        # Try to load with pandas first (more robust for older formats)
        pd.read_pickle(file_path)
        return False
    except Exception:
        try:
            # Fallback to standard pickle
            with open(file_path, 'rb') as f:
                pickle.load(f)
            return False
        except Exception as e:
            # Check for specific corruption indicators
            error_str = str(e).lower()
            corruption_indicators = [
                'invalid load key',
                'unexpected end of file',
                'pickle data was truncated',
                'ran out of input',
                '\x00'
            ]
            return any(indicator in error_str for indicator in corruption_indicators)


def loadWorkday(start,end,update=False):
    if update:
        cal_dict = {}
        for y in range(2016,2040):
            cal_dict[y] = cd.getCalendar(y)  
        Cal = pd.concat(cal_dict,axis=0).droplevel(0)
        Cal.index = [ dt.date(d.year,d.month,d.day) for d in Cal.index ]
        with open(os.path.join(DIR_INPUT,'Calendar.pkl'), 'wb') as file:
            pickle.dump(Cal, file, protocol=pickle.HIGHEST_PROTOCOL)
    else:
        Cal = safe_load_pickle(os.path.join(DIR_INPUT,'Calendar.pkl'))
        if Cal is None:
            raise FileNotFoundError("Calendar.pkl is missing or corrupted and update=False")
    wd = Cal[Cal==False].loc[start:end].index
    return wd

def loadCNBDTS():
    # Direct load to avoid unnecessary read-write in updatePKL when input dict is empty
    file_path = os.path.join(DIR_INPUT, 'database-px.pkl')
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
        env['Def'] = pd.read_pickle(os.path.join(DIR_INPUT,btype+r'-bondpool.pkl'))
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

import os 
import pandas as pd
from tools.config import DIR_INPUT, DIR_DATA
import tools.loading as ld
import pickle

def loadData(btype):
    folders = []
    for f in os.listdir(os.path.join(DIR_DATA)):
        if f.startswith('20'):
            folders.append(f)
    
    #% concatenate TS files
    dtype = ['Close','Volume','CBClean','CBDirty']
    fmap = {}
    for d in dtype:
        for f in folders:
            fname = btype+'-'+d+'.xlsx'        
            fmap[d] = fname   
    fmap['ftp'] = 'CBond-CBCurve.xlsx'
    fmap['repo'] = 'Repo.xlsx'
    database = {}
    for k in fmap.keys(): 
        try:
            dtemp = {}  
            v = fmap[k]     
            if k in ['ftp','repo']:
                col = '指标名称'
            else:
                col = 'Date'
            for f in folders:
                filei = os.path.join(DIR_DATA,f,v)
                dtemp[f] = pd.read_excel(filei,sheet_name=0,index_col=col,skiprows=1)
            dtemp = pd.concat(dtemp,axis=0)
            dtemp = dtemp.droplevel(0)
            dtemp = dtemp.sort_index()
            database[k] = dtemp
        except Exception as ex:
            print(ex,k)
    return database

def loadBondDataPKL(btype,prange,update=False):
    try:
        bond_info = pd.read_pickle(os.path.join(DIR_INPUT,btype+r'-bondpool.pkl'))
    except Exception as e:
        print(f"Warning: Error loading {btype}-bondpool.pkl with pd.read_pickle: {e}")
        print("Falling back to pickle.load...")
        with open(os.path.join(DIR_INPUT,btype+r'-bondpool.pkl'), 'rb') as file:
            bond_info = pickle.load(file)
    if update:
        import tools.retrieve as rd
        if btype in ['TBond','CBond']:
            database_bond = rd.retrieveWindBondTS(list(bond_info.index),prange)
        else:
            database_bond = rd.retrieveWindBondTS(list(bond_info.index),prange,close=True)
        database_bond = ld.updatePKL(database_bond,os.path.join(DIR_DATA,btype+'-px.pkl'))
    else:
        try:
            database_bond = pd.read_pickle(os.path.join(DIR_DATA,btype+'-px.pkl'))
        except Exception as e:
            print(f"Warning: Error loading {btype}-px.pkl with pd.read_pickle: {e}")
            print("Falling back to pickle.load...")
            with open(os.path.join(DIR_DATA,btype+'-px.pkl'), 'rb') as file:
                database_bond = pickle.load(file)    
    return database_bond

def loadCNBDCurvePKL(update=False):
    try:
        database_cbcv = pd.read_pickle(os.path.join(DIR_DATA,'CNDBCurve-px.pkl'))
    except Exception as e:
        print(f"Warning: Error loading CNDBCurve-px.pkl with pd.read_pickle: {e}")
        print("Falling back to pickle.load...")
        with open(os.path.join(DIR_DATA,'CNDBCurve-px.pkl'), 'rb') as file:
            database_cbcv = pickle.load(file)

    if update:
        for ctype in ['CDB','CGB']:
            import tools.retrieve as rd
            database_cbcv[ctype] = rd.retrieveWindCNBDCurveTS(ctype)
        database_cbcv = ld.updatePKL(database_cbcv,os.path.join(DIR_DATA,'CNDBCurve-px.pkl'))
    return database_cbcv

def loadIRSPKL():
    # this file has been updated daily
    try:
        cvdata = pd.read_pickle(os.path.join(DIR_INPUT,'database-px.pkl'))
        return cvdata
    except Exception as e:
        print(f"Warning: Error loading database-px.pkl with pd.read_pickle: {e}")
        print("Falling back to pickle.load...")
        with open(os.path.join(DIR_INPUT,'database-px.pkl'), 'rb') as file:
            cvdata = pickle.load(file)
        return cvdata

def loadDB(btype,prange,update):
    if update['pool']:
        import tools.retrieve as rd
        rd.retrieveWindBacktestPool(btype, prange)
    database = loadBondDataPKL(btype, prange, update['bonds'])
    database.update(loadCNBDCurvePKL(update['cbts']))
    database.update(loadIRSPKL())
    return database