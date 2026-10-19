# -*- coding: utf-8 -*-
"""FX overlay for foreign bonds (multiasset.book.fx): embedded currency, the
hedge on it, and the ticket netted against the FX sleeve."""

import pandas as pd
import pytest

from multiasset.book.fx import fx_overlay
from multiasset.book.pnl import BookPnL


def _idx(n=3):
    return pd.bdate_range('2024-01-01', periods=n)


def test_hedge_nets_bond_fx_against_sleeve():
    idx = _idx()
    notional = pd.DataFrame({'US10Y': 100.0, 'CN10Y': 500.0, 'USDCNY': 30.0}, index=idx)
    ov = fx_overlay(notional, {'US10Y': 'US', 'CN10Y': 'CN', 'USDCNY': ''})

    assert ov.bond['USD'].iloc[0] == 100.0           # CN bond carries no foreign ccy
    assert ov.hedge['USD'].iloc[0] == -100.0         # sell USD forward on the bond
    assert ov.net_forward['USD'].iloc[0] == -70.0    # sleeve +30 netted: sell only 70
    assert ov.net_exposure['USD'].iloc[0] == 30.0    # FX view comes only from the sleeve


def test_cross_sleeve_spans_two_currencies_and_german_bonds_are_eur():
    idx = _idx()
    notional = pd.DataFrame({'EU10Y': 50.0, 'EURUSD_SYN': 20.0}, index=idx)
    ov = fx_overlay(notional, {'EU10Y': 'DE', 'EURUSD_SYN': ''})

    assert ov.bond['EUR'].iloc[0] == 50.0
    assert ov.sleeve['EUR'].iloc[0] == 20.0 and ov.sleeve['USD'].iloc[0] == -20.0
    assert ov.net_exposure['EUR'].iloc[0] == 20.0


def test_short_bond_flips_hedge_sign():
    notional = pd.DataFrame({'JP10Y': -40.0}, index=_idx())
    ov = fx_overlay(notional, {'JP10Y': 'JP'})
    assert ov.hedge['JPY'].iloc[0] == 40.0 and ov.net_exposure['JPY'].iloc[0] == 0.0


def test_embedded_and_hedge_pnl_cancel_in_book_total():
    idx = _idx()
    z = pd.DataFrame(0.0, index=idx, columns=['US10Y'])
    emb = pd.DataFrame({'US10Y': [5.0, -2.0, 1.0]}, index=idx)
    pnl = BookPnL(capital_gain=z, carry=z, other=z, cash=pd.Series(0.0, index=idx),
                  fx_embedded=emb, fx_hedge=-emb)
    assert pnl.total.sum().sum() == 0.0
    assert (pnl.fx_embedded + pnl.fx_hedge).abs().sum().sum() == pytest.approx(0.0)


def test_hedge_ticket_nets_sleeve_and_skips_cn_only_books():
    from multiasset.book.fx import fx_hedge_ticket

    alloc = {'US10Y': 1e9, 'CN10Y': 3e9, 'USDCNY': 3e8, 'EURUSD_SYN': 1e8}
    uni = {'US10Y': 'US Gov Bond', 'CN10Y': 'China Gov Bond'}
    rows = {r['Currency']: r for r in fx_hedge_ticket(alloc, uni)}

    assert rows['USD/CNY']['Net forward (CNY m)'] == pytest.approx(-800.0)  # sleeve 300-100, bonds 1000
    assert rows['USD/CNY']['Direction'] == 'SELL FWD'
    assert rows['EUR/CNY']['Direction'] == 'BUY FWD'                          # pure cross view, no bonds
    assert fx_hedge_ticket({'CN10Y': 3e9}, {'CN10Y': 'China Gov Bond'}) == []
