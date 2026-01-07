#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Aug 29 22:47:32 2022

@author: mayunfei
"""

""" Bootstrapping the yield curve """
import math
import numpy as np  

class BootstrapYieldCurve(object):
    
    def __init__(self):
        self.zero_rates = dict()  # Map each T to a zero rate
        self.instruments = dict()  # Map each T to an instrument
        
    def add_instrument(self, par, T, coup, price,
                       freq): #compounding_freq=2):
        """  Save instrument info by maturity """
        self.instruments[T] = (par, coup, price, freq)#compounding_freq)
    
    def get_zero_rates(self):
        """  Calculate a list of available zero rates """
        maturities = self.get_maturities()
        if not maturities:
            return []
        self.__bootstrap_zero_coupons__(maturities)
        self.__get_bond_spot_rates__(maturities)
        return [100*self.zero_rates[T] for T in maturities]
        
    def get_maturities(self):
        """ Return sorted maturities from added instruments. """
        return sorted(self.instruments.keys())
        
    def __bootstrap_zero_coupons__(self, maturities=None):
        """ Get zero rates from zero coupon bonds """
        if maturities is None:
            maturities = self.get_maturities()
        for T in maturities:
            (par, coup, price, freq) = self.instruments[T]
            if coup == 0:
                self.zero_rates[T] = \
                    self.zero_coupon_spot_rate(par, price, T)
                    
    def __get_bond_spot_rates__(self, maturities=None):
        """ Get spot rates for every marurity available """
        if maturities is None:
            maturities = self.get_maturities()
        for T in maturities:
            par, coup, price, freq = self.instruments[T]
            if coup != 0:
                self.zero_rates[T] = self.__calculate_bond_spot_rate__(T, (par, coup, price, freq))
                
    def __calculate_bond_spot_rate__(self, T, instrument):
        """ Get spot rate of a bond by bootstrapping """
        #try:
        (par, coup, price, freq) = instrument
        periods = T * freq  # Number of coupon payments
        value = price
        per_coupon = coup / freq  # Coupon per period
              
        if self.zero_rates:
            # Build sorted arrays only once per call
            items = sorted(self.zero_rates.items())
            x = np.fromiter((k for k, _ in items), dtype=float)
            y = np.fromiter((v for _, v in items), dtype=float)
        else:
            x = np.array([], dtype=float)
            y = np.array([], dtype=float)
        
        if int(periods) == 0:
            spot_rate = ((par+per_coupon)/value - 1)/T# math.exp(math.log((par+per_coupon)/value)/T)-1
        else:
            dt = 1/float(freq)
            n = int(periods)
            idxs = np.arange(n, dtype=float)
            x0s = T - int(T/dt)*dt + idxs*dt
            # Exclude exact zero maturities
            mask = x0s != 0.0
            if mask.any() and x.size > 0:
                # Linear interpolation of spot rates at coupon times
                # Handle extrapolation by clamping to edges
                rates = np.interp(x0s[mask], x, y, left=y[0], right=y[-1])
                discounts = (1.0 + rates) ** (-x0s[mask])
                value -= per_coupon * float(discounts.sum())
            # Derive spot rate for a particular maturity
            last_period = T
            spot_rate = math.exp(math.log((par+per_coupon)/value)/T)-1
        return spot_rate
            
    def zero_coupon_spot_rate(self, par, price, T):
        """ Get zero rate of a zero coupon bond """
        spot_rate = math.exp(math.log(par/price)/T)-1 
        return spot_rate

    def getIdx(self,x,x0):
        np_x = np.asarray(x)
        idx = (np.abs(np_x - x0)).argmin()
        return idx
    
    def linear_polation(self,x,y,x0):
        # Fast, stable linear interpolation using numpy, with edge clamping
        if len(x) == 0:
            raise ValueError("Empty support points for interpolation")
        x_arr = np.asarray(x, dtype=float)
        y_arr = np.asarray(y, dtype=float)
        order = np.argsort(x_arr)
        xs = x_arr[order]
        ys = y_arr[order]
        y0 = float(np.interp(x0, xs, ys, left=ys[0], right=ys[-1]))
        return y0

#%%
if __name__ == "__main__":
    yield_curve = BootstrapYieldCurve()
    # notional, maturity, coupon yield, dirty price, compound frequency
    yield_curve.add_instrument(100, 0.15, 0., 100.97,1)
    yield_curve.add_instrument(100, 0.4, 1.16, 100.616,1)
    yield_curve.add_instrument(100, 0.55, 3.03, 102.431,1)
    yield_curve.add_instrument(100, 0.98, 2.18, 100.796, 1)
    yield_curve.add_instrument(100, 1.09, 1.35, 101.144, 1)
    yield_curve.add_instrument(100, 1.56, 1.59, 100.949, 1)
    y = yield_curve.get_zero_rates()
    x = yield_curve.get_maturities()

    import matplotlib.pyplot as plt
    plt.plot(x, y)
    plt.title("Zero Curve")
    plt.ylabel("Zero Rate (%)")
    plt.xlabel("Maturity in Years")
    plt.show()