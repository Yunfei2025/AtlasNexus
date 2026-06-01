"""Data loading utilities and cached datasets used by the Dash applications."""

from __future__ import annotations

import os
import pathlib
import pickle
import re
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import time
import logging

logger = logging.getLogger(__name__)

# Enable timing logs for heavy loads when set: WEB_LOG_TIMINGS=1
WEB_LOG_TIMINGS = os.environ.get("WEB_LOG_TIMINGS", "0") == "1"

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from settings.fixed_income import BondConfig
from settings.general import DateConfig
from settings.paths import DIR_INPUT
from settings.futures import FuturesConfig

# Setup the app
# Use integer milliseconds and coerce env overrides to int for consistency
t_int = int(30 * 60e3)  # unit ms, min*60*1e3 sec
GRAPH_INTERVAL = int(os.environ.get("GRAPH_INTERVAL", t_int))
t_int1 = int(120 * 60e3)  # unit ms, min*60*1e3 sec
GRAPH_INTERVAL1 = int(os.environ.get("GRAPH_INTERVAL", t_int1))

# get relative data folder
PATH = pathlib.Path(__file__).resolve().parent.parent.parent
DATA_PATH = PATH.joinpath("input").resolve()


def _normalize_legacy_repo_label(value: object) -> object:
    if isinstance(value, str):
        return re.sub(r'^Repo-', 'Repo7d-', value, flags=re.IGNORECASE)
    return value


def _normalize_legacy_repo_obj(obj: object) -> object:
    if isinstance(obj, pd.DataFrame):
        out = obj.copy()
        if out.index.dtype == object:
            out.index = out.index.map(_normalize_legacy_repo_label)
        if out.columns.dtype == object:
            out.columns = out.columns.map(_normalize_legacy_repo_label)
        return out
    if isinstance(obj, pd.Series):
        out = obj.copy()
        if out.index.dtype == object:
            out.index = out.index.map(_normalize_legacy_repo_label)
        out.name = _normalize_legacy_repo_label(out.name)
        return out
    if isinstance(obj, dict):
        return {
            _normalize_legacy_repo_label(key): _normalize_legacy_repo_obj(value)
            for key, value in obj.items()
        }
    if isinstance(obj, list):
        return [_normalize_legacy_repo_obj(value) for value in obj]
    if isinstance(obj, tuple):
        return tuple(_normalize_legacy_repo_obj(value) for value in obj)
    return obj


def _load_pickle(path: pathlib.Path):
    """Load pickle while being tolerant to legacy formats and corruption."""
    start = time.time()
    try:
        return _normalize_legacy_repo_obj(pd.read_pickle(path))
    except Exception as e:
        print(f"Warning: Error loading {path} with pd.read_pickle: {e}")
        try:
            with open(path, "rb") as f:
                return _normalize_legacy_repo_obj(pickle.load(f))
        except Exception as pickle_error:
            error_str = str(pickle_error).lower()
            corruption_indicators = ["invalid load key", "\x00", "unexpected end of file"]
            if any(indicator in error_str for indicator in corruption_indicators):
                print(f"Error: Pickle file {path} appears to be corrupted: {pickle_error}")
                print("You may need to regenerate this data file.")
                backup_path = str(path) + ".corrupted.bak"
                if not os.path.exists(backup_path):
                    import shutil

                    shutil.copy2(path, backup_path)
                    print(f"Corrupted file backed up to: {backup_path}")
            raise pickle_error
    finally:
        if WEB_LOG_TIMINGS:
            elapsed = time.time() - start
            logger.info('Loaded %s in %.3fs', path, elapsed)


def _load_pickle_optional(path: pathlib.Path):
    """Load a pickle without emitting warnings when the file is missing or stale.

    This is used for cache-style artifacts that already have a fallback builder,
    so an absent or incompatible file should be treated as a cache miss.
    """
    if not path.exists():
        return None
    try:
        return _normalize_legacy_repo_obj(pd.read_pickle(path))
    except Exception:
        try:
            with open(path, "rb") as f:
                return _normalize_legacy_repo_obj(pickle.load(f))
        except Exception:
            return None


# Toggle heavy tick loading via env (default on for backward compatibility)
LOAD_TICKS = os.environ.get("LOAD_TICKS", "1") == "1"

# Allow skipping expensive preload during development/startup by setting
# WEB_PRELOAD=0 in the environment. This speeds up Dash import/startup and
# defers data loading until callbacks request it.
WEB_PRELOAD = os.environ.get("WEB_PRELOAD", "1") == "1"

def _build_tenor_spread_fallback() -> dict:
    """Build minimal TenorSpread structure from database-px.pkl when Tenor-spds.pkl is absent."""
    try:
        db = _load_pickle(os.path.join(DIR_INPUT, 'database-px.pkl'))
        if not isinstance(db, dict):
            return {}
        cgb = db.get('CGB', {})
        cdb = db.get('CDB', {})
        if not cgb or not cdb:
            return {}

        def _s(src, k):
            v = src.get(k)
            return pd.to_numeric(v, errors='coerce') if v is not None else None

        cgb5  = _s(cgb, '中债国债到期收益率:5年')
        cgb10 = _s(cgb, '中债国债到期收益率:10年')
        cgb20 = _s(cgb, '中债国债到期收益率:20年')
        cgb30 = _s(cgb, '中债国债到期收益率:30年')
        cdb5  = _s(cdb, '中债国开债到期收益率:5年')
        cdb10 = _s(cdb, '中债国开债到期收益率:10年')
        cdb30 = _s(cdb, '中债国开债到期收益率:30年')

        instruments = {}
        if cgb5  is not None and cgb10 is not None: instruments['CGB-5s10s']  = cgb10 - cgb5
        if cgb10 is not None and cgb30 is not None: instruments['CGB-10s30s'] = cgb30 - cgb10
        if cgb10 is not None and cgb20 is not None: instruments['CGB-10s20s'] = cgb20 - cgb10
        if cdb5  is not None and cdb10 is not None: instruments['CDB-5s10s']  = cdb10 - cdb5
        if cdb5  is not None and cgb5  is not None: instruments['CDBCGB-5y']  = cdb5  - cgb5
        if cdb10 is not None and cgb10 is not None: instruments['CDBCGB-10y'] = cdb10 - cgb10

        if not instruments:
            return {}

        df_spread = pd.DataFrame(instruments).apply(pd.to_numeric, errors='coerce')
        df_cr3m = df_spread.copy() * (90.0 / 360.0)
        for col in df_cr3m.columns:
            if re.search(r'\d+s\d+', col, re.IGNORECASE):
                df_cr3m[col] = -df_cr3m[col]

        stat_cols = ['stationary', 'halflife', 'mean', 'vol', 'max', 'min']
        stat_info = pd.DataFrame(index=df_spread.columns, columns=stat_cols)
        stat_info.index.name = 'ID'
        for col in df_spread.columns:
            sp = df_spread[col].dropna()
            if len(sp) > 10:
                stat_info.loc[col, 'mean'] = float(sp.mean())
                stat_info.loc[col, 'vol']  = float(sp.std())
                stat_info.loc[col, 'max']  = float(sp.max())
                stat_info.loc[col, 'min']  = float(sp.min())
                stat_info.loc[col, 'halflife'] = np.nan
                stat_info.loc[col, 'stationary'] = 'NO'
        for c in ['halflife', 'mean', 'vol', 'max', 'min']:
            stat_info[c] = pd.to_numeric(stat_info[c], errors='coerce')

        return {'Spread': df_spread, 'CarryRoll3m': df_cr3m, 'StatInfo': stat_info}
    except Exception:
        return {}


def _build_spread_ts() -> dict:
    out = {}
    # bond types
    for btype in ["TBond", "CBond"]:
        spreads = _load_pickle(os.path.join(DIR_INPUT,f"{btype}-spds.pkl"))
        out[f"{btype}Curve"] = spreads["BondCurve"]
        out[f"{btype}Swap"] = spreads["BondSwap"]

    # IRS
    irs_data = _load_pickle(os.path.join(DIR_INPUT,"IRS-pxspds.pkl"))
    out["SwapSpread"] = irs_data

    # spread categories
    for btype in BondConfig.INCLUDE_FILTERS.keys():
        ltbspds = _load_pickle(os.path.join(DIR_INPUT,f"{btype}-spds.pkl"))
        out[f"{btype}Spread"] = ltbspds[f"{btype}Spread"]

    miscspds = _load_pickle(os.path.join(DIR_INPUT,"Misc-spds.pkl"))
    portspds = _load_pickle(os.path.join(DIR_INPUT,"Portfolio-spds.pkl"))
    out["SectorPCASpread"] = miscspds["PCASpread"]
    out["BinarySpread"] = miscspds["BinarySpread"]
    out["AssetPCASpread"] = portspds

    # Tenor spreads (CGB/CDB slope + CDBCGB cross-sector)
    try:
        tenor_path = pathlib.Path(DIR_INPUT) / 'Tenor-spds.pkl'
        tenor_spds = _load_pickle_optional(tenor_path)
        if isinstance(tenor_spds, dict) and "TenorSpread" in tenor_spds:
            out["TenorSpread"] = tenor_spds["TenorSpread"]
        else:
            raise FileNotFoundError(str(tenor_path))
    except Exception:
        fb = _build_tenor_spread_fallback()
        if fb:
            out["TenorSpread"] = fb

    # futures
    futspds = _load_pickle(os.path.join(DIR_INPUT,"futures-spds.pkl"))
    out["NetBasis"] = futspds["NetBasis"]
    out["NetIRR"] = futspds["NetIRR"]
    out["TermBasis"] = futspds["TermBasis"]
    return out

def _load_bond_refs(btypes):
    bond_ref = {}
    term_ref = {}
    factors = {}
    for btype in btypes:
        ref = _load_pickle(os.path.join(DIR_INPUT,f"{btype}-cvref.pkl"))
        bond_ref[btype] = ref["RefBond"].iloc[-1]
        term_ref[btype] = round(ref["RefTerm"].iloc[-1], 2)
        factors[btype] = ref["Factors"]
    return bond_ref, term_ref, factors

def _load_fixing_ts(spread_ts):
    try:
        fixing_ts_all = _load_pickle(os.path.join(DIR_INPUT, "database-px.pkl"))["IRS"]
        datelist = spread_ts["SwapSpread"]["Spread"].index.intersection(fixing_ts_all.index)
        fixing_ts = fixing_ts_all.loc[datelist, ["FR007.IR", "SHIBOR3M.IR"]]
        fixing_ts["S-R.IR"] = fixing_ts["SHIBOR3M.IR"] - fixing_ts["FR007.IR"]
        return fixing_ts
    except Exception as exc:
        logger.warning("Failed to load fixing_ts from database-px.pkl: %s", exc)
        return pd.DataFrame(columns=["FR007.IR", "SHIBOR3M.IR", "S-R.IR"])

def _load_fut_ticks(tickers):
    fut_tick = {}
    for ticker in tickers:
        try:
            fname = f"{ticker.split('.')[0]}.pkl"
            fpath = DATA_PATH.parent.joinpath("database", "futures", fname)
            if not fpath.exists():
                continue
            fut_tick[ticker] = _load_pickle(fpath)
        except Exception:
            continue
    return fut_tick

def _build_day_list():
    dates = DateConfig.get_date_strings()
    day_list = pd.bdate_range(dates["d2d"], dates["dp"])
    day_list = [d.date() for d in day_list]
    if len(day_list) == 0:
        day_list = [DateConfig.get_date_mappings()["dp"].date()]
    return day_list

def _build_tick_dfp(fut_tick, tickers, day_list):
    tick_dfp = {}
    try:
        for f in tickers:
            tick_p = {d: fut_tick[f][d] for d in day_list if d in fut_tick.get(f, {}).keys()}
            if not tick_p:
                continue
            tick_dfp[f] = pd.concat(tick_p).droplevel(0).sort_index()
    except Exception:
        pass
    return tick_dfp


# If WEB_PRELOAD is disabled, expose lightweight placeholders and avoid
# loading large pickles during module import. Callers may still call the
# helper functions later to load data on demand.
btypes = ["TBond", "CBond"]
if WEB_PRELOAD:
    spread_ts = _build_spread_ts()
    bond_ref, term_ref, factors = _load_bond_refs(btypes)
    fixing_ts = _load_fixing_ts(spread_ts)

    if LOAD_TICKS:
        tickers = list(FuturesConfig.get_ticker_list())
        fut_tick = _load_fut_ticks(tickers)
        day_list = _build_day_list()
        tick_dfp = _build_tick_dfp(fut_tick, tickers, day_list)
    else:
        tick_dfp = {}
        fut_tick = {}
        day_list = []
else:
    # Lightweight defaults used when preloading is turned off
    spread_ts = {}
    bond_ref = {}
    term_ref = {}
    factors = {}
    fixing_ts = pd.DataFrame()
    tick_dfp = {}
    fut_tick = {}
    day_list = []

__all__ = [
    "GRAPH_INTERVAL",
    "GRAPH_INTERVAL1",
    "DATA_PATH",
    "spread_ts",
    "bond_ref",
    "term_ref",
    "factors",
    "fixing_ts",
    "tick_dfp",
    "LOAD_TICKS",
]
