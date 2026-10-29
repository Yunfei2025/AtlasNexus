import pytest

from web.tabs.alpha.callbacks.portfolio import netted_trs_margin_by_leg
from web.tabs.risk.charts import build_kpi_cards, build_kpi_strip

BOND, SWAP = 0.05, 0.03


def test_bond_legs_net_across_trades_and_margin_is_rate_times_net_exposure():
    trades = [
        [('240203.IB', -1000.0), ('260206.IB', 1500.0), ('', 0.0)],      # trade A
        [('240203.IB', 400.0), ('260208.IB', -300.0), ('', 0.0)],         # trade B shares 240203
    ]
    out = netted_trs_margin_by_leg(trades, BOND, SWAP)
    assert out['240203.IB']['exposure'] == pytest.approx(-600.0)         # offsets across trades
    assert out['240203.IB']['margin'] == pytest.approx(600.0 * BOND)     # not 1400 * 5%
    assert out['260206.IB']['margin'] == pytest.approx(1500.0 * BOND)
    assert out['260208.IB']['exposure'] < 0 < out['260206.IB']['exposure']


def test_swap_legs_net_by_dv01_with_a_stress_floor_and_no_bond_rate():
    out = netted_trs_margin_by_leg([[('FR007S5Y.IR', 1000.0)], [('FR007S5Y.IR', -400.0)]], BOND, SWAP)
    leg = out['FR007S5Y.IR']
    assert leg['kind'] == 'swap' and leg['exposure'] == pytest.approx(600.0)
    assert 0 < leg['margin'] < 600.0 * BOND            # DV01-based charge, far below the 5% bond haircut


def test_unrecognised_legs_take_the_flat_swap_rate_and_are_not_netted():
    out = netted_trs_margin_by_leg([[('XYZ', 100.0)], [('XYZ', -100.0)], [('', 250.0), ('', 0.0)]], BOND, SWAP)
    assert out['XYZ']['kind'] == 'unresolved' and out['XYZ']['margin'] == pytest.approx(200.0 * SWAP)
    assert out['(unresolved trade)']['margin'] == pytest.approx(250.0 * SWAP)   # leg-1 floor for a trade with no legs


def test_kpi_long_short_use_alpha_margin_not_alpha_notional():
    net_pos = {
        'NCD1Y': {'Beta': 12980.0, 'Alpha': 8390.0},        # alpha notional must not leak into capital
        '240203.IB': {'Beta': 0.0, 'Alpha': -5670.0},
        '260015.IB': {'Beta': 950.0, 'Alpha': -1880.0},
    }
    alpha_margin = {
        'NCD1Y': {'exposure': 8390.0, 'margin': 8.0},
        '240203.IB': {'exposure': -5670.0, 'margin': 283.5},
        '260015.IB': {'exposure': -1880.0, 'margin': 94.0},
    }
    k = build_kpi_cards(net_pos, {'5Y': {'Bonds': 0.0}}, ['5Y'], alpha_margin=alpha_margin)
    assert k['beta_long'] == pytest.approx(12980.0 + 950.0)
    assert k['alpha_long'] == pytest.approx(8.0) and k['alpha_short'] == pytest.approx(283.5 + 94.0)
    assert k['long'] == pytest.approx(13938.0) and k['short'] == pytest.approx(377.5)
    assert k['net'] == pytest.approx(k['long'] - k['short'])
    strip = str(build_kpi_strip(k))
    assert 'Beta 13.9k + Alpha margin 0.01k' in strip and 'capital basis' in strip


def test_kpi_without_alpha_margin_keeps_the_notional_basis():
    net_pos = {'X': {'Beta': 100.0, 'Alpha': -30.0}, 'Y': {'Beta': 0.0, 'Alpha': -50.0}}
    k = build_kpi_cards(net_pos, {'5Y': {'Bonds': 0.0}}, ['5Y'])
    assert (k['long'], k['short']) == (70.0, 50.0) and 'alpha_long' not in k
