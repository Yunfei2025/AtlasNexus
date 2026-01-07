# -*- coding: utf-8 -*-
"""
Risk factor loader and portfolio classes.
"""
import os
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Union
from pathlib import Path
from sklearn.decomposition import PCA
from multiasset.assets import Asset


class PCARiskFactorAnalyzer:
    """
    PCA-based risk factor analyzer for yield curves.
    
    Computes principal components for each country's yield curve data
    and uses PC1 (level), PC2 (slope), PC3 (curvature) as risk factors.
    """
    
    # Configuration: country -> (pickle_file, pickle_key or None, list of columns or None)
    # If columns is None, use all columns in the DataFrame.
    CURVE_CONFIG: Dict[str, Tuple[str, Optional[str], Optional[List[str]]]] = {
        'CN': (
            'database-px.pkl',
            'CGB',
            [
                '中债国债到期收益率:1年',
                '中债国债到期收益率:2年',
                '中债国债到期收益率:5年',
                '中债国债到期收益率:10年',
                '中债国债到期收益率:30年',
            ],
        ),
        # Other countries are loaded from fxcurve_ts.pkl (handled as default)
    }
    
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
    
    # -------------------------------------------------------------------------
    # Data loading helper
    # -------------------------------------------------------------------------
    def _load_curve_data(self, country: str) -> Optional[pd.DataFrame]:
        """
        Load yield curve DataFrame for a given country.
        
        Returns None if data is unavailable or insufficient.
        """
        try:
            if country in self.CURVE_CONFIG:
                pkl_file, pkl_key, cols = self.CURVE_CONFIG[country]
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
        countries = set(curves_ts.keys()) | set(self.CURVE_CONFIG.keys())
        
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
        # Determine all countries
        curves_ts = pd.read_pickle(os.path.join(self.input_dir, "fxcurve_ts.pkl"))
        countries = set(curves_ts.keys()) | set(self.CURVE_CONFIG.keys())
        
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


class RiskFactorLoader:
    """Loads and caches risk factor data."""
    
    def __init__(self, input_dir: Union[str, Path]):
        """
        Initialize the risk factor loader.
        
        Args:
            input_dir: Directory containing curve and database files
        """
        self.input_dir = str(input_dir)
        self._risk_factors_cache: Optional[pd.DataFrame] = None
        # Create PCA analyzer for IR factors
        self.pca_analyzer = PCARiskFactorAnalyzer(input_dir)
    
    def load_risk_factors(self, use_cache: bool = True) -> pd.DataFrame:
        """
        Load all risk factors from data files.
        
        Args:
            use_cache: Whether to use cached data
            
        Returns:
            DataFrame with all risk factors
        """
        if use_cache and self._risk_factors_cache is not None:
            return self._risk_factors_cache
        
        macro_data = pd.read_pickle(os.path.join(self.input_dir, 'macro-px.pkl'))
        risk_factors = pd.DataFrame()
        
        # Interest rate factors
        risk_factors = self._load_ir_factors(risk_factors)
        
        # FX factors
        risk_factors = self._load_fx_factors(risk_factors, macro_data)
        
        # Commodity factors
        risk_factors = self._load_commodity_factors(risk_factors, macro_data)
        print("Loaded risk factors:", risk_factors.columns.tolist())
        
        # Drop NaN values
        # risk_factors = risk_factors.dropna()
        
        self._risk_factors_cache = risk_factors
        return risk_factors
    
    def _load_ir_factors(self, risk_factors: pd.DataFrame) -> pd.DataFrame:
        """
        Load interest rate level, slope, and curvature factors using full-history PCA.
        
        Uses PCARiskFactorAnalyzer to compute PC1 (Level), PC2 (Slope), PC3 (Curvature)
        from yield curve data over the entire history.
        """
        # Calculate full-history PCA scores for all countries
        pca_scores = self.pca_analyzer.calculate_full_history_pca_scores(n_components=3)
        
        if pca_scores.empty:
            print("Warning: No PCA scores computed for IR factors")
            return risk_factors
        
        # Map PCA components to IR factor names:
        # PC1 -> IRDL (Level), PC2 -> IRSL (Slope), PC3 -> IRCV (Curvature)
        pc_to_ir_map = {
            'PC1': 'IRDL',
            'PC2': 'IRSL',
            'PC3': 'IRCV',
        }
        
        for col in pca_scores.columns:
            # Column format: PC1.US, PC2.CN, etc.
            parts = col.split('.')
            if len(parts) == 2:
                pc_name, country = parts
                if pc_name in pc_to_ir_map:
                    ir_name = f"{pc_to_ir_map[pc_name]}.{country}"
                    risk_factors[ir_name] = pca_scores[col]
        
        return risk_factors
    
    def _load_fx_factors(self, risk_factors: pd.DataFrame, 
                         macro_data: Dict) -> pd.DataFrame:
        """Load FX factors."""
        for currency in ["USD", "EUR", "JPY", "GBP"]:
            risk_factors[f"FXDL.{currency}CNY"] = macro_data["fx"][f"{currency}CNY.IB"]
        
        return risk_factors
    
    def _load_commodity_factors(self, risk_factors: pd.DataFrame,
                                macro_data: Dict) -> pd.DataFrame:
        """Load commodity factors."""
        for commodity in ["AU.SHF", "AL.SHF", "CU.SHF", "SC.INE"]:
            ticker = commodity.split(".")[0]
            risk_factors[f"CMDL.{ticker}"] = macro_data["commodity"][commodity]
        
        return risk_factors
    
    def clear_cache(self):
        """Clear cached risk factors."""
        self._risk_factors_cache = None


class Portfolio:
    """Multi-asset portfolio with risk factor exposure."""
    
    def __init__(self, assets: List[Asset], risk_factor_loader: RiskFactorLoader):
        """
        Initialize a portfolio.
        
        Args:
            assets: List of Asset objects
            risk_factor_loader: RiskFactorLoader instance
        """
        self.assets = {asset.name: asset for asset in assets}
        self.risk_factor_loader = risk_factor_loader
        self._risk_factors: Optional[pd.DataFrame] = None
        self._asset_returns: Optional[pd.DataFrame] = None
        self._volatilities: Optional[pd.Series] = None
    
    def get_risk_factors(self, use_cache: bool = True) -> pd.DataFrame:
        """
        Get risk factor data.
        
        Args:
            use_cache: Whether to use cached data
            
        Returns:
            DataFrame of risk factors
        """
        if use_cache and self._risk_factors is not None:
            return self._risk_factors
        
        self._risk_factors = self.risk_factor_loader.load_risk_factors(use_cache=use_cache)
        return self._risk_factors
    
    def calculate_asset_returns(self, use_cache: bool = True) -> pd.DataFrame:
        """
        Calculate returns for all assets.
        
        Args:
            use_cache: Whether to use cached returns
            
        Returns:
            DataFrame of asset returns
        """
        if use_cache and self._asset_returns is not None:
            return self._asset_returns
        
        risk_factors = self.get_risk_factors(use_cache=use_cache)
        asset_returns = pd.DataFrame()
        
        for name, asset in self.assets.items():
            returns = asset.get_returns(risk_factors, use_cache=use_cache)
            asset_returns[name] = returns
        
        # Drop NaN values
        asset_returns = asset_returns.dropna()
        
        self._asset_returns = asset_returns
        return asset_returns
    
    def calculate_volatilities(self, annualization_factor: float = np.sqrt(252),
                               use_cache: bool = True) -> pd.Series:
        """
        Calculate volatilities for all assets.
        
        Args:
            annualization_factor: Factor to annualize volatility
            use_cache: Whether to use cached values
            
        Returns:
            Series of annualized volatilities
        """
        if use_cache and self._volatilities is not None:
            return self._volatilities
        
        risk_factors = self.get_risk_factors(use_cache=use_cache)
        volatilities = pd.Series(dtype=float)
        
        for name, asset in self.assets.items():
            vol = asset.get_volatility(risk_factors, annualization_factor, use_cache=use_cache)
            volatilities[name] = vol
        
        self._volatilities = volatilities
        return volatilities
    
    def get_asset(self, name: str) -> Asset:
        """Get an asset by name."""
        if name not in self.assets:
            raise ValueError(f"Asset '{name}' not found in portfolio")
        return self.assets[name]
    
    def add_asset(self, asset: Asset):
        """Add an asset to the portfolio."""
        self.assets[asset.name] = asset
        self.clear_cache()
    
    def remove_asset(self, name: str):
        """Remove an asset from the portfolio."""
        if name in self.assets:
            del self.assets[name]
            self.clear_cache()
    
    def clear_cache(self):
        """Clear all cached calculations."""
        self._asset_returns = None
        self._volatilities = None
        for asset in self.assets.values():
            asset.clear_cache()
    
    def calculate_factor_exposures(self, weights: pd.Series) -> pd.DataFrame:
        """
        Calculate total portfolio sensitivity to each risk factor.
        
        Args:
            weights: Portfolio weights for each asset
            
        Returns:
            DataFrame with factor exposures (weighted sensitivities)
        """
        factor_exposures = {}
        
        for asset_name, weight in weights.items():
            asset = self.assets[asset_name]
            
            # For each factor the asset is exposed to
            for factor_name, sensitivity in asset.factors.items():
                if factor_name not in factor_exposures:
                    factor_exposures[factor_name] = 0.0
                factor_exposures[factor_name] += weight * sensitivity
        
        # Convert to DataFrame for better display
        exposure_df = pd.DataFrame([
            {'Risk Factor': factor, 'Total Sensitivity': exposure}
            for factor, exposure in sorted(factor_exposures.items())
        ])
        
        return exposure_df
    
    def calculate_factor_risk_contributions(self, weights: pd.Series, 
                                            use_cache: bool = True) -> pd.DataFrame:
        """
        Calculate risk contribution by risk factor.
        
        This shows how much each risk factor contributes to total portfolio risk.
        
        Args:
            weights: Portfolio weights for each asset
            use_cache: Whether to use cached risk factors
            
        Returns:
            DataFrame with risk contributions by factor
        """
        risk_factors_df = self.get_risk_factors(use_cache=use_cache)
        
        # Calculate factor returns (weighted by portfolio exposures)
        factor_returns = {}
        
        for asset_name, weight in weights.items():
            asset = self.assets[asset_name]
            asset_return = asset.get_returns(risk_factors_df, use_cache=use_cache)
            
            # Decompose asset returns by factor
            for factor_name, sensitivity in asset.factors.items():
                if factor_name not in risk_factors_df.columns:
                    continue
                
                # Calculate this factor's contribution to asset returns
                if 'IRDL' in factor_name or 'IRSL' in factor_name or 'IRCV' in factor_name:
                    # IR factors are PCA scores (cumulative), take diff for daily changes
                    pc_score_changes = risk_factors_df[factor_name].diff()
                    factor_contrib = sensitivity * pc_score_changes
                elif 'FXDL' in factor_name:
                    factor_contrib = risk_factors_df[factor_name].pct_change() * 100 * sensitivity
                else:
                    factor_contrib = risk_factors_df[factor_name].pct_change() * 100 * sensitivity
                
                # Weight by portfolio weight
                weighted_contrib = factor_contrib * weight
                
                if factor_name not in factor_returns:
                    factor_returns[factor_name] = weighted_contrib
                else:
                    factor_returns[factor_name] = factor_returns[factor_name] + weighted_contrib
        
        # Calculate volatility and risk contribution for each factor
        factor_stats = []
        total_risk = 0.0
        
        for factor_name, returns in factor_returns.items():
            vol = returns.std() * np.sqrt(252)
            total_risk += vol
            factor_stats.append({
                'Risk Factor': factor_name,
                'Volatility (% ann.)': vol
            })
        
        # Convert to DataFrame and calculate risk contributions
        factor_df = pd.DataFrame(factor_stats)
        factor_df['Risk Contribution (%)'] = (factor_df['Volatility (% ann.)'] / total_risk) * 100
        
        return factor_df.sort_values('Risk Contribution (%)', ascending=False)
    
    def __len__(self):
        return len(self.assets)
    
    def __repr__(self):
        return f"Portfolio(assets={len(self.assets)})"
