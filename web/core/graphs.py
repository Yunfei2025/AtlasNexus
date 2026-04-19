"""Graph-building callbacks for FI Engine Dash applications."""

from __future__ import annotations
import os
import json
import pickle
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
import plotly.graph_objs as go
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

# Thresholds and type groupings
ZSCORE_ALERT_THRESHOLD: float = 2.0
TYPES_SIMPLE_ONLY: set[str] = {"AssetPCASpread"}
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
    if spread_type in ["InsPos", "AssetPCASpread", "SectorPCASpread", "BinarySpread"]:
        return dict(start=min(series.index), end=max(series.index))
    dates = DateConfig.get_date_mappings()
    return dict(start=dates["d1y"], end=dates["d"])


def _compute_y_range(
    spread_type: str,
    series: pd.Series,
    x_range: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if spread_type == "InsPos":
        return dict(low=min(series["Volume"]), up=max(series["Volume"]))
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
    if spread_type == "InsPos":
        return layout_ts_line(title, y_unit, x_range, y_range)
    if spread_type in ("AssetPCASpread", "SectorPCASpread"):
        return layout_ts_line(title, y_unit, x_range, y_range, lineinfo, shape=True)
    if spread_type == "BinarySpread":
        return layout_ts_line(title, y_unit, x_range, y_range, lineinfo, xmulti=True)
    return layout_ts_line(title, y_unit, x_range, y_range, lineinfo, ymulti=True, shape=True)


def build_spread_series(b: str, inst: str, season: int, stype: str) -> Dict[str, Any]:
    """Assemble primary and auxiliary time series required for a spread chart."""

    def _resolve_datasets(spread_type: str):
        if spread_type == "InsPos":
            d = spread_ts[spread_type][inst]
            tenors = list(d.columns)
        else:
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
        if spread_type == "InsPos":
            s = d[tenor].dropna()
            s.name = "Volume"
            df_local = s.to_frame()
            buy_idx = df_local[df_local["Volume"] > 0].index
            sell_idx = df_local[df_local["Volume"] < 0].index
            df_local.loc[buy_idx, "color"] = "green"
            df_local.loc[sell_idx, "color"] = "red"
            df_local["color"].fillna("grey", inplace=True)
            return df_local

        s = 100 * d["Spread"][tenor].dropna()
        if spread_type in ["TBondCurve", "CBondCurve"]:
            s = s - d["StatInfo"].loc[tenor, "mean"] * 100
        return s

    dfts, tenor_options = _resolve_datasets(stype)
    b = _ensure_tenor(b, tenor_options)
    primary_series = _primary_series(stype, dfts, b)

    figinfo = getInfo(b, primary_series, dfts, inst, stype)
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
            extra[0] = spread_ts[spread_type]["CloseYield"][tenor]
            extra[1] = spread_ts[spread_type]["CurveYield"][tenor]
            return extra
        if spread_type in ["TBondSwap", "CBondSwap"]:
            extra[0] = spread_ts[spread_type]["BondCarry"][tenor]
            return extra
        if spread_type == "SwapSpread":
            extra[0] = spread_ts[spread_type]["CarryRoll3m"][tenor]
            return extra
        if spread_type == "NetBasis":
            extra[0] = spread_ts["NetIRR"][FuturesConfig.SEASONS[season_idx]][tenor]
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


@app.callback([Output("curves-graph", "figure"),
               Output("curves-title", "children"),
               Output("ref-bonds-container", "style")],
              Input("data-refresh", "n_intervals"),
              Input('curve-selection', 'value'),
              )
def curves_graph(interval, curve_type):
    """Combined callback for bond and IRS curves."""
    try:
        if curve_type in ['TBond', 'CBond']:
            # Bond curves
            figure = _load_pickle_cached(os.path.join(DIR_INPUT, curve_type + '-fig.obj'))
            title = "Real Time Bond Curves"
            ref_bonds_style = {"display": "block"}  # Show reference bonds table
        elif curve_type == 'IRSSpot':
            # IRS Spot curve
            figure = _load_pickle_cached(os.path.join(DIR_INPUT, 'IRS-spotfig.obj'))
            title = "Real Time Interest Rate Swap Curves - Spot"
            ref_bonds_style = {"display": "none"}  # Hide reference bonds table
        elif curve_type == 'IRSForward':
            # IRS Forward curve
            figure = _load_pickle_cached(os.path.join(DIR_INPUT, 'IRS-forwardfig.obj'))
            title = "Real Time Interest Rate Swap Curves - Forward"
            ref_bonds_style = {"display": "none"}  # Hide reference bonds table
        else:
            # Default fallback
            figure = _load_pickle_cached(os.path.join(DIR_INPUT, 'TBond-fig.obj'))
            title = "Real Time Bond Curves"
            ref_bonds_style = {"display": "block"}
        
        return figure, title, ref_bonds_style
    except FileNotFoundError:
        empty_figure = {"data": [], "layout": {"title": "Error: The figure file does not exist."}}
        return empty_figure, "Error Loading Curves", {"display": "none"}


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
              Input("select-inst", "value"),
              Input("select-season", "value"),
              )
def statistics(interval, data_rt_js, stype, inst, season):
    thd = ZSCORE_ALERT_THRESHOLD
    if not data_rt_js:
        empty_layout = layout_stat(yunits.get(stype, "Z-score"))
        return go.Figure(data=[], layout=empty_layout)
    data_rt = json.loads(data_rt_js)

    if stype == 'InsPos':
        yunit = yunits[stype]
        df_ins = pd.DataFrame(data_rt[stype][inst])
        spread = df_ins[0].rename('Volume').replace(0, np.nan).dropna()
    else:
        if stype == 'NetBasis':
            df_raw = data_rt[stype][FuturesConfig.SEASONS[season]]
        else:
            df_raw = data_rt[stype]
        df_ = pd.DataFrame(df_raw)
        yunit = "Z-score"
        spread = df_[['spread', 'Zscore']].dropna()
        buy = spread[spread["Zscore"] >= thd].index
        sell = spread[spread["Zscore"] <= -thd].index
        spread.loc[buy, 'color'] = 'green'
        spread.loc[sell, 'color'] = 'red'
        spread['color'].fillna('grey', inplace=True)

    # Sort by index (ticker code) for better readability
    spread = spread.sort_index()
    
    trace = getTraceStat(spread,stype)
    layout = layout_stat(yunit)
    figure = go.Figure(data=[trace], layout=layout)
    figure.update_layout(clickmode='event+select')
    return figure


@app.callback(Output("graph-spread", "figure"),
              Input("spread-type", "value"),
              Input("select-inst", "value"),
              Input("select-season", "value"),
              Input("ticker", "children"),
              )
def spreadts(stype, inst, season, b):
    dfc = build_spread_series(b, inst, season, stype)
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

    # Explicitly scope yaxis2 (fixing overlay) and yaxis3 (CR 3m) ranges to the
    # visible x-window so both right axes scale to 1Y data, not full history.
    _axis_sources = [("yaxis2", trace_fs), ("yaxis3", trace_add)]
    for axis_key, traces in _axis_sources:
        if axis_key not in layout:
            continue
        _vals: List[float] = []
        _tag = "y2" if axis_key == "yaxis2" else "y3"
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
