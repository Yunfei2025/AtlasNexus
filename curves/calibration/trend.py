#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Mar 14 22:46:07 2022

@author: mayunfei
"""

import pandas as pd

def generate(data, d):
    """Generates directional change events from time series.

    Based on:
        M. Aloud, E. Tsang, R. B. Olsen, and A. Dupuis, "A Directional-Change Events Approach for Studying Financial Time Series," 2012.

    Args:
        data: pandas.Series or array of floats
        d: Directional Change threshold

    Returns:
        A pandas series of Directional Change Events.

    """
    
    p = pd.DataFrame({
    "Price": data.values
    })
    p["Event"] = ''
    event = 'upturn'
    ext = p['Price'][0] 
    n_ext = 0
    
    for i in range(0, len(p)):
        if event == 'upturn':
            if (p['Price'][i]-ext)/ext <= - d:
                event = 'downturn'                
                p.at[n_ext, 'Event'] = 'Local Max'
                p.at[i, 'Event'] = 'Downward Trend Confirmed'
                ext = p['Price'][i]
                n_ext = i
                
            else:
                if p['Price'][i] > ext:
                    ext = p['Price'][i]
                    n_ext = i
        else:
            if (p['Price'][i]-ext)/ext >= d:
                event = 'upturn'               
                p.at[n_ext, 'Event'] = 'Local Min'
                p.at[i, 'Event'] = 'Upward Trend Confirmed'   
                ext = p['Price'][i]
                n_ext = i
            else:
                if p['Price'][i] < ext:
                    ext = p['Price'][i]
                    n_ext = i
    p = p.dropna()
    p['Date'] = data.index
    p.set_index('Date',inplace=True)
    return p['Event']

def TSSampling(vT):
    vm = vT.resample('5T').mean()
    vD = vT.resample('D').mean().dropna()
    h0 = pd.to_timedelta('9h 30m')
    h1 = pd.to_timedelta('11h 30m')
    h2 = pd.to_timedelta('13h')
    h3 = pd.to_timedelta('15h 15m')
    vTn = pd.Series(dtype=float)
    for d in vD.index:
        v = pd.concat([vm.loc[d+h0:d+h1],vm.loc[d+h2:d+h3]],axis=0)
        vTn = pd.concat([vTn,v],axis=0)
    vTn = vTn.fillna(method='ffill')
    # vTn.index.name = 'Time'
    # vTn = vTn.reset_index()
    # vTn.index.name = 'Tick No.'
    # vTn = vTn.reset_index()
    # vTn.set_index('Time',inplace=True)
    return vTn

def genTrendLine(vT,theta):
    event = generate(vT.dropna(), theta)
    allevents = ['Local Max','Local Min','Downward Trend Confirmed','Upward Trend Confirmed']
    df_eve = pd.DataFrame(columns=allevents,index=vT.index)
    for e in df_eve.columns:
        edates = event[event==e].index
        df_eve.loc[edates,e] = vT.loc[edates].values
    df_eve = df_eve.astype(float)
    upend  = df_eve[df_eve['Local Max'].notna()]['Local Max']
    downend  = df_eve[df_eve['Local Min'].notna()]['Local Min']
    exts = pd.concat([upend,downend],axis=0).sort_index()
    exts.name = 'Trend Line'
    dfp = {'Line1':vT.to_frame(),'Line2':exts.to_frame(),'Marker':df_eve}
    return dfp
