"""Data extraction and generation functions for yield surface."""

from __future__ import annotations


from datetime import datetime, timedelta
import os
import re

import pandas as pd

from settings.general import DateConfig
from settings.paths import DIR_INPUT


def _surface_file_path() -> str:
    return os.path.join(DIR_INPUT, "surface-ts.pkl")


def _normalize_surface_index(surface_dict: dict) -> dict:
    normalized = surface_dict or {}
    for key, df in normalized.items():
        if isinstance(df, pd.DataFrame) and not isinstance(df.index, pd.DatetimeIndex):
            normalized[key] = df.copy()
            normalized[key].index = pd.to_datetime(normalized[key].index)
    return normalized


def _latest_surface_date(surface_dict: dict) -> pd.Timestamp | None:
    latest_dates: list[pd.Timestamp] = []
    for value in (surface_dict or {}).values():
        if isinstance(value, pd.DataFrame) and not value.empty:
            index = value.index
            if not isinstance(index, pd.DatetimeIndex):
                index = pd.to_datetime(index)
            latest_dates.append(index.max())
    if not latest_dates:
        return None
    return max(latest_dates)


def _expected_surface_asof() -> datetime.date:
    today = datetime.today()
    return DateConfig.prev_cn_workday(today - timedelta(days=1))


def load_surface_data(refresh: bool = False) -> tuple[dict, dict]:
    from surface.retrieve import get_surface_cache_status, retrieveSurface

    file_path = _surface_file_path()
    cached_dict = pd.read_pickle(file_path) if os.path.exists(file_path) else {}
    cached_dict = _normalize_surface_index(cached_dict)
    cache_status = get_surface_cache_status(file_path)
    cached_latest = _latest_surface_date(cached_dict)
    expected_asof = cache_status["expected_asof"]
    gap_backfill_start = cache_status["gap_backfill_start"]
    cache_is_stale = cached_latest is None or cached_latest.date() < expected_asof
    cache_has_gap = gap_backfill_start is not None
    refresh_attempted = refresh
    refresh_mode = "manual" if refresh else "cached"
    refresh_error = None

    surface_dict = cached_dict
    if refresh_attempted:
        try:
            surface_dict = retrieveSurface(force=True)
        except Exception as exc:
            refresh_error = str(exc)
            if not cached_dict:
                raise

    if surface_dict is None and os.path.exists(file_path):
        surface_dict = pd.read_pickle(file_path)

    surface_dict = _normalize_surface_index(surface_dict or {})
    latest_asof = _latest_surface_date(surface_dict)

    return surface_dict, {
        "refresh_attempted": refresh_attempted,
        "refresh_mode": refresh_mode,
        "refresh_error": refresh_error,
        "expected_asof": expected_asof.isoformat(),
        "latest_asof": latest_asof.date().isoformat() if latest_asof is not None else None,
        "gap_backfill_start": gap_backfill_start.isoformat() if gap_backfill_start is not None else None,
        "cache_is_stale": cache_is_stale,
        "cache_has_gap": cache_has_gap,
    }

def extractTerms(strlist: list[str]) -> list[str]:
    """Extract term information from Wind data column names.
    
    Args:
        strlist: List of column name strings from Wind data.
        
    Returns:
        List of standardized term strings (e.g., '1-month', '10-year').
    """
    item = strlist[0].split(':')[0]
    if item in ['中债国开债到期收益率', '中债国债到期收益率', \
                '美国国债收益率','财政部-中国地方政府债券收益率曲线']:
        cn = 1
    elif item == '利率互换':
        cn = 2
    else:
        print('请指定其他收益率')
        cn = 1  # Default fallback
    
    ts = [i.split(':')[cn] for i in strlist]
    tn = [i.replace('个', '') for i in ts]
    ns = []
    for i in range(len(tn)):
        a = re.findall(r'(\d+)(\w+?)', tn[i])[0]
        if a[0] == '0':
            ns.append(str(0) + '-month')
        else:
            if a[1] == '年':
                ns.append(str(a[0]) + '-year')
            elif a[1] == '月':
                ns.append(str(a[0]) + '-month')
    return ns


def genCurveData(start: str, end: str = None, country: str = 'CN', refresh: bool = False) -> dict:
    """Generate yield curve data for the surface visualization.
    
    Args:
        start: Start date string for data retrieval.
        end: End date string for data retrieval. If None, uses today.
        country: Country code ('CN' for China, 'US' for United States).
        
    Returns:
        Dictionary containing plot list data and key points.
    """
    d = datetime.today()
    surface_dict, metadata = load_surface_data(refresh=refresh)
    
    # Select data based on country
    if country == 'US':
        df = surface_dict.get("US", surface_dict.get("CN"))  # Fallback to CN if US not available
    else:
        df = surface_dict.get("CN", list(surface_dict.values())[0] if surface_dict else None)
    
    if df is None or df.empty:
        # Return empty data structure if no data available
        return dict(plist={"x": [], "y": [], "z": []}, points={}, metadata=metadata)
    
    # Ensure index is DatetimeIndex for proper comparison
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    
    # Filter data by date range
    if start:
        start_dt = pd.to_datetime(start)
        df = df[df.index >= start_dt]
    if end:
        end_dt = pd.to_datetime(end)
        df = df[df.index <= end_dt]
    
    if df.empty:
        # Return empty data structure if no data in range
        return dict(plist={"x": [], "y": [], "z": []}, points={}, metadata=metadata)
    
    xlist = extractTerms(df.columns)
    ylist = [d.strftime("%Y-%m-%d") for d in df.index]

    zlist = []
    for row in df.iterrows():
        index, data = row
        zlist.append(data.tolist())

    today_date = df.index[-1].strftime("%Y-%m-%d") if hasattr(df.index[-1], 'strftime') else str(df.index[-1])

    idx = len(df) - 1
    df.columns = xlist
    
    # Use appropriate key terms based on country
    if country == 'US':
        key_terms = ["1-month", "10-year"] if "10-year" in xlist else [xlist[0], xlist[-1]]
    else:
        key_terms = ["1-month", "10-year"] if "10-year" in xlist else [xlist[0], xlist[-1]]
    
    points = {
        "P-Short": {"x": key_terms[0], "y": today_date, "z": df[key_terms[0]].iloc[idx]},
        "P-Long": {"x": key_terms[1], "y": today_date, "z": df[key_terms[1]].iloc[idx]},
    }
    return dict(plist={"x": xlist, "y": ylist, "z": zlist}, points=points, metadata=metadata)
