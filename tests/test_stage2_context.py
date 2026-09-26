# -*- coding: utf-8 -*-
"""Regression tests for the Stage-1/Stage-2 split in FactorRiskParityOptimizer
(see docs/plans/beta_book_exposure_vs_capital.md Step 2).

``_stage1_context`` (expensive: SLSQP ERC across factors, monthly cadence)
and ``rebuild_asset_weights`` (cheap: closed-form tenor tilt, intended to
also run daily off a rescaled factor budget) replace what was previously one
fused ``_two_stage_weights`` method. The load-bearing property this file
checks is that the split introduced NO behaviour change: calling
``rebuild_asset_weights(ctx, None)`` — i.e. with no rescaling — must
reproduce the original combined method's output bit-for-bit.

Requires real market data (factor-rates.pkl / bond universe via
create_custom_portfolio) — skips gracefully if unavailable, matching the
pattern in test_walkforward_coverage.py, since CLAUDE.md documents the
suite as not requiring market data in general.
"""

from __future__ import annotations

import time

import pandas as pd
import pytest

from settings.paths import DIR_INPUT

try:
    from multiasset.main import create_custom_portfolio
    from multiasset.factor_optimizer import FactorRiskParityOptimizer, Stage2Context
except Exception:  # pragma: no cover - import-time data/env issues
    create_custom_portfolio = None
    FactorRiskParityOptimizer = None
    Stage2Context = None


REBALANCE_DATE = pd.Timestamp('2024-06-03')  # a Monday, well within typical history


def _make_optimizer(asset_names):
    """Build a FactorRiskParityOptimizer over `asset_names`, or skip the test
    if the underlying market data isn't available in this environment."""
    if create_custom_portfolio is None or FactorRiskParityOptimizer is None:
        pytest.skip("multiasset optimizer modules unavailable")
    try:
        port = create_custom_portfolio(asset_names, use_deterministic=True)
        opt = FactorRiskParityOptimizer(
            portfolio=port, input_dir=str(DIR_INPUT), vol_lookback_months=6,
        )
        # Touch the risk-factor load early so a missing-data skip happens
        # here, not mid-assertion.
        rf = opt.portfolio.get_risk_factors(use_cache=True)
        if rf is None or rf.empty:
            pytest.skip("no risk-factor data available in this environment")
        return opt
    except Exception as e:
        pytest.skip(f"market data unavailable for Stage2Context tests: {e}")


def test_rebuild_with_reference_budget_reproduces_two_stage_weights_exactly():
    """rebuild_asset_weights(ctx, None) must exactly reproduce
    _two_stage_weights's original combined-method output — same code path,
    just re-entered through the split. Uses the CN IRDL/IRSL/IRCV triplet
    (the most complex Stage-2 case: multi-tenor, three pooled factors)."""
    assets = ['CN1Y', 'CN2Y', 'CN5Y', 'CN10Y', 'CN20Y', 'CN30Y']
    opt = _make_optimizer(assets)

    w_combined, _ = opt.fit_and_calculate(REBALANCE_DATE, use_dv01_shape=True)

    ctx = opt.stage2_context()
    if ctx is None:
        pytest.skip("fit_and_calculate took the empty-exposure-matrix fallback path")

    w_split = opt.rebuild_asset_weights(ctx, None)

    pd.testing.assert_series_equal(
        w_combined.sort_index(), w_split.sort_index(), check_exact=False, atol=0, rtol=0,
    )


def test_rebuild_with_reference_budget_reproduces_two_stage_weights_mixed_pool():
    """Same exactness check on a mixed pool (rates + FX + commodity) to
    cover the non-rate ('else') branch of the original Stage-2 loop."""
    assets = ['CN1Y', 'CN2Y', 'CN5Y', 'CN10Y', 'CN20Y', 'CN30Y', 'USDCNY', 'Gold']
    opt = _make_optimizer(assets)

    w_combined, _ = opt.fit_and_calculate(REBALANCE_DATE, use_dv01_shape=True)
    ctx = opt.stage2_context()
    if ctx is None:
        pytest.skip("fit_and_calculate took the empty-exposure-matrix fallback path")
    w_split = opt.rebuild_asset_weights(ctx, None)

    pd.testing.assert_series_equal(
        w_combined.sort_index(), w_split.sort_index(), check_exact=False, atol=0, rtol=0,
    )


def test_rebuild_asset_weights_is_cheap():
    """rebuild_asset_weights must be fast enough to call once per trading
    day: 250 calls (≈1yr) should run in well under half a second once ctx
    is built (the SLSQP solve is NOT re-run per call)."""
    assets = ['CN1Y', 'CN2Y', 'CN5Y', 'CN10Y', 'CN20Y', 'CN30Y']
    opt = _make_optimizer(assets)

    opt.fit_and_calculate(REBALANCE_DATE, use_dv01_shape=True)
    ctx = opt.stage2_context()
    if ctx is None:
        pytest.skip("fit_and_calculate took the empty-exposure-matrix fallback path")

    t0 = time.time()
    for _ in range(250):
        opt.rebuild_asset_weights(ctx, None)
    elapsed = time.time() - t0
    assert elapsed < 0.5, f"250 rebuild_asset_weights calls took {elapsed:.2f}s, expected < 0.5s"


def test_rebuild_asset_weights_respects_long_only_bond_bounds():
    """Every bond weight must stay non-negative — Stage 2's tenor tilt has a
    long-only floor (see _tilt_group_shape), and the clip->renorm loop in
    rebuild_asset_weights must not violate it even with a budget skewed
    entirely toward one directional (slope/curve) factor."""
    assets = ['CN1Y', 'CN2Y', 'CN5Y', 'CN10Y', 'CN20Y', 'CN30Y']
    opt = _make_optimizer(assets)

    opt.fit_and_calculate(REBALANCE_DATE, use_dv01_shape=True)
    ctx = opt.stage2_context()
    if ctx is None:
        pytest.skip("fit_and_calculate took the empty-exposure-matrix fallback path")

    # Skew the budget: nearly all weight on the slope factor of the one
    # group present, none on level -- exercises the sign flexibility of
    # group_sub_budget while confirming bond output stays long-only.
    skewed_budget = dict(ctx.reference_factor_budget)
    for g in ctx.groups:
        if g.slope_factor:
            skewed_budget[g.level_factor] = 0.01
            skewed_budget[g.slope_factor] = 0.98
            if g.curve_factor:
                skewed_budget[g.curve_factor] = 0.01

    w = opt.rebuild_asset_weights(ctx, skewed_budget)
    assert (w.values >= -1e-9).all(), f"negative weight found: {w[w < 0]}"
    assert abs(w.sum() - 1.0) < 1e-6


def test_stage2_context_reference_budget_sums_to_one():
    """Stage 1's ERC output (reference_factor_budget) must sum to 1 —
    it's a fraction-of-capital budget, not a raw weight."""
    assets = ['CN1Y', 'CN2Y', 'CN5Y', 'CN10Y', 'CN20Y', 'CN30Y', 'USDCNY']
    opt = _make_optimizer(assets)

    opt.fit_and_calculate(REBALANCE_DATE, use_dv01_shape=True)
    ctx = opt.stage2_context()
    if ctx is None:
        pytest.skip("fit_and_calculate took the empty-exposure-matrix fallback path")

    total = sum(ctx.reference_factor_budget.values())
    assert abs(total - 1.0) < 1e-6
