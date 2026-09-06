"""Tests for weighted factor extraction (item 2.3,
docs/dev/affine-curve-improvement-plan.md F9).
"""
import numpy as np
import pandas as pd
import pytest

from curves.affine.affine import calAffineCov, getAffineFactors
from curves.affine.curve import Curve, quote_quality_weights


def _make_curve_and_inputs(seed=3):
    np.random.seed(seed)
    n_dates = 60
    taus = np.array([0.3, 0.5, 1, 2, 3, 5, 10])
    term = pd.DataFrame(np.tile(taus, (n_dates, 1)))
    level = np.cumsum(np.random.randn(n_dates, len(taus)) * 0.015, axis=0)
    spot = pd.DataFrame(2 + 0.3 * np.log(1 + np.tile(taus, (n_dates, 1))) + level)

    c = Curve(pd.Timestamp('2026-09-05'), 'TBond')
    c.calibrate(term, spot)
    df_bs = pd.Series(spot.iloc[-1].values, index=taus)
    bond_ref = pd.Series([f'b{i}' for i in range(len(taus))], index=taus)
    return c, df_bs, bond_ref


def test_get_affine_factors_none_weights_matches_unweighted():
    c, df_bs, _ = _make_curve_and_inputs()
    x_unweighted = getAffineFactors(df_bs, c.S2, c.gamma, c.mtype, c.caltype)
    x_explicit_equal = getAffineFactors(
        df_bs, c.S2, c.gamma, c.mtype, c.caltype, weights=np.ones(len(df_bs))
    )
    a = np.array(x_unweighted, dtype=float).ravel()
    b = np.array(x_explicit_equal, dtype=float).ravel()
    assert np.allclose(a, b)


def test_get_affine_factors_rejects_bad_weights():
    c, df_bs, _ = _make_curve_and_inputs()
    with pytest.raises(ValueError):
        getAffineFactors(df_bs, c.S2, c.gamma, c.mtype, c.caltype, weights=[1.0, 2.0])  # wrong length
    with pytest.raises(ValueError):
        getAffineFactors(df_bs, c.S2, c.gamma, c.mtype, c.caltype, weights=np.array([-1.0] * len(df_bs)))


def test_extract_factors_robust_weighted_differs_from_unweighted():
    c, df_bs, bond_ref = _make_curve_and_inputs()
    c.extractFactorsRobust(df_bs, bond_ref, k_mad=2.0, min_points=4)
    unweighted = np.array(c.factors, dtype=float).ravel()

    weights = pd.Series(1.0, index=df_bs.index)
    weights.iloc[2] = 0.05  # heavily downweight one point
    c.extractFactorsRobust(df_bs, bond_ref, k_mad=2.0, min_points=4, weights=weights)
    weighted = np.array(c.factors, dtype=float).ravel()

    assert not np.allclose(unweighted, weighted)
    assert c._fit_weights is not None
    assert c._fit_weights.iloc[2] == 0.05


def test_extract_factors_robust_default_weights_none_is_backward_compatible():
    c, df_bs, bond_ref = _make_curve_and_inputs()
    c.extractFactorsRobust(df_bs, bond_ref, k_mad=2.0, min_points=4)
    assert c._fit_weights is None


def test_quote_quality_weights_live_beats_cnbd_fallback():
    idx = ['a', 'b']
    is_live = pd.Series([True, False], index=idx)
    w = quote_quality_weights(is_live)
    assert w['a'] > w['b']


def test_quote_quality_weights_wide_spread_penalized():
    idx = ['tight', 'wide']
    is_live = pd.Series([True, True], index=idx)
    spread_bp = pd.Series([1.0, 30.0], index=idx)
    w = quote_quality_weights(is_live, spread_bp=spread_bp, max_spread_bp=15.0)
    assert w['tight'] > w['wide']


def test_quote_quality_weights_missing_signals_default_neutral():
    """A point with no spread/volume info should not be penalized just for
    missing those optional signals."""
    idx = ['a']
    is_live = pd.Series([True], index=idx)
    spread_bp = pd.Series([np.nan], index=idx)
    w = quote_quality_weights(is_live, spread_bp=spread_bp)
    assert w['a'] == pytest.approx(1.0)


def test_quote_quality_weights_bounded_in_unit_interval():
    rng = np.random.default_rng(0)
    n = 50
    idx = [f'b{i}' for i in range(n)]
    is_live = pd.Series(rng.integers(0, 2, n).astype(bool), index=idx)
    spread_bp = pd.Series(rng.uniform(0, 50, n), index=idx)
    volume = pd.Series(rng.uniform(0, 1e6, n), index=idx)
    w = quote_quality_weights(is_live, spread_bp, volume)
    assert (w > 0).all()
    assert (w <= 1.0).all()
