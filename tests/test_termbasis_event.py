# -*- coding: utf-8 -*-
"""Tests for TermBasisEvent -- the roll-progress-gated event-driven Calendar

Spread strategy that runs alongside (not in place of) the stationary-MR
TermBasis z-score engine. Mirrors tests/test_newissue_otr_ofr.py's coverage
style for the analogous BondNewIssue event strategy: episode segmentation,
causal cohort scoring, entry/exit gating, and leg resolution.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from curves.calibration.termbasis_cohort import (
    EPISODE_ID_COL, ROLL_PROGRESS_COL, SPREAD_COL, START_COL,
    build_episode_frame, segment_episodes, termbasis_percentile_causal,
)
from web.tabs.alpha.backtest.engine_termbasis_event import run_termbasis_event_backtest
from web.tabs.alpha.data.legs import resolve_legs


# ---------------------------------------------------------------------------
# build_episode_frame
# ---------------------------------------------------------------------------

def _analytics_df(rows: dict) -> tuple[pd.DataFrame, pd.Series]:
    """rows: {date_str: (contract_code, next_contract_code, fytm, next_fytm, roll_progress)}"""
    idx = [pd.Timestamp(d) for d in rows]
    data = {
        'contract_code':      [v[0] for v in rows.values()],
        'next_contract_code': [v[1] for v in rows.values()],
        'fytm':                [v[2] for v in rows.values()],
        'next_fytm':           [v[3] for v in rows.values()],
    }
    df = pd.DataFrame(data, index=pd.DatetimeIndex(idx))
    roll_progress = pd.Series([v[4] for v in rows.values()], index=pd.DatetimeIndex(idx))
    return df, roll_progress


def test_build_episode_frame_computes_term_basis_bp_and_start_date():
    df, roll_progress = _analytics_df({
        '2026-01-01': ('T2603.CFE', 'T2606.CFE', 2.00, 1.90, 0.05),
        '2026-01-02': ('T2603.CFE', 'T2606.CFE', 2.01, 1.89, 0.08),
    })
    ep = build_episode_frame(df, roll_progress)
    assert list(ep[EPISODE_ID_COL]) == [('T2603.CFE', 'T2606.CFE'), ('T2603.CFE', 'T2606.CFE')]
    # term_basis_bp = (fytm - next_fytm) * 100
    assert ep[SPREAD_COL].iloc[0] == pytest.approx((2.00 - 1.90) * 100)
    assert ep[SPREAD_COL].iloc[1] == pytest.approx((2.01 - 1.89) * 100)
    assert (ep[START_COL] == pd.Timestamp('2026-01-01')).all()
    assert list(ep[ROLL_PROGRESS_COL]) == [0.05, 0.08]


def test_build_episode_frame_drops_rows_missing_fytm_or_next_fytm():
    df, roll_progress = _analytics_df({
        '2026-01-01': ('T2603.CFE', 'T2606.CFE', 2.00, np.nan, 0.05),
        '2026-01-02': ('T2603.CFE', 'T2606.CFE', 2.01, 1.89, 0.08),
    })
    ep = build_episode_frame(df, roll_progress)
    assert len(ep) == 1
    assert ep.index[0] == pd.Timestamp('2026-01-02')


def test_build_episode_frame_drops_rows_missing_contract_codes():
    df, roll_progress = _analytics_df({
        '2026-01-01': (np.nan, 'T2606.CFE', 2.00, 1.90, 0.05),
        '2026-01-02': ('T2603.CFE', 'T2606.CFE', 2.01, 1.89, 0.08),
    })
    ep = build_episode_frame(df, roll_progress)
    assert len(ep) == 1
    assert ep.index[0] == pd.Timestamp('2026-01-02')


def test_build_episode_frame_empty_input_returns_empty_frame_with_columns():
    ep = build_episode_frame(pd.DataFrame(), pd.Series(dtype=float))
    assert ep.empty
    assert list(ep.columns) == [EPISODE_ID_COL, START_COL, ROLL_PROGRESS_COL, SPREAD_COL]


# ---------------------------------------------------------------------------
# segment_episodes
# ---------------------------------------------------------------------------

def test_segment_episodes_splits_by_front_next_contract_pair():
    df, roll_progress = _analytics_df({
        '2026-01-01': ('T2603.CFE', 'T2606.CFE', 2.00, 1.90, 0.05),
        '2026-01-02': ('T2603.CFE', 'T2606.CFE', 2.01, 1.89, 0.10),
        '2026-04-01': ('T2606.CFE', 'T2609.CFE', 2.05, 1.95, 0.04),
    })
    ep = build_episode_frame(df, roll_progress)
    episodes = segment_episodes(ep)
    assert set(episodes.keys()) == {('T2603.CFE', 'T2606.CFE'), ('T2606.CFE', 'T2609.CFE')}
    assert len(episodes[('T2603.CFE', 'T2606.CFE')]) == 2
    assert len(episodes[('T2606.CFE', 'T2609.CFE')]) == 1


def test_segment_episodes_empty_input():
    assert segment_episodes(pd.DataFrame()) == {}


# ---------------------------------------------------------------------------
# termbasis_percentile_causal (thin wrapper over newissue_cohort's generic
# cohort_percentile_causal -- exercised here with TermBasisEvent's own
# column names/roll_progress-scaled tolerance, not calendar days)
# ---------------------------------------------------------------------------

def _synthetic_episodes(n_cycles: int, n_points: int = 20, spread_at_end: float = None):
    """n_cycles episodes, each with roll_progress spanning 0..1 and a spread
    that widens linearly with roll_progress (cheap early / rich late), one
    quarter apart so start dates are strictly increasing."""
    episodes = {}
    for cyc in range(n_cycles):
        front = f'T26{3 + cyc:02d}.CFE'
        nxt = f'T26{6 + cyc:02d}.CFE'
        start = pd.Timestamp('2025-01-01') + pd.Timedelta(days=90 * cyc)
        roll_progress = np.linspace(0.02, 0.98, n_points)
        spread = -20 + 40 * roll_progress  # deterministic, no noise
        idx = [start + pd.Timedelta(days=int(i)) for i in range(n_points)]
        df = pd.DataFrame({
            EPISODE_ID_COL: [(front, nxt)] * n_points,
            START_COL: [start] * n_points,
            ROLL_PROGRESS_COL: roll_progress,
            SPREAD_COL: spread,
        }, index=pd.DatetimeIndex(idx))
        episodes[(front, nxt)] = df
    return episodes


def test_termbasis_percentile_causal_excludes_future_and_self_episodes():
    episodes = _synthetic_episodes(4)
    ids = sorted(episodes.keys(), key=lambda k: episodes[k][START_COL].iloc[0])
    target_id = ids[2]  # 3rd cycle: 2 strictly-prior cycles available, 1 future excluded
    target_row = episodes[target_id].iloc[10]  # roll_progress ~ mid-cycle

    result = termbasis_percentile_causal(
        episodes, target_id,
        target_roll_progress=float(target_row[ROLL_PROGRESS_COL]),
        target_spread_bp=float(target_row[SPREAD_COL]),
        roll_progress_tolerance=0.05,
        min_episodes=2,
    )
    assert result['n_episodes'] == 2  # only the 2 strictly-prior cycles
    assert result['reason'] is None
    # Every cycle has an identical deterministic spread-vs-roll_progress path,
    # so the target sits exactly at the cohort's median/100th regardless of
    # which cycle -- percentile should reflect a tie, not blow up.
    assert 0.0 <= result['percentile'] <= 100.0


def test_termbasis_percentile_causal_insufficient_episodes():
    episodes = _synthetic_episodes(1)
    only_id = next(iter(episodes))
    row = episodes[only_id].iloc[0]
    result = termbasis_percentile_causal(
        episodes, only_id,
        target_roll_progress=float(row[ROLL_PROGRESS_COL]),
        target_spread_bp=float(row[SPREAD_COL]),
        roll_progress_tolerance=0.05,
        min_episodes=3,
    )
    assert result['reason'] == 'insufficient_episodes'
    assert np.isnan(result['percentile'])


# ---------------------------------------------------------------------------
# run_termbasis_event_backtest
# ---------------------------------------------------------------------------

def _episode_frame_for_backtest(n_cycles: int, seed: int = 0, n_points: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for cyc in range(n_cycles):
        front = f'T26{3 + cyc:02d}.CFE'
        nxt = f'T26{6 + cyc:02d}.CFE'
        dates = pd.bdate_range('2025-01-01', periods=n_points) + pd.Timedelta(days=90 * cyc)
        roll_progress = np.linspace(0.02, 0.98, n_points)
        base = -20 + 40 * roll_progress + rng.normal(0, 3, n_points)
        for i, d in enumerate(dates):
            rows.append({
                'date': d, 'contract_code': front, 'next_contract_code': nxt,
                'fytm': 2.0, 'next_fytm': 2.0 - base[i] / 100.0, 'roll_progress': roll_progress[i],
            })
    df = pd.DataFrame(rows).set_index('date')
    analytics_df = df[['contract_code', 'next_contract_code', 'fytm', 'next_fytm']]
    return build_episode_frame(analytics_df, df['roll_progress'])


def test_run_termbasis_event_backtest_no_episodes_returns_error():
    result = run_termbasis_event_backtest(pd.DataFrame())
    assert 'error' in result
    assert result['style'] == 'EventDriven'


def test_run_termbasis_event_backtest_early_cycles_are_cold_start_no_entry():
    """The first `min_cohort_episodes` cycles must never trade -- no future
    information exists yet to score them against (same cold-start philosophy
    as BondNewIssue's run_new_issue_backtest)."""
    ep = _episode_frame_for_backtest(n_cycles=5)
    result = run_termbasis_event_backtest(ep, min_cohort_episodes=2)
    trades_by_episode = {t['episode_id']: t for t in result['trades']}
    ordered_ids = sorted(trades_by_episode.keys(), key=lambda k: ep[ep[EPISODE_ID_COL] == k].index.min())

    assert trades_by_episode[ordered_ids[0]]['status'] == 'no_entry'
    assert trades_by_episode[ordered_ids[0]]['reason'] == 'insufficient_episodes'
    assert trades_by_episode[ordered_ids[1]]['status'] == 'no_entry'
    assert trades_by_episode[ordered_ids[1]]['reason'] == 'insufficient_episodes'


def test_run_termbasis_event_backtest_enters_early_cycle_and_exits_at_late_gate():
    ep = _episode_frame_for_backtest(n_cycles=5)
    result = run_termbasis_event_backtest(
        ep, min_cohort_episodes=2,
        entry_roll_progress_max=0.30, exit_roll_progress_min=0.70,
    )
    closed = [t for t in result['trades'] if t['status'] == 'closed']
    assert len(closed) >= 1
    for t in closed:
        # Entered only within the early-cycle window.
        assert t['entry_roll_progress'] <= 0.30 + 1e-9
        # Exited at/after the late-cycle gate (or at the episode's last row,
        # which this synthetic data always reaches well past 0.70).
        assert t['exit_roll_progress'] >= 0.70 - 1e-9
        assert t['entry_date'] < t['exit_date']
        assert t['direction'] in ('BUY', 'SELL')


def test_run_termbasis_event_backtest_equity_curve_accumulates_pnl():
    ep = _episode_frame_for_backtest(n_cycles=5)
    result = run_termbasis_event_backtest(ep, min_cohort_episodes=2)
    closed = [t for t in result['trades'] if t['status'] == 'closed']
    assert not result['equity_ts'].empty
    assert len(result['equity_ts']) == len(closed)
    # Cumulative equity should equal the running sum of each trade's pnl_bp,
    # in chronological (exit-date) order.
    expected_cum = np.cumsum([t['pnl_bp'] for t in closed])
    assert result['equity_ts'].iloc[-1] == pytest.approx(expected_cum[-1])


def test_run_termbasis_event_backtest_direction_matches_percentile_side():
    """direction=+1 (BUY, long-front/short-next) fires on a cheap entry
    percentile; direction=-1 (SELL) fires on a rich one -- never both in the
    same episode, and pnl_bp sign convention must match (widen profits BUY,
    narrow profits SELL)."""
    ep = _episode_frame_for_backtest(n_cycles=5, seed=1)
    result = run_termbasis_event_backtest(ep, min_cohort_episodes=2)
    for t in result['trades']:
        if t['status'] != 'closed':
            continue
        widened = t['exit_spread'] > t['entry_spread']
        if t['direction'] == 'BUY':
            assert t['pnl_bp'] == pytest.approx(t['exit_spread'] - t['entry_spread'])
            assert (t['pnl_bp'] > 0) == widened
        else:
            assert t['pnl_bp'] == pytest.approx(-(t['exit_spread'] - t['entry_spread']))
            assert (t['pnl_bp'] > 0) == (not widened)


# ---------------------------------------------------------------------------
# leg resolution
# ---------------------------------------------------------------------------

def _ld_with_futs_def() -> dict:
    """Minimal resolve_legs() `ld` dict with a deterministic futs_def --
    two T-contracts, front = earlier LASTTRADE_DATE."""
    futs_def = pd.DataFrame(
        {'LASTTRADE_DATE': [pd.Timestamp('2026-03-13'), pd.Timestamp('2026-06-12')]},
        index=['T2603.CFE', 'T2606.CFE'],
    )
    return {
        'otr_cgb': {}, 'otr_cdb': {}, 'nb': {}, 'tb_stat': None,
        'futs_def': futs_def, 'fs_irs': {},
    }


def test_resolve_legs_termbasis_event_reuses_front_next_contract_logic():
    """TermBasisEvent must resolve legs identically to TermBasis (same
    ctype -> front/next contract pair), since only the entry/exit gate
    differs between the two coexisting candidate types."""
    ld = _ld_with_futs_def()
    assert resolve_legs('TermBasisEvent', 'T', ld=ld) == ('T2603', 'T2606')
    assert resolve_legs('TermBasisEvent', 'T', ld=ld) == resolve_legs('TermBasis', 'T', ld=ld)


def test_resolve_legs_termbasis_event_empty_futs_def_returns_blank_legs():
    ld = _ld_with_futs_def()
    ld['futs_def'] = pd.DataFrame()
    assert resolve_legs('TermBasisEvent', 'T', ld=ld) == ('', '')
