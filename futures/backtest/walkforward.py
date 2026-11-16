"""Multi-contract intraday strategy evaluation for one futures product.

Every (strategy, bar size) candidate runs at default parameters on each contract's own main-contract
days, flat at every close, net of costs. Each row also carries an 'overnight' block: the same candidate, costs and
exits with the position held through the close (an information-only comparison; the desk trades flat).
run_daily() adds daily-bar candidates (held overnight) for comparison. The result is the evidence the Futures Desk uses to approve a
strategy: Sharpe per contract and pooled, its standard error, win rate, payoff and expectancy.
No parameters are tuned (see the alpha no-param-tuning finding): a candidate either holds up across
contracts or it does not.
"""

import json
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from settings.paths import DIR_INPUT

from .costs import DEFAULT_FEE_BP, FEE_BP, apply_costs, normalize_exits, product_of, trade_stats
from .data_loader import load_raw_file
from . import minute_bars
from . import night as night_mod
from .live_bars import NIGHT_END
from .minute_bars import MIN_ROWS, list_contracts, load_index, load_minute_bars, resample_minute_bars
from .strategies import (
    run_atr_band_strategy, run_bollinger_strategy, run_demark_strategy, run_intraday_momentum_strategy,
    run_ma_strategy, run_sar_strategy, run_vwap_strategy,
)

# Default strategy parameters, keyed by the Research panel's input ids (also the panel's initial values).
DEFAULT_PARAMS = {
    'bf-ma-short': 5, 'bf-ma-long': 20, 'bf-boll-window': 20, 'bf-boll-std': 1.0, 'bf-boll-exit': [],
    'bf-vwap-window': 20, 'bf-mom-window': 14, 'bf-atr-ema-window': 11, 'bf-atr-window': 14,
    'bf-sar-af': 0.02, 'bf-sar-max-af': 0.2,
}
_P = DEFAULT_PARAMS
STRATEGIES = {
    'MA': lambda d: run_ma_strategy(d, _P['bf-ma-short'], _P['bf-ma-long']),
    'Boll': lambda d: run_bollinger_strategy(d, _P['bf-boll-window'], _P['bf-boll-std']),
    'VWAP': lambda d: run_vwap_strategy(d, _P['bf-vwap-window']),
    'Mom': lambda d: run_intraday_momentum_strategy(d, _P['bf-mom-window'], _P['bf-vwap-window']),
    'ATR': lambda d: run_atr_band_strategy(d, _P['bf-atr-ema-window'], _P['bf-atr-window']),
    'SAR': lambda d: run_sar_strategy(d, _P['bf-sar-af'], _P['bf-sar-max-af']),
    'DeMark': lambda d: run_demark_strategy(d),
}
# Strategies whose signal is a number of units, not just a side: ATR stacks three layers (1 + 2 + 3), so its
# position is -6..+6 units. A sized position is the maximum, one unit = 1 / max of it.
MAX_UNITS = {'ATR': 6.0}


def max_units(strategy):
    return MAX_UNITS.get(str(strategy).split('@')[0], 1.0)


# Walk-forward strategy name -> the Research strategy selector's value
PANEL_STRATEGY = {'Mom': 'Momentum'}
TIMEFRAMES = ['15min', '30min', '1h']
# Daily-bar candidates run on the long continuous daily series, held overnight. VWAP and Momentum reset every
# day, so they have no daily version.
DAILY_STRATEGIES = ['MA', 'Boll', 'ATR', 'SAR', 'DeMark']
DAILY_FILE = DIR_INPUT / 'futures-dailyK_con.pkl'
MIN_DAILY_TRADES = 30
# Approval gates (shown in the UI next to the table)
MIN_CONTRACT_DAYS = 15   # a contract with fewer main-contract days is too short to judge
MIN_TRADES = 30
MIN_NIGHT_DAYS = 60      # a night+day run needs at least this many trade days with a night session to pass
# Stop / target levels tried per candidate when searching exits (% of the entry price; None = off)
EXIT_STOPS = [None, 0.3, 0.5, 1.0]
EXIT_TARGETS = [None, 0.5, 1.0]
EXIT_GRID = [normalize_exits(st, tg, 'pct') for st in EXIT_STOPS for tg in EXIT_TARGETS]   # first = no exits
ANN = math.sqrt(252)


def load_ticks(path):
    """One contract's ticks as a frame with last/ask/bid and per-tick volume `vol`."""
    frames = []
    for _, df in sorted((load_raw_file(path) or {}).items(), key=lambda kv: str(kv[0])):
        if df is None or len(df) == 0:
            continue
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]
        if 'last' not in df.columns:
            continue
        df.index = pd.to_datetime(df.index, errors='coerce')
        df = df[df.index.notna()].sort_index()
        for c in ('last', 'ask', 'bid', 'volume'):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce')
        df['vol'] = df['volume'].diff().clip(lower=0).fillna(0) if 'volume' in df.columns else 0.0
        frames.append(df)
    if not frames:
        return None
    df = pd.concat(frames)
    df = df[~df.index.duplicated(keep='last')].dropna(subset=['last'])
    return df[df['last'] > 0]


resample_bars = resample_minute_bars  # minute bars -> 15min / 30min / 1h, identical to resampling the ticks


def product_minute_bars(product, latest=None, tick_dir=None, bar_dir=None, night=False, live_dir=None):
    """{contract: minute bars} for a product from the tick files or the bar cache. latest=N keeps only the
    N contracts with the most recent data. night=True returns night + day bars (the cached files hold both,
    see minute_bars.load_minute_bars); the default is the day session only."""
    names = list_contracts(product, tick_dir, bar_dir)
    if latest:
        idx = load_index(bar_dir)
        tick_dir_ = tick_dir or minute_bars.TICK_DIR
        recency = lambda c: (idx.get(c, {}).get('last') or '',
                             os.path.getmtime(os.path.join(str(tick_dir_), f'{c}.pkl'))
                             if os.path.exists(os.path.join(str(tick_dir_), f'{c}.pkl')) else 0)
        names = sorted(names, key=recency, reverse=True)[:latest]
    out = {}
    for c in names:
        b = load_minute_bars(c, tick_dir, bar_dir, night=bool(night and product in NIGHT_END), live_dir=live_dir)
        if b is not None and len(b) >= MIN_ROWS:
            out[c] = b
    return out


def daily_pnl_of(res):
    sr = res['strategy_returns']
    return sr.groupby(sr.index.normalize()).sum()


def _sharpe(x):
    x = pd.Series(x).dropna()
    return float(x.mean() / x.std() * ANN) if len(x) > 4 and x.std() > 0 else float('nan')


def _sharpe_se(x):
    """Annualised standard error of a Sharpe estimated from len(x) daily observations."""
    n = len(pd.Series(x).dropna())
    s = _sharpe(x)
    return float(ANN * math.sqrt((1 + 0.5 * (s / ANN) ** 2) / n)) if n > 4 and not math.isnan(s) else float('nan')


def load_daily_df(product, path=None):
    """The product's continuous daily bars (open / high / low / close / volume), or None when the series is
    missing. The series is the main contract's own prices, rolls not adjusted."""
    try:
        raw = load_raw_file(str(path or DAILY_FILE)) or {}
    except Exception:
        return None
    key = next((k for k in raw if product_of(k) == product), None)
    if key is None:
        return None
    df = raw[key].copy()
    df.columns = [str(c).lower() for c in df.columns]
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    for c in ('open', 'high', 'low', 'close', 'volume'):
        df[c] = pd.to_numeric(df.get(c), errors='coerce')
    df = df.dropna(subset=['close'])
    return df[df['close'] > 0]


def daily_pnl(product, strategy, cost_bp, exits=None, path=None):
    """Daily net P&L (return on notional) of one daily-bar strategy on the continuous series, held overnight."""
    df = load_daily_df(product, path)
    if df is None:
        raise ValueError(f"no daily series for {product}")
    return daily_pnl_of(apply_costs(STRATEGIES[strategy](df), cost_bp, flat_at_close=False, exits=exits))


def run_daily(product, cost_bp, recent_from=None, exits=None, path=None):
    """Daily-bar candidates for `product` on its continuous daily series (held overnight, net of cost_bp per
    side). Each row has the full-history Sharpe and the Sharpe since `recent_from` (the intraday run's first
    day), so the two can be compared over the same dates. None when the series is missing.
    Roll gaps of the continuous series are not adjusted."""
    df = load_daily_df(product, path)
    if df is None:
        return None
    rows = {}
    for sname in DAILY_STRATEGIES:
        try:
            res = apply_costs(STRATEGIES[sname](df), cost_bp, flat_at_close=False, exits=exits)
        except Exception:
            continue
        pnl = daily_pnl_of(res)
        recent = pnl[pnl.index >= pd.Timestamp(recent_from)] if recent_from is not None else pnl
        yearly = pnl.groupby(pnl.index.year).agg(['sum', 'size'])
        yearly = yearly[yearly['size'] >= 100]
        st = trade_stats(res, cost_bp)
        rows[f'{sname}@1D'] = {
            'pooled': _sharpe(pnl), 'se': _sharpe_se(pnl), 'days': int(len(pnl)),
            'recent': _sharpe(recent), 'recent_se': _sharpe_se(recent), 'recent_days': int(len(recent)),
            'trades': st['trades'], 'win': st['win'], 'payoff': st['payoff'], 'expectancy_bp': st['expectancy_bp'],
            'years_positive': int((yearly['sum'] > 0).sum()), 'years': int(len(yearly)),
            'total_return': float(pnl.sum()),
        }
    return {'start': str(df.index.min().date()), 'end': str(df.index.max().date()), 'exits': exits,
            'min_trades': MIN_DAILY_TRADES, 'rows': rows}


def run_walkforward(product, cost_bp=None, tick_dir=None, bar_dir=None, progress=None, exits=None,
                    search_exits=False, night=False, live_dir=None):
    """Evaluate all candidates for `product` across every contract (tick files or the minute-bar cache).
    exits: one stop loss / profit target applied to every candidate (costs.normalize_exits).
    search_exits: instead, try EXIT_GRID (incl. no exits) per candidate and keep the best pooled Sharpe;
    each row then carries its chosen 'exits' and its no-exit Sharpe 'base_pooled'.
    night: run on night + day sessions (night bars joined to their trade date, flat at the 15:00 close). The
    result is marked session='night+day', counts the trade days that really had a night session, and each row
    carries 'night_cmp': this candidate's P&L on those days with and without the night session. A candidate
    cannot pass with fewer than MIN_NIGHT_DAYS such days: the other days are plain day sessions and would
    vouch for a night strategy that was barely tested."""
    if night and product not in NIGHT_END:
        raise ValueError(f"{product} has no night session")
    contract = product_minute_bars(product, tick_dir=tick_dir, bar_dir=bar_dir, night=night, live_dir=live_dir)
    if not contract:
        raise ValueError(f"no intraday data for {product} (no tick files and no cached minute bars)")
    if progress:
        progress(f"loaded {len(contract)} contracts")

    # Main contract of each day = the one with the highest traded volume
    dvol = pd.DataFrame({c: b['volume'].groupby(b.index.normalize()).sum() for c, b in contract.items()})
    main_of = dvol.idxmax(axis=1)

    # Measured half-spread: median over the main-contract minutes of each minute's median quote
    hs = pd.concat([b.loc[b.index.normalize().isin(main_of.index[main_of == c]), 'hs_bp']
                    for c, b in contract.items()]).dropna()
    half_spread = float(hs.median()) if len(hs) else 1.0
    fee = FEE_BP.get(product, DEFAULT_FEE_BP)
    cost = half_spread + fee if cost_bp is None else float(cost_bp)

    spans = {c: main_of.index[main_of == c] for c in contract}
    night_days = pd.DatetimeIndex([])
    if night:
        night_days = pd.DatetimeIndex(sorted({d for c, b in contract.items()
                                             for d in night_mod.night_trade_days(b).intersection(spans[c])}))
        base = run_walkforward(product, cost_bp, tick_dir, bar_dir, None, exits, search_exits)
        if progress:
            progress(f"{len(night_days)} trade days with a night session; day-only baseline done")

    def score(raw, ex, flat=True):
        """Row + daily P&L of one candidate (raw strategy output per contract) under exits `ex`. flat=False
        holds the position through each close (the gap to the next open is then in the P&L)."""
        parts, stats = {}, []
        for c, r in raw.items():
            days = spans[c]
            res = apply_costs(r, cost, flat_at_close=flat, exits=ex)
            parts[c] = daily_pnl_of(res).reindex(days).fillna(0.0)
            stats.append(trade_stats(res[res.index.normalize().isin(days)], cost))
        series = pd.concat(parts.values()).sort_index()
        n_tr = sum(st['trades'] for st in stats)
        wsum = n_tr or 1
        per_c = {c: _sharpe(p) for c, p in parts.items() if len(p) >= MIN_CONTRACT_DAYS}
        pos = sum(1 for v in per_c.values() if v > 0)
        pooled = _sharpe(series)
        row = {
            'pooled': pooled, 'se': _sharpe_se(series), 'per_contract': per_c, 'exits': ex,
            'trades': n_tr, 'trades_per_day': n_tr / max(len(series), 1),
            'win': sum(st['win'] * st['trades'] for st in stats if not math.isnan(st['win'])) / wsum,
            'payoff': float(np.nanmean([st['payoff'] for st in stats])) if stats else float('nan'),
            'expectancy_bp': sum(st['expectancy_bp'] * st['trades'] for st in stats
                                 if not math.isnan(st['expectancy_bp'])) / wsum,
            'total_return': float(series.sum()),
            'max_dd': float((series.cumsum().cummax() - series.cumsum()).max()), 'worst_day': float(series.min()),
            'passes': bool(pooled > 0 and n_tr >= MIN_TRADES and len(per_c) >= 2
                           and pos >= max(2, math.ceil(len(per_c) * 2 / 3))
                           and (not night or len(night_days) >= MIN_NIGHT_DAYS)),
        }
        row['passes_ex_night'] = bool(pooled > 0 and n_tr >= MIN_TRADES and len(per_c) >= 2
                                      and pos >= max(2, math.ceil(len(per_c) * 2 / 3)))
        return row, series

    grid = EXIT_GRID if search_exits else [exits]
    pnl, rows = {}, {}
    for tf in TIMEFRAMES:
        bars = {c: resample_bars(b, tf) for c, b in contract.items()}
        for sname, fn in STRATEGIES.items():
            cand = f'{sname}@{tf}'
            raw = {}
            for c, b in bars.items():
                if len(b) < 50 or len(spans[c]) == 0:
                    continue
                try:
                    raw[c] = fn(b)   # the strategy's signals do not depend on the exits: compute once
                except Exception:
                    continue
            if not raw:
                continue
            scored = [score(raw, ex) for ex in grid]
            best = max(range(len(scored)), key=lambda k: (-math.inf if math.isnan(scored[k][0]['pooled'])
                                                          else scored[k][0]['pooled']))
            rows[cand], pnl[cand] = scored[best]
            ov, _ = score(raw, rows[cand]['exits'], flat=False)   # same exits, held overnight
            rows[cand]['overnight'] = {k: ov[k] for k in ('pooled', 'se', 'per_contract', 'total_return', 'max_dd',
                                                          'worst_day', 'trades', 'trades_per_day')}
            if night:
                with_n = pnl[cand].reindex(night_days).dropna()
                day_only = pd.Series((base['daily_pnl'].get(cand) or {}), dtype=float)
                day_only.index = pd.to_datetime(day_only.index)
                day_only = day_only.reindex(with_n.index).dropna()
                rows[cand]['night_cmp'] = {'days': int(len(with_n)), 'with_night': float(with_n.sum()),
                                           'day_only': float(day_only.sum()),
                                           'day_pooled': (base['rows'].get(cand) or {}).get('pooled')}
            if search_exits:   # the no-exit result, to show how much the search added
                rows[cand]['base_pooled'] = scored[0][0]['pooled']
        if progress:
            progress(f"finished {tf}")

    return {
        'product': product, 'run_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'cost_bp': cost, 'half_spread_bp': half_spread, 'fee_bp': fee,
        'exits': 'search' if search_exits else exits, 'exit_grid': EXIT_GRID if search_exits else None,
        'days': int(len(main_of)), 'last_day': str(main_of.index.max().date()),
        'contracts': {c: {'days': int(len(spans[c])),
                          'start': str(spans[c].min().date()) if len(spans[c]) else None,
                          'end': str(spans[c].max().date()) if len(spans[c]) else None}
                      for c in contract},
        'gates': {'min_contract_days': MIN_CONTRACT_DAYS, 'min_trades': MIN_TRADES, 'min_night_days': MIN_NIGHT_DAYS},
        'session': 'night+day' if night else 'day', 'night_days': int(len(night_days)),
        'rows': rows,
        'daily': run_daily(product, cost, main_of.index.min(), exits if isinstance(exits, dict) else None),
        'daily_pnl': {k: {str(d.date()): float(v) for d, v in s.items()} for k, s in pnl.items()},
    }


def _wf_name(product, night=False):
    return f'wf_{product}_night.json' if night else f'wf_{product}.json'


def save_walkforward(result, out_dir):
    """Persist a run so the tab can show the last result without recomputing. A night+day run goes to its own
    file: wf_<product>.json stays the day-session evidence the approvals and the Monitor read."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(str(out_dir), _wf_name(result['product'], result.get('session') == 'night+day'))
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(result, fh, ensure_ascii=False, allow_nan=True)
    os.replace(tmp, path)
    return path


def load_walkforward(product, out_dir, night=False):
    try:
        with open(os.path.join(str(out_dir), _wf_name(product, night)), encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return None
