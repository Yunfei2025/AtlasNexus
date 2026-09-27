# -*- coding: utf-8 -*-
"""Regression tests for multiasset.book.sizing (Step 4 of
docs/plans/beta_book_exposure_vs_capital.md — daily per-factor resizing).

The load-bearing property: today's Individual Factors signal is a DAILY
series, but the old factor_scaling implementation only ever sampled it at
`rebalance_date` (once a month), so a mid-month signal change did nothing
until the next rebalance. scaled_factor_budgets_daily / daily_weights_from_
context fix this — these tests confirm the fix without re-deriving it from
scratch on every run: a constant signal must reproduce the old monthly
behaviour exactly (proving the new path subsumes the old one), and a
mid-month signal jump must move weights on the jump date, not the 1st.

Requires real market data (factor-rates.pkl / bond universe via
create_custom_portfolio) — skips gracefully if unavailable, matching
test_stage2_context.py's pattern.
"""

from __future__ import annotations

import pandas as pd
import pytest

from settings.paths import DIR_INPUT

try:
    from multiasset.main import create_custom_portfolio
    from multiasset.factor_optimizer import FactorRiskParityOptimizer
    from multiasset.backtest_cache import scalar_to_coeff
    from multiasset.book.sizing import scaled_factor_budgets_daily, daily_weights_from_context
except Exception:  # pragma: no cover - import-time data/env issues
    create_custom_portfolio = None
    FactorRiskParityOptimizer = None


REBALANCE_DATE = pd.Timestamp('2024-06-03')


def _make_optimizer(asset_names):
    if create_custom_portfolio is None or FactorRiskParityOptimizer is None:
        pytest.skip("multiasset optimizer modules unavailable")
    try:
        port = create_custom_portfolio(asset_names, use_deterministic=True)
        opt = FactorRiskParityOptimizer(
            portfolio=port, input_dir=str(DIR_INPUT), vol_lookback_months=6,
        )
        rf = opt.portfolio.get_risk_factors(use_cache=True)
        if rf is None or rf.empty:
            pytest.skip("no risk-factor data available in this environment")
        return opt
    except Exception as e:
        pytest.skip(f"market data unavailable for daily-budget tests: {e}")


def _daily_index(n_days=30, start='2024-06-01'):
    return pd.bdate_range(start, periods=n_days)


def test_scaled_factor_budgets_daily_constant_signal_matches_flat_scale():
    """A constant signal for the whole window must produce a constant
    scaled budget equal to reference*coeff every day — proving there is no
    hidden day-to-day drift when the signal itself doesn't move."""
    idx = _daily_index()
    reference_budget = {'IRDL.CN': 0.3, 'IRSL.CN': 0.1, 'IRCV.CN': 0.05}

    def constant_signal(f, d):
        return 0.5  # same signal every day, every factor

    budgets = scaled_factor_budgets_daily(
        reference_budget, constant_signal, idx, screened_factors=list(reference_budget.keys()),
    )
    for f, ref in reference_budget.items():
        expected = ref * scalar_to_coeff(0.5, f)
        assert (budgets[f] == expected).all(), f"{f} should be flat at {expected} every day"


def test_scaled_factor_budgets_daily_unscreened_factor_keeps_reference():
    """A factor not in screened_factors must keep its unscaled reference
    budget on every day — matching the old per-date gating exactly (a
    factor the correlation screen didn't pick for this rebalance month
    never gets a tilt applied)."""
    idx = _daily_index()
    reference_budget = {'IRDL.CN': 0.3, 'IRSL.CN': 0.1}

    def strong_signal(f, d):
        return 2.0  # would otherwise clip hard if applied

    budgets = scaled_factor_budgets_daily(
        reference_budget, strong_signal, idx, screened_factors=['IRDL.CN'],  # IRSL.CN NOT screened
    )
    assert (budgets['IRSL.CN'] == 0.1).all()
    assert (budgets['IRDL.CN'] == 0.3 * scalar_to_coeff(2.0, 'IRDL.CN')).all()


def test_scaled_factor_budgets_daily_no_signal_keeps_reference():
    """A day with no signal available (signal_asof returns None) must keep
    the unscaled reference budget for that day, not raise or produce NaN."""
    idx = _daily_index(n_days=5)
    reference_budget = {'IRDL.CN': 0.3}

    def sometimes_none(f, d):
        return None if d.day % 2 == 0 else 1.0

    budgets = scaled_factor_budgets_daily(
        reference_budget, sometimes_none, idx, screened_factors=['IRDL.CN'],
    )
    for d in idx:
        if d.day % 2 == 0:
            assert budgets.loc[d, 'IRDL.CN'] == 0.3
        else:
            assert budgets.loc[d, 'IRDL.CN'] == 0.3 * scalar_to_coeff(1.0, 'IRDL.CN')


def test_daily_weights_constant_signal_reproduces_reference_budget_weights():
    """A constant position of 1.0 for the whole month (scalar_to_coeff(1.0,
    ...) == 1.0 for every factor, i.e. "unscaled") must produce daily weights
    identical to what rebuild_asset_weights(ctx, None) gives — the new daily
    path, under a signal that never changes and never rescales the reference
    budget, must exactly subsume the old monthly-sampled behaviour."""
    assets = ['CN1Y', 'CN2Y', 'CN5Y', 'CN10Y', 'CN20Y', 'CN30Y']
    opt = _make_optimizer(assets)
    opt.fit_and_calculate(REBALANCE_DATE, use_dv01_shape=True)
    ctx = opt.stage2_context()
    if ctx is None:
        pytest.skip("fit_and_calculate took the empty-exposure-matrix fallback path")

    idx = _daily_index(n_days=10, start=REBALANCE_DATE.strftime('%Y-%m-%d'))

    def zero_signal(f, d):
        return 0.0  # coeff = 1.0 for long-only factors -> budget unchanged

    budgets = scaled_factor_budgets_daily(
        ctx.reference_factor_budget, zero_signal, idx,
        screened_factors=list(ctx.reference_factor_budget.keys()),
    )
    ctx_by_date = {REBALANCE_DATE: ctx}
    budgets_by_date = {REBALANCE_DATE: budgets}
    weights_daily = daily_weights_from_context(ctx_by_date, budgets_by_date, idx)

    expected = opt.rebuild_asset_weights(ctx, None)
    for d in idx:
        row = weights_daily.loc[d].reindex(expected.index).fillna(0.0)
        pd.testing.assert_series_equal(row.sort_index(), expected.sort_index(),
                                       check_exact=False, atol=1e-9, rtol=1e-9, check_names=False)


def test_daily_weights_mid_window_signal_jump_moves_weights_on_jump_date():
    """THE regression test for the frozen-signal bug: a signal that jumps
    partway through the window must move weights on the JUMP DATE, not
    wait for a new rebalance. The old implementation sampled the signal
    only at rebalance_date, so this would have failed (weights constant
    for the whole window) before Step 4.

    Uses a synthetic Stage2Context (not a live optimizer run) so the test
    doesn't depend on the live factor pool happening to give the CN group a
    non-negligible budget on any specific date — the property under test is
    purely about sizing.py's day-to-day resampling, not the optimizer's
    factor selection for a particular universe/date."""
    import numpy as np
    from multiasset.factor_optimizer import GroupStage2Spec, Stage2Context

    tenors = ['CN1Y', 'CN2Y', 'CN5Y', 'CN10Y', 'CN20Y', 'CN30Y']
    durations = np.array([0.95, 1.9, 4.5, 8.5, 13.0, 17.0])
    slope_loadings = durations * np.array([-1, -1, 0, 1, 1, 1])
    curve_loadings = durations * np.array([1, 0, -1, -1, 0, 1])
    loadings = np.column_stack([durations, slope_loadings, curve_loadings])

    group = GroupStage2Spec(
        suffix='CN', asset_indices=tuple(range(6)), loadings=loadings,
        level_factor='IRDL.CN', slope_factor='IRSL.CN', curve_factor='IRCV.CN',
        is_credit=False,
    )
    ctx = Stage2Context(
        asset_names=tuple(tenors), factor_names=('IRDL.CN', 'IRSL.CN', 'IRCV.CN'),
        reference_factor_budget={'IRDL.CN': 0.8, 'IRSL.CN': 0.1, 'IRCV.CN': 0.1},
        groups=(group,), nonrate_factor_indices={}, tilt_lambda=None,
        asset_class_of={t: 'bond' for t in tenors},
    )

    idx = _daily_index(n_days=10)
    jump_date = idx[5]

    def jumping_signal(f, d):
        if f != 'IRSL.CN':
            return 0.0
        return -1.0 if d < jump_date else 1.0  # slope signal flips sign at jump_date

    budgets = scaled_factor_budgets_daily(
        ctx.reference_factor_budget, jumping_signal, idx,
        screened_factors=list(ctx.reference_factor_budget.keys()),
    )
    ctx_by_date = {idx[0]: ctx}
    budgets_by_date = {idx[0]: budgets}
    weights_daily = daily_weights_from_context(ctx_by_date, budgets_by_date, idx)

    before = weights_daily.loc[idx[4]]
    on_jump = weights_daily.loc[jump_date]
    after = weights_daily.loc[idx[6]]

    assert not before.equals(on_jump), "weights must change ON the jump date, not stay frozen"
    # after == on_jump (signal is flat again post-jump) but != before
    pd.testing.assert_series_equal(on_jump.sort_index(), after.sort_index(), check_names=False)
    # The short end (CN2Y, negatively loaded on slope) and long end (CN10Y,
    # positively loaded) must be affected by DIFFERENT magnitudes across the
    # jump -- a genuine tenor-shape tilt, not a uniform scale-only change
    # (which would move every tenor by the same proportion).
    delta_2y = on_jump['CN2Y'] - before['CN2Y']
    delta_10y = on_jump['CN10Y'] - before['CN10Y']
    assert abs(delta_2y - delta_10y) > 1e-6, \
        "CN2Y and CN10Y must be affected differently by a slope-signal flip"


def test_daily_weights_sum_stays_within_reasonable_bound():
    """Sanity bound: daily_weights_from_context's output must not blow up
    numerically even under an extreme (max-coefficient) signal — this is
    NOT the capital constraint (that's Step 7's job), just a basic
    finiteness/non-explosion check on the sizing math itself."""
    assets = ['CN1Y', 'CN2Y', 'CN5Y', 'CN10Y', 'CN20Y', 'CN30Y']
    opt = _make_optimizer(assets)
    opt.fit_and_calculate(REBALANCE_DATE, use_dv01_shape=True)
    ctx = opt.stage2_context()
    if ctx is None:
        pytest.skip("fit_and_calculate took the empty-exposure-matrix fallback path")

    idx = _daily_index(n_days=5, start=REBALANCE_DATE.strftime('%Y-%m-%d'))

    def max_signal(f, d):
        return 1.0  # max long-only coeff (1+1=2.0) or a strong directional coeff

    budgets = scaled_factor_budgets_daily(
        ctx.reference_factor_budget, max_signal, idx,
        screened_factors=list(ctx.reference_factor_budget.keys()),
    )
    weights_daily = daily_weights_from_context({REBALANCE_DATE: ctx}, {REBALANCE_DATE: budgets}, idx)
    assert weights_daily.abs().to_numpy().max() < 100, "weights should not blow up numerically"
    assert weights_daily.notna().any().any()
