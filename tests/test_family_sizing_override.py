# -*- coding: utf-8 -*-
"""Family-level sizing overrides (FXDL / CMDL -> discrete, 2026-11-19)."""
from multiasset.factor_model import factor_sizing_override


def test_fx_and_commodity_families_use_discrete():
    for f in ('FXDL.USDCNY', 'FXDL.GBPUSD', 'CMDL.AU', 'CMDL.EC', 'CMDL.NEWCONTRACT'):
        assert factor_sizing_override(f) == {'sizing_mode': 'discrete'}


def test_other_families_unaffected_and_exact_codes_still_work():
    assert factor_sizing_override('IRDL.CN') == {}
    assert factor_sizing_override('CRDL.NCD') == {}
    assert factor_sizing_override('EQDL.IF') == {}
    assert factor_sizing_override('IRSL.US') == {'sizing_mode': 'discrete'}
