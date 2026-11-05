"""Compact 1-minute bar cache of the intraday contract files, kept in the shared input folder.

The tick files in DIR_DATA/futures are large (~1.8 GB) and live on one computer. Everything the Futures
Desk computes (walk-forward, today's signal, monitor replay) needs only 1-minute OHLCV bars plus the
quoted half-spread, which are ~0.2 MB per contract. Bars resampled from these minute bars to 15min / 30min
/ 1h are identical to bars resampled from the ticks.

    python -m futures.backtest.minute_bars          # sync every contract (run before switching computer)
    python -m futures.backtest.minute_bars AU TL    # only these products
"""

import json
import os
import re
import sys

import pandas as pd

from settings.paths import DIR_DATA, DIR_INPUT

TICK_DIR = DIR_DATA / 'futures'
BAR_DIR = DIR_INPUT / 'futures_desk' / 'bars'
CONTRACT_RE = re.compile(r'[A-Z]+\d{3,4}')
MIN_ROWS = 100   # fewer minute bars than this is an empty or aborted download


def _dirs(tick_dir, bar_dir):
    return (tick_dir or TICK_DIR), (bar_dir or BAR_DIR)


def _product(contract):
    return re.match(r'[A-Z]+', contract).group()


def ticks_to_minute_bars(ticks):
    """Ticks (last / ask / bid / per-tick `vol`, see walkforward.load_ticks) -> 1-minute bars with
    open / high / low / close / volume and hs_bp, the median quoted half-spread in bp of mid."""
    b = ticks['last'].resample('1min').ohlc()
    b['volume'] = ticks['vol'].resample('1min').sum()
    if {'ask', 'bid'} <= set(ticks.columns):
        q = ticks[(ticks['ask'] > ticks['bid']) & (ticks['bid'] > 0)]
        b['hs_bp'] = ((q['ask'] - q['bid']) / (q['ask'] + q['bid']) * 1e4).resample('1min').median()
    else:
        b['hs_bp'] = float('nan')
    b = b.dropna(subset=['close'])
    return b.astype({'volume': 'float64', 'hs_bp': 'float32'})


def resample_minute_bars(bars, rule):
    """Aggregate minute bars to `rule` ('15min', '1h', or the tab's '15T' / '1H' spellings)."""
    rule = re.sub(r'(?<=\d)T\b', 'min', rule)
    rule = re.sub(r'(?<=\d)H\b', 'h', rule)
    if rule in ('1min', '1T'):
        return bars[['open', 'high', 'low', 'close', 'volume']].copy()
    out = bars.resample(rule).agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last',
                                   'volume': 'sum'})
    return out.dropna(subset=['close'])


def load_index(bar_dir=None):
    try:
        with open(os.path.join(str(bar_dir or BAR_DIR), 'index.json'), encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save_index(index, bar_dir):
    os.makedirs(bar_dir, exist_ok=True)
    path = os.path.join(str(bar_dir), 'index.json')
    with open(path + '.tmp', 'w', encoding='utf-8') as fh:
        json.dump(index, fh, indent=1, sort_keys=True)
    os.replace(path + '.tmp', path)


def _stale(contract, index, tick_dir):
    """True when the tick file exists and is newer (or differently sized) than what the cache was built from."""
    src = os.path.join(str(tick_dir), f'{contract}.pkl')
    if not os.path.exists(src):
        return False
    meta = index.get(contract)
    st = os.stat(src)
    return meta is None or meta.get('src_mtime') != st.st_mtime or meta.get('src_size') != st.st_size


def _build(contract, tick_dir, bar_dir, index):
    from .walkforward import load_ticks
    src = os.path.join(str(tick_dir), f'{contract}.pkl')
    st = os.stat(src)
    ticks = load_ticks(src)
    bars = ticks_to_minute_bars(ticks) if ticks is not None and len(ticks) else None
    if bars is None or len(bars) < MIN_ROWS:
        index[contract] = {'src_mtime': st.st_mtime, 'src_size': st.st_size, 'rows': 0}
        return None
    os.makedirs(bar_dir, exist_ok=True)
    tmp = os.path.join(str(bar_dir), f'{contract}.parquet.tmp')
    bars.to_parquet(tmp, compression='zstd')
    os.replace(tmp, os.path.join(str(bar_dir), f'{contract}.parquet'))
    index[contract] = {'src_mtime': st.st_mtime, 'src_size': st.st_size, 'rows': int(len(bars)),
                       'first': str(bars.index.min()), 'last': str(bars.index.max())}
    return bars


def list_contracts(product=None, tick_dir=None, bar_dir=None):
    """Contracts available from the tick files and/or the bar cache (skips empty downloads)."""
    tick_dir, bar_dir = _dirs(tick_dir, bar_dir)
    names = set()
    for d, ext in ((tick_dir, '.pkl'), (bar_dir, '.parquet')):
        if os.path.isdir(d):
            names |= {f[:-len(ext)] for f in os.listdir(d) if f.endswith(ext) and CONTRACT_RE.fullmatch(f[:-len(ext)])}
    index = load_index(bar_dir)
    names = {c for c in names if index.get(c, {}).get('rows', 1) > 0}
    if product:
        names = {c for c in names if _product(c) == product}
    return sorted(names)


def load_minute_bars(contract, tick_dir=None, bar_dir=None):
    """Minute bars of one contract: rebuilt from ticks (and written to the cache) when the tick file is
    newer than the cache, otherwise read from the cache. None when neither exists or it is empty."""
    tick_dir, bar_dir = _dirs(tick_dir, bar_dir)
    index = load_index(bar_dir)
    if _stale(contract, index, tick_dir):
        bars = _build(contract, tick_dir, bar_dir, index)
        _save_index(index, bar_dir)
        return bars
    path = os.path.join(str(bar_dir), f'{contract}.parquet')
    return pd.read_parquet(path) if os.path.exists(path) else None


def last_bar_time(product, bar_dir=None):
    """Latest cached minute-bar time for a product (from the index; no file reads)."""
    last = [m['last'] for c, m in load_index(bar_dir).items() if _product(c) == product and m.get('last')]
    return pd.Timestamp(max(last)) if last else None


def sync(products=None, tick_dir=None, bar_dir=None, progress=None):
    """Bring the cache up to date with every tick file (optionally only `products`). Returns the contracts
    rebuilt."""
    tick_dir, bar_dir = _dirs(tick_dir, bar_dir)
    index = load_index(bar_dir)
    done = []
    for f in sorted(os.listdir(tick_dir)) if os.path.isdir(tick_dir) else []:
        c = f[:-4]
        if not f.endswith('.pkl') or not CONTRACT_RE.fullmatch(c) or (products and _product(c) not in products):
            continue
        if _stale(c, index, tick_dir):
            _build(c, tick_dir, bar_dir, index)
            _save_index(index, bar_dir)
            done.append(c)
            if progress:
                progress(c)
    return done


def cache_size_mb(bar_dir=None):
    d = str(bar_dir or BAR_DIR)
    return sum(os.path.getsize(os.path.join(d, f)) for f in os.listdir(d)) / 1e6 if os.path.isdir(d) else 0.0


if __name__ == '__main__':
    built = sync(set(sys.argv[1:]) or None, progress=lambda c: print('cached', c, flush=True))
    print(f"{len(built)} contracts rebuilt; cache {cache_size_mb():.1f} MB in {BAR_DIR}")
