# -*- coding: utf-8 -*-
"""Daily P&L vectorisation and turnover/transaction-cost calculation.

Moved verbatim (as a function) from the historical-allocation orchestrator
(formerly backtest_hist.py:730-802) — no behaviour change. `total_return_pnl`
still reads only the ['total'] column of calculate_daily_returns_series;
splitting capital-gain from carry is a later step
(docs/plans/beta_book_exposure_vs_capital.md Step 5), not part of this move.
"""

from __future__ import annotations

import logging

import pandas as pd

from multiasset.data import calculate_daily_returns_series

logger = logging.getLogger(__name__)

# Transaction cost, basis points per unit ONE-WAY turnover (round-trip = 2x).
# Conservative estimate for bond futures / IRS.
TX_COST_BP: float = 0.5


def build_returns_matrix(all_assets_ever, market_data, start_date, end_date,
                         daily_idx: pd.DatetimeIndex) -> pd.DataFrame:
    """Per-asset daily TOTAL return (carry+capital, or price-only for
    FX/commodity — see calculate_daily_returns_series), indexed by
    `daily_idx`. Assets whose return series fails to load are silently
    dropped from the resulting columns (matches original try/except-and-skip
    behaviour)."""
    ret_series: dict[str, pd.Series] = {}
    for name in all_assets_ever:
        try:
            ret_df = calculate_daily_returns_series(name, market_data, start_date, end_date)
            if not ret_df.empty:
                s = ret_df.set_index('Date')['total']
                if not isinstance(s.index, pd.DatetimeIndex):
                    s.index = pd.to_datetime(s.index)
                ret_series[name] = s
        except Exception as e:
            logger.warning("Could not load returns for %s: %s", name, e)
    return pd.DataFrame(ret_series, index=daily_idx)


def build_daily_allocation(allocations_by_date: dict, rets_columns,
                           daily_idx: pd.DatetimeIndex) -> pd.DataFrame:
    """Forward-fill the (sparse, per-rebalance-date) CNY allocation onto every
    daily date. This is the monthly-step-function behaviour that Step 4 of
    the plan replaces with a genuinely daily-varying notional; kept as-is
    here since Step 1 is a pure move, zero behaviour change."""
    alloc_rows = {pd.Timestamp(rd): alloc for rd, alloc in allocations_by_date.items()}
    alloc_raw = pd.DataFrame(alloc_rows).T
    alloc_raw.index = pd.DatetimeIndex(alloc_raw.index)
    return (
        alloc_raw
        .reindex(alloc_raw.index.union(daily_idx))
        .ffill()
        .reindex(daily_idx)
        .reindex(columns=rets_columns)
        .fillna(0.0)
    )


def compute_daily_pnl_m(alloc_daily: pd.DataFrame, rets_matrix: pd.DataFrame) -> pd.DataFrame:
    """Daily PnL in millions CNY, per asset."""
    return (alloc_daily * rets_matrix).fillna(0.0) / 1_000_000


def compute_turnover_and_tx_cost(allocations_by_date: dict, rets_columns,
                                 daily_idx: pd.DatetimeIndex,
                                 total_capital_cny: float,
                                 tx_cost_bp: float = TX_COST_BP):
    """Turnover (one-way, per rebalance date) and the resulting transaction
    cost series (millions CNY, indexed by `daily_idx`, charged on the first
    daily date on/after each rebalance).

    Returns (turnover_by_date: pd.Series, tx_cost_m: pd.Series,
             ann_turnover: float placeholder — caller divides by n_years,
             total_tx_cost_m: float).
    """
    tx_cost_rate = tx_cost_bp / 1e4

    weight_rows = {}
    for rd, alloc in allocations_by_date.items():
        tot = sum(abs(v) for v in alloc.values()) or 1.0
        weight_rows[pd.Timestamp(rd)] = {k: v / tot for k, v in alloc.items()}

    wt_df = pd.DataFrame(weight_rows).T.sort_index().reindex(
        columns=list(rets_columns), fill_value=0.0
    )
    wt_df_prev = wt_df.shift(1).fillna(0.0)
    turnover_by_date = (wt_df - wt_df_prev).abs().sum(axis=1)  # one-way per rebalance

    cap_m = total_capital_cny / 1_000_000
    tx_cost_m = pd.Series(0.0, index=daily_idx)
    for rd, to in turnover_by_date.items():
        match = daily_idx[daily_idx >= rd]
        if len(match):
            tx_cost_m[match[0]] += float(to) * tx_cost_rate * cap_m

    total_tx_cost_m = float(tx_cost_m.sum())
    return turnover_by_date, tx_cost_m, total_tx_cost_m
