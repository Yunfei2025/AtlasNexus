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


def _project_to_psd(matrix, min_eigenvalue=1e-10):
    """Project a symmetric matrix onto the positive-semidefinite cone."""
    matrix = np.asarray(matrix, dtype=float)
    matrix = 0.5 * (matrix + matrix.T)
    eigenvalues, eigenvectors = np.linalg.eigh(matrix)
    eigenvalues = np.clip(eigenvalues, min_eigenvalue, None)
    projected = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T
    return 0.5 * (projected + projected.T)


def _solve_regularized_system(B_mat, rhs, ridge_scale=1e-8, rcond=1e-6, max_abs_factor=1e6):
    """Solve a small affine factor system with Tikhonov regularization."""
    B_mat = np.asarray(B_mat, dtype=float)
    rhs = np.asarray(rhs, dtype=float)

    BtB = B_mat.T @ B_mat
    scale = np.trace(BtB) / max(1, BtB.shape[0])
    lam = max(float(ridge_scale * scale), 1e-10)

    try:
        x = np.linalg.solve(BtB + lam * np.eye(BtB.shape[0]), B_mat.T @ rhs)
    except np.linalg.LinAlgError:
        x, _, _, _ = np.linalg.lstsq(B_mat, rhs, rcond=rcond)

    if not np.isfinite(x).all():
        x = np.nan_to_num(x, nan=0.0, posinf=max_abs_factor, neginf=-max_abs_factor)

    return np.clip(x, -max_abs_factor, max_abs_factor)


def _solve_regularized_factors(B_mat_all, rhs_all, ridge_scale=1e-8, max_abs_factor=1e6):
    """Solve per-date affine factors with light Tikhonov regularization.

    The previous batched pseudo-inverse path could explode when the 12x3
    loading matrix was nearly rank deficient. This routine stabilizes the solve
    by adding a small ridge to ``B.T @ B`` and clipping pathological outputs.
    """
    n_dates = B_mat_all.shape[0]
    x_arr = np.empty((n_dates, 3), dtype=float)

    for d in range(n_dates):
        B = np.asarray(B_mat_all[d], dtype=float)
        rhs = np.asarray(rhs_all[d], dtype=float)
        x_arr[d] = _solve_regularized_system(
            B,
            rhs,
            ridge_scale=ridge_scale,
            rcond=1e-6,
            max_abs_factor=max_abs_factor,
        )

    return x_arr


def calAffineCov(term, spot, gamma, mtype, caltype):
    """Iterative fixed-point calibration of the 3x3 factor covariance matrix S2.

    Key optimisation: B (factor loadings) and I (drift integrals) depend only on
    (gamma, tau), NOT on S2.  We therefore pre-compute them once before the
    convergence loop and cache them via _compute_IB_cached.  Each iteration is
    then a pure NumPy einsum + batched pseudo-inverse multiply — no Python loops.
    """
    gamma_f = float(gamma)
    k = term.shape[1]

    tau_all = term.values.astype(float)   # (n_dates, k)
    y_all   = spot.values.astype(float)   # (n_dates, k)

    # Drop dates where any tau or spot value is NaN — ensures only complete
    # observations feed into the covariance estimate.
    valid_mask = np.isfinite(tau_all).all(axis=1) & np.isfinite(y_all).all(axis=1)
    tau_all = tau_all[valid_mask]
    y_all   = y_all[valid_mask]
    n_dates = tau_all.shape[0]
    if n_dates < 4:
        raise ValueError(f"calAffineCov: too few valid dates ({n_dates}) after NaN filter.")

    # ------------------------------------------------------------------
    # Pre-compute I matrices and B vectors — done ONCE, S2-independent.
    # I_mat_all : (n_dates, k, 3, 3)
    # B_mat_all : (n_dates, k, 3)
    #
    # Safe to cache on (gamma, tau, mtype) only because B and I are purely
    # geometric — they have no dependence on S2 or market data.
    # ------------------------------------------------------------------
    I_mat_all = np.empty((n_dates, k, 3, 3))
    B_mat_all = np.empty((n_dates, k, 3))
    for d in range(n_dates):
        for i in range(k):
            I_flat, B_vec = _compute_IB_cached(gamma_f, tau_all[d, i], mtype)
            I_mat_all[d, i] = np.array(I_flat).reshape(3, 3)
            B_mat_all[d, i] = np.array(B_vec)

    S2_np = np.eye(3)
    nstep = 20
    damping = 0.5
    for ns in range(1, nstep + 1):
        # a_vec: contract S2 with pre-computed I matrices — no Python loop
        a_vec_all = np.einsum('ij,dkij->dk', S2_np, I_mat_all)  # (n_dates, k)

        rhs_all = y_all - a_vec_all  # (n_dates, k)

        # Regularized per-date solve. This is slightly slower than a batched
        # pseudo-inverse but much more stable on near-singular loading matrices.
        x_arr = _solve_regularized_factors(B_mat_all, rhs_all)

        if not np.isfinite(x_arr).all():
            print(f'\rIteration: {ns}, non-finite factor estimates encountered; reusing last stable covariance.', end='')
            break

        # Robust covariance computation to avoid overflow when x_arr contains
        # extremely large values. We standardize per-column (demean and divide
        # by std, with a safe lower bound) compute the small covariance there,
        # and then rescale back. This avoids squaring huge numbers and creating
        # inf entries that then propagate into S2.
        def _robust_cov(arr):
            arr = np.asarray(arr, dtype=np.float64)
            if arr.size == 0:
                return np.zeros((3, 3), dtype=float)
            mu = np.mean(arr, axis=0)
            sd = np.std(arr, axis=0, ddof=1)
            sd_safe = np.where(sd < 1e-8, 1.0, sd)
            z = (arr - mu) / sd_safe
            # compute covariance in standardized space
            cov_z = (z.T @ z) / max(1, arr.shape[0] - 1)
            # rescale back
            cov = cov_z * np.outer(sd_safe, sd_safe)
            return cov

        S2_candidate = _robust_cov(x_arr)
        if not np.isfinite(S2_candidate).all():
            print(f'\rIteration: {ns}, non-finite covariance encountered; reusing last stable covariance.', end='')
            try:
                # Diagnostics to help identify the root cause: shapes and basic stats
                print('\ncalAffineCov DIAG:')
                print(f'  n_dates={n_dates}, k={k}, S2_np_norm={np.linalg.norm(S2_np):.3g}')
                print(f'  x_arr.shape={getattr(x_arr, "shape", None)}')
                finite_x = np.isfinite(x_arr)
                print(f'  x_arr finite: {finite_x.all()}, nan_count={np.isnan(x_arr).sum()}, inf_count={(~finite_x & ~np.isnan(x_arr)).sum()}')
                if np.isfinite(x_arr).any():
                    xa = x_arr[np.isfinite(x_arr)]
                    print(f'  x_arr stats: min={xa.min():.6g}, max={xa.max():.6g}, mean={xa.mean():.6g}, std={xa.std():.6g}')
                try:
                    print(f'  B_mat_all.shape={getattr(B_mat_all, "shape", None)}')
                    b_finite = np.isfinite(B_mat_all).all()
                    print(f'  B_mat_all all-finite: {b_finite}')
                except Exception:
                    pass
            except Exception as _diag_e:
                print(f'  calAffineCov diagnostic failed: {_diag_e}')
            break

        S2_candidate = _project_to_psd(S2_candidate)
        S2_new = damping * S2_candidate + (1 - damping) * S2_np
        if not np.isfinite(S2_new).all():
            print(f'\rIteration: {ns}, S2_new became non-finite after damping; reusing last stable covariance.', end='')
            try:
                print('\ncalAffineCov DIAG (S2_new non-finite):')
                print(f'  S2_candidate finite: {np.isfinite(S2_candidate).all()}')
                print(f'  S2_candidate stats: min={np.nanmin(S2_candidate):.6g}, max={np.nanmax(S2_candidate):.6g}')
            except Exception:
                pass
            break
        S_err = np.linalg.norm(S2_new - S2_np, ord='fro') / max(1.0, np.linalg.norm(S2_np, ord='fro'))
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

    rhs = y0 - a_vec
    x = _solve_regularized_system(
        B_mat,
        rhs,
        ridge_scale=1e-6,
        rcond=1e-6,
        max_abs_factor=1e4,
    )
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

@lru_cache(maxsize=512)
def _compute_IB_cached(gamma, tau, mtype):
    """Compute I-matrix (drift integrals) and B-vector (factor loadings) for (gamma, tau).

    Cached on model geometry only — S2-independent.  This gives high cache-hit
    rates across the sliding-window in calAffineCov because the same (gamma, tau)
    values repeat across adjacent backtest dates.

    Returns:
        (I_flat, B_tuple) where I_flat is a 9-element tuple (row-major 3x3)
        and B_tuple is a 3-element tuple.
    """
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

    return tuple(I.ravel()), tuple(B)


@lru_cache(maxsize=128)
def _calAB_np_cached(gamma, tau, S2_flat, mtype):
    """Pure float/numpy calAB. S2_flat is a 9-element tuple (row-major 3x3)."""
    I_flat, B_tuple = _compute_IB_cached(gamma, tau, mtype)
    S2_arr = np.array(S2_flat).reshape(3, 3)
    I_mat = np.array(I_flat).reshape(3, 3)
    a = float(np.sum(S2_arr * I_mat))
    return a, B_tuple


def calAB_np(gamma, tau, S2_flat, mtype):
    """Public entry: returns (float, np.ndarray(3,))."""
    a, B_tuple = _calAB_np_cached(float(gamma), float(tau), S2_flat, mtype)
    return a, np.array(B_tuple)
