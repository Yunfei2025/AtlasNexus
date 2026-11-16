"""Compact 1-minute bar cache of the intraday contract files, kept next to the tick files in database/futures_desk.

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
SLICE_DIR = DIR_INPUT / 'futures_desk' / 'monitor_bars'   # small, append-only: lets a second computer run the Monitor
SLICE_WARMUP_DAYS = 15
BAR_DIR = DIR_DATA / 'futures_desk' / 'bars'   # time series grow daily: kept out of the input repo
CONTRACT_RE = re.compile(r'[A-Z]+\d{3,4}')
MIN_ROWS = 100   # fewer minute bars than this is an empty or aborted download


def slice_bars(contract):
    """A contract's bars from the monitor slice (its shards concatenated), or None."""
    d = os.path.join(str(SLICE_DIR), contract)
    if not os.path.isdir(d):
        return None
    parts = [pd.read_parquet(os.path.join(d, f)) for f in sorted(os.listdir(d)) if f.endswith('.parquet')]
    return pd.concat(parts).sort_index() if parts else None


def export_monitor_slice(approved, tick_dir=None, bar_dir=None, live_dir=None, slice_dir=None):
    """Write what the Monitor needs into SLICE_DIR so a computer without the full cache can show it.

    For each approved product, the newest three contracts' bars (night joined) from SLICE_WARMUP_DAYS trade days
    before its walk-forward's last day to now, one parquet shard per contract and trade date. A shard is written
    once (again only when its row count changes, e.g. night bars joined late), so the folder grows by a few KB
    per product per day instead of rewriting a big file; shards older than the window and contracts no longer
    in the newest three are deleted. Nothing happens without the full cache. Returns {'written', 'removed'}."""
    from .night import night_signature
    tick_dir, bar_dir = _dirs(tick_dir, bar_dir)
    slice_dir = str(slice_dir or SLICE_DIR)
    cache = _cache_index(bar_dir)
    sidx = _read_json(os.path.join(slice_dir, 'index.json'))
    out, new_idx = {'written': 0, 'removed': 0}, {}
    for prod, rec in (approved or {}).items():
        names = sorted((c for c in cache if _product(c) == prod and cache[c].get('rows', 0) > 0),
                       key=lambda c: cache[c].get('last') or '', reverse=True)[:3]
        for c in names:
            meta = sidx.get(c, {})
            sig = [cache[c].get('last'), cache[c].get('night_sig'), rec['wf_last_day']]
            if meta.get('src') == sig:
                new_idx[c] = meta
                continue
            path = os.path.join(str(bar_dir), f'{c}.parquet')
            if not os.path.exists(path):
                continue
            bars = pd.read_parquet(path)
            days = pd.DatetimeIndex(sorted(bars.index.normalize().unique()))
            first = max(days.searchsorted(pd.Timestamp(rec['wf_last_day'])) - SLICE_WARMUP_DAYS, 0)
            keep = days[first:]
            counts = bars.groupby(bars.index.normalize()).size()
            have = dict(meta.get('dates', {}))
            os.makedirs(os.path.join(slice_dir, c), exist_ok=True)
            for d in keep:
                key, n = str(d.date()), int(counts[d])
                if have.get(key) != n or not os.path.exists(os.path.join(slice_dir, c, f'{key}.parquet')):
                    tmp = os.path.join(slice_dir, c, f'{key}.parquet.tmp')
                    bars[bars.index.normalize() == d].to_parquet(tmp, compression='zstd', compression_level=19)
                    os.replace(tmp, os.path.join(slice_dir, c, f'{key}.parquet'))
                    have[key] = n
                    out['written'] += 1
            for key in [k for k in have if pd.Timestamp(k) < keep[0]]:
                try:
                    os.remove(os.path.join(slice_dir, c, f'{key}.parquet'))
                    out['removed'] += 1
                except OSError:
                    pass
                have.pop(key)
            new_idx[c] = {'dates': dict(sorted(have.items())), 'rows': int(sum(have.values())),
                          'first': str(keep[0].date()), 'last': cache[c].get('last'), 'src': sig}
    if os.path.isdir(slice_dir):
        for c in os.listdir(slice_dir):
            if os.path.isdir(os.path.join(slice_dir, c)) and c not in new_idx:
                for f in os.listdir(os.path.join(slice_dir, c)):
                    os.remove(os.path.join(slice_dir, c, f))
                    out['removed'] += 1
                os.rmdir(os.path.join(slice_dir, c))
    if new_idx != sidx or out['written'] or out['removed']:
        os.makedirs(slice_dir, exist_ok=True)
        tmp = os.path.join(slice_dir, 'index.json.tmp')
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(new_idx, fh, indent=1, sort_keys=True)
        os.replace(tmp, os.path.join(slice_dir, 'index.json'))
    return out


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


def _read_json(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return {}


def _uses_slice(bar_dir):
    """The monitor slice stands in for the full cache only at the default location."""
    return bar_dir is None or str(bar_dir) == str(BAR_DIR)


def _cache_index(bar_dir=None):
    """The full cache's own index.json (what _save_index writes back), without the slice's contracts."""
    return _read_json(os.path.join(str(bar_dir or BAR_DIR), 'index.json'))


def load_index(bar_dir=None):
    index = _read_json(os.path.join(str(bar_dir or BAR_DIR), 'index.json'))
    if _uses_slice(bar_dir):   # contracts only the slice has (a computer without the full cache)
        for c, m in _read_json(os.path.join(str(SLICE_DIR), 'index.json')).items():
            index.setdefault(c, {k: m[k] for k in ('rows', 'first', 'last')})
    return index


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


def _night_stale(contract, index, live_dir):
    """True when the contract's night history changed since its night bars were joined into the cached file."""
    from .night import night_signature
    meta = index.get(contract)
    return bool(meta) and meta.get('rows', 1) > 0 and meta.get('night_sig') != night_signature(contract, live_dir)


def _join_night(bars, contract, live_dir):
    """Day bars + the contract's archived night sessions on their trade dates (futures.backtest.night)."""
    from .night import load_night_history, with_night
    return with_night(bars, load_night_history(contract, live_dir))


def _write(contract, bars, bar_dir, index, src_meta, live_dir):
    """Write a contract's cached file (day + night bars) and record what it was built from."""
    from .night import night_signature
    os.makedirs(bar_dir, exist_ok=True)
    tmp = os.path.join(str(bar_dir), f'{contract}.parquet.tmp')
    bars.to_parquet(tmp, compression='zstd')
    os.replace(tmp, os.path.join(str(bar_dir), f'{contract}.parquet'))
    index[contract] = {**src_meta, 'rows': int(len(bars)), 'first': str(bars.index.min()),
                       'last': str(bars.index.max()), 'night_sig': night_signature(contract, live_dir)}


def _build(contract, tick_dir, bar_dir, index, live_dir=None):
    from .walkforward import load_ticks
    src = os.path.join(str(tick_dir), f'{contract}.pkl')
    st = os.stat(src)
    ticks = load_ticks(src)
    bars = ticks_to_minute_bars(ticks) if ticks is not None and len(ticks) else None
    if bars is None or len(bars) < MIN_ROWS:
        index[contract] = {'src_mtime': st.st_mtime, 'src_size': st.st_size, 'rows': 0}
        return None
    _write(contract, _join_night(bars, contract, live_dir), bar_dir, index,
           {'src_mtime': st.st_mtime, 'src_size': st.st_size}, live_dir)
    return bars


def list_contracts(product=None, tick_dir=None, bar_dir=None):
    """Contracts available from the tick files and/or the bar cache (skips empty downloads)."""
    tick_dir, bar_dir = _dirs(tick_dir, bar_dir)
    names = set()
    for d, ext in ((tick_dir, '.pkl'), (bar_dir, '.parquet')):
        if os.path.isdir(d):
            names |= {f[:-len(ext)] for f in os.listdir(d) if f.endswith(ext) and CONTRACT_RE.fullmatch(f[:-len(ext)])}
    index = load_index(bar_dir)
    if _uses_slice(bar_dir):
        names |= set(_read_json(os.path.join(str(SLICE_DIR), 'index.json')))
    names = {c for c in names if index.get(c, {}).get('rows', 1) > 0}
    if product:
        names = {c for c in names if _product(c) == product}
    return sorted(names)


def load_minute_bars(contract, tick_dir=None, bar_dir=None, night=False, live_dir=None):
    """Minute bars of one contract from the cache, which holds the day sessions with the archived night
    sessions joined on (futures.backtest.night). The file is rebuilt from the ticks when the tick file is newer
    than the cache, and the night bars are re-joined when the night history changed (also without tick files:
    the cached day bars are kept). night=False (the default) returns the day-session bars only, so the desk's
    approved strategies see exactly what they were tested on; night=True returns night + day.
    None when neither exists or it is empty."""
    from .night import strip_night
    tick_dir, bar_dir = _dirs(tick_dir, bar_dir)
    index = _cache_index(bar_dir)
    path = os.path.join(str(bar_dir), f'{contract}.parquet')
    if _stale(contract, index, tick_dir):
        bars = _build(contract, tick_dir, bar_dir, index, live_dir)
        _save_index(index, bar_dir)
    else:
        bars = pd.read_parquet(path) if os.path.exists(path) else (slice_bars(contract) if _uses_slice(bar_dir) else None)
        if bars is not None and os.path.exists(path) and _night_stale(contract, index, live_dir):
            bars = _join_night(strip_night(bars), contract, live_dir)
            meta = index[contract]
            _write(contract, bars, bar_dir, index, {k: meta[k] for k in ('src_mtime', 'src_size') if k in meta}, live_dir)
            _save_index(index, bar_dir)
    if bars is None:
        return None
    return bars if night else strip_night(bars)


def last_bar_time(product, bar_dir=None):
    """Latest cached minute-bar time for a product (from the index; no file reads)."""
    last = [m['last'] for c, m in load_index(bar_dir).items() if _product(c) == product and m.get('last')]
    return pd.Timestamp(max(last)) if last else None


def sync(products=None, tick_dir=None, bar_dir=None, progress=None):
    """Bring the cache up to date with every tick file (optionally only `products`). Returns the contracts
    rebuilt."""
    tick_dir, bar_dir = _dirs(tick_dir, bar_dir)
    index = _cache_index(bar_dir)
    done = []
    for f in sorted(os.listdir(tick_dir)) if os.path.isdir(tick_dir) else []:
        c = f[:-4]
        if not f.endswith('.pkl') or not CONTRACT_RE.fullmatch(c) or (products and _product(c) not in products):
            continue
        if _stale(c, index, tick_dir) or _night_stale(c, index, None):
            load_minute_bars(c, tick_dir, bar_dir)   # rebuilds from the ticks and/or re-joins the night bars
            index = _cache_index(bar_dir)
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
