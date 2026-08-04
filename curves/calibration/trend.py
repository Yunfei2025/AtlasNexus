#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Mar 14 22:46:07 2022

@author: mayunfei
"""

import numpy as np
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
        # Relative moves must be normalized by magnitude rather than signed
        # level. Yield-based spreads are inverted before trend backtesting, so
        # their input can be negative; dividing by a negative extremum reverses
        # the directional-change comparisons and can freeze the state.
        ext_scale = abs(ext)
        if ext_scale == 0:
            ext_scale = np.finfo(float).eps
        if event == 'upturn':
            if (p['Price'][i]-ext)/ext_scale <= - d:
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
            if (p['Price'][i]-ext)/ext_scale >= d:
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

def generate_absolute(data, theta_abs, theta_ts=None):
    """Generates directional change events using an absolute threshold.

    Same algorithm as :func:`generate` but triggers on
    ``abs(price - extremum) >= theta_abs`` instead of a relative move.
    This is necessary for spread series that can hover near zero where
    a relative threshold is undefined or unstable.

    The state machine is inherently sequential, but the per-step work is
    done on plain numpy arrays rather than per-row ``.iloc``/``.at`` pandas
    access, which is materially faster over long histories.

    Args:
        data: pandas.Series of spread levels (index = dates/timestamps).
        theta_abs: Absolute threshold in the same units as *data*
                   (e.g. 0.02 for 2 bp when data is in %), used whenever
                   *theta_ts* is not supplied or is invalid for a given day.
        theta_ts: Optional per-day absolute threshold, aligned to
                  ``data.index`` (e.g. a monthly-frozen adaptive schedule).
                  Falls back to *theta_abs* for any day where it is
                  NaN/non-positive.

    Returns:
        pandas.Series of Directional Change Events (same format as :func:`generate`).
    """
    price_arr = np.asarray(data.values, dtype=float)
    n = len(price_arr)
    event_arr = np.empty(n, dtype=object)
    event_arr[:] = ''

    base_theta = float(theta_abs)
    thr_arr = None
    if theta_ts is not None:
        thr_series = theta_ts if isinstance(theta_ts, pd.Series) else pd.Series(theta_ts, index=data.index)
        thr_arr = pd.to_numeric(thr_series.reindex(data.index), errors='coerce').to_numpy(dtype=float)

    event = 'upturn'
    ext = price_arr[0]
    n_ext = 0

    for i in range(n):
        price = price_arr[i]
        if np.isnan(price):
            continue
        thr = thr_arr[i] if thr_arr is not None else np.nan
        if not np.isfinite(thr) or thr <= 0:
            thr = base_theta
        if event == 'upturn':
            if (price - ext) <= -thr:
                event = 'downturn'
                event_arr[n_ext] = 'Local Max'
                event_arr[i] = 'Downward Trend Confirmed'
                ext = price
                n_ext = i
            elif price > ext:
                ext = price
                n_ext = i
        else:
            if (price - ext) >= thr:
                event = 'upturn'
                event_arr[n_ext] = 'Local Min'
                event_arr[i] = 'Upward Trend Confirmed'
                ext = price
                n_ext = i
            elif price < ext:
                ext = price
                n_ext = i

    result = pd.Series(event_arr, index=data.index, name='Event')
    return result[~np.isnan(price_arr)]


def trend_state_machine(events):
    """Convert directional-change events into a +1/0/−1 trend state series.

    Args:
        events: pandas.Series of DC events (output of :func:`generate` or
                :func:`generate_absolute`).  Index = dates.

    Returns:
        pandas.Series with the same index as *events*:
            +1 after 'Upward Trend Confirmed',
            −1 after 'Downward Trend Confirmed',
             0 before the first event.
    """
    raw = pd.Series(np.nan, index=events.index, dtype=float)
    raw[events.eq('Upward Trend Confirmed')] = 1.0
    raw[events.eq('Downward Trend Confirmed')] = -1.0
    return raw.ffill().fillna(0.0).astype(int)


def compute_trend_signal(
    spread_series,
    theta_abs=0.02,
    momentum_window=20,
    vol_window=60,
    momentum_threshold=0.5,
    carry_buffer=0.0,
):
    """Compute the full trend signal for a spread series.

    Combines directional-change trend state, momentum confirmation,
    and carry filter into a single composite signal.

    Args:
        spread_series: pandas.Series of spread levels.
        theta_abs: Absolute DC threshold (spread units).
        momentum_window: Lookback for momentum (days).
        vol_window: Lookback for volatility normalisation (days).
        momentum_threshold: Normalised momentum threshold (|m| >= this).
        carry_buffer: Minimum spread level for carry-ok (long side).

    Returns:
        dict with keys:
            trend_state: int (+1/−1/0)
            momentum_20d: float (raw 20d change)
            momentum_norm: float (normalised momentum)
            carry_ok: bool
            signal: int (+1/−1/0 final composite)
            events: pd.Series of DC events
    """
    s = pd.to_numeric(spread_series, errors="coerce").dropna()
    result = {
        "trend_state": 0,
        "momentum_20d": 0.0,
        "momentum_norm": 0.0,
        "carry_ok": False,
        "signal": 0,
        "events": pd.Series(dtype=str),
    }
    if len(s) < momentum_window + 10:
        return result

    events = generate_absolute(s, theta_abs)
    result["events"] = events

    # Trend state from DC events
    if len(events) == 0:
        return result
    states = trend_state_machine(events)
    # Forward-fill to spread index
    state_full = states.reindex(s.index).ffill().fillna(0).astype(int)
    trend_state = int(state_full.iloc[-1])
    result["trend_state"] = trend_state

    # Momentum confirmation
    m20 = float(s.iloc[-1] - s.iloc[-momentum_window]) if len(s) >= momentum_window else 0.0
    result["momentum_20d"] = m20
    changes = s.diff().dropna()
    sigma = float(changes.iloc[-vol_window:].std()) if len(changes) >= vol_window else float(changes.std())
    m_norm = m20 / sigma if sigma > 0 else 0.0
    result["momentum_norm"] = m_norm

    # Carry filter
    carry_ok = float(s.iloc[-1]) >= carry_buffer
    result["carry_ok"] = carry_ok

    # Composite signal
    momentum_confirmed = (
        np.sign(m20) == trend_state and abs(m_norm) >= momentum_threshold
    ) if trend_state != 0 else False

    if trend_state == 1 and carry_ok and momentum_confirmed:
        result["signal"] = 1
    elif trend_state == -1 and momentum_confirmed:
        result["signal"] = -1
    else:
        result["signal"] = 0

    return result


def TSSampling(vT):
    vm = vT.resample('5min').mean()
    vD = vT.resample('D').mean().dropna()
    h0 = pd.to_timedelta('9h 30m')
    h1 = pd.to_timedelta('11h 30m')
    h2 = pd.to_timedelta('13h')
    h3 = pd.to_timedelta('15h 15m')
    vTn = pd.Series(dtype=float)
    for d in vD.index:
        v = pd.concat([vm.loc[d+h0:d+h1],vm.loc[d+h2:d+h3]],axis=0)
        vTn = pd.concat([vTn,v],axis=0)
    vTn = vTn.ffill()
    # vTn.index.name = 'Time'
    # vTn = vTn.reset_index()
    # vTn.index.name = 'Tick No.'
    # vTn = vTn.reset_index()
    # vTn.set_index('Time',inplace=True)
    return vTn

def genTrendLine(vT,theta):
    clean = vT.dropna()
    event = generate(clean, theta)
    allevents = [
        'Local Max',
        'Local Min',
        'Downward Trend Confirmed',
        'Upward Trend Confirmed',
    ]
    df_eve = pd.DataFrame(columns=allevents,index=vT.index)
    for e in df_eve.columns:
        if e in event.unique():
            edates = event[event==e].index
            df_eve.loc[edates,e] = vT.loc[edates].values

    df_eve = df_eve.astype(float)
    upend  = df_eve[df_eve['Local Max'].notna()]['Local Max']
    downend  = df_eve[df_eve['Local Min'].notna()]['Local Min']
    exts = pd.concat([upend,downend],axis=0).sort_index()
    exts.name = 'Trend Line'
    dfp = {
        'Line1':vT.to_frame(),
        'Line2':exts.to_frame(),
        'Marker':df_eve,
    }
    return dfp
