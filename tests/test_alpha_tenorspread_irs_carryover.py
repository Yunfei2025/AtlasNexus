"""Repo7d-1y5y, Shi3M-1y5y, Repo7d-3m1y, Basis-1y, Basis-5y are carried over
from SwapSpread into TenorSpread ("Curve & Cross-Asset Spreads") as a
deliberate duplication, per user request, so the core portfolio category can
include them directly. See curves.generators.stat.compute_tenor_spreads.
"""

from web.tabs.alpha.data.duration import _get_duration_mult, _get_borrow_cost_annual_bp
from web.tabs.alpha.data.legs import resolve_legs

_EMPTY_LD = {
    'otr_cgb': {}, 'otr_cdb': {}, 'nb': {}, 'tb_stat': None,
    'futs_def': __import__('pandas').DataFrame(), 'fs_irs': {},
}


def test_resolve_legs_for_carried_over_instruments():
    assert resolve_legs('TenorSpread', 'Repo7d-1y5y', ld=_EMPTY_LD) == ('FR007S5Y.IR', 'FR007S1Y.IR')
    assert resolve_legs('TenorSpread', 'Shi3M-1y5y', ld=_EMPTY_LD) == ('SHI3MS5Y.IR', 'SHI3MS1Y.IR')
    assert resolve_legs('TenorSpread', 'Repo7d-3m1y', ld=_EMPTY_LD) == ('FR007S1Y.IR', 'FR007S3M.IR')
    assert resolve_legs('TenorSpread', 'Basis-1y', ld=_EMPTY_LD) == ('SHI3MS1Y.IR', 'FR007S1Y.IR')
    assert resolve_legs('TenorSpread', 'Basis-5y', ld=_EMPTY_LD) == ('SHI3MS5Y.IR', 'FR007S5Y.IR')


def test_resolve_legs_existing_tenor_spread_ids_unaffected():
    # 'CGB-1s2s' must still take the CGB slope path (OTR bond lookup), not the
    # new REPO7D-/SHI3M-/BASIS- branch -- with an empty OTR table the slope
    # path resolves to ('', '') rather than an IRS code like 'FR007S...'.
    leg1, leg2 = resolve_legs('TenorSpread', 'CGB-1s2s', ld=_EMPTY_LD)
    assert leg1 == '' and leg2 == ''
    assert not leg1.upper().startswith('FR007S') and not leg2.upper().startswith('FR007S')


def test_duration_uses_longer_leg_for_pair_ids():
    # Pair: longer/second leg drives duration (DV01-hedged convention).
    d_15 = _get_duration_mult('Repo7d-1y5y', 'TenorSpread')
    d_31 = _get_duration_mult('Repo7d-3m1y', 'TenorSpread')
    assert d_15 > 3.0  # ~5y leg
    assert 0.5 < d_31 < 1.5  # ~1y leg (longer of 3m/1y)


def test_duration_single_tenor_basis_uses_its_own_tenor():
    d1 = _get_duration_mult('Basis-1y', 'TenorSpread')
    d5 = _get_duration_mult('Basis-5y', 'TenorSpread')
    assert 0.5 < d1 < 1.5
    assert 3.5 < d5 < 6.0
    assert d5 > d1


def test_duration_existing_cgb_slope_ids_unaffected():
    # CGB-5s10s: shorter leg is NOT used for duration (second/longer leg is).
    d = _get_duration_mult('CGB-5s10s', 'TenorSpread')
    assert 8.0 < d < 10.5  # ~10y duration, unchanged by the [mMyY] branch edit


def test_borrow_cost_zero_for_irs_carryover_instruments():
    # No bond leg -> no repo borrow cost, matching SwapSpread's own (0, 0).
    for inst in ('Repo7d-1y5y', 'Shi3M-1y5y', 'Repo7d-3m1y', 'Basis-1y', 'Basis-5y'):
        assert _get_borrow_cost_annual_bp('TenorSpread', inst) == (0.0, 0.0)


def test_borrow_cost_existing_bond_curve_ids_unaffected():
    assert _get_borrow_cost_annual_bp('TenorSpread', 'CDBCGB-5y') == (10.0, 10.0)
    assert _get_borrow_cost_annual_bp('TenorSpread', 'LGBCGB-10y') == (40.0, 40.0)
    assert _get_borrow_cost_annual_bp('TenorSpread', 'CGB-5s10s') == (10.0, 40.0)
