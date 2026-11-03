# -*- coding: utf-8 -*-
"""Funded, DV01-weighted carry of the CGB/CDB curve trades (TenorSpread slopes and flies).

The alpha book holds a spread as a DV01-neutral package financed by TRS: it receives each bond's
return and pays funding on every leg's notional. The package's carry is therefore NOT the raw
yield spread; with notionals ``h_i`` sized so that the DV01 of the package equals ``D_ref`` per
unit of reference notional (the longer leg for a slope, the belly for a fly - the same ``D_ref``
the backtest engines price P&L with, ``dspread x D_ref``):

    slope  XsYs  BUY = long short tenor, short long tenor
           carry = (y_s - f) * D_l / D_s - (y_l - f)
    fly    NsMsLs BUY = long 2x belly, short each wing
           carry = 2 (y_m - f) - (y_s - f) * D_m / D_s - (y_l - f) * D_m / D_l

in % per year of reference notional, ``f`` the funding rate. Cross-curve names (same tenor on both
legs: CDBCGB, LGBCGB, MTNCGB, bond-vs-repo) are not handled here: funding cancels leg against leg
and their stored carry is already right.

``trs_spread_bp`` is the dealer's spread over the funding rate. It is a cost on the notional of
EVERY leg whichever way the trade is held (a long TRS pays funding + spread, a short TRS receives
funding - spread), so it cannot be folded into one BUY-side series: BUY and SELL carry are
returned separately. It is a placeholder (0) until the dealer's spread is known.
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from settings.paths import DIR_INPUT

_ID_RE = re.compile(r'^(CGB|CDB)-((?:\d+s){2,3})$', re.IGNORECASE)


def parse_curve_trade(spread_id: str) -> Optional[Tuple[str, List[int]]]:
    """``'CGB-2s5s10s'`` -> ``('CGB', [2, 5, 10])``; None for anything that is not a CGB/CDB slope/fly."""
    m = _ID_RE.match(str(spread_id).strip())
    if not m:
        return None
    return m.group(1).upper(), [int(t) for t in re.findall(r'(\d+)s', m.group(2))]


def modified_duration(y_pct, n_years: float):
    """Annuity modified duration of an ``n_years`` par bond at yield ``y_pct`` (%), the same formula
    the beta book prices with (multiasset.book.sizing)."""
    y = y_pct / 100.0
    return (1.0 - (1.0 + y) ** (-n_years)) / (y * (1.0 + y))


def package_notionals(yields: Sequence[pd.Series], tenors: Sequence[int]) -> List[pd.Series]:
    """Signed leg notionals of the BUY package per unit of reference notional (+ long, - short)."""
    d = [modified_duration(y, n) for y, n in zip(yields, tenors)]
    if len(tenors) == 2:
        return [d[1] / d[0], -1.0 + 0.0 * d[1]]
    if len(tenors) == 3:
        return [-d[1] / d[0], 2.0 + 0.0 * d[1], -d[1] / d[2]]
    raise ValueError(f'a slope has 2 tenors and a fly 3, got {len(tenors)}')


def funded_package_carry(
    yields: Sequence[pd.Series],
    tenors: Sequence[int],
    funding: pd.Series,
    trs_spread_bp: float = 0.0,
) -> Tuple[pd.Series, pd.Series]:
    """(BUY, SELL) annual carry in % of reference notional of a DV01-neutral slope/fly package.

    ``yields`` are the leg yields in % ordered as ``tenors`` (short to long), ``funding`` the funding
    rate in % on the same index. BUY is long the short tenor of a slope / long the belly of a fly.
    """
    h = package_notionals(yields, tenors)
    s = float(trs_spread_bp) / 100.0
    gross = sum(x.abs() for x in h)
    buy = sum(hi * (y - funding) for hi, y in zip(h, yields)) - s * gross
    sell = -sum(hi * (y - funding) for hi, y in zip(h, yields)) - s * gross
    return buy, sell


def load_cn_funding(swap_ts: Optional[pd.DataFrame] = None, window: int = 20) -> Optional[pd.Series]:
    """Funding rate (%) for the carry: the 3M FR007 swap where it exists (from 2022-02), the trailing
    ``window``-day FR007 fixing before that. None when neither is available."""
    fr7 = None
    try:
        raw = pd.read_pickle(os.path.join(str(DIR_INPUT), 'macro-px.pkl'))
        macro = pd.concat(raw, axis=1).droplevel(0, axis=1)
        macro.columns = [c.split('.')[0] for c in macro.columns]
        rate = pd.to_numeric(macro['FR007'], errors='coerce').dropna()
        rate.index = pd.to_datetime(rate.index)
        fr7 = rate.sort_index().rolling(window, min_periods=min(5, window)).mean()
    except Exception as exc:
        print(f'WARN tenor carry: FR007 history unavailable ({exc})')
    s3m = None
    if isinstance(swap_ts, pd.DataFrame) and 'FR007S3M.IR' in swap_ts.columns:
        s3m = pd.to_numeric(swap_ts['FR007S3M.IR'], errors='coerce')
        s3m.index = pd.to_datetime(s3m.index)
        s3m = s3m.sort_index()
    if s3m is not None and fr7 is not None:
        return s3m.combine_first(fr7)
    return s3m if s3m is not None else fr7


def funded_carry_frames(
    curve_yields: Dict[str, Dict[int, pd.Series]],
    columns: Sequence[str],
    index: pd.DatetimeIndex,
    funding: pd.Series,
    trs_spread_bp: float = 0.0,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Funded 3-month carry (% of reference notional) for the curve trades among ``columns``, as
    (BUY, SELL) frames on ``index``. ``curve_yields[curve][tenor]`` are the key-rate yields in %.
    Columns that are not CGB/CDB slopes/flies, or lack a leg's yield, are left out."""
    buy, sell = {}, {}
    f = funding.reindex(funding.index.union(index)).ffill().reindex(index)
    for col in columns:
        parsed = parse_curve_trade(col)
        if parsed is None:
            continue
        curve, tenors = parsed
        legs = [curve_yields.get(curve, {}).get(n) for n in tenors]
        if any(y is None for y in legs):
            continue
        ys = [y.reindex(y.index.union(index)).ffill().reindex(index) for y in legs]
        b, s = funded_package_carry(ys, tenors, f, trs_spread_bp)
        buy[col], sell[col] = b * 0.25, s * 0.25          # annual % -> 3 months (90/360)
    return pd.DataFrame(buy, index=index), pd.DataFrame(sell, index=index)
