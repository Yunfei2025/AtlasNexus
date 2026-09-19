# -*- coding: utf-8 -*-
"""TermBasisEvent backtest -- the roll-progress-gated event-driven Calendar

Spread strategy, run alongside (not in place of) the stationary-MR
``TermBasis`` z-score engine (``engine_mr.py``). Mirrors
``engine_event.run_new_issue_backtest``'s architecture and docstring
rationale: a calendar-spread's front/next contract pair has no continuous
pair history either (it rebinds at every quarterly roll, and the terminal
delivery date forces convergence -- not a free-floating stationary process),
so this is scored the same walk-forward, causal-cohort-percentile way as
BondNewIssue, using OI-derived ``roll_progress`` in place of calendar-day
event age (see curves/calibration/termbasis_cohort.py's module docstring for
why roll_progress is the better axis here).

Long the near (front) contract / short the far (next) contract profits when
the front-next basis widens back toward its cohort norm from a cheap
entry percentile; the mirror short-front/long-next trade profits from a
rich entry. Both are scored against the same cohort, entered only in the
early-roll regime (``ENTRY_ROLL_PROGRESS_MAX``), and force-exited once OI
has mostly migrated to the next contract (``EXIT_ROLL_PROGRESS_MIN``) even
if the percentile gate never re-fires -- late-cycle front-contract prices
are unreliable (thin liquidity into delivery), so this is a hard exit, not
a target.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from settings.futures import TermBasisEventConfig
from curves.calibration.termbasis_cohort import (
    EPISODE_ID_COL, ROLL_PROGRESS_COL, SPREAD_COL,
    segment_episodes, termbasis_percentile_causal,
)


def run_termbasis_event_backtest(
    episode_frame: pd.DataFrame,
    entry_roll_progress_max: float = TermBasisEventConfig.ENTRY_ROLL_PROGRESS_MAX,
    exit_roll_progress_min: float = TermBasisEventConfig.EXIT_ROLL_PROGRESS_MIN,
    roll_progress_tolerance: float = TermBasisEventConfig.ROLL_PROGRESS_TOLERANCE,
    entry_percentile_max: float = TermBasisEventConfig.ENTRY_PERCENTILE_MAX,
    entry_percentile_min: float = TermBasisEventConfig.ENTRY_PERCENTILE_MIN,
    min_cohort_episodes: int = TermBasisEventConfig.MIN_COHORT_EPISODES,
) -> Dict[str, Any]:
    """Walk-forward EventDriven backtest over all roll-cycle episodes in

    `episode_frame` (one ctype; build per-ctype frames via
    ``termbasis_cohort.build_episode_frame`` and call this once per ctype).

    For each episode (one front/next contract pair), scans dates with
    ``roll_progress <= entry_roll_progress_max`` (the early-cycle,
    carry-driven regime). Enters long-front/short-next on the first date
    whose causal cohort percentile is at or below `entry_percentile_max`
    (basis unusually cheap for this stage of the roll) and short-front/
    long-next on the first date at or above `entry_percentile_min`
    (unusually rich). Exits at the first date with
    ``roll_progress >= exit_roll_progress_min`` after entry, or at the
    episode's last available date if the cycle ends first. Episodes without
    enough *prior* cycles to score (`insufficient_episodes`) are left
    observe-only, same cold-start philosophy as BondNewIssue.

    Returns a results dict with 'error' set if there are no episodes at all;
    otherwise 'trades' (list[dict]), 'equity_ts' (cumulative pnl in bp),
    'n_episodes', and 'style' = 'EventDriven'.
    """
    episodes = segment_episodes(episode_frame)
    if not episodes:
        return {'error': 'No TermBasisEvent roll-cycle episodes found', 'style': 'EventDriven'}

    ordered_ids = sorted(
        episodes.keys(),
        key=lambda eid: episodes[eid].index.min(),
    )

    trades: List[Dict[str, Any]] = []
    equity_bp = 0.0
    equity_points: List[Any] = []

    for episode_id in ordered_ids:
        ep = episodes[episode_id]
        window = ep[pd.to_numeric(ep[ROLL_PROGRESS_COL], errors='coerce') <= entry_roll_progress_max].sort_index()

        entry_idx = None
        entry_score: Optional[Dict[str, Any]] = None
        entry_direction: Optional[int] = None  # +1 long-front/short-next, -1 mirror
        for idx, row in window.iterrows():
            roll_progress = row.get(ROLL_PROGRESS_COL)
            spread = pd.to_numeric(row.get(SPREAD_COL), errors='coerce')
            if pd.isna(spread) or pd.isna(roll_progress):
                continue
            score = termbasis_percentile_causal(
                episodes, episode_id, float(roll_progress), float(spread),
                roll_progress_tolerance=roll_progress_tolerance,
                min_episodes=min_cohort_episodes,
            )
            if score['reason'] == 'insufficient_episodes':
                continue
            pct = score['percentile']
            if pct is None or pd.isna(pct):
                continue
            if pct <= entry_percentile_max:
                entry_idx, entry_score, entry_direction = idx, score, 1
                break
            if pct >= entry_percentile_min:
                entry_idx, entry_score, entry_direction = idx, score, -1
                break

        if entry_idx is None:
            trades.append({
                'episode_id': episode_id,
                'status': 'no_entry',
                'reason': 'insufficient_episodes' if not window.empty else 'no_window_data',
            })
            continue

        # Exit: first date after entry with roll_progress >= exit threshold,
        # else the episode's last available row (cycle ended without ever
        # reaching the late-cycle gate -- e.g. history truncated mid-cycle).
        post_entry = ep.loc[ep.index > entry_idx]
        exit_candidates = post_entry[pd.to_numeric(post_entry[ROLL_PROGRESS_COL], errors='coerce') >= exit_roll_progress_min]
        exit_idx = exit_candidates.index.min() if not exit_candidates.empty else ep.index.max()

        entry_row = ep.loc[entry_idx]
        exit_row = ep.loc[exit_idx]
        entry_spread = float(pd.to_numeric(entry_row[SPREAD_COL], errors='coerce'))
        exit_spread = float(pd.to_numeric(exit_row[SPREAD_COL], errors='coerce'))
        # direction=+1 (long-front/short-next) profits when basis widens
        # (exit_spread > entry_spread); direction=-1 profits when it narrows.
        pnl_bp = entry_direction * (exit_spread - entry_spread)
        equity_bp += pnl_bp
        equity_points.append((exit_row.name, equity_bp))

        trades.append({
            'episode_id': episode_id,
            'status': 'closed',
            'direction': 'BUY' if entry_direction == 1 else 'SELL',
            'entry_date': entry_idx,
            'exit_date': exit_idx,
            'entry_roll_progress': float(entry_row[ROLL_PROGRESS_COL]),
            'exit_roll_progress': float(pd.to_numeric(exit_row[ROLL_PROGRESS_COL], errors='coerce')) if pd.notna(exit_row[ROLL_PROGRESS_COL]) else np.nan,
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
        'entry_percentile_min': entry_percentile_min,
        'entry_roll_progress_max': entry_roll_progress_max,
        'exit_roll_progress_min': exit_roll_progress_min,
    }
