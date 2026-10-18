# -*- coding: utf-8 -*-
"""Registry of duration-overlay instruments for the beta book.

The beta book is unlevered, so futures and swaps are used only as a DURATION
overlay: to hedge cash-bond DV01, or to run net short duration when IRDL goes
short (docs/plans/factor_model_improvement.md 3.9c, 3.10). Decisions (user,
2026-10-17):

* CHINA shorts: 5Y and longer are shorted as cash bonds (easy to borrow); 1Y and 2Y
  use FR007 swaps (``RiskModelConfig.CN_SHORT_ROUTING``). CFFEX futures TS (2Y), TF
  (5Y), T (10Y), TL (30Y) stay in the registry as an option (a 5Y swap is redundant
  next to TF: monthly R2 vs cash CGB 0.83 vs 0.87) but are not used by default.
* FOREIGN rates (US/DE/JP/UK): no futures/swap data, so a short is a SHORT
  CASH BOND of the same market (``hedge_route``).
* Futures DV01 uses the annuity-formula duration PROXY at the contract's
  nominal tenor and the matching cash-CGB yield (no CTD / conversion-factor
  data exists). It is a proxy, not an exchange DV01.
* Margin is ``DERIVATIVE_MARGIN_RATE`` (3%) of |notional| and counts as used
  capital: capital usage = cash gross + derivative margin, capped with the
  book's 95% utilisation ceiling.

This module is definitions + sizing maths only; the P&L leg (futures roll/basis
carry, swap fixed-vs-FR007 carry) is a separate step.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd

DERIVATIVE_MARGIN_RATE: float = 0.03   # user-provided, applies to futures and cleared swaps

# Countries whose rates can be traded through the registry. Everything else
# (US, DE, JP, UK) is shorted with the cash bond itself.
OVERLAY_MARKETS: Tuple[str, ...] = ('CN',)


@dataclass(frozen=True)
class HedgeInstrument:
    name: str                      # 'TF'
    kind: str                      # 'future' | 'swap'
    market: str                    # 'CN'
    tenor_years: float             # nominal tenor feeding the duration proxy
    yield_col: str                 # CGB tenor whose yield drives the proxy, e.g. '5Y'
    data_key: str                  # futures-dailyK_con.pkl key, or database-px 'IRS' column
    face_cny: float = 1_000_000.0  # contract face (futures); swaps are sized by notional
    first_date: str = '2015-01-01'  # first available history in the repo
    gap_filler: bool = False       # swaps used only where no future exists

    @property
    def is_future(self) -> bool:
        return self.kind == 'future'


# CFFEX face values (confirmed by the user 2026-10-17): TS 2,000,000; TF/T/TL
# 1,000,000. first_date = first row in futures-dailyK_con.pkl / database-px.pkl
# as of 2026-10-17.
REGISTRY: Dict[str, HedgeInstrument] = {i.name: i for i in (
    HedgeInstrument('TS', 'future', 'CN', 2.0, '2Y', 'TS.CFE', 2_000_000.0, '2018-08-17'),
    HedgeInstrument('TF', 'future', 'CN', 5.0, '5Y', 'TF.CFE', 1_000_000.0, '2015-03-30'),
    HedgeInstrument('T', 'future', 'CN', 10.0, '10Y', 'T.CFE', 1_000_000.0, '2015-03-23'),
    HedgeInstrument('TL', 'future', 'CN', 30.0, '30Y', 'TL.CFE', 1_000_000.0, '2023-04-21'),
    # Swaps fill ONLY the gaps between futures; data from database-px.pkl['IRS'] (2022-02).
    HedgeInstrument('SWAP1Y', 'swap', 'CN', 1.0, '1Y', 'FR007S1Y.IR', 1.0, '2022-02-28', gap_filler=True),
    HedgeInstrument('SWAP2Y', 'swap', 'CN', 2.0, '2Y', 'FR007S2Y.IR', 1.0, '2022-02-28', gap_filler=True),
    HedgeInstrument('SWAP3Y', 'swap', 'CN', 3.0, '3Y', 'FR007S3Y.IR', 1.0, '2022-02-28', gap_filler=True),
)}


def hedge_route(country: str) -> str:
    """'overlay' for China (futures / swaps); 'short_bond' for every other market."""
    return 'overlay' if country in OVERLAY_MARKETS else 'short_bond'


def mod_duration(yield_pct, tenor_years: float):
    """Annuity-formula modified duration, the same proxy the book uses for cash
    bonds (multiasset.data.calculate_daily_returns_series). ``yield_pct`` in %;
    a scalar gives a float, a Series gives a Series."""
    if isinstance(yield_pct, pd.Series):
        y = (yield_pct.astype(float) / 100.0).clip(lower=0.001)
    else:
        y = max(float(yield_pct) / 100.0, 0.001)
    return (1.0 - (1.0 + y) ** (-tenor_years)) / (y * (1.0 + y))


def available(inst: HedgeInstrument, asof) -> bool:
    return pd.Timestamp(asof) >= pd.Timestamp(inst.first_date)


def candidates(asof, allow_swaps: bool = True, market: str = 'CN') -> List[HedgeInstrument]:
    """Instruments usable on ``asof``, sorted by tenor."""
    out = [i for i in REGISTRY.values()
           if i.market == market and available(i, asof) and (allow_swaps or not i.gap_filler)]
    return sorted(out, key=lambda i: i.tenor_years)


def split_dv01(tenor_years: float, asof, allow_swaps: bool = True) -> Dict[str, float]:
    """Weights (summing to 1) that spread a China DV01 at ``tenor_years`` over the
    instruments available on ``asof``: an exact-tenor instrument takes all of it,
    otherwise the two neighbours share it linearly in tenor (7Y -> TF 60%, T 40%),
    and beyond either end the nearest instrument takes it all. Interpolation is
    in tenor, a stand-in for key-rate matching."""
    cands = candidates(asof, allow_swaps)
    if not cands:
        raise ValueError(f'no China overlay instrument available on {asof}')
    tenors = [c.tenor_years for c in cands]
    if tenor_years <= tenors[0]:
        return {cands[0].name: 1.0}
    if tenor_years >= tenors[-1]:
        return {cands[-1].name: 1.0}
    for lo, hi in zip(cands[:-1], cands[1:]):
        if lo.tenor_years <= tenor_years <= hi.tenor_years:
            w_hi = (tenor_years - lo.tenor_years) / (hi.tenor_years - lo.tenor_years)
            return {n: w for n, w in ((lo.name, 1.0 - w_hi), (hi.name, w_hi)) if w > 1e-12}
    raise AssertionError('unreachable')


def dv01_per_cny(inst: HedgeInstrument, yield_pct: float) -> float:
    """CNY of P&L per bp per 1 CNY of notional (duration proxy)."""
    return mod_duration(yield_pct, inst.tenor_years) * 1e-4


def notional_for_dv01(inst: HedgeInstrument, dv01_cny_per_bp: float, yield_pct: float) -> float:
    """CNY notional that carries ``dv01_cny_per_bp`` (signed like the input)."""
    return dv01_cny_per_bp / dv01_per_cny(inst, yield_pct)


def contracts_for_dv01(inst: HedgeInstrument, dv01_cny_per_bp: float, yield_pct: float) -> int:
    """Whole futures contracts for a DV01 (nominal price 100: notional = face)."""
    if not inst.is_future:
        raise ValueError(f'{inst.name} is a swap; size it by notional_for_dv01')
    return int(round(notional_for_dv01(inst, dv01_cny_per_bp, yield_pct) / inst.face_cny))


def margin_cny(notional_cny: float, rate: float = DERIVATIVE_MARGIN_RATE) -> float:
    return abs(float(notional_cny)) * rate


def capital_usage(cash_gross_cny: float, derivative_notional_cny: float, total_capital_cny: float,
                  rate: float = DERIVATIVE_MARGIN_RATE) -> float:
    """Fraction of capital used: cash-bond/asset gross + derivative margin. Compare
    with RiskModelConfig.CAPITAL_UTILISATION_MAX (0.95)."""
    return (abs(cash_gross_cny) + margin_cny(derivative_notional_cny, rate)) / total_capital_cny


def cash_headroom(derivative_notional_cny: float, total_capital_cny: float, max_utilisation: float = 0.95,
                  rate: float = DERIVATIVE_MARGIN_RATE) -> float:
    """Cash gross allowed (CNY) once derivative margin is reserved inside the cap."""
    return max_utilisation * total_capital_cny - margin_cny(derivative_notional_cny, rate)
