#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Aug 29 22:47:32 2022

@author: mayunfei
"""

""" Bootstrapping the yield curve """
import math
import numpy as np
from functools import lru_cache
from scipy.optimize import brentq

class BootstrapYieldCurve(object):
    
    def __init__(self):
        self.zero_rates = dict()  # Map each T to a zero rate
        self.instruments = dict()  # Map each T to an instrument
        self._maturities_cache = None  # Cache for sorted maturities
        self._zero_rates_arrays = None  # Cache for interpolation arrays
        self._last_calculated_maturity = None  # Track incremental processing
        
    @lru_cache(maxsize=128)
    def _calculate_discount_factor(self, rate, time):
        """Cached discount factor calculation."""
        return (1.0 + rate) ** (-time)
    
    @lru_cache(maxsize=256)
    def _zero_coupon_spot_rate_cached(self, par, price, T):
        """Cached zero coupon spot rate calculation."""
        return math.exp(math.log(par/price)/T) - 1
        
    def add_instrument(self, par, T, coup, price, freq):
        """Save instrument info by maturity (tax-agnostic)."""
        # Store instrument without tax treatment (market/pre-tax cashflows)
        self.instruments[T] = (par, coup, price, freq)
        # Invalidate caches when new instruments are added
        self._maturities_cache = None
        self._zero_rates_arrays = None
        self._last_calculated_maturity = None
    
        
    def get_zero_rates(self):
        """Calculate a list of available zero rates with optimized processing."""
        maturities = self.get_maturities()
        if not maturities:
            return []
        
        # Process only new maturities if we have incremental data
        if self._last_calculated_maturity is not None:
            new_maturities = [T for T in maturities if T > self._last_calculated_maturity]
            if new_maturities:
                self.__bootstrap_zero_coupons__(new_maturities)
                self.__get_bond_spot_rates__(new_maturities)
        else:
            # Full processing
            self.__bootstrap_zero_coupons__(maturities)
            self.__get_bond_spot_rates__(maturities)
        
        if maturities:
            self._last_calculated_maturity = max(maturities)
        
        return [100 * self.zero_rates[T] for T in maturities]
        
    def get_maturities(self):
        """Return sorted maturities from added instruments with caching."""
        if self._maturities_cache is None:
            self._maturities_cache = sorted(self.instruments.keys())
        return self._maturities_cache
        
    def __bootstrap_zero_coupons__(self, maturities=None):
        """Get zero rates from zero coupon bonds with optimized calculations."""
        if maturities is None:
            maturities = self.get_maturities()
        
        # Batch process zero coupon bonds
        zero_coupon_instruments = []
        for T in maturities:
            (par, coup, price, freq) = self.instruments[T]
            if coup == 0:
                zero_coupon_instruments.append((T, par, price))
        
        # Vectorized calculation for multiple zero coupon bonds
        if zero_coupon_instruments:
            T_array = np.array([item[0] for item in zero_coupon_instruments])
            par_array = np.array([item[1] for item in zero_coupon_instruments])
            price_array = np.array([item[2] for item in zero_coupon_instruments])
            
            # Vectorized zero coupon rate calculation
            rates = np.exp(np.log(par_array / price_array) / T_array) - 1
            
            for i, T in enumerate(T_array):
                self.zero_rates[T] = rates[i]
                
        # Invalidate interpolation cache when new rates are added
        self._zero_rates_arrays = None
                    
    def __get_bond_spot_rates__(self, maturities=None):
        """Get spot rates for every maturity available with optimized processing."""
        if maturities is None:
            maturities = self.get_maturities()
        
        # Process only coupon-bearing bonds
        coupon_bonds = [(T, self.instruments[T]) for T in maturities 
                       if self.instruments[T][1] != 0]  # coup != 0
        
        for T, instrument in coupon_bonds:
            self.zero_rates[T] = self.__calculate_bond_spot_rate__(T, instrument)
                
    def __calculate_bond_spot_rate__(self, T, instrument):
        """Get spot rate of a bond by bootstrapping with performance optimizations."""
        (par, coup, price, freq) = instrument
        periods = T * freq  # Number of coupon payments
        value = price
        per_coupon = coup / freq  # Coupon per period (currency per 100 par)
              
        if coup == 0:  # Zero coupon bond
            return self._zero_coupon_spot_rate_cached(par, price, T)
        
        # Build interpolation arrays more efficiently
        if self.zero_rates:
            # Use cached arrays if possible
            if (self._zero_rates_arrays is None or 
                len(self._zero_rates_arrays[0]) != len(self.zero_rates)):
                # Build arrays only when necessary
                sorted_items = sorted(self.zero_rates.items())
                x = np.array([k for k, _ in sorted_items], dtype=np.float64)
                y = np.array([v for _, v in sorted_items], dtype=np.float64)
                self._zero_rates_arrays = (x, y)
            else:
                x, y = self._zero_rates_arrays
        else:
            x = np.array([], dtype=np.float64)
            y = np.array([], dtype=np.float64)
        
        dt = 1.0 / freq  # Avoid repeated division
        n = int(periods)
        
        if n > 0:
            # Pre-calculate coupon payment times using numpy
            # Align with bootstrap0: times from 0, dt, 2dt, ..., T-dt (+ remainder), excluding 0
            remainder = T - n * dt
            coupon_times = remainder + np.arange(n, dtype=np.float64) * dt  # length n, last < T
            
            # Exclude times extremely close to 0
            mask = coupon_times > 1e-10
            if np.any(mask):
                ct = coupon_times[mask]
                
                # Process known and unknown nodes more efficiently
                if x.size == 0:
                    known_disc_sum = 0.0
                    post_ct = ct
                else:
                    # Pre-calculate discount factors for known nodes
                    disc_known_nodes = np.power(1.0 + y, -x)
                    x_max = x[-1]
                    
                    # Split using vectorized operations
                    pre_mask = ct <= x_max
                    post_mask = ~pre_mask
                    
                    known_disc_sum = 0.0
                    if np.any(pre_mask):
                        known_ct = ct[pre_mask]
                        # Vectorized interpolation
                        known_discounts = np.interp(known_ct, x, disc_known_nodes)
                        known_disc_sum = np.sum(known_discounts)
                    
                    post_ct = ct[post_mask] if np.any(post_mask) else np.array([])
                
                # Subtract PV of known coupons
                if known_disc_sum > 0:
                    value -= per_coupon * known_disc_sum
                
                # Process post-maturity coupons with optimized solver
                if x.size == 0:
                    y_last = 0.0
                else:
                    y_last = y[-1]
                    
                if post_ct.size > 0:
                    # Optimized bisection solver with better initial bounds
                    def pv_with_r(r):
                        if x.size == 0:
                            z_t = np.full(post_ct.shape, r, dtype=np.float64)
                        else:
                            x0 = x[-1]
                            if abs(T - x0) < 1e-10:  # Nearly equal
                                z_t = np.full(post_ct.shape, r, dtype=np.float64)
                            else:
                                w = (post_ct - x0) / (T - x0)
                                z_t = y_last + (r - y_last) * w
                        
                        # Vectorized discount calculation
                        disc_post = np.power(1.0 + z_t, -post_ct)
                        pv_coupons = per_coupon * np.sum(disc_post)
                        
                        # Final cash flow at T
                        dT = (1.0 + r) ** (-T)
                        pv_final = (par + per_coupon) * dT
                        return pv_coupons + pv_final
                    
                    # Improved bracket selection
                    r_lo = max(-0.95, y_last - 0.1)
                    r_hi = y_last + 0.3
                    
                    # Fast bracket expansion with fewer evaluations
                    f_lo = pv_with_r(r_lo) - value
                    f_hi = pv_with_r(r_hi) - value
                    
                    expand_count = 0
                    while f_lo * f_hi > 0 and expand_count < 5:
                        r_lo = max(r_lo - 0.1, -0.99)
                        r_hi = min(r_hi + 0.1, 2.0)
                        f_lo = pv_with_r(r_lo) - value
                        f_hi = pv_with_r(r_hi) - value
                        expand_count += 1
                    
                    if f_lo * f_hi > 0:
                        # Fallback with flat extrapolation
                        if x.size > 0:
                            disc_last = np.power(1.0 + y_last, -post_ct)
                            value -= per_coupon * np.sum(disc_last)
                        return math.exp(math.log((par + per_coupon) / value) / T) - 1
                    
                    try:
                        return brentq(lambda r: pv_with_r(r) - value, r_lo, r_hi, xtol=1e-12, rtol=1e-12)
                    except ValueError:
                        return 0.5 * (r_lo + r_hi)
        
        # Final spot rate calculation (optimized)
        return math.exp(math.log((par + per_coupon) / value) / T) - 1
            
    def zero_coupon_spot_rate(self, par, price, T):
        """Get zero rate of a zero-coupon bond (pre-tax) - kept for backward compatibility."""
        return self._zero_coupon_spot_rate_cached(par, price, T)

    # --- Optimized Static Methods for Pricing ---
    @staticmethod
    def price_from_ytm(par, coup, T, freq, ytm):
        """Compute dirty price from YTM with pre-tax cashflows (market standard) - optimized.

        coup and ytm are annualized in percent. par is face value.
        """
        if T == 0:
            return par
        if coup == 0:
            return par / ((1.0 + ytm/100.0) ** T)
            
        # Optimized coupon bond pricing
        n = int(round(T * freq))
        if n <= 0:
            return par
            
        dt = 1.0 / freq
        c = coup / freq
        r = ytm / 100.0
        discount_factor = 1.0 / (1.0 + r)
        
        # Vectorized calculation for better performance
        periods = np.arange(1, n + 1, dtype=np.float64)
        discount_factors = np.power(discount_factor, periods * dt)
        
        # Calculate coupon payments
        coupon_payments = np.full(n, c, dtype=np.float64)
        coupon_payments[-1] += par  # Add principal to final payment
        
        # Calculate present value
        price = np.sum(coupon_payments * discount_factors)
        return float(price)

    @staticmethod  
    def price_from_ytm_tax_aware(par, coup, T, freq, ytm,
                                 coupon_tax_rate=0.25, tax_exempt=True,
                                 oid_mode='at_maturity'):
        """Compute dirty price from YTM with optional investor tax treatment - optimized.

        - Coupons: after-tax if not tax_exempt.
        - Zero/OID: if coup==0 and not tax_exempt, reduce redemption by tax on gain in a
          simplified 'at_maturity' mode. For coupon bonds, principal is untaxed.
        """
        if T == 0:
            return par
            
        eff_tax = 0.0 if tax_exempt else max(0.0, min(1.0, coupon_tax_rate))
        
        if coup == 0:
            if eff_tax == 0.0:
                return par / ((1.0 + ytm/100.0) ** T)
            if oid_mode == 'at_maturity':
                effective_redemption = par * (1.0 - eff_tax)
                return effective_redemption / ((1.0 + ytm/100.0) ** T)
            else:
                return par / ((1.0 + ytm/100.0) ** T)
        
        # Optimized coupon bond with tax considerations
        n = int(round(T * freq))
        if n <= 0:
            return par
            
        dt = 1.0 / freq
        c = coup / freq
        c_after = c * (1.0 - eff_tax)
        r = ytm / 100.0
        discount_factor = 1.0 / (1.0 + r)
        
        # Vectorized calculation
        periods = np.arange(1, n + 1, dtype=np.float64)
        discount_factors = np.power(discount_factor, periods * dt)
        
        # Tax-adjusted coupon payments
        coupon_payments = np.full(n, c_after, dtype=np.float64)
        coupon_payments[-1] += par  # Principal is untaxed
        
        price = np.sum(coupon_payments * discount_factors)
        return float(price)
    
    def clear_cache(self):
        """Clear all internal caches for memory management."""
        self._maturities_cache = None
        self._zero_rates_arrays = None
        self._last_calculated_maturity = None
        self._calculate_discount_factor.cache_clear()
        self._zero_coupon_spot_rate_cached.cache_clear()
    
        
    def get_cache_info(self):
        """Get cache statistics for monitoring."""
        return {
            'discount_factor_cache': self._calculate_discount_factor.cache_info(),
            'zero_coupon_cache': self._zero_coupon_spot_rate_cached.cache_info(),
            'maturities_cached': self._maturities_cache is not None,
            'zero_rates_arrays_cached': self._zero_rates_arrays is not None
        }#%%
if __name__ == "__main__":
    yield_curve = BootstrapYieldCurve()
    # notional, maturity, coupon yield, dirty price, compound frequency
    yield_curve.add_instrument(100, 0.1643, 0.0, 99.7900, 1)
    yield_curve.add_instrument(100, 0.4767, 0.0, 99.3699, 1)
    # Example with coupon-bearing bonds. By default tax_exempt=True (institutional exemption)
    yield_curve.add_instrument(100, 0.5698, 3.03, 102.4287, 1)
    yield_curve.add_instrument(100, 1.0, 2.18, 99.4564, 1)
    yield_curve.add_instrument(100, 1.3068, 3.12, 104.7392, 1)
    yield_curve.add_instrument(100, 1.5808, 1.59, 100.9527, 1)
    yield_curve.add_instrument(100, 2.5315, 1.45, 100.7693, 1)
    yield_curve.add_instrument(100, 4.4493, 1.43, 100.1431, 1)
    yield_curve.add_instrument(100, 9.5096, 1.61, 98.6066, 2.0)
    
    y = yield_curve.get_zero_rates()
    x = yield_curve.get_maturities()
    
    print("🚀 Bootstrap optimization test completed!")
    print(f"📊 Processed {len(x)} instruments")
    print(f"🎯 Zero rates range: {min(y):.3f}% to {max(y):.3f}%")

    try:
        import plotly.express as px
        import plotly.io as pio
        pio.renderers.default = 'browser'
        # Interactive zero curve with Plotly
        fig = px.line(x=x, y=y, markers=True,
                      title="Zero Curve",
                      labels={"x": "Maturity in Years", "y": "Zero Rate (%)"})
        # Hide legend (single series) and show the figure
        fig.update_traces(name="Zero Curve", showlegend=False)
        fig.show()
    except ImportError:
        print("📊 Plotly not available, skipping visualization")