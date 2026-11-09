"""Live 1-minute bars for the Futures Desk Monitor, fetched from Wind only for the products asked for.

One small `wsi` call per product and refresh: only the minutes after the last stored bar are requested, and the
result is merged into input/futures_desk/live/<contract>.parquet (today's bars only, replaced each day). Outside
trading hours, or with FI_DISABLE_WIND set, nothing is requested. The desk reads these files as an overlay on
top of the settled minute-bar cache; they never enter the cache, the walk-forward or the Monitor's forward
statuses.

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
                    closed_only=False, wind_off=None):
    """Fetch the day's minute bars of each product's main contract and merge them into the live files.

    Market open: today's bars, incrementally. Market closed: the last session once, then nothing (the file is
    marked complete). closed_only=True never fetches while the market is open (the Monitor shows the finished
    day without Start). Returns {'skipped': reason or None, 'products': {product: {'contract', 'rows', 'new',
    'last'} or {'error'}}}. `wsi`, `codes`, `is_trading` and `wind_off` can be injected (tests)."""
    now = now or datetime.now()
    if is_trading is None:
        from data.providers.retrieve import _is_trading_hours as is_trading
    t = now.strftime('%H:%M:%S')
    past_close = now.weekday() >= 5 or t >= CLOSE_TIME or t < SESSION_START
    open_now = bool(is_trading(now)) and not past_close
    if open_now and closed_only:
        return {'skipped': 'market open: press Start live for intraday updates', 'products': {}}
    if not open_now:
        if wind_off is None:
            from data.providers.retrieve import _wind_disabled as wind_off
        if wind_off():
            return {'skipped': 'Wind disabled', 'products': {}}
    if wsi is None:
        from data.providers.retrieve import _wsi as wsi
    out = {}
    today = now.strftime('%Y-%m-%d')
    with fetch_lock:
        try:
            code_of = main_contract_codes(codes)
        except Exception as e:
            return {'skipped': f'main contract lookup failed: {e}', 'products': {}}
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
    return {'skipped': None, 'products': out}
