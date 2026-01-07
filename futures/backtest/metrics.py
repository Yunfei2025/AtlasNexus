"""
Strategy evaluation metrics module
Contains strategy performance calculation and evaluation functions
"""

import pandas as pd
import numpy as np


def calculate_metrics(df):
    """Calculate strategy metrics"""
    if df is None or len(df) == 0:
        return {}
    total_return = (df['cumulative_returns'].iloc[-1] - 1) * 100
    days = (df.index[-1] - df.index[0]).days
    if days <= 0: days = 1
    annual_return = (df['cumulative_returns'].iloc[-1] ** (365 / days) - 1) * 100
    cum = df['cumulative_returns']
    drawdown = (cum - cum.expanding().max()) / cum.expanding().max()
    max_drawdown = drawdown.min() * 100
    trades = (df['signal'].diff().abs() > 0).sum()
    try:
        daily_returns = df['strategy_returns'].resample('D').apply(lambda x: (1+x).prod() - 1)
        daily_returns = daily_returns[daily_returns != 0]
        if len(daily_returns) > 1:
            rf = 0.02
            ann_ret = daily_returns.mean() * 252
            ann_vol = daily_returns.std() * np.sqrt(252)
            sharpe = (ann_ret - rf) / ann_vol if ann_vol > 0 else 0
        else:
            sharpe = 0
    except:
        sharpe = 0
    return {
        "Total Return": f"{total_return:.2f}%",
        "Annualized Return": f"{annual_return:.2f}%",
        "Max Drawdown": f"{max_drawdown:.2f}%",
        "Trades": trades,
        "Sharpe Ratio": f"{sharpe:.2f}"
    }


def calculate_metrics_numeric(df):
    """Calculate numeric metrics for comparison"""
    if df is None or len(df) == 0:
        return {'sharpe': -np.inf, 'calmar': -np.inf}
    
    try:
        # Sharpe
        daily_returns = df['strategy_returns'].resample('D').apply(lambda x: (1+x).prod() - 1)
        daily_returns = daily_returns[daily_returns != 0]
        if len(daily_returns) > 1:
            ann_ret = daily_returns.mean() * 252
            ann_vol = daily_returns.std() * np.sqrt(252)
            sharpe = (ann_ret - 0.02) / ann_vol if ann_vol > 0 else -np.inf
        else:
            sharpe = -np.inf
            
        # Calmar
        cum = df['cumulative_returns']
        drawdown = (cum - cum.expanding().max()) / cum.expanding().max()
        max_dd = drawdown.min() # negative
        
        days = (df.index[-1] - df.index[0]).days
        if days <= 0: days = 1
        total_ret = df['cumulative_returns'].iloc[-1] - 1
        ann_ret_rate = (1 + total_ret) ** (365 / days) - 1
        
        if max_dd < 0:
            calmar = ann_ret_rate / abs(max_dd)
        else:
            calmar = 100 if ann_ret_rate > 0 else -np.inf
            
        return {'sharpe': sharpe, 'calmar': calmar}
    except:
        return {'sharpe': -np.inf, 'calmar': -np.inf}


def run_rolling_best_strategy(data, strategies_dict, lookback_months=6):
    """
    Rolling best strategy
    strategies_dict: { 'StrategyName': df_result, ... }
    """
    df = data.copy()
    
    # Initialize result columns
    df['signal'] = 0
    df['best_strategy'] = 'None'
    
    if not strategies_dict:
        df['position'] = 0
        df['strategy_returns'] = 0
        df['cumulative_returns'] = 1.0
        return df

    # Get monthly start times
    month_starts = df.resample('MS').first().index
    
    if len(month_starts) <= lookback_months:
        # Insufficient data
        df['position'] = 0
        df['strategy_returns'] = 0
        df['cumulative_returns'] = 1.0
        return df
        
    # Start trading from lookback_months month
    for i in range(lookback_months, len(month_starts)):
        curr_month = month_starts[i]
        # Evaluation window: [curr_month - 6 months, curr_month)
        eval_start = month_starts[i - lookback_months]
        eval_end = curr_month
        
        # Next month start time
        next_month = month_starts[i+1] if i+1 < len(month_starts) else df.index[-1] + pd.Timedelta(seconds=1)
        
        best_score = -np.inf
        best_name = list(strategies_dict.keys())[0] # Default
        
        # Evaluate each strategy's performance in eval window
        for name, strat_df in strategies_dict.items():
            # Slice
            mask_eval = (strat_df.index >= eval_start) & (strat_df.index < eval_end)
            df_eval = strat_df.loc[mask_eval]
            
            if df_eval.empty: continue
            
            metrics = calculate_metrics_numeric(df_eval)
            sharpe = metrics['sharpe']
            calmar = metrics['calmar']
            
            # Scoring logic: Sharpe + Calmar
            score = sharpe + calmar
            
            if score > best_score:
                best_score = score
                best_name = name
        
        # Apply winning strategy's signal to current month
        mask_trade = (df.index >= curr_month) & (df.index < next_month)
        if best_name in strategies_dict:
            df.loc[mask_trade, 'signal'] = strategies_dict[best_name].loc[mask_trade, 'signal']
            df.loc[mask_trade, 'best_strategy'] = best_name

    # Set signals for first 6 months to 0
    first_trade_date = month_starts[lookback_months]
    df.loc[df.index < first_trade_date, 'signal'] = 0
    
    # Calculate returns
    df['position'] = df['signal'].diff()
    df['returns'] = df['close'].pct_change()
    df['strategy_returns'] = df['signal'].shift(1) * df['returns']
    
    # Cumulative returns start from first trading day
    df.loc[df.index < first_trade_date, 'strategy_returns'] = 0
    
    df['cumulative_returns'] = (1 + df['strategy_returns']).cumprod()
    
    return df
