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

Carry (``_yield_carry`` / ``_yield_to_return``) is always GROSS of
funding/repo cost — funding is never netted into the return/P&L series,
including for IRDL. Holding a government bond is a funded position, so
IRDL's Sharpe should still reflect the cost of that leverage; that
deduction is instead applied to ``strategy_returns`` as a daily,
position-scaled cost — see ``funding_cost_series()`` /
``_apply_funding_cost()`` — charged only on the days, and to the extent,
the position actually held duration exposure. A flat annualised deduction
regardless of position size was tried first and rejected: it overcharged
a lightly-positioned strategy and, because strategy-return vol scales down
with position size while a flat deduction doesn't, could swing Sharpe by
many points off a tiny vol denominator. SPDL/CRDL (already credit/swap
spread levels, not raw yields) get no funding-rate deduction anywhere —
see module-level comment in factor_backtest.py for why that's a separate,
unresolved question rather than assumed.

Tests use SPDL/CRDL (gross carry, no funding-rate lookup) to isolate the
basic carry formula deterministically, and inject a fake funding-rate
series via monkeypatch to test funding_cost_series() without depending on
the real macro-px.pkl file's contents.
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
    funding_cost_series,
    _apply_funding_cost,
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


def test_irdl_carry_is_gross_with_no_funding_rate_available():
    """With no funding-rate series available (the default in this test file
    via the autouse fixture), IRDL must still get carry — gross, as always."""
    level = _rising_yield_series(step=0.0)
    carry = _yield_carry(level, 'IRDL.CN')
    expected_daily = level.iloc[0] / 100.0 / 252.0
    assert np.isclose(carry.dropna().iloc[-1], expected_daily, rtol=1e-9)


def test_irdl_carry_is_gross_even_with_a_funding_rate_available(monkeypatch):
    """IRDL carry must stay gross yield/252 — never netted against the
    funding rate — even when a funding-rate series is available. Funding
    cost is deducted from strategy_returns, not inside carry/returns."""
    level = _rising_yield_series(n=100, start=3.0, step=0.0)  # flat 3.0% yield
    funding = pd.Series(1.0, index=level.index)  # flat 1.0% funding rate

    monkeypatch.setattr(factor_backtest, '_load_funding_rate', lambda country: funding)
    factor_backtest._funding_rate_cache.clear()

    carry = _yield_carry(level, 'IRDL.CN')
    gross_daily = 3.0 / 100.0 / 252.0
    assert np.isclose(carry.dropna().iloc[-1], gross_daily, rtol=1e-9)


def test_funding_cost_series_scales_with_position(monkeypatch):
    """funding_cost_series() must charge position_{t-1} * funding_rate_{t-1}/252,
    not a flat rate regardless of position size — a half-sized position
    should be charged half the cost of a full position."""
    level = _rising_yield_series(n=100, start=3.0, step=0.0)
    funding = pd.Series(1.0, index=level.index)  # flat 1.0% funding rate

    monkeypatch.setattr(factor_backtest, '_load_funding_rate', lambda country: funding)
    factor_backtest._funding_rate_cache.clear()

    full_position = pd.Series(1.0, index=level.index)
    half_position = pd.Series(0.5, index=level.index)

    cost_full = funding_cost_series(full_position, level, 'IRDL.CN')
    cost_half = funding_cost_series(half_position, level, 'IRDL.CN')

    expected_full_daily = 1.0 / 100.0 / 252.0
    assert np.isclose(cost_full.dropna().iloc[-1], expected_full_daily, rtol=1e-9)
    assert np.isclose(cost_half.dropna().iloc[-1], expected_full_daily / 2.0, rtol=1e-9)


def test_funding_cost_series_is_zero_when_flat(monkeypatch):
    """A zero position (flat/out of the market) must incur zero funding cost,
    even when a funding-rate series is available."""
    level = _rising_yield_series(n=50, start=3.0, step=0.0)
    funding = pd.Series(2.0, index=level.index)
    monkeypatch.setattr(factor_backtest, '_load_funding_rate', lambda country: funding)
    factor_backtest._funding_rate_cache.clear()

    flat_position = pd.Series(0.0, index=level.index)
    cost = funding_cost_series(flat_position, level, 'IRDL.CN')
    assert (cost.fillna(0) == 0).all()


def test_funding_cost_series_is_zero_for_non_irdl_factors(monkeypatch):
    """SPDL/CRDL/IRSL/IRCV etc. get no funding-rate deduction at all —
    scoped to IRDL only (see funding_cost_series docstring)."""
    level = _rising_yield_series(n=50, start=2.0, step=0.0)
    funding = pd.Series(5.0, index=level.index)
    monkeypatch.setattr(factor_backtest, '_load_funding_rate', lambda country: funding)
    factor_backtest._funding_rate_cache.clear()

    position = pd.Series(1.0, index=level.index)
    for code in ('SPDL.CDB', 'CRDL.LGB', 'IRSL.CN', 'IRCV.CN'):
        cost = funding_cost_series(position, level, code)
        assert (cost.fillna(0) == 0).all(), f"{code} should have zero funding cost"


def test_funding_cost_series_is_zero_when_no_funding_series_available(monkeypatch):
    """Falls back to an all-zero cost series (no charge) rather than raising
    or propagating NaN when the funding-rate series can't be loaded at all."""
    level = _rising_yield_series(n=50, start=3.0, step=0.0)
    monkeypatch.setattr(factor_backtest, '_load_funding_rate', lambda country: None)
    factor_backtest._funding_rate_cache.clear()

    position = pd.Series(1.0, index=level.index)
    cost = funding_cost_series(position, level, 'IRDL.CN')
    assert (cost.fillna(0) == 0).all()


def test_apply_funding_cost_reduces_irdl_strategy_returns(monkeypatch):
    """_apply_funding_cost must subtract the position-scaled funding cost
    from strategy_returns for IRDL, and be a no-op (unchanged) for a
    non-IRDL factor code."""
    level = _rising_yield_series(n=50, start=3.0, step=0.0)
    funding = pd.Series(1.0, index=level.index)
    monkeypatch.setattr(factor_backtest, '_load_funding_rate', lambda country: funding)
    factor_backtest._funding_rate_cache.clear()

    position = pd.Series(1.0, index=level.index)
    gross_returns = pd.Series(0.0001, index=level.index)

    net_irdl = _apply_funding_cost(gross_returns, position, level, 'IRDL.CN')
    assert (net_irdl < gross_returns).any(), "IRDL funding cost must reduce strategy_returns"

    net_non_irdl = _apply_funding_cost(gross_returns, position, level, 'SPDL.CDB')
    pd.testing.assert_series_equal(net_non_irdl, gross_returns)


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
