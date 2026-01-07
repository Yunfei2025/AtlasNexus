# -*- coding: utf-8 -*-
"""
Object-Oriented Backtesting Module for Bonds and IRS Contracts

Architecture:
- CampisiAttribution base class with specialized subclasses
- Backtester classes encapsulating valuation and attribution
- PerformanceMetrics class for analytics
- Improved separation of concerns and testability

@author: CMBC
"""
import os
import sys
import pathlib
from typing import Tuple, Dict, Union, Optional
from datetime import date
from abc import ABC, abstractmethod
import pandas as pd
import numpy as np

# Add project root to path
PATH = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(PATH))

from settings.paths import DIR_INPUT
from settings.general import DateConfig
from settings.fixed_income import IRSConfig
from curves.affine.pricingYield import pricing
from curves.calibration.selector import extract_bond_info, prepare_bond_schedule
from curves.calibration.irscurves import irsContract, genIRSCurves, px2Fixings, str2tenor, interpolate_with_extrapolation
from curves.utils.loader import loadCNBDTS


# ============================================================
# ATTRIBUTION CLASSES
# ============================================================

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
                 coupon: float, frequency: int = 2, schedule=None):
        """
        Initialize bond attribution.
        
        Parameters:
        -----------
        coupon : float
            Annual coupon rate (in percentage)
        frequency : int
            Payment frequency per year
        schedule : object, optional
            Bond cashflow schedule for repricing
        """
        super().__init__(prices, yields, durations)
        self.coupon = coupon
        self.frequency = frequency
        self.schedule = schedule
    
    def calculate(self) -> pd.DataFrame:
        """Calculate bond attribution using carry, roll-down, rate change decomposition."""
        for i in range(1, len(self.prices)):
            t0, t1 = self.prices.index[i-1], self.prices.index[i]
            days = (t1 - t0).days
            
            price_chg = self.prices.iloc[i] - self.prices.iloc[i-1]
            yield_chg = self.rates.iloc[i] - self.rates.iloc[i-1]
            
            # Carry: Accrued interest
            carry = (self.coupon / 365.0) * days
            
            # Roll-down: Time passage effect
            duration_t0 = self.durations.iloc[i-1]
            yield_t0 = self.rates.iloc[i-1]
            
            if self.schedule is not None:
                try:
                    _, clean_rolled, _, _ = pricing(t1, self.coupon, self.schedule, 
                                                    self.frequency, yield_t0)
                    roll_down = float(clean_rolled) - float(self.prices.iloc[i-1])
                except Exception:
                    roll_down = (yield_t0 / 100.0) * float(self.prices.iloc[i-1]) * (days / 365.0) - carry
            else:
                roll_down = (yield_t0 / 100.0) * float(self.prices.iloc[i-1]) * (days / 365.0) - carry
            
            # Rate change: DV01 impact
            rate_change = -duration_t0 * (yield_chg / 100.0) * self.prices.iloc[i-1]
            
            # Residual
            total_return = price_chg + carry
            residual = total_return - carry - roll_down - rate_change
            
            self.attribution.loc[t1, 'Carry'] = carry
            self.attribution.loc[t1, 'Roll-down'] = roll_down
            self.attribution.loc[t1, 'Rate Change'] = rate_change
            self.attribution.loc[t1, 'Residual'] = residual
            self.attribution.loc[t1, 'Total Return'] = total_return
            self.attribution.loc[t1, 'Price Change'] = price_chg
            self.attribution.loc[t1, 'Rate Change (bp)'] = yield_chg * 100.0
        
        return self.attribution


class IRSAttribution(CampisiAttribution):
    """Campisi Attribution for Interest Rate Swaps."""
    
    def __init__(self, pnl_series: pd.Series, quotes: pd.Series, durations: pd.Series,
                 curve_type: str, start_date: date, contract_end: date, notional: float = 1.0):
        """
        Initialize IRS attribution.
        
        Parameters:
        -----------
        curve_type : str
            Curve type ('r7d' or 's3m')
        start_date : date
            Contract start date
        contract_end : date
            Contract maturity date
        notional : float
            Contract notional amount
        """
        super().__init__(pnl_series, quotes, durations)
        self.curve_type = curve_type
        self.start_date = start_date
        self.contract_end = contract_end
        self.notional = notional
        self.capital = notional * 1e4
        
        # Load curve data
        curve_data = pd.read_pickle(os.path.join(DIR_INPUT, 'IRS-cvdata.pkl'))
        self.spot_curves = curve_data[curve_type]['spot']
        self.fwd_curves = curve_data[curve_type].get('forward', None)
        
        # Tenor cache
        self.tenor_cache = {}
    
    def _get_interpolated_rate(self, curve_data: pd.Series, target_term: float) -> float:
        """Interpolate rate from curve at target term using cached tenors."""
        if len(curve_data) < 1:
            return np.nan
        
        tenor_key = tuple(curve_data.index)
        if tenor_key not in self.tenor_cache:
            self.tenor_cache[tenor_key] = str2tenor(list(curve_data.index))
        
        tenor_numeric = self.tenor_cache[tenor_key]
        rate = interpolate_with_extrapolation(tenor_numeric, curve_data.values, [target_term])[0]
        return rate
    
    def calculate(self) -> pd.DataFrame:
        """Calculate IRS attribution with carry, roll-down, rate change decomposition."""
        for i in range(1, len(self.prices)):
            t0, t1 = self.prices.index[i-1], self.prices.index[i]
            days = (t1 - t0).days
            dt_years = days / 365.0
            
            pnl = self.prices.iloc[i]
            quote_t0 = self.rates.iloc[i-1]
            quote_t1 = self.rates.iloc[i]
            rate_chg = quote_t1 - quote_t0
            duration_t0 = self.durations.iloc[i-1]
            
            # Remaining terms
            term_t0 = max(0.0, (self.contract_end - t0).days / 365.0)
            term_t1 = max(0.0, (self.contract_end - t1).days / 365.0)
            
            # 1. Carry: Net fixed vs floating accrual
            carry = 0.0
            if self.fwd_curves is not None and t0 in self.fwd_curves.index:
                fwd_t0 = self.fwd_curves.loc[t0].dropna()
                f_rate = self._get_interpolated_rate(fwd_t0, dt_years)
                if not np.isnan(f_rate):
                    carry = (quote_t0 - f_rate) / 100.0 * self.capital * dt_years
            
            # 2. Rate change: DV01 impact
            rate_impact = -duration_t0 * (rate_chg / 100.0) * self.capital
            
            # 3. Roll-down: NPV change from rolling down spot curve
            roll_down = None
            if t0 in self.spot_curves.index and term_t0 > 0 and term_t1 > 0:
                spot_t0 = self.spot_curves.loc[t0].dropna()
                if len(spot_t0) >= 2:
                    s_t0 = self._get_interpolated_rate(spot_t0, term_t0)
                    s_t1 = self._get_interpolated_rate(spot_t0, term_t1)
                    
                    if not np.isnan(s_t0) and not np.isnan(s_t1):
                        roll_down = -duration_t0 * (s_t1 - s_t0) / 100.0 * self.capital
            
            if roll_down is None:
                roll_down = (quote_t0 / 100.0) * self.capital * dt_years - carry
            
            # 4. Residual
            residual = pnl - carry - rate_impact - roll_down
            
            # Store results
            idx = self.attribution.index[i-1]
            self.attribution.loc[idx, 'Carry'] = carry
            self.attribution.loc[idx, 'Roll-down'] = roll_down
            self.attribution.loc[idx, 'Rate Change'] = rate_impact
            self.attribution.loc[idx, 'Residual'] = residual
            self.attribution.loc[idx, 'Total Return'] = pnl
            self.attribution.loc[idx, 'Rate Change (bp)'] = rate_chg * 100
        
        return self.attribution


# ============================================================
# PERFORMANCE METRICS CLASS
# ============================================================

class PerformanceMetrics:
    """Calculate and store performance metrics from PnL series."""
    
    def __init__(self, pnl: pd.Series, capital: float, trading_days: int = 252):
        """
        Initialize with PnL series.
        
        Parameters:
        -----------
        pnl : pd.Series
            Daily PnL series
        capital : float
            Initial capital/notional
        trading_days : int
            Trading days per year for annualization
        """
        self.pnl = pnl
        self.capital = capital
        self.trading_days = trading_days
        self.daily_ret = pd.to_numeric(pnl.fillna(0), errors='coerce').fillna(0) / capital
        self._metrics = None
    
    def calculate(self) -> pd.Series:
        """Calculate comprehensive performance metrics."""
        if self._metrics is not None:
            return self._metrics
        
        # Total return (compounded)
        prod_value = self.daily_ret.add(1).prod()
        total_return = float(prod_value) - 1.0
        
        # Annualized metrics
        ann_return = self.daily_ret.mean() * self.trading_days
        ann_vol = self.daily_ret.std(ddof=1) * np.sqrt(self.trading_days)
        
        # Sharpe ratio
        sharpe = ann_return / ann_vol if ann_vol != 0 else np.nan
        
        # Maximum drawdown
        cumret = self.daily_ret.add(1).cumprod()
        running_max = cumret.cummax()
        drawdown = cumret.div(running_max).sub(1)
        max_drawdown = float(drawdown.min())
        
        # Win rate
        win_rate = (self.daily_ret > 0).sum() / len(self.daily_ret) if len(self.daily_ret) > 0 else 0
        
        self._metrics = pd.Series({
            'Total Return': total_return,
            'Annualized Return': ann_return,
            'Annualized Volatility': ann_vol,
            'Sharpe Ratio': sharpe,
            'Max Drawdown': max_drawdown,
            'Win Rate': win_rate,
            'Total Days': len(self.daily_ret)
        })
        
        return self._metrics


# ============================================================
# BACKTESTER CLASSES
# ============================================================

class Backtester(ABC):
    """Abstract base class for backtesters."""
    
    def __init__(self, start: Union[pd.Timestamp, date], end: Union[pd.Timestamp, date]):
        """
        Initialize backtester with date range.
        
        Parameters:
        -----------
        start : pd.Timestamp or date
            Start date for backtest
        end : pd.Timestamp or date
            End date for backtest
        """
        self.start = start
        self.end = end
        self.pnl = None
        self.attribution = None
        self.metrics = None
    
    @abstractmethod
    def run(self) -> None:
        """Execute backtest. Must be implemented by subclasses."""
        pass
    
    def get_results(self) -> Dict:
        """Get backtest results as dictionary."""
        return {
            'pnl': self.pnl,
            'attribution': self.attribution,
            'metrics': self.metrics
        }


class BondBacktester(Backtester):
    """Backtester for fixed-rate bonds."""
    
    def __init__(self, bond: str, start: Union[pd.Timestamp, date], 
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
        self.clean_prices = None
        self.durations = None
        self.yields = None
        self.coupon = None
        self.frequency = None
        self.schedule = None
    
    def run(self) -> None:
        """Execute bond backtest with attribution."""
        # Load environment data
        btype = "CBond"
        env = pd.read_pickle(os.path.join(DIR_INPUT, f"{btype}-InstrumentInfo.pkl"))
        env_ts = pd.read_pickle(os.path.join(DIR_INPUT, f"{btype}-cvpx.pkl"))
        
        # Extract bond information
        bond_data = env.loc[self.bond]
        bond_info = extract_bond_info(bond_data)
        self.coupon, self.frequency, self.schedule = prepare_bond_schedule(bond_info)
        
        # Get YTM time series
        self.yields = env_ts["ytm_act"][self.bond].loc[self.start:self.end]
        
        # Collect prices and durations
        clean_prices = []
        durations = []
        for d in self.yields.index:
            _, clean, duration, _ = pricing(d, self.coupon, self.schedule, 
                                           self.frequency, self.yields.loc[d])
            clean_prices.append(clean)
            durations.append(duration)
        
        self.clean_prices = pd.Series(clean_prices, index=self.yields.index)
        self.durations = pd.Series(durations, index=self.yields.index)
        
        # Calculate PnL
        self.pnl = self.clean_prices.diff() + self.coupon / 365
        
        # Attribution analysis
        attributor = BondAttribution(self.clean_prices, self.yields, self.durations,
                                     self.coupon, self.frequency, self.schedule)
        self.attribution = attributor.calculate()
        
        # Performance metrics
        capital = 100  # Bond face value
        metrics_calc = PerformanceMetrics(self.pnl, capital)
        self.metrics = metrics_calc.calculate()


class IRSBacktester(Backtester):
    """Backtester for Interest Rate Swaps."""
    
    def __init__(self, irs: str, start: Union[pd.Timestamp, date], 
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
        
        # Attribution analysis
        attributor = IRSAttribution(self.pnl, self.quotes, self.durations,
                                    curve_type, self.start, contract_end, self.notional)
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


class PortfolioBacktester(Backtester):
    """Backtester for portfolios combining bonds and IRS positions."""
    
    def __init__(self, start: Union[pd.Timestamp, date], end: Union[pd.Timestamp, date]):
        """Initialize portfolio backtester."""
        super().__init__(start, end)
        self.positions = []
        self.weights = []
        self.component_results = {}
    
    def add_bond_position(self, bond: str, notional: float):
        """
        Add a bond position to the portfolio.
        
        Parameters:
        -----------
        bond : str
            Bond identifier (e.g., "190408.IB")
        notional : float
            Position notional in millions (positive for long, negative for short)
        """
        self.positions.append(('bond', bond, notional))
    
    def add_irs_position(self, irs: str, notional: float):
        """
        Add an IRS position to the portfolio.
        
        Parameters:
        -----------
        irs : str
            IRS instrument identifier (e.g., "FR007S1Y.IR")
        notional : float
            Position notional in millions (positive for receive-fixed/short, negative for pay-fixed/long)
        """
        self.positions.append(('irs', irs, notional))
    
    def run(self) -> None:
        """Execute portfolio backtest by running individual components and aggregating results."""
        portfolio_pnl = None
        total_capital = 0
        
        print(f"\nRunning portfolio backtest from {self.start} to {self.end}")
        print("=" * 80)
        
        # Run backtest for each position
        for i, (pos_type, instrument, notional) in enumerate(self.positions):
            print(f"\n[{i+1}/{len(self.positions)}] Processing {pos_type.upper()}: {instrument}")
            print(f"  Notional: {notional:,.2f} million")
            
            if pos_type == 'bond':
                # Bond position: notional in millions, scale to match face value
                backtester = BondBacktester(instrument, self.start, self.end)
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
                backtester = IRSBacktester(instrument, self.start, self.end, notional=abs(notional))
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


# ============================================================
# CONVENIENCE FUNCTIONS
# ============================================================

def backtest_bond_irs_portfolio(bond: str, irs: str, bond_notional: float, irs_notional: float,
                               start: Union[pd.Timestamp, date], end: Union[pd.Timestamp, date]) -> Dict:
    """
    Backtest a portfolio with bond and IRS positions.
    
    Parameters:
    -----------
    bond : str
        Bond identifier (e.g., "190408.IB")
    irs : str
        IRS instrument identifier (e.g., "FR007S1Y.IR")
    bond_notional : float
        Bond position notional in millions (positive for long, negative for short)
    irs_notional : float
        IRS position notional in millions (positive for receive-fixed, negative for pay-fixed)
    start : date or pd.Timestamp
        Backtest start date
    end : date or pd.Timestamp
        Backtest end date
    
    Returns:
    --------
    Dict : Portfolio backtest results including PnL, attribution, and metrics
    
    Example:
    --------
    # Long 100M bond, short 100M IRS (pay fixed rate)
    results = backtest_bond_irs_portfolio(
        bond="190408.IB", 
        irs="FR007S1Y.IR",
        bond_notional=100,      # Long 100M
        irs_notional=-100,      # Short 100M (pay fixed)
        start=date(2024, 1, 1),
        end=date(2024, 12, 31)
    )
    """
    portfolio = PortfolioBacktester(start, end)
    portfolio.add_bond_position(bond, bond_notional)
    portfolio.add_irs_position(irs, irs_notional)
    portfolio.run()
    
    return portfolio.get_results()


# ============================================================
# MAIN EXECUTION
# ============================================================

def main():
    """Main execution function demonstrating OOP backtesting framework."""
    # Get date mappings
    date_map = DateConfig.get_date_mappings()
    end = date_map['dp'].date()
    start = date_map['d3m'].date()
    
    print("=" * 80)
    print("BACKTESTING - BOND")
    print("=" * 80)
    
    # Example 1: Bond backtest using OOP
    bond = "190408.IB"
    bond_backtester = BondBacktester(bond, start, end)
    bond_backtester.run()
    
    print(f"\nBond: {bond}")
    print(f"Period: {start} to {end}")
    print("\nPerformance Metrics:")
    print(bond_backtester.metrics.to_string())
    
    print("\n" + "=" * 80)
    print("BACKTESTING - IRS")
    print("=" * 80)
    
    # Example 2: IRS backtest using OOP
    irs = "FR007S1Y.IR"
    notional = 1.0
    irs_backtester = IRSBacktester(irs, start, end, notional)
    irs_backtester.run()
    
    print(f"\nIRS: {irs}")
    print(f"Curve Type: {irs_backtester.metadata['curve_type']}")
    print(f"Contract Start: {irs_backtester.metadata['start']}")
    print(f"Contract Maturity: {irs_backtester.metadata['contract_end']}")
    print(f"Backtest Period: {irs_backtester.metadata['start']} to {irs_backtester.metadata['backtest_end']}")
    print(f"Term: {irs_backtester.metadata['term']:.2f} years")
    print(f"Notional: {irs_backtester.metadata['notional']}")
    print("\nPerformance Metrics:")
    print(irs_backtester.metrics.to_string())
    
    print("\n" + "-" * 80)
    print("CAMPISI ATTRIBUTION - Summary Statistics")
    print("-" * 80)
    print(irs_backtester.attribution[['Carry', 'Roll-down', 'Rate Change', 'Residual', 'Total Return']].describe().round(4))
    
    print("\n" + "-" * 80)
    print("CAMPISI ATTRIBUTION - Contribution Analysis")
    print("-" * 80)
    attr_sum, attr_pct = IRSAttribution(
        irs_backtester.pnl, irs_backtester.quotes, irs_backtester.durations,
        irs_backtester.metadata['curve_type'], irs_backtester.metadata['start'],
        irs_backtester.metadata['contract_end'], notional
    ).get_contribution_analysis()
    
    print("\nTotal Contribution by Component:")
    print(attr_sum.to_string())
    print("\nPercentage Contribution:")
    print(attr_pct.to_string() + " %")
    
    print("\n" + "-" * 80)
    print("CAMPISI ATTRIBUTION - Last 5 Days")
    print("-" * 80)
    print(irs_backtester.attribution.tail().round(4).to_string())
    
    print("\n" + "=" * 80)
    print("BACKTESTING - PORTFOLIO (Long Bond + Short IRS)")
    print("=" * 80)
    
    # Example 3: Portfolio backtest - Long 100M bond, Short 100M IRS (pay fixed)
    portfolio_results = backtest_bond_irs_portfolio(
        bond="190408.IB",
        irs="FR007S1Y.IR",
        bond_notional=100,    # Long 100 million
        irs_notional=-100,    # Short 100 million (pay fixed rate)
        start=start,
        end=end
    )
    
    print("\n" + "-" * 80)
    print("PORTFOLIO POSITIONS")
    print("-" * 80)
    print(portfolio_results['position_summary'].to_string(index=False))
    
    print("\n" + "-" * 80)
    print("PORTFOLIO PERFORMANCE METRICS")
    print("-" * 80)
    print(portfolio_results['metrics'].to_string())
    
    print("\n" + "-" * 80)
    print("PORTFOLIO ATTRIBUTION - Last 5 Days")
    print("-" * 80)
    if portfolio_results['attribution'] is not None:
        print(portfolio_results['attribution'].tail().round(4).to_string())
    
    print("\n" + "-" * 80)
    print("PORTFOLIO VS INDIVIDUAL COMPONENTS")
    print("-" * 80)
    comparison = pd.DataFrame({
        'Portfolio': [
            portfolio_results['metrics']['Total Return'],
            portfolio_results['metrics']['Annualized Return'],
            portfolio_results['metrics']['Annualized Volatility'],
            portfolio_results['metrics']['Sharpe Ratio'],
            portfolio_results['metrics']['Max Drawdown']
        ],
        'Bond Only': [
            bond_backtester.metrics['Total Return'] * 100,  # Scale to 100M
            bond_backtester.metrics['Annualized Return'] * 100,
            bond_backtester.metrics['Annualized Volatility'] * 100,
            bond_backtester.metrics['Sharpe Ratio'],
            bond_backtester.metrics['Max Drawdown'] * 100
        ],
        'IRS Only': [
            irs_backtester.metrics['Total Return'] * -100,  # Scale to -100M (pay fixed)
            irs_backtester.metrics['Annualized Return'] * -100,
            irs_backtester.metrics['Annualized Volatility'] * 100,  # Vol is always positive
            -irs_backtester.metrics['Sharpe Ratio'],  # Flip sign for pay-fixed
            irs_backtester.metrics['Max Drawdown'] * -100  # Flip for pay-fixed
        ]
    }, index=['Total Return', 'Ann. Return', 'Ann. Volatility', 'Sharpe Ratio', 'Max Drawdown'])
    print(comparison.round(6).to_string())
    
    return {
        'bond': bond_backtester.get_results(),
        'irs': irs_backtester.get_results(),
        'portfolio': portfolio_results
    }

#%%
if __name__ == "__main__":
    results = main()