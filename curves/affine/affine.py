# -*- coding: utf-8 -*-
"""
Created on Tue Aug  9 16:26:57 2022

@author: 马云飞
"""
import pandas as pd
import sympy as sp
from functools import lru_cache

# Convert matrices to hashable tuples for caching
def _matrix_to_tuple(matrix):
    """Convert sympy matrix to hashable tuple for caching"""
    return tuple(tuple(row) for row in matrix.tolist())

def _tuple_to_matrix(matrix_tuple, rows, cols):
    """Convert tuple back to sympy matrix"""
    return sp.Matrix(matrix_tuple)


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

def calAB_matrix(tau, S2, gamma, mtype):
    """Delegates to calAB_analytic — the diagonalization-based Matrix path was
    numerically unstable for the defective Jordan-block K (Model A / Model B)."""
    return calAB_analytic(gamma, tau, S2, mtype)


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
