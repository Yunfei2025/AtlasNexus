# -*- coding: utf-8 -*-
"""
Multi-asset portfolio allocation using risk parity.

This module provides both the legacy functional interface and the new OOP interface
for calculating risk parity allocations.

@author: CMBC
Created on Tue Nov 25 21:24:15 2025
"""
import os 
import sys
from pathlib import Path
import pandas as pd
import numpy as np
from typing import List

# Ensure parent directory (containing the `factors` package) is on sys.path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from multiasset.retrieve import retrieveFXIRCurves
from multiasset.assets import BondAsset, CommodityAsset, MultiFactorBondAsset, Asset
from multiasset.portfolio import Portfolio, RiskFactorLoader
from multiasset.optimizer import RiskParityOptimizer
from multiasset.factor_optimizer import FactorRiskParityOptimizer
from multiasset.utils import get_default_sensitivities

try:
    retrieveFXIRCurves()
except Exception as e:
    print(f"Warning: Could not retrieve FX/IR curves: {e}")

from settings.paths import DIR_INPUT


def create_bond_universe(pca_analyzer=None) -> List[MultiFactorBondAsset]:
    """
    Create comprehensive bond universe with multiple tenors.
    
    Args:
        pca_analyzer: Optional PCARiskFactorAnalyzer for computing PCA-based sensitivities.
                      If provided, sensitivities will be derived from PCA loadings.
    
    Returns:
        List of MultiFactorBondAsset objects for all countries and tenors
    """
    # Map display country codes to risk factor country codes
    country_mapping = {
        'US': 'US',
        'EU': 'DE',  # European bonds use German (DE) yields as proxy
        'UK': 'UK',
        'JP': 'JP',
        'CN': 'CN'
    }
    
    tenors = ['1Y', '2Y', '5Y', '10Y', '30Y']
    
    bonds: List[MultiFactorBondAsset] = []
    for display_country, rf_country in country_mapping.items():
        for tenor in tenors:
            name = f"{display_country}{tenor}"
            
            # Get PCA-based sensitivities if analyzer is available
            pca_sens = None
            if pca_analyzer is not None:
                pca_sens = pca_analyzer.get_tenor_sensitivities(rf_country, tenor)
                if pca_sens:
                    # Multiply by duration to get value sensitivity
                    # PCA loading gives yield change per PC unit
                    # Value change = -duration × yield change
                    defaults = get_default_sensitivities(tenor)
                    duration = defaults.get('IRDL', 5.0)
                    pca_sens = {
                        k: -duration * v for k, v in pca_sens.items()
                    }
            
            bond = MultiFactorBondAsset(
                name=name,
                country=rf_country,  # Use risk factor country code
                tenor=tenor,
                sensitivities=None,  # Use defaults for duration
                pca_sensitivities=pca_sens  # PCA-derived sensitivities
            )
            bonds.append(bond)
    
    return bonds


def create_commodity_universe() -> List[CommodityAsset]:
    """
    Create commodity universe.
    
    Returns:
        List of CommodityAsset objects
    """
    commodities: List[CommodityAsset] = [
        CommodityAsset(name='Gold', factor='CMDL.AU'),
        CommodityAsset(name='Aluminium', factor='CMDL.AL'),
        CommodityAsset(name='Copper', factor='CMDL.CU'),
        CommodityAsset(name='Crude_Oil', factor='CMDL.SC'),
    ]
    
    return commodities


def create_default_portfolio() -> Portfolio:
    """
    Create the default multi-asset portfolio with comprehensive bond universe.
    
    Includes:
    - 25 bonds (5 countries × 5 tenors) with multi-factor sensitivities
    - 4 commodities
    
    Returns:
        Portfolio with default assets configured
    """
    # Initialize risk factor loader (this also initializes the PCA analyzer)
    loader = RiskFactorLoader(DIR_INPUT)
    
    # Trigger PCA calculation to get sensitivities
    # This calls calculate_full_history_pca_scores which stores loadings
    loader.load_risk_factors(use_cache=False)
    
    # Create comprehensive bond universe with PCA-derived sensitivities
    bonds = create_bond_universe(pca_analyzer=loader.pca_analyzer)
    
    # Create commodity universe
    commodities = create_commodity_universe()
    
    # Combine all assets
    assets: List[Asset] = bonds + commodities  # type: ignore
    
    # Create portfolio
    portfolio = Portfolio(assets, loader)
    
    return portfolio


def create_custom_portfolio(selected_asset_names: List[str]) -> Portfolio:
    """
    Create a custom portfolio based on a list of asset names.
    
    Args:
        selected_asset_names: List of asset names to include
        
    Returns:
        Portfolio with only the selected assets
    """
    # Initialize risk factor loader
    loader = RiskFactorLoader(DIR_INPUT)
    
    # Trigger PCA calculation to get sensitivities
    loader.load_risk_factors(use_cache=False)
    
    # Generate all possible assets with PCA-derived sensitivities
    all_bonds = create_bond_universe(pca_analyzer=loader.pca_analyzer)
    all_commodities = create_commodity_universe()
    all_possible_assets = all_bonds + all_commodities # type: ignore
    
    # Filter assets based on names
    selected_assets = [
        asset for asset in all_possible_assets 
        if asset.name in selected_asset_names
    ]
    
    if not selected_assets:
        print("Warning: No valid assets found matching the selection. Using default portfolio.")
        return create_default_portfolio()
        
    # Create portfolio
    portfolio = Portfolio(selected_assets, loader)
    
    return portfolio


# def create_simple_portfolio() -> Portfolio:
#     """
#     Create a simple portfolio (legacy - for backward compatibility).
    
#     Returns:
#         Portfolio with simple single-factor bonds
#     """
#     loader = RiskFactorLoader(DIR_DATA, DIR_INPUT)
    
#     # Simple single-factor bonds
#     assets: List[Asset] = [
#         BondAsset(name='US_Treasury', factor='IRDL.US', duration=9.0),
#         BondAsset(name='EU_Treasury', factor='IRDL.DE', duration=9.0),
#         BondAsset(name='UK_Treasury', factor='IRDL.UK', duration=9.0),
#         BondAsset(name='JP_Treasury', factor='IRDL.JP', duration=9.0),
#         CommodityAsset(name='Gold', factor='CMDL.AU'),
#         CommodityAsset(name='Aluminium', factor='CMDL.AL'),
#         CommodityAsset(name='Copper', factor='CMDL.CU'),
#         CommodityAsset(name='Crude_Oil', factor='CMDL.SC'),
#     ]
    
#     portfolio = Portfolio(assets, loader)
#     return portfolio


def run_risk_parity_allocation(total_capital: float = 10_000_000_000,
                                use_cache: bool = True,
                                use_factor_risk_parity: bool = True,
                                selected_assets: List[str] = None) -> tuple:
    """
    Run risk parity allocation using OOP interface.
    
    Args:
        total_capital: Total capital to allocate (default: 10 billion CNY)
        use_cache: Whether to use cached calculations for performance
        use_factor_risk_parity: If True, use factor-level risk parity; 
                                if False, use asset-level risk parity
        selected_assets: Optional list of asset names to include in the portfolio.
                         If None, uses the default full universe.
    
    Returns:
        Tuple of (summary DataFrame, asset returns DataFrame, volatilities Series,
                 factor exposures DataFrame, factor risk contributions DataFrame,
                 Portfolio object)
    
    Example:
        >>> summary, returns, vols, factor_exp, factor_risk, portfolio = run_risk_parity_allocation()
        >>> print(summary)
    """
    if selected_assets and len(selected_assets) > 0:
        portfolio = create_custom_portfolio(selected_assets)
    else:
        portfolio = create_default_portfolio()
    
    if use_factor_risk_parity:
        optimizer = FactorRiskParityOptimizer(portfolio)
    else:
        optimizer = RiskParityOptimizer(portfolio)
    
    summary, asset_returns, volatilities, factor_exposures, factor_risk_contributions = optimizer.optimize(
        total_capital, use_cache=use_cache
    )
    
    optimizer.print_summary(summary, total_capital, factor_exposures, factor_risk_contributions)
    
    return summary, asset_returns, volatilities, factor_exposures, factor_risk_contributions, portfolio


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    # Use the new OOP interface with factor-level risk parity
    print("\n" + "="*80)
    print("Running Factor-Level Risk Parity Allocation (OOP Implementation)")
    print("="*80)
    
    summary, returns, vols, factor_exp, factor_risk, portfolio = run_risk_parity_allocation()
    
    # Additional analysis
    print("\n\nDETAILED BREAKDOWN BY CATEGORY:")
    print("="*80)
    
    # Commodities have specific names
    commodity_names = ['Gold', 'Aluminium', 'Copper', 'Crude_Oil']
    commodities = summary[summary['Asset'].isin(commodity_names)]
    bonds = summary[~summary['Asset'].isin(commodity_names)]
    
    print(f"\nBONDS (Total: {bonds['Allocation (CNY)'].sum():,.0f} CNY, {bonds['Weight (%)'].sum():.2f}%):")
    print(bonds.to_string(index=False))
    
    print(f"\nCOMMODITIES (Total: {commodities['Allocation (CNY)'].sum():,.0f} CNY, {commodities['Weight (%)'].sum():.2f}%):")
    print(commodities.to_string(index=False))
    
    print("\n\n" + "="*80)
    print("KEY INSIGHTS:")
    print("="*80)
    print(f"1. Most stable asset (lowest vol): {vols.idxmin()} ({vols.min():.2f}%)")
    print(f"2. Most volatile asset (highest vol): {vols.idxmax()} ({vols.max():.2f}%)")
    print(f"3. Bonds allocation: {bonds['Allocation (CNY)'].sum() / 1e6:.2f} million CNY ({bonds['Weight (%)'].sum():.2f}%)")
    print(f"4. Commodities allocation: {commodities['Allocation (CNY)'].sum() / 1e6:.2f} million CNY ({commodities['Weight (%)'].sum():.2f}%)")
    print("\n5. Individual Allocations (in billions CNY):")
    for idx, row in summary.iterrows():
        print(f"   {row['Asset']:20s}: {row['Allocation (CNY)']/1e6:8.3f} million CNY")
    print("="*80)

