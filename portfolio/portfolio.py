# -*- coding: utf-8 -*-
"""
Created on Sun Apr  6 12:17:21 2025

Yield-curve PCA + unified optimization (carry-max + risk-parity + factor-targets)
with long-only base instruments and hedge overlays.

This script is self-contained with hard-coded sample inputs so you can run it
as-is and then replace the inputs with your real data.

Outputs:
- optimized_positions_with_hedges.csv
- factor_exposures_and_rcs.csv

@author: CMBC
"""
import os
import pandas as pd
import pathlib
import sys
import numpy as np
import xlwings as xw
from typing import List, Tuple, Dict, Optional
import logging

from sklearn.decomposition import PCA
from scipy.optimize import minimize

# local libraries - update imports to use correct modules
PATH = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(PATH))

# Import functions from local optimizer module
from portfolio.optimizer import get_dur, get_mat
# Import config from settings module
from settings.general import DateConfig
from settings.paths import DIR_INPUT, DIR_OUTPUT
# Import file utilities 
from curves.utils.file import updatePKL

# Configure logging using centralized setup
from utils.log_window import get_logger
logger = get_logger(__name__)

# Constants definition
class PortfolioConfig:
    """Portfolio configuration class"""
    N_FACTORS = 3  # Number of PCA factors
    LAMBDA_PARITY = 1e-4            # Risk parity penalty coefficient (reduced to prioritize factor targets)
    LAMBDA_FACTOR_TARGET = 1e9      # Factor target penalty coefficient (balanced)
    LAMBDA_BUDGET = 1e-2            # Budget penalty coefficient (reduced to prioritize factor targets)
    OPTIMIZATION_MAXITER = 100000   # Maximum optimization iterations (increased for better convergence)
    ROUNDING_UNIT = 1.0             # Weight rounding unit (reduced to 1 million)
    YEARS_LIST = [1, 2, 3, 4, 5, 7, 10, 30]  # Years list
    
    # New parameters for improved factor targeting
    USE_FACTOR_CONSTRAINTS = True   # Use factor targets as hard constraints (re-enabled with better tolerance)
    FACTOR_TOLERANCE = 0.05         # Tolerance for factor constraint violations (reasonable tolerance)
    ADAPTIVE_PENALTY = True         # Use adaptive penalty scaling
    PENALTY_GROWTH_FACTOR = 2.0     # How much to increase penalty if targets not met
    
    # Default target factor DV01 (will be set during optimization)
    target_factor_dv01 = np.array([0.0, 0.0, 0.0])  # Default to zero targets

def retrieve_cv_pool(universe: List[str], window: str) -> pd.DataFrame:
    """Retrieve yield curve data pool"""
    try:
        sec_ts = {}
        sec_ts = updatePKL(sec_ts, os.path.join(DIR_INPUT, 'database-px.pkl'))
        dates = DateConfig.get_date_mappings()
        cvdata = sec_ts['CGB'].loc[dates[window].date():dates['d'].date(), universe].dropna()
        return cvdata
    except Exception as e:
        logger.error(f"Failed to retrieve yield curve data: {e}")
        raise

def getSpdcv(sec_ts: Dict, window: str) -> Tuple[pd.DataFrame, Dict]:
    """Retrieve spread data"""
    from settings.fixed_income import SpreadConfig
    spdmap = SpreadConfig.build_spdmap()
    try:
        cvspd = {}
        dates = DateConfig.get_date_mappings()
        for s in spdmap.keys():
            cvspd[s] = pd.DataFrame()
            s_ = 'IRS' if s in ['r7d', 's3m'] else s
            for c in spdmap[s].keys():
                cvspd[s][c] = sec_ts[s_][c] - sec_ts['CGB'][spdmap[s][c]]
            cvspd[s] = cvspd[s].loc[dates[window].date():dates['d'].date()].dropna()
        
        tenors = spdmap['CDB'].values()
        cvref = sec_ts['CGB'].loc[dates[window].date():dates['d'].date(), tenors].dropna()
        
        pca_spd = {}
        temp = pd.concat(cvspd, axis=1)
        temp.columns = temp.columns.droplevel(0)
        pca_spd['Spot'] = pd.concat([cvref, temp], axis=1)
        pca_spd = updatePKL(pca_spd, os.path.join(DIR_INPUT, 'Portfolio-spds.pkl'), rewrite=True)
        
        return cvref, cvspd
    except Exception as e:
        logger.error(f"Failed to retrieve spread data: {e}")
        raise

class PortfolioOptimizer:
    """Portfolio optimizer class"""
    
    def __init__(self, cvref: pd.DataFrame, config: PortfolioConfig):
        self.cvref = cvref
        self.config = config
        self.base_maturities = None
        self.mod_durations = None
        self.dv01_base = None
        self.loadings_base = None
        self.factor_vols_bp = None
        
    def setup_base_instruments(self) -> None:
        """Setup base instruments"""
        self.base_maturities = get_mat(self.cvref.columns)
        self.mod_durations = get_dur(self.cvref.columns)
        self.dv01_base = self.mod_durations * 1e-4
        
    def perform_pca_analysis(self) -> None:
        """Perform PCA analysis"""
        try:
            # Calculate daily yield changes
            Delta = self.cvref.diff().dropna().values
            
            # Perform PCA
            pca = PCA(n_components=self.config.N_FACTORS)
            pca.fit(Delta)
            
            # Get principal components and loadings
            pcs = pca.components_
            self.loadings_base = pcs.T
            
            # Calculate annualized factor volatility
            explained_var = pca.explained_variance_
            self.factor_vols_bp = np.sqrt(explained_var) * np.sqrt(252) * 1e4
            
            # Interpret PCA results
            self._interpret_pca_results(pcs)
            
        except Exception as e:
            logger.error(f"PCA analysis failed: {e}")
            raise
    
    def _interpret_pca_results(self, pcs: np.ndarray) -> None:
        """Interpret PCA results"""
        for i, pc in enumerate(pcs):
            if i == 0:
                logger.info("PC1: Level, Positive = Upward shift.")
            elif i == 1:
                slope_type, _ = self._interpret_pc(pc)
                logger.info(f"PC2: Slope, {slope_type}")
            elif i == 2:
                _, curvature_type = self._interpret_pc(pc)
                logger.info(f"PC3: Curvature, {curvature_type}")
    
    def _interpret_pc(self, loadings: np.ndarray) -> Tuple[str, str]:
        """Interpret principal component slope and curvature meaning"""
        short = loadings[0]
        long = loadings[-1]
        belly = loadings[len(loadings)//2]
        
        # Slope interpretation
        if (short < 0 and long > 0) or (short > 0 and long < 0):
            slope_type = "Positive = Flattener" if long > short else "Positive = Steepener"
        else:
            slope_type = "Mixed/Non-standard slope pattern"
        
        # Curvature interpretation
        if belly > 0 and short < belly and long < belly:
            curvature_type = "Positive = Belly sell-off (inverted hump)"
        elif belly < 0 and short > belly and long > belly:
            curvature_type = "Positive = Belly rally (more hump)"
        else:
            curvature_type = "Mixed/Non-standard curvature"
        
        return slope_type, curvature_type
    
    def setup_hedge_instruments(self, hedge_labels: List[str]) -> Tuple[np.ndarray, np.ndarray, List[str]]:
        """Setup hedge instruments"""
        try:
            # Map hedge instruments to base maturities
            hedge_map_idx = [self.base_maturities.index(t.split('-')[1]) for t in hedge_labels]
            
            # Hedge instrument DV01 (negative sign indicates short position)
            dv01_hedge = -self.dv01_base[hedge_map_idx]
            
            # Build labels for all instruments
            labels = self.base_maturities + hedge_labels
            
            return dv01_hedge, hedge_map_idx, labels
            
        except ValueError as e:
            logger.error(f"Hedge instrument setup failed: {e}")
            raise
    
    def build_optimization_problem(self, hedge_labels: List[str], dv01_hedge: np.ndarray, 
                                 hedge_map_idx: List[int], labels: List[str],
                                 budget_base_mm: float, max_total_abs_dv01: float) -> Tuple:
        """Build optimization problem"""
        N = len(self.base_maturities)
        H = len(hedge_labels)
        M = N + H
        
        # Build DV01 vector
        dv01_all = np.concatenate([self.dv01_base, dv01_hedge])
        
        # Build loadings matrix
        loadings_hedge = self.loadings_base[hedge_map_idx, :]
        loadings_all = np.vstack([self.loadings_base, loadings_hedge])
        
        # Indices
        idx_base = np.arange(N)
        idx_hedge = np.arange(N, M)
        
        # Setup bounds
        bounds = self._setup_bounds(N, H, max_total_abs_dv01, self.dv01_base, dv01_hedge, labels)
        
        # Initial weights
        w0 = self._setup_initial_weights(N, H, budget_base_mm, 
                               self.config.target_factor_dv01, self.loadings_base, self.dv01_base)
        
        # Constraints
        # Setup constraints
        constraints = self._setup_constraints(N, M, budget_base_mm, max_total_abs_dv01, dv01_all, idx_base, loadings_all, self.config.target_factor_dv01)
        
        # Store loadings for constraint evaluation (needed for factor constraints)
        self.loadings_all = loadings_all
        
        return dv01_all, loadings_all, idx_base, idx_hedge, bounds, w0, constraints
    
    def _setup_bounds(self, N: int, H: int, max_total_abs_dv01: float, 
                      dv01_base: np.ndarray, dv01_hedge: np.ndarray, labels: List[str]) -> List[Tuple]:
        """Setup optimization bounds based on DV01"""
        # Half of total DV01 for all instruments
        half_total_dv01 = max_total_abs_dv01 / 2
        
        # Base instruments: long-only with DV01-based limit
        # For each instrument: max_weight = half_total_dv01 / dv01
        bounds = []
        for i in range(N):
            if dv01_base[i] > 0:
                Lmax = half_total_dv01 / dv01_base[i]
            else:
                Lmax = 0.0
            bounds.append((0.0, Lmax))
        
        # Hedge instruments: can be long or short with DV01-based limits
        for i in range(H):
            if abs(dv01_hedge[i]) > 0:
                if 'Bond' in labels[N + i]:
                    HBmax = half_total_dv01 / abs(dv01_hedge[i])
                    bounds.append((0.0, HBmax))
                elif 'Swap' in labels[N + i]:
                    HSmax = half_total_dv01 / abs(dv01_hedge[i])
                    bounds.append((0.0, HSmax))
                elif 'None' in labels[N + i]:
                    bounds.append((0.0, 0.0))  # No position allowed
                else:
                    HSmax = half_total_dv01 / abs(dv01_hedge[i])
                    bounds.append((0.0, HSmax))  # Default to swap limit
            else:
                bounds.append((0.0, 0.0))
        
        return bounds
    
    def _setup_initial_weights(self, N: int, H: int, budget_base_mm: float, 
                               target_factor_dv01: np.ndarray, loadings_base: np.ndarray,
                               dv01_base: np.ndarray) -> np.ndarray:
        """Setup initial weights with optimal factor alignment using pseudo-inverse"""
        try:
            # Try to find weights that better match factor targets
            if np.any(target_factor_dv01 != 0):
                # Use pseudo-inverse approach to solve: loadings_base.T @ (w * dv01_base) ≈ target_factor_dv01
                # This gives us a starting point much closer to the desired factor exposure
                
                # Create the system: A @ w = b, where A = loadings_base.T * dv01_base, b = target_factor_dv01
                A = loadings_base.T * dv01_base
                b = target_factor_dv01
                
                try:
                    # Use pseudo-inverse for better numerical stability
                    from numpy.linalg import pinv
                    w_optimal = pinv(A) @ b
                    
                    # Scale to budget while maintaining factor proportions
                    if np.sum(w_optimal) > 0:
                        w_optimal = w_optimal * (budget_base_mm / np.sum(w_optimal))
                    else:
                        w_optimal = np.ones(N) * (budget_base_mm / N)
                        
                except:
                    # Fallback to manual allocation if pseudo-inverse fails
                    w_optimal = np.zeros(N)
                    for i in range(N):
                        # Allocate budget proportionally based on factor importance
                        factor_importance = np.sum(np.abs(loadings_base[i, :] * target_factor_dv01))
                        if factor_importance > 0:
                            w_optimal[i] = factor_importance
                    
                    # Normalize and scale to budget
                    if np.sum(w_optimal) > 0:
                        w_optimal = (w_optimal / np.sum(w_optimal)) * budget_base_mm
                    else:
                        w_optimal = np.ones(N) * (budget_base_mm / N)
                
                # Clip to bounds
                target_weights = np.clip(w_optimal, 0.0, budget_base_mm / 2)
                
            else:
                # Equal allocation if no specific targets
                target_weights = np.ones(N) * (budget_base_mm / N)
            
            # Hedge weights start at 0
            w0 = np.concatenate([target_weights, np.zeros(H)])
            
            logger.info(f"Initial weights: {target_weights}")
            initial_fd = self._factor_dv01s(w0[:N], loadings_base, dv01_base)
            logger.info(f"Initial factor DV01: {initial_fd}")
            logger.info(f"Target factor DV01: {target_factor_dv01}")
            logger.info(f"Initial factor error: {np.abs(initial_fd - target_factor_dv01)}")
            
            return w0
            
        except Exception as e:
            logger.warning(f"Failed to setup smart initial weights: {e}, using fallback")
            # Fallback to simple equal allocation
            w0_base = np.ones(N) * (budget_base_mm / N)
            w0_base = np.clip(w0_base, 0.0, budget_base_mm / 2)
            w0 = np.concatenate([w0_base, np.zeros(H)])
            return w0
    
    def _setup_constraints(self, N: int, M: int, budget_base_mm: float, 
                          max_total_abs_dv01: float, dv01_all: np.ndarray, 
                          idx_base: np.ndarray, loadings_all: np.ndarray, 
                          target_factor_dv01: np.ndarray) -> List[Dict]:
        """Setup minimal constraints - use penalties in objective function instead"""
        constraints = []
        
        # # Hard constraint: total portfolio DV01
        # def dv01_constraint(w, dv01_all=dv01_all, max_total_abs_dv01=max_total_abs_dv01):
        #     val = max_total_abs_dv01 - abs(np.sum(w * dv01_all))
        #     print(f"Constraint check: {val:.4f} (max={max_total_abs_dv01}, actual={abs(np.sum(w * dv01_all)):.4f})")
        #     return val
        
        # constraints.append({
        #     "type": "ineq",
        #     "fun": dv01_constraint
        # })
        # constraints.append({
        #     "type": "ineq",
        #     "fun": lambda w, dv01_all=dv01_all, max_total_abs_dv01=max_total_abs_dv01:
        #         max_total_abs_dv01 - abs(np.sum(w * dv01_all))
        # })
  
        # Only add factor constraints if explicitly enabled and target is set
        if (self.config.USE_FACTOR_CONSTRAINTS and np.any(target_factor_dv01 != 0)):
            
            tol = max(np.max(np.abs(target_factor_dv01)) * 0.5, self.config.FACTOR_TOLERANCE)
            logger.info(f"Adding factor constraints with dynamic tolerance: {tol:.3f}")
            
            # Factor constraints: |factor_dv01 - target| <= tolerance
            for i in range(len(target_factor_dv01)):
                if target_factor_dv01[i] != 0:  # Only constrain non-zero targets
                    # Upper bound: factor_dv01[i] <= target[i] + tolerance
                    constraints.append({
                        "type": "ineq",
                        "fun": lambda w, i=i, t=target_factor_dv01[i], tol=tol: 
                               (t + tol) - self._factor_dv01s(w, loadings_all, dv01_all)[i]
                    })
                    # Lower bound: factor_dv01[i] >= target[i] - tolerance
                    constraints.append({
                        "type": "ineq", 
                        "fun": lambda w, i=i, t=target_factor_dv01[i], tol=tol:
                               self._factor_dv01s(w, loadings_all, dv01_all)[i] - (t - tol)
                    })
                    logger.info(f"Factor {i} constraint: {target_factor_dv01[i]:.2f} ± {tol:.2f}")
        
        logger.info(f"Total constraints: {len(constraints)}")
        return constraints
    
    def _relax_constraints(self, constraints: List[Dict], relaxation_factor: float = 2.0) -> List[Dict]:
        """Relax constraints by multiplying limits by relaxation factor"""
        relaxed_constraints = []
        
        for constraint in constraints:
            if constraint["type"] == "ineq":
                # Create a relaxed version of the constraint
                relaxed_constraints.append({
                    "type": "ineq",
                    "fun": lambda w, orig_fun=constraint["fun"], factor=relaxation_factor: 
                           orig_fun(w) * factor
                })
            else:
                relaxed_constraints.append(constraint)
        
        return relaxed_constraints
    
    def objective_function(self, w: np.ndarray, loadings_all: np.ndarray, 
                          dv01_all: np.ndarray, idx_base: np.ndarray,
                          target_factor_dv01: np.ndarray, budget_base_mm: float,  max_total_abs_dv01: float) -> float:
        """Objective function with improved factor targeting and constraint penalties"""
        # Calculate factor DV01
        fd = self._factor_dv01s(w, loadings_all, dv01_all)
        
        # Improved factor target penalty with balanced approach
        if np.any(target_factor_dv01 != 0):
            # Calculate errors
            absolute_error = np.abs(fd - target_factor_dv01)
            
            # Use a combination of quadratic and higher-order penalties for stability
            # Focus primarily on absolute error to avoid issues with small targets
            target_pen = (np.sum(absolute_error ** 2) +           # Quadratic base penalty
                         0.1 * np.sum(absolute_error ** 3))       # Cubic penalty for precision
                
        else:
            target_pen = 0
        
        # Risk parity penalty removed (user requested)
        parity_pen = 0

        # Budget penalty - enforce budget constraint via penalty
        budget_total = np.sum(w[idx_base])
        budget_error = abs(budget_total - budget_base_mm) / budget_base_mm
        budget_pen = 1e6 * budget_error ** 2  # Strong penalty for budget violations
        
        # Soft penalty for base portfolio DV01 exceeding 1.5 * max_total_abs_dv01
        base_dv01 = abs(np.sum(w[idx_base] * dv01_all[idx_base]))
        base_dv01_limit = 5*budget_base_mm/1e4 #1.5 * max_total_abs_dv01
        if base_dv01 > base_dv01_limit:
            base_dv01_pen = 1e8 * ((base_dv01 - base_dv01_limit) / base_dv01_limit) ** 2
        else:
            base_dv01_pen = 0

        # Total utility
        utility = (self.config.LAMBDA_FACTOR_TARGET * target_pen + 
                 budget_pen + base_dv01_pen) # 
        
        return utility
    
    def _factor_dv01s(self, w: np.ndarray, loadings_all: np.ndarray, 
                      dv01_all: np.ndarray) -> np.ndarray:
        """Calculate factor DV01"""
        dv01s = w * dv01_all
        return loadings_all.T @ dv01s
    
    def _risk_contributions(self, w: np.ndarray, loadings_all: np.ndarray, 
                           dv01_all: np.ndarray) -> np.ndarray:
        """Calculate risk contributions"""
        fd = self._factor_dv01s(w, loadings_all, dv01_all)
        return np.abs(fd) * self.factor_vols_bp
    
    def optimize_portfolio(self, w0: np.ndarray, bounds: List[Tuple], 
                          constraints: List[Dict], loadings_all: np.ndarray,
                          dv01_all: np.ndarray, idx_base: np.ndarray,
                          target_factor_dv01: np.ndarray,
                          budget_base_mm: float,
                          max_total_abs_dv01: float) -> Tuple[bool, np.ndarray, str]:
        """Execute portfolio optimization with enhanced factor targeting"""
        try:
            # Single-stage optimization with improved convergence
            logger.info("Starting enhanced single-stage optimization...")

            # Use the main objective function
            obj_func = lambda w: self.objective_function(w, loadings_all, dv01_all, 
                                                       idx_base, target_factor_dv01,
                                                       budget_base_mm, max_total_abs_dv01)

            # Enhanced solver options for better convergence
            solver_options = {
                'maxiter': self.config.OPTIMIZATION_MAXITER,
                'ftol': 1e-9,        # Stricter function tolerance
                'eps': 1e-8,         # Smaller step size for gradients
                'disp': True         # Enable verbose output to debug
            }

            # Try L-BFGS-B first (handles bounds but no constraints)
            if len(constraints) == 0:
                logger.info("Using L-BFGS-B method (bounds only)...")
                res = minimize(obj_func, w0, bounds=bounds, method='L-BFGS-B', 
                              options={'maxiter': self.config.OPTIMIZATION_MAXITER, 'disp': True})
            else:
                logger.info("Using SLSQP method (with constraints)...")
                res = minimize(obj_func, w0, bounds=bounds, constraints=constraints,
                              method='SLSQP', options=solver_options)

            # If first attempt fails or gives poor results, try with relaxed constraints
            if not res.success or not self._check_factor_quality(res.x, loadings_all, dv01_all, target_factor_dv01):
                logger.info("First optimization unsuccessful, trying with relaxed approach...")
                
                # Temporarily disable factor constraints for a feasible solution
                relaxed_constraints = [c for c in constraints 
                                     if not self._is_factor_constraint(c)]
                
                res2 = minimize(obj_func, w0, bounds=bounds, constraints=relaxed_constraints,
                              method='SLSQP', options=solver_options)
                
                # Use better of the two results
                if res2.success and (not res.success or res2.fun < res.fun):
                    res = res2
                    logger.info("Using relaxed solution")

            if res.success:
                logger.info(f"Optimization converged with objective value: {res.fun:.6f}")
            else:
                logger.warning(f"Optimization did not converge: {res.message}")

            # Round weights
            w_opt = np.round(res.x / self.config.ROUNDING_UNIT) * self.config.ROUNDING_UNIT

            # Check factor target achievement with detailed analysis
            fd_final = self._factor_dv01s(w_opt, loadings_all, dv01_all)
            target_errors = np.abs(fd_final - target_factor_dv01)
            
            # Improved relative error calculation - avoid division by very small numbers
            relative_errors = np.zeros_like(target_errors)
            for i in range(len(target_factor_dv01)):
                if np.abs(target_factor_dv01[i]) > 1e-3:  # Only calc relative error for significant targets
                    relative_errors[i] = target_errors[i] / np.abs(target_factor_dv01[i])
                else:
                    relative_errors[i] = 0  # Set to 0 for very small targets to avoid huge numbers
            
            # Calculate meaningful metrics
            meaningful_targets = np.abs(target_factor_dv01) > 1e-3
            if np.any(meaningful_targets):
                avg_relative_error = np.mean(relative_errors[meaningful_targets])
                max_relative_error = np.max(relative_errors[meaningful_targets]) if np.any(meaningful_targets) else 0
            else:
                avg_relative_error = 0
                max_relative_error = 0

            logger.info("="*60)
            logger.info("ENHANCED OPTIMIZATION RESULT")
            logger.info("="*60)
            if res.success:
                logger.info(f"Objective = {res.fun:.6f}, Avg Error = {np.mean(target_errors):.4f}")
                logger.info(f"Max Error = {np.max(target_errors):.4f}, RMSE = {np.sqrt(np.mean(target_errors**2)):.4f}")
            else:
                logger.info(f"Optimization failed: {res.message}")

            logger.info("="*60)
            logger.info(f"Final factor DV01: {fd_final}")
            logger.info(f"Target factor DV01: {target_factor_dv01}")
            logger.info(f"Factor target errors: {target_errors}")
            logger.info(f"Relative errors (%): {relative_errors * 100}")
            logger.info(f"Average absolute error: {np.mean(target_errors):.4f}")
            logger.info(f"Average relative error (%): {avg_relative_error * 100:.2f}")
            logger.info(f"Max relative error (%): {max_relative_error * 100:.2f}")
            logger.info("="*60)

            return res.success, w_opt, res.message
            
        except Exception as e:
            logger.error(f"Portfolio optimization failed: {e}")
            raise

    def _check_factor_quality(self, w: np.ndarray, loadings_all: np.ndarray, 
                             dv01_all: np.ndarray, target_factor_dv01: np.ndarray) -> bool:
        """Check if factor targeting quality is acceptable"""
        if not np.any(target_factor_dv01 != 0):
            return True
            
        fd = self._factor_dv01s(w, loadings_all, dv01_all)
        errors = np.abs(fd - target_factor_dv01)
        max_error = np.max(errors)
        avg_error = np.mean(errors)
        
        # Quality thresholds
        max_allowed_error = np.max(np.abs(target_factor_dv01)) * 0.5  # 50% of largest target
        avg_allowed_error = np.mean(np.abs(target_factor_dv01)) * 0.2  # 20% of average target
        
        return max_error <= max_allowed_error and avg_error <= avg_allowed_error

    def _is_factor_constraint(self, constraint: Dict) -> bool:
        """Check if a constraint is a factor constraint"""
        # Simple heuristic: factor constraints reference _factor_dv01s
        func_code = constraint['fun'].__code__
        return '_factor_dv01s' in func_code.co_names if hasattr(func_code, 'co_names') else False
    


class PortfolioResults:
    """Portfolio results processing class"""
    
    @staticmethod
    def create_positions_dataframe(labels: List[str], w_opt: np.ndarray, 
                                 dv01_all: np.ndarray, N: int, H: int) -> pd.DataFrame:
        """Create positions dataframe"""
        positions = pd.DataFrame({
            'Instrument': labels,
            'Type': ["Base"] * N + ["Hedge"] * H,
            'Weight_¥mm': w_opt,
            'DV01_¥mm/bp': w_opt * dv01_all,
        })
        positions.set_index('Instrument', inplace=True)
        return positions
    
    @staticmethod
    def create_factors_dataframe(fdv01_opt: np.ndarray, target_factor_dv01: np.ndarray,
                               factor_vols_bp: np.ndarray, RCs_opt: np.ndarray,
                               n_factors: int) -> pd.DataFrame:
        """Create factors dataframe"""
        factors = pd.DataFrame({
            'Factor': [f'PC{i+1}' for i in range(n_factors)],
            'DV01_¥mm/bp': fdv01_opt,
            'Target_DV01_¥mm/bp': target_factor_dv01,
            'Vol_bp_annual': factor_vols_bp,
            'RiskContribution_¥mm': RCs_opt,
        })
        factors.set_index('Factor', inplace=True)
        return factors
    
    @staticmethod
    def save_results(positions: pd.DataFrame, factors: pd.DataFrame) -> None:
        """Save results to Excel file"""
        try:
            file_path = os.path.join(DIR_OUTPUT, 'PortInfo.xlsx')
            with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                positions.to_excel(writer, sheet_name='positions', index=False)
                factors.to_excel(writer, sheet_name='factors', index=False)
            logger.info(f"Results saved to: {file_path}")
        except Exception as e:
            logger.error(f"Failed to save results: {e}")
            raise
    
    @staticmethod
    def print_summary(positions: pd.DataFrame, factors: pd.DataFrame, 
                     w_opt: np.ndarray, idx_base: np.ndarray, dv01_all: np.ndarray,
                     budget_base_mm: float, max_total_abs_dv01: float) -> None:
        """Print results summary"""
        # Calculate diagnostic metrics
        net_base = float(np.sum(w_opt[idx_base]))
        gross_all = float(np.sum(np.abs(w_opt)))
        base_abs_dv01 = float(np.sum(w_opt[idx_base] * dv01_all[idx_base]))
        tot_abs_dv01 = float(np.sum(w_opt * dv01_all))
        
        print("\n" + "="*60)
        print("Portfolio Optimization Results Summary")
        print("="*60)
        print("\nOptimized positions:")
        print(positions.to_string(index=False))
        print("\nFactor exposures:")
        print(factors.to_string(index=False))
        print(f"\nBase instrument notional size (¥mm): {gross_all:>10,.2f}  (cap {budget_base_mm:,.2f})")
        print(f"Base instrument DV01 (¥mm): {base_abs_dv01:>10,.2f}  (cap {max_total_abs_dv01:,.2f})")
        print(f"Net notional size (¥mm): {net_base:>10,.2f}")
        print(f"Total |DV01| (¥mm): {tot_abs_dv01:>10,.2f}")
        print("="*60)

def read_excel_inputs(xlwings=True) -> Tuple[float, float, float, float, float, List[str]]:
    """Read input parameters from Excel"""
    try:
        if xlwings:
            wb = xw.Book.caller()
            sheet = wb.sheets['Main']
            
            # Read parameters
            budget_base_mm = float(sheet.range('G2').value)
            max_total_abs_dv01 = float(sheet.range('I2').value)
            sen_level = float(sheet.range('G4').value)
            sen_slope = float(sheet.range('G5').value)
            sen_curva = float(sheet.range('G6').value)
            hedge_labels = list(sheet.range('J8:J15').value)
        else:
            file = PATH.parent.joinpath(r'Dashboard.xlsm').resolve()
            fileinfo = pd.read_excel(file, sheet_name='Main',
                                     skiprows=[0], usecols="F:L")
            budget_base_mm = float(fileinfo.columns[1])
            max_total_abs_dv01 = float(fileinfo.columns[3])    # ¥mm (base DV01)
            sen_level = float(fileinfo.iloc[1,1]) # ¥mm (+:up)
            sen_slope = float(fileinfo.iloc[2,1])  # ¥mm (+:steepener,-:flattener)
            sen_curva = float(fileinfo.iloc[3,1])  # ¥mm (+ wing:, -:belly)
            hedge_labels = list(fileinfo.iloc[5:13,4].dropna())
            
        # Validate inputs
        if budget_base_mm <= 0:
            raise ValueError("Budget must be greater than 0")
        if max_total_abs_dv01 <= 0:
            raise ValueError("Maximum DV01 must be greater than 0")
        
        return budget_base_mm, max_total_abs_dv01, sen_level, sen_slope, sen_curva, hedge_labels
        
    except Exception as e:
        logger.error(f"Failed to read Excel inputs: {e}")
        raise

def write_excel_outputs(sheet, factors: pd.DataFrame, positions: pd.DataFrame,
                       base_maturities: List[str], hedge_labels: List[str]) -> None:
    """Write results to Excel"""
    try:
        # Write factor information - reshape arrays to column vectors
        sheet.range('H4:H6').value = factors['DV01_¥mm/bp'].values.reshape(-1, 1)
        sheet.range('K4:K6').value = factors['Vol_bp_annual'].values.reshape(-1, 1)
        sheet.range('L4:L6').value = factors['RiskContribution_¥mm'].values.reshape(-1, 1)
        
        # Write position information - reshape arrays to column vectors
        sheet.range('H8:H15').value = positions.loc[base_maturities, 'Weight_¥mm'].values.reshape(-1, 1)
        sheet.range('I8:I15').value = positions.loc[base_maturities, 'DV01_¥mm/bp'].values.reshape(-1, 1)
        sheet.range('K8:K15').value = positions.loc[hedge_labels, 'Weight_¥mm'].values.reshape(-1, 1)
        sheet.range('L8:L15').value = positions.loc[hedge_labels, 'DV01_¥mm/bp'].values.reshape(-1, 1)
        
        logger.info("Results written to Excel")
        
    except Exception as e:
        logger.error(f"Failed to write to Excel: {e}")
        raise

@xw.func
def constructPortfolio(xlwings=True):
    """Main function to construct portfolio"""
    try:
        logger.info("Starting portfolio construction...")
        
        # 1. Initialize configuration
        config = PortfolioConfig()
        
        # 2. Retrieve yield curve data
        universe = [f'中债国债到期收益率:{y}年' for y in config.YEARS_LIST]
        cvref = retrieve_cv_pool(universe, 'd1y')
        
        # 3. Create optimizer
        optimizer = PortfolioOptimizer(cvref, config)
        optimizer.setup_base_instruments()
        optimizer.perform_pca_analysis()
        
        # 4. Read Excel inputs
        budget_base_mm, max_total_abs_dv01, \
        sen_level, sen_slope, sen_curva, hedge_labels = read_excel_inputs(xlwings)
        config.target_factor_dv01 = np.array([sen_level, sen_slope, sen_curva])
        
        # 5. Setup hedge instruments
        dv01_hedge, hedge_map_idx, labels = optimizer.setup_hedge_instruments(hedge_labels)
        
        # 6. Build optimization problem
        dv01_all, loadings_all, idx_base, idx_hedge, bounds, w0, constraints = \
            optimizer.build_optimization_problem(hedge_labels, dv01_hedge, hedge_map_idx, labels,
                                              budget_base_mm, max_total_abs_dv01)
        
        # 7. Execute optimization
        success, w_opt, message = optimizer.optimize_portfolio(w0, bounds, constraints,
                                                             loadings_all, dv01_all, idx_base,
                                                             config.target_factor_dv01, budget_base_mm, max_total_abs_dv01)
        
        # Debug: print optimization results
        logger.info(f"Optimization success: {success}")
        logger.info(f"Optimization message: {message}")
        logger.info(f"Final weights: {w_opt}")
        logger.info(f"Sum of weights: {np.sum(w_opt):.2f}")
        
        # 8. Process results
        N = len(optimizer.base_maturities)
        H = len(hedge_labels)
        
        # Calculate final metrics
        fdv01_opt = optimizer._factor_dv01s(w_opt, loadings_all, dv01_all)
        RCs_opt = optimizer._risk_contributions(w_opt, loadings_all, dv01_all)
        
        # Debug: print calculated metrics
        logger.info(f"Factor DV01s: {fdv01_opt}")
        logger.info(f"Risk Contributions: {RCs_opt}")
        logger.info(f"Factor vols: {optimizer.factor_vols_bp}")
        
        # Factor target analysis
        target_errors = np.abs(fdv01_opt - config.target_factor_dv01)
        target_errors_pct = np.abs(target_errors / (np.abs(config.target_factor_dv01) + 1e-6)) * 100
        
        logger.info("="*60)
        logger.info("FACTOR TARGET ANALYSIS")
        logger.info("="*60)
        logger.info(f"{'Factor':<10} {'Target':<12} {'Achieved':<12} {'Error':<12} {'Error%':<8}")
        logger.info("-" * 60)
        for i, (target, achieved, error, error_pct) in enumerate(zip(config.target_factor_dv01, fdv01_opt, target_errors, target_errors_pct)):
            logger.info(f"PC{i+1:<9} {target:<12.2f} {achieved:<12.2f} {error:<12.2f} {error_pct:<8.1f}%")
        logger.info("-" * 60)
        logger.info(f"Average absolute error: {np.mean(target_errors):.2f}")
        logger.info(f"Average relative error: {np.mean(target_errors_pct):.1f}%")
        logger.info("="*60)
        
        # Create result dataframes
        positions = PortfolioResults.create_positions_dataframe(labels, w_opt, dv01_all, N, H)
        factors = PortfolioResults.create_factors_dataframe(fdv01_opt, config.target_factor_dv01,
                                                         optimizer.factor_vols_bp, RCs_opt,
                                                         config.N_FACTORS)
        
        # 9. Display results
        PortfolioResults.print_summary(positions, factors, w_opt, idx_base, dv01_all,
                                     budget_base_mm, max_total_abs_dv01)
        # 10. Write to Excel
        if xlwings:
            wb = xw.Book.caller()
            sheet = wb.sheets['Main']
            write_excel_outputs(sheet, factors, positions, optimizer.base_maturities, hedge_labels)
        # else: 
        #     PortfolioResults.save_results(positions, factors)
        
        logger.info("Portfolio construction completed")
        
    except Exception as e:
        logger.error(f"Portfolio construction failed: {e}")
        raise

if __name__ == '__main__':
    constructPortfolio(xlwings=False)
    
    
    
