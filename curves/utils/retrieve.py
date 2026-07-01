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

# Add project root to Python path FIRST
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Now import modules that depend on sys.path
from data.providers.retrieve import _wsd, _wset, _wss, _edb, _wsq, _wst, _is_trading_hours
from settings.general import GeneralConfig, DateConfig
from settings.futures import FuturesConfig
from settings.fixed_income import BondConfig, IRSConfig
from settings.wind import WindConfig
from settings.paths import DIR_INPUT, DIR_DATA
from curves.utils.file import updatePKL
from utils.log_window import get_logger

logger = get_logger(__name__)

# Localized new-config convenience variables
_dates = DateConfig.get_date_mappings()
_date_strs = DateConfig.get_date_strings()

def _save_pickle(obj, path):
    with open(path, 'wb') as f:
        pickle.dump(obj, f)


def _wsq_until_nonempty(symbols, fields, *, retry_delay: float = 0.5, max_retries: int = 5):
    """Retry realtime WSQ requests until a non-empty DataFrame is returned.

    Returns the last result (possibly empty) after max_retries so callers
    can fall back to cached data instead of looping forever.
    """
    result = pd.DataFrame()
    for attempt in range(1, max_retries + 1):
        result = _wsq(symbols, fields)
        if isinstance(result, pd.DataFrame) and not result.empty:
            logger.info("WSQ succeeded on attempt %d/%d (%d symbols)", attempt, max_retries, len(result))
            return result
        logger.warning("WSQ returned empty data on attempt %d/%d — retrying...", attempt, max_retries)
        time.sleep(retry_delay)
    logger.warning("WSQ still empty after %d attempts — returning empty frame.", max_retries)
    return result
        
def filterInstrument(bond_info,btype,hist=False):
    if 'CLAUSE' in bond_info.columns:
        bond_info = bond_info[bond_info['CLAUSE'].isna()]
    bond_info = bond_info[~bond_info['FULLNAME'].str.contains('|'.join(BondConfig.EXCLUDE_KEYWORDS))]
    bond_info = bond_info[~bond_info['INTERESTTYPE'].str.contains('浮动')]
    bond_info['INTERESTFREQUENCY'] = bond_info['INTERESTFREQUENCY'].fillna(1)
    bond_info['CARRYDATE'] = [d.date() for d in bond_info['CARRYDATE']]
    bond_info['MATURITYDATE'] = [d.date() for d in bond_info['MATURITYDATE']]
    if not hist:
        # bond_info = bond_info[(bond_info['PTMYEAR']<=10)|
                             # ((bond_info['PTMYEAR']>=25.0)&(bond_info['PTMYEAR']<=30.0))]
        bond_info = bond_info[bond_info['PTMYEAR']<=30]
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

def updateInstrumentPool(btype, date_str, hist=False, on_demand=False):
    """Update instrument pool from Wind API.

    Args:
        btype: Bond type (TBond, CBond, etc.)
        date_str: Date string in YYYYMMDD format
        hist: If True, apply historical filtering
        on_demand: If True, allow non-trading hour retrieval
    """
    if on_demand:
        from data.providers.retrieve import set_allow_nontrading_retrieval
        set_allow_nontrading_retrieval(True)

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

def updateInstrumentDef(asof=None, on_demand=False):
    """Update instrument definitions for all bond types and futures.

    Args:
        asof: Optional date (datetime.date or YYYY-MM-DD/YYYYMMDD str).
              Defaults to previous working day derived from today.
        on_demand: If True, allow non-trading hour retrieval and suppress Wind API warnings.
    """
    # For on-demand retrieval, allow Wind API access outside trading hours
    if on_demand:
        from data.providers.retrieve import set_allow_nontrading_retrieval
        set_allow_nontrading_retrieval(True)
        os.environ['FI_SUPPRESS_WIND_WARNINGS'] = '1'

    print("Updating instrument definitions...")
    obond = list(BondConfig.INCLUDE_FILTERS.keys())

    if asof is not None:
        from datetime import datetime as _dt
        if isinstance(asof, str):
            # Handle both YYYY-MM-DD and YYYYMMDD formats
            try:
                asof = _dt.strptime(asof, '%Y-%m-%d').date()
            except ValueError:
                asof = _dt.strptime(asof, '%Y%m%d').date()
        dates = DateConfig.get_date_mappings(asof=asof)
        dp = dates['dp']
        dps = dp.strftime('%Y%m%d')
    else:
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
                interval = get_mtime_date(def_file) - dp.date()

                if on_demand or interval.days == 7: # always update on demand, otherwise every 7 days
                    pool = updateInstrumentPool(btype, dps, on_demand=on_demand)
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
            print(f"✅ Updated {btype}-InstrumentInfo.pkl")
        except Exception as ex:
            if on_demand:
                print(f"⚠️ Failed to update {btype}-InstrumentInfo.pkl (Wind API: {ex})")
            else:
                print('Check if Wind data quota exceeded. ',ex,btype)

def retrieveInstrumentDefinitions():
    """Auto-registered retriever wrapper so 'update-data' also refreshes
    *-InstrumentInfo.pkl (engine/data_updatdae.py only discovers functions
    named 'retrieve*'; updateInstrumentDef itself does not match)."""
    updateInstrumentDef(on_demand=True)

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
    return ts

def _extract_contract_close(contract_df, close_df):
    """Extract close prices for contracts based on their codes.

    For each date and ticker, looks up the contract code and retrieves its close price.

    Parameters
    ----------
    contract_df : pd.DataFrame
        DataFrame with contract codes (indexed by date, columns are tickers)
    close_df : pd.DataFrame
        DataFrame with close prices for all contracts (indexed by date, columns are contract codes)

    Returns
    -------
    pd.DataFrame
        DataFrame with close prices aligned to contract_df structure
    """
    # Create a new dataframe with same structure but float dtype
    contract_cls = pd.DataFrame(index=contract_df.index, columns=contract_df.columns, dtype='float64')

    for col in contract_cls.columns:
        for date_idx in contract_cls.index:
            code = contract_df.loc[date_idx, col]
            if isinstance(code, str) and code in close_df.columns:
                try:
                    contract_cls.loc[date_idx, col] = close_df.loc[date_idx, code]
                except (KeyError, IndexError):
                    contract_cls.loc[date_idx, col] = np.nan
            else:
                contract_cls.loc[date_idx, col] = np.nan

    return contract_cls


def _get_next_season_contract(contract_df, dps, ds):
    """Transform contract codes to next quarterly season for date range [dps, ds].

    Converts contract codes like T2603.CFE -> T2606.CFE, handling year rollover.
    Quarterly cycle: 03 (Mar) -> 06 (Jun) -> 09 (Sep) -> 12 (Dec) -> 03 (next year).

    Parameters
    ----------
    contract_df : pd.DataFrame
        DataFrame with contract codes (indexed by date)
    dps : str
        Start date in YYYYMMDD format
    ds : str
        End date in YYYYMMDD format
    """
    start_date = pd.to_datetime(dps, format='%Y%m%d').date()
    end_date = pd.to_datetime(ds, format='%Y%m%d').date()

    # Filter to date range
    mask = (contract_df.index >= start_date) & (contract_df.index <= end_date)
    contract1_df = contract_df.loc[mask].copy()

    def transform_contract(code):
        if pd.isna(code) or not isinstance(code, str):
            return code
        try:
            # Extract ticker prefix and date from code (e.g., "T2603.CFE" -> "T", "26", "03", ".CFE")
            parts = code.split('.')
            if len(parts) != 2:
                return code

            base_code = parts[0]
            suffix = '.' + parts[1]

            # Extract year and month from base_code (e.g., "T2603" -> "T", "26", "03")
            if len(base_code) < 4:
                return code

            ticker = base_code[:-4]
            year_str = base_code[-4:-2]
            month_str = base_code[-2:]

            year = int(year_str)
            month = int(month_str)

            # Advance by 3 months (quarterly cycle)
            month += 3
            if month > 12:
                month -= 12
                year += 1

            # Format as YYMM and reconstruct code
            new_code = ticker + f"{year:02d}{month:02d}" + suffix
            return new_code
        except (ValueError, IndexError):
            return code

    for col in contract1_df.columns:
        contract1_df[col] = contract1_df[col].apply(transform_contract)

    return contract1_df


def fetchFuturesDatabaseWindow(prange, on_demand=False):
    """Fetch the bond-futures analytics window from Wind without persisting.

    Returns a dict with per-date, per-ctype (TS/TF/T/TL.CFE) frames:
    ``contract``/``contract1``/``contract2`` (codes), ``close`` (all contract
    closes), ``contract_cls``/``contract1_cls``/``contract2_cls`` (front/next/
    next-next close), ``irr`` (tbf_irr02 %), ``ytm`` (tbf_fytm02 %) and
    ``ctd`` (CTD bond code).  Used by both the full-history backfill
    (:func:`retrieveFuturesDatabaseTS`) and the daily incremental analytics
    update in ``FuturesAnalyticsGenerator``.
    """
    d = prange[-1]
    ds = d.strftime("%Y%m%d")
    dp = prange[0] - relativedelta(months=1)
    dps = dp.strftime("%Y%m%d")
    flist = ["TS.CFE", "TF.CFE", "T.CFE", "TL.CFE"]
    database_update = {}
    database_update['contract'] = _wsd(flist, "trade_hiscode", dps, ds, "", on_demand=on_demand)
    database_update['contract1'] = _get_next_season_contract(database_update['contract'], dps, ds)
    database_update['contract2'] = _get_next_season_contract(database_update['contract1'], dps, ds)
    tlist = list(database_update['contract'].iloc[0])+list(database_update['contract1'].iloc[0])+list(database_update['contract2'].iloc[0])
    database_update['close'] = pd.DataFrame(columns=tlist)
    database_update['close'][tlist] = _wsd(tlist, "close", dps, ds, "futurePriceType=1;bondTradingVenue=1;", on_demand=on_demand)
    database_update['contract_cls'] = _extract_contract_close(database_update['contract'], database_update['close'])
    database_update['contract1_cls'] = _extract_contract_close(database_update['contract1'], database_update['close'])
    database_update['contract2_cls'] = _extract_contract_close(database_update['contract2'], database_update['close'])
    database_update['irr'] = _wsd(flist, "tbf_irr02", dps, ds, "futurePriceType=1;bondTradingVenue=1;", on_demand=on_demand)
    database_update['ytm'] = _wsd(flist, "tbf_fytm02", dps, ds, "futurePriceType=1;bondTradingVenue=1;", on_demand=on_demand)
    database_update['ctd'] = _wsd(flist, "tbf_ctd02", dps, ds, "futurePriceType=1;bondTradingVenue=1;", on_demand=on_demand)

    # Fetch tbf_fytm02 for each specific next-quarter contract code so we can
    # compute the FYTM spread (fytm - next_fytm) as the TermBasis series.
    # contract1 cells hold the actual contract codes (e.g. T2609.CFE); we
    # collect the unique codes and call _wsd once, then align per (date, ctype).
    c1_df = database_update['contract1']
    next_codes = [c for c in pd.unique(c1_df.values.ravel()) if isinstance(c, str) and c]
    if next_codes:
        next_ytm_wide = _wsd(next_codes, "tbf_fytm02", dps, ds,
                             "futurePriceType=1;bondTradingVenue=1;", on_demand=on_demand)
        database_update['next_ytm'] = _extract_contract_close(c1_df, next_ytm_wide)
    else:
        database_update['next_ytm'] = pd.DataFrame(index=c1_df.index, columns=c1_df.columns, dtype='float64')

    return database_update


def retrieveFuturesDatabaseTS(prange, on_demand=False):
    """Fetch full-history bond-futures analytics and persist to futures-db.pkl.

    Backfill-only path (run-center).  Daily EOD does an incremental append into
    ``futures-analytics.pkl`` instead — see ``FuturesAnalyticsGenerator``.
    """
    database_update = fetchFuturesDatabaseWindow(prange, on_demand=on_demand)
    database_update = updatePKL(database_update, os.path.join(DIR_DATA, 'futures-db.pkl'))

def retrieveFuturesTS(backfill: bool = False):
    """Update bond futures time series in futures-px.pkl.

    Parameters
    ----------
    backfill : bool
        When True, fetch up to 1 year of history for basis/netbasis/irr/ctd
        (Wind computes these correctly for each historically-correct NQ1/NQ2/NQ3
        contract via contractType=, so CF and CTD are accurate for all dates).
        Use False (default) for daily incremental updates.
    on_demand : bool
        When True, allow retrieval outside trading hours by bypassing time checks.
    """
    print("Updating bond futures time series...")
    with open(os.path.join(DIR_INPUT, 'futures-InstrumentInfo.pkl'), 'rb') as file:
        futures = pickle.load(file)

    dps = _date_strs['dp']
    # Close / OI: always fetch recent window (specific contract codes, e.g. T2606)
    starts_recent = _date_strs['d7d']
    # Basis/netbasis/IRR/CTD: contractType= makes Wind roll automatically, so we
    # can fetch longer history and get correct values for historical contracts.
    if backfill:
        starts_basis = _date_strs.get('d1y', _date_strs['d7d'])
        print("  backfill mode: fetching up to 1 year of basis/IRR/CTD history")
    else:
        starts_basis = _date_strs['d7d']

    futures_ts = {'close': {}, 'basis': {}, 'netbasis': {}, 'position': {}, 'irr': {}, 'ctd': {}}
    for b in futures['Bucket'].keys():
        bond_list = []
        for t in futures['Bucket'][b]:
            bond_list.extend(list(futures['DeliveryPool'][t].index))
        # Current contract close/OI (T2606 etc.) — short window only
        futures_ts['close'][b]    = _wsd(futures['Bucket'][b], "close", starts_recent, dps)
        futures_ts['position'][b] = _wsd(futures['Bucket'][b], "oi",    starts_recent, dps)
        # Wind-computed basis fields use contractType= which handles historical roll
        futures_ts['basis'][b]    = _wsd(bond_list, "tbf_basis",   starts_basis, dps, "contractType=" + b)
        futures_ts['netbasis'][b] = _wsd(bond_list, "tbf_netbasis", starts_basis, dps, "contractType=" + b)
        futures_ts['irr'][b]      = _wsd(bond_list, "tbf_IRR",     starts_basis, dps, "contractType=" + b)
    futures_ts = updatePKL(futures_ts, os.path.join(DIR_INPUT, 'futures-px.pkl'))
    

_WINDRT_CACHE = os.path.join(DIR_INPUT, 'windrt.pkl')


def _save_windrt_cache(btype: str, bond_rt) -> None:
    """Persist the processed RT result to windrt.pkl under key btype."""
    try:
        cache = {}
        if os.path.exists(_WINDRT_CACHE):
            with open(_WINDRT_CACHE, 'rb') as f:
                cache = pickle.load(f)
        cache[btype] = bond_rt
        with open(_WINDRT_CACHE, 'wb') as f:
            pickle.dump(cache, f)
    except Exception as e:
        print(f"[Cache] Failed to save windrt.pkl: {e}")


def _load_windrt_cache(btype: str):
    """Load cached RT result for btype from windrt.pkl. Returns None if unavailable."""
    try:
        with open(_WINDRT_CACHE, 'rb') as f:
            cache = pickle.load(f)
        return cache.get(btype)
    except Exception:
        return None


def _normalize_bondrt_frame(env, bond_rt, btype: str) -> pd.DataFrame:
    """Return a bond RT frame with stable bid/offer yield columns.

    Wind/cache payloads can arrive with older English column names, a single-sided
    quote, or no RT columns at all. Downstream refreshers expect both `买价收益率`
    and `卖价收益率`, so synthesize them here using aliases and CNBD fallback.
    """
    fallback = env['Def']['估价收益率:%(中债)']

    if not isinstance(bond_rt, pd.DataFrame):
        bond_rt = pd.DataFrame(index=fallback.index)
    else:
        bond_rt = bond_rt.copy()

    if bond_rt.index.name != fallback.index.name:
        bond_rt.index.name = fallback.index.name

    aliases = {
        '买价收益率': ['买价收益率', 'Bid', 'RT_BID1', 'RT_BID_PRICE1YTM'],
        '卖价收益率': ['卖价收益率', 'Ofr', 'RT_ASK1', 'RT_ASK_PRICE1YTM'],
        '成交收益率': ['成交收益率', 'RT_LAST_YTM'],
    }

    normalized = pd.DataFrame(index=fallback.index)
    for target, candidates in aliases.items():
        series = None
        for candidate in candidates:
            if candidate in bond_rt.columns:
                extracted = bond_rt[candidate]
                if isinstance(extracted, pd.DataFrame):
                    extracted = extracted.iloc[:, 0]
                series = pd.to_numeric(extracted, errors='coerce').reindex(fallback.index)
                break
        if series is not None:
            normalized[target] = series

    if '买价收益率' not in normalized.columns and '卖价收益率' in normalized.columns:
        normalized['买价收益率'] = normalized['卖价收益率']
    if '卖价收益率' not in normalized.columns and '买价收益率' in normalized.columns:
        normalized['卖价收益率'] = normalized['买价收益率']

    for col in ['买价收益率', '卖价收益率']:
        if col not in normalized.columns:
            normalized[col] = fallback
        else:
            normalized[col] = normalized[col].fillna(fallback)

    if '成交收益率' not in normalized.columns:
        normalized['成交收益率'] = (normalized['买价收益率'] + normalized['卖价收益率']) / 2
    else:
        normalized['成交收益率'] = normalized['成交收益率'].fillna(
            (normalized['买价收益率'] + normalized['卖价收益率']) / 2
        )

    logger.info(
        "BondRT normalized for %s with columns: %s",
        btype,
        ', '.join(normalized.columns.astype(str))
    )
    return normalized


def _rename_rt_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Rename Wind RT columns to stable internal names.

    Wind live calls and offline placeholder frames can differ only by case
    (`RT_BID_PRICE1YTM` vs `rt_bid_price1ytm`). Support both so callers never
    crash on a simple field-name mismatch.
    """
    col_map = BondConfig.get_column_mapping()
    rename_map = {}
    for column in frame.columns:
        mapped = col_map.get(column)
        if mapped is None and isinstance(column, str):
            mapped = col_map.get(column.upper())
        rename_map[column] = mapped or column
    return frame.rename(columns=rename_map)


def _normalize_swaprt_frame(swap_rt) -> pd.DataFrame:
    """Return a swap RT frame with stable bid/offer/trade yield columns."""
    expected_index = pd.Index(list(dict.fromkeys(IRSConfig.FIXING_LIST + IRSConfig.IRS_LIST)), dtype=object)

    if not isinstance(swap_rt, pd.DataFrame):
        swap_rt = pd.DataFrame(index=expected_index)
    else:
        swap_rt = swap_rt.copy()

    swap_rt = _rename_rt_columns(swap_rt)
    swap_rt = swap_rt.reindex(expected_index)

    aliases = {
        '买价收益率': ['买价收益率', 'Bid'],
        '卖价收益率': ['卖价收益率', 'Ofr'],
        '成交收益率': ['成交收益率'],
    }

    normalized = pd.DataFrame(index=expected_index)
    for target, candidates in aliases.items():
        for candidate in candidates:
            if candidate in swap_rt.columns:
                normalized[target] = pd.to_numeric(swap_rt[candidate], errors='coerce').reindex(expected_index)
                break

    if '成交收益率' not in normalized.columns:
        normalized['成交收益率'] = np.nan
    if '买价收益率' not in normalized.columns and '成交收益率' in normalized.columns:
        normalized['买价收益率'] = normalized['成交收益率']
    if '卖价收益率' not in normalized.columns and '成交收益率' in normalized.columns:
        normalized['卖价收益率'] = normalized['成交收益率']

    if '买价收益率' not in normalized.columns:
        normalized['买价收益率'] = np.nan
    if '卖价收益率' not in normalized.columns:
        normalized['卖价收益率'] = np.nan

    normalized['买价收益率'] = normalized['买价收益率'].fillna(normalized['卖价收益率'])
    normalized['卖价收益率'] = normalized['卖价收益率'].fillna(normalized['买价收益率'])

    mid = (normalized['买价收益率'] + normalized['卖价收益率']) / 2
    normalized['成交收益率'] = normalized['成交收益率'].fillna(mid)
    normalized['买价收益率'] = normalized['买价收益率'].fillna(normalized['成交收益率'])
    normalized['卖价收益率'] = normalized['卖价收益率'].fillna(normalized['成交收益率'])

    logger.info(
        "SwapRT normalized with columns: %s",
        ', '.join(normalized.columns.astype(str))
    )
    return normalized


def retrieveWindRT(btype):
    logger.info("Fetching Wind real-time data for %s...", btype)
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
        bond_rt = _rename_rt_columns(bond_rt)
        bond_rt = bond_rt.replace(0,np.nan)
    _save_windrt_cache(btype, bond_rt)
    n = len(bond_rt) if isinstance(bond_rt, pd.DataFrame) else sum(len(v) for v in bond_rt.values())
    logger.info("Wind real-time data fetched for %s: %d records", btype, n)
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
        online = _is_trading_hours()
        if online:
            bond_rt = retrieveWindRT(btype)
            if bond_rt is not None and not bond_rt.empty:
                env['BondRT'] = _normalize_bondrt_frame(env, bond_rt, btype)
                logger.info("BondRT source: Wind live data (%d bonds)", len(bond_rt))
            else:
                logger.warning("Wind returned empty data for %s — falling back to cache.", btype)
                cached = _load_windrt_cache(btype)
                if cached is not None:
                    env['BondRT'] = _normalize_bondrt_frame(env, cached, btype)
                    logger.info("BondRT source: cache (windrt.pkl) for %s", btype)
                else:
                    cnbd = env['Def']['估价收益率:%(中债)']
                    logger.warning("No cache for %s — using CNBD yields as fallback.", btype)
                    env['BondRT'] = _normalize_bondrt_frame(
                        env,
                        pd.DataFrame({'买价收益率': cnbd, '卖价收益率': cnbd}),
                        btype,
                    )
        else:
            logger.info("Outside trading hours — loading windrt.pkl for %s.", btype)
            cached = _load_windrt_cache(btype)
            if cached is not None:
                env['BondRT'] = _normalize_bondrt_frame(env, cached, btype)
                logger.info("BondRT source: cache (windrt.pkl) for %s", btype)
            else:
                cnbd = env['Def']['估价收益率:%(中债)']
                logger.warning("No cache for %s — using CNBD yields as fallback.", btype)
                env['BondRT'] = _normalize_bondrt_frame(
                    env,
                    pd.DataFrame({'买价收益率': cnbd, '卖价收益率': cnbd}),
                    btype,
                )

        # Use CNBD price as fallback for NaN values or values very close to 0
        fallback_count = 0
        for k in env['BondRT'].index:
            for p in ['买价收益率','卖价收益率']:
                px = env['BondRT'].loc[k,p]
                px_cnbd = env['Def'].loc[k,'估价收益率:%(中债)']
                if np.isnan(px) or (px < 1e-4) or (px > 10) :
                    env['BondRT'].loc[k,p] = px_cnbd
                    fallback_count += 1

        if fallback_count:
            logger.info("CNBD fallback applied to %d price entries for %s.", fallback_count, btype)

        if online:
            env['SwapRT'] = _normalize_swaprt_frame(retrieveWindRT('IRS'))
            if btype in ['TBond','CBond']:
                fixings = ['FR001.IR','FR007.IR','SHIBOR3M.IR']
                available_fixings = [ticker for ticker in fixings if ticker in env['SwapRT'].index]
                if available_fixings and '成交收益率' in env['SwapRT'].columns:
                    fs = env['SwapRT'].loc[available_fixings, '成交收益率']
                    for c in ['买价收益率', '卖价收益率']:
                        env['SwapRT'].loc[available_fixings, c] = fs.values
        else:
            cached_irs = _load_windrt_cache('IRS')
            if cached_irs is not None:
                env['SwapRT'] = _normalize_swaprt_frame(cached_irs)
                logger.info("SwapRT source: cache (windrt.pkl)")
            else:
                logger.warning("No IRS cache found — SwapRT will be empty.")
                env['SwapRT'] = _normalize_swaprt_frame(pd.DataFrame())
    return env


        