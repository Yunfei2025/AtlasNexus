# -*- coding: utf-8 -*-
"""Futures Desk approvals: one approved intraday strategy per product, with the evidence it passed on."""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from settings.paths import DIR_INPUT

DESK_DIR = DIR_INPUT / 'futures_desk'   # wf_<PRODUCT>.json (walk-forward runs) and approved.json
APPROVED_PATH = DESK_DIR / 'approved.json'
DAILY_PATH = DESK_DIR / 'approved_daily.json'   # one approved daily-bar strategy per product, held overnight
PORTFOLIO_PATH = DESK_DIR / 'portfolio.json'   # the products traded: a list, in the order they were added


def load_portfolio(path=None):
    """Products in the portfolio, in order, or None when no portfolio has been saved yet (the desk then trades
    every approved, non-halted product, as it did before the portfolio existed)."""
    try:
        data = json.loads((path or PORTFOLIO_PATH).read_text(encoding='utf-8'))
        return list(data['products'])
    except Exception:
        return None


def save_portfolio(products, path=None):
    path = path or PORTFOLIO_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps({'products': list(products), 'saved_at': datetime.now().strftime('%Y-%m-%d %H:%M')},
                              indent=2), encoding='utf-8')
    tmp.replace(path)


def load_approved(path=None):
    path = path or APPROVED_PATH
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _read(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def load_approved_daily(path=None):
    return _read(path or DAILY_PATH)


def _save(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


def daily_gate(dd, candidate):
    """(passes, reason) of a daily candidate: its own full-history Sharpe must be positive on at least the minimum
    number of trades. The years-positive count is shown, not gated: daily series are short."""
    row = ((dd or {}).get('rows') or {}).get(candidate)
    if row is None:
        return False, f"{candidate} is not in the daily result"
    if row['trades'] < dd.get('min_trades', 30):
        return False, f"{candidate} has {row['trades']} trades, {dd.get('min_trades', 30)} are needed"
    if not row['pooled'] > 0:
        return False, f"{candidate} has a full-history Sharpe of {row['pooled']:+.2f}"
    return True, ''


def approve_daily(product, candidate, wf, path=None):
    """Record a daily-bar candidate (e.g. 'ATR@1D') as the product's daily strategy, next to its intraday one.
    The daily series' own evidence is stored (full-history Sharpe, years positive); the daily P&L is recomputed
    for the mean, std and longest losing run the Monitor needs."""
    from futures.backtest.walkforward import daily_pnl, max_units
    dd = wf.get('daily')
    ok, why = daily_gate(dd, candidate)
    if not ok:
        raise ValueError(why)
    row = dd['rows'][candidate]
    strategy, timeframe = candidate.split('@')
    units = max_units(strategy)
    pnl = daily_pnl(product, strategy, wf['cost_bp'], dd.get('exits')) / units   # return on the full position
    path = path or DAILY_PATH
    data = _read(path)
    data[product] = {
        'strategy': strategy, 'timeframe': timeframe, 'candidate': candidate, 'session': 'daily',
        'approved_at': datetime.now().strftime('%Y-%m-%d %H:%M'), 'cost_bp': wf['cost_bp'], 'exits': dd.get('exits'),
        'wf_run_at': wf['run_at'], 'wf_last_day': dd['end'], 'series_start': dd['start'],
        'pooled_sharpe': row['pooled'], 'sharpe_se': row['se'], 'recent_sharpe': row['recent'], 'days': row['days'],
        'years_positive': row['years_positive'], 'years': row['years'], 'trades': row['trades'], 'win': row['win'],
        'payoff': row['payoff'], 'expectancy_bp': row['expectancy_bp'], 'status': 'approved',
        'daily_mean': float(pnl.mean()) if len(pnl) else None, 'daily_std': float(pnl.std()) if len(pnl) > 1 else None,
        'max_streak': _longest_losing_run(pnl), 'max_units': units,
    }
    _save(data, path)
    return data[product]


def remove_daily(product, path=None):
    path = path or DAILY_PATH
    data = _read(path)
    if product not in data:
        raise ValueError(f"{product} has no approved daily strategy")
    rec = data.pop(product)
    _save(data, path)
    return rec


def set_status_daily(product, status, reason, path=None):
    path = path or DAILY_PATH
    data = _read(path)
    if product not in data:
        raise ValueError(f"{product} has no approved daily strategy")
    data[product].update(status=status, status_reason=reason, status_at=datetime.now().strftime('%Y-%m-%d %H:%M'))
    _save(data, path)
    return data[product]


def candidate_exits(wf, candidate):
    """The stop / target a walk-forward candidate was scored with (its own when exits were searched)."""
    row = (wf.get('rows') or {}).get(candidate) or {}
    if 'exits' in row:
        return row['exits']
    return None if wf.get('exits') == 'search' else wf.get('exits')


def _longest_losing_run(pnl):
    """Longest run of consecutive losing days in the walk-forward P&L (flat days skipped); None without P&L."""
    best = cur = 0
    for v in pnl[pnl != 0]:
        cur = cur + 1 if v < 0 else 0
        best = max(best, cur)
    return best if len(pnl) else None


def approve(product, candidate, wf, path=None, force=False):
    """Record `candidate` (e.g. 'SAR@30min') as the product's approved strategy. Refuses a candidate
    that did not pass the gates in the walk-forward run `wf`.

    A night + day run (wf['session']) approves the strategy on night + day bars. Its only extra gate is the
    number of trade days that had a night session; force=True overrides that one gate (and records the
    override), never the day gates."""
    row = (wf.get('rows') or {}).get(candidate)
    if row is None:
        raise ValueError(f"{candidate} is not in the walk-forward result")
    from futures.backtest.walkforward import max_units
    if max_units(candidate) > 1:
        raise ValueError(f"{candidate} scales in and out in units (up to {max_units(candidate):g}); the intraday "
                         f"tickets trade one position per signal, so only its daily version can be approved")
    night = wf.get('session') == 'night+day'
    if night:
        if not row.get('passes_ex_night'):
            raise ValueError(f"{candidate} fails the day gates: not even a forced approval is allowed")
        if not row['passes'] and not force:
            raise ValueError(f"{candidate} has {wf.get('night_days', 0)} night days, "
                             f"{(wf.get('gates') or {}).get('min_night_days')} are needed: use Force approve")
    elif not row['passes']:
        raise ValueError(f"{candidate} does not pass the approval gates")
    path = path or APPROVED_PATH
    strategy, timeframe = candidate.split('@')
    pnl = pd.Series(((wf.get('daily_pnl') or {}).get(candidate)) or {}, dtype=float)
    data = load_approved(path)
    data[product] = {
        'strategy': strategy, 'timeframe': timeframe, 'candidate': candidate,
        'approved_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'cost_bp': wf['cost_bp'], 'exits': candidate_exits(wf, candidate), 'wf_run_at': wf['run_at'], 'wf_last_day': wf['last_day'],
        'pooled_sharpe': row['pooled'], 'sharpe_se': row['se'], 'per_contract': row['per_contract'],
        'trades': row['trades'], 'win': row['win'], 'payoff': row['payoff'],
        'expectancy_bp': row['expectancy_bp'], 'status': 'approved',
        'session': 'night+day' if night else 'day',
        **({'night_days': wf.get('night_days'), 'forced': not row['passes']} if night else {}),
        'daily_mean': float(pnl.mean()) if len(pnl) else None, 'daily_std': float(pnl.std()) if len(pnl) > 1 else None,
        'max_streak': _longest_losing_run(pnl),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)
    return data[product]


def remove(product, path=None):
    """Delete a product's approval record entirely (unlike a halt, nothing is kept). Returns the removed
    record. It only returns through a fresh walk-forward and approve()."""
    path = path or APPROVED_PATH
    data = load_approved(path)
    if product not in data:
        raise ValueError(f"{product} is not approved")
    rec = data.pop(product)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)
    return rec


def set_status(product, status, reason, path=None):
    """Set an approved product's status ('approved' | 'watch' | 'halted'). A halted product only
    returns through a fresh walk-forward and approve()."""
    if status not in ('approved', 'watch', 'halted'):
        raise ValueError(f"unknown status {status}")
    path = path or APPROVED_PATH
    data = load_approved(path)
    if product not in data:
        raise ValueError(f"{product} is not approved")
    data[product].update(status=status, status_reason=reason, status_at=datetime.now().strftime('%Y-%m-%d %H:%M'))
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)
    return data[product]
