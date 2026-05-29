# -*- coding: utf-8 -*-
"""
Bond Selector Module - Simplified

This module provides simplified functions for bond selection and yield curve construction.
"""
import os
import time
import pandas as pd
import numpy as np
from functools import lru_cache
from datetime import datetime
import warnings

from settings.paths import DIR_INPUT, DIR_DATA
from settings.fixed_income import BondConfig
from settings.general import DateConfig
import curves.affine.bootstrap as bs
import curves.affine.pricingYield as yd
from ..utils.file import updatePKL, loadPKL

warnings.filterwarnings('ignore', category=FutureWarning)

# Configuration
class Config:
    """Global configuration for bond selector."""
    VERBOSE = False
    ENABLE_CACHING = True

# Utility functions
@lru_cache(maxsize=1000)
def calculate_term(date_str: str, maturity_str: str) -> float:
    """Calculate term in years between two dates."""
    try:
        date = pd.to_datetime(date_str)
        maturity = pd.to_datetime(maturity_str)
        return (maturity - date).days / 365
    except:
        return np.nan


def filter_bonds_by_type(bond_names: pd.Series, bond_type: str) -> pd.Index:
    """Filter bonds by type."""
    if bond_type == 'TBond':
        mask = bond_names.str.contains('国债', na=False)
    elif bond_type == 'CBond':
        mask = bond_names.str.contains('国家开发银行', na=False)
    else:
        return bond_names.index
    return bond_names[mask].index


def filter_bonds_by_term(terms: pd.Series, min_term: float, max_term: float) -> pd.Index:
    """Filter bonds by term range."""
    l = 0
    while l == 0:
        mask = (terms > min_term) & (terms <= max_term)
        bond_filtered = terms[mask].index
        l = len(bond_filtered)
        max_term += 0.005
    return bond_filtered


def get_most_liquid_bond(turnover: pd.Series) -> str:
    """Select bond with highest turnover."""
    if len(turnover) == 0:
        return np.nan
    return turnover.idxmax() if len(turnover) > 1 else turnover.index[0]


def get_offtherun_bond(turnover: pd.Series, n_exclude: int = 1) -> str:
    """Select first-off-the-run bond by excluding the top n_exclude most liquid.

    For RV trading the on-the-run benchmark must NOT define the calibration
    curve — otherwise the curve chases the benchmark and the on/off spread
    collapses to zero. We exclude the most liquid bond(s) so the affine curve
    represents fair value for generic off-the-run bonds, and `ytm_act - ytm_quo`
    for the on-the-run bond becomes a clean on/off-the-run premium.

    Fallback: if the bucket has <= n_exclude bonds, return the most liquid
    one (avoids returning NaN for sparse tenor buckets such as 20Y/30Y).
    """
    if len(turnover) == 0:
        return np.nan
    if len(turnover) <= n_exclude:
        return turnover.idxmax()
    ranked = turnover.sort_values(ascending=False)
    return ranked.index[n_exclude]


def _as_scalar_bond_id(bond_id):
    """Normalize a bond identifier to a scalar hashable value.

    Some upstream pandas selections can return a one-element Series/Index/ndarray
    instead of a plain scalar. Downstream membership checks and DataFrame lookups
    require a hashable bond code.
    """
    if isinstance(bond_id, pd.Series):
        non_na = bond_id.dropna()
        return _as_scalar_bond_id(non_na.iloc[0]) if not non_na.empty else np.nan
    if isinstance(bond_id, (pd.Index, list, tuple, np.ndarray)):
        if len(bond_id) == 0:
            return np.nan
        return _as_scalar_bond_id(bond_id[0])
    return bond_id


def extract_yield(env: dict, bond_id: str, date: datetime, price_type: str) -> float:
    """Extract yield to maturity based on price type."""
    bond_id = _as_scalar_bond_id(bond_id)
    if price_type == 'hist':
        hist_data = env.get('Close')
        if hist_data is not None and date in hist_data.index and bond_id in hist_data.columns:
            yield_val = hist_data.loc[date, bond_id]
            if pd.notna(yield_val) and yield_val > 0:
                return yield_val
                
    elif price_type == 'close':
        try:
            return env['Def'].loc[bond_id, '估价收益率:%(中债)']
        except KeyError:
            if Config.VERBOSE:
                print(f"Missing data for {bond_id}")
            
    else:  # real time data
        bond_rt_data = env.get('BondRT')
        if bond_rt_data is not None and bond_id in bond_rt_data.index:
            fallback_yield = env['Def'].loc[bond_id, '估价收益率:%(中债)']
            bond_rt = bond_rt_data.loc[bond_id]
            if price_type == 'Bid':
                ytm = bond_rt.get('买价收益率', fallback_yield)
            elif price_type == 'Ofr':
                ytm = bond_rt.get('卖价收益率', fallback_yield)
            else:
                ytm = fallback_yield
            return ytm if pd.notna(ytm) else fallback_yield
        elif Config.VERBOSE:
            print(f'Missing real time data for {bond_id} {date}')
    
    return np.nan


def extract_bond_info(bond_data: pd.Series) -> dict:
    """Extract essential bond information."""
    return {
        'name': bond_data.get('证券全称', ''),
        'start_date': bond_data.get('起息日期'),
        'maturity_date': bond_data.get('到期日期'),
        'frequency': bond_data.get('每年付息次数', 1.0),
        'coupon': bond_data.get('票面利率:%', 0.0),
        'cnbd_yield': (bond_data.get('估价收益率:%(中债)') or 
                      bond_data.get('收盘收益率(%)') or 0.0)
    }


def prepare_bond_schedule(bond_info: dict) -> tuple:
    """Prepare bond schedule for pricing."""
    name, start, maturity, freq, coupon = (
        bond_info['name'], bond_info['start_date'], bond_info['maturity_date'],
        bond_info['frequency'], bond_info['coupon']
    )
    
    # Handle special cases
    if pd.isna(freq) or freq == 0:
        freq = 1.0
    if '贴现' in str(name):
        coupon = 0.0
        freq = 1.0
    
    schedule = yd.scheduleDate(start, maturity, name, freq)
    return coupon, freq, schedule


class RefBondSelector:
    """Main class for reference bond selection."""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
    
    def select_reference_bonds(
        self,
        env: dict,
        date_range: list,
        bond_type: str,
        daily: bool,
        update: bool = True,
    ) -> pd.DataFrame:
        """Select reference bonds for given date range and bond type."""
        if self.verbose:
            print(f"Starting reference bond selection for {bond_type}...")
            start_time = time.time()
        
        # Initialize data structures
        bonds = self._prepare_bond_data(env)
        term_buckets = BondConfig.TERM_BUCKETS
  
        # Load existing results
        ref_file = os.path.join(DIR_INPUT, f'{bond_type}-cvref.pkl')
        existing_data = loadPKL(ref_file)

        if 'RefBond' in existing_data:
            result_df = existing_data['RefBond'].sort_index()
            result_df = result_df.loc[~result_df.index.duplicated(keep='first')]
            result_df = result_df.astype(object)
            # Back-compat: add columns for any new buckets not present in the stored file,
            # then reorder to match the current TERM_BUCKETS definition.
            expected_columns = [f'Term near {t}Y' for t in term_buckets.keys()]
            for col in expected_columns:
                if col not in result_df.columns:
                    result_df[col] = np.nan
            result_df = result_df[expected_columns]
        else:
            column_names = [f'Term near {t}Y' for t in term_buckets.keys()]
            result_df = pd.DataFrame(columns=column_names, dtype=object)
        # Determine dates to process
        if daily:
            dates_to_process = [DateConfig.get_date_mappings()['dp'].date()]
        else:
            px_file = os.path.join(DIR_DATA, f'{bond_type}-px.pkl')
            datelist = loadPKL(px_file)['Close'].index
            mask = (datelist >= date_range[0]) & (datelist <= date_range[1])
            dates_to_process = datelist[mask]

        if update and len(result_df) > 0:
            refresh_mask = (
                (result_df.index >= date_range[0])
                & (result_df.index <= date_range[1])
            )
            existing_result_df = result_df.drop(
                index=result_df.index[refresh_mask],
                errors='ignore'
            )
            result_df = pd.DataFrame(columns=result_df.columns, dtype=object)
        else:
            existing_result_df = result_df

        if not update and len(result_df) > 0:
            dates_to_process = [d for d in dates_to_process if d not in result_df.index]

        # Collect new rows in a dict and concat once instead of cell-by-cell assignment
        new_rows: dict = {}
        for i, current_date in enumerate(dates_to_process):
            if self.verbose and i % max(1, len(dates_to_process) // 10) == 0:
                progress = 100 * i / len(dates_to_process)
                print(f"Progress: {progress:.1f}% - Processing {current_date}")

            day_results = self._process_single_date(
                bonds, current_date, bond_type, term_buckets, result_df
            )
            new_rows[current_date] = day_results
            # Keep result_df up-to-date so stability logic can see the row
            for bucket_name, selected_bond in day_results.items():
                if bucket_name in result_df.columns:
                    result_df[bucket_name] = result_df[bucket_name].astype(object)
                result_df.loc[current_date, bucket_name] = selected_bond

        # Merge new rows (if any) and persist
        if new_rows:
            result_df = pd.concat(
                [existing_result_df, pd.DataFrame(new_rows).T]
            ).loc[lambda df: ~df.index.duplicated(keep='last')]
        else:
            result_df = existing_result_df
        result_df = result_df.ffill().dropna(how='all').sort_index()
        final_data = {'RefBond': result_df}
        final_data = updatePKL(final_data, ref_file)
        if self.verbose:
            end_time = time.time()
            print(f"Completed in {end_time - start_time:.2f} seconds")
            print(f"Result shape: {result_df.shape}")
        
        return result_df
    
    def _prepare_bond_data(self, env: dict) -> dict:
        """Prepare and filter bond data for processing."""
        # Handle historical or single date data
        if 'Volume' in env:
            # Historical case with volume time series
            bonds = env['Volume'].columns.intersection(env['Def'].index)
            df_balance = env['Def']['债券余额:亿'].loc[bonds]
            
            # Filter valid bonds
            valid_mask = (df_balance != 0) & (df_balance.notna())
            bonds = bonds[valid_mask]
            df_balance = df_balance[valid_mask]
            
            # Calculate turnover time series
            df_turnover = env['Volume'][bonds].div(df_balance.values, axis=1) / 1e8
            df_turnover = df_turnover.replace([np.inf, -np.inf], 0).dropna(axis=0, how='all')
            # 20-day rolling mean smooths zero-volume days and gives stable
            # on/off-the-run ranking. min_periods=5 avoids penalising bonds
            # that just started trading (auction week).
            df_turnover = df_turnover.rolling(window=20, min_periods=5).mean()
        else:
            # Single date case
            required_cols = ['债券余额:亿', '成交量:万元', '到期日期', '起息日期', '证券全称']
            bonds = env['Def'].index
            
            for col in required_cols:
                if col not in env['Def'].columns:
                    raise KeyError(f"Required column '{col}' not found in env['Def']")
            
            df_balance = env['Def']['债券余额:亿'].loc[bonds]
            df_volume = env['Def']['成交量:万元'].loc[bonds]
            
            # Filter valid bonds
            valid_mask = (df_balance != 0) & (df_balance.notna())
            bonds = bonds[valid_mask]
            df_balance = df_balance[valid_mask]
            df_volume = df_volume[valid_mask]
            
            # Calculate turnover
            turnover_ratio = df_volume / df_balance / 1e4
            turnover_ratio = turnover_ratio.replace([np.inf, -np.inf], 0).dropna()
            
            # Create DataFrame structure for compatibility
            df_turnover = pd.DataFrame(index=[DateConfig.get_date_mappings()['dp'].date()], columns=bonds)
            df_turnover.loc[df_turnover.index[0]] = turnover_ratio
        
        return {
            'bonds': bonds,
            'balance': df_balance,
            'turnover': df_turnover,
            'maturity': env['Def']['到期日期'].loc[bonds],
            'start_date': env['Def']['起息日期'].loc[bonds],
            'bond_names': env['Def']['证券全称'].loc[bonds],
            'definition': env['Def']
        }
    
    def _process_single_date(self, bonds: dict, current_date: datetime,
                           bond_type: str, term_buckets: dict, existing_results: pd.DataFrame) -> dict:
        """Process bond selection for a single date."""
        day_results = {}
        # Filter by bond type
        type_filtered = filter_bonds_by_type(bonds['bond_names'], bond_type)
        available_bonds = bonds['bonds'].intersection(type_filtered)
        
        # Filter by start date
        started_mask = bonds['start_date'][available_bonds] < current_date
        end_mask = bonds['maturity'][available_bonds] > current_date
        available_bonds = available_bonds[started_mask & end_mask]
        
        if len(available_bonds) == 0:
            return day_results
        
        # Calculate terms — direct date arithmetic avoids strftime round-trips
        terms = (bonds['maturity'][available_bonds] - current_date).apply(
            lambda d: d.days / 365
        )
        
        # Get turnover for this date
        date_turnover = pd.Series(dtype=float)
        if current_date in bonds['turnover'].index:
            date_turnover = bonds['turnover'].loc[current_date, available_bonds]#.dropna()
        else:
            print("Missing Volume data for the date ", current_date)
            # Halt execution here for debugging / safety: stop further processing
            raise SystemExit("Execution halted at selector.py after missing Volume data (line ~281)")

        # Process each term bucket
        for bucket_term, (min_term, max_term) in term_buckets.items():
            bucket_name = f'Term near {bucket_term}Y'

            # Filter by term bucket
            bucket_bonds = filter_bonds_by_term(terms, min_term, max_term)
            candidate_bonds = available_bonds.intersection(bucket_bonds)

            # Special handling for short terms (zero coupon bonds)
            if bucket_term in [0.5, 1.0]:
                freq_data = bonds['definition'].loc[candidate_bonds, '每年付息次数']
                zero_coupon_mask = (freq_data == 1) & freq_data.notna()
                candidate_bonds = candidate_bonds[zero_coupon_mask]

            # For short-end buckets (<1.5Y) use the most liquid bond: near-maturity
            # off-the-run bonds often have stale CNBD yields that equal their coupon
            # rate (2-5%) rather than the current market rate, which inflates the
            # bootstrap spot. For longer buckets use first off-the-run to avoid
            # the calibration curve chasing on-the-run richness.
            available_turnover = date_turnover.loc[candidate_bonds].dropna()
            # avoid duplication with previous bucket
            term_idx = list(existing_results.columns).index(bucket_name)
            if term_idx > 0:
                prev_bucket_name = existing_results.columns[term_idx - 1]
                prev_tenor_bond = day_results[prev_bucket_name]
                if prev_tenor_bond in available_turnover.index:
                    available_turnover = available_turnover.drop(index=prev_tenor_bond)

            if bucket_term < 1.5:
                selected_bond = _as_scalar_bond_id(get_most_liquid_bond(available_turnover))
            else:
                selected_bond = _as_scalar_bond_id(get_offtherun_bond(available_turnover, n_exclude=1))

            # Sticky off-the-run: prefer the previous selection as long as
            # it is still in this bucket. This prevents day-to-day turnover
            # noise from flipping the reference between adjacent off-the-run
            # bonds, and lets new on-the-run issuance roll smoothly into the
            # calibration (old on-the-run becomes the new first off-the-run
            # only when the previous reference ages out of the bucket).
            previous_dates = existing_results.index[existing_results.index < current_date]
            if len(previous_dates) > 0:
                prev_date = previous_dates[-1]
                prev_bond = _as_scalar_bond_id(existing_results.loc[prev_date, bucket_name])
                if (prev_bond in bonds['start_date'].index
                        and prev_bond in bucket_bonds):
                    selected_bond = prev_bond
                elif pd.isna(selected_bond) and prev_bond in bonds['start_date'].index:
                    selected_bond = prev_bond
            day_results[bucket_name] = _as_scalar_bond_id(selected_bond)
        return day_results


class YieldCurveBuilder:
    """Build yield curves from reference bonds."""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
    
    def build_curve(self, bond_ref: pd.Series, env: dict, price_type: str, date: datetime, tax: float = 0.0) -> pd.DataFrame:
        """Build yield curve from reference bonds.

        Args:
            tax: Optional coupon-premium adjustment applied before bootstrapping.
                 The current bond-curve workflow uses ``tax=0`` for both TBond
                 and CBond so spot calibration and downstream pricing share the
                 same no-tax convention.
        """
        yield_curve = bs.BootstrapYieldCurve()
        results = pd.DataFrame(index=bond_ref.index, columns=['bond_id', 'ttm', 'spot'], dtype=object)
        
        for bucket_name, bond_id in bond_ref.items():
            bond_id = _as_scalar_bond_id(bond_id)
            if pd.isna(bond_id):
                continue

            # Extract bond information
            if bond_id not in env['Def'].index:
                warnings.warn(
                    f"Skipping reference bond {bond_id} on {date}: not found in env['Def']"
                )
                continue
            bond_data = env['Def'].loc[bond_id]
            bond_info = extract_bond_info(bond_data)

            # Get yield
            ytm = extract_yield(env, bond_id, date, price_type)
            
            if pd.isna(ytm) or not np.isfinite(ytm):
                continue
            
            # Prepare schedule
            coupon, frequency, schedule = prepare_bond_schedule(bond_info)
            
            # Calculate pricing
            dirty, clean, duration, convexity = yd.pricing(
                date, coupon, schedule, frequency, ytm
            )
            
            # Calculate time to maturity
            maturity_date = bond_info['maturity_date']
            date_1 = pd.Timestamp(maturity_date).date()
            date_2 = pd.Timestamp(date).date()
            ttm = (date_1 - date_2).days / 365
            
            # Under the current no-tax convention the dirty price is used
            # as-is. The branch is kept for optional future adjustments.
            if tax > 0.0 and np.isfinite(dirty):
                cpv = yd.coupon_pv_sum(date, coupon, schedule, frequency, ytm)
                dirty_for_bootstrap = dirty - tax * cpv
            else:
                dirty_for_bootstrap = dirty

            # Add to yield curve
            results.loc[bucket_name, 'bond_id'] = bond_id
            results.loc[bucket_name, 'ttm'] = ttm
            yield_curve.add_instrument(100, ttm, coupon, dirty_for_bootstrap, frequency)
        
        # Extract yield curve
        maturities = yield_curve.get_maturities()
        zero_rates = yield_curve.get_zero_rates()
        rate_map = dict(zip(maturities, zero_rates))
        
        # Map spot rates
        for bucket_name in results.index:
            ttm = pd.to_numeric(results.loc[bucket_name, 'ttm'], errors='coerce')
            results.loc[bucket_name, 'spot'] = rate_map.get(float(ttm), np.nan) if pd.notna(ttm) else np.nan

        results['ttm'] = pd.to_numeric(results['ttm'], errors='coerce')
        results['spot'] = pd.to_numeric(results['spot'], errors='coerce')
        return results

def compute_spot_term_panels(
    env: dict,
    price_range: list,
    botr: pd.DataFrame,
    bond_type: str,
    price_type: str = "hist",
    update: bool = True,
):
    """Compute spot and term panels for a date range."""
    # Determine dates to compute
    start = price_range[0]
    end = price_range[1]

    mask = (botr.index >= start) & (botr.index <= end)
    date_index = botr.index[mask]
    columns = list(botr.columns)
    
    # Load existing data
    file_path = os.path.join(DIR_INPUT, f'{bond_type}-cvref.pkl')
    existing_data = loadPKL(file_path)
    existing_spot = existing_data.get('RefSpot', None)
    existing_term = existing_data.get('RefTerm', None)

    if update:
        missing_dates = list(date_index)
    else:
        existing_spot_index = existing_spot.index if existing_spot is not None else pd.Index([])
        missing_dates = [d for d in date_index if d not in existing_spot_index]

    if price_type in ['hist','close']:
        if len(missing_dates) == 0:
            return existing_data
        else:
            # Compute new values
            new_spot = pd.DataFrame(index=missing_dates, columns=columns, dtype=float)
            new_term = pd.DataFrame(index=missing_dates, columns=columns, dtype=float)

            _tax = 0.0
            for d in missing_dates:
                bond_ref = botr.loc[d]
                builder = YieldCurveBuilder()
                dfp = builder.build_curve(bond_ref, env, price_type, d, tax=_tax)

                ttm_series = pd.Series(index=columns, dtype=float)
                spot_series = pd.Series(index=columns, dtype=float)

                for bucket, bond_id in bond_ref.items():
                    if bucket in dfp.index:
                        ttm_value = pd.to_numeric(dfp.loc[bucket, 'ttm'], errors='coerce')
                        spot_value = pd.to_numeric(dfp.loc[bucket, 'spot'], errors='coerce')
                        ttm_series.loc[bucket] = float(ttm_value) if pd.notna(ttm_value) else np.nan
                        spot_series.loc[bucket] = float(spot_value) if pd.notna(spot_value) else np.nan

                new_term.loc[d] = ttm_series
                new_spot.loc[d] = spot_series

            # Save results
            final_data = {'RefSpot': new_spot, 'RefTerm': new_term}
            final_data = updatePKL(final_data, file_path)
            return final_data
    else:
        d = botr.index[-1]
        bond_ref = botr.loc[d]
        plist = ['Bid', 'Ofr']
        ref_series = {}
        _tax = 0.0
        for p in plist:
            builder = YieldCurveBuilder()
            dfp = builder.build_curve(bond_ref, env, p, d, tax=_tax)
            series = pd.Series(dfp['spot'].values, index=dfp['ttm'].values, dtype=float)
            series.index = pd.to_numeric(series.index, errors='coerce')
            series = series[~pd.isna(series.index)]
            series = series[~series.index.duplicated(keep='last')].sort_index()
            ref_series[p] = series
        ref_df = pd.concat(ref_series, axis=1).sort_index()
        return ref_df

def update_price(df_price, quote0, sen0, bonds, d0):
    """Update bond pricing data with new quotes and sensitivities."""
    bonds_ = quote0.index
    df_price['ytm_act'].loc[d0, bonds.index] = bonds.loc[bonds.index, '收盘收益率(%)']
    df_price['ytm_quo'].loc[d0, bonds_] = quote0.loc[bonds_, '收益率']
    df_price['dur_curva'].loc[d0, bonds_] = sen0.loc[bonds_, 'Greek1']
    df_price['dur_level'].loc[d0, bonds_] = sen0.loc[bonds_, 'Greek2']
    df_price['dur_slope'].loc[d0, bonds_] = sen0.loc[bonds_, 'Greek3']
        
    for k in df_price.keys():       
        df_price[k] = df_price[k].sort_index()       
    return df_price