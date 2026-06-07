# -*- coding: utf-8 -*-
from __future__ import annotations

"""
Created on Mon Sep 18 22:47:31 2023

@author: CMBC
"""
import pandas as pd
import pickle
import threading
import datetime as dt
import logging
import numpy as np
from typing import Optional
from settings.general import TradingHoursConfig
from factors.config import config_manager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Wind connectivity — single startup probe with timeout
# ---------------------------------------------------------------------------
# How long (seconds) to wait for w.start() before declaring Wind unavailable.
# Override this at module level before the first Wind call if needed:
#   import data.providers.retrieve as r; r.WIND_CONNECT_TIMEOUT = 60
WIND_CONNECT_TIMEOUT: float = 20.0
WSQ_CALL_TIMEOUT: float = 10.0
WSQ_CHUNK_SIZE: int = 200


def _is_trading_hours(now: Optional[dt.datetime] = None) -> bool:
    now = now or dt.datetime.now()
    if TradingHoursConfig.WEEKDAYS_ONLY and now.weekday() >= 5:
        return False
    current_time = now.time()
    return dt.time(TradingHoursConfig.START_HOUR, 0) <= current_time <= dt.time(TradingHoursConfig.END_HOUR, 0)


# When True, allow Wind retrieval even outside normal trading hours.
# Intended for manual/backtest retrieval where users explicitly request
# historical data on weekends. It does NOT enable scheduled/automatic
# processes to bypass trading-hour checks unless they also set this flag.
ALLOW_NONTRADING_RETRIEVAL: bool = False


# Initial Wind availability: only True if within trading hours (or if the
# override flag is enabled at import time).
_WIND_AVAILABLE: Optional[bool] = None if (_is_trading_hours() or ALLOW_NONTRADING_RETRIEVAL) else False


def _normalize_list(items: str | list) -> list[str]:
    """Normalize comma-separated string or list into stripped list."""
    if isinstance(items, str):
        return [item.strip() for item in items.split(',') if item.strip()]
    return list(items)


def _empty_wsq_frame(codes, fields) -> pd.DataFrame:
    return pd.DataFrame(index=_normalize_list(codes), columns=_normalize_list(fields), dtype=float)


def _clean_value(v) -> str | float:
    """Clean a single value: decode bytes, strip whitespace, convert empty to NaN."""
    if isinstance(v, (bytes, bytearray)):
        v = v.decode('utf-8', errors='ignore').strip()
    elif isinstance(v, str):
        v = v.strip()
    return np.nan if v == '' else v


def _normalize_wind_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize Wind frame: clean object columns, strip whitespace, convert empty to NaN."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return frame
    obj_cols = frame.select_dtypes(include=['object']).columns
    if not len(obj_cols):
        return frame
    normalized = frame.copy()
    normalized[obj_cols] = normalized[obj_cols].apply(lambda col: col.map(_clean_value))
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
        logger.warning(
            "[Wind] wsq timeout after %ss for %d codes; returning NaN frame.",
            f"{WSQ_CALL_TIMEOUT:.0f}",
            len(template.index),
        )
        return template

    if exc_holder[0] is not None:
        logger.warning("Wind wsq error: %s", exc_holder[0])
        return template

    result = result_holder[0]
    if not isinstance(result, pd.DataFrame):
        return template
    result = result.reindex(index=template.index)
    return _normalize_wind_frame(result)


def _wind_start(log_msg: str = "Failed to start") -> bool:
    """Start or restart Wind connection. Returns True on success, False on failure."""
    global _WIND_AVAILABLE
    if not _is_trading_hours() and not ALLOW_NONTRADING_RETRIEVAL:
        _WIND_AVAILABLE = False
        logger.warning("[Wind] Outside trading hours and ALLOW_NONTRADING_RETRIEVAL=False. Enable with set_allow_nontrading_retrieval(True) for historical data.")
        return False
    try:
        from WindPy import w
        w.start()
        _WIND_AVAILABLE = True
        return True
    except Exception as e:
        _WIND_AVAILABLE = False
        logger.warning("[Wind] %s: %s — running in offline mode.", log_msg, e)
        return False


def _ensure_wind() -> bool:
    """Ensure Wind connection is available. Returns True on success."""
    return _wind_start("Failed to start")


def reset_wind_connection():
    """Force a fresh Wind session restart."""
    _wind_start("Failed to restart")


def set_allow_nontrading_retrieval(flag: bool):
    """Enable or disable non-trading-hour retrieval.

    When enabled, Wind connection attempts will be allowed outside trading
    hours. This is intended for explicit/manual backtest retrieval only and
    should not be enabled by scheduled/automatic processes.
    """
    global ALLOW_NONTRADING_RETRIEVAL
    ALLOW_NONTRADING_RETRIEVAL = bool(flag)
    return ALLOW_NONTRADING_RETRIEVAL


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
        logger.warning("Wind %s error: %s", func_name, ex)
        return pd.DataFrame()


def _wset(api, options, on_demand: bool = False):
    if on_demand:
        global ALLOW_NONTRADING_RETRIEVAL
        old_val = ALLOW_NONTRADING_RETRIEVAL
        ALLOW_NONTRADING_RETRIEVAL = True
        try:
            return _wind_call("wset", api, options)
        finally:
            ALLOW_NONTRADING_RETRIEVAL = old_val
    return _wind_call("wset", api, options)

def _wss(codes, fields, options="", on_demand: bool = False):
    if on_demand:
        global ALLOW_NONTRADING_RETRIEVAL
        old_val = ALLOW_NONTRADING_RETRIEVAL
        ALLOW_NONTRADING_RETRIEVAL = True
        try:
            return _wind_call("wss", codes, fields, options)
        finally:
            ALLOW_NONTRADING_RETRIEVAL = old_val
    return _wind_call("wss", codes, fields, options)

def _wsd(codes, fields, start, end, options="", on_demand: bool = False):
    if on_demand:
        global ALLOW_NONTRADING_RETRIEVAL
        old_val = ALLOW_NONTRADING_RETRIEVAL
        ALLOW_NONTRADING_RETRIEVAL = True
        try:
            return _wind_call("wsd", codes, fields, start, end, options)
        finally:
            ALLOW_NONTRADING_RETRIEVAL = old_val
    return _wind_call("wsd", codes, fields, start, end, options)

def _wsi(codes, fields, start, end, options="", options2=None, on_demand: bool = False):
    extra = (options2,) if options2 is not None else ()
    if on_demand:
        global ALLOW_NONTRADING_RETRIEVAL
        old_val = ALLOW_NONTRADING_RETRIEVAL
        ALLOW_NONTRADING_RETRIEVAL = True
        try:
            return _wind_call("wsi", codes, fields, start, end, options, *extra)
        finally:
            ALLOW_NONTRADING_RETRIEVAL = old_val
    return _wind_call("wsi", codes, fields, start, end, options, *extra)

def _wst(codes, fields, ds):
    return _wind_call("wst", codes, fields, ds + " 09:00:00", ds + " 17:00:00", "")

def _edb(ids, start, end, options="Fill=Previous"):
    return _wind_call("edb", ids, start, end, options)


def _wsq(codes, fields):
    if not _ensure_wind():
        return _empty_wsq_frame(codes, fields)

    code_list = _normalize_list(codes)
    if len(code_list) <= WSQ_CHUNK_SIZE:
        return _wsq_single_call(code_list, fields)

    chunks = [code_list[i:i + WSQ_CHUNK_SIZE] for i in range(0, len(code_list), WSQ_CHUNK_SIZE)]
    frames = []
    for i, chunk in enumerate(chunks, 1):
        logger.debug("[Wind] wsq chunk %d/%d: %d codes", i, len(chunks), len(chunk))
        frames.append(_wsq_single_call(chunk, fields))
    return pd.concat(frames, axis=0) if frames else _empty_wsq_frame(code_list, fields)

def _save_pickle(obj, path):
    with open(path, 'wb') as f:
        pickle.dump(obj, f)

def convert_time(num_list: list) -> list[dt.time | str]:
    """Convert numeric time values (e.g., 143000) to datetime.time objects."""
    result = []
    for n in num_list:
        s = str(int(n))
        if len(s) == 6:
            result.append(dt.time(int(s[:2]), int(s[2:4]), int(s[4:6])))
        else:
            result.append('')
    return result




# =============================================================================
# Data Loading Functions (relocated from loader.py)
# =============================================================================

def _normalize_ohlcv(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize OHLCV data: remove NaNs, convert index to datetime, rename columns."""
    data = data.dropna()
    data.index = pd.to_datetime(data.index)
    data.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
    return data


def fetch_wind_data_day(symbol):
    """Fetch daily OHLCV data from Wind."""
    if config_manager is None:
        logger.debug('Wind day data fetch skipped: config_manager not available')
        return pd.DataFrame()
    data = _wsd(
        symbol,
        "open,high,low,close,volume",
        config_manager.date_config.day_data_start_date,
        config_manager.date_config.day_data_end_date,
        "Fill=Previous",
    )
    return _normalize_ohlcv(data)


def fetch_wind_data_bar(symbol):
    """Fetch intraday bar data from Wind."""
    if config_manager is None:
        logger.debug('Wind bar data fetch skipped: config_manager not available')
        return pd.DataFrame()
    data = _wsi(
        symbol,
        "open,high,low,close,volume",
        config_manager.date_config.bar_data_start_date,
        config_manager.date_config.bar_data_end_date,
        "Fill=Previous",
    )
    return _normalize_ohlcv(data)


def fetch_interest_rate(symbol):
    """Fetch interest rate data from Wind."""
    if config_manager is None:
        logger.debug('Interest rate fetch skipped: config_manager not available')
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


