# -*- coding: utf-8 -*-
"""
Risk factor loader for multi-asset portfolios.
"""
import os
import pandas as pd
from typing import Dict, Optional, Union
from pathlib import Path
from multiasset.pca_analyzer import PCARiskFactorAnalyzer, DeterministicRiskFactorAnalyzer


def _load_macro_artifact(input_dir: str):
    macro_path = os.path.join(input_dir, 'macro-px.pkl')
    try:
        return pd.read_pickle(macro_path)
    except Exception as exc:
        print(f"Warning: could not load macro data from {macro_path}: {exc}")
        return {
            "fx": pd.DataFrame(),
            "commodity": pd.DataFrame(),
        }


class RiskFactorLoader:
    """Loads and caches risk factor data."""
    
    def __init__(self, input_dir: Union[str, Path], use_deterministic: bool = True):
        """
        Initialize the risk factor loader.
        
        Args:
            input_dir: Directory containing curve and database files
            use_deterministic: If True, use deterministic factors; if False, use PCA-derived factors
        """
        self.input_dir = str(input_dir)
        self._risk_factors_cache: Optional[pd.DataFrame] = None
        self.use_deterministic = use_deterministic
        self.factor_analyzer = None
        self.pca_analyzer = None
        
        # Create analyzers for IR factors
        if use_deterministic:
            self.det_analyzer = DeterministicRiskFactorAnalyzer(input_dir)
        else:
            self.factor_analyzer = PCARiskFactorAnalyzer(input_dir)
            self.pca_analyzer = self.factor_analyzer
    
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
        
        macro_data = _load_macro_artifact(self.input_dir)
        risk_factors = pd.DataFrame()
        
        # Interest rate factors
        risk_factors = self._load_ir_factors(risk_factors)
        
        # Curve spread factors
        risk_factors = self._load_sp_factors(risk_factors)

        # Credit spread factors (CDB/LGB/MTN/ICP vs CGB)
        risk_factors = self._load_cr_factors(risk_factors)

        # FX factors
        risk_factors = self._load_fx_factors(risk_factors, macro_data)
        
        # Commodity factors
        risk_factors = self._load_commodity_factors(risk_factors, macro_data)

        # Equity index futures factors
        risk_factors = self._load_equity_factors(risk_factors, macro_data)
        
        # Drop NaN values
        # risk_factors = risk_factors.dropna()

        if not isinstance(risk_factors.index, pd.DatetimeIndex):
            risk_factors.index = pd.to_datetime(risk_factors.index)
        risk_factors = risk_factors.sort_index()

        self._risk_factors_cache = risk_factors
        return risk_factors

    def last_date(self) -> Optional[pd.Timestamp]:
        """Return the last date present in the loaded risk-factor data, or None."""
        rf = self._risk_factors_cache
        if rf is None or rf.empty:
            rf = self.load_risk_factors(use_cache=True)
        if rf is None or rf.empty:
            return None
        return pd.Timestamp(rf.index.max())

    def _load_ir_factors(self, risk_factors: pd.DataFrame) -> pd.DataFrame:
        """
        Load interest rate level, slope, and curvature factors.
        
        Uses either deterministic weights or PCA-derived components depending on configuration.
        """
        if self.use_deterministic:
            # Use deterministic (rule-based) factors
            det_scores = self.det_analyzer.calculate_full_history_deterministic_scores()
            
            if det_scores.empty:
                print("Warning: No deterministic scores computed for IR factors")
                return risk_factors
            
            # Map deterministic factor names to IR factor codes:
            # Level -> IRDL, Slope -> IRSL, Curvature -> IRCV
            factor_to_ir_map = {
                'Level': 'IRDL',
                'Slope': 'IRSL',
                'Curvature': 'IRCV',
            }
            
            for col in det_scores.columns:
                # Column format: Level.US, Slope.CN, etc.
                parts = col.split('.')
                if len(parts) == 2:
                    factor_name, country = parts
                    if factor_name in factor_to_ir_map:
                        ir_name = f"{factor_to_ir_map[factor_name]}.{country}"
                        risk_factors[ir_name] = det_scores[col]
        else:
            # Use PCA-derived factors
            factor_scores = self.factor_analyzer.calculate_full_history_pca_scores(n_components=3)
            
            if factor_scores.empty:
                print("Warning: No PCA-derived scores computed for IR factors")
                return risk_factors
            
            # Map PCA components to IR factor names:
            # PC1 -> IRDL (Level), PC2 -> IRSL (Slope), PC3 -> IRCV (Curvature)
            pc_to_ir_map = {
                'PC1': 'IRDL',
                'PC2': 'IRSL',
                'PC3': 'IRCV',
            }
            
            for col in factor_scores.columns:
                # Column format: PC1.US, PC2.CN, etc.
                parts = col.split('.')
                if len(parts) == 2:
                    pc_name, country = parts
                    if pc_name in pc_to_ir_map:
                        ir_name = f"{pc_to_ir_map[pc_name]}.{country}"
                        risk_factors[ir_name] = factor_scores[col]
        
        return risk_factors
    
    def _load_sp_factors(self, risk_factors: pd.DataFrame) -> pd.DataFrame:
        """
        Load spread level and slope factors.
        
        Uses either deterministic weights or PCA-derived components depending on configuration.
        For IRS and CDB: Level and Slope factors
        For ICP: Level factor only (single tenor)
        """
        if self.use_deterministic:
            # Use deterministic (rule-based) spread factors
            det_scores = self.det_analyzer.calculate_full_history_deterministic_spread_scores()
            
            if det_scores.empty:
                print("Warning: No deterministic spread scores computed")
                return risk_factors
            
            # Map deterministic factor names to spread factor codes:
            # Level -> SPDL, Slope -> SPSL
            factor_to_sp_map = {
                'Level': 'SPDL',
                'Slope': 'SPSL',
            }
            
            for col in det_scores.columns:
                # Column format: Level.CDB, Slope.IRS, Level.ICP, etc.
                parts = col.split('.')
                if len(parts) == 2:
                    factor_name, spread = parts
                    if factor_name in factor_to_sp_map:
                        sp_name = f"{factor_to_sp_map[factor_name]}.{spread}"
                        risk_factors[sp_name] = det_scores[col]
        else:
            # Use PCA-derived spread factors
            factor_scores = self.factor_analyzer.calculate_full_history_spread_pca_scores(n_components=2)
            
            if not factor_scores.empty:
                # Map PCA components to spread factor names:
                # PC1 -> SPDL (Level), PC2 -> SPSL (Slope)
                pc_to_sp_map = {
                    'PC1': 'SPDL',
                    'PC2': 'SPSL',
                }
                
                for col in factor_scores.columns:
                    # Column format: PC1.IRS, PC2.CDB, etc.
                    parts = col.split('.')
                    if len(parts) == 2:
                        pc_name, spread = parts
                        if pc_name in pc_to_sp_map:
                            sp_name = f"{pc_to_sp_map[pc_name]}.{spread}"
                            risk_factors[sp_name] = factor_scores[col]
            
            # Load ICP directly (no PCA decomposition needed for single tenor: 1Y)
            try:
                cn_data = pd.read_pickle(os.path.join(self.input_dir, 'database-px.pkl'))
                if 'ICP' in cn_data:
                    icp_col = '中债商业银行同业存单到期收益率(AAA):1年'
                    if icp_col in cn_data['ICP'].columns:
                        risk_factors['SPDL.ICP'] = cn_data['ICP'][icp_col]
            except Exception as e:
                print(f"Warning: Could not load ICP data: {e}")
        
        return risk_factors
    
    def _load_cr_factors(self, risk_factors: pd.DataFrame) -> pd.DataFrame:
        """
        Load credit spread level, slope, and curvature factors (CDB/LGB/MTN/ICP).

        Each universe's spread (own yield - CGB yield at matching tenor) uses its
        own tenor-aware weights (see DeterministicRiskFactorAnalyzer). Deterministic
        only — no PCA-mode credit factors are computed.
        """
        if not self.use_deterministic:
            return risk_factors

        det_scores = self.det_analyzer.calculate_full_history_deterministic_credit_scores()
        if det_scores.empty:
            print("Warning: No deterministic scores computed for credit factors")
            return risk_factors

        # Map deterministic factor names to credit factor codes:
        # Level -> CRDL, Slope -> CRSL, Curvature -> CRCV
        factor_to_cr_map = {
            'Level': 'CRDL',
            'Slope': 'CRSL',
            'Curvature': 'CRCV',
        }

        for col in det_scores.columns:
            # Column format: Level.CDB, Slope.LGB, etc.
            parts = col.split('.')
            if len(parts) == 2:
                factor_name, universe = parts
                if factor_name in factor_to_cr_map:
                    cr_name = f"{factor_to_cr_map[factor_name]}.{universe}"
                    risk_factors[cr_name] = det_scores[col]

        return risk_factors

    def _load_fx_factors(self, risk_factors: pd.DataFrame,
                         macro_data: Dict) -> pd.DataFrame:
        """Load FX factors."""
        fx_data = macro_data.get("fx") if isinstance(macro_data, dict) else None
        if not isinstance(fx_data, pd.DataFrame) or fx_data.empty:
            print("Warning: FX macro data unavailable; skipping FX factors")
            return risk_factors

        for currency in ["USD", "EUR", "JPY", "GBP"]:
            column_name = f"{currency}CNY.IB"
            if column_name in fx_data.columns:
                risk_factors[f"FXDL.{currency}CNY"] = fx_data[column_name]
            else:
                print(f"Warning: FX column {column_name} missing; skipping FXDL.{currency}CNY")
        
        return risk_factors
    
    def _load_commodity_factors(self, risk_factors: pd.DataFrame,
                                macro_data: Dict) -> pd.DataFrame:
        """Load commodity factors."""
        commodity_data = macro_data.get("commodity") if isinstance(macro_data, dict) else None
        if not isinstance(commodity_data, pd.DataFrame) or commodity_data.empty:
            print("Warning: commodity macro data unavailable; skipping commodity factors")
            return risk_factors

        for commodity in ["AU.SHF", "AG.SHF", "AL.SHF", "CU.SHF", "ZN.SHF", "SC.INE",
                          "RB.SHF", "LC.GFE", "SA.CZC", "JM.DCE", "EC.INE"]:
            ticker = commodity.split(".")[0]
            if commodity in commodity_data.columns:
                risk_factors[f"CMDL.{ticker}"] = commodity_data[commodity]
            else:
                print(f"Warning: commodity column {commodity} missing; skipping CMDL.{ticker}")
        
        return risk_factors
    
    def _load_equity_factors(self, risk_factors: pd.DataFrame,
                              macro_data: Dict) -> pd.DataFrame:
        """Load equity index futures factors (EQDL.*) from macro commodity data."""
        commodity_data = macro_data.get("commodity") if isinstance(macro_data, dict) else None
        if not isinstance(commodity_data, pd.DataFrame) or commodity_data.empty:
            print("Warning: commodity macro data unavailable; skipping equity factors")
            return risk_factors

        for equity in ["IF.CFE", "IC.CFE", "IH.CFE", "IM.CFE"]:
            ticker = equity.split(".")[0]
            if equity in commodity_data.columns:
                risk_factors[f"EQDL.{ticker}"] = commodity_data[equity]
            else:
                print(f"Warning: equity column {equity} missing; skipping EQDL.{ticker}")

        return risk_factors

    def clear_cache(self):
        """Clear cached risk factors."""
        self._risk_factors_cache = None
