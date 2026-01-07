"""
Base factor calculator module.

This module contains the abstract base class for all factor calculators.
"""

import pandas as pd
import numpy as np
from abc import ABC, abstractmethod
from typing import Dict, Tuple, Union, List


class BaseFactorCalculator(ABC):
    """Abstract base class for all factor calculators."""
    
    def __init__(self, data: pd.DataFrame):
        """
        Initialize factor calculator with market data.
        
        Parameters:
        -----------
        data : pd.DataFrame
            Market data with OHLCV columns
        """
        self.data = data
        self._validate_data()
    
    def _validate_data(self):
        """Validate that required columns exist in data."""
        required_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        missing_columns = [col for col in required_columns if col not in self.data.columns]
        if missing_columns:
            raise ValueError(f"Missing required columns: {missing_columns}")
    
    @abstractmethod
    def calculate_all(self) -> Dict[str, pd.Series]:
        """Calculate all factors for this category."""
        pass