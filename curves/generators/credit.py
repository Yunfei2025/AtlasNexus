# -*- coding: utf-8 -*-
"""
Created on Wed Feb 28 22:11:22 2024

@author: CMBC
Refactored with OOP and improved performance
"""

import os
import sys
import pathlib
import datetime
import argparse
from functools import partial

import numpy as np
import pandas as pd

# parallel computing libraries
from multiprocessing import Pool

# local libraries
PATH = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(PATH))

from curves.calibration.selector import update_price
from curves.utils.loader import loadCurvePxTS, loadInstrumentDefinition
from curves.utils.file import updatePKL
from settings.paths import DIR_INPUT 
from settings.general import GeneralConfig, DateConfig


def _parse_date(date_value=None) -> datetime.date:
    if date_value is None:
        return DateConfig.get_date_mappings()['d'].date()
    if isinstance(date_value, datetime.datetime):
        return date_value.date()
    if isinstance(date_value, datetime.date):
        return date_value
    return datetime.datetime.strptime(str(date_value), "%Y%m%d").date()

class CreditSpreadGenerator:
    """Compute and persist daily curve pricing for a given bond type."""

    def __init__(self, object_type: str, num_cores: int = GeneralConfig.N_CORE, date=None) -> None:
        self.object_type = object_type
        self.num_cores = max(1, int(num_cores))
        self.today = _parse_date(date)
        self.prev_business_day = DateConfig.prev_cn_workday(self.today - datetime.timedelta(days=1))
        self._env = None
        self._curve_by_date = None

    def load_environment(self) -> None:
        self._env = loadInstrumentDefinition(self.object_type)
        if 'Def' not in self._env or not isinstance(self._env['Def'], pd.DataFrame):
            raise ValueError('Invalid instrument definition loaded for %s' % self.object_type)

    def load_curve_objects(self) -> None:
        # Curve objects are stored in TBond-cvobj.pkl historically
        self._curve_by_date = updatePKL({}, os.path.join(DIR_INPUT, 'TBond-cvobj.pkl'))
        if self.prev_business_day not in self._curve_by_date:
            raise KeyError('Curve not found for date %s' % self.prev_business_day)

    def _build_buckets(self, candidates: pd.Index) -> list:
        if len(candidates) == 0:
            return []
        # Balanced split to avoid skew
        parts = np.array_split(candidates, self.num_cores)
        return [p for p in parts if len(p) > 0]

    def _price_buckets_parallel(self, curve0, definition_df: pd.DataFrame, buckets: list) -> list:
        # Use context manager for proper Pool cleanup
        with Pool(processes=self.num_cores) as pool:
            print('\nPricing in parallel for %s with %d cores' % (self.object_type, self.num_cores))
            results = list(pool.imap_unordered(partial(curve0.affinePricing, definition_df), buckets))
        return results

    def _aggregate_quotes(self, results: list) -> tuple:
        # results: list of tuples (quote_df, sen_df)
        if len(results) == 0:
            return pd.DataFrame(), pd.DataFrame()
        quote_frames = [r[0] for r in results if r is not None]
        sen_frames = [r[1] for r in results if r is not None]
        quote0 = pd.concat(quote_frames).sort_index()
        sen0 = pd.concat(sen_frames).sort_index()
        # ensure numeric and drop NaNs
        quote0 = quote0.apply(pd.to_numeric, errors='coerce').dropna()
        sen0 = sen0.apply(pd.to_numeric, errors='coerce').dropna()
        return quote0, sen0

    def _persist(self, quote0: pd.DataFrame, sen0: pd.DataFrame) -> None:
        obond_px = loadCurvePxTS(self.object_type)
        obond_px = update_price(obond_px, quote0, sen0, self._env['Def'], self.prev_business_day)
        for k in obond_px.keys():
            obond_px[k].index = [d for d in obond_px[k].index]
        updatePKL(obond_px, os.path.join(DIR_INPUT, f'{self.object_type}-cvpx.pkl'))

    def run(self) -> None:
        t0 = datetime.datetime.now()
        self.load_environment()
        self.load_curve_objects()

        curve0 = self._curve_by_date[self.prev_business_day]
        # filter candidates within 10Y remaining maturity
        definition_df = self._env['Def']
        candidates = definition_df[definition_df['剩余期限'] < 10.].index
        buckets = self._build_buckets(candidates)

        if not buckets:
            print('No candidates to price for %s' % self.object_type)
            return

        results = self._price_buckets_parallel(curve0, definition_df, buckets)
        quote0, sen0 = self._aggregate_quotes(results)
        if quote0.empty or sen0.empty:
            print('No valid quotes generated for %s' % self.object_type)
            return

        self._persist(quote0, sen0)

        print('\nFinished initializing %s Spread at: %s (elapsed %.2fs)'
              % (self.object_type,
                 datetime.datetime.now().strftime('%H:%M:%S'),
                 (datetime.datetime.now() - t0).total_seconds()))

    @classmethod
    def main(cls, bond_type, num_cores=None, date=None):
        """Main entry point for the CreditSpreadGenerator"""
        if num_cores is None:
            num_cores = GeneralConfig.N_CORE
        instance = cls(bond_type, num_cores, date=date)
        instance.run()

def main(bond_type = 'LBond', date="20260604"):#None):
    print(f"🚀 Starting {bond_type} curve generation.")
    try:
        CreditSpreadGenerator.main(bond_type=bond_type, date=date)
        print("✅ Curve generation completed successfully!")
    except Exception as e:
        print(f"❌ Curve generation failed: {e}")

if __name__ == '__main__':
    main()

    