# -*- coding: utf-8 -*-
"""Factor-level return / funding-hurdle tests.

Factor-level backtests (this module's own MA/Bollinger/Momentum/Z-Score
wrappers, factor_model.py's FactorModel, and the RFBT trainer replay path in
web/tabs/beta/callbacks/_rfbt_train_helpers.py) are PRICE-ONLY:
``r_t ≈ -D_mod × Δy_t / 100``, with no carry and no funding deduction of any
kind — see docs/plans/beta_book_exposure_vs_capital.md Step 3.

An earlier version of ``_yield_carry`` added ``yield_{t-1}/100/252`` for
Level-type factors (IRDL/SPDL/CRDL) only, leaving Slope/Curvature factors
(IRSL/IRCV/SPSL/SPCV/CRSL/CRCV — long-short, net-zero-notional contrasts
where a level-based carry has no economic meaning) at zero. That made
IRDL's Sharpe artificially higher than IRSL/IRCV for reasons unrelated to
genuine risk-adjusted quality, and biased the Stage-1 risk-parity solve in
factor_optimizer.py toward IRDL. Carry, funding and capital usage are now
computed independently at the BOOK level, on real per-tenor notional — see
multiasset/book/pnl.py, multiasset/book/funding.py.

An earlier version also netted IRDL's funding/repo cost directly into
``strategy_returns`` (via a now-removed ``_apply_funding_cost``), as a daily
position-scaled deduction. That is gone too — funding_cost_series() is kept
(book-level funding reuses its "cost proportional to position/notional
actually held" logic) but nothing calls it at the factor level any more.
The equivalent hurdle is applied only when computing Sharpe, via
compute_metrics's ``funding_hurdle`` parameter, which deliberately keeps
funding OUT of the volatility denominator (an earlier flat-rate-on-a-tiny-vol
attempt could swing Sharpe from +4.6 to -5.4 for the same P&L).

Tests inject a fake funding-rate series via monkeypatch where needed, to
test funding_cost_series() / compute_metrics(funding_hurdle=...) without
depending on the real macro-px.pkl file's contents.
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
    compute_metrics,
)


def _rising_yield_series(n: int = 300, start: float = 3.0, step: float = 0.0) -> pd.Series:
    """A yield level series (percent) with a constant level and zero drift,
    so price return is exactly zero — used to isolate "is there any carry
    term at all" from price-return effects."""
    idx = pd.bdate_range('2020-01-01', periods=n)
    return pd.Series(start + step * np.arange(n), index=idx)


@pytest.fixture(autouse=True)
def _no_real_funding_rate(monkeypatch):
    """Prevent IRDL tests from silently hitting the real macro-px.pkl file —
    tests that specifically want a funding rate inject their own via
    _load_funding_rate monkeypatching. Also clears the module-level cache so
    injected fakes never leak between tests.
    """
    factor_backtest._funding_rate_cache.clear()
    monkeypatch.setattr(factor_backtest, '_load_funding_rate', lambda country: None)
    yield
    factor_backtest._funding_rate_cache.clear()


def test_yield_carry_is_zero_for_every_factor_type():
    """_yield_carry must be exactly zero for every factor code — Level
    (IRDL/SPDL/CRDL), Slope/Curvature (IRSL/IRCV/etc.), and anything else.
    This is the sharpest possible assertion that carry is gone from the
    factor level: a flat (zero price-return) series with nonzero yield
    would previously have produced positive carry for Level factors."""
    level = _rising_yield_series(step=0.0)  # perfectly flat: Δy = 0 everywhere
    for code in ('IRDL.CN', 'SPDL.CDB', 'CRDL.LGB',
                 'IRSL.CN', 'IRCV.CN', 'SPSL.CDB', 'SPCV.CDB', 'CRSL.LGB', 'CRCV.LGB'):
        carry = _yield_carry(level, code)
        assert (carry.fillna(0) == 0).all(), f"{code} should have zero carry, got nonzero values"


def test_yield_carry_ignores_funding_rate_availability(monkeypatch):
    """Carry must stay zero regardless of whether a funding-rate series is
    available — there is no netting path left to exercise."""
    level = _rising_yield_series(n=100, start=3.0, step=0.0)
    funding = pd.Series(1.0, index=level.index)
    monkeypatch.setattr(factor_backtest, '_load_funding_rate', lambda country: funding)
    factor_backtest._funding_rate_cache.clear()

    carry = _yield_carry(level, 'IRDL.CN')
    assert (carry.fillna(0) == 0).all()


def test_funding_cost_series_scales_with_position(monkeypatch):
    """funding_cost_series() must charge position_{t-1} * funding_rate_{t-1}/252,
    not a flat rate regardless of position size — a half-sized position
    should be charged half the cost of a full position. Not currently
    called from any factor-level backtest path (kept as a book-level
    primitive — see module docstring), but the formula itself must still be
    correct since multiasset/book/funding.py reuses it."""
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


def test_compute_metrics_funding_hurdle_reduces_sharpe_without_changing_vol():
    """A funding_hurdle passed into compute_metrics must reduce Sharpe (via
    the numerator only) while leaving Ann. Vol and Ann. Return themselves
    completely unchanged — the whole point of applying it only at the
    Sharpe step rather than netting it into the return series."""
    idx = pd.bdate_range('2020-01-01', periods=300)
    rng = np.random.default_rng(0)
    rets = pd.Series(0.0006 + rng.normal(0, 0.001, size=len(idx)), index=idx)
    df = pd.DataFrame({'strategy_returns': rets})

    m_no_hurdle = compute_metrics(df, geometric_annualisation=True)
    hurdle = pd.Series(0.0002, index=idx)  # flat daily funding cost
    m_with_hurdle = compute_metrics(df, geometric_annualisation=True, funding_hurdle=hurdle)

    assert m_with_hurdle['Ann. Vol'] == m_no_hurdle['Ann. Vol']
    assert m_with_hurdle['Ann. Return'] == m_no_hurdle['Ann. Return']
    assert m_with_hurdle['Sharpe'] < m_no_hurdle['Sharpe']
    assert np.isclose(m_with_hurdle['Ann. Funding Cost'], 0.0002 * 252, rtol=1e-9)
    # 'Sharpe (gross of funding)' must match the no-hurdle Sharpe exactly.
    assert np.isclose(m_with_hurdle['Sharpe (gross of funding)'], m_no_hurdle['Sharpe'], rtol=1e-9)


def test_compute_metrics_no_hurdle_defaults_to_zero_funding_cost():
    idx = pd.bdate_range('2020-01-01', periods=100)
    df = pd.DataFrame({'strategy_returns': pd.Series(0.0005, index=idx)})
    m = compute_metrics(df, geometric_annualisation=True)
    assert m['Ann. Funding Cost'] == 0.0
    assert m['Sharpe (gross of funding)'] == m['Sharpe']


def test_is_level_factor_classification():
    """_is_level_factor no longer gates any behaviour, but the
    classification itself (Level vs Slope/Curvature) must still be correct —
    kept for any future book-level module that needs the same lookup."""
    assert _is_level_factor('IRDL.CN')
    assert _is_level_factor('SPDL.CDB')
    assert _is_level_factor('CRDL.LGB')
    assert not _is_level_factor('IRSL.CN')
    assert not _is_level_factor('IRCV.CN')
    assert not _is_level_factor('FXDL.USDCNY')  # not a yield factor at all


def test_yield_to_return_without_factor_code_is_price_only_backward_compat():
    """Omitting factor_code must reproduce the exact price-only behaviour,
    so any caller not yet updated to pass it keeps working."""
    level = _rising_yield_series(step=0.01)  # yields drifting up
    old_style = _yield_to_return(level, mod_dur=1.0)
    new_style_no_code = _yield_to_return(level, mod_dur=1.0, factor_code=None)
    pd.testing.assert_series_equal(old_style, new_style_no_code)


def test_yield_to_return_is_price_only_regardless_of_factor_code():
    """On a flat yield series, _yield_to_return must be exactly 0.0 for
    every factor code — the sharpest possible assertion that carry never
    enters this function's output any more."""
    level = _rising_yield_series(step=0.0)  # flat: isolates carry from price effect
    price_only = _yield_to_return(level, mod_dur=1.0)  # no factor_code
    for code in ('IRDL.CN', 'SPDL.CDB', 'CRDL.LGB', 'IRSL.CN', 'IRCV.CN'):
        with_code = _yield_to_return(level, mod_dur=1.0, factor_code=code)
        pd.testing.assert_series_equal(price_only, with_code)
        assert (with_code.dropna() == 0.0).all()


def test_yield_to_return_and_factor_level_to_price_return_agree():
    """The two independent implementations of yield-factor returns
    (_yield_to_return and factor_level_to_price_return) must produce
    identical total returns for the same factor — both are price-only now
    and must agree exactly."""
    level = _rising_yield_series(step=0.01)
    r1 = _yield_to_return(level, mod_dur=1.0, factor_code='SPDL.CDB')
    r2 = factor_level_to_price_return(level, 'SPDL.CDB', output_in_percent=False)
    pd.testing.assert_series_equal(r1, r2, check_names=False)


def test_no_apply_funding_cost_in_factor_backtest():
    """Regression guard: _apply_funding_cost was removed from factor_backtest
    (Step 3) — nothing should reintroduce a funding deduction directly into
    strategy_returns at the factor level. If this starts failing, check that
    whatever re-added it also updated this test file's module docstring."""
    assert not hasattr(factor_backtest, '_apply_funding_cost')
