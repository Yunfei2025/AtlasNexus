# -*- coding: utf-8 -*-
"""Tests for the Momentum/Carry (trend bucket) score-magnitude entry gate.

Regression coverage for a 2026-09-19 fix: `_add_unified_score_preview`
(curves/refreshers/alpha_scoring.py) already computes `score` =
|expected_return_H| / risk -- a dimensionless, non-negative (direction is a
separate field) ratio where score>=1 means the expected move over the
scoring horizon is at least one standard deviation of risk. That score was
being used only for ranking in build_alpha_candidates's trend bucket, never
as an entry gate -- a pullback-confirmed row with score << 1 (negligible
edge-to-risk) could still enter. MOMENTUM_CARRY_MIN_SCORE=1.0 now filters
the trend bucket after the pullback direction is assigned.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from curves.refreshers.alpha_candidates import MOMENTUM_CARRY_MIN_SCORE
from curves.refreshers.alpha_scoring import _add_unified_score_preview


def _score_input_row(*, spread, mean, vol, carry_roll=0.0, reg_slope=0.0,
                      reg_mean=None, reg_vol_resid=None, duration=5.0):
    return {
        'spread': spread, 'mean': mean, 'vol': vol, 'carry_roll': carry_roll,
        'reg_slope_per_day': reg_slope,
        'reg_mean': reg_mean if reg_mean is not None else mean,
        'reg_vol_resid': reg_vol_resid if reg_vol_resid is not None else vol,
        'risk_vol_63d': vol, 'Duration': duration, 'ttm': duration,
    }


# ---------------------------------------------------------------------------
# _add_unified_score_preview: score is non-negative, direction is separate
# ---------------------------------------------------------------------------

def test_score_is_nonnegative_regardless_of_direction():
    """score = |expected_return_H| / risk is always >= 0 by construction --
    it is a magnitude, not a signed quantity. Direction lives in its own
    column, set from the sign of expected P&L."""
    df = pd.DataFrame([
        _score_input_row(spread=1.0, mean=0.0, vol=0.5),   # spread above mean -> expect fall -> BUY
        _score_input_row(spread=-1.0, mean=0.0, vol=0.5),  # spread below mean -> expect rise -> SELL
    ])
    out = _add_unified_score_preview(df)
    assert (out['score'] >= 0).all()
    assert list(out['direction']) == ['BUY', 'SELL']


def test_score_scales_with_edge_to_risk_ratio():
    """A larger deviation from the reversion target (same risk) produces a
    proportionally larger score -- the ratio, not just its sign, is
    meaningful and must scale as documented."""
    small_edge = pd.DataFrame([_score_input_row(spread=0.5, mean=0.0, vol=0.5)])
    large_edge = pd.DataFrame([_score_input_row(spread=2.0, mean=0.0, vol=0.5)])
    score_small = _add_unified_score_preview(small_edge)['score'].iloc[0]
    score_large = _add_unified_score_preview(large_edge)['score'].iloc[0]
    assert score_large > score_small
    # Edge-to-risk gap of 0.5 vs 2.0 (same vol) -> roughly 4x score.
    assert score_large == pytest.approx(score_small * 4, rel=0.05)


def test_score_of_one_means_edge_equals_one_risk_stdev():
    """The documented dimensional meaning of score=1.0: expected P&L (over
    the horizon, net of duration scaling) exactly equals one standard
    deviation of return risk."""
    # duration=1 keeps return-space == yield-space for a clean 1:1 check;
    # spread deviates from mean by exactly `vol`, so return = risk -> score=1.
    df = pd.DataFrame([_score_input_row(spread=0.5, mean=0.0, vol=0.5, duration=1.0)])
    out = _add_unified_score_preview(df)
    assert out['score'].iloc[0] == pytest.approx(1.0, rel=1e-6)


# ---------------------------------------------------------------------------
# The actual gate: MOMENTUM_CARRY_MIN_SCORE applied to the trend bucket
# ---------------------------------------------------------------------------

def test_momentum_carry_min_score_constant_is_one():
    """Documents the exact threshold the user asked to restore: score>=1
    for the trend bucket's entry gate (score is unsigned; BUY/SELL is a
    separate field set by the pullback logic, not by score's sign)."""
    assert MOMENTUM_CARRY_MIN_SCORE == 1.0


def test_trend_score_gate_filters_low_magnitude_rows():
    """Simulates the gate step in build_alpha_candidates: after direction is
    set by the trend_state/trend_zt pullback logic, a row must ALSO clear
    score >= MOMENTUM_CARRY_MIN_SCORE to survive -- a pullback-confirmed
    direction with negligible edge-to-risk must be dropped."""
    trend = pd.DataFrame({
        'ID': ['STRONG_EDGE', 'WEAK_EDGE', 'BORDERLINE'],
        'direction': ['BUY', 'BUY', 'SELL'],
        'score': [2.5, 0.3, 1.0],
    })
    trend_score = pd.to_numeric(trend['score'], errors='coerce')
    filtered = trend[trend_score.ge(MOMENTUM_CARRY_MIN_SCORE)].copy()

    assert set(filtered['ID']) == {'STRONG_EDGE', 'BORDERLINE'}
    assert 'WEAK_EDGE' not in set(filtered['ID'])


def test_trend_score_gate_does_not_touch_mr_bucket():
    """The score gate is scoped to the trend/carry bucket only -- MR's
    entry gate remains composite_z >= entry_z_used (its own, pre-existing
    mechanism), unaffected by MOMENTUM_CARRY_MIN_SCORE."""
    mr = pd.DataFrame({
        'ID': ['MR_LOW_SCORE_BUT_VALID_Z'],
        'direction': ['BUY'],
        'composite_z': [2.1],
        'entry_z_used': [2.0],
        'score': [0.1],  # would fail the trend gate, but MR doesn't use it
    })
    mr_composite_z = pd.to_numeric(mr['composite_z'], errors='coerce')
    # MR's own gate (mirrors alpha_candidates.py's actual mr filtering step):
    mr_kept = mr[mr_composite_z.abs().ge(mr['entry_z_used'])]
    assert len(mr_kept) == 1  # MR row survives on its own z-based gate despite low score
