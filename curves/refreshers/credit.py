# -*- coding: utf-8 -*-
"""
Created on Tue Mar 12 21:41:36 2024

Refactored: OOP structure with performance and robustness improvements for spread reference refresh
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
from typing import Dict, Any, Tuple, List
import logging

# local libraries
PATH = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(PATH))

from curves.utils.loader import loadInstrumentDefinition, loadStatData, loadRefData
from curves.utils.retrieve import retrieveEnvRT
from settings.paths import DIR_INPUT
from settings.general import GeneralConfig, DateConfig
from settings.fixed_income import BondConfig

from curves.calibration.stat import statAdjust
from curves.calibration.selector import compute_spot_term_panels

# logging using centralized setup
from utils.log_window import get_logger
logger = get_logger(__name__)

class CreditSpreadRefresher:
    """Refresh spreads for an other-bond type using a base TBond curve.

    Workflow:
      - Load TBond curve and recent TBond rt-quote bundle
      - Load env/defs for TBond and target other-bond type (obtype)
      - Refresh RT, build current bond-reference from TBond
      - Price other-bond universe (Bid/Ofr) in parallel using TBond curve factors
      - Merge with TBond sensitivities and produce opxrt bundle for obtype
    """

    def __init__(self, other_bond_type: str, max_workers: int | None = None):
        self.base_type = 'TBond'
        self.obtype = other_bond_type
        self.max_workers = max_workers if max_workers is not None else GeneralConfig.N_CORE

        self.curve = None
        self.pxrt_base = None
        self.env_base: Dict[str, Any] | None = None
        self.env_other: Dict[str, Any] | None = None
        self.stat_other: Dict[str, Any] | None = None
        self.ref_base: Dict[str, Any] | None = None
        self.bond_ref_df: pd.DataFrame | None = None
        self.obonds_quo: pd.Index | None = None

    # ------------- IO -------------
    def _load_curve_and_base_px(self) -> Tuple[Any, Dict[str, Any]]:
        curve_path = os.path.join(DIR_INPUT, f'{self.base_type}-cvrt.obj')
        pxrt_path = os.path.join(DIR_INPUT, f'{self.base_type}-rtquo.pkl')
        with open(curve_path, 'rb') as f:
            curve = pickle.load(f)
        with open(pxrt_path, 'rb') as f:
            pxrt_base = pickle.load(f)
        self.curve = curve
        self.pxrt_base = pxrt_base
        return curve, pxrt_base

    def _load_envs_and_stats(self) -> None:
        self.env_base = loadInstrumentDefinition(self.base_type)
        self.env_other = loadInstrumentDefinition(self.obtype)
        self.stat_other = loadStatData(self.obtype)
        self.ref_base = loadRefData(self.base_type)

    # ------------- RT refresh and setup -------------
    def refresh_and_prepare(self, calc_date: date) -> None:
        assert self.env_base is not None and self.env_other is not None and self.ref_base is not None
        # RT
        # import pdb; pdb.set_trace()
        self.env_base = retrieveEnvRT(self.env_base, self.base_type)
        self.env_other = retrieveEnvRT(self.env_other, self.obtype)
        # TBond spot/term as of now using compute_spot_term_panels
        price_range = [calc_date, calc_date]
        self.bond_ref_df = compute_spot_term_panels(self.env_base, price_range, self.ref_base['RefBond'], self.base_type, 'inst', update=False)
        # Other bonds pricing set: 1Y-10Y
        df_def = self.env_other['Def']
        if '剩余期限' not in df_def.columns and '到期日期' in df_def.columns:
            mat = df_def['到期日期'] - pd.to_datetime(calc_date)
            df_def['剩余期限'] = mat.dt.days / 365
        mask = (df_def['剩余期限'] > BondConfig.PRICING_MIN_TTM) & (df_def['剩余期限'] < BondConfig.PRICING_MAX_TTM)
        self.obonds_quo = df_def[mask].index

    # ------------- Pricing -------------
    def _make_buckets(self, items: pd.Index, worker_count: int) -> List[pd.Index]:
        if items is None or len(items) == 0:
            return []
        m = int(np.ceil(len(items) / worker_count))
        return [items[m * i:m * (i + 1)] for i in range(worker_count) if len(items[m * i:m * (i + 1)]) > 0]

    def _price_one_side(self, price_type: str) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
        assert self.curve is not None and self.env_other is not None and self.bond_ref_df is not None
        logger.info(f"Pricing {self.obtype} {price_type} side...")
        # factor extraction with NaN-safe reference
        ref_series = self.bond_ref_df[price_type].dropna()
        self.curve.extractFactors(ref_series, self.curve.reference)

        total = len(self.obonds_quo)
        if total == 0:
            return pd.DataFrame(), pd.DataFrame(), self.curve.fitting()
        worker_count = max(1, min(self.max_workers, total))
        buckets = self._make_buckets(self.obonds_quo, worker_count)

        if total <= 500 or worker_count == 1 or len(buckets) <= 1:
            dict_p = [self.curve.affinePricing(self.env_other['Def'], b) for b in buckets]
        else:
            try:
                with Pool(processes=min(worker_count, len(buckets))) as pool:
                    dict_p = pool.starmap(self.curve.affinePricing, [(self.env_other['Def'], b) for b in buckets])
            except Exception as e:
                logger.warning(f"Parallel pricing failed ({e}), falling back to sequential")
                dict_p = [self.curve.affinePricing(self.env_other['Def'], b) for b in buckets]

        dict_quote = {i: dict_p[i][0] for i in range(len(dict_p))}
        dict_sen = {i: dict_p[i][1] for i in range(len(dict_p))}
        quote_df = pd.concat(dict_quote).droplevel(0).sort_index()
        sen_df = pd.concat(dict_sen).droplevel(0).sort_index()
        quote_df = quote_df.apply(pd.to_numeric, errors='coerce').dropna()
        sen_df = sen_df.apply(pd.to_numeric, errors='coerce').dropna()
        return quote_df, sen_df, self.curve.fitting()

    # ------------- Orchestration -------------
    def run(self) -> Dict[str, Any]:
        # calc date
        d = DateConfig.get_date_mappings()['d']
        logger.info(f"Refresh Market Data for {self.obtype} at: {d.strftime('%H:%M:%S')}")
        calc_date = d.date()
        # load
        self._load_curve_and_base_px()
        self._load_envs_and_stats()
        self.refresh_and_prepare(calc_date)

        # price both sides
        quotedict: Dict[str, pd.DataFrame] = {}
        sendict: Dict[str, pd.DataFrame] = {}
        curvedict: Dict[str, Dict[str, Any]] = {}
        for side in ['Bid', 'Ofr']:
            q, s, cfit = self._price_one_side(side)
            quotedict[side] = q
            sendict[side] = s
            curvedict[side] = cfit
            logger.info(f"Finished computing {self.obtype} {side} curve at: {datetime.now().strftime('%H:%M:%S')}")

        # combine with TBond sensitivity
        sen_other = (sendict.get('Bid', pd.DataFrame()) + sendict.get('Ofr', pd.DataFrame())) / 2
        sen_combined = pd.concat([self.pxrt_base['Sen'], sen_other], axis=0)
        opxrt = {
            'Curve': (curvedict['Bid'] + curvedict['Ofr']) / 2,
            'Quote': statAdjust(quotedict, self.env_other, self.stat_other[self.obtype + 'Spread']),
            'Sen': sen_combined,
        }
        self._save_results(opxrt)
        logger.info(f"Finished refreshing {self.obtype} at: {datetime.now().strftime('%H:%M:%S')}")
        return opxrt

    @classmethod
    def main(cls, other_bond_type=None, max_workers=None):
        """Main entry point for the CreditSpreadRefresher"""
        if other_bond_type is None:
            other_bond_type = next(iter(BondConfig.INCLUDE_FILTERS.keys()), 'LBond')
        try:
            instance = cls(other_bond_type=other_bond_type, max_workers=max_workers)
            instance.run()
        except Exception as e:
            logger.error(f"Error in main execution: {e}")
            raise

    def _save_results(self, opxrt: Dict[str, Any]) -> None:
        out_path = os.path.join(DIR_INPUT, f'{self.obtype}-rtquo.pkl')
        with open(out_path, 'wb') as f:
            pickle.dump(opxrt, f)
# "LBond, GBond,BBond, MNote"
def main(other_bond_type='GBond', max_workers=None):
    try:
        CreditSpreadRefresher.main(other_bond_type=other_bond_type, max_workers=max_workers)
    except Exception as e:
        logger.error(f"Error in main execution: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()