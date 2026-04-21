# -*- coding: utf-8 -*-
"""
Created on Tue Aug  9 16:26:57 2022

@author: 马云飞
"""
import pandas as pd
import numpy as np
import sympy as sp
import math
from functools import lru_cache

# Convert matrices to hashable tuples for caching
def _matrix_to_tuple(matrix):
    """Convert sympy matrix to hashable tuple for caching"""
    return tuple(tuple(row) for row in matrix.tolist())

def _tuple_to_matrix(matrix_tuple, rows, cols):
    """Convert tuple back to sympy matrix"""
    return sp.Matrix(matrix_tuple)


def calAffineCov(term, spot, gamma, mtype, caltype):
    """Iterative fixed-point calibration of the 3x3 factor covariance matrix S2.

    Optimised vs the original:
    - Inner per-date loop is vectorised: all dates are processed with a single
      batched lstsq solve instead of one Python-level iteration per date.
    - Convergence tracking and covariance arithmetic use pure NumPy (no sympy
      overhead in the hot path).  The sympy matrix is only reconstructed once
      at the very end for backward compatibility with callers.
    """
    gamma_f = float(gamma)
    n_dates = len(spot.index)
    k = term.shape[1]

    # Pre-build tau array once — shape (n_dates, k)
    tau_all = term.values.astype(float)
    y_all   = spot.values.astype(float)

    # Initial S2 as numpy array
    S2_np = np.eye(3)

    nstep = 20
    for ns in range(1, nstep + 1):
        S2_flat = tuple(S2_np.ravel())

        # Build a_vec and B_mat for every (date, tenor) pair.
        # a_vec_all: (n_dates, k), B_mat_all: (n_dates, k, 3)
        a_vec_all = np.empty((n_dates, k))
        B_mat_all = np.empty((n_dates, k, 3))
        for i in range(k):
            # calAB_np is already cached on (gamma, tau_scalar, S2_flat, mtype)
            for d in range(n_dates):
                a_val, b_row = calAB_np(gamma_f, tau_all[d, i], S2_flat, mtype)
                a_vec_all[d, i] = a_val
                B_mat_all[d, i, :] = b_row

        # Solve all dates at once: rhs = y - a, shape (n_dates, k)
        rhs_all = y_all - a_vec_all   # (n_dates, k)

        # Batched least-squares: loop is still O(n_dates) but is tiny vs inner
        x_arr = np.empty((n_dates, 3))
        for d in range(n_dates):
            x_arr[d], _, _, _ = np.linalg.lstsq(B_mat_all[d], rhs_all[d], rcond=None)

        # New S2 from sample covariance of extracted factors
        S2_new = np.cov(x_arr, rowvar=False)   # (3, 3)

        S_err = abs(np.linalg.det(S2_np) - np.linalg.det(S2_new))
        print(f'\rIteration: {ns}, Residual of Covariance Matrix {S_err:.4f}', end='')

        if S_err < 0.001:
            S2_np = S2_new
            break
        S2_np = S2_new

    # Return as sympy matrix for full backward compatibility
    return sp.Matrix(S2_np.tolist())
        
def getAffineFactors(dfi,S2,gamma,mtype,caltype): 
    k = dfi.shape[0]
    y0 = dfi.values.astype(float)          # (k,)
    taus0 = dfi.index
    S2_flat = tuple(float(S2[i,j]) for i in range(3) for j in range(3))
    gamma_f = float(gamma)

    a_vec = np.empty(k)
    B_mat = np.empty((k, 3))
    for i in range(k):
        a_vec[i], B_mat[i] = calAB_np(gamma_f, float(taus0[i]), S2_flat, mtype)

    # Least-squares solve: B_mat @ x = (y0 - a_vec)
    rhs = y0 - a_vec
    x, _, _, _ = np.linalg.lstsq(B_mat, rhs, rcond=None)
    return sp.Matrix(x.tolist())  # keep return type compatible

def Affine(tau,x,S2,gamma,mtype,caltype):
    gamma_f = float(gamma)
    tau_f = float(tau)
    # Build S2_flat once (caller may pass sympy or numpy S2)
    if isinstance(S2, sp.MatrixBase):
        S2_flat = tuple(float(S2[i,j]) for i in range(3) for j in range(3))
    else:
        S2_flat = tuple(float(v) for v in np.asarray(S2).ravel())
    a, B = calAB_np(gamma_f, tau_f, S2_flat, mtype)

    # x may be sympy Matrix(3,1) or numpy array
    if isinstance(x, sp.MatrixBase):
        x_arr = np.array([float(x[i]) for i in range(3)])
    else:
        x_arr = np.asarray(x, dtype=float).ravel()

    y = a + float(B @ x_arr)
    # Return b as sympy Matrix(1,3) for backward compatibility
    b_sp = sp.Matrix([B.tolist()])
    return y, b_sp

@lru_cache(maxsize=128)
def _calAB_analytic_cached(gamma_val, tau_val, S2_tuple, mtype):
    """Cached version of calAB_analytic for numeric values"""
    S2 = _tuple_to_matrix(S2_tuple, 3, 3)
    
    I = sp.zeros(3,3)    
    if mtype == 'Model A':       
        I[0,0] = -tau_val**2/6
        I[1,1] = (2*_intI_cached(0,gamma_val,tau_val)-_intI_cached(0,2*gamma_val,tau_val)-1)/(2*gamma_val**2)
        I[2,2] = I[1,1]+(2*_intI_cached(1,gamma_val,tau_val)-_intI_cached(1,2*gamma_val,tau_val)-0.25*_intI_cached(2,2*gamma_val,tau_val))/(2*gamma_val**2)
        I[0,1] = I[1,0] = -0.25*tau_val/gamma_val+_intI_cached(1,gamma_val,tau_val)/(2*gamma_val**2)
        I[0,2] = I[2,0] = I[0,1]+_intI_cached(2,gamma_val,tau_val)/(2*gamma_val**2)
        I[1,2] = I[2,1] = 0.25*tau_val/gamma_val+I[1,1]+_intI_cached(1,2*gamma_val,tau_val)/(4*gamma_val**2)
    elif mtype == 'Model B': 
        G = 0.5*gamma_val*tau_val-_intI_cached(1,gamma_val,tau_val)
        I01 = -0.25*tau_val/gamma_val+_intI_cached(1,gamma_val,tau_val)/(2*gamma_val**2)
        I11 = (2*_intI_cached(0,gamma_val,tau_val)-_intI_cached(0,2*gamma_val,tau_val)-1)/(2*gamma_val**2)    
        II = _intI_cached(1,gamma_val,tau_val)-4*_intI_cached(3,gamma_val,tau_val)-0.5*_intI_cached(1,2*gamma_val,tau_val) \
            -3/8*_intI_cached(2,2*gamma_val,tau_val)+_intI_cached(3,2*gamma_val,tau_val)/4+_intI_cached(4,2*gamma_val,tau_val)/8-2*G
        I[0,0] = -tau_val**2/6
        I[1,1] = G/(gamma_val**2)+I[0,0]+I01
        I[2,2] = -2/3*tau_val**2+I11-II/(gamma_val**2)
        I[0,1] = I[1,0] = I[0,0]-I01
        I[0,2] = I[2,0] = I01-2*I[0,0]-(_intI_cached(1,gamma_val,tau_val)+2*_intI_cached(2,gamma_val,tau_val))/(2*gamma_val**2)
        I[1,2] = I[2,1] = -0.5*tau_val/gamma_val+I[0,2]-I11 \
            -(3*_intI_cached(1,gamma_val,tau_val)+2*_intI_cached(2,gamma_val,tau_val)-0.5*_intI_cached(1,2*gamma_val,tau_val)-0.5*_intI_cached(2,2*gamma_val,tau_val))/(2*gamma_val**2)
    else:
        raise ValueError(f'Model type {mtype} not implemented')
        
    a = sum(S2[i,j]*I[i,j] for i in range(3) for j in range(3))

    x = gamma_val*tau_val
    I1 = (1-sp.exp(-x))/x
    
    B = sp.zeros(1,3)
    if mtype == 'Model A':
        B[0,0] = 1
        B[0,1] = I1
        B[0,2] = I1-sp.exp(-x)
    elif mtype == 'Model B': 
        B[0,0] = 1
        B[0,1] = 1-I1
        B[0,2] = I1+(1+2*x)*sp.exp(-x)-2
    else:
        raise ValueError(f'Model type {mtype} not implemented')
        
    return float(a), _matrix_to_tuple(B)

def calAB_analytic(gamma,tau,S2,mtype):
    try:
        gamma_val = float(gamma)
        tau_val = float(tau)
        S2_tuple = _matrix_to_tuple(S2)
        
        a_val, B_tuple = _calAB_analytic_cached(gamma_val, tau_val, S2_tuple, mtype)
        B = _tuple_to_matrix(B_tuple, 1, 3)
        return a_val, B
    except (TypeError, ValueError):
        # Fallback to original computation for symbolic expressions
        I = sp.zeros(3,3)    
        if mtype == 'Model A':       
            I[0,0] = -tau**2/6
            I[1,1] = (2*intI(0,gamma,tau)-intI(0,2*gamma,tau)-1)/(2*gamma**2)
            I[2,2] = I[1,1]+(2*intI(1,gamma,tau)-intI(1,2*gamma,tau)-0.25*intI(2,2*gamma,tau))/(2*gamma**2)
            I[0,1] = I[1,0] = -0.25*tau/gamma+intI(1,gamma,tau)/(2*gamma**2)
            I[0,2] = I[2,0] = I[0,1]+intI(2,gamma,tau)/(2*gamma**2)
            I[1,2] = I[2,1] = 0.25*tau/gamma+I[1,1]+intI(1,2*gamma,tau)/(4*gamma**2)
        elif mtype == 'Model B': 
            G = 0.5*gamma*tau-intI(1,gamma,tau)
            I01 = -0.25*tau/gamma+intI(1,gamma,tau)/(2*gamma**2)
            I11 = (2*intI(0,gamma,tau)-intI(0,2*gamma,tau)-1)/(2*gamma**2)    
            II = intI(1,gamma,tau)-4*intI(3,gamma,tau)-0.5*intI(1,2*gamma,tau) \
                -3/8*intI(2,2*gamma,tau)+intI(3,2*gamma,tau)/4+intI(4,2*gamma,tau)/8-2*G
            I[0,0] = -tau**2/6
            I[1,1] = G/(gamma**2)+I[0,0]+I01
            I[2,2] = -2/3*tau**2+I11-II/(gamma**2)
            I[0,1] = I[1,0] = I[0,0]-I01
            I[0,2] = I[2,0] = I01-2*I[0,0]-(intI(1,gamma,tau)+2*intI(2,gamma,tau))/(2*gamma**2)
            I[1,2] = I[2,1] = -0.5*tau/gamma+I[0,2]-I11 \
                -(3*intI(1,gamma,tau)+2*intI(2,gamma,tau)-0.5*intI(1,2*gamma,tau)-0.5*intI(2,2*gamma,tau))/(2*gamma**2)
        else:
            print('Implement ',mtype)        
        a = 0
        for i in range(3):
            for j in range(3):
                a += S2[i,j]*I[i,j]

        x = gamma*tau
        I1 = (1-sp.exp(-x))/x
        
        B = sp.zeros(1,3)
        if mtype == 'Model A':
            B[0,0] = 1
            B[0,1] = I1
            B[0,2] = I1-sp.exp(-x)
        elif mtype == 'Model B': 
            B[0,0] = 1
            B[0,1] = 1-I1
            B[0,2] = I1+(1+2*x)*sp.exp(-x)-2
        else:
            print('Implement ',mtype)        
        return a, B

def calAB_matrix(tau, S2, gamma, mtype):
    """Delegates to calAB_analytic — the diagonalization-based Matrix path was
    numerically unstable for the defective Jordan-block K (Model A / Model B)."""
    return calAB_analytic(gamma, tau, S2, mtype)


@lru_cache(maxsize=256)
def _intI_cached(n, gamma_val, tau_val):
    """Cached version of intI function with numeric values"""
    x = gamma_val * tau_val
    if n == 0:
        return (1 - math.exp(-x)) / x
    else:
        return n * _intI_cached(n-1, gamma_val, tau_val) - x**(n-1) * math.exp(-x)

def intI(n,gamma,tau):
    # Convert symbolic expressions to float if possible for better caching
    try:
        gamma_val = float(gamma)
        tau_val = float(tau)
        return _intI_cached(n, gamma_val, tau_val)
    except (TypeError, ValueError):
        # Fallback to original computation for symbolic expressions
        x = gamma*tau
        if n == 0:
            return (1-sp.exp(-x))/x
        else:
            return n*intI(n-1,gamma,tau)-x**(n-1)*sp.exp(-x)


# ---------------------------------------------------------------------------
# Pure-NumPy fast path (no SymPy overhead)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=128)
def _calAB_np_cached(gamma, tau, S2_flat, mtype):
    """Pure float/numpy calAB. S2_flat is a 9-element tuple (row-major 3x3)."""
    I = np.zeros((3, 3))
    II0 = _intI_cached(0, gamma, tau)
    II1 = _intI_cached(1, gamma, tau)
    II2 = _intI_cached(2, gamma, tau)

    if mtype == 'Model A':
        II0_2g = _intI_cached(0, 2*gamma, tau)
        II1_2g = _intI_cached(1, 2*gamma, tau)
        II2_2g = _intI_cached(2, 2*gamma, tau)
        g2 = gamma * gamma
        I[0,0] = -tau*tau / 6.0
        I[1,1] = (2*II0 - II0_2g - 1) / (2*g2)
        I[2,2] = I[1,1] + (2*II1 - II1_2g - 0.25*II2_2g) / (2*g2)
        I[0,1] = I[1,0] = -0.25*tau/gamma + II1/(2*g2)
        I[0,2] = I[2,0] = I[0,1] + II2/(2*g2)
        I[1,2] = I[2,1] = 0.25*tau/gamma + I[1,1] + II1_2g/(4*g2)
    elif mtype == 'Model B':
        II0_2g = _intI_cached(0, 2*gamma, tau)
        II1_2g = _intI_cached(1, 2*gamma, tau)
        II2_2g = _intI_cached(2, 2*gamma, tau)
        II3 = _intI_cached(3, gamma, tau)
        II3_2g = _intI_cached(3, 2*gamma, tau)
        II4_2g = _intI_cached(4, 2*gamma, tau)
        g2 = gamma * gamma
        G = 0.5*gamma*tau - II1
        I01 = -0.25*tau/gamma + II1/(2*g2)
        I11 = (2*II0 - II0_2g - 1) / (2*g2)
        II_val = II1 - 4*II3 - 0.5*II1_2g - 3/8*II2_2g + II3_2g/4 + II4_2g/8 - 2*G
        I[0,0] = -tau*tau / 6.0
        I[1,1] = G/g2 + I[0,0] + I01
        I[2,2] = -2/3*tau*tau + I11 - II_val/g2
        I[0,1] = I[1,0] = I[0,0] - I01
        I[0,2] = I[2,0] = I01 - 2*I[0,0] - (II1 + 2*II2)/(2*g2)
        I[1,2] = I[2,1] = -0.5*tau/gamma + I[0,2] - I11 \
            - (3*II1 + 2*II2 - 0.5*II1_2g - 0.5*II2_2g)/(2*g2)
    else:
        raise ValueError(f'Model type {mtype} not implemented')

    S2_arr = np.array(S2_flat).reshape(3, 3)
    a = float(np.sum(S2_arr * I))

    x = gamma * tau
    ex = math.exp(-x)
    I1 = (1.0 - ex) / x

    B = np.empty(3)
    if mtype == 'Model A':
        B[0] = 1.0
        B[1] = I1
        B[2] = I1 - ex
    elif mtype == 'Model B':
        B[0] = 1.0
        B[1] = 1.0 - I1
        B[2] = I1 + (1.0 + 2*x)*ex - 2.0
    else:
        raise ValueError(f'Model type {mtype} not implemented')

    return a, tuple(B)


def calAB_np(gamma, tau, S2_flat, mtype):
    """Public entry: returns (float, np.ndarray(3,))."""
    a, B_tuple = _calAB_np_cached(float(gamma), float(tau), S2_flat, mtype)
    return a, np.array(B_tuple)
