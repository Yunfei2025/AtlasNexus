# -*- coding: utf-8 -*-
"""
Created on Mon Sep 18 22:47:31 2023

@author: CMBC
"""
import pandas as pd
import pickle
import threading
import datetime as dt
import numpy as np
from typing import Optional
from settings.general import DateConfig
from settings.wind import WindConfig
from factors.config import config_manager

# Localized new-config convenience variables
_dates = DateConfig.get_date_mappings()
_date_strs = DateConfig.get_date_strings()

# ---------------------------------------------------------------------------
# Wind connectivity — single startup probe with timeout
# ---------------------------------------------------------------------------
# How long (seconds) to wait for w.start() before declaring Wind unavailable.
# Override this at module level before the first Wind call if needed:
#   import data.providers.retrieve as r; r.WIND_CONNECT_TIMEOUT = 60
WIND_CONNECT_TIMEOUT: float = 20.0
WSQ_CALL_TIMEOUT: float = 10.0
WSQ_CHUNK_SIZE: int = 200


def _normalize_codes(codes) -> list[str]:
    if isinstance(codes, str):
        return [code.strip() for code in codes.split(',') if code.strip()]
    return list(codes)


def _normalize_fields(fields: str) -> list[str]:
    return [field.strip() for field in fields.split(',') if field.strip()]


def _empty_wsq_frame(codes, fields) -> pd.DataFrame:
    code_list = _normalize_codes(codes)
    field_list = _normalize_fields(fields)
    return pd.DataFrame(index=code_list, columns=field_list, dtype=float)


def _normalize_wind_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return frame
    obj_cols = frame.select_dtypes(include=['object']).columns
    if not len(obj_cols):
        return frame

    def _clean(v):
        if isinstance(v, (bytes, bytearray)):
            v = v.decode('utf-8', errors='ignore').strip()
        elif isinstance(v, str):
            v = v.strip()
        return np.nan if v == '' else v

    normalized = frame.copy()
    normalized[obj_cols] = normalized[obj_cols].apply(lambda col: col.map(_clean))
    return normalized


def _wsq_single_call(codes, fields) -> pd.DataFrame:
    template = _empty_wsq_frame(codes, fields)
    result_holder = [template]
    exc_holder: list[Optional[Exception]] = [None]

    def _do_wsq():
        try:
            from WindPy import w
            result_holder[0] = w.wsq(codes, fields, usedf=True)[1]
        except Exception as ex:
            exc_holder[0] = ex

    t = threading.Thread(target=_do_wsq, daemon=True)
    t.start()
    t.join(timeout=WSQ_CALL_TIMEOUT)

    if t.is_alive():
        print(
            f"[Wind] wsq timeout after {WSQ_CALL_TIMEOUT:.0f}s "
            f"for {len(template.index)} codes; returning NaN frame."
        )
        return template

    if exc_holder[0] is not None:
        print('Wind wsq error:', exc_holder[0])
        return template

    result = result_holder[0]
    if not isinstance(result, pd.DataFrame):
        return template
    result = result.reindex(index=template.index)
    return _normalize_wind_frame(result)


def _ensure_wind() -> bool:
    """Simple start for Wind terminal.

    This directly imports WindPy and calls `w.start()`; returns True on
    success, False on failure. Intentionally does not use timeouts or caching.
    """
    try:
        from WindPy import w
        w.start()
        return True
    except Exception as e:
        print(f"[Wind] Failed to start: {e} — running in offline mode.")
        return False


def reset_wind_connection():
    """Force a fresh Wind session restart."""
    try:
        from WindPy import w
        w.start()
    except Exception as e:
        print(f"[Wind] Failed to restart: {e}")


# ---------------------------------------------------------------------------
# WindPy safe wrappers
# ---------------------------------------------------------------------------
def _wind_call(func_name: str, *args) -> pd.DataFrame:
    """Generic Wind API call: ensures connection, calls func, normalizes result."""
    if not _ensure_wind():
        return pd.DataFrame()
    try:
        from WindPy import w
        result = getattr(w, func_name)(*args, usedf=True)[1]
        return _normalize_wind_frame(result)
    except Exception as ex:
        print(f'Wind {func_name} error:', ex)
        return pd.DataFrame()


def _wset(api, options):
    return _wind_call("wset", api, options)

def _wss(codes, fields, options=""):
    return _wind_call("wss", codes, fields, options)

def _wsd(codes, fields, start, end, options=""):
    return _wind_call("wsd", codes, fields, start, end, options)

def _wsi(codes, fields, start, end, options="", options2=None):
    extra = (options2,) if options2 is not None else ()
    return _wind_call("wsi", codes, fields, start, end, options, *extra)

def _wst(codes, fields, ds):
    return _wind_call("wst", codes, fields, ds + " 09:00:00", ds + " 17:00:00", "")

def _edb(ids, start, end, options="Fill=Previous"):
    return _wind_call("edb", ids, start, end, options)


def _wsq(codes, fields):
    if not _ensure_wind():
        return _empty_wsq_frame(codes, fields)

    code_list = _normalize_codes(codes)
    if len(code_list) <= WSQ_CHUNK_SIZE:
        return _wsq_single_call(code_list, fields)

    chunks = [code_list[i:i + WSQ_CHUNK_SIZE] for i in range(0, len(code_list), WSQ_CHUNK_SIZE)]
    frames = []
    for i, chunk in enumerate(chunks, 1):
        print(f"[Wind] wsq chunk {i}/{len(chunks)}: {len(chunk)} codes")
        frames.append(_wsq_single_call(chunk, fields))
    return pd.concat(frames, axis=0) if frames else _empty_wsq_frame(code_list, fields)

def _save_pickle(obj, path):
    with open(path, 'wb') as f:
        pickle.dump(obj, f)

def convertTime(num_list):
    time_list = []
    for n in num_list:
        ns = str(int(n))
        if len(ns) == 6:
            time_list.append(dt.time(int(ns[:2]),int(ns[2:4]),int(ns[4:6])))
        else:
            time_list.append('')
    return time_list




def fxswap():
    starts = _date_strs['d7d']
    dps = _date_strs['dp']
    
    usdcny = _wsd("USDCNY.EX,USDCNY.IB", "close", starts, dps)
    sofr_ts = _wsd(WindConfig.SOFR_STR, "close", starts, dps)
    fxswap_ts = _wsd(WindConfig.FXSWAP, "close", starts, dps)


# =============================================================================
# Data Loading Functions (relocated from loader.py)
# =============================================================================

def fetch_wind_data_day(symbol):
    """
    Fetch daily OHLCV data from Wind.

    Parameters:
    -----------
    symbol : str
        Symbol to fetch data for

    Returns:
    --------
    pd.DataFrame: OHLCV data with datetime index
    """
    if config_manager is None:
        print('Wind day data fetch skipped: config_manager not available')
        return pd.DataFrame()
    data = _wsd(
        symbol,
        "open,high,low,close,volume",
        config_manager.date_config.day_data_start_date,
        config_manager.date_config.day_data_end_date,
        "Fill=Previous",
    )
    data = data.dropna()
    data.index = pd.to_datetime(data.index)
    data.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
    return data


def fetch_wind_data_bar(symbol):
    """
    Fetch intraday bar data from Wind.

    Parameters:
    -----------
    symbol : str
        Symbol to fetch data for

    Returns:
    --------
    pd.DataFrame: OHLCV data with datetime index
    """
    if config_manager is None:
        print('Wind bar data fetch skipped: config_manager not available')
        return pd.DataFrame()
    data = _wsi(
        symbol,
        "open,high,low,close,volume",
        config_manager.date_config.bar_data_start_date,
        config_manager.date_config.bar_data_end_date,
        "Fill=Previous",
    )
    data = data.dropna()
    data.index = pd.to_datetime(data.index)
    data.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
    return data


def fetch_interest_rate(symbol):
    """
    Fetch interest rate data from Wind.

    Parameters:
    -----------
    symbol : str
        Symbol to fetch data for

    Returns:
    --------
    pd.DataFrame: Interest rate data with datetime index
    """

    if config_manager is None:
        print('Interest rate fetch skipped: config_manager not available')
        return pd.DataFrame()
    data = _wsi(
        config_manager.date_config.interest_rate_symbols,
        "open,high,low,close,volume",
        config_manager.date_config.interest_rate_start_date,
        config_manager.date_config.interest_rate_end_date,
        "Fill=Previous",
        config_manager.date_config.interest_rate_frequency,
    )
    data = data.dropna()
    data.index = pd.to_datetime(data.index)
    data.columns = ['Close']
    return data


