# -*- coding: utf-8 -*-
"""
OOP-Optimized IRS Curves Calibration Module

Refactored for better performance, structure, and maintainability using OOP principles.
Author: 马云飞 (refactored)
"""

import os
import re
from typing import Dict, List, Tuple, Optional, Union
from datetime import date
import pandas as pd
import numpy as np
from dateutil.relativedelta import relativedelta
from scipy import interpolate

from settings.general import GeneralConfig, DateConfig
from settings.fixed_income import IRSConfig
from settings.paths import DIR_INPUT
from curves.affine.pricingYield import pricing, pricingYield, scheduleDate, floaters
from curves.affine.curve import IRSCurve
from curves.utils.loader import loadWorkday
from curves.utils.file import updatePKL


# ============================================================
# UTILITY CLASSES
# ============================================================

class TenorConverter:
    """Handles tenor string/numeric conversions with caching."""
    
    def __init__(self):
        self._yn = GeneralConfig.YN
        self._cache_str2num = {}
        self._cache_num2str = {}
    
    def to_string(self, tenor_list: List[float]) -> List[str]:
        """Convert numeric tenors to string format (e.g., 7d, 3m, 1s)."""
        result = []
        for d in tenor_list:
            if d in self._cache_num2str:
                result.append(self._cache_num2str[d])
                continue
            
            if d * self._yn < 15:
                s = f"{int(round(d * self._yn))}d"
            elif d * self._yn < 90:
                s = f"{int(round(d * 12))}m"
            else:
                s = f"{int(round(d * 4))}s"
            
            self._cache_num2str[d] = s
            result.append(s)
        return result
    
    def to_numeric(self, tenor_str_list: List[Union[str, float, int]]) -> List[float]:
        """Convert string format to numeric tenors (inverse of to_string)."""
        result = []
        for s in tenor_str_list:
            if isinstance(s, (int, float)):
                result.append(s)
                continue
            
            if s in self._cache_str2num:
                result.append(self._cache_str2num[s])
                continue
            
            s = str(s).strip().lower()
            if s.endswith('d'):
                val = int(s[:-1]) / self._yn
            elif s.endswith('m'):
                val = int(s[:-1]) / 12.0
            elif s.endswith('s'):
                val = int(s[:-1]) / 4.0
            else:
                raise ValueError(f"Invalid tenor format: {s}")
            
            self._cache_str2num[s] = val
            result.append(val)
        return result


class Interpolator:
    """Handles interpolation and extrapolation with robust error handling."""
    
    @staticmethod
    def interpolate_with_extrapolation(x_known: np.ndarray, y_known: np.ndarray, 
                                       x_target: np.ndarray) -> np.ndarray:
        """
        Interpolate with linear extrapolation beyond bounds.
        
        Parameters:
        -----------
        x_known : array-like
            Known x values (must be sorted)
        y_known : array-like  
            Known y values corresponding to x_known
        x_target : array-like
            Target x values to interpolate/extrapolate
            
        Returns:
        --------
        ndarray : Interpolated/extrapolated y values
        """
        x_known = np.asarray(x_known)
        y_known = np.asarray(y_known)
        x_target = np.asarray(x_target)
        
        # Filter out NaN values from input data
        valid_mask = ~np.isnan(y_known)
        if not np.any(valid_mask):
            return np.full_like(x_target, np.nan, dtype=float)
        
        x_valid = x_known[valid_mask]
        y_valid = y_known[valid_mask]
        
        if len(x_valid) == 0:
            return np.full_like(x_target, np.nan, dtype=float)
        elif len(x_valid) == 1:
            return np.full_like(x_target, y_valid[0], dtype=float)
        
        # Create interpolator for values within bounds
        interpolator = interpolate.interp1d(x_valid, y_valid, kind='linear', 
                                           bounds_error=False, fill_value=np.nan)
        result = interpolator(x_target)
        
        # Handle extrapolation for values outside bounds
        min_x, max_x = x_valid.min(), x_valid.max()
        
        # Linear extrapolation below minimum
        below_mask = x_target < min_x
        if np.any(below_mask):
            slope = (y_valid[1] - y_valid[0]) / (x_valid[1] - x_valid[0])
            result[below_mask] = y_valid[0] + slope * (x_target[below_mask] - x_valid[0])
        
        # Linear extrapolation above maximum
        above_mask = x_target > max_x
        if np.any(above_mask):
            slope = (y_valid[-1] - y_valid[-2]) / (x_valid[-1] - x_valid[-2])
            result[above_mask] = y_valid[-1] + slope * (x_target[above_mask] - x_valid[-1])
        
        return result


class CurveDataManager:
    """Manages IRS curve data loading, caching, and persistence."""
    
    def __init__(self, data_path: str = None):
        self.data_path = data_path or os.path.join(DIR_INPUT, 'IRS-cvdata.pkl')
        self._curve_data = None
        self._last_load_time = None
        self._did_migrate_legacy_tenors = False

    def _migrate_legacy_tenors(self) -> bool:
        """Backfill legacy tenor columns (e.g., '3m') into current ones (e.g., '1s')."""
        if self._curve_data is None:
            return False

        legacy_to_current = {
            '3m': '1s',
            '6m': '2s',
            '9m': '3s',
            '1y': '4s'
        }

        changed = False
        for curve_type in IRSConfig.CURVE_TYPES:
            for kind in ['spot', 'forward']:
                df = self._curve_data.get(curve_type, {}).get(kind)
                if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                    continue

                for legacy, current in legacy_to_current.items():
                    if legacy not in df.columns:
                        continue

                    if current not in df.columns:
                        df[current] = df[legacy]
                        changed = True
                    else:
                        before_na = df[current].isna().sum()
                        df[current] = df[current].where(~df[current].isna(), df[legacy])
                        after_na = df[current].isna().sum()
                        if after_na != before_na:
                            changed = True

        return changed
    
    def load(self, force_reload: bool = False) -> Dict:
        """Load curve data from pickle file with caching."""
        if self._curve_data is None or force_reload:
            if os.path.exists(self.data_path):
                self._curve_data = pd.read_pickle(self.data_path)
                # One-time migration for legacy tenor labels stored in existing pickles
                if not self._did_migrate_legacy_tenors:
                    if self._migrate_legacy_tenors():
                        print("Migrated legacy tenors in IRS-cvdata (e.g., 3m -> 1s).")
                        self.save()
                    self._did_migrate_legacy_tenors = True
            else:
                # Initialize empty structure
                self._curve_data = {
                    ct: {'spot': pd.DataFrame(), 'forward': pd.DataFrame()}
                    for ct in IRSConfig.CURVE_TYPES
                }
        return self._curve_data
    
    def save(self) -> Dict:
        """Save curve data to pickle file."""
        if self._curve_data is not None:
            self._curve_data = updatePKL(self._curve_data, self.data_path)
        return self._curve_data
    
    def update_curve(self, curve_type: str, date: date, spot_values: pd.Series, 
                     forward_values: pd.Series, tenor_labels: List[str]):
        """Update curve data for a specific date and curve type."""
        if self._curve_data is None:
            self.load()
        
        self._curve_data[curve_type]['spot'].loc[date, tenor_labels] = spot_values
        self._curve_data[curve_type]['forward'].loc[date, tenor_labels] = forward_values
    
    def has_date(self, curve_type: str, target_date: date) -> bool:
        """Check if curve data exists for a given date."""
        if self._curve_data is None:
            self.load()
        return target_date in self._curve_data[curve_type]['spot'].index
    
    def get_curve(self, curve_type: str, date: date, curve_kind: str = 'spot') -> pd.Series:
        """Get curve data for a specific date."""
        if self._curve_data is None:
            self.load()
        return self._curve_data[curve_type][curve_kind].loc[date]


class FixingRateProvider:
    """Provides fixing rates and spot rates with interpolation."""
    
    def __init__(self, tenor_converter: TenorConverter):
        self.tenor_converter = tenor_converter
        self.interpolator = Interpolator()
    
    def get_fixing_series(self, trade_date: date, workdays: pd.DatetimeIndex, 
                         forward_data: pd.Series, fixing_rate: float) -> pd.Series:
        """
        Generate fixing rate series for given workdays.
        
        Parameters:
        -----------
        trade_date : date
            Trade date
        workdays : pd.DatetimeIndex
            Working days to generate fixings for
        forward_data : pd.Series
            Forward rate data indexed by tenor strings
        fixing_rate : float
            Current fixing rate
            
        Returns:
        --------
        pd.Series : Fixing rates for each workday
        """
        # Convert tenor strings to numeric
        tenor_numeric = self.tenor_converter.to_numeric(list(forward_data.index))
        forward_data_numeric = pd.Series(forward_data.values, index=tenor_numeric)
        forward_data_numeric.loc[0] = fixing_rate
        forward_data_numeric = (
            forward_data_numeric.sort_index()
            .groupby(level=0)
            .apply(lambda x: x.dropna().iloc[-1] if x.dropna().size else x.iloc[-1])
            .dropna()
        )
        
        # Calculate terms for workdays
        terms = [(day - trade_date).days / GeneralConfig.YN for day in workdays]
        
        # Add end point for extrapolation
        forward_data_numeric.loc[terms[-1]] = forward_data_numeric.iloc[-1]
        
        # Interpolate/extrapolate
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
        # Convert tenor strings to numeric
        tenor_numeric = self.tenor_converter.to_numeric(list(spot_data.index))
        spot_data_numeric = pd.Series(spot_data.values, index=tenor_numeric)
        spot_data_numeric.loc[0] = fixing_rate
        spot_data_numeric = (
            spot_data_numeric.sort_index()
            .groupby(level=0)
            .apply(lambda x: x.dropna().iloc[-1] if x.dropna().size else x.iloc[-1])
            .dropna()
        )
        
        # Calculate terms for workdays
        terms = [(day - trade_date).days / GeneralConfig.YN for day in workdays]
        
        # Add end point
        spot_data_numeric.loc[terms[-1]] = spot_data_numeric.iloc[-1]
        
        # Interpolate/extrapolate
        spot_values = self.interpolator.interpolate_with_extrapolation(
            spot_data_numeric.index.values,
            spot_data_numeric.values,
            np.array(terms)
        )
        
        result = pd.Series(spot_values, index=workdays)
        result.iloc[0] = fixing_rate
        return result


class CurveGenerator:
    """Generates and calibrates IRS curves."""
    
    def __init__(self, curve_data_manager: CurveDataManager, tenor_converter: TenorConverter):
        self.curve_data_manager = curve_data_manager
        self.tenor_converter = tenor_converter
    
    def generate_curves(self, env: pd.DataFrame, irs_ref: Dict, target_date: date) -> Dict[str, IRSCurve]:
        """
        Generate IRS curves for all curve types.
        
        Parameters:
        -----------
        env : pd.DataFrame
            Environment data containing IRS time series
        irs_ref : Dict
            Reference instruments for each curve type
        target_date : date
            Target date for curve generation
            
        Returns:
        --------
        Dict[str, IRSCurve] : Generated curves by curve type
        """
        # Extract time series for each curve type
        curve_ts = {ct: env[irs_ref[ct]].dropna(how='all') for ct in IRSConfig.CURVE_TYPES}
        last_curve = curve_ts['r7d']
        
        # Determine previous date
        if target_date in last_curve.index:
            prev_date = last_curve.index[last_curve.index.get_indexer([target_date])[0] - 1]
        elif target_date > last_curve.index[-1]:
            prev_date = last_curve.index[-1]
        else:
            prev_date = last_curve.index[last_curve.index.get_indexer([target_date], method='ffill')[0]]
        
        print(f'Computing day: {target_date.strftime("%Y-%m-%d")}')
        print(f'Last day:      {prev_date.strftime("%Y-%m-%d")}')
        
        # Load curve data
        curve_data = self.curve_data_manager.load()
        
        # Extract historical spots if needed
        if not self.curve_data_manager.has_date('r7d', prev_date):
            start = target_date - relativedelta(months=1)
            timewindow = env.loc[start:target_date].dropna().index[-3:]
            for ct in IRSConfig.CURVE_TYPES:
                self._extract_historical_spots(curve_ts[ct], timewindow, ct)
        
        # Generate curves for each type
        curves = {}
        start = target_date - relativedelta(months=1)
        timewindow = env.loc[start:target_date].dropna().index
        
        for ct in IRSConfig.CURVE_TYPES:
            curves[ct] = self._generate_single_curve(
                ct, prev_date, target_date, curve_ts[ct], timewindow
            )
        
        # Save updated curve data
        self.curve_data_manager.save()
        
        return curves
    
    def _generate_single_curve(self, curve_type: str, prev_date: date, 
                               target_date: date, curve_ts: pd.Series, 
                               timewindow: pd.DatetimeIndex) -> IRSCurve:
        """Generate a single curve for a given curve type."""
        # Get spot data
        curve_data = self.curve_data_manager.load()
        spot_data = curve_data[curve_type]['spot']
        common = [d for d in timewindow if d in spot_data.index]
        spot_data = spot_data.loc[common]
        spot_data = self._normalize_tenor_columns(spot_data)
        
        # Extract available tenors
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
        
        # Create and calibrate curve
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
        
        # Update curve data
        sr = curve.anchor['SpotRate']
        terms = self.tenor_converter.to_string(sr.index.tolist())
        fr = curve.anchor['ForwardRate']
        self.curve_data_manager.update_curve(curve_type, prev_date, sr.values, fr.values, terms)
        
        return curve

    @staticmethod
    def _normalize_tenor_columns(spot_data: pd.DataFrame) -> pd.DataFrame:
        """
        Normalize legacy tenor labels to current 's' labels.

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
        
        # Update curve data manager — append new rows, do not overwrite existing history
        curve_data = self.curve_data_manager.load()
        new_spot = pd.concat(spot_data, axis=1).T
        new_forward = pd.concat(forward_data, axis=1).T
        existing_spot = curve_data[curve_type]['spot']
        existing_forward = curve_data[curve_type]['forward']
        add_mask_spot = ~new_spot.index.isin(existing_spot.index)
        add_mask_fwd  = ~new_forward.index.isin(existing_forward.index)
        if add_mask_spot.any():
            curve_data[curve_type]['spot'] = pd.concat(
                [existing_spot, new_spot[add_mask_spot]]
            ).sort_index()
        if add_mask_fwd.any():
            curve_data[curve_type]['forward'] = pd.concat(
                [existing_forward, new_forward[add_mask_fwd]]
            ).sort_index()


# ============================================================
# REFACTORED IRS CONTRACT CLASS
# ============================================================

class IRSContract:
    """Enhanced IRS Contract with better structure and validation."""
    
    def __init__(self, start_date: date, end_date: date, quote: float, 
                 curve_type: str, frequency: int):
        """
        Initialize IRS contract.
        
        Parameters:
        -----------
        start_date : date
            Contract start date
        end_date : date
            Contract maturity date
        quote : float
            Fixed rate quote (in percentage)
        curve_type : str
            Curve type ('r7d' or 's3m')
        frequency : int
            Payment frequency (0 for short-term, 4 for standard)
        """
        self.start_date = start_date
        self.end_date = end_date
        self.quote = quote
        self.curve_type = curve_type
        self.frequency = frequency
        
        # Generate schedule
        self.schedule = scheduleDate(start_date, end_date, curve_type, frequency)
        
        # Calculate duration and convexity
        ytm = pricingYield(self.schedule[0], quote, self.schedule, 4, 100)
        _, _, self.duration, self.convexity = pricing(
            self.schedule[0], quote, self.schedule, 4, ytm
        )
        
        # Initialize valuation results
        self.cashflow = None
        self.fix_rate = None
        self.pnl_realised = None
        self.pnl_predicted = None
        self.pnl_predicted_dc = None
        self.pnl_total = None
        self.value = None
        self.pv_sum = None
    
    def valuation(self, notional: float, valuation_date: date,
                           fixing_series: pd.Series, spot_series: pd.Series):
        """
        Perform contract valuation.
        
        Parameters:
        -----------
        notional : float
            Contract notional amount
        valuation_date : date
            Date of valuation
        fixing_series : pd.Series
            Forward fixing rates indexed by date
        spot_series : pd.Series
            Spot rates indexed by date
        """
        # Initialize cashflow DataFrame
        cashflow = pd.DataFrame(index=self.schedule[:-1])
        P = notional
        
        for i in range(len(self.schedule) - 1):
            s = self.schedule[i]
            s1 = self.schedule[i + 1]
            
            # Determine notional at maturity
            N = P * 1e4 if i == len(self.schedule) - 2 else 0
            
            # Cashflow type
            cashflow.loc[s, 'CashFlowType'] = "Set" if s1 <= valuation_date else "Predicted"
            
            # Get floating rate fixings
            fdays = floaters(s, s1, 7)
            idx = [fixing_series.index.get_indexer([d], method="ffill")[0] for d in fdays]
            fs = fixing_series.iloc[idx]
            
            interval = (s1 - s).days / GeneralConfig.YN
            cashflow.loc[s, 'Fixing'] = fs.iloc[0]
            cashflow.loc[s, 'FixingDate'] = fs.index[0]
            
            # Calculate floating rate
            if self.curve_type == 'r7d':
                r0 = self._calculate_r7d_floating(s, s1, fs, fdays)
            elif self.curve_type == 's3m':
                r0 = 1 + fs.iloc[0] * interval * GeneralConfig.YN / GeneralConfig.YN1 / 100
            
            cashflow.loc[s, 'Floating'] = 100 * (r0 - 1) / interval
            cashflow.loc[s, 'CashFlow(Float)'] = 1e4 * P * (r0 - 1) + N
            cashflow.loc[s, 'CashFlow(Fixed)'] = 100 * P * self.quote * interval + N
            cashflow.loc[s, 'PayDate'] = s1
            cashflow.loc[s, 'Interval'] = interval
        
        # Net cashflows
        cashflow['CashFlow(NetPay)'] = cashflow['CashFlow(Float)'] - cashflow['CashFlow(Fixed)']
        
        # Separate set and forward schedules
        schedule_set = list(cashflow[cashflow['CashFlowType'] == "Set"].index)
        schedule_fwd = list(cashflow[cashflow['CashFlowType'] == "Predicted"].index)
        
        # Calculate discount factors
        cashflow['DF'] = 1.0
        cashflow['TermRes'] = 0.0
        cashflow['SpotRate'] = 0.0

        # Maintain a running sum that mirrors the original
        # `(cashflow['Interval'].iloc[:i] * cashflow['DF'].iloc[:i]).sum()` —
        # incremental update keeps the bootstrap O(N) instead of O(N^2).
        interval_vals = cashflow['Interval'].to_numpy(dtype=float)
        df_vals = cashflow['DF'].to_numpy(dtype=float).copy()
        fwd_offset = len(cashflow) - len(schedule_fwd)
        sum_term = 0.0

        for i, s in enumerate(schedule_fwd):
            s1 = cashflow.loc[s, 'PayDate']
            res = (s1 - valuation_date).days / GeneralConfig.YN
            cashflow.loc[s, 'TermRes'] = res

            idx = spot_series.index.get_indexer([s1], method="ffill")[0]
            spot = spot_series.iloc[idx] / 100
            cashflow.loc[s, 'SpotRate'] = spot * 100

            if i == 0:
                new_df = 1 / (1 + spot * res * GeneralConfig.YN / GeneralConfig.YN1)
            else:
                new_df = (1 - spot * sum_term) / (1 + spot * cashflow.loc[s, 'Interval'])
            cashflow.loc[s, 'DF'] = new_df
            df_vals[fwd_offset + i] = new_df
            sum_term += interval_vals[i] * df_vals[i]
        
        # Present values
        cashflow['PV(Float)'] = cashflow['CashFlow(Float)'] * cashflow['DF']
        cashflow['PV(Fixed)'] = cashflow['CashFlow(Fixed)'] * cashflow['DF']
        cashflow['PV(NetPay)'] = cashflow['CashFlow(NetPay)'] * cashflow['DF']
        
        # Calculate summary metrics
        pv_sum = cashflow[[
            'CashFlow(Float)', 'CashFlow(Fixed)', 'CashFlow(NetPay)',
            'PV(Float)', 'PV(Fixed)', 'PV(NetPay)'
        ]].sum(axis=0)
        
        ND = P * 1e4 * cashflow['DF'].iloc[-1]
        temp = (cashflow['Interval'] * cashflow['DF']).sum()
        floating_leg = cashflow['PV(Float)'].sum() - ND
        
        # Store results
        self.fix_rate = floating_leg / temp / P / 100
        self.pnl_realised = cashflow.loc[schedule_set, 'CashFlow(NetPay)'].sum() if schedule_set else 0
        self.pnl_predicted = cashflow.loc[schedule_fwd, 'CashFlow(NetPay)'].sum() if schedule_fwd else 0
        self.pnl_predicted_dc = (
            cashflow.loc[schedule_fwd, 'CashFlow(NetPay)'] * 
            cashflow.loc[schedule_fwd, 'DF']
        ).sum() if schedule_fwd else 0
        self.pnl_total = self.pnl_realised + self.pnl_predicted
        self.value = self.pnl_realised + self.pnl_predicted_dc
        self.cashflow = cashflow
        self.pv_sum = pv_sum
    
    def _calculate_r7d_floating(self, s: date, s1: date, fs: pd.Series, fdays: List[date]) -> float:
        """Calculate R7D floating accrual using actual overlap days for each reset."""
        r0 = 1.0
        for fixing_date, rate in zip(fdays, fs):
            period_start = max(s, fixing_date)
            period_end = min(s1, fixing_date + relativedelta(days=7))
            day_count = (period_end - period_start).days
            if day_count <= 0:
                continue
            r0 *= (1 + rate * day_count / GeneralConfig.YN1 / 100)
        return r0
    
    @property
    def PnL(self):
        """Alias for total PnL."""
        return self.pnl_total
    
    @property
    def Value(self):
        """Alias for contract value."""
        return self.value
    
    @property
    def fixrate(self):
        """Alias for fix rate."""
        return self.fix_rate
    
    @property
    def cov(self):
        """Alias for convexity."""
        return self.convexity


# ============================================================
# FACADE/API FUNCTIONS (backward compatibility)
# ============================================================

# Global instances for backward compatibility
_tenor_converter = TenorConverter()
_curve_data_manager = CurveDataManager()
_fixing_provider = FixingRateProvider(_tenor_converter)
_curve_generator = CurveGenerator(_curve_data_manager, _tenor_converter)

def tenor2str(tenor_list):
    """Convert tenors to string format (legacy wrapper)."""
    return _tenor_converter.to_string(tenor_list)

def str2tenor(tenor_str_list):
    """Convert string format to tenors (legacy wrapper)."""
    return _tenor_converter.to_numeric(tenor_str_list)

def interpolate_with_extrapolation(x_known, y_known, x_target):
    """Interpolate with extrapolation (legacy wrapper)."""
    return Interpolator.interpolate_with_extrapolation(x_known, y_known, x_target)

def genIRSCurves(env, irs_ref, d):
    """Generate IRS curves (legacy wrapper)."""
    return _curve_generator.generate_curves(env, irs_ref, d)

def px2Fixings(td):
    """Get fixing and spot data for a trade date (refactored)."""
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

def irsContract(start_date, end_date, quote, curve_type, frequency):
    """Create IRS contract (legacy wrapper using new class)."""
    return IRSContract(start_date, end_date, quote, curve_type, frequency)


# ============================================================
# ADDITIONAL UTILITY FUNCTIONS (kept as-is for now)
# ============================================================

def filter_terms_by_range(terms, workdays, index_range, allow_extrapolation=False):
    """Filter terms and corresponding workdays to only include values within index range."""
    if allow_extrapolation:
        return terms, workdays
    
    min_term, max_term = index_range.min(), index_range.max()
    valid_mask = [(min_term <= t <= max_term) for t in terms]
    valid_terms = [t for t, valid in zip(terms, valid_mask) if valid]
    valid_workdays = [wd for wd, valid in zip(workdays, valid_mask) if valid]
    return valid_terms, valid_workdays

def irsSpreads(qtpx):
    """Calculate IRS spreads (serial, fly, basis, box) efficiently."""
    repo_cols = qtpx.columns[qtpx.columns.str.contains('FR007S') & ~qtpx.columns.str.contains('1M|2M|7Y|10Y')]
    shibor_cols = qtpx.columns[qtpx.columns.str.contains('SHI3MS') & ~qtpx.columns.str.contains('7Y|10Y')]
    repos, shibors = qtpx[repo_cols], qtpx[shibor_cols]
    spreads = {}
    for j in range(1, 5):
        spreads[f'repo{j}s'] = repos.diff(j, axis=1).iloc[:, j:]
    for j in range(1, 5):
        spreads[f'shi3M{j}s'] = shibors.diff(j, axis=1).iloc[:, j:]
    pairs = pd.concat(spreads, axis=1)
    pairs.columns = IRSConfig.PAIRS
    flys = _calculate_fly_spreads(repos, shibors)
    rmap = {0:'3m', 1:'6m', 2:'9m', 3:'1y', 4:'2y', 5:'3y', 6:'4y', 7:'5y'}
    basis = pd.DataFrame({f'Basis-{rmap[i+1]}': shibors.iloc[:, i] - repos.iloc[:, i+1]
                         for i in range(min(len(shibor_cols), len(repo_cols)-1))})
    box = pd.concat({f'Basis-{j}s': basis.diff(j, axis=1).iloc[:, j:] for j in range(1, 5)}, axis=1)
    box.columns = IRSConfig.BOX
    return pd.concat([pairs, flys, basis, box], axis=1)

def _calculate_fly_spreads(repos, shibors):
    """Calculate fly spreads for repo and shibor."""
    rmap = {0:'3m', 1:'6m', 2:'9m', 3:'1y', 4:'2y', 5:'3y', 6:'4y', 7:'5y'}
    spreads = {}
    for i in range(len(repos.columns) - 2):
        for j in range(i + 1, len(repos.columns) - 1):
            for k in range(j + 1, len(repos.columns)):
                spreads[f'Repo-{rmap[i]}{rmap[j]}{rmap[k]}'] = 2 * repos.iloc[:, j] - (repos.iloc[:, i] + repos.iloc[:, k])
    for i in range(len(shibors.columns) - 2):
        for j in range(i + 1, len(shibors.columns) - 1):
            for k in range(j + 1, len(shibors.columns)):
                spreads[f'Shi3M-{rmap[i+1]}{rmap[j+1]}{rmap[k+1]}'] = 2 * shibors.iloc[:, j] - (shibors.iloc[:, i] + shibors.iloc[:, k])
    return pd.concat(spreads, axis=1) if spreads else pd.DataFrame()

def irsSpreadsRatio(spread_list):
    """Calculate ratio for each spread type."""
    ratio = {}
    for s in spread_list:
        note = s.split('-')[1]
        if len(note) == 2:
            ratio[s] = 1
        elif len(note) == 4:
            ratio[s] = IRSConfig.TERM_MAP[note[2:]] / IRSConfig.TERM_MAP[note[:2]]
        elif len(note) == 6:
            t1, t2, t3 = IRSConfig.TERM_MAP[note[2:4]], IRSConfig.TERM_MAP[note[:2]], IRSConfig.TERM_MAP[note[4:]]
            ratio[s] = [t1 / t2 / 2, t1 / t3 / 2]
    return ratio

def _irs_quote_spread_weights(sp):
    """Return quote weights matching the spread definitions used in QtPx."""
    f, s, t = 'FR007S', 'SHI3MS', '.IR'
    stype, note = sp.split('-')
    tenors = [token.upper() for token in re.findall(r'\d+[my]', note.lower())]

    if stype in ['Repo', 'Shi3M']:
        prefix = f if stype == 'Repo' else s
        if len(tenors) == 2:
            return {
                prefix + tenors[1] + t: 1.0,
                prefix + tenors[0] + t: -1.0,
            }
        if len(tenors) == 3:
            return {
                prefix + tenors[1] + t: 2.0,
                prefix + tenors[0] + t: -1.0,
                prefix + tenors[2] + t: -1.0,
            }
    if stype == 'Basis':
        if len(tenors) == 1:
            return {
                s + tenors[0] + t: 1.0,
                f + tenors[0] + t: -1.0,
            }
        if len(tenors) == 2:
            later = _irs_quote_spread_weights(f'Basis-{tenors[1].lower()}')
            earlier = _irs_quote_spread_weights(f'Basis-{tenors[0].lower()}')
            merged = later.copy()
            for instrument, weight in earlier.items():
                merged[instrument] = merged.get(instrument, 0.0) - weight
            return merged
    raise KeyError(f'Unsupported IRS quote spread: {sp}')

def irsQuoteComposite(spread_list, cost, *, quote_side, opposite_cost):
    """Calculate tradable bid/ofr quotes for IRS spreads using crossed-side legs."""
    spread_cost = pd.Series(index=spread_list, dtype=float)
    for sp in spread_list:
        weights = _irs_quote_spread_weights(sp)
        value = 0.0
        for instrument, weight in weights.items():
            if quote_side == 'Bid':
                series = cost if weight > 0 else opposite_cost
            else:
                series = cost if weight > 0 else opposite_cost
            value += weight * series[instrument]
        spread_cost[sp] = value
    return spread_cost

def irsSpreadComposite(spread_list, cost):
    """Calculate composite spread costs."""
    f, s, t = 'FR007S', 'SHI3MS', '.IR'
    irs_ratio = irsSpreadsRatio(spread_list)
    spread_cost = pd.Series(index=spread_list)
    for sp in spread_list:
        stype, note = sp.split('-')
        note = note.upper()
        if stype == 'Basis':
            if len(note) == 2:
                spread_cost[sp] = cost[s + note + t] - irs_ratio[sp] * cost[f + note + t]
            else:
                spread_cost[sp] = spread_cost[f'{stype}-{note[2:].lower()}'] - spread_cost[f'{stype}-{note[:2].lower()}']
        elif stype in ['Repo', 'Shi3M']:
            prefix = f if stype == 'Repo' else s
            if len(note) == 4:
                spread_cost[sp] = cost[prefix + note[2:] + t] - irs_ratio[sp] * cost[prefix + note[:2] + t]
            else:
                spread_cost[sp] = (cost[prefix + note[2:4] + t] - irs_ratio[sp][0] * cost[prefix + note[:2] + t] - irs_ratio[sp][1] * cost[prefix + note[4:] + t])
    return spread_cost

def get_swap_quote_frame(swap_rt, tickers=None, threshold_bp=10, fallback_quotes=None):
    """Return Bid/Ofr/Mid swap quotes with guarded realtime fallbacks."""
    cols = ['买价收益率', '卖价收益率', '成交收益率']
    if tickers is None:
        quote_frame = swap_rt.loc[:, cols].copy()
    else:
        quote_frame = swap_rt.loc[tickers, cols].copy()

    quote_frame = quote_frame.apply(pd.to_numeric, errors='coerce')
    bid_quotes = quote_frame['买价收益率'].copy()
    ofr_quotes = quote_frame['卖价收益率'].copy()
    traded_yield = quote_frame['成交收益率'].copy()

    mid_quotes = (bid_quotes + ofr_quotes) / 2
    quote_spread_bp = (ofr_quotes - bid_quotes).abs() * 100
    deviation_bp = (mid_quotes - traded_yield).abs() * 100
    use_trade_mask = traded_yield.notna() & (mid_quotes.isna() | (deviation_bp > threshold_bp))
    mid_quotes.loc[use_trade_mask] = traded_yield.loc[use_trade_mask]

    if fallback_quotes is not None:
        fallback_series = pd.Series(fallback_quotes).reindex(mid_quotes.index)
        unreasonable_mid = mid_quotes.isna() | ~np.isfinite(mid_quotes) | (mid_quotes < 0) | (mid_quotes > 10)
        use_fallback_mask = fallback_series.notna() & traded_yield.isna() & (unreasonable_mid | (quote_spread_bp > threshold_bp))
        mid_quotes.loc[use_fallback_mask] = fallback_series.loc[use_fallback_mask]

    invalid_bid = bid_quotes.isna() | ~np.isfinite(bid_quotes) | (bid_quotes < 0) | (bid_quotes > 10)
    invalid_ofr = ofr_quotes.isna() | ~np.isfinite(ofr_quotes) | (ofr_quotes < 0) | (ofr_quotes > 10)
    bid_quotes.loc[invalid_bid & mid_quotes.notna()] = mid_quotes.loc[invalid_bid & mid_quotes.notna()]
    ofr_quotes.loc[invalid_ofr & mid_quotes.notna()] = mid_quotes.loc[invalid_ofr & mid_quotes.notna()]

    return pd.DataFrame({
        'Bid': bid_quotes,
        'Ofr': ofr_quotes,
        'Mid': mid_quotes,
    })

def get_swap_mid_quotes(swap_rt, tickers=None, threshold_bp=10, fallback_quotes=None):
    """Return swap mid quotes with 成交收益率 and historical fallback for bad bid-offer quotes."""
    return get_swap_quote_frame(
        swap_rt,
        tickers=tickers,
        threshold_bp=threshold_bp,
        fallback_quotes=fallback_quotes,
    )['Mid']

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
    """Get spot rates (wrapper)."""
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
    """Convert curves to fixings and spot series."""
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

def evalueContract(di, quote_rt, fwddata, pshift):
    """Evaluate IRS contracts and compute carry/roll/carry-roll metrics."""
    d = DateConfig.get_date_mappings()['d'].date()
    fixing_ts, spot_ts, fwd_date = fwddata['fixing'], fwddata['spot'], fwddata['date']
    interpolators = {ct: interpolate.interp1d([(day - d).days / 365 for day in spot_ts[ct].index], spot_ts[ct].values, kind='linear') for ct in spot_ts}
    irs_val = pd.DataFrame(index=IRSConfig.IRS_LIST)
    irs_contracts = {}
    notional = 1
    term_map = {'3m': 0.25, '6m': 0.5, '1y': 1}
    for instrument in irs_val.index:
        start_date = (di + pd.offsets.BDay(pshift)).date()
        end_date = start_date + IRSConfig.get_irs_terms()[instrument]
        term = (end_date - start_date).days / 365
        curve_type = 'r7d' if 'FR00' in instrument else 's3m'
        frequency = 0 if term < 0.25 else 4
        contract = IRSContract(start_date, end_date, quote_rt.loc[instrument], curve_type, frequency)
        contract.valuation(notional, fwd_date, fixing_ts[curve_type], spot_ts[curve_type])
        irs_contracts[instrument] = contract
        cashflow = contract.cashflow
        irs_val.loc[instrument, 'Quote'] = contract.quote
        irs_val.loc[instrument, 'FixRate'] = contract.fixrate
        irs_val.loc[instrument, 'Value(bp)'] = contract.Value
        irs_val.loc[instrument, 'Duration'] = contract.duration
        irs_val.loc[instrument, 'Convexity'] = contract.cov
        irs_val.loc[instrument, 'Carry(3m,bp)'] = cashflow['CashFlow(NetPay)'].iloc[0]
        irs_val.loc[instrument, 'Carry(6m,bp)'] = cashflow['CashFlow(NetPay)'].iloc[:2].sum()
        irs_val.loc[instrument, 'Carry(1y,bp)'] = cashflow['CashFlow(NetPay)'].iloc[:3].sum()
        _calculate_roll_returns(irs_val, instrument, term, interpolators[curve_type], term_map)
    for period in ['3m', '6m', '1y']:
        irs_val[f'CarryRoll({period},bp)'] = irs_val[f'Carry({period},bp)'] + irs_val[f'Roll({period},bp)']
    return {'value': irs_val.round(4), 'obj': irs_contracts}

def _calculate_roll_returns(irs_val, instrument, term, interpolator, term_map):
    """Calculate roll returns for different periods."""
    years = interpolator.x if hasattr(interpolator, 'x') else []
    if hasattr(interpolator, 'y'):
        if term >= 10:
            term = years[-1] if len(years) else 10
        elif term <= years[0] if len(years) else term <= 0:
            term = years[0] if len(years) else 0.01
    s0 = interpolator(term)
    for period, period_term in term_map.items():
        if term - period_term <= 0.01:
            irs_val.loc[instrument, f'Roll({period},bp)'] = 0
        else:
            sr = interpolator(term - period_term)
            irs_val.loc[instrument, f'Roll({period},bp)'] = -100 * (s0 - sr) * irs_val.loc[instrument, 'Duration']
