# -*- coding: utf-8 -*-
"""Shared trade-direction labelling for the Alpha backtest engines."""

from __future__ import annotations


def _direction_label(position: int) -> str:
    """Map an engine position to its trade-direction label.

    ``position`` is held on the *sign-normalised* series the engine sees: for
    yield-based spreads the caller passes ``-raw`` (see
    ``YIELD_BASED_SPREAD_TYPES``), so ``position=+1`` means

        price_pnl = (ts_exit - ts_entry) * (+1) * dur
                  = -(raw_exit - raw_entry) * dur

    i.e. it profits when the *raw* spread falls/narrows.  For a curve spread
    such as ``CGB-10s30s`` (``raw = Y30 - Y10``) that is economically long the
    30y and short the 10y -- long the 30y price, short its yield -- which is
    the desk's LONG.  ``position=-1`` is the opposite, SHORT.

    The MR branch previously labelled ``position=+1`` as ``SELL`` while the
    trend branch labelled the identical position ``LONG``, so the two styles
    contradicted each other and an economically long MR trade was reported as
    a short.  Both now derive the label from the position sign alone; the P&L
    arithmetic is unchanged.
    """
    return 'LONG' if position == 1 else 'SHORT'
