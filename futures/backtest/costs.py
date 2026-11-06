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


def normalize_exits(stop=None, target=None, unit='pct'):
    """{'stop', 'target', 'unit'}, or None when neither is set. unit 'pct' = % of the entry price,
    'pts' = price points. Blank or non-positive values are off."""
    def _val(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return v if v > 0 else None
    stop, target = _val(stop), _val(target)
    if stop is None and target is None:
        return None
    return {'stop': stop, 'target': target, 'unit': 'pts' if unit == 'pts' else 'pct'}


def describe_exits(exits):
    if exits == 'search':
        return "stop / target searched per candidate"
    if not exits:
        return "no stop / target"
    u = '%' if exits['unit'] == 'pct' else ' pts'
    parts = ([f"stop {exits['stop']:g}{u}"] if exits.get('stop') else []) + \
            ([f"target {exits['target']:g}{u}"] if exits.get('target') else [])
    return ' · '.join(parts)


def apply_exits(df, sig, exits):
    """Overlay a stop loss / profit target on a position signal.

    A position is entered at the close of the bar where the signal changes; from the next bar on, the bar's
    low / high is checked against the stop and the target (stop first when both are touched; a gap through
    the level fills at the open). After an exit the position stays flat until the signal changes, so the
    strategy does not re-enter on the same signal. Returns (signal, fill): fill is the price the position
    is marked at on each bar (the close, or the exit price on an exit bar)."""
    c = df['close'].to_numpy(dtype=float)
    o = df['open'].to_numpy(dtype=float) if 'open' in df else c
    h = df['high'].to_numpy(dtype=float) if 'high' in df else c
    lo = df['low'].to_numpy(dtype=float) if 'low' in df else c
    s = np.asarray(sig, dtype=float)
    pct = exits['unit'] == 'pct'
    dist = lambda entry, v: None if v is None else (entry * v / 100 if pct else v)
    out, fill = np.zeros(len(s)), c.copy()
    pos, entry, locked = 0.0, np.nan, None
    for i in range(len(s)):
        if pos != 0:
            px = None
            sd, td = dist(entry, exits.get('stop')), dist(entry, exits.get('target'))
            if sd is not None:
                level = entry - pos * sd
                if (lo[i] <= level) if pos > 0 else (h[i] >= level):
                    px = min(o[i], level) if pos > 0 else max(o[i], level)
            if px is None and td is not None:
                level = entry + pos * td
                if (h[i] >= level) if pos > 0 else (lo[i] <= level):
                    px = max(o[i], level) if pos > 0 else min(o[i], level)
            if px is not None:
                fill[i], locked, pos = px, pos, 0.0
                continue
        if locked is not None:
            if s[i] == locked:
                continue
            locked = None
        if s[i] != pos:
            pos = s[i]
            entry = c[i] if pos != 0 else np.nan
        out[i] = pos
    return pd.Series(out, index=df.index), pd.Series(fill, index=df.index)


def apply_costs(res, cost_bp, flat_at_close, exits=None, final_bar_is_close=True):
    """Re-derive strategy_returns / cumulative_returns from res['signal'].

    flat_at_close: force the position flat on each day's last bar (no overnight risk).
    cost_bp: charged on every change of position, per unit of notional, per side (a reversal pays twice).
    exits: optional stop loss / profit target (see normalize_exits / apply_exits).
    final_bar_is_close: False when the last bar is mid-session (live data), so it is not forced flat.
    """
    df = res.copy()
    sig = df['signal'].astype(float)
    if flat_at_close:
        day = df.index.normalize()
        sig[np.r_[day[:-1] != day[1:], bool(final_bar_is_close)]] = 0.0
    fill = df['close']
    if exits:
        sig, fill = apply_exits(df, sig, exits)
    ret = (fill / df['close'].shift(1) - 1).fillna(0.0)
    turn = sig.diff().abs()
    turn.iloc[0] = abs(sig.iloc[0])
    df['signal'] = sig
    df['fill'] = fill
    df['strategy_returns'] = sig.shift(1).fillna(0.0) * ret - turn * cost_bp * 1e-4
    df['cumulative_returns'] = (1 + df['strategy_returns']).cumprod()
    return df


def trade_stats(res, cost_bp=0.0):
    """Round-trip trade statistics from a result frame (after apply_costs).

    A trade is a run of constant non-zero position; its P&L is the gross return over the run less
    the entry and exit cost. Returns count, win rate, payoff (avg win / avg loss) and expectancy in bp.
    """
    held = res['signal'].astype(float).shift(1).fillna(0.0)
    px = res['fill'] if 'fill' in res else res['close']
    gross = held * (px / res['close'].shift(1) - 1).fillna(0.0)
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
