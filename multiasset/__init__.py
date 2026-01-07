# -*- coding: utf-8 -*-
"""
Multi-asset portfolio allocation module.

This module provides OOP-based tools for multi-asset portfolio construction
and risk parity allocation.

Classes:
    - Asset: Base class for all assets
    - BondAsset: Government bond asset
    - CommodityAsset: Commodity futures asset
    - RiskFactorLoader: Loads risk factor data
    - Portfolio: Multi-asset portfolio
    - RiskParityOptimizer: Risk parity allocation optimizer

Functions:
    - create_default_portfolio: Create default portfolio configuration
    - run_risk_parity_allocation: Run risk parity allocation
    - mappx2rf: Load risk factors (legacy)
    - calculate_risk_parity_allocation: Calculate allocation (legacy)
"""

from multiasset.assets import (
    Asset, BondAsset, CommodityAsset, 
    SlopeSensitiveBondAsset, MultiFactorBondAsset
)
from multiasset.portfolio import Portfolio, RiskFactorLoader
from multiasset.optimizer import RiskParityOptimizer, AdvancedRiskParityOptimizer

__all__ = [
    # Asset classes
    'Asset',
    'BondAsset',
    'CommodityAsset',
    'SlopeSensitiveBondAsset',
    'MultiFactorBondAsset',
    
    # Portfolio classes
    'Portfolio',
    'RiskFactorLoader',
    
    # Optimizer classes
    'RiskParityOptimizer',
    'AdvancedRiskParityOptimizer',
]

__version__ = '2.0.0'
