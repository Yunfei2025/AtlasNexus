"""Data extraction and generation functions for yield surface."""

from __future__ import annotations


import re

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


def genCurveData(start: str, end: str = None, country: str = 'CN') -> dict:
    """Generate yield curve data for the surface visualization.
    
    Args:
        start: Start date string for data retrieval.
        end: End date string for data retrieval. If None, uses today.
        country: Country code ('CN' for China, 'US' for United States).
        
    Returns:
        Dictionary containing plot list data and key points.
    """
    import os
    from datetime import datetime
    import pandas as pd
    from settings.paths import DIR_INPUT
    from surface.retrieve import retrieveSurface
    d = datetime.today()
    # retrieveSurface()
    
    file_path = os.path.join(DIR_INPUT, "surface-ts.pkl")
    surface_dict = pd.read_pickle(file_path)
    
    # Select data based on country
    if country == 'US':
        df = surface_dict.get("US", surface_dict.get("CN"))  # Fallback to CN if US not available
    else:
        df = surface_dict.get("CN", list(surface_dict.values())[0] if surface_dict else None)
    
    if df is None or df.empty:
        # Return empty data structure if no data available
        return dict(plist={"x": [], "y": [], "z": []}, points={})
    
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
        return dict(plist={"x": [], "y": [], "z": []}, points={})
    
    xlist = extractTerms(df.columns)
    ylist = [d.strftime("%Y-%m-%d") for d in df.index]

    zlist = []
    for row in df.iterrows():
        index, data = row
        zlist.append(data.tolist())

    # Get the date for today's point annotation (use last date in filtered data)
    # Format must match ylist format (%Y-%m-%d)
    today_date = df.index[-1].strftime("%Y-%m-%d") if hasattr(df.index[-1], 'strftime') else str(df.index[-1])
    
    idx = df.index.get_indexer([d], method='nearest')[0]
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
    return dict(plist={"x": xlist, "y": ylist, "z": zlist}, points=points)
