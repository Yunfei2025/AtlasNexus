# -*- coding: utf-8 -*-
"""Regression tests for multiasset.book.capital (Step 7 of
docs/plans/beta_book_exposure_vs_capital.md — long-only capital constraint
with a utilisation buffer).

The load-bearing property: the pre-refactor book was ALWAYS 100% invested
(weights renormalised to sum(abs(w))==1 every time), so a bearish signal
could only rotate exposure between assets, never de-risk. weights_to_notional
instead preserves the signal's own scale when it's already under the
ceiling — so an all-bearish day genuinely shrinks deployed capital (the
"de-risking test" below), while an all-bullish day is capped at the
ceiling exactly (not scaled UP past it).
"""

from __future__ import annotations

import pandas as pd
import pytest

from multiasset.book.capital import weights_to_notional, gross_utilisation


def test_all_bullish_capped_at_utilisation_ceiling_exactly():
    """When gross weight exceeds the ceiling, notional must scale down to
    exactly max_utilisation * total_capital, not overshoot or undershoot."""
    weights = pd.Series({'CN1Y': 0.6, 'CN10Y': 0.6})  # gross = 1.2, well over 0.95
    total_capital = 10_000_000.0
    notional = weights_to_notional(weights, total_capital, max_utilisation=0.95)
    assert gross_utilisation(notional) == pytest.approx(0.95 * total_capital, rel=1e-9)


def test_de_risking_all_bearish_reduces_deployed_capital_below_ceiling():
    """THE de-risking test: when the signal itself is small/bearish (gross
    well under the ceiling), notional must NOT be scaled back up to the
    ceiling — deployed capital must be strictly less than
    max_utilisation*capital. This is the property the old
    sum(abs(w))==1 renormalisation broke."""
    weights = pd.Series({'CN1Y': 0.05, 'CN10Y': 0.05})  # gross = 0.10, well under 0.95
    total_capital = 10_000_000.0
    notional = weights_to_notional(weights, total_capital, max_utilisation=0.95)
    assert gross_utilisation(notional) == pytest.approx(0.10 * total_capital, rel=1e-9)
    assert gross_utilisation(notional) < 0.95 * total_capital


def test_bond_notional_stays_long_only():
    weights = pd.Series({'CN1Y': -0.3, 'CN10Y': 0.5})
    total_capital = 10_000_000.0
    asset_class_of = {'CN1Y': 'bond', 'CN10Y': 'bond'}
    notional = weights_to_notional(weights, total_capital, asset_class_of=asset_class_of)
    assert notional['CN1Y'] >= 0.0, "bond notional must be clipped to long-only"


def test_fx_notional_may_be_negative():
    weights = pd.Series({'USDCNY': -0.2, 'CN10Y': 0.5})
    total_capital = 10_000_000.0
    asset_class_of = {'USDCNY': 'fx', 'CN10Y': 'bond'}
    notional = weights_to_notional(weights, total_capital, asset_class_of=asset_class_of)
    assert notional['USDCNY'] < 0.0, "FX is the signed exception — should stay negative"
    assert notional['CN10Y'] >= 0.0


def test_no_asset_class_map_defaults_to_long_only():
    weights = pd.Series({'A': -0.1, 'B': 0.2})
    notional = weights_to_notional(weights, 1_000_000.0)
    assert notional['A'] >= 0.0


def test_gross_never_exceeds_ceiling_across_a_multiday_series():
    """(notional.abs().sum(axis=1) <= max_utilisation*capital + eps).all()
    checked ROW BY ROW on a full daily series, not just at a single
    rebalance date — mirrors how the daily-resizing loop (Step 4) calls
    this once per day."""
    total_capital = 10_000_000.0
    idx = pd.bdate_range('2024-01-01', periods=30)
    rows = {}
    for i, d in enumerate(idx):
        scale = 0.5 + (i % 10) * 0.1  # oscillates from under to over the ceiling
        rows[d] = pd.Series({'CN1Y': scale * 0.5, 'CN10Y': scale * 0.5})
    weights_daily = pd.DataFrame(rows).T

    notional_rows = {d: weights_to_notional(weights_daily.loc[d], total_capital)
                     for d in weights_daily.index}
    notional_daily = pd.DataFrame(notional_rows).T

    gross_series = gross_utilisation(notional_daily)
    assert (gross_series <= 0.95 * total_capital + 1e-6).all()


def test_single_day_spike_across_multiple_factors_still_respects_cap():
    """The test that would fail if the cap were wired in only at the
    monthly Stage-1 sizing level instead of also at the daily step:
    hold a moderate reference weight, then simulate a single day where
    scalar_to_coeff-style scaling pushes several factors to their max
    coefficient simultaneously (e.g. 2.0x for long-only factors) — that one
    day's resulting weight vector must STILL be capped at the ceiling by
    weights_to_notional, independent of what the monthly base assumed."""
    total_capital = 10_000_000.0
    moderate_day = pd.Series({'CN1Y': 0.2, 'CN10Y': 0.2, 'USDCNY': 0.1})
    spike_day = pd.Series({'CN1Y': 0.4, 'CN10Y': 0.4, 'USDCNY': 0.2})  # every factor at max coeff

    notional_moderate = weights_to_notional(moderate_day, total_capital)
    notional_spike = weights_to_notional(spike_day, total_capital)

    assert gross_utilisation(notional_moderate) <= 0.95 * total_capital + 1e-6
    assert gross_utilisation(notional_spike) <= 0.95 * total_capital + 1e-6
    # The spike day's PRE-cap gross (1.0) exceeds the moderate day's (0.5),
    # so post-cap it should be scaled down more (i.e. its notional should
    # actually hit the ceiling, unlike the moderate day which may not).
    assert gross_utilisation(notional_spike) == pytest.approx(0.95 * total_capital, rel=1e-6)


def test_zero_weights_returns_zero_notional_not_error():
    weights = pd.Series({'CN1Y': 0.0, 'CN10Y': 0.0})
    notional = weights_to_notional(weights, 10_000_000.0)
    assert (notional == 0.0).all()


def test_empty_weights_returns_empty():
    notional = weights_to_notional(pd.Series(dtype=float), 10_000_000.0)
    assert notional.empty
