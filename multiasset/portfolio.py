# -*- coding: utf-8 -*-
"""
Multi-asset portfolio with risk factor exposure.
"""
import pandas as pd
import numpy as np
from typing import List, Optional
from multiasset.assets import Asset
from multiasset.risk_loader import RiskFactorLoader


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
                    # IR factors are PCA cumulative scores — diff() recovers daily changes
                    pc_score_changes = risk_factors_df[factor_name].diff()
                    factor_contrib = sensitivity * pc_score_changes
                elif 'SPDL' in factor_name or 'SPSL' in factor_name:
                    # Spread factors are also cumulative sums of daily bp changes —
                    # must use diff(), NOT pct_change() (which explodes on a cumsum series)
                    factor_contrib = risk_factors_df[factor_name].diff() * sensitivity
                elif 'FXDL' in factor_name or 'CMDL' in factor_name:
                    # FX and commodity factors: stored as price levels, use pct return
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
