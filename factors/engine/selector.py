#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Factor Selection and Filtering Utilities

Handles factor filtering by IC, IR, significance, and multicollinearity (VIF).
"""

import pandas as pd
import numpy as np
from typing import List, Dict
from scipy import stats


class FactorSelector:
    """Handles factor selection and filtering operations."""
    
    def __init__(self, config):
        """Initialize with configuration parameters."""
        self.config = config
    
    def select_factors(self, metrics: pd.DataFrame, train_factors: pd.DataFrame = None) -> List[str]:
        """
        Select top factors using configured filtering methods.
        
        Args:
            metrics: Factor performance metrics DataFrame
            train_factors: Training factor data for VIF calculation
            
        Returns:
            List of selected factor names
        """
        if metrics.empty:
            return []
        
        try:
            # Step 1: Apply primary filtering method
            filtered_factors = self._apply_primary_filter(metrics)
            
            if filtered_factors.empty:
                print(f"⚠️ No factors pass {self.config.filtering_method} filtering")
                return []
            
            # Step 2: Check factor diversification (remove highly correlated factors)
            if (self.config.use_factor_diversification and 
                len(filtered_factors) > 1 and train_factors is not None):
                filtered_factors = self._apply_diversification_filter(filtered_factors, train_factors)
            
            # Step 3: Apply VIF filtering if enabled
            if self.config.use_vif_filtering and len(filtered_factors) > 1 and train_factors is not None:
                filtered_factors = self._apply_vif_filter(filtered_factors, train_factors)
            
            if filtered_factors.empty:
                print("⚠️ No factors remain after filtering")
                return []
            
            # Step 4: Select top N factors by absolute IC
            top_factors = filtered_factors.nlargest(self.config.top_n, 'IC_abs')
            selected = top_factors.index.tolist()
            
            vif_status = "with VIF" if self.config.use_vif_filtering else "without VIF"
            div_status = "with diversification" if self.config.use_factor_diversification else ""
            print(f"✅ Selected {len(selected)} factors using {self.config.filtering_method} {vif_status} {div_status}")
            return selected
            
        except Exception as e:
            print(f"❌ Factor selection failed: {e}")
            return []
    
    def _apply_diversification_filter(self, metrics: pd.DataFrame, 
                                     train_factors: pd.DataFrame) -> pd.DataFrame:
        """
        Remove factors that are highly correlated to already selected factors.
        Keeps factors with highest IC first.
        
        Args:
            metrics: Filtered metrics DataFrame
            train_factors: Training factor data
            
        Returns:
            DataFrame with correlated factors removed
        """
        try:
            max_corr = getattr(self.config, 'max_factor_correlation', 0.6)
            
            # Sort by absolute IC (descending)
            sorted_factors = metrics.sort_values('IC_abs', ascending=False)
            factor_names = sorted_factors.index.tolist()
            
            # Get factor data
            available_factors = [f for f in factor_names if f in train_factors.columns]
            if len(available_factors) <= 1:
                return metrics
            
            factor_data = train_factors[available_factors].dropna()
            if factor_data.empty or len(factor_data) < 10:
                return metrics
            
            # Calculate correlation matrix
            corr_matrix = factor_data.corr().abs()
            
            # Greedy selection: keep factors that are not highly correlated
            selected = []
            for factor in available_factors:
                if not selected:
                    selected.append(factor)
                else:
                    # Check correlation with already selected factors
                    correlations = [corr_matrix.loc[factor, sel] for sel in selected 
                                  if sel in corr_matrix.index and factor in corr_matrix.columns]
                    
                    if not correlations or max(correlations) < max_corr:
                        selected.append(factor)
            
            n_removed = len(available_factors) - len(selected)
            if n_removed > 0:
                print(f"📊 Diversification filter: removed {n_removed} correlated factors")
            
            return metrics.loc[selected]
            
        except Exception as e:
            print(f"⚠️ Diversification filter failed: {e}, skipping")
            return metrics
    
    def _apply_primary_filter(self, metrics: pd.DataFrame) -> pd.DataFrame:
        """Apply the primary filtering method based on configuration."""
        method = self.config.filtering_method
        
        if method == 'ic_only':
            return self._filter_by_ic(metrics)
        elif method == 'ir_only':
            return self._filter_by_ir(metrics)
        elif method == 'combined':
            return self._filter_combined(metrics)
        elif method == 'significance':
            return self._filter_by_significance(metrics)
        else:
            # Fallback to IC filtering
            return self._filter_by_ic(metrics)
    
    def _filter_by_ic(self, metrics: pd.DataFrame) -> pd.DataFrame:
        """Filter factors by IC threshold."""
        return metrics[metrics['IC_abs'] >= self.config.ic_threshold]
    
    def _filter_by_ir(self, metrics: pd.DataFrame) -> pd.DataFrame:
        """Filter factors by IR threshold."""
        if 'IR' not in metrics.columns:
            print("⚠️ IR column not found, falling back to IC filtering")
            return self._filter_by_ic(metrics)
        
        return metrics[metrics['IR'].abs() >= self.config.ir_threshold]
    
    def _filter_combined(self, metrics: pd.DataFrame) -> pd.DataFrame:
        """Filter factors using combined IC and IR criteria."""
        ic_filtered = self._filter_by_ic(metrics)
        
        if 'IR' in metrics.columns:
            combined_filtered = ic_filtered[ic_filtered['IR'].abs() >= self.config.ir_threshold]
            print(f"📊 Combined: {len(ic_filtered)} passed IC, {len(combined_filtered)} passed both")
            return combined_filtered
        else:
            print("⚠️ IR column not found, using IC filtering only")
            return ic_filtered
    
    def _filter_by_significance(self, metrics: pd.DataFrame) -> pd.DataFrame:
        """Filter factors by statistical significance."""
        if not self.config.use_significance_test:
            return self._filter_by_ic(metrics)
        
        # Check minimum observations
        if 'count' in metrics.columns:
            min_obs_filtered = metrics[metrics['count'] >= self.config.min_observations]
        else:
            min_obs_filtered = metrics
        
        # Calculate t-statistic for IC significance
        if len(min_obs_filtered) > 0 and 'count' in min_obs_filtered.columns:
            ic_vals = min_obs_filtered['IC'].fillna(0)
            n_vals = min_obs_filtered['count']
            
            # Avoid division by zero and invalid sqrt
            ic_vals_safe = ic_vals.clip(-0.99, 0.99)
            t_stats = ic_vals_safe * np.sqrt(n_vals - 2) / np.sqrt(1 - ic_vals_safe**2)
            
            # Two-tailed test
            critical_t = stats.t.ppf(1 - self.config.confidence_level/2, n_vals - 2)
            significant_mask = t_stats.abs() > critical_t
            significant_factors = min_obs_filtered[significant_mask]
            
            print(f"📊 Significance: {len(significant_factors)} factors with p < {self.config.confidence_level}")
            return significant_factors
        else:
            print("⚠️ Insufficient data for significance testing, using IC filtering")
            return self._filter_by_ic(metrics)
    
    def _apply_vif_filter(self, metrics: pd.DataFrame, train_factors: pd.DataFrame) -> pd.DataFrame:
        """Apply VIF (Variance Inflation Factor) filtering."""
        if len(metrics) <= 1:
            return metrics
        
        try:
            # Get factors that passed previous filtering
            factor_names = metrics.index.tolist()
            available_factors = [f for f in factor_names if f in train_factors.columns]
            
            if len(available_factors) <= 1:
                return metrics
            
            factor_data = train_factors[available_factors]
            print(f"🔍 VIF Analysis: Checking {len(available_factors)} factors...")
            
            # Calculate VIF
            vif_results = calculate_vif(factor_data)
            
            if vif_results.empty or 'VIF' not in vif_results.columns:
                print("⚠️ VIF calculation failed, skipping VIF filtering")
                return metrics
            
            # Show VIF diagnostics
            self._show_vif_diagnostics(vif_results)
            
            # Filter factors with acceptable VIF
            low_vif_factors = vif_results[
                (vif_results['VIF'] <= self.config.vif_threshold) & 
                (~vif_results['VIF'].isin([np.inf, np.nan]))
            ]['Factor'].tolist()
            
            vif_filtered = metrics[metrics.index.isin(low_vif_factors)]
            
            # Handle overly restrictive VIF filtering
            if len(vif_filtered) <= 1 and len(metrics) > 3:
                vif_filtered = self._handle_restrictive_vif(metrics, factor_data)
            
            removed_count = len(metrics) - len(vif_filtered)
            print(f"📊 VIF: {len(vif_filtered)} factors retained (removed {removed_count})")
            
            return vif_filtered
            
        except Exception as e:
            print(f"⚠️ VIF filtering failed: {e}, skipping VIF filtering")
            return metrics
    
    def _show_vif_diagnostics(self, vif_results: pd.DataFrame) -> None:
        """Display VIF diagnostic information."""
        print(f"📊 VIF Results (threshold: {self.config.vif_threshold}):")
        vif_sorted = vif_results.sort_values('VIF', ascending=False)
        
        for _, row in vif_sorted.head(5).iterrows():  # Show top 5
            vif_val = row['VIF']
            status = "❌ HIGH" if vif_val > self.config.vif_threshold else "✅ OK"
            if np.isinf(vif_val):
                print(f"   {row['Factor']}: INF {status}")
            else:
                print(f"   {row['Factor']}: {vif_val:.2f} {status}")
    
    def _handle_restrictive_vif(self, metrics: pd.DataFrame, factor_data: pd.DataFrame) -> pd.DataFrame:
        """Handle overly restrictive VIF filtering with fallback strategies."""
        print(f"🔄 VIF too restrictive, trying fallback threshold {self.config.vif_fallback_threshold}")
        
        # Try fallback threshold
        original_threshold = self.config.vif_threshold
        self.config.vif_threshold = self.config.vif_fallback_threshold
        
        try:
            vif_results = calculate_vif(factor_data)
            
            if not vif_results.empty and 'VIF' in vif_results.columns:
                low_vif_factors = vif_results[
                    (vif_results['VIF'] <= self.config.vif_threshold) & 
                    (~vif_results['VIF'].isin([np.inf, np.nan]))
                ]['Factor'].tolist()
                
                fallback_filtered = metrics[metrics.index.isin(low_vif_factors)]
                
                if len(fallback_filtered) > 1:
                    print(f"✅ Fallback VIF threshold worked: {len(fallback_filtered)} factors")
                    return fallback_filtered
        
        finally:
            # Restore original threshold
            self.config.vif_threshold = original_threshold
        
        # Ultimate fallback: skip VIF filtering
        print("⚠️ VIF filtering still too restrictive, skipping VIF step")
        return metrics


def create_factor_selector(config) -> FactorSelector:
    """
    Factory function to create a FactorSelector instance.
    
    Args:
        config: Configuration object with filtering parameters
        
    Returns:
        Configured FactorSelector instance
    """
    return FactorSelector(config)


def filter_high_ic_factors(ic_results: pd.DataFrame, threshold: float = 0.03, method: str = 'IC_abs') -> pd.DataFrame:
    """
    Filter factors with IC values above threshold
    
    Args:
        ic_results: IC results DataFrame
        threshold: IC threshold value (default 0.03)
        method: IC method to use ('IC_abs', 'IR_abs', 'IC', 'IR')
    
    Returns:
        Filtered factors DataFrame
    """
    if method in ic_results.columns:
        high_ic_factors = ic_results[ic_results[method] > threshold].copy()
        high_ic_factors = high_ic_factors.sort_values(method, ascending=False)
    else:
        print(f"Warning: Column '{method}' not found, available columns: {list(ic_results.columns)}")
        # Fallback to IC_abs if available
        if 'IC_abs' in ic_results.columns:
            high_ic_factors = ic_results[ic_results['IC_abs'] > threshold].copy()
            high_ic_factors = high_ic_factors.sort_values('IC_abs', ascending=False)
        else:
            print("Error: No usable IC column found")
            return pd.DataFrame()
    
    return high_ic_factors


def calculate_collinearity_matrix(factors_data: pd.DataFrame, method: str = 'pearson') -> pd.DataFrame:
    """
    Calculate correlation matrix for factor collinearity analysis
    
    Args:
        factors_data: Factor data DataFrame
        method: Correlation method ('pearson', 'spearman', 'kendall')
    
    Returns:
        Correlation matrix DataFrame
    """
    if factors_data.empty:
        return pd.DataFrame()
    
    try:
        # Remove non-numeric columns and handle missing values
        numeric_data = factors_data.select_dtypes(include=[np.number])
        
        if numeric_data.empty:
            print("No numeric columns found for correlation analysis")
            return pd.DataFrame()
        
        # Calculate correlation matrix
        if method == 'pearson':
            corr_matrix = numeric_data.corr(method='pearson')
        elif method == 'spearman':
            corr_matrix = numeric_data.corr(method='spearman')
        elif method == 'kendall':
            corr_matrix = numeric_data.corr(method='kendall')
        else:
            print(f"Unknown method '{method}', using pearson")
            corr_matrix = numeric_data.corr(method='pearson')
        
        return corr_matrix
        
    except Exception as e:
        print(f"Correlation calculation failed: {e}")
        return pd.DataFrame()


def identify_highly_correlated_factors(corr_matrix: pd.DataFrame, threshold: float = 0.8) -> List[Dict]:
    """
    Identify pairs of factors with high correlation
    
    Args:
        corr_matrix: Correlation matrix DataFrame
        threshold: Correlation threshold for identifying high correlation
    
    Returns:
        List of dictionaries with highly correlated factor pairs
    """
    if corr_matrix.empty:
        return []
    
    highly_correlated = []
    
    # Get upper triangle of correlation matrix (avoid duplicates)
    upper_triangle = np.triu(np.abs(corr_matrix.values), k=1)
    
    # Find indices where correlation exceeds threshold
    high_corr_indices = np.where(upper_triangle > threshold)
    
    for i, j in zip(high_corr_indices[0], high_corr_indices[1]):
        factor1 = corr_matrix.index[i]
        factor2 = corr_matrix.columns[j]
        correlation = corr_matrix.iloc[i, j]
        
        highly_correlated.append({
            'factor1': factor1,
            'factor2': factor2,
            'correlation': correlation
        })
    
    return highly_correlated


def calculate_vif(factors_data: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate Variance Inflation Factor (VIF) for multicollinearity detection
    
    Args:
        factors_data: Factor data DataFrame
    
    Returns:
        DataFrame with VIF values for each factor
    """
    try:
        from sklearn.linear_model import LinearRegression
        
        # Clean data
        clean_data = factors_data.select_dtypes(include=[np.number]).dropna()
        
        if clean_data.empty or len(clean_data.columns) < 2:
            return pd.DataFrame()
        
        vif_results = []
        
        for i, factor in enumerate(clean_data.columns):
            # Prepare data: factor as target, others as features
            X = clean_data.drop(columns=[factor])
            y = clean_data[factor]
            
            if len(X.columns) == 0:
                vif_results.append({'Factor': factor, 'VIF': 1.0})
                continue
            
            try:
                # Fit regression model
                model = LinearRegression()
                model.fit(X, y)
                
                # Calculate R-squared
                y_pred = model.predict(X)
                ss_res = np.sum((y - y_pred) ** 2)
                ss_tot = np.sum((y - np.mean(y)) ** 2)
                
                if ss_tot == 0:
                    r_squared = 0
                else:
                    r_squared = 1 - (ss_res / ss_tot)
                
                # Calculate VIF
                if r_squared >= 0.999:  # Avoid division by very small numbers
                    vif = np.inf
                else:
                    vif = 1 / (1 - r_squared)
                
                vif_results.append({'Factor': factor, 'VIF': vif})
                
            except Exception as e:
                print(f"VIF calculation failed for {factor}: {e}")
                vif_results.append({'Factor': factor, 'VIF': np.nan})
        
        return pd.DataFrame(vif_results)
        
    except Exception as e:
        print(f"VIF calculation failed: {e}")
        return pd.DataFrame()
