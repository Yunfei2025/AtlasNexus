"""Live 1-minute bars for the Futures Desk Monitor, fetched from Wind only for the products asked for.

One small `wsi` call per product and refresh: only the minutes after the last stored bar are requested, and the
result is merged into input/futures_desk/live/<contract>.parquet (today's bars only, replaced each day). Outside
trading hours nothing is requested. FI_DISABLE_WIND (set by the daily console) blocks only the passive view;
▶ Start live is an explicit request and calls Wind on demand (in the isolated Wind worker). The desk reads these files as an overlay on
top of the settled minute-bar cache; they never enter the cache, the walk-forward or the Monitor's forward
statuses.

All times are Beijing (exchange) time whatever the machine's clock: session hours, Wind bar timestamps and
the live files. Only the day session is modelled (as in the minute-bar cache and the walk-forward). Night
sessions (products in NIGHT_END) are fetched separately by fetch_night_bars into <contract>_night.parquet /
index_night.json, for display only: no history exists for them, so they never enter the cache, the
walk-forward, the Monitor statuses or the book. Every night fetched is also merged into
night_history/<contract>.parquet so night history accumulates from now on (no backfill).

After the close the last session is fetched once (marked 'complete' in index.json) and then served from the
file, so the Monitor can show the finished day without calling Wind again.
"""

import json
import os
import re
import threading
from datetime import datetime, timedelta

import pandas as pd

from settings.paths import DIR_INPUT

LIVE_DIR = DIR_INPUT / 'futures_desk' / 'live'
SESSION_START = '08:55:00'
CLOSE_TIME = '15:15:00'   # after this a day session is over (CFFEX bond futures close 15:15)
FIELDS = "open,high,low,close,volume"
OVERLAP_MIN = 2   # re-request the last minutes: the newest bar is still forming when it was fetched
fetch_lock = threading.Lock()
EXCHANGE_TZ = 'Asia/Shanghai'


def china_now():
    """Current Beijing (exchange) time as a naive datetime, to compare with session times and bar stamps."""
    return pd.Timestamp.now(tz=EXCHANGE_TZ).tz_localize(None).to_pydatetime()


def in_day_session(now):
    """True between SESSION_START and CLOSE_TIME on a weekday (Beijing time; holidays show up as no bars)."""
    t = now.strftime('%H:%M:%S')
    return now.weekday() < 5 and SESSION_START <= t < CLOSE_TIME


def _dir(live_dir):
    return live_dir or LIVE_DIR


def session_days(now, n=5):
    """Candidate session days, newest first: today once the session has started, else the previous weekday,
    then earlier weekdays (n of them, so a holiday falls back to the last day that traded)."""
    d = now.date()
    if now.weekday() >= 5 or now.strftime('%H:%M:%S') < SESSION_START:
        d -= timedelta(days=1)
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.strftime('%Y-%m-%d'))
        d -= timedelta(days=1)
    return out


def _product(code):
    m = re.match(r'[A-Za-z]+', code or '')
    return m.group().upper() if m else None


def main_contract_codes(codes=None):
    """{'AU': 'AU2612.SHF', ...} from today's main-contract list (cached in input/futures-code.pkl; the Wind
    lookup behind it only runs when that file is missing or older than a week)."""
    if codes is None:
        from settings.futures import FuturesConfig
        codes = FuturesConfig.get_contract_no()
    return {_product(c): c for c in codes if _product(c)}


def load_index(live_dir=None):
    try:
        with open(os.path.join(str(_dir(live_dir)), 'index.json'), encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save_index(index, live_dir):
    d = str(_dir(live_dir))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'index.json.tmp'), 'w', encoding='utf-8') as fh:
        json.dump(index, fh, indent=1, sort_keys=True)
    os.replace(os.path.join(d, 'index.json.tmp'), os.path.join(d, 'index.json'))


def load_live(contract, live_dir=None):
    """(bars, meta) of a contract's live file, or (None, None)."""
    path = os.path.join(str(_dir(live_dir)), f'{contract}.parquet')
    meta = load_index(live_dir).get(contract)
    if not meta or not os.path.exists(path):
        return None, None
    return pd.read_parquet(path), meta


def live_meta_for(product, live_dir=None):
    """Most recently fetched live entry of a product as (contract, meta), or (None, None)."""
    entries = [(c, m) for c, m in load_index(live_dir).items() if m.get('product') == product]
    return max(entries, key=lambda e: e[1].get('fetched_at', ''), default=(None, None))


def with_live(bars, live):
    """Merge the live minute bars onto the settled cache, keeping the newest value at overlapping timestamps.

    A same-day cache may already contain earlier intraday rows (for example from a partial sync or an older
    local file), but the live session still needs to overlay the newest bars for today. We therefore merge
    both sources and let the later live timestamps win, rather than discarding the live slice whenever the
    dates overlap.
    """
    if live is None or live.empty:
        return bars
    if bars is None or bars.empty:
        return live
    merged = pd.concat([bars, live[bars.columns]], sort=True)
    return merged[~merged.index.duplicated(keep='last')].sort_index()


def _normalize(frame, day):
    """Wind wsi frame -> minute bars of `day` (open/high/low/close/volume, hs_bp unknown)."""
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame()
    f = frame.copy()
    f.columns = [str(c).lower() for c in f.columns]
    f.index = pd.to_datetime(f.index, errors='coerce')
    f = f[f.index.notna()].sort_index()
    for c in ('open', 'high', 'low', 'close', 'volume'):
        f[c] = pd.to_numeric(f.get(c), errors='coerce')
    f = f.dropna(subset=['close'])
    f = f[(f['close'] > 0) & (f.index.normalize() == pd.Timestamp(day))]
    f['volume'] = f['volume'].fillna(0.0)
    f['hs_bp'] = float('nan')
    return f[['open', 'high', 'low', 'close', 'volume', 'hs_bp']].astype({'hs_bp': 'float32'})


def fetch_live_bars(products, now=None, wsi=None, codes=None, is_trading=None, live_dir=None,
                    closed_only=False, wind_off=None, on_demand=None):
    """Fetch the day's minute bars of each product's main contract and merge them into the live files.

    Market open: today's bars, incrementally. Market closed: the last session once, then nothing (the file is
    marked complete). closed_only=True never fetches while the market is open (the Monitor shows the finished
    day without Start). on_demand (default: not closed_only, i.e. the user pressed Start) calls Wind even when
    FI_DISABLE_WIND is set; the passive view respects it. `now` defaults to Beijing time. Returns {'skipped': reason or None, 'products': {product: {'contract', 'rows', 'new',
    'last'} or {'error'}}, 'session': 'open' | 'closed', 'now': Beijing time}. `wsi`, `codes`, `is_trading`
    and `wind_off` can be injected (tests)."""
    now = now or china_now()
    on_demand = (not closed_only) if on_demand is None else bool(on_demand)
    if is_trading is None:
        is_trading = in_day_session
    t = now.strftime('%H:%M:%S')
    past_close = now.weekday() >= 5 or t >= CLOSE_TIME or t < SESSION_START
    open_now = bool(is_trading(now)) and not past_close
    info = {'session': 'open' if open_now else 'closed', 'now': now}
    if open_now and closed_only:
        return {'skipped': 'market open: press Start live for intraday updates', 'products': {}, **info}
    if not on_demand:
        if wind_off is None:
            from data.providers.retrieve import _wind_disabled as wind_off
        if wind_off():
            return {'skipped': 'Wind disabled', 'products': {}, **info}
    if wsi is None:
        from data.providers.retrieve import _wsi

        def wsi(*args):
            return _wsi(*args, on_demand=on_demand)
    out = {}
    today = now.strftime('%Y-%m-%d')
    with fetch_lock:
        try:
            code_of = main_contract_codes(codes)
        except Exception as e:
            return {'skipped': f'main contract lookup failed: {e}', 'products': {}, **info}
        index = load_index(live_dir)
        for prod in products:
            code = code_of.get(prod)
            if not code:
                out[prod] = {'error': 'no main contract code on file'}
                continue
            contract = code.split('.')[0]
            try:
                for day in ([today] if open_now else session_days(now)):
                    old, meta = load_live(contract, live_dir)
                    same = old is not None and meta and meta.get('date') == day and not old.empty
                    if same and meta.get('complete') and not open_now:
                        out[prod] = {'contract': contract, 'rows': int(len(old)), 'new': 0, 'last': old.index.max()}
                        break
                    if same:
                        start = (old.index.max() - timedelta(minutes=OVERLAP_MIN)).strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        old, start = None, f'{day} {SESSION_START}'
                    end = now.strftime('%Y-%m-%d %H:%M:%S') if day == today and open_now else f'{day} 15:30:00'
                    new = _normalize(wsi(code, FIELDS, start, end), day)
                    if new.empty and old is None:
                        if open_now:
                            out[prod] = {'error': 'Wind returned no bars (not connected, or the session has not '
                                                  'started)'}
                            break
                        out[prod] = {'error': f'Wind returned no bars for {day} (not connected, or a holiday)'}
                        continue   # earlier day
                    merged = new if old is None else pd.concat([old, new])
                    merged = merged[~merged.index.duplicated(keep='last')].sort_index()
                    d = str(_dir(live_dir))
                    os.makedirs(d, exist_ok=True)
                    tmp = os.path.join(d, f'{contract}.parquet.tmp')
                    merged.to_parquet(tmp, compression='zstd')
                    os.replace(tmp, os.path.join(d, f'{contract}.parquet'))
                    index = {c: m for c, m in index.items()
                             if not (m.get('product') == prod and (c == contract or m.get('date') != day))}
                    index[contract] = {'product': prod, 'date': day, 'fetched_at': now.strftime('%Y-%m-%d %H:%M:%S'),
                                       'last': str(merged.index.max()), 'rows': int(len(merged)),
                                       'complete': bool(not open_now and (day != today or past_close))}
                    out[prod] = {'contract': contract, 'rows': int(len(merged)), 'new': int(len(new)),
                                 'last': merged.index.max()}
                    break
            except Exception as e:
                out[prod] = {'error': str(e)}
        _save_index(index, live_dir)
    return {'skipped': None, 'products': out, **info}


# ── Night session (display only) ─────────────────────────────────────────────────────────────────────────────
NIGHT_START = '21:00:00'
# Night session end (Beijing, the morning after the start day) by product; products absent here have no night session.
NIGHT_END = {'AU': '02:30:00', 'AG': '02:30:00', 'AL': '01:00:00', 'CU': '01:00:00', 'JM': '23:00:00'}
NIGHT_INDEX = 'index_night.json'


def night_session(product, now):
    """(day, start, end, open_now) of the night session that is open, or else the last finished one, for a
    product with a night session (None otherwise). `day` is the evening it starts on (Beijing); Friday's
    session runs into Saturday morning, and there is none starting on a Saturday or Sunday evening."""
    end_t = NIGHT_END.get(product)
    if end_t is None:
        return None
    d = now.date() if now.strftime('%H:%M:%S') >= '20:55:00' else now.date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    start = datetime.combine(d, datetime.strptime(NIGHT_START, '%H:%M:%S').time())
    end = datetime.combine(d, datetime.strptime(end_t, '%H:%M:%S').time())
    if end <= start:
        end += timedelta(days=1)
    return d.strftime('%Y-%m-%d'), start, end, bool(start <= now < end)


def _night_index(live_dir):
    try:
        with open(os.path.join(str(_dir(live_dir)), NIGHT_INDEX), encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save_night_index(index, live_dir):
    d = str(_dir(live_dir))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, NIGHT_INDEX + '.tmp'), 'w', encoding='utf-8') as fh:
        json.dump(index, fh, indent=1, sort_keys=True)
    os.replace(os.path.join(d, NIGHT_INDEX + '.tmp'), os.path.join(d, NIGHT_INDEX))


NIGHT_HISTORY_DIR = 'night_history'


def _archive_night(contract, merged, live_dir):
    """Upsert a session's night bars into live/night_history/<contract>.parquet, which (unlike the per-session
    live file) keeps every night fetched from now on, one row per minute. Never raises: the archive must not
    break the display."""
    try:
        d = os.path.join(str(_dir(live_dir)), NIGHT_HISTORY_DIR)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f'{contract}.parquet')
        hist = pd.read_parquet(path) if os.path.exists(path) else None
        both = merged if hist is None or hist.empty else pd.concat([hist, merged])
        both = both[~both.index.duplicated(keep='last')].sort_index()
        both.to_parquet(path + '.tmp', compression='zstd')
        os.replace(path + '.tmp', path)
    except Exception:
        pass


def load_night(contract, live_dir=None):
    """(bars, meta) of a contract's night file, or (None, None)."""
    path = os.path.join(str(_dir(live_dir)), f'{contract}_night.parquet')
    meta = _night_index(live_dir).get(contract)
    if not meta or not os.path.exists(path):
        return None, None
    return pd.read_parquet(path), meta


def night_meta_for(product, live_dir=None):
    """Most recently fetched night entry of a product as (contract, meta), or (None, None)."""
    entries = [(c, m) for c, m in _night_index(live_dir).items() if m.get('product') == product]
    return max(entries, key=lambda e: e[1].get('fetched_at', ''), default=(None, None))


def _normalize_night(frame, start, end):
    """Wind wsi frame -> minute bars inside the night session [start, end]."""
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame()
    f = frame.copy()
    f.columns = [str(c).lower() for c in f.columns]
    f.index = pd.to_datetime(f.index, errors='coerce')
    f = f[f.index.notna()].sort_index()
    for c in ('open', 'high', 'low', 'close', 'volume'):
        f[c] = pd.to_numeric(f.get(c), errors='coerce')
    f = f.dropna(subset=['close'])
    f = f[(f['close'] > 0) & (f.index >= pd.Timestamp(start)) & (f.index <= pd.Timestamp(end))]
    f['volume'] = f['volume'].fillna(0.0)
    f['hs_bp'] = float('nan')
    return f[['open', 'high', 'low', 'close', 'volume', 'hs_bp']].astype({'hs_bp': 'float32'})


def fetch_night_bars(products, now=None, wsi=None, codes=None, live_dir=None, closed_only=False, wind_off=None,
                     on_demand=None):
    """Night-session minute bars of each product that has one (NIGHT_END), merged into <contract>_night files.

    Same rules as fetch_live_bars: while the session is open the bars are fetched incrementally (not when
    closed_only); once it is over the finished session is fetched once and marked complete. Products without a
    night session are left out of the result. Returns {'skipped', 'products', 'session', 'now'}."""
    now = now or china_now()
    on_demand = (not closed_only) if on_demand is None else bool(on_demand)
    products = [p for p in products if p in NIGHT_END]
    info = {'now': now}
    if not products:
        return {'skipped': None, 'products': {}, 'session': 'closed', **info}
    open_any = any(night_session(p, now)[3] for p in products)
    info['session'] = 'open' if open_any else 'closed'
    if open_any and closed_only:
        return {'skipped': 'night session open: press Start live for intraday updates', 'products': {}, **info}
    if not on_demand:
        if wind_off is None:
            from data.providers.retrieve import _wind_disabled as wind_off
        if wind_off():
            return {'skipped': 'Wind disabled', 'products': {}, **info}
    if wsi is None:
        from data.providers.retrieve import _wsi

        def wsi(*args):
            return _wsi(*args, on_demand=on_demand)
    out = {}
    with fetch_lock:
        try:
            code_of = main_contract_codes(codes)
        except Exception as e:
            return {'skipped': f'main contract lookup failed: {e}', 'products': {}, **info}
        index = _night_index(live_dir)
        for prod in products:
            code = code_of.get(prod)
            if not code:
                out[prod] = {'error': 'no main contract code on file'}
                continue
            contract = code.split('.')[0]
            try:
                day, start, end, open_now = night_session(prod, now)
                old, meta = load_night(contract, live_dir)
                same = old is not None and meta and meta.get('date') == day and not old.empty
                if same and meta.get('complete') and not open_now:
                    out[prod] = {'contract': contract, 'rows': int(len(old)), 'new': 0, 'last': old.index.max()}
                    continue
                if same:
                    s_ = (old.index.max() - timedelta(minutes=OVERLAP_MIN)).strftime('%Y-%m-%d %H:%M:%S')
                else:
                    old, s_ = None, start.strftime('%Y-%m-%d %H:%M:%S')
                e_ = min(now, end) if open_now else end + timedelta(minutes=1)
                new = _normalize_night(wsi(code, FIELDS, s_, e_.strftime('%Y-%m-%d %H:%M:%S')), start, end)
                if new.empty and old is None:
                    out[prod] = {'error': 'Wind returned no night bars (not connected, a holiday, or the session '
                                          'has not started)'}
                    continue
                merged = new if old is None else pd.concat([old, new])
                merged = merged[~merged.index.duplicated(keep='last')].sort_index()
                d = str(_dir(live_dir))
                os.makedirs(d, exist_ok=True)
                tmp = os.path.join(d, f'{contract}_night.parquet.tmp')
                merged.to_parquet(tmp, compression='zstd')
                os.replace(tmp, os.path.join(d, f'{contract}_night.parquet'))
                _archive_night(contract, merged, live_dir)
                index = {c: m for c, m in index.items() if not (m.get('product') == prod and c != contract)}
                index[contract] = {'product': prod, 'date': day, 'fetched_at': now.strftime('%Y-%m-%d %H:%M:%S'),
                                   'last': str(merged.index.max()), 'rows': int(len(merged)),
                                   'complete': bool(not open_now)}
                out[prod] = {'contract': contract, 'rows': int(len(merged)), 'new': int(len(new)),
                             'last': merged.index.max()}
            except Exception as e:
                out[prod] = {'error': str(e)}
        _save_night_index(index, live_dir)
    return {'skipped': None, 'products': out, **info}
