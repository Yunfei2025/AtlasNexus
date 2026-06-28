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

    def _set_asof(self, asof: date) -> None:
        """Set the trading and pricing dates for a specific historical day."""
        dates = DateConfig.get_date_mappings(asof=asof)
        self.trade_date = dates['d'].date()
        self.pricing_date = dates['dp'].date()

    def backfill_history(self, start_date: Optional[date] = None, end_date: Optional[date] = None) -> None:
        """Rebuild IRS curve-price history across a historical date range.

        This is an opt-in maintenance path for reconstructing IRS-cvpx.pkl from the
        raw swap history in database-px.pkl.
        """
        self.load_environment()

        available_dates = pd.Index(pd.to_datetime(self.environment_ts.index).date).unique().sort_values()
        if available_dates.empty:
            raise ValueError('No IRS history available for backfill.')

        start_bound = start_date or available_dates[0]
        end_bound = end_date or available_dates[-1]
        target_dates = [d for d in available_dates if start_bound <= d <= end_bound]
        if not target_dates:
            raise ValueError(f'No IRS dates found between {start_bound} and {end_bound}.')

        print(f'Backfilling IRS history from {target_dates[0]} to {target_dates[-1]} ({len(target_dates)} days)...')
        for i, current_date in enumerate(target_dates, start=1):
            self._set_asof(current_date)
            self.generate_close_curves()
            self.persist_curves()
            self.prepare_forward_data()
            self.evaluate_contracts()
            self.update_curve_px_timeseries()
            if i % 50 == 0 or i == len(target_dates):
                print(f'Backfilled {i}/{len(target_dates)} IRS days through {current_date}')

    @classmethod
    def backfill_main(cls, start: Optional[str] = None, end: Optional[str] = None) -> int:
        """CLI entry point for historical IRS backfill."""
        def _parse(value: Optional[str]) -> Optional[date]:
            if not value:
                return None
            try:
                return datetime.strptime(value, '%Y%m%d').date()
            except (ValueError, TypeError):
                try:
                    return datetime.strptime(value, '%Y-%m-%d').date()
                except Exception:
                    return None

        instance = cls(asof=_parse(end) or None)
        instance.backfill_history(start_date=_parse(start), end_date=_parse(end))
        return 0
       
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
                # Only write ytm_act for instruments with a real market quote; instruments
                # with no quote today are left out so updatePKL keeps them NaN instead of
                # carrying forward a stale value.
                act_instruments = getattr(self, '_available_quote_instruments', contracts)
                act_instruments_with_data = [c for c in act_instruments if pd.notna(act_values.loc[c])]
                if act_instruments_with_data:
                    curve_px['ytm_act'].loc[self.pricing_date, act_instruments_with_data] = act_values.loc[act_instruments_with_data].values
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
    def main(cls, date: Optional[str] = None, *, backfill: bool = False,
             start_date: Optional[str] = None, end_date: Optional[str] = None):
        """Main entry point for the IRSGenerator.

        Args:
            date: Optional date string in YYYYMMDD format. Defaults to today.
        """
        def _parse(value: Optional[str]) -> Optional[date]:
            if not value:
                return None
            try:
                return datetime.strptime(value, '%Y%m%d').date()
            except (ValueError, TypeError):
                try:
                    return datetime.strptime(value, '%Y-%m-%d').date()
                except Exception:
                    return None

        if backfill:
            instance = cls(asof=_parse(end_date or date) or None)
            instance.backfill_history(start_date=_parse(start_date), end_date=_parse(end_date or date))
            return 0

        asof = _parse(date)
        instance = cls(asof=asof)
        instance.run()
        return 0


def main(date:  Optional[str] = None, *, backfill: bool = False,
         start_date: Optional[str] = None, end_date: Optional[str] = None) -> int:
    print("Starting IRS curve generation.")
    try:
        IRSGenerator.main(date=date, backfill=backfill, start_date=start_date, end_date=end_date)
        print("IRS curve generation completed successfully.")
        return 0
    except Exception as e:
        print(f"IRS curve generation failed: {e}")
        return 1


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Generate or backfill IRS curve history')
    parser.add_argument('--date', default='20260609', help='Target date in YYYYMMDD or YYYY-MM-DD format')
    parser.add_argument('--backfill', action='store_true', help='Backfill historical IRS curve-price data')
    parser.add_argument('--start-date', dest='start_date', default=None, help='Backfill start date in YYYYMMDD or YYYY-MM-DD format')
    parser.add_argument('--end-date', dest='end_date', default=None, help='Backfill end date in YYYYMMDD or YYYY-MM-DD format')
    args = parser.parse_args()
    _sys_exit = main(date=args.date, backfill=args.backfill, start_date=args.start_date, end_date=args.end_date)
    raise SystemExit(_sys_exit)