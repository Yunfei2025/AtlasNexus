# -*- coding: utf-8 -*-
"""
Created on Wed Sep 24 19:52:56 2025

@author: CMBC
"""
import os
import sys
import pickle
import time
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime as dt
from dateutil.relativedelta import relativedelta 
from data.providers.retrieve import _wsd, _wset, _wss, _edb, _wsq, _wst

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from settings.general import GeneralConfig, DateConfig
from settings.futures import FuturesConfig
from settings.fixed_income import BondConfig, IRSConfig
from settings.wind import WindConfig
from settings.paths import DIR_INPUT, DIR_DATA
from curves.utils.file import updatePKL

# Localized new-config convenience variables
_dates = DateConfig.get_date_mappings()
_date_strs = DateConfig.get_date_strings()

def _save_pickle(obj, path):
    with open(path, 'wb') as f:
        pickle.dump(obj, f)


def _wsq_until_nonempty(symbols, fields, *, retry_delay: float = 0.5):
    """Retry realtime WSQ requests until a non-empty DataFrame is returned."""
    attempt = 0
    while True:
        attempt += 1
        result = _wsq(symbols, fields)
        if isinstance(result, pd.DataFrame) and not result.empty:
            return result
        print(f"WSQ returned empty data on attempt {attempt}; retrying...")
        time.sleep(retry_delay)
        
def filterInstrument(bond_info,btype,hist=False):
    if 'CLAUSE' in bond_info.columns:
        bond_info = bond_info[bond_info['CLAUSE'].isna()]
    bond_info = bond_info[~bond_info['FULLNAME'].str.contains('|'.join(BondConfig.EXCLUDE_KEYWORDS))]
    bond_info = bond_info[~bond_info['INTERESTTYPE'].str.contains('浮动')]
    bond_info['INTERESTFREQUENCY'] = bond_info['INTERESTFREQUENCY'].fillna(1)
    bond_info['CARRYDATE'] = [d.date() for d in bond_info['CARRYDATE']]
    bond_info['MATURITYDATE'] = [d.date() for d in bond_info['MATURITYDATE']]
    if not hist:
        bond_info = bond_info[(bond_info['PTMYEAR']<=10)|
                              ((bond_info['PTMYEAR']>=25.0)&(bond_info['PTMYEAR']<=30.0))]
        if btype not in ['CBond','TBond']:
            if btype in ['CP','SCP']:
                bond_info = bond_info[bond_info['PTMYEAR'] >= 1/4]
                bond_info = bond_info[bond_info['OUTSTANDINGBALANCE'] >= 10]
            else:
                bond_info = bond_info[bond_info['PTMYEAR'] >= 1]
                bond_info = bond_info[bond_info['OUTSTANDINGBALANCE'] >= 50]
        bond_info = bond_info.sort_values('PTMYEAR')
    return bond_info

def retrieveWindBacktestPool(btype, prange):
    dp = prange[0]
    dps = dp.strftime("%Y%m%d")
    d = prange[-1]
    ds = d.strftime("%Y%m%d")
    
    pool = {}
    for di in [dps,ds]:
        file_path = os.path.join(DIR_DATA, 'pool', btype + 'Pool' + di + '.pkl')
        if not (os.path.exists(file_path)):
            temp = updateInstrumentPool(btype, di, hist=True)
            if temp.shape[0] <= 2:
                print("This is a holiday, choose another day.")
                break
            else:
                file = open(file_path, 'wb')
                pickle.dump(temp, file)
                file.close()
                pool[di] = temp
        else:
            pool[di] = pd.read_pickle(file_path)

    # Filtering by start and end date
    wdinfo = WindConfig.WDINFO
    bond_info_dict = {}
    for di in [dps,ds]:
        bond_info_dict[di] = _wss(list(pool[di].index), wdinfo,"tradeDate="+di+";returnType=1;\
                           credibility=1;priceAdj=U;cycle=D")      
    bond_info = pd.concat([bond_info_dict[dps],bond_info_dict[ds]],axis=0)#.dropna(subset = ['OUTSTANDINGBALANCE'])
    
    # Drop duplicate index entries, preferring the row where OUTSTANDINGBALANCE is non-null
    if 'OUTSTANDINGBALANCE' in bond_info.columns:
        _has_val = bond_info['OUTSTANDINGBALANCE'].notna()
        # Sort to put rows with values first, then keep the first occurrence per index
        bond_info = bond_info.assign(_has_val=_has_val).sort_values('_has_val', ascending=False)
        bond_info = bond_info[~bond_info.index.duplicated(keep='first')].drop(columns=['_has_val'])
    else:
        # Fallback: if column missing, prefer keeping the last occurrence (usually latest date)
        bond_info = bond_info[~bond_info.index.duplicated(keep='last')]
    bond_info = filterInstrument(bond_info, btype, hist=True)
    col_map = BondConfig.get_column_mapping()
    bond_info.columns = [col_map[c] for c in bond_info.columns]

    _save_pickle(bond_info, os.path.join(DIR_DATA, btype + r'-bondpool.pkl'))

def retrieveWindCNBDCurveTS(ctype):
    d = dt.today()
    ds = d.strftime("%Y%m%d")
    dp = d - relativedelta(days=7)
    dps = dp.strftime("%Y%m%d")
    for data in WindConfig.DATAMAP.keys():
        if ctype == 'CDB':
            curve_id = WindConfig.CDBCVD_IDS
        elif ctype == 'CGB':
            curve_id = WindConfig.CGBCV_IDS
        else:
            curve_id = ''
        curve_ts = _edb(curve_id, dps, ds)
        curve_ts.columns = [WindConfig.CV_ID_MAP[c] for c in curve_ts.columns]
    return curve_ts

def retrieveWindBondTS(bondlist, prange, close=False):
    d = prange[-1]
    ds = d.strftime("%Y%m%d")
    dp = prange[0] - relativedelta(months=1)
    dps = dp.strftime("%Y%m%d")
    database_update = {}
    if close:
        database_update['Close'] = _wsd(bondlist, WindConfig.DATAMAP['Close'], dps, ds, "credibility=1")
    else:
        for key in WindConfig.DATAMAP.keys():
            if key == 'Close':
                database_update[key] = _wsd(bondlist, WindConfig.DATAMAP[key], dps, ds, "credibility=1")
            else:
                database_update[key] = _wsd(bondlist, WindConfig.DATAMAP[key], dps, ds)
        database_update['Volume'] = database_update['Volume'].ffill()        
    return database_update

def updateInstrumentPool(btype,date_str,hist=False):
    try:
        pool = _wset("sectorconstituent","date="+date_str+";sectorid="+BondConfig.SECTOR_MAP[btype])
        # Filtering by name and dates
        # pool = pool[~pool['sec_name'].str.contains('|'.join(exclude))]
        if btype not in ['CBond','TBond']:
            pool = pool[pool['sec_name'].str.contains('|'.join(BondConfig.INCLUDE_FILTERS[btype]))]
        bond_date = _wss(list(pool['wind_code']), "carrydate,maturitydate", "tradeDate="+_date_strs['dp'])
        if hist:
            start_limit = dt.strptime(date_str,"%Y%m%d") - relativedelta(years=BondConfig.TBOND_POOL_START)
            pool = bond_date[(bond_date['CARRYDATE'] > start_limit)]
        else:
            if btype in ['CBond','TBond']:
                start_limit = _dates['dp'] - relativedelta(years=BondConfig.TBOND_POOL_START)
            else:
                start_limit = _dates['dp'] - relativedelta(years=BondConfig.OBOND_POOL_START)
            end_limit = _dates['dp']
            pool = bond_date[(bond_date['CARRYDATE'] > start_limit)\
                                 &(bond_date['MATURITYDATE'] > end_limit)]
    except Exception as ex:
        print('Check if Wind data quota exceeded. ',ex,btype)
    return pool

def updateInstrumentDef():
    print("Updating instrument definition...")
    obond = list(BondConfig.INCLUDE_FILTERS.keys())
    dp = _dates['dp']
    dps = _date_strs['dp']
    for btype in ['TBond', 'CBond', 'IRS', 'futures']+obond:
        try:
            if btype == 'IRS':
                irs_curve = _wsd(IRSConfig.IRS_LIST, "close", dps, dps)
                # irs_curve.index = [irs_idmap[c] for c in irs_curve.index]
                fixing = _wss(IRSConfig.FIXING_LIST, "close", "tradeDate="+dps+";priceAdj=U;cycle=D")
                bond_info = pd.concat([fixing,irs_curve],axis=0)
            elif btype == 'futures':
                bond_info = {'Bucket':{},'DeliveryPool':{}}
                for t in FuturesConfig.get_ticker_list():
                    bond_info['DeliveryPool'][t] = _wset(
                        "deliverablebondlist",
                        "windcode=" + t + ";date=" + dps + ";flag=interbank;pricetype=close;field=code,term,rate,factor,basegap"
                    )
                    bond_info['DeliveryPool'][t] = bond_info['DeliveryPool'][t].set_index('code')
                _tickers = FuturesConfig.get_ticker_list()
                bond_info['Bucket'] = {'NQ1': _tickers[:4], 'NQ2': _tickers[4:8], 'NQ3': _tickers[8:12]}
                bond_info['Def'] = _wss(_tickers, "lasttrade_date,close,tbf_ctd02,tbf_irr02,tbf_fytm02", 
                                        "futurePriceType=1;bondTradingVenue=1;tradeDate="+dps)
            else:
                from curves.utils.generator_utils import get_mtime_date
                def_file = DIR_INPUT / (btype + "-InstrumentInfo.pkl")
                interval = dp.date() - get_mtime_date(def_file)

                if interval.days == 5: # update the pool every 5 days
                    pool = updateInstrumentPool(btype, dps)
                    bonds = pool.index
                else:
                    with open(def_file, 'rb') as filed:
                        bond_info = pickle.load(filed)
                    bonds = bond_info.index
                # Filtering by start and end date
                wdinfo = WindConfig.WDINFO
                bond_info = _wss(list(bonds), wdinfo, "tradeDate="+dps+";returnType=1;credibility=1;priceAdj=U;cycle=D")
                Nb = bond_info['YIELD_CNBD'].dropna().shape[0]
                if Nb == 0:
                    bond_info = _wss(list(bonds), wdinfo, "tradeDate="+dps+";returnType=1;credibility=1;priceAdj=U;cycle=D")
                bond_info = filterInstrument(bond_info,btype)
                file_str = os.path.join(DIR_INPUT, btype + '-bondlist.xlsx')
                with pd.ExcelWriter(file_str) as writer:
                    bond_info['PTMYEAR'].to_excel(writer)
                col_map = BondConfig.get_column_mapping()
                bond_info.columns = [col_map[c] for c in bond_info.columns]
            _save_pickle(bond_info, os.path.join(DIR_INPUT, btype + '-InstrumentInfo.pkl'))
        except Exception as ex:
            print('Check if Wind data quota exceeded. ',ex,btype)
            
def retrieveCNBDTS():
    print("Updating irs and china bond time series...")
    ds = _date_strs['d']
    if GeneralConfig.DSHIFT == 1:
        starts = _date_strs['d7d']
    else:
        starts = _date_strs['d1m']
    ts = {}
    irs_curve = _wsd(IRSConfig.IRS_LIST, "close", starts, ds)
    fixing = _wsd(IRSConfig.FIXING_LIST, "close", starts, ds)
    ts['IRS'] = pd.concat([fixing,irs_curve],axis=1).sort_index()#.dropna()

    for k in WindConfig.KTID.keys():
        tlist = ','.join(WindConfig.KTID[k].keys())
        edb_ts = _edb(tlist, starts, ds)
        edb_ts.columns = [WindConfig.KTID[k][c] for c in edb_ts.columns]
        ts[k] = edb_ts
    file_path = os.path.join(DIR_INPUT, 'database-px.pkl')
    ts = updatePKL(ts, file_path)



def retrieveFuturesTS():
    print("Updating bond futures time series...")
    with open(os.path.join(DIR_INPUT, 'futures-InstrumentInfo.pkl'), 'rb') as file:
        futures = pickle.load(file)
    starts = _date_strs['d7d']
    dps = _date_strs['dp']
    futures_ts = {'close': {}, 'basis': {}, 'netbasis': {},'position': {}, 'irr': {},'ctd':{}}
    for b in futures['Bucket'].keys():
        bond_list = []
        for t in futures['Bucket'][b]:
            bond_list.extend(list(futures['DeliveryPool'][t].index))
        futures_ts['close'][b] = _wsd(futures['Bucket'][b], "close", starts, dps)
        futures_ts['position'][b] = _wsd(futures['Bucket'][b], "oi", starts, dps)
        futures_ts['basis'][b] = _wsd(bond_list, "tbf_basis", starts, dps, "contractType=" + b)
        futures_ts['netbasis'][b] = _wsd(bond_list, "tbf_netbasis", starts, dps, "contractType=" + b)
        futures_ts['irr'][b] = _wsd(bond_list, "tbf_IRR", starts, dps, "contractType=" + b)
        futures_ts['ctd'][b] = _wsd(futures['Bucket'][b], "tbf_CTD2", starts, dps, "exchangeType=NIB;bondPriceType=1")
    futures_ts = updatePKL(futures_ts, os.path.join(DIR_INPUT, 'futures-px.pkl'))
    
def retrieveWindRT(btype):
    with open(os.path.join(DIR_INPUT,btype+'-InstrumentInfo.pkl'), 'rb') as file:
        bond_info = pickle.load(file)
    if btype == 'IRS':
        bond_rt = _wsq_until_nonempty(list(bond_info.index), "rt_bid1,rt_ask1,rt_last_ytm")
    elif btype == 'futures':
        bond_rt = {}
        bond_rt['futures'] = _wsq_until_nonempty(list(FuturesConfig.get_ticker_list()), "rt_bid1,rt_ask1,rt_last")
        with open(os.path.join(DIR_INPUT, btype + '-InstrumentInfo.pkl'), 'rb') as file:
            futures_dp = pickle.load(file)['DeliveryPool']
        bond_list = []
        for t in futures_dp.keys():
            bond_list.extend(list(futures_dp[t].index))
        bond_list = list(set(bond_list))
        bond_rt['bonds'] = _wsq_until_nonempty(bond_list, "rt_ask1,rt_bid1,rt_latest")
    else:
        bond_rt = _wsq_until_nonempty(list(bond_info.index), "rt_bid_price1ytm,rt_ask_price1ytm")

    if btype != 'futures':
        assert isinstance(bond_rt, pd.DataFrame)
        col_map_rt = BondConfig.get_column_mapping()
        bond_rt.columns = [ col_map_rt[c] for c in bond_rt.columns]
        bond_rt = bond_rt.replace(0,np.nan)
    return bond_rt

def retrieveEnvRT(env,btype):
    if btype == 'futures':
        bond_rt = retrieveWindRT('futures')
        env['Def'] = pd.concat([env['Def'],bond_rt['futures']],axis=1)
        for f in env['DeliveryPool'].keys():
            bonds = env['DeliveryPool'][f].index
            cols = bond_rt['bonds'].columns
            env['DeliveryPool'][f].loc[bonds,cols] = bond_rt['bonds'].loc[bonds]
    else:
        env['BondRT'] = retrieveWindRT(btype)
        # Use CNBD price as fallback for NaN values or values very close to 0
        fallback_count = 0
        for k in env['BondRT'].index:
            for p in ['买价收益率','卖价收益率']:
                px = env['BondRT'].loc[k,p]
                px_cnbd = env['Def'].loc[k,'估价收益率:%(中债)']
                if np.isnan(px) or (px < 1e-4) or (px > 10) :
                    env['BondRT'].loc[k,p] = px_cnbd
                    fallback_count += 1

        env['SwapRT'] = retrieveWindRT('IRS')
        if btype in ['TBond','CBond']:
            fixings = ['FR001.IR','FR007.IR','SHIBOR3M.IR']
            for c in ['买价收益率','卖价收益率']:
                fs = env['SwapRT'].loc[fixings,'成交收益率']
                env['SwapRT'].loc[fixings,c]=fs.values
    return env


        