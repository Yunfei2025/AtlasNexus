# -*- coding: utf-8 -*-
"""IRS curve calibration package.

Public API mirrors the legacy `curves.calibration.irscurves` module.

Pricing-curve usage at a glance:
- Carry / floating-leg projection: smooth affine `curves['ForwardRate']` for
  the bulk, with `anchor['ForwardRate']` only at tenors < 0.25y so the very
  short end stays pinned to actual market fixings.
- Roll: smooth affine `curves['SpotRate']` (linearly interpolated to daily
  granularity) — avoids stepped-curve artifacts at key tenor nodes.

The stepped/raw bootstrap (`IRSCurve.anchor`) is exposed in plots as the
`inst` / dashed line, but is NOT used for pricing beyond the short-end pin.
"""

from curves.calibration.irs.tenors import (
    TenorConverter,
    tenor2str,
    str2tenor,
)
from curves.calibration.irs.interp import (
    Interpolator,
    interpolate_with_extrapolation,
    filter_terms_by_range,
)
from curves.calibration.irs.data import CurveDataManager
from curves.calibration.irs.generator import CurveGenerator
from curves.calibration.irs.contract import IRSContract, irsContract
from curves.calibration.irs.fixings import (
    FixingRateProvider,
    genIRSCurves,
    px2Fixings,
    refIRSCurves,
    getSpot,
    curves2Fixings,
)
from curves.calibration.irs.valuation import (
    evalueContract,
    _calculate_roll_returns,
)
from curves.calibration.irs.spreads import (
    irsSpreads,
    irsSpreadsRatio,
    irsQuoteComposite,
    irsSpreadComposite,
    _calculate_fly_spreads,
    _irs_quote_spread_weights,
)
from curves.calibration.irs.quotes import (
    get_swap_quote_frame,
    get_swap_mid_quotes,
)

__all__ = [
    'TenorConverter', 'tenor2str', 'str2tenor',
    'Interpolator', 'interpolate_with_extrapolation', 'filter_terms_by_range',
    'CurveDataManager', 'CurveGenerator',
    'IRSContract', 'irsContract',
    'FixingRateProvider',
    'genIRSCurves', 'px2Fixings', 'refIRSCurves', 'getSpot', 'curves2Fixings',
    'evalueContract',
    'irsSpreads', 'irsSpreadsRatio', 'irsQuoteComposite', 'irsSpreadComposite',
    'get_swap_quote_frame', 'get_swap_mid_quotes',
]
