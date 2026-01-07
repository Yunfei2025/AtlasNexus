#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Feb 18 11:32:00 2023

@author: mayunfei
"""
# Removed heavy wildcard import from pylab to avoid namespace pollution and speed imports
import math
from tools.config import app_color, IRSConfig, GeneralConfig, DateConfig
import datetime as dt
import numpy as np
import pandas as pd
import plotly.graph_objs as go
import plotly.io as pio
import plotly.express as px
# SymbolValidator import updated for Plotly 6.x compatibility
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
from plotly.subplots import make_subplots

"""Utilities for stable symbols and palettes"""
try:
    SYMBOLS = list(SymbolValidator().values)
except Exception:
    SYMBOLS = PLOTLY_SYMBOLS

def _symbol(index):
    return SYMBOLS[index % len(SYMBOLS)]

def _palette_color(palette, index):
    return palette[index % len(palette)]




def plotMix(dfp, dfv):
    pio.renderers.default = 'browser'

    dfl1 = dfp['Line1']
    dfl2 = dfp['Line2']
    dfm = dfp['Marker']
    fig = go.Figure([
            go.Scatter(
                name=dfl1.columns[i],
                x=dfl1.index,
                y=dfl1.iloc[:, i],
                line={
                    "width": 3,
                    "color": _palette_color(px.colors.qualitative.Set1, i)
                })
            for i in range(dfl1.shape[1])] +
        [go.Scatter(
            name=dfl2.columns[i],
            x=dfl2.index,
            y=dfl2.iloc[:, i],
            line={
                "width": 3,
                "color": _palette_color(px.colors.qualitative.Set1, i + 1)
            })
            for i in range(dfl2.shape[1])] +
        [go.Scatter(
            name=dfm.columns[i],
            x=dfm.index,
            y=dfm.iloc[:, i],
            mode='markers',
            marker=dict(
                symbol=_symbol(1 + i * 4),
                color=_palette_color(px.colors.qualitative.Set1, i),
                size=10,
            ))
            for i in range(dfm.shape[1])])

    fig.update_layout(
        height=700,
        xaxis={
            "showgrid": True,
            "showline": True,
            "gridcolor": "#0f3174",
            "zeroline": False,
            "title": "Date",
        },
        yaxis={
            "showgrid": True,
            "showline": True,
            "gridcolor": "#0f3174",
            "zeroline": False,
            "title": "%",
        },
        xaxis_title=dfl1.index.name,
        yaxis_title='%',
        title={'text': 'Trend of CNBD Treasury Bond and IRS', 'x': 0.5, 'xanchor': 'center',
               'yanchor': 'top'},
        legend=dict(x=0.7, y=1., traceorder="normal"),
        plot_bgcolor=app_color["graph_bg"],
        paper_bgcolor=app_color["graph_bg"],
        font={"color": "#fff"})
    # fig.show()
    return fig


def plotPortTS(df, output, C_num):
    pio.renderers.default = 'browser'
    dfinfo = output['df_info']

    dic = {}
    specs = [[{'colspan': 2, 'secondary_y': True}, None], [{'colspan': 2, 'secondary_y': True}, None]]
    for i in range(3):
        specs.append([dic, dic])
    fig = make_subplots(rows=5, cols=C_num,
                        horizontal_spacing=0.1,
                        vertical_spacing=0.05,
                        specs=specs)
    fig.add_trace(go.Scatter(
        name='累计损益',
        x=df.index,
        y=df['累计损益'].values,
        legendgroup='1',
        line={
            "width": 3,
            "color": "rgba(102, 198, 147, 0.7)"
        }
    ),
        row=1, col=1,
        secondary_y=False)
    fig.add_trace(go.Bar(
        name='损益',
        x=df.index,
        y=df['损益'].values,
        legendgroup='1',
    ),
        row=1, col=1,
        secondary_y=True)
    fig.update_yaxes(title_text="Daily PnL", secondary_y=False, row=1, col=1)
    fig.update_yaxes(title_text="Cumulative PnL", secondary_y=True, row=1, col=1)  # ,range=[-30,30])

    fig.add_trace(go.Scatter(
        name='累计收益率(%)',
        x=df.index,
        y=df['累计收益率(%)'].values,
        legendgroup='2',
        line={
            "width": 3,
            "color": "rgba(102, 198, 147, 0.7)"
        }
    ),
        row=2, col=1,
        secondary_y=False)
    fig.add_trace(go.Scatter(
        name='累计交易量',
        x=df.index,
        y=df['累计交易量'].values,
        legendgroup='2',
        line={
            "width": 3,
            "color": "rgba(0, 79, 152, 0.7)"
        }
    ),
        row=2, col=1,
        secondary_y=True)
    fig.update_yaxes(title_text="Cumulative Yield", secondary_y=False, row=2, col=1)  # ,range=[-30,30])
    fig.update_yaxes(title_text="Cumulative Volume", secondary_y=True, row=2, col=1)  # ,range=[-30,30])
    fig.update_layout(bargap=0.05, legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01, bgcolor='rgba(0,0,0,0)'),
                      legend_tracegroupgap=180)

    dfp = df[['组合价差', '净DV01-平移', '单边规模', '净DV01-倾斜', '单边DV01', '净DV01-弯曲']]
    for i, c in enumerate(dfp.columns):
        fig.add_trace(go.Bar(
            x=dfp.index,
            y=dfp[c].values,
            showlegend=False,
            marker=dict(color="rgba(102, 198, 147, 1.0)"),
        ),
            row=i // C_num + 3, col=(i % C_num) + 1)
        fig.update_yaxes(title_text=c, row=i // C_num + 3, col=(i % C_num) + 1)
        fig.update_layout(bargap=0.01)
    fig.show()
    return fig


def plotBandPortion(df, unit, title):
    import plotly
    import plotly.io as pio
    import plotly.graph_objects as go
    import plotly.express as px
    if df.shape[1] <= 10:
        colorSets = px.colors.qualitative.Set3
    else:
        colorSets = px.colors.qualitative.Light24
    pio.renderers.default = 'browser'
    fig = go.Figure([go.Scatter(
        name=df.columns[i],
        x=df.index,
        y=df.iloc[:, i],
        mode="lines",
        fill="tonexty",
        line={
            "width": 3,
            "color": colorSets[i]},
        opacity=1.0)
        for i in range(df.shape[1])])
    fig.update_layout(
        xaxis_title=df.index.name,
        yaxis_title=unit,
        title={
            "text": title,
            "x": 0.5,
            "xanchor": "center",
            "yanchor": "top"},
        legend={
            "x": 0.05,
            "y": 0.9,
            "traceorder": "normal",
            "bgcolor": 'rgba(0,0,0,0)'})
    fig.show()
    # file = os.path.join(dir_output,title+'.html')
    # plotly.offline.plot(fig,filename=file)




def plotReg(df):
    fig = px.scatter(df, x=df.columns[0], y=df.columns[1], trendline="ols")
    fig.data[1].line.color = 'red'
    fig.update_layout(
        xaxis_title=df.columns[0],
        yaxis_title=df.columns[1],
        title={'text': 'Regression', 'x': 0.5, 'xanchor': 'center', 'yanchor': 'top'},
        legend=dict(x=0.05, y=.9, traceorder="normal"))
    fig.show()


def plotResidual(residual, spread, statinfo, title):
    pio.renderers.default = 'browser'
    subtitles = ['%s' % b for b in residual.columns]

    C_num = 3
    R_num = math.ceil(residual.shape[1] / C_num)

    dic = {"secondary_y": True}
    specsi = []
    specs = []
    for i in range(C_num):
        specsi.append(dic)
    for i in range(R_num):
        specs.append(specsi)

    fig = make_subplots(rows=R_num, cols=C_num,
                        subplot_titles=subtitles,
                        horizontal_spacing=0.05,
                        vertical_spacing=0.05,
                        specs=specs)

    start = residual.index.min()
    end = residual.index.max()
    for i, c in enumerate(residual.columns):
        df0 = 100 * residual[c]
        sp0 = 100 * spread[c]
        mean = 100 * statinfo.loc[c, 'mean']
        vol = 100 * statinfo.loc[c, 'vol']
        fig.add_trace(go.Scatter(
            name=c,
            x=sp0.index,
            y=sp0.values,
            showlegend=False,
            line={
                "width": 2,
                "color": "red"}
        ),
            row=i // C_num + 1,
            col=(i % C_num) + 1,
        )

        fig.add_trace(go.Scatter(
            name=c,
            x=df0.index,
            y=df0.values,
            showlegend=False,
            legendgroup=str(i),
            line={
                "width": 2,
                "color": "rgba(102, 198, 147, 1.0)"}
        ),
            row=i // C_num + 1,
            col=(i % C_num) + 1,
            secondary_y=True,
        )

        fig.add_trace(go.Scatter(x=[start, end],
                                 y=[mean, mean],
                                 showlegend=False,
                                 mode='lines',
                                 line=dict(color="blue", width=3),
                                 name='Mean'),
                      row=i // C_num + 1,
                      col=(i % C_num) + 1,
                      )

        fig.add_trace(go.Scatter(x=[start, end],
                                 y=[mean + vol, mean + vol],
                                 showlegend=False,
                                 mode='lines',
                                 line=dict(color="blue", width=2, dash="dash"),
                                 name='+1STD'),
                      row=i // C_num + 1,
                      col=(i % C_num) + 1,
                      )

        fig.add_trace(go.Scatter(x=[start, end],
                                 y=[mean - vol, mean - vol],
                                 showlegend=False,
                                 mode='lines',
                                 line=dict(color="blue", width=2, dash="dash"),
                                 name='-1STD'),
                      row=i // C_num + 1,
                      col=(i % C_num) + 1,
                      )

    fig.update_yaxes(title_text="Residual (bp, green)", secondary_y=True)
    fig.update_yaxes(title_text="Spread (bp, red)", secondary_y=False)
    fig.update_layout(title={'text': title}, height=1000)
    # fig.show() 



