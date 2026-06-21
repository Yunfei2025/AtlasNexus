# -*- coding: utf-8 -*-
"""
Created on Wed Sep 24 21:52:07 2025

@author: CMBC
"""

import pandas as pd
import plotly.graph_objs as go
import plotly.io as pio
import plotly.express as px
from plotly.subplots import make_subplots
from settings.general import GeneralConfig

try:
    from plotly.validators.scatter.marker import SymbolValidator
except ImportError:
    # Fallback for Plotly 6.x - use predefined symbols instead
    class SymbolValidator:
        @property
        def values(self):
            return ['circle', 'square', 'diamond', 'triangle-up', 'triangle-down', 
                   'triangle-left', 'triangle-right', 'cross', 'x', 'star', 'hexagon', 
                   'hexagon2', 'octagon', 'asterisk', 'hash', 'y-up', 'y-down', 'y-left', 
                   'y-right', 'line-ew', 'line-ns', 'line-ne', 'line-nw']
        
# Alternative approach: Define commonly used symbols as constants
PLOTLY_SYMBOLS = ['circle', 'square', 'diamond', 'triangle-up', 'triangle-down', 
                  'triangle-left', 'triangle-right', 'cross', 'x', 'star', 'hexagon', 
                  'hexagon2', 'octagon', 'asterisk', 'hash', 'y-up', 'y-down', 'y-left', 
                  'y-right', 'line-ew', 'line-ns', 'line-ne', 'line-nw']

"""Utilities for stable symbols and palettes"""
try:
    SYMBOLS = list(SymbolValidator().values)
except Exception:
    SYMBOLS = PLOTLY_SYMBOLS

def _symbol(index):
    return SYMBOLS[index % len(SYMBOLS)]

def _palette_color(palette, index):
    return palette[index % len(palette)]

# ---------------------------------------------------------------------------
# AtlasNexus design tokens (mirrors web/assets/colors.css + typography.css)
# Curve charts are rendered server-side as pickled Plotly figures, so the CSS
# custom properties aren't available at draw time — values are hard-coded
# here to stay in sync with the canonical token files.
# ---------------------------------------------------------------------------
CURVE_THEME = {
    "bg": "#122a4c",            # --navy-700 / --surface-panel
    "grid": "rgba(255,255,255,0.05)",
    "axis_line": "#1e3a5f",     # --border-default
    "axis_text": "#6f83a3",     # --text-muted
    "text_primary": "#e9eef8",  # --text-primary
    "text_secondary": "#a4b6d2",# --text-secondary
    "spot": "#e0a23c",          # --accent-amber (hero curve)
    "forward": "#45b6e6",       # --accent-cyan
    "band": "#7d96be",          # bid-offer range
    "mid": "#e9eef8",           # --text-primary
    "live": "#41b078",          # --positive (live/RT prints)
    "whisker": "#4a5d7c",       # --text-faint
    "font_sans": "IBM Plex Sans, sans-serif",
    "font_mono": "IBM Plex Mono, monospace",
}


def _curve_axis(title, range_=None, dtick=None):
    axis = {
        "showgrid": True,
        "showline": True,
        "linecolor": CURVE_THEME["axis_line"],
        "gridcolor": CURVE_THEME["grid"],
        "zeroline": False,
        "title": {"text": title, "font": {"family": CURVE_THEME["font_sans"], "size": 12, "color": CURVE_THEME["axis_text"]}},
        "tickfont": {"family": CURVE_THEME["font_mono"], "size": 12, "color": CURVE_THEME["axis_text"]},
    }
    if range_ is not None:
        axis["range"] = range_
    if dtick is not None:
        axis["dtick"] = dtick
    return axis


def _curve_base_layout(height=660):
    return dict(
        plot_bgcolor=CURVE_THEME["bg"],
        paper_bgcolor=CURVE_THEME["bg"],
        font={"color": CURVE_THEME["text_secondary"], "family": CURVE_THEME["font_sans"]},
        height=height,
        margin=dict(l=62, r=26, t=20, b=54),
        hoverlabel=dict(
            bgcolor="rgba(12,24,48,0.96)",
            bordercolor="#2a517f",
            font=dict(color=CURVE_THEME["text_primary"], family=CURVE_THEME["font_mono"], size=12),
        ),
        legend=dict(
            x=0.01, y=1.12, traceorder="normal", orientation="h",
            font={"family": CURVE_THEME["font_sans"], "size": 11, "color": CURVE_THEME["text_secondary"]},
        ),
    )


def _bid_offer_band_trace(name, tenor, lo, hi):
    """Floating bar rendering the bid-offer range at each tenor (mockup's range bars)."""
    return go.Bar(
        name=name,
        x=tenor,
        y=hi - lo,
        base=lo,
        width=[0.12] * len(tenor) if len(tenor) else 0.12,
        marker=dict(color=CURVE_THEME["band"], opacity=0.55, line=dict(color="rgba(255,255,255,0.18)", width=0.5)),
        hoverinfo="skip",
    )


def _offscale_trace(tenor, value, y_floor, y_ceiling):
    """Clamp out-of-range (tenor, value) points to the axis floor/ceiling with a caret marker."""
    clamped_x, clamped_y, labels, rotate = [], [], [], []
    for t, v in zip(tenor, value):
        if pd.isna(t) or pd.isna(v):
            continue
        if v < y_floor:
            clamped_x.append(t); clamped_y.append(y_floor); labels.append(f'{t:.2g}Y · {v:.2f}% (off-scale)'); rotate.append(180)
        elif v > y_ceiling:
            clamped_x.append(t); clamped_y.append(y_ceiling); labels.append(f'{t:.2g}Y · {v:.2f}% (off-scale)'); rotate.append(0)
    if not clamped_x:
        return None
    return go.Scatter(
        name='OffScale',
        x=clamped_x, y=clamped_y,
        mode='markers+text',
        marker=dict(symbol='triangle-down', color=CURVE_THEME["spot"], size=11, opacity=0.85),
        text=labels,
        textposition='top center',
        textfont=dict(family=CURVE_THEME["font_mono"], size=10, color=CURVE_THEME["axis_text"]),
        showlegend=False,
    )


def _whisker_traces(name, tenor, lo, hi):
    """Uncertainty whiskers (vertical line + caps) drawn as a single Scatter with line breaks."""
    xs, ys = [], []
    cap = 0.045
    for t, l, h in zip(tenor, lo, hi):
        xs += [t, t, None, t - cap, t + cap, None, t - cap, t + cap, None]
        ys += [l, h, None, l, l, None, h, h, None]
    return go.Scatter(
        name=name,
        x=xs, y=ys,
        mode="lines",
        line=dict(color=CURVE_THEME["whisker"], width=1),
        hoverinfo="skip",
        showlegend=bool(len(tenor)),
    )

def plotCurve(btype, dict_plot):
    from datetime import datetime
    d = datetime.today()
    if btype == 'TBond':
        title = 'China Government Bonds'
    elif btype == 'CBond':
        title = 'China Policybank Bonds'
    elif btype == 'LBond':
        title = 'China Local Government Bonds'
    else:
        title = 'Other Bond'

    dfl = dict_plot['Curve']
    dfm = dict_plot['Quote']
    dfr = dict_plot['RefSpot']
    dfr = dfr[pd.to_numeric(dfr.index, errors='coerce') <= 10.0]

    tenor = pd.to_numeric(pd.Series(dfm.index), errors='coerce').to_numpy()
    bid = pd.to_numeric(dfm['Bid'], errors='coerce').to_numpy()
    ofr = pd.to_numeric(dfm['Ofr'], errors='coerce').to_numpy()
    mid = (bid + ofr) / 2.0
    vol = pd.to_numeric(dfm['vol'], errors='coerce').to_numpy()

    # bid-offer range bars (rectangle bands), z below everything
    trace_band = [_bid_offer_band_trace('Bid–Offer', tenor, bid, ofr)]

    # uncertainty whiskers (mid ± vol) on the subset where vol is available
    whisk_mask = ~pd.isna(vol)
    trace_whisk = [_whisker_traces('Uncertainty', tenor[whisk_mask], (mid - vol)[whisk_mask], (mid + vol)[whisk_mask])]

    # mid marks
    trace_mid = [go.Scatter(
        name='Mid',
        x=tenor,
        y=mid,
        text=dfm['ID'],
        mode='markers',
        marker=dict(color=CURVE_THEME["mid"], size=4, opacity=0.9),
    )]

    # live/RT prints
    rt = pd.to_numeric(dfm['RT'], errors='coerce')
    rt_mask = rt.notna().to_numpy()
    trace_rt = [go.Scatter(
        name='RT',
        x=tenor[rt_mask],
        y=rt.to_numpy()[rt_mask],
        mode='markers',
        marker=dict(symbol='diamond', color=CURVE_THEME["live"], size=7, line=dict(color="#0a1428", width=1)),
    )]

    # reference markers (selected reference bonds)
    trace_ref = [go.Scatter(
        name='Ref',
        x=dfr.index,
        y=dfr.iloc[:, i],
        mode='markers',
        marker=dict(symbol=_symbol(1), color=CURVE_THEME["forward"], size=11,
                    line=dict(color="#0a1428", width=1)),
    )
        for i in range(dfr.shape[1])]

    # fitted curves: hero (Bid/Ofr average treated as Spot) gets amber, others cyan
    trace_curve = []
    for i in range(dfl.shape[1]):
        is_hero = i == 0
        trace_curve.append(go.Scatter(
            name=dfl.columns[i],
            x=dfl.index,
            y=dfl.iloc[:, i],
            line=dict(
                width=3.5 if is_hero else 2.5,
                color=CURVE_THEME["spot"] if is_hero else CURVE_THEME["forward"],
            ),
        ))

    # y-range from the fitted curve (robust to a handful of off-scale quotes),
    # padded; quotes/mids outside this band are clamped with a caret marker
    # instead of compressing the whole axis (mirrors the mockup's "off-scale" note).
    curve_vals = pd.to_numeric(dfl.stack(), errors='coerce').dropna()
    if not curve_vals.empty:
        pad = max(0.1, (curve_vals.max() - curve_vals.min()) * 0.15)
        y_floor, y_ceiling = curve_vals.min() - pad, curve_vals.max() + pad
    else:
        y_floor, y_ceiling = 0.0, 10.0

    trace_offscale = []
    offscale = _offscale_trace(tenor, mid, y_floor, y_ceiling)
    if offscale is not None:
        trace_offscale.append(offscale)

    data = trace_band + trace_whisk + trace_mid + trace_rt + trace_ref + trace_curve + trace_offscale

    layout = _curve_base_layout()
    layout.update(dict(
        barmode='overlay',
        xaxis=_curve_axis('Tenor (years)'),
        yaxis=_curve_axis('Yield (%)', range_=[y_floor, y_ceiling]),
    ))
    return dict(data=data, layout=layout)

def plotBondTS(bonds, df_price, output, C_num, ptype, rtype, adjust=True):
    pio.renderers.default = 'browser'
    dfinfo = output['df_info']
    subtitles = [b + ', 剩余期限: %.2fY' % dfinfo.loc[b, '剩余期限'] for b in bonds]

    if rtype == 'yield':
        dic = {"secondary_y": True}
        specsi = []
        specs = []
        for i in range(C_num):
            specsi.append(dic)
        for i in range(len(bonds) // C_num):
            specs.append(specsi)
        fig = make_subplots(rows=len(bonds) // C_num, cols=C_num,
                            subplot_titles=subtitles,
                            horizontal_spacing=0.1,
                            vertical_spacing=0.05,
                            specs=specs)

        dfl0 = df_price['accum'][bonds]
        for i, c in enumerate(dfl0.columns):
            df0 = dfl0[c]
            fig.add_trace(go.Scatter(
                name='Close',
                x=df0.index,
                y=df0.values,
                showlegend=False,
                line={
                    "width": 2,
                    "color": "rgba(102, 198, 147, 1.0)"}
            ),
                row=i // C_num + 1, col=(i % C_num) + 1,
                secondary_y=False,
            )

        res = (df_price['ytm_act'][bonds] - df_price['ytm_quo_mean'][bonds]) / df_price['ytm_quo_vol'][bonds]
        for i, c in enumerate(res.columns):
            df0 = res[c]
            fig.add_trace(go.Scatter(
                name='Z-Score',
                x=df0.index,
                y=df0.values,
                showlegend=False,
                mode="lines",
                fill="tonexty",
                line={
                    "width": 1,
                    "color": "rgba(169,169,169,0.8)"},
                opacity=1.0
            ),
                row=i // C_num + 1, col=(i % C_num) + 1,
                secondary_y=True,
            )

        for i, c in enumerate(bonds):
            action = {}
            action['long'] = df_price['long'][c].dropna().index
            action['short'] = df_price['short'][c].dropna().index
            action['close'] = df_price['close'][c].dropna().index
            dfp = res[c]
            for j, (k, v) in enumerate(action.items()):
                fig.add_trace(go.Scatter(
                    name=k,
                    x=v,
                    y=dfp.loc[v].values,
                    showlegend=False,
                    mode='markers',
                    marker={
                        "symbol": _symbol(j),
                        "color": _palette_color(px.colors.qualitative.Set1, j),
                        "size": 5,
                    }
                ),
                    row=i // C_num + 1, col=(i % C_num) + 1,
                    secondary_y=True,
                )
        fig.update_yaxes(title_text="Yield (%)", secondary_y=False)
        fig.update_yaxes(title_text="Z-Score", secondary_y=True, range=[-5, 5])
        fig.update_xaxes(range=[dfl0.index[0], dfl0.index[-1]])

    elif rtype == 'price':
        fig = make_subplots(rows=len(bonds) // C_num, cols=C_num,
                            subplot_titles=subtitles,
                            horizontal_spacing=0.05,
                            vertical_spacing=0.02)
        if adjust:
            dfl1 = df_price[ptype + '_quo_mean'][bonds]
        else:
            dfl1 = df_price[ptype + '_quo'][bonds]
        dfl2 = df_price[ptype + '_act'][bonds]
        dfvol = df_price['ytm_quo_vol'][bonds]

        for i, c in enumerate(dfl1.columns):
            df1 = dfl1[c]
            fig.add_trace(go.Scatter(
                name='Price',
                x=df1.index,
                y=df1.values,
                showlegend=False,
                line={
                    "width": 2,
                    "color": "rgba(102, 198, 147, 0.7)"
                }
            ), row=i // C_num + 1, col=(i % C_num) + 1)

        for i, c in enumerate(dfl1.columns):
            df1 = dfl1[c]  # .dropna()
            vol = dfvol[c]
            fig.add_trace(go.Scatter(
                name='Price Upper',
                x=df1.index,
                y=df1.values + vol,
                showlegend=False,
                line={
                    "width": 2,
                    "color": "rgba(102, 198, 147, 0.3)"
                }
            ), row=i // C_num + 1, col=(i % C_num) + 1)

        for i, c in enumerate(dfl1.columns):
            df1 = dfl1[c]  # .dropna()
            vol = dfvol[c]
            fig.add_trace(go.Scatter(
                name='Price Lower',
                x=df1.index,
                y=df1.values - vol,
                showlegend=False,
                line={
                    "width": 2,
                    "color": "rgba(102, 198, 147, 0.3)"
                }
            ), row=i // C_num + 1, col=(i % C_num) + 1)

        for i, c in enumerate(dfl2.columns):
            df2 = dfl2[c].dropna()
            fig.add_trace(go.Scatter(
                name='Close',
                x=df2.index,
                y=df2.values,
                showlegend=False,
                line={
                    "width": 2,
                    "color": "rgba(255, 0, 0, 0.7)"
                }
            ), row=i // C_num + 1, col=(i % C_num) + 1)

        if ptype == 'clean':
            dfl3 = df_price['clean_cb'][bonds]
            for i, c in enumerate(dfl3.columns):
                df3 = dfl3[c].dropna()
                fig.add_trace(go.Scatter(
                    name='ChinaBondValued',
                    x=df3.index,
                    y=df3.values,
                    showlegend=False,
                    line={
                        "width": 2,
                        "color": "rgba(0, 79, 152, 0.7)"
                    }
                ), row=i // C_num + 1, col=(i % C_num) + 1)

        if ptype == 'ytm':
            for i, c in enumerate(bonds):
                action = {}
                action['long'] = df_price['long'][c].dropna().index
                action['short'] = df_price['short'][c].dropna().index
                action['close'] = df_price['close'][c].dropna().index
                dfp = df_price[ptype + '_act'][c]
                for j, (k, v) in enumerate(action.items()):
                    fig.add_trace(go.Scatter(
                        name=k,
                        x=v,
                        y=dfp.loc[v].values,
                        showlegend=False,
                        mode='markers',
                        marker={
                            "symbol": _symbol(j),
                            "color": _palette_color(px.colors.qualitative.Set1, j),
                            "size": 6,
                        }
                    ), row=i // C_num + 1, col=(i % C_num) + 1)
        fig.update_xaxes(range=[dfl1.index[0], dfl1.index[-1]])
    else:
        pass
    fig.show()
    return fig

# ── Trend dashboard palette (mirrors docs/dev "Trend Dashboard — Layout
#    Improvements" mockup): red+blue hero, one teal for funding rates, one
#    amber for curve factors — kills the old rainbow Set1 palette. ─────────
TREND_THEME = {
    "bg":           "#0c1530",                 # panel bg
    "grid":         "rgba(150,170,210,0.07)",  # ~8% gridlines
    "axis_line":    "rgba(255,255,255,0.06)",
    "axis_text":    "#9fb0c8",
    "text_primary": "#e6edf7",
    "hero_series":  "#ef4444",
    "hero_trend":   "#5b9bd5",
    "local_max":    "#f5a623",
    "local_min":    "#46c46e",
    "down_confirm": "#ef4444",
    "up_confirm":   "#5b9bd5",
    "funding":      "#22d3ee",
    "factor":       "#fbbf24",
    "group_label":  "#6b7c9a",
}


def plotTrend(dfp, dfv, dff):
    pio.renderers.default = 'browser'
    dfl1 = dfp['Line1']
    dfl2 = dfp['Line2']
    dfm = dfp['Marker']

    bgx = {
        "showgrid": True,
        "showline": True,
        "gridcolor": TREND_THEME["grid"],
        "linecolor": TREND_THEME["axis_line"],
        "zeroline": False,
        "tickfont": {"size": 11, "color": TREND_THEME["axis_text"]},
    }
    bgy = {
        "showgrid": True,
        "showline": True,
        "gridcolor": TREND_THEME["grid"],
        "linecolor": TREND_THEME["axis_line"],
        "zeroline": False,
        "title": "%",
        "tickfont": {"size": 11, "color": TREND_THEME["axis_text"]},
    }

    # ── Layout: 3 rows × 3 cols ───────────────────────────────────────────────
    # Row 1 (50 %)  : big trend figure spanning all 3 columns
    # Row 2 (25 %)  : 3 fixing subplots (FR001 / FR007 / SHIBOR3M) side-by-side
    # Row 3 (25 %)  : 3 factor subplots side-by-side
    n_fix = min(dfv.shape[1], 3)
    n_fac = min(dff.shape[1], 3)

    # Build subplot titles: empty for the big chart, then fixing/factor names
    _fix_titles = list(dfv.columns[:n_fix])
    _fac_titles = list(dff.columns[:n_fac])
    # pad to 3 if fewer series
    _fix_titles += [""] * (3 - n_fix)
    _fac_titles += [""] * (3 - n_fac)
    subplot_titles = [""] + _fix_titles + _fac_titles   # 7 entries

    specs = [
        [{"colspan": 3}, None, None],   # row 1: big figure (full width)
        [{}, {}, {}],                   # row 2: fixing subplots
        [{}, {}, {}],                   # row 3: factor subplots
    ]
    fig = make_subplots(
        rows=3,
        cols=3,
        specs=specs,
        row_heights=[0.50, 0.25, 0.25],
        horizontal_spacing=0.05,
        vertical_spacing=0.1,
        subplot_titles=subplot_titles,
    )

    # ── Row 1: main trend chart ──────────────────────────────────────────────
    # Source series (red hero) vs. trend/extrema line (blue hero)
    hero_colors = [TREND_THEME["hero_series"], TREND_THEME["hero_trend"]]
    for i in range(dfl1.shape[1]):
        fig.add_trace(go.Scatter(
            name=dfl1.columns[i],
            x=dfl1.index,
            y=dfl1.iloc[:, i],
            line={"width": 2, "color": _palette_color(hero_colors, i)},
        ), row=1, col=1)

    for i in range(dfl2.shape[1]):
        fig.add_trace(go.Scatter(
            name=dfl2.columns[i],
            x=dfl2.index,
            y=dfl2.iloc[:, i],
            mode='lines+markers',
            line={"width": 2, "color": _palette_color(hero_colors, i + 1)},
            marker={"size": 5, "color": _palette_color(hero_colors, i + 1)},
        ), row=1, col=1)

    marker_styles = {
        'Local Max': {'symbol': 'triangle-down', 'color': TREND_THEME["local_max"], 'size': 10},
        'Local Min': {'symbol': 'triangle-up', 'color': TREND_THEME["local_min"], 'size': 10},
        'Downward Trend Confirmed': {'symbol': 'x', 'color': TREND_THEME["down_confirm"], 'size': 9},
        'Upward Trend Confirmed': {'symbol': 'cross', 'color': TREND_THEME["up_confirm"], 'size': 9},
    }
    for i in range(dfm.shape[1]):
        col = dfm.columns[i]
        style = marker_styles.get(
            col,
            {
                'symbol': _symbol(1 + i * 4),
                'color': TREND_THEME["hero_trend"],
                'size': 10,
            },
        )
        fig.add_trace(go.Scatter(
            name=col,
            x=dfm.index,
            y=dfm.iloc[:, i],
            mode='markers',
            marker=dict(
                symbol=style['symbol'],
                color=style['color'],
                size=style['size'],
            ),
            hoverinfo='skip',
        ), row=1, col=1)

    # ── Row 2: fixings — one subplot per series (single teal) ────────────────
    for i in range(n_fix):
        fig.add_trace(go.Scatter(
            name=dfv.columns[i],
            x=dfv.index,
            y=dfv.iloc[:, i],
            line={"width": 1.6, "color": TREND_THEME["funding"]},
            showlegend=False,
        ), row=2, col=i + 1)

    # ── Row 3: factors — one subplot per series (single amber) ───────────────
    for i in range(n_fac):
        fig.add_trace(go.Scatter(
            name=dff.columns[i],
            x=dff.index,
            y=dff.iloc[:, i],
            line={"width": 1.6, "color": TREND_THEME["factor"]},
            showlegend=False,
        ), row=3, col=i + 1)

    # ── Global styling ───────────────────────────────────────────────────────
    fig.update_layout(
        height=820,
        margin=dict(l=6, r=6, t=46, b=6),
        showlegend=False,
        plot_bgcolor="rgba(255,255,255,0.012)",
        paper_bgcolor=TREND_THEME["bg"],
        font={"color": TREND_THEME["text_primary"], "family": "-apple-system,Helvetica Neue,Arial,sans-serif"},
    )
    fig.update_xaxes(**bgx)
    fig.update_yaxes(**bgy)
    # Slightly smaller y-axis title for the small subplots
    fig.update_yaxes(title_text="", row=2)
    fig.update_yaxes(title_text="", row=3)
    # Style subplot annotation titles (row/col labels)
    for ann in fig.layout.annotations:
        ann.font.size = 11
        ann.font.color = TREND_THEME["axis_text"]

    # Group labels ("FUNDING RATES" / "CURVE FACTORS") above rows 2 and 3,
    # echoing the mockup's section headers between chart rows.
    fig.add_annotation(
        text="FUNDING RATES", xref="paper", yref="paper",
        x=0, y=0.685, xanchor="left", yanchor="bottom", showarrow=False,
        font={"size": 10.5, "color": TREND_THEME["group_label"], "family": "-apple-system,Helvetica Neue,Arial,sans-serif"},
    )
    fig.add_annotation(
        text="CURVE FACTORS", xref="paper", yref="paper",
        x=0, y=0.355, xanchor="left", yanchor="bottom", showarrow=False,
        font={"size": 10.5, "color": TREND_THEME["group_label"], "family": "-apple-system,Helvetica Neue,Arial,sans-serif"},
    )

    return fig

def plotIRSSpotCurve(fixings, curve_dict):
    from settings.general import DateConfig
    from settings.fixed_income import IRSConfig
    d = DateConfig.get_date_mappings()['d']
    tenor = {'r7d': 7 / GeneralConfig.YN, 's3m': 90 / GeneralConfig.YN}
    label = {'r7d': 'FR007', 's3m': 'Shibor3M', 'basis': 'S.R.'}
    # r7d is the hero family (amber); s3m is the secondary family (cyan) — mirrors
    # the mockup's Spot/Forward palette.
    family_color = {'r7d': CURVE_THEME["spot"], 's3m': CURVE_THEME["forward"]}
    anchor = {}
    for c in curve_dict['inst'].keys():
        idx_ = [curve_dict['inst'][c].index.get_indexer([i], method='nearest')[0] for i in IRSConfig.R7D_LIST.values()]
        dfa = curve_dict['inst'][c].iloc[idx_]['SpotRate']
        anchor[c] = dfa

    # plot fixing
    trace0 = [go.Scatter(
        name=label[c] + '(Close)',
        x=[tenor[c]],
        y=[fixings['close'][c]],
        mode='markers',
        marker=dict(symbol='circle-open', color=family_color[c], size=18),
        showlegend=False)
                 for c in tenor.keys()] + \
             [go.Scatter(
                 name=label[c],
                 x=[tenor[c]],
                 y=[fixings['inst'][c]],
                 mode='markers',
                 marker=dict(symbol='circle', color=family_color[c], size=13),
                 showlegend=False)
                 for c in tenor.keys()]

    # plot repo and shibor irs curve
    trace1 = [go.Scatter(
        name=label[c] + 'Curve(Close)',
        x=curve_dict['close'][c].index,
        y=curve_dict['close'][c]['SpotRate'],
        line={"width": 1, "color": family_color[c], "dash": 'dash'})
                 for c in tenor.keys()] + \
             [go.Scatter(
                 name=label[c] + 'Curve',
                 x=curve_dict['inst'][c].index,
                 y=curve_dict['inst'][c]['SpotRate'],
                 line={"width": 1, "color": family_color[c]})
                 for c in tenor.keys()] + \
             [go.Scatter(
                 name=label[c] + 'FitCurve(Close)',
                 x=curve_dict['closefit'][c].index,
                 y=curve_dict['closefit'][c]['SpotRate'],
                 line={"width": 3, "color": family_color[c], "dash": 'dash'},
                 showlegend=False)
                 for c in tenor.keys()] + \
             [go.Scatter(
                 name=c + 'FitCurve',
                 x=curve_dict['instfit'][c].index,
                 y=curve_dict['instfit'][c]['SpotRate'],
                 line={"width": 3.5 if c == 'r7d' else 2.5, "color": family_color[c]},
                 showlegend=False)
                 for c in tenor.keys()]

    # Add TBond/CBond fit curves on the spot chart when the refresher has populated them.
    for btype, color in [('TBond', '#f0c44d'), ('CBond', '#7fd1ec')]:
        spot_col = f'{btype}SpotRate'
        if spot_col not in curve_dict['instfit']['r7d'].columns:
            continue
        trace1.append(go.Scatter(
            name=btype + 'FitCurve',
            x=curve_dict['instfit']['r7d'].index,
            y=curve_dict['instfit']['r7d'][spot_col],
            line={"width": 2, "color": color, "dash": 'dot'},
        ))

    # plot reference markers
    trace2 = [go.Scatter(
        name='Ref',
        x=anchor[c].index,
        y=anchor[c].values,
        mode='markers',
        marker=dict(symbol=_symbol(1), color=family_color[c], size=12,
                    line=dict(color="#0a1428", width=1)),
        )
        for c in tenor.keys()]

    if 'adjSpotRate' in curve_dict['instfit']['r7d'].columns:
        trace1.extend([go.Scatter(
            name=label[c] + 'FitCurveAdj',
            x=curve_dict['instfit'][c].index,
            y=curve_dict['instfit'][c]['adjSpotRate'],
            xaxis='x',
            yaxis='y',
            line={"width": 3, "color": family_color[c], "dash": 'dot'},
            showlegend=False)
            for c in tenor.keys()])

    data = trace0 + trace1 + trace2

    layout = _curve_base_layout()
    layout.update(dict(
        xaxis=_curve_axis('Tenor (years)', range_=[0, 10.1]),
        yaxis=_curve_axis('Yield (%)'),
        yaxis2={
            "showgrid": False,
            "showline": True,
            "linecolor": CURVE_THEME["axis_line"],
            "anchor": 'x',
            "overlaying": 'y',
            "side": 'right',
        },
    ))
    fig = go.Figure(data=data, layout=layout)
    return fig


def plotIRSForwardCurve(fixings, curve_dict, irs_val):
    from datetime import datetime
    import numpy as np
    d = datetime.today()

    tenor = {'r7d': 7 / GeneralConfig.YN, 's3m': 90 / GeneralConfig.YN}
    label = {'r7d': 'FR007', 's3m': 'Shibor3M', 'basis': 'S.R.'}
    # r7d is the hero family (amber); s3m is the secondary family (cyan).
    family_color = {'r7d': CURVE_THEME["spot"], 's3m': CURVE_THEME["forward"]}
    tenorlist = np.array([1 / 2, 3 / 4, 1, 2, 3, 4, 5, 7, 10]).round(2)
    r7dlist = ['FR007S6M.IR', 'FR007S9M.IR','FR007S1Y.IR', 'FR007S2Y.IR', 'FR007S3Y.IR', 'FR007S4Y.IR', 'FR007S5Y.IR', 'FR007S7Y.IR', 'FR007S10Y.IR']
    s3mlist = ['SHI3MS6M.IR', 'SHI3MS9M.IR','SHI3MS1Y.IR','SHI3MS2Y.IR','SHI3MS3Y.IR', 'SHI3MS4Y.IR', 'SHI3MS5Y.IR', 'SHI3MS7Y.IR', 'SHI3MS10Y.IR']
    datalist = ['CarryRoll(1y,bp)', 'CarryRoll(6m,bp)', 'CarryRoll(3m,bp)', ]
    #datalist = 'Carry(3m,bp)'

    # Compute TBond/CBond carry/roll if spot rates have been populated by the refresher.
    # Carry  = (bond_spot - FR007_period_rate) × period_term × 100  [positive = bond yields > funding]
    # Roll   = (bond_spot(T) - bond_spot(T-period)) × T × 100       [positive on upward-sloping curve]
    # Both formulas use the same scaling as IRS cashflow/roll calculations.
    bond_tenorlist = np.array([1, 2, 3, 4, 5, 7, 10])
    bond_carry_roll = {}
    for btype in ['TBond', 'CBond']:
        spot_col = f'{btype}SpotRate'
        if spot_col not in curve_dict['instfit']['r7d'].columns:
            continue
        spot_vals = curve_dict['instfit']['r7d'][spot_col].values.astype(float)
        spot_tenor = curve_dict['instfit']['r7d'].index.values.astype(float)
        try:
            fr007_3m = float(irs_val.loc['FR007S3M.IR', 'Quote'])
            fr007_6m = float(irs_val.loc['FR007S6M.IR', 'Quote'])
            fr007_1y = float(irs_val.loc['FR007S1Y.IR', 'Quote'])
        except (KeyError, TypeError):
            continue
        funding = {'3m': (fr007_3m, 0.25), '6m': (fr007_6m, 0.5), '1y': (fr007_1y, 1.0)}
        cr_vals = {}
        for period, (fund_rate, period_term) in funding.items():
            cr_list = []
            for T in bond_tenorlist:
                s0 = float(np.interp(T, spot_tenor, spot_vals))
                carry = (s0 - fund_rate) * 100 * period_term
                T_roll = T - period_term
                sr = float(np.interp(max(T_roll, spot_tenor[0]), spot_tenor, spot_vals))
                roll = (s0 - sr) * T_roll * 100 if T_roll > 0.01 else 0.0
                cr_list.append(carry + roll)
            cr_vals[f'CarryRoll({period},bp)'] = cr_list
        bond_carry_roll[btype] = cr_vals

    rmax = abs(irs_val[datalist]).max(axis=1).max() + 10
    #rmax = abs(irs_val[datalist]).max() + 10
    if bond_carry_roll:
        for _bvals in bond_carry_roll.values():
            for _cvals in _bvals.values():
                rmax = max(rmax, float(np.abs(np.array(_cvals, dtype=float)).max()) + 10)
    
    mymap = {'3m': 1 / 4, '6m': 1 / 2, '1y': 1}
    import pandas as pd
    fixing_mean = pd.DataFrame(index=tenor.keys(), columns=mymap.keys())
    for t in mymap.keys():
        for c in tenor.keys():
            fixing_mean.loc[c, t] = curve_dict['instfit'][c].loc[:mymap[t], 'ForwardRate'].mean()
            fixing_mean.loc[c + 'tgt', t] = curve_dict['instfit'][c].loc[:mymap[t], 'adjForwardRate'].mean()
    fixing_mean = fixing_mean.round(4)

    # plot fixing
    trace0 = [go.Scatter(
        name=label[c] + '(Close)',
        x=[0],
        y=[fixings['close'][c]],
        mode='markers',
        marker=dict(symbol='circle-open', color=family_color[c], size=14),
        showlegend=False)
                 for c in tenor.keys()] + \
             [go.Scatter(
                 name=label[c],
                 x=[0],
                 y=[fixings['inst'][c]],
                 mode='markers',
                 marker=dict(symbol='circle', color=family_color[c], size=14),
                 showlegend=False)
                 for c in tenor.keys()]

    # plot repo and shibor irs forward curve
    trace1 = [go.Scatter(
        name=label[c] + 'Curve(Close)',
        x=curve_dict['close'][c].index,
        y=curve_dict['close'][c]['ForwardRate'],
        line={"width": 1, "color": family_color[c], "dash": 'dash'})
                 for c in tenor.keys()] + \
             [go.Scatter(
                 name=label[c] + 'Curve',
                 x=curve_dict['inst'][c].index,
                 y=curve_dict['inst'][c]['ForwardRate'],
                 line={"width": 1, "color": family_color[c]})
                 for c in tenor.keys()] + \
             [go.Scatter(
                 name=label[c] + 'FitCurve(Close)',
                 x=curve_dict['closefit'][c].index,
                 y=curve_dict['closefit'][c]['ForwardRate'],
                 line={"width": 3, "color": family_color[c], "dash": 'dash'},
                 showlegend=False)
                 for c in tenor.keys()] + \
             [go.Scatter(
                 name=label[c] + 'FitCurve',
                 x=curve_dict['instfit'][c].index,
                 y=curve_dict['instfit'][c]['ForwardRate'],
                 line={"width": 3.5 if c == 'r7d' else 2.5, "color": family_color[c]},
                 showlegend=False)
                 for c in tenor.keys()]
    for btype, color in [('TBond', '#f0c44d'), ('CBond', '#7fd1ec')]:
        fit_curve = curve_dict['instfit']['r7d']
        fit_curve = fit_curve.loc[fit_curve.index.astype(float) > 1.0]
        trace1.append(go.Scatter(
                     name=btype+' FitCurve',
                     x=fit_curve.index,
                     y=fit_curve[btype+'ForwardRate'],
                     line={"width": 2, "color": color, "dash": 'dot'})
        )

    if 'adjForwardRate' in curve_dict['instfit']['r7d'].columns:
        trace1.extend([go.Scatter(
            name=label[c] + 'FitCurveAdj',
            x=curve_dict['instfit'][c].index,
            y=curve_dict['instfit'][c]['adjForwardRate'],
            line={"width": 3, "color": family_color[c], "dash": 'dot'},
            showlegend=False)
            for c in tenor.keys()])

    # plot carry bar charts.
    # Layout (width=0.08, spacing 0.02): TBond at T-0.24, CBond at T-0.14,
    # FR007 at T-0.04, Shibor at T+0.06.  Bond bars only exist for tenors 1–10Y.
    _bond_colors = {
        'TBond': ['#FF8C00', '#FFA500', '#FFD700'],   # orange shades
        'CBond': ['#3CB371', '#2E8B57', '#90EE90'],   # green shades
    }
    _bond_offsets = {'TBond': -0.24, 'CBond': -0.14}
    trace2 = (
        [dict(
            type="bar",
            name=f'{btype} CR({c[10:-4]})',
            x=bond_tenorlist + _bond_offsets[btype],
            y=bond_carry_roll[btype][c],
            width=0.08,
            marker={"color": _bond_colors[btype][j]},
            showlegend=True,
            yaxis='y2',
            text=[f'{btype}-{int(t)}Y' for t in bond_tenorlist],
            hoverinfo='text+y',
        )
        for btype in ['TBond', 'CBond'] if btype in bond_carry_roll
        for j, c in enumerate(datalist)]
        + [dict(
            type="bar",
            name=c,
            x=tenorlist - 0.04,
            y=irs_val.loc[r7dlist, c],
            width=0.08,
            marker={"color": _bond_colors['TBond'][i]},
            showlegend=True,
            yaxis='y2',
            text=r7dlist,
            hoverinfo='text+y',
        )
        for (i, c) in enumerate(datalist)]
        + [dict(
            type="bar",
            name=c,
            x=tenorlist + 0.06,
            y=irs_val.loc[s3mlist, c],
            width=0.08,
            marker={"color": _bond_colors['CBond'][i]},
            showlegend=False,
            yaxis='y2',
            text=s3mlist,
            hoverinfo='text+y',
        )
        for (i, c) in enumerate(datalist)]
    )

    data = trace2 + trace0 + trace1

    layout = _curve_base_layout()
    layout.update(dict(
        barmode='overlay',
        xaxis=_curve_axis('Tenor (years)', range_=[0, 10.1]),
        yaxis=_curve_axis('Yield (%)'),
        yaxis2={
            "showgrid": False,
            "showline": True,
            "linecolor": CURVE_THEME["axis_line"],
            "zeroline": True,
            "zerolinecolor": "rgba(255,255,255,0.18)",
            "zerolinewidth": 0.01,
            "anchor": 'x',
            "overlaying": 'y',
            "side": 'right',
            "range": [-rmax, rmax],
        },
        shapes=[
            {
                "xref": "x",
                "yref": "y",
                "x1": mymap[t],
                "x0": 0,
                "y0": fixing_mean.loc[k + 'tgt', t],
                "y1": fixing_mean.loc[k + 'tgt', t],
                "opacity": 0.6,
                "type": "line",
                "line": {"dash": "dot", "color": family_color[k], "width": 2},
            }
            for k in tenor.keys() for t in mymap.keys()],
        legend=dict(
            x=1.0,
            y=0.0,
            xanchor='right',
            yanchor='bottom',
            traceorder="normal",
            orientation='h',
            entrywidth=120,
            entrywidthmode='pixels',
            font=dict(size=10, family=CURVE_THEME["font_sans"], color=CURVE_THEME["text_secondary"]),
        ),
    ))
    fig = go.Figure(data=data, layout=layout)
    return fig