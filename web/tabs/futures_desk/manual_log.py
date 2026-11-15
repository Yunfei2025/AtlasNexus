# -*- coding: utf-8 -*-
"""What you actually did: one JSON file per trading day of the order tickets you marked done in the Monitor,
with your fill price and lots, in input/futures_desk/manual/<YYYY-MM-DD>.json.

{key: {'done': bool, 'at': 'HH:MM:SS' Beijing, 'lots': int, 'fill': float | None, 'ticket': str}}
key = '<PRODUCT>|<entry HH:MM>|open' or '...|close' (see actions.action_key)."""

from __future__ import annotations

import json
import os

from futures.backtest.live_bars import china_now

from . import approvals


def _dir(log_dir=None):
    d = log_dir or (approvals.DESK_DIR / 'manual')
    os.makedirs(d, exist_ok=True)
    return d


def _path(day, log_dir=None):
    return os.path.join(_dir(log_dir), f"{day:%Y-%m-%d}.json" if hasattr(day, 'strftime') else f"{day}.json")


def load_log(day, log_dir=None):
    try:
        with open(_path(day, log_dir), encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def _write(day, data, log_dir=None):
    path = _path(day, log_dir)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def set_done(day, key, done, lots=None, ticket=None, log_dir=None):
    """Mark a ticket done (keeps any fill already typed) or not done."""
    data = load_log(day, log_dir)
    rec = data.get(key, {})
    rec['done'] = bool(done)
    if done:
        rec['at'] = china_now().strftime('%H:%M:%S')
        if lots is not None:
            rec['lots'] = int(lots)
        if ticket:
            rec['ticket'] = ticket
    data[key] = rec
    _write(day, data, log_dir)
    return rec


def set_fill(day, key, fill, log_dir=None):
    """Record the fill price you got (None clears it). Does not change the done flag."""
    data = load_log(day, log_dir)
    rec = data.get(key, {'done': False})
    rec['fill'] = None if fill is None else float(fill)
    data[key] = rec
    _write(day, data, log_dir)
    return rec
