"""Graph-building callbacks for FI Engine Dash applications."""

from __future__ import annotations
import os
import re as _re
import json
import pickle
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
import plotly.graph_objs as go
from dash import html
from dash.dependencies import Input, Output
from dash.exceptions import PreventUpdate

from settings.general import DateConfig
from settings.futures import FuturesConfig
from settings.fixed_income import BondConfig,  SpreadConfig
from settings.paths import DIR_INPUT

from web.core.server import app
from web.core.styles import (
    layout_stat,
    layout_ts_line,
    getInfo,
    getTraceStat,
    getFixingType,
    getTrace,
    getTraceAdd,
)
from web.core.load import spread_ts, fixing_ts, DATA_PATH

# Units map for different spread types
yunits = BondConfig.get_spread_units()
ospread = SpreadConfig.build_ospreado()


def _zscore_color(z: float) -> str:
    """Map z-score to a 5-step red->neutral->green scale for better signaling."""
    if z >= 2.0:
        return '#27ae60'   # strong buy   — emerald
    elif z >= 1.0:
        return '#82e0aa'   # mild buy     — light green
    elif z <= -2.0:
        return '#c0392b'   # strong sell  — crimson
    elif z <= -1.0:
        return '#f1948a'   # mild sell    — light red
    else:
        return '#4a5568'   # neutral      — slate gray


def _suppress_curve_yield_jumps(
    curve_yield: pd.Series,
    close_yield: pd.Series,
    abs_limit: float = 20.0,
    diff_limit: float = 5.0,
) -> pd.Series:
    """Suppress impossible curve-yield spikes using the close-yield series as anchor."""
    curve = pd.to_numeric(curve_yield, errors='coerce').replace([np.inf, -np.inf], np.nan).astype(float).copy()
    if curve.empty:
        return curve

    close = pd.to_numeric(close_yield, errors='coerce').reindex(curve.index).astype(float)
    outlier = curve.abs().gt(abs_limit)
    if close.notna().any():
        outlier = outlier | (close.notna() & (curve - close).abs().gt(diff_limit))

    if not outlier.any():
        return curve

    # Explicit float64 cast after mask prevents object-dtype regression on some
    # pandas/numpy versions where mask() on nullable-float columns loses dtype.
    curve = curve.mask(outlier).astype('float64')
    original_index = curve.index
    try:
        curve.index = pd.to_datetime(curve.index)
        curve = curve.interpolate(method='time', limit_area='inside').ffill().bfill()
    except Exception:
        curve = curve.interpolate(method='linear', limit_area='inside').ffill().bfill()
    curve.index = original_index
    return curve


def _sector_pca_sort_key(ticker: str) -> tuple:
    """Return (group, tenor_months) sort key for SectorPCASpread tickers."""
    def _tenor_months(t: str) -> int:
        m = _re.match(r'^(\d+)(Y|M)$', t, _re.IGNORECASE)
        if not m:
            return 9999
        n, unit = int(m.group(1)), m.group(2).upper()
        return n * 12 if unit == 'Y' else n
    if ticker.startswith('TBond-'):
        return (0, _tenor_months(ticker.split('-', 1)[1]))
    if ticker.startswith('CBond-'):
        return (1, _tenor_months(ticker.split('-', 1)[1]))
    if ticker.startswith('FR007S'):
        return (2, _tenor_months(ticker.replace('FR007S', '').replace('.IR', '')))
    if ticker.startswith('SHI3MS'):
        return (3, _tenor_months(ticker.replace('SHI3MS', '').replace('.IR', '')))
    return (4, ticker)


# Thresholds and type groupings
ZSCORE_ALERT_THRESHOLD: float = 2.0
TYPES_SIMPLE_ONLY: set[str] = set()
TYPES_WITH_FS: set[str] = {"SectorPCASpread"}
TYPES_BINARY: set[str] = {"BinarySpread"}

# Simple on-disk pickle cache keyed by file mtime to avoid repeated loads
_FIG_CACHE: Dict[str, Tuple[float, Any]] = {}


def _load_pickle_cached(path_obj) -> Any:
    """Load a pickle once per file mtime to avoid redundant disk IO."""
    path = str(path_obj)
    try:
        mtime = os.path.getmtime(path)
    except FileNotFoundError:
        return None
    cached = _FIG_CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    with open(path, 'rb') as f:
        obj = pickle.load(f)
    _FIG_CACHE[path] = (mtime, obj)
    return obj


def _build_fixing_trace(fixing_series: pd.Series) -> List[go.Scatter]:
    """Create secondary-axis fixing trace for overlay."""
    return [
        go.Scatter(
            name=fixing_series.name,
            x=fixing_series.index,
            y=fixing_series.values,
            yaxis="y2",
            line={"width": 1, "color": "red"},
        )
    ]


def _compute_x_range(spread_type: str, series: pd.Series) -> Dict[str, Any]:
    if spread_type in ["SectorPCASpread", "BinarySpread"]:
        return dict(start=min(series.index), end=max(series.index))
    dates = DateConfig.get_date_mappings()
    return dict(start=dates["d1y"], end=dates["d"])


def _compute_y_range(
    spread_type: str,
    series: pd.Series,
    x_range: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if x_range is not None:
        try:
            filtered = series.loc[x_range["start"]:x_range["end"]].dropna()
            if len(filtered) > 0:
                series = filtered
        except Exception:
            pass
    return dict(low=float(series.min()) - 1, up=float(series.max()) + 1)


def _select_layout(
    spread_type: str,
    title: str,
    y_unit: str,
    x_range: Dict[str, Any],
    y_range: Dict[str, Any],
    lineinfo: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if spread_type == "SectorPCASpread":
        return layout_ts_line(title, y_unit, x_range, y_range, lineinfo, shape=True)
    if spread_type == "BinarySpread":
        return layout_ts_line(title, y_unit, x_range, y_range, lineinfo, xmulti=True)
    return layout_ts_line(title, y_unit, x_range, y_range, lineinfo, ymulti=True, shape=True)


def build_spread_series(b: str, season: int, stype: str) -> Dict[str, Any]:
    """Assemble primary and auxiliary time series required for a spread chart."""

    def _resolve_datasets(spread_type: str):
        d = (
            spread_ts[spread_type][FuturesConfig.SEASONS[season]]
            if spread_type == "NetBasis"
            else spread_ts[spread_type]
        )
        tenors = list(d["StatInfo"].index)
        return d, tenors

    def _ensure_tenor(selected: str, tenors: List[str]) -> str:
        return selected if selected in tenors else tenors[0]

    def _primary_series(spread_type: str, d, tenor: str) -> Union[pd.Series, pd.DataFrame]:
        if spread_type in ["TBondCurve", "CBondCurve"] + ospread:
            cl = d["CloseYield"][tenor]
            cy_clean = _suppress_curve_yield_jumps(d["CurveYield"][tenor], cl)
            s = 100 * (cl - cy_clean).dropna()
        else:
            s = 100 * d["Spread"][tenor].dropna()
        return s

    dfts, tenor_options = _resolve_datasets(stype)
    b = _ensure_tenor(b, tenor_options)
    primary_series = _primary_series(stype, dfts, b)

    figinfo = getInfo(b, primary_series, dfts, "", stype)
    ftype = getFixingType(b)

    def _build_additional_series(spread_type: str, d, tenor: str, season_idx: int) -> Dict[Union[int, str], Any]:
        extra: Dict[Union[int, str], Any] = {}
        if spread_type == "BinarySpread":
            slope = 100 * d["StatInfo"].loc[tenor, "slope"]
            incpt = 100 * d["StatInfo"].loc[tenor, "intercept"]
            r2 = d["StatInfo"].loc[tenor, "R2"]
            x_vals = np.arange(0, primary_series.shape[0], 1)
            y_vals = slope * x_vals + incpt
            extra[0] = pd.Series(y_vals, index=x_vals)
            extra[1] = f"y={slope:.2f}x+{incpt:.2f}, R2: {r2:.2f}"
            return extra
        if spread_type in ["TBondCurve", "CBondCurve"] + ospread:
            cl = spread_ts[spread_type]["CloseYield"][tenor]
            extra[0] = cl
            extra[1] = _suppress_curve_yield_jumps(spread_ts[spread_type]["CurveYield"][tenor], cl)
            # CR(3m,bp) for BondCurve types: Spread series (annual %, 0.01=1bp) on y4
            if spread_type in ["TBondCurve", "CBondCurve"]:
                try:
                    spd_cr = spread_ts[spread_type].get("Spread")
                    if isinstance(spd_cr, pd.DataFrame) and tenor in spd_cr.columns:
                        extra['cr_buy'] = spd_cr[tenor]
                except Exception:
                    pass
            return extra
        if spread_type in ["TBondSwap", "CBondSwap"]:
            bc = spread_ts[spread_type]["BondCarry"][tenor]
            extra[0] = bc  # backward compat
            extra['cr_buy'] = bc    # annual bp → divide by 4 for 3m bp in trace
            extra['cr_sell'] = -bc
            return extra
        if spread_type == "SwapSpread":
            extra[0] = spread_ts[spread_type]["CarryRoll3m"][tenor]
            return extra
        if spread_type == "NetBasis":
            extra[0] = spread_ts["NetIRR"][FuturesConfig.SEASONS[season_idx]][tenor]
            return extra
        if spread_type == "TenorSpread":
            try:
                cr3m = spread_ts["TenorSpread"].get("CarryRoll3m")
                if isinstance(cr3m, pd.DataFrame) and tenor in cr3m.columns:
                    extra['cr_buy'] = cr3m[tenor]   # 3m % BUY carry (×100 for bp in trace)
                    extra['cr_sell'] = -cr3m[tenor]
            except Exception:
                pass
            extra[0] = pd.Series(dtype=float)
            return extra
        extra[0] = pd.Series(dtype=float)
        return extra

    additional_series: Dict[Union[int, str], Any] = _build_additional_series(stype, dfts, b, season)

    date_common = fixing_ts.index.intersection(primary_series.index)
    fs = fixing_ts.loc[date_common, ftype]
    return {"df": primary_series, "df1": additional_series, "fs": fs, "figinfo": figinfo}


@app.callback(Output("bond-graph", "figure"),
              Input("data-refresh", "n_intervals"),
              Input('bond-type', 'value'),
              )
def bondcurve(interval, btype):
    try:
       figure = _load_pickle_cached(os.path.join(DIR_INPUT,btype+'-fig.obj'))
       return figure
    except FileNotFoundError:
       return("Error: The figure file does not exist.")


@app.callback(Output("irs-graph", "figure"),
              Input("data-refresh", "n_intervals"),
              Input('curve-type', 'value'),
              )
def irscurve(interval, ctype):
    try:
       figure = _load_pickle_cached(os.path.join(DIR_INPUT,'IRS-'+ctype+'fig.obj'))
       return figure
    except FileNotFoundError:
       return("Error: The figure file does not exist.")


_REF_BOND_COLUMNS = [
    {"name": "Tenor", "id": "Tenor"},
    {"name": "CGB", "id": "CGB"},
    {"name": "CDB", "id": "CDB"},
]


def _ref_bonds_table_data():
    """Reference bonds (TBond/CBond) at standard tenors, from the Market Data tab's loader."""
    try:
        from web.tabs.atlas_market_data_tab import _load_reference_bonds
        df = _load_reference_bonds()
        if df.empty:
            return [], []
        # Keep only Tenor, CGB, CDB columns
        df = df[["Tenor", "CGB", "CDB"]]
        return df.to_dict("records"), _REF_BOND_COLUMNS
    except Exception as e:
        print(f"[curves_graph] ref bonds load error: {e}")
        return [], []


_CURVE_TYPE_LABELS = {
    "TBond": "China Government Bond",
    "CBond": "China Policybank Bond",
    "IRSSpot": "IRS Spot Curve",
    "IRSForward": "IRS Forward Curve",
}


def _trace_field(trace: Any, field: str, default: Any = None) -> Any:
    """Read a field off a trace, whether it's a plain dict (plotCurve) or a
    go.Scatter/go.Bar object (plotIRSSpotCurve/plotIRSForwardCurve return go.Figure)."""
    if isinstance(trace, dict):
        return trace.get(field, default)
    return getattr(trace, field, default)


def _trace_by_name(figure: Any, name: str) -> Any:
    """Find a trace (dict or graph_objs trace) by its `name` in a pickled Plotly figure."""
    traces = figure.get("data", []) if isinstance(figure, dict) else getattr(figure, "data", [])
    for tr in traces:
        if _trace_field(tr, "name") == name:
            return tr
    return None


def _decode_plotly_array(value: Any) -> Any:
    """Decode Plotly 6.x's compact typed-array form ({'dtype', 'bdata'}), which
    go.Scatter/.Bar properties can return as-is after a pickle round-trip."""
    if isinstance(value, dict) and "bdata" in value and "dtype" in value:
        import base64
        return np.frombuffer(base64.b64decode(value["bdata"]), dtype=np.dtype(value["dtype"]))
    return value


def _xy_series(trace: Any) -> pd.Series:
    if trace is None:
        return pd.Series(dtype=float)
    x = pd.to_numeric(pd.Series(_decode_plotly_array(_trace_field(trace, "x", []))), errors="coerce")
    y = pd.to_numeric(pd.Series(_decode_plotly_array(_trace_field(trace, "y", []))), errors="coerce")
    s = pd.Series(y.to_numpy(), index=x.to_numpy()).dropna()
    return s[~s.index.isna()].sort_index()


def _nearest(series: pd.Series, target: float) -> Optional[float]:
    if series.empty:
        return None
    idx = (series.index.to_series() - target).abs().idxmin()
    return float(series.loc[idx])


def _curve_snapshot_stats(curve_type: str, figure: Any) -> Dict[str, Any]:
    """Derive the right-rail snapshot (spot levels, slope, bid-offer, fwd peak)
    directly from the already-drawn traces, so the rail always matches the chart."""
    stats: Dict[str, Any] = {}
    try:
        if curve_type in ("TBond", "CBond"):
            # plotCurve names the fitted hero (yield) curve trace 'SpotRate'.
            hero = _xy_series(_trace_by_name(figure, "SpotRate"))
            band = _trace_by_name(figure, "Bid–Offer")
            mid = _xy_series(_trace_by_name(figure, "Mid"))
            if not hero.empty:
                s10y = _nearest(hero, 10.0)
                s2y = _nearest(hero, 2.0)
                stats["10Y Spot"] = s10y
                stats["2Y Spot"] = s2y
                if s10y is not None and s2y is not None:
                    stats["2s10s"] = (s10y - s2y) * 100.0
                # Peak yield and corresponding tenor
                peak_idx = hero.idxmax()
                peak_val = hero.max()
                if not pd.isna(peak_idx) and not pd.isna(peak_val):
                    stats["Peak yield"] = (float(peak_val), float(peak_idx))
            if band is not None:
                lo = pd.to_numeric(pd.Series(_decode_plotly_array(_trace_field(band, "base", []))), errors="coerce")
                width = pd.to_numeric(pd.Series(_decode_plotly_array(_trace_field(band, "y", []))), errors="coerce")
                spr = (width.dropna().abs() * 100.0)  # abs() ensures positive spread
                if not spr.empty:
                    stats["Avg Bid–Ofr"] = float(spr.mean())
                stats["Instruments"] = int(lo.notna().sum())
            elif not mid.empty:
                stats["Instruments"] = int(mid.shape[0])
        elif curve_type in ("IRSSpot", "IRSForward"):
            # plotIRSSpotCurve names the fit trace 'r7dFitCurve'/'s3mFitCurve';
            # plotIRSForwardCurve names it 'FR007FitCurve'/'Shibor3MFitCurve'.
            hero_name = "FR007FitCurve" if curve_type == "IRSForward" else "r7dFitCurve"
            sec_name = "Shibor3MFitCurve" if curve_type == "IRSForward" else "s3mFitCurve"
            hero = _xy_series(_trace_by_name(figure, hero_name))
            sec = _xy_series(_trace_by_name(figure, sec_name))
            if not hero.empty:
                stats["FR007 10Y"] = _nearest(hero, 10.0)
                stats["FR007 2Y"] = _nearest(hero, 2.0)
            if not sec.empty:
                stats["Shibor3M 10Y"] = _nearest(sec, 10.0)
            if curve_type == "IRSForward" and not hero.empty:
                peak_x = float(hero.idxmax())
                stats["Fwd peak"] = (float(hero.max()), peak_x)
    except Exception as e:
        print(f"[curve_snapshot] stats error: {e}")
    return stats


def _snapshot_stat(label: str, value: str, big: bool = False) -> html.Div:
    return html.Div([
        html.Div(label, className="curve-snapshot__k"),
        html.Div(value, className="curve-snapshot__v" + (" curve-snapshot__v--big" if big else "")),
    ], className="curve-snapshot__stat")


def _render_curve_snapshot(curve_type: str, stats: Dict[str, Any]) -> Any:
    """Build the right-rail 'Curve Snapshot' panel matching the restyled mockup."""
    if not stats:
        return []

    if curve_type in ("TBond", "CBond"):
        rows = [html.H3("Curve Snapshot", className="curve-snapshot__title")]
        s10y = stats.get("10Y Spot")
        if s10y is not None:
            rows.append(_snapshot_stat("10Y Spot", f"{s10y:.3f} %", big=True))
        grid_top = []
        s2y = stats.get("2Y Spot")
        if s2y is not None:
            grid_top.append(_snapshot_stat("2Y Spot", f"{s2y:.3f} %"))
        slope = stats.get("2s10s")
        if slope is not None:
            grid_top.append(_snapshot_stat("2s10s", f"{slope:+.1f} bp"))
        if grid_top:
            rows.append(html.Div(grid_top, className="curve-snapshot__grid2"))
        grid_bottom = []
        spr = stats.get("Avg Bid–Ofr")
        if spr is not None:
            grid_bottom.append(_snapshot_stat("Avg Bid–Ofr", f"{spr:.1f} bp"))
        n = stats.get("Instruments")
        if n is not None:
            grid_bottom.append(_snapshot_stat("Instruments", str(n)))
        if grid_bottom:
            rows.append(html.Div(className="curve-snapshot__divider"))
            rows.append(html.Div(grid_bottom, className="curve-snapshot__grid2"))
        peak = stats.get("Peak yield")
        if peak is not None:
            rows.append(html.Div(className="curve-snapshot__divider"))
            rows.append(_snapshot_stat("Peak yield @ Term", f"{peak[0]:.3f} % @ {peak[1]:.2f}Y"))
        return rows

    # IRS spot / forward
    rows = [html.H3("Curve Snapshot", className="curve-snapshot__title")]
    fr10 = stats.get("FR007 10Y")
    if fr10 is not None:
        rows.append(_snapshot_stat("FR007 10Y", f"{fr10:.3f} %", big=True))
    grid_top = []
    fr2 = stats.get("FR007 2Y")
    if fr2 is not None:
        grid_top.append(_snapshot_stat("FR007 2Y", f"{fr2:.3f} %"))
    shi10 = stats.get("Shibor3M 10Y")
    if shi10 is not None:
        grid_top.append(_snapshot_stat("Shibor3M 10Y", f"{shi10:.3f} %"))
    if grid_top:
        rows.append(html.Div(grid_top, className="curve-snapshot__grid2"))
    peak = stats.get("Fwd peak")
    if peak is not None:
        rows.append(html.Div(className="curve-snapshot__divider"))
        rows.append(_snapshot_stat("Fwd peak @ Term", f"{peak[0]:.2f} % @ {peak[1]:.1f}Y"))
    return rows


@app.callback([Output("curves-graph", "figure"),
               Output("curves-title", "children"),
               Output("ref-bonds-container", "style"),
               Output("ref-bonds-t", "data"),
               Output("ref-bonds-t", "columns"),
               Output("curves-chart-subtitle", "children"),
               Output("curves-snapshot", "children")],
              Input("data-refresh", "n_intervals"),
              Input('curve-selection', 'value'),
              )
def curves_graph(interval, curve_type):
    """Combined callback for bond and IRS curves."""
    from datetime import datetime
    subtitle = _CURVE_TYPE_LABELS.get(curve_type, curve_type or "")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subtitle_with_time = f"{subtitle} · {timestamp}"
    try:
        if curve_type in ['TBond', 'CBond']:
            # Bond curves
            figure = _load_pickle_cached(os.path.join(DIR_INPUT, curve_type + '-fig.obj'))
            title = "Real Time Bond Curves"
            ref_bonds_style = {"display": "block"}  # Show reference bonds table
            ref_bonds_data, ref_bonds_columns = _ref_bonds_table_data()
        elif curve_type == 'IRSSpot':
            # IRS Spot curve
            figure = _load_pickle_cached(os.path.join(DIR_INPUT, 'IRS-spotfig.obj'))
            title = "Real Time Interest Rate Swap Curves - Spot"
            ref_bonds_style = {"display": "none"}  # Hide reference bonds table
            ref_bonds_data, ref_bonds_columns = [], []
        elif curve_type == 'IRSForward':
            # IRS Forward curve
            figure = _load_pickle_cached(os.path.join(DIR_INPUT, 'IRS-forwardfig.obj'))
            title = "Real Time Interest Rate Swap Curves - Forward"
            ref_bonds_style = {"display": "none"}  # Hide reference bonds table
            ref_bonds_data, ref_bonds_columns = [], []
        else:
            # Default fallback
            figure = _load_pickle_cached(os.path.join(DIR_INPUT, 'TBond-fig.obj'))
            title = "Real Time Bond Curves"
            ref_bonds_style = {"display": "block"}
            ref_bonds_data, ref_bonds_columns = _ref_bonds_table_data()

        snapshot = _render_curve_snapshot(curve_type, _curve_snapshot_stats(curve_type, figure))
        return figure, title, ref_bonds_style, ref_bonds_data, ref_bonds_columns, subtitle_with_time, snapshot
    except FileNotFoundError:
        empty_figure = {"data": [], "layout": {"title": "Error: The figure file does not exist."}}
        return empty_figure, "Error Loading Curves", {"display": "none"}, [], [], subtitle_with_time, []


@app.callback(Output("trend-graph", "figure"),
              Input("data-refresh", "n_intervals"),
              Input('trend-type', 'value'),
              )
def trend(interval, ctype):
    try:
       figure = _load_pickle_cached(os.path.join(DIR_INPUT,'trend-fig.obj'))
       return figure[ctype]
    except FileNotFoundError:
       return("Error: The figure file does not exist.")


@app.callback(Output("ticker", 'children', allow_duplicate=True),
              Input('graph-spread-bar', 'clickData'),
		  prevent_initial_call=True
              )
def display_click_data(clickData):
    if not clickData or "points" not in clickData or not clickData["points"]:
        raise PreventUpdate
    return clickData["points"][0]["label"]


@app.callback(Output("graph-spread-bar", "figure"),
              Input("data-refresh", "n_intervals"),
              Input("realtime-data", "data"),
              Input("spread-type", "value"),
              Input("select-season", "value"),
              )
def statistics(interval, data_rt_js, stype, season):
    if not data_rt_js:
        empty_layout = layout_stat(yunits.get(stype, "Z-score"))
        return go.Figure(data=[], layout=empty_layout)
    data_rt = json.loads(data_rt_js)

    if stype == 'NetBasis':
        df_raw = data_rt.get(stype, {}).get(FuturesConfig.SEASONS[season])
    else:
        df_raw = data_rt.get(stype)
    if df_raw is None:
        raise PreventUpdate
    df_ = pd.DataFrame(df_raw)
    yunit = "Z-score"
    spread = df_[['spread', 'Zscore']].dropna().copy()
    spread['color'] = spread['Zscore'].apply(_zscore_color)

    # Sort by index (ticker code) for better readability
    if stype == 'SectorPCASpread':
        spread = spread.loc[sorted(spread.index, key=_sector_pca_sort_key)]
    else:
        spread = spread.sort_index()
    
    trace = getTraceStat(spread,stype)
    layout = layout_stat(yunit)
    figure = go.Figure(data=[trace], layout=layout)
    figure.update_layout(clickmode='event+select')
    return figure


@app.callback(Output("graph-spread", "figure"),
              Input("spread-type", "value"),
              Input("select-season", "value"),
              Input("ticker", "children"),
              )
def spreadts(stype, season, b):
    dfc = build_spread_series(b, season, stype)
    df = dfc["df"]
    df1 = dfc["df1"]
    fs = dfc["fs"]
    figinfo = dfc["figinfo"]
    title = figinfo["title"]
    lineinfo = figinfo["line"]

    trace_main = getTrace(df, stype)
    trace_add = getTraceAdd(df1, stype)
    trace_fs = _build_fixing_trace(fs)

    if stype in TYPES_BINARY:
        data = trace_main + trace_add
    elif stype in TYPES_SIMPLE_ONLY:
        data = trace_main
    elif stype in TYPES_WITH_FS:
        data = trace_main + trace_fs
    else:
        data = trace_main + trace_fs + trace_add

    xrg = _compute_x_range(stype, df)
    yrg = _compute_y_range(stype, df, x_range=xrg)
    layout = _select_layout(stype, title, yunits[stype], xrg, yrg, lineinfo)

    # Explicitly scope yaxis2 (fixing overlay), yaxis3 and yaxis4 (CR 3m) ranges
    # to the visible x-window so right axes scale to 1Y data, not full history.
    _axis_sources = [("yaxis2", trace_fs), ("yaxis3", trace_add), ("yaxis4", trace_add)]
    for axis_key, traces in _axis_sources:
        if axis_key not in layout:
            continue
        _vals: List[float] = []
        _tag = axis_key.replace("yaxis", "y")  # "yaxis2" → "y2", "yaxis3" → "y3", etc.
        for t in traces:
            if getattr(t, "yaxis", None) == _tag and t.x is not None and t.y is not None:
                try:
                    s = pd.Series(list(t.y), index=pd.to_datetime(list(t.x))).dropna()
                    s = s.loc[xrg["start"]:xrg["end"]]
                    _vals.extend(s.values.tolist())
                except Exception:
                    pass
        if _vals:
            layout[axis_key]["range"] = [min(_vals) - 1, max(_vals) + 1]

    return dict(data=data, layout=layout)
