# -*- coding: utf-8 -*-
"""Close / rebalance reminders for Summary > Books > Portfolio Allocation Snapshot.

There is no order or fill pipeline: the books are edited by hand and the snapshot is the working surface. The
two books are netted for risk and margin, but each stays the source of truth for its own positions:

* Alpha - an exit is decided per TRADE (its own stop / target / signal, shown by the alpha table's alerts). This
  module turns an alert into the legs to trade, so the manual change is one concrete ticket.
* Beta - a target book that moves every day with the factor signals. Trading it daily costs ~40x capital a year
  of turnover; a calendar rebalance (monthly) costs ~14x. So the snapshot asks for a rebalance when the month
  has turned or the held book has drifted far from target, and lists the trades back to target.

Pure functions on the table's display rows (strings as rendered), no I/O.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

BOND_LOT_MM = 10.0          # bonds / credit / swap spreads trade in 10MM lots (same as the Portfolio tab)
OTHER_LOT_MM = 1.0          # FX / commodity: 1MM
_BOND_TYPES = ('Rates', 'Credit', 'Spread')


def _num(value: Any) -> Optional[float]:
    """Parse a rendered number ('1,234.5', '+0.12', '12.3%'); None for blank / 'N/A' / non-numeric."""
    if value is None:
        return None
    s = str(value).replace(',', '').replace('%', '').replace('+', '').strip()
    if not s or s.upper() in ('N/A', 'NAN', 'NONE', '—', '-'):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v == v else None


# ── Alpha ────────────────────────────────────────────────────────────────────────────────────────────────────

def alpha_close_ticket(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Legs to trade to CLOSE an alpha trade, from its table row.

    The trade is ``+leg1 / -leg2 [/ -leg3]`` for BUY and the mirror image for SELL, so closing is the opposite.
    Sizes are in MM CNY: the booked ``Volume (mm)`` when entered, else the target ``Capital (MM CNY)`` (an
    indicative ticket for a trade that is sized but not yet booked), times the leg DV01 ratios. Legs without a
    code (the unresolved ones) are skipped; a leg with no ratio is skipped rather than guessed.
    """
    direction = str(row.get('Direction', '')).strip().upper()
    if direction not in ('BUY', 'SELL', 'LONG', 'SHORT'):
        return []
    buy = direction in ('BUY', 'LONG')
    size = _num(row.get('Volume (mm)'))
    booked = size is not None and size > 0
    if not booked:
        cap = _num(row.get('Capital (MM CNY)'))
        size = abs(cap) if cap else None
    if not size:
        return []
    legs = [
        (str(row.get('Leg 1', '') or ''), 1.0, 'SELL' if buy else 'BUY'),
        (str(row.get('Leg 2', '') or ''), _num(row.get('Ratio (V2/V1)')), 'BUY' if buy else 'SELL'),
        (str(row.get('Leg 3', '') or ''), _num(row.get('Ratio (V3/V1)')), 'BUY' if buy else 'SELL'),
    ]
    out = []
    for code, ratio, side in legs:
        if not code or ratio is None or ratio <= 0:
            continue
        out.append({'leg': code, 'side': side, 'volume_mm': round(abs(size) * ratio, 1), 'booked': booked})
    return out


def format_ticket(ticket: Iterable[Dict[str, Any]]) -> str:
    """'SELL 100.0 MM 240203.IB · BUY 210.5 MM 260018.IB'"""
    return ' · '.join(f"{t['side']} {t['volume_mm']:,.1f} MM {t['leg']}" for t in ticket)


# ── Beta ─────────────────────────────────────────────────────────────────────────────────────────────────────

def beta_rebalance_plan(
    rows: Iterable[Dict[str, Any]],
    today: Optional[pd.Timestamp] = None,
    drift_trigger: float = 0.5,
) -> Dict[str, Any]:
    """Whether the held beta book is due a rebalance, why, and the trades back to target.

    ``rows`` are the beta table rows: ``Capital (MM CNY)`` is the signed TARGET, ``Volume (MM)`` the HELD size
    (a magnitude - the direction is the target's, as in ``beta_mtm_mm``), ``Open Date`` when it was booked.

    Due when any of:
      * ``month``  - the latest booking date is before the current calendar month (calendar rebalance);
      * ``drift``  - DV01-weighted distance of the held book from target exceeds ``drift_trigger`` of the
                     target's gross DV01 (an off-cycle rebalance; the trigger is a judgement, not tuned);
      * ``unbooked`` - a target has no held size at all while others do.
    With nothing booked the status is ``'not_booked'`` (nothing to rebalance against).

    Returns ``{'status': 'due'|'ok'|'not_booked', 'reasons': [...], 'drift': float|None, 'last_booked':
    Timestamp|None, 'trades': [{'name', 'target_mm', 'held_mm', 'delta_mm'}], 'deltas': {name: delta_mm}}``
    with trades limited to deltas of at least one lot.
    """
    today = pd.Timestamp(today if today is not None else pd.Timestamp.today()).normalize()
    items, dates = [], []
    for r in rows:
        if str(r.get('Asset Type', '')) == 'TOTAL':
            continue
        target = _num(r.get('Capital (MM CNY)'))
        if target is None:
            continue
        held_mag = _num(r.get('Volume (MM)'))
        sign = -1.0 if target < 0 else 1.0
        held = None if held_mag is None else sign * abs(held_mag)
        dur = _num(r.get('Duration')) or 0.0
        lot = BOND_LOT_MM if str(r.get('Asset Type', '')) in _BOND_TYPES else OTHER_LOT_MM
        name = str(r.get('Instrument') or r.get('Asset Name') or '')
        items.append({'name': name, 'target': target, 'held': held, 'dur': dur, 'lot': lot})
        d = pd.to_datetime(str(r.get('Open Date', '') or ''), errors='coerce')
        if held_mag and pd.notna(d):
            dates.append(d.normalize())

    plan: Dict[str, Any] = {'status': 'not_booked', 'reasons': [], 'drift': None, 'last_booked': None,
                            'trades': [], 'deltas': {}}
    if not any(i['held'] for i in items):
        return plan

    reasons = []
    last = max(dates) if dates else None
    plan['last_booked'] = last
    if last is None or (last.year, last.month) < (today.year, today.month):
        reasons.append('month')
    if any(i['held'] is None for i in items):
        reasons.append('unbooked')

    num = den = 0.0
    for i in items:
        held = i['held'] or 0.0
        plan['deltas'][i['name']] = round(i['target'] - held, 4)
        w = i['dur'] if i['dur'] > 0 else 0.0
        num += abs(i['target'] - held) * w
        den += abs(i['target']) * w
    plan['drift'] = (num / den) if den > 0 else None
    if plan['drift'] is not None and plan['drift'] > drift_trigger:
        reasons.append('drift')

    plan['trades'] = [
        {'name': i['name'], 'target_mm': i['target'], 'held_mm': i['held'] or 0.0,
         'delta_mm': round(i['target'] - (i['held'] or 0.0), 1)}
        for i in items if abs(i['target'] - (i['held'] or 0.0)) >= i['lot']
    ]
    plan['reasons'] = reasons
    plan['status'] = 'due' if reasons else 'ok'
    return plan
