import numpy as np
import pandas as pd

from multiasset.pca_analyzer import CN_IR_TENORS
from multiasset.rolldown import (
    cn_loading_matrix,
    carry_rolldown,
    select_t_star,
    tilt_weights,
    factor_drift,
    run_rolldown_tilt,
)

# A synthetic upward-sloping, concave curve modeled on the real CGB shape
# (2026-09-16): steep through the belly (10Y->20Y), then flat 20Y->30Y, so
# 20Y earns strong carry AND roll-down while 30Y's roll collapses.
CURVE = pd.Series({'1Y': 1.23, '2Y': 1.24, '5Y': 1.41, '10Y': 1.69, '20Y': 2.13, '30Y': 2.14})


def test_carry_rolldown_favors_belly_over_flat_long_end():
    cr = carry_rolldown(CURVE)

    assert list(cr.index) == list(CN_IR_TENORS)
    # funding tenor has zero carry/roll against itself
    assert np.isclose(cr.loc['1Y', 'carry_bp'], 0.0)
    # 30Y has similar carry to 20Y but the curve is flat 20Y->30Y, so its
    # roll is much smaller
    assert cr.loc['30Y', 'roll_bp'] < cr.loc['20Y', 'roll_bp']
    assert cr.loc['20Y', 'total_bp'] > cr.loc['30Y', 'total_bp']


def test_select_t_star_picks_best_risk_adjusted_tenor():
    cr = carry_rolldown(CURVE)
    t_star = select_t_star(cr, level_vol=0.01)
    assert t_star == '20Y'


def test_tilt_preserves_level_exposure_exactly():
    B = cn_loading_matrix()
    tenors = list(CN_IR_TENORS)
    e_star = np.array([60.0, 90.0, 150.0])
    w_baseline = pd.Series(np.linalg.pinv(B.T) @ e_star, index=tenors)

    w_tilted = tilt_weights(w_baseline, t_star='20Y', tilt_pct=0.20)

    assert w_tilted['20Y'] > w_baseline['20Y']

    drift = factor_drift(w_tilted, B, e_star, tenors=tuple(tenors))
    assert np.isclose(drift.loc['Level', 'drift'], 0.0, atol=1e-6)
    # Slope/Curvature are not level-loaded equally, so some drift is expected
    assert abs(drift.loc['Slope', 'drift']) > 0.0


def test_run_rolldown_tilt_end_to_end_matches_manual_pipeline():
    B = cn_loading_matrix()
    tenors = list(CN_IR_TENORS)
    e_star = np.array([60.0, 90.0, 150.0])
    w_baseline = pd.Series(np.linalg.pinv(B.T) @ e_star, index=tenors)

    result = run_rolldown_tilt(CURVE, w_baseline, e_star, level_vol=0.01, tilt_pct=0.20)

    assert result['t_star'] == '20Y'
    assert result['tilt_pct'] == 0.20
    assert set(result['w_tilted'].keys()) == set(tenors)
    assert result['w_tilted']['20Y'] > result['w_baseline']['20Y']
    assert np.isclose(result['factor_drift']['Level']['drift'], 0.0, atol=1e-6)
