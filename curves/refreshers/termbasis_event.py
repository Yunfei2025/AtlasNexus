# -*- coding: utf-8 -*-
"""TermBasisEvent artifact builder -- the roll-progress-gated event-driven

Calendar Spread strategy, run alongside (not in place of) the stationary-MR
``TermBasis`` z-score engine (``curves/generators/stat.py``'s
``compute_futures_stats``). Mirrors ``curves/refreshers/newissue_spreads.py``'s
role and output shape (``{'TermBasisEvent': {'StatInfo': df, 'Spread': df}}``,
the same ``{Prefix}-spds.pkl`` convention ``web/tabs/alpha/data/loaders.py``
already reads) so it plugs into the existing candidate-scoring/dashboard
seams without a new consumer pattern.

Sources directly from ``futures-analytics.pkl`` (built by
``FuturesAnalyticsGenerator``) and the same OI lookup
``StatGenerator.compute_futures_stats`` uses for ``RollProgress`` -- no new
data retrieval, only a different scoring path over data that already exists.
"""
from __future__ import annotations

import os
from typing import Dict

import numpy as np
import pandas as pd

from settings.paths import DIR_INPUT
from settings.futures import FuturesConfig, TermBasisEventConfig
from curves.utils.file import loadPKL, updatePKL
from curves.calibration.termbasis_cohort import (
    EPISODE_ID_COL, ROLL_PROGRESS_COL, SPREAD_COL, START_COL,
    build_episode_frame, segment_episodes, termbasis_percentile_causal,
)
from web.tabs.alpha.backtest.engine_termbasis_event import run_termbasis_event_backtest

from utils.log_window import get_logger
logger = get_logger(__name__)

OUT_FILE = 'TermBasisEvent-spds.pkl'

STAT_INFO_COLUMNS = [
    'ctype', 'front_contract', 'next_contract', 'episode_start_date',
    'roll_progress', 'entry_percentile', 'n_cohort_episodes',
    'term_basis_bp', 'gate', 'direction', 'style', 'data_ready',
]


def _oi_wide() -> pd.DataFrame:
    """Same combine_first(NQ1 -> NQ2 -> NQ3) OI lookup as

    ``StatGenerator.compute_futures_stats`` -- kept in sync deliberately so
    TermBasisEvent's roll_progress matches the stationary-MR engine's
    RollProgress exactly (same OI source, same priority order).
    """
    futures_px = loadPKL(os.path.join(DIR_INPUT, 'futures-px.pkl')) or {}
    buckets = futures_px.get('position', {}) if isinstance(futures_px, dict) else {}
    oi_wide: pd.DataFrame = None
    if isinstance(buckets, dict) and buckets:
        for bucket_df in buckets.values():
            if not isinstance(bucket_df, pd.DataFrame) or bucket_df.empty:
                continue
            bdf = bucket_df.copy()
            bdf.index = pd.DatetimeIndex(bdf.index)
            oi_wide = bdf if oi_wide is None else oi_wide.combine_first(bdf)
    return oi_wide


def _roll_progress(df_full: pd.DataFrame, oi_wide: pd.DataFrame) -> pd.Series:
    if oi_wide is None or 'contract_code' not in df_full.columns:
        return pd.Series(dtype=float)
    front_codes = df_full['contract_code']
    next_codes = df_full.get('next_contract_code')
    if next_codes is None:
        return pd.Series(dtype=float)
    front_oi = pd.Series(
        [oi_wide.at[d, c] if (c in oi_wide.columns and d in oi_wide.index) else np.nan
         for d, c in zip(df_full.index, front_codes)],
        index=df_full.index,
    )
    next_oi = pd.Series(
        [oi_wide.at[d, c] if isinstance(c, str) and c in oi_wide.columns and d in oi_wide.index else np.nan
         for d, c in zip(df_full.index, next_codes)],
        index=df_full.index,
    )
    denom = (front_oi + next_oi).replace(0, np.nan)
    return (next_oi / denom)


def build_episode_frames() -> Dict[str, pd.DataFrame]:
    """One episode frame per ctype (T/TF/TS/TL), from futures-analytics.pkl."""
    analytics = loadPKL(os.path.join(DIR_INPUT, 'futures-analytics.pkl'))
    if not analytics:
        return {}
    oi_wide = _oi_wide()
    out: Dict[str, pd.DataFrame] = {}
    for ctype in FuturesConfig.CONTRACT_TYPES:
        df_full = analytics.get(ctype)
        if not isinstance(df_full, pd.DataFrame) or df_full.empty:
            continue
        roll_progress = _roll_progress(df_full, oi_wide)
        ep_frame = build_episode_frame(df_full, roll_progress)
        if not ep_frame.empty:
            out[ctype] = ep_frame
    return out


def build_stat_info(episode_frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Latest-row live-gate snapshot per ctype: current roll_progress, the

    causal cohort percentile at that stage, and whether the entry/exit gate
    currently fires. `mean`/`vol` are intentionally absent (EventDriven, no
    stable OU mean), same convention as BondNewIssue's build_stat_info.
    """
    rows = {}
    for ctype, ep_frame in episode_frames.items():
        if ep_frame.empty:
            continue
        last = ep_frame.sort_index().iloc[-1]
        episode_id = last[EPISODE_ID_COL]
        roll_progress = last[ROLL_PROGRESS_COL]
        spread = last[SPREAD_COL]
        episodes = segment_episodes(ep_frame)

        gate, direction, pct, n_ep = 'none', None, np.nan, 0
        if pd.notna(roll_progress) and pd.notna(spread):
            if roll_progress <= TermBasisEventConfig.ENTRY_ROLL_PROGRESS_MAX:
                score = termbasis_percentile_causal(
                    episodes, episode_id, float(roll_progress), float(spread),
                    roll_progress_tolerance=TermBasisEventConfig.ROLL_PROGRESS_TOLERANCE,
                    min_episodes=TermBasisEventConfig.MIN_COHORT_EPISODES,
                )
                pct, n_ep = score['percentile'], score['n_episodes']
                if pct is not None and not pd.isna(pct):
                    if pct <= TermBasisEventConfig.ENTRY_PERCENTILE_MAX:
                        gate, direction = 'entry', 'BUY'
                    elif pct >= TermBasisEventConfig.ENTRY_PERCENTILE_MIN:
                        gate, direction = 'entry', 'SELL'
            elif roll_progress >= TermBasisEventConfig.EXIT_ROLL_PROGRESS_MIN:
                gate = 'exit'

        front, next_ = episode_id if isinstance(episode_id, tuple) else (None, None)
        rows[ctype] = {
            'ctype': ctype, 'front_contract': front, 'next_contract': next_,
            'episode_start_date': last.get(START_COL),
            'roll_progress': roll_progress, 'entry_percentile': pct,
            'n_cohort_episodes': n_ep, 'term_basis_bp': spread,
            'gate': gate, 'direction': direction,
            'style': 'EventDriven', 'data_ready': True,
        }
    if not rows:
        return pd.DataFrame(columns=STAT_INFO_COLUMNS)
    return pd.DataFrame(rows).T


def build_spread_panel(episode_frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Date x ctype term_basis_bp panel -- the continuous display series

    (each ctype's column is stitched across its own episodes, same as
    stat.py's existing TermBasis Spread, for chart/candidate-list continuity).
    Episode-level gating detail (roll_progress, percentile, gate) lives in
    StatInfo/backtest trades, not this panel.
    """
    cols = {}
    for ctype, ep_frame in episode_frames.items():
        if ep_frame.empty:
            continue
        s = pd.to_numeric(ep_frame[SPREAD_COL], errors='coerce').dropna()
        if not s.empty:
            cols[ctype] = s
    if not cols:
        return pd.DataFrame()
    return pd.DataFrame(cols).sort_index()


def build_backtests(episode_frames: Dict[str, pd.DataFrame]) -> Dict[str, dict]:
    """Per-ctype run_termbasis_event_backtest results, for the Backtest tab."""
    return {
        ctype: run_termbasis_event_backtest(ep_frame)
        for ctype, ep_frame in episode_frames.items()
        if not ep_frame.empty
    }


def refresh_termbasis_event(update: bool = True) -> Dict[str, Dict[str, pd.DataFrame]]:
    """Build/persist TermBasisEvent-spds.pkl from futures-analytics.pkl."""
    episode_frames = build_episode_frames()
    stat_info = build_stat_info(episode_frames)
    spread_panel = build_spread_panel(episode_frames)
    result = {'TermBasisEvent': {'StatInfo': stat_info, 'Spread': spread_panel}}

    if update:
        out_path = os.path.join(DIR_INPUT, OUT_FILE)
        updatePKL(result, out_path, rewrite=True)

    return result


def main():
    try:
        result = refresh_termbasis_event(update=True)
        n = len(result.get('TermBasisEvent', {}).get('StatInfo', []))
        logger.info("TermBasisEvent-spds.pkl refreshed: %d active ctype(s).", n)
    except Exception as e:
        logger.error("Error refreshing TermBasisEvent spreads: %s", e)
        raise


if __name__ == '__main__':
    main()
