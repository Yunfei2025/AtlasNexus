# -*- coding: utf-8 -*-
"""
Optimized Backtest Module

This module provides a structured approach to backtesting fixed income strategies.
Separated into logical classes and functions for better maintainability.

@author: 马云飞 (optimized)
@date: 2023-01-11 (restructured 2025-08-26)
"""

import os
import sys
import pathlib
import logging
from typing import Dict, List, Tuple, Union, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
from dateutil.relativedelta import relativedelta

# Local libraries
PATH = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(PATH))

import curves.affine.curve as c
from settings.paths import DIR_INPUT
from settings.fixed_income import IRSConfig
from settings.general import GeneralConfig

# Import with fallbacks
from curves.utils.loader import loadCurvePxTS
from curves.calibration.selector import RefBondSelector, compute_spot_term_panels
from curves.calibration import irscurves as irs
from curves.utils.plot import plotBondTS
from curves.calibration.stat import statAnalysis_BC
from curves.utils.file import updatePKL, loadPKL

# Configure logging using centralized setup
from utils.log_window import get_logger
logger = get_logger(__name__)


@dataclass
class BacktestConfig:
    """Configuration for backtest parameters."""
    long_threshold: float = 1.0
    short_threshold: float = 1.0
    close_threshold: float = 0.5
    min_maturity: float = 1.0
    max_maturity: float = 10.0
    stat_window_months: int = 3
    bonds_per_plot: int = 10


class PositionSignalGenerator:
    """Handles position signal generation based on Z-scores."""
    
    def __init__(self, config: BacktestConfig):
        self.config = config
    
    def generate_signals(self, df_price: pd.DataFrame, signal_type: str) -> pd.DataFrame:
        """
        Generate trading signals based on Z-scores.
        
        Args:
            df_price: Price dataframe
            signal_type: Type of signal ('ytm', 'dirty', etc.)
            
        Returns:
            Updated dataframe with position signals
        """
        try:
            # Calculate Z-Score
            df_price['Z-Score'] = (
                (df_price[f'{signal_type}_act'] - df_price[f'{signal_type}_quo_mean']) / 
                df_price[f'{signal_type}_quo_vol']
            )
            
            # Generate signals
            df_price['long'] = np.sign(
                df_price['Z-Score'][df_price['Z-Score'] > self.config.long_threshold]
            )
            df_price['short'] = np.sign(
                df_price['Z-Score'][df_price['Z-Score'] < -self.config.short_threshold]
            )
            df_price['close'] = np.sign(
                df_price['Z-Score'][abs(df_price['Z-Score']) < self.config.close_threshold]
            )
            
            # Combine signals
            action = (df_price['long']
                     .fillna(df_price['short'])
                     .fillna(df_price['close']))
            df_price['position'] = action.ffill()
            
            return df_price
            
        except Exception as e:
            logger.error(f"Error generating position signals: {e}")
            raise


class CurveManager:
    """Manages curve initialization and updates."""
    
    def __init__(self, bond_type: str):
        self.bond_type = bond_type
        self.lookback = 3 # 3 months
        # Internal caches to avoid recomputation across dates
        self._cache = {
            'botr': None,   # Reference bonds history
            'spot': None,   # Spot curve panel
            'term': None,   # Term structure panel
            # 'window_start': None,
            # 'window_end': None
        }
    
    def initialize_curves(self, env: Dict, price_range: List) -> Dict:
        """
        Initialize yield curves for the given period.
        
        Args:
            env: Environment data
            price_range: Date range for analysis
            
        Returns:
            Dictionary of curve objects by date
        """
        curve_obj_file = os.path.join(DIR_INPUT, f'{self.bond_type}-cvobj.pkl')
        curve_data_file = os.path.join(DIR_INPUT, f'{self.bond_type}-cvdata.pkl')

        # Load existing curves
        dict_curve = loadPKL(curve_obj_file)
        curve_data = loadPKL(curve_data_file)
        logger.info(f"Calculating {len(price_range)} missing days")

        if 'spot' not in curve_data.keys():
            nums = [round(i*0.1, 1) for i in range(1, 101)]
            curve_data['spot'] = pd.DataFrame(columns=nums)
            curve_data['forward'] = pd.DataFrame(columns=nums)

        # Pre-compute reference bond set & spot/term matrices ONCE instead of per date
        if self.bond_type != 'IRS':
            self._precompute_reference(env, price_range)
        
        for date in price_range:
            try:
                print(date)
                if self.bond_type == 'IRS':
                    self._convert_spot_fwd(env, price_range)
                    dict_curve[date] = self._create_irs_curve(env, date, price_range)
                    # temp = dict_curve[date].fitting()
                    # curve_data['spot'].loc[date] = temp['SpotRate']
                    # curve_data['forward'].loc[date] = temp['ForwardRate']
                else:
                    dict_curve[date] = self._create_bond_curve(date)
                    temp = dict_curve[date].fitting()
                    if "SpotRate" not in temp.columns:
                        curve_data['spot'].loc[date] = temp['SpotRate']
                        curve_data['forward'].loc[date] = temp['Forward Curve']
                    else:
                        curve_data['spot'].loc[date] = temp['SpotRate']
                        curve_data['forward'].loc[date] = temp['ForwardRate']
            except Exception as e:
                logger.warning(f"{e}")    
        updatePKL(curve_data, curve_data_file)
        # import pdb; pdb.set_trace()
        # Save updated curves
        updatePKL(dict_curve, curve_obj_file)
        return dict_curve

    def _precompute_reference(self, env: Dict, price_range: List):
        """Precompute reference bond selection and spot/term matrices over an extended window.

        This replaces the previous strategy of recomputing selectRefBond_hist + getSpotCurve
        inside every per-date calibration. For a window of N days and a 3‑month rolling
        calibration lookback, the naive approach performed O(N^2) work on overlapping ranges.
        This collapses it to O(N).
        """
        if self._cache['spot'] is not None:
            return  # Already precomputed

        # Extend start backwards by 3 months for calibration windows
        end_date = max(price_range)
        start_date = min(price_range)
        extended_start = (pd.Timestamp(start_date) - relativedelta(months=self.lookback)).date()
        window_range = [extended_start, end_date]
        logger.info("Precomputing reference bonds & spot/term panels (single pass)...")
        selector = RefBondSelector()
        botr_full = selector.select_reference_bonds(
            env,
            window_range,
            self.bond_type,
            daily=False,
            update=True,
        )
        ref_full = compute_spot_term_panels(
            env,
            window_range,
            botr_full,
            self.bond_type,
            price_type="hist",
            update=True,
        )
        # import pdb; pdb.set_trace()
        self._cache.update({
            'botr': botr_full,
            'spot': ref_full['RefSpot'],
            'term': ref_full['RefTerm'],
        })

    def _convert_spot_fwd(self, env, price_range):
        underlying = {'r7d': 'FR007', 's3m': 'SHI'}
        curve_ts = {ct: env[[i for i in env.columns if underlying[ct] in i ]].dropna(how='all') for ct in IRSConfig.CURVE_TYPES}
        # The IRS calibration utilities are implemented as classes in irscurves.
        # Instantiate a CurveDataManager, TenorConverter and CurveGenerator and
        # call the instance method _extract_historical_spots which will populate
        # the internal curve data structure. Persist via the manager's save.
        try:
            cdm = irs.CurveDataManager()
            tenor_conv = irs.TenorConverter()
            gen = irs.CurveGenerator(cdm, tenor_conv)
            # Keep price_range as datetime.date list to match env index type
            timewindow = price_range
            for ct in IRSConfig.CURVE_TYPES:
                gen._extract_historical_spots(curve_ts[ct], timewindow, ct)
            # Persist results
            cdm.save()
        except Exception as e:
            logger.error(f"Failed to extract IRS historical spots: {e}")
            raise
        
    def _create_irs_curve(self, env: Dict, date: datetime, 
                              price_range: List) -> c.Curve:
        """Create a curve object for a specific date."""
        irs_ref = {
            'r7d': list(IRSConfig.R7D_LIST.keys()),
            's3m': list(IRSConfig.S3M_LIST.keys())
        }
        return irs.genIRSCurves(env, irs_ref, date)
        
    def _create_bond_curve(self, date: datetime) -> c.Curve:
        """Create bond curve using precomputed reference (fast path)."""
        if self._cache['spot'] is None:
            raise RuntimeError("Precomputed spot/term cache not initialized. Call initialize_curves first.")

        start_date = (pd.Timestamp(date) - relativedelta(months=self.lookback)).date()
       
        spot_full = self._cache['spot']
        term_full = self._cache['term']
        botr_full = self._cache['botr']

        if date not in spot_full.index:
            raise KeyError(f"Date {date} not found in database, check if it is a holiday.")

        # Build per-date inputs
        spot_slice = spot_full.loc[start_date:date]
        term_slice = term_full.loc[start_date:date]
        df_ref = pd.Series(spot_full.loc[date].values, index=term_full.loc[date].values)
        bond_ref = botr_full.loc[date]
        curve = c.Curve(date, self.bond_type)
        curve.calibrate(term_slice, spot_slice)
        curve.extractFactors(df_ref, bond_ref)
        return curve

class CurveParameterExtractor:
    """Extracts and saves curve parameters."""
    
    def __init__(self, bond_type: str):
        self.bond_type = bond_type
    
    def extract_parameters(self, dict_curve: Dict, test_days: List) -> None:
        """
        Extract curve parameters and save to file.
        
        Args:
            dict_curve: Dictionary of curve objects
            test_days: List of test dates
        """
        date_list = [d for d in test_days if d in dict_curve.keys()]
        tenor = list(np.linspace(1, 10, 10))
        tenor_labels = [f'{self.bond_type}-{t}Y' for t in tenor]
        
        # Initialize result dataframes
        results = {
            'ImpliedVol': pd.DataFrame(columns=['level', 'slope', 'curvature']),
            'Factors': pd.DataFrame(columns=['level', 'slope', 'curvature']),
            'Spot': pd.DataFrame(columns=tenor_labels)
        }
        
        logger.info("Extracting curve parameters")
        
        for date in date_list:
            try:
                curve = dict_curve[date]
                
                # Extract implied volatility
                results['ImpliedVol'].loc[date] = [
                    float(curve.S2[0, 0]), float(curve.S2[1, 1]), float(curve.S2[2, 2])
                ]
                
                # Extract factors
                results['Factors'].loc[date] = [float(f) for f in curve.factors[:3]]
                
                # Extract spot rates
                spot_curve = curve.fitting()['SpotRate'].loc[tenor]
                spot_curve.index = tenor_labels
                results['Spot'].loc[date] = spot_curve.loc[tenor_labels]
                
            except Exception as e:
                logger.warning(f"Failed to extract parameters for {date}: {e}")
        
        # Convert to float and save
        for key in results:
            results[key] = results[key].astype(float).sort_index()
        
        output_file = os.path.join(DIR_INPUT, f'{self.bond_type}-cvref.pkl')
        updatePKL(results, output_file)


class PricingEngine:
    """Handles bond and IRS pricing calculations."""
    
    def __init__(self, bond_type: str):
        self.bond_type = bond_type
    
    def price_instruments(self, dict_curve: Dict, env: Dict, 
                         price_range: List) -> Dict[str, pd.DataFrame]:
        """
        Price instruments using curve data.
        
        Args:
            dict_curve: Dictionary of curve objects
            env: Environment data
            price_range: Date range for pricing
            
        Returns:
            Dictionary of pricing results
        """
        period = self._get_pricing_period(dict_curve, price_range)
        
        if self.bond_type == 'IRS':
            return self._price_irs(dict_curve, env, period)
        else:
            return self._price_bonds(dict_curve, env, period, price_range)
    
    def _get_pricing_period(self, dict_curve: Dict, price_range: List) -> pd.Series:
        """Get the pricing period based on available curves."""
        start, end = self._parse_date_range(price_range)
        period = pd.Series(list(dict_curve.keys()))
        return period[(period >= start) & (period <= end)]
    
    def _parse_date_range(self, price_range: List) -> Tuple[datetime.date, datetime.date]:
        """Parse date range from various input formats."""
        if isinstance(price_range[0], str):
            for fmt in ("%Y%m%d", "%Y-%m-%d"):
                try:
                    start = datetime.strptime(price_range[0], fmt).date()
                    end = datetime.strptime(price_range[1], fmt).date()
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(f"Cannot parse date strings: {price_range[0]}, {price_range[1]}")
        else:
            if len(price_range) == 1:
                start = end = price_range[0]
            else:
                start = price_range[0]
                end = price_range[1]
        return start, end
    
    def _price_irs(self, dict_curve: Dict, env: Dict, 
                   period: pd.Series) -> Dict[str, pd.DataFrame]:
        """Price IRS instruments."""
        common_idx = [ d for d in period if d in env.index ]
        results = {
            'ytm_act': env.loc[common_idx, IRSConfig.IRS_LIST],
            'ytm_quo': pd.DataFrame(columns=IRSConfig.IRS_LIST)
        }
        
        for date in common_idx:
            try:
                logger.info(f"Pricing IRS for {date}:")  
                prev_date = date - pd.offsets.BDay()
                fwd_data = irs.curves2Fixings(prev_date, env, dict_curve[date])
                contracts = irs.evalueContract(
                    date, results['ytm_act'].loc[date, IRSConfig.IRS_LIST], 
                    fwd_data, 1
                )
                results['ytm_quo'].loc[date, IRSConfig.IRS_LIST] = \
                    contracts['value'].loc[IRSConfig.IRS_LIST, 'FixRate']
            except Exception as e:
                logger.warning(f"Failed to price IRS for {date}: {e}")
        
        return {k: v.astype(float) for k, v in results.items()}
    
    def _price_bonds(self, dict_curve: Dict, env: Dict, 
                     period: pd.Series, price_range: List = None) -> Dict[str, pd.DataFrame]:
        """Price bond instruments."""
        tenor_keys = [1.0, 2.0, 3.0, 4.0, 5.0]
        bonds = env['Def'].index.intersection(env['Close'].columns)
        period = env['Close'].index.intersection(period)
        
        # ytm_act = Close for all dates in price_range present in env['Close'],
        # independent of whether curve calibration succeeded for those dates.
        if price_range is not None:
            start, end = self._parse_date_range(price_range)
            close_period = env['Close'].loc[start:end].index
        else:
            close_period = period
        
        # Initialize result dataframes
        data_types = ['ytm_act', 'ytm_quo', 'dur_level', 'dur_slope', 'dur_curva']
        results = {dtype: pd.DataFrame(dtype=float, index=period, columns=bonds) 
                  for dtype in data_types}
        results['ytm_spot'] = pd.DataFrame(columns=tenor_keys)
        results['ytm_act'] = env['Close'].loc[close_period, bonds]
        
        info_pool = env['Def'].copy()
        _bt_config = BacktestConfig()  # instantiate once, reuse across all dates
        for date in period:
            # try:
            logger.info(f"Pricing bonds for {date}:")
            bonds_filtered = self._filter_bonds_by_maturity(env, date, info_pool, _bt_config)
            quote, sensitivity = dict_curve[date].affinePricing(env['Def'], bonds_filtered)

            # Store results
            results['ytm_quo'].loc[date, quote.index] = quote['收益率']
            results['dur_level'].loc[date, sensitivity.index] = sensitivity['Greek1']
            results['dur_slope'].loc[date, sensitivity.index] = sensitivity['Greek2']
            results['dur_curva'].loc[date, sensitivity.index] = sensitivity['Greek3']
            results['ytm_spot'].loc[date] = \
                dict_curve[date].fitting().loc[tenor_keys, 'SpotRate']
            # except Exception as e:
            #     logger.warning(f"Failed to price bonds for {date}: {e}")
            # finally:
            env['Def'] = info_pool
        
        return {k: v.astype(float) for k, v in results.items()}
    
    def _filter_bonds_by_maturity(self, env: Dict, date: datetime,
                                  info_pool: pd.DataFrame,
                                  config: BacktestConfig) -> pd.Index:
        """Filter bonds by maturity criteria."""
        ttm = env['Def']['到期日期'] - date
        ttm_years = pd.Series([t.days / 365 for t in ttm], index=ttm.index)

        valid_bonds = ttm_years[
            (ttm_years > config.min_maturity) &
            (ttm_years < config.max_maturity)
        ].index

        env['Def'] = info_pool.loc[valid_bonds]

        # Calculate remaining maturity
        maturity = env['Def']['到期日期'] - date
        env['Def']['剩余期限'] = [m.days / 365 for m in maturity]

        return env['Def'][
            (env['Def']['剩余期限'] > config.min_maturity) &
            (env['Def']['剩余期限'] < config.max_maturity)
        ].index


class PriceConverter:
    """Converts between YTM and dirty/clean prices."""
    
    def __init__(self, bond_type: str):
        self.bond_type = bond_type
    
    def convert_ytm_to_prices(self, df_price: Dict, quote_type: str, 
                             price_range: List, env: Dict) -> Dict:
        """
        Convert YTM to dirty and clean prices.
        
        Args:
            df_price: Price data dictionary
            quote_type: Type of quote ('act', 'quo', etc.)
            price_range: Date range for conversion
            env: Environment data
            
        Returns:
            Updated price dictionary with dirty and clean prices
        """
        period = df_price[f'ytm_{quote_type}'].loc[price_range[0]:price_range[1]].index
        bonds = env['Def'].index.intersection(df_price[f'ytm_{quote_type}'].columns)
        
        # Initialize price dataframes
        df_price[f'dirty_{quote_type}'] = pd.DataFrame(
            dtype=float, index=period, columns=bonds
        )
        df_price[f'clean_{quote_type}'] = pd.DataFrame(
            dtype=float, index=period, columns=bonds
        )
        
        for date in period:
            try:
                logger.debug(f"Computing prices for: {date.strftime('%Y-%m-%d')}")
                curve = c.Curve(date, self.bond_type)
                prices = curve.Pricing(
                    bonds, env, df_price[f'ytm_{quote_type}'].loc[date], ytm_other=True
                )
                df_price[f'dirty_{quote_type}'].loc[date] = prices['全价']
                df_price[f'clean_{quote_type}'].loc[date] = prices['净价']
            except Exception as e:
                logger.warning(f"Failed to convert prices for {date}: {e}")
        
        return df_price


class BacktestAnalyzer:
    """Main class for running backtest analysis and plotting."""
    
    def __init__(self, config: BacktestConfig = None):
        self.config = config or BacktestConfig()
        self.signal_generator = PositionSignalGenerator(self.config)
    
    def run_backtest_analysis(self, bond_type: str, test_period: List, 
                             env: Dict, stationary: bool = True) -> None:
        """
        Run complete backtest analysis with plotting.
        
        Args:
            bond_type: Type of bond/instrument
            test_period: Period for testing
            env: Environment data
            stationary: Whether to filter for stationary bonds
        """
        logger.info(f"Running backtest analysis for {bond_type}")
        
        # Load and prepare data
        df_price = loadCurvePxTS(bond_type, adjust=True)
        df_price = self.signal_generator.generate_signals(df_price, 'ytm')
        
        # Filter data for test period
        df_price = self._filter_data_for_period(df_price, test_period)
        
        # Calculate returns and PnL
        df_price = self._calculate_pnl(df_price, test_period, env)
        
        # Select bonds for analysis
        bonds = self._select_bonds_for_analysis(df_price, env, stationary)
        
        # Generate plots
        self._generate_plots(bonds, df_price, env)
    
    def _filter_data_for_period(self, df_price: Dict, test_period: List) -> Dict:
        """Filter price data for the test period."""
        for key in df_price.keys():
            if 'stat' not in key:
                df_price[key] = df_price[key].loc[test_period[0]:test_period[1]]
            if ('position' in key) and ('clean_quo_mean' in key):
                df_price[key].dropna(axis=1, how='all', inplace=True)
        return df_price
    
    def _calculate_pnl(self, df_price: Dict, test_period: List, env: Dict) -> Dict:
        """Calculate PnL and cumulative returns."""
        # Get common bonds
        common = env['CBClean'].columns.intersection(df_price['clean_act'].columns)
        df_price['clean_cb'] = env['CBClean'].loc[df_price['clean_act'].index, common]
        
        # Calculate returns
        return_act = (df_price['clean_act']
                     .fillna(df_price['clean_cb'].loc[test_period[0]:test_period[1]]))
        return_act = return_act.diff(1)
        return_quo = df_price['clean_quo_mean'].diff(1)
        
        # Calculate PnL
        pnl = df_price['position'].shift(1) * (return_act - return_quo)
        df_price['accum'] = pnl.cumsum()
        
        return df_price
    
    def _select_bonds_for_analysis(self, df_price: Dict, env: Dict, 
                                  stationary: bool) -> pd.Index:
        """Select bonds for analysis based on criteria."""
        # Filter by maturity
        bonds = env['Def'][
            (env['Def']['剩余期限'] > self.config.min_maturity) &
            (env['Def']['剩余期限'] < self.config.max_maturity)
        ].sort_index()
        
        # Get common bonds
        common = env['CBClean'].columns.intersection(df_price['clean_act'].columns)
        bonds = bonds.index.intersection(common)
        
        # Ensure even number of bonds
        bonds = bonds[0:len(bonds)//2*2]
        
        # Filter for stationary bonds if requested
        if stationary:
            stationary_bonds = df_price['ytm_stat'][
                df_price['ytm_stat']['stationary'] == 'YES'
            ].index
            # Uncomment if you want to filter: bonds = bonds.intersection(stationary_bonds)
        
        return bonds
    
    def _generate_plots(self, bonds: pd.Index, df_price: Dict, env: Dict) -> None:
        """Generate plots for bond analysis."""
        n_plots = len(bonds) // self.config.bonds_per_plot
        
        logger.info(f"Generating {n_plots} plots with {self.config.bonds_per_plot} bonds each")
        
        for i in range(n_plots):
            start_idx = self.config.bonds_per_plot * i
            end_idx = self.config.bonds_per_plot * (i + 1)
            bonds_plot = bonds[start_idx:end_idx]
            
            # Generate different types of plots
            plotBondTS(bonds_plot, df_price, env, 2, 'ytm', 'price')
            plotBondTS(bonds_plot, df_price, env, 2, 'dirty', 'yield')


class ResultsConsolidator:
    """Consolidates pricing results from multiple sources."""
    
    def __init__(self, bond_type: str):
        self.bond_type = bond_type
    
    def consolidate_pricing_results(self, dict_price: List[Dict]) -> Dict[str, pd.DataFrame]:
        """
        Consolidate pricing results from multiple dictionaries.
        
        Args:
            dict_price: List of pricing result dictionaries
            
        Returns:
            Consolidated pricing results
        """
        if self.bond_type == 'IRS':
            data_types = ['ytm_act', 'ytm_quo']
        else:
            data_types = ['ytm_act', 'ytm_quo', 'dur_level', 'dur_slope', 'dur_curva', 'ytm_spot']
        
        consolidated = {}
        
        for data_type in data_types:
            consolidated[data_type] = {}
            
            # Combine results from all dictionaries
            for i, price_dict in enumerate(dict_price):
                if data_type in price_dict:
                    consolidated[data_type][i] = price_dict[data_type]
            
            # Concatenate and clean up
            if consolidated[data_type]:
                consolidated[data_type] = (pd.concat(consolidated[data_type])
                                         .droplevel(0)
                                         .sort_index()
                                         .drop_duplicates())
        
        return consolidated


class StatisticalAdjuster:
    """Handles statistical adjustments for pricing data."""
    
    def __init__(self, bond_type: str):
        self.bond_type = bond_type
    
    def adjust_pricing_statistics(self, test_period: List, env: Dict) -> Dict[str, pd.DataFrame]:
        """
        Adjust pricing statistics for the given test period.
        
        Args:
            test_period: Period for testing
            env: Environment data
            
        Returns:
            Adjusted pricing data
        """
        # Legacy function loadPriceTimeSeries not present in refactored module.
        # Fallback: reuse loadCurvePxTS which provides time series used earlier.
        from curves.utils.loader import loadCurvePxTS
        df_price = loadCurvePxTS(self.bond_type, adjust=True)
        
        # Initialize adjustment dataframes (ensure keys exist)
        if 'ytm_quo' not in df_price or 'ytm_act' not in df_price:
            logger.warning("ytm_quo / ytm_act missing in loaded price time series; skipping statistical adjustment")
            return df_price

        df_price['ytm_quo_mean'] = pd.DataFrame(
            dtype=float,
            index=df_price['ytm_quo'].index,
            columns=df_price['ytm_quo'].columns
        )
        df_price['ytm_quo_vol'] = pd.DataFrame(
            0.0,
            dtype=float,
            index=df_price['ytm_quo'].index,
            columns=df_price['ytm_quo'].columns
        )

        stat_obj = {}
        for i, date in enumerate(df_price['ytm_quo'].index):
            try:
                start_date = date - relativedelta(months=3)
                end_date = date - timedelta(hours=1)

                # Defensive intersection of columns with env Def index
                bond_universe = env['Def'].index if 'Def' in env else df_price['ytm_act'].columns
                common_bonds_act = df_price['ytm_act'].columns.intersection(bond_universe)
                common_bonds = df_price['ytm_quo'].columns.intersection(bond_universe)
                df_act = df_price['ytm_act'].loc[start_date:end_date, common_bonds_act]
                df_quo = df_price['ytm_quo'].loc[start_date:end_date, common_bonds]

                stat_obj['BondCurve'] = statAnalysis_BC(env, df_act, df_quo)
                bonds = stat_obj['BondCurve'].index.intersection(common_bonds)

                # Update mean and volatility only for available stats
                if 'ytm_stat' in df_price:
                    mean_series = df_price['ytm_stat'].loc[bonds, 'mean'] if 'mean' in df_price['ytm_stat'].columns else 0
                    vol_series = df_price['ytm_stat'].loc[bonds, 'vol'] if 'vol' in df_price['ytm_stat'].columns else 0
                else:
                    mean_series = 0
                    vol_series = 0

                df_price['ytm_quo_mean'].loc[date, bonds] = (
                    df_price['ytm_quo'].loc[date, bonds].to_numpy() + mean_series
                )
                df_price['ytm_quo_vol'].loc[date, bonds] = (
                    df_price['ytm_quo_vol'].loc[date, bonds].to_numpy() + vol_series
                )
            except Exception as e:
                logger.warning(f"Failed to adjust statistics for {date}: {e}")

        # Clean up zero volatilities -> set to NaN for future division safety
        df_price['ytm_quo_vol'] = df_price['ytm_quo_vol'].replace(0.0, pd.NA)

        # Persist
        output_file = os.path.join(DIR_INPUT, f'{self.bond_type}-cvpx.pkl')
        updatePKL(df_price, output_file)
        return df_price


class CarryRollCalculator:
    """Calculates carry and roll for IRS contracts."""
    
    def calculate_carry_roll(self, dict_curve: Dict, test_days: List, env: Dict) -> None:
        """
        Calculate carry and roll metrics for IRS contracts.
        
        Args:
            dict_curve: Dictionary of curve objects
            test_days: List of test dates
            env: Environment data
        """
        date_list = [d for d in test_days if d in dict_curve.keys()]
        
        contracts_info = {
            'roll3m': pd.DataFrame(index=date_list, columns=IRSConfig.IRS_LIST),
            'carry3m': pd.DataFrame(index=date_list, columns=IRSConfig.IRS_LIST),
        }
        
        logger.info("Calculating carry and roll parameters")
        
        for date in date_list:
            try:
                start_date = date - relativedelta(months=GeneralConfig.STAT_WINDOW)
                end_date = date - timedelta(hours=1)
                
                fwd_data = irs.curves2Fixings(date, env, dict_curve[date])
                contracts = irs.evalueContract(
                    date, env.loc[date, IRSConfig.IRS_LIST], fwd_data, 1
                )
                
                contracts_info['duration'] = contracts['value']['Duration']
                contracts_info['carry3m'].loc[date] = contracts['value']['Carry(3m,bp)'].values / 100
                contracts_info['roll3m'].loc[date] = contracts['value']['Roll(3m,bp)'].values / 100
                
            except Exception as e:
                logger.warning(f"Failed to calculate carry/roll for {date}: {e}")
        
        # Save results
        output_file = os.path.join(DIR_INPUT, 'IRS-cvpx.pkl')
        updatePKL(contracts_info, output_file)


# Legacy function wrappers for backward compatibility
def position_signal(df_price: pd.DataFrame, a: float, b: float, stype: str) -> pd.DataFrame:
    """Legacy wrapper for position signal generation."""
    config = BacktestConfig(long_threshold=a, short_threshold=a, close_threshold=b)
    generator = PositionSignalGenerator(config)
    return generator.generate_signals(df_price, stype)


# Additional utility functions that were in the original file would be added here
# with similar class-based organization...

if __name__ == "__main__":
    # Example usage
    config = BacktestConfig(
        long_threshold=1.0,
        short_threshold=1.0,
        close_threshold=0.5,
        bonds_per_plot=10
    )
    
    analyzer = BacktestAnalyzer(config)
    # analyzer.run_backtest_analysis('CB', ['2023-01-01', '2023-12-31'], env_data)
