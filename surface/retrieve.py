# -*- coding: utf-8 -*-
"""
Created on Mon Dec  8 22:53:04 2025

@author: CMBC
"""

import datetime as dt
import os

import pandas as pd
from dateutil.relativedelta import relativedelta

from utils.file import updatePKL, get_mtime_date
from settings.paths import DIR_INPUT


MAX_EXPECTED_GAP_DAYS = 14


def _normalize_surface_dict(surface_dict):
    normalized = surface_dict or {}
    for key, value in normalized.items():
        if isinstance(value, pd.DataFrame) and not isinstance(value.index, pd.DatetimeIndex):
            normalized[key] = value.copy()
            normalized[key].index = pd.to_datetime(normalized[key].index)
    return normalized

def _get_latest_cached_date(file_path: str):
    if not os.path.exists(file_path):
        return None
    try:
        surface_dict = pd.read_pickle(file_path)
    except Exception:
        return None

    latest_dates = []
    for value in (surface_dict or {}).values():
        if isinstance(value, pd.DataFrame) and not value.empty:
            index = value.index
            if not isinstance(index, pd.DatetimeIndex):
                index = pd.to_datetime(index)
            latest_dates.append(index.max().date())
    return max(latest_dates) if latest_dates else None


def _infer_gap_backfill_start(surface_dict, expected_asof: dt.date):
    candidates = []
    lookback_start = pd.Timestamp(expected_asof - relativedelta(years=1))

    for value in (surface_dict or {}).values():
        if not isinstance(value, pd.DataFrame) or value.empty:
            continue

        index = value.index
        if not isinstance(index, pd.DatetimeIndex):
            index = pd.to_datetime(index)
        index = pd.DatetimeIndex(index).sort_values()

        latest_date = index.max().date()
        if latest_date < expected_asof:
            candidates.append(latest_date + dt.timedelta(days=1))
            continue

        recent_index = index[index >= lookback_start]
        if len(recent_index) < 2:
            continue

        diffs = recent_index.to_series().diff().dropna()
        large_gaps = diffs[diffs.dt.days > MAX_EXPECTED_GAP_DAYS]
        if large_gaps.empty:
            continue

        gap_end = large_gaps.index[-1]
        gap_size = large_gaps.iloc[-1]
        gap_start = (gap_end - gap_size + pd.Timedelta(days=1)).date()
        candidates.append(gap_start)

    return min(candidates) if candidates else None


def get_surface_cache_status(file_path: str | None = None):
    file_path = file_path or os.path.join(DIR_INPUT, "surface-ts.pkl")
    today = dt.datetime.today()

    from settings.general import DateConfig

    expected_asof = DateConfig.prev_cn_workday(today - dt.timedelta(days=1))
    surface_dict = pd.read_pickle(file_path) if os.path.exists(file_path) else {}
    surface_dict = _normalize_surface_dict(surface_dict)
    latest_cached_date = _get_latest_cached_date(file_path)
    gap_backfill_start = _infer_gap_backfill_start(surface_dict, expected_asof)

    return {
        "expected_asof": expected_asof,
        "latest_cached_date": latest_cached_date,
        "gap_backfill_start": gap_backfill_start,
        "file_mtime_date": get_mtime_date(file_path),
        "has_cache": bool(surface_dict),
    }


def retrieveSurface(force: bool = False):
    d = dt.datetime.today()
    file_path = os.path.join(DIR_INPUT, "surface-ts.pkl")
    surface_dict = pd.read_pickle(file_path) if os.path.exists(file_path) else {}
    surface_dict = _normalize_surface_dict(surface_dict)

    cache_status = get_surface_cache_status(file_path)
    expected_asof = cache_status["expected_asof"]
    latest_cached_date = cache_status["latest_cached_date"]
    gap_backfill_start = cache_status["gap_backfill_start"]
    needs_update = (
        force
        or d.date() != cache_status["file_mtime_date"]
        or latest_cached_date is None
        or latest_cached_date < expected_asof
        or gap_backfill_start is not None
    )

    if needs_update:
        print("INFO: Updating time series...")
        from WindPy import w
        w.start()

        if gap_backfill_start is not None:
            start_date = gap_backfill_start
        elif latest_cached_date is not None and latest_cached_date < expected_asof:
            start_date = latest_cached_date + dt.timedelta(days=1)
        elif force and latest_cached_date is not None:
            start_date = max(latest_cached_date - dt.timedelta(days=7), expected_asof - dt.timedelta(days=7))
        else:
            start_date = expected_asof - relativedelta(years=10)

        dps = start_date.strftime("%Y%m%d")
        ds = expected_asof.strftime("%Y%m%d")
        
        from surface.config import cn_id_list, cn_id_name, us_id_list, us_id_name
        df0 = w.edb(cn_id_list, dps, ds, "Fill=Previous", usedf=True)[1]
        df0.columns = cn_id_name
        surface_dict["CN"] = df0
        
        df1 = w.edb(us_id_list, dps, ds, "Fill=Previous", usedf=True)[1]
        df1.columns = us_id_name
        surface_dict["US"] = df1
        
        surface_dict = updatePKL(surface_dict, file_path)

    if surface_dict is None and os.path.exists(file_path):
        surface_dict = pd.read_pickle(file_path)

    return surface_dict or {}