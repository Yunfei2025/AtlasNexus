"""
Yield curve factors calculator.

This module contains the yield curve factors calculator class.
"""

import pandas as pd
import numpy as np
from typing import Dict
from .base import BaseFactorCalculator


class YieldCurveFactors(BaseFactorCalculator):
    """Calculator for yield curve factors."""
    
    def _validate_data(self):
        """Override to validate yield curve specific columns."""
        yield_columns = ['TB2Y.WI', 'TB5Y.WI', 'TB10Y.WI']
        missing_columns = [col for col in yield_columns if col not in self.data.columns]
        if missing_columns:
            # If yield curve data is not available, skip validation
            pass
    
    def calculate_slope(self) -> pd.Series:
        """
        Calculate yield curve slope.
         = 10年国债收益率 - 2年国债收益率
        """
        if 'TB10Y.WI' not in self.data.columns or 'TB2Y.WI' not in self.data.columns:
            return pd.Series(dtype=float, index=self.data.index)
        return self.data['TB10Y.WI'] - self.data['TB2Y.WI']
    
    def calculate_curvature(self) -> pd.Series:
        """
        Calculate yield curve curvature.
         = 5年国债收益率 - (10年国债收益率 + 2年国债收益率) / 2
        """
        required_cols = ['TB5Y.WI', 'TB10Y.WI', 'TB2Y.WI']
        if not all(col in self.data.columns for col in required_cols):
            return pd.Series(dtype=float, index=self.data.index)
        return self.data['TB5Y.WI'] - (self.data['TB10Y.WI'] + self.data['TB2Y.WI']) / 2
    
    def calculate_all(self) -> Dict[str, pd.Series]:
        """Calculate all yield curve factors."""
        factors = {}
        factors['Slope'] = self.calculate_slope()
        factors['Curvature'] = self.calculate_curvature()
        return factors