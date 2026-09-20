# -*- coding: utf-8 -*-
"""Carry/accrual regression tests.

Regression tests for a defect where yield-factor returns were price-only
(``-D*Δy/100``), omitting the coupon/carry accrual a bond actually earns
while held. For a Level-type factor (equal-weighted portfolio of outright
tenor yields — IRDL/SPDL/CRDL) this understated the real total return by
roughly the average yield level itself: on IRDL.CN, ~2.8 percentage points
annualised (0.17% price-only vs ~3.0% GROSS price+carry against a ~2.8%
average yield). Slope/Curvature factors (IRSL/IRCV/SPSL/SPCV/CRSL/CRCV) are
long-short, net-zero-notional contrasts across tenors, where a level-based
carry has no economic meaning — their carry is intentionally left at zero
pending a leg-difference formula (see _yield_carry docstring).

IRDL specifically is further netted against its country's funding/repo
rate (FR007 for CN, etc. — see _IRDL_FUNDING_RATE_MACRO_COL): holding a
government bond is a funded position, and gross yield/252 alone produced
an unrealistic ~9.3 Sharpe once carry (a near-deterministic daily addition)
dominated the return series' volatility. Net-of-funding carry on IRDL.CN
brought full-history Sharpe down to ~2.5 — still elevated versus a typical
strategy Sharpe, but no longer absurd. SPDL/CRDL (already credit/swap
spread levels, not raw yields) are NOT netted against a funding rate —
see module-level comment in factor_backtest.py for why that's a separate,
unresolved question rather than assumed.

Tests use SPDL/CRDL (gross carry, no funding-rate lookup) to isolate the
basic carry formula deterministically, and inject a fake funding-rate
series via monkeypatch to test the net-of-funding path without depending
on the real macro-px.pkl file's contents.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from multiasset import factor_backtest
from multiasset.factor_backtest import (
    _is_level_factor,
    _yield_carry,
    _yield_to_return,
    factor_level_to_price_return,
)


def _rising_yield_series(n: int = 300, start: float = 3.0, step: float = 0.0) -> pd.Series:
    """A yield level series (percent) with a constant level and zero drift,
    so price return is exactly zero and any nonzero return must be carry."""
    idx = pd.bdate_range('2020-01-01', periods=n)
    return pd.Series(start + step * np.arange(n), index=idx)


@pytest.fixture(autouse=True)
def _no_real_funding_rate(monkeypatch):
    """Prevent IRDL tests from silently hitting the real macro-px.pkl file —
    tests that specifically want a funding rate inject their own via
    _load_funding_rate monkeypatching (see test_irdl_carry_nets_against_funding_rate).
    Also clears the module-level cache so injected fakes never leak between tests.
    """
    factor_backtest._funding_rate_cache.clear()
    monkeypatch.setattr(factor_backtest, '_load_funding_rate', lambda country: None)
    yield
    factor_backtest._funding_rate_cache.clear()


def test_level_factor_gross_carry_is_positive_and_proportional_to_yield():
    """A flat (zero price-return) Level factor must still earn ~ yield/252/day.
    Uses SPDL (no funding-rate netting) to isolate the base formula."""
    level = _rising_yield_series(step=0.0)  # perfectly flat: Δy = 0 everywhere
    carry = _yield_carry(level, 'SPDL.CDB')

    assert (carry.dropna() > 0).all(), "a positive yield level must produce positive carry"
    expected_daily = level.iloc[0] / 100.0 / 252.0
    assert np.isclose(carry.dropna().iloc[-1], expected_daily, rtol=1e-9)


def test_irdl_without_funding_rate_falls_back_to_gross_carry():
    """With no funding-rate series available (the default in this test file
    via the autouse fixture), IRDL must still get carry — gross, not none."""
    level = _rising_yield_series(step=0.0)
    carry = _yield_carry(level, 'IRDL.CN')
    expected_daily = level.iloc[0] / 100.0 / 252.0
    assert np.isclose(carry.dropna().iloc[-1], expected_daily, rtol=1e-9)


def test_irdl_carry_nets_against_funding_rate(monkeypatch):
    """IRDL carry must be (yield - funding_rate)/252, not gross yield/252,
    when a funding-rate series is available."""
    level = _rising_yield_series(n=100, start=3.0, step=0.0)  # flat 3.0% yield
    funding = pd.Series(1.0, index=level.index)  # flat 1.0% funding rate

    monkeypatch.setattr(factor_backtest, '_load_funding_rate', lambda country: funding)
    factor_backtest._funding_rate_cache.clear()

    carry = _yield_carry(level, 'IRDL.CN')
    expected_net_daily = (3.0 - 1.0) / 100.0 / 252.0
    assert np.isclose(carry.dropna().iloc[-1], expected_net_daily, rtol=1e-9)

    gross_daily = 3.0 / 100.0 / 252.0
    assert carry.dropna().iloc[-1] < gross_daily, "netting funding cost must reduce carry vs gross"


def test_irdl_net_carry_can_go_negative_when_funding_exceeds_yield(monkeypatch):
    """A funding squeeze (repo rate > bond yield) must show as negative carry,
    not be floored at zero — that's a real, meaningful cost of holding a
    funded position, not a data error."""
    level = _rising_yield_series(n=50, start=2.0, step=0.0)
    funding = pd.Series(5.0, index=level.index)  # funding cost exceeds bond yield

    monkeypatch.setattr(factor_backtest, '_load_funding_rate', lambda country: funding)
    factor_backtest._funding_rate_cache.clear()

    carry = _yield_carry(level, 'IRDL.CN')
    assert (carry.dropna() < 0).all(), "funding cost above yield must produce negative carry"


def test_irdl_falls_back_to_gross_before_funding_series_inception(monkeypatch):
    """Dates before the funding-rate series' own history starts (e.g. FR007
    begins partway through IRDL.CN's history) must use gross carry, not NaN."""
    level = _rising_yield_series(n=100, start=3.0, step=0.0)
    # Funding rate only exists for the second half of the level series.
    funding = pd.Series(1.0, index=level.index[50:])

    monkeypatch.setattr(factor_backtest, '_load_funding_rate', lambda country: funding)
    factor_backtest._funding_rate_cache.clear()

    carry = _yield_carry(level, 'IRDL.CN')
    gross_daily = 3.0 / 100.0 / 252.0
    net_daily = (3.0 - 1.0) / 100.0 / 252.0

    assert not carry.iloc[1:49].isna().any(), "pre-inception dates must not be NaN"
    assert np.allclose(carry.iloc[1:49], gross_daily, rtol=1e-9), "pre-inception must be gross"
    assert np.isclose(carry.iloc[-1], net_daily, rtol=1e-9), "post-inception must be net"


def test_slope_and_curvature_factors_have_zero_carry():
    """Long-short (net-zero-notional) factors get no level-based carry —
    the level has no accrual interpretation for them (see module docstring
    and _yield_carry's own docstring)."""
    level = _rising_yield_series()
    for code in ('IRSL.CN', 'IRCV.CN', 'SPSL.CDB', 'SPCV.CDB', 'CRSL.LGB', 'CRCV.LGB'):
        carry = _yield_carry(level, code)
        assert (carry.fillna(0) == 0).all(), f"{code} should have zero carry, got nonzero values"


def test_is_level_factor_classification():
    assert _is_level_factor('IRDL.CN')
    assert _is_level_factor('SPDL.CDB')
    assert _is_level_factor('CRDL.LGB')
    assert not _is_level_factor('IRSL.CN')
    assert not _is_level_factor('IRCV.CN')
    assert not _is_level_factor('FXDL.USDCNY')  # not a yield factor at all


def test_yield_to_return_without_factor_code_is_price_only_backward_compat():
    """Omitting factor_code must reproduce the exact pre-fix (price-only)
    behaviour, so any caller not yet updated to pass it keeps working."""
    level = _rising_yield_series(step=0.01)  # yields drifting up
    old_style = _yield_to_return(level, mod_dur=1.0)
    new_style_no_code = _yield_to_return(level, mod_dur=1.0, factor_code=None)
    pd.testing.assert_series_equal(old_style, new_style_no_code)


def test_yield_to_return_with_level_factor_code_adds_carry():
    level = _rising_yield_series(step=0.0)  # flat: isolates carry from price effect
    price_only = _yield_to_return(level, mod_dur=1.0)  # no factor_code
    with_carry = _yield_to_return(level, mod_dur=1.0, factor_code='SPDL.CDB')

    diff = (with_carry - price_only).dropna()
    assert (diff > 0).all(), "adding carry to a flat-yield series should strictly increase return"
    expected_daily = level.iloc[0] / 100.0 / 252.0
    assert np.isclose(diff.iloc[-1], expected_daily, rtol=1e-9)


def test_yield_to_return_and_factor_level_to_price_return_agree():
    """The two independent implementations of yield-factor returns
    (_yield_to_return and factor_level_to_price_return) must produce
    identical total returns for the same Level factor — they were
    historically two separate copies of the same price-only formula and
    both needed the carry term added consistently."""
    level = _rising_yield_series(step=0.01)
    r1 = _yield_to_return(level, mod_dur=1.0, factor_code='SPDL.CDB')
    r2 = factor_level_to_price_return(level, 'SPDL.CDB', output_in_percent=False)
    pd.testing.assert_series_equal(r1, r2, check_names=False)
