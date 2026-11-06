"""Live 1-minute bars for the Futures Desk Monitor, fetched from Wind only for the products asked for.

One small `wsi` call per product and refresh: only the minutes after the last stored bar are requested, and the
result is merged into input/futures_desk/live/<contract>.parquet (today's bars only, replaced each day). Outside
trading hours, or with FI_DISABLE_WIND set, nothing is requested. The desk reads these files as an overlay on
top of the settled minute-bar cache; they never enter the cache, the walk-forward or the Monitor's forward
statuses.
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
FIELDS = "open,high,low,close,volume"
OVERLAP_MIN = 2   # re-request the last minutes: the newest bar is still forming when it was fetched
fetch_lock = threading.Lock()


def _dir(live_dir):
    return live_dir or LIVE_DIR


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
    """Settled minute bars plus today's live bars, only when the settled bars do not cover that day yet
    (once the end-of-day sync includes today, the live file is ignored)."""
    if live is None or live.empty:
        return bars
    if bars is None or bars.empty:
        return live
    if live.index.min().normalize() <= bars.index.max().normalize():
        return bars
    return pd.concat([bars, live[bars.columns]]).sort_index()


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


def fetch_live_bars(products, now=None, wsi=None, codes=None, is_trading=None, live_dir=None):
    """Fetch today's minute bars of each product's main contract and merge them into the live files.

    Returns {'skipped': reason or None, 'products': {product: {'contract', 'rows', 'new', 'last'} or
    {'error'}}}. `wsi`, `codes` and `is_trading` can be injected (tests)."""
    now = now or datetime.now()
    if is_trading is None:
        from data.providers.retrieve import _is_trading_hours as is_trading
    if not is_trading(now):
        return {'skipped': 'outside trading hours (or Wind disabled)', 'products': {}}
    if wsi is None:
        from data.providers.retrieve import _wsi as wsi
    out = {}
    day = now.strftime('%Y-%m-%d')
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
                old, meta = load_live(contract, live_dir)
                if old is not None and meta and meta.get('date') == day and not old.empty:
                    start = (old.index.max() - timedelta(minutes=OVERLAP_MIN)).strftime('%Y-%m-%d %H:%M:%S')
                else:
                    old, start = None, f'{day} {SESSION_START}'
                new = _normalize(wsi(code, FIELDS, start, now.strftime('%Y-%m-%d %H:%M:%S')), day)
                if new.empty and old is None:
                    out[prod] = {'error': 'Wind returned no bars (not connected, or the session has not started)'}
                    continue
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
                                   'last': str(merged.index.max()), 'rows': int(len(merged))}
                out[prod] = {'contract': contract, 'rows': int(len(merged)), 'new': int(len(new)),
                             'last': merged.index.max()}
            except Exception as e:
                out[prod] = {'error': str(e)}
        _save_index(index, live_dir)
    return {'skipped': None, 'products': out}
