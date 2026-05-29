# -*- coding: utf-8 -*-
"""
Bond and Swap Hedging Module

Optimized hedging calculations for bonds and swaps with improved performance
and code structure.

Created on Thu Oct 19 22:07:25 2023
Optimized on Oct 20, 2025

@author: CMBC
"""
import numpy as np
import pandas as pd
import sympy as sp
import scipy.optimize as opt
from scipy import interpolate
from typing import Dict, List, Tuple, Optional, Union
from settings.fixed_income import BondConfig
from curves.calibration.irscurves import get_swap_mid_quotes

# Constants
HEDGE_TERMS = [' 1Y', ' 2Y', ' 5Y', ' 10Y']
ANCHOR_SWAPS = ['FR007S1Y.IR', 'FR007S2Y.IR', 'FR007S5Y.IR']
OPTIMIZATION_TOLERANCE = 1e-2
QUARTER_YEAR = 1/4
BASIS_POINTS = 100

class HedgeCalculator:
    """Centralized class for hedge calculations with optimized performance."""
    
    def __init__(self):
        self.col_map = BondConfig.get_column_mapping()
        self._jacobian_cache = None
    
    def get_ftp(self, bond_obj: pd.Series, env: Optional[Dict] = None) -> float:
        """Extract FTP from bond object, preferring previous-day FR007 from env['SwapTS']."""
        if not env:
            return np.nan

        try:
            swap_rt = env.get('SwapRT')
            if isinstance(swap_rt, pd.DataFrame) and 'FR007.IR' in swap_rt.index:
                for col in ['成交收益率', self.col_map.get('Bid'), self.col_map.get('Ofr')]:
                    if col and col in swap_rt.columns:
                        value = pd.to_numeric(pd.Series([swap_rt.loc['FR007.IR', col]]), errors='coerce').iloc[0]
                        if pd.notna(value) and np.isfinite(value):
                            return float(value)

                bid_col = self.col_map.get('Bid')
                ofr_col = self.col_map.get('Ofr')
                if bid_col in swap_rt.columns and ofr_col in swap_rt.columns:
                    bid = pd.to_numeric(pd.Series([swap_rt.loc['FR007.IR', bid_col]]), errors='coerce').iloc[0]
                    ofr = pd.to_numeric(pd.Series([swap_rt.loc['FR007.IR', ofr_col]]), errors='coerce').iloc[0]
                    if pd.notna(bid) and pd.notna(ofr):
                        return float((bid + ofr) / 2.0)
        except Exception:
            pass

        try:
            swap_ts = env.get('SwapTS')
            if isinstance(swap_ts, pd.DataFrame) and 'FR007.IR' in swap_ts.columns:
                fr007 = pd.to_numeric(swap_ts['FR007.IR'], errors='coerce').dropna()
                if not fr007.empty:
                    return float(fr007.iloc[-1])
        except Exception:
            pass

        return np.nan

    
    def _get_hedge_terms(self, curve) -> pd.Index:
        """Get hedge terms from curve reference with better error handling."""
        terms_key = curve.reference.index
        hedge_string = '|'.join(HEDGE_TERMS)
        return terms_key[terms_key.str.contains(hedge_string)]
        
    
    def _create_interpolation_function(self, curve):
        """Create optimized interpolation function."""
        spot_curve = curve.fitting()['SpotRate']
        return interpolate.interp1d(
            spot_curve.index, 
            spot_curve.values, 
            kind='linear',
            bounds_error=False,
            fill_value=0.0
        )
    
    def _optimize_hedge_position(self, sen: pd.DataFrame, bond: str, 
                                hedgings: pd.Index) -> np.ndarray:
        """Optimized hedge position calculation."""
        if len(hedgings) == 0:
            return np.array([])
            
        # Check if bond exists in sensitivity data
        if bond not in sen.index:
            print(f"Warning: Bond {bond} not found in sensitivity data")
            return np.zeros(len(hedgings))
        
        # Check if hedging instruments exist in sensitivity data
        missing_hedges = [h for h in hedgings if h not in sen.index]
        if missing_hedges:
            print(f"Warning: Hedging instruments {missing_hedges} not found in sensitivity data")
            available_hedges = [h for h in hedgings if h in sen.index]
            if not available_hedges:
                return np.array([])
            hedgings = pd.Index(available_hedges)
        
        hedge_greeks = np.asarray(sen.loc[hedgings, 'Greek3'].values, dtype=float)
        bond_greek = np.asarray(sen.loc[bond, 'Greek3'], dtype=float).item()
        
        def objective(weights):
            return (np.dot(hedge_greeks, weights) - bond_greek) ** 2
        
        def duration_constraint(weights):
            hedge_durations = np.asarray(sen.loc[hedgings, 'Greek1'].values, dtype=float)
            bond_duration = np.asarray(sen.loc[bond, 'Greek1'], dtype=float).item()
            return np.dot(hedge_durations, weights) - bond_duration
        
        def weight_constraint(weights):
            return np.sum(weights) - 1
        
        bounds = [(0, 1)] * len(hedgings)
        constraints = [
            {'type': 'eq', 'fun': duration_constraint},
            {'type': 'eq', 'fun': weight_constraint}
        ]
        
        initial_guess = np.full(len(hedgings), 1.0 / len(hedgings))
        
        result = opt.minimize(
            objective,
            x0=initial_guess,
            constraints=constraints,
            bounds=bounds,
            method='SLSQP',
            options={'ftol': OPTIMIZATION_TOLERANCE}
        )
        
        return result.x if result.success else np.zeros(len(hedgings))
    
    def _calculate_roll_carry(self, stat_his: Dict, env: Dict, sen: pd.DataFrame,
                             bonds: List[str], btype: str, f1) -> None:
        """Calculate roll and carry for bonds."""
        k = f'{btype}Spread' if btype not in ['TBond', 'CBond'] else 'BondCurve'
        bonds = [ b for b in bonds if b in env['Def'].index]

        for bond in bonds:
            if bond not in stat_his[k].index:
                continue

            bond_obj = env['Def'].loc[bond]
            ttm = stat_his[k].loc[bond, 'ttm']
            bond_greek1 = np.nan
            if isinstance(sen, pd.DataFrame) and bond in sen.index and 'Greek1' in sen.columns:
                bond_greek1 = pd.to_numeric(pd.Series([sen.loc[bond, 'Greek1']]), errors='coerce').iloc[0]
            
            # Calculate Roll
            if ttm > QUARTER_YEAR:
                s1, s2 = f1(ttm), f1(ttm - QUARTER_YEAR)
                if pd.notna(bond_greek1):
                    roll_value = -BASIS_POINTS * (s1 - s2) * bond_greek1
                else:
                    roll_value = np.nan
            else:
                roll_value = -BASIS_POINTS * f1(ttm) * ttm
            
            stat_his[k].loc[bond, 'Roll(3m,bp)'] = roll_value
            
            # Calculate Carry
            ftp = self.get_ftp(bond_obj, env=env)
            coupon = env['Def'].loc[bond, '票面利率:%']
            ytm = bond_obj.loc['估价收益率:%(中债)']
            carry_value = BASIS_POINTS * (ytm - ftp) / 4
            stat_his[k].loc[bond, 'Carry(3m,bp)'] = carry_value     

def BondHedge(stat_his: Dict, env: Dict, ytm_quote: pd.DataFrame, 
              curve, sen: pd.DataFrame, btype: str) -> Dict:
    """
    Optimized bond hedge calculation with improved performance and structure.
    
    Args:
        stat_his: Statistical history dictionary
        env: Environment data dictionary
        ytm_quote: YTM quotes DataFrame
        curve: Curve object for fitting
        sen: Sensitivity DataFrame
        btype: Bond type string
    
    Returns:
        Updated stat_his dictionary
    """
    calculator = HedgeCalculator()
    
    # Get hedge instruments
    hedgings = calculator._get_hedge_terms(curve)

    # Check if hedge terms were found
    if len(hedgings) == 0:
        print(f"Warning: No hedge instruments found in curve reference")
        return stat_his
    
    # Safely get hedge references
    try:
        hedge_bonds = curve.reference.loc[hedgings]
    except KeyError as e:
        print(f"Error accessing hedge references: {e}")
        print(f"Available curve reference index: {list(curve.reference.index)}")
        print(f"Requested hedgings: {list(hedgings)}")
        return stat_his
    
    # Create interpolation function
    f1 = calculator._create_interpolation_function(curve)
    
    # Initialize position hedge DataFrame
    position_hedge = pd.DataFrame(
        index=ytm_quote.index, 
        columns=hedgings,
        dtype=float
    )
    
    # Vectorized hedge calculation
    for bond in sen.index:
        weights = calculator._optimize_hedge_position(sen, bond, hedge_bonds)
        if len(weights) == len(hedgings):
            position_hedge.loc[bond] = weights
        else:
            # Fill with zeros if optimization failed
            position_hedge.loc[bond] = np.zeros(len(hedgings))
    
    position_hedge = position_hedge.round(4)
    position_hedge.columns = ['Curve' + c for c in position_hedge.columns]
    
    # Prepare bonds list and calculate roll/carry
    bonds = list(position_hedge.index)
    if btype not in ['TBond', 'CBond']:
        k = f'{btype}Spread'
    else:
        k = 'BondCurve'
        bonds.extend(list(hedgings))
        bonds = list(set(bonds))
        
    calculator._calculate_roll_carry(stat_his, env, sen, bonds, btype, f1)
    
    # Prepare final output
    bonds_filtered = [b for b in bonds if b in sen.index]
    greeks = sen.loc[bonds_filtered, ['Greek1', 'Greek2', 'Greek3']].mul(-1).round(4)
    greeks.columns = ['level', 'slope', 'curvature']
    
    ytm_tmp = ytm_quote.copy()
    ytm_tmp.columns = ['Bid', 'Ofr']
    
    # Combine results
    combined = greeks.join(stat_his[k], how='left')\
                    .join(ytm_tmp, how='left')\
                    .join(position_hedge, how='left')
    stat_his[k] = combined
    return stat_his


def SwapHedge(stat_his: Dict, env: Dict, ytm_quote: pd.DataFrame) -> Dict:
    """
    Optimized swap hedge calculation with improved structure.
    
    Args:
        stat_his: Statistical history dictionary
        env: Environment data dictionary 
        ytm_quote: YTM quotes DataFrame
    
    Returns:
        Updated stat_his dictionary
    """
    calculator = HedgeCalculator()
    
    # Get anchor swap rates
    irs_anchor = _get_anchor_swap_rates(env, calculator.col_map)
    
    # Create Jacobian matrix (cached for performance)
    jac_matrix = _create_jacobian_matrix(irs_anchor)
    
    # Initialize results DataFrame
    irs_tmp = pd.DataFrame(
        index=ytm_quote.index, 
        columns=['Bid', 'Ofr'],
        dtype=float
    )
    
    # Vectorized calculation where possible
    for bond in ytm_quote.index:
        ttm = env['Def'].loc[bond, '剩余期限']
        bid_val, ofr_val, mid_val = _calculate_swap_rates(env, calculator.col_map, ttm)
        
        # Update results
        irs_tmp.loc[bond, 'Bid'] = bid_val
        irs_tmp.loc[bond, 'Ofr'] = ofr_val
        stat_his['BondSwap'].loc[bond, 'Bid'] = bid_val
        stat_his['BondSwap'].loc[bond, 'Ofr'] = ofr_val
        
        # Calculate hedge ratios
        if 1.0 <= ttm <= 5.0:
            _calculate_hedge_ratios(stat_his, bond, ttm, mid_val, jac_matrix)
        elif ttm > 5.0:
            _set_long_term_ratios(stat_his, bond, ttm)
    
    # Final formatting
    stat_his['BondSwap'].iloc[:, 1:] = stat_his['BondSwap'].iloc[:, 1:].astype(float).round(4)
    stat_his['BondSwap'].sort_index(inplace=True)
    
    return stat_his


def flyHedge(stat_his: Dict, cv_ref: pd.DataFrame, bond_sen: pd.DataFrame) -> Dict:
    """
    Optimized butterfly hedge calculation.
    
    Args:
        stat_his: Statistical history dictionary
        cv_ref: Curve reference DataFrame
        bond_sen: Bond sensitivity DataFrame
    
    Returns:
        Updated stat_his dictionary
    """
    bonds = bond_sen.index
    bond_ref = list(cv_ref['RefBond'].iloc[-1][['Term near 2Y', 'Term near 5Y', 'Term near 10Y']])
    
    position_hedge = pd.DataFrame(
        index=bonds, 
        columns=bond_ref,
        dtype=float
    )
    
    # Vectorized calculations where possible
    ref_cov = np.asarray(bond_sen.loc[bond_ref, 'cov'].values, dtype=float)
    ref_dur = np.asarray(bond_sen.loc[bond_ref, 'dur'].values, dtype=float)
    
    for bond in bonds:
        weights = _optimize_fly_position(bond_sen, bond, bond_ref, ref_cov, ref_dur)
        position_hedge.loc[bond] = weights
    
    position_hedge = position_hedge.round(4)
    position_hedge.columns = ['Fly' + c for c in position_hedge.columns]
    
    stat_his['BondCurve'] = stat_his['BondCurve'].join(position_hedge, how='left')
    return stat_his


# Helper functions for improved modularity
def _get_anchor_swap_rates(env: Dict, col_map: Dict) -> np.ndarray:
    """Get anchor swap rates for hedge calculation."""
    return get_swap_mid_quotes(env['SwapRT'], ANCHOR_SWAPS).values


def _create_jacobian_matrix(irs_anchor: np.ndarray) -> np.ndarray:
    """Create Jacobian matrix for swap calculations."""
    return np.array([irs_anchor, [1.0, 1.0, 1.0], [1.0, 2.0, 5.0]], dtype=float)


def _calculate_swap_rates(env: Dict, col_map: Dict, ttm: float) -> Tuple[float, float, float]:
    """Calculate interpolated swap bid/offer and guarded mid based on TTM."""
    swap_rt = env['SwapRT']
    swap_mid = get_swap_mid_quotes(swap_rt, ANCHOR_SWAPS)
    
    if 1.0 <= ttm < 2.0:
        weight1, weight2 = 2.0 - ttm, ttm - 1.0
        bid_val = (weight1 * swap_rt.loc['FR007S1Y.IR', col_map['Bid']] + 
                  weight2 * swap_rt.loc['FR007S2Y.IR', col_map['Bid']])
        ofr_val = (weight1 * swap_rt.loc['FR007S1Y.IR', col_map['Ofr']] + 
                  weight2 * swap_rt.loc['FR007S2Y.IR', col_map['Ofr']])
        mid_val = (weight1 * swap_mid.loc['FR007S1Y.IR'] + 
                   weight2 * swap_mid.loc['FR007S2Y.IR'])
    elif 2.0 <= ttm < 5.0:
        weight1, weight2 = (5.0 - ttm) / 3.0, (ttm - 2.0) / 3.0
        bid_val = (weight1 * swap_rt.loc['FR007S2Y.IR', col_map['Bid']] + 
                  weight2 * swap_rt.loc['FR007S5Y.IR', col_map['Bid']])
        ofr_val = (weight1 * swap_rt.loc['FR007S2Y.IR', col_map['Ofr']] + 
                  weight2 * swap_rt.loc['FR007S5Y.IR', col_map['Ofr']])
        mid_val = (weight1 * swap_mid.loc['FR007S2Y.IR'] + 
                   weight2 * swap_mid.loc['FR007S5Y.IR'])
    elif ttm >= 5.0:
        bid_val = swap_rt.loc['FR007S5Y.IR', col_map['Bid']]
        ofr_val = swap_rt.loc['FR007S5Y.IR', col_map['Ofr']]
        mid_val = swap_mid.loc['FR007S5Y.IR']
    else:
        bid_val = ofr_val = mid_val = np.nan
    
    return bid_val, ofr_val, mid_val


def _calculate_hedge_ratios(stat_his: Dict, bond: str, ttm: float,
                          irs_mid: float, jac_matrix: np.ndarray) -> None:
    """Calculate hedge ratios for medium-term bonds.

    Uses numpy for numerical stability.  When the swap curve is flat the
    Jacobian determinant (3·r1 − 4·r2 + r5) is exactly zero; lstsq gives the
    minimum-norm solution in that degenerate case.
    """
    b_r = np.array([irs_mid, 1.0, ttm], dtype=float)
    try:
        n_r = np.linalg.solve(jac_matrix, b_r)
    except np.linalg.LinAlgError:
        n_r, _, _, _ = np.linalg.lstsq(jac_matrix, b_r, rcond=None)

    stat_his['BondSwap'].loc[bond, 'FR007S1Y.IR'] = float(n_r[0])
    stat_his['BondSwap'].loc[bond, 'FR007S2Y.IR'] = float(n_r[1])
    stat_his['BondSwap'].loc[bond, 'FR007S5Y.IR'] = float(n_r[2])


def _set_long_term_ratios(stat_his: Dict, bond: str, ttm: float) -> None:
    """Set hedge ratios for long-term bonds."""
    stat_his['BondSwap'].loc[bond, 'FR007S1Y.IR'] = 0
    stat_his['BondSwap'].loc[bond, 'FR007S2Y.IR'] = 0
    stat_his['BondSwap'].loc[bond, 'FR007S5Y.IR'] = ttm / 5.0


def _optimize_fly_position(bond_sen: pd.DataFrame, bond: str, bond_ref: List[str],
                          ref_cov: np.ndarray, ref_dur: np.ndarray) -> np.ndarray:
    """Optimize butterfly position for a single bond."""
    bond_cov = np.asarray(bond_sen.loc[bond, 'cov'], dtype=float).item()
    bond_dur = np.asarray(bond_sen.loc[bond, 'dur'], dtype=float).item()
    
    def objective(weights):
        return (np.dot(ref_cov, weights) - bond_cov) ** 2
    
    def duration_constraint(weights):
        return np.dot(ref_dur, weights) - bond_dur
    
    def weight_constraint(weights):
        return np.sum(weights) - 1
    
    bounds = [(0, 1)] * len(bond_ref)
    constraints = [
        {'type': 'eq', 'fun': duration_constraint},
        {'type': 'eq', 'fun': weight_constraint}
    ]
    
    result = opt.minimize(
        objective,
        x0=np.zeros(len(bond_ref)),
        constraints=constraints,
        bounds=bounds,
        method='SLSQP',
        options={'ftol': OPTIMIZATION_TOLERANCE}
    )
    
    return result.x if result.success else np.zeros(len(bond_ref))