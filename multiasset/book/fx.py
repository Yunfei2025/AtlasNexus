# -*- coding: utf-8 -*-
"""Explicit FX overlay for foreign bonds held by a CNY-based book.

A foreign bond bought with CNY carries two risks: its local rates exposure
(IRDL/IRSL/IRCV.<country>) and its currency (FXDL.<ccy>CNY, 1.0 x notional).
The portfolio optimizer sees both (see multiasset.utils.get_default_
sensitivities). The currency leg is then neutralised by a forward sold against
CNY on the bond's notional. That forward and the FX sleeve (USDCNY/EURCNY/...
spot assets, signed by the FXDL view) trade the same factor, so they are NETTED
into one ticket per currency:

    bond[c]          embedded long-ccy exposure of foreign bonds (CNY notional)
    hedge[c]         forward to sell on the bonds           = -bond[c]
    sleeve[c]        FXDL view, expressed in the currency   (USDCNY long = +USD)
    net_forward[c]   the single forward to execute          = sleeve[c] - bond[c]
    net_exposure[c]  FX exposure left after the hedge       = sleeve[c]

so a currency view comes only from the FXDL sleeve, never from owning bonds.

P&L (multiasset.book.pnl): the bond's embedded spot move and the hedge's
offsetting move are both booked, net zero, so rates P&L stays clean and the
FX exposure is visible rather than assumed away. The hedge's carry (foreign
short rate minus CNY short rate) is charged through the funding hurdle, which
bills foreign notional at the foreign overnight rate
(multiasset.book.funding); the cross-currency basis is not modelled (no
forward-point data).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import pandas as pd

# FX sleeve asset -> {currency: signed unit exposure} per +1 notional.
# Crosses are CNY-neutral: long the non-USD leg vs CNY, short USDCNY.
FX_ASSET_LEGS: Dict[str, Dict[str, float]] = {
    'USDCNY': {'USD': 1.0},
    'EURCNY': {'EUR': 1.0},
    'GBPCNY': {'GBP': 1.0},
    'JPYCNY': {'JPY': 1.0},
    'EURUSD_SYN': {'EUR': 1.0, 'USD': -1.0},
    'GBPUSD_SYN': {'GBP': 1.0, 'USD': -1.0},
    'JPYUSD_SYN': {'JPY': 1.0, 'USD': -1.0},
}

# Bond domicile (multiasset.book.funding.normalise_domicile codes) -> currency.
DOMICILE_TO_CCY: Dict[str, str] = {'US': 'USD', 'DE': 'EUR', 'EU': 'EUR', 'UK': 'GBP', 'JP': 'JPY'}


# portfolio_df 'Universe' -> domicile, for callers (Portfolio tab) that have
# a single-day allocation table and no market_data to resolve countries from.
UNIVERSE_TO_DOMICILE: Dict[str, str] = {
    'US Gov Bond': 'US', 'DE Gov Bond': 'DE', 'UK Gov Bond': 'UK', 'Japan Gov Bond': 'JP',
}


@dataclass
class FXOverlay:
    """Daily CNY notionals (date x currency), long-currency positive."""
    bond: pd.DataFrame
    hedge: pd.DataFrame
    sleeve: pd.DataFrame
    net_forward: pd.DataFrame
    net_exposure: pd.DataFrame

    def summary(self, total_capital: float) -> pd.DataFrame:
        """Average absolute notional, as % of capital, per currency."""
        cols = {
            'Bond FX embedded': self.bond, 'Hedge (sell fwd)': self.hedge,
            'FX sleeve': self.sleeve, 'Net forward ticket': self.net_forward,
            'Net FX exposure': self.net_exposure,
        }
        return pd.DataFrame({k: v.abs().mean() / total_capital * 100.0 for k, v in cols.items()}).round(2)


def _by_currency(notional_daily: pd.DataFrame, legs: Dict[str, Dict[str, float]]) -> pd.DataFrame:
    out = pd.DataFrame(0.0, index=notional_daily.index, columns=sorted({c for v in legs.values() for c in v}))
    for asset, ccy_legs in legs.items():
        if asset in notional_daily.columns:
            for ccy, unit in ccy_legs.items():
                out[ccy] = out[ccy] + notional_daily[asset].fillna(0.0) * unit
    return out


def bond_ccy_of(domicile_of: Dict[str, str]) -> Dict[str, Dict[str, float]]:
    """asset -> {ccy: 1.0} for assets whose domicile is a foreign currency area."""
    return {a: {DOMICILE_TO_CCY[d]: 1.0} for a, d in domicile_of.items() if d in DOMICILE_TO_CCY}


def fx_overlay(notional_daily: pd.DataFrame, domicile_of: Dict[str, str]) -> FXOverlay:
    """Embedded FX of foreign bonds, the hedge on it, and the netted ticket.

    ``domicile_of`` is multiasset.book.funding.build_domicile_of's output;
    a bond's CNY notional is taken as its currency exposure (hedge ratio 1).
    """
    bond = _by_currency(notional_daily, bond_ccy_of(domicile_of))
    sleeve = _by_currency(notional_daily, FX_ASSET_LEGS)
    ccys = sorted(set(bond.columns) | set(sleeve.columns))
    bond, sleeve = bond.reindex(columns=ccys, fill_value=0.0), sleeve.reindex(columns=ccys, fill_value=0.0)
    hedge = -bond
    return FXOverlay(bond=bond, hedge=hedge, sleeve=sleeve,
                     net_forward=sleeve + hedge, net_exposure=bond + hedge + sleeve)


def fx_hedge_ticket(alloc_cny: Dict[str, float], universe_of: Dict[str, str]) -> list:
    """One-day netted FX ticket for the Portfolio tab: per currency, the
    embedded bond FX, the FX sleeve, and the single forward to execute (CNY,
    millions). ``alloc_cny``: asset -> signed CNY allocation; ``universe_of``:
    asset -> universe label (e.g. 'US Gov Bond')."""
    domicile_of = {a: UNIVERSE_TO_DOMICILE.get(universe_of.get(a, ''), '') for a in alloc_cny}
    ov = fx_overlay(pd.DataFrame([alloc_cny]), domicile_of)
    rows = []
    for ccy in ov.bond.columns:
        bond, sleeve, net = (float(x[ccy].iloc[0]) / 1e6 for x in (ov.bond, ov.sleeve, ov.net_forward))
        if abs(bond) < 1e-9 and abs(sleeve) < 1e-9:
            continue
        rows.append({
            'Currency': f'{ccy}/CNY', 'Bond FX (CNY m)': round(bond, 1), 'FX sleeve (CNY m)': round(sleeve, 1),
            'Net forward (CNY m)': round(net, 1),
            'Direction': 'SELL FWD' if net < -1e-9 else ('BUY FWD' if net > 1e-9 else 'FLAT'),
        })
    return rows
