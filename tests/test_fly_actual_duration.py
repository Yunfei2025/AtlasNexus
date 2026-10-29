import pytest

from web.tabs.alpha.data import legs
from web.tabs.risk import helpers

# actual modified durations (years) of the OTR bonds in the 2026-10-29 book
_DUR = {'240203.IB': 2.2242, '260206.IB': 0.7620, '260208.IB': 4.5357,        # CDB 2Y / 1Y / 5Y
        '260015.IB': 4.5434, '260018.IB': 1.8474, '260016.IB': 8.9830,        # CGB 5Y / 2Y / 10Y
        '2600006.IB': 21.9540}


@pytest.fixture(autouse=True)
def _bond_durations(monkeypatch):
    monkeypatch.setattr(legs, '_bond_modified_durations', lambda: dict(_DUR))


def test_wings_each_take_half_the_belly_dv01_on_the_actual_bonds():
    legs3 = ('240203.IB', '260206.IB', '260208.IB')                              # CDB-1s2s5s: belly, short, long
    r2, r3 = legs.fly_leg_dv01_ratios('TenorSpread', 'CDB-1s2s5s', legs3)
    d1, d2, d3 = (_DUR[c] for c in legs3)
    assert r2 * d2 == pytest.approx(0.5 * d1, rel=1e-3)
    assert r3 * d3 == pytest.approx(0.5 * d1, rel=1e-3)
    assert 1.0 * d1 == pytest.approx(r2 * d2 + r3 * d3, rel=1e-3)               # belly DV01 fully hedged
    assert (r2, r3) != legs.fly_leg_dv01_ratios('TenorSpread', 'CDB-1s2s5s')    # differs from the nominal-tenor answer


def test_unknown_leg_falls_back_to_one_nominal_triple_not_a_mix():
    nominal = legs.fly_leg_dv01_ratios('TenorSpread', 'CGB-2s5s10s')
    assert legs.fly_leg_dv01_ratios('TenorSpread', 'CGB-2s5s10s', ('260015.IB', '260018.IB', '999999.IB')) == nominal
    assert legs.fly_leg_dv01_ratios('TenorSpread', 'CGB-2s5s10s', None) == nominal
    assert legs.fly_leg_durations('TenorSpread', 'CGB-2s5s10s', ('260015.IB', '260018.IB', '999999.IB')) == pytest.approx(
        (5 * 0.92, 2 * 0.92, 10 * 0.92))


def test_non_fly_ids_have_no_fly_ratios():
    assert legs.fly_leg_dv01_ratios('TenorSpread', 'CDB-2s5s', ('260208.IB', '240203.IB', '')) is None


def test_actual_duration_lookup_for_bonds_swaps_and_unknowns():
    assert legs.actual_leg_duration('2600006.IB') == pytest.approx(21.954)      # not 0.92 x 29.8y = 27.4
    assert legs.actual_leg_duration('FR007S5Y.IR') == pytest.approx(4.8084, abs=1e-3)
    assert legs.actual_leg_duration('NCD-1Y') is None and legs.actual_leg_duration('999999.IB') is None


def test_two_leg_bond_duration_and_ratio_use_the_actual_bond_duration():
    assert helpers._leg_duration_years('260015.IB', 'TenorSpread', 'CGB-2s5s', 0.0, {}) == pytest.approx(4.5434)
    ratio = helpers._leg_volume_ratio('260015.IB', '260018.IB', 'TenorSpread', 'CGB-2s5s', 0.0, {})
    assert ratio == pytest.approx(_DUR['260015.IB'] / _DUR['260018.IB'])        # DV01-neutral on the real bonds
