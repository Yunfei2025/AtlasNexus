# -*- coding: utf-8 -*-
"""
Created on Wed Sep 24 21:52:07 2025

@author: CMBC
"""

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

    # pio.renderers.default = 'browser'
    dfl = dict_plot['Curve']
    dfm = dict_plot['Quote']
    dfr = dict_plot['RefSpot']

    # plot curves
    trace1 = [go.Scatter(
        name=dfl.columns[i],
        x=dfl.index,
        y=dfl.iloc[:, i],
        line={
            "width": 3,
            "color": _palette_color(px.colors.qualitative.Set1, i)
        })
        for i in range(dfl.shape[1])]

    # plot reference markers
    trace2 = [go.Scatter(
        name='Ref',
        x=dfr.index,
        y=dfr.iloc[:, i],
        mode='markers',
        marker=dict(
            symbol=_symbol(1),
            color='red',
            size=15,
        ))
        for i in range(dfr.shape[1])]

    # plot quote markers
    trace3 = [go.Scatter(
        name=dfm.columns[i],
        x=dfm.index,
        y=dfm.iloc[:, i],
        mode='markers',
        marker=dict(
            symbol=_symbol(1),
            color=_palette_color(px.colors.qualitative.Bold, i + 1),
            size=10,
        ))
        for i in range(1, 5)]

    # plot adj quote markers
    trace4 = [go.Scatter(
        name='Mid',
        x=dfm.index,
        y=(dfm['Bid'] + dfm['Ofr']) / 2,
        error_y=dict(
            type='data',  # value of error bar given in data coordinates
            symmetric=False,
            array=dfm['vol'],
            arrayminus=dfm['vol'],
            visible=True),
        text=dfm['ID'],
        mode='markers',
        marker=dict(
            symbol=_symbol(1),
            color=px.colors.qualitative.Pastel2[2],
            size=10,
            opacity=0.5,
        ))]

    data = trace1 + trace2 + trace3 + trace4

    layout = dict(
        xaxis_title=dfl.index.name,
        yaxis_title='%',
        title={'text': title + '<br> Realtime Curves: ' + d.strftime("%Y-%m-%d %H:%M:%S"), \
               'x': 0.5, 'xanchor': 'center', 'yanchor': 'top'},
        plot_bgcolor=GeneralConfig.app_color["graph_bg"],
        paper_bgcolor=GeneralConfig.app_color["graph_bg"],
        font={"color": "#fff"},
        xaxis={
            "showgrid": True,
            "showline": True,
            "gridcolor": "#0f3174",
            "zeroline": False,
            # "fixedrange": True,
            "title": "Tenor",
        },
        yaxis={
            "showgrid": True,
            "showline": True,
            "gridcolor": "#0f3174",
            # "fixedrange": True,
            "zeroline": False,
            "title": "%",
        },
        height=700,
        legend=dict(x=0.01, y=1.1, traceorder="normal")
    )
    # # plot curve
    # fig = go.Figure(data=data,layout=layout)
    # fig.show()
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

def plotTrend(dfp, dfv, dff):
    pio.renderers.default = 'browser'
    dfl1 = dfp['Line1']
    dfl2 = dfp['Line2']
    dfm = dfp['Marker']
    bgx = {
        "showgrid": True,
        "showline": True,
        "gridcolor": "#0f3174",
        "zeroline": False,
    #    "title": "Date",
    }
    bgy = {
        "showgrid": True,
        "showline": True,
        "gridcolor": "#0f3174",
        "zeroline": False,
        "title": "%",
    }
    specs = [[{'rowspan': 3, 'colspan': 2}, {}, {}, {}],
             [{}, {}, {}, {}],
             [{}, {}, {}, {}]]
    fig = make_subplots(rows=3, cols=4,
                        horizontal_spacing=0.05,
                        vertical_spacing=0.02,
                        shared_xaxes = True,
                        specs=specs)
    for i in range(dfl1.shape[1]):
        fig.add_trace(go.Scatter(
            name=dfl1.columns[i],
            x=dfl1.index,
            y=dfl1.iloc[:, i],
            line={
                "width": 3,
                "color": _palette_color(px.colors.qualitative.Set1, i)
            }),
            row=1, col=1)
    for i in range(dfl2.shape[1]):
        fig.add_trace(go.Scatter(
            name=dfl2.columns[i],
            x=dfl2.index,
            y=dfl2.iloc[:, i],
            line={
                "width": 3,
                "color": _palette_color(px.colors.qualitative.Set1, i + 1)
            }),
            row=1, col=1)
    for i in range(dfm.shape[1]):
        fig.add_trace(go.Scatter(
            name=dfm.columns[i],
            x=dfm.index,
            y=dfm.iloc[:, i],
            mode='markers',
            marker=dict(
                symbol=_symbol(1 + i * 4),
                color=_palette_color(px.colors.qualitative.Set1, i),
                size=10,
            )),
            row=1, col=1)
    for i in range(dfv.shape[1]):
        fig.add_trace(go.Scatter(
            name=dfv.columns[i],
            x=dfv.index,
            y=dfv.iloc[:, i],
            line={
                "width": 3,
                "color": _palette_color(px.colors.qualitative.Set1, i + 1)
            },
            xaxis='x3',
            yaxis='y3',
            showlegend=True),
            row=i+1, col=3)
    for i in range(dff.shape[1]):
        fig.add_trace(go.Scatter(
            name=dff.columns[i],
            x=dff.index,
            y=dff.iloc[:, i],
            line={
                "width": 3,
                "color": _palette_color(px.colors.qualitative.Set1, i + 4)
            },
            showlegend=True),
            row=i+1, col=4)

    fig.update_layout(
        height=700,
        xaxis_title=dfl1.index.name,
        yaxis_title='%',
        title={'text': 'Trends: CNBD Treasury Bond, IRS and Fixings',#Implied Vol of Curve Level/Slope/Curvature',
               'x': 0.5,
               'xanchor': 'center',
               'yanchor': 'top'},
        legend=dict(x=0.01, y=0.1, traceorder="normal"),
        plot_bgcolor=GeneralConfig.app_color["graph_bg"],
        paper_bgcolor=GeneralConfig.app_color["graph_bg"],
        font={"color": "#fff"},
    )
    fig.update_layout(
        xaxis=bgx,
        yaxis=bgy,
        xaxis3=bgx,
        yaxis3=bgy,
        xaxis7=bgx,
        yaxis7=bgy,
        xaxis11=bgx,
        yaxis11=bgy,
        xaxis4=bgx,
        yaxis4=bgy,
        xaxis8=bgx,
        yaxis8=bgy,
        xaxis12=bgx,
        yaxis12=bgy,
    )
    #fig.show()
    return fig

def plotIRSSpotCurve(fixings, curve_dict):
    from settings.general import DateConfig
    from settings.fixed_income import IRSConfig
    d = DateConfig.get_date_mappings()['d']
    # pio.renderers.default = 'browser'
    tenor = {'r7d': 7 / GeneralConfig.YN, 's3m': 90 / GeneralConfig.YN}
    label = {'r7d': 'FR007', 's3m': 'Shibor3M', 'basis': 'S.R.'}
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
        marker=dict(
            symbol='circle-open',
            color=_palette_color(px.colors.qualitative.Set1, i),
            size=20,
        ),
        showlegend=False)
                 for (i, c) in enumerate(tenor.keys())] + \
             [go.Scatter(
                 name=label[c],
                 x=[tenor[c]],
                 y=[fixings['inst'][c]],
                 mode='markers',
                 marker=dict(
                     symbol='circle',
                     color=_palette_color(px.colors.qualitative.Set1, i),
                     size=15,
                 ),
                 showlegend=False)
                 for (i, c) in enumerate(tenor.keys())]

    # plot repo and shibor irs curve
    trace1 = [go.Scatter(
        name=label[c] + 'Curve(Close)',
        x=curve_dict['close'][c].index,
        y=curve_dict['close'][c]['SpotRate'],
        line={
            "width": 1,
            "color": _palette_color(px.colors.qualitative.Set1, i),
            "dash": 'dash',
        })
                 for (i, c) in enumerate(tenor.keys())] + \
             [go.Scatter(
                 name=label[c] + 'Curve',
                 x=curve_dict['inst'][c].index,
                 y=curve_dict['inst'][c]['SpotRate'],
                 line={
                     "width": 1,
                     "color": _palette_color(px.colors.qualitative.Set1, i)
                 })
                 for (i, c) in enumerate(tenor.keys())] + \
             [go.Scatter(
                 name=label[c] + 'FitCurve(Close)',
                 x=curve_dict['closefit'][c].index,
                 y=curve_dict['closefit'][c]['SpotRate'],
                 line={
                     "width": 3,
                     "color": _palette_color(px.colors.qualitative.Set1, i),
                     "dash": 'dash',
                 },
                 showlegend=False)
                 for (i, c) in enumerate(tenor.keys())] + \
             [go.Scatter(
                 name=c + 'FitCurve',
                 x=curve_dict['instfit'][c].index,
                 y=curve_dict['instfit'][c]['SpotRate'],
                 line={
                     "width": 3,
                     "color": _palette_color(px.colors.qualitative.Set1, i)
                 },
                 showlegend=False)
                 for (i, c) in enumerate(tenor.keys())]

    # plot reference markers
    colormap = {'s3m':'blue','r7d':'red'}
    trace2 = [go.Scatter(
        name='Ref',
        x=anchor[c].index,
        y=anchor[c].values,
        mode='markers',
        marker=dict(
            symbol=_symbol(1),
            color=colormap[c],
            size=15,
        ))
        for c in tenor.keys()]

    if 'adjSpotRate' in curve_dict['instfit']['r7d'].columns:
        trace1.extend([go.Scatter(
            name=label[c] + 'FitCurveAdj',
            x=curve_dict['instfit'][c].index,
            y=curve_dict['instfit'][c]['adjSpotRate'],
            xaxis='x',
            yaxis='y',
            line={
                "width": 3,
                "color": _palette_color(px.colors.qualitative.Set1, i),
                "dash": 'dot',
            },
            showlegend=False)
            for (i, c) in enumerate(tenor.keys())])

    # if 'basis' in curve_dict['close'].keys():
    #     # plot fit curve
    #     trace1.extend([go.Scatter(
    #         name='BasisCurve(Close)',
    #         x=curve_dict['close']['basis'].index,
    #         y=curve_dict['close']['basis']['SpotRate'],
    #         xaxis='x',
    #         yaxis='y2',
    #         line={
    #             "width": 1,
    #             "color": px.colors.qualitative.Set1[2],
    #             "dash": 'dash',
    #         }),
    #         go.Scatter(
    #             name='BasisCurve',
    #             x=curve_dict['inst']['basis'].index,
    #             y=curve_dict['inst']['basis']['SpotRate'],
    #             xaxis='x',
    #             yaxis='y2',
    #             line={
    #                 "width": 1,
    #                 "color": px.colors.qualitative.Set1[2]
    #             })])

    data = trace0 + trace1 + trace2

    layout = dict(
        xaxis_title='years',
        yaxis_title='%',
        xaxis={
            "showgrid": True,
            "showline": True,
            "gridcolor": "#0f3174",
            "zeroline": False,
            "fixedrange": True,
            "title": "Tenor",
            "range": [0, 10.1]
        },
        yaxis={
            "showgrid": True,
            "showline": True,
            "gridcolor": "#0f3174",
            "fixedrange": True,
            "zeroline": False,
            "title": "%",
            # "range":[2,2.9]
        },
        yaxis2={
            "showgrid": False,
            "showline": True,
            "anchor": 'x',
            "overlaying": 'y',
            "side": 'right',
        },
        height=700,
        title={'text': '<br> Realtime IRS Spot Curves: ' + d.strftime("%Y-%m-%d %H:%M:%S"), \
               'x': 0.5, 'xanchor': 'center', 'yanchor': 'top'},
        legend=dict(x=0.01, y=1.0,
                    traceorder="normal"),
        plot_bgcolor=GeneralConfig.app_color["graph_bg"],
        paper_bgcolor=GeneralConfig.app_color["graph_bg"],
        font={"color": "#fff"},
    )
    fig = go.Figure(data=data, layout=layout)
    # fig.show() 
    return fig


def plotIRSForwardCurve(fixings, curve_dict, irs_val):
    from datetime import datetime
    import numpy as np
    d = datetime.today()
    pio.renderers.default = 'browser'

    tenor = {'r7d': 7 / GeneralConfig.YN, 's3m': 90 / GeneralConfig.YN}
    label = {'r7d': 'FR007', 's3m': 'Shibor3M', 'basis': 'S.R.'}
    tenorlist = np.array([1 / 2, 3 / 4, 1, 2, 3, 4, 5]).round(2)
    r7dlist = ['FR007S6M.IR', 'FR007S9M.IR','FR007S1Y.IR', 'FR007S2Y.IR', 'FR007S3Y.IR', 'FR007S4Y.IR', 'FR007S5Y.IR']
    s3mlist = ['SHI3MS6M.IR', 'SHI3MS9M.IR','SHI3MS1Y.IR','SHI3MS2Y.IR','SHI3MS3Y.IR', 'SHI3MS4Y.IR', 'SHI3MS5Y.IR']
    datalist = ['CarryRoll(1y,bp)', 'CarryRoll(6m,bp)', 'CarryRoll(3m,bp)', ]
    #datalist = 'Carry(3m,bp)'
    rmax = abs(irs_val[datalist]).max(axis=1).max() + 10
    #rmax = abs(irs_val[datalist]).max() + 10
    
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
        marker=dict(
            symbol='circle-open',
            color=_palette_color(px.colors.qualitative.Set1, i),
            size=15,
        ),
        showlegend=False)
                 for (i, c) in enumerate(tenor.keys())] + \
             [go.Scatter(
                 name=label[c],
                 x=[0],
                 y=[fixings['inst'][c]],
                 mode='markers',
                 marker=dict(
                     symbol='circle',
                     color=_palette_color(px.colors.qualitative.Set1, i),
                     size=15,
                 ),
                 showlegend=False)
                 for (i, c) in enumerate(tenor.keys())]

    # plot repo and shibor irs forward curve
    trace1 = [go.Scatter(
        name=label[c] + 'Curve(Close)',
        x=curve_dict['close'][c].index,
        y=curve_dict['close'][c]['ForwardRate'],
        line={
            "width": 1,
            "color": _palette_color(px.colors.qualitative.Set1, i),
            "dash": 'dash',
        })
                 for (i, c) in enumerate(tenor.keys())] + \
             [go.Scatter(
                 name=label[c] + 'Curve',
                 x=curve_dict['inst'][c].index,
                 y=curve_dict['inst'][c]['ForwardRate'],
                 line={
                     "width": 1,
                     "color": _palette_color(px.colors.qualitative.Set1, i)
                 })
                 for (i, c) in enumerate(tenor.keys())] + \
             [go.Scatter(
                 name=label[c] + 'FitCurve(Close)',
                 x=curve_dict['closefit'][c].index,
                 y=curve_dict['closefit'][c]['ForwardRate'],
                 line={
                     "width": 3,
                     "color": _palette_color(px.colors.qualitative.Set1, i),
                     "dash": 'dash',
                 },
                 showlegend=False)
                 for (i, c) in enumerate(tenor.keys())] + \
             [go.Scatter(
                 name=label[c] + 'FitCurve',
                 x=curve_dict['instfit'][c].index,
                 y=curve_dict['instfit'][c]['ForwardRate'],
                 line={
                     "width": 3,
                     "color": _palette_color(px.colors.qualitative.Set1, i)
                 },
                 showlegend=False)
                 for (i, c) in enumerate(tenor.keys())]
    i = 4
    for btype in ['TBond','CBond']:
        trace1.append(go.Scatter(
                     name=btype+' FitCurve',
                     x=curve_dict['instfit']['r7d'].index,
                     y=curve_dict['instfit']['r7d'][btype+'ForwardRate'],
                     line={
                         "width": 3,
                         "color": _palette_color(px.colors.qualitative.Set1, i)
                     })
        )
        i += 1

    if 'adjForwardRate' in curve_dict['instfit']['r7d'].columns:
        trace1.extend([go.Scatter(
            name=label[c] + 'FitCurveAdj',
            x=curve_dict['instfit'][c].index,
            y=curve_dict['instfit'][c]['adjForwardRate'],
            line={
                "width": 3,
                "color": _palette_color(px.colors.qualitative.Set1, i),
                "dash": 'dot',
            },
            showlegend=False)
            for (i, c) in enumerate(tenor.keys())])

    # plot carry bar charts 
    trace2 = [dict(
        type="bar",
        name=c,
        x=tenorlist - 0.05,
        y=irs_val.loc[r7dlist, c],
        width=0.1,
        marker={"color": px.colors.diverging.balance[i]},
        showlegend=True,
        yaxis='y2',
        text=r7dlist,
        hoverinfo='text+y',
    )
                 for (i, c) in enumerate(datalist)] + \
             [dict(
                 type="bar",
                 name=c,
                 x=tenorlist + 0.05,
                 y=irs_val.loc[s3mlist, c],
                 width=0.1,
                 marker={"color": px.colors.diverging.balance[i]},
                 showlegend=False,
                 yaxis='y2',
                 text=s3mlist,
                 hoverinfo='text+y',
             )
                 for (i, c) in enumerate(datalist)]

    data = trace2 + trace0 + trace1

    layout = dict(
        barmode='overlay',
        xaxis_title='years',
        yaxis_title='%',
        xaxis={
            "showgrid": True,
            "showline": True,
            "gridcolor": "#0f3174",
            "zeroline": False,
            "fixedrange": True,
            "title": "Tenor",
            "range": [0, 10.1]
        },
        yaxis={
            "showgrid": True,
            "showline": True,
            "gridcolor": "#0f3174",
            "fixedrange": True,
            "zeroline": False,
            "title": "%",
        },
        yaxis2={
            "showgrid": False,
            "showline": True,
            "zeroline": True,
            "zerolinecolor": "#fff",
            "zerolinewidth": 0.01,
            "anchor": 'x',
            "overlaying": 'y',
            "side": 'right',
            "range": [-rmax, rmax],
            # "tickvals":[]
        },
        shapes=[
            {
                "xref": "x",
                "yref": "y",
                "x1": mymap[t],
                "x0": 0,
                "y0": fixing_mean.loc[k + 'tgt', t],
                "y1": fixing_mean.loc[k + 'tgt', t],
                "opacity": 0.5,
                "type": "line",
                "line": {"dash": "dot", "color": _palette_color(px.colors.qualitative.Set1, i), "width": 2},
            }
            for (i, k) in enumerate(tenor.keys()) for t in mymap.keys()],
        height=700,
        title={'text': '<br> Realtime IRS Forward Curves: ' + d.strftime("%Y-%m-%d %H:%M:%S"), \
               'x': 0.5, 'xanchor': 'center', 'yanchor': 'top'},
        legend=dict(x=0.01, y=1.0,
                    traceorder="normal"),
        plot_bgcolor=GeneralConfig.app_color["graph_bg"],
        paper_bgcolor=GeneralConfig.app_color["graph_bg"],
        font={"color": "#fff"},
    )
    fig = go.Figure(data=data, layout=layout)
    # fig.show()
    return fig