# -*- coding: utf-8 -*-
"""Phase 5 (Backtest) of docs/dev/tbondcurve-30y-otr-ofr-plan.md.

BondNewIssue is a dedicated event-driven strategy: it has no continuous pair
history, so it is never routed through the MR (`engine_mr`) or trend
(`engine_trend`) z-score engines. Entry is a walk-forward issuance-cohort
percentile check within the OTR age window; each episode is scored only
against *causal* prior episodes (see `curves.calibration.newissue_cohort`),
so this backtest cannot use future-episode information — the same gate logic
production candidate scoring must use (per the plan's style policy).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from settings.fixed_income import NewIssueConfig
from curves.calibration.newissue_cohort import (
    MIN_COHORT_EPISODES,
    segment_episodes,
    cohort_percentile_causal,
)


def run_new_issue_backtest(
    universe_df: pd.DataFrame,
    entry_percentile_max: float = 60.0,
    entry_age_min_days: int = NewIssueConfig.ENTRY_AGE_MIN_DAYS,
    entry_age_max_days: int = NewIssueConfig.ENTRY_AGE_MAX_DAYS,
    age_tolerance_days: int = 5,
    min_cohort_episodes: int = MIN_COHORT_EPISODES,
) -> Dict[str, Any]:
    """Walk-forward EventDriven backtest over all episodes in `universe_df`.

    For each episode (identified by `otr_id`), scans dates within
    [entry_age_min_days, entry_age_max_days]. Enters (long OTR, short 1st-OFR)
    on the first date whose causal cohort percentile is at or below
    `entry_percentile_max` (i.e. the widening hasn't already run its course
    per history) and exits at the end of the age window. Episodes without
    enough *prior* episodes to score (`insufficient_episodes`) are left
    observe-only — no trade, consistent with the plan's cold-start philosophy.

    Returns a results dict with 'error' set if there are no episodes at all;
    otherwise 'trades' (list[dict]), 'equity_ts' (cumulative pnl in bp),
    'n_episodes', and 'style' = 'EventDriven'.
    """
    episodes = segment_episodes(universe_df)
    if not episodes:
        return {'error': 'No BondNewIssue episodes found in universe_df', 'style': 'EventDriven'}

    ordered_ids = sorted(
        episodes.keys(),
        key=lambda oid: pd.Timestamp(episodes[oid]['otr_start_date'].iloc[0]),
    )

    trades: List[Dict[str, Any]] = []
    equity_bp = 0.0
    equity_points: List[Any] = []

    for otr_id in ordered_ids:
        ep = episodes[otr_id]
        window = ep[
            (pd.to_numeric(ep['event_age_days'], errors='coerce') >= entry_age_min_days)
            & (pd.to_numeric(ep['event_age_days'], errors='coerce') <= entry_age_max_days)
        ].sort_index()

        entry_idx = None
        entry_score: Optional[Dict[str, Any]] = None
        for idx, row in window.iterrows():
            spread = pd.to_numeric(row.get('spread'), errors='coerce')
            age = row.get('event_age_days')
            if pd.isna(spread) or pd.isna(age):
                continue
            score = cohort_percentile_causal(
                episodes, otr_id, int(age), float(spread),
                age_tolerance_days=age_tolerance_days,
                min_episodes=min_cohort_episodes,
            )
            if score['reason'] == 'insufficient_episodes':
                continue
            if score['percentile'] is not None and not pd.isna(score['percentile']) and score['percentile'] <= entry_percentile_max:
                entry_idx = idx
                entry_score = score
                break

        if entry_idx is None:
            trades.append({
                'otr_id': otr_id,
                'status': 'no_entry',
                'reason': 'insufficient_episodes' if not window.empty else 'no_window_data',
            })
            continue

        entry_row = window.loc[entry_idx]
        exit_row = window.iloc[-1]
        entry_spread = float(pd.to_numeric(entry_row['spread'], errors='coerce'))
        exit_spread = float(pd.to_numeric(exit_row['spread'], errors='coerce'))
        # Long OTR / short 1st-OFR profits when spread = ytm_1ofr - ytm_otr widens.
        pnl_bp = (exit_spread - entry_spread) * 100.0
        equity_bp += pnl_bp
        equity_points.append((exit_row.name, equity_bp))

        trades.append({
            'otr_id': otr_id,
            'status': 'closed',
            'direction': 'BUY',
            'entry_date': entry_idx,
            'exit_date': exit_row.name,
            'entry_age_days': int(entry_row['event_age_days']),
            'exit_age_days': int(exit_row['event_age_days']),
            'entry_spread': entry_spread,
            'exit_spread': exit_spread,
            'entry_percentile': entry_score['percentile'] if entry_score else np.nan,
            'pnl_bp': pnl_bp,
        })

    equity_ts = (
        pd.Series({d: v for d, v in equity_points}).sort_index()
        if equity_points else pd.Series(dtype=float)
    )

    return {
        'style': 'EventDriven',
        'n_episodes': len(episodes),
        'trades': trades,
        'equity_ts': equity_ts,
        'entry_percentile_max': entry_percentile_max,
        'entry_age_window': (entry_age_min_days, entry_age_max_days),
    }
