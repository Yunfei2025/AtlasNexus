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

# CNY per 1.0 move of the quoted price, per lot (exchange contract specs, typed in: verify before sizing orders).
CONTRACT_MULTIPLIER = {
    'IF': 300, 'IH': 300, 'IC': 200, 'IM': 200,
    'T': 10000, 'TF': 10000, 'TS': 20000, 'TL': 10000,
    'AU': 1000, 'AG': 15, 'CU': 5, 'AL': 5, 'ZN': 5, 'RB': 10,
    'LC': 1, 'SA': 20, 'SC': 1000, 'JM': 60, 'EC': 50,
}

# Exchange fees: (unit, open, close-today), unit 'bp' = 1/10000 of turnover, 'cny' = CNY per lot. The desk is flat at
# every close, so each round trip pays the open fee and the close-today (平今) fee. Source: 9qihuo.com exchange fee
# table, update 2026-11-25 21:14 (main contracts: 2612/2701/2702/2703); per-month rules for older AG / AU / RB months
# from a broker's table of exchange fees (May 2026). Broker add-ons are NOT included: set FEE_MARKUP to your own.
# Exchanges change these (especially close-today fees on hot products): re-check before relying on a backtest.
EXCHANGE_FEES = {
    'IF': ('bp', 0.23, 2.3), 'IH': ('bp', 0.23, 2.3), 'IC': ('bp', 0.23, 2.3), 'IM': ('bp', 0.23, 2.3),
    'T': ('cny', 3, 0), 'TF': ('cny', 3, 0), 'TS': ('cny', 3, 0), 'TL': ('cny', 3, 0),
    'AU': ('cny', 10, 0), 'AG': ('bp', 0.1, 0.1), 'CU': ('bp', 0.5, 1.0), 'AL': ('cny', 3, 3),
    'ZN': ('cny', 3, 0), 'RB': ('bp', 0.2, 0.2),
    'SC': ('cny', 20, 0), 'EC': ('bp', 6.0, 12.0),
    'JM': ('bp', 1.0, 1.0), 'SA': ('bp', 1.0, 1.0), 'LC': ('bp', 0.8, 0.8),
}
# Delivery-month overrides: {product: {months: (unit, open, close-today)}} (contract month = last two digits)
EXCHANGE_FEE_MONTHS = {
    'AG': {('06', '12'): ('bp', 0.5, 1.5)},
    'AU': {('06', '12'): ('cny', 20, 0)},
    'RB': {('01', '05', '10'): ('bp', 1.0, 1.0)},
}
FEE_MARKUP = 1.0   # multiply exchange fees by this to include your broker's add-on (e.g. 1.5)
DEFAULT_FEE_BP = 0.5   # products without a fee entry


def _fee_schedule(contract):
    prod = product_of(contract)
    month = re.sub(r'\D', '', contract or '')[-2:]
    for months, sched in EXCHANGE_FEE_MONTHS.get(prod, {}).items():
        if month in months:
            return sched
    return EXCHANGE_FEES.get(prod)


def fee_bp(contract, price=None, overnight=False):
    """Exchange fee in bp of notional PER SIDE for one contract ('AG2612' or a bare product 'AG'): the average of
    the open fee and the close-today fee (overnight=True: the ordinary close fee, which equals the open fee).
    Per-lot fees are converted at `price` x the contract multiplier; without a price they count as 0.
    Products without a schedule get DEFAULT_FEE_BP."""
    sched = _fee_schedule(contract)
    if sched is None:
        return DEFAULT_FEE_BP
    unit, opn, close_today = sched
    close = opn if overnight else close_today
    if unit == 'bp':
        per_side = (opn + close) / 2
    else:
        mult = CONTRACT_MULTIPLIER.get(product_of(contract))
        if not price or not mult:
            return 0.0
        per_side = (opn + close) / 2 / (float(price) * mult) * 1e4
    return per_side * FEE_MARKUP




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


def fee_rates(contract, price):
    """(open, close_today, close) exchange fee in bp of notional per side, each a float array aligned with `price`
    (per-lot fees depend on the price), or None when the product has no schedule. A bare product code uses the
    product's ordinary months (continuous daily series)."""
    sched = _fee_schedule(contract)
    if sched is None:
        return None
    unit, opn, close_today = sched
    px = np.asarray(price, dtype=float)
    if unit == 'bp':
        conv = np.ones_like(px)
    else:
        mult = CONTRACT_MULTIPLIER.get(product_of(contract))
        conv = 1e4 / (px * mult) if mult else np.zeros_like(px)
    m = FEE_MARKUP
    return opn * conv * m, close_today * conv * m, opn * conv * m


def fee_returns(sig, index, rates):
    """Fee per bar as a fraction of notional for position path `sig`: every unit opened pays the open fee; every
    unit closed pays the close-today fee if its position was opened on the same trading day (the bar's calendar
    date: night bars are stamped onto their trade date), else the ordinary close fee. A reversal closes and opens.
    Adding to a position keeps the first entry's day (a simplification for stacked units)."""
    s = np.asarray(sig, dtype=float)
    prev = np.r_[0.0, s[:-1]]
    flip = np.sign(prev) * np.sign(s) < 0
    opened = np.where(flip, np.abs(s), np.clip(np.abs(s) - np.abs(prev), 0, None))
    closed = np.where(flip, np.abs(prev), np.clip(np.abs(prev) - np.abs(s), 0, None))
    day = pd.DatetimeIndex(index).normalize().to_numpy()
    f_open, f_today, f_close = rates
    out = np.zeros(len(s))
    entry = None
    for i in range(len(s)):
        if closed[i] > 0:
            out[i] += closed[i] * (f_today[i] if entry is not None and day[i] == entry else f_close[i])
        if opened[i] > 0:
            out[i] += opened[i] * f_open[i]
            if prev[i] == 0 or flip[i]:
                entry = day[i]
        if s[i] == 0:
            entry = None
    return out * 1e-4


def apply_costs(res, cost_bp, flat_at_close, exits=None, final_bar_is_close=True, fees=None):
    """Re-derive strategy_returns / cumulative_returns from res['signal'].

    flat_at_close: force the position flat on each day's last bar (no overnight risk).
    cost_bp: charged on every change of position, per unit of notional, per side (a reversal pays twice).
    exits: optional stop loss / profit target (see normalize_exits / apply_exits).
    final_bar_is_close: False when the last bar is mid-session (live data), so it is not forced flat.
    fees: a contract code ('AG2612', or a bare product for a continuous series). The exchange fee is then charged
    by holding period (fee_returns: close-today vs ordinary close) ON TOP of cost_bp, which should then be the
    half-spread only. None (default): cost_bp is the whole cost.
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
    rates = fee_rates(fees, df['close']) if fees else None
    if rates is not None:
        df['strategy_returns'] -= fee_returns(sig, df.index, rates)
    elif fees:   # product without a schedule: the default fee per side
        df['strategy_returns'] -= turn * DEFAULT_FEE_BP * 1e-4
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


# Kept for callers that only know the product: the main contract's intraday fee at a typical price.
FEE_BP = {p: round(fee_bp(p, price), 3) for p, price in {
    'IF': 4500, 'IH': 3000, 'IC': 6000, 'IM': 6500, 'T': 108, 'TF': 106, 'TS': 102, 'TL': 118, 'AU': 750,
    'AG': 9000, 'CU': 90000, 'AL': 21000, 'ZN': 23000, 'RB': 3100, 'SC': 480, 'EC': 1500, 'JM': 1400,
    'SA': 1300, 'LC': 90000}.items()}
