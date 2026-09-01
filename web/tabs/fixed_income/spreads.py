"""Spread Analysis tab (Alpha Book > Spread subtab).

Provides `build_spreads_layout()` and `register_spreads_callbacks(app)` for the
legacy "Spread Analysis" dashboard content, migrated from `web.core.content`
onto the AtlasNexus Dash app instance.

This module intentionally keeps imports local to functions and tries hard to
avoid triggering heavy data loads from `web.core.load`.
"""

from __future__ import annotations

from dash import dcc, html
from dash.dependencies import Input, Output, State

from .common import _fi_card_header


def build_spreads_layout():
    """Build the 'Spread Analysis' layout (Alpha Book > Spread subtab)."""
    # Local imports to keep module import light
    from settings.fixed_income import InstitutionConfig
    from settings.futures import FuturesConfig
    from web.core.styles import app_color  # styles only; ok

    GRAPH_INTERVAL_LONG = 300_000

    _label_style = {
        'color': 'var(--text-muted)', 'fontSize': '9px', 'fontWeight': '600',
        'textTransform': 'uppercase', 'letterSpacing': '0.06em',
        'marginBottom': '4px', 'display': 'block',
    }

    # Dropdown options for spread type with disabled group headers
    _spread_options = [
        {"label": "— Sectors —",           "value": "__sectors__",  "disabled": True},
        {"label": "Curve & Cross-Asset Spreads", "value": "TenorSpread"},
        {"label": "Sector PCA",             "value": "SectorPCASpread"},
        {"label": "— Bonds —",             "value": "__bonds__",    "disabled": True},
        {"label": "Treasury Bond",          "value": "TBondCurve"},
        {"label": "Policybank Bond",        "value": "CBondCurve"},
        {"label": "New-Issue OTR/OFR Event", "value": "BondNewIssue"},
        {"label": "Local Treasury Bond",    "value": "LBondSpread"},
        {"label": "Corporate Bank Bond",    "value": "BBondSpread"},
        {"label": "Government-backed Bond", "value": "GBondSpread"},
        {"label": "Medium Term Note",       "value": "MNoteSpread"},
        {"label": "— Swaps —",             "value": "__swaps__",    "disabled": True},
        {"label": "Swaps",                  "value": "SwapSpread"},
        {"label": "Treasury BondSwap",      "value": "TBondSwap"},
        {"label": "Policybank BondSwap",    "value": "CBondSwap"},
        {"label": "— Futures —",           "value": "__futures__",  "disabled": True},
        {"label": "Bond Futures Basis",     "value": "NetBasis"},
        {"label": "Futures Term Basis",     "value": "TermBasis"},
        {"label": "Futures Swap",           "value": "FuturesSwap"},
    ]

    _DD_STYLE = {"fontSize": "11px", "color": "var(--text-primary)"}

    return html.Div([
        dcc.Store(id="realtime-data"),
        dcc.Interval(id="data-refresh-long", interval=int(GRAPH_INTERVAL_LONG), n_intervals=0),

        html.Div([
            html.H1("Spread Analysis", style={
                'margin': '0 0 3px', 'fontSize': '20px', 'fontWeight': '600',
                'color': 'var(--text-primary)',
            }),
            html.Div(
                "Time series, seasonal patterns, and daily statistics",
                style={'fontSize': '11px', 'color': 'var(--text-muted)'},
            ),
        ], style={'marginBottom': '4px'}),

        # ── Top row: Controls (left) + Daily Spread Statistics + Spread Time Series (right) ──
        html.Div([
            # Controls card — narrow, fixed width
            html.Div([
                _fi_card_header("Controls"),
                html.Div([
                    html.Div([
                        html.Label("Spread Type", style=_label_style),
                        dcc.Dropdown(
                            options=_spread_options,
                            value="TenorSpread",
                            id="spread-type",
                            clearable=False,
                            style=_DD_STYLE,
                        ),
                    ]),
                    html.Div([
                        html.Label("Seasonal Highlight Month", style=_label_style),
                        dcc.Dropdown(
                            options=[
                                {"label": m, "value": i + 1}
                                for i, m in enumerate([
                                    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
                                ])
                            ],
                            value=__import__("datetime").date.today().month,
                            id="seasonal-highlight-month",
                            clearable=True,
                            placeholder="None",
                            style=_DD_STYLE,
                        ),
                    ]),
                    html.Div([
                        html.Label("Seasonal Years", style=_label_style),
                        dcc.Dropdown(
                            options=[
                                {"label": "3 years", "value": 3},
                                {"label": "5 years", "value": 5},
                                {"label": "8 years", "value": 8},
                                {"label": "All", "value": 20},
                            ],
                            value=5,
                            id="seasonal-years",
                            clearable=False,
                            style=_DD_STYLE,
                        ),
                    ]),
                    html.Button(
                        "↻ Refresh", id="alpha-spread-refresh-btn", n_clicks=0,
                        style={'padding': '6px 12px', 'background': 'var(--accent-amber)', 'color': 'var(--navy-950)',
                               'border': 'none', 'borderRadius': '4px', 'fontSize': '10px', 'fontWeight': '700',
                               'cursor': 'pointer', 'width': '100%'},
                    ),
                    html.Div(id="alpha-spread-updated-at", style={'fontSize': '8px', 'color': 'var(--text-muted)'}),
                ], style={'padding': '12px 14px', 'display': 'flex', 'flexDirection': 'column', 'gap': '12px'}),
            ], style={'width': '220px', 'flexShrink': '0', 'border': '1px solid var(--border-strong)',
                      'borderRadius': '8px', 'overflow': 'hidden'}),

            # Daily Spread Statistics + Spread Time Series (stacked vertically on right)
            html.Div([
                # Daily Spread Statistics
                html.Div([
                    _fi_card_header("Daily Spread Statistics", badge_text="Z-score distribution · pick spreads below"),
                    html.Div(
                        dcc.Graph(
                            id="graph-spread-bar",
                            figure=dict(layout=dict(
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                            )),
                            config={"displayModeBar": False},
                            style={'padding': '12px 16px', 'height': '350px'},
                        ),
                    ),
                ], style={'border': '1px solid var(--border-strong)', 'borderRadius': '8px', 'overflow': 'hidden',
                          'backgroundColor': 'transparent', 'flex': '1'}),

                # Spread Time Series
                html.Div([
                    _fi_card_header("Spread Time Series"),
                    html.Div(id="ticker", className="graph__title", style={'padding': '8px 16px 0'}),
                    html.Div(
                        dcc.Graph(
                            id="graph-spread",
                            figure=dict(layout=dict(
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                                autosize=True,
                            )),
                            config={"displayModeBar": False, "responsive": True},
                            style={'height': '100%', 'width': '100%'},
                        ),
                        # Now a 2-row subplot (Z-score + spread/overlays, each on
                        # its own axis — see _split_zscore_subplot in
                        # web/core/graphs.py); 350px was already tight for one
                        # panel, so two legible rows need more headroom.
                        style={'padding': '8px', 'height': '520px'},
                    ),
                ], style={'border': '1px solid var(--border-strong)', 'borderRadius': '8px', 'overflow': 'hidden',
                          'backgroundColor': 'transparent', 'flex': '1'}),
            ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '10px', 'flex': '1', 'minWidth': '0'}),
        ], style={'display': 'flex', 'gap': '12px', 'alignItems': 'flex-start'}),

        # ── Seasonal Pattern (right) + Monthly Statistics (left, narrower) ─────
        html.Div([
            # Monthly Statistics / Issuance Statistics (BondNewIssue) — left, narrower
            html.Div([
                html.Div([
                    html.Span(id="spread-seasonal-stats-title", children="Monthly Statistics",
                              style={'fontSize': '13px', 'fontWeight': '600', 'color': 'var(--text-primary)'}),
                    html.Span(id="spread-seasonal-stats-badge", children="Directional bias", style={
                        'fontSize': '9px', 'color': 'var(--text-muted)', 'background': 'var(--surface-input)',
                        'padding': '2px 7px', 'borderRadius': '3px', 'border': '1px solid var(--border-default)',
                    }),
                ], style={'display': 'flex', 'alignItems': 'center', 'gap': '10px',
                          'padding': '11px 16px', 'background': 'var(--surface-panel)',
                          'borderBottom': '1px solid var(--border-strong)'}),
                html.Div(id="spread-seasonal-stats", style={'padding': '12px 16px', 'overflow': 'auto', 'maxHeight': '340px'}),
            ], style={'flex': '0 0 300px', 'border': '1px solid var(--border-strong)', 'borderRadius': '8px',
                      'overflow': 'hidden', 'backgroundColor': 'transparent'}),

            # Seasonal Pattern — right, flex 1
            html.Div([
                _fi_card_header("Seasonal Pattern", badge_text="Year-over-year overlay"),
                dcc.Graph(
                    id="graph-spread-seasonal",
                    figure=dict(layout=dict(
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                    )),
                    config={"displayModeBar": False},
                    style={"height": "340px", 'padding': '8px'},
                ),
            ], style={'flex': '1', 'minWidth': '0', 'border': '1px solid var(--border-strong)',
                      'borderRadius': '8px', 'overflow': 'hidden', 'backgroundColor': 'transparent'}),
        ], style={'display': 'flex', 'gap': '12px', 'alignItems': 'stretch'}),

    ], style={'padding': '10px', 'display': 'flex', 'flexDirection': 'column', 'gap': '10px'})


def register_spreads_callbacks(app) -> None:
    """Register the callbacks required by `build_spreads_layout()` onto `app`."""
    from dash import callback_context
    import datetime
    import json
    import os
    import pickle
    import pandas as pd
    from settings.paths import DIR_INPUT

    # Import plotting dependencies at function level to catch errors early
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

    # Pickle cache to avoid redundant file loads
    _PICKLE_CACHE: dict[str, tuple[float, object]] = {}

    def _load_pickle_cached(path_obj):
        """Load pickle with caching based on file mtime."""
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

    # ── Futures spread rendering (Bond-Futures / Term Basis / Futures-Swap) ──────
    # These three read directly from futures-spds.pkl (derived from
    # futures-analytics.pkl by StatGenerator.compute_futures_stats).  Their spreads
    # are already in their natural units (bp for IRR−Repo and FYTM−IRS, price
    # points for the calendar Term Basis), so we render them here instead of the
    # legacy season-keyed graphs path which assumes %-stored spreads (×100 → bp).
    _FUT_SPREADS = {"NetBasis", "TermBasis", "FuturesSwap"}
    _FUT_UNIT = {"NetBasis": "bp", "FuturesSwap": "bp", "TermBasis": "pts"}
    _FUT_TITLE = {
        "NetBasis":    "Bond Futures Basis (IRR − Repo)",
        "FuturesSwap": "Futures Swap (FYTM − IRS)",
        "TermBasis":   "Futures Term Basis (Front − Next)",
    }
    _FUT_ZTHD = 2.0

    def _fnum(v):
        try:
            f = float(v)
            return f if f == f else None
        except (TypeError, ValueError):
            return None

    def _fut_stat_bucket(stype):
        """Return {ticker: (spread_series, mean, vol, max, min, ewm_vol, extra)} for a futures type.

        StatInfo here is already bp-scaled (compute_futures_stats calibrates
        OU_calibrate directly on the bp spread), unlike web/core/styles.getInfo's
        percent-scaled StatInfo -- no ×100 needed for ewm_vol.

        ``extra`` is a dict of type-specific extras, empty for NetBasis/FuturesSwap.
        For TermBasis it carries: price_basis (Series, price points),
        front_contract/next_contract (contract codes), roll_progress (Series, 0..1).
        """
        spd = _load_pickle_cached(os.path.join(DIR_INPUT, "futures-spds.pkl")) or {}
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

    def _fut_empty(title):
        return go.Figure(data=[], layout=dict(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            title=title,
        ))

    def _futures_bar_figure(stype):
        bucket = _fut_stat_bucket(stype)
        if not bucket:
            return _fut_empty(f"Waiting for data: {stype}...")
        unit = _FUT_UNIT[stype]
        rows = []
        for tk in sorted(bucket):
            s, mean, vol, _, _, ewm_vol, _ = bucket[tk]
            last = float(s.iloc[-1])
            zvol = ewm_vol if ewm_vol else vol
            z = (last - mean) / zvol if (mean is not None and zvol) else None
            color = "grey"
            if z is not None and z >= _FUT_ZTHD:
                color = "green"
            elif z is not None and z <= -_FUT_ZTHD:
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

    def _futures_ts_figure(stype, ticker):
        from dateutil.relativedelta import relativedelta
        from settings.general import GeneralConfig
        bucket = _fut_stat_bucket(stype)
        if not bucket:
            return _fut_empty(f"Waiting for data: {stype}...")
        if ticker not in bucket:
            ticker = sorted(bucket)[0]   # default to first when none clicked yet
        s, mean, vol, vmax, vmin, ewm_vol, extra = bucket[ticker]
        unit = _FUT_UNIT[stype]
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
        zvol = ewm_vol if ewm_vol else vol
        zscore = ((s - mean) / zvol).dropna() if (mean is not None and zvol) else None
        has_zscore = zscore is not None and not zscore.empty

        traces = []
        if has_zscore:
            traces.append(go.Scatter(
                name="Z-score", x=zscore.index, y=zscore.values,
                line={"width": 3, "color": "#2a6fd3"},
            ))
            traces.append(go.Scatter(
                name="Spread (bp)", x=s.index, y=s.values,
                yaxis="y5",
                line={"width": 1.5, "color": "rgba(42,111,211,0.55)"},
            ))
        else:
            traces.append(go.Scatter(
                name="Spread (bp)", x=s.index, y=s.values,
                line={"width": 3, "color": "#2a6fd3"},
            ))

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
                _ana = _load_pickle_cached(os.path.join(DIR_INPUT, "futures-analytics.pkl")) or {}
                _dbpx = _load_pickle_cached(os.path.join(DIR_INPUT, "database-px.pkl")) or {}
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

        fig = go.Figure(data=traces)
        if has_zscore:
            # Plotted series IS the Z-score, so ±1σ/±2σ are just fixed lines
            # at y=±1/±2 rather than bp offsets from mean.
            bands = [(0, "mean", "solid", "#aaaaaa"),
                     (1, "+1σ", "dot", "#f39c12"), (-1, "-1σ", "dot", "#f39c12"),
                     (2, "+2σ", "dash", "#ef553b"), (-2, "-2σ", "dash", "#ef553b")]
        elif mean is not None:
            bands = [(mean, "mean", "solid", "#aaaaaa")]
            if vol:
                bands += [
                    (mean + vol, "+1σ", "dot", "#f39c12"),
                    (mean - vol, "-1σ", "dot", "#f39c12"),
                    (mean + 2 * vol, "+2σ", "dash", "#ef553b"),
                    (mean - 2 * vol, "-2σ", "dash", "#ef553b"),
                ]
        else:
            bands = []
        for val, label, dash, color in bands:
            fig.add_hline(y=val, line_dash=dash, line_color=color,
                          annotation_text=label, annotation_position="right")
        _fmt = lambda v: f"{v:.2f}{unit}" if v is not None else "NA"
        _label = ticker
        if stype == "TermBasis":
            _front, _next = extra.get("front_contract"), extra.get("next_contract")
            if isinstance(_front, str) and isinstance(_next, str) and _front and _next:
                _label = f"{_front.replace('.CFE', '')}|{_next.replace('.CFE', '')}"
        title = (f"<b>{_FUT_TITLE[stype]} — {_label}</b><br>"
                 f"Latest: {_fmt(float(s.iloc[-1]))}, Mean: {_fmt(mean)}, "
                 f"Vol: {_fmt(vol)}, Max: {_fmt(vmax)}, Min: {_fmt(vmin)}")
        layout_kwargs = dict(
            plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
            font=dict(color="#ffffff"), title=title,
            xaxis=dict(range=[start, s.index[-1]]),
            yaxis=dict(title="Z-score" if has_zscore else unit),
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=11)),
            margin=dict(l=50, r=50, t=60, b=40),
            hovermode='x unified',
        )
        if _yaxis2 is not None:
            layout_kwargs["yaxis2"] = _yaxis2
        if _yaxis3 is not None:
            layout_kwargs["yaxis3"] = _yaxis3
        if has_zscore:
            layout_kwargs["yaxis5"] = dict(
                title=unit, overlaying="y", side="right", showgrid=False, zeroline=False,
                tickfont=dict(color="rgba(170,176,192,0.8)"), title_font=dict(color="rgba(170,176,192,0.8)"),
            )
        fig.update_layout(**layout_kwargs)
        return fig

    def _newissue_ts_figure(ticker_label: str):
        """Render canonical BondNewIssue stage time series (e.g. NIB_OTR-5Y).

        Plots only the current (leg1, leg2) episode -- e.g. the still-open
        NIB-vs-OTR pair -- rather than a series stitched across every past
        bond pair for the stage/tenor bucket, so a freshly-issued NIB starts
        the chart at its own issue date instead of showing years of an
        unrelated predecessor bond's history.
        """
        from dateutil.relativedelta import relativedelta
        from settings.general import GeneralConfig
        from web.tabs.alpha.data import (
            load_spread_timeseries,
            to_newissue_stage_label,
            load_newissue_current_episode,
        )

        ts = load_spread_timeseries('BondNewIssue')
        if not isinstance(ts, pd.DataFrame) or ts.empty:
            return _fut_empty("Waiting for data: BondNewIssue...")

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

        s = load_newissue_current_episode(ticker_label)
        if s is None or s.empty:
            # Legacy/unqualified label or fallback summary artifact: fall back
            # to the stitched cross-episode column rather than showing nothing.
            s = pd.to_numeric(ts[ticker_label], errors='coerce').dropna()
        if len(s) < 2 and str(ticker_label).startswith('NIBOTR-'):
            tenor = str(ticker_label).split('-', 1)[-1]
            fallback_col = f'OTROFR1-{tenor}'
            if fallback_col in ts.columns:
                s = load_newissue_current_episode(fallback_col)
                if s is None or s.empty:
                    s = pd.to_numeric(ts[fallback_col], errors='coerce').dropna()
                ticker_label = fallback_col
        if s.empty:
            return _fut_empty(f"No data for {ticker_label}")

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

        fig = go.Figure(data=[go.Scatter(
            name="Spread",
            x=s.index,
            y=s.values,
            line={"width": 3, "color": "#2a6fd3"},
        )])

        if mean is not None:
            bands = [(mean, "mean", "solid", "#aaaaaa")]
            if vol and vol > 0:
                bands += [
                    (mean + vol, "+1σ", "dot", "#f39c12"),
                    (mean - vol, "-1σ", "dot", "#f39c12"),
                    (mean + 2 * vol, "+2σ", "dash", "#ef553b"),
                    (mean - 2 * vol, "-2σ", "dash", "#ef553b"),
                ]
            for val, label, dash, color in bands:
                fig.add_hline(y=val, line_dash=dash, line_color=color,
                              annotation_text=label, annotation_position="right")

        title = (
            f"<b>{ticker_label}</b><br>"
            f"Latest: {float(s.iloc[-1]):.2f}bp, Mean: {mean:.2f}bp, "
            f"Vol: {(vol if vol is not None else float('nan')):.2f}bp, "
            f"Max: {vmax:.2f}bp, Min: {vmin:.2f}bp"
        )
        fig.update_layout(
            plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
            font=dict(color="#ffffff"), title=title,
            xaxis=dict(range=[start, s.index[-1]]),
            yaxis=dict(title='Spread, bp'),
            showlegend=False,
            margin=dict(l=50, r=20, t=60, b=40),
            hovermode='x unified',
        )
        return fig

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
            if stype in _FUT_SPREADS:
                return _futures_bar_figure(stype)

            # Check if key exists in data to avoid KeyError
            if data_rt_js:
                data_rt = json.loads(data_rt_js)
                # Handle special cases consistent with web.core.graphs.statistics
                if stype == 'NetBasis':
                    if 'NetBasis' not in data_rt:
                        raise KeyError(f"Data not available for {stype}")
                elif stype not in data_rt or data_rt.get(stype) is None:
                    _misc_spd_key = {'BinarySpread': 'BinarySpread', 'SectorPCASpread': 'PCASpread'}.get(stype)
                    if _misc_spd_key:
                        try:
                            import pandas as pd
                            import re as _re
                            _misc_static = _load_pickle_cached(os.path.join(DIR_INPUT, "Misc-spds.pkl"))
                            if isinstance(_misc_static, Mapping):
                                _bucket = _misc_static.get(_misc_spd_key, {})
                                if isinstance(_bucket, dict):
                                    _spread = _bucket.get('Spread')
                                    _stat = _bucket.get('StatInfo')
                                    if isinstance(_spread, pd.DataFrame) and isinstance(_stat, pd.DataFrame) and not _spread.empty:
                                        _current = _spread.iloc[-1].rename('spread').to_frame()
                                        _current = _current.join(_stat[['mean', 'vol']], how='inner')
                                        _current['Zscore'] = (_current['spread'] - _current['mean']) / _current['vol']
                                        _current['color'] = 'grey'
                                        if stype == 'SectorPCASpread':
                                            _current.index = [_re.sub(r'(-\d+)\.0(Y)$', r'\1\2', idx) for idx in _current.index]
                                        data_rt[stype] = _current.to_dict()
                                        data_rt_js = json.dumps(data_rt)
                        except Exception:
                            pass
                    if stype == 'TenorSpread':
                        try:
                            import pandas as pd
                            _tenor_static = _load_pickle_cached(os.path.join(DIR_INPUT, 'Tenor-spds.pkl'))
                            if isinstance(_tenor_static, Mapping) and 'TenorSpread' in _tenor_static:
                                _ts = _tenor_static['TenorSpread']
                                if isinstance(_ts, dict):
                                    _spread = _ts.get('Spread')
                                    _stat = _ts.get('StatInfo')
                                    if (isinstance(_spread, pd.DataFrame) and not _spread.empty
                                            and isinstance(_stat, pd.DataFrame) and not _stat.empty):
                                        _current = _spread.iloc[-1].rename('spread').to_frame()
                                        _current = _current.join(_stat[['mean', 'vol']], how='inner')
                                        _vol = pd.to_numeric(_current['vol'], errors='coerce').replace(0, float('nan'))
                                        _mean = pd.to_numeric(_current['mean'], errors='coerce')
                                        _current['Zscore'] = (pd.to_numeric(_current['spread'], errors='coerce') - _mean) / _vol
                                        _current['color'] = 'grey'
                                        data_rt['TenorSpread'] = _current.to_dict()
                                        data_rt_js = json.dumps(data_rt)
                        except Exception:
                            pass
                    if stype not in data_rt or data_rt.get(stype) is None:
                        # Return a friendly empty chart instead of crashing
                        return go.Figure(data=[], layout=dict(
                            plot_bgcolor="rgba(0,0,0,0)",
                            paper_bgcolor="rgba(0,0,0,0)",
                            title=f"Waiting for data: {stype}..."
                        ))

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
        if stype == 'BondNewIssue':
            customdata = point.get("customdata")
            if isinstance(customdata, (list, tuple)) and customdata:
                ticker = customdata[0]
            elif customdata is not None:
                ticker = customdata
            else:
                ticker = point.get("x")
                if ticker is None:
                    ticker = point.get("label")
        else:
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
        return ticker

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

    @app.callback(
        Output("graph-spread", "figure"),
        Input("spread-type", "value"),
        Input("ticker", "children"),
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
            if stype in _FUT_SPREADS:
                return _fit_to_frame(_futures_ts_figure(stype, ticker))

            if stype == 'BondNewIssue':
                return _fit_to_frame(_newissue_ts_figure(ticker))

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
        Input("ticker", "children"),
        Input("seasonal-highlight-month", "value"),
        Input("seasonal-years", "value"),
    )
    def _update_seasonal(stype, ticker, highlight_month, n_years):
        from dash.exceptions import PreventUpdate
        from web.tabs.alpha.seasonal import (
            seasonal_pivot,
            monthly_seasonal_stats,
            build_seasonal_overlay_figure,
            episode_pivot,
            build_episode_overlay_figure,
            episode_bucket_stats,
        )

        _empty_fig = go.Figure(layout=dict(
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            font=dict(color="#ffffff"),
        ))

        if not ticker or not stype:
            return _empty_fig, html.Div()

        n_years = int(n_years or 5)

        # BondNewIssue: episode-relative overlay (day-since-issuance/roll, one
        # line per historical episode) instead of a calendar-year overlay —
        # each pair identity only lives from one roll to the next (quarter,
        # at most a year), so "day of year" is not meaningful here.
        if stype == 'BondNewIssue':
            from web.tabs.alpha.data import load_newissue_episode_series, to_newissue_stage_label
            label = to_newissue_stage_label(ticker) if ':' in str(ticker) else ticker
            try:
                episodes = load_newissue_episode_series(label)
                pivot = episode_pivot(episodes)
            except Exception as e:
                print(f"[seasonal] BondNewIssue episode error for {label}: {e}")
                return _empty_fig, html.Div()

            if pivot.empty:
                return _empty_fig, html.Div(
                    f"No episode history for {label}",
                    style={"color": "#8fb3d9", "fontSize": "11px", "padding": "4px"},
                )

            bucket_stats = pd.DataFrame()
            try:
                bucket_stats = episode_bucket_stats(pivot)
            except Exception as e:
                print(f"[seasonal] BondNewIssue episode stats error: {e}")

            fig = build_episode_overlay_figure(
                pivot,
                title=f"{label} — episode overlay (day since roll)",
                bucket_stats=bucket_stats,
            )

            stats_children = html.Div()
            try:
                if not bucket_stats.empty:
                    _arrow = {"up": "↑", "down": "↓", "neutral": "—"}
                    _dir_color = {"up": "#00cc96", "down": "#ef553b", "neutral": "#aab0c0"}
                    header = html.Div([
                        html.Span("Day",   style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "34px"}),
                        html.Span("Dir",   style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "16px"}),
                        html.Span("Cons%", style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "44px"}),
                        html.Span("AvgΔ",  style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "44px"}),
                        html.Span("Obs",   style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "34px"}),
                        html.Span("p-val", style={"fontSize": "10px", "color": "#8fb3d9"}),
                    ], style={"display": "flex", "gap": "12px", "padding": "2px 6px",
                               "borderBottom": "1px solid #1a3a7a", "marginBottom": "2px"})
                    rows = []
                    for day, row in bucket_stats.iterrows():
                        p = row["p_value"]
                        sig = "**" if p < 0.05 else ("*" if p < 0.10 else "")
                        dir_c = _dir_color[row["direction"]]
                        rows.append(html.Div([
                            html.Span(f"D+{day}", style={"fontSize": "11px", "color": "#ffffff", "minWidth": "34px"}),
                            html.Span(f"{_arrow[row['direction']]}",
                                      style={"fontSize": "11px", "color": dir_c, "minWidth": "16px"}),
                            html.Span(f"{row['consistency']*100:.0f}%{sig}", style={"fontSize": "11px", "color": "#ffffff", "minWidth": "44px"}),
                            html.Span(f"{row['avg_chg_bp']:+.2f}", style={"fontSize": "11px", "color": "#ffffff", "minWidth": "44px"}),
                            html.Span(f"n={row['n_episodes']}", style={"fontSize": "11px", "color": "#aab0c0", "minWidth": "34px"}),
                            html.Span(f"p={p:.2f}", style={"fontSize": "11px", "color": "#aab0c0"}),
                        ], style={"display": "flex", "gap": "12px", "padding": "2px 6px"}))
                    note = html.Div(
                        "* p<0.10  ** p<0.05  (one-sided binomial; no FDR correction applied)",
                        style={"fontSize": "9px", "color": "#8fb3d9", "marginTop": "4px", "padding": "0 6px"},
                    )
                    stats_children = html.Div([header] + rows + [note],
                                              style={"background": "transparent", "borderRadius": "4px",
                                                     "padding": "6px 0", "marginBottom": "8px"})
            except Exception as e:
                print(f"[seasonal] BondNewIssue episode stats error: {e}")

            return fig, stats_children

        # TermBasis: roll-cycle overlay (days-to-maturity of the front
        # contract, one line per historical quarterly roll) instead of a
        # calendar-year overlay — term basis is structurally driven by
        # proximity to the front contract's roll, not the calendar month.
        if stype == 'TermBasis':
            from web.tabs.alpha.seasonal import (
                roll_cycle_pivot,
                roll_cycle_bucket_stats,
                build_roll_cycle_figure,
            )
            tb = (_load_pickle_cached(os.path.join(DIR_INPUT, "futures-spds.pkl")) or {}).get("TermBasis", {})
            dtm_df = tb.get("DaysToMaturity") if isinstance(tb, dict) else None
            basis_df = tb.get("Spread") if isinstance(tb, dict) else None
            roll_df = tb.get("RollProgress") if isinstance(tb, dict) else None
            if not isinstance(dtm_df, pd.DataFrame) or not isinstance(basis_df, pd.DataFrame) \
                    or ticker not in dtm_df.columns or ticker not in basis_df.columns:
                return _empty_fig, html.Div(
                    f"No roll-cycle history for {ticker}",
                    style={"color": "#8fb3d9", "fontSize": "11px", "padding": "4px"},
                )

            pivot = roll_cycle_pivot(dtm_df[ticker], basis_df[ticker])
            if pivot.empty:
                return _empty_fig, html.Div(
                    f"No roll-cycle history for {ticker}",
                    style={"color": "#8fb3d9", "fontSize": "11px", "padding": "4px"},
                )

            bucket_stats = pd.DataFrame()
            try:
                bucket_stats = roll_cycle_bucket_stats(pivot)
            except Exception as e:
                print(f"[seasonal] TermBasis roll-cycle stats error: {e}")

            roll_pivot = pd.DataFrame()
            if isinstance(roll_df, pd.DataFrame) and ticker in roll_df.columns:
                try:
                    roll_pivot = roll_cycle_pivot(dtm_df[ticker], roll_df[ticker])
                except Exception as e:
                    print(f"[seasonal] TermBasis roll-progress pivot error: {e}")

            fig = build_roll_cycle_figure(
                pivot,
                title=f"{ticker} — roll-cycle overlay (days to maturity)",
                bucket_stats=bucket_stats,
                roll_progress_pivot=roll_pivot if not roll_pivot.empty else None,
            )

            stats_children = html.Div()
            try:
                if not bucket_stats.empty:
                    _arrow = {"up": "↑", "down": "↓", "neutral": "—"}
                    _dir_color = {"up": "#00cc96", "down": "#ef553b", "neutral": "#aab0c0"}
                    header = html.Div([
                        html.Span("DTM",   style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "34px"}),
                        html.Span("Dir",   style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "16px"}),
                        html.Span("Cons%", style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "44px"}),
                        html.Span("AvgLvl",style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "44px"}),
                        html.Span("Obs",   style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "34px"}),
                        html.Span("p-val", style={"fontSize": "10px", "color": "#8fb3d9"}),
                    ], style={"display": "flex", "gap": "12px", "padding": "2px 6px",
                               "borderBottom": "1px solid #1a3a7a", "marginBottom": "2px"})
                    rows = []
                    for dtm_val, row in bucket_stats.iterrows():
                        p = row["p_value"]
                        sig = "**" if p < 0.05 else ("*" if p < 0.10 else "")
                        dir_c = _dir_color[row["direction"]]
                        rows.append(html.Div([
                            html.Span(f"{dtm_val}d", style={"fontSize": "11px", "color": "#ffffff", "minWidth": "34px"}),
                            html.Span(f"{_arrow[row['direction']]}",
                                      style={"fontSize": "11px", "color": dir_c, "minWidth": "16px"}),
                            html.Span(f"{row['consistency']*100:.0f}%{sig}", style={"fontSize": "11px", "color": "#ffffff", "minWidth": "44px"}),
                            html.Span(f"{row['avg_level']:+.2f}", style={"fontSize": "11px", "color": "#ffffff", "minWidth": "44px"}),
                            html.Span(f"n={row['n_cycles']}", style={"fontSize": "11px", "color": "#aab0c0", "minWidth": "34px"}),
                            html.Span(f"p={p:.2f}", style={"fontSize": "11px", "color": "#aab0c0"}),
                        ], style={"display": "flex", "gap": "12px", "padding": "2px 6px"}))
                    note = html.Div(
                        "* p<0.10  ** p<0.05  (one-sided binomial; no FDR correction applied)",
                        style={"fontSize": "9px", "color": "#8fb3d9", "marginTop": "4px", "padding": "0 6px"},
                    )
                    stats_children = html.Div([header] + rows + [note],
                                              style={"background": "transparent", "borderRadius": "4px",
                                                     "padding": "6px 0", "marginBottom": "8px"})
            except Exception as e:
                print(f"[seasonal] TermBasis roll-cycle stats error: {e}")

            return fig, stats_children


        # --- Acquire the spread series ---
        series: pd.Series | None = None
        try:
            if stype in _FUT_SPREADS:
                bucket = _fut_stat_bucket(stype)
                if ticker in bucket:
                    series = bucket[ticker][0]  # (series, mean, vol, max, min, ewm_vol, extra)
                elif bucket:
                    series = next(iter(bucket.values()))[0]
            else:
                from web.tabs.alpha.data import load_spread_timeseries
                spd_df = load_spread_timeseries(stype)
                if isinstance(spd_df, pd.DataFrame) and not spd_df.empty:
                    if ticker in spd_df.columns:
                        series = spd_df[ticker]
                    elif spd_df.columns.size:
                        series = spd_df.iloc[:, 0]
        except Exception as e:
            print(f"[seasonal] series load error for {stype}/{ticker}: {e}")

        if series is None or series.dropna().empty:
            return _empty_fig, html.Div(
                f"No data for {ticker or stype}",
                style={"color": "#8fb3d9", "fontSize": "11px", "padding": "4px"},
            )

        # --- Compute seasonal statistics ---
        try:
            pivot = seasonal_pivot(series, years=n_years)
            stats = monthly_seasonal_stats(series, min_years=3)
        except Exception as e:
            print(f"[seasonal] compute error: {e}")
            return _empty_fig, html.Div()

        # --- Build overlay figure ---
        try:
            title_ticker = ticker
            if stype == 'BondNewIssue' and ':' in str(ticker):
                from web.tabs.alpha.data import to_newissue_stage_label
                title_ticker = to_newissue_stage_label(ticker)
            fig = build_seasonal_overlay_figure(
                pivot,
                highlight_month=int(highlight_month) if highlight_month else None,
                stats=stats,
                title=f"{title_ticker} — seasonal year overlay",
                raw_series=series,
                spread_type=stype,
            )
        except Exception as e:
            print(f"[seasonal] figure error: {e}")
            fig = _empty_fig

        # --- Build stats mini-table ---
        stats_children = html.Div()
        if stats is not None and not stats.empty:
            try:
                _arrow = {"up": "↑", "down": "↓", "neutral": "—"}
                _dir_color = {
                    "up":      "#00cc96",
                    "down":    "#ef553b",
                    "neutral": "#aab0c0",
                }
                rows = []
                for month, row in stats.iterrows():
                    p = row["p_value"]
                    sig = "**" if p < 0.05 else ("*" if p < 0.10 else "")
                    is_hl = (highlight_month and int(month) == int(highlight_month))
                    row_style = {
                        "background": "#1a3a7a" if is_hl else "transparent",
                        "display": "flex",
                        "gap": "12px",
                        "padding": "2px 6px",
                        "borderRadius": "3px",
                    }
                    cell_style = {"fontSize": "11px", "color": "#ffffff", "minWidth": "34px"}
                    sub_style  = {"fontSize": "11px", "color": "#aab0c0", "minWidth": "34px"}
                    dir_c = _dir_color[row["direction"]]
                    rows.append(html.Div([
                        html.Span(row["month_name"], style={**cell_style, "minWidth": "28px"}),
                        html.Span(
                            f"{_arrow[row['direction']]}",
                            style={**cell_style, "color": dir_c, "minWidth": "16px"}
                        ),
                        html.Span(f"{row['consistency']*100:.0f}%{sig}", style={**cell_style, "minWidth": "44px"}),
                        html.Span(f"{row['avg_chg_bp']:+.1f}", style={**cell_style, "minWidth": "44px"}),
                        html.Span(f"n={row['n_years']}", style={**sub_style}),
                        html.Span(f"p={p:.2f}", style={**sub_style}),
                    ], style=row_style))

                header = html.Div([
                    html.Span("Month", style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "28px"}),
                    html.Span("Dir",   style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "16px"}),
                    html.Span("Cons%", style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "44px"}),
                    html.Span("AvgΔ",  style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "44px"}),
                    html.Span("Obs",   style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "34px"}),
                    html.Span("p-val", style={"fontSize": "10px", "color": "#8fb3d9"}),
                ], style={"display": "flex", "gap": "12px", "padding": "2px 6px",
                           "borderBottom": "1px solid #1a3a7a", "marginBottom": "2px"})

                note = html.Div(
                    "* p<0.10  ** p<0.05  (one-sided binomial; no FDR correction applied)",
                    style={"fontSize": "9px", "color": "#8fb3d9", "marginTop": "4px", "padding": "0 6px"},
                )
                stats_children = html.Div([header] + rows + [note],
                                          style={"background": "transparent", "borderRadius": "4px",
                                                 "padding": "6px 0", "marginBottom": "8px"})
            except Exception as e:
                print(f"[seasonal] stats table error: {e}")

        return fig, stats_children
