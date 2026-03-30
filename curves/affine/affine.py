# -*- coding: utf-8 -*-
"""
Created on Tue Aug  9 16:26:57 2022

@author: 马云飞
"""
import pandas as pd
import numpy as _np
import sympy as sp
import time 
from functools import lru_cache
from scipy.linalg import expm as _scipy_expm

# Convert matrices to hashable tuples for caching
def _matrix_to_tuple(matrix):
    """Convert sympy matrix to hashable tuple for caching"""
    return tuple(tuple(row) for row in matrix.tolist())

def _tuple_to_matrix(matrix_tuple, rows, cols):
    """Convert tuple back to sympy matrix"""
    return sp.Matrix(matrix_tuple)

@lru_cache(maxsize=128)
def _inv_safe_cached(matrix_tuple, rows, cols):
    """Cached version of matrix inversion"""
    M = _tuple_to_matrix(matrix_tuple, rows, cols)
    try:
        return _matrix_to_tuple(M.inv())
    except Exception:
        return _matrix_to_tuple(M.pinv())

def _inv_safe(M: sp.Matrix) -> sp.Matrix:
    try:
        # Try to use cached version for numeric matrices
        matrix_tuple = _matrix_to_tuple(M)
        rows, cols = M.shape
        result_tuple = _inv_safe_cached(matrix_tuple, rows, cols)
        return _tuple_to_matrix(result_tuple, rows, cols)
    except (TypeError, ValueError):
        # Fallback for symbolic matrices
        try:
            return M.inv()
        except Exception:
            return M.pinv()

def calAffine(tau,x,k,L,M,g,u,theta):
    Li = _inv_safe(L)
    ki = _inv_safe(k)
    G = g*L
    f,q = calQ(tau,k,M)
    ytm = G*f*Li*(x-theta)+g*theta-0.5*G*ki*q*ki*G.T
    ytm = ytm[0]+u
    return ytm

def calAffineCov(term,spot,gamma,mtype,caltype):
    S20 = sp.diag(1,1,1)
    nstep = 10
    S_err = 1
    ns = 0
    k = term.shape[1]
    a = sp.zeros(k,1)
    b = sp.zeros(k,3)
    x_df = pd.DataFrame(index=spot.index,columns=['x1','x2','x3'])
    df = [] 
    #% calibrate S2
    while (S_err > 0.001) & (ns < nstep):
        S2 = S20
        ns += 1
        # Precompute matrices once per iteration for Matrix method
        for d in spot.index:
            # get factors        
            y0 = sp.Matrix(spot.loc[d])
            tau0 = term.loc[d]
            for i in range(k):
                tau = tau0[i] 
                if caltype == 'Analytic':
                    ai, bi = calAB_analytic(gamma,tau,S2,mtype)
                elif caltype == 'Matrix':
                    ai, bi = calAB_matrix(tau,S2,gamma,mtype) #_compute_a_b_matrix(tau, pre)
                else:
                    print('Other method.')
                a[i] = ai
                b[i,:] = bi
            # Solve least squares robustly (handle singular b^T b)
            # BTB = b.T*b
            # try:
            #     x = BTB.LUsolve(b.T*(y0-a))
            # except Exception:
            #     x = BTB.pinv() * (b.T*(y0-a))
            x = (b.T*b).inv()*b.T*(y0-a)
            x_df.loc[d] = [i for i in x]
        x_df = x_df.astype(float)
        S20 = sp.Matrix(x_df.cov())
        S_err = abs(S2.det()-S20.det())               
        print('\rIteration: ',ns,', Residual of Covanriance Matrix','%.4f'%S_err,end='')
    return S2
        
def getAffineFactors(dfi,S2,gamma,mtype,caltype): 
    k = dfi.shape[0]
    y0 = sp.Matrix(dfi.values)
    taus0 = dfi.index
    a = sp.zeros(k,1)
    b = sp.zeros(k,3)
    df = []           
    for i in range(k):
        tau = taus0[i]
        if caltype == 'Analytic':
            ai, bi = calAB_analytic(gamma,tau,S2,mtype)
        elif caltype == 'Matrix':
            ai, bi = calAB_matrix(tau,S2,gamma,mtype) #_compute_a_b_matrix(tau, pre)
        else:
            print('Other method.')
        a[i] = ai
        b[i,:] = bi

    # Solve least squares robustly (handle singular b^T b)
    BTB = b.T*b
    try:
        x = BTB.LUsolve(b.T*(y0-a))
    except Exception:
        x = BTB.pinv() * (b.T*(y0-a))
    # Ensure factors are real-valued
    x_real = x.applyfunc(lambda v: sp.re(v))
    return x_real

def Affine(tau,x,S2,gamma,mtype,caltype):      
    if caltype == 'Analytic':
        a, b = calAB_analytic(gamma,tau,S2,mtype)
    elif caltype == 'Matrix':
        # Compute a and b using shared diagonalization
        a, b = calAB_matrix(tau,S2,gamma,mtype)
    else:
        print('Other method.')
    y = a+(b*x)[0]
    return y,b

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

@lru_cache(maxsize=64)
def _calAB_matrix_cached(tau_val, S2_tuple, gamma_val, mtype):
    """Cached version of calAB_matrix for numeric values"""
    S2 = _tuple_to_matrix(S2_tuple, 3, 3)
    
    # Pre-define model parameters to avoid repeated conditionals
    if mtype == 'Model A':
        g_vals = [1, 1, 0]
        K_vals = [[0.01, 0, 0], [0, gamma_val, -gamma_val], [0, 0, gamma_val]]
    elif mtype == 'Model B': 
        g_vals = [1, 0, 0]
        K_vals = [[0.01, -gamma_val, -gamma_val], [0, gamma_val, gamma_val], [0, 0, gamma_val]]
    else:
        raise ValueError(f'Model type {mtype} not implemented')
    
    # Create matrices more efficiently
    g = sp.Matrix([[g_vals[0]], [g_vals[1]], [g_vals[2]]])
    K = sp.Matrix(K_vals)
    
    # Constants
    u = 0
    theta = sp.zeros(3, 1)
    
    # Diagonalize K once
    L, k = K.diagonalize()
    
    # Use safe inverse for better numerical stability
    L_tuple = _matrix_to_tuple(L)
    Li_tuple = _inv_safe_cached(L_tuple, 3, 3)
    Li = _tuple_to_matrix(Li_tuple, 3, 3)
    
    k_tuple = _matrix_to_tuple(k)
    ki_tuple = _inv_safe_cached(k_tuple, 3, 3)
    ki = _tuple_to_matrix(ki_tuple, 3, 3)
    
    # Compute M using the helper function
    M_tuple = _calM_cached(L_tuple, S2_tuple)
    M = _tuple_to_matrix(M_tuple, 3, 3)
    
    # Compute G
    G = g.T * L
    
    # Get f and q from calQ
    f_tuple, q_tuple = _calQ_cached(tau_val, k_tuple, M_tuple)
    f = _tuple_to_matrix(f_tuple, 3, 3)
    q = _tuple_to_matrix(q_tuple, 3, 3)
    
    # Compute a more efficiently
    # Since theta is zero vector, g*theta and G*f*Li*theta are zero
    a_temp = -0.5 * G * ki * q * ki * G.T
    a = a_temp[0, 0] + u
    
    # Compute b more efficiently
    # Pre-compute matrix exponential using scipy (numerically stable)
    # sp.exp(-K_tau) uses jordan_form()/nsimplify() which introduces noise
    K_np = _np.array(K.tolist(), dtype=float)
    exp_K_tau = sp.Matrix(_scipy_expm(-K_np * tau_val).tolist())
    identity = sp.eye(3)
    
    # Use safe inverse for K
    K_tuple = _matrix_to_tuple(K)
    K_inv_tuple = _inv_safe_cached(K_tuple, 3, 3)
    K_inv = _tuple_to_matrix(K_inv_tuple, 3, 3)
    
    b = (-1/tau_val) * g.T * K_inv * (exp_K_tau - identity)
    
    return float(a), _matrix_to_tuple(b)

def calAB_matrix(tau, S2, gamma, mtype):
    try:
        tau_val = float(tau)
        gamma_val = float(gamma)
        S2_tuple = _matrix_to_tuple(S2)
        
        a_val, b_tuple = _calAB_matrix_cached(tau_val, S2_tuple, gamma_val, mtype)
        b = _tuple_to_matrix(b_tuple, 1, 3)
        return a_val, b
    except (TypeError, ValueError):
        # Fallback to original computation for symbolic expressions
        # Pre-define model parameters to avoid repeated conditionals
        if mtype == 'Model A':
            g_vals = [1, 1, 0]
            K_vals = [[0.01, 0, 0], [0, gamma, -gamma], [0, 0, gamma]]
        elif mtype == 'Model B': 
            g_vals = [1, 0, 0]
            K_vals = [[0.01, -gamma, -gamma], [0, gamma, gamma], [0, 0, gamma]]
        else:
            raise ValueError(f'Model type {mtype} not implemented')
        
        # Create matrices more efficiently
        g = sp.Matrix([[g_vals[0]], [g_vals[1]], [g_vals[2]]])
        K = sp.Matrix(K_vals)
        
        # Constants
        u = 0
        theta = sp.zeros(3, 1)
        
        # Diagonalize K once
        L, k = K.diagonalize()
        
        # Use safe inverse for better numerical stability
        Li = _inv_safe(L)
        ki = _inv_safe(k)
        
        # Compute M using the helper function
        M = calM(L, S2)
        
        # Compute G
        G = g.T * L
        
        # Get f and q from calQ
        f, q = calQ(tau, k, M)
        
        # Compute a more efficiently
        # Since theta is zero vector, g*theta and G*f*Li*theta are zero
        a_temp = -0.5 * G * ki * q * ki * G.T
        a = a_temp[0, 0] + u
        
        # Compute b more efficiently
        # Pre-compute matrix exponential using scipy (numerically stable)
        try:
            K_np = _np.array(K.tolist(), dtype=float)
            tau_f = float(tau)
            exp_K_tau = sp.Matrix(_scipy_expm(-K_np * tau_f).tolist())
        except (TypeError, ValueError):
            K_tau = K * tau
            exp_K_tau = sp.exp(-K_tau)
        identity = sp.eye(3)
        
        # Use safe inverse for K
        K_inv = _inv_safe(K)
        
        b = (-1/tau) * g.T * K_inv * (exp_K_tau - identity)
        
        return a, b

@lru_cache(maxsize=64)
def _calQ_cached(tau_val, k_tuple, M_tuple):
    """Cached version of calQ for numeric values"""
    k = _tuple_to_matrix(k_tuple, 3, 3)
    M = _tuple_to_matrix(M_tuple, 3, 3)
    
    # Initialize matrices
    f = sp.zeros(3, 3)
    f2 = sp.zeros(3, 3)  
    q = sp.zeros(3, 3)  
    H = sp.zeros(3, 3)
    
    # Compute diagonal elements of f more efficiently
    for i in range(3):
        k_val = k[i, i]
        if abs(k_val) > 1e-10:  # Avoid division by zero with tolerance
            f[i, i] = (1 - sp.exp(-k_val * tau_val)) / (k_val * tau_val)
        else:
            f[i, i] = 1  # Limit case when k approaches 0
    
    # Compute f2 matrix
    for i in range(3):
        for j in range(3):
            l = k[i, i] + k[j, j]
            if abs(l) > 1e-10:  # Avoid division by zero with tolerance
                f2[i, j] = (1 - sp.exp(-l * tau_val)) / (l * tau_val)
            else:
                f2[i, j] = 1  # Limit case
    
    # Compute H using element-wise multiplication
    H = M.multiply_elementwise(f2)
    
    # Compute q using matrix operations
    q = H - M * f - f * M + M
    
    return _matrix_to_tuple(f), _matrix_to_tuple(q)

def calQ(tau, k, M):
    """Optimized calQ function with caching"""
    try:
        tau_val = float(tau)
        k_tuple = _matrix_to_tuple(k)
        M_tuple = _matrix_to_tuple(M)
        
        f_tuple, q_tuple = _calQ_cached(tau_val, k_tuple, M_tuple)
        f = _tuple_to_matrix(f_tuple, 3, 3)
        q = _tuple_to_matrix(q_tuple, 3, 3)
        return f, q
    except (TypeError, ValueError):
        # Fallback to original computation for symbolic expressions
        # Initialize matrices
        f = sp.zeros(3, 3)
        f2 = sp.zeros(3, 3)  
        q = sp.zeros(3, 3)  
        H = sp.zeros(3, 3)
        
        # Compute diagonal elements of f more efficiently
        for i in range(3):
            k_val = k[i, i]
            if k_val != 0:  # Avoid division by zero
                f[i, i] = (1 - sp.exp(-k_val * tau)) / (k_val * tau)
            else:
                f[i, i] = 1  # Limit case when k approaches 0
        
        # Compute f2 matrix
        for i in range(3):
            for j in range(3):
                l = k[i, i] + k[j, j]
                if l != 0:  # Avoid division by zero
                    f2[i, j] = (1 - sp.exp(-l * tau)) / (l * tau)
                else:
                    f2[i, j] = 1  # Limit case
        
        # Compute H using element-wise multiplication
        H = M.multiply_elementwise(f2)
        
        # Compute q using matrix operations
        q = H - M * f - f * M + M
        
        return f, q

@lru_cache(maxsize=64)
def _calM_cached(L_tuple, S2_tuple):
    """Cached version of calM"""
    L = _tuple_to_matrix(L_tuple, 3, 3)
    S2 = _tuple_to_matrix(S2_tuple, 3, 3)
    
    Li_tuple = _inv_safe_cached(L_tuple, 3, 3)
    Li = _tuple_to_matrix(Li_tuple, 3, 3)
    M = Li * S2 * Li.T
    return _matrix_to_tuple(M)

def calM(L, S2):
    """Optimized calM function with caching"""
    try:
        L_tuple = _matrix_to_tuple(L)
        S2_tuple = _matrix_to_tuple(S2)
        M_tuple = _calM_cached(L_tuple, S2_tuple)
        return _tuple_to_matrix(M_tuple, 3, 3)
    except (TypeError, ValueError):
        # Fallback to original computation
        Li = _inv_safe(L)
        M = Li * S2 * Li.T
        return M

@lru_cache(maxsize=256)
def _intI_cached(n, gamma_val, tau_val):
    """Cached version of intI function with numeric values"""
    x = gamma_val * tau_val
    if n == 0:
        return (1 - sp.exp(-x)) / x
    else:
        return n * _intI_cached(n-1, gamma_val, tau_val) - x**(n-1) * sp.exp(-x)

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
