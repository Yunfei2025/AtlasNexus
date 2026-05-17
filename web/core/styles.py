"""
Styling utilities and figure layout helpers used across Dash apps.

This module preserves its public API while adding docstrings and type hints
to improve readability and maintenance.
"""

from typing import Any, Dict, List, Mapping, Union
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
color_mode: Dict[int, str] = {1: "#F93822", 0: "#007ACE", -1: "#00B612"}

# Common style constants
GRID_COLOR: str = "#0f3174"
WHITE: str = "#fff"
ACCENT: str = px.colors.diverging.balance[3]
SHAPE_COLOR: str = "#BD9391"

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
    if stype == 'InsPos':
        bond = b.split(':')[0]
        term = b.split(':')[1]
        title = "<b> %s: %s </b>,  Bond Type: %s,  Term: %s <br>" % (BondConfig.SPREAD_MAP[stype], inst, bond, term)
        lineinfo = ''
    else:
        df_stat = dfts['StatInfo']
        start = df.index[-1] - relativedelta(months=GeneralConfig.STAT_WINDOW)
        end = df.index[-1]
        std = df_stat.loc[b,'vol']*100
        vmax = df_stat.loc[b,'max']*100
        vmin = df_stat.loc[b,'min']*100
        mean = df_stat.loc[b,'mean']*100
        stationary = df_stat.loc[b, 'stationary']
        ttm = extractTTM(b, stype, df_stat)

        # halflife
        if (df_stat.loc[b,'halflife']=='')|(df_stat.loc[b,'stationary']=='NO'):
            halflife = 'NA'
        else:
            halflife = '%.1f days'%df_stat.loc[b,'halflife']

        # title
        if stype == 'BinarySpread':
            term = df_stat.loc[b, 'label']
            if pd.isna(term):
                ticker = b
            else:
                yt = term[5:]
                anchor = dfts['Anchor'][yt]
                ticker = b+'-'+anchor
        elif stype == 'NetBasis':
            ticker = b + '-' + df_stat.loc[b, 'futures']
        else:
            ticker = b
        title = "<b>%s Ticker: %s </b><br> \
            Term to Maturity: %s,    Stationary: %s,    Halflife: %s <br> \
            Mean: %.1fbp, Vol: %.1fbp \
            Max:  %.1fbp, Min: %.1fbp "%(BondConfig.SPREAD_MAP[stype],ticker,ttm,\
                stationary,halflife,mean,std,vmax,vmin)
        lineinfo = dict(mean=mean, std=std, start=start,end=end)
    return dict(title = title,line=lineinfo)

def getTrace(df: Union[pd.Series, pd.DataFrame], stype: str) -> List[Any]:
    """Create main time-series trace for the spread panel."""
    if stype == 'InsPos':
        trace1 = [go.Bar(
            name="Volume",
            x=df.index,
            y=df["Volume"],
            yaxis='y',
            marker=dict(
                color=df.get("color", 'grey'),
            ),
            hovertext="",
        )]
    else:
        trace1 = [go.Scatter(
            name='Spread',
            x=df.index,
            y=df.values,
            yaxis='y',
            line={
                "width": 3,
                "color": "#2a6fd3"
            }
        )]
    return trace1

def getTraceStat(df: Union[pd.Series, pd.DataFrame], stype: str) -> go.Bar:
    """Create bar trace for statistical overview chart."""
    if stype == 'InsPos':
        trace = go.Bar(
            x=df.index,
            y=df.values,
            marker = dict(
                color='grey',
                ),        
            hovertext="",
            name=df.name,
        )
    else:
        trace = go.Bar(
            x=df.index,
            y=df["Zscore"],
            marker = dict(
                color=df["color"],
                ),        
            hovertext="",
            name="Zscore"
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
                #"dash" :'dash',
                }
        ) for i in [0,1]]
    elif stype in ['TBondSwap','CBondSwap']:
        trace2 = [go.Scatter(
            name = 'Bond Carry (3m)',
            x=df1[0].index,
            y=df1[0],
            yaxis='y3',
            line={
                "width": 1,
                "color": ACCENT,
                "dash" :'dash',
                }
        )]
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
        plot_bgcolor=app_color["graph_bg"],
        paper_bgcolor=app_color["graph_bg"],
    )
    if title is not None:
        base["title"] = title
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

def layout_ts(title: str, yunit: str, xrg: Mapping[str, Any], yrg: Mapping[str, Any]) -> Dict[str, Any]:
    """Base layout for time-series panels."""
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
            "title": yunit,
        }))
    return layout

def _make_stat_shapes(lineinfo: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Helper to create mean and ±std overlay line shapes."""
    return [
        {
            "xref": "x",
            "yref": "y",
            "x1": lineinfo["end"],
            "x0": lineinfo["start"],
            "y0": lineinfo["mean"],
            "y1": lineinfo["mean"],
            "type": "line",
            "line": {"dash": "dash", "color": SHAPE_COLOR, "width": 2},
        },
        {
            "xref": "x",
            "yref": "y",
            "x1": lineinfo["end"],
            "x0": lineinfo["start"],
            "y0": lineinfo["mean"]-lineinfo["std"],
            "y1": lineinfo["mean"]-lineinfo["std"],
            "type": "line",
            "line": {"dash": "dot", "color": SHAPE_COLOR, "width": 2},
        },
        {
            "xref": "x",
            "yref": "y",
            "x1": lineinfo["end"],
            "x0": lineinfo["start"],
            "y0": lineinfo["mean"]+lineinfo["std"],
            "y1": lineinfo["mean"]+lineinfo["std"],
            "type": "line",
            "line": {"dash": "dot", "color": SHAPE_COLOR, "width": 2},
        },
    ]

def layout_ts_line(title: str, yunit: str, xrg: Mapping[str, Any], yrg: Mapping[str, Any], lineinfo: Mapping[str, Any] = {}, xmulti: bool = False, ymulti: bool = False, shape: bool = False) -> Dict[str, Any]:
    """Layout for time series chart with optional extra axes and shapes."""
    layout = layout_ts(title,yunit,xrg,yrg)
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
        layout["yaxis4"]={
                "showgrid": False,
                "showline": True,
                "anchor":'x',
                "overlaying":'y',
                "side":'right',
                "zeroline": True,
                "zerolinecolor": WHITE,
                "zerolinewidth": 1,
                },
    if shape:
        layout["shapes"] = _make_stat_shapes(lineinfo)
    return layout

def extractTTM(b: str, stype: str, df_stat: pd.DataFrame) -> str:
    """Extract a human-friendly term-to-maturity string for the title."""
    if stype == 'AssetPCASpread':
        ttm = ''
    elif stype == 'TermSpread':
        ttm = '%.2fY' % df_stat.loc[b, 'TermSpreadTTM']
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
    elif stype == 'BinarySpread':
        ttm = df_stat.loc[b, 'label']
    elif stype in ['InsPos','TermBasis']:
        ttm = ''
    else:
        ttm = '%.2fY' % df_stat.loc[b, 'ttm']
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
