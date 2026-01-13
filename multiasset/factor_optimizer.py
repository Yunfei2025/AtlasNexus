# -*- coding: utf-8 -*-
"""
Factor-level risk parity optimizer.

This optimizer allocates capital so that each risk factor contributes 
equally to total portfolio risk, rather than each asset.
"""
import pandas as pd
import numpy as np
from typing import Optional, Tuple, Dict
from scipy.optimize import minimize
from multiasset.portfolio import Portfolio
from multiasset.pca_analyzer import PCARiskFactorAnalyzer
from dateutil.relativedelta import relativedelta
# Prefer local config in multiasset; fallback to settings if not available
from .config import RiskModelConfig  # type: ignore


class PCAFactorRiskParityOptimizer:
    """
    Optimizer using PCA-derived risk factors for factor risk parity.
    
    At each rebalance date:
    1. Run PCA on each country's yield curve (past 1 year of data)
    2. Define IRDL (level), IRSL (slope), IRCV (curvature) as PC1, PC2, PC3
    3. Calculate factor volatilities using EWMA
    4. Optimize portfolio weights for equal factor risk contribution
    """
    
    def __init__(self, portfolio: Portfolio, input_dir: str,
                 pca_lookback_years: float = 1.0,
                 vol_lookback_months: int = 3,
                 ewma_lambda: float = 0.94):
        """
        Initialize the PCA-based factor risk parity optimizer.
        
        Args:
            portfolio: Portfolio instance
            input_dir: Directory containing yield curve data
            pca_lookback_years: Years of data for PCA fitting
            vol_lookback_months: Months of data for EWMA volatility
            ewma_lambda: EWMA decay parameter
        """
        self.portfolio = portfolio
        self.input_dir = input_dir
        self.pca_analyzer = PCARiskFactorAnalyzer(input_dir, pca_lookback_years)
        self.vol_lookback_months = vol_lookback_months
        self.ewma_lambda = ewma_lambda
        self._weights: Optional[pd.Series] = None
        self._pca_factor_vols: Optional[pd.Series] = None
    
    def fit_and_calculate(self, rebalance_date: pd.Timestamp,
                          risk_budgets: Optional[Dict[str, float]] = None,
                          total_capital: float = 1.0) -> Tuple[pd.Series, pd.Series]:
        """
        Fit PCA and calculate optimal weights for a given rebalance date.
        
        Args:
            rebalance_date: Date at which to rebalance
            risk_budgets: Optional dictionary mapping factor names to risk budgets
            total_capital: Total capital for absolute risk budget calculation
            
        Returns:
            Tuple of (weights Series, factor volatilities Series)
        """
        # 1. Fit PCA for each country
        pca_results = self.pca_analyzer.fit_pca(rebalance_date, n_components=3)
        
        # 2. Calculate PCA factor returns
        vol_start = rebalance_date - relativedelta(months=self.vol_lookback_months)
        pca_factor_returns = self.pca_analyzer.calculate_pca_factor_returns(
            start_date=vol_start,
            end_date=rebalance_date
        )
        
        # 3. Calculate factor volatilities using EWMA
        factor_vols = self._calculate_ewma_volatilities(pca_factor_returns)
        self._pca_factor_vols = factor_vols
        
        # 4. Build exposure matrix and optimize
        weights = self._optimize_weights(factor_vols, risk_budgets=risk_budgets, total_capital=total_capital)
        self._weights = weights
        
        return weights, factor_vols
    
    def _calculate_ewma_volatilities(self, factor_returns: pd.DataFrame) -> pd.Series:
        """
        Calculate EWMA volatilities for PCA factors.
        
        Args:
            factor_returns: DataFrame of PCA factor returns
            
        Returns:
            Series of annualized volatilities by factor
        """
        factor_vols = {}
        alpha = 1.0 - self.ewma_lambda
        
        for col in factor_returns.columns:
            returns = factor_returns[col].dropna()
            
            if len(returns) < 5:
                factor_vols[col] = float('nan')
                continue
            
            # EWMA variance
            ewma_var = returns.ewm(alpha=alpha, adjust=False).var()
            
            # Use latest EWMA variance, annualize (sqrt(252))
            latest_vol = np.sqrt(ewma_var.iloc[-1]) * np.sqrt(252)
            factor_vols[col] = latest_vol
        
        return pd.Series(factor_vols)
    
    def _optimize_weights(self, factor_vols: pd.Series,
                          risk_budgets: Optional[Dict[str, float]] = None,
                          total_capital: float = 1.0) -> pd.Series:
        """
        Optimize portfolio weights using factor risk parity or risk budgeting.
        
        Args:
            factor_vols: Series of factor volatilities
            risk_budgets: Optional dictionary of risk budgets per factor (in million CNY units)
            total_capital: Total capital to allocate (absolute units)
            
        Returns:
            Series of optimal weights
        """
        # Get asset-factor exposure matrix
        exposure_matrix, asset_names, factor_names = self._build_exposure_matrix(factor_vols)
        
        if exposure_matrix.empty:
            # Fall back to equal weights
            return pd.Series(1.0/len(self.portfolio.assets), 
                           index=list(self.portfolio.assets.keys()))
        
        B = exposure_matrix.values
        sigma_f = np.array([factor_vols.get(f, 0) for f in factor_names])
        
        # Remove factors with zero or nan volatility
        valid_mask = ~np.isnan(sigma_f) & (sigma_f > 0)
        B = B[:, valid_mask]
        sigma_f = sigma_f[valid_mask]
        
        if len(sigma_f) == 0:
            return pd.Series(1.0/len(asset_names), index=asset_names)
            
        filtered_factor_names = [f for i, f in enumerate(factor_names) if valid_mask[i]]
        n_assets = len(asset_names)
        
        # --- Define Risk Budgets ---
        constraints = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}]
        
        if risk_budgets:
            # Absolute Risk Budgeting logic:
            # 1. Convert budgets (inputs in Millions) to fractional risk of portfolio capital
            #    BudgetFraction = (Value_Million * 1e6) / Total_Capital
            #    If Capital=100M, Budget=1M -> Fraction = 0.01 (1%)
            #    This compares directly with Factor Risk Contribution (approx Factor Vol * Exposure)
        
            # Default to very small budget (effectively zero) if factor present but not budgeted?
            # Or very large (unconstrained)? "Risk Budgeting" implies explicit allocation.
            # We'll use 0.0001 (small non-zero) for missing, assuming user intended to exclude.
            
            budget_targets = []
            for f in filtered_factor_names:
                user_val = risk_budgets.get(f, 0.0) 
                # Convert '1 unit is million' -> absolute value -> fraction of capital
                # Note: Factor Risk Contribution here is in Volatility units (e.g. 0.05).
                # User budget = 1M (VaR/Vol?).
                # If User budget is 1M (Absolute Volatility in Currency), and Capital is 100M.
                # Target Vol = 1M/100M = 0.01 (1%).
                
                # Check for zero capital edge case
                if total_capital > 1e-6:
                    target_vol = (user_val * 1_000_000.0) / total_capital
                else:
                    target_vol = 1.0 # Fallback
                
                budget_targets.append(target_vol)
            
            budget_targets = np.array(budget_targets)
            
            # Objective: Minimize squared distance between Risk Contribution and Target
            # Also enforces 'risk_budgets should be a maximum' via inequality constraint
            
            def objective(w):
                # RC = Factor Vol * Exposure = sigma * (B.T @ w)
                factor_exposures = B.T @ w
                factor_risks = np.abs(factor_exposures * sigma_f)
                
                # Minimize deviation from max budget
                # We want to be "close to this value as much as possible"
                return np.sum((factor_risks - budget_targets) ** 2)

            # Max constraint: RC <= Budget
            # Form: Budget - RC >= 0
            def max_budget_constraint(w):
                factor_exposures = B.T @ w
                factor_risks = np.abs(factor_exposures * sigma_f)
                return budget_targets - factor_risks
            
            constraints.append({'type': 'ineq', 'fun': max_budget_constraint})

        else:
            # Legacy/Default Equal Risk Contribution logic
            # Target = Mean Risk Contribution
            def objective(w):
                factor_exposures = B.T @ w
                factor_risks = np.abs(factor_exposures * sigma_f)
                target_risk = factor_risks.mean()
                return np.sum((factor_risks - target_risk) ** 2)

        bounds = [(0, 1) for _ in range(n_assets)]
        w0 = np.ones(n_assets) / n_assets
        
        result = minimize(
            objective, w0,
            method='SLSQP',
            bounds=bounds,
            constraints=constraints,
            options={'maxiter': 1000, 'ftol': 1e-9}
        )
        
        return pd.Series(result.x, index=asset_names)
    
    def _build_exposure_matrix(self, factor_vols: pd.Series) -> Tuple[pd.DataFrame, list, list]:
        """
        Build asset-factor exposure matrix using PCA factor names.
        
        Maps asset sensitivities to PCA factors (IRDL.XX, IRSL.XX, IRCV.XX).
        """
        asset_names = list(self.portfolio.assets.keys())
        factor_names = [f for f in factor_vols.index if pd.notna(factor_vols[f])]
        
        # Build exposure matrix
        exposure_matrix = np.zeros((len(asset_names), len(factor_names)))
        
        for i, asset_name in enumerate(asset_names):
            asset = self.portfolio.assets[asset_name]
            for j, factor_name in enumerate(factor_names):
                # Map asset factor to PCA factor
                # e.g., if asset has IRDL.US sensitivity, use that for PCA IRDL.US
                if factor_name in asset.factors:
                    exposure_matrix[i, j] = asset.factors[factor_name]
        
        return pd.DataFrame(exposure_matrix, index=asset_names, columns=factor_names), asset_names, factor_names
    
    def allocate_capital(self, total_capital: float, 
                        rebalance_date: pd.Timestamp) -> pd.Series:
        """
        Allocate capital using PCA factor risk parity.
        
        Args:
            total_capital: Total capital to allocate
            rebalance_date: Date at which to rebalance
            
        Returns:
            Series of capital allocations
        """
        weights, _ = self.fit_and_calculate(rebalance_date)
        return weights * total_capital
    
    def get_pca_diagnostics(self) -> Dict:
        """Get PCA diagnostics including explained variance ratios."""
        diagnostics = {}
        
        for country in ['US', 'JP', 'DE', 'UK', 'CN']:
            var_ratios = self.pca_analyzer.get_explained_variance(country)
            if var_ratios is not None:
                diagnostics[country] = {
                    'PC1_var': var_ratios[0] if len(var_ratios) > 0 else None,
                    'PC2_var': var_ratios[1] if len(var_ratios) > 1 else None,
                    'PC3_var': var_ratios[2] if len(var_ratios) > 2 else None,
                    'total_explained': sum(var_ratios)
                }
        
        return diagnostics
    
    def get_factor_loadings(self, country: str) -> Optional[pd.DataFrame]:
        """Get PCA factor loadings for a country."""
        return self.pca_analyzer.get_factor_loadings(country)
    
    def clear_cache(self):
        """Clear cached data."""
        self._weights = None
        self._pca_factor_vols = None
        self.pca_analyzer.clear_cache()

    def optimize(self, total_capital: float, use_cache: bool = True, risk_budgets: Dict[str, float] = None):
        """
        Run the optimization and return detailed results.
        
        Args:
            total_capital: Total capital to allocate
            use_cache: Whether to use cached data
            risk_budgets: Optional risk budgets per factor
            
        Returns:
            Tuple of (summary, asset_returns, volatilities, factor_exposures, factor_risk_contributions)
        """
        # Load data to find latest date
        self.portfolio.risk_factor_loader.load_risk_factors(use_cache=use_cache)
        # Need to ensure PCA is initialized/data loaded
        if self.portfolio.risk_factor_loader._risk_factors_cache is None:
             self.portfolio.risk_factor_loader.load_risk_factors(use_cache=False)
             
        rebalance_date = self.portfolio.risk_factor_loader._risk_factors_cache.index.max()
        
        # Fit and Calculate
        weights, factor_vols = self.fit_and_calculate(rebalance_date, risk_budgets=risk_budgets, total_capital=total_capital)
        
        # Construct summary
        allocation = weights * total_capital
        summary = pd.DataFrame({
            'Asset': weights.index,
            'Allocation (CNY)': allocation.values,
            'Weight (%)': weights.values * 100,
            'Asset Type': [self.portfolio.assets[a].__class__.__name__ for a in weights.index] # Approx type
        })
        
        # Compute Risk Contributions
        factor_risk_contributions = self.portfolio.calculate_factor_risk_contributions(weights, use_cache=use_cache)
        
        # Compute Factor Exposures (Long Format)
        exposure_matrix, asset_names, factor_names = self._build_exposure_matrix(factor_vols)
        factor_exposures_df = pd.DataFrame(exposure_matrix, index=weights.index, columns=factor_names)
        factor_exp_long = factor_exposures_df.reset_index().melt(id_vars='index', var_name='Risk Factor', value_name='Exposure')
        factor_exp_long.rename(columns={'index': 'Asset'}, inplace=True)
        
        # Dummy asset returns (not calculated here usually, but required by signature)
        asset_returns = pd.DataFrame() 
        
        return summary, asset_returns, factor_vols, factor_exp_long, factor_risk_contributions

    def print_summary(self, summary, total_capital, factor_exposures, factor_risk_contributions):
        """Print summary of optimization results."""
        print(f"Total Capital: {total_capital:,.2f}")
        print(summary)
