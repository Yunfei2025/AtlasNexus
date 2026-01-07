# -*- coding: utf-8 -*-
"""
IRS Backtester Module

Implements backtesting for Interest Rate Swaps with Campisi attribution.

@author: CMBC
"""
from typing import Union
from datetime import date
import pandas as pd

from settings.fixed_income import IRSConfig
from settings.paths import DIR_INPUT
from curves.calibration.irscurves import irsContract, px2Fixings, str2tenor, interpolate_with_extrapolation
from curves.utils.loader import loadCNBDTS
from backtest.base import Backtester
from backtest.attribution import IRSAttribution
from backtest.metrics import PerformanceMetrics
import numpy as np
import os


class IRSBacktester(Backtester):
    """Backtester for Interest Rate Swaps."""
    
    def __init__(self, irs: str, btype: str, start: Union[pd.Timestamp, date], 
                 end: Union[pd.Timestamp, date], notional: float = 1.0):
        """
        Initialize IRS backtester.
        
        Parameters:
        -----------
        irs : str
            IRS instrument identifier (e.g., "FR007S1Y.IR")
        notional : float
            Contract notional amount
        """
        super().__init__(start, end)
        self.irs = irs
        self.btype = btype
        self.notional = notional
        self.metadata = {}
        self.quotes = None
        self.durations = None
    
    def run(self) -> None:
        """Execute IRS backtest with attribution."""
        # Load environment data
        env_ts = loadCNBDTS()['SwapTS']
        
        # Determine contract parameters
        curve_type = 'r7d' if 'FR007' in self.irs else 's3m'
        contract_end = self.start + IRSConfig.get_irs_terms()[self.irs]
        term = (pd.Timestamp(contract_end) - pd.Timestamp(self.start)).days / 365
        frequency = 0 if term < 0.25 else 4
        
        # Get quote time series
        self.quotes = env_ts[self.irs].loc[self.start:self.end]
        
        # Pre-allocate series
        self.pnl = pd.Series(index=self.quotes.index, dtype=float)
        self.durations = pd.Series(index=self.quotes.index, dtype=float)
        self.carry = pd.Series(index=self.quotes.index, dtype=float)
        self.rolldown = pd.Series(index=self.quotes.index, dtype=float)
        
        # Load curve data for carry and rolldown
        curve_data = pd.read_pickle(os.path.join(DIR_INPUT, 'IRS-cvdata.pkl'))
        spot_curves = curve_data[curve_type]['spot']
        fwd_curves = curve_data[curve_type].get('forward', None)
        tenor_cache = {}
        
        # Main valuation loop
        for d in self.quotes.index:
            fwddata = px2Fixings(d)
            fixing_ts = fwddata['fixing'][curve_type]
            spot_ts = fwddata['spot'][curve_type]
            fwd_date = fwddata['date']
            
            quote = self.quotes.loc[d]
            contract = irsContract(self.start, contract_end, quote, curve_type, frequency)
            contract.valuation(self.notional, fwd_date, fixing_ts, spot_ts)
            
            self.pnl.loc[d] = contract.PnL
            self.durations.loc[d] = contract.duration
        
        # Calculate carry and rolldown
        capital = self.notional * 1e4
        for i in range(1, len(self.quotes)):
            t0, t1 = self.quotes.index[i-1], self.quotes.index[i]
            days = (t1 - t0).days
            dt_years = days / 365.0
            
            quote_t0 = self.quotes.iloc[i-1]
            duration_t0 = self.durations.iloc[i-1]
            
            # Remaining terms
            term_t0 = max(0.0, (contract_end - t0).days / 365.0)
            term_t1 = max(0.0, (contract_end - t1).days / 365.0)
            
            # Carry: Net fixed vs floating accrual
            carry_val = 0.0
            if fwd_curves is not None and t0 in fwd_curves.index:
                fwd_t0 = fwd_curves.loc[t0].dropna()
                if len(fwd_t0) >= 1:
                    tenor_key = tuple(fwd_t0.index)
                    if tenor_key not in tenor_cache:
                        tenor_cache[tenor_key] = str2tenor(list(fwd_t0.index))
                    tenor_numeric = tenor_cache[tenor_key]
                    f_rate = interpolate_with_extrapolation(tenor_numeric, fwd_t0.values, [dt_years])[0]
                    if not np.isnan(f_rate):
                        carry_val = (quote_t0 - f_rate) / 100.0 * capital * dt_years
            
            # Rolldown: NPV change from rolling down spot curve
            rolldown_val = None
            if t0 in spot_curves.index and term_t0 > 0 and term_t1 > 0:
                spot_t0 = spot_curves.loc[t0].dropna()
                if len(spot_t0) >= 2:
                    tenor_key = tuple(spot_t0.index)
                    if tenor_key not in tenor_cache:
                        tenor_cache[tenor_key] = str2tenor(list(spot_t0.index))
                    tenor_numeric = tenor_cache[tenor_key]
                    s_t0 = interpolate_with_extrapolation(tenor_numeric, spot_t0.values, [term_t0])[0]
                    s_t1 = interpolate_with_extrapolation(tenor_numeric, spot_t0.values, [term_t1])[0]
                    
                    if not np.isnan(s_t0) and not np.isnan(s_t1):
                        rolldown_val = -duration_t0 * (s_t1 - s_t0) / 100.0 * capital
            
            if rolldown_val is None:
                rolldown_val = (quote_t0 / 100.0) * capital * dt_years - carry_val
            
            self.carry.iloc[i] = carry_val
            self.rolldown.iloc[i] = rolldown_val
        
        # Attribution analysis
        attributor = IRSAttribution(self.pnl, self.quotes, self.durations,
                                    self.carry, self.rolldown)
        self.attribution = attributor.calculate()
        
        # Performance metrics
        capital = self.notional * 1e4
        metrics_calc = PerformanceMetrics(self.pnl, capital)
        self.metrics = metrics_calc.calculate()
        
        # Store metadata
        self.metadata = {
            'irs': self.irs,
            'curve_type': curve_type,
            'start': self.start,
            'contract_end': contract_end,
            'backtest_end': self.end,
            'term': term,
            'frequency': frequency,
            'notional': self.notional
        }
