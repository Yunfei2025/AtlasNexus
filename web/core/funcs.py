"""Helper functions for futures price/volume processing used in Dash callbacks."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import plotly.graph_objs as go
from WindPy import w

from .load import tick_dfp
from settings.general import DateConfig

w.start()


def get_current_time() -> int:
    """Return the current time in seconds."""
    now = dt.datetime.now()
    return now.hour * 3600 + now.minute * 60 + now.second


def candlestick_trace(df: pd.DataFrame, vol: pd.DataFrame, imc: float) -> go.Candlestick:
    dfvol = {}
    for i in range(len(df.index)):
        e = df.index[i]
        if i == 0:
            dfvol[e] = vol.loc[:e].fillna(0)
        else:
            s = df.index[i - 1]
            dfvol[e] = vol.loc[s:e].fillna(0)
        dfvol[e] = dfvol[e].groupby('last')[['bid', 'ofr']].sum()
        hbid = dfvol[e][
            (dfvol[e]['bid'] - imc * dfvol[e]['ofr'].shift(-1) > 0)
            & (dfvol[e]['bid'] > 100)
        ].index
        hofr = dfvol[e][
            (dfvol[e]['ofr'] - imc * dfvol[e]['bid'].shift(1) > 0)
            & (dfvol[e]['ofr'] > 100)
        ].index
        dfvol[e].loc[hbid, 'label'] = 'hbid'
        dfvol[e].loc[hofr, 'label'] = 'hofr'

    hovertext = []
    for i in range(len(df.index)):
        dfh = dfvol[df.index[i]]
        dfh = dfh.sort_index(ascending=False)
        htext = []
        for j in dfh.index:
            p = f"{j:3.3f}: "
            vb = f"{dfh.loc[j, 'bid']:5.0f}"
            vo = f"{int(dfh.loc[j, 'ofr'])}"
            label = dfh.loc[j].get('label')
            if label == 'hbid':
                htext.append(p + '<b style="color:green">' + vb + '</b>' + ' | ' + vo + '<br>')
            elif label == 'hofr':
                htext.append(p + vb + ' | ' + '<b style="color:red">' + vo + '</b><br>')
            else:
                htext.append(p + vb + ' | ' + vo + '<br>')
        hovertext.append(''.join(htext))

    return go.Candlestick(
        x=df.index,
        low=df['Low'],
        high=df['High'],
        close=df['Close'],
        open=df['Open'],
        increasing_line_color='red',
        decreasing_line_color='green',
        text=hovertext,
        hoverinfo='text',
        name="candlestick",
    )


def getVolInfo(tick: pd.DataFrame, csinterval: str):
    vwap = (tick['last'] * tick['volume']).cumsum() / tick['volume'].cumsum()
    price = tick[['last', 'ask', 'bid']]
    price['taken'] = price['ask'] - price['last']
    price['given'] = price['last'] - price['bid']
    vol = tick['volume']
    tkn = price[price['taken'] <= 0]['taken'].index
    gvn = price[price['given'] <= 0]['given'].index
    voltkn = vol.loc[tkn]
    volgvn = vol.loc[gvn]
    vol = pd.concat([volgvn, voltkn], axis=1)
    vol.columns = ['bid', 'ofr']
    volr = vol.resample(csinterval).sum()

    delta = (volr['ofr'] - volr['bid']) / (volr['ofr'] + volr['bid'])
    vol['last'] = tick['last']
    vprof = tick.groupby('last')['volume'].sum()

    ohlc_dict = {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'}
    df = tick['last'].resample(csinterval).apply(ohlc_dict).dropna(how='any')
    df['Imbanlace'] = delta
    df = df.shift(1).dropna()
    return df, vwap, vol, vprof


def queryPriceVolumeData(date: str, futures: str, csinterval: str):
    tick = w.wst(
        futures,
        "last,ask,bid,volume",
        date + " 09:00:00",
        date + " 15:15:00",
        "",
        usedf=True,
    )[1]
    tick = tick.drop(tick.index[0])
    tick = tick.set_index(pd.DatetimeIndex(pd.to_datetime(tick.index)))
    tick['volume'] = tick['volume'].diff(1)
    tick = tick.dropna()
    df, vwap, vol, vprof = getVolInfo(tick, csinterval)
    last_min = tick.index.max()
    tick_last_min = tick.loc[last_min.strftime('%Y-%m-%d')].between_time(
        last_min.strftime('%H:%M'),
        (last_min + pd.to_timedelta(1, unit='m')).strftime('%H:%M'),
    )
    lst_vol = tick_last_min.groupby('last')['volume'].sum()
    tick_before_last_min = tick[~tick.isin(tick_last_min)]
    bf_lst_vol = tick_before_last_min.groupby('last')['volume'].sum()
    return dict(
        price=df,
        vol=vol,
        vwap=vwap,
        vol_prof=vprof,
        bf_lst_vol=bf_lst_vol,
        vol_last_min=lst_vol,
    )
