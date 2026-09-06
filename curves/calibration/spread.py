"""Quoted bid/ofr half-spread model for the mid-curve market-making track.

See docs/dev/affine-curve-improvement-plan.md F8 / items 4.1, 4.2.

Item 4.1 replaces the previous two-independent-side affine fit (one curve
fit to reference bids, one to reference offers) with a single mid-curve fit,
since two curves smoothed independently through ~9 noisy reference points
give no guarantee that ofr_curve(tau) >= bid_curve(tau), and the resulting
per-bond model bid/ofr spread was an artifact of reference-bond spreads, not
of that bond's own liquidity.

This module supplies the other half: once there is one mid curve, a
half-spread model publishes `bid = mid + h`, `ofr = mid - h` (in yield
terms -- a WIDER yield spread means a narrower price spread on the offer
side and vice versa is not relevant here since h is applied symmetrically
in yield space) with a floor that guarantees h >= 0, so bid/ofr can never
cross by construction.

Starting point: a simple calibrated table by tenor bucket and liquidity
tier, widened by reference-quote quality/staleness. This is intentionally
not fitted to historical bid/ofr data yet -- iterate the table once real
quoted-spread history is available (see item 4.2's "start simple, iterate
later").
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

# Base half-spread by tenor bucket, in bp of YTM. Coarser than
# BondConfig.TERM_BUCKETS on purpose -- this is a market-making width, not a
# calibration anchor grid. Widens with tenor: duration risk on an unhedged
# quote grows with tenor, so does the yield-space width a market maker needs
# to compensate for it.
_BASE_HALF_SPREAD_BP_BY_TENOR = {
    0.5: 1.0,
    1.0: 1.5,
    2.0: 2.0,
    3.0: 2.5,
    5.0: 3.0,
    10.0: 4.0,
}
_TENOR_KNOTS = np.array(sorted(_BASE_HALF_SPREAD_BP_BY_TENOR.keys()))
_BASE_BP_AT_KNOTS = np.array([_BASE_HALF_SPREAD_BP_BY_TENOR[t] for t in _TENOR_KNOTS])

# Liquidity-tier multiplier on the base half-spread. "reference" bonds (the
# ones the curve is actually fit to) are the most liquid tier by construction
# in this universe; "off_reference" is any other bond in the pricing window.
_LIQUIDITY_TIER_MULTIPLIER = {
    "reference": 1.0,
    "off_reference": 1.5,
}

# Multiplier applied when a bond's own live quote failed the staleness gate
# (see BondCurveRefresher._stale_reference_info) -- a market maker should
# quote wider, not narrower, around a stale/uncertain reference.
_STALE_QUOTE_MULTIPLIER = 2.0

# Floor: half-spread can never be quoted inside this, in bp. Guarantees
# bid/ofr never cross even if every other factor collapses to its minimum.
MIN_HALF_SPREAD_BP = 0.5

# Age-based widening: for every full day a reference point's live quote has
# been stale/absent, widen by this many bp, capped at _MAX_AGE_WIDEN_BP.
_AGE_WIDEN_BP_PER_DAY = 0.5
_MAX_AGE_WIDEN_BP = 5.0


def _base_half_spread_bp(tenor_years: np.ndarray) -> np.ndarray:
    """Piecewise-linear interpolation over the tenor knot table, clamped to
    the table's own endpoints (no extrapolation below 0.5y or above 10y)."""
    tenor = np.clip(tenor_years, _TENOR_KNOTS[0], _TENOR_KNOTS[-1])
    return np.interp(tenor, _TENOR_KNOTS, _BASE_BP_AT_KNOTS)


def compute_half_spread_bp(
    tenor_years: pd.Series,
    is_reference: pd.Series,
    is_stale: Optional[pd.Series] = None,
    quote_age_days: Optional[pd.Series] = None,
) -> pd.Series:
    """Compute the quoted half-spread (bp of YTM) per bond.

    Args:
        tenor_years: remaining time to maturity, indexed by bond id.
        is_reference: True where the bond is one of the curve's own
            reference points (tighter tier); False otherwise.
        is_stale: True where the bond's live quote failed the staleness gate
            this refresh (see BondCurveRefresher._stale_reference_info).
            None means no staleness information is available (assume fresh).
        quote_age_days: days since a genuinely fresh two-sided quote was
            last observed for this bond, for age-based widening on top of
            the flat stale multiplier. None disables age widening.

    Returns:
        Half-spread in bp of YTM, indexed like ``tenor_years``, always
        >= MIN_HALF_SPREAD_BP (the non-crossing floor).
    """
    tenor = pd.to_numeric(tenor_years, errors='coerce').reindex(tenor_years.index)
    base_bp = pd.Series(_base_half_spread_bp(tenor.to_numpy(dtype=float)), index=tenor.index)

    tier_mult = pd.Series(
        np.where(is_reference.reindex(tenor.index).fillna(False).to_numpy(dtype=bool),
                 _LIQUIDITY_TIER_MULTIPLIER["reference"],
                 _LIQUIDITY_TIER_MULTIPLIER["off_reference"]),
        index=tenor.index,
    )

    half_spread_bp = base_bp * tier_mult

    if is_stale is not None:
        stale_mask = is_stale.reindex(tenor.index).fillna(False).to_numpy(dtype=bool)
        half_spread_bp = half_spread_bp * np.where(stale_mask, _STALE_QUOTE_MULTIPLIER, 1.0)

    if quote_age_days is not None:
        age = pd.to_numeric(quote_age_days.reindex(tenor.index), errors='coerce').fillna(0.0)
        age_widen = (age.clip(lower=0.0) * _AGE_WIDEN_BP_PER_DAY).clip(upper=_MAX_AGE_WIDEN_BP)
        half_spread_bp = half_spread_bp + age_widen

    return half_spread_bp.clip(lower=MIN_HALF_SPREAD_BP)


def apply_spread_to_mid(
    mid_ytm: pd.Series,
    tenor_years: pd.Series,
    is_reference: pd.Series,
    is_stale: Optional[pd.Series] = None,
    quote_age_days: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """Publish bid/ofr YTM quotes around a mid curve, guaranteed non-crossing.

    ``bid = mid + half_spread``, ``ofr = mid - half_spread`` in yield terms
    (a bond's ofr YIELD is below its bid YIELD, i.e. the ofr PRICE is above
    the bid price -- standard convention already used elsewhere in this
    module, e.g. BondCurveRefresher._stale_reference_info's bid/ofr columns).

    Returns a DataFrame with columns ['Mid', 'Bid', 'Ofr', 'HalfSpreadBp'],
    indexed like ``mid_ytm``.
    """
    half_spread_bp = compute_half_spread_bp(tenor_years, is_reference, is_stale, quote_age_days)
    half_spread_pct = half_spread_bp.reindex(mid_ytm.index) / 100.0

    out = pd.DataFrame(index=mid_ytm.index)
    out['Mid'] = mid_ytm
    out['Bid'] = mid_ytm + half_spread_pct
    out['Ofr'] = mid_ytm - half_spread_pct
    out['HalfSpreadBp'] = half_spread_bp.reindex(mid_ytm.index)
    return out
