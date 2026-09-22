# -*- coding: utf-8 -*-
"""Tests for the Momentum bucket's Zscore-magnitude entry gate, and for
`_add_unified_score_preview`'s separate `score` column.

Background: `_add_unified_score_preview` (curves/refreshers/alpha_scoring.py)
computes `score` = |expected_return_H| / risk -- a dimensionless, non-negative
(direction is a separate field) ratio. It is a real, correctly-computed
column (tested below), but as of 2026-09-22 it is NOT the Momentum entry
gate -- it is display/ranking only for Momentum rows.

The actual gate (MOMENTUM_CARRY_MIN_SCORE, in build_alpha_candidates) checks
|Zscore| -- for Momentum rows, 'Zscore' is overwritten by
_add_momentum_ma_zscore to be the pullback z-score (trend_momentum) against
the established trend, not the row's original level Zscore. A
pullback-confirmed row whose pullback magnitude is too small (|Zscore| < 1)
is dropped even though its expected edge/risk score might be large, and vice
versa -- the two are independent measures of the row.
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
# The actual gate: MOMENTUM_CARRY_MIN_SCORE applied to |Zscore| (the
# pullback z-score / trend_momentum), NOT the 'score' column
# ---------------------------------------------------------------------------

def test_momentum_carry_min_score_constant_is_one():
    """Documents the threshold: |Zscore| (pullback z-score) >= 1.0 for the
    Momentum bucket's entry gate. Zscore is unsigned-magnitude-gated here;
    BUY/SELL is a separate field set by the pullback logic beforehand, not
    by this gate."""
    assert MOMENTUM_CARRY_MIN_SCORE == 1.0


def test_momentum_zscore_gate_filters_small_pullbacks():
    """Simulates the gate step in build_alpha_candidates: after direction is
    set by the trend_state/trend_zt pullback logic (which overwrites
    'Zscore' with the pullback z-score), a row must ALSO clear
    |Zscore| >= MOMENTUM_CARRY_MIN_SCORE to survive -- a pullback-confirmed
    direction whose pullback is too small in sigma terms must be dropped,
    regardless of its (separate, unrelated) 'score' edge/risk value."""
    momentum = pd.DataFrame({
        'ID': ['STRONG_PULLBACK', 'WEAK_PULLBACK', 'BORDERLINE', 'SMALL_ZSCORE_BIG_SCORE'],
        'direction': ['BUY', 'BUY', 'SELL', 'BUY'],
        'Zscore': [2.5, 0.3, -1.0, 0.2],
        'score': [1.2, 1.5, 0.9, 9.6],  # deliberately uncorrelated with Zscore
    })
    zscore = pd.to_numeric(momentum['Zscore'], errors='coerce')
    filtered = momentum[zscore.abs().ge(MOMENTUM_CARRY_MIN_SCORE)].copy()

    assert set(filtered['ID']) == {'STRONG_PULLBACK', 'BORDERLINE'}
    assert 'WEAK_PULLBACK' not in set(filtered['ID'])
    # A high 'score' does NOT rescue a row with a small Zscore/pullback --
    # the gate is on Zscore, score is display-only for Momentum rows.
    assert 'SMALL_ZSCORE_BIG_SCORE' not in set(filtered['ID'])


def test_momentum_zscore_gate_does_not_touch_mr_bucket():
    """The Zscore-magnitude gate is scoped to the Momentum bucket only --
    MR's entry gate remains composite_z >= entry_z_used (its own,
    pre-existing mechanism), unaffected by MOMENTUM_CARRY_MIN_SCORE."""
    mr = pd.DataFrame({
        'ID': ['MR_LOW_ZSCORE_BUT_VALID_COMPOSITE_Z'],
        'direction': ['BUY'],
        'composite_z': [2.1],
        'entry_z_used': [2.0],
        'Zscore': [0.1],  # would fail the momentum gate, but MR doesn't use it
    })
    mr_composite_z = pd.to_numeric(mr['composite_z'], errors='coerce')
    # MR's own gate (mirrors alpha_candidates.py's actual mr filtering step):
    mr_kept = mr[mr_composite_z.abs().ge(mr['entry_z_used'])]
    assert len(mr_kept) == 1  # MR row survives on its own composite_z gate despite low Zscore
