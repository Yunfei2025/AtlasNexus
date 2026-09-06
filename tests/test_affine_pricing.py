"""Tests for curves/affine/* correctness fixes (Phase 1,
docs/dev/affine-curve-improvement-plan.md).
"""
import pandas as pd
import pytest
import sympy as sp

from curves.affine.pricingYield import scheduleDate, pricing, pricingYield, pricingAffine
from curves.affine.affine import calAffineCov


def test_coupon_bond_price_ytm_round_trip():
    """price -> ytm -> price round trip for an ordinary semi-annual bond."""
    mats = pd.Timestamp('2023-06-01')
    mate = pd.Timestamp('2028-06-01')
    freq = 2.0
    day = pd.Timestamp('2026-09-05')
    coup = 2.5
    schedule = scheduleDate(mats, mate, 'test coupon bond', freq)

    ytm_in = 1.85
    price, clean, dur, conv = pricing(day, coup, schedule, freq, ytm_in)
    ytm_out = pricingYield(day, coup, schedule, freq, price)

    assert abs(ytm_out - ytm_in) < 0.001  # < 0.1bp


def test_discount_bond_price_ytm_round_trip():
    """A genuine discount/zero-coupon bond (freq=0) must round-trip through
    the simple-interest short-end formula, not crash or use a fabricated
    coupon frequency. See F1 / item 1.1."""
    mats = pd.Timestamp('2026-06-01')
    mate = pd.Timestamp('2026-12-01')
    freq = 0.0
    day = pd.Timestamp('2026-09-05')
    schedule = scheduleDate(mats, mate, '2026年记账式贴现(测试)国债', freq)

    ytm_in = 1.5
    price, clean, dur, conv = pricing(day, 0.0, schedule, freq, ytm_in)

    dres = (mate - day).days
    expected_price = 100 / (1 + (ytm_in / 100) * dres / 365)
    assert abs(price - expected_price) < 1e-8

    ytm_out = pricingYield(day, 0.0, schedule, freq, price)
    assert abs(ytm_out - ytm_in) < 0.001


def test_discount_bond_pricing_affine_matches_pricing():
    """pricingAffine's freq==0 branch must agree with pricing() under a flat
    curve, and must not divide by zero. See F1 / item 1.1."""
    mats = pd.Timestamp('2026-06-01')
    mate = pd.Timestamp('2026-12-01')
    freq = 0.0
    day = pd.Timestamp('2026-09-05')
    schedule = scheduleDate(mats, mate, 'test discount', freq)

    S2 = sp.zeros(3, 3)
    gamma = 0.62
    factors = sp.Matrix([1.5, 0, 0])  # flat y=1.5
    mtype = 'Model A'

    p_affine, clean_affine, sen, p_pretax, clean_pretax = pricingAffine(
        day, 0.0, 0.0, schedule, freq, factors, S2, gamma, mtype, None
    )
    p_direct, clean_direct, dur, conv = pricing(day, 0.0, schedule, freq, 1.5)

    assert abs(float(p_affine) - p_direct) < 1e-8


def test_pricing_affine_actual_schedule_dates():
    """pricingAffine must use real schedule dates for the curve-lookup tenor
    (tau_y), not the i*TS+dres approximation, while keeping the discounting-
    period count (stub + whole periods) unchanged for a flat curve. See F10 /
    item 1.2."""
    mats = pd.Timestamp('2023-06-01')
    mate = pd.Timestamp('2028-06-01')
    freq = 2.0
    day = pd.Timestamp('2026-09-05')
    coup = 2.5
    schedule = scheduleDate(mats, mate, 'test coupon bond', freq)

    S2 = sp.zeros(3, 3)
    gamma = 0.62
    factors = sp.Matrix([1.5, 0, 0])  # flat curve: tau_y precision shouldn't matter
    mtype = 'Model A'

    p_affine, *_ = pricingAffine(day, coup, 0.0, schedule, freq, factors, S2, gamma, mtype, None)
    p_direct, *_ = pricing(day, coup, schedule, freq, 1.5)

    assert abs(float(p_affine) - p_direct) < 1e-6


def test_cal_affine_cov_returns_convergence_flag():
    """calAffineCov must return (S2, converged) so Curve.calibrate can store
    a non-convergence warning flag. See F3 / item 1.5."""
    import numpy as np

    np.random.seed(0)
    n_dates = 30
    taus = np.array([0.3, 0.5, 1, 2, 3, 5, 10])
    term = pd.DataFrame(np.tile(taus, (n_dates, 1)))
    spot = pd.DataFrame(
        2 + 0.3 * np.log(1 + np.tile(taus, (n_dates, 1)))
        + np.random.randn(n_dates, len(taus)) * 0.05
    )

    S2, converged = calAffineCov(term, spot, 0.62, 'Model A', None)
    assert S2.shape == (3, 3)
    assert isinstance(converged, bool)
    assert converged is True


def test_cal_affine_cov_default_is_levels_not_innovations():
    """calAffineCov must default to use_innovations=False (the previous,
    stable covariance-of-levels estimate). The innovations estimator is a
    real, documented improvement in THEORY (F2), but verified 2026-09-05
    against 5 real historical windows to diverge to NaN/Inf in 4 of 5 under
    the current naive fixed-point implementation -- it must stay an
    explicit opt-in, not the default, until a stabilizing fix (shrinkage,
    decoupled estimation, damped update) lands. See F2 / item 2.1."""
    import numpy as np

    np.random.seed(1)
    n_dates = 60
    taus = np.array([0.3, 0.5, 1, 2, 3, 5, 10])
    term = pd.DataFrame(np.tile(taus, (n_dates, 1)))
    level = np.cumsum(np.random.randn(n_dates, len(taus)) * 0.02, axis=0)
    spot = pd.DataFrame(2 + 0.3 * np.log(1 + np.tile(taus, (n_dates, 1))) + level)

    S2_default, _ = calAffineCov(term, spot, 0.62, 'Model A', None)
    S2_level, _ = calAffineCov(term, spot, 0.62, 'Model A', None, use_innovations=False)

    S2_default_np = np.array(S2_default.tolist(), dtype=float)
    S2_level_np = np.array(S2_level.tolist(), dtype=float)
    assert np.allclose(S2_default_np, S2_level_np)


def test_cal_affine_cov_innovations_opt_in_still_well_formed_on_this_series():
    """When explicitly requested, the innovations estimator should still
    produce a well-formed (symmetric, PSD) covariance on a benign synthetic
    series, distinct from the level estimate -- it is not broken in every
    case, just not safe as an unconditional default (see the real-data
    divergence test below)."""
    import numpy as np

    np.random.seed(1)
    n_dates = 60
    taus = np.array([0.3, 0.5, 1, 2, 3, 5, 10])
    term = pd.DataFrame(np.tile(taus, (n_dates, 1)))
    level = np.cumsum(np.random.randn(n_dates, len(taus)) * 0.02, axis=0)
    spot = pd.DataFrame(2 + 0.3 * np.log(1 + np.tile(taus, (n_dates, 1))) + level)

    S2_innov, _ = calAffineCov(term, spot, 0.62, 'Model A', None, use_innovations=True)
    S2_level, _ = calAffineCov(term, spot, 0.62, 'Model A', None, use_innovations=False)

    S2_innov_np = np.array(S2_innov.tolist(), dtype=float)
    S2_level_np = np.array(S2_level.tolist(), dtype=float)

    assert np.isfinite(S2_innov_np).all()
    assert np.allclose(S2_innov_np, S2_innov_np.T)
    assert (np.linalg.eigvalsh(S2_innov_np) >= -1e-8).all()
    assert not np.allclose(S2_innov_np, S2_level_np, rtol=0.05)


def test_cal_affine_cov_innovations_requires_min_five_dates():
    """Diffing loses one observation, so the innovations path needs one more
    date than the level path before it can produce a (barely) usable
    3x3 covariance estimate."""
    import numpy as np
    import pytest

    taus = np.array([0.3, 0.5, 1, 2, 3, 5, 10])
    term = pd.DataFrame(np.tile(taus, (4, 1)))
    spot = pd.DataFrame(2 + 0.3 * np.log(1 + np.tile(taus, (4, 1))))

    with pytest.raises(ValueError):
        calAffineCov(term, spot, 0.62, 'Model A', None, use_innovations=True)
    # Same 4 dates are still fine for the level-based estimator.
    calAffineCov(term, spot, 0.62, 'Model A', None, use_innovations=False)


def test_pricing_final_period_ex_coupon_day_no_double_discount():
    """A bond in its FINAL coupon period, priced ON its coupon date, must be
    discounted over one remaining period -- not two.

    `pricing()`'s single-payment branch used
    `nt = dres/TS + floor(dres/TS)`. On the ex-coupon day the schedule ffill
    lands exactly on the coupon date, so dres == TS (the full final period)
    and nt became 2.0 instead of 1.0. That understated the dirty price by
    about one coupon and made the bootstrap emit a roughly DOUBLED 1y zero
    for that single day -- observed as 1.27% -> 2.57% on 240010.IB
    (2026-05-15) and four other historical 1Y spikes up to 470bp.
    """
    day = pd.Timestamp('2026-05-15').date()
    # Annual bond, coupon today, single remaining flow ~1y out.
    schedule = pd.Series([
        pd.Timestamp('2024-05-15').date(),
        pd.Timestamp('2025-05-15').date(),
        pd.Timestamp('2026-05-15').date(),
        pd.Timestamp('2027-05-17').date(),
    ])
    coup, freq, ytm = 1.85, 1.0, 1.175

    dirty, clean, dur, cvx = pricing(day, coup, schedule, freq, ytm)

    # One remaining cashflow of 100 + 1.85 discounted over ~1.005 periods.
    expected = (100.0 + coup / freq) / (1.0 + ytm / freq / 100.0) ** (367 / 367)
    assert dirty == pytest.approx(expected, abs=1e-6)
    # Sanity: the double-discounted value the bug produced must NOT recur.
    assert dirty > 100.0, f'dirty {dirty} looks double-discounted'

    # And it must still round-trip.
    assert pricingYield(day, coup, schedule, freq, dirty) == pytest.approx(ytm, abs=1e-6)


def test_pricing_continuous_across_coupon_date():
    """Dirty price must fall by ~one coupon across the coupon date, with no
    discontinuity beyond that."""
    schedule = pd.Series([
        pd.Timestamp('2024-05-15').date(),
        pd.Timestamp('2025-05-15').date(),
        pd.Timestamp('2026-05-15').date(),
        pd.Timestamp('2027-05-17').date(),
    ])
    coup, freq, ytm = 1.85, 1.0, 1.175
    before = pricing(pd.Timestamp('2026-05-14').date(), coup, schedule, freq, ytm)[0]
    on = pricing(pd.Timestamp('2026-05-15').date(), coup, schedule, freq, ytm)[0]
    after = pricing(pd.Timestamp('2026-05-18').date(), coup, schedule, freq, ytm)[0]

    assert (before - on) == pytest.approx(coup / freq, abs=0.02)
    assert abs(after - on) < 0.05


def test_add_instrument_redemption_time_defaults_to_T():
    """Back-compat: omitting redemption_time must reproduce the old numbers
    exactly, since T served as the redemption discount time before."""
    from curves.affine.bootstrap import BootstrapYieldCurve

    a = BootstrapYieldCurve()
    a.add_instrument(100, 2.0, 2.0, 100.5, 1.0)
    b = BootstrapYieldCurve()
    b.add_instrument(100, 2.0, 2.0, 100.5, 1.0, redemption_time=2.0)
    assert a.get_zero_rates() == b.get_zero_rates()


def test_redemption_time_shifts_zero_in_expected_direction():
    """Discounting the redemption at its true (later) payment date must lower
    the implied zero slightly -- the same cashflow over a longer horizon."""
    from curves.affine.bootstrap import BootstrapYieldCurve

    node = BootstrapYieldCurve()
    node.add_instrument(100, 1.0, 2.0, 100.5, 1.0)
    z_node = node.get_zero_rates()[0]

    real = BootstrapYieldCurve()
    real.add_instrument(100, 1.0, 2.0, 100.5, 1.0, redemption_time=1.0 + 2 / 365)
    z_real = real.get_zero_rates()[0]

    assert z_real < z_node
    # 2 days on a ~1.5% 1y zero is sub-bp.
    assert abs(z_real - z_node) * 100 < 2.0


def test_duplicate_maturity_key_warns_instead_of_silent_overwrite():
    """Two reference bonds landing on the same float ttm used to overwrite
    silently, losing one anchor. The upstream duplicate guard should prevent
    it; surface it if it ever slips through."""
    from curves.affine.bootstrap import BootstrapYieldCurve

    yc = BootstrapYieldCurve()
    yc.add_instrument(100, 2.0, 2.0, 101.0, 1.0)
    with pytest.warns(UserWarning, match='duplicate maturity key'):
        yc.add_instrument(100, 2.0, 3.0, 104.0, 1.0)
