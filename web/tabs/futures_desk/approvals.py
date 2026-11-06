# -*- coding: utf-8 -*-
"""Futures Desk approvals: one approved intraday strategy per product, with the evidence it passed on."""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from settings.paths import DIR_INPUT

DESK_DIR = DIR_INPUT / 'futures_desk'   # wf_<PRODUCT>.json (walk-forward runs) and approved.json
APPROVED_PATH = DESK_DIR / 'approved.json'


def load_approved(path=None):
    path = path or APPROVED_PATH
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def candidate_exits(wf, candidate):
    """The stop / target a walk-forward candidate was scored with (its own when exits were searched)."""
    row = (wf.get('rows') or {}).get(candidate) or {}
    if 'exits' in row:
        return row['exits']
    return None if wf.get('exits') == 'search' else wf.get('exits')


def approve(product, candidate, wf, path=None):
    """Record `candidate` (e.g. 'SAR@30min') as the product's approved strategy. Refuses a candidate
    that did not pass the gates in the walk-forward run `wf`."""
    row = (wf.get('rows') or {}).get(candidate)
    if row is None:
        raise ValueError(f"{candidate} is not in the walk-forward result")
    if not row['passes']:
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
        'daily_mean': float(pnl.mean()) if len(pnl) else None, 'daily_std': float(pnl.std()) if len(pnl) > 1 else None,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)
    return data[product]


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
