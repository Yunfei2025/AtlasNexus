"""Background callbacks and utility routines for Dash server."""

from __future__ import annotations

import datetime
import json
import os
import sys
import pickle
import pathlib
import time
import logging

logger = logging.getLogger(__name__)

# Optional import-time logging
if os.environ.get('WEB_LOG_TIMINGS','0') == '1':
    _import_start = time.time()
    logger.info('Importing web.core.scripts...')
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Mapping

import re
import pandas as pd
from dash.dependencies import Input, Output, State

# Setup paths
project_root = pathlib.Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from web.core.server import app  # noqa: E402
from web.core.load import t_int, DATA_PATH
from settings.fixed_income import BondConfig
from settings.general import TradingHoursConfig
from settings.paths import DIR_INPUT

# Curve refreshers are imported lazily inside _autoruns1_tick() so that this
# module loads in ~ms at startup. The first refresh tick pays the import cost
# once; subsequent ticks hit the already-loaded modules.
REFRESHERS_AVAILABLE = True

if os.environ.get('WEB_LOG_TIMINGS','0') == '1':
    logger.info('web.core.scripts import took %.3fs', time.time() - _import_start)

# ---------------------------------------------------------------------------
# Bounded pickle cache
# ---------------------------------------------------------------------------
# mtime-keyed: {path: (mtime_float, object)}. Capped at _PICKLE_CACHE_MAX
# entries (LRU by insertion order via dict) to prevent unbounded growth when
# many large pickle files are loaded over a long session.
_PICKLE_CACHE_MAX = 64
_PICKLE_CACHE: dict[str, tuple[float, Any]] = {}

BOND_TYPES = ("TBond", "CBond")

_locks = {
    "initialise": threading.Lock(),
    "autoruns1": threading.Lock(),
    "autoruns2": threading.Lock(),
}

# Cached status strings exposed to UI callbacks. The periodic refresh thread
# writes here; Dash callbacks just read. Replaces the old DiskcacheManager
# subprocess flow, which deadlocked on Windows because multiprocess spawn
# re-imports this module in a fresh interpreter.
_status_state: dict[str, Any] = {
    "initialise": "",
    "autoruns1": "Initialising...",
    "autoruns2": None,
}
_status_lock = threading.Lock()

DIRECT_CALLS_AVAILABLE = REFRESHERS_AVAILABLE


def _set_status(key: str, value: Any) -> None:
    with _status_lock:
        _status_state[key] = value


def _get_status(key: str) -> Any:
    with _status_lock:
        return _status_state.get(key)


class Utils:
    """Utility functions for file operations and parallel execution."""

    @staticmethod
    def get_mtime_date(path_obj: pathlib.Path | str) -> datetime.date | None:
        try:
            # Accept either a pathlib.Path or a string path. Convert to Path to
            # ensure we can call .stat() without raising AttributeError when
            # callers pass a plain string (common with os.path.join calls).
            p = pathlib.Path(path_obj)
            return datetime.datetime.fromtimestamp(p.stat().st_mtime).date()
        except FileNotFoundError:
            return None

    @staticmethod
    def load_pickle_cached(path_obj: pathlib.Path | str) -> Any | None:
        path = str(path_obj)
        try:
            mtime = os.path.getmtime(path)
        except FileNotFoundError:
            return None

        cached = _PICKLE_CACHE.get(path)
        if cached and cached[0] == mtime:
            return cached[1]

        try:
            with open(path, "rb") as f:
                obj = pickle.load(f)
            # Enforce LRU cap: evict oldest entry when limit is reached.
            if len(_PICKLE_CACHE) >= _PICKLE_CACHE_MAX and path not in _PICKLE_CACHE:
                oldest_key = next(iter(_PICKLE_CACHE))
                del _PICKLE_CACHE[oldest_key]
            _PICKLE_CACHE[path] = (mtime, obj)
            return obj
        except Exception as e:
            print(f"Error loading {path}: {e}")
            return None

    @staticmethod
    def run_parallel_tasks(tasks, max_workers=4):
        if not tasks:
            return

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(task) for task in tasks]
            for future in futures:
                try:
                    future.result()
                except Exception as e:
                    print(f"Task failed: {e}")

def is_business_hours() -> bool:
    now = datetime.datetime.now()
    return (9 <= now.hour <= 18) and (now.weekday() <= 5)


def run_initialise() -> str:
    if not _locks["initialise"].acquire(blocking=False):
        return "Initialising (already running)..."
    try:
        if not DIRECT_CALLS_AVAILABLE:
            return "Error: Direct API calls not available. Please check imports."

        t = datetime.datetime.today()
        try:
            from engine.context import build_run_config
            from engine.data_update import ensure_daily_required_updates

            cfg = build_run_config(project_root=project_root, mode="data", asof=t.date())
            refreshed = ensure_daily_required_updates(cfg)
            if refreshed:
                print(f"Daily required data refreshed: {', '.join(refreshed)}")
        except Exception as e:
            print(f"WARNING: Daily required data refresh failed: {e}")

        try:
            from curves.utils.retrieve import updateInstrumentDef
            updateInstrumentDef(asof=None)
        except Exception as e:
            pass

        if (t.hour >= TradingHoursConfig.START_HOUR) and (t.hour <= TradingHoursConfig.INIT_END_HOUR) and (t.weekday() <= 4):
            print("Updating database and running generators...")
            try:
                from curves import initialise as curves_initialise
                status = curves_initialise.main()
                if isinstance(status, str) and status:
                    return status
            except ImportError as e:
                error_msg = f"Could not import curves.initialise: {e}"
                print(error_msg)
                return error_msg
        return "Finished Curve Initialisation."
    except Exception as e:
        error_msg = f"Initialisation failed: {str(e)}"
        print(error_msg)
        return error_msg
    finally:
        try:
            _locks["initialise"].release()
        except RuntimeError:
            pass

def _autoruns1_tick() -> None:
    """One iteration of the periodic refresh — safe to call from a thread.

    Body of the original ``autoruns1`` Dash callback, hoisted out so it runs
    in a plain daemon thread instead of a Dash background-callback subprocess
    (which is unreliable on Windows under DiskcacheManager).

    Refreshers are imported lazily here (not at module level) so the web app
    starts in ~ms. The first tick pays the import cost once; Python's module
    cache means subsequent ticks are free.
    """
    if not _locks["autoruns1"].acquire(blocking=False):
        return
    try:
        if not DIRECT_CALLS_AVAILABLE:
            _set_status("autoruns1", "Error: Direct API calls not available")
            return

        # Lazy imports — paid once on first tick, cached by Python module system.
        from curves.refreshers.rates import BondCurveRefresher
        from curves.refreshers.credit import CreditSpreadRefresher
        from curves.refreshers.irs import IRSRefresher
        from curves.refreshers.stat import StatRefresher

        t = datetime.datetime.today()
        date_m = Utils.get_mtime_date(os.path.join(DIR_INPUT, "macro-px.pkl"))
        in_window = (t.hour >= TradingHoursConfig.START_HOUR) and (t.hour <= TradingHoursConfig.END_HOUR) and (t.date() == date_m)
        in_credit_window = (t.hour >= TradingHoursConfig.CREDIT_START_HOUR) and (t.hour <= TradingHoursConfig.CREDIT_END_HOUR) and (t.date() == date_m)

        if in_window:
            Utils.run_parallel_tasks([
                lambda btype=btype: BondCurveRefresher.main(bond_type=btype)
                for btype in BOND_TYPES
            ])

        if in_credit_window:
            Utils.run_parallel_tasks([
                lambda obtype=obtype: CreditSpreadRefresher.main(other_bond_type=obtype)
                for obtype in BondConfig.INCLUDE_FILTERS.keys()
            ])

        if in_window:
            IRSRefresher.main()
            StatRefresher.main()
            _set_status(
                "autoruns1",
                "This app generates prices and statistics of Bonds and Swaps every "
                + str(int(t_int / 60e3))
                + "min. Data refreshed at: "
                + datetime.datetime.today().strftime("%Y-%m-%d %H:%M:%S"),
            )
    except Exception as e:
        error_msg = f"Auto refresh failed: {e}"
        print(error_msg)
        _set_status("autoruns1", error_msg)
    finally:
        try:
            _locks["autoruns1"].release()
        except RuntimeError:
            pass


def _autoruns2_tick() -> None:
    """Long-interval refresh tick. Currently a no-op (legacy body disabled)."""
    if not _locks["autoruns2"].acquire(blocking=False):
        return
    try:
        if not DIRECT_CALLS_AVAILABLE:
            _set_status("autoruns2", "Error: Direct API calls not available")
            return
        # Legacy body intentionally left empty — preserves the previous
        # commented-out behavior of autoruns2.
    except Exception as e:
        error_msg = f"Long auto refresh failed: {e}"
        print(error_msg)
        _set_status("autoruns2", error_msg)
    finally:
        try:
            _locks["autoruns2"].release()
        except RuntimeError:
            pass


_periodic_thread_started = threading.Event()


def start_periodic_refresh(interval_seconds: float | None = None) -> None:
    """Launch the daemon thread that drives autoruns1/autoruns2 periodically.

    Idempotent — calling more than once is a no-op. Runs entirely in-process,
    so it behaves identically on macOS and Windows (no subprocess spawn).
    """
    if _periodic_thread_started.is_set():
        return
    _periodic_thread_started.set()

    if interval_seconds is None:
        interval_seconds = max(1.0, t_int / 1000.0)

    long_interval_seconds = max(interval_seconds, 4.0 * interval_seconds)

    def _loop() -> None:
        # Defer the first tick so startup `_bg_init` can finish first.
        time.sleep(min(30.0, interval_seconds))
        last_long_tick = 0.0
        while True:
            try:
                _autoruns1_tick()
                now = time.monotonic()
                if now - last_long_tick >= long_interval_seconds:
                    _autoruns2_tick()
                    last_long_tick = now
            except Exception as exc:
                logger.warning(f"Periodic refresh tick failed: {exc}")
            time.sleep(interval_seconds)

    threading.Thread(
        target=_loop,
        daemon=True,
        name="atlas-periodic-refresh",
    ).start()


@app.callback(
    Output("container-button-1", "children"),
    Input("generate-button", "n_clicks"),
)
def initialise(n_clicks):
    """Manual re-init trigger. Runs work in a thread so the click returns fast."""
    if not n_clicks:
        return _get_status("initialise") or ""

    if not _locks["initialise"].locked():
        def _run() -> None:
            try:
                _set_status("initialise", run_initialise())
            except Exception as exc:
                _set_status("initialise", f"Initialisation failed: {exc}")

        threading.Thread(
            target=_run,
            daemon=True,
            name="atlas-manual-initialise",
        ).start()

    return _get_status("initialise") or "Initialising..."


@app.callback(
    Output("refresh-time", "children"),
    Input("data-refresh", "n_intervals"),
    State("container-button-1", "children"),
)
def autoruns1(interval, status_text):
    """UI-facing read of the latest periodic-refresh status."""
    if not status_text:
        return "Initialising..."
    return _get_status("autoruns1") or "Initialising..."


@app.callback(
    Output("hidden-div", "children"),
    Input("data-refresh-long", "n_intervals"),
    State("container-button-1", "children"),
)
def autoruns2(interval, status_text):
    if not status_text:
        return None
    return _get_status("autoruns2")


@app.callback(
    Output("realtime-data", "data"),
    Input("data-refresh", "n_intervals"),
)
def refresh(interval):
    data_rt: dict[str, Any] = {}
    for btype in ["TBond", "CBond"]:
        datart_dict = Utils.load_pickle_cached(os.path.join(DIR_INPUT,f"{btype}-spdsrt.pkl"))
        if isinstance(datart_dict, Mapping):
            data_rt[f"{btype}Curve"] = datart_dict["BondCurve"]
            data_rt[f"{btype}Swap"] = datart_dict["BondSwap"]

    irs_rt = Utils.load_pickle_cached(os.path.join(DIR_INPUT,"IRS-spdsrt.pkl"))
    if isinstance(irs_rt, Mapping):
        _irs_spreads = irs_rt['spreads']
        if hasattr(_irs_spreads, 'index'):
            _irs_spreads = _irs_spreads[~_irs_spreads.index.str.endswith('.IR')]
        data_rt['SwapSpread'] = _irs_spreads

    for btype in BondConfig.INCLUDE_FILTERS.keys():
        spd = Utils.load_pickle_cached(os.path.join(DIR_INPUT,f"{btype}-spdsrt.pkl"))
        data_rt[f"{btype}Spread"] = spd

    portspds = Utils.load_pickle_cached(os.path.join(DIR_INPUT,"Portfolio-spds.pkl"))
    if isinstance(portspds, Mapping):
        data_rt['AssetPCASpread'] = portspds.get('StatInfo', None)

    miscspds = Utils.load_pickle_cached(os.path.join(DIR_INPUT,"Misc-spdsrt.pkl"))
    if isinstance(miscspds, Mapping):
        data_rt['SectorPCASpread'] = miscspds.get('PCASpread', None)
        data_rt['BinarySpread'] = miscspds.get('BinarySpread', None)
    # Fallback: if runtime pkl is unavailable, synthesize current rows from the
    # static snapshot so the bar charts still show live-looking data.
    _misc_static_loaded = False
    _misc_static = None

    def _load_misc_static():
        nonlocal _misc_static_loaded, _misc_static
        if not _misc_static_loaded:
            _misc_static = Utils.load_pickle_cached(os.path.join(DIR_INPUT, "Misc-spds.pkl"))
            _misc_static_loaded = True
        return _misc_static

    if data_rt.get('BinarySpread') is None:
        try:
            ms = _load_misc_static()
            if isinstance(ms, Mapping):
                _bs = ms.get('BinarySpread', {})
                if isinstance(_bs, dict):
                    _spread = _bs.get('Spread')
                    _stat = _bs.get('StatInfo')
                    if isinstance(_spread, pd.DataFrame) and isinstance(_stat, pd.DataFrame) and not _spread.empty:
                        _current = _spread.iloc[-1].rename('spread').to_frame()
                        _current = _current.join(_stat[['mean', 'vol']], how='inner')
                        _current['Zscore'] = (_current['spread'] - _current['mean']) / _current['vol']
                        _current['color'] = 'grey'
                        data_rt['BinarySpread'] = _current
        except Exception:
            pass

    if data_rt.get('SectorPCASpread') is None:
        try:
            ms = _load_misc_static()
            if isinstance(ms, Mapping):
                _pca = ms.get('PCASpread', {})
                if isinstance(_pca, dict):
                    _spread = _pca.get('Spread')
                    _stat = _pca.get('StatInfo')
                    if isinstance(_spread, pd.DataFrame) and isinstance(_stat, pd.DataFrame) and not _spread.empty:
                        _current = _spread.iloc[-1].rename('spread').to_frame()
                        _current = _current.join(_stat[['mean', 'vol']], how='inner')
                        _current['Zscore'] = (_current['spread'] - _current['mean']) / _current['vol']
                        _current['color'] = 'grey'
                        # Rename '1.0Y'-style tenors to '1Y' to match RT format
                        _current.index = [re.sub(r'(-\d+)\.0(Y)$', r'\1\2', idx) for idx in _current.index]
                        data_rt['SectorPCASpread'] = _current
        except Exception:
            pass

    futspds = Utils.load_pickle_cached(os.path.join(DIR_INPUT,"futures-spdsrt.pkl"))
    if isinstance(futspds, Mapping):
        data_rt['NetBasis'] = futspds.get('NetBasis', None)
        data_rt['TermBasis'] = futspds.get('TermBasis', None)

    # TenorSpread has no live RT feed; synthesize bar-chart rows from the latest
    # daily-batch Tenor-spds.pkl so the bar chart doesn't show "Waiting for data".
    try:
        tenor_static = Utils.load_pickle_cached(os.path.join(DIR_INPUT, 'Tenor-spds.pkl'))
        if isinstance(tenor_static, Mapping) and 'TenorSpread' in tenor_static:
            _ts = tenor_static['TenorSpread']
            if isinstance(_ts, dict):
                _spread = _ts.get('Spread')
                _stat   = _ts.get('StatInfo')
                if (isinstance(_spread, pd.DataFrame) and not _spread.empty
                        and isinstance(_stat, pd.DataFrame) and not _stat.empty):
                    _current = _spread.iloc[-1].rename('spread').to_frame()
                    _current = _current.join(_stat[['mean', 'vol']], how='inner')
                    _vol = pd.to_numeric(_current['vol'], errors='coerce').replace(0, float('nan'))
                    _mean = pd.to_numeric(_current['mean'], errors='coerce')
                    _current['Zscore'] = (pd.to_numeric(_current['spread'], errors='coerce') - _mean) / _vol
                    _current['color'] = 'grey'
                    data_rt['TenorSpread'] = _current
    except Exception:
        pass

    out_dict = {}
    for key, value in data_rt.items():
        if isinstance(value, pd.DataFrame):
            out_dict[key] = value.to_dict()
        elif isinstance(value, dict):
            out_dict[key] = {
                k: (v.to_dict() if isinstance(v, pd.DataFrame) else v)
                for k, v in value.items()
            }
        else:
            out_dict[key] = value
    return json.dumps(out_dict)
