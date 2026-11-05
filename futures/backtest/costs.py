"""Realistic accounting for the futures backtest: trading costs, flat-at-close, per-bar volume.

The strategy functions in strategies.py return gross, overnight-held results. apply_costs() re-derives
the P&L columns from the signal so every strategy is charged the same way.
"""

import re

import numpy as np
import pandas as pd

# bp of notional per side = measured median half-spread + exchange fee (2026-11-05, main contracts).
# CFFEX index futures charge ~2.3bp to close a position opened the same day, which dominates IC.
DEFAULT_COST_BP = {'AU': 0.4, 'TL': 0.5, 'IC': 1.9}
FALLBACK_COST_BP = 1.0
# Approximate exchange fee per side, bp of notional, used when the spread is measured (walkforward.py)
FEE_BP = {'IC': 1.3, 'IF': 1.3, 'IH': 1.3, 'IM': 1.3, 'T': 0.05, 'TF': 0.05, 'TS': 0.05, 'TL': 0.05, 'AU': 0.1}
DEFAULT_FEE_BP = 0.5


def product_of(symbol):
    """'TL2612' / 'TL.CFE' / 'sa601' -> 'TL' / 'TL' / 'SA'."""
    m = re.match(r'[A-Za-z]+', symbol or '')
    return m.group().upper() if m else None


def default_cost_bp(symbol):
    return DEFAULT_COST_BP.get(product_of(symbol), FALLBACK_COST_BP)


def per_bar_volume(df):
    """Per-tick volume from Wind's volume, which is cumulative within each day.

    Summing the cumulative figure per bar (what resample_data does) overweights late-day ticks and
    breaks VWAP/Momentum. Returns df['volume'] unchanged when it is already per-tick.
    """
    vol = pd.to_numeric(df['volume'], errors='coerce')
    day = df.index.normalize()
    step = vol.groupby(day).diff()
    if (step.dropna() < 0).mean() > 0.01:  # not cumulative
        return vol
    return step.clip(lower=0).fillna(0.0)


def apply_costs(res, cost_bp, flat_at_close):
    """Re-derive strategy_returns / cumulative_returns from res['signal'].

    flat_at_close: force the position flat on each day's last bar (no overnight risk).
    cost_bp: charged on every change of position, per unit of notional, per side (a reversal pays twice).
    """
    df = res.copy()
    sig = df['signal'].astype(float)
    if flat_at_close:
        day = df.index.normalize()
        sig[np.r_[day[:-1] != day[1:], True]] = 0.0
    ret = df['close'].pct_change().fillna(0.0)
    turn = sig.diff().abs()
    turn.iloc[0] = abs(sig.iloc[0])
    df['signal'] = sig
    df['strategy_returns'] = sig.shift(1).fillna(0.0) * ret - turn * cost_bp * 1e-4
    df['cumulative_returns'] = (1 + df['strategy_returns']).cumprod()
    return df


def trade_stats(res, cost_bp=0.0):
    """Round-trip trade statistics from a result frame (after apply_costs).

    A trade is a run of constant non-zero position; its P&L is the gross return over the run less
    the entry and exit cost. Returns count, win rate, payoff (avg win / avg loss) and expectancy in bp.
    """
    held = res['signal'].astype(float).shift(1).fillna(0.0)
    gross = held * res['close'].pct_change().fillna(0.0)
    run = (held != held.shift()).cumsum()
    live = held != 0
    if not live.any():
        return {'trades': 0, 'win': np.nan, 'payoff': np.nan, 'expectancy_bp': np.nan}
    pnl = gross[live].groupby(run[live]).sum() - 2 * cost_bp * 1e-4
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    return {
        'trades': int(len(pnl)),
        'win': float((pnl > 0).mean()),
        'payoff': float(wins.mean() / -losses.mean()) if len(wins) and len(losses) else np.nan,
        'expectancy_bp': float(pnl.mean() * 1e4),
    }
