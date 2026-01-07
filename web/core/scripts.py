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
from typing import Any

import pandas as pd
import diskcache
from dash import DiskcacheManager
from dash.dependencies import Input, Output, State

# Setup paths
project_root = pathlib.Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from web.core.server import app
from web.core.load import t_int, DATA_PATH
from settings.fixed_income import BondConfig
from settings.general import DIR_INPUT
from curves.refreshers.irs import IRSRefresher
from curves.refreshers.rates import BondCurveRefresher
from curves.refreshers.credit import CreditSpreadRefresher
from curves.refreshers.stat import StatRefresher

REFRESHERS_AVAILABLE = True
print("✅ Refresher modules loaded successfully")

if os.environ.get('WEB_LOG_TIMINGS','0') == '1':
    logger.info('web.core.scripts import took %.3fs', time.time() - _import_start)

cache = diskcache.Cache("./cache")
background_callback_manager = DiskcacheManager(cache)
_PICKLE_CACHE: dict[str, tuple[float, object]] = {}
BOND_TYPES = ("TBond", "CBond")

_locks = {
    "initialise": threading.Lock(),
    "autoruns1": threading.Lock(),
    "autoruns2": threading.Lock(),
}

DIRECT_CALLS_AVAILABLE = REFRESHERS_AVAILABLE


class Utils:
    """Utility functions for file operations and parallel execution."""

    @staticmethod
    def get_mtime_date(path_obj: pathlib.Path) -> datetime.date | None:
        try:
            # Accept either a pathlib.Path or a string path. Convert to Path to
            # ensure we can call .stat() without raising AttributeError when
            # callers pass a plain string (common with os.path.join calls).
            p = pathlib.Path(path_obj)
            return datetime.datetime.fromtimestamp(p.stat().st_mtime).date()
        except FileNotFoundError:
            return None

    @staticmethod
    def load_pickle_cached(path_obj: pathlib.Path):
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

@app.callback(
    Output("container-button-1", "children"),
    Input("generate-button", "n_clicks"),
    background=True,
    manager=background_callback_manager,
)
def initialise(n_clicks):
    if not _locks["initialise"].acquire(blocking=False):
        return "Initialising (already running)..."
    try:
        if not DIRECT_CALLS_AVAILABLE:
            return "Error: Direct API calls not available. Please check imports."

        t = datetime.datetime.today()
        if (t.hour >= 9) and (t.hour <= 18) and (t.weekday() <= 5):
            print("Updating database and running generators...")
            try:
                from curves import initialise as curves_initialise
                curves_initialise.main()
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

@app.callback(
    Output("refresh-time", "children"),
    Input("data-refresh", "n_intervals"),
    State("container-button-1", "children"),
    background=True,
    manager=background_callback_manager,
)
def autoruns1(interval, status_text):
    if status_text and _locks["autoruns1"].acquire(blocking=False):
        try:
            if not DIRECT_CALLS_AVAILABLE:
                return "Error: Direct API calls not available"

            t = datetime.datetime.today()
            date_m = Utils.get_mtime_date(os.path.join(DIR_INPUT,"futures-spds.pkl"))
            if (t.hour >= 9) and (t.hour <= 17) and (t.date() == date_m):
                Utils.run_parallel_tasks([
                    lambda btype=btype: BondCurveRefresher.main(bond_type=btype)
                    for btype in BOND_TYPES
                ])

            if (t.hour >= 10) and (t.hour <= 12) and (t.date() == date_m):
                Utils.run_parallel_tasks([
                    lambda obtype=obtype: CreditSpreadRefresher.main(other_bond_type=obtype)
                    for obtype in BondConfig.INCLUDE_FILTERS.keys()
                ])
            if (t.hour >= 9) and (t.hour <= 17) and (t.date() == date_m):
                IRSRefresher.main()
                StatRefresher.main()

                return (
                    "This app generates prices and statistics of Bonds and Swaps every "
                    + str(int(t_int / 60e3))
                    + "min. Data refreshed at: "
                    + datetime.datetime.today().strftime("%Y-%m-%d %H:%M:%S")
                )
        except Exception as e:
            error_msg = f"Auto refresh failed: {str(e)}"
            print(error_msg)
            return error_msg
        finally:
            try:
                _locks["autoruns1"].release()
            except RuntimeError:
                pass
    return "Initialising..."


@app.callback(
    Output("hidden-div", "children"),
    Input("data-refresh-long", "n_intervals"),
    State("container-button-1", "children"),
    background=True,
    manager=background_callback_manager,
)
def autoruns2(interval, status_text):
    if status_text and _locks["autoruns2"].acquire(blocking=False):
        try:
            if not DIRECT_CALLS_AVAILABLE:
                return "Error: Direct API calls not available"
            # t = datetime.datetime.today()
            # date_m = Utils.get_mtime_date(os.path.join(DIR_INPUT,"MNote-spds.pkl"))
            # if (t.hour >= 10) and (t.hour <= 12) and (t.date() == date_m):
            #     Utils.run_parallel_tasks([
            #         lambda obtype=obtype: CreditSpreadRefresher.main(other_bond_type=obtype)
            #         for obtype in BondConfig.INCLUDE_FILTERS.keys()
            #     ])
        except Exception as e:
            error_msg = f"Long auto refresh failed: {str(e)}"
            print(error_msg)
            return error_msg
        finally:
            try:
                _locks["autoruns2"].release()
            except RuntimeError:
                pass


@app.callback(
    Output("realtime-data", "data"),
    Input("data-refresh", "n_intervals"),
)
def refresh(interval):
    data_rt: dict[str, Any] = {}
    for btype in ["TBond", "CBond"]:
        datart_dict = Utils.load_pickle_cached(os.path.join(DIR_INPUT,f"{btype}-spdsrt.pkl"))
        if datart_dict:
            data_rt[f"{btype}Curve"] = datart_dict["BondCurve"]
            data_rt[f"{btype}Swap"] = datart_dict["BondSwap"]

    irs_rt = Utils.load_pickle_cached(os.path.join(DIR_INPUT,"IRS-spdsrt.pkl"))
    if irs_rt:
        data_rt['SwapSpread'] = irs_rt['spreads']

    for btype in BondConfig.INCLUDE_FILTERS.keys():
        spd = Utils.load_pickle_cached(os.path.join(DIR_INPUT,f"{btype}-spdsrt.pkl"))
        data_rt[f"{btype}Spread"] = spd

    portspds = Utils.load_pickle_cached(os.path.join(DIR_INPUT,"Portfolio-spds.pkl"))
    if portspds:
        data_rt['AssetPCASpread'] = portspds.get('StatInfo', None)

    miscspds = Utils.load_pickle_cached(os.path.join(DIR_INPUT,"Misc-spdsrt.pkl"))
    if miscspds:
        data_rt['SectorPCASpread'] = miscspds.get('PCASpread', None)
        data_rt['BinarySpread'] = miscspds.get('BinarySpread', None)

    futspds = Utils.load_pickle_cached(os.path.join(DIR_INPUT,"futures-spdsrt.pkl"))
    if futspds:
        data_rt['NetBasis'] = futspds.get('NetBasis', None)
        data_rt['TermBasis'] = futspds.get('TermBasis', None)

    positions = Utils.load_pickle_cached(os.path.join(DIR_INPUT,"positions.pkl"))
    if positions:
        positions_last = {k: v.iloc[-1] for k, v in positions.items()}
        data_rt['InsPos'] = pd.concat(positions_last, axis=1)

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
