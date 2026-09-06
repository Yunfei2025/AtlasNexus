"""Tests for curves/calibration/selector.py Phase 1 fixes
(docs/dev/affine-curve-improvement-plan.md).
"""
import warnings

import numpy as np
import pandas as pd
import pytest

from curves.calibration.selector import (
    filter_bonds_by_term,
    _fit_coupon_beta,
    MissingVolumeDataError,
)


def test_filter_bonds_by_term_widens_symmetrically():
    """An empty band should widen on both sides, not only upward. See F5 /
    item 1.3."""
    terms = pd.Series([4.95], index=['bond_a'])
    # Bucket targets 5.0Y but the only candidate sits just below min_term.
    result = filter_bonds_by_term(terms, min_term=5.0, max_term=5.5)
    assert 'bond_a' in result


def test_filter_bonds_by_term_caps_widening_and_warns():
    """No candidate anywhere near the band: must not loop forever, must warn,
    and must return an empty index. See F5 / item 1.3."""
    terms = pd.Series([50.0], index=['bond_far'])
    with pytest.warns(UserWarning):
        result = filter_bonds_by_term(terms, min_term=5.0, max_term=5.5, max_widen=0.25)
    assert len(result) == 0


def test_filter_bonds_by_term_does_not_overwiden_past_neighbour_bucket():
    """Widening is capped so a bucket can't quietly swallow a bond meant for
    an adjacent bucket. See F5 / item 1.3."""
    # A bond at 6.5y should not be captured by a "5Y" bucket [4.0, 6.0] even
    # after widening, since max_widen keeps the band well short of 6.5.
    terms = pd.Series([6.5], index=['bond_b'])
    result = filter_bonds_by_term(terms, min_term=4.0, max_term=6.0, max_widen=0.25)
    assert 'bond_b' not in result


def test_missing_volume_data_error_is_not_system_exit():
    """The old SystemExit killed the host process and defeated the EOD
    pipeline's per-step isolation. See F12 / item 1.4."""
    assert issubclass(MissingVolumeDataError, RuntimeError)
    assert not issubclass(MissingVolumeDataError, SystemExit)


def test_fit_coupon_beta_recovers_known_coefficient():
    """On a synthetic cross-section with a known coupon effect, the fit
    should recover it closely. See F13 / item 1.7."""
    rng = np.random.default_rng(0)
    n = 20
    ttm = np.linspace(0.1, 2.0, n)
    coupon = rng.uniform(0.5, 3.0, n)
    true_beta = -0.10
    level = 1.2 + 0.05 * ttm
    ytm = level + true_beta * coupon + rng.normal(0, 0.001, n)

    beta = _fit_coupon_beta(coupon, ytm, ttm)
    assert abs(beta - true_beta) < 0.02


def test_fit_coupon_beta_returns_zero_for_thin_or_flat_cross_section():
    """Too few points, or no coupon variation, must not fit a beta (avoids
    over-fitting reference-selection noise). See F13 / item 1.7."""
    assert _fit_coupon_beta(np.array([1.0, 1.0, 1.0]),
                             np.array([2.0, 2.1, 1.9]),
                             np.array([0.5, 1.0, 1.5])) == 0.0
    assert _fit_coupon_beta(np.array([1.0, 2.0]),
                             np.array([2.0, 1.9]),
                             np.array([0.5, 1.0])) == 0.0


def test_fit_coupon_beta_rejects_implausible_magnitude():
    """A same-day fit implying a coupon sensitivity beyond the sanity cap is
    almost certainly overfitting a thin cross-section, not a real effect."""
    # Two points with a huge coupon-driven gap forced through a degenerate fit.
    ttm = np.array([1.0, 1.0, 1.0, 1.0])
    coupon = np.array([1.0, 1.0, 5.0, 5.0])
    ytm = np.array([1.0, 1.0, -20.0, -20.0])  # implies beta way beyond +/-2
    beta = _fit_coupon_beta(coupon, ytm, ttm)
    assert beta == 0.0


def _stub_bonds(maturity: dict, current_date, turnover: dict):
    """Minimal `bonds` dict for RefBondSelector._process_single_date."""
    ids = list(maturity)
    mat = pd.Series({b: current_date + pd.Timedelta(days=int(y * 365))
                     for b, y in maturity.items()})
    return {
        'bonds': pd.Index(ids),
        'balance': pd.Series(100.0, index=ids),
        'turnover': pd.DataFrame([[turnover[b] for b in ids]],
                                 index=[current_date], columns=ids),
        'maturity': mat,
        'start_date': pd.Series(current_date - pd.Timedelta(days=400), index=ids),
        'bond_names': pd.Series([f'{b} 记账式附息(国债)' for b in ids], index=ids),
        'definition': pd.DataFrame({'每年付息次数': 1.0}, index=ids),
    }


def test_sticky_selection_never_reuses_another_buckets_bond():
    """The sticky-previous-selection branch must re-apply the duplicate guard.

    Regression for the 2024-01-04..2024-02-01 TBond break: 220004.IB held the
    0.7Y AND 1Y buckets for 21 straight days at TTM ~1.07-1.14 (0.7Y bucket is
    [0.6, 0.9]). Two anchors 0.08y apart broke the bootstrap on the next roll
    -- RefSpot 10Y fell 2.102% -> 1.563% while its own input bond traded flat.
    """
    from curves.calibration.selector import RefBondSelector

    current = pd.Timestamp('2024-02-01')
    # 'shared' sits in the 1Y band; nothing else is near the 0.7Y band, so the
    # pre-fix code would widen + stick it into BOTH buckets.
    bonds = _stub_bonds({'shared': 1.05, 'other_1y': 1.10, 'long': 2.0},
                        current, {'shared': 9.0, 'other_1y': 5.0, 'long': 1.0})
    buckets = {0.7: [0.6, 0.9], 1: [0.9, 1.2], 2: [1.6, 2.5]}
    cols = [f'Term near {t}Y' for t in buckets]
    # Seed history so the sticky branch is live and already had 'shared' at 0.7Y.
    existing = pd.DataFrame([{ 'Term near 0.7Y': 'shared',
                               'Term near 1Y': 'other_1y',
                               'Term near 2Y': 'long'}],
                            index=[current - pd.Timedelta(days=1)], columns=cols)

    result = RefBondSelector()._process_single_date(
        bonds, current, 'TBond', buckets, existing)

    picks = [b for b in result.values() if isinstance(b, str)]
    assert len(picks) == len(set(picks)), f'duplicate anchor across buckets: {result}'


def test_sticky_fallback_still_rejects_exact_duplicate():
    """The empty-bucket fallback must not place the SAME bond in two buckets
    even when it is the only fallback candidate -- near-collinear-but-
    distinct anchors are tolerated (adjacent TERM_BUCKETS share zero-width
    boundaries, e.g. 0.5Y=[0.4,0.6] meets 0.7Y=[0.6,0.9], so two genuinely
    different, correctly-selected bonds can legitimately sit a few
    hundredths of a year apart), but reusing one bond for two anchors is the
    degenerate case that silently overwrites a bootstrap instrument."""
    from curves.calibration.selector import RefBondSelector

    current = pd.Timestamp('2024-02-01')
    # Nothing else is eligible for the 0.7Y band, so it falls through to the
    # sticky fallback; 'shared' is already claimed by the 1Y bucket today.
    bonds = _stub_bonds({'shared': 1.05, 'long': 2.0},
                        current, {'shared': 9.0, 'long': 1.0})
    buckets = {1: [0.9, 1.2], 0.7: [0.6, 0.9], 2: [1.6, 2.5]}
    cols = [f'Term near {t}Y' for t in buckets]
    existing = pd.DataFrame([{'Term near 0.7Y': 'shared',
                              'Term near 1Y': 'shared',
                              'Term near 2Y': 'long'}],
                            index=[current - pd.Timedelta(days=1)], columns=cols)

    result = RefBondSelector()._process_single_date(
        bonds, current, 'TBond', buckets, existing)

    picks = [b for b in result.values() if isinstance(b, str)]
    assert len(picks) == len(set(picks)), f'duplicate anchor across buckets: {result}'


def test_ffill_does_not_resurrect_a_blocked_duplicate():
    """Regression: the merge/ffill step in select_reference_bonds() must not
    backfill a bucket that THIS run's per-day selection deliberately left
    NaN because its only candidate was already claimed by another bucket
    that day.

    Seen on real CBond data 2023-10-10..13: 0.5Y's fresh pick took
    230206.IB, so 0.7Y correctly got NaN from the duplicate guard -- then a
    blanket ffill() immediately overwrote that NaN with 230206.IB again
    (0.7Y's own value from 2023-10-09), recreating the exact duplicate the
    guard had just blocked and leaving the bootstrap with two anchors at an
    identical maturity. This exercises the same merge/ffill logic
    select_reference_bonds runs after building `new_rows`, rather than
    driving the full function (whose DIR_INPUT/DIR_DATA file I/O and
    datetime.date/Timestamp mixing make it awkward to unit test directly).
    """
    d0 = pd.Timestamp('2023-10-09')
    d1 = pd.Timestamp('2023-10-10')
    cols = ['Term near 0.5Y', 'Term near 0.7Y', 'Term near 2Y']

    existing_result_df = pd.DataFrame(
        [{'Term near 0.5Y': np.nan, 'Term near 0.7Y': 'shared', 'Term near 2Y': 'long'}],
        index=[d0], columns=cols)
    # What _process_single_date actually returns on d1: 0.5Y took 'shared'
    # fresh; 0.7Y's duplicate guard correctly declined it (NaN), since
    # 'shared' is already claimed today.
    new_rows = {d1: {'Term near 0.5Y': 'shared', 'Term near 0.7Y': np.nan,
                     'Term near 2Y': 'long'}}

    new_rows_df = pd.DataFrame(new_rows).T
    result_df = pd.concat(
        [existing_result_df, new_rows_df]
    ).loc[lambda df: ~df.index.duplicated(keep='last')]
    result_df = result_df.sort_index()
    processed_mask = pd.DataFrame(False, index=result_df.index, columns=result_df.columns)
    processed_mask.loc[new_rows_df.index, new_rows_df.columns] = True
    filled = result_df.ffill()
    result_df = result_df.where(processed_mask, filled)
    result_df = result_df.dropna(how='all')

    row = result_df.loc[d1]
    picks = [b for b in row if isinstance(b, str)]
    assert len(picks) == len(set(picks)), (
        f'ffill recreated a duplicate anchor on {d1.date()}: {dict(row)}')
    assert pd.isna(row['Term near 0.7Y']), (
        "0.7Y should stay NaN on d1 -- the selector explicitly declined it "
        "(its only candidate was already claimed), so ffill must not "
        f"backfill it: got {row['Term near 0.7Y']!r}")
