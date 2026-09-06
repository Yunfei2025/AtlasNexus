"""Tests for curves/calibration/residual_stats.py (item 3.3,
docs/dev/affine-curve-improvement-plan.md).
"""
import numpy as np
import pandas as pd

from curves.calibration.residual_stats import (
    compute_residual_stats,
    compute_residual_stats_panel,
)


def _simulate_ou(n, theta, kappa, sigma, seed=0):
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    x[0] = theta
    for t in range(1, n):
        x[t] = x[t - 1] + kappa * (theta - x[t - 1]) + sigma * rng.standard_normal()
    dates = pd.date_range('2026-01-01', periods=n, freq='D')
    return pd.Series(x, index=dates)


def test_recovers_ou_mean_and_halflife_on_stationary_series():
    theta, kappa = 0.05, 0.3
    residual = _simulate_ou(200, theta, kappa, sigma=0.01, seed=0)
    out = compute_residual_stats(residual)

    assert out['stationary'] == 'YES'
    assert abs(out['ou_mean'] - theta) < 0.01
    true_halflife = np.log(2) / kappa
    assert abs(out['halflife'] - true_halflife) < 1.0
    assert np.isfinite(out['zscore'])


def test_mean_is_fixed_ou_mean_not_a_rolling_mean():
    """The OU mean should not chase the series' recent trailing average --
    it's the AR(1)-implied long-run level of the whole fitted window."""
    residual = _simulate_ou(200, theta=0.05, kappa=0.3, sigma=0.01, seed=1)
    out = compute_residual_stats(residual)
    trailing_20_mean = residual.iloc[-20:].mean()
    # OU mean should be closer to the true long-run level (0.05) than to
    # whatever the last 20 observations happen to average (sampling noise).
    assert abs(out['ou_mean'] - 0.05) <= abs(trailing_20_mean - 0.05) + 0.02


def test_too_few_points_returns_all_nan():
    residual = pd.Series([0.01, 0.02, 0.015], index=pd.date_range('2026-01-01', periods=3))
    out = compute_residual_stats(residual, min_points=20)
    assert out['n_obs'] == 3
    assert pd.isna(out['ou_mean'])
    assert pd.isna(out['zscore'])
    assert out['stationary'] is None


def test_empty_series_returns_all_nan():
    out = compute_residual_stats(pd.Series(dtype=float))
    assert out['n_obs'] == 0
    assert pd.isna(out['ou_mean'])


def test_reference_roll_restarts_estimation_from_roll_date():
    """A discontinuous level jump (simulating a curve.reference roll) must
    not be fit as if it were the residual's own dynamics -- item 3.2/3.3
    integration."""
    rng = np.random.default_rng(2)
    n = 100
    dates = pd.date_range('2026-01-01', periods=n, freq='D')
    pre = 0.02 + rng.standard_normal(50) * 0.005
    post = 0.15 + rng.standard_normal(50) * 0.005
    residual = pd.Series(np.concatenate([pre, post]), index=dates)

    roll_date = dates[50]
    events = pd.DataFrame(
        [{'old_bond': 'A', 'new_bond': 'B'}],
        index=pd.MultiIndex.from_tuples([(roll_date, 'Term near 5Y')], names=['date', 'bucket']),
    )

    out_naive = compute_residual_stats(residual)
    out_aware = compute_residual_stats(residual, change_events=events, bucket='Term near 5Y')

    assert out_aware['fit_start'] == roll_date
    assert out_aware['n_obs'] == 49  # strictly after roll_date
    assert abs(out_aware['ou_mean'] - 0.15) < 0.02
    # The naive fit blends both regimes and should be pulled well away from
    # the true post-roll level.
    assert abs(out_naive['ou_mean'] - 0.15) > abs(out_aware['ou_mean'] - 0.15)


def test_no_matching_bucket_in_change_events_ignored_gracefully():
    residual = _simulate_ou(60, 0.05, 0.3, 0.01, seed=3)
    events = pd.DataFrame(
        [{'old_bond': 'A', 'new_bond': 'B'}],
        index=pd.MultiIndex.from_tuples(
            [(residual.index[30], 'Term near 10Y')], names=['date', 'bucket']
        ),
    )
    # bucket doesn't match anything in events -> no restart, same as None.
    out = compute_residual_stats(residual, change_events=events, bucket='Term near 5Y')
    assert out['fit_start'] is None
    assert out['n_obs'] == 60


def test_rolldown_sign_and_magnitude_on_upward_sloping_curve():
    residual = pd.Series(
        0.05 + np.zeros(30), index=pd.date_range('2026-01-01', periods=30)
    ) + np.random.default_rng(4).standard_normal(30) * 0.005

    taus = np.linspace(0.1, 10, 50)
    spot = 1.5 + 0.3 * np.log(1 + taus)
    forward_curve = pd.DataFrame({'SpotRate': spot, 'ForwardRate': spot}, index=taus)

    out = compute_residual_stats(residual, forward_curve=forward_curve, tenor_years=5.0, horizon_years=0.25)

    expected = (np.interp(5.0, taus, spot) - np.interp(4.75, taus, spot)) * 100.0
    assert abs(out['roll_bp'] - expected) < 1e-9
    assert out['roll_bp'] > 0  # upward-sloping curve -> positive rolldown


def test_rolldown_none_when_curve_or_tenor_missing():
    residual = pd.Series(
        0.05 + np.zeros(30), index=pd.date_range('2026-01-01', periods=30)
    )
    out = compute_residual_stats(residual)  # no forward_curve/tenor given
    assert pd.isna(out['roll_bp'])


def test_panel_wrapper_runs_per_bond():
    bonds = ['B1', 'B2']
    dates = pd.date_range('2026-01-01', periods=60)
    residuals = pd.DataFrame({
        'B1': _simulate_ou(60, 0.02, 0.3, 0.01, seed=5).to_numpy(),
        'B2': _simulate_ou(60, 0.08, 0.3, 0.01, seed=6).to_numpy(),
    }, index=dates)

    panel = compute_residual_stats_panel(residuals)
    assert set(panel.index) == set(bonds)
    assert abs(panel.loc['B1', 'ou_mean'] - 0.02) < 0.02
    assert abs(panel.loc['B2', 'ou_mean'] - 0.08) < 0.02
