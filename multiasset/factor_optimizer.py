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
from multiasset.factor_backtest import compute_ewma_factor_vols, compute_ewma_factor_covariance, get_factor_price_beta
from multiasset.portfolio import Portfolio
from multiasset.pca_analyzer import PCARiskFactorAnalyzer
from dateutil.relativedelta import relativedelta
# Prefer local config in multiasset; fallback to settings if not available
from .config import RiskModelConfig  # type: ignore


class FactorRiskParityOptimizer:
    """
    Optimizer using portfolio risk factors for factor risk parity.
    
    At each rebalance date:
    1. Load the configured portfolio risk factors
    2. Convert factor levels into price-return-space volatility estimates
    3. Calculate factor volatilities using EWMA
    4. Optimize portfolio weights for equal factor risk contribution
    """
    
    def __init__(self, portfolio: Portfolio, input_dir: str,
                 factor_model_lookback_years: float = 1.0,
                 vol_lookback_months: int = 3,
                 ewma_lambda: float = 0.94,
                 pca_lookback_years: Optional[float] = None):
        """
        Initialize the factor risk parity optimizer.
        
        Args:
            portfolio: Portfolio instance
            input_dir: Directory containing yield curve data
            factor_model_lookback_years: Years of data for factor-model fitting
            vol_lookback_months: Months of data for EWMA volatility
            ewma_lambda: EWMA decay parameter
            pca_lookback_years: Legacy alias for factor_model_lookback_years
        """
        if pca_lookback_years is not None:
            factor_model_lookback_years = pca_lookback_years

        self.portfolio = portfolio
        self.input_dir = input_dir
        self.factor_analyzer = PCARiskFactorAnalyzer(input_dir, factor_model_lookback_years)
        self.pca_analyzer = self.factor_analyzer
        self.vol_lookback_months = vol_lookback_months
        self.ewma_lambda = ewma_lambda
        self._weights: Optional[pd.Series] = None
        self._factor_vols: Optional[pd.Series] = None
        self._factor_cov: Optional[pd.DataFrame] = None
        self._pca_factor_vols = self._factor_vols
    
    def fit_and_calculate(self, rebalance_date: pd.Timestamp,
                          risk_budgets: Optional[Dict[str, float]] = None,
                          total_capital: float = 1.0,
                          hedge_asset_names: Optional[list] = None,
                          neutral_asset_names: Optional[list] = None) -> Tuple[pd.Series, pd.Series]:
        """
        Calculate optimal weights for a given rebalance date.
        
        Args:
            rebalance_date: Date at which to rebalance
            risk_budgets: Optional dictionary mapping factor names to risk budgets
            total_capital: Total capital for absolute risk budget calculation
            hedge_asset_names: Optional list of asset names that are allowed to
                take short positions (bounds [-0.3, 0.3] instead of [0, 1]).
            
        Returns:
            Tuple of (weights Series, factor volatilities Series)
        """
        risk_factors = self.portfolio.get_risk_factors(use_cache=True)
        if not isinstance(risk_factors.index, pd.DatetimeIndex):
            risk_factors.index = pd.to_datetime(risk_factors.index)
        risk_factors = risk_factors.sort_index()

        vol_start = rebalance_date - relativedelta(months=self.vol_lookback_months)
        factor_window = risk_factors.loc[
            (risk_factors.index >= vol_start) & (risk_factors.index <= rebalance_date)
        ]

        factor_vols = pd.Series(compute_ewma_factor_vols(
            factor_window,
            ewma_lambda=self.ewma_lambda,
        ))
        self._factor_vols = factor_vols
        self._pca_factor_vols = factor_vols

        factor_cov = compute_ewma_factor_covariance(factor_window, ewma_lambda=self.ewma_lambda)
        self._factor_cov = factor_cov

        weights = self._optimize_weights(
            factor_vols, factor_cov=factor_cov,
            risk_budgets=risk_budgets, total_capital=total_capital,
            hedge_asset_names=hedge_asset_names,
            neutral_asset_names=neutral_asset_names,
        )
        self._weights = weights

        return weights, factor_vols
    
    def _calculate_ewma_volatilities(self, factor_returns: pd.DataFrame) -> pd.Series:
        """
        Calculate EWMA volatilities for factor return series.
        
        Args:
            factor_returns: DataFrame of factor returns
            
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
                          factor_cov: Optional[pd.DataFrame] = None,
                          risk_budgets: Optional[Dict[str, float]] = None,
                          total_capital: float = 1.0,
                          hedge_asset_names: Optional[list] = None,
                          neutral_asset_names: Optional[list] = None) -> pd.Series:
        """
        Optimize portfolio weights using factor risk parity or risk budgeting.

        Uses the full EWMA factor covariance matrix (Σ = B C_f Bᵀ) when
        available, so that inter-factor correlations are captured.  Falls back
        to the diagonal approximation when factor_cov is empty.

        Args:
            factor_vols: Series of factor volatilities (used for filtering and fallback)
            factor_cov: Annualised EWMA factor covariance DataFrame (n_factors × n_factors)
            risk_budgets: Optional dict of risk budgets per factor (in million CNY)
            total_capital: Total capital to allocate (absolute units)
            hedge_asset_names: Optional list of asset names allowed to take short
                positions; they receive bounds (-0.3, 0.3) while regular assets
                stay long-only (0.0, 1.0).

        Returns:
            Series of optimal weights
        """
        exposure_matrix, asset_names, factor_names = self._build_exposure_matrix(factor_vols)

        if exposure_matrix.empty:
            return pd.Series(1.0 / len(self.portfolio.assets),
                             index=list(self.portfolio.assets.keys()))

        B = exposure_matrix.values                                   # (n_assets, n_factors)
        sigma_f = np.array([factor_vols.get(f, 0) for f in factor_names])

        # Keep only factors with non-zero vol
        valid_mask = ~np.isnan(sigma_f) & (sigma_f > 0)
        B = B[:, valid_mask]
        sigma_f_valid = sigma_f[valid_mask]
        valid_factors = [f for i, f in enumerate(factor_names) if valid_mask[i]]

        if len(sigma_f_valid) == 0:
            return pd.Series(1.0 / len(asset_names), index=asset_names)

        n_assets = len(asset_names)

        # ── Build asset covariance Σ = B C_f Bᵀ ──────────────────────────────
        use_full_cov = (factor_cov is not None and not factor_cov.empty)
        if use_full_cov:
            C_f = np.array([
                [factor_cov.loc[fi, fj]
                 if (fi in factor_cov.index and fj in factor_cov.columns)
                 else (sigma_f_valid[ki] ** 2 if ki == kj else 0.0)
                 for kj, fj in enumerate(valid_factors)]
                for ki, fi in enumerate(valid_factors)
            ], dtype=float)
        else:
            C_f = np.diag(sigma_f_valid ** 2)

        Sigma = B @ C_f @ B.T
        Sigma = (Sigma + Sigma.T) / 2 + 1e-8 * np.eye(n_assets)   # symmetrise + regularise

        # Pre-compute transpose once so every scipy.minimize iteration avoids
        # recomputing it inside the closure.
        BT = B.T

        # ── Helper: asset-level risk contributions ────────────────────────────
        def _port_vol(w: np.ndarray) -> float:
            return float(np.sqrt(max(float(w @ Sigma @ w), 1e-12)))

        def _risk_contributions(w: np.ndarray) -> np.ndarray:
            pv = _port_vol(w)
            return w * (Sigma @ w) / pv                             # sums to pv

        # ── Helper: factor-level risk contributions ───────────────────────────
        def _factor_rc_fractions(w: np.ndarray) -> np.ndarray:
            """Return each factor's share of total portfolio variance (sums to 1)."""
            e = BT @ w                                              # (n_valid_factors,)
            Cfe = C_f @ e
            rc_var = e * Cfe                                        # contribution to variance
            total_var = float(rc_var.sum())
            if total_var < 1e-12:
                return np.ones(len(valid_factors)) / len(valid_factors)
            return rc_var / total_var

        # ── Objective ─────────────────────────────────────────────────────────
        constraints = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}]

        if risk_budgets:
            has_negative = any(
                v is not None and float(v) < 0.0 for v in risk_budgets.values()
            )
            if use_full_cov:
                # Proportional budget mode: match factor-RC fractions to budget fractions
                raw_budgets = np.array([
                    float(risk_budgets.get(f, 0.0)) if risk_budgets.get(f) is not None else 0.0
                    for f in valid_factors
                ])
                total_rb = raw_budgets.sum()
                budget_fracs = raw_budgets / total_rb if total_rb > 0 else np.ones(len(valid_factors)) / len(valid_factors)

                if has_negative:
                    # Signed RC matching (e.g. short slope exposure)
                    def objective(w: np.ndarray) -> float:
                        e = BT @ w
                        Cfe = C_f @ e
                        signed_rc = e * Cfe / max(_port_vol(w), 1e-12)  # signed vol contributions
                        total_sv = np.abs(signed_rc).sum()
                        target = budget_fracs * (total_sv if total_sv > 1e-12 else 1.0)
                        return float(np.sum((signed_rc - target) ** 2))
                else:
                    def objective(w: np.ndarray) -> float:
                        return float(np.sum((_factor_rc_fractions(w) - budget_fracs) ** 2))
            else:
                # Legacy diagonal mode: match |e_k σ_k| targets
                budget_targets = np.array([
                    (float(risk_budgets.get(f, 0.0)) * 1_000_000.0) / total_capital
                    if total_capital > 1e-6 else 0.0
                    for f in valid_factors
                ])
                if has_negative:
                    def objective(w: np.ndarray) -> float:
                        signed = BT @ w * sigma_f_valid
                        return float(np.sum((signed - budget_targets) ** 2))
                else:
                    def objective(w: np.ndarray) -> float:
                        factor_risks = np.abs(BT @ w * sigma_f_valid)
                        return float(np.sum((factor_risks - budget_targets) ** 2))

                    def max_budget_constraint(w: np.ndarray) -> np.ndarray:
                        return budget_targets - np.abs(BT @ w * sigma_f_valid)

                    constraints.append({'type': 'ineq', 'fun': max_budget_constraint})
        else:
            # Pure ERC: equal asset-level risk contributions (respects correlations via Σ)
            def objective(w: np.ndarray) -> float:
                RC = _risk_contributions(w)
                target = _port_vol(w) / n_assets
                return float(np.sum((RC - target) ** 2))

        # ── Per-asset bounds ─────────────────────────────────────────────────
        # Hedge instruments are allowed to take short positions.  Regular assets
        # stay long-only.  A small minimum weight floor prevents the optimizer
        # from zeroing out assets when the B matrix is rank-deficient (e.g. 6
        # CN bonds all sharing the same 3 factors → degenerate ERC landscape).
        _MAX_HEDGE_WT = 0.30
        _hedge_set   = set(hedge_asset_names)   if hedge_asset_names   else set()
        _neutral_set = set(neutral_asset_names) if neutral_asset_names else set()

        # Auto-detect neutral assets from risk_budgets: an asset is neutral when
        # its total weighted budget exposure across all factors it loads on is ~0.
        # Scalar levels are {0, ±0.25, ±0.5, ±0.75, ±1.0}; scalar=0 means flat.
        if risk_budgets and not _neutral_set:
            _budget_arr = np.array([
                float(risk_budgets.get(f, 0.0)) if risk_budgets.get(f) is not None else 0.0
                for f in valid_factors
            ])
            _asset_budget_exposure = np.abs(B) @ np.abs(_budget_arr)
            _total_budget = np.abs(_budget_arr).sum()
            if _total_budget > 1e-9:
                for _ai, _aname in enumerate(asset_names):
                    if _asset_budget_exposure[_ai] < 1e-9 * _total_budget:
                        _neutral_set.add(_aname)

        from multiasset.assets import CommodityAsset, FXAsset
        _commodity_set = {name for name in asset_names if isinstance(self.portfolio.assets.get(name), CommodityAsset)}
        _fx_set = {name for name in asset_names if isinstance(self.portfolio.assets.get(name), FXAsset)}
        _commodity_min_wt = 0.01
        non_commodity_count = n_assets - len(_commodity_set)
        _min_wt = 1.0 / (non_commodity_count * 10) if non_commodity_count > 0 else 0.0
        _CAP_COMM = max(1.0 / n_assets, 0.15)
        _CAP_FX   = max(1.0 / n_assets, 0.20)
        # Cap bonds at 2× equal share so no single bond dominates when the
        # B matrix is nearly rank-deficient (e.g. 6 CN bonds on one factor).
        _CAP_BOND = max(2.0 / n_assets, 0.15)
        # Neutral cap = 0.25 × equal-share weight (minimum scalar tick applied to RP base).
        # Long-only scalars are {0.25, 0.5, 0.75, 1.0}; scalar=0 maps to this floor
        # so the optimizer produces a practically-flat position without being excluded.
        _CAP_NEUTRAL = max(0.25 / n_assets, _min_wt)
        bounds = [
            (-_MAX_HEDGE_WT, _MAX_HEDGE_WT) if name in _hedge_set
            else (0.0, _CAP_NEUTRAL)            if name in _neutral_set
            else (_commodity_min_wt, _CAP_COMM) if name in _commodity_set
            else (_min_wt, _CAP_FX)             if name in _fx_set
            else (_min_wt, _CAP_BOND)
            for name in asset_names
        ]

        # Start from the minimum-weight floors: _min_wt for bonds, _commodity_min_wt for commodities
        w0 = np.array([
            _commodity_min_wt if name in _commodity_set else _min_wt
            for name in asset_names
        ])
        remaining = 1.0 - w0.sum()
        if remaining > 0:
            # Distribute remaining weight equally among non-commodity assets.
            non_commodity_indices = [i for i, name in enumerate(asset_names) if name not in _commodity_set]
            if non_commodity_indices:
                w0[non_commodity_indices] += remaining / len(non_commodity_indices)

        result = minimize(
            objective, w0,
            method='SLSQP',
            bounds=bounds,
            constraints=constraints,
            options={'maxiter': 1000, 'ftol': 1e-9},
        )

        # ── If the primary solve did not converge, retry without hedge shorts ─
        # This mirrors portfolio/portfolio.py's two-stage fallback logic.
        if not result.success and _hedge_set:
            fallback_bounds = [
                (_commodity_min_wt, _CAP_COMM) if name in _commodity_set
                else (_min_wt, _CAP_FX) if name in _fx_set
                else (_min_wt, _CAP_BOND)
                for name in asset_names
            ]
            result_fb = minimize(
                objective, w0,
                method='SLSQP',
                bounds=fallback_bounds,
                constraints=constraints,
                options={'maxiter': 1000, 'ftol': 1e-9},
            )
            if result_fb.success or result_fb.fun < result.fun:
                result = result_fb

        return pd.Series(result.x, index=asset_names)

    def _compute_factor_risk_contributions(
        self,
        weights: pd.Series,
        exposure_matrix: pd.DataFrame,
        factor_names: list,
        factor_cov: Optional[pd.DataFrame],
        factor_vols: pd.Series,
    ) -> pd.DataFrame:
        """
        Compute factor-level risk contributions using the full covariance matrix.

        For each factor k:
          RC_k = e_k * (C_f @ e)_k  (contribution to portfolio variance)
          where e = Bᵀ w  (portfolio factor exposures)

        Returns a DataFrame with columns:
          Risk Factor, Volatility (% ann.), Risk Contribution (%)
        """
        if exposure_matrix.empty:
            return pd.DataFrame()

        _exp_idx = exposure_matrix.index
        if not _exp_idx.is_unique:
            _exp_idx = _exp_idx[~_exp_idx.duplicated(keep='first')]
        w = weights.reindex(_exp_idx).fillna(0.0).values
        B = exposure_matrix.values                                   # (n_assets, n_factors)
        sigma_f = np.array([factor_vols.get(f, 0.0) for f in factor_names])

        valid_mask = ~np.isnan(sigma_f) & (sigma_f > 0)
        B_v = B[:, valid_mask]
        sigma_v = sigma_f[valid_mask]
        valid_factors = [f for i, f in enumerate(factor_names) if valid_mask[i]]

        use_full_cov = (factor_cov is not None and not factor_cov.empty)
        if use_full_cov:
            C_f = np.array([
                [factor_cov.loc[fi, fj]
                 if (fi in factor_cov.index and fj in factor_cov.columns)
                 else (sigma_v[ki] ** 2 if ki == kj else 0.0)
                 for kj, fj in enumerate(valid_factors)]
                for ki, fi in enumerate(valid_factors)
            ], dtype=float)
        else:
            C_f = np.diag(sigma_v ** 2)

        e = B_v.T @ w                                               # (n_valid_factors,)
        Cfe = C_f @ e
        port_var = float(e @ Cfe)
        port_vol_val = float(np.sqrt(max(port_var, 1e-12)))

        rows = []
        for k, f in enumerate(valid_factors):
            rc_var = float(e[k] * Cfe[k])
            rc_pct = rc_var / port_var * 100.0 if port_var > 1e-12 else 0.0
            # Signed net factor exposure e_k tells you directional bet:
            #   positive → portfolio gains when factor PRICE rises (e.g. long level = yield falls)
            #   negative → portfolio gains when factor PRICE falls (e.g. short slope)
            rows.append({
                'Risk Factor': f,
                'Volatility (% ann.)': float(sigma_v[k]),
                'Net Exposure': float(e[k]),          # signed: + long factor, - short factor
                'Risk Contribution (%)': rc_pct,      # always >= 0 (variance contribution)
            })

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        return df.sort_values('Risk Contribution (%)', ascending=False).reset_index(drop=True)

    
    def _build_exposure_matrix(self, factor_vols: pd.Series) -> Tuple[pd.DataFrame, list, list]:
        """
        Build asset-factor exposure matrix using factor names.
        
        Maps asset sensitivities to model factors (IRDL.XX, IRSL.XX, IRCV.XX).
        """
        asset_names = list(self.portfolio.assets.keys())
        factor_names = [f for f in factor_vols.index if pd.notna(factor_vols[f])]
        
        # Build exposure matrix
        exposure_matrix = np.zeros((len(asset_names), len(factor_names)))
        
        for i, asset_name in enumerate(asset_names):
            asset = self.portfolio.assets[asset_name]
            for j, factor_name in enumerate(factor_names):
                if factor_name in asset.factors:
                    exposure_matrix[i, j] = get_factor_price_beta(
                        factor_name,
                        asset.factors[factor_name],
                    )
        
        return pd.DataFrame(exposure_matrix, index=asset_names, columns=factor_names), asset_names, factor_names
    
    def allocate_capital(self, total_capital: float, 
                        rebalance_date: pd.Timestamp) -> pd.Series:
        """
        Allocate capital using factor risk parity.
        
        Args:
            total_capital: Total capital to allocate
            rebalance_date: Date at which to rebalance
            
        Returns:
            Series of capital allocations
        """
        weights, _ = self.fit_and_calculate(rebalance_date)
        return weights * total_capital
    
    def get_factor_model_diagnostics(self) -> Dict:
        """Get factor-model diagnostics including explained variance ratios."""
        diagnostics = {}
        
        for country in ['US', 'JP', 'DE', 'UK', 'CN']:
            var_ratios = self.factor_analyzer.get_explained_variance(country)
            if var_ratios is not None:
                diagnostics[country] = {
                    'PC1_var': var_ratios[0] if len(var_ratios) > 0 else None,
                    'PC2_var': var_ratios[1] if len(var_ratios) > 1 else None,
                    'PC3_var': var_ratios[2] if len(var_ratios) > 2 else None,
                    'total_explained': sum(var_ratios)
                }
        
        return diagnostics

    def get_pca_diagnostics(self) -> Dict:
        """Backward-compatible alias for factor-model diagnostics."""
        return self.get_factor_model_diagnostics()
    
    def get_factor_loadings(self, country: str) -> Optional[pd.DataFrame]:
        """Get PCA factor loadings for a country."""
        return self.factor_analyzer.get_factor_loadings(country)
    
    def clear_cache(self):
        """Clear cached data."""
        self._weights = None
        self._factor_vols = None
        self._pca_factor_vols = None
        self.factor_analyzer.clear_cache()

    def optimize(self, total_capital: float, use_cache: bool = True,
                 risk_budgets: Dict[str, float] = None,
                 hedge_asset_names: list = None,
                 neutral_asset_names: list = None):
        """
        Run the optimization and return detailed results.
        
        Args:
            total_capital: Total capital to allocate
            use_cache: Whether to use cached data
            risk_budgets: Optional risk budgets per factor
            hedge_asset_names: Optional list of asset names with short-allowed bounds
            
        Returns:
            Tuple of (summary, asset_returns, volatilities, factor_exposures, factor_risk_contributions)
        """
        # Load data to find latest date
        self.portfolio.risk_factor_loader.load_risk_factors(use_cache=use_cache)
        # Need to ensure PCA is initialized/data loaded
        if self.portfolio.risk_factor_loader._risk_factors_cache is None:
             self.portfolio.risk_factor_loader.load_risk_factors(use_cache=False)
             
        # Snap to the 1st of the current month so the portfolio tab uses the same
        # cut-off as the monthly backtest rebalance dates (avoids look-ahead bias).
        _today = pd.Timestamp.today().normalize()
        _first_of_month = _today.replace(day=1)
        _data_max = pd.Timestamp(self.portfolio.risk_factor_loader._risk_factors_cache.index.max())
        rebalance_date = min(_first_of_month, _data_max)
        
        # Fit and Calculate
        weights, factor_vols = self.fit_and_calculate(
            rebalance_date,
            risk_budgets=risk_budgets,
            total_capital=total_capital,
            hedge_asset_names=hedge_asset_names,
            neutral_asset_names=neutral_asset_names,
        )
        
        # Construct summary
        allocation = weights * total_capital
        summary = pd.DataFrame({
            'Asset': weights.index,
            'Allocation (CNY)': allocation.values,
            'Weight (%)': weights.values * 100,
            'Asset Type': [self.portfolio.assets[a].__class__.__name__ for a in weights.index] # Approx type
        })
        
        # Compute Factor Exposures (Long Format) and Risk Contributions
        exposure_matrix, asset_names, factor_names = self._build_exposure_matrix(factor_vols)

        # Use full-covariance attribution when available
        factor_risk_contributions = self._compute_factor_risk_contributions(
            weights, exposure_matrix, factor_names, self._factor_cov, factor_vols
        )

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


PCAFactorRiskParityOptimizer = FactorRiskParityOptimizer
