# -*- coding: utf-8 -*-
"""IRS curve generation and calibration."""

from datetime import date
from typing import Dict

import pandas as pd
from dateutil.relativedelta import relativedelta

from settings.fixed_income import IRSConfig
from curves.affine.curve import IRSCurve

from curves.calibration.irs.data import CurveDataManager
from curves.calibration.irs.tenors import TenorConverter


class CurveGenerator:
    """Generates and calibrates IRS curves."""

    def __init__(self, curve_data_manager: CurveDataManager, tenor_converter: TenorConverter):
        self.curve_data_manager = curve_data_manager
        self.tenor_converter = tenor_converter

    def generate_curves(self, env: pd.DataFrame, irs_ref: Dict, target_date: date) -> Dict[str, IRSCurve]:
        """Generate IRS curves for all curve types."""
        curve_ts = {ct: env[irs_ref[ct]].dropna(how='all') for ct in IRSConfig.CURVE_TYPES}
        last_curve = curve_ts['r7d']

        if target_date in last_curve.index:
            prev_date = last_curve.index[last_curve.index.get_indexer([target_date])[0] - 1]
        elif target_date > last_curve.index[-1]:
            prev_date = last_curve.index[-1]
        else:
            prev_date = last_curve.index[last_curve.index.get_indexer([target_date], method='ffill')[0]]

        print(f'Computing day: {target_date.strftime("%Y-%m-%d")}')
        print(f'Last day:      {prev_date.strftime("%Y-%m-%d")}')

        self.curve_data_manager.load()

        if not self.curve_data_manager.has_date('r7d', prev_date):
            start = target_date - relativedelta(months=1)
            timewindow = env.loc[start:target_date].dropna().index[-3:]
            for ct in IRSConfig.CURVE_TYPES:
                self._extract_historical_spots(curve_ts[ct], timewindow, ct)

        curves = {}
        start = target_date - relativedelta(months=1)
        timewindow = env.loc[start:target_date].dropna().index

        for ct in IRSConfig.CURVE_TYPES:
            curves[ct] = self._generate_single_curve(
                ct, prev_date, target_date, curve_ts[ct], timewindow
            )

        self.curve_data_manager.save()

        return curves

    def _generate_single_curve(self, curve_type: str, prev_date: date,
                               target_date: date, curve_ts: pd.Series,
                               timewindow: pd.DatetimeIndex) -> IRSCurve:
        """Generate a single curve for a given curve type."""
        curve_data = self.curve_data_manager.load()
        spot_data = curve_data[curve_type]['spot']
        common = [d for d in timewindow if d in spot_data.index]
        spot_data = spot_data.loc[common]
        spot_data = self._normalize_tenor_columns(spot_data)

        available_labels = [lbl for lbl in IRSConfig.TENOR_MAP.values() if lbl in spot_data.columns]
        inv_tenor_map = {v: k for k, v in IRSConfig.TENOR_MAP.items()}
        terms_for_labels = [inv_tenor_map[lbl] for lbl in available_labels]

        spot_key = spot_data[available_labels]
        spot_key.columns = [f'Term at {t}' for t in available_labels]
        term_data = pd.DataFrame(
            [terms_for_labels] * len(spot_key),
            index=spot_key.index,
            columns=spot_key.columns
        )

        curve = IRSCurve(prev_date, curve_type)
        curve.extractKeySpot(curve_ts.loc[prev_date])
        curve.interpolateCurve()
        curve.calibrate(term_data.dropna(), spot_key.dropna())

        df_ref = pd.Series(
            spot_key.loc[prev_date].values,
            index=term_data.loc[prev_date].values,
            name='Ref Spot'
        )
        curve.extractFactors(df_ref)
        curve.fitting()

        sr = curve.anchor['SpotRate']
        terms = self.tenor_converter.to_string(sr.index.tolist())
        fr = curve.anchor['ForwardRate']
        self.curve_data_manager.update_curve(curve_type, prev_date, sr.values, fr.values, terms)

        return curve

    @staticmethod
    def _normalize_tenor_columns(spot_data: pd.DataFrame) -> pd.DataFrame:
        """Normalize legacy tenor labels to current 's' labels.

        Example: '3m' -> '1s', '6m' -> '2s', '9m' -> '3s', '1y' -> '4s'
        """
        legacy_to_current = {
            '3m': '1s',
            '6m': '2s',
            '9m': '3s',
            '1y': '4s'
        }

        spot_data = spot_data.copy()

        for legacy, current in legacy_to_current.items():
            if legacy not in spot_data.columns:
                continue

            if current in spot_data.columns:
                spot_data[current] = spot_data[current].where(
                    ~spot_data[current].isna(), spot_data[legacy]
                )
                spot_data = spot_data.drop(columns=[legacy])
            else:
                spot_data = spot_data.rename(columns={legacy: current})

        return spot_data

    @staticmethod
    def _normalize_tenor_index(tenor_series: pd.Series) -> pd.Series:
        """Normalize legacy tenor index labels to the current 's' labels."""
        if tenor_series is None or tenor_series.empty:
            return tenor_series

        legacy_to_current = {
            '3m': '1s',
            '6m': '2s',
            '9m': '3s',
            '1y': '4s'
        }

        sr = tenor_series.copy()
        sr.index = [str(i).strip().lower() for i in sr.index]

        for legacy, current in legacy_to_current.items():
            if legacy not in sr.index:
                continue

            if current in sr.index:
                try:
                    if pd.isna(sr.loc[current]):
                        sr.loc[current] = sr.loc[legacy]
                except Exception:
                    pass
                sr = sr.drop(index=legacy)
            else:
                sr = sr.rename(index={legacy: current})

        if sr.index.has_duplicates:
            sr = sr.groupby(level=0).apply(lambda x: x.dropna().iloc[-1] if x.dropna().size else x.iloc[-1])

        return sr

    def _extract_historical_spots(self, curve_ts: pd.Series, timewindow: pd.DatetimeIndex,
                                  curve_type: str):
        """Extract historical spot data for a curve type over a time window."""
        spot_data = {}
        forward_data = {}
        curve_instance = None

        for target_date in timewindow:
            if curve_instance is None:
                curve_instance = IRSCurve(target_date, curve_type)
            else:
                curve_instance.day = target_date

            curve_instance.extractKeySpot(curve_ts.loc[target_date])
            curve_instance.interpolateCurve()

            sr = curve_instance.anchor['SpotRate']
            sr.index = self.tenor_converter.to_string(sr.index.tolist())
            spot_data[target_date] = sr

            fr = curve_instance.anchor['ForwardRate']
            fr.index = self.tenor_converter.to_string(fr.index.tolist())
            forward_data[target_date] = fr

        curve_data = self.curve_data_manager.load()
        new_spot = pd.concat(spot_data, axis=1).T
        new_forward = pd.concat(forward_data, axis=1).T
        existing_spot = curve_data[curve_type]['spot']
        existing_forward = curve_data[curve_type]['forward']
        add_mask_spot = ~new_spot.index.isin(existing_spot.index)
        add_mask_fwd = ~new_forward.index.isin(existing_forward.index)
        if add_mask_spot.any():
            curve_data[curve_type]['spot'] = pd.concat(
                [existing_spot, new_spot[add_mask_spot]]
            ).sort_index()
        if add_mask_fwd.any():
            curve_data[curve_type]['forward'] = pd.concat(
                [existing_forward, new_forward[add_mask_fwd]]
            ).sort_index()
