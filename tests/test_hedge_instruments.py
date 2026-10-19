# -*- coding: utf-8 -*-
"""Instrument registry for the beta-book duration overlay
(multiasset.book.hedge_instruments)."""

import os

import pandas as pd
import pytest

from multiasset.book import hedge_instruments as hi


def test_china_uses_the_overlay_and_foreign_markets_short_the_bond():
    assert hi.hedge_route('CN') == 'overlay'
    for c in ('US', 'DE', 'JP', 'UK'):
        assert hi.hedge_route(c) == 'short_bond'
    assert all(i.market == 'CN' for i in hi.REGISTRY.values())


def test_five_year_point_is_a_future_not_a_swap():
    names = [c.name for c in hi.candidates('2024-06-03')]
    assert 'TF' in names and not any(n.endswith('5Y') for n in hi.REGISTRY)
    assert hi.split_dv01(5.0, '2024-06-03') == {'TF': 1.0}


def test_gap_tenors_use_swaps_only_when_allowed():
    assert hi.split_dv01(1.0, '2024-06-03') == {'SWAP1Y': 1.0}
    assert hi.split_dv01(3.0, '2024-06-03') == {'SWAP3Y': 1.0}
    # without swaps, 1Y falls to the shortest future and 3Y shares TS/TF by distance
    assert hi.split_dv01(1.0, '2024-06-03', allow_swaps=False) == {'TS': 1.0}
    w = hi.split_dv01(3.0, '2024-06-03', allow_swaps=False)
    assert w == pytest.approx({'TS': 2 / 3, 'TF': 1 / 3})


def test_off_tenor_dv01_is_split_between_neighbours_and_sums_to_one():
    w = hi.split_dv01(7.0, '2024-06-03')
    assert w == pytest.approx({'TF': 0.6, 'T': 0.4})
    assert sum(hi.split_dv01(20.0, '2024-06-03').values()) == pytest.approx(1.0)
    assert hi.split_dv01(40.0, '2024-06-03') == {'TL': 1.0}


def test_availability_respects_data_start_dates():
    # TS starts 2018-08, TL 2023-04, swaps 2022-02: earlier dates fall back to what exists
    assert [c.name for c in hi.candidates('2016-01-04')] == ['TF', 'T']
    assert hi.split_dv01(2.0, '2016-01-04') == {'TF': 1.0}
    assert hi.split_dv01(30.0, '2020-01-02') == {'T': 1.0}
    assert 'TL' in [c.name for c in hi.candidates('2023-05-01')]


def test_duration_proxy_and_contract_sizing():
    # annuity formula: 5Y at 2.5% -> about 4.6
    assert hi.mod_duration(2.5, 5.0) == pytest.approx(4.6, abs=0.1)
    tf = hi.REGISTRY['TF']
    notional = hi.notional_for_dv01(tf, 1_000_000.0, 2.5)          # 1m CNY per bp
    assert notional == pytest.approx(1_000_000.0 / (hi.mod_duration(2.5, 5.0) * 1e-4))
    n = hi.contracts_for_dv01(tf, 1_000_000.0, 2.5)
    assert n == round(notional / 1_000_000.0)
    # short DV01 -> negative contracts; TS contracts are 2m face
    assert hi.contracts_for_dv01(tf, -1_000_000.0, 2.5) == -n
    ts = hi.REGISTRY['TS']
    assert hi.contracts_for_dv01(ts, 1_000_000.0, 2.0) == round(hi.notional_for_dv01(ts, 1e6, 2.0) / 2_000_000.0)
    with pytest.raises(ValueError):
        hi.contracts_for_dv01(hi.REGISTRY['SWAP1Y'], 1e6, 2.0)


def test_margin_counts_inside_the_utilisation_cap():
    capital = 10e9
    assert hi.margin_cny(-3e9) == pytest.approx(90e6)                     # 3% of |notional|
    # 95% cash gross + 3bn of futures notional -> 0.95 + 0.009 = 96% used
    assert hi.capital_usage(0.95 * capital, 3e9, capital) == pytest.approx(0.959)
    # the cash headroom shrinks by exactly the margin
    assert hi.cash_headroom(3e9, capital) == pytest.approx(0.95 * capital - 90e6)


def test_data_keys_exist_in_the_repo_artifacts():
    from settings.paths import DIR_INPUT
    fut_path = os.path.join(str(DIR_INPUT), 'futures-dailyK_con.pkl')
    px_path = os.path.join(str(DIR_INPUT), 'database-px.pkl')
    if not (os.path.exists(fut_path) and os.path.exists(px_path)):
        pytest.skip('market data artifacts not present')
    fut = pd.read_pickle(fut_path)
    irs = pd.read_pickle(px_path)['IRS']
    for inst in hi.REGISTRY.values():
        if inst.is_future:
            assert inst.data_key in fut, inst.name
        else:
            assert inst.data_key in irs.columns, inst.name
