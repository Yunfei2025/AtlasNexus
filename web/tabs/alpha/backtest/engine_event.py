# -*- coding: utf-8 -*-
"""Phase 5 (Backtest) of docs/dev/tbondcurve-30y-otr-ofr-plan.md.

BondNewIssue is a dedicated event-driven strategy: it has no continuous pair
history, so it is never routed through the MR (`engine_mr`) or trend
(`engine_trend`) z-score engines. Entry is a walk-forward issuance-cohort
percentile check within the rank-age window; each episode is scored only
against *causal* prior episodes (see `curves.calibration.newissue_cohort`),
so this backtest cannot use future-episode information — the same gate logic
production candidate scoring must use (per the plan's style policy).

Modeled as two stages (see plan's "Canonical Definitions"):
    nib_otr   — challenger (NIB) vs incumbent (OTR)
    otr_ofr1  — incumbent (OTR) vs its immediate successor (OFR1)
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

# Per-stage column mapping (mirrors curves/refreshers/newissue_spreads.py::_STAGES).
_STAGE_COLUMNS = {
    'nib_otr': {
        'group_col': 'nib_id', 'start_col': 'nib_start_date',
        'age_col': 'nib_age_days', 'spread_col': 'spread_nib_otr',
    },
    'otr_ofr1': {
        'group_col': 'otr_id', 'start_col': 'otr_since_date',
        'age_col': 'otr_rank_age_days', 'spread_col': 'spread_otr_ofr1',
    },
}


def run_new_issue_backtest(
    universe_df: pd.DataFrame,
    stage: str = 'otr_ofr1',
    entry_percentile_max: float = 60.0,
    entry_age_min_days: int = NewIssueConfig.ENTRY_AGE_MIN_DAYS,
    entry_age_max_days: int = NewIssueConfig.ENTRY_AGE_MAX_DAYS,
    age_tolerance_days: int = 5,
    min_cohort_episodes: int = MIN_COHORT_EPISODES,
) -> Dict[str, Any]:
    """Walk-forward EventDriven backtest over all episodes in `universe_df`,
    for one rotation stage (`nib_otr` or `otr_ofr1`).

    For each episode (identified by the stage's group column), scans dates
    within [entry_age_min_days, entry_age_max_days]. Enters on the first date
    whose causal cohort percentile is at or below `entry_percentile_max` (i.e.
    the widening hasn't already run its course per history) and exits at the
    end of the age window. Episodes without enough *prior* episodes to score
    (`insufficient_episodes`) are left observe-only — no trade, consistent
    with the plan's cold-start philosophy. `nib_otr` episodes additionally
    require `lag_exists` at entry — no live migration to trade otherwise.

    Returns a results dict with 'error' set if there are no episodes at all;
    otherwise 'trades' (list[dict]), 'equity_ts' (cumulative pnl in bp),
    'n_episodes', 'stage', and 'style' = 'EventDriven'.
    """
    cols = _STAGE_COLUMNS[stage]
    episodes = segment_episodes(universe_df, group_col=cols['group_col'])
    if not episodes:
        return {'error': 'No BondNewIssue episodes found in universe_df', 'style': 'EventDriven', 'stage': stage}

    ordered_ids = sorted(
        episodes.keys(),
        key=lambda eid: pd.Timestamp(episodes[eid][cols['start_col']].iloc[0]),
    )

    trades: List[Dict[str, Any]] = []
    equity_bp = 0.0
    equity_points: List[Any] = []

    for episode_id in ordered_ids:
        ep = episodes[episode_id]
        window = ep[
            (pd.to_numeric(ep[cols['age_col']], errors='coerce') >= entry_age_min_days)
            & (pd.to_numeric(ep[cols['age_col']], errors='coerce') <= entry_age_max_days)
        ].sort_index()

        entry_idx = None
        entry_score: Optional[Dict[str, Any]] = None
        for idx, row in window.iterrows():
            if stage == 'nib_otr' and not bool(row.get('lag_exists', False)):
                continue  # existence-of-lag gate: no live migration to trade
            spread = pd.to_numeric(row.get(cols['spread_col']), errors='coerce')
            age = row.get(cols['age_col'])
            if pd.isna(spread) or pd.isna(age):
                continue
            score = cohort_percentile_causal(
                episodes, episode_id, int(age), float(spread),
                age_tolerance_days=age_tolerance_days,
                min_episodes=min_cohort_episodes,
                start_col=cols['start_col'], age_col=cols['age_col'], spread_col=cols['spread_col'],
            )
            if score['reason'] == 'insufficient_episodes':
                continue
            if score['percentile'] is not None and not pd.isna(score['percentile']) and score['percentile'] <= entry_percentile_max:
                entry_idx = idx
                entry_score = score
                break

        if entry_idx is None:
            trades.append({
                'episode_id': episode_id,
                'status': 'no_entry',
                'reason': 'insufficient_episodes' if not window.empty else 'no_window_data',
            })
            continue

        entry_row = window.loc[entry_idx]
        exit_row = window.iloc[-1]
        entry_spread = float(pd.to_numeric(entry_row[cols['spread_col']], errors='coerce'))
        exit_spread = float(pd.to_numeric(exit_row[cols['spread_col']], errors='coerce'))
        # nib_otr profits when spread=y_NIB-y_OTR widens (NIB catching up);
        # otr_ofr1 profits when spread=y_OTR-y_OFR1 narrows (OTR eroding) — see
        # plan doc for sign convention per stage.
        direction = 1.0 if stage == 'nib_otr' else -1.0
        pnl_bp = direction * (exit_spread - entry_spread) * 100.0
        equity_bp += pnl_bp
        equity_points.append((exit_row.name, equity_bp))

        trades.append({
            'episode_id': episode_id,
            'status': 'closed',
            'direction': 'BUY' if stage == 'nib_otr' else 'SELL',
            'entry_date': entry_idx,
            'exit_date': exit_row.name,
            'entry_age_days': int(entry_row[cols['age_col']]),
            'exit_age_days': int(exit_row[cols['age_col']]),
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
        'stage': stage,
        'n_episodes': len(episodes),
        'trades': trades,
        'equity_ts': equity_ts,
        'entry_percentile_max': entry_percentile_max,
        'entry_age_window': (entry_age_min_days, entry_age_max_days),
    }

