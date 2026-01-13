# -*- coding: utf-8 -*-
"""
Risk factor loader for multi-asset portfolios.
"""
import os
import pandas as pd
from typing import Dict, Optional, Union
from pathlib import Path
from multiasset.pca_analyzer import PCARiskFactorAnalyzer


class RiskFactorLoader:
    """Loads and caches risk factor data."""
    
    def __init__(self, input_dir: Union[str, Path]):
        """
        Initialize the risk factor loader.
        
        Args:
            input_dir: Directory containing curve and database files
        """
        self.input_dir = str(input_dir)
        self._risk_factors_cache: Optional[pd.DataFrame] = None
        # Create PCA analyzer for IR factors
        self.pca_analyzer = PCARiskFactorAnalyzer(input_dir)
    
    def load_risk_factors(self, use_cache: bool = True) -> pd.DataFrame:
        """
        Load all risk factors from data files.
        
        Args:
            use_cache: Whether to use cached data
            
        Returns:
            DataFrame with all risk factors
        """
        if use_cache and self._risk_factors_cache is not None:
            return self._risk_factors_cache
        
        macro_data = pd.read_pickle(os.path.join(self.input_dir, 'macro-px.pkl'))
        risk_factors = pd.DataFrame()
        
        # Interest rate factors
        risk_factors = self._load_ir_factors(risk_factors)
        
        # Curve spread factors
        risk_factors = self._load_sp_factors(risk_factors)
        
        # FX factors
        risk_factors = self._load_fx_factors(risk_factors, macro_data)
        
        # Commodity factors
        risk_factors = self._load_commodity_factors(risk_factors, macro_data)
        print("Loaded risk factors:", risk_factors.columns.tolist())
        
        # Drop NaN values
        # risk_factors = risk_factors.dropna()
        
        self._risk_factors_cache = risk_factors
        return risk_factors
    
    def _load_ir_factors(self, risk_factors: pd.DataFrame) -> pd.DataFrame:
        """
        Load interest rate level, slope, and curvature factors using full-history PCA.
        
        Uses PCARiskFactorAnalyzer to compute PC1 (Level), PC2 (Slope), PC3 (Curvature)
        from yield curve data over the entire history.
        """
        # Calculate full-history PCA scores for all countries
        pca_scores = self.pca_analyzer.calculate_full_history_pca_scores(n_components=3)
        
        if pca_scores.empty:
            print("Warning: No PCA scores computed for IR factors")
            return risk_factors
        
        # Map PCA components to IR factor names:
        # PC1 -> IRDL (Level), PC2 -> IRSL (Slope), PC3 -> IRCV (Curvature)
        pc_to_ir_map = {
            'PC1': 'IRDL',
            'PC2': 'IRSL',
            'PC3': 'IRCV',
        }
        
        for col in pca_scores.columns:
            # Column format: PC1.US, PC2.CN, etc.
            parts = col.split('.')
            if len(parts) == 2:
                pc_name, country = parts
                if pc_name in pc_to_ir_map:
                    ir_name = f"{pc_to_ir_map[pc_name]}.{country}"
                    risk_factors[ir_name] = pca_scores[col]
        
        return risk_factors
    
    def _load_sp_factors(self, risk_factors: pd.DataFrame) -> pd.DataFrame:
        """
        Load spread level and slope factors.
        
        For IRS and CDB: Uses PCA to compute PC1 (SPDL - Level) and PC2 (SPSL - Slope)
        For ICP: Loads the original series directly as SPDL.ICP (no PCA - single tenor)
        """
        # Calculate full-history PCA scores for IRS and CDB (2 components)
        pca_scores = self.pca_analyzer.calculate_full_history_spread_pca_scores(n_components=2)
        
        if not pca_scores.empty:
            # Map PCA components to spread factor names:
            # PC1 -> SPDL (Level), PC2 -> SPSL (Slope)
            pc_to_sp_map = {
                'PC1': 'SPDL',
                'PC2': 'SPSL',
            }
            
            for col in pca_scores.columns:
                # Column format: PC1.IRS, PC2.CDB, etc.
                parts = col.split('.')
                if len(parts) == 2:
                    pc_name, spread = parts
                    if pc_name in pc_to_sp_map:
                        sp_name = f"{pc_to_sp_map[pc_name]}.{spread}"
                        risk_factors[sp_name] = pca_scores[col]
        
        # Load ICP directly (no PCA - single tenor: 1Y)
        try:
            cn_data = pd.read_pickle(os.path.join(self.input_dir, 'database-px.pkl'))
            if 'ICP' in cn_data:
                icp_col = '中债商业银行同业存单到期收益率(AAA):1年'
                if icp_col in cn_data['ICP'].columns:
                    risk_factors['SPDL.ICP'] = cn_data['ICP'][icp_col]
        except Exception as e:
            print(f"Warning: Could not load ICP data: {e}")
        
        return risk_factors
    
    def _load_fx_factors(self, risk_factors: pd.DataFrame, 
                         macro_data: Dict) -> pd.DataFrame:
        """Load FX factors."""
        for currency in ["USD", "EUR", "JPY", "GBP"]:
            risk_factors[f"FXDL.{currency}CNY"] = macro_data["fx"][f"{currency}CNY.IB"]
        
        return risk_factors
    
    def _load_commodity_factors(self, risk_factors: pd.DataFrame,
                                macro_data: Dict) -> pd.DataFrame:
        """Load commodity factors."""
        for commodity in ["AU.SHF", "AL.SHF", "CU.SHF", "SC.INE"]:
            ticker = commodity.split(".")[0]
            risk_factors[f"CMDL.{ticker}"] = macro_data["commodity"][commodity]
        
        return risk_factors
    
    def clear_cache(self):
        """Clear cached risk factors."""
        self._risk_factors_cache = None
