# -*- coding: utf-8 -*-
"""
Portfolio Backtester Module

Implements portfolio backtesting combining bonds and IRS positions.

@author: CMBC
"""
from typing import Union, Dict
from datetime import date
import pandas as pd
import numpy as np

from backtest.base import Backtester
from backtest.bond import BondBacktester
from backtest.irs import IRSBacktester
from backtest.metrics import PerformanceMetrics


class PortfolioBacktester(Backtester):
    """Backtester for portfolios combining bonds and IRS positions."""
    
    def __init__(self, start: Union[pd.Timestamp, date], end: Union[pd.Timestamp, date]):
        """Initialize portfolio backtester."""
        super().__init__(start, end)
        self.positions = []
        self.weights = []
        self.component_results = {}
        self.total_capital = 0
    
    def add_bond_position(self, bond: str, btype: str, notional: float):
        """
        Add a bond position to the portfolio.
        
        Parameters:
        -----------
        bond : str
            Bond identifier (e.g., "190408.IB")
        notional : float
            Position notional in millions (positive for long, negative for short)
        """
        self.positions.append(('bond', btype, bond, notional))
    
    def add_irs_position(self, irs: str, btype: str, notional: float):
        """
        Add an IRS position to the portfolio.
        
        Parameters:
        -----------
        irs : str
            IRS instrument identifier (e.g., "FR007S1Y.IR")
        notional : float
            Position notional in millions (positive for receive-fixed/short, negative for pay-fixed/long)
        """
        self.positions.append(('irs', btype, irs, notional))
    
    def run(self) -> None:
        """Execute portfolio backtest by running individual components and aggregating results."""
        portfolio_pnl = None
        total_capital = 0
        
        print(f"\nRunning portfolio backtest from {self.start} to {self.end}")
        print("=" * 80)
        
        # Run backtest for each position
        for i, (pos_type, btype, instrument, notional) in enumerate(self.positions):
            print(f"\n[{i+1}/{len(self.positions)}] Processing {pos_type.upper()}: {instrument} ({btype})")
            print(f"  Notional: {notional:,.2f} million")
            
            if pos_type == 'bond':
                # Bond position: notional in millions, scale to match face value
                backtester = BondBacktester(instrument, btype, self.start, self.end)
                backtester.run()
                
                # Scale PnL by notional (in millions)
                scaled_pnl = backtester.pnl * (notional / 100)  # Convert from per 100 face value
                capital = abs(notional)
            
                self.component_results[f'bond_{instrument}'] = {
                    'backtester': backtester,
                    'scaled_pnl': scaled_pnl,
                    'capital': capital,
                    'notional': notional,
                    'type': 'bond'
                }
                
            elif pos_type == 'irs':
                # IRS position: notional in millions
                # Positive notional = receive fixed (short position) → gains when rates rise
                # Negative notional = pay fixed (long position) → gains when rates fall
                backtester = IRSBacktester(instrument, btype, self.start, self.end, notional=abs(notional))
                backtester.run()
                
                # IRS PnL is already scaled by notional
                # Apply sign: negative notional means we reverse the PnL sign (pay-fixed loses when rates rise)
                scaled_pnl = backtester.pnl * np.sign(notional)
                capital = abs(notional) * 1e4
                
                self.component_results[f'irs_{instrument}'] = {
                    'backtester': backtester,
                    'scaled_pnl': scaled_pnl,
                    'capital': capital,
                    'notional': notional,
                    'type': 'irs'
                }
            
            # Aggregate portfolio PnL
            if portfolio_pnl is None:
                portfolio_pnl = scaled_pnl.copy()
            else:
                # Align indices and add
                portfolio_pnl = portfolio_pnl.add(scaled_pnl, fill_value=0)
            
            total_capital += capital
            
            print(f"  Capital allocated: {capital:,.2f}")
            print(f"  Average daily PnL: {scaled_pnl.mean():,.4f}")
        
        # Store portfolio-level results
        self.pnl = portfolio_pnl
        self.total_capital = total_capital
        
        # Calculate portfolio metrics
        print(f"\n{'=' * 80}")
        print("Computing portfolio metrics...")
        metrics_calc = PerformanceMetrics(self.pnl, total_capital)
        self.metrics = metrics_calc.calculate()
        
        # Calculate portfolio attribution (weighted sum of components)
        self._calculate_portfolio_attribution()
        
        print("Portfolio backtest completed.\n")
    
    def _calculate_portfolio_attribution(self):
        """Calculate portfolio-level attribution by aggregating component attributions."""
        attribution_dfs = []
        
        for key, result in self.component_results.items():
            backtester = result['backtester']
            notional = result['notional']
            pos_type = result['type']
            
            if backtester.attribution is not None:
                # Scale attribution by notional
                if pos_type == 'bond':
                    scaled_attr = backtester.attribution * (notional / 100)
                elif pos_type == 'irs':
                    scaled_attr = backtester.attribution * np.sign(notional)
                
                attribution_dfs.append(scaled_attr)
        
        if attribution_dfs:
            # Sum all attributions (align by date)
            self.attribution = pd.concat(attribution_dfs, axis=0).groupby(level=0).sum()
        else:
            self.attribution = None
    
    def get_position_summary(self) -> pd.DataFrame:
        """Get summary of all positions in the portfolio."""
        summary_data = []
        
        for key, result in self.component_results.items():
            pos_type = result['type']
            notional = result['notional']
            backtester = result['backtester']
            
            instrument = backtester.bond if pos_type == 'bond' else backtester.irs
            avg_pnl = result['scaled_pnl'].mean()
            total_pnl = result['scaled_pnl'].sum()
            
            summary_data.append({
                'Instrument': instrument,
                'Type': pos_type.upper(),
                'Notional (M)': notional,
                'Capital': result['capital'],
                'Avg Daily PnL': avg_pnl,
                'Total PnL': total_pnl,
                'Position': 'Long' if notional > 0 else 'Short'
            })
        
        return pd.DataFrame(summary_data)
    
    def get_results(self) -> Dict:
        """Get comprehensive portfolio results."""
        return {
            'pnl': self.pnl,
            'attribution': self.attribution,
            'metrics': self.metrics,
            'components': self.component_results,
            'position_summary': self.get_position_summary(),
            'total_capital': self.total_capital
        }
