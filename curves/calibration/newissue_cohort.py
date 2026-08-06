# -*- coding: utf-8 -*-
"""Phase 4 (candidate scoring) support for docs/dev/tbondcurve-30y-otr-ofr-plan.md.

Segments a per-(asset_class, tenor_bucket) OTR/OFR universe DataFrame (as
produced by curves.calibration.otr_ofr_universe) into issuance episodes keyed
by `otr_id`, and scores a live/backtest episode against its *causal* cohort:
only episodes whose OTR was selected strictly before the target episode's OTR
are used ("leave each issuance out of its own training sample", per the plan).

This module never mixes predecessor/successor pairs into one continuous
z-score history — each episode is scored independently, in event time
(`event_age_days`), against prior episodes only.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

MIN_COHORT_EPISODES = 3


def segment_episodes(universe_df: pd.DataFrame) -> Dict[Any, pd.DataFrame]:
    """Split a universe DataFrame into one DataFrame per episode (otr_id).

    Each bond can only ever be `otr_id` once in its life (it rolls off once
    superseded), so grouping by `otr_id` recovers each contiguous episode
    without relying on gap detection.
    """
    if universe_df is None or universe_df.empty or 'otr_id' not in universe_df.columns:
        return {}
    episodes: Dict[Any, pd.DataFrame] = {}
    for otr_id, group in universe_df.dropna(subset=['otr_id']).groupby('otr_id'):
        episodes[otr_id] = group.sort_index()
    return episodes


def episode_start_date(episode_df: pd.DataFrame) -> Optional[pd.Timestamp]:
    if episode_df is None or episode_df.empty:
        return None
    start = episode_df['otr_start_date'].iloc[0]
    return pd.Timestamp(start) if pd.notna(start) else None


def cohort_percentile_causal(
    episodes: Dict[Any, pd.DataFrame],
    target_otr_id: Any,
    target_age_days: int,
    target_spread: float,
    age_tolerance_days: int = 5,
    min_episodes: int = MIN_COHORT_EPISODES,
) -> Dict[str, Any]:
    """Percentile rank of `target_spread` within the causal cohort's spread
    distribution at approximately the same event age.

    "Causal" = only episodes whose OTR start date is strictly before the
    target episode's OTR start date are used — matches or later episodes
    (including the target itself) are excluded, so no future-episode
    information leaks into the score (true walk-forward).
    """
    if pd.isna(target_spread):
        return {'percentile': np.nan, 'n_episodes': 0, 'reason': 'missing_target_spread'}

    target_episode = episodes.get(target_otr_id)
    target_start = episode_start_date(target_episode) if target_episode is not None else None
    if target_start is None:
        return {'percentile': np.nan, 'n_episodes': 0, 'reason': 'unknown_target_episode'}

    matched_values = []
    for otr_id, ep_df in episodes.items():
        if otr_id == target_otr_id:
            continue
        ep_start = episode_start_date(ep_df)
        if ep_start is None or ep_start >= target_start:
            continue  # not strictly prior — excluded to avoid lookahead
        if 'event_age_days' not in ep_df.columns or 'spread' not in ep_df.columns:
            continue
        age_diff = (pd.to_numeric(ep_df['event_age_days'], errors='coerce') - target_age_days).abs()
        if age_diff.empty:
            continue
        nearest_idx = age_diff.idxmin()
        if age_diff.loc[nearest_idx] > age_tolerance_days:
            continue
        value = pd.to_numeric(ep_df.loc[nearest_idx, 'spread'], errors='coerce')
        if pd.notna(value):
            matched_values.append(float(value))

    n_episodes = len(matched_values)
    if n_episodes < min_episodes:
        return {'percentile': np.nan, 'n_episodes': n_episodes, 'reason': 'insufficient_episodes'}

    arr = np.asarray(matched_values, dtype=float)
    percentile = float((arr <= target_spread).sum()) / n_episodes * 100.0
    return {'percentile': percentile, 'n_episodes': n_episodes, 'reason': None}
