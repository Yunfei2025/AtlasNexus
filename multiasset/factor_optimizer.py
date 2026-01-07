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
from multiasset.portfolio import Portfolio, PCARiskFactorAnalyzer
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
    
    def fit_and_calculate(self, rebalance_date: pd.Timestamp) -> Tuple[pd.Series, pd.Series]:
        """
        Fit PCA and calculate optimal weights for a given rebalance date.
        
        Args:
            rebalance_date: Date at which to rebalance
            
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
        weights = self._optimize_weights(factor_vols)
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
    
    def _optimize_weights(self, factor_vols: pd.Series) -> pd.Series:
        """
        Optimize portfolio weights using factor risk parity.
        
        Args:
            factor_vols: Series of factor volatilities
            
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
        
        n_assets = len(asset_names)
        
        def objective(w):
            # Factor risk contributions
            factor_exposures = B.T @ w
            factor_risks = np.abs(factor_exposures * sigma_f)
            target_risk = factor_risks.mean()
            return np.sum((factor_risks - target_risk) ** 2)
        
        constraints = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}]
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


class FactorRiskParityOptimizer:
    """
    Optimizer that allocates capital using factor-level risk parity.
    
    Instead of making each asset contribute equal risk, this ensures
    each risk factor contributes equally to total portfolio risk.
    """
    
    def __init__(self, portfolio: Portfolio, lookback_months: Optional[int] = None, ewma_lambda: Optional[float] = None):
        """
        Initialize the optimizer.
        
        Args:
            portfolio: Portfolio instance
        """
        self.portfolio = portfolio
        self._weights: Optional[pd.Series] = None
        self._allocations: Optional[pd.Series] = None
        # Volatility model configuration (defaults pulled from config if not provided)
        self.lookback_months = lookback_months if lookback_months is not None else getattr(
            RiskModelConfig, 'FACTOR_VOL_LOOKBACK_MONTHS', 3
        )
        self.ewma_lambda = ewma_lambda if ewma_lambda is not None else getattr(
            RiskModelConfig, 'FACTOR_VOL_EWMA_LAMBDA', 0.94
        )
    
    def _build_factor_exposure_matrix(self, use_cache: bool = True) -> Tuple[pd.DataFrame, list, list]:
        """
        Build matrix of asset exposures to risk factors.
        
        Returns:
            Tuple of (exposure_matrix, asset_names, factor_names)
            exposure_matrix[i, j] = sensitivity of asset i to factor j
        """
        risk_factors_df = self.portfolio.get_risk_factors(use_cache=use_cache)
        
        # Get all unique factors from all assets
        all_factors = set()
        for asset in self.portfolio.assets.values():
            for factor_name in asset.factors.keys():
                if factor_name in risk_factors_df.columns:
                    all_factors.add(factor_name)
        
        factor_names = sorted(list(all_factors))
        asset_names = list(self.portfolio.assets.keys())
        
        # Build exposure matrix
        exposure_matrix = np.zeros((len(asset_names), len(factor_names)))
        
        for i, asset_name in enumerate(asset_names):
            asset = self.portfolio.assets[asset_name]
            for j, factor_name in enumerate(factor_names):
                if factor_name in asset.factors:
                    exposure_matrix[i, j] = asset.factors[factor_name]
        
        return pd.DataFrame(exposure_matrix, index=asset_names, columns=factor_names), asset_names, factor_names
    
    def _calculate_factor_volatilities(self, use_cache: bool = True) -> pd.Series:
        """
        Calculate volatility of each risk factor using a 3-month lookback and EWMA.
        
        Returns:
            Series of factor volatilities
        """
        risk_factors_df = self.portfolio.get_risk_factors(use_cache=use_cache)
        factor_vols: dict[str, float] = {}

        # Determine the lookback start date using relativedelta in calendar months
        window_df = risk_factors_df
        if len(risk_factors_df.index) > 0:
            idx = risk_factors_df.index
            if not isinstance(idx, pd.DatetimeIndex):
                # attempt conversion
                try:
                    idx_dt = pd.to_datetime(idx)
                    risk_factors_df = risk_factors_df.copy()
                    risk_factors_df.index = idx_dt
                except Exception:
                    pass  # keep as-is if conversion fails
            if isinstance(risk_factors_df.index, pd.DatetimeIndex):
                end_date = risk_factors_df.index.max()
                start_date = end_date - relativedelta(months=self.lookback_months)
                window_df = risk_factors_df.loc[risk_factors_df.index > start_date]

        for factor_name in window_df.columns:
            # Build daily return series in percent for the factor
            if 'IRDL' in factor_name or 'IRSL' in factor_name or 'IRCV' in factor_name:
                # Interest rate factors: these are PCA scores (cumulative), take diff
                # The diff gives daily PC score changes
                returns_pct = window_df[factor_name].diff()
            else:
                # FX and Commodity (and others): percent change
                returns_pct = window_df[factor_name].pct_change() * 100.0

            # Drop NaNs produced by diff/pct_change
            returns_pct = returns_pct.dropna()

            if returns_pct.empty:
                factor_vols[factor_name] = float('nan')
                continue

            # EWMA variance with decay λ: use pandas ewm with alpha = 1-λ
            # sigma_t^2 = (1-λ) * Σ λ^i * r_{t-i}^2
            alpha = 1.0 - self.ewma_lambda
            ewma_var = returns_pct.pow(2).ewm(alpha=alpha, adjust=False).mean()

            # Use the latest EWMA variance as estimate; annualize volatility
            latest_var = ewma_var.iloc[-1]
            vol_ann = np.sqrt(latest_var) * np.sqrt(252)
            factor_vols[factor_name] = float(vol_ann)

        return pd.Series(factor_vols)
    
    def calculate_weights(self, use_cache: bool = True) -> pd.Series:
        """
        Calculate factor risk parity weights.
        
        This uses optimization to find weights such that each factor
        contributes equally to total portfolio risk.
        
        Args:
            use_cache: Whether to use cached calculations
            
        Returns:
            Series of portfolio weights
        """
        if use_cache and self._weights is not None:
            return self._weights
        
        # Build factor exposure matrix
        exposure_matrix, asset_names, factor_names = self._build_factor_exposure_matrix(use_cache)
        
        # Get factor volatilities
        factor_vols = self._calculate_factor_volatilities(use_cache)
        
        # Extract matrices for optimization
        B = exposure_matrix.values  # N_assets x N_factors
        sigma_f = np.array([factor_vols[f] for f in factor_names])  # N_factors
        
        n_assets = len(asset_names)
        
        # Objective function: minimize sum of squared differences in factor risk contributions
        def objective(w):
            # Factor exposures: f_i = sum_j(w_j * B_ji)
            factor_exposures = B.T @ w  # N_factors
            
            # Factor risk contributions: RC_i = |f_i * sigma_i|
            factor_risks = np.abs(factor_exposures * sigma_f)
            
            # Target: equal risk contribution
            target_risk = factor_risks.mean()
            
            # Minimize sum of squared deviations
            return np.sum((factor_risks - target_risk) ** 2)
        
        # Constraints
        constraints = [
            {'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}  # weights sum to 1
        ]
        
        # Bounds: all weights between 0 and 1
        bounds = [(0, 1) for _ in range(n_assets)]
        
        # Initial guess: equal weights
        w0 = np.ones(n_assets) / n_assets
        
        # Optimize
        result = minimize(
            objective,
            w0,
            method='SLSQP',
            bounds=bounds,
            constraints=constraints,
            options={'maxiter': 1000, 'ftol': 1e-9}
        )
        
        if not result.success:
            print(f"Warning: Optimization did not converge. Message: {result.message}")
        
        # Create weights series
        weights = pd.Series(result.x, index=asset_names)
        
        self._weights = weights
        return weights
    
    def allocate_capital(self, total_capital: float, 
                         use_cache: bool = True) -> pd.Series:
        """
        Allocate capital using factor risk parity.
        
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
    
    def calculate_factor_risk_contributions(self, use_cache: bool = True) -> pd.DataFrame:
        """
        Calculate risk contribution of each factor.
        
        Args:
            use_cache: Whether to use cached calculations
            
        Returns:
            DataFrame with factor risk contributions
        """
        weights = self.calculate_weights(use_cache=use_cache)
        
        # Build factor exposure matrix
        exposure_matrix, asset_names, factor_names = self._build_factor_exposure_matrix(use_cache)
        
        # Get factor volatilities
        factor_vols = self._calculate_factor_volatilities(use_cache)
        
        # Calculate factor exposures
        B = exposure_matrix.values
        w = weights.values
        factor_exposures = B.T @ w
        
        # Calculate factor risk contributions
        factor_risks = []
        for i, factor_name in enumerate(factor_names):
            exposure = factor_exposures[i]
            vol = factor_vols[factor_name]
            risk = abs(exposure * vol)
            factor_risks.append({
                'Risk Factor': factor_name,
                'Exposure': exposure,
                'Volatility (% ann.)': vol,
                'Risk Contribution': risk
            })
        
        factor_df = pd.DataFrame(factor_risks)
        total_risk = factor_df['Risk Contribution'].sum()
        factor_df['Risk Contribution (%)'] = (factor_df['Risk Contribution'] / total_risk) * 100
        
        return factor_df.sort_values('Risk Contribution (%)', ascending=False)
    
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
        factor_risk_contributions = self.calculate_factor_risk_contributions(use_cache=use_cache)
        
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
        print(f"FACTOR RISK PARITY ALLOCATION - Total Capital: {total_capital:,.0f} CNY")
        print("="*80)
        print(summary.to_string(index=False))
        print("="*80)
        print(f"\nVerification - Total Allocated: {summary['Allocation (CNY)'].sum():,.0f} CNY")
        print("="*80)
        
        if factor_exposures is not None:
            print("\n" + "="*80)
            print("PORTFOLIO FACTOR EXPOSURES (Weighted Sensitivities)")
            print("="*80)
            print(factor_exposures.to_string(index=False))
            print("="*80)
        
        if factor_risk_contributions is not None:
            print("\n" + "="*80)
            print("RISK CONTRIBUTION BY FACTOR (Should be Equal)")
            print("="*80)
            print(factor_risk_contributions.to_string(index=False))
            print("="*80)
            print(f"\nTarget equal risk: {100/len(factor_risk_contributions):.2f}% per factor")
            print(f"Actual range: {factor_risk_contributions['Risk Contribution (%)'].min():.2f}% - {factor_risk_contributions['Risk Contribution (%)'].max():.2f}%")
            print("="*80)
    
    def clear_cache(self):
        """Clear cached optimization results."""
        self._weights = None
        self._allocations = None
        self.portfolio.clear_cache()
