# -*- coding: utf-8 -*-
"""
Asset class hierarchy for multi-asset portfolio management.
"""
from abc import ABC, abstractmethod
import pandas as pd
import numpy as np
from typing import Optional, Dict, Union
from multiasset.utils import get_default_sensitivities


# Country code to currency code mapping for FX factors
COUNTRY_TO_CURRENCY = {
    'US': 'USD',
    'UK': 'GBP',
    'JP': 'JPY',
    'DE': 'EUR',  # Germany/EU uses EUR
    'EU': 'EUR',
    'CN': 'CNY',
}


class Asset(ABC):
    """Base class for all assets in the portfolio."""

    def __init__(self, name: str, factor: Union[str, Dict[str, float]],
                 sensitivity: Optional[float] = None):
        """
        Initialize an asset.

        Args:
            name: Asset name
            factor: Risk factor identifier (str) or dict of {factor: sensitivity}
            sensitivity: Sensitivity to the risk factor (for single-factor assets)
        """
        self.name = name

        # Handle both single-factor and multi-factor specification
        if isinstance(factor, dict):
            self.factors = factor  # Dict[factor_name, sensitivity]
            self.factor = list(factor.keys())[0] if factor else None
            self.sensitivity = list(factor.values())[0] if factor else None
        else:
            self.factor = factor
            self.sensitivity = sensitivity if sensitivity is not None else 1.0
            self.factors = {factor: self.sensitivity}

        self._returns_cache: Optional[pd.Series] = None
        self._volatility_cache: Optional[float] = None

    @abstractmethod
    def calculate_returns(self, risk_factors: pd.DataFrame) -> pd.Series:
        """
        Calculate asset returns from risk factors.

        Args:
            risk_factors: DataFrame of risk factor time series

        Returns:
            Series of asset returns
        """
        pass

    def get_returns(self, risk_factors: pd.DataFrame, use_cache: bool = True) -> pd.Series:
        """
        Get asset returns with optional caching.

        Args:
            risk_factors: DataFrame of risk factor time series
            use_cache: Whether to use cached returns

        Returns:
            Series of asset returns
        """
        if use_cache and self._returns_cache is not None:
            return self._returns_cache

        self._returns_cache = self.calculate_returns(risk_factors)
        return self._returns_cache

    def get_volatility(self, risk_factors: pd.DataFrame,
                       annualization_factor: float = np.sqrt(252),
                       use_cache: bool = True) -> float:
        """
        Calculate annualized volatility.

        Args:
            risk_factors: DataFrame of risk factor time series
            annualization_factor: Factor to annualize volatility (default: sqrt(252) for daily data)
            use_cache: Whether to use cached volatility

        Returns:
            Annualized volatility
        """
        if use_cache and self._volatility_cache is not None:
            return self._volatility_cache

        returns = self.get_returns(risk_factors, use_cache=use_cache)
        self._volatility_cache = returns.std() * annualization_factor
        return self._volatility_cache

    def clear_cache(self):
        """Clear cached calculations."""
        self._returns_cache = None
        self._volatility_cache = None

    def __repr__(self):
        return f"{self.__class__.__name__}(name='{self.name}', factor='{self.factor}', sensitivity={self.sensitivity})"


class BondAsset(Asset):
    """Government bond asset with duration-based sensitivity."""

    def __init__(self, name: str, factor: str, duration: float = 9.0):
        """
        Initialize a bond asset.

        Args:
            name: Bond name (e.g., 'US_Treasury')
            factor: Yield risk factor (e.g., 'IRDL.US')
            duration: Modified duration (default: 9.0 years for 10Y bonds)
        """
        super().__init__(name, factor, sensitivity=-duration)
        self.duration = duration

    def calculate_returns(self, risk_factors: pd.DataFrame) -> pd.Series:
        """
        Calculate bond price returns from yield changes.

        Price change (%) ≈ -Duration × Yield change (decimal)

        Args:
            risk_factors: DataFrame with yield levels in %

        Returns:
            Series of bond price returns in %
        """
        if self.factor not in risk_factors.columns:
            raise ValueError(f"Risk factor '{self.factor}' not found in data")

        # Convert yields from % to decimal
        yield_levels = risk_factors[self.factor] / 100.0

        # Calculate daily yield changes
        yield_changes = yield_levels.diff()

        # Price returns = -Duration × Yield change × 100 (to get %)
        price_returns = self.sensitivity * yield_changes * 100

        return price_returns


class CommodityAsset(Asset):
    """Commodity futures asset with direct price exposure."""

    def __init__(self, name: str, factor: str):
        """
        Initialize a commodity asset.

        Args:
            name: Commodity name (e.g., 'Gold')
            factor: Price risk factor (e.g., 'CMDL.AU')
        """
        super().__init__(name, factor, sensitivity=1.0)

    def calculate_returns(self, risk_factors: pd.DataFrame) -> pd.Series:
        """
        Calculate commodity returns from price changes.

        Args:
            risk_factors: DataFrame with commodity prices

        Returns:
            Series of commodity returns in %
        """
        if self.factor not in risk_factors.columns:
            raise ValueError(f"Risk factor '{self.factor}' not found in data")

        # Direct percentage returns
        returns = risk_factors[self.factor].pct_change() * 100

        return returns


class FXAsset(Asset):
    """FX spot rate asset with direct exchange rate exposure."""

    def __init__(self, name: str, factor: str):
        """
        Initialize an FX asset.

        Args:
            name: FX pair name (e.g., 'USDCNY')
            factor: FX delta level risk factor (e.g., 'FXDL.USDCNY')
        """
        super().__init__(name, factor, sensitivity=1.0)

    def calculate_returns(self, risk_factors: pd.DataFrame) -> pd.Series:
        """
        Calculate FX returns from exchange rate changes.

        Args:
            risk_factors: DataFrame with FX spot levels

        Returns:
            Series of FX returns in %
        """
        if self.factor not in risk_factors.columns:
            raise ValueError(f"Risk factor '{self.factor}' not found in data")

        # Direct percentage returns
        returns = risk_factors[self.factor].pct_change() * 100

        return returns


class SlopeSensitiveBondAsset(BondAsset):
    """
    Bond asset with sensitivity to both level and slope.

    This allows modeling exposure to curve steepening/flattening separately
    from parallel shifts.
    """

    def __init__(self, name: str, level_factor: str, slope_factor: str,
                 duration: float = 9.0, slope_sensitivity: float = 6.0):
        """
        Initialize a slope-sensitive bond asset.

        Args:
            name: Bond name
            level_factor: Yield level risk factor (e.g., 'IRDL.US')
            slope_factor: Yield slope risk factor (e.g., 'IRSL.US')
            duration: Modified duration for level moves
            slope_sensitivity: Key-rate duration difference for slope moves
        """
        super().__init__(name, level_factor, duration)
        self.slope_factor = slope_factor
        self.slope_sensitivity = -slope_sensitivity  # Negative like duration
        
        # IMPORTANT: Register slope factor in self.factors for exposure matrix building
        # This allows the optimizer to see the slope exposure and differentiate assets
        self.factors[slope_factor] = self.slope_sensitivity

    def calculate_returns(self, risk_factors: pd.DataFrame) -> pd.Series:
        """
        Calculate bond returns from both level and slope changes.

        Args:
            risk_factors: DataFrame with yield levels and slopes

        Returns:
            Series of bond price returns in %
        """
        # Level effect
        level_returns = super().calculate_returns(risk_factors)

        # Slope effect
        if self.slope_factor in risk_factors.columns:
            slope_levels = risk_factors[self.slope_factor] / 100.0
            slope_changes = slope_levels.diff()
            slope_returns = self.slope_sensitivity * slope_changes * 100

            return level_returns + slope_returns
        else:
            return level_returns


class MultiFactorBondAsset(Asset):
    """
    Bond asset with multiple risk factor sensitivities.

    Supports exposure to:
    - Interest rate level (IRDL) - PC1 of yield curve
    - Interest rate slope (IRSL) - PC2 of yield curve
    - Interest rate curvature (IRCV) - PC3 of yield curve
    - FX rate (FXDL)
    
    For IR factors (PCA-based):
        The sensitivity represents the bond value change (in %) per 1-unit PC score change.
        Sensitivity = -duration × loading × std
        where loading is the PCA loading for this tenor, and std is the yield change std.
    
    For FX factors:
        The sensitivity represents the bond value change per 1% FX move.
        Sensitivity = 1.0 means full currency exposure.
    """

    def __init__(self, name: str, country: str, tenor: str,
                 sensitivities: Optional[Dict[str, float]] = None,
                 pca_sensitivities: Optional[Dict[str, float]] = None):
        """
        Initialize a multi-factor bond asset.

        Args:
            name: Bond name (e.g., 'US1Y', 'EU10Y')
            country: Country code (e.g., 'US', 'EU', 'UK', 'JP', 'CN')
            tenor: Tenor identifier (e.g., '1Y', '2Y', '5Y', '10Y', '30Y')
            sensitivities: Dict of duration-based sensitivities (legacy, for backward compat).
                           Format: {'IRDL': duration, 'IRSL': slope_sens, 'IRCV': curv_sens, 'FXDL': fx_sens}
            pca_sensitivities: Dict of PCA-derived sensitivities. If provided, these override
                               the duration-based sensitivities for IR factors.
                               Format: {'IRDL': pc1_sens, 'IRSL': pc2_sens, 'IRCV': pc3_sens}
        """
        self.country = country
        self.tenor = tenor

        # Default sensitivities based on tenor if not provided
        if sensitivities is None:
            sensitivities = get_default_sensitivities(tenor)
        
        self.base_sensitivities = sensitivities.copy()
        self.pca_sensitivities = pca_sensitivities

        # Build factor map
        factor_map = {}

        # Interest rate level sensitivity (IRDL = PC1)
        if 'IRDL' in sensitivities:
            # If PCA sensitivities provided, use them; otherwise use duration as proxy
            if pca_sensitivities and 'IRDL' in pca_sensitivities:
                # PCA sensitivity: value change per 1-unit PC1 change
                factor_map[f'IRDL.{country}'] = pca_sensitivities['IRDL']
            else:
                # Legacy: use negative duration (will be scaled by yield change)
                factor_map[f'IRDL.{country}'] = -sensitivities['IRDL']

        # Interest rate slope sensitivity (IRSL = PC2)
        if 'IRSL' in sensitivities:
            if pca_sensitivities and 'IRSL' in pca_sensitivities:
                factor_map[f'IRSL.{country}'] = pca_sensitivities['IRSL']
            else:
                factor_map[f'IRSL.{country}'] = -sensitivities['IRSL']

        # Interest rate curvature sensitivity (IRCV = PC3)
        # Check pca_sensitivities first (preferred), then fall back to base sensitivities
        if pca_sensitivities and 'IRCV' in pca_sensitivities and pca_sensitivities['IRCV'] != 0:
            factor_map[f'IRCV.{country}'] = pca_sensitivities['IRCV']
        elif 'IRCV' in sensitivities and sensitivities['IRCV'] != 0:
            factor_map[f'IRCV.{country}'] = -sensitivities['IRCV']

        # FX sensitivity (for foreign bonds priced in CNY)
        # Use proper currency code (USD, EUR, GBP, JPY) instead of country code
        if 'FXDL' in sensitivities and country != 'CN':
            currency = COUNTRY_TO_CURRENCY.get(country, country)
            factor_map[f'FXDL.{currency}CNY'] = sensitivities['FXDL']

        super().__init__(name, factor_map)

    def calculate_returns(self, risk_factors: pd.DataFrame) -> pd.Series:
        """
        Calculate bond returns from multiple risk factors.

        For IR factors (IRDL, IRSL, IRCV):
            These are PCA scores (cumulative). Returns = sensitivity × Δ(PC score)
            The sensitivity already includes duration × loading × std.
            
        For FX factors:
            Returns = sensitivity × (% change in FX rate)

        Args:
            risk_factors: DataFrame with all risk factors

        Returns:
            Series of bond price returns in %
        """
        total_returns = None

        for factor_name, sensitivity in self.factors.items():
            if factor_name not in risk_factors.columns:
                continue

            # Different calculation for different factor types
            if 'IRDL' in factor_name or 'IRSL' in factor_name or 'IRCV' in factor_name:
                # IR factors are PCA scores (cumulative changes)
                # Take diff to get daily PC score changes
                pc_score_changes = risk_factors[factor_name].diff()
                # Returns = sensitivity × PC score change
                # sensitivity is already: -duration × loading × std (value change per PC unit)
                factor_returns = sensitivity * pc_score_changes
            elif 'FXDL' in factor_name:
                # FX factors: direct percentage returns
                factor_returns = risk_factors[factor_name].pct_change() * 100 * sensitivity
            else:
                # Generic: percentage returns
                factor_returns = risk_factors[factor_name].pct_change() * 100 * sensitivity

            if total_returns is None:
                total_returns = factor_returns
            else:
                total_returns = total_returns + factor_returns

        if total_returns is None:
            raise ValueError(f"No valid risk factors found for asset {self.name}")

        return total_returns


