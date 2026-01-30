"""
Strategy logic module
Contains implementations of various trading strategies
"""

import pandas as pd
import numpy as np


def run_ma_strategy(data, short_window, long_window):
    """MA crossover strategy"""
    df = data.copy()
    df['ma_short'] = df['close'].rolling(window=short_window).mean()
    df['ma_long'] = df['close'].rolling(window=long_window).mean()
    df['signal'] = np.where(df['ma_short'] > df['ma_long'], 1, -1)
    df.iloc[:long_window, df.columns.get_loc('signal')] = 0
    df['position'] = df['signal'].diff()
    df['returns'] = df['close'].pct_change()
    df['strategy_returns'] = df['signal'].shift(1) * df['returns']
    df['cumulative_returns'] = (1 + df['strategy_returns']).cumprod()
    return df


def run_bollinger_strategy(data, window, num_std, exit_at_ma=False):
    """Bollinger Bands strategy"""
    df = data.copy()
    df['ma'] = df['close'].rolling(window=window).mean()
    df['std'] = df['close'].rolling(window=window).std()
    df['upper_band'] = df['ma'] + num_std * df['std']
    df['lower_band'] = df['ma'] - num_std * df['std']
    
    position = 0
    signals = []
    close_arr = df['close'].values
    upper_arr = df['upper_band'].values
    lower_arr = df['lower_band'].values
    ma_arr = df['ma'].values
    
    for i in range(len(df)):
        if np.isnan(upper_arr[i]):
            signals.append(0)
            continue
        c = close_arr[i]
        u = upper_arr[i]
        l = lower_arr[i]
        m = ma_arr[i]
        
        if c < l:
            position = 1
        elif c > u:
            position = -1
        elif exit_at_ma:
            if position == 1 and c > m: position = 0
            elif position == -1 and c < m: position = 0
        
        signals.append(position)
        
    df['signal'] = signals
    df['position'] = df['signal'].diff()
    df['returns'] = df['close'].pct_change()
    df['strategy_returns'] = df['signal'].shift(1) * df['returns']
    df['cumulative_returns'] = (1 + df['strategy_returns']).cumprod()
    return df


def run_vwap_strategy(data, window):
    """VWAP strategy: close all positions at end of day"""
    df = data.copy()
    p = df['close']
    v = df['volume']
    df['pv'] = p * v
    df['vwap'] = df['pv'].rolling(window=window).sum() / v.rolling(window=window).sum()
    df['signal'] = np.where(df['close'] > df['vwap'], 1, -1)
    df.iloc[:window, df.columns.get_loc('signal')] = 0
    
    dates = df.index.date
    is_last_bar_of_day = np.r_[dates[:-1] != dates[1:], True]
    df.loc[is_last_bar_of_day, 'signal'] = 0
    
    df['position'] = df['signal'].diff()
    df['returns'] = df['close'].pct_change()
    df['strategy_returns'] = df['signal'].shift(1) * df['returns']
    df['cumulative_returns'] = (1 + df['strategy_returns']).cumprod()
    return df


def run_intraday_momentum_strategy(data, window=14, vwap_window=20):
    """Intraday momentum strategy + VWAP exit"""
    df = data.copy()
    if df.index.name != 'datetime':
        df.index.name = 'datetime'
    
    p = df['close']
    v = df['volume']
    df['pv'] = p * v
    df['vwap'] = df['pv'].rolling(window=vwap_window).sum() / v.rolling(window=vwap_window).sum()
    
    df['date'] = df.index.date
    df['time_str'] = df.index.strftime('%H:%M')
    df['day_open'] = df.groupby('date')['open'].transform('first')
    df['offset'] = (df['close'] / df['day_open'] - 1).abs()
    
    pivot_offset = df.pivot_table(index='date', columns='time_str', values='offset')
    rolling_avg_offset = pivot_offset.rolling(window=window).mean().shift(1)
    stacked_avg = rolling_avg_offset.stack().rename('avg_offset')
    avg_df = stacked_avg.reset_index()
    
    df = pd.merge(df.reset_index(), avg_df, on=['date', 'time_str'], how='left').set_index('datetime')
    df['upper_limit'] = df['day_open'] * (1 + df['avg_offset'])
    df['lower_limit'] = df['day_open'] * (1 - df['avg_offset'])
    
    signals = []
    position = 0
    close_arr = df['close'].values
    upper_arr = df['upper_limit'].values
    lower_arr = df['lower_limit'].values
    vwap_arr = df['vwap'].values
    dates_arr = df['date'].values
    is_last_bar = np.r_[dates_arr[:-1] != dates_arr[1:], True]
    
    for i in range(len(df)):
        if np.isnan(upper_arr[i]) or np.isnan(vwap_arr[i]):
            signals.append(0)
            position = 0
            continue
        c = close_arr[i]
        u = upper_arr[i]
        l = lower_arr[i]
        vwap = vwap_arr[i]
        
        if is_last_bar[i]:
            position = 0
            signals.append(0)
            continue
            
        if position == 0:
            if c > u: position = 1
            elif c < l: position = -1
        elif position == 1:
            if c <= vwap: position = 0
        elif position == -1:
            if c >= vwap: position = 0
                
        signals.append(position)
    
    df['signal'] = signals
    df['position'] = df['signal'].diff()
    df['returns'] = df['close'].pct_change()
    df['strategy_returns'] = df['signal'].shift(1) * df['returns']
    df['cumulative_returns'] = (1 + df['strategy_returns']).cumprod()
    return df


def run_atr_mean_reversion_strategy(data, ema_window=11, atr_window=14, atr_mult=2.0, exit_at_ema=True):
    """ATR mean-reversion strategy.

    Bands: EMA(ema_window) ± atr_mult * ATR(atr_window)
    - Long when close < lower band
    - Short when close > upper band
    - Optional exit when price reverts back to EMA
    """
    df = data.copy()

    df['ema'] = df['close'].ewm(span=ema_window, adjust=False).mean()

    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    df['atr'] = true_range.rolling(window=atr_window).mean()

    mult = float(atr_mult) if atr_mult is not None else 2.0
    df['atr_upper'] = df['ema'] + mult * df['atr']
    df['atr_lower'] = df['ema'] - mult * df['atr']

    position = 0
    signals = []
    close_arr = df['close'].values
    upper_arr = df['atr_upper'].values
    lower_arr = df['atr_lower'].values
    ema_arr = df['ema'].values

    for i in range(len(df)):
        if np.isnan(upper_arr[i]) or np.isnan(lower_arr[i]) or np.isnan(ema_arr[i]):
            signals.append(0)
            continue

        c = close_arr[i]
        u = upper_arr[i]
        l = lower_arr[i]
        m = ema_arr[i]

        if c < l:
            position = 1
        elif c > u:
            position = -1
        elif exit_at_ema:
            if position == 1 and c >= m:
                position = 0
            elif position == -1 and c <= m:
                position = 0

        signals.append(position)

    df['signal'] = signals
    df['position'] = df['signal'].diff()
    df['returns'] = df['close'].pct_change()
    df['strategy_returns'] = df['signal'].shift(1) * df['returns']
    df['cumulative_returns'] = (1 + df['strategy_returns']).cumprod()
    return df


def run_atr_band_strategy(data, ema_window=20, atr_window=20):
    """
    ATR Band Strategy
    Baseline: EMA(n)
    Bands: EMA ± k * ATR(m), k=1,2,3
    Logic:
    - Buy 3 units when price breaks below lower band 3
    - Buy 2 units when price breaks below lower band 2
    - Buy 1 unit when price breaks below lower band 1
    - Sell 3 units when price breaks above upper band 3
    - Sell 2 units when price breaks above upper band 2
    - Sell 1 unit when price breaks above upper band 1
    - Uses layered independent signal stacking logic
    """
    df = data.copy()
    
    # 1. Calculate EMA
    df['ema'] = df['close'].ewm(span=ema_window, adjust=False).mean()
    
    # 2. Calculate ATR
    # TR = Max(H-L, |H-Cp|, |L-Cp|)
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    df['atr'] = true_range.rolling(window=atr_window).mean()
    
    # 3. Calculate bands
    df['upper_1'] = df['ema'] + 1 * df['atr']
    df['upper_2'] = df['ema'] + 2 * df['atr']
    df['upper_3'] = df['ema'] + 3 * df['atr']
    df['lower_1'] = df['ema'] - 1 * df['atr']
    df['lower_2'] = df['ema'] - 2 * df['atr']
    df['lower_3'] = df['ema'] - 3 * df['atr']
    
    # 4. Generate signals (layered stacking)
    # Layer 1: 1x ATR band (weight 1)
    s1 = pd.Series(np.nan, index=df.index)
    s1[df['close'] < df['lower_1']] = 1
    s1[df['close'] > df['upper_1']] = -1
    s1 = s1.ffill().fillna(0)
    
    # Layer 2: 2x ATR band (weight 2)
    s2 = pd.Series(np.nan, index=df.index)
    s2[df['close'] < df['lower_2']] = 2
    s2[df['close'] > df['upper_2']] = -2
    s2 = s2.ffill().fillna(0)
    
    # Layer 3: 3x ATR band (weight 3)
    s3 = pd.Series(np.nan, index=df.index)
    s3[df['close'] < df['lower_3']] = 3
    s3[df['close'] > df['upper_3']] = -3
    s3 = s3.ffill().fillna(0)
    
    # Combined signal
    df['signal'] = s1 + s2 + s3
    
    # 5. Calculate returns
    df['position'] = df['signal'].diff()
    df['returns'] = df['close'].pct_change()
    # Note: This assumes N units yield N times returns. If capital is limited, normalization is needed.
    # Here we simply treat it as leveraged/multiple returns.
    df['strategy_returns'] = df['signal'].shift(1) * df['returns']
    df['cumulative_returns'] = (1 + df['strategy_returns']).cumprod()
    
    return df


def run_sar_strategy(data, acceleration=0.02, maximum=0.2):
    """
    SAR (Parabolic Stop and Reverse) strategy
    """
    df = data.copy()
    
    # Try to import talib
    try:
        import talib
        # SAR requires High and Low
        if 'high' not in df.columns or 'low' not in df.columns:
            # If no High/Low available, use Close as substitute (though inaccurate, prevents errors)
            h = df['close']
            l = df['close']
        else:
            h = df['high']
            l = df['low']
            
        df['sar'] = talib.SAR(h, l, acceleration=acceleration, maximum=maximum)
    except ImportError:
        # Pure Python implementation of SAR
        # Ensure high/low data is available
        high = df['high'].values if 'high' in df.columns else df['close'].values
        low = df['low'].values if 'low' in df.columns else df['close'].values
        
        length = len(df)
        sar = np.zeros(length)
        trend = np.zeros(length) # 1 up, -1 down
        ep = np.zeros(length)
        af = np.zeros(length)
        
        # Initial state
        # Simple initialization: assume first bar is uptrend
        trend[0] = 1
        sar[0] = low[0]
        ep[0] = high[0]
        af[0] = acceleration
        
        for i in range(1, length):
            prev_sar = sar[i-1]
            prev_af = af[i-1]
            prev_ep = ep[i-1]
            prev_trend = trend[i-1]
            
            # Calculate tentative SAR
            curr_sar = prev_sar + prev_af * (prev_ep - prev_sar)
            
            if prev_trend == 1: # Uptrend
                # Check if trend reverses
                if low[i] < curr_sar:
                    trend[i] = -1
                    sar[i] = prev_ep # SAR becomes the extreme point of previous trend
                    ep[i] = low[i]
                    af[i] = acceleration
                else:
                    trend[i] = 1
                    # SAR constraint: cannot be higher than previous 2 lows
                    if i > 1:
                        curr_sar = min(curr_sar, low[i-1], low[i-2])
                    else:
                        curr_sar = min(curr_sar, low[i-1])
                    sar[i] = curr_sar
                    
                    # Update EP and AF
                    if high[i] > prev_ep:
                        ep[i] = high[i]
                        af[i] = min(prev_af + acceleration, maximum)
                    else:
                        ep[i] = prev_ep
                        af[i] = prev_af
                        
            else: # Downtrend
                # Check if trend reverses
                if high[i] > curr_sar:
                    trend[i] = 1
                    sar[i] = prev_ep
                    ep[i] = high[i]
                    af[i] = acceleration
                else:
                    trend[i] = -1
                    # SAR constraint: cannot be lower than previous 2 highs
                    if i > 1:
                        curr_sar = max(curr_sar, high[i-1], high[i-2])
                    else:
                        curr_sar = max(curr_sar, high[i-1])
                    sar[i] = curr_sar
                    
                    # Update EP and AF
                    if low[i] < prev_ep:
                        ep[i] = low[i]
                        af[i] = min(prev_af + acceleration, maximum)
                    else:
                        ep[i] = prev_ep
                        af[i] = prev_af
                        
        df['sar'] = sar

    # Generate signals
    # Close price > SAR -> Bullish (1)
    # Close price < SAR -> Bearish (-1)
    df['signal'] = np.where(df['close'] > df['sar'], 1, -1)
    
    # Calculate returns
    df['position'] = df['signal'].diff()
    df['returns'] = df['close'].pct_change()
    df['strategy_returns'] = df['signal'].shift(1) * df['returns']
    df['cumulative_returns'] = (1 + df['strategy_returns']).cumprod()
    
    return df
