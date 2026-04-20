# -*- coding: utf-8 -*-
"""
Created on Mon Sep 18 22:47:31 2023

@author: CMBC
"""
import pandas as pd
import pickle
import threading
import datetime as dt
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

_WIND_AVAILABLE: bool | None = None  # None = not yet probed
_WIND_LOCK = threading.Lock()


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
    return result.reindex(index=template.index)


def _try_start_wind() -> bool:
    """Start the Wind terminal connection with a timeout.

    Probes only once per process and caches the result.  If Wind does not
    respond within *WIND_CONNECT_TIMEOUT* seconds the function returns False
    immediately, letting all callers fall back to cached data without hanging.
    """
    global _WIND_AVAILABLE
    if _WIND_AVAILABLE is not None:
        return _WIND_AVAILABLE

    with _WIND_LOCK:
        # Re-check inside the lock in case another thread already probed.
        if _WIND_AVAILABLE is not None:
            return _WIND_AVAILABLE

        success = [False]
        exc_holder: list[Optional[Exception]] = [None]

        def _do_start():
            try:
                from WindPy import w
                w.start()
                success[0] = True
            except Exception as e:
                exc_holder[0] = e

        t = threading.Thread(target=_do_start, daemon=True)
        t.start()
        t.join(timeout=WIND_CONNECT_TIMEOUT)

        if t.is_alive():
            print(
                f"[Wind] Terminal did not respond within {WIND_CONNECT_TIMEOUT:.0f}s "
                "— running in offline mode (cached data only)."
            )
            _WIND_AVAILABLE = False
        elif exc_holder[0] is not None:
            print(f"[Wind] Failed to start: {exc_holder[0]} — running in offline mode.")
            _WIND_AVAILABLE = False
        else:
            _WIND_AVAILABLE = success[0]
            if not _WIND_AVAILABLE:
                print("[Wind] Start returned False — running in offline mode.")

    return _WIND_AVAILABLE


def reset_wind_connection():
    """Force a fresh connectivity probe on the next Wind call.

    Useful if Wind becomes available after the process has been running
    (e.g. the user logs in mid-session).
    """
    global _WIND_AVAILABLE
    _WIND_AVAILABLE = None


# ---------------------------------------------------------------------------
# WindPy safe wrappers
# ---------------------------------------------------------------------------
def _wset(api, options):
    if not _try_start_wind():
        return pd.DataFrame()
    try:
        from WindPy import w
        return w.wset(api, options, usedf=True)[1]
    except Exception as ex:
        print('Wind wset error:', api, ex)
        return pd.DataFrame()

def _wss(codes, fields, options=""):
    if not _try_start_wind():
        return pd.DataFrame()
    try:
        from WindPy import w
        return w.wss(codes, fields, options, usedf=True)[1]
    except Exception as ex:
        print('Wind wss error:', ex)
        return pd.DataFrame()

def _wsd(codes, fields, start, end, options=""):
    if not _try_start_wind():
        return pd.DataFrame()
    try:
        from WindPy import w
        return w.wsd(codes, fields, start, end, options, usedf=True)[1]
    except Exception as ex:
        print('Wind wsd error:', ex)
        return pd.DataFrame()

def _wsq(codes, fields):
    if not _try_start_wind():
        return _empty_wsq_frame(codes, fields)

    code_list = _normalize_codes(codes)
    if len(code_list) <= WSQ_CHUNK_SIZE:
        return _wsq_single_call(code_list, fields)

    frames = []
    for start in range(0, len(code_list), WSQ_CHUNK_SIZE):
        chunk = code_list[start:start + WSQ_CHUNK_SIZE]
        chunk_no = start // WSQ_CHUNK_SIZE + 1
        total_chunks = (len(code_list) + WSQ_CHUNK_SIZE - 1) // WSQ_CHUNK_SIZE
        print(
            f"[Wind] wsq chunk {chunk_no}/{total_chunks}: "
            f"{len(chunk)} codes"
        )
        frames.append(_wsq_single_call(chunk, fields))

    if not frames:
        return _empty_wsq_frame(code_list, fields)
    return pd.concat(frames, axis=0)

def _wsi(codes, fields, start, end, options="", options2=None):
    if not _try_start_wind():
        return pd.DataFrame()
    try:
        from WindPy import w
        if options2 is not None:
            return w.wsi(codes, fields, start, end, options, options2, usedf=True)[1]
        return w.wsi(codes, fields, start, end, options, usedf=True)[1]
    except Exception as ex:
        print('Wind wsi error:', ex)
        return pd.DataFrame()

def _wst(codes, fields, ds):
    if not _try_start_wind():
        return pd.DataFrame()
    try:
        from WindPy import w
        return w.wst(codes, fields, ds + " 09:00:00", ds + " 17:00:00", "", usedf=True)[1]
    except Exception as ex:
        print('Wind wst error:', ex)
        return pd.DataFrame()

def _edb(ids, start, end, options="Fill=Previous"):
    if not _try_start_wind():
        return pd.DataFrame()
    try:
        from WindPy import w
        return w.edb(ids, start, end, options, usedf=True)[1]
    except Exception as ex:
        print('Wind edb error:', ex)
        return pd.DataFrame()

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


