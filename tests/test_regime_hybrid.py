import pandas as pd

from curves.calibration.regime import _variance_ratio
from web.tabs.alpha.backtest.engine_hybrid import _stabilize_regime_scores


def test_regime_switch_requires_persistent_opposite_evidence():
    scores = pd.Series(
        [-0.75] * 5 + [0.75] * 4 + [0.0] + [0.75] * 5,
        index=pd.date_range('2026-01-01', periods=15, freq='D'),
    )

    regimes = _stabilize_regime_scores(scores, persistence=5)

    assert regimes.iloc[4] == 'mean_reverting'
    assert regimes.iloc[8] == 'mean_reverting'
    assert regimes.iloc[-1] == 'trending'


def test_regime_exit_requires_persistent_loss_of_evidence():
    scores = pd.Series(
        [0.75] * 5 + [0.0] * 4 + [0.0],
        index=pd.date_range('2026-01-01', periods=10, freq='D'),
    )

    regimes = _stabilize_regime_scores(scores, persistence=5)

    assert regimes.iloc[8] == 'trending'
    assert regimes.iloc[-1] == 'uncertain'


def test_variance_ratio_distinguishes_persistent_from_alternating_changes():
    persistent = pd.Series([1.0] * 40)
    alternating = pd.Series([1.0, -1.0] * 20)

    assert _variance_ratio(persistent, 5) == 1.0
    assert _variance_ratio(alternating, 5) < 0.25