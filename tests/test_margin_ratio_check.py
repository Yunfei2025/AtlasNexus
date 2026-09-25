"""Tests for utils/margin_ratio_check.py (§5.4 of
docs/plans/portfolio_construction_beta_alpha.md: periodic re-validation of
estimate_margin_mm's netting-correction multiplier).
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.margin_ratio_check import compute_ratios, _single_leg_dv01_estimate
from web.tabs.alpha.data.duration import _MARGIN_MIN_RATE


def test_compute_ratios_recovers_known_multiplier():
    """A row built as (single-leg estimate * known multiplier) should recover
    exactly that multiplier as its ratio."""
    known_multiplier = 3.0
    notional = 1000.0
    duration = 5.0
    single_leg = _single_leg_dv01_estimate(notional, duration)

    df = pd.DataFrame([{
        'ID': 'TEST-A', 'spread_type': 'TenorSpread',
        'notional_mm': notional, 'margin_mm': single_leg * known_multiplier,
        '_duration': duration,
    }])

    ratios = compute_ratios(df)
    assert len(ratios) == 1
    assert abs(ratios.iloc[0]['ratio'] - known_multiplier) < 1e-9


def test_compute_ratios_excludes_floor_bound_rows():
    """A row whose actual margin equals the notional floor carries no
    information about the netting multiplier and must be dropped."""
    notional = 1000.0
    floor_margin = notional * _MARGIN_MIN_RATE

    df = pd.DataFrame([
        {'ID': 'FLOOR-A', 'spread_type': 'TenorSpread',
         'notional_mm': notional, 'margin_mm': floor_margin, '_duration': 0.5},
        {'ID': 'REAL-B', 'spread_type': 'TenorSpread',
         'notional_mm': notional, 'margin_mm': floor_margin * 10, '_duration': 5.0},
    ])

    ratios = compute_ratios(df)
    assert list(ratios['ID']) == ['REAL-B']


def test_compute_ratios_skips_rows_with_missing_or_invalid_data():
    df = pd.DataFrame([
        {'ID': 'NAN-NOTIONAL', 'spread_type': 'TenorSpread',
         'notional_mm': None, 'margin_mm': 10.0, '_duration': 5.0},
        {'ID': 'ZERO-NOTIONAL', 'spread_type': 'TenorSpread',
         'notional_mm': 0.0, 'margin_mm': 10.0, '_duration': 5.0},
        {'ID': 'NEGATIVE-MARGIN', 'spread_type': 'TenorSpread',
         'notional_mm': 1000.0, 'margin_mm': -5.0, '_duration': 5.0},
        {'ID': 'MISSING-DURATION', 'spread_type': 'TenorSpread',
         'notional_mm': 1000.0, 'margin_mm': 10.0, '_duration': None},
        {'ID': 'VALID', 'spread_type': 'TenorSpread',
         'notional_mm': 1000.0, 'margin_mm': 50.0, '_duration': 5.0},
    ])

    ratios = compute_ratios(df)
    assert list(ratios['ID']) == ['VALID']


def test_compute_ratios_raises_on_missing_columns():
    df = pd.DataFrame([{'ID': 'A', 'spread_type': 'TenorSpread'}])
    try:
        compute_ratios(df)
        assert False, "expected ValueError for missing required columns"
    except ValueError as exc:
        assert 'notional_mm' in str(exc) or 'margin_mm' in str(exc) or '_duration' in str(exc)


def test_compute_ratios_empty_frame_returns_empty():
    df = pd.DataFrame(columns=['ID', 'spread_type', 'notional_mm', 'margin_mm', '_duration'])
    ratios = compute_ratios(df)
    assert ratios.empty
