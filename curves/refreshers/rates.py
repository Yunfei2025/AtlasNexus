"""
Created on Wed Jul  5 13:59:25 2023

Refactor: OOP structure with performance improvements for curve reference refreshing
@author: 马云飞
"""

import argparse
import os
import sys
import pickle
import pathlib
import numpy as np
import pandas as pd
from datetime import datetime, date
from multiprocessing import Pool
from typing import Dict, Any, Tuple, List, Optional, cast
import logging

# local libraries
PATH = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(PATH))

from curves.utils.loader import loadInstrumentDefinition, loadStatData, loadRefData
from curves.utils.retrieve import retrieveEnvRT
from settings.paths import DIR_INPUT
from settings.general import GeneralConfig, DateConfig
from curves.calibration.stat import statAdjust
from curves.utils.plot import plotCurve
from curves.calibration.selector import compute_spot_term_panels

# logging using centralized setup
from utils.log_window import get_logger
logger = get_logger(__name__)

# --- Worker globals for multiprocessing (reduces pickling overhead on Windows) ---
_WORKER_ENV_DEF: Optional[pd.DataFrame] = None
_WORKER_CURVE: Any = None


def _init_worker(env_def, curve):
    global _WORKER_ENV_DEF, _WORKER_CURVE
    _WORKER_ENV_DEF = env_def
    _WORKER_CURVE = curve


def _price_bucket(bucket):
    if _WORKER_ENV_DEF is None or _WORKER_CURVE is None:
        raise RuntimeError("Pricing worker is not initialized")
    return _WORKER_CURVE.affinePricing(_WORKER_ENV_DEF, bucket)


class BondCurveRefresher:
    """Refresh curve prices in an object-oriented, performant way."""

    def __init__(self, bond_type: str, max_workers: Optional[int] = None, min_maturity: float = GeneralConfig.MIN_MATURITY, max_maturity: float = GeneralConfig.MAX_MATURITY):
        self.bond_type = bond_type
        self.max_workers = max_workers if max_workers is not None else GeneralConfig.N_CORE
        self.min_maturity = min_maturity
        self.max_maturity = max_maturity
        self.curve: Any = None
        self.env: Optional[Dict[str, Any]] = None
        self.stat: Optional[Dict[str, Any]] = None
        self.ref: Optional[Dict[str, Any]] = None
        self.bond_ref_df: Optional[pd.DataFrame] = None
        self.env_quo: Optional[pd.Index] = None

    # ---- IO / Loading ----
    def load_curve_and_env(self) -> Tuple[Any, Dict[str, Any]]:
        curve_file_path = os.path.join(DIR_INPUT, f'{self.bond_type}-cvrt.obj')
        try:
            
            with open(curve_file_path, 'rb') as file:
                curve = pd.read_pickle(file)
            env = loadInstrumentDefinition(self.bond_type)
            self.curve = curve
            self.env = env
            return curve, env
        except FileNotFoundError:
            logger.error(f"Curve file not found: {curve_file_path}")
            raise
        except Exception as e:
            logger.error(f"Error loading curve/env: {e}")
            raise

    def refresh_market_data(self, calc_date: date) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        try:
            if self.env is None:
                raise ValueError("Environment must be loaded before refresh")
            env = cast(Dict[str, Any], retrieveEnvRT(self.env, self.bond_type))
            stat = cast(Dict[str, Any], loadStatData(self.bond_type))
            ref = cast(Dict[str, Any], loadRefData(self.bond_type))
            # Use compute_spot_term_panels for single date computation
            price_range = [calc_date, calc_date]
            self.bond_ref_df = cast(
                pd.DataFrame,
                compute_spot_term_panels(env, price_range, ref['RefBond'], self.bond_type, 'inst', update=False),
            )
            self.env, self.stat, self.ref = env, stat, ref
            return env, stat, ref
        except Exception as e:
            logger.error(f"Error refreshing market data: {e}")
            raise

    def compute_quoted_bonds(self) -> pd.Index:
        if self.env is None or self.curve is None:
            raise ValueError("Curve and environment must be loaded before computing quoted bonds")
        # ensure 剩余期限 exists or derive it
        if '剩余期限' not in self.env['Def'].columns:
            if '到期日期' in self.env['Def'].columns:
                # Convert curve.day to Timestamp to match the 到期日期 column type
                curve_day_ts = pd.Timestamp(self.curve.day).date()
                mat = self.env['Def']['到期日期'] - curve_day_ts
                self.env['Def']['剩余期限'] = [ d.days / 365 for d in mat ]
        filt = (self.env['Def']['剩余期限'] > self.min_maturity) & (self.env['Def']['剩余期限'] < self.max_maturity)
        bonds = self.env['Def'][filt].index
        self.env_quo = bonds
        return bonds

    @staticmethod
    def _make_buckets(index_like: pd.Index, worker_count: int) -> List[pd.Index]:
        if len(index_like) == 0:
            return []
        m = int(np.ceil(len(index_like) / worker_count))
        buckets = [index_like[m * i:m * (i + 1)] for i in range(worker_count)]
        return [b for b in buckets if len(b) > 0]

    # ---- Pricing ----
    def _price_one_side(self, price_type: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        logger.info(f"Processing {price_type} curve...")
        # update curve factors for the side; sanitize NaNs

        if self.bond_ref_df is None or self.curve is None or self.env is None or self.env_quo is None:
            raise ValueError("Pricing inputs are not initialized")

        ref_series = self.bond_ref_df[price_type].dropna()
        self.curve.extractFactors(ref_series, self.curve.reference)
        
        # build buckets
        total = len(self.env_quo)
        if total == 0:
            return pd.DataFrame(), pd.DataFrame(), self.curve.fitting()
        
        worker_count = max(1, min(self.max_workers, total))
        buckets = self._make_buckets(self.env_quo, worker_count)
        
        # small tasks: use sequential to avoid overhead
        if total <= 500 or worker_count == 1 or len(buckets) <= 1:
            dict_p = [self.curve.affinePricing(self.env['Def'], b) for b in buckets]
        else:
            try:
                with Pool(processes=min(worker_count, len(buckets)), initializer=_init_worker, initargs=(self.env['Def'], self.curve)) as pool:
                    dict_p = pool.map(_price_bucket, buckets)
            except Exception as e:
                logger.warning(f"Parallel pricing failed ({e}), falling back to sequential")
                dict_p = [self.curve.affinePricing(self.env['Def'], b) for b in buckets]

        # merge results
        dict_quote = {i: dict_p[i][0] for i in range(len(dict_p))}
        dict_sen = {i: dict_p[i][1] for i in range(len(dict_p))}
        quote_df = pd.concat(dict_quote).droplevel(0).sort_index()
        sen_df = pd.concat(dict_sen).droplevel(0).sort_index()

        # ensure numeric and clean
        quote_df = quote_df.apply(pd.to_numeric, errors='coerce').dropna()
        sen_df = sen_df.apply(pd.to_numeric, errors='coerce').dropna()

        logger.info(f"Finished computing {price_type} curve at: {datetime.now().strftime('%H:%M:%S')}")
        return quote_df, sen_df, self.curve.fitting()

    # ---- Orchestration ----
    def run(self) -> Dict[str, Any]:
        # calculation date
        d = DateConfig.get_date_mappings()['d']
        logger.info(f"Refresh Market Data for {self.bond_type} at: {d.strftime('%H:%M:%S')}")
        calc_date = d.date()

        # load and refresh
        self.load_curve_and_env()
        env, stat, ref = self.refresh_market_data(calc_date)
        # bond ref and set members

        # self.bond_ref_df = pd.Series(spoti.values, index=termi.values) #create_bond_reference(spoti, termi)
        self.compute_quoted_bonds()

        # price both sides
        quotedict: Dict[str, pd.DataFrame] = {}
        sendict: Dict[str, pd.DataFrame] = {}
        curvedict: Dict[str, pd.DataFrame] = {}
        
        for side in ['Bid', 'Ofr']:
            q, s, cfit = self._price_one_side(side)
            quotedict[side] = q
            sendict[side] = s
            curvedict[side] = cfit

        if self.bond_ref_df is None:
            raise ValueError("Bond reference data is not initialized")

        sen = (sendict.get('Bid', pd.DataFrame()) + sendict.get('Ofr', pd.DataFrame())) / 2
        refspot_avg = ((self.bond_ref_df['Bid'] + self.bond_ref_df['Ofr']) / 2).to_frame()
        pxrt = {
            'Curve': (curvedict['Bid'] + curvedict['Ofr']) / 2,
            'RefSpot': refspot_avg,
            'Quote': statAdjust(quotedict, env, stat['BondCurve']),
            'Sen': sen
        }

        # plot and save
        figure = plotCurve(self.bond_type, pxrt)
        self._save_results(self.curve, pxrt, self.bond_type, figure)

        logger.info(f"Finished refreshing {self.bond_type} Curve at: {datetime.now().strftime('%H:%M:%S')}")
        return pxrt

    @classmethod
    def main(cls, bond_type='CBond', max_workers: Optional[int] = None):
        """Main entry point for the BondCurveRefresher"""
        try:
            instance = cls(bond_type=bond_type, max_workers=max_workers)
            instance.run()
        except Exception as e:
            logger.error(f"Error in main execution: {e}")
            raise

    @staticmethod
    def _save_results(curve: Any, pxrt: Dict[str, Any], btype: str, figure: Any) -> None:
        try:
            with open(os.path.join(DIR_INPUT, f'{btype}-cvrt.obj'), 'wb') as f:
                pickle.dump(curve, f)
            with open(os.path.join(DIR_INPUT, f'{btype}-fig.obj'), 'wb') as f:
                pickle.dump(figure, f)
            with open(os.path.join(DIR_INPUT, f'{btype}-rtquo.pkl'), 'wb') as f:
                pickle.dump(pxrt, f)
        except Exception as e:
            logger.error(f"Error saving results: {e}")
            raise

def main(bond_type='TBond', max_workers: Optional[int] = None):
    try:
        BondCurveRefresher.main(bond_type=bond_type, max_workers=max_workers)
    except Exception as e:
        logger.error(f"Error in main execution: {e}")
        sys.exit(1)
#%%
if __name__ == '__main__':
    main()
