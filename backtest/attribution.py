# -*- coding: utf-8 -*-
"""
Attribution Analysis Classes

Implements Campisi Attribution Model for decomposing fixed income returns.

@author: CMBC
"""
import os
from typing import Tuple
from datetime import date
from abc import ABC, abstractmethod
import pandas as pd
import numpy as np

from settings.paths import DIR_INPUT
from curves.affine.pricingYield import pricing
from curves.calibration.irscurves import str2tenor, interpolate_with_extrapolation


class CampisiAttribution(ABC):
    """
    Abstract base class for Campisi Attribution Model.
    
    Decomposes returns into: Carry + Roll-down + Rate Change + Residual
    """
    
    def __init__(self, prices: pd.Series, rates: pd.Series, durations: pd.Series):
        """
        Initialize attribution with common data.
        
        Parameters:
        -----------
        prices : pd.Series
            Price or PnL series over time
        rates : pd.Series
            Interest rates/yields over time (in percent)
        durations : pd.Series
            Modified durations over time
        """
        self.prices = prices
        self.rates = rates
        self.durations = durations
        self.attribution = pd.DataFrame(
            index=prices.index[1:],
            columns=['Carry', 'Roll-down', 'Rate Change', 'Residual', 'Total Return', 'Rate Change (bp)'],
            dtype=float
        )
    
    @abstractmethod
    def calculate(self) -> pd.DataFrame:
        """Calculate attribution components. Must be implemented by subclasses."""
        pass
    
    def get_summary_stats(self) -> pd.DataFrame:
        """Get statistical summary of attribution components."""
        return self.attribution[['Carry', 'Roll-down', 'Rate Change', 'Residual']].describe()
    
    def get_contribution_analysis(self) -> Tuple[pd.Series, pd.Series]:
        """Get total and percentage contribution by component."""
        attr_sum = self.attribution[['Carry', 'Roll-down', 'Rate Change', 'Residual']].sum()
        attr_pct = (attr_sum / attr_sum.sum() * 100).round(2)
        return attr_sum, attr_pct


class BondAttribution(CampisiAttribution):
    """Campisi Attribution for fixed-rate bonds."""
    
    def __init__(self, prices: pd.Series, yields: pd.Series, durations: pd.Series,
                 carry: pd.Series, rolldown: pd.Series, frequency: int = 2, schedule=None):
        """
        Initialize bond attribution.
        
        Parameters:
        -----------
        prices : pd.Series
            Clean price series over time
        yields : pd.Series
            Yield to maturity series over time (in percent)
        durations : pd.Series
            Modified duration series over time
        carry : pd.Series
            Pre-calculated carry series
        rolldown : pd.Series
            Pre-calculated roll-down series
        frequency : int
            Payment frequency per year
        schedule : object, optional
            Bond cashflow schedule for repricing
        """
        super().__init__(prices, yields, durations)
        self.carry = carry
        self.rolldown = rolldown
        self.frequency = frequency
        self.schedule = schedule

    def calculate(self) -> pd.DataFrame:
        """Calculate bond attribution using carry, roll-down, rate change decomposition."""
        # Vectorized calculations
        price_chg = self.prices.diff()
        yield_chg = self.rates.diff()
        
        # Rate change: vectorized DV01 impact
        rate_change = -self.durations.shift(1) * (yield_chg / 100.0) * self.prices.shift(1)
        
        # Vectorized final calculations
        total_return = price_chg + self.carry
        residual = total_return - self.carry - self.rolldown - rate_change
        
        # Vectorized assignment
        self.attribution['Carry'] = self.carry
        self.attribution['Roll-down'] = self.rolldown
        self.attribution['Rate Change'] = rate_change
        self.attribution['Residual'] = residual
        self.attribution['Total Return'] = total_return
        self.attribution['Price Change'] = price_chg
        self.attribution['Rate Change (bp)'] = yield_chg * 100.0
        
        return self.attribution


class IRSAttribution(CampisiAttribution):
    """Campisi Attribution for Interest Rate Swaps."""
    
    def __init__(self, pnl_series: pd.Series, quotes: pd.Series, durations: pd.Series,
                 carry: pd.Series, rolldown: pd.Series):
        """
        Initialize IRS attribution.
        
        Parameters:
        -----------
        pnl_series : pd.Series
            PnL series over time
        quotes : pd.Series
            Quote series over time (in percent)
        durations : pd.Series
            Modified duration series over time
        carry : pd.Series
            Pre-calculated carry series
        rolldown : pd.Series
            Pre-calculated roll-down series
        """
        super().__init__(pnl_series, quotes, durations)
        self.carry = carry
        self.rolldown = rolldown
    
    def calculate(self) -> pd.DataFrame:
        """Calculate IRS attribution with carry, roll-down, rate change decomposition."""
        # Vectorized calculations
        pnl_chg = self.prices.diff()
        quote_chg = self.rates.diff()
        
        # Rate change: vectorized DV01 impact (capital already in carry/rolldown)
        # Use first carry value to infer capital
        capital = self.carry.iloc[1] * 365.0 / (self.rates.iloc[0] - 0.01) * 100.0 if self.carry.iloc[1] != 0 else 1e4
        rate_change = -self.durations.shift(1) * (quote_chg / 100.0) * capital
        
        # Vectorized final calculations
        total_return = self.prices
        residual = total_return - self.carry - self.rolldown - rate_change
        
        # Vectorized assignment
        self.attribution['Carry'] = self.carry
        self.attribution['Roll-down'] = self.rolldown
        self.attribution['Rate Change'] = rate_change
        self.attribution['Residual'] = residual
        self.attribution['Total Return'] = total_return
        self.attribution['Price Change'] = pnl_chg
        self.attribution['Rate Change (bp)'] = quote_chg * 100.0
        
        return self.attribution
