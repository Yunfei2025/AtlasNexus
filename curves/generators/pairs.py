"""
Created on Wed Jul  5 13:59:25 2025

Refactor: OOP structure with performance improvements for curve reference refreshing
@author: 马云飞
"""
import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from curves.utils.loader import loadInstrumentDefinition
from settings.paths import DIR_INPUT
from settings.fixed_income import BondConfig, IRSConfig


def swap_dv01(term_years, rate=0.015, freq=4):
    """Approximate swap DV01 using a simple annuity formula."""
    alpha = 1.0 / freq
    n = int(round(term_years * freq))
    v = 1.0 / (1.0 + rate / freq)  # discount per period
    annuity = alpha * (v * (1 - v**n) / (1 - v)) if n > 0 else 0.0
    return annuity


class PairsGenerator:
    """Generates and enriches carry-roll pairs with regression statistics."""

    def __init__(self, min_cr: float = 30.0, lookback_days: int = 60):
        """
        Parameters
        ----------
        min_cr : float
            Minimum CR threshold for filtering pairs.
        lookback_days : int
            Number of days of historical data to use for regression.
        """
        self.min_cr = min_cr
        self.lookback_days = lookback_days
        self._instr = None
        self._common_short = None
        self._group_list = None
        self.cr_df = None

    @staticmethod
    def _compute_mdur_irs() -> pd.Series:
        """Compute IRS modified duration proxy as a Series indexed by IRS code."""
        mdur = {}
        for c in IRSConfig.IRS_LIST:
            label = c.split(".")[0][6:]
            if 'M' in label:
                T = int(label[:-1])
                mdur[c] = 0.9 * T / 12  # month-based proxy
            else:
                T = int(label[:-1])
                mdur[c] = swap_dv01(T)
        return pd.Series(mdur, name='Mdur')

    @staticmethod
    def _filter_short_codes(codes):
        """Exclude tenors containing '7Y' or '10Y'."""
        try:
            return [c for c in codes if ('7Y' not in str(c)) and ('10Y' not in str(c))]
        except Exception:
            return []

    def _prepare_instruments(self, mdur_irs: pd.Series) -> tuple:
        """Load inputs, compute CR metrics, and assemble instrument table.

        Returns
        -------
        tuple
            (instr, common_short, group_list)
            - instr: DataFrame indexed by instrument code with columns 'CR(3m,bp)', 'CRShort(3m,bp)', 'Mdur', 'Type'
            - common_short: list of instruments eligible for short leg
            - group_list: instruments excluding common_short (eligible long leg)
        """
        rfr = pd.read_pickle(os.path.join(DIR_INPUT, "database-px.pkl"))['IRS']['FR001.IR'].iloc[-1]

        out = {}
        btype_list = ["TBond", "CBond"] + list(BondConfig.INCLUDE_FILTERS.keys()) + ["IRS"]
        short_list = []

        for btype in btype_list:
            out[btype] = pd.DataFrame()
            results = pd.read_pickle(os.path.join(DIR_INPUT, f"{btype}-spdsrt.pkl"))
            if btype in ["TBond", "CBond"]:
                spreads = results["BondCurve"]
                new_list = pd.read_pickle(os.path.join(DIR_INPUT, f"{btype}-cvref.pkl"))['RefBond'].iloc[-1][-4:]
                short_list.extend(self._filter_short_codes(list(new_list)))
            elif btype == "IRS":
                spreads = results['spreads'].loc[IRSConfig.IRS_LIST]
            else:
                spreads = results

            out[btype]['CR(3m,bp)'] = spreads['Carry(3m,bp)'] + spreads['Roll(3m,bp)']

            if btype != "IRS":
                env = loadInstrumentDefinition(btype)
                out[btype]['Mdur'] = env['Def']['修正久期']
                common = env['Def'].index.intersection(out[btype].index)

                dur = env['Def']['修正久期']
                BC = pd.Series(index=env['Def'].index, dtype=float)
                BC.loc[dur < 8] = 20
                BC.loc[(dur >= 8) & (dur <= 10)] = 30
                BC.loc[dur > 10] = 120

                out[btype].loc[common, 'CRShort(3m,bp)'] = (
                    100 * (rfr - env['Def'].loc[common, '票面利率:%']) / 4
                    - spreads.loc[common, 'Roll(3m,bp)']
                    - BC.loc[common] / 4
                )

                new_list = out[btype].index[out[btype]['CRShort(3m,bp)'] > 0]
                short_list.extend(self._filter_short_codes(list(new_list)))
            else:
                out[btype]['Mdur'] = mdur_irs
                out[btype]['CRShort(3m,bp)'] = spreads['Carry(3m,bp)'] + spreads['Roll(3m,bp)']
                short_list.extend(self._filter_short_codes(list(out[btype].index)))
            out[btype]['Type'] = btype

        instr = pd.concat(out, axis=0).dropna()
        instr.index = instr.index.droplevel(0)
        common_short = list(instr.index.intersection(short_list))
        group_list = [b for b in instr.index if b not in common_short]
        return instr, common_short, group_list

    def _compute_cr_pairs(self, instr: pd.DataFrame, group_list: list, common_short: list) -> pd.DataFrame:
        """Vectorized computation of CR pairs into a long DataFrame.

        For long instrument b and short instrument s:
          if Mdur[b] >= Mdur[s]:
              CR = CR[b] + floor(Mdur[b]/Mdur[s]) * CRShort[b]; Ratio = floor(Mdur[b]/Mdur[s])
          else:
              CR = CR[b] + CRShort[b] / floor(Mdur[s]/Mdur[b]); Ratio = 1 / floor(Mdur[s]/Mdur[b])
        """
        if not group_list or not common_short:
            return pd.DataFrame(columns=['Long', 'Short', 'CR', 'Ratio', 'LongType', 'ShortType'])

        rows = instr.loc[group_list]
        cols = instr.loc[common_short]

        row_CR = rows['CR(3m,bp)'].to_numpy(dtype=float)
        row_CRShort = rows['CRShort(3m,bp)'].to_numpy(dtype=float)
        row_Mdur = rows['Mdur'].to_numpy(dtype=float)
        col_Mdur = cols['Mdur'].to_numpy(dtype=float)

        R = row_Mdur.shape[0]
        C = col_Mdur.shape[0]

        num = row_Mdur[:, None]
        den = col_Mdur[None, :]

        with np.errstate(divide='ignore', invalid='ignore'):
            ratio_raw = np.divide(num, den, where=(den != 0))
            mask_ge = ratio_raw >= 1
            ratio_ge = np.floor(ratio_raw)

            inv_ratio_raw = np.divide(den, num, where=(num != 0))
            ratio_lt = np.floor(inv_ratio_raw)

        ratio_lt[ratio_lt < 1] = 1  # guard

        base = row_CR[:, None]
        adj = np.where(mask_ge, row_CRShort[:, None] * ratio_ge, row_CRShort[:, None] / ratio_lt)
        cr_mat = base + adj

        ratio_mat = np.where(mask_ge, ratio_ge, 1.0 / ratio_lt)

        # Flatten to long format
        longs = np.repeat(np.asarray(group_list), C)
        shorts = np.tile(np.asarray(common_short), R)
        cr_flat = cr_mat.reshape(-1)
        ratio_flat = ratio_mat.reshape(-1)
        longtype = instr.loc[longs, 'Type']
        shorttype = instr.loc[shorts, 'Type']
        df = pd.DataFrame({
            'Long': longs,
            'Short': shorts,
            'CR': cr_flat.round(),
            'Ratio': ratio_flat.round(2),
            'LongType': list(longtype),
            'ShortType': list(shorttype),
        })
        return df.sort_values('CR', ascending=False).reset_index(drop=True)

    def _load_timeseries(self, cr_df: pd.DataFrame) -> pd.DataFrame:
        """Load historical YTM time series for all instruments in cr_df."""
        type_list = set(cr_df['LongType']).union(set(cr_df['ShortType']))
        ts = {}
        for t in type_list:
            llist = set(cr_df[cr_df['LongType'] == t]['Long'])
            slist = set(cr_df[cr_df['ShortType'] == t]['Short'])
            blist = list(llist.union(slist))
            ts[t] = pd.read_pickle(os.path.join(DIR_INPUT, f"{t}-cvpx.pkl"))["ytm_act"][blist].iloc[-self.lookback_days:]
        ts_all = pd.concat(ts, axis=1)
        ts_all.columns = ts_all.columns.droplevel(0)
        return ts_all

    @staticmethod
    def _regression_ols(x: np.ndarray, y: np.ndarray) -> tuple:
        """Compute OLS slope, intercept, and RMSE.

        Parameters
        ----------
        x : 1D array
            Independent variable.
        y : 1D array
            Dependent variable.

        Returns
        -------
        tuple
            (slope, intercept, rmse)
        """
        n = len(x)
        if n < 2:
            return np.nan, np.nan, np.nan
        x_mean = float(x.mean())
        y_mean = float(y.mean())
        x_center = x - x_mean
        y_center = y - y_mean
        xx = float(np.dot(x_center, x_center))
        if xx <= 0.0:
            return np.nan, np.nan, np.nan
        xy_cov = float(np.dot(x_center, y_center))
        slope = xy_cov / xx
        intercept = y_mean - slope * x_mean
        preds = slope * x + intercept
        resid = y - preds
        rmse = float(np.sqrt(np.mean(resid ** 2)))
        return slope, intercept, rmse

    def _enrich_with_regression(self, cr_df: pd.DataFrame, ts_all: pd.DataFrame) -> pd.DataFrame:
        """Add regression statistics (slope, intercept, residual, days) to cr_df."""
        for i in cr_df.index:
            df1 = ts_all[cr_df.loc[i, 'Long']]
            df2 = ts_all[cr_df.loc[i, 'Short']]
            # Spread series aligned on common dates; drop NaNs so x,y sync
            spd = (df1 - df2).dropna()
            n = int(len(spd))
            if n >= 2:
                x = np.arange(n, dtype=float)
                y = 100*spd.to_numpy(dtype=float)
                slope, intercept, rmse = self._regression_ols(x, y)
            else:
                slope, intercept, rmse = np.nan, np.nan, np.nan

            cr_df.loc[i, 'Slope'] = slope
            cr_df.loc[i, 'Intercept'] = intercept
            cr_df.loc[i, 'Residual'] = rmse
            cr_df.loc[i, 'Days'] = n
        return cr_df

    def generate(self) -> pd.DataFrame:
        """Run the full pipeline and return enriched cr_df.

        Returns
        -------
        pd.DataFrame
            Pair DataFrame with columns: Long, Short, CR, Ratio, LongType, ShortType, Slope, Intercept, Residual, Days.
        """
        # 1. Compute IRS Mdur
        mdur_irs = self._compute_mdur_irs()

        # 2. Prepare instruments
        self._instr, self._common_short, self._group_list = self._prepare_instruments(mdur_irs)

        # 3. Compute CR pairs
        cr_df = self._compute_cr_pairs(self._instr, self._group_list, self._common_short)

        # 4. Filter by minimum CR
        cr_df = cr_df[cr_df['CR'] >= self.min_cr].reset_index(drop=True)

        if cr_df.empty:
            # No pairs meet threshold
            self.cr_df = cr_df
            return cr_df

        # 5. Load time series
        ts_all = self._load_timeseries(cr_df)

        # 6. Enrich with regression statistics
        cr_df = self._enrich_with_regression(cr_df, ts_all)
        # Ensure numeric presentation: keep 6 decimal places for regression stats
        for col in ('Slope', 'Intercept', 'Residual'):
            if col in cr_df.columns:
                # round safely, preserving NaNs
                cr_df[col] = cr_df[col].astype(float).round(6)

        self.cr_df = cr_df
        return cr_df


def main(min_cr: float = 30.0, lookback_days: int = 60, write_to_excel: bool = True) -> pd.DataFrame:
    """Main entry point for generating carry-roll pairs with regression stats.

    Parameters
    ----------
    min_cr : float
        Minimum CR threshold for filtering pairs.
    lookback_days : int
        Number of days of historical data to use for regression.
    write_to_excel : bool
        If True, write output to Dashboard.xlsm.

    Returns
    -------
    pd.DataFrame
        Enriched pairs DataFrame.
    """
    generator = PairsGenerator(min_cr=min_cr, lookback_days=lookback_days)
    cr_df = generator.generate()

    if write_to_excel and not cr_df.empty:
        try:
            import pathlib
            import xlwings as xw
            PATH = pathlib.Path(__file__).parent.parent.parent
            dashboard_path = PATH.parent.joinpath('Dashboard.xlsm').resolve()
            wb = xw.Book(str(dashboard_path))
            wb.sheets['Test'].range('A2').options(index=False, header=True).value = cr_df
        except Exception as e:
            print(f"Warning: Could not write to Excel: {e}")

# Preserve backward compatibility: build cr_df at module level if imported
if __name__ != '__main__':
    main(write_to_excel=False)
else:
    # When run as script, generate and write to Excel
    main(write_to_excel=True)
    