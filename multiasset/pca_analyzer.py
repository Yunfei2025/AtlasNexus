# -*- coding: utf-8 -*-
"""
PCA-based risk factor analyzer for yield curves.
"""
import os
import pickle
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Union
from pathlib import Path
from sklearn.decomposition import PCA

from .config import CURVE_CONFIG, SPREAD_CONFIG


def _load_fx_curve_artifact(input_dir: str) -> dict:
    for file_name in ("fxcurve_ts.pkl", "curve_ts.pkl"):
        file_path = os.path.join(input_dir, file_name)
        if os.path.exists(file_path):
            try:
                return pd.read_pickle(file_path)
            except Exception as exc:
                try:
                    with open(file_path, 'rb') as file:
                        return pickle.load(file)
                except Exception:
                    # Quietly treat legacy artifacts as cache misses; callers can
                    # regenerate the file from upstream market data.
                    pass
    raise FileNotFoundError("Neither fxcurve_ts.pkl nor curve_ts.pkl exists in the input directory")


# Deterministic factor weights for yield curve analysis
# Tenors: 1Y, 2Y, 5Y, 10Y, 30Y
DETERMINISTIC_WEIGHTS = {
    'Level': np.array([0.2, 0.2, 0.2, 0.2, 0.2]),      # Equal weights (sum=1)
    'Slope': np.array([-0.4, -0.2, 0.0, 0.2, 0.4]),    # Short negative, long positive (sum=0)
    'Curvature': np.array([0.25, -0.25, 0.0, -0.25, 0.25])  # Wings vs belly (sum=0)
}

# Deterministic spread weights
# CDB: 5 tenors (1Y, 2Y, 5Y, 10Y, 30Y) - Level and Slope
DETERMINISTIC_SPREAD_WEIGHTS = {
    'CDB': {
        'Level': np.array([0.2, 0.2, 0.2, 0.2, 0.2]),     # Equal weights (sum=1)
        'Slope': np.array([-0.4, -0.2, 0.0, 0.2, 0.4]),   # Short negative, long positive (sum=0)
    },
    # IRS: 3 tenors (1Y, 2Y, 5Y) - Level and Slope
    'IRS': {
        'Level': np.array([1/3, 1/3, 1/3]),              # Equal weights (sum=1)
        'Slope': np.array([-0.5, 0.0, 0.5]),             # Short negative, long positive (sum=0)
    },
    # ICP: 1 tenor (1Y) - Level only
    'ICP': {
        'Level': np.array([1.0]),                        # Single tenor (sum=1)
    },
}


class DeterministicRiskFactorAnalyzer:
    """
    Deterministic (rule-based) risk factor analyzer for yield curves.
    
    Uses predefined weights for Level, Slope, Curvature factors instead of PCA.
    Assumes tenors: 1Y, 2Y, 5Y, 10Y, 30Y
    """
    
    def __init__(self, input_dir: Union[str, Path]):
        """
        Initialize the deterministic risk factor analyzer.
        
        Args:
            input_dir: Directory containing curve data files
        """
        self.input_dir = str(input_dir)
        self._full_history_scores_cache: Optional[pd.DataFrame] = None
        self.weights = DETERMINISTIC_WEIGHTS.copy()
        
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
                curves_ts = _load_fx_curve_artifact(self.input_dir)
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
                # Handle ICP separately (from database-px.pkl)
                if spread_type == 'ICP':
                    for file_name, key in (('database-px.pkl', 'ICP'), ('IRS-cvpx.pkl', 'ytm_act')):
                        file_path = os.path.join(self.input_dir, file_name)
                        if not os.path.exists(file_path):
                            continue
                        try:
                            data = pd.read_pickle(file_path)
                            if file_name == 'database-px.pkl' and 'ICP' in data:
                                icp_col = '中债商业银行同业存单到期收益率(AAA):1年'
                                if icp_col in data['ICP'].columns:
                                    return data['ICP'][[icp_col]]
                            if file_name == 'IRS-cvpx.pkl' and isinstance(data, dict) and key in data:
                                frame = data[key]
                                icp_col = 'FR007S1Y.IR'
                                if icp_col in frame.columns:
                                    return frame[[icp_col]]
                        except Exception as exc:
                            print(f"Warning: could not load spread fallback {file_path}: {exc}")
                return None
            
            pkl_file, pkl_key, cols = SPREAD_CONFIG[spread_type]
            file_path = os.path.join(self.input_dir, pkl_file)
            try:
                data = pd.read_pickle(file_path)
                data = data[pkl_key]
            except Exception as exc:
                print(f"Warning: Could not load spread data for {spread_type} from {file_path}: {exc}")
                if spread_type == 'IRS':
                    fallback_path = os.path.join(self.input_dir, 'IRS-cvpx.pkl')
                    if os.path.exists(fallback_path):
                        try:
                            fallback = pd.read_pickle(fallback_path)
                            data = fallback.get('ytm_act') if isinstance(fallback, dict) else None
                        except Exception as fallback_exc:
                            print(f"Warning: Could not load IRS fallback {fallback_path}: {fallback_exc}")
                            return None
                    else:
                        return None
                else:
                    return None
            
            available = [c for c in cols if c in data.columns]
            if len(available) < 1:
                return None
            
            return data[available]
        except Exception as e:
            print(f"Warning: Could not load spread data for {spread_type}: {e}")
            return None
    
    def calculate_full_history_deterministic_scores(
        self, 
        countries: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        Calculate deterministic factor scores over full available history.
        
        Args:
            countries: List of country codes to analyze. If None, uses all in CURVE_CONFIG.
            
        Returns:
            DataFrame with columns like 'Level.US', 'Slope.US', 'Curvature.US', etc.
        """
        if self._full_history_scores_cache is not None:
            return self._full_history_scores_cache
        
        if countries is None:
            # Deterministic mode should cover the same country universe as PCA mode:
            # CN from CURVE_CONFIG plus countries available in fxcurve/curve artifacts.
            try:
                curves_ts = _load_fx_curve_artifact(self.input_dir)
                countries = sorted(set(CURVE_CONFIG.keys()) | set(curves_ts.keys()))
            except Exception:
                countries = list(CURVE_CONFIG.keys())
        
        all_scores = pd.DataFrame()
        
        for country in countries:
            curve_data = self._load_curve_data(country)
            if curve_data is None or curve_data.empty:
                print(f"Skipping {country}: no curve data")
                continue
            
            # Apply deterministic weights directly to yield levels.
            # IRDL.XX = weighted average yield (e.g. ~2.5% for CN)
            # IRSL.XX = weighted slope (long - short), meaningful in % units
            # This preserves the current absolute level rather than an
            # arbitrary cumsum starting from 0 on the first available date.
            for factor_name, weights in self.weights.items():
                n_tenors = min(len(weights), len(curve_data.columns))
                if n_tenors < len(weights):
                    print(f"Warning: {country} has only {n_tenors} tenors, expected {len(weights)}")
                    w = weights[:n_tenors]
                    tenor_levels = curve_data.iloc[:, :n_tenors]
                else:
                    w = weights
                    tenor_levels = curve_data.iloc[:, :len(weights)]
                
                # Factor level = weighted combination of current yield levels
                factor_level = (tenor_levels * w).sum(axis=1)
                
                # Store with naming convention: Factor.Country
                col_name = f"{factor_name}.{country}"
                all_scores[col_name] = factor_level
        
        self._full_history_scores_cache = all_scores
        return all_scores
    
    def calculate_full_history_deterministic_spread_scores(
        self,
        spread_types: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        Calculate deterministic spread factor scores over full available history.
        
        Args:
            spread_types: List of spread types to analyze. If None, uses all in DETERMINISTIC_SPREAD_WEIGHTS.
            
        Returns:
            DataFrame with columns like 'Level.CDB', 'Slope.CDB', 'Level.IRS', etc.
        """
        if spread_types is None:
            spread_types = list(DETERMINISTIC_SPREAD_WEIGHTS.keys())
        
        all_scores = pd.DataFrame()
        
        for spread_type in spread_types:
            spread_data = self._load_spread_data(spread_type)
            if spread_data is None or spread_data.empty:
                print(f"Skipping {spread_type}: no spread data")
                continue
            
            # Get weights for this spread type
            if spread_type not in DETERMINISTIC_SPREAD_WEIGHTS:
                print(f"Skipping {spread_type}: no weights defined")
                continue
            
            spread_weights = DETERMINISTIC_SPREAD_WEIGHTS[spread_type]
            
            # Apply deterministic weights directly to spread levels.
            # SPDL.CDB = equal-weighted avg CDB spread level in %
            # SPSL.CDB = slope of CDB spread curve
            # Preserves current absolute level rather than an arbitrary cumsum.
            for factor_name, weights in spread_weights.items():
                n_tenors = min(len(weights), len(spread_data.columns))
                if n_tenors < len(weights):
                    print(f"Warning: {spread_type} has only {n_tenors} tenors, expected {len(weights)}")
                    w = weights[:n_tenors]
                    tenor_levels = spread_data.iloc[:, :n_tenors]
                else:
                    w = weights
                    tenor_levels = spread_data.iloc[:, :len(weights)]
                
                # Factor level = weighted combination of current spread levels
                factor_level = (tenor_levels * w).sum(axis=1)
                
                # Store with naming convention: Factor.SpreadType
                col_name = f"{factor_name}.{spread_type}"
                all_scores[col_name] = factor_level
        
        return all_scores
    
    def get_weights_dataframe(self) -> pd.DataFrame:
        """
        Return the deterministic weights as a DataFrame for inspection.
        
        Returns:
            DataFrame with factors as columns and tenors as rows
        """
        tenors = ['1Y', '2Y', '5Y', '10Y', '30Y']
        weights_df = pd.DataFrame(self.weights, index=tenors)
        return weights_df
    
    def get_spread_weights_dataframes(self) -> Dict[str, pd.DataFrame]:
        """
        Return the deterministic spread weights as DataFrames for inspection.
        
        Returns:
            Dict mapping spread type to DataFrame with factors as columns and tenors as rows
        """
        result = {}
        for spread_type, weights in DETERMINISTIC_SPREAD_WEIGHTS.items():
            if spread_type == 'CDB':
                tenors = ['1Y', '2Y', '5Y', '10Y', '30Y']
            elif spread_type == 'IRS':
                tenors = ['1Y', '2Y', '5Y']
            elif spread_type == 'ICP':
                tenors = ['1Y']
            else:
                continue
            result[spread_type] = pd.DataFrame(weights, index=tenors)
        return result

    def get_tenor_sensitivities(self, country: str, tenor: str) -> Dict[str, float]:
        """
        Get deterministic sensitivities for a specific tenor.
        
        Returns the sensitivity of this tenor's yield to each deterministic factor.
        Sensitivity = deterministic weight for that tenor and factor.
        
        Args:
            country: Country code (e.g., 'CN', 'US') - not used for deterministic weights
            tenor: Tenor string (e.g., '1Y', '10Y')
            
        Returns:
            Dict with IRDL, IRSL, IRCV sensitivities (value change per 1-unit factor change)
        """
        tenor_order = ['1Y', '2Y', '5Y', '10Y', '30Y']
        tenor_idx = tenor_order.index(tenor)
        
        sensitivities = {}
        factor_map = {
            'Level': 'IRDL',
            'Slope': 'IRSL',
            'Curvature': 'IRCV',
        }
        
        for factor_name, ir_factor in factor_map.items():
            if factor_name in self.weights:
                weights = self.weights[factor_name]
                if tenor_idx < len(weights):
                    sensitivities[ir_factor] = float(weights[tenor_idx])
        
        return sensitivities


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
                curves_ts = _load_fx_curve_artifact(self.input_dir)
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
        curves_ts = _load_fx_curve_artifact(self.input_dir)
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
        curves_ts = _load_fx_curve_artifact(self.input_dir)
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
