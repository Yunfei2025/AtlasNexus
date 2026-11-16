"""Night session merged into the trading day.

A Chinese futures trading day starts the evening before: the 21:00 night session belongs to the NEXT trading
day, whose day session closes at 15:00. The desk's machinery (strategies, apply_costs, daily P&L) keys a
session on the bar's calendar date, so night bars are re-stamped onto their trade date at the clock time
`t - 21h` (21:00 -> 00:00, 02:30 -> 05:30). The shift is a whole number of hours, so 15min / 30min / 1h bars
stay aligned, and every night bar sorts before the 09:00 day open of the same trade date. Positions are then
carried night -> day and forced flat at the 15:00 close as before; the 02:30 -> 09:00 break is held like lunch.

Night history exists only from when it was fetched (live/night_history), so most days have no night bars; a
day without them is simply the day session as before.
"""

from __future__ import annotations

import os

import pandas as pd

NIGHT_SHIFT_BACK = pd.Timedelta(hours=6)    # night timestamp - 6h falls on the evening the session started
NIGHT_OPEN = pd.Timedelta(hours=21)
MIN_NIGHT_BARS = 30                         # fewer minute bars than this on a trade date is not a night session


def daily_volume(product, tick_dir=None, bar_dir=None):
    """Day-session volume per trade date (rows) and contract (columns) of a product, from the bar cache."""
    from .minute_bars import list_contracts, load_minute_bars
    cols = {}
    for c in list_contracts(product, tick_dir, bar_dir):
        b = load_minute_bars(c, tick_dir, bar_dir)
        if b is not None and len(b):
            cols[c] = b['volume'].groupby(b.index.normalize()).sum()
    return pd.DataFrame(cols).sort_index()


def main_after(dvol, night_date):
    """The contract a night session belongs to: the one with the most day volume on the first trade day after the
    night (the walk-forward's own main-contract rule). A night with no later day yet (tonight's) takes the last
    known main. None when there is no volume data."""
    if dvol is None or dvol.empty:
        return None
    later = dvol.index[dvol.index > pd.Timestamp(night_date)]
    row = dvol.loc[later[0] if len(later) else dvol.index[-1]].dropna()
    return row.idxmax() if len(row) and row.max() > 0 else None


def load_night_history(contract, live_dir=None):
    """Archived night minute bars of one contract (live/night_history/<contract>.parquet), or None."""
    from .live_bars import NIGHT_HISTORY_DIR, _dir
    path = os.path.join(str(_dir(live_dir)), NIGHT_HISTORY_DIR, f'{contract}.parquet')
    if not os.path.exists(path):
        return None
    bars = pd.read_parquet(path)
    return bars if len(bars) else None


def night_signature(contract, live_dir=None):
    """[mtime, size] of a contract's night history file (None when it has none): the bar cache records it, so a
    new night makes the cached file stale."""
    from .live_bars import NIGHT_HISTORY_DIR, _dir
    path = os.path.join(str(_dir(live_dir)), NIGHT_HISTORY_DIR, f'{contract}.parquet')
    if not os.path.exists(path):
        return None
    st = os.stat(path)
    return [st.st_mtime, st.st_size]


DAY_OPEN = pd.Timedelta(hours=8)   # night bars are re-stamped before this clock time; every day-session bar is after it


def strip_night(bars):
    """The day-session bars only: what the minute-bar cache held before night bars were joined to it."""
    if bars is None or bars.empty:
        return bars
    return bars[(bars.index - bars.index.normalize()) >= DAY_OPEN]


def night_to_trade_day(night, trade_days):
    """Re-stamp night bars onto their trade date (see module doc). `trade_days` is the sorted index of day-session
    dates; a night's trade date is the first one after the evening it started. Nights with no later trade day yet
    (the newest one) have no day session to join and are dropped."""
    if night is None or night.empty:
        return night
    start_day = (night.index - NIGHT_SHIFT_BACK).normalize()
    pos = pd.DatetimeIndex(trade_days).sort_values().searchsorted(start_day, side='right')
    days = pd.DatetimeIndex(trade_days).sort_values()
    ok = pos < len(days)
    out = night[ok].copy()
    out.index = days[pos[ok]] + (night.index[ok] - (start_day[ok] + NIGHT_OPEN))
    return out.sort_index()


def with_night(day_bars, night):
    """Day-session minute bars plus the night bars of the nights that precede each of their trade dates."""
    if night is None or night.empty:
        return day_bars
    shifted = night_to_trade_day(night, day_bars.index.normalize().unique())
    if shifted is None or shifted.empty:
        return day_bars
    both = pd.concat([shifted.reindex(columns=day_bars.columns), day_bars])
    return both[~both.index.duplicated(keep='last')].sort_index()


def restamp_onto(night, trade_day):
    """Night bars placed on a given trade date (for tonight's session, whose day bars do not exist yet)."""
    if night is None or night.empty:
        return night
    start_day = (night.index - NIGHT_SHIFT_BACK).normalize()
    out = night.copy()
    out.index = pd.Timestamp(trade_day).normalize() + (night.index - (start_day + NIGHT_OPEN))
    return out.sort_index()


def unshift(ts, days):
    """Real exchange time of a stamp taken from a night + day frame: a day-session stamp is returned as is, a
    night one (clock time before 08:00 on its trade date) goes back to 21:00 + offset on the previous trade
    date. `days` is the sorted DatetimeIndex of the frame's day-session dates (the trade date itself may be
    missing, e.g. tonight's)."""
    if ts is None or (not isinstance(ts, pd.Timestamp) and pd.isna(ts)):
        return ts
    ts = pd.Timestamp(ts)
    d = ts.normalize()
    off = ts - d
    if off >= DAY_OPEN:
        return ts
    i = days.searchsorted(d)
    prev = days[i - 1] if i > 0 else d - pd.Timedelta(days=1)
    return prev + NIGHT_OPEN + off


def night_trade_days(bars):
    """Trade dates of `bars` (a with_night frame) that carry a real night session."""
    t = bars.index
    pre = t[(t - t.normalize()) < pd.Timedelta(hours=8)]
    counts = pd.Series(1, index=pre.normalize()).groupby(level=0).sum()
    return counts[counts >= MIN_NIGHT_BARS].index
