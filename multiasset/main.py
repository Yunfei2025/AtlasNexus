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
from typing import List, Dict

# Ensure parent directory (containing the `factors` package) is on sys.path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from multiasset.retrieve import retrieveFXIRCurves
from multiasset.assets import BondAsset, CommodityAsset, MultiFactorBondAsset, SlopeSensitiveBondAsset, Asset
from multiasset.portfolio import Portfolio
from multiasset.risk_loader import RiskFactorLoader
from multiasset.factor_optimizer import PCAFactorRiskParityOptimizer
from multiasset.utils import get_default_sensitivities

try:
    retrieveFXIRCurves()
except Exception as e:
    print(f"Warning: Could not retrieve FX/IR curves: {e}")

from settings.paths import DIR_INPUT

# Shared risk factor loader to avoid recomputing PCA on every call
_SHARED_LOADER: RiskFactorLoader | None = None

def _get_shared_loader(use_deterministic: bool = True) -> RiskFactorLoader:
    """Get or create the shared RiskFactorLoader instance."""
    global _SHARED_LOADER
    if _SHARED_LOADER is None or _SHARED_LOADER.use_deterministic != use_deterministic:
        _SHARED_LOADER = RiskFactorLoader(DIR_INPUT, use_deterministic=use_deterministic)
    return _SHARED_LOADER


def create_bond_universe(analyzer=None) -> List[MultiFactorBondAsset]:
    """
    Create comprehensive bond universe with multiple tenors.
    
    Args:
        analyzer: Optional risk factor analyzer (PCA or deterministic) for computing sensitivities.
                  If provided, sensitivities will be derived from the analyzer.
    
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
            
            # Get sensitivities if analyzer is available
            sensitivities = None
            if analyzer is not None:
                sensitivities = analyzer.get_tenor_sensitivities(rf_country, tenor)
                if sensitivities:
                    # Multiply by duration to get value sensitivity
                    # Loading gives yield change per factor unit
                    # Value change = -duration × yield change
                    defaults = get_default_sensitivities(tenor)
                    duration = defaults.get('IRDL', 5.0)
                    sensitivities = {
                        k: -duration * v for k, v in sensitivities.items()
                    }
            
            bond = MultiFactorBondAsset(
                name=name,
                country=rf_country,  # Use risk factor country code
                tenor=tenor,
                sensitivities=None,  # Use defaults for duration
                pca_sensitivities=sensitivities  # Derived sensitivities
            )
            bonds.append(bond)
    
    return bonds


def create_spread_universe(analyzer=None) -> List[Asset]:
    """
    Create spread universe (IRS, CDB, ICP).
    
    Args:
        analyzer: Optional risk factor analyzer (PCA or deterministic) for computing sensitivities.
    
    Returns:
        List of Asset objects for spread instruments
    """
    spread_types = {
        'IRS': 'IRS',    # Interest Rate Swap
        'CDB': 'CDB',    # China Development Bond
        'ICP': 'ICP'     # Interbank Commercial Paper
    }
    
    tenors = ['1Y', '2Y', '5Y', '10Y', '30Y']
    
    spreads: List[Asset] = []
    for spread_code, spread_name in spread_types.items():
        for tenor in tenors:
            name = f"{spread_code}{tenor}"

            duration = float(tenor.replace('Y', ''))

            # Spread instruments use SPDL (level) and optionally SPSL (slope).
            # Model them like bonds: price return ≈ -duration × Δ(spread).
            level_factor = f'SPDL.{spread_code}'

            if spread_code != 'ICP':
                slope_factor = f'SPSL.{spread_code}'
                spreads.append(
                    SlopeSensitiveBondAsset(
                        name=name,
                        level_factor=level_factor,
                        slope_factor=slope_factor,
                        duration=duration,
                        slope_sensitivity=max(duration * 0.5, 0.5),
                    )
                )
            else:
                spreads.append(
                    BondAsset(
                        name=name,
                        factor=level_factor,
                        duration=duration,
                    )
                )
    
    return spreads


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


def create_default_portfolio(use_cache: bool = True, use_deterministic: bool = True) -> Portfolio:
    """
    Create the default multi-asset portfolio with comprehensive bond universe.
    
    Includes:
    - 25 bonds (5 countries × 5 tenors) with multi-factor sensitivities
    - 15 spreads (3 types × 5 tenors)
    - 4 commodities
    
    Args:
        use_cache: Whether to use cached PCA calculations (default: True)
        use_deterministic: If True, use deterministic factors; if False, use PCA
    
    Returns:
        Portfolio with default assets configured
    """
    # Use shared loader to avoid recomputing PCA
    loader = _get_shared_loader(use_deterministic=use_deterministic)
    
    # Trigger PCA/deterministic calculation to get sensitivities
    loader.load_risk_factors(use_cache=use_cache)
    
    # Select the appropriate analyzer based on configuration
    analyzer = loader.det_analyzer if loader.use_deterministic else loader.pca_analyzer
    
    # Create comprehensive bond universe with derived sensitivities
    bonds = create_bond_universe(analyzer=analyzer)
    
    # Create spread universe
    spreads = create_spread_universe(analyzer=analyzer)
    
    # Create commodity universe
    commodities = create_commodity_universe()
    
    # Combine all assets
    assets: List[Asset] = bonds + spreads + commodities  # type: ignore
    
    # Create portfolio
    portfolio = Portfolio(assets, loader)
    
    return portfolio


def create_custom_portfolio(selected_asset_names: List[str], use_cache: bool = True, use_deterministic: bool = True) -> Portfolio:
    """
    Create a custom portfolio based on a list of asset names.
    
    Args:
        selected_asset_names: List of asset names to include
        use_cache: Whether to use cached PCA calculations (default: True)
        use_deterministic: If True, use deterministic factors; if False, use PCA
        
    Returns:
        Portfolio with only the selected assets
    """
    # Use shared loader to avoid recomputing PCA
    loader = _get_shared_loader(use_deterministic=use_deterministic)
    
    # Trigger PCA/deterministic calculation to get sensitivities
    loader.load_risk_factors(use_cache=use_cache)
    
    # Select the appropriate analyzer based on configuration
    analyzer = loader.det_analyzer if loader.use_deterministic else loader.pca_analyzer
    
    # Generate all possible assets with derived sensitivities
    all_bonds = create_bond_universe(analyzer=analyzer)
    all_spreads = create_spread_universe(analyzer=analyzer)
    all_commodities = create_commodity_universe()
    all_possible_assets = all_bonds + all_spreads + all_commodities # type: ignore
    
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


def run_risk_parity_allocation(total_capital: float = 10_000_000_000,
                                use_cache: bool = True,
                                selected_assets: List[str] = None,
                                risk_budgets: Dict[str, float] | None = None,
                                use_deterministic: bool = True) -> tuple:
    """
    Run factor-level risk parity allocation using OOP interface.
    
    Args:
        total_capital: Total capital to allocate (default: 10 billion CNY)
        use_cache: Whether to use cached calculations for performance
        selected_assets: Optional list of asset names to include in the portfolio.
        risk_budgets: Optional dictionary of risk budgets per factor
        use_deterministic: If True, use deterministic factors; if False, use PCA
    
    Returns:
        Tuple of (summary DataFrame, asset returns DataFrame, volatilities Series,
                 factor exposures DataFrame, factor risk contributions DataFrame,
                 Portfolio object)
    """
    print(f"[DEBUG] Starting run_risk_parity_allocation with {len(selected_assets) if selected_assets else 0} assets")
    if selected_assets and len(selected_assets) > 0:
        print(f"[DEBUG] Creating custom portfolio for: {selected_assets}")
        portfolio = create_custom_portfolio(selected_assets, use_cache=use_cache, use_deterministic=use_deterministic)
    else:
        print("[DEBUG] Creating default portfolio")
        portfolio = create_default_portfolio(use_cache=use_cache, use_deterministic=use_deterministic)
    
    print(f"[DEBUG] Portfolio created with {len(portfolio.assets)} assets")
    print("[DEBUG] Creating optimizer...")
    optimizer = PCAFactorRiskParityOptimizer(portfolio=portfolio, input_dir=str(DIR_INPUT))
    
    print("[DEBUG] Running optimization...")
    summary, asset_returns, volatilities, factor_exposures, factor_risk_contributions = optimizer.optimize(
        total_capital, use_cache=use_cache, risk_budgets=risk_budgets
    )
    
    print("[DEBUG] Optimization complete")
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

