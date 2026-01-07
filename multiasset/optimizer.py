# -*- coding: utf-8 -*-
"""
Risk parity optimizer for portfolio allocation.
"""
import pandas as pd
import numpy as np
from typing import Optional, Tuple
from multiasset.portfolio import Portfolio


class RiskParityOptimizer:
    """
    Optimizer that allocates capital using risk parity methodology.
    
    Risk parity ensures each asset contributes equally to total portfolio risk
    by allocating weights inversely proportional to volatility.
    """
    
    def __init__(self, portfolio: Portfolio):
        """
        Initialize the optimizer.
        
        Args:
            portfolio: Portfolio instance
        """
        self.portfolio = portfolio
        self._weights: Optional[pd.Series] = None
        self._allocations: Optional[pd.Series] = None
    
    def calculate_weights(self, use_cache: bool = True) -> pd.Series:
        """
        Calculate risk parity weights.
        
        Weights are inversely proportional to volatility:
        w_i ∝ 1/σ_i, normalized so Σw_i = 1
        
        Args:
            use_cache: Whether to use cached calculations
            
        Returns:
            Series of portfolio weights
        """
        if use_cache and self._weights is not None:
            return self._weights
        
        volatilities = self.portfolio.calculate_volatilities(use_cache=use_cache)
        
        # Inverse volatility weighting
        inv_vol = 1.0 / volatilities
        weights = inv_vol / inv_vol.sum()
        
        self._weights = weights
        return weights
    
    def allocate_capital(self, total_capital: float, 
                         use_cache: bool = True) -> pd.Series:
        """
        Allocate capital using risk parity.
        
        Args:
            total_capital: Total capital to allocate
            use_cache: Whether to use cached calculations
            
        Returns:
            Series of capital allocations by asset
        """
        weights = self.calculate_weights(use_cache=use_cache)
        allocations = weights * total_capital
        
        self._allocations = allocations
        return allocations
    
    def calculate_risk_contributions(self, use_cache: bool = True) -> pd.Series:
        """
        Calculate risk contribution of each asset.
        
        For risk parity, all assets should contribute equally to total risk.
        Risk contribution = weight × volatility / (Σ weight × volatility)
        
        Args:
            use_cache: Whether to use cached calculations
            
        Returns:
            Series of risk contributions (in %)
        """
        weights = self.calculate_weights(use_cache=use_cache)
        volatilities = self.portfolio.calculate_volatilities(use_cache=use_cache)
        
        risk_contributions = weights * volatilities
        risk_contributions_pct = (risk_contributions / risk_contributions.sum()) * 100
        
        return risk_contributions_pct
    
    def optimize(self, total_capital: float, 
                 use_cache: bool = True) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame]:
        """
        Run full optimization and return comprehensive results.
        
        Args:
            total_capital: Total capital to allocate
            use_cache: Whether to use cached calculations
            
        Returns:
            Tuple of (summary DataFrame, asset returns DataFrame, volatilities Series,
                     factor exposures DataFrame, factor risk contributions DataFrame)
        """
        # Calculate all metrics
        weights = self.calculate_weights(use_cache=use_cache)
        allocations = self.allocate_capital(total_capital, use_cache=use_cache)
        volatilities = self.portfolio.calculate_volatilities(use_cache=use_cache)
        risk_contributions = self.calculate_risk_contributions(use_cache=use_cache)
        asset_returns = self.portfolio.calculate_asset_returns(use_cache=use_cache)
        
        # Calculate factor-level exposures and risk contributions
        factor_exposures = self.portfolio.calculate_factor_exposures(weights)
        factor_risk_contributions = self.portfolio.calculate_factor_risk_contributions(weights, use_cache=use_cache)
        
        # Create summary DataFrame
        summary = pd.DataFrame({
            'Asset': allocations.index,
            'Weight (%)': weights.values * 100,
            'Allocation (CNY)': allocations.values,
            'Volatility (% ann.)': volatilities.values,
            'Risk Contribution (%)': risk_contributions.values
        })
        
        return summary, asset_returns, volatilities, factor_exposures, factor_risk_contributions
    
    def print_summary(self, summary: pd.DataFrame, total_capital: float,
                     factor_exposures: Optional[pd.DataFrame] = None,
                     factor_risk_contributions: Optional[pd.DataFrame] = None):
        """
        Print allocation summary with factor exposures.
        
        Args:
            summary: Summary DataFrame from optimize()
            total_capital: Total capital allocated
            factor_exposures: DataFrame of factor exposures
            factor_risk_contributions: DataFrame of factor risk contributions
        """
        print("\n" + "="*80)
        print(f"RISK PARITY ALLOCATION - Total Capital: {total_capital:,.0f} CNY")
        print("="*80)
        print(summary.to_string(index=False))
        print("="*80)
        print(f"\nVerification - Total Allocated: {summary['Allocation (CNY)'].sum():,.0f} CNY")
        print(f"Risk Contributions should be equal (all ~{100/len(summary):.1f}%)")
        print("="*80)
        
        if factor_exposures is not None:
            print("\n" + "="*80)
            print("PORTFOLIO FACTOR EXPOSURES (Weighted Sensitivities)")
            print("="*80)
            print(factor_exposures.to_string(index=False))
            print("="*80)
        
        if factor_risk_contributions is not None:
            print("\n" + "="*80)
            print("RISK CONTRIBUTION BY FACTOR")
            print("="*80)
            print(factor_risk_contributions.to_string(index=False))
            print("="*80)
    
    def clear_cache(self):
        """Clear cached optimization results."""
        self._weights = None
        self._allocations = None
        self.portfolio.clear_cache()


class AdvancedRiskParityOptimizer(RiskParityOptimizer):
    """
    Advanced optimizer with additional constraints and methods.
    
    Future extensions could include:
    - Minimum/maximum weight constraints
    - Correlation-adjusted risk parity
    - Transaction cost awareness
    - Rebalancing optimization
    """
    
    def __init__(self, portfolio: Portfolio, 
                 min_weight: float = 0.0, 
                 max_weight: float = 1.0):
        """
        Initialize advanced optimizer.
        
        Args:
            portfolio: Portfolio instance
            min_weight: Minimum weight per asset (default: 0%)
            max_weight: Maximum weight per asset (default: 100%)
        """
        super().__init__(portfolio)
        self.min_weight = min_weight
        self.max_weight = max_weight
    
    def calculate_weights(self, use_cache: bool = True) -> pd.Series:
        """
        Calculate risk parity weights with constraints.
        
        Args:
            use_cache: Whether to use cached calculations
            
        Returns:
            Series of constrained portfolio weights
        """
        # Get unconstrained weights
        weights = super().calculate_weights(use_cache=use_cache)
        
        # Apply constraints (simple clipping, could be improved with optimization)
        weights = weights.clip(lower=self.min_weight, upper=self.max_weight)
        
        # Renormalize
        weights = weights / weights.sum()
        
        self._weights = weights
        return weights
