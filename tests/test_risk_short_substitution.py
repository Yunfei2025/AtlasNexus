from web.tabs.risk import short_substitution as ss

_INFO = {
    '260015.IB': ('CGB', 4.75), '260016.IB': ('CGB', 9.8), '2600006.IB': ('CGB', 29.8),
    '2600005.IB': ('CGB', 19.7), '260020.IB': ('CGB', 0.97),
    '260208.IB': ('CDB', 4.75), '240203.IB': ('CDB', 2.3), '999999.IB': ('Credit', 3.0),
}
_OTR = {'5Y': '260015.IB', '10Y': '260016.IB', '30Y': '2600006.IB'}


def _run(net_pos, monkeypatch):
    monkeypatch.setattr(ss, '_load_bond_info', lambda: _INFO)
    return {r['code']: r for r in ss.build_short_substitutions(net_pos, _OTR)}


def test_allowed_cgb_shorts_swaps_and_longs_are_left_alone(monkeypatch):
    rows = _run({
        '260015.IB': {'Beta': 100.0, 'Alpha': -900.0},     # CGB 5Y short: allowed
        '260016.IB': {'Beta': 0.0, 'Alpha': -500.0},       # CGB 10Y short: allowed
        'FR007S1Y.IR': {'Beta': 0.0, 'Alpha': -9000.0},    # payer swap: allowed
        '260208.IB': {'Beta': 0.0, 'Alpha': 400.0},        # CDB long
    }, monkeypatch)
    assert rows == {}


def test_beta_long_nets_before_substitution(monkeypatch):
    rows = _run({'2600005.IB': {'Beta': 470.0, 'Alpha': -1310.0}}, monkeypatch)
    assert rows['2600005.IB']['net_mm'] == -840.0


def test_long_end_goes_to_cgb_short_end_to_fr007_dv01_matched(monkeypatch):
    rows = _run({
        '260208.IB': {'Beta': 0.0, 'Alpha': -6000.0},      # CDB 5Y  -> CGB 5Y
        '2600005.IB': {'Beta': 0.0, 'Alpha': -1000.0},     # CGB 20Y -> CGB 10Y + 30Y
        '240203.IB': {'Beta': 0.0, 'Alpha': -5000.0},      # CDB 2Y  -> pay FR007 2Y
    }, monkeypatch)
    assert [s['code'] for s in rows['260208.IB']['substitutes']] == ['260015.IB']
    assert [s['code'] for s in rows['2600005.IB']['substitutes']] == ['260016.IB', '2600006.IB']
    assert [s['code'] for s in rows['240203.IB']['substitutes']] == ['FR007S2Y.IR']
    for r in rows.values():
        assert abs(sum(s['dv01'] for s in r['substitutes']) - r['dv01']) < 1e-9


def test_credit_short_is_flagged_without_substitute(monkeypatch):
    rows = _run({'999999.IB': {'Beta': 0.0, 'Alpha': -100.0},
                 'LGB1Y': {'Beta': -50.0, 'Alpha': 0.0}}, monkeypatch)
    assert rows['999999.IB']['substitutes'] == [] and rows['LGB1Y']['substitutes'] == []
