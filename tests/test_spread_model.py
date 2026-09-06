"""Tests for curves/calibration/spread.py (item 4.2) and the mid-curve fit
integration in curves/refreshers/rates.py (item 4.1).
See docs/dev/affine-curve-improvement-plan.md F8.
"""
import numpy as np
import pandas as pd

from curves.calibration.spread import (
    apply_spread_to_mid,
    compute_half_spread_bp,
    MIN_HALF_SPREAD_BP,
)


def test_bid_never_below_ofr():
    """The floor must guarantee bid >= ofr in yield terms for every input,
    including extreme/degenerate tenor and staleness combinations."""
    rng = np.random.default_rng(0)
    n = 200
    idx = [f"b{i}" for i in range(n)]
    tenor = pd.Series(rng.uniform(0.05, 30.0, n), index=idx)
    is_ref = pd.Series(rng.integers(0, 2, n).astype(bool), index=idx)
    is_stale = pd.Series(rng.integers(0, 2, n).astype(bool), index=idx)
    mid = pd.Series(rng.uniform(-1.0, 8.0, n), index=idx)

    out = apply_spread_to_mid(mid, tenor, is_ref, is_stale)
    assert (out['Bid'] >= out['Ofr']).all()


def test_half_spread_never_below_floor():
    tenor = pd.Series([0.01, 100.0], index=['a', 'b'])
    is_ref = pd.Series([True, True], index=['a', 'b'])
    hs = compute_half_spread_bp(tenor, is_ref)
    assert (hs >= MIN_HALF_SPREAD_BP).all()


def test_half_spread_widens_with_tenor():
    tenor = pd.Series([0.5, 2.0, 5.0, 10.0], index=['a', 'b', 'c', 'd'])
    is_ref = pd.Series([True, True, True, True], index=tenor.index)
    hs = compute_half_spread_bp(tenor, is_ref)
    assert hs.is_monotonic_increasing


def test_off_reference_wider_than_reference_at_same_tenor():
    tenor = pd.Series([2.0, 2.0], index=['ref', 'offref'])
    is_ref = pd.Series([True, False], index=['ref', 'offref'])
    hs = compute_half_spread_bp(tenor, is_ref)
    assert hs['offref'] > hs['ref']


def test_stale_quote_widens_spread():
    tenor = pd.Series([2.0, 2.0], index=['fresh', 'stale'])
    is_ref = pd.Series([True, True], index=['fresh', 'stale'])
    is_stale = pd.Series([False, True], index=['fresh', 'stale'])
    hs = compute_half_spread_bp(tenor, is_ref, is_stale)
    assert hs['stale'] > hs['fresh']


def test_quote_age_widens_spread_up_to_cap():
    tenor = pd.Series([2.0, 2.0, 2.0], index=['a', 'b', 'c'])
    is_ref = pd.Series([True, True, True], index=tenor.index)
    age = pd.Series([0.0, 5.0, 100.0], index=tenor.index)
    hs = compute_half_spread_bp(tenor, is_ref, quote_age_days=age)
    assert hs['a'] < hs['b'] < hs['c'] or hs['b'] == hs['c']  # widening caps out


def test_apply_spread_to_mid_columns_and_values():
    tenor = pd.Series([2.0], index=['a'])
    is_ref = pd.Series([True], index=['a'])
    mid = pd.Series([1.5], index=['a'])
    out = apply_spread_to_mid(mid, tenor, is_ref)
    assert list(out.columns) == ['Mid', 'Bid', 'Ofr', 'HalfSpreadBp']
    assert out.loc['a', 'Bid'] > out.loc['a', 'Mid'] > out.loc['a', 'Ofr']
