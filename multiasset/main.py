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
from typing import List, Dict, Optional

# Ensure parent directory (containing the `factors` package) is on sys.path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from multiasset.retrieve import retrieveFXIRCurves
from multiasset.assets import (
    BondAsset, CommodityAsset, FXAsset, MultiFactorBondAsset, SlopeSensitiveBondAsset,
    MultiFactorCreditAsset, Asset,
)
from multiasset.config import CREDIT_CONFIG
from multiasset.portfolio import Portfolio
from multiasset.risk_loader import RiskFactorLoader
from multiasset.factor_optimizer import FactorRiskParityOptimizer
from multiasset.utils import get_default_sensitivities

def ensure_data() -> None:
    """Fetch FX/IR curves on demand; safe to call multiple times."""
    try:
        retrieveFXIRCurves()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Could not retrieve FX/IR curves: %s", e)

from settings.paths import DIR_INPUT

# ── Hedge instrument catalogue ────────────────────────────────────────────────
# Each entry: name → (instrument_type, cn_tenor_or_none, irs_duration_or_none)
#   IRS_SWAP  – modelled as pure IRDL.CN exposure with given modified duration
#   CGB_BOND  – full MultiFactorBondAsset with CN PCA sensitivities
_HEDGE_INSTRUMENT_DEFS: Dict[str, dict] = {
    'HEDGE_IRS_1Y':  {'type': 'IRS_SWAP', 'duration': 0.95,  'label': '1Y IRS Swap'},
    'HEDGE_IRS_5Y':  {'type': 'IRS_SWAP', 'duration': 4.50,  'label': '5Y IRS Swap'},
    'HEDGE_CGB_10Y': {'type': 'CGB_BOND', 'tenor':   '10Y',  'label': '10Y CGB Bond'},
    'HEDGE_CGB_30Y': {'type': 'CGB_BOND', 'tenor':   '30Y',  'label': '30Y CGB Bond'},
}

# Shared risk factor loader to avoid recomputing PCA on every call
_SHARED_LOADER: Optional[RiskFactorLoader] = None

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
    
    tenors = ['1Y', '2Y', '5Y', '10Y', '20Y', '30Y']
    
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
    Create spread universe (IRS only).

    CDB and ICP tenor instruments moved to create_credit_universe(), which
    exposes them to the correct CRDL/CRSL/CRCV spread-vs-CGB factors instead
    of the outright-yield-level SPDL/SPSL factors this function used to build
    them against. SPDL.CDB/SPDL.ICP remain selectable as standalone factors
    (e.g. for training/vol) but no longer back a tradable instrument here.

    Args:
        analyzer: Optional risk factor analyzer (PCA or deterministic) for computing sensitivities.

    Returns:
        List of Asset objects for spread instruments
    """
    tenors = ['1Y', '2Y', '5Y', '10Y', '30Y']

    spreads: List[Asset] = []
    for tenor in tenors:
        name = f"IRS{tenor}"
        duration = float(tenor.replace('Y', ''))

        # Spread instruments use SPDL (level) and SPSL (slope).
        # Model them like bonds: price return ≈ -duration × Δ(spread).
        level_factor = 'SPDL.IRS'
        slope_factor = 'SPSL.IRS'
        # SPSL sign convention matches IRSL: short-end positive, belly zero, long-end negative
        # (spread slope factor rises → short-end spreads widen, long-end spreads tighten)
        slope_mag = max(duration * 0.5, 0.5)
        if duration <= 2.0:
            signed_slope = slope_mag            # short-end: positive
        elif duration <= 5.0:
            signed_slope = 0.0                  # belly: neutral
        else:
            signed_slope = -min(slope_mag, 3.0) # long-end: negative, capped
        spreads.append(
            SlopeSensitiveBondAsset(
                name=name,
                level_factor=level_factor,
                slope_factor=slope_factor,
                duration=duration,
                slope_sensitivity=signed_slope,
            )
        )

    return spreads


def create_credit_universe(analyzer=None) -> List[MultiFactorCreditAsset]:
    """
    Create credit spread universe (CDB, LGB, MTN, ICP).

    Each instrument is the own-yield-minus-CGB spread at a given tenor
    (see multiasset.config.CREDIT_CONFIG), with CRDL/CRSL/CRCV exposure
    derived from the same tenor-aware weights the factor levels are
    computed from (multiasset.pca_analyzer.get_credit_weights), unlike
    the IR universe's fixed 5-tenor grid.

    Args:
        analyzer: Optional DeterministicRiskFactorAnalyzer for computing
                  CRDL/CRSL/CRCV sensitivities. If not provided, instruments
                  fall back to a Level-only exposure of -duration.

    Returns:
        List of MultiFactorCreditAsset objects for all credit universes and tenors.
    """
    credit: List[MultiFactorCreditAsset] = []
    for universe, (_, _, tenor_cols) in CREDIT_CONFIG.items():
        for _, _, tenor_years in tenor_cols:
            tenor = f"{tenor_years:g}Y"
            sector = {'0.25Y': '3M', '0.5Y': '6M', '0.75Y': '9M'}.get(tenor, tenor)
            name = f"{universe}{sector}"

            duration = get_default_sensitivities(sector).get('IRDL', 5.0)
            sensitivities = None
            if analyzer is not None:
                sensitivities = analyzer.get_credit_tenor_sensitivities(universe, tenor)

            credit.append(
                MultiFactorCreditAsset(
                    name=name,
                    universe=universe,
                    tenor=sector,
                    duration=duration,
                    credit_sensitivities=sensitivities,
                )
            )

    return credit


def create_hedge_instruments(hedge_names: List[str], analyzer=None) -> List[Asset]:
    """
    Create hedge instrument assets from the predefined catalogue.

    Hedge instruments are added to the portfolio with short-allowed bounds in the
    optimizer so the solver can short them to offset specific factor exposures.

    Args:
        hedge_names: List of names from _HEDGE_INSTRUMENT_DEFS
            (e.g. ['HEDGE_IRS_1Y', 'HEDGE_CGB_10Y'])
        analyzer: Optional risk-factor analyzer; passed to MultiFactorBondAsset
            for PCA-derived CN sensitivities.

    Returns:
        List of Asset objects for use in Portfolio and FactorRiskParityOptimizer.
    """
    instruments: List[Asset] = []
    for name in hedge_names:
        defn = _HEDGE_INSTRUMENT_DEFS.get(name)
        if defn is None:
            print(f"Warning: unknown hedge instrument '{name}', skipping")
            continue
        if defn['type'] == 'IRS_SWAP':
            # Model IRS as a plain-vanilla rate exposure: price ≈ −duration × Δ(IRDL.CN)
            asset: Asset = BondAsset(
                name=name,
                factor='IRDL.CN',
                duration=defn['duration'],
            )
        else:  # CGB_BOND
            sensitivities = None
            if analyzer is not None:
                raw = analyzer.get_tenor_sensitivities('CN', defn['tenor'])
                if raw:
                    defaults = get_default_sensitivities(defn['tenor'])
                    duration = defaults.get('IRDL', 5.0)
                    sensitivities = {k: -duration * v for k, v in raw.items()}
            asset = MultiFactorBondAsset(
                name=name,
                country='CN',
                tenor=defn['tenor'],
                sensitivities=None,
                pca_sensitivities=sensitivities,
            )
        instruments.append(asset)
    return instruments


def create_commodity_universe() -> List[CommodityAsset]:
    """
    Create commodity universe.

    Returns:
        List of CommodityAsset objects
    """
    commodities: List[CommodityAsset] = [
        CommodityAsset(name='Gold', factor='CMDL.AU'),
        CommodityAsset(name='Silver', factor='CMDL.AG'),
        CommodityAsset(name='Aluminium', factor='CMDL.AL'),
        CommodityAsset(name='Copper', factor='CMDL.CU'),
        CommodityAsset(name='Zinc', factor='CMDL.ZN'),
        CommodityAsset(name='Crude_Oil', factor='CMDL.SC'),
    ]

    return commodities


def create_fx_universe() -> List[FXAsset]:
    """
    Create FX spot rate universe.

    Returns:
        List of FXAsset objects
    """
    from multiasset.assets import FXAsset

    fx_pairs: List[FXAsset] = [
        FXAsset(name='USDCNY', factor='FXDL.USDCNY'),
        FXAsset(name='EURCNY', factor='FXDL.EURCNY'),
        FXAsset(name='JPYCNY', factor='FXDL.JPYCNY'),
        FXAsset(name='GBPCNY', factor='FXDL.GBPCNY'),
    ]

    return fx_pairs


def create_default_portfolio(use_cache: bool = True, use_deterministic: bool = True) -> Portfolio:
    """
    Create the default multi-asset portfolio with comprehensive bond universe.
    
    Includes:
    - 25 bonds (5 countries × 5 tenors) with multi-factor sensitivities
    - 15 spreads (3 types × 5 tenors)
    - 4 commodities
    
    Args:
        use_cache: Whether to use cached factor-model calculations (default: True)
        use_deterministic: If True, use deterministic factors; if False, use PCA-derived factors
    
    Returns:
        Portfolio with default assets configured
    """
    # Use shared loader to avoid recomputing factor-model inputs
    loader = _get_shared_loader(use_deterministic=use_deterministic)
    
    # Trigger factor calculation to get sensitivities
    loader.load_risk_factors(use_cache=use_cache)
    
    # Select the appropriate analyzer based on configuration
    analyzer = loader.det_analyzer if loader.use_deterministic else loader.factor_analyzer
    
    # Create comprehensive bond universe with derived sensitivities
    bonds = create_bond_universe(analyzer=analyzer)

    # Create spread universe
    spreads = create_spread_universe(analyzer=analyzer)

    # Create credit spread universe (CDB/LGB/MTN/ICP vs CGB)
    credit = create_credit_universe(analyzer=analyzer)

    # Create commodity universe
    commodities = create_commodity_universe()

    # Combine all assets
    assets: List[Asset] = bonds + spreads + credit + commodities  # type: ignore
    
    # Create portfolio
    portfolio = Portfolio(assets, loader)
    
    return portfolio


def create_custom_portfolio(selected_asset_names: List[str], use_cache: bool = True,
                            use_deterministic: bool = True,
                            hedge_asset_names: List[str] = None) -> Portfolio:
    """
    Create a custom portfolio based on a list of asset names.

    Args:
        selected_asset_names: List of asset names to include
        use_cache: Whether to use cached factor-model calculations (default: True)
        use_deterministic: If True, use deterministic factors; if False, use PCA-derived factors
        hedge_asset_names: Optional list of hedge instrument names from _HEDGE_INSTRUMENT_DEFS

    Returns:
        Portfolio with selected assets (and hedge instruments when provided)
    """
    loader = _get_shared_loader(use_deterministic=use_deterministic)
    loader.load_risk_factors(use_cache=use_cache)
    analyzer = loader.det_analyzer if loader.use_deterministic else loader.factor_analyzer

    all_bonds = create_bond_universe(analyzer=analyzer)
    all_spreads = create_spread_universe(analyzer=analyzer)
    all_credit = create_credit_universe(analyzer=analyzer)
    all_commodities = create_commodity_universe()
    all_fx = create_fx_universe()
    all_possible_assets = all_bonds + all_spreads + all_credit + all_commodities + all_fx  # type: ignore

    _seen: set = set()
    selected_assets = []
    for asset in all_possible_assets:
        if asset.name in selected_asset_names and asset.name not in _seen:
            selected_assets.append(asset)
            _seen.add(asset.name)

    if not selected_assets:
        print("Warning: No valid assets found matching the selection. Using default portfolio.")
        return create_default_portfolio()

    # Append hedge instruments (duplicates filtered by name)
    if hedge_asset_names:
        existing_names = {a.name for a in selected_assets}
        hedges = create_hedge_instruments(
            [n for n in hedge_asset_names if n not in existing_names],
            analyzer=analyzer,
        )
        selected_assets = selected_assets + hedges  # type: ignore

    return Portfolio(selected_assets, loader)


def run_risk_parity_allocation(total_capital: float = 10_000_000_000,
                                use_cache: bool = True,
                                selected_assets: List[str] = None,
                                risk_budgets: Optional[Dict[str, float]] = None,
                                use_deterministic: bool = True,
                                hedge_asset_names: List[str] = None,
                                neutral_asset_names: List[str] = None) -> tuple:
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
    if selected_assets and len(selected_assets) > 0:
        portfolio = create_custom_portfolio(
            selected_assets,
            use_cache=use_cache,
            use_deterministic=use_deterministic,
            hedge_asset_names=hedge_asset_names,
        )
    else:
        portfolio = create_default_portfolio(use_cache=use_cache, use_deterministic=use_deterministic)

    optimizer = FactorRiskParityOptimizer(portfolio=portfolio, input_dir=str(DIR_INPUT))

    summary, asset_returns, volatilities, factor_exposures, factor_risk_contributions = optimizer.optimize(
        total_capital, use_cache=use_cache, risk_budgets=risk_budgets,
        hedge_asset_names=hedge_asset_names,
        neutral_asset_names=neutral_asset_names,
    )

    optimizer.print_summary(summary, total_capital, factor_exposures, factor_risk_contributions)

    return summary, asset_returns, volatilities, factor_exposures, factor_risk_contributions, portfolio


# =============================================================================
# IRDL HEDGE OVERLAY
# =============================================================================

# Default DV01 (CNY per basis-point) per contract for each country's bond futures.
# CGB: T (10Y) contract on CFFEX ≈ 800 CNY/bp; TF (5Y) ≈ 450 CNY/bp.
# These are approximations; override via the UI.
_DEFAULT_FUTURES_DV01: Dict[str, float] = {
    'CN': 800.0,    # CFFEX T (10Y CGB futures)
    'US': 640.0,    # CBOT ZN (10Y UST futures, ~$64 per bp)
    'DE': 750.0,    # Eurex Bund futures (~€75 per bp ≈ 750 CNY at ~10 USDCNY)
    'JP': 560.0,    # TSE JGB futures (~¥56,000/bp at ~100 JPYCNY)
    'UK': 600.0,    # ICE Long Gilt futures (~£60/bp)
}

# IRS DV01 per 1 million CNY notional, by maturity.
# Approximation: modified_duration × 1_000_000 / 10_000
_DEFAULT_IRS_DV01_PER_1M: Dict[str, float] = {
    '2Y':  180.0,   # ~1.8Y duration × 1M / 10k
    '5Y':  440.0,   # ~4.4Y duration
    '10Y': 840.0,   # ~8.4Y duration
    '30Y': 1800.0,  # ~18Y duration
}


def compute_irdl_hedge(
    factor_risk_records: List[Dict],
    total_capital: float,
    hedge_ratio: float = 1.0,
    instrument: str = 'futures',
    dv01_overrides: Dict[str, float] = None,
    irs_maturity: str = '10Y',
) -> List[Dict]:
    """
    Compute an optional IRDL hedge overlay on top of the RP allocation.

    This is a post-optimisation overlay — it does NOT change portfolio weights.
    It answers: "given the portfolio's net IRDL exposure, how many futures contracts
    (or how much IRS notional) do we need to short/pay-fixed to reduce duration risk?"

    Args:
        factor_risk_records: factor_risk.to_dict('records') from optimizer output.
            Must contain 'Risk Factor' and 'Net Exposure' fields.
        total_capital: Portfolio total capital in CNY.
        hedge_ratio: 0.0–1.0.  1.0 = fully neutralise IRDL per country.
        instrument: 'futures' → bond futures contracts; 'irs' → pay-fixed IRS notional.
        dv01_overrides: Override default DV01 per country (for futures) or per maturity (for IRS).
        irs_maturity: IRS tenor to use when instrument='irs' (default '10Y').

    Returns:
        List of dicts with keys:
          Country, Net IRDL Exp, Port DV01 (CNY/bp), Hedge DV01 (CNY/bp),
          Contracts / IRS Notional (M CNY), Direction, Instrument
    """
    dv01_map = dict(_DEFAULT_FUTURES_DV01)
    if dv01_overrides:
        dv01_map.update(dv01_overrides)

    irs_dv01 = (_DEFAULT_IRS_DV01_PER_1M.get(irs_maturity, 840.0)
                if instrument == 'irs'
                else None)

    tickets = []
    for row in factor_risk_records:
        factor = row.get('Risk Factor', '')
        if not factor.startswith('IRDL.'):
            continue
        country = factor.split('.')[1]
        net_exp = float(row.get('Net Exposure', 0.0))
        if net_exp == 0.0:
            continue

        # Portfolio DV01: how many CNY/bp does the portfolio gain/lose on this factor
        # net_exp is in duration-years; total_capital / 10_000 converts to CNY-per-bp
        port_dv01 = net_exp * total_capital / 10_000.0   # CNY per bp

        # Hedge size targets net_exp → (1 - hedge_ratio) × net_exp
        hedge_dv01 = -port_dv01 * hedge_ratio            # negative = short / pay-fixed

        if instrument == 'futures':
            fv = dv01_map.get(country, 800.0)
            qty = hedge_dv01 / fv                         # contracts (negative = short)
            qty_label = f"{int(round(qty)):+d} contracts"
            direction = 'SHORT' if qty < 0 else 'LONG'
        else:
            # IRS: notional in millions CNY
            notional_m = hedge_dv01 / irs_dv01 if irs_dv01 else 0.0
            qty = notional_m
            qty_label = f"{notional_m:+,.1f} M CNY"
            direction = 'PAY FIXED' if notional_m < 0 else 'RCV FIXED'

        tickets.append({
            'Country':              country,
            'Net IRDL Exp (DY)':    round(net_exp, 4),
            'Port DV01 (CNY/bp)':   round(port_dv01),
            'Hedge DV01 (CNY/bp)':  round(hedge_dv01),
            'Quantity':             qty_label,
            'Direction':            direction,
            'Instrument':           (f'{country} Bond Futures'
                                     if instrument == 'futures'
                                     else f'{irs_maturity} IRS'),
        })
    return tickets


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

