# -*- coding: utf-8 -*-
"""Exchange contract details the Monitor needs to turn a signal into an order you can type into a broker app.

Typed in from exchange contract specs, like pool.CONTRACT_MULTIPLIER -- NOT read from any data feed.
Verify a product here before trading it, and after any exchange rule change."""

from __future__ import annotations

import math
import re

from futures.backtest.costs import product_of

# Minimum price change, in the quoted price.
TICK_SIZE = {
    'IF': 0.2, 'IH': 0.2, 'IC': 0.2, 'IM': 0.2,
    'T': 0.005, 'TF': 0.005, 'TS': 0.002, 'TL': 0.01,
    'AU': 0.02, 'AG': 1, 'CU': 10, 'AL': 5, 'ZN': 5, 'RB': 1,
    'LC': 20, 'SA': 1, 'SC': 0.1, 'JM': 0.5, 'EC': 0.1,
}

EXCHANGE = {
    'IF': 'CFFEX', 'IH': 'CFFEX', 'IC': 'CFFEX', 'IM': 'CFFEX',
    'T': 'CFFEX', 'TF': 'CFFEX', 'TS': 'CFFEX', 'TL': 'CFFEX',
    'AU': 'SHFE', 'AG': 'SHFE', 'CU': 'SHFE', 'AL': 'SHFE', 'ZN': 'SHFE', 'RB': 'SHFE',
    'SC': 'INE', 'EC': 'INE', 'JM': 'DCE', 'SA': 'CZCE', 'LC': 'GFEX',
}

# Exchanges where closing a position opened today is a separate order type (平今) from closing an older one.
CLOSE_TODAY_EXCHANGES = {'SHFE', 'INE'}

# Day-session close, Beijing time: CFFEX bond futures trade to 15:15, everything else here to 15:00.
_BOND = {'T', 'TF', 'TS', 'TL'}


def day_close(product):
    """'HH:MM' the day session closes, which is when the strategies are flat."""
    return '15:15' if product in _BOND else '15:00'


def tick_of(product):
    return TICK_SIZE.get(product)


def round_tick(price, product):
    """Price on the product's tick grid (nearest tick); unchanged when the tick is unknown."""
    tick = TICK_SIZE.get(product)
    if price is None or tick is None or not math.isfinite(price):
        return price
    return round(round(price / tick) * tick, 10)


def price_fmt(price, product):
    """Price string with exactly the tick's decimals, e.g. AL 22,570 / AU 841.40 / TL 117.45."""
    if price is None:
        return '—'
    tick = TICK_SIZE.get(product)
    if tick is None:
        dec = 2
    elif tick >= 1:
        dec = 0
    else:
        dec = len(f"{tick:.10f}".rstrip('0').split('.')[1])
    return f"{round_tick(price, product):,.{dec}f}"


def app_code(contract):
    """Contract code as broker apps show it: lower case on SHFE / INE / DCE / GFEX (al2612), upper case on
    CFFEX (IM2612), upper case with a 3-digit month on CZCE (SA612)."""
    prod = product_of(contract)
    m = re.match(r'([A-Za-z]+)(\d+)', contract or '')
    if not m or prod is None:
        return contract
    digits = m.group(2)
    ex = EXCHANGE.get(prod)
    if ex == 'CFFEX':
        return f"{prod}{digits}"
    if ex == 'CZCE':
        return f"{prod}{digits[-3:]}"
    return f"{prod.lower()}{digits}"


def order_words(direction, opening, product):
    """Side and offset in English with the app's Chinese button words, e.g. ('Buy', 'Open', '买开')."""
    side = 'Buy' if direction > 0 else 'Sell'
    if opening:
        return side, 'Open', ('买' if direction > 0 else '卖') + '开'
    today = EXCHANGE.get(product) in CLOSE_TODAY_EXCHANGES
    return side, 'Close today' if today else 'Close', ('买' if direction > 0 else '卖') + ('平今' if today else '平')
