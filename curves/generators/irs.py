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
from datetime import timedelta, datetime, date
from dateutil.relativedelta import relativedelta
from typing import Optional
import warnings

warnings.filterwarnings('ignore')


import re

# local libraries
PATH = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(PATH))

from settings.paths import DIR_INPUT
from settings.fixed_income import IRSConfig
from settings.general import GeneralConfig, DateConfig
from curves.calibration.irscurves import evalueContract, irsSpreads, genIRSCurves, curves2Fixings
from curves.utils.loader import loadInstrumentDefinition, loadCNBDTS, loadCurvePxTS
from curves.utils.file import updatePKL


_LEGACY_REPO_PREFIX = re.compile(r'^Repo-', re.IGNORECASE)


def _normalize_legacy_repo_label(value):
    if isinstance(value, str):
        return _LEGACY_REPO_PREFIX.sub('Repo7d-', value)
    return value


def _normalize_legacy_repo_frame(frame):
    if not isinstance(frame, pd.DataFrame):
        return frame
    out = frame.copy()
    if out.index.dtype == object:
        out.index = out.index.map(_normalize_legacy_repo_label)
    if out.columns.dtype == object:
        out.columns = out.columns.map(_normalize_legacy_repo_label)
    return out


class IRSGenerator:
    """Generate IRS curves and update curve price time series with optimized operations."""

    def __init__(self, btype: str = 'IRS', asof: Optional[date] = None) -> None:
        self.btype = btype
        dates = DateConfig.get_date_mappings(asof=asof)
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
        swap_ts = _normalize_legacy_repo_frame(loadCNBDTS()['SwapTS'])
        # If the cached data doesn't reach pricing_date, re-fetch from Wind so
        # evaluate_contracts can do a .loc[pricing_date] lookup without a KeyError.
        swap_last = pd.Timestamp(swap_ts.index[-1]).date() if (swap_ts is not None and not swap_ts.empty) else None
        if swap_last is not None and swap_last < self.pricing_date:
            print(f"INFO: database-px.pkl IRS data ends {swap_last}, need {self.pricing_date} — re-fetching from Wind...")
            try:
                from curves.utils.retrieve import retrieveCNBDTS
                retrieveCNBDTS()
                swap_ts = _normalize_legacy_repo_frame(loadCNBDTS()['SwapTS'])
                new_last = pd.Timestamp(swap_ts.index[-1]).date() if not swap_ts.empty else swap_last
                print(f"INFO: after re-fetch, IRS data ends {new_last}")
            except Exception as exc:
                print(f"WARN: Could not re-fetch IRS data from Wind: {exc}")
        self.environment_ts = swap_ts
       
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
        available = [c for c in IRSConfig.IRS_LIST if c in self.environment_ts.columns]
        quotes_today = self.environment_ts.reindex(columns=IRSConfig.IRS_LIST).loc[self.pricing_date]
        self.contracts = evalueContract(self.pricing_date, quotes_today, self.forward_data, 1)
        self._available_quote_instruments = available

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
                act_values = self.contracts['value'].loc[contracts, 'Quote']
                quo_values = self.contracts['value'].loc[contracts, 'FixRate'].values
                # Only write ytm_act for instruments with a real market quote
                act_instruments = getattr(self, '_available_quote_instruments', contracts)
                act_instruments_with_data = [c for c in act_instruments if pd.notna(act_values.loc[c])]
                if act_instruments_with_data:
                    curve_px['ytm_act'].loc[self.pricing_date, act_instruments_with_data] = act_values.loc[act_instruments_with_data].values
                elif self.pricing_date not in curve_px['ytm_act'].index:
                    # No quotes available; write NaN placeholder so updatePKL can forward-fill from the prior date
                    curve_px['ytm_act'].loc[self.pricing_date] = float('nan')
                curve_px['ytm_quo'].loc[self.pricing_date, contracts] = quo_values

            # Update carry3m and roll3m time series so StatGenerator can build CarryRoll3m
            for key, col in [('carry3m', 'Carry(3m,bp)'), ('roll3m', 'Roll(3m,bp)')]:
                if col in self.contracts['value'].columns:
                    values = self.contracts['value'].loc[IRSConfig.IRS_LIST, col].values / 100
                    if key not in curve_px:
                        curve_px[key] = pd.DataFrame(columns=IRSConfig.IRS_LIST)
                    curve_px[key].loc[self.pricing_date, IRSConfig.IRS_LIST] = values
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
    def main(cls, date: Optional[str] = None):
        """Main entry point for the IRSGenerator.

        Args:
            date: Optional date string in YYYYMMDD format. Defaults to today.
        """
        asof = None
        if date:
            try:
                asof = datetime.strptime(date, '%Y%m%d').date()
            except (ValueError, TypeError):
                pass
        instance = cls(asof=asof)
        instance.run()


def main(date:  Optional[str] = None) -> int:
    print("Starting IRS curve generation.")
    try:
        IRSGenerator.main(date=date)
        print("IRS curve generation completed successfully.")
        return 0
    except Exception as e:
        print(f"IRS curve generation failed: {e}")
        return 1


if __name__ == '__main__':
    import sys as _sys
    _date = "20260609"#_sys.argv[1] if len(_sys.argv) > 1 else None
    _sys.exit(main(date=_date))