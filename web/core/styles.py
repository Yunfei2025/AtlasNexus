"""
Styling utilities and figure layout helpers used across Dash apps.

This module preserves its public API while adding docstrings and type hints
to improve readability and maintenance.
"""

from typing import Any, Dict, List, Mapping, Union
import re
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import pandas as pd
import plotly.graph_objs as go
import plotly.express as px
from dateutil.relativedelta import relativedelta
from settings.fixed_income import IRSConfig, BondConfig, SpreadConfig
from settings.general import GeneralConfig

app_color: Dict[str, str] = {"graph_bg": "#082255", "graph_line": "#007ACE"}
OSPREAD = SpreadConfig.build_ospreado()

# Signal color convention: 1=SELL/short, 0=NEUTRAL, -1=BUY/long
color_mode: Dict[int, str] = {
    1: "#c0392b",   # SELL    — matches --an-red
    0: "#2e86c1",   # NEUTRAL — matches --an-blue
    -1: "#27ae60",  # BUY     — matches --an-green
}

# Common style constants
GRID_COLOR: str = "#0f3174"
WHITE: str = "#fff"
ACCENT: str = px.colors.diverging.balance[3]
SHAPE_COLOR: str = "#aab0c0"  # aligned with --an-muted for stat-line overlays

tabs_styles: Dict[str, Any] = {'zIndex': 99, 
               #'display': 'inlineBlock', 
               #'height': '14vh', 
               #'width': '12vw',
               #'position': 'fixed',
               "background": "#082255", 
               #'top': '12.5vh', 
               #'left': '7.5vw',
               'border': 'grey', 
               'border-radius': '4px'}

tab_selected_style: Dict[str, Any] = {
    "background": "#082255",
    'text-transform': 'uppercase',
    'color': 'white',
    'border': 'grey',
    'font-size': '14px',
    'font-weight': 600,
    'align-items': 'center',
    'justify-content': 'center',
    'border-radius': '4px',
    'padding':'6px'
}

tab_style: Dict[str, Any] = {
    "background": "#425476",
    'text-transform': 'uppercase',
    'color': 'white',
    'font-size': '14px',
    'font-weight': 600,
    'align-items': 'center',
    'justify-content': 'center',
    'border-radius': '4px',
    'padding':'6px',
    'border-style': 'solid',
    'border-color': '#061E44',
}

def getFixingType(b: Union[str, Any]) -> str:
    """Infer fixing series type from a ticker-like input string."""
    text = str(b)
    if 'Repo' in text:
        ftype = 'FR007.IR'
    elif 'Shi3M' in text:
        ftype = 'SHIBOR3M.IR'
    elif 'Basis' in text:
        ftype = 'S-R.IR'
    else:
        ftype = 'FR007.IR'
    return ftype

def getInfo(b: str, df: Union[pd.Series, pd.DataFrame], dfts: Mapping[str, Any], inst: str, stype: str) -> Dict[str, Any]:
    """Build figure title and reference line info for the given spread."""
    df_stat = dfts['StatInfo']
    start = df.index[-1] - relativedelta(months=GeneralConfig.STAT_WINDOW)
    end = df.index[-1]

    # Some fallback datasets ship partial StatInfo tables; derive stats from
    # the plotted series when a stat column (e.g. vol) is missing.
    if isinstance(df, pd.DataFrame):
        spread_values = pd.to_numeric(df.squeeze(), errors='coerce').dropna()
    else:
        spread_values = pd.to_numeric(df, errors='coerce').dropna()

    def _stat_raw(name: str):
        if not isinstance(df_stat, pd.DataFrame):
            return None
        if b not in df_stat.index or name not in df_stat.columns:
            return None
        value = pd.to_numeric(pd.Series([df_stat.loc[b, name]]), errors='coerce').iloc[0]
        if pd.isna(value):
            return None
        return float(value)

    def _stat_bp(name: str) -> float:
        raw = _stat_raw(name)
        if raw is not None:
            return raw * 100
        if spread_values.empty:
            return 0.0
        if name == 'vol':
            return float(spread_values.std()) if len(spread_values) > 1 else 0.0
        if name == 'max':
            return float(spread_values.max())
        if name == 'min':
            return float(spread_values.min())
        if name == 'mean':
            return float(spread_values.mean())
        return 0.0

    std = _stat_bp('vol')
    vmax = _stat_bp('max')
    vmin = _stat_bp('min')
    mean = _stat_bp('mean')
    # EWMA(span=60) vol tracks the current regime, not a static full-window
    # blend, so it's the right denominator for a live entry/exit Z-score. Falls
    # back to the static 'vol' when a StatInfo table has no ewm_vol column yet.
    ewm_vol = _stat_raw('ewm_vol')
    ewm_vol = ewm_vol * 100 if ewm_vol is not None else std

    stationary = 'NO'
    if isinstance(df_stat, pd.DataFrame) and b in df_stat.index and 'stationary' in df_stat.columns:
        stationary = str(df_stat.loc[b, 'stationary'])
    ttm = extractTTM(b, stype, df_stat)

    # halflife
    halflife_raw = None
    if isinstance(df_stat, pd.DataFrame) and b in df_stat.index and 'halflife' in df_stat.columns:
        halflife_raw = df_stat.loc[b, 'halflife']
    if pd.isna(halflife_raw) or halflife_raw == '' or stationary == 'NO':
        halflife = 'NA'
    else:
        halflife = '%.1f days' % float(halflife_raw)

    # title
    if stype == 'BinarySpread':
        term = None
        if isinstance(df_stat, pd.DataFrame) and b in df_stat.index and 'label' in df_stat.columns:
            term = df_stat.loc[b, 'label']
        if pd.isna(term):
            ticker = b
        else:
            yt = term[5:]
            anchor = dfts.get('Anchor', {}).get(yt, '')
            ticker = b+'-'+anchor
    elif stype == 'NetBasis':
        futures_code = ''
        if isinstance(df_stat, pd.DataFrame) and b in df_stat.index and 'futures' in df_stat.columns:
            futures_code = str(df_stat.loc[b, 'futures'])
        ticker = b + '-' + futures_code if futures_code else b
    else:
        ticker = b
    # The ticker/category is already shown above the chart (the "#ticker"
    # header in the Spread Time Series card), so the in-chart title only
    # needs the analytical stats, not a restatement of "<category> Ticker:
    # <id>". Two compact lines, sized down from Plotly's headline default
    # (which assumes a single short title, not a dense stats block).
    title = (
        "Term: %s &nbsp;·&nbsp; Stationary: %s &nbsp;·&nbsp; Halflife: %s<br>"
        "Mean: %.1fbp &nbsp;·&nbsp; Vol: %.1fbp &nbsp;·&nbsp; Max: %.1fbp &nbsp;·&nbsp; Min: %.1fbp"
    ) % (ttm, stationary, halflife, mean, std, vmax, vmin)
    lineinfo = dict(mean=mean, std=std, ewm_vol=ewm_vol, start=start, end=end)
    return dict(title = title,line=lineinfo)

def getTrace(df: Union[pd.Series, pd.DataFrame], stype: str) -> List[Any]:
    """Create main time-series trace for the spread panel.

    Demoted to the secondary y5 axis: Z-score (getZscoreTrace) is the primary
    entry/exit signal and owns the main y axis -- see build_spread_series.
    """
    trace1 = [go.Scatter(
        name='Spread',
        x=df.index,
        y=df.values,
        yaxis='y5',
        line={
            "width": 1.5,
            "color": "rgba(42,111,211,0.55)"
        }
    )]
    return trace1

def getZscoreTrace(zscore: pd.Series) -> List[Any]:
    """Bold primary-axis Z-score trace -- the entry/exit signal a mean-reversion
    trade actually watches, so it gets top visual priority over the raw spread
    (see getTrace, demoted to yaxis5)."""
    if zscore is None or zscore.empty:
        return []
    return [go.Scatter(
        name='Z-score',
        x=zscore.index,
        y=zscore.values,
        yaxis='y',
        line={"width": 3, "color": "#2a6fd3"},
    )]

def getTraceStat(df: Union[pd.Series, pd.DataFrame], stype: str) -> go.Bar:
    """Create bar trace for statistical overview chart."""
    hovertext = None
    if isinstance(df, pd.DataFrame) and 'spread' in df.columns:
        hovertext = [f"Spread: {value :.2f}bp" for value in df['spread']]

    labels = df.index
    custom_ids = df.index
    if isinstance(df, pd.DataFrame) and 'label' in df.columns:
        labels = df['label']

    trace = go.Bar(
        x=labels,
        y=df['Zscore'],
        customdata=custom_ids,
        marker=dict(color=df['color'], line=dict(width=0)),
        hovertext=hovertext,
        name='Zscore',
    )
    return trace

def getTraceAdd(df1: Mapping[int, pd.Series], stype: str) -> List[Any]:
    """Create additional traces depending on the spread type."""
    if stype == 'BinarySpread':
        trace2 = [
            go.Scatter(
            name = df1[1],
            x=df1[0].index,
            y=df1[0].values,
            xaxis='x2',
            line={
                "width": 3,
                "color": "red",
                })
        ]
    elif stype in ['TBondCurve','CBondCurve']+OSPREAD:
        label = {0: 'Close Yield', 1: 'Curve Yield'}
        width = {0: 3, 1: 1}
        color = {0: WHITE, 1: ACCENT}
        if stype == 'SwapSpread':
            coe = 100
        else:
            coe = 1
        trace2 = [go.Scatter(
            name = label[i],
            x=df1[i].index,
            y=coe*df1[i].values,
            yaxis='y3',
            line={
                "width": width[i],
                "color": color[i],
                }
        ) for i in [0,1]]
        # CR(3m,bp) for BondCurve: Spread (annual %, 0.01=1bp) × 25 → 3m bp; on y4 to avoid
        # scale conflict with CloseYield/CurveYield on y3.
        cr_s = df1.get('cr_buy')
        if cr_s is not None and hasattr(cr_s, 'dropna') and not cr_s.dropna().empty:
            trace2.append(go.Scatter(
                name='CR(3m,bp)',
                x=cr_s.index,
                y=25 * cr_s,
                yaxis='y4',
                line={"width": 1, "color": px.colors.diverging.balance[3], "dash": "dash"},
            ))
    elif stype in ['TBondSwap','CBondSwap']:
        if 'cr_buy' in df1 and df1['cr_buy'] is not None:
            trace2 = [
                go.Scatter(
                    name='CR BUY (3m,bp)',
                    x=df1['cr_buy'].index,
                    y=df1['cr_buy'] / 4,  # annual bp → 3m bp
                    yaxis='y3',
                    line={"width": 1, "color": "rgba(0,204,150,0.85)", "dash": "dash"},
                ),
                go.Scatter(
                    name='CR SELL (3m,bp)',
                    x=df1['cr_sell'].index,
                    y=df1['cr_sell'] / 4,
                    yaxis='y3',
                    line={"width": 1, "color": "rgba(239,85,59,0.85)", "dash": "dash"},
                ),
            ]
        else:
            trace2 = [go.Scatter(
                name='Bond Carry (3m)',
                x=df1[0].index,
                y=df1[0],
                yaxis='y3',
                line={"width": 1, "color": ACCENT, "dash": "dash"},
            )]
    elif stype == 'TenorSpread':
        trace2 = []
        if 'cr_buy' in df1 and df1['cr_buy'] is not None:
            trace2 = [
                go.Scatter(
                    name='CR BUY (3m,bp)',
                    x=df1['cr_buy'].index,
                    y=100 * df1['cr_buy'],  # 3m % → 3m bp
                    yaxis='y3',
                    line={"width": 1, "color": "rgba(0,204,150,0.85)", "dash": "dash"},
                ),
                go.Scatter(
                    name='CR SELL (3m,bp)',
                    x=df1['cr_sell'].index,
                    y=100 * df1['cr_sell'],
                    yaxis='y3',
                    line={"width": 1, "color": "rgba(239,85,59,0.85)", "dash": "dash"},
                ),
            ]
        # Z-score now plotted on the primary axis for every spread type (see
        # getZscoreTrace in spreadts()) instead of this y4 overlay.
    elif stype == 'SwapSpread':
        trace2 = [go.Scatter(
            name = 'CR(3m,bp)',
            x=df1[0].index,
            y=100 * df1[0],
            yaxis='y3',
            line={
                "width": 1,
                "color": px.colors.diverging.balance[3],
                "dash": 'dash',
            }
        )]
    elif stype == 'NetBasis':
        c = 'Implied Repo Rate'
        trace2 = [go.Scatter(
            name = c,
            x=df1[0].index,
            y=df1[0],
            yaxis='y3',
            line={
                "width": 1,
                "color": ACCENT,
                "dash" :'dash',
                }
        )]
    else:
        trace2=[]
    return trace2

def _base_layout(title: Union[str, None] = None, height: Union[int, None] = None) -> Dict[str, Any]:
    """Common base layout shared by all figures."""
    base = dict(
        font={"color": WHITE},
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    if title is not None:
        # A small, left-aligned stats caption, not a centered headline — the
        # ticker itself is already shown above the chart. Muted/smaller than
        # Plotly's title default, which is sized for one short line.
        base["title"] = {
            "text": title,
            "x": 0.0,
            "xanchor": "left",
            "font": {"size": 11, "color": "rgba(170,176,192,0.85)"},
        }
    if height is not None:
        base["height"] = height
    return base

def layout_stat(yunit: str) -> Dict[str, Any]:
    """Layout for the statistics bar chart panel."""
    layout = _base_layout()
    layout.update(dict(
        legend=dict(x=0.1, y=1.1), 
        legend_orientation="h",
        xaxis={
            "showgrid": True,
            "showline": False,
            "gridcolor": GRID_COLOR,  
            "zeroline": False,
            "fixedrange": True},
        yaxis = {
                "title":yunit,
                "side":'left', 
                "showline": False,
                "zeroline": False,
                "fixedrange": True,
                "gridcolor": GRID_COLOR}
        ))
    return layout

def layout_ts(title: str, yunit: str, xrg: Mapping[str, Any], yrg: Mapping[str, Any], has_zscore: bool = False) -> Dict[str, Any]:
    """Base layout for time-series panels.

    When `has_zscore` is set, the primary y axis shows the Z-score signal
    (unitless, std devs) instead of the raw spread -- see spreadts()/getTrace.
    """
    layout = _base_layout(title=title, height=600)
    layout.update(dict(
        legend=dict(yanchor="top", y=1.2, xanchor="right", x=1.),
        xaxis={
            "range": [xrg["start"],xrg["end"]],
            "showline": True,
            "gridcolor": GRID_COLOR,
            "zeroline": False,
            "fixedrange": True,
            "title": "Time",
        },
        yaxis={
            "range": [yrg["low"],yrg["up"]],
            "showgrid": True,
            "showline": True,
            "gridcolor": GRID_COLOR,
            "fixedrange": True,
            "zeroline": False,
            "title": "Z-score" if has_zscore else yunit,
        }))
    return layout

SIGMA1_COLOR: str = "#f39c12"  # ±1σ zone wash + edge line
SIGMA2_COLOR: str = "#ef553b"  # ±2σ zone wash + edge line

def _make_stat_shapes(lineinfo: Mapping[str, Any], has_zscore: bool = False) -> List[Dict[str, Any]]:
    """Helper to create mean/±1σ/±2σ reference shapes.

    Z-score row: shaded darkness bands instead of 4 competing dashed/dotted
    lines — a light ±1σ wash and a slightly darker ±1σ→±2σ wash, each with a
    thin edge line at its outer boundary only, plus a single mean line at 0.
    Bands read as "zones" at a glance and don't crowd the z-score line itself
    the way 4 parallel threshold lines did.

    Raw-spread row (has_zscore=False): unchanged — bp-based mean/±1σ/±2σ
    lines, since this series varies by instrument rather than being a fixed
    ±1/±2 scale.
    """
    x0 = lineinfo["start"]
    x1 = lineinfo["end"]

    def _hline(y: float, dash: str, color: str) -> Dict[str, Any]:
        return {
            "xref": "x", "yref": "y",
            "x0": x0, "x1": x1, "y0": y, "y1": y,
            "type": "line",
            "line": {"dash": dash, "color": color, "width": 1.5},
        }

    def _band(y0: float, y1: float, color: str, opacity: float) -> Dict[str, Any]:
        return {
            "xref": "x", "yref": "y",
            "x0": x0, "x1": x1, "y0": y0, "y1": y1,
            "type": "rect",
            "fillcolor": color,
            "opacity": opacity,
            "line": {"width": 0},
            "layer": "below",
        }

    if has_zscore:
        return [
            _band(-2, -1, SIGMA2_COLOR, 0.07),
            _band(-1, 1, SIGMA1_COLOR, 0.10),
            _band(1, 2, SIGMA2_COLOR, 0.07),
            _hline(-2, "solid", SIGMA2_COLOR),
            _hline(2, "solid", SIGMA2_COLOR),
            _hline(0, "dash", SHAPE_COLOR),
        ]

    mean = lineinfo["mean"]
    std = lineinfo["std"]
    return [
        _hline(mean, "dash", SHAPE_COLOR),
        _hline(mean - std, "dot", SIGMA1_COLOR),
        _hline(mean + std, "dot", SIGMA1_COLOR),
        _hline(mean - 2 * std, "dash", SIGMA2_COLOR),
        _hline(mean + 2 * std, "dash", SIGMA2_COLOR),
    ]

def _make_stat_annotations(lineinfo: Mapping[str, Any], has_zscore: bool = False) -> List[Dict[str, Any]]:
    """Helper to label mean/±1σ/±2σ reference shapes at the right edge of the chart."""
    x1 = lineinfo["end"]

    def _label(y: float, text: str, color: str) -> Dict[str, Any]:
        return {
            "xref": "x",
            "yref": "y",
            "x": x1,
            "y": y,
            "xanchor": "left",
            "yanchor": "middle",
            "text": text,
            "showarrow": False,
            "font": {"size": 9, "color": color},
        }

    if has_zscore:
        # Only label the outer ±2σ edges and the mean — the ±1σ boundary is
        # already legible as the wash's own edge, no line/label needed there.
        return [
            _label(0, "mean", SHAPE_COLOR),
            _label(-2, "-2σ", SIGMA2_COLOR),
            _label(2, "+2σ", SIGMA2_COLOR),
        ]

    mean = lineinfo["mean"]
    std = lineinfo["std"]
    return [
        _label(mean, "mean", SHAPE_COLOR),
        _label(mean - std, "-1σ", SIGMA1_COLOR),
        _label(mean + std, "+1σ", SIGMA1_COLOR),
        _label(mean - 2 * std, "-2σ", SIGMA2_COLOR),
        _label(mean + 2 * std, "+2σ", SIGMA2_COLOR),
    ]

def layout_ts_line(title: str, yunit: str, xrg: Mapping[str, Any], yrg: Mapping[str, Any], lineinfo: Mapping[str, Any] = {}, xmulti: bool = False, ymulti: bool = False, shape: bool = False, y4_title: str = "", has_zscore: bool = False) -> Dict[str, Any]:
    """Layout for time series chart with optional extra axes and shapes."""
    layout = layout_ts(title,yunit,xrg,yrg,has_zscore=has_zscore)
    if has_zscore:
        # Raw spread demoted off the primary axis (see getTrace/getZscoreTrace);
        # give it its own dedicated right-side axis rather than reusing y3/y4,
        # which other overlays (fixing rate, curve yield, carry/roll) already own.
        layout["yaxis5"] = {
            "showgrid": False,
            "showline": True,
            "anchor": 'x',
            "overlaying": 'y',
            "side": 'right',
            "zeroline": False,
            "title": yunit,
            "tickfont": {"color": "rgba(170,176,192,0.8)"},
            "titlefont": {"color": "rgba(170,176,192,0.8)"},
        }
    layout["yaxis2"]={
                "showgrid": False,
                "showline": True,
                "anchor":'x',
                "overlaying":'y',
                "side":'right',
                "zeroline": True,
                "zerolinecolor": WHITE,
                "zerolinewidth": 1,
                #"title": "%",
                "tickvals":[]
                }
    if xmulti:
        layout["xaxis2"]={
            "showgrid": False,
            "showline": True,
            "anchor":'x',
            "overlaying":'x',
            "side":'right',
            "zeroline": True,
            "zerolinecolor": ACCENT,
            "zerolinewidth": 1,
            "tickvals":[]
            }
    if ymulti:
        layout["yaxis3"]={
                "showgrid": False,
                "showline": True,
                "anchor":'x',
                "overlaying":'y',
                "side":'right',
                "zeroline": True,
                "zerolinecolor": ACCENT,
                "zerolinewidth": 1,
                "title":"%"
                }
        if y4_title:
            layout["yaxis4"]={
                    "showgrid": False,
                    "showline": True,
                    "anchor":'x',
                    "overlaying":'y',
                    "side":'right',
                    "zeroline": True,
                    "zerolinecolor": SHAPE_COLOR,
                    "zerolinewidth": 1,
                    "title": y4_title,
                }
        else:
            layout["yaxis4"]={
                    "showgrid": False,
                    "showline": False,
                    "anchor":'x',
                    "overlaying":'y',
                    "side":'right',
                    "zeroline": False,
                    "tickvals": [],
                }
    if shape:
        layout["shapes"] = _make_stat_shapes(lineinfo, has_zscore=has_zscore)
        layout["annotations"] = _make_stat_annotations(lineinfo, has_zscore=has_zscore)
    return layout

def extractTTM(b: str, stype: str, df_stat: pd.DataFrame) -> str:
    """Extract a human-friendly term-to-maturity string for the title."""
    if stype == 'AssetPCASpread':
        ttm = ''
    elif stype == 'TermSpread':
        try:
            ttm = '%.2fY' % float(df_stat.loc[b, 'TermSpreadTTM'])
        except (KeyError, TypeError, ValueError):
            ttm = ''
    elif stype == 'SectorPCASpread':
        if '-' in b:
            ttm = b.split('-')[1]
        elif 'FR007' in b:
            ttm = b.split('.')[0].split('S')[1]
        elif 'SHI3M' in b:
            ttm = b.split('.')[0].split('MS')[1]
    elif stype == 'SwapSpread':
        if '-' in b:
            bl = b.split('-')[-1]
            if len(bl)==2:
                ttm = IRSConfig.TERM_MAP[bl]/4
            elif len(bl)==4:
                ttm = IRSConfig.TERM_MAP[bl[2:]]/4
            elif len(bl)==6:
                ttm = IRSConfig.TERM_MAP[bl[2:4]]/4
            else:
                ttm = ''
            ttm = '%.2fY' % ttm
        else:
            ttm = b.split('.')[0][-2:]
    elif stype == 'TenorSpread':
        # Flies (NsMsLs, e.g. CGB-2s5s10s) -> the belly (middle) tenor, e.g.
        # "2y" for CGB-2s5s10s. 2-leg slopes (CGB-5s10s) have no true middle,
        # so fall back to the full instrument name for those, matching prior
        # behavior; cross-curve IDs (CDBCGB-10y, etc.) never match \d+s and
        # also fall back.
        tenors = re.findall(r'(\d+)s', b, re.IGNORECASE)
        ttm = f"{tenors[len(tenors) // 2]}y" if len(tenors) >= 3 else b
    elif stype == 'BinarySpread':
        try:
            ttm = df_stat.loc[b, 'label']
        except KeyError:
            ttm = ''
    elif stype == 'TermBasis':
        ttm = ''
    else:
        try:
            ttm = '%.2fY' % df_stat.loc[b, 'ttm']
        except (KeyError, TypeError, ValueError):
            ttm = ''
    return ttm

__all__ = [
    'app_color',
    'color_mode',
    'tabs_styles',
    'tab_selected_style',
    'tab_style',
    'getFixingType',
    'getInfo',
    'getTrace',
    'getTraceStat',
    'getTraceAdd',
    'layout_stat',
    'layout_ts',
    'layout_ts_line',
    'extractTTM',
]
