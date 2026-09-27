# -*- coding: utf-8 -*-
"""Turnover and transaction-cost calculation for the historical-allocation
orchestrator.

Originally moved verbatim from the historical-allocation orchestrator
(backtest_hist.py:730-802) alongside a daily-P&L helper pair
(build_returns_matrix / compute_daily_pnl_m, removed in Step 5 — daily P&L
is now multiasset.book.pnl.compute_book_pnl). Only the turnover/tx-cost
function remains here.

As of Step 8 (docs/plans/beta_book_exposure_vs_capital.md), turnover is
computed on DAILY notional deltas (positions can move every day since
Step 4's daily resizing), not monthly weight deltas at rebalance dates —
the old monthly-only version silently assumed zero cost on every day a
position changed without a full rebalance, which stopped being true once
positions became daily-varying. Tx cost also dropped from 0.5bp to 0.1bp
(RiskModelConfig.TX_COST_BP), reflecting that a desk re-hedging daily in
small increments pays materially less per adjustment than a monthly
rebalance moving the whole book at once.
"""

from __future__ import annotations

import pandas as pd

from multiasset.config import RiskModelConfig

# Kept for any external import; RiskModelConfig.TX_COST_BP is now the
# source of truth (see that config's own docstring for the 0.5->0.1bp
# rationale).
TX_COST_BP: float = RiskModelConfig.TX_COST_BP


def compute_turnover_and_tx_cost(notional_daily: pd.DataFrame,
                                 tx_cost_bp: float = None):
    """Daily turnover (one-way CNY notional traded) and the resulting
    transaction-cost series, both indexed by `notional_daily.index`.

        turnover_daily[d] = |notional[d] - notional[d-1]|.sum()   # one-way
        tx_cost_m[d]       = turnover_daily[d] * (tx_cost_bp/1e4) / 1e6

    Day 0 (no prior day to diff against) is charged as if building the
    ENTIRE initial position from scratch — the old monthly code got this
    implicitly via `.shift(1).fillna(0.0)` on the weight matrix; made
    explicit here since `notional_daily.diff()` alone would otherwise
    treat day 0 as a zero-turnover day and silently omit the cost of the
    very first allocation.

    Returns (turnover_daily: pd.Series in CNY, tx_cost_m: pd.Series in
    millions CNY, total_tx_cost_m: float). Callers divide
    `turnover_daily.sum() / n_years` for an annualised turnover figure, same
    convention as before Step 8.
    """
    if tx_cost_bp is None:
        tx_cost_bp = RiskModelConfig.TX_COST_BP
    tx_cost_rate = tx_cost_bp / 1e4

    if notional_daily.empty:
        empty = pd.Series(dtype=float, index=notional_daily.index)
        return empty, empty, 0.0

    diffs = notional_daily.diff()
    diffs.iloc[0] = notional_daily.iloc[0]  # day 0: building the initial position IS turnover
    turnover_daily = diffs.abs().sum(axis=1)  # one-way, CNY

    tx_cost_m = turnover_daily * tx_cost_rate / 1_000_000
    total_tx_cost_m = float(tx_cost_m.sum())
    return turnover_daily, tx_cost_m, total_tx_cost_m
