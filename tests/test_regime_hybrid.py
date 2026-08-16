import numpy as np
import pandas as pd

from curves.calibration.regime import (
    _variance_ratio,
    compute_regime_features,
    _hurst_null_mean,
    _efficiency_ratio_null_mean,
)
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


def test_variance_ratio_is_unbiased_on_iid_noise():
    # Lo & MacKinlay (1988): VR(k) should average ~1.0 on white noise, not the
    # ~0.72 the naive rolling(k).sum().var()/(k*var()) estimator produced.
    rng = np.random.default_rng(42)
    vrs = [
        _variance_ratio(pd.Series(rng.standard_normal(60)), 5)
        for _ in range(500)
    ]
    assert 0.85 < float(np.mean(vrs)) < 1.15


def test_regime_classifier_is_unbiased_on_random_walk():
    # A pure random walk carries no trend/mean-reversion signal, so the
    # classifier's net vote should not be systematically lopsided. Before the
    # fix, ER/VR/Hurst thresholds were biased and produced 'mean_reverting'
    # on a random walk roughly 60% of the time with a mean vote near -1.25.
    rng = np.random.default_rng(7)
    scores = []
    labels = []
    for _ in range(300):
        s = pd.Series(np.cumsum(rng.standard_normal(200)))
        feat = compute_regime_features(s, window=60)
        scores.append(feat['regime_score'])
        labels.append(feat['regime'])

    mean_score = float(np.mean(scores))
    assert abs(mean_score) < 0.4, f"classifier is biased on white noise: mean regime_score={mean_score:.3f}"

    mr_share = labels.count('mean_reverting') / len(labels)
    trend_share = labels.count('trending') / len(labels)
    assert abs(mr_share - trend_share) < 0.35, (
        f"label distribution skewed on white noise: mean_reverting={mr_share:.2f} trending={trend_share:.2f}"
    )


def test_hurst_and_efficiency_ratio_nulls_shrink_toward_neutral_with_window():
    # Both nulls should sit close to the "no signal" value and the efficiency
    # ratio null should shrink as the window grows (per sqrt(2/(pi*w))).
    assert 0.5 <= _hurst_null_mean(60) < 0.55
    assert 0.5 <= _hurst_null_mean(250) < 0.55
    assert _efficiency_ratio_null_mean(250) < _efficiency_ratio_null_mean(60)