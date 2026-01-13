# -*- coding: utf-8 -*-
"""
Multi-asset portfolio allocation module.

This module provides OOP-based tools for multi-asset portfolio construction
and PCA factor-level risk parity allocation.

Classes:
    - Asset: Base class for all assets
    - BondAsset: Government bond asset
    - CommodityAsset: Commodity futures asset
    - RiskFactorLoader: Loads risk factor data
    - Portfolio: Multi-asset portfolio
    - PCAFactorRiskParityOptimizer: PCA-based factor-level risk parity optimizer

Functions:
    - create_default_portfolio: Create default portfolio configuration
    - run_risk_parity_allocation: Run PCA factor risk parity allocation
    - mappx2rf: Load risk factors (legacy)
    - calculate_risk_parity_allocation: Calculate allocation (legacy)
"""

from multiasset.assets import (
    Asset, BondAsset, CommodityAsset, 
    SlopeSensitiveBondAsset, MultiFactorBondAsset
)
from multiasset.portfolio import Portfolio
from multiasset.risk_loader import RiskFactorLoader
from multiasset.pca_analyzer import PCARiskFactorAnalyzer
from multiasset.factor_optimizer import PCAFactorRiskParityOptimizer

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
    'PCARiskFactorAnalyzer',
    
    # Optimizer classes
    'PCAFactorRiskParityOptimizer',
]

__version__ = '2.0.0'
