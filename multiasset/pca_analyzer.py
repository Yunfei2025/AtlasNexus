# -*- coding: utf-8 -*-
"""
PCA-based risk factor analyzer for yield curves.
"""
import os
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Union
from pathlib import Path
from sklearn.decomposition import PCA

from .config import CURVE_CONFIG, SPREAD_CONFIG


class PCARiskFactorAnalyzer:
    """
    PCA-based risk factor analyzer for yield curves.
    
    Computes principal components for each country's yield curve data
    and uses PC1 (level), PC2 (slope), PC3 (curvature) as risk factors.
    """
    
    def __init__(self, input_dir: Union[str, Path], lookback_years: float = 1.0):
        """
        Initialize the PCA risk factor analyzer.
        
        Args:
            input_dir: Directory containing curve data files
            lookback_years: Number of years of data to use for PCA (default: 1 year)
        """
        self.input_dir = str(input_dir)
        self.lookback_years = lookback_years
        self._pca_models: Dict[str, PCA] = {}
        self._factor_loadings: Dict[str, pd.DataFrame] = {}
        self._pca_factors_cache: Optional[pd.DataFrame] = None
        self._last_rebalance_date: Optional[pd.Timestamp] = None
        self._full_history_scores_cache: Optional[pd.DataFrame] = None
        self._full_history_spread_scores_cache: Optional[pd.DataFrame] = None
    
    # -------------------------------------------------------------------------
    # Data loading helper
    # -------------------------------------------------------------------------
    def _load_curve_data(self, country: str) -> Optional[pd.DataFrame]:
        """
        Load yield curve DataFrame for a given country.
        
        Returns None if data is unavailable or insufficient.
        """
        try:
            if country in CURVE_CONFIG:
                pkl_file, pkl_key, cols = CURVE_CONFIG[country]
                data = pd.read_pickle(os.path.join(self.input_dir, pkl_file))
                if pkl_key is not None:
                    data = data[pkl_key]
                if cols is not None:
                    available = [c for c in cols if c in data.columns]
                    if len(available) < 3:
                        return None
                    data = data[available]
                return data
            else:
                # Default: load from fxcurve_ts.pkl
                curves_ts = pd.read_pickle(os.path.join(self.input_dir, "fxcurve_ts.pkl"))
                return curves_ts.get(country)
        except Exception as e:
            print(f"Warning: Could not load curve data for {country}: {e}")
            return None
    
    def _load_spread_data(self, spread_type: str) -> Optional[pd.DataFrame]:
        """
        Load spread curve DataFrame for a given spread type.
        
        Returns None if data is unavailable or insufficient.
        """
        try:
            if spread_type not in SPREAD_CONFIG:
                return None
            
            pkl_file, pkl_key, cols = SPREAD_CONFIG[spread_type]
            data = pd.read_pickle(os.path.join(self.input_dir, pkl_file))
            data = data[pkl_key]
            
            available = [c for c in cols if c in data.columns]
            if len(available) < 2:  # Need at least 2 points for spread PCA
                return None
            
            return data[available]
        except Exception as e:
            print(f"Warning: Could not load spread data for {spread_type}: {e}")
            return None
    
    # -------------------------------------------------------------------------
    # PCA fitting
    # -------------------------------------------------------------------------
    def fit_pca(self, rebalance_date: pd.Timestamp,
                n_components: int = 3) -> Dict[str, Tuple[PCA, pd.DataFrame]]:
        """
        Fit PCA models for each country using historical yield curve data.
        
        Args:
            rebalance_date: The date at which to perform PCA analysis
            n_components: Number of principal components to extract (default: 3)
            
        Returns:
            Dict mapping country to (PCA model, factor loadings DataFrame)
        """
        if not isinstance(rebalance_date, pd.Timestamp):
            rebalance_date = pd.Timestamp(rebalance_date)
        
        lookback_days = int(self.lookback_years * 252)
        
        # Determine list of countries: keys from fxcurve_ts + explicit config keys
        curves_ts = pd.read_pickle(os.path.join(self.input_dir, "fxcurve_ts.pkl"))
        countries = set(curves_ts.keys()) | set(CURVE_CONFIG.keys())
        
        results: Dict[str, Tuple[PCA, pd.DataFrame]] = {}
        
        for country in countries:
            curve_df = self._load_curve_data(country)
            if curve_df is None:
                continue
            
            pca_result = self._fit_single_country(
                country, curve_df, rebalance_date, lookback_days, n_components
            )
            if pca_result is not None:
                results[country] = pca_result
        
        self._last_rebalance_date = rebalance_date
        return results
    
    def _fit_single_country(
        self,
        country: str,
        curve_df: pd.DataFrame,
        rebalance_date: pd.Timestamp,
        lookback_days: int,
        n_components: int,
    ) -> Optional[Tuple[PCA, pd.DataFrame]]:
        """Fit PCA for a single country and cache results."""
        if not isinstance(curve_df.index, pd.DatetimeIndex):
            curve_df.index = pd.to_datetime(curve_df.index)
        
        curve_df = curve_df[curve_df.index <= rebalance_date]
        window_df = curve_df.iloc[-lookback_days:] if len(curve_df) >= lookback_days else curve_df
        
        if len(window_df) < 30:
            return None
        
        yield_changes = window_df.diff().dropna()
        if len(yield_changes) < 20:
            return None
        
        # Standardize
        yield_changes_std = (yield_changes - yield_changes.mean()) / yield_changes.std()
        yield_changes_std = yield_changes_std.dropna(axis=1)
        
        pca = PCA(n_components=min(n_components, yield_changes_std.shape[1]))
        pca.fit(yield_changes_std)
        
        loadings = pd.DataFrame(
            pca.components_.T,
            index=yield_changes_std.columns,
            columns=[f'PC{i+1}' for i in range(pca.n_components_)],
        )
        
        self._pca_models[country] = pca
        self._factor_loadings[country] = loadings
        return (pca, loadings)
    
    # -------------------------------------------------------------------------
    # Factor return calculation
    # -------------------------------------------------------------------------
    def calculate_pca_factor_returns(
        self,
        start_date: Optional[pd.Timestamp] = None,
        end_date: Optional[pd.Timestamp] = None,
    ) -> pd.DataFrame:
        """
        Calculate PCA factor returns (IRDL, IRSL, IRCV) for all countries.
        
        Uses the fitted PCA loadings to project yield changes onto principal components.
        
        Args:
            start_date: Start date for factor returns
            end_date: End date for factor returns
            
        Returns:
            DataFrame with columns like IRDL.US, IRSL.US, IRCV.US, etc.
        """
        if not self._pca_models:
            raise ValueError("Must call fit_pca() before calculating factor returns")
        
        if start_date is not None and not isinstance(start_date, pd.Timestamp):
            start_date = pd.Timestamp(start_date)
        if end_date is not None and not isinstance(end_date, pd.Timestamp):
            end_date = pd.Timestamp(end_date)
        
        factor_returns = pd.DataFrame()
        
        for country in self._pca_models.keys():
            curve_df = self._load_curve_data(country)
            if curve_df is None:
                continue
            
            returns = self._calculate_country_factor_returns(
                country, curve_df, start_date, end_date
            )
            if returns is not None:
                factor_returns = pd.concat([factor_returns, returns], axis=1)
        
        return factor_returns
    
    def _calculate_country_factor_returns(
        self,
        country: str,
        curve_df: pd.DataFrame,
        start_date: Optional[pd.Timestamp],
        end_date: Optional[pd.Timestamp],
    ) -> Optional[pd.DataFrame]:
        """Calculate PCA factor returns for a single country."""
        if not isinstance(curve_df.index, pd.DatetimeIndex):
            curve_df.index = pd.to_datetime(curve_df.index)
        
        if start_date is not None:
            curve_df = curve_df[curve_df.index >= start_date]
        if end_date is not None:
            curve_df = curve_df[curve_df.index <= end_date]
        
        yield_changes = curve_df.diff()
        loadings = self._factor_loadings.get(country)
        if loadings is None:
            return None
        
        available_cols = [c for c in loadings.index if c in yield_changes.columns]
        if not available_cols:
            return None
        
        yield_changes_subset = yield_changes[available_cols]
        
        result = pd.DataFrame(index=yield_changes_subset.index)
        for i, pc_name in enumerate(['IRDL', 'IRSL', 'IRCV']):
            pc_col = f'PC{i+1}'
            if pc_col in loadings.columns:
                result[f'{pc_name}.{country}'] = (
                    yield_changes_subset * loadings[pc_col].values
                ).sum(axis=1)
        
        return result
    
    # -------------------------------------------------------------------------
    # Accessors
    # -------------------------------------------------------------------------
    def get_factor_loadings(self, country: str) -> Optional[pd.DataFrame]:
        """Get PCA factor loadings for a specific country."""
        return self._factor_loadings.get(country)
    
    def get_explained_variance(self, country: str) -> Optional[np.ndarray]:
        """Get explained variance ratios for a country's PCA."""
        if country in self._pca_models:
            return self._pca_models[country].explained_variance_ratio_
        return None
    
    def clear_cache(self):
        """Clear cached PCA models and factors."""
        self._pca_models = {}
        self._factor_loadings = {}
        self._pca_factors_cache = None
        self._last_rebalance_date = None
    
    # -------------------------------------------------------------------------
    # Full-history PCA for visualization
    # -------------------------------------------------------------------------
    def calculate_full_history_pca_scores(self, n_components: int = 3) -> pd.DataFrame:
        """
        Calculate PCA scores over the full history for visualization.
        
        Unlike fit_pca() which uses a lookback window for optimization,
        this method fits PCA on the entire available history and projects
        all data points to get continuous PC1/PC2/PC3 time series.
        
        Args:
            n_components: Number of principal components (default: 3)
            
        Returns:
            DataFrame with columns like PC1.US, PC2.US, PC3.US, PC1.CN, etc.
            representing the cumulative PCA scores over time.
        """
        # Return cached result if available
        if self._full_history_scores_cache is not None:
            return self._full_history_scores_cache
        
        # Determine all countries
        curves_ts = pd.read_pickle(os.path.join(self.input_dir, "fxcurve_ts.pkl"))
        countries = set(curves_ts.keys()) | set(CURVE_CONFIG.keys())
        
        all_scores = pd.DataFrame()
        
        for country in countries:
            curve_df = self._load_curve_data(country)
            if curve_df is None:
                continue
            
            scores = self._calculate_country_full_history_scores(
                country, curve_df, n_components
            )
            if scores is not None:
                all_scores = pd.concat([all_scores, scores], axis=1)
        
        # Cache the result
        self._full_history_scores_cache = all_scores
        return all_scores
    
    def _calculate_country_full_history_scores(
        self,
        country: str,
        curve_df: pd.DataFrame,
        n_components: int,
    ) -> Optional[pd.DataFrame]:
        """
        Calculate full-history PCA scores for a single country.
        
        Fits PCA on all available data and returns cumulative PC scores.
        """
        if not isinstance(curve_df.index, pd.DatetimeIndex):
            curve_df.index = pd.to_datetime(curve_df.index)
        
        # Use all available data
        curve_df = curve_df.dropna()
        
        if len(curve_df) < 30:
            return None
        
        # Calculate yield changes
        yield_changes = curve_df.diff().dropna()
        
        if len(yield_changes) < 20:
            return None
        
        # Standardize
        mean = yield_changes.mean()
        std = yield_changes.std().replace(0, 1)
        yield_changes_std = (yield_changes - mean) / std
        yield_changes_std = yield_changes_std.dropna(axis=1)
        
        # Fit PCA on full history
        pca = PCA(n_components=min(n_components, yield_changes_std.shape[1]))
        pca.fit(yield_changes_std)
        
        # Project all data to get PC scores (daily changes in PC space)
        pc_changes = pca.transform(yield_changes_std)
        
        # Cumulative sum to get PC level time series
        pc_cumsum = np.cumsum(pc_changes, axis=0)
        
        # Create DataFrame with PC scores
        pc_names = ['PC1', 'PC2', 'PC3'][:pca.n_components_]
        result = pd.DataFrame(
            pc_cumsum,
            index=yield_changes_std.index,
            columns=[f'{pc}.{country}' for pc in pc_names]
        )
        
        # Store the loadings and std for sensitivity calculation
        loadings = pd.DataFrame(
            pca.components_.T,
            index=yield_changes_std.columns,
            columns=pc_names
        )
        self._pca_models[country] = pca
        self._factor_loadings[country] = loadings
        # Store the std of yield changes for de-standardization
        if not hasattr(self, '_yield_change_std'):
            self._yield_change_std = {}
        self._yield_change_std[country] = std
        
        return result
    
    def calculate_full_history_spread_pca_scores(self, n_components: int = 2) -> pd.DataFrame:
        """
        Calculate PCA scores over the full history for spread curves.
        
        Similar to calculate_full_history_pca_scores but for spread types (IRS, CDB).
        
        Args:
            n_components: Number of principal components (default: 2 for spreads)
            
        Returns:
            DataFrame with columns like PC1.IRS, PC2.IRS, PC1.CDB, PC2.CDB
        """
        # Return cached result if available
        if self._full_history_spread_scores_cache is not None:
            return self._full_history_spread_scores_cache
        
        all_scores = pd.DataFrame()
        
        for spread_type in SPREAD_CONFIG.keys():
            spread_df = self._load_spread_data(spread_type)
            if spread_df is None:
                continue
            
            scores = self._calculate_spread_full_history_scores(
                spread_type, spread_df, n_components
            )
            if scores is not None:
                all_scores = pd.concat([all_scores, scores], axis=1)
        
        # Cache the result
        self._full_history_spread_scores_cache = all_scores
        return all_scores
    
    def _calculate_spread_full_history_scores(
        self,
        spread_type: str,
        spread_df: pd.DataFrame,
        n_components: int,
    ) -> Optional[pd.DataFrame]:
        """
        Calculate full-history PCA scores for a single spread type.
        """
        if not isinstance(spread_df.index, pd.DatetimeIndex):
            spread_df.index = pd.to_datetime(spread_df.index)
        
        # Use all available data
        spread_df = spread_df.dropna()
        
        if len(spread_df) < 30:
            return None
        
        # Calculate spread changes
        spread_changes = spread_df.diff().dropna()
        
        if len(spread_changes) < 20:
            return None
        
        # Standardize
        mean = spread_changes.mean()
        std = spread_changes.std().replace(0, 1)
        spread_changes_std = (spread_changes - mean) / std
        spread_changes_std = spread_changes_std.dropna(axis=1)
        
        # Fit PCA on full history
        pca = PCA(n_components=min(n_components, spread_changes_std.shape[1]))
        pca.fit(spread_changes_std)
        
        # Project all data to get PC scores (daily changes in PC space)
        pc_changes = pca.transform(spread_changes_std)
        
        # Cumulative sum to get PC level time series
        pc_cumsum = np.cumsum(pc_changes, axis=0)
        
        # Create DataFrame with PC scores
        pc_names = ['PC1', 'PC2'][:pca.n_components_]
        result = pd.DataFrame(
            pc_cumsum,
            index=spread_changes_std.index,
            columns=[f'{pc}.{spread_type}' for pc in pc_names]
        )
        
        # Store the loadings and std for sensitivity calculation
        loadings = pd.DataFrame(
            pca.components_.T,
            index=spread_changes_std.columns,
            columns=pc_names
        )
        # Use a separate dict for spread loadings
        if not hasattr(self, '_spread_loadings'):
            self._spread_loadings = {}
        if not hasattr(self, '_spread_change_std'):
            self._spread_change_std = {}
        
        self._spread_loadings[spread_type] = loadings
        self._spread_change_std[spread_type] = std
        
        return result
    
    def get_tenor_sensitivities(self, country: str, tenor: str) -> Dict[str, float]:
        """
        Get PCA-based sensitivities for a specific tenor.
        
        Returns the sensitivity of this tenor's yield to each PC factor.
        Sensitivity = loading * std (to convert from standardized to actual bp change)
        
        For a 1-unit change in PC score, the yield changes by (loading * std) bp.
        The bond value change is then: -duration * (loading * std) / 100
        
        Args:
            country: Country code (e.g., 'CN', 'US')
            tenor: Tenor string (e.g., '1Y', '10Y')
            
        Returns:
            Dict with IRDL, IRSL, IRCV sensitivities (value change per 1-unit PC change)
        """
        if country not in self._factor_loadings:
            return {}
        
        loadings = self._factor_loadings[country]
        std = self._yield_change_std.get(country, pd.Series(dtype=float))
        
        # Find the column that matches the tenor
        tenor_col = None
        if country == 'CN':
            # Chinese column names
            tenor_map = {
                '1Y': '中债国债到期收益率:1年',
                '2Y': '中债国债到期收益率:2年',
                '5Y': '中债国债到期收益率:5年',
                '10Y': '中债国债到期收益率:10年',
                '30Y': '中债国债到期收益率:30年',
            }
            tenor_col = tenor_map.get(tenor)
        else:
            # Foreign curves: e.g., 'US10Y'
            tenor_col = f'{country}{tenor}'
        
        if tenor_col is None or tenor_col not in loadings.index:
            return {}
        
        # Get the loadings and std for this tenor
        tenor_loadings = loadings.loc[tenor_col]  # Series with PC1, PC2, PC3 as index
        tenor_std = std.loc[tenor_col] if isinstance(std, pd.Series) and tenor_col in std.index else 1.0
        
        # Sensitivity = loading * std
        # This gives the yield change (in %) for a 1-unit PC change
        # For bond value: ΔV = -Duration × Δyield
        # Since our PC scores are cumulative yield changes (in std units),
        # and loadings tell us how to convert PC changes to yield changes (in std units),
        # the actual yield change = loading * std
        sensitivities = {}
        pc_to_factor = {'PC1': 'IRDL', 'PC2': 'IRSL', 'PC3': 'IRCV'}
        
        for pc, factor in pc_to_factor.items():
            if pc in tenor_loadings.index:
                # Loading * std gives yield change in % per 1-unit PC change
                # For bond: sensitivity = -Duration × (loading * std)
                # But we want the VALUE change, so we multiply by notional later
                loading_val = float(tenor_loadings.loc[pc])
                sensitivities[factor] = loading_val * tenor_std
        
        return sensitivities
