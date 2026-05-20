# -*- coding: utf-8 -*-
"""Fixing/spot series construction and curve refresh.

Combines the **smooth (affine-fitted) curves** (`IRSCurve.curves`) with the
**stepped (linear-bootstrapped) anchor** (`IRSCurve.anchor`) for the very
short end. The bulk of the projected fixing/spot series for pricing is from
the smooth fitted curve; anchor only contributes for tenors < 0.25y (forwards)
or <= 0.3y (spots) to keep the short end pinned to actual market fixings.
"""

import os
from datetime import date
from typing import Dict

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

from settings.general import GeneralConfig, DateConfig
from settings.fixed_income import IRSConfig
from settings.paths import DIR_INPUT
from curves.affine.curve import IRSCurve
from curves.utils.loader import loadWorkday

from curves.calibration.irs.data import CurveDataManager
from curves.calibration.irs.generator import CurveGenerator
from curves.calibration.irs.interp import Interpolator, interpolate_with_extrapolation
from curves.calibration.irs.quotes import get_swap_mid_quotes
from curves.calibration.irs.tenors import TenorConverter


class FixingRateProvider:
    """Provides fixing rates and spot rates with interpolation."""

    def __init__(self, tenor_converter: TenorConverter):
        self.tenor_converter = tenor_converter
        self.interpolator = Interpolator()

    def get_fixing_series(self, trade_date: date, workdays: pd.DatetimeIndex,
                         forward_data: pd.Series, fixing_rate: float) -> pd.Series:
        """Generate fixing rate series for given workdays."""
        tenor_numeric = self.tenor_converter.to_numeric(list(forward_data.index))
        forward_data_numeric = pd.Series(forward_data.values, index=tenor_numeric)
        forward_data_numeric.loc[0] = fixing_rate
        forward_data_numeric = (
            forward_data_numeric.sort_index()
            .groupby(level=0)
            .apply(lambda x: x.dropna().iloc[-1] if x.dropna().size else x.iloc[-1])
            .dropna()
        )

        terms = [(day - trade_date).days / GeneralConfig.YN for day in workdays]

        forward_data_numeric.loc[terms[-1]] = forward_data_numeric.iloc[-1]

        fixing_values = self.interpolator.interpolate_with_extrapolation(
            forward_data_numeric.index.values,
            forward_data_numeric.values,
            np.array(terms)
        )

        result = pd.Series(fixing_values, index=workdays)
        result.iloc[0] = fixing_rate
        return result

    def get_spot_series(self, trade_date: date, workdays: pd.DatetimeIndex,
                       spot_data: pd.Series, fixing_rate: float) -> pd.Series:
        """Generate spot rate series for given workdays."""
        tenor_numeric = self.tenor_converter.to_numeric(list(spot_data.index))
        spot_data_numeric = pd.Series(spot_data.values, index=tenor_numeric)
        spot_data_numeric.loc[0] = fixing_rate
        spot_data_numeric = (
            spot_data_numeric.sort_index()
            .groupby(level=0)
            .apply(lambda x: x.dropna().iloc[-1] if x.dropna().size else x.iloc[-1])
            .dropna()
        )

        terms = [(day - trade_date).days / GeneralConfig.YN for day in workdays]

        spot_data_numeric.loc[terms[-1]] = spot_data_numeric.iloc[-1]

        spot_values = self.interpolator.interpolate_with_extrapolation(
            spot_data_numeric.index.values,
            spot_data_numeric.values,
            np.array(terms)
        )

        result = pd.Series(spot_values, index=workdays)
        result.iloc[0] = fixing_rate
        return result


# Module-level singletons for legacy wrappers
_tenor_converter = TenorConverter()
_curve_data_manager = CurveDataManager()
_fixing_provider = FixingRateProvider(_tenor_converter)
_curve_generator = CurveGenerator(_curve_data_manager, _tenor_converter)


def genIRSCurves(env, irs_ref, d):
    """Generate IRS curves (legacy wrapper)."""
    return _curve_generator.generate_curves(env, irs_ref, d)


def px2Fixings(td):
    """Get fixing and spot data for a trade date."""
    start = td + relativedelta(days=1)
    end = td + relativedelta(years=10)
    workdays = loadWorkday(start, end)

    curve_data = _curve_data_manager.load()
    fixing_data = pd.read_pickle(os.path.join(DIR_INPUT, 'database-px.pkl'))['IRS'].loc[td]

    fixing_ts = {}
    spot_ts = {}

    for ct in IRSConfig.CURVE_TYPES:
        forward = curve_data[ct]['forward'].loc[td]
        spot = curve_data[ct]['spot'].loc[td]

        forward = CurveGenerator._normalize_tenor_index(forward)
        spot = CurveGenerator._normalize_tenor_index(spot)

        if forward.empty or spot.empty:
            print(f"Warning: Empty curve data for curve type {ct}")
            continue

        forward.loc['0d'] = fixing_data.loc['FR007.IR']
        spot.loc['0d'] = fixing_data.loc['FR001.IR']

        fixing_ts[ct] = _fixing_provider.get_fixing_series(td, workdays, forward, fixing_data.loc['FR007.IR'])
        spot_ts[ct] = _fixing_provider.get_spot_series(td, workdays, spot, fixing_data.loc['FR001.IR'])

    return {'fixing': fixing_ts, 'spot': spot_ts, 'date': td}


def refIRSCurves(env, curves, irs_ref, fallback_quotes=None):
    """Refresh IRS curves with real-time data."""
    d = DateConfig.get_date_mappings()['d'].date()
    curve_instruments = {
        ct: get_swap_mid_quotes(env['SwapRT'], irs_ref[ct], fallback_quotes=fallback_quotes)
        for ct in IRSConfig.CURVE_TYPES
    }
    for ct in IRSConfig.CURVE_TYPES:
        new_curve = IRSCurve(d, ct)
        new_curve.extractKeySpot(curve_instruments[ct])
        new_curve.interpolateCurve()
        df = new_curve.anchor['SpotRate']
        tenor_labels = _tenor_converter.to_string(df.index.tolist())
        symap = dict(zip(tenor_labels, df.index))
        desired_labels = [lbl for lbl in IRSConfig.TENOR_MAP.values() if lbl in symap]
        df_ref = df.loc[[symap[s] for s in desired_labels]]
        df_ref.name = 'Ref Spot'
        curves[ct].extractKeySpot(curve_instruments[ct])
        curves[ct].interpolateCurve()
        curves[ct].extractFactors(df_ref)
        curves[ct].fitting()
    return curves


def getSpot(td, curve, fixing, adj=False):
    """Build daily spot-rate series from the smooth fitted curve.

    Uses `curve.curves['SpotRate']` (smooth affine fit) for the bulk and
    `curve.anchor['SpotRate']` only for tenors <= 0.3y (short end pinned
    to actual market fixing).
    """
    start = td + relativedelta(days=1)
    end = td + relativedelta(years=10)
    workdays = loadWorkday(start, end)
    spot_curve = curve.adjcurves['SpotRate'] if adj else curve.curves['SpotRate']
    anchor_spot = curve.anchor['SpotRate']
    anchor_spot.loc[0] = fixing
    anchor_spot = anchor_spot.sort_index()
    anchor_spot = anchor_spot[anchor_spot.index <= 0.3]
    combined_spot = pd.concat([anchor_spot, spot_curve], axis=0).sort_index()
    terms = [(day - td).days / GeneralConfig.YN for day in workdays]
    combined_spot.loc[terms[-1]] = combined_spot.iloc[-1]
    spot_values = interpolate_with_extrapolation(combined_spot.index, combined_spot.values, terms)
    result = pd.Series(spot_values, index=workdays)
    result.iloc[0] = fixing
    return result


def curves2Fixings(d, env_ts, curves, adj=False):
    """Convert IRSCurve objects to projected fixing and spot daily series.

    The forward (fixing) series uses `curves[ct].curves['ForwardRate']`
    (smooth affine) for the bulk; anchor['ForwardRate'] contributes only
    for tenors < 0.25y where the very short end is pinned to actual
    market FR007 fixings. The spot series likewise uses the smooth fit
    via `getSpot()`.
    """
    fr007 = env_ts['FR007.IR'].dropna()
    shibor3m = env_ts['SHIBOR3M.IR'].dropna()
    if d not in fr007.index:
        d = fr007.index[-1]
    fixings = {'close': {'r7d': fr007.loc[d], 's3m': shibor3m.loc[d]}}
    fixing_set_ts = {'r7d': env_ts['FR007.IR'].dropna(), 's3m': env_ts['SHIBOR3M.IR'].dropna()}
    fixing_fwd_ts, spot_ts, fixing_ts = {}, {}, {}
    for ct in IRSConfig.CURVE_TYPES:
        start = d + relativedelta(days=1)
        end = d + relativedelta(years=10)
        workdays = loadWorkday(start, end)
        anchor_fixing = curves[ct].anchor['ForwardRate']
        anchor_fixing.loc[0] = fixings['close'][ct]
        anchor_fixing = anchor_fixing.sort_index().dropna()
        anchor_fixing = anchor_fixing[anchor_fixing.index < 0.25]
        forward_curve = curves[ct].adjcurves['ForwardRate'] if adj else curves[ct].curves['ForwardRate']
        combined_fixing = pd.concat([anchor_fixing, forward_curve], axis=0).sort_index().dropna()
        terms = [(day - d).days / GeneralConfig.YN for day in workdays]
        combined_fixing.loc[terms[-1]] = combined_fixing.iloc[-1]
        fixing_values = interpolate_with_extrapolation(combined_fixing.index, combined_fixing.values, terms)
        fixing_fwd_ts[ct] = pd.Series(fixing_values, index=workdays)
        fixing_fwd_ts[ct].iloc[0] = fixings['close'][ct]
        spot_ts[ct] = getSpot(d, curves[ct], fixings['close'][ct], adj)
        historical_days = [day for day in fixing_set_ts[ct].index if day not in fixing_fwd_ts[ct].index]
        fixing_ts[ct] = pd.concat([fixing_set_ts[ct].loc[historical_days], fixing_fwd_ts[ct]], axis=0)
    return {'fixing': fixing_ts, 'spot': spot_ts, 'date': d}
