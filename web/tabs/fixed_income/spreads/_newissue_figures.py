# -*- coding: utf-8 -*-
"""BondNewIssue Spread Time Series chart rendering."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objs as go

from ._futures_figures import fut_empty


def newissue_ts_figure(ticker_label: str):
    """Render canonical BondNewIssue stage time series (e.g. NIB_OTR-5Y).

    Plots the current episode's two specific bonds' full yield-spread
    history (back to whenever both first quote together), not just the
    days the pipeline's daily rank snapshot happened to label this exact
    pair as OTR/OFR1 -- a bond freshly promoted into that rank can hold
    it for only a day or two even though both legs have months of
    overlapping history under their previous ranks. A vertical marker
    shows where the rank pairing was actually confirmed, so the
    before/after can still be compared. Falls back to the rank-episode
    window only when the bond-level history lookup finds nothing.
    """
    from dateutil.relativedelta import relativedelta
    from settings.general import GeneralConfig
    from web.tabs.alpha.data import (
        load_spread_timeseries,
        to_newissue_stage_label,
        load_newissue_current_episode,
        load_newissue_pair_history,
    )

    ts = load_spread_timeseries('BondNewIssue')
    if not isinstance(ts, pd.DataFrame) or ts.empty:
        return fut_empty("Waiting for data: BondNewIssue...")

    def _best_default_column() -> str:
        ordered = [c for c in ts.columns if str(c).startswith('OTROFR1-')]
        if not ordered:
            ordered = list(ts.columns)
        return max(ordered, key=lambda c: int(pd.to_numeric(ts[c], errors='coerce').notna().sum()))

    actual_pair_id = ticker_label
    if actual_pair_id and ':' in str(actual_pair_id):
        ticker_label = to_newissue_stage_label(actual_pair_id)

    if not ticker_label or ticker_label not in ts.columns:
        ticker_label = _best_default_column()

    switch_date = None
    pair_label = None
    pair_history = load_newissue_pair_history(ticker_label)
    if pair_history is not None:
        s, pair_label, switch_date = pair_history
    else:
        s = None
    if s is None or s.empty:
        # load_newissue_pair_history's richer bond-level (cvpx.pkl) lookup
        # comes up empty for legs outside the standard pricing universe
        # (e.g. 30Y OFR-ladder bonds, capped at
        # BondConfig.PRICING_MAX_TTM=10.0) -- fall back to the newissue
        # universe's own rank-history series, which still carries the
        # current pair's leg codes for the title even though it only
        # covers the days this exact pair held the rank together.
        current_episode = load_newissue_current_episode(ticker_label)
        if current_episode is not None:
            s, pair_label = current_episode
        else:
            s = None
    if s is None or s.empty:
        # Legacy/unqualified label or fallback summary artifact: fall back
        # to the stitched cross-episode column rather than showing nothing.
        s = pd.to_numeric(ts[ticker_label], errors='coerce').dropna()
    if len(s) < 2 and str(ticker_label).startswith('NIBOTR-'):
        tenor = str(ticker_label).split('-', 1)[-1]
        fallback_col = f'OTROFR1-{tenor}'
        if fallback_col in ts.columns:
            fallback_pair_history = load_newissue_pair_history(fallback_col)
            if fallback_pair_history is not None:
                s, pair_label, switch_date = fallback_pair_history
            else:
                s = None
            if s is None or s.empty:
                fallback_current_episode = load_newissue_current_episode(fallback_col)
                if fallback_current_episode is not None:
                    s, pair_label = fallback_current_episode
                else:
                    s = None
            if s is None or s.empty:
                s = pd.to_numeric(ts[fallback_col], errors='coerce').dropna()
            ticker_label = fallback_col
    if s.empty:
        return fut_empty(f"No data for {ticker_label}")

    # Prefer the actual bond codes (e.g. "260016.IB vs 260010.IB") over
    # the generic stage/tenor label -- the label alone doesn't say which
    # specific bonds are being compared, and once you know the tenor/stage
    # from the ticker selector above the chart, it's redundant here.
    display_ticker = ticker_label
    if pair_label and '|' in pair_label:
        leg1_id, _, leg2_id = pair_label.partition('|')
        display_ticker = f"{leg1_id} vs {leg2_id}"

    mean = float(s.mean()) if len(s) else None
    vol = float(s.std(ddof=1)) if len(s) > 1 else None
    vmax = float(s.max()) if len(s) else None
    vmin = float(s.min()) if len(s) else None

    # Anchor the visible window to the episode's own start date rather than
    # a fixed calendar lookback -- a short-lived episode (e.g. a NIB from
    # a couple of weeks ago) should not be padded with empty axis space,
    # and a long-running stitched fallback series should still be capped.
    window = getattr(GeneralConfig, "STAT_WINDOW", 12)
    capped_start = s.index[-1] - relativedelta(months=window)
    start = max(s.index[0], capped_start)

    title = (
        f"<span style='font-size:20px'><b>{display_ticker}</b></span><br>"
        f"Latest: {float(s.iloc[-1]):.2f}bp, Mean: {mean:.2f}bp, "
        f"Vol: {(vol if vol is not None else float('nan')):.2f}bp, "
        f"Max: {vmax:.2f}bp, Min: {vmin:.2f}bp"
    )

    # Match the Treasury Bond (TBondCurve) spread chart's look: a bold
    # Z-score line on its own row with shaded +-1sigma/+-2sigma bands,
    # plus the raw spread on a second row below (see
    # web/core/graphs.py::spreadts / _split_zscore_subplot).
    from web.core.styles import getTrace, getZscoreTrace, layout_ts_line
    from web.core.graphs import _compute_y_range, _split_zscore_subplot

    if vol and vol > 0:
        zscore = ((s - mean) / vol).dropna()
    else:
        zscore = pd.Series(dtype=float)
    has_zscore = not zscore.empty

    if has_zscore:
        # getTrace() always demotes its series to the y5 axis, which only
        # exists in the layout when has_zscore=True (see layout_ts_line) --
        # so it must not be used to plot the spread on its own as a
        # primary-axis trace below.
        data = getZscoreTrace(zscore) + getTrace(s, 'BondNewIssue')
    else:
        data = [go.Scatter(name="Spread", x=s.index, y=s.values,
                            line={"width": 3, "color": "#2a6fd3"})]

    xrg = dict(start=start, end=s.index[-1])
    yrg = _compute_y_range('BondNewIssue', zscore if has_zscore else s, x_range=xrg)
    lineinfo = dict(start=start, end=s.index[-1], mean=mean, std=vol or 0.0)
    layout = layout_ts_line(title, 'bp', xrg, yrg, lineinfo, shape=True, has_zscore=has_zscore)

    fig = go.Figure(data=data, layout=layout) if not has_zscore else _split_zscore_subplot(data, layout)

    # Mark where the OTR/OFR1 (or NIB/OTR) rank pairing was actually
    # confirmed -- the plotted history extends earlier using the bonds'
    # own quote history (see load_newissue_pair_history), so this line
    # is the only visual cue for "before this date the pair wasn't yet
    # the official rank pairing."
    if switch_date is not None and start <= switch_date <= s.index[-1]:
        # add_vline's own annotation_position on a datetime x-axis raises
        # inside plotly's shapeannotation helper (int/Timestamp math), so
        # the line and its label are added separately.
        fig.add_vline(x=switch_date, line_width=1.5, line_dash="dash",
                      line_color="#aab0c0", row="all", col="all")
        fig.add_annotation(x=switch_date, y=1, yref="paper", yanchor="bottom",
                           text="rank confirmed", showarrow=False,
                           font=dict(size=9, color="#aab0c0"))
    return fig
