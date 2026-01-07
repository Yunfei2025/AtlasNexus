# -*- coding: utf-8 -*-
"""
Statistics Module for Pair Analysis

This module handles regression analysis and statistical calculations.
"""
from typing import Dict, Tuple
import numpy as np
import pandas as pd
import statsmodels.api as sm


class RegressionResults:
    """Class to encapsulate regression results"""
    def __init__(self, stats: Dict[str, float], fitted: np.ndarray, residuals: np.ndarray = None):
        self.stats = stats
        self.fitted = fitted
        self.residuals = residuals if residuals is not None else np.array([])
        
        # Calculate standard deviation of residuals for confidence bands
        if len(self.residuals) > 0:
            self._residual_std = np.std(self.residuals, ddof=2)  # Use ddof=2 for regression
        else:
            self._residual_std = 0.0
        
    @property
    def n_obs(self) -> int:
        return self.stats["n_obs"]
    
    @property
    def intercept(self) -> float:
        return self.stats["intercept"]
    
    @property
    def slope(self) -> float:
        return self.stats["slope_per_step"]
    
    @property
    def r_squared(self) -> float:
        return self.stats["r2"]
    
    @property
    def residual_std(self) -> float:
        """Standard deviation of residuals for confidence bands"""
        return self._residual_std
    
    def get_confidence_bands(self) -> Tuple[np.ndarray, np.ndarray]:
        """Calculate +/- 1 standard deviation confidence bands"""
        upper_band = self.fitted + self._residual_std
        lower_band = self.fitted - self._residual_std
        return upper_band, lower_band


class StatisticalAnalyzer:
    """Class for performing statistical analysis on time series data"""
    
    @staticmethod
    def run_regression(spread_df: pd.DataFrame) -> RegressionResults:
        """Run regression analysis on the spread"""
        # Pre-allocate arrays for better performance
        n_obs = len(spread_df)
        if n_obs < 5:
            raise ValueError(f"Insufficient sample size ({n_obs}<5) for regression analysis")
        
        # Vectorized time index creation
        t_values = np.arange(n_obs, dtype=np.float64)
        spread_values = spread_df['spread'].values.astype(np.float64)
        
        # Add constant term efficiently
        X = np.column_stack([np.ones(n_obs), t_values])
        
        try:
            # Use more efficient OLS fitting
            model = sm.OLS(spread_values, X, missing="drop")
            res = model.fit()

            # Extract results efficiently
            fitted = res.fittedvalues
            residuals = res.resid
            
            # Pre-calculate statistics to avoid repeated calls
            params = res.params
            bse = res.bse
            tvalues = res.tvalues
            pvalues = res.pvalues
            
            stats = {
                "n_obs": int(res.nobs),
                "intercept": float(params[0]),
                "slope_per_step": float(params[1]),
                "r2": float(res.rsquared),
                "adj_r2": float(res.rsquared_adj),
                "stderr_intercept": float(bse[0]),
                "stderr_slope": float(bse[1]),
                "t_intercept": float(tvalues[0]),
                "t_slope": float(tvalues[1]),
                "p_intercept": float(pvalues[0]),
                "p_slope": float(pvalues[1]),
                "dw": float(sm.stats.stattools.durbin_watson(res.resid)),
                "residual_std": float(np.std(residuals, ddof=2)),  # Standard deviation of residuals
            }
            
            return RegressionResults(stats, fitted, residuals)
            
        except Exception as e:
            print(f"Regression calculation failed: {e}")
            # Return default values
            default_stats = {
                "n_obs": n_obs,
                "intercept": 0.0,
                "slope_per_step": 0.0,
                "r2": 0.0,
                "adj_r2": 0.0,
                "stderr_intercept": 0.0,
                "stderr_slope": 0.0,
                "t_intercept": 0.0,
                "t_slope": 0.0,
                "p_intercept": 1.0,
                "p_slope": 1.0,
                "dw": 0.0,
                "residual_std": 0.0,
            }
            return RegressionResults(default_stats, np.zeros(n_obs), np.zeros(n_obs))

    @staticmethod
    def calculate_spread(leg1_data: pd.Series, leg2_data: pd.Series) -> pd.DataFrame:
        """Calculate spread between two time series in basis points (bp)"""
        # Convert to DataFrames for alignment
        df1 = leg1_data.reset_index()
        df1.columns = ['date', 'ret1']
        df2 = leg2_data.reset_index()
        df2.columns = ['date', 'ret2']
        
        # Efficient merge using index alignment
        df1_aligned = df1.set_index('date')
        df2_aligned = df2.set_index('date')
        
        # Use join for better performance than merge
        aligned_data = df1_aligned.join(df2_aligned, how='inner')
        
        # Vectorized spread calculation and convert to basis points (multiply by 100)
        aligned_data['spread'] = (aligned_data['ret1'] - aligned_data['ret2']) * 100
        
        # Remove NaN values efficiently
        aligned_data = aligned_data.dropna(subset=['spread'])
        
        # Reset index for output
        result = aligned_data.reset_index()[['date', 'spread']]
        
        return result