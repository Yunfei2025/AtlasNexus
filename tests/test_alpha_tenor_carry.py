# -*- coding: utf-8 -*-
"""Alpha book: funded, DV01-weighted package carry for CGB/CDB slopes and flies, and the negative-carry
entry gate. The alpha book is TRS-financed, so every leg of a spread costs funding on its notional; the old
carry was the raw yield spread x 0.25 (equal notionals, no funding)."""

import numpy as np
import pandas as pd
import pytest

from curves.calibration.tenor_carry import (
    funded_carry_frames, funded_package_carry, modified_duration, package_notionals, parse_curve_trade,
)

IDX = pd.bdate_range('2024-01-02', periods=5)


def flat(v):
    return pd.Series(float(v), index=IDX)


def test_parse_curve_trade_only_accepts_cgb_cdb_slopes_and_flies():
    assert parse_curve_trade('CGB-5s10s') == ('CGB', [5, 10])
    assert parse_curve_trade('cdb-2s5s10s') == ('CDB', [2, 5, 10])
    for other in ('CDBCGB-5y', 'MTNCGB-3y', 'NCDRepo7d-1y', 'Repo7d-1y5y', 'CGB-5s', 'LGBCGB-30y'):
        assert parse_curve_trade(other) is None


@pytest.mark.parametrize('tenors,ys', [([1, 2], [1.2, 1.4]), ([2, 10], [1.3, 1.9]), ([2, 5, 10], [1.3, 1.5, 1.9]),
                                       ([10, 20, 30], [1.9, 2.1, 2.2])])
def test_package_is_dv01_neutral(tenors, ys):
    h = package_notionals([flat(y) for y in ys], tenors)
    dv01 = sum(hi * modified_duration(flat(y), n) for hi, y, n in zip(h, ys, tenors))
    assert dv01.abs().max() < 1e-12


def test_slope_carry_matches_the_hand_formula_and_funding_matters():
    # CGB-1s2s BUY = long 1Y, short 2Y at DV01 neutrality: carry = (y1 - f) D2/D1 - (y2 - f)
    y1, y2, f = 1.17, 1.23, 1.40
    buy, sell = funded_package_carry([flat(y1), flat(y2)], [1, 2], flat(f))
    d1, d2 = modified_duration(y1, 1), modified_duration(y2, 2)
    expected = (y1 - f) * d2 / d1 - (y2 - f)
    assert buy.iloc[0] == pytest.approx(expected)
    assert expected < 0                       # long a 1Y below funding, 2x the notional of the short leg
    raw = y2 - y1                             # the old equal-notional BUY carry is -(y2-y1) = -0.06: wrong size
    assert abs(buy.iloc[0] - (-raw)) > 0.2
    assert sell.iloc[0] == pytest.approx(-buy.iloc[0])      # no TRS spread: SELL is the mirror image


def test_fly_carry_matches_the_hand_formula():
    y = [1.30, 1.45, 1.90]
    f = 1.40
    buy, _ = funded_package_carry([flat(v) for v in y], [2, 5, 10], flat(f))
    d = [modified_duration(v, n) for v, n in zip(y, [2, 5, 10])]
    expected = 2 * (y[1] - f) - (y[0] - f) * d[1] / d[0] - (y[2] - f) * d[1] / d[2]
    assert buy.iloc[0] == pytest.approx(expected)


def test_funding_cancels_in_a_package_only_when_the_dv01_weights_sum_to_the_reference():
    # equal yields -> carry is -(f)(sum of signed notionals); with f == y on every leg carry is 0
    buy, sell = funded_package_carry([flat(1.5), flat(1.5)], [1, 2], flat(1.5))
    assert buy.iloc[0] == pytest.approx(0.0) and sell.iloc[0] == pytest.approx(0.0)


def test_trs_spread_is_a_cost_in_both_directions_on_gross_notional():
    ys = [flat(1.2), flat(1.4), flat(1.9)]
    b0, s0 = funded_package_carry(ys, [2, 5, 10], flat(1.4), 0.0)
    b1, s1 = funded_package_carry(ys, [2, 5, 10], flat(1.4), 20.0)
    gross = sum(x.abs() for x in package_notionals(ys, [2, 5, 10]))
    assert (b0 - b1).iloc[0] == pytest.approx(0.20 * gross.iloc[0])
    assert (s0 - s1).iloc[0] == pytest.approx(0.20 * gross.iloc[0])        # SELL pays it too
    assert s1.iloc[0] != pytest.approx(-b1.iloc[0])                         # so one BUY series cannot carry it


def test_frames_skip_cross_curve_names_and_missing_legs():
    curves = {'CGB': {1: flat(1.2), 2: flat(1.3), 5: flat(1.4)}, 'CDB': {1: flat(1.3)}}
    buy, sell = funded_carry_frames(curves, ['CGB-1s2s', 'CGB-2s5s', 'CDB-1s2s', 'CDBCGB-5y', 'CGB-5s10s'],
                                    IDX, flat(1.4))
    assert list(buy.columns) == ['CGB-1s2s', 'CGB-2s5s']                   # CDB 2Y / CGB 10Y missing, cross-curve out
    assert list(sell.columns) == list(buy.columns)
    d1, d2 = modified_duration(1.2, 1), modified_duration(1.3, 2)
    assert buy['CGB-1s2s'].iloc[0] == pytest.approx(((1.2 - 1.4) * d2 / d1 - (1.3 - 1.4)) * 0.25)   # 3m = annual/4


# --- the entry gate --------------------------------------------------------------------------------

def _mr_series(n=700, seed=11):
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = 0.9 * x[i - 1] + rng.normal(0, 0.03)
    idx = pd.bdate_range('2021-01-04', periods=n)
    return pd.Series(x + 0.5, index=idx)


def _run(carry, gate, spread_type='TenorSpread'):
    from web.tabs.alpha.backtest.engine_monthly import run_monthly_style_backtest
    ts = _mr_series()
    styles = {p: 'mr' for p in pd.period_range(ts.index[0], ts.index[-1], freq='M')}
    cr = pd.Series(float(carry), index=ts.index)
    return run_monthly_style_backtest(ts, styles, entry_z=2.0, exit_z=0.5, stop_z=3.0, min_hold=3,
                                      carry_roll_ts=cr, spread_type=spread_type, carry_gate=gate)


def _directions(res):
    df = res.get('trades_df')
    return set() if df is None or df.empty else set(df['direction'])


def test_gate_blocks_entries_against_negative_carry_and_only_those():
    ungated = _directions(_run(-0.05, False))
    assert 'LONG' in ungated and 'SHORT' in ungated                 # the series trades both ways without the gate
    neg = _directions(_run(-0.05, True))                             # LONG carry is negative: long entries blocked
    assert 'LONG' not in neg and 'SHORT' in neg
    pos = _directions(_run(+0.05, True))                             # LONG earns carry, SHORT pays: shorts blocked
    assert 'SHORT' not in pos and 'LONG' in pos
    assert _directions(_run(0.0, True)) == ungated                   # zero carry is not negative


def test_gate_follows_the_setting_for_tenorspread_only(monkeypatch):
    import settings.general as G
    monkeypatch.setattr(G, 'ALPHA_CARRY_GATE_ENABLED', True)
    on = _directions(_run(-0.05, None, 'TenorSpread'))
    other = _directions(_run(-0.05, None, 'SwapSpread'))              # carry of other types is not funded: ungated
    assert 'LONG' not in on
    assert 'LONG' in other
    monkeypatch.setattr(G, 'ALPHA_CARRY_GATE_ENABLED', False)
    assert 'LONG' in _directions(_run(-0.05, None, 'TenorSpread'))   # default off


def test_default_settings_ship_the_gate_off_and_the_trs_spread_at_zero():
    import settings.general as G
    assert G.ALPHA_CARRY_GATE_ENABLED is False
    assert G.ALPHA_TRS_SPREAD_BP == 0.0
