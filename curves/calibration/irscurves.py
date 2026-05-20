# -*- coding: utf-8 -*-
"""Backward-compatibility shim for IRS curves.

The real implementation lives in the `curves.calibration.irs` package.
This module re-exports the legacy public surface so existing imports such as

    from curves.calibration.irscurves import irsContract, evalueContract, ...
    from curves.calibration import irscurves as irs

continue to work unchanged.
"""

from curves.calibration.irs import (  # noqa: F401
    TenorConverter,
    tenor2str,
    str2tenor,
    Interpolator,
    interpolate_with_extrapolation,
    filter_terms_by_range,
    CurveDataManager,
    CurveGenerator,
    IRSContract,
    irsContract,
    FixingRateProvider,
    genIRSCurves,
    px2Fixings,
    refIRSCurves,
    getSpot,
    curves2Fixings,
    evalueContract,
    irsSpreads,
    irsSpreadsRatio,
    irsQuoteComposite,
    irsSpreadComposite,
    get_swap_quote_frame,
    get_swap_mid_quotes,
)
from curves.calibration.irs.spreads import (  # noqa: F401
    _calculate_fly_spreads,
    _irs_quote_spread_weights,
)
from curves.calibration.irs.valuation import _calculate_roll_returns  # noqa: F401
