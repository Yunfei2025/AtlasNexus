# -*- coding: utf-8 -*-
from __future__ import annotations

"""
Created on Mon Sep 18 22:47:31 2023

@author: CMBC
"""
import os
import sys
import pandas as pd
import pickle
import threading
import subprocess
import datetime as dt
import logging
import time
from pathlib import Path
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
WIND_FAILURE_RESET_SECONDS: float = 120.0
WIND_FAILURE_BACKOFF_SECONDS: float = 60.0
WIND_FAILURE_THRESHOLD: int = 3

_WIND_CALL_LOCK = threading.Lock()
_WIND_FAILURE_COUNT = 0
_WIND_BACKOFF_UNTIL = 0.0
_WIND_LAST_FAILURE_TS = 0.0


def _wind_disabled() -> bool:
    """Global kill switch for Wind calls in unstable environments."""
    return os.environ.get("FI_DISABLE_WIND", "").strip().lower() in {"1", "true", "yes", "on"}


def _mark_wind_failed() -> None:
    """Track consecutive Wind failures and temporarily suppress retries."""
    global _WIND_FAILURE_COUNT, _WIND_BACKOFF_UNTIL, _WIND_LAST_FAILURE_TS
    now = time.monotonic()

    # Failures separated by a long gap should not accumulate forever.
    if _WIND_LAST_FAILURE_TS and (now - _WIND_LAST_FAILURE_TS > WIND_FAILURE_RESET_SECONDS):
        _WIND_FAILURE_COUNT = 0

    _WIND_FAILURE_COUNT += 1
    _WIND_LAST_FAILURE_TS = now

    if _WIND_FAILURE_COUNT >= WIND_FAILURE_THRESHOLD:
        _WIND_BACKOFF_UNTIL = now + WIND_FAILURE_BACKOFF_SECONDS
        logger.warning(
            "[Wind] %d consecutive failures; backing off for %ss before retrying.",
            _WIND_FAILURE_COUNT,
            WIND_FAILURE_BACKOFF_SECONDS,
        )


def _wind_backoff_active() -> bool:
    """Return True when the app should skip Wind retries for a short cooldown."""
    return time.monotonic() < _WIND_BACKOFF_UNTIL


def _reset_wind_failures() -> None:
    global _WIND_FAILURE_COUNT, _WIND_BACKOFF_UNTIL, _WIND_LAST_FAILURE_TS
    _WIND_FAILURE_COUNT = 0
    _WIND_BACKOFF_UNTIL = 0.0
    _WIND_LAST_FAILURE_TS = 0.0


def _is_trading_hours(now: Optional[dt.datetime] = None) -> bool:
    if _wind_disabled():
        return False
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


def _call_wind_via_subprocess(func_name: str, *args):
    """Run a Wind call in a child Python process to isolate native crashes.

    Calls are serialised: only one Wind child process exists at a time, so a
    slow Wind cannot pile up concurrent native sessions.
    """
    if _wind_disabled():
        return pd.DataFrame()
    with _WIND_CALL_LOCK:
        return _call_wind_via_subprocess_locked(func_name, *args)


def _call_wind_via_subprocess_locked(func_name: str, *args):
    if _wind_backoff_active():
        logger.warning("[Wind] skipping %s call during cooldown to protect app stability.", func_name)
        return pd.DataFrame()

    project_root = str(Path(__file__).resolve().parents[2])
    script = (
        "import pickle, sys\n"
        f"sys.path.insert(0, {project_root!r})\n"
        "try:\n"
        "    from WindPy import w\n"
        "    if not w.isconnected():\n"
        "        w.start()\n"
        f"    value = getattr(w, {func_name!r})(*{args!r}, usedf=True)[1]\n"
        "    sys.stdout.buffer.write(b'OK\\n')\n"
        "    sys.stdout.buffer.write(pickle.dumps(value))\n"
        "except Exception as ex:\n"
        "    sys.stdout.buffer.write(b'ERR\\n')\n"
        "    sys.stdout.buffer.write(repr(ex).encode('utf-8', 'replace'))\n"
        "    raise\n"
    )

    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=project_root,
    )

    try:
        stdout, stderr = proc.communicate(timeout=WSQ_CALL_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        _mark_wind_failed()
        logger.warning("[Wind] %s timeout after %ss; returning empty frame.", func_name, f"{WSQ_CALL_TIMEOUT:.0f}")
        return pd.DataFrame()

    if proc.returncode != 0:
        _mark_wind_failed()
        err_text = stderr.decode("utf-8", "replace")
        logger.warning("[Wind] %s child process failed: %s", func_name, err_text or "unknown error")
        return pd.DataFrame()

    if not stdout:
        logger.warning("[Wind] %s returned no data from child process.", func_name)
        return pd.DataFrame()

    if stdout.startswith(b"ERR\n"):
        _mark_wind_failed()
        logger.warning("[Wind] %s child process error: %s", func_name, stdout[4:].decode("utf-8", "replace"))
        return pd.DataFrame()

    if not stdout.startswith(b"OK\n"):
        logger.warning("[Wind] %s child process returned unexpected payload.", func_name)
        return pd.DataFrame()

    try:
        value = pickle.loads(stdout[3:])
    except Exception as ex:
        _mark_wind_failed()
        logger.warning("[Wind] %s pickle decode error: %s", func_name, ex)
        return pd.DataFrame()

    _reset_wind_failures()
    return value


def _wind_call_sync(func_name: str, *args) -> pd.DataFrame:
    if not _ensure_wind():
        return pd.DataFrame()
    result = _call_wind_via_subprocess(func_name, *args)
    if not isinstance(result, pd.DataFrame):
        return pd.DataFrame()
    return _normalize_wind_frame(result)


def _wsq_single_call(codes, fields) -> pd.DataFrame:
    template = _empty_wsq_frame(codes, fields)
    if _wind_backoff_active():
        logger.warning("[Wind] skipping wsq call during cooldown to protect app stability.")
        return template

    result = _call_wind_via_subprocess("wsq", codes, fields)
    if not isinstance(result, pd.DataFrame):
        _mark_wind_failed()
        return template

    _reset_wind_failures()
    result = result.reindex(index=template.index)
    return _normalize_wind_frame(result)


def _wind_start(log_msg: str = "Failed to start") -> bool:
    """Start or restart Wind connection. Returns True on success, False on failure."""
    global _WIND_AVAILABLE
    if _wind_disabled():
        _WIND_AVAILABLE = False
        logger.warning("[Wind] disabled by FI_DISABLE_WIND; running in offline mode.")
        return False
    if not _is_trading_hours() and not ALLOW_NONTRADING_RETRIEVAL:
        _WIND_AVAILABLE = False
        logger.warning("[Wind] Outside trading hours and ALLOW_NONTRADING_RETRIEVAL=False. Enable with set_allow_nontrading_retrieval(True) for historical data.")
        return False
    # WindPy is never imported in this process: a native fault in the Wind
    # DLL would kill the web server. Every call starts its own session in a
    # child process (_call_wind_via_subprocess).
    _WIND_AVAILABLE = True
    return True


def _ensure_wind() -> bool:
    """Ensure Wind connection is available. Returns True on success."""
    if _wind_disabled():
        return False
    if _wind_backoff_active():
        logger.warning("[Wind] skipping connection retry during cooldown to avoid repeated native crashes.")
        return False
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
def _wind_call(func_name: str, *args, allow_nontrading: bool = False) -> pd.DataFrame:
    """Generic Wind API call that runs in a child process to contain crashes."""
    global ALLOW_NONTRADING_RETRIEVAL
    old_val = ALLOW_NONTRADING_RETRIEVAL
    ALLOW_NONTRADING_RETRIEVAL = bool(allow_nontrading) or ALLOW_NONTRADING_RETRIEVAL
    try:
        result = _call_wind_via_subprocess(func_name, *args)
    finally:
        ALLOW_NONTRADING_RETRIEVAL = old_val

    if not isinstance(result, pd.DataFrame):
        return pd.DataFrame()
    return result


def _wset(api, options, on_demand: bool = False):
    if on_demand:
        return _wind_call("wset", api, options, allow_nontrading=True)
    return _wind_call("wset", api, options)

def _wss(codes, fields, options="", on_demand: bool = False):
    if on_demand:
        return _wind_call("wss", codes, fields, options, allow_nontrading=True)
    return _wind_call("wss", codes, fields, options)

def _wsd(codes, fields, start, end, options="", on_demand: bool = False):
    if on_demand:
        return _wind_call("wsd", codes, fields, start, end, options, allow_nontrading=True)
    return _wind_call("wsd", codes, fields, start, end, options)

def _wsi(codes, fields, start, end, options="", options2=None, on_demand: bool = False):
    extra = (options2,) if options2 is not None else ()
    if on_demand:
        return _wind_call("wsi", codes, fields, start, end, options, *extra, allow_nontrading=True)
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


