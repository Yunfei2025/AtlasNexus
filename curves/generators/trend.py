import os
import sys
import pickle
import datetime
from datetime import date
import pathlib
import pandas as pd
from dateutil.relativedelta import relativedelta
from typing import Optional
import time
import traceback

# local libraries
PATH = pathlib.Path(__file__).parent.parent.parent
if str(PATH) not in sys.path:
    sys.path.insert(0, str(PATH))

from settings.paths import DIR_INPUT, DIR_DATA
from settings.fixed_income import InstitutionConfig
from settings.general import DateConfig
from curves.utils.plot import plotTrend
from curves.calibration.trend import genTrendLine
from curves.utils.loader import loadCNBDTS
from curves.utils.file import updatePKL

class TrendGenerator:
    def __init__(self, as_of_date=None):
        self.as_of_date = as_of_date or DateConfig.get_date_mappings()['d'].date()
        self.start_date = self.as_of_date - relativedelta(years=1)
        self.dir_input = pathlib.Path(DIR_INPUT)
        self.dir_data = pathlib.Path(DIR_DATA)
        # Load environment once
        self.env = loadCNBDTS()

    # -------------
    # Trend figures
    # -------------
    def _build_series(self):
        desired_columns = ['中债国债到期收益率:1年', '中债国债到期收益率:2年', '中债国债到期收益率:5年', '中债国债到期收益率:10年',
                           '中债国债到期收益率:30年']
        vT = self.env['CGB'].loc[self.start_date:self.as_of_date, desired_columns]
        dvT = vT[['中债国债到期收益率:1年', '中债国债到期收益率:5年',
                   '中债国债到期收益率:10年', '中债国债到期收益率:30年']].diff(axis=1).dropna(axis=1)
        dvT.columns = ['中债国债到期收益率:5年-1年', '中债国债到期收益率:10年-5年', '中债国债到期收益率:30年-10年']
        vI = self.env['SwapTS'].loc[self.start_date:self.as_of_date, ['FR007S1Y.IR', 'FR007S2Y.IR', 'FR007S5Y.IR']]
        dvI = vI.diff(axis=1).dropna(axis=1)
        dvI.columns = ['FR007:2Y-1Y', 'FR007:5Y-2Y']
        dvI['FR007:5Y-1Y'] = vI['FR007S5Y.IR'] - vI['FR007S1Y.IR']
        dvI['TBond-FR007:1Y'] = vT['中债国债到期收益率:1年'] - vI['FR007S1Y.IR']
        dvI['TBond-FR007:2Y'] = vT['中债国债到期收益率:2年'] - vI['FR007S2Y.IR']
        dvI['TBond-FR007:5Y'] = vT['中债国债到期收益率:5年'] - vI['FR007S5Y.IR']

        vFixing = self.env['SwapTS'].loc[self.start_date:self.as_of_date, ['FR001.IR', 'FR007.IR', 'SHIBOR3M.IR']]
        vFactors = self.env['Factors'].loc[self.start_date:self.as_of_date, ].astype(float).round(2)

        return vT, dvT, vI, dvI, vFixing, vFactors

    def generate_trend_figures(self, slope: float = 0.02):
        vT, dvT, vI, dvI, vFixing, vFactors = self._build_series()
        figures = {}

        vTa = pd.concat([vT, dvT], axis=1)
        for col in vTa.columns:
            if col == '中债国债到期收益率:20年':
                continue
            dfp = genTrendLine(vTa[col], slope)
            figures[col] = plotTrend(dfp, vFixing, vFactors)

        vIa = pd.concat([vI, dvI], axis=1)
        for col in vIa.columns:
            dfp = genTrendLine(vIa[col], slope)
            figures[col] = plotTrend(dfp, vFixing, vFactors)
        return figures

    def save_trend_figures(self, figures: dict, filename: str = 'trend-fig.obj'):
        out_path = self.dir_input.joinpath(filename)
        with open(out_path, 'wb') as f:
            pickle.dump(figures, f)

    # -----------
    # Positions
    # -----------
    def _empty_positions(self):
        template_cols = [f"{b}:{t}" for b in InstitutionConfig.BOND_TYPES for t in InstitutionConfig.TERM_BUCKETS]
        return {inst: pd.DataFrame(columns=template_cols) for inst in InstitutionConfig.INSTITUTION_TYPES}

    @staticmethod
    def _parse_date_from_filename(fname: str) -> datetime.date:
        # expects ...-YYYYMMDD.xlsx
        try:
            di = fname.split('-')[1].split('.')[0]
            return datetime.datetime.strptime(di, '%Y%m%d').date()
        except Exception:
            return None

    def build_positions(self):
        positions = self._empty_positions()
        pos_dir = self.dir_data.joinpath('positions')
        print(f"INFO: TrendGenerator: positions directory: {pos_dir}", flush=True)
        if not pos_dir.exists():
            print("INFO: TrendGenerator: positions directory does not exist, returning empty positions", flush=True)
            return positions
        try:
            files = os.listdir(pos_dir)
        except Exception as e:
            print(f"ERROR: listing positions directory {pos_dir}: {e}", flush=True)
            print(traceback.format_exc(), flush=True)
            return positions
        print(f"INFO: TrendGenerator: found {len(files)} files in positions dir", flush=True)
        for fname in files:
            # Skip files matching the legacy "现券成交分机构统计" series
            if fname.startswith('现券成交分机构统计'):
                print(f"INFO: TrendGenerator: skipping legacy positions file: {fname}", flush=True)
                continue
            print(f"INFO: TrendGenerator: processing positions file: {fname}", flush=True)
            file_start = time.perf_counter()
            as_of = self._parse_date_from_filename(fname)
            if not as_of:
                print(f"INFO: TrendGenerator: skipping file (date parse failed): {fname}", flush=True)
                continue
            try:
                positions_df = pd.read_excel(
                    pos_dir.joinpath(fname),
                    sheet_name='机构净买入债券成交金额统计表',
                    skiprows=3,
                    index_col=(0, 1),
                )
            except Exception as e:
                print(f"ERROR: TrendGenerator: failed to read Excel {fname}: {e}", flush=True)
                print(traceback.format_exc(), flush=True)
                continue
            for inst in InstitutionConfig.INSTITUTION_TYPES:
                for b in InstitutionConfig.BOND_TYPES:
                    try:
                        pos_ = positions_df.loc[inst, b].replace('--', 0)
                        pos_ = pos_.astype(float).to_frame().T
                        pos_.columns = [f"{b}:{t}" for t in InstitutionConfig.TERM_BUCKETS]
                        positions[inst].loc[as_of, pos_.columns] = pos_.values
                    except Exception:
                        print(f"WARNING: TrendGenerator: failed to process inst={inst} bond={b} in file {fname}", flush=True)
                        print(traceback.format_exc(), flush=True)
                        continue
            file_elapsed = time.perf_counter() - file_start
            print(f"INFO: TrendGenerator: finished {fname} in {file_elapsed:.3f}s", flush=True)

        for inst in positions:
            positions[inst].sort_index(inplace=True)
        return positions

    def save_positions(self, positions: dict, filename: str = 'positions.pkl'):
        out_path = self.dir_input.joinpath(filename)
        return updatePKL(positions, str(out_path))


    @classmethod
    def main(cls, date: Optional[str] = None):
        """Class method to run trend generation.

        Args:
            date: Optional date string in YYYYMMDD format
        """
        import datetime as dt
        as_of_date = None
        if date:
            try:
                as_of_date = dt.datetime.strptime(date, '%Y%m%d').date()
            except (ValueError, TypeError):
                pass
        instance = cls(as_of_date=as_of_date)
        instance.generate_and_save_trends()
    
    def generate_and_save_trends(self):
        """Generate and save trend analysis."""
        print('INFO: TrendGenerator: building trend figures...', flush=True)
        figures = self.generate_trend_figures()
        print(f'INFO: TrendGenerator: trend figures built ({len(figures)})', flush=True)

        print('INFO: TrendGenerator: saving trend figures...', flush=True)
        self.save_trend_figures(figures)

        # positions = self.build_positions()
        #self.save_positions(positions)
        print('\nFinish analysing trends at:', datetime.datetime.now().strftime("%H:%M:%S"), flush=True)


if __name__ == '__main__':
    TrendGenerator.main()
    
