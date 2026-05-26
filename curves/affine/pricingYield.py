
# -*- coding: utf-8 -*-
"""
Optimized pricing and yield calculation functions.

Created on Fri Aug 12 10:54:06 2022
@author: 马云飞
Optimized for performance and simplicity
"""
import math
import numpy as np
import sympy as sp
import pandas as pd
from scipy import optimize
from dateutil.relativedelta import relativedelta

from curves.utils.calendar import getNextTradingDate
from settings.general import DateConfig
from curves.affine.affine import Affine, calAB_np

# Frequency mapping for better performance
FREQ_MAPPING = {1.0: 12, 2.0: 6, 4.0: 3}
def scheduleDate(mats, mate, name, f):
    """
    Generate schedule dates for bond payments.
    
    Args:
        mats: Start date
        mate: End date  
        name: Bond name
        f: Frequency (0.0, 1.0, 2.0, 4.0)
    
    Returns:
        pd.Series: Schedule dates
    """
    if f == 0.0 or '贴现' in name:
        schedule = [mats, mate]
    else:
        if f not in FREQ_MAPPING:
            print(f'Unsupported frequency f={f} for {name}')
            return pd.Series([mats, mate])
        
        schedule = [mats]
        N = FREQ_MAPPING[f]
        current_date = mats
        
        while current_date < mate:
            current_date = current_date + relativedelta(months=N)
            schedule.append(current_date)
    
    schedule = getNextTradingDate(schedule)
    return pd.Series(schedule)
 
def floaters(mats, mate, f):
    """
    Generate floating rate schedule.
    
    Args:
        mats: Start date
        mate: End date
        f: Days frequency
    
    Returns:
        list: Schedule dates
    """
    start_date = mats - relativedelta(days=1) if DateConfig.is_cn_workday(mats) else mats
    schedule = [DateConfig.prev_cn_workday(start_date)]
    current_date = schedule[0]
    
    while current_date + relativedelta(days=f) < mate:
        current_date = current_date + relativedelta(days=f)
        schedule.append(current_date)
    
    return schedule
    
def _pricing_objective(ytm, day, coup, schedule, f, p0):
    """Objective function for yield optimization."""
    return p0 - pricing(day, coup, schedule, f, ytm)[0]

def pricingYield(day, coup, schedule, f, p0):
    """
    Calculate yield to maturity using Newton's method.
    
    Args:
        day: Current date
        coup: Coupon rate
        schedule: Payment schedule
        f: Frequency
        p0: Current price
    
    Returns:
        float: Yield to maturity or NaN
    """
    flow_dates = schedule[schedule > day]
    
    if len(flow_dates) == 0:
        return np.nan
    
    def _is_reasonable(yield_value: float) -> bool:
        return np.isfinite(yield_value) and abs(float(yield_value)) <= 50.0

    try:
        root = optimize.newton(
            _pricing_objective,
            2.5,
            args=(day, coup, schedule, f, p0),
            maxiter=500,
        )
        if _is_reasonable(root):
            return float(root)
    except (RuntimeError, ValueError, OverflowError):
        pass

    # Fallback: bracket the economically plausible region and use a robust
    # bracketing solver. This avoids returning absurd yields when Newton lands
    # on a spurious root for long-dated/low-coupon bonds.
    bracket_points = [-5.0, -1.0, 0.0, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 50.0]
    values = []
    for y in bracket_points:
        try:
            values.append(_pricing_objective(y, day, coup, schedule, f, p0))
        except Exception:
            values.append(np.nan)

    for left, right, f_left, f_right in zip(bracket_points[:-1], bracket_points[1:], values[:-1], values[1:]):
        if not (np.isfinite(f_left) and np.isfinite(f_right)):
            continue
        if f_left == 0:
            return float(left)
        if f_right == 0:
            return float(right)
        if f_left * f_right < 0:
            try:
                root = optimize.brentq(
                    _pricing_objective,
                    left,
                    right,
                    args=(day, coup, schedule, f, p0),
                    maxiter=500,
                )
                if _is_reasonable(root):
                    return float(root)
            except Exception:
                continue

    return np.nan
        
def pricing(day, coup, schedule, freq, ytm):
    """
    Calculate bond price, clean price, duration, and convexity.
    
    Args:
        day: Current date 
        coup: Coupon rate %
        schedule: Payment schedule
        freq: Payment frequency
        ytm: Yield to maturity %
    
    Returns:
        tuple: (price, clean_price, modified duration, convexity)
    """
    flow_dates = schedule[schedule > day]
    schedule_idx = pd.Index(schedule)
    
    if len(flow_dates) == 0:
        return np.nan, np.nan, np.nan, np.nan
    
    # Get time calculations
    idx = schedule_idx.get_indexer([day], method='ffill')[0]
    
    if len(schedule) >= 2:
        TS = (schedule_idx[idx + 1] - schedule_idx[idx]).days
        dres = (schedule_idx[idx + 1] - day).days
    else:
        TS = 365
        dres = (flow_dates.iloc[0] - day).days
    
    YN = 365
    n_flows = len(flow_dates)
    discount_rate = ytm / freq / 100
    
    if n_flows == 1:  # Single payment
        nt = dres / YN if dres <= YN else dres / TS + math.floor(dres / TS)
        
        if dres <= YN:
            discount = 1 / (1 + discount_rate * nt)
        else:
            discount = (1 / (1 + discount_rate)) ** nt
            
        p = (100 + coup / freq) * discount
        d = nt / (1 + ytm / 100 / freq) # nt / freq / 100 * discount
        v = d * 2 * nt / freq / 100 * discount
        
    else:  # Multiple payments
        base_discount = 1 / (1 + discount_rate)
        nt = dres / TS + n_flows - 1
        
        # Principal payment
        m = 100 * (base_discount ** nt)
        p = m
        d = nt * m
        v = nt * (nt + 1) * m
        
        # Coupon payments - vectorized calculation
        time_factors = np.arange(n_flows) + dres / TS
        coupon_payments = coup / freq
        discounts = base_discount ** time_factors
        
        coupon_pv = coupon_payments * discounts
        p += np.sum(coupon_pv)
        d += np.sum(time_factors * coupon_pv)
        v += np.sum(time_factors * (time_factors + 1) * coupon_pv)
        
        # Normalize duration and convexity
        d = (1 / freq * base_discount) * d / p
        v = (1 / freq * base_discount) ** 2 * v / p
    
    # Accrued interest
    accrued = coup / freq * (1 - dres / TS)
    clean_price = p - accrued
    
    return p, clean_price, d, v

def pricingAffine(day, coup, tax, schedule, freq, factors, S2, gamma, mtype, caltype):
    """
    Calculate bond price using affine term structure model.
    
    Args:
        day: Current date
        coup: Coupon rate
        tax: Tax rate
        schedule: Payment schedule
        freq: Payment frequency
        factors: Risk factors
        S2, gamma, mtype, caltype: Affine model parameters
    
    Returns:
        tuple: (price, clean_price, sensitivity)
    """
    flow_dates = schedule[schedule > day]
    
    if len(flow_dates) == 0:
        return np.nan, np.nan, np.nan * factors
    
    i = flow_dates.index[0]
    dres = (flow_dates.loc[i] - day).days
    
    if i == 0:
        i = 1
    
    TS = (schedule.loc[i] - schedule.loc[i - 1]).days
    n_flows = len(flow_dates)
    
    # Pre-extract numpy arrays for fast inner loop
    if isinstance(S2, sp.MatrixBase):
        S2_flat = tuple(float(S2[r,c]) for r in range(3) for c in range(3))
    else:
        S2_flat = tuple(float(v) for v in np.asarray(S2).ravel())
    gamma_f = float(gamma)
    if isinstance(factors, sp.MatrixBase):
        x_arr = np.array([float(factors[j]) for j in range(3)])
    else:
        x_arr = np.asarray(factors, dtype=float).ravel()

    # Compute taus in days
    time_indices = np.arange(n_flows)
    taus_days = time_indices * TS + dres

    # Vectorized: compute a and B for all cashflow dates
    p = 0.0
    s = np.zeros(3)
    coupon_pv_sum = 0.0   # sum of all coupon present values (for tax adjustment)
    s_coupon = np.zeros(3)  # factor sensitivity of coupon_pv_sum
    for t in range(n_flows):
        tau_d = taus_days[t]
        tau_y = tau_d / 365.0
        a, B = calAB_np(gamma_f, tau_y, S2_flat, mtype)
        y = a + B @ x_arr
        discount = 1.0 / (1.0 + y / freq / 100.0)
        discount_factor = discount ** (tau_d / TS)
        
        coupon_pv = coup / freq * discount_factor
        p += coupon_pv
        contrib = B * tau_y * coupon_pv
        s -= contrib
        coupon_pv_sum += coupon_pv
        s_coupon -= contrib
    
    # Principal payment (reuse last computed values)
    final_tau_d = taus_days[-1]
    final_tau_y = final_tau_d / 365.0
    a, B = calAB_np(gamma_f, final_tau_y, S2_flat, mtype)
    y = a + B @ x_arr
    discount = 1.0 / (1.0 + y / freq / 100.0)
    principal_discount = discount ** (final_tau_d / TS)
    
    p0 = 100.0 * principal_discount
    p += p0
    s -= B * final_tau_y * p0
    
    # Tax adjustment: CGB coupon income is exempt from 25% corporate tax.
    # Banks value each coupon at full face value (no tax haircut), so the
    # additional price premium equals:  tax_rate * PV(all coupons)
    if tax > 0:
        p += tax * coupon_pv_sum
        s += tax * s_coupon
    
    # Accrued interest
    accrued = coup / freq * (1.0 - dres / TS)
    clean_price = p - accrued
    
    # Return sensitivity as sympy Matrix(1,3) for backward compatibility
    s_sp = sp.Matrix([s.tolist()])
    return p, clean_price, s_sp / 1e2
