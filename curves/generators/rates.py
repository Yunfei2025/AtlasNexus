# -*- coding: utf-8 -*-
"""
Curve Generator

This module generates daily parameters for bond yield curves with support for 
parallel processing and various execution environments.

Usage:
    Command line: python rates.py --type TBond --log-level INFO
    
IDE/Interactive environments:
    - The module automatically detects interactive environments (IPython, Spyder, etc.)
    - In interactive mode, multiprocessing is disabled to avoid global variable warnings
    - For better performance in IDEs, consider running with appropriate console settings

IDE Configuration:
    Spyder: Run > Configuration per file > Execute in dedicated console
    PyCharm: Run > Edit Configurations > Add content roots to PYTHONPATH
    VS Code: Configure python.terminal.executeInFileDir: true

Created on Fri May  5 15:04:36 2023
@author: 马云飞
"""
import argparse
import os
import sys
import pickle
import pathlib
import pandas as pd
import numpy as np
import datetime
import time
import logging
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
from dateutil.relativedelta import relativedelta

# parallel computing
from multiprocessing import Pool

# Detect execution environment
def _is_interactive_environment():
    """Detect if running in an interactive environment like IPython, Spyder, etc."""
    try:
        # Check for IPython
        if 'ipykernel' in sys.modules or 'IPython' in sys.modules:
            return True
        # Check for Spyder
        if 'spyder' in sys.modules or 'spydercustomize' in sys.modules:
            return True
        # Check if __main__ module has a file attribute (console doesn't)
        import __main__
        if not hasattr(__main__, '__file__'):
            return True
    except:
        pass
    return False

# Store environment detection result
_IS_INTERACTIVE = _is_interactive_environment()

# local libraries
PATH = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(PATH))

from curves.calibration.selector import RefBondSelector, compute_spot_term_panels, update_price
from curves.utils.loader import loadCurvePxTS, loadInstrumentDefinition
from curves.utils.file import updatePKL
from curves.affine.curve import Curve
from settings.paths import DIR_INPUT
from settings.general import GeneralConfig, DateConfig

@dataclass
class CurveConfig:
    """曲线配置类"""
    bond_type: str
    calculation_date: datetime.date
    start_date: datetime.date
    sigma_window_months: int = GeneralConfig.SIGMA_WINDOW_MONTHS
    min_maturity: float = GeneralConfig.MIN_MATURITY
    max_maturity: float = GeneralConfig.MAX_MATURITY
    tenor_points: int = 10


class WorkerManager:
    """Manages worker processes for parallel pricing."""
    
    def __init__(self):
        self.env_def = None
        self.curve = None
    
    def init_worker(self, env_def, curve):
        """Initialize worker with environment and curve data."""
        self.env_def = env_def
        self.curve = curve
    
    def price_bucket(self, bucket):
        """Price a bucket of bonds."""
        if self.curve is None or self.env_def is None:
            raise ValueError("Worker not properly initialized")
        return self.curve.affinePricing(self.env_def, bucket)


# Global instance for multiprocessing compatibility
_worker_manager = WorkerManager()


def _init_worker(env_def, curve):
    """Initializer for worker processes."""
    _worker_manager.init_worker(env_def, curve)


def _price_bucket(bucket):
    """Worker function to price a bucket."""
    return _worker_manager.price_bucket(bucket)


class BondCurveGenerator:
    """Generate daily parameters of the curve with OOP structure and performance improvements."""
    
    def __init__(self, config: CurveConfig):
        self.config = config
        self.logger = self._setup_logging()
        
    def _setup_logging(self) -> logging.Logger:
        """setup logging using centralized system"""
        from utils.log_window import get_logger
        return get_logger(f"CurveGenerator_{self.config.bond_type}")
    
    def load_data(self) -> Tuple[Dict]:
        """load data and reference data"""
        try:
            self.logger.info(f"loading {self.config.bond_type} instrument definition...")
            env = loadInstrumentDefinition(self.config.bond_type)
            self.logger.info(f"loading {self.config.bond_type} reference data...")
            # ref = loadRefData(self.config.bond_type)
            return env
        except Exception as e:
            self.logger.error(f"loading data failed: {e}")
            raise
    
    def get_reference_bonds(self, env: Dict) -> Tuple[pd.DataFrame, dict]:
        """Get reference bonds and compute spot/term panels using shared selector utilities."""
        try:
            dp = DateConfig.get_date_mappings()['dp'].date()
            window_range = [self.config.start_date, dp]
            # Select reference bonds (skip updating existing selections)
            selector = RefBondSelector()
            botr = selector.select_reference_bonds(env, window_range, self.config.bond_type, daily=True, update=False)
            # botr = select_reference_bonds(env, window_range, self.config.bond_type, daily=True, update=False)
            # Compute spot and term panels in one pass
            ref = compute_spot_term_panels(env, window_range, botr, self.config.bond_type, price_type='close')
            return botr, ref
        except Exception as e:
            self.logger.error(f"get reference bonds failed: {e}")
            raise
    
    def update_curve_parameters(self, curve: Curve, ref: Dict, 
                               dp: datetime.date, bond_ref: pd.Series) -> None:
        """update curve parameters"""
        try:
            # update implied volatility
            # float() is required: curve.S2 elements are sympy Floats, which
            # pandas 2.x rejects when assigning into dtype='float64' columns.
            ref['ImpliedVol'].loc[dp, 'level'] = float(curve.S2[0, 0])
            ref['ImpliedVol'].loc[dp, 'slope'] = float(curve.S2[1, 1])
            ref['ImpliedVol'].loc[dp, 'curvature'] = float(curve.S2[2, 2])
            
            # update factors
            ref['Factors'].loc[dp, 'level'] = float(curve.factors[0])
            ref['Factors'].loc[dp, 'slope'] = float(curve.factors[1])
            ref['Factors'].loc[dp, 'curvature'] = float(curve.factors[2])
            
            # update spot curve
            tenor = list(np.linspace(1, 10, self.config.tenor_points))
            tenor_label = [f"{self.config.bond_type}-{t}Y" for t in tenor]
            spot_di = curve.fitting()['SpotRate'].loc[tenor]
            spot_di.index = [f"{self.config.bond_type}-{t}Y" for t in spot_di.index]
            ref['Spot'].loc[dp] = spot_di.reindex(tenor_label)
            
        except Exception as e:
            self.logger.error(f"update curve parameters failed: {e}")
            raise
    
    def parallel_pricing(self, curve: Curve, env: Dict, bonds_quo: pd.Index) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """parallel pricing"""
        try:
            # batch processing
            if len(bonds_quo) == 0:
                return (pd.DataFrame(), pd.DataFrame())

            worker_count = max(1, min(GeneralConfig.N_CORE, len(bonds_quo)))
            m = int(np.ceil(len(bonds_quo) / worker_count))
            buckets = [bonds_quo[m * i:m * (i + 1)] for i in range(worker_count)]
            buckets = [b for b in buckets if len(b) > 0]

            self.logger.info(f"start pricing {self.config.bond_type}, {len(bonds_quo)} bonds with up to {min(GeneralConfig.N_CORE, len(buckets))} workers")

            # In interactive environments or small tasks: avoid multiprocessing
            if (_IS_INTERACTIVE or len(bonds_quo) <= 500 or worker_count == 1 or len(buckets) <= 1):
                if _IS_INTERACTIVE:
                    self.logger.info("Running in interactive environment, using sequential processing")
                dict_p = [curve.affinePricing(env['Def'], b) for b in buckets]
            else:
                try:
                    with Pool(processes=min(GeneralConfig.N_CORE, len(buckets)), initializer=_init_worker, initargs=(env['Def'], curve)) as pool:
                        dict_p = pool.map(_price_bucket, buckets)
                except Exception as e:
                    self.logger.warning(f"parallel pricing failed ({e}), falling back to sequential")
                    dict_p = [curve.affinePricing(env['Def'], b) for b in buckets]

            # merge results
            dict_quote = {i: dict_p[i][0] for i in range(len(dict_p))}
            dict_sen = {i: dict_p[i][1] for i in range(len(dict_p))}
            
            quote0 = pd.concat(dict_quote).droplevel(0).sort_index()
            sen0 = pd.concat(dict_sen).droplevel(0).sort_index()
            
            # data type conversion and cleaning
            quote0 = quote0.apply(pd.to_numeric, errors='coerce').dropna()
            sen0 = sen0.apply(pd.to_numeric, errors='coerce').dropna()
            
            return quote0, sen0
            
        except Exception as e:
            self.logger.error(f"parallel pricing failed: {e}")
            raise
    
    def save_curve_objects(self, curve_objs: Dict, dp: datetime.date, curve: Curve) -> None:
        """save curve objects"""
        try:
            curve_objs[dp] = curve
            curve_objs = updatePKL(curve_objs, os.path.join(DIR_INPUT, f"{self.config.bond_type}-cvobj.pkl"))
            self.logger.info("save curve objects successfully")
        except Exception as e:
            self.logger.error(f"save curve objects failed: {e}")
            raise
    
    def update_bond_prices(self, quote0: pd.DataFrame, sen0: pd.DataFrame, 
                          env: Dict, dp: datetime.date) -> None:
        """update bond prices"""
        try:
            bond_px = loadCurvePxTS(self.config.bond_type)
            bond_px = update_price(bond_px, quote0, sen0, env['Def'], dp)
            bond_px = updatePKL(bond_px, 
                                  os.path.join(DIR_INPUT, f"{self.config.bond_type}-cvpx.pkl"))
            self.logger.info("update bond prices successfully")
            
        except Exception as e:
            self.logger.error(f"update bond prices failed: {e}")
            raise
    
    def save_final_curve(self, curve: Curve, ref: Dict, botr: pd.DataFrame, 
                         spot: pd.DataFrame, term: pd.DataFrame) -> None:
        """save final curve"""
        try:
            # save real-time curve object
            curve_file_path = os.path.join(DIR_INPUT, f"{self.config.bond_type}-cvrt.obj")
            with open(curve_file_path, 'wb') as file:
                pickle.dump(curve, file)
            
            # save reference data
            ref_data = {
                'RefBond': botr,
                'RefSpot': spot,
                'RefTerm': term
            }
            ref_data = updatePKL(ref_data, 
                                   os.path.join(DIR_INPUT, f"{self.config.bond_type}-cvref.pkl"))
            
            self.logger.info("save final curve successfully")
            
        except Exception as e:
            self.logger.error(f"save final curve failed: {e}")
            raise
    
    def run(self) -> None:
        """run curve generation process"""
        try:
            self.logger.info(f"start generating {self.config.bond_type} curve, calculation date: {self.config.calculation_date}")

            # load data
            env = self.load_data()
            # get reference bonds
            botr, ref = self.get_reference_bonds(env)
            spot, term = ref['RefSpot'], ref['RefTerm']
            # filter pricing bonds
            bonds_quo = env['Def'][(env['Def']['剩余期限'] > self.config.min_maturity) &
                                  (env['Def']['剩余期限'] < self.config.max_maturity)].index
            
            # update yesterday curve
            dp = DateConfig.get_date_mappings()['dp'].date()
            start0 = dp - relativedelta(months=self.config.sigma_window_months)
            curve0 = Curve(dp, self.config.bond_type)
            
            # Simple DataFrame slicing with date conversion
            def safe_slice(df, start_date, end_date):
                """Safely slice DataFrame with date range, handling mixed date types."""
                try:
                    return df.loc[start_date:end_date]
                except (TypeError, KeyError):
                    # Convert index to date objects and retry
                    df_copy = df.copy()
                    df_copy.index = [idx.date() if hasattr(idx, 'date') else idx for idx in df_copy.index]
                    return df_copy.loc[start_date:end_date]

            term_slice = safe_slice(term, start0, dp)
            spot_slice = safe_slice(spot, start0, dp)
            curve0.calibrate(term_slice, spot_slice)

            # get reference spot curve
            df_ref = pd.Series(spot.iloc[-1].values, index=term.iloc[-1].values)
            df_ref.name = 'Ref Spot'
            bond_ref = botr.iloc[-1]
            
            curve0.extractFactors(df_ref, bond_ref)
            
            # update curve parameters
            self.update_curve_parameters(curve0, ref, dp, bond_ref)
            
            # save curve objects
            curve_objs = {}
            self.save_curve_objects(curve_objs, dp, curve0)

            # parallel pricing
            self.logger.info("starting parallel_pricing()")
            t0 = time.perf_counter()
            quote0, sen0 = self.parallel_pricing(curve0, env, bonds_quo)
            t1 = time.perf_counter()
            self.logger.info(f"parallel_pricing() finished (elapsed {t1-t0:.2f}s)")

            # save pricing results
            # update bond prices
            self.logger.info("starting update_bond_prices()")
            t0 = time.perf_counter()
            self.update_bond_prices(quote0, sen0, env, dp)
            t1 = time.perf_counter()
            self.logger.info(f"update_bond_prices() finished (elapsed {t1-t0:.2f}s)")
            
            # build final curve — reuse the 1-month S2 already calibrated in curve0
            # (curve0 uses start0 = dp - months(sigma_window_months); do NOT
            #  re-calibrate from self.config.start_date which is only 7 days)
            curve = Curve(self.config.calculation_date, self.config.bond_type)
            curve.S2 = curve0.S2
            curve.extractFactors(df_ref, bond_ref)
            
            # save final result
            self.logger.info("starting save_final_curve()")
            t0 = time.perf_counter()
            self.save_final_curve(curve, ref, botr, spot, term)
            t1 = time.perf_counter()
            self.logger.info(f"save_final_curve() finished (elapsed {t1-t0:.2f}s)")
            
            self.logger.info(f"{self.config.bond_type} curve generation completed, time: {datetime.datetime.now().strftime('%H:%M:%S')}")
            
        except Exception as e:
            self.logger.error(f"curve generation failed: {e}")
            raise

    @classmethod
    def main(cls, bond_type, log_level='INFO'):
        """Main entry point for the BondCurveGenerator"""
        # Use centralized logging setup instead of basicConfig
        from utils.log_window import get_logger
        logger = get_logger(__name__)
        
        try:
            # create configuration
            d = DateConfig.get_date_mappings()['d']
            start = d.date() - relativedelta(days=7)
            
            config = CurveConfig(
                bond_type=bond_type,
                calculation_date=d.date(),
                start_date=start  # start is already a date object
            )
            
            # create generator and run
            instance = cls(config)
            instance.run()
            
        except NotImplementedError as e:
            print(f"⚠️  Missing dependency: {e}")
            print(f"💡 This is expected when running in test mode without full data infrastructure.")
            return False
        except Exception as e:
            print(f"❌ Program execution failed: {e}")
            raise
            
        return True


def main(bond_type = 'CBond'):
    print(f"🚀 Starting {bond_type} curve generation.")
    try:
        success = BondCurveGenerator.main(bond_type=bond_type)
        if success:
            print("✅ Curve generation completed successfully!")
        else:
            print("⚠️  Curve generation completed with warnings (missing dependencies)")
        return 0
    except Exception as e:
        print(f"❌ Curve generation failed: {e}")
        return 1


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
