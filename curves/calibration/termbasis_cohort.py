# -*- coding: utf-8 -*-
"""TermBasisEvent cohort support — the roll-progress-gated event-driven

Calendar Spread strategy that runs alongside (not in place of) the
stationary-MR ``TermBasis`` z-score engine in ``curves/generators/stat.py``.

Segments a ctype's futures-analytics history into one episode per
front/next-season contract pair (``(contract_code, next_contract_code)``),
directly analogous to how ``curves.calibration.newissue_cohort`` segments a
BondNewIssue universe into one episode per OTR tenure. OI-derived
``roll_progress`` (0..1, next_oi / (front_oi + next_oi); see
``StatGenerator.compute_futures_stats``'s ``RollProgress``) stands in for
``NewIssueConfig``'s calendar-day event age: it is a better axis here
because roll speed varies cycle to cycle while OI migration is the actual
structural driver of the spread, not the calendar.

Scoring itself (the causal, walk-forward cohort percentile) is not
reimplemented here -- ``curves.calibration.newissue_cohort.cohort_percentile_causal``
is fully generic over column names, so it is called directly with
TermBasisEvent's column names. This module only owns episode segmentation
(front/next contract pairs instead of otr_id) and the universe-frame shape
TermBasisEvent needs to feed it.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from curves.calibration.newissue_cohort import (
    MIN_COHORT_EPISODES,
    episode_start_date,
    cohort_percentile_causal,
)

# Column names used throughout TermBasisEvent's episode frames -- passed as
# the start_col/age_col/spread_col args to the generic newissue_cohort helpers.
EPISODE_ID_COL   = 'episode_id'        # (front_contract_code, next_contract_code)
START_COL        = 'episode_start_date'
ROLL_PROGRESS_COL = 'roll_progress'    # stands in for age_col (0..1, not days)
SPREAD_COL       = 'term_basis_bp'     # front_fytm - next_fytm, bp


def build_episode_frame(analytics_df: pd.DataFrame, roll_progress: pd.Series) -> pd.DataFrame:
    """Reshape one ctype's futures-analytics frame + its RollProgress series

    into the episode-keyed frame TermBasisEvent scoring needs: one row per
    date, with ``episode_id`` (front/next contract pair), ``episode_start_date``
    (first date that pair was observed as front/next), ``roll_progress``, and
    ``term_basis_bp`` (fytm - next_fytm, matching stat.py's TermBasis sign
    convention).

    Never fabricates rows -- a date is only included if both fytm and
    next_fytm are present, same as stat.py's existing term_full/term_stats.
    """
    if analytics_df is None or analytics_df.empty:
        return pd.DataFrame(columns=[EPISODE_ID_COL, START_COL, ROLL_PROGRESS_COL, SPREAD_COL])

    df = analytics_df.copy()
    df.index = pd.DatetimeIndex(df.index)

    fytm = pd.to_numeric(df.get('fytm'), errors='coerce')
    next_fytm = pd.to_numeric(df.get('next_fytm'), errors='coerce')
    term_basis_bp = (fytm - next_fytm) * 100.0

    front_code = df.get('contract_code')
    next_code = df.get('next_contract_code')
    if front_code is None or next_code is None:
        return pd.DataFrame(columns=[EPISODE_ID_COL, START_COL, ROLL_PROGRESS_COL, SPREAD_COL])

    episode_id = list(zip(front_code, next_code))

    out = pd.DataFrame({
        EPISODE_ID_COL: episode_id,
        ROLL_PROGRESS_COL: roll_progress.reindex(df.index),
        SPREAD_COL: term_basis_bp,
    }, index=df.index)
    out = out.dropna(subset=[SPREAD_COL])
    out = out[out[EPISODE_ID_COL].map(lambda t: isinstance(t[0], str) and isinstance(t[1], str) and bool(t[0]) and bool(t[1]))]

    # episode_start_date: first date this (front, next) pair appears.
    starts = out.groupby(EPISODE_ID_COL).apply(lambda g: g.index.min())
    out[START_COL] = out[EPISODE_ID_COL].map(starts)
    return out.sort_index()


def segment_episodes(episode_frame: pd.DataFrame) -> Dict[Any, pd.DataFrame]:
    """Split a TermBasisEvent episode frame into one DataFrame per

    (front_contract_code, next_contract_code) pair. Mirrors
    ``newissue_cohort.segment_episodes`` but groups on the tuple episode id
    directly rather than a single id column, since a contract pair (not a
    single bond code) is the natural episode identity here.
    """
    if episode_frame is None or episode_frame.empty or EPISODE_ID_COL not in episode_frame.columns:
        return {}
    episodes: Dict[Any, pd.DataFrame] = {}
    for key_id, group in episode_frame.groupby(EPISODE_ID_COL):
        episodes[key_id] = group.sort_index()
    return episodes


def termbasis_percentile_causal(
    episodes: Dict[Any, pd.DataFrame],
    target_episode_id: Any,
    target_roll_progress: float,
    target_spread_bp: float,
    roll_progress_tolerance: float,
    min_episodes: int = MIN_COHORT_EPISODES,
) -> Dict[str, Any]:
    """TermBasisEvent-flavored wrapper around

    ``newissue_cohort.cohort_percentile_causal``, fixing the column names to
    TermBasisEvent's episode-frame shape. Purely a naming convenience -- the
    causal-cohort logic (strictly-prior episodes only, nearest-roll_progress
    match within tolerance, no lookahead) is unchanged.
    """
    return cohort_percentile_causal(
        episodes, target_episode_id, target_roll_progress, target_spread_bp,
        age_tolerance_days=roll_progress_tolerance,
        min_episodes=min_episodes,
        start_col=START_COL, age_col=ROLL_PROGRESS_COL, spread_col=SPREAD_COL,
    )
