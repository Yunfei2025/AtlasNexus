"""Per-bond residual analytics for the affine-curve RV signal layer.

Computes, per bond, from its ``ytm_act - ytm_quo`` residual history:
    - OU-fitted stationary mean (fair-value anchor, NOT a rolling mean)
    - EWMA(span=ZSCORE_EWM_VOL_SPAN) volatility (current-regime scale, NOT a
      static full-sample vol)
    - z-score = (residual - OU_mean) / EWMA_vol
    - mean-reversion half-life (AR(1) fit)
    - carry/rolldown from the fitted forward curve

See docs/dev/affine-curve-improvement-plan.md item 3.3 (F2/goal 1) for the
full rationale: mean-reversion of the residual's LEVEL does not imply its
REALIZED VOLATILITY is constant over time, so the mean and vol halves of the
z-score are estimated differently on purpose -- mirroring the existing
precedent in curves/calibration/stat.py::OU_calibrate and
web/tabs/alpha/backtest/engine_mr.py, rather than either a fully rolling or
fully static z-score.

Reference-roll awareness (item 3.2 / F6): when a bond's own curve.reference
set rolls, the affine curve's fitted level can jump discontinuously, which
would otherwise show up in ytm_quo (and hence the residual) as a spurious
level shift unrelated to any real market move. This module accepts an
optional reference-change event log (RefBondChange from
RefBondSelector.select_reference_bonds) and, when a roll falls inside a
bond's residual history, restarts the OU/half-life/EWMA-vol estimation from
the most recent roll date instead of fitting across the discontinuity.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from curves.calibration.stat import ZSCORE_EWM_VOL_SPAN, _adf_result, _fit_ar1_params


def _most_recent_roll_date(
    change_events: Optional[pd.DataFrame],
    bucket: Optional[str],
    before: pd.Timestamp,
) -> Optional[pd.Timestamp]:
    """Latest reference-change event date for `bucket` strictly before
    `before`, or None if there is no such event / no event log / no bucket
    given. `change_events` is the RefBondChange table (MultiIndex
    (date, bucket), see RefBondSelector.select_reference_bonds)."""
    if change_events is None or change_events.empty or bucket is None:
        return None
    if 'bucket' not in change_events.index.names:
        return None
    try:
        bucket_events = change_events.xs(bucket, level='bucket')
    except KeyError:
        return None
    # Normalise both sides to Timestamps before comparing. The cvref pickles
    # index by `datetime.date` while the event log is built from Timestamps,
    # and pandas raises TypeError on a datetime64-vs-date comparison rather
    # than coercing -- which would break this guard in production.
    try:
        event_dates = pd.DatetimeIndex(pd.to_datetime(bucket_events.index))
        cutoff = pd.Timestamp(before)
    except (TypeError, ValueError):
        return None
    dates = event_dates[event_dates < cutoff]
    if len(dates) == 0:
        return None
    return dates.max()


def compute_residual_stats(
    residual: pd.Series,
    forward_curve: Optional[pd.DataFrame] = None,
    tenor_years: Optional[float] = None,
    horizon_years: float = 0.25,
    change_events: Optional[pd.DataFrame] = None,
    bucket: Optional[str] = None,
    ewm_span: int = ZSCORE_EWM_VOL_SPAN,
    min_points: int = 20,
) -> dict:
    """Compute residual analytics for one bond's ``ytm_act - ytm_quo`` history.

    Args:
        residual: the bond's residual history (ytm_act - ytm_quo, in %),
            indexed by date, sorted ascending.
        forward_curve: optional ``Curve.fitting()`` output (columns
            SpotRate/ForwardRate, indexed by tenor in years) for
            carry/rolldown. None skips carry/rolldown (fields come back NaN).
        tenor_years: this bond's current remaining time to maturity, needed
            to look up rolldown on `forward_curve`. Required if
            `forward_curve` is given.
        horizon_years: rolldown horizon (e.g. 0.25 = 3m rolldown). Rolldown
            is the yield PICKUP from aging along today's curve:
            spot(tenor) - spot(tenor - horizon), so it is a positive number
            when the curve is upward-sloping (typical carry-positive case).
        change_events: optional RefBondChange table (item 3.2). When given
            with `bucket`, estimation restarts from the most recent roll
            date so a discontinuous curve-level jump does not get fit as if
            it were part of the residual's own dynamics.
        bucket: this bond's current reference bucket name (e.g.
            'Term near 5Y'), used to look up `change_events`. Ignored if
            `change_events` is None.
        ewm_span: EWMA span for the volatility estimate (defaults to the
            same ZSCORE_EWM_VOL_SPAN used by OU_calibrate elsewhere in this
            codebase, so a live snapshot and a backtest agree on scale).
        min_points: minimum residual observations (after any roll-restart)
            required to fit anything at all; below this everything comes
            back NaN rather than fit on too little data to be meaningful.

    Returns:
        dict with keys: stationary ('YES'/'NO'/None), ou_mean, ewm_vol,
        zscore (as of the LAST observation), halflife, carry_bp, roll_bp,
        carry_roll_bp, fit_start (the date estimation actually started
        from, after any roll-restart), n_obs (points used in the fit).
    """
    residual = pd.to_numeric(residual, errors='coerce').dropna().sort_index()

    out = dict(
        stationary=None, ou_mean=np.nan, ewm_vol=np.nan, zscore=np.nan,
        halflife=np.nan, carry_bp=np.nan, roll_bp=np.nan, carry_roll_bp=np.nan,
        fit_start=None, n_obs=0,
    )
    if residual.empty:
        return out

    fit_start = _most_recent_roll_date(change_events, bucket, residual.index[-1])
    if fit_start is not None:
        # Same date-vs-Timestamp hazard as in _most_recent_roll_date: compare
        # on a coerced copy of the index, but keep the original index on the
        # returned slice so callers see unchanged date types.
        idx_ts = pd.DatetimeIndex(pd.to_datetime(residual.index))
        fitted = residual[idx_ts > pd.Timestamp(fit_start)]
    else:
        fitted = residual
    out['fit_start'] = fit_start
    out['n_obs'] = int(len(fitted))

    if len(fitted) < min_points:
        return out

    _, stationary, _, _ = _adf_result(fitted)
    out['stationary'] = stationary

    # Volatility: EWMA over the (post-roll-restart) fitted window, current
    # regime scale -- see module docstring; this is NOT the static
    # full-sample std, on purpose.
    span = min(ewm_span, fitted.shape[0])
    ewm_vol = fitted.ewm(span=max(span, 2), min_periods=max(min(span, fitted.shape[0]), 2)).std().iloc[-1]
    out['ewm_vol'] = float(ewm_vol) if pd.notna(ewm_vol) else np.nan

    # Mean and half-life: OU/AR(1) fixed stationary mean when the series
    # tests stationary, NOT a rolling mean (see module docstring) -- a
    # non-stationary series has no fixed level to anchor to, so it falls
    # back to the plain sample mean of the fitted window (still not
    # "rolling" in the sliding-window sense, just this window's mean) and no
    # half-life, matching OU_calibrate's own fallback behavior.
    if stationary == 'YES':
        A, B, _ = _fit_ar1_params(fitted)
        if np.isfinite(A) and (1 - A) != 0 and A > 0:
            theta = B / (1 - A)
            kappa = -np.log(A)
            out['ou_mean'] = float(theta)
            out['halflife'] = float(np.log(2) / max(1e-12, kappa))
        else:
            out['ou_mean'] = float(fitted.mean())
            out['halflife'] = np.nan
    else:
        out['ou_mean'] = float(fitted.mean())
        out['halflife'] = np.nan

    if pd.notna(out['ewm_vol']) and out['ewm_vol'] > 0:
        out['zscore'] = float((fitted.iloc[-1] - out['ou_mean']) / out['ewm_vol'])

    if forward_curve is not None and tenor_years is not None:
        _compute_carry_roll(out, forward_curve, tenor_years, horizon_years)

    return out


def _compute_carry_roll(
    out: dict,
    forward_curve: pd.DataFrame,
    tenor_years: float,
    horizon_years: float,
) -> None:
    """Rolldown from the fitted spot curve: spot(T) - spot(T - horizon), the
    yield pickup from aging horizon_years along TODAY's curve shape (not a
    forecast of future curve moves). Populates carry_bp/roll_bp/
    carry_roll_bp on `out` in place; leaves them NaN if the curve doesn't
    cover the needed tenor range."""
    if 'SpotRate' not in forward_curve.columns:
        return
    spot = pd.to_numeric(forward_curve['SpotRate'], errors='coerce')
    spot.index = pd.to_numeric(pd.Series(spot.index), errors='coerce').to_numpy()
    spot = spot.dropna().sort_index()
    if spot.empty:
        return

    shorter_tenor = tenor_years - horizon_years
    if shorter_tenor <= spot.index.min() or tenor_years > spot.index.max():
        return

    y_now = float(np.interp(tenor_years, spot.index, spot.to_numpy()))
    y_shorter = float(np.interp(shorter_tenor, spot.index, spot.to_numpy()))
    # Positive roll_bp = curve is upward-sloping here, so a bond aging
    # `horizon_years` picks up (y_now - y_shorter) of price gain -- the
    # bond's yield falls toward the shorter-tenor point as time passes,
    # richening it (a long position benefits from a normal upward-sloping
    # curve, hence the sign here matches the standard "positive roll is
    # good for a long" convention).
    roll_bp = (y_now - y_shorter) * 100.0
    out['roll_bp'] = roll_bp
    out['carry_bp'] = np.nan  # coupon-carry vs funding is instrument-specific; left to the caller
    out['carry_roll_bp'] = roll_bp if pd.isna(out.get('carry_bp')) else out['carry_bp'] + roll_bp


def compute_residual_stats_panel(
    residuals: pd.DataFrame,
    forward_curve: Optional[pd.DataFrame] = None,
    tenors: Optional[pd.Series] = None,
    horizon_years: float = 0.25,
    change_events: Optional[pd.DataFrame] = None,
    bucket_by_bond: Optional[pd.Series] = None,
    ewm_span: int = ZSCORE_EWM_VOL_SPAN,
    min_points: int = 20,
) -> pd.DataFrame:
    """Vectorized wrapper: run compute_residual_stats for every column
    (bond) in `residuals`. `tenors` and `bucket_by_bond`, if given, are
    indexed by bond id (same as `residuals.columns`).
    """
    rows = {}
    for bond_id in residuals.columns:
        tenor = float(tenors.loc[bond_id]) if tenors is not None and bond_id in tenors.index else None
        bucket = bucket_by_bond.loc[bond_id] if bucket_by_bond is not None and bond_id in bucket_by_bond.index else None
        rows[bond_id] = compute_residual_stats(
            residuals[bond_id],
            forward_curve=forward_curve,
            tenor_years=tenor,
            horizon_years=horizon_years,
            change_events=change_events,
            bucket=bucket,
            ewm_span=ewm_span,
            min_points=min_points,
        )
    return pd.DataFrame(rows).T
