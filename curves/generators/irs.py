# -*- coding: utf-8 -*-
"""
Created on Wed Nov 15 15:19:34 2023
Simplified and optimized IRS curve generator

Author: 马云飞
"""
import os
import sys
import pickle
import pathlib
import pandas as pd
from datetime import timedelta, datetime
from dateutil.relativedelta import relativedelta
import warnings

warnings.filterwarnings('ignore')

# local libraries
PATH = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(PATH))

from settings.paths import DIR_INPUT
from settings.fixed_income import IRSConfig
from settings.general import GeneralConfig, DateConfig
from curves.calibration.irscurves import evalueContract, irsSpreads, genIRSCurves, curves2Fixings
from curves.utils.loader import loadInstrumentDefinition, loadCNBDTS, loadCurvePxTS
from curves.utils.file import updatePKL


class IRSGenerator:
    """Generate IRS curves and update curve price time series with optimized operations."""

    def __init__(self, btype: str = 'IRS') -> None:
        self.btype = btype
        dates = DateConfig.get_date_mappings()
        self.trade_date = dates['d'].date()
        self.pricing_date = dates['dp'].date()
        self.environment = None
        self.environment_ts = None
        self.curves = {}
        self.forward_data = None
        self.contracts = None
        
    def load_environment(self) -> None:
        """Load instrument definition and time series"""
        self.environment = loadInstrumentDefinition(self.btype)
        self.environment_ts = loadCNBDTS()['SwapTS']
       
    def generate_close_curves(self) -> None:
        """Generate IRS close curves"""
        irs_ref = {'r7d': list(IRSConfig.R7D_LIST.keys()), 's3m': list(IRSConfig.S3M_LIST.keys())}
        self.curves['close'] = genIRSCurves(self.environment_ts, irs_ref, self.trade_date)

    def persist_curves(self) -> None:
        """Save curves to file"""
        filepath = os.path.join(DIR_INPUT, f"{self.btype}-cvrt.obj")
        with open(filepath, 'wb') as file:
            pickle.dump(self.curves['close'], file)

    def prepare_forward_data(self) -> None:
        """Prepare forward data from curves"""
        self.forward_data = curves2Fixings(self.pricing_date, self.environment_ts, self.curves['close'])

    def evaluate_contracts(self) -> None:
        """Evaluate IRS contracts"""
        quotes_today = self.environment_ts.loc[self.pricing_date, IRSConfig.IRS_LIST]
        self.contracts = evalueContract(self.pricing_date, quotes_today, self.forward_data, 1)

    def update_curve_px_timeseries(self) -> None:
        """Update curve price time series"""
        if self.contracts is None:
            print('Warning: Contracts are not evaluated; skipping curve px update.')
            return

        curve_px = loadCurvePxTS(self.btype)

        try:
            # Vectorized assignment into wide DataFrames
            if 'ytm_act' in curve_px and 'ytm_quo' in curve_px:
                contracts = IRSConfig.IRS_LIST
                act_values = self.contracts['value'].loc[contracts, 'Quote'].values
                quo_values = self.contracts['value'].loc[contracts, 'FixRate'].values
                curve_px['ytm_act'].loc[self.pricing_date, contracts] = act_values
                curve_px['ytm_quo'].loc[self.pricing_date, contracts] = quo_values
        except Exception as e:
            print(f'Error: Failed vectorized assignment into curve price TS: {e}')
            raise

        filepath = os.path.join(DIR_INPUT, f"{self.btype}-cvpx.pkl")
        updatePKL(curve_px, filepath)

    def compute_spread_statistics(self) -> pd.DataFrame:
        """Compute spread statistics for the given window"""
        start_window = self.trade_date - relativedelta(months=GeneralConfig.STAT_WINDOW)
        end_window = self.trade_date - timedelta(hours=1)
        qtpx = self.environment_ts.loc[start_window:end_window]
        return irsSpreads(qtpx)

    def run(self) -> None:
        """Run the complete IRS generation process"""
        self.load_environment()
        self.generate_close_curves()
        self.persist_curves()
        self.prepare_forward_data()
        self.evaluate_contracts()
        self.update_curve_px_timeseries()
        
        # Optionally compute spreads (non-critical)
        try:
            _ = self.compute_spread_statistics()
        except Exception:
            pass  # Skip silently if spreads fail

    @classmethod
    def main(cls):
        """Main entry point for the IRSGenerator"""
        instance = cls()
        instance.run()


def main() -> None:
    IRSGenerator.main()


if __name__ == '__main__':
    main()