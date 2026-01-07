# -*- coding: utf-8 -*-
"""
Bond Backtester Module

Implements backtesting for fixed-rate bonds with Campisi attribution.

@author: CMBC
"""
import os
from typing import Union
from datetime import date
import pandas as pd

from settings.paths import DIR_INPUT
from curves.affine.pricingYield import pricing
from curves.calibration.selector import extract_bond_info, prepare_bond_schedule
from curves.calibration.irscurves import interpolate_with_extrapolation
from backtest.base import Backtester
from backtest.attribution import BondAttribution
from backtest.metrics import PerformanceMetrics


class BondBacktester(Backtester):
    """Backtester for fixed-rate bonds."""
    
    def __init__(self, bond: str, btype: str, start: Union[pd.Timestamp, date], 
                 end: Union[pd.Timestamp, date]):
        """
        Initialize bond backtester.
        
        Parameters:
        -----------
        bond : str
            Bond identifier (e.g., "190408.IB")
        """
        super().__init__(start, end)
        self.bond = bond
        self.btype = btype
        self.clean_prices = None
        self.durations = None
        self.yields = None
        self.ftp = None
        self.coupon = None
        self.frequency = None
        self.schedule = None

    def getyield(self) -> float:
        """Placeholder function for getting yield to maturity."""
        env_ts = pd.read_pickle(os.path.join(DIR_INPUT, f"{self.btype}-cvpx.pkl"))
        return env_ts["ytm_act"][self.bond].loc[self.start:self.end]
    
    def getftp(self) -> float:
        """Placeholder function for getting fund transfering price."""
        return self.yields.iloc[0]

    def run(self) -> None:
        """Execute bond backtest with attribution."""
        # Load environment data
        env = pd.read_pickle(os.path.join(DIR_INPUT, f"{self.btype}-InstrumentInfo.pkl"))

        
        # Extract bond information
        bond_data = env.loc[self.bond]
        bond_info = extract_bond_info(bond_data)
        self.coupon, self.frequency, self.schedule = prepare_bond_schedule(bond_info)
        
        # Get YTM time series
        self.yields = self.getyield()
        self.ftp = self.getftp()

        # Collect prices and durations
        clean_prices = []
        durations = []
        rolldowns = []
        day_del = pd.Series([d.days for d in self.yields.index.diff()], 
                           index=self.yields.index).fillna(0)
        
        # Load and cache curve data once
        curve_data = pd.read_pickle(os.path.join(DIR_INPUT, f"{self.btype}-cvdata.pkl"))
        
        # Pre-compute maturity date
        maturity_date = self.schedule.iloc[-1]
        
        # Convert yields to numpy array for faster access
        yields_values = self.yields.values
        day_del_values = day_del.values
        dates = self.yields.index
        dates = dates.intersection(curve_data['spot'].index)
        
        for i, d in enumerate(dates):
            # Use integer indexing for speed
            _, clean, modified_dur, _ = pricing(d, self.coupon, self.schedule, 
                                           self.frequency, yields_values[i])
            
            clean_prices.append(clean)
            durations.append(modified_dur)
            
            # Calculate roll-down using spot curve
            if i == 0:
                rolldowns.append(0.0)
            else:
                spot = curve_data['spot'].loc[d]
                d_del = day_del_values[i] / 365.0
                ttm = (maturity_date - d).days / 365.0
                ttm_pre = ttm + d_del
                
                # Interpolate spot rates (cache tenors/rates)
                spot_tenors = spot.index.values
                spot_rates = spot.values
                
                s_t0 = interpolate_with_extrapolation(spot_tenors, spot_rates, [ttm_pre])[0]
                s_t1 = interpolate_with_extrapolation(spot_tenors, spot_rates, [ttm])[0]
                
                # Duration-based roll-down
                dy = (s_t1 - s_t0) / 100.0
                rolldown = -modified_dur * dy * clean_prices[i-1]
                rolldowns.append(rolldown)

        self.clean_prices = pd.Series(clean_prices, index=dates)
        self.rolldown = pd.Series(rolldowns, index=dates)
        self.duration = pd.Series(durations, index=dates)
        # import pdb; pdb.set_trace()
        # Calculate PnL
        self.carry = (self.coupon / 365 - self.ftp / 365)*day_del
        self.pnl = self.clean_prices.diff() + self.carry
        
        # Attribution analysis
        attributor = BondAttribution(self.clean_prices, self.yields, self.duration,
                                     self.carry, self.rolldown, self.frequency, self.schedule)
        self.attribution = attributor.calculate()
        
        # Performance metrics
        capital = 100  # Bond face value
        metrics_calc = PerformanceMetrics(self.pnl, capital)
        self.metrics = metrics_calc.calculate()
