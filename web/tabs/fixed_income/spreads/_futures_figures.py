# -*- coding: utf-8 -*-
"""Futures spread rendering (Bond-Futures / Term Basis / Futures-Swap).

These three read directly from futures-spds.pkl (derived from
futures-analytics.pkl by StatGenerator.compute_futures_stats).  Their spreads
are already in their natural units (bp for IRR−Repo, FYTM−IRS, and the
calendar Term Basis, which is a yield/FYTM spread; the raw price basis
is a separate pts-denominated overlay, see PriceBasis below), so they are
rendered here instead of the legacy season-keyed graphs path which assumes
%-stored spreads (×100 → bp).
"""

from __future__ import annotations

import os

import pandas as pd
import plotly.graph_objs as go

from settings.paths import DIR_INPUT

from ._pickle_cache import load_pickle_cached

FUT_SPREADS = {"NetBasis", "TermBasis", "FuturesSwap"}
FUT_UNIT = {"NetBasis": "bp", "FuturesSwap": "bp", "TermBasis": "bp"}
FUT_TITLE = {
    "NetBasis":    "Cash-and-Carry (IRR − Repo)",
    "FuturesSwap": "Futures Swap (FYTM − IRS)",
    "TermBasis":   "Calendar Spread (Front FYTM − Next FYTM)",
}
FUT_ZTHD = 2.0


def _fnum(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def fut_stat_bucket(stype):
    """Return {ticker: (spread_series, mean, vol, max, min, ewm_vol, extra)} for a futures type.

    StatInfo here is already bp-scaled (compute_futures_stats calibrates
    OU_calibrate directly on the bp spread), unlike web/core/styles.getInfo's
    percent-scaled StatInfo -- no ×100 needed for ewm_vol.

    ``extra`` is a dict of type-specific extras, empty for NetBasis/FuturesSwap.
    For TermBasis it carries: price_basis (Series, price points),
    front_contract/next_contract (contract codes), roll_progress (Series, 0..1).
    """
    spd = load_pickle_cached(os.path.join(DIR_INPUT, "futures-spds.pkl")) or {}
    out = {}
    if stype in ("NetBasis", "FuturesSwap"):
        bucket = spd.get(stype, {})
        if isinstance(bucket, dict):
            for tk, d in bucket.items():
                if not isinstance(d, dict):
                    continue
                si, sp = d.get("StatInfo"), d.get("Spread")
                if not isinstance(si, pd.DataFrame) or not isinstance(sp, pd.DataFrame):
                    continue
                if si.empty or sp.empty or tk not in si.index:
                    continue
                s = pd.to_numeric(sp.iloc[:, 0], errors="coerce").dropna()
                if s.empty:
                    continue
                out[tk] = (s, _fnum(si.loc[tk, "mean"]), _fnum(si.loc[tk, "vol"]),
                           _fnum(si.loc[tk, "max"]), _fnum(si.loc[tk, "min"]),
                           _fnum(si.loc[tk, "ewm_vol"]) if "ewm_vol" in si.columns else None,
                           {})
    elif stype == "TermBasis":
        tb = spd.get("TermBasis", {})
        si = tb.get("StatInfo") if isinstance(tb, dict) else None
        sp = tb.get("Spread") if isinstance(tb, dict) else None
        pb = tb.get("PriceBasis") if isinstance(tb, dict) else None
        rp = tb.get("RollProgress") if isinstance(tb, dict) else None
        dtm = tb.get("DaysToMaturity") if isinstance(tb, dict) else None
        if isinstance(si, pd.DataFrame) and isinstance(sp, pd.DataFrame) and not si.empty:
            for tk in si.index:
                if tk not in sp.columns:
                    continue
                s = pd.to_numeric(sp[tk], errors="coerce").dropna()
                if s.empty:
                    continue
                extra = {}
                if "front_contract" in si.columns:
                    extra["front_contract"] = si.loc[tk, "front_contract"]
                if "next_contract" in si.columns:
                    extra["next_contract"] = si.loc[tk, "next_contract"]
                if isinstance(pb, pd.DataFrame) and tk in pb.columns:
                    pb_s = pd.to_numeric(pb[tk], errors="coerce").dropna()
                    if not pb_s.empty:
                        extra["price_basis"] = pb_s
                if isinstance(rp, pd.DataFrame) and tk in rp.columns:
                    rp_s = pd.to_numeric(rp[tk], errors="coerce").dropna()
                    if not rp_s.empty:
                        extra["roll_progress"] = rp_s
                if isinstance(dtm, pd.DataFrame) and tk in dtm.columns:
                    dtm_s = pd.to_numeric(dtm[tk], errors="coerce").dropna()
                    if not dtm_s.empty:
                        extra["days_to_maturity"] = dtm_s
                out[tk] = (s, _fnum(si.loc[tk, "mean"]), _fnum(si.loc[tk, "vol"]),
                           _fnum(si.loc[tk, "max"]), _fnum(si.loc[tk, "min"]),
                           _fnum(si.loc[tk, "ewm_vol"]) if "ewm_vol" in si.columns else None,
                           extra)
    return out


def fut_empty(title):
    return go.Figure(data=[], layout=dict(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        title=title,
    ))


def futures_bar_figure(stype):
    bucket = fut_stat_bucket(stype)
    if not bucket:
        return fut_empty(f"Waiting for data: {stype}...")
    unit = FUT_UNIT[stype]
    rows = []
    for tk in sorted(bucket):
        s, mean, vol, _, _, ewm_vol, _ = bucket[tk]
        last = float(s.iloc[-1])
        zvol = ewm_vol if ewm_vol else vol
        z = (last - mean) / zvol if (mean is not None and zvol) else None
        color = "grey"
        if z is not None and z >= FUT_ZTHD:
            color = "green"
        elif z is not None and z <= -FUT_ZTHD:
            color = "red"
        rows.append((tk, last, z, color))
    trace = go.Bar(
        x=[r[0] for r in rows],
        y=[r[2] for r in rows],
        marker=dict(color=[r[3] for r in rows]),
        hovertext=[f"Spread: {r[1]:.2f}{unit}" for r in rows],
        name="Zscore",
    )
    try:
        from web.core.styles import layout_stat
        layout = layout_stat("Z-score")
    except Exception:
        layout = dict(plot_bgcolor="rgba(0,0,0,0)",
                      paper_bgcolor="rgba(0,0,0,0)",
                      font=dict(color="#ffffff"), yaxis=dict(title="Z-score"))
    fig = go.Figure(data=[trace], layout=layout)
    fig.update_layout(clickmode="event+select")
    return fig


def futures_ts_figure(stype, ticker):
    from dateutil.relativedelta import relativedelta
    from settings.general import GeneralConfig
    bucket = fut_stat_bucket(stype)
    if not bucket:
        return fut_empty(f"Waiting for data: {stype}...")
    if ticker not in bucket:
        ticker = sorted(bucket)[0]   # default to first when none clicked yet
    s, mean, vol, vmax, vmin, ewm_vol, extra = bucket[ticker]
    unit = FUT_UNIT[stype]
    window = getattr(GeneralConfig, "STAT_WINDOW", 12)
    start = s.index[-1] - relativedelta(months=window)

    # TermBasis's Spread series is stitched across every historical
    # quarterly roll (T→TF, TL2609|2612, TL2612|2703, ...), so a fixed
    # calendar lookback shows several unrelated contract pairs concatenated
    # together. Clip both the plotted series and the window start to the
    # current pair's own start (last DTM roll-up jump), same idea as the
    # BondNewIssue episode window below -- clipping only xaxis.range would
    # still leave the older pairs' data reachable via hover/zoom.
    if stype == "TermBasis":
        dtm_s = extra.get("days_to_maturity")
        if isinstance(dtm_s, pd.Series) and not dtm_s.empty:
            _jump = dtm_s.diff() > 0
            if _jump.any():
                cycle_start = dtm_s.index[_jump][-1]
                start = max(start, cycle_start)
                s = s.loc[s.index >= cycle_start]

    # Z-score = (spread - mean) / ewm_vol is the primary entry/exit signal
    # for a mean-reversion trade -- EWMA(span=60) vol tracks the current
    # regime instead of a static full-window blend (see OU_calibrate).
    # Promoted to the primary axis; the raw spread is demoted below.
    # Same layout/shading/subplot-split as the Treasury Bond (TBondCurve)
    # and BondNewIssue Spread Time Series charts -- see
    # web/core/graphs.py::spreadts / _split_zscore_subplot.
    from web.core.styles import getTrace, getZscoreTrace, layout_ts_line
    from web.core.graphs import _compute_y_range, _split_zscore_subplot

    zvol = ewm_vol if ewm_vol else vol
    zscore = ((s - mean) / zvol).dropna() if (mean is not None and zvol) else None
    has_zscore = zscore is not None and not zscore.empty

    if has_zscore:
        # getTrace() always demotes its series to the y5 axis, which only
        # exists in the layout when has_zscore=True (see layout_ts_line) --
        # so it must not be used to plot the spread on its own as a
        # primary-axis trace below.
        traces = getZscoreTrace(zscore) + getTrace(s, stype)
    else:
        traces = [go.Scatter(name="Spread (bp)", x=s.index, y=s.values,
                              line={"width": 3, "color": "#2a6fd3"})]

    # For NetBasis: overlay IRR and Repo (%) on a secondary y-axis
    # For TermBasis: overlay the raw price basis (pts) and OI roll-progress (0-1)
    _yaxis2 = None
    _yaxis3 = None
    if stype == "TermBasis":
        price_basis = extra.get("price_basis")
        if isinstance(price_basis, pd.Series) and not price_basis.empty:
            _pb = price_basis.loc[price_basis.index >= start]
            if not _pb.empty:
                traces.append(go.Scatter(
                    name="Price basis (pts)", x=_pb.index, y=_pb.values,
                    line={"width": 1.5, "color": "#2ecc71", "dash": "dot"},
                    yaxis="y2",
                ))
                _yaxis2 = dict(title="pts", overlaying="y", side="right",
                               position=0.93,
                               showgrid=False, zeroline=False,
                               tickfont=dict(color="#2ecc71"), title_font=dict(color="#2ecc71"))
        roll_progress = extra.get("roll_progress")
        if isinstance(roll_progress, pd.Series) and not roll_progress.empty:
            _rp = roll_progress.loc[roll_progress.index >= start]
            if not _rp.empty:
                traces.append(go.Scatter(
                    name="Roll progress (next OI share)", x=_rp.index, y=_rp.values,
                    line={"width": 1.5, "color": "#e05c5c", "dash": "dashdot"},
                    yaxis="y3",
                ))
                _yaxis3 = dict(title="OI share", overlaying="y", side="right",
                               position=0.86, range=[0, 1],
                               showgrid=False, zeroline=False,
                               tickfont=dict(color="#e05c5c"), title_font=dict(color="#e05c5c"))
    if stype == "NetBasis":
        try:
            from settings.futures import FuturesConfig
            _ana = load_pickle_cached(os.path.join(DIR_INPUT, "futures-analytics.pkl")) or {}
            _dbpx = load_pickle_cached(os.path.join(DIR_INPUT, "database-px.pkl")) or {}
            _df_ana = _ana.get(ticker)
            if isinstance(_df_ana, pd.DataFrame) and "irr" in _df_ana.columns:
                _irr = pd.to_numeric(_df_ana["irr"], errors="coerce")
                _irr = _irr.where(_irr >= -0.5).dropna()
                _irr.index = pd.DatetimeIndex(_irr.index)
                _irr = _irr.loc[start:]
                if not _irr.empty:
                    traces.append(go.Scatter(
                        name="IRR (%)", x=_irr.index, y=_irr.values,
                        line={"width": 1.5, "color": "#f39c12", "dash": "dot"},
                        yaxis="y2",
                    ))
            _irs_df = _dbpx.get("IRS") if isinstance(_dbpx, dict) else None
            if isinstance(_irs_df, pd.DataFrame) and "FR007.IR" in _irs_df.columns:
                _funding = FuturesConfig.FUNDING_BASIS_BP / 100.0
                _repo = pd.to_numeric(_irs_df["FR007.IR"], errors="coerce").dropna()
                _repo.index = pd.DatetimeIndex(_repo.index)
                _repo = (_repo + _funding).loc[start:]
                if not _repo.empty:
                    traces.append(go.Scatter(
                        name=f"Repo FR007+{FuturesConfig.FUNDING_BASIS_BP:.0f}bp (%)",
                        x=_repo.index, y=_repo.values,
                        line={"width": 1.5, "color": "#2ecc71", "dash": "dot"},
                        yaxis="y2",
                    ))
            _yaxis2 = dict(title="%", overlaying="y", side="right",
                           showgrid=False, zeroline=False,
                           tickfont=dict(color="#aaaaaa"), title_font=dict(color="#aaaaaa"))
        except Exception:
            pass

    _fmt = lambda v: f"{v:.2f}{unit}" if v is not None else "NA"
    _label = ticker
    if stype == "TermBasis":
        _front, _next = extra.get("front_contract"), extra.get("next_contract")
        if isinstance(_front, str) and isinstance(_next, str) and _front and _next:
            _label = f"{_front.replace('.CFE', '')}|{_next.replace('.CFE', '')}"
    title = (f"<b>{FUT_TITLE[stype]} — {_label}</b><br>"
             f"Latest: {_fmt(float(s.iloc[-1]))}, Mean: {_fmt(mean)}, "
             f"Vol: {_fmt(vol)}, Max: {_fmt(vmax)}, Min: {_fmt(vmin)}")

    xrg = dict(start=start, end=s.index[-1])
    yrg = _compute_y_range(stype, zscore if has_zscore else s, x_range=xrg)
    lineinfo = dict(start=start, end=s.index[-1], mean=mean or 0.0, std=vol or 0.0)
    layout = layout_ts_line(title, unit, xrg, yrg, lineinfo, shape=True, has_zscore=has_zscore)
    if _yaxis2 is not None:
        layout["yaxis2"] = _yaxis2
    if _yaxis3 is not None:
        layout["yaxis3"] = _yaxis3
    layout["showlegend"] = True
    layout["legend"] = dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=11))

    if not has_zscore:
        return go.Figure(data=traces, layout=layout)

    return _split_zscore_subplot(traces, layout)
