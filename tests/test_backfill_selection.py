from curves.backtest.selection import expand_backfill_btypes


def test_obond_expands_to_underlying_bond_types():
    assert expand_backfill_btypes("OBond") == ["LBond", "BBond", "GBond", "MNote"]


def test_plain_btypes_remain_unchanged():
    assert expand_backfill_btypes("TBond") == ["TBond"]
