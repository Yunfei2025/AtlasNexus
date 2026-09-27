# -*- coding: utf-8 -*-
"""Regression tests for the daily turnover/transaction-cost calculation
(Step 8 of docs/plans/beta_book_exposure_vs_capital.md).

The load-bearing property: turnover is now computed on DAILY notional
deltas (positions can move every day since Step 4), not monthly weight
deltas sampled only at rebalance dates — a book that changes position
every day but never has an explicit "rebalance" in the old sense must
still be charged tx cost for every one of those daily changes.
"""

from __future__ import annotations

import pandas as pd
import pytest

from web.tabs.beta.callbacks.backtest_hist._pnl import compute_turnover_and_tx_cost, TX_COST_BP
from multiasset.config import RiskModelConfig


def test_tx_cost_bp_default_matches_config():
    assert TX_COST_BP == RiskModelConfig.TX_COST_BP == 0.1


def test_static_book_charges_only_day_one_cost():
    """A book that never changes position after day 0 must be charged the
    initial-build cost on day 0 and NOTHING on every subsequent day."""
    idx = pd.bdate_range('2024-01-01', periods=10)
    notional = pd.DataFrame({'CN10Y': 1_000_000.0}, index=idx)  # constant every day

    turnover_daily, tx_cost_m, total_tx_cost_m = compute_turnover_and_tx_cost(notional)

    assert turnover_daily.iloc[0] == pytest.approx(1_000_000.0)
    assert (turnover_daily.iloc[1:] == 0.0).all()
    expected_day0_cost_m = 1_000_000.0 * (RiskModelConfig.TX_COST_BP / 1e4) / 1_000_000
    assert tx_cost_m.iloc[0] == pytest.approx(expected_day0_cost_m, rel=1e-9)
    assert (tx_cost_m.iloc[1:] == 0.0).all()
    assert total_tx_cost_m == pytest.approx(expected_day0_cost_m, rel=1e-9)


def test_daily_flipping_book_charges_cost_every_day():
    """A book that flips notional every single day must be charged
    turnover on EVERY day, not just at monthly boundaries — this is the
    direct fix for the old monthly-only cost model, which would have
    silently charged zero for 251 of 252 trading days here."""
    idx = pd.bdate_range('2024-01-01', periods=252)  # ~1 trading year
    values = [1_000_000.0 if i % 2 == 0 else -1_000_000.0 for i in range(len(idx))]
    notional = pd.DataFrame({'CN10Y': values}, index=idx)

    turnover_daily, tx_cost_m, total_tx_cost_m = compute_turnover_and_tx_cost(notional)

    # Every day after day 0 has a full flip => |delta| = 2,000,000
    assert (turnover_daily.iloc[1:] == 2_000_000.0).all()
    n_nonzero_cost_days = (tx_cost_m > 0).sum()
    assert n_nonzero_cost_days == len(idx), \
        "a daily-flipping book must be charged cost on every day, not just monthly"


def test_total_cost_scales_linearly_in_tx_cost_bp():
    idx = pd.bdate_range('2024-01-01', periods=20)
    values = [1_000_000.0 * (1 + 0.1 * i) for i in range(len(idx))]  # steadily growing position
    notional = pd.DataFrame({'CN10Y': values}, index=idx)

    _, _, cost_at_1bp = compute_turnover_and_tx_cost(notional, tx_cost_bp=1.0)
    _, _, cost_at_2bp = compute_turnover_and_tx_cost(notional, tx_cost_bp=2.0)

    assert cost_at_2bp == pytest.approx(2.0 * cost_at_1bp, rel=1e-9)


def test_multi_asset_turnover_sums_across_assets():
    """Turnover on a given day must be the SUM of |delta| across every
    asset (one-way, gross), not e.g. net across the book."""
    idx = pd.bdate_range('2024-01-01', periods=3)
    notional = pd.DataFrame({
        'CN2Y':  [1_000_000.0, 1_500_000.0, 1_500_000.0],   # +500k on day 1
        'CN10Y': [1_000_000.0, 500_000.0,   500_000.0],     # -500k on day 1
    }, index=idx)

    turnover_daily, _, _ = compute_turnover_and_tx_cost(notional)
    # Day 0: building both positions from scratch = 2,000,000
    assert turnover_daily.iloc[0] == pytest.approx(2_000_000.0)
    # Day 1: |+500k| + |-500k| = 1,000,000 (NOT net-zero)
    assert turnover_daily.iloc[1] == pytest.approx(1_000_000.0)
    assert turnover_daily.iloc[2] == pytest.approx(0.0)


def test_empty_notional_returns_empty_without_error():
    empty = pd.DataFrame()
    turnover_daily, tx_cost_m, total_tx_cost_m = compute_turnover_and_tx_cost(empty)
    assert turnover_daily.empty
    assert tx_cost_m.empty
    assert total_tx_cost_m == 0.0
