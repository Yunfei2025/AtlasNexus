"""
Optimized Bond Option Pricing System

@author: CMBC
Refactored for better performance, maintainability, and simplicity
"""
import os
import sys
import pandas as pd
import numpy as np
from scipy.stats import norm
from datetime import datetime
from typing import Union, Dict, Tuple, Optional
from dataclasses import dataclass
import warnings

# Ensure project root is on sys.path (…/bin-v2.9) so `curves` and `settings` imports work reliably
_THIS = os.path.abspath(__file__)
_PRICER_DIR = os.path.dirname(_THIS)
_DERIV_DIR = os.path.dirname(_PRICER_DIR)
_PROJECT_ROOT = os.path.dirname(_DERIV_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.append(_PROJECT_ROOT)

from .utils import parse_date, TimeStringConverter
import curves.affine.pricingYield as p
from settings.paths import DIR_INPUT, DIR_DATA


@dataclass
class OptionConfig:
    """Base configuration for options"""
    underlying: object
    exercise_date: str
    expiry_date: str
    eval_date: str
    strike: float
    strike_yield: Optional[float] = None
    notional: float = 20_000_000
    option_type: str = 'call'
    risk_free_rate: float = 0.01857 # Default 1.98%

    def get_time_to_expiry_years(self) -> float:
        """Calculate time to expiry in years"""
        start = parse_date(self.exercise_date)
        end = parse_date(self.expiry_date)
        return (end - start).days / 365.25

    def get_time_to_expiry_months(self) -> float:
        """Calculate time to expiry in months"""
        return self.get_time_to_expiry_years() * 12


class BondPricer:
    """Optimized bond pricing operations"""
    
    def __init__(self, bond):
        self.bond = bond
        self.name = bond.name
        self._schedule = None
        self._cached_metrics = {}

    @property
    def schedule(self):
        """Lazy load schedule to avoid unnecessary computation"""
        if self._schedule is None:
            self._schedule = p.scheduleDate(
                self.bond.loc['起息日期'], 
                self.bond.loc['到期日期'], 
                self.name, 
                self.bond.loc['每年付息次数']
            )
        return self._schedule

    def get_ytm(self, day: str) -> float:
        """Get yield to maturity with improved error handling"""
        cache_key = f"ytm_{day}"
        if cache_key in self._cached_metrics:
            return self._cached_metrics[cache_key]

        try:
            file_name = 'TBond-cvpx.pkl' if '国债' in self.name else 'CBond-cvpx.pkl'
            file_path = os.path.join(DIR_INPUT, file_name)
            ytm_data = pd.read_pickle(file_path)['ytm_act']
            ytm = ytm_data.loc[parse_date(day), self.name] / 100
        except Exception as e:
            print(f"Failed to get YTM from file: {e}")
            ytm = 1.6175  # 1.6175% as percentage
            print(f"Use default YTM = {ytm}%")
            ytm = ytm / 100  # Convert to decimal
        
        self._cached_metrics[cache_key] = ytm
        return ytm
        
    def ytm2px(self, day: str) -> Dict[str, float]:
        """Compute pricing metrics with caching. Robust to different p.pricing return shapes."""
        cache_key = f"metrics_{day}"
        if cache_key in self._cached_metrics:
            return self._cached_metrics[cache_key]

        ytm = self.get_ytm(day)
        clean = 100.0
        dur = 5.0
        try:
            result = p.pricing(
                parse_date(day),
                self.bond.loc['票面利率:%'],
                self.schedule,
                self.bond.loc['每年付息次数'],
                100 * ytm
            )
            # Simplified parsing - handle common cases
            if isinstance(result, (tuple, list)) and len(result) >= 2:
                clean = float(result[1]) if len(result) > 1 else float(result[0])
                dur = float(result[2]) if len(result) > 2 else 5.0
            elif np.isscalar(result):
                clean = float(result)
            else:
                clean, dur = 100.0, 5.0  # Use defaults
        except Exception as e:
            print(f"Warning: pricing fallback used ({e})")

        # Validate all metrics
        if np.isnan(ytm) or ytm <= 0:
            print(f"Warning: Invalid YTM {ytm}, using fallback 0.02")
            ytm = 0.02
        if np.isnan(clean) or clean <= 0:
            print(f"Warning: Invalid clean price {clean}, using fallback 100.0")
            clean = 100.0
        if np.isnan(dur) or dur <= 0:
            print(f"Warning: Invalid duration {dur}, using fallback 5.0")
            dur = 5.0
        
        metrics = {
            'ytm': ytm,
            'clean': clean,
            'duration': dur,
            'modified_duration': dur / (1 + ytm)
        }
        self._cached_metrics[cache_key] = metrics
        return metrics


class BlackOptionPricer:
    """Black-Scholes (lognormal) option pricing model"""
    
    @staticmethod
    def price_option(S: float, K: float, T: float, r: float, 
                    sigma: float, option_type: str = 'call', sigma_type: str = 'abs',
                    ) -> Dict[str, float]:
        """
        Black-Scholes (lognormal) option pricing with vectorized calculations
        """
        if T <= 0:
            # Handle expiration
            intrinsic = max((S - K) if option_type == 'call' else (K - S), 0)
            return {
                'price': intrinsic, 'delta': 0.0, 'gamma': 0.0,
                'vega': 0.0, 'theta': 0.0, 'rho': 0.0
            }
        
        if sigma_type == 'abs':
            sigma = sigma / S
        
        sqrt_T = np.sqrt(T)
        if S <= 0 or sigma <= 0 or K <= 0 or np.isnan(S) or np.isnan(sigma) or np.isnan(K):
            return {'price': 0.0, 'delta': 0.0, 'gamma': 0.0, 'vega': 0.0, 'theta': 0.0, 'rho': 0.0}

        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
        d2 = d1 - sigma * sqrt_T
        
        # Check for NaN in d1, d2 calculations
        if np.isnan(d1) or np.isnan(d2):
            return {'price': 0.0, 'delta': 0.0, 'gamma': 0.0, 'vega': 0.0, 'theta': 0.0, 'rho': 0.0}
        discount = np.exp(-r * T)

        if option_type == 'call':
            price = S * norm.cdf(d1) - K * discount * norm.cdf(d2)
            delta = norm.cdf(d1)
            rho = K * T * discount * norm.cdf(d2) / 100  # Per 1% rate change
        else:
            price = K * discount * norm.cdf(-d2) - S * norm.cdf(-d1)
            delta = -norm.cdf(-d1)
            rho = -K * T * discount * norm.cdf(-d2) / 100

        gamma = norm.pdf(d1) / (S * sigma * sqrt_T)
        vega = S * norm.pdf(d1) * sqrt_T / 100  # Per 1% vol change
        theta = (-S * norm.pdf(d1) * sigma / (2 * sqrt_T)
                 - r * K * discount * norm.cdf(d2 if option_type == 'call' else -d2)) / 365

        return {
            'price': price, 'delta': delta, 'gamma': gamma,
            'vega': vega, 'theta': theta, 'rho': rho
        }

class NormalOptionPricer:
    """Bachelier (normal) model for options (appropriate for yield options)."""
    @staticmethod
    def price_option(S: float, K: float, T: float, r: float, sigma: float, option_type: str = 'call') -> Dict[str, float]:
        # Edge cases
        if T <= 0 or sigma <= 0:
            intrinsic = max((S - K) if option_type == 'call' else (K - S), 0.0)
            return {'price': intrinsic, 'delta': 0.0, 'gamma': 0.0, 'vega': 0.0, 'theta': 0.0, 'rho': 0.0}
        sqrt_T = np.sqrt(T)
        denom = sigma * sqrt_T
        if denom <= 0:
            return {'price': 0.0, 'delta': 0.0, 'gamma': 0.0, 'vega': 0.0, 'theta': 0.0, 'rho': 0.0}
        d = (S - K) / denom
        Nd = norm.cdf(d)
        nd = norm.pdf(d)
        discount = np.exp(-r * T)
        if option_type == 'call':
            price = discount * ((S - K) * Nd + denom * nd)
            delta = discount * Nd
        else:
            price = discount * ((K - S) * norm.cdf(-d) + denom * nd)
            delta = -discount * norm.cdf(-d)
        gamma = discount * nd / denom
        vega = discount * sqrt_T * nd  # per 1 absolute sigma unit
        # Approximate theta (time decay) normal model (keeping simple):
        theta = -discount * nd * sigma / (2 * sqrt_T) / 365
        rho = -T * price / 100  # rough sensitivity per 1% rate
        return {'price': price, 'delta': delta, 'gamma': gamma, 'vega': vega, 'theta': theta, 'rho': rho}
    

class VolatilitySurface:
    """Simplified volatility surface handling"""
    
    def __init__(self):
        self.time_converter = TimeStringConverter()
        self.yield_vol = None
        self.price_vol = None
        self._cache = {}

    def _get_time_array(self, index):
        """Convert time index to array of years"""
        times = []
        for idx in index:
            try:
                times.append(self.time_converter.parse_time_string(idx))
            except ValueError:
                try:
                    times.append(float(idx))
                except ValueError:
                    times.append(float(idx) / 365.0)
        return np.array(times)

    def load_volatility_surface(self, bond, eval_date: str) -> Optional[pd.DataFrame]:
        """Load yield volatility surface from Excel"""
        cache_key = f"{bond.name}_{eval_date}"
        if cache_key in self._cache:
            self.yield_vol = self._cache[cache_key]
            return self.yield_vol

        term = f"{int(bond.loc['期限'])}Y"
        file_name = f"招商银行_{term}国债利率期权波动率曲面_{eval_date}.xlsx"
        file_path = os.path.join(DIR_DATA, 'vols', file_name)

        if not os.path.exists(file_path):
            print(f"Vol file not found: {file_path}")
            return None

        try:
            yield_vol_df = pd.read_excel(file_path).set_index('期权期限')
            if '标的' in yield_vol_df.columns:
                del yield_vol_df['标的']
            
            self.yield_vol = yield_vol_df
            self._cache[cache_key] = yield_vol_df
            print(f"✅ Loaded yield vol surface")
            return yield_vol_df
        except Exception as e:
            print(f"Error loading vol surface: {e}")
            return None

    def convert_to_price_strikes_and_volatility(self, bond, eval_date: str) -> Tuple[Optional[pd.DataFrame], float]:
        """
        Convert yield strikes to price strikes AND convert yield vol to price vol for BondOption
        Creates price_vol surface with price strikes and price volatilities
        """
        if self.yield_vol is None:
            return None, 1.0

        try:
            pricer = BondPricer(bond)
            metrics = pricer.ytm2px(eval_date)
            
            # Convert yield strikes to price strikes
            clean_prices = []
            for yield_strike in self.yield_vol.columns:
                _, clean, dur, _ = p.pricing(
                    parse_date(eval_date),
                    bond.loc['票面利率:%'],
                    pricer.schedule,
                    bond.loc['每年付息次数'],
                    100 * float(yield_strike)  # Convert to percentage for pricing
                )
                clean_prices.append(round(clean, 4))

            # Create price volatility surface
            bond_price = metrics['clean']
            mod_duration = metrics['modified_duration']
            
            # Convert yield vol to price vol: σ_price = P × MDur × σ_yield_decimal
            price_vol_abs = self.yield_vol.values * bond_price * mod_duration
            
            # Create new DataFrame with price strikes and price volatilities
            self.price_vol = pd.DataFrame(
                price_vol_abs,
                index=self.yield_vol.index,
                columns=clean_prices
            )
            
            sample_yield_vol = self.yield_vol.iloc[0,0] 
            sample_price_vol = self.price_vol.iloc[0,0]
            
            print(f"=== Yield → Price Conversion ===")
            print(f"Bond price: {bond_price:.4f}, Modified duration: {mod_duration:.4f}")
            print(f"Sample conversion: {sample_yield_vol*10000:.0f} bps yield → {sample_price_vol:.4f} price vol")
            print(f"Expected ~4% for 10Y bond: {sample_price_vol/bond_price*100:.2f}%")
            
            return self.price_vol, mod_duration
            
        except Exception as e:
            print(f"Error converting to price strikes/volatilities: {e}")
            return None, 1.0

    def _interpolate_surface(self, surface, strike: float, time_to_expiry: float, 
                           fallback: float, min_vol: float, vol_type: str) -> float:
        """Common interpolation logic for both surfaces"""
        from scipy.interpolate import RegularGridInterpolator
        
        strikes = np.array([float(col) for col in surface.columns])
        times = self._get_time_array(surface.index)
        
        interp_func = RegularGridInterpolator(
            (times, strikes), surface.values,
            method='linear', bounds_error=False, fill_value=fallback
        )
        
        vol = interp_func([time_to_expiry, strike])[0]
        if np.isnan(vol) or vol <= 0:
            print(f"Warning: Invalid {vol_type} volatility {vol}, using fallback {fallback}")
            vol = fallback
        
        print(f"{vol_type} vol: {vol:.4f} for strike {strike:.4f}")
        return max(vol, min_vol)

    def interpolate_volatility(self, strike: float, time_to_expiry: float) -> float:
        """Interpolate price volatility"""
        return self._interpolate_surface(
            self.price_vol, strike, time_to_expiry, 
            fallback=1.0, min_vol=0.1, vol_type="Price"
        )

    def interpolate_volatility_yield(self, yield_strike: float, time_to_expiry: float) -> float:
        """Interpolate yield volatility"""
        vol = self._interpolate_surface(
            self.yield_vol, yield_strike, time_to_expiry,
            fallback=0.005, min_vol=0.0001, vol_type="Yield"
        )
        print(f"  ({vol*10000:.0f} bps for yield {yield_strike*100:.4f}%)")
        return vol
     

class BaseOption(OptionConfig):
    """Base option class with common functionality"""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pricer = BondPricer(self.underlying)
        self.vol_surface = VolatilitySurface()

    def _get_base_results(self) -> Dict[str, Union[str, float]]:
        """Get common result fields"""
        return {
            'notional': self.notional,
            'option_type': self.option_type,
            'time_to_expiry': self.get_time_to_expiry_months(),
            'risk_free_rate': self.risk_free_rate
        }


class BondOption(BaseOption):
    """Simplified Bond Option implementation"""
    
    def __init__(self, strike_yield: Optional[float] = None,
                 strike: Optional[float] = None, **kwargs):
        """
        Initialize BondOption with either price strike or yield strike
        
        Args:
            strike_yield: Strike yield (percentage). If provided, converts to clean price strike
            **kwargs: Other parameters for BaseOption
        """
        # Normalize inputs: strike_yield given in percentage form (e.g. 1.6265) -> decimal
        if strike_yield is not None and strike_yield > 1:
            strike_yield_decimal = strike_yield / 100.0
        else:
            strike_yield_decimal = strike_yield

        # If only yield provided, approximate clean price strike via current bond price
        # (simpler than full re-pricing at strike yield for now)
        if strike is None and strike_yield_decimal is not None:
            # We will compute an approximate strike price later during pricing using current price
            strike = 0.0  # placeholder
        super().__init__(strike=strike if strike is not None else 0.0,
                         strike_yield=strike_yield_decimal,
                         **kwargs)
        self.strike = strike
        self.strike_yield = strike_yield_decimal
        

    def price_option(self) -> Dict[str, Union[str, float]]:
        """Simplified bond option pricing"""
        try:
            metrics = self.pricer.ytm2px(self.eval_date)
            T = self.get_time_to_expiry_years()
            
            # Approximate strike price from yield if needed
            if (self.strike is None or self.strike == 0.0) and self.strike_yield is not None:
                dy = self.strike_yield - metrics['ytm']
                self.strike = metrics['clean'] - metrics['modified_duration'] * metrics['clean'] * dy
            
            # Get volatility based on strike type
            self.vol_surface.load_volatility_surface(self.underlying, self.eval_date)
            
            if self.strike_yield is not None:
                # Yield strike: convert yield vol to price vol
                yield_vol = self.vol_surface.interpolate_volatility_yield(self.strike_yield, T)
                mod_dur = metrics['modified_duration']
                price_vol = mod_dur * yield_vol  # relative price vol
                abs_price_vol = metrics['clean'] * mod_dur * yield_vol  # absolute price vol
                print(f"[DEBUG] Yield vol: {yield_vol:.6f} ({yield_vol*10000:.2f} bps), ModDur: {mod_dur:.4f}, Rel price vol: {price_vol:.6f}, Abs price vol: {abs_price_vol:.4f}")
                volatility = abs_price_vol
            else:
                # Price strike: use price volatility
                self.vol_surface.convert_to_price_strikes_and_volatility(self.underlying, self.eval_date)
                volatility = self.vol_surface.interpolate_volatility(self.strike, T)
                price_vol = volatility / metrics['clean']
                yield_vol = None
            if np.isnan(volatility) or volatility <= 0:
                print(f"Warning: Invalid volatility {volatility}, using fallback 1.0")
                volatility = 1.0
            # Price option
            option_results = BlackOptionPricer.price_option(
                S=metrics['clean'], K=self.strike, T=T,
                r=self.risk_free_rate, sigma=volatility, option_type=self.option_type
            )
            # Scale results by notional
            notional_mult = self.notional / 100.0
            for key in ['price', 'delta', 'vega', 'theta', 'rho']:
                option_results[key] *= notional_mult
            option_results['gamma'] *= notional_mult / 100.0
            # Return combined results
            return {
                **self._get_base_results(),
                'strike': self.strike,
                'strike_yield': self.strike_yield,
                'underlying_price': metrics['clean'],
                'underlying_ytm': metrics['ytm'],
                'duration': metrics['modified_duration'],
                'volatility': price_vol,  # relative price volatility (ModDur * yield_vol)
                'yield_vol': yield_vol,   # yield volatility (decimal)
                **option_results
            }
            
        except Exception as e:
            print(f"Error pricing bond option: {e}")
            raise


class InterestRateOption(BaseOption):
    """Interest rate option with yield-based strikes"""
    
    def __init__(self, strike_yield: float, **kwargs):
        if strike_yield > 1:
            strike_yield = strike_yield / 100
        super().__init__(strike=strike_yield, **kwargs)
        self.strike_yield = strike_yield

    def price_option(self) -> Dict[str, Union[str, float]]:
        """Price interest rate option using yield volatility"""
        try:
            current_ytm = self.pricer.get_ytm(self.eval_date)
            T = self.get_time_to_expiry_years()
            
            # Get yield volatility (absolute, in yield units)
            self.vol_surface.load_volatility_surface(self.underlying, self.eval_date)
            yield_vol = self.vol_surface.interpolate_volatility_yield(self.strike_yield, T)
            if np.isnan(yield_vol) or yield_vol <= 0:
                print(f"Warning: Invalid yield volatility {yield_vol}, using fallback 0.005")
                yield_vol = 0.005

            # Price using normal (Bachelier) model on yields (do NOT scale sigma by S)
            option_results = NormalOptionPricer.price_option(
                S=current_ytm, K=self.strike_yield, T=T,
                r=self.risk_free_rate, sigma=yield_vol, option_type=self.option_type
            )

            # Retrieve bond metrics for translation to price space
            bond_metrics = self.pricer.ytm2px(self.eval_date)
            bond_price = bond_metrics['clean']
            mod_dur = bond_metrics['modified_duration']

            # DV01 factor: bond_price * mod_dur converts yield change to price change
            # Scale to notional (price quoted per 100 nominal units)
            scale = bond_price * mod_dur * (self.notional / 100.0)

            # Scale Greeks consistently (gamma scales with squared factor, etc.)
            scaled = {
                'price': option_results['price'] * scale,
                'delta': option_results['delta'] * scale,
                'gamma': option_results['gamma'] * scale * (bond_price * mod_dur),
                'vega': option_results['vega'] * scale,
                'theta': option_results['theta'] * scale,
                'rho': option_results['rho'] * scale,
            }

            return {
                **self._get_base_results(),
                'model': 'bachelier',
                'strike_yield': self.strike_yield,
                'underlying_ytm': current_ytm,
                'volatility': yield_vol,
                'duration': mod_dur,
                'bond_price': bond_price,
                **scaled
            }
            
        except Exception as e:
            print(f"Error pricing interest rate option: {e}")
            raise

