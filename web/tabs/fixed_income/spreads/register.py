# -*- coding: utf-8 -*-
"""Dash callback registration for the Spread Analysis tab. Thin wrapper:
figure/table construction lives in _futures_figures.py, _newissue_figures.py,
_seasonal_callback.py and _seasonal_stats_panels.py — this module only wires
Input/Output/State plus the handful of callbacks small enough to stay
inline (timestamp, header labels, click handling, realtime refresh)."""

from __future__ import annotations

import datetime
import json
import os
from typing import Mapping

import pandas as pd
from dash import html
from dash.dependencies import Input, Output, State

from settings.paths import DIR_INPUT

from ._pickle_cache import load_pickle_cached
from ._futures_figures import FUT_SPREADS, futures_bar_figure, futures_ts_figure
from ._newissue_figures import newissue_ts_figure
from ._seasonal_callback import update_seasonal

# Import plotting dependencies at module level to catch errors early
try:
    import plotly.graph_objs as go
    PLOTTING_AVAILABLE = True
except Exception as e:
    print(f"Warning: Plotting dependencies not available: {e}")
    PLOTTING_AVAILABLE = False
    go = None

# Try to import web.core modules (they might fail if data files are missing)
try:
    from web.core.graphs import statistics as orig_statistics
    from web.core.graphs import spreadts as orig_spreadts
    from web.core.scripts import refresh as orig_refresh
    GRAPHS_AVAILABLE = True
except Exception as e:
    print(f"Warning: web.core.graphs not available (data files may be missing): {e}")
    GRAPHS_AVAILABLE = False
    orig_statistics = None
    orig_spreadts = None
    orig_refresh = None


def _fit_to_frame(fig):
    """Strip any hardcoded height/width so the graph fills its container
    (dcc.Graph has responsive=True + height:100% on the Spread Time Series card).
    Accepts either a go.Figure or a plain {data, layout} dict (spreadts() returns the latter)."""
    try:
        if isinstance(fig, dict):
            layout = fig.setdefault("layout", {})
            layout["height"] = None
            layout["width"] = None
            layout["autosize"] = True
            layout["margin"] = dict(l=50, r=20, t=40, b=40)
        else:
            fig.update_layout(height=None, width=None, autosize=True,
                               margin=dict(l=50, r=20, t=40, b=40))
    except Exception:
        pass
    return fig


def _resolve_misc_or_tenor_spread_bar_data(stype, data_rt):
    """Fill data_rt[stype] from the static Misc-spds.pkl / Tenor-spds.pkl
    artifacts when the realtime payload doesn't already carry it. Returns
    the (possibly mutated) data_rt dict."""
    _misc_spd_key = {'BinarySpread': 'BinarySpread', 'SectorPCASpread': 'PCASpread'}.get(stype)
    if _misc_spd_key:
        try:
            import re as _re
            _misc_static = load_pickle_cached(os.path.join(DIR_INPUT, "Misc-spds.pkl"))
            if isinstance(_misc_static, Mapping):
                _bucket = _misc_static.get(_misc_spd_key, {})
                if isinstance(_bucket, dict):
                    _spread = _bucket.get('Spread')
                    _stat = _bucket.get('StatInfo')
                    if isinstance(_spread, pd.DataFrame) and isinstance(_stat, pd.DataFrame) and not _spread.empty:
                        _current = _spread.iloc[-1].rename('spread').to_frame()
                        _stat_cols = ['mean', 'vol'] + (['ewm_vol'] if 'ewm_vol' in _stat.columns else [])
                        _current = _current.join(_stat[_stat_cols], how='inner')
                        # Prefer EWMA(span=60) vol (matches Spread Time Series chart's
                        # Z-score convention); fall back to static full-window vol.
                        _vol = pd.to_numeric(_current.get('ewm_vol'), errors='coerce') if 'ewm_vol' in _current.columns else None
                        _static_vol = pd.to_numeric(_current['vol'], errors='coerce')
                        _vol = _vol.fillna(_static_vol) if _vol is not None else _static_vol
                        _vol = _vol.replace(0, float('nan'))
                        _current['Zscore'] = (pd.to_numeric(_current['spread'], errors='coerce') - pd.to_numeric(_current['mean'], errors='coerce')) / _vol
                        _current['color'] = 'grey'
                        if stype == 'SectorPCASpread':
                            _current.index = [_re.sub(r'(-\d+)\.0(Y)$', r'\1\2', idx) for idx in _current.index]
                        data_rt[stype] = _current.to_dict()
        except Exception:
            pass
    if stype == 'TenorSpread':
        try:
            _tenor_static = load_pickle_cached(os.path.join(DIR_INPUT, 'Tenor-spds.pkl'))
            if isinstance(_tenor_static, Mapping) and 'TenorSpread' in _tenor_static:
                _ts = _tenor_static['TenorSpread']
                if isinstance(_ts, dict):
                    _spread = _ts.get('Spread')
                    _stat = _ts.get('StatInfo')
                    if (isinstance(_spread, pd.DataFrame) and not _spread.empty
                            and isinstance(_stat, pd.DataFrame) and not _stat.empty):
                        _current = _spread.iloc[-1].rename('spread').to_frame()
                        _stat_cols = ['mean', 'vol'] + (['ewm_vol'] if 'ewm_vol' in _stat.columns else [])
                        _current = _current.join(_stat[_stat_cols], how='inner')
                        # Prefer EWMA(span=60) vol (matches Spread Time Series chart's
                        # Z-score convention); fall back to static full-window vol.
                        _vol = pd.to_numeric(_current.get('ewm_vol'), errors='coerce') if 'ewm_vol' in _current.columns else None
                        _static_vol = pd.to_numeric(_current['vol'], errors='coerce')
                        _vol = _vol.fillna(_static_vol) if _vol is not None else _static_vol
                        _vol = _vol.replace(0, float('nan'))
                        _mean = pd.to_numeric(_current['mean'], errors='coerce')
                        _current['Zscore'] = (pd.to_numeric(_current['spread'], errors='coerce') - _mean) / _vol
                        _current['color'] = 'grey'
                        data_rt['TenorSpread'] = _current.to_dict()
        except Exception:
            pass
    return data_rt


def register_spreads_callbacks(app) -> None:
    """Register the callbacks required by `build_spreads_layout()` onto `app`."""

    # Realtime data refresh callback
    @app.callback(
        Output("realtime-data", "data"),
        Input("data-refresh", "n_intervals"),
        Input("alpha-spread-refresh-btn", "n_clicks"),
    )
    def _refresh_realtime_data(interval, _refresh_clicks):
        """Load realtime spread data using the core script."""
        if not GRAPHS_AVAILABLE or orig_refresh is None:
            print("Realtime data refresh skipped: web.core.scripts not available")
            return "{}"
        try:
            return orig_refresh(interval)
        except Exception as e:
            print(f"Error refreshing realtime data via core script: {e}")
            import traceback
            traceback.print_exc()
            return "{}"

    # Spreads callbacks
    @app.callback(
        Output("alpha-spread-updated-at", "children"),
        Input("data-refresh", "n_intervals"),
        Input("spread-type", "value"),
        Input("alpha-spread-refresh-btn", "n_clicks"),
    )
    def _update_spread_timestamp(_interval, _stype, _refresh_clicks):
        return f"Updated: {datetime.datetime.now().strftime('%H:%M:%S')}"

    @app.callback(
        Output("spread-seasonal-stats-title", "children"),
        Output("spread-seasonal-stats-badge", "children"),
        Input("spread-type", "value"),
    )
    def _update_seasonal_stats_header(stype):
        if stype == 'BondNewIssue':
            return "Issuance Statistics", "Days since issuance/roll"
        if stype == 'TermBasis':
            return "Roll Statistics", "Days to front-contract maturity"
        return "Monthly Statistics", "Directional bias"

    @app.callback(
        Output("graph-spread-bar", "figure"),
        Input("data-refresh", "n_intervals"),
        Input("realtime-data", "data"),
        Input("spread-type", "value"),
        Input("alpha-spread-refresh-btn", "n_clicks"),
    )
    def _update_spread_bar(interval, data_rt_js, stype, _refresh_clicks):
        """Update the spread bar chart."""
        if not PLOTTING_AVAILABLE or go is None:
            # Return a simple dict-based figure if plotly isn't available
            return {"data": [], "layout": {"title": "Plotting not available"}}

        if not GRAPHS_AVAILABLE or orig_statistics is None:
            return go.Figure(data=[], layout=dict(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                title="Data files not loaded. Please run EOD job to generate data."
            ))

        try:
            # Futures spreads render directly from futures-spds.pkl (new pipeline).
            if stype in FUT_SPREADS:
                return futures_bar_figure(stype)

            # Check if key exists in data to avoid KeyError
            if data_rt_js:
                data_rt = json.loads(data_rt_js)
                # Handle special cases consistent with web.core.graphs.statistics
                if stype == 'NetBasis':
                    if 'NetBasis' not in data_rt:
                        raise KeyError(f"Data not available for {stype}")
                elif stype not in data_rt or data_rt.get(stype) is None:
                    data_rt = _resolve_misc_or_tenor_spread_bar_data(stype, data_rt)
                    if stype not in data_rt or data_rt.get(stype) is None:
                        # Return a friendly empty chart instead of crashing
                        return go.Figure(data=[], layout=dict(
                            plot_bgcolor="rgba(0,0,0,0)",
                            paper_bgcolor="rgba(0,0,0,0)",
                            title=f"Waiting for data: {stype}..."
                        ))
                    data_rt_js = json.dumps(data_rt)

            # Forward real data to original implementation
            return orig_statistics(interval, data_rt_js, stype, None)
        except Exception as e:
            print(f"Error in _update_spread_bar: {e}")
            import traceback
            traceback.print_exc()
            empty_figure = go.Figure(data=[], layout=dict(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                title=f"Error: {str(e)[:100]}"
            ))
            return empty_figure

    @app.callback(
        Output("ticker", "children", allow_duplicate=True),
        Output("ticker-id", "data", allow_duplicate=True),
        Input("graph-spread-bar", "clickData"),
        State("spread-type", "value"),
        prevent_initial_call=True,
    )
    def _display_click_data(clickData, stype):
        """Handle click events on spread bar chart."""
        from dash.exceptions import PreventUpdate
        if not clickData or "points" not in clickData or not clickData["points"]:
            raise PreventUpdate
        point = clickData["points"][0]
        customdata = point.get("customdata")
        if isinstance(customdata, (list, tuple)) and customdata:
            ticker = customdata[0]
        elif customdata is not None:
            ticker = customdata
        else:
            ticker = point.get("x")
            if ticker is None:
                ticker = point.get("label")
        if not ticker:
            raise PreventUpdate
        # TBondCurve/CBondCurve OFR-ladder pair rows (ID = "ofrk_id|ofr1_id",
        # no ":" -- unlike BondNewIssue's "tenor:stage:leg1|leg2" IDs) display
        # as "ofrk_id (vs ofr1_id)" -- the OFR1 leg can change identity over
        # the calibration window (see otr_ofr_rv.py's CalibrationSpread
        # fallback), so naming today's actual reference bond is useful
        # context, not redundant restatement.
        if (stype in ('TBondCurve', 'CBondCurve') and isinstance(ticker, str)
                and '|' in ticker and ':' not in ticker):
            ofrk_id, _, ofr1_id = ticker.partition('|')
            display_label = f"{ofrk_id} (vs {ofr1_id})" if ofr1_id else ofrk_id
        elif stype == 'BondNewIssue' and isinstance(ticker, str) and ':' in ticker:
            from web.tabs.alpha.data import to_newissue_stage_label
            display_label = to_newissue_stage_label(ticker)
        else:
            display_label = ticker
        return display_label, ticker

    @app.callback(
        Output("graph-spread", "figure"),
        Input("spread-type", "value"),
        Input("ticker-id", "data"),
    )
    def _update_spread_ts(stype, ticker):
        """Update the spread time series chart."""
        if not PLOTTING_AVAILABLE or go is None:
            return {"data": [], "layout": {"title": "Plotting not available"}}

        if not GRAPHS_AVAILABLE or orig_spreadts is None:
            return _fit_to_frame(go.Figure(data=[], layout=dict(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                title="Data files not loaded. Please run EOD job to generate data."
            )))

        try:
            # Futures spreads render directly from futures-spds.pkl (new pipeline).
            # These default to the first contract type when no bar is clicked yet.
            if stype in FUT_SPREADS:
                return _fit_to_frame(futures_ts_figure(stype, ticker))

            if stype == 'BondNewIssue':
                return _fit_to_frame(newissue_ts_figure(ticker))

            # Handle empty/None ticker gracefully
            if not ticker:
                return _fit_to_frame(go.Figure(data=[], layout=dict(
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    title="Please select a ticker from the bar chart above"
                )))
            return _fit_to_frame(orig_spreadts(stype, None, ticker))
        except Exception as e:
            print(f"Error in _update_spread_ts: {e}")
            import traceback
            traceback.print_exc()
            empty_figure = go.Figure(data=[], layout=dict(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                title=f"Error: {str(e)[:100]}"
            ))
            return _fit_to_frame(empty_figure)

    # Seasonal overlay callback
    @app.callback(
        [
            Output("graph-spread-seasonal", "figure"),
            Output("spread-seasonal-stats", "children"),
        ],
        Input("spread-type", "value"),
        Input("ticker-id", "data"),
        Input("seasonal-highlight-month", "value"),
        Input("seasonal-years", "value"),
    )
    def _update_seasonal(stype, ticker, highlight_month, n_years):
        return update_seasonal(stype, ticker, highlight_month, n_years)
