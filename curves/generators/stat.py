import os
import re
import sys
import datetime
import pathlib
from datetime import timedelta
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from dateutil.relativedelta import relativedelta
from typing import Optional, Dict, Tuple

# local libraries
PATH = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(PATH))

from curves.utils.loader import loadInstrumentDefinition, loadCNBDTS, loadRefData
import curves.calibration.stat as st
from curves.calibration import irscurves as irs
from curves.utils.file import updatePKL
from settings.paths import DIR_INPUT, DIR_OUTPUT 
from settings.fixed_income import BondConfig, IRSConfig
from settings.general import GeneralConfig, DateConfig 
from settings.futures import FuturesConfig

def _suppress_model_jumps(
    df_quo: pd.DataFrame,
    df_act: pd.DataFrame,
    jump_threshold: float = 0.03,
    ratio_threshold: float = 5.0,
) -> pd.DataFrame:
    """Suppress affine model calibration artifacts (discontinuous factor shifts) in ytm_quo.

    A calibration jump is flagged when ytm_quo changes by more than `jump_threshold` (in %)
    while ytm_act barely moves (ratio of changes exceeds `ratio_threshold`).
    Flagged entries are replaced with NaN then linearly interpolated.
    Threshold lowered from 0.08 to 0.03 to catch 3-6bp coupon-date factor recalibration artifacts.
    """
    df_quo_diff = df_quo.diff().abs()
    act_aligned = df_act.reindex(index=df_quo.index, columns=df_quo.columns)
    df_act_diff = act_aligned.diff().abs()
    very_small_act = df_act_diff.fillna(0) < 1e-6
    ratio_exceeded = (df_act_diff > 0) & (df_quo_diff > ratio_threshold * df_act_diff)
    outlier = (df_quo_diff > jump_threshold) & (very_small_act | ratio_exceeded)
    if not outlier.any().any():
        return df_quo
    # Use .where() to avoid index/column misalignment issues on boolean-mask assignment
    df_clean = df_quo.where(~outlier.reindex_like(df_quo).fillna(False))
    # Cast to float64 before interpolating. The row index here is an Index of
    # python date objects, so interpolate(method='index') fails on pandas 3.13+.
    # Interpolate on a temporary DatetimeIndex instead, then restore the index.
    df_clean = df_clean.astype(float)
    original_index = df_clean.index
    df_clean.index = pd.to_datetime(df_clean.index)
    df_clean = df_clean.interpolate(method='time', axis=0, limit_area='inside')
    df_clean.index = original_index
    return df_clean


class StatGenerator:

    """Generate daily statistics with OOP structure and performance improvements."""

    def __init__(self, asof: Optional[datetime.date] = None) -> None:
        # Dates and windows — anchored to asof to prevent lookahead bias
        dates = DateConfig.get_date_mappings(asof=asof)
        self.d: datetime.date = dates['d'].date()
        self.dp: datetime.date = dates['dp'].date()
        self.start: datetime.date = (self.d - relativedelta(months=GeneralConfig.STAT_WINDOW))
        self.start1y: datetime.date = (self.d - relativedelta(years=1))
        self.da: datetime.date = self.d  # upper bound for all historical slices

        # Global env time series — re-fetch from Wind if the IRS data is stale.
        # retrieveCNBDTS may have run before Wind published the day-end fixings;
        # all-NaN rows are dropped by updatePKL, leaving database-px.pkl stale.
        self.env_ts: dict = loadCNBDTS()
        if asof is None:
            swap_ts = self.env_ts.get('SwapTS')
            swap_last = pd.Timestamp(swap_ts.index[-1]).date() if (swap_ts is not None and not swap_ts.empty) else None
            if swap_last is not None and swap_last < self.dp:
                print(f"INFO: database-px.pkl IRS data ends {swap_last}, expected {self.dp} — re-fetching from Wind...")
                try:
                    from curves.utils.retrieve import retrieveCNBDTS
                    retrieveCNBDTS()
                    self.env_ts = loadCNBDTS()
                    swap_ts2 = self.env_ts.get('SwapTS')
                    new_last = pd.Timestamp(swap_ts2.index[-1]).date() if (swap_ts2 is not None and not swap_ts2.empty) else swap_last
                    print(f"INFO: after re-fetch, IRS data ends {new_last}")
                except Exception as exc:
                    print(f"WARN: Could not re-fetch IRS data from Wind: {exc}")

        # In-memory state
        self.spot_ts: dict = {}
        self.bond_groups: dict = {}
        self.spreads: dict = {}

        # Cache TBond env/series explicitly to avoid implicit variable leakage
        self.env_tbond: Optional[dict] = None
        self.df_act_tbond: Optional[pd.DataFrame] = None

    @staticmethod
    def _resolve_curve_column_map(curve_df: pd.DataFrame, tenors: list[int]) -> dict[int, str]:
        """Map tenor years to actual column names present in a CNBD curve frame.

        Supports either 国债 / 国开债 prefixes by detecting whichever set exists
        in the provided DataFrame.
        """
        if not isinstance(curve_df, pd.DataFrame):
            return {}

        candidates = [
            '中债国债到期收益率:',
            '中债国开债到期收益率:',
            '中国:地方政府债到期收益率(AAA):',
            '中债中短期票据到期收益率(AAA):',
        ]

        column_map: dict[int, str] = {}
        for tenor in tenors:
            for prefix in candidates:
                col = f'{prefix}{tenor}年'
                if col in curve_df.columns:
                    column_map[tenor] = col
                    break
        return column_map

    def _ensure_cgb_cdb_timeseries(self) -> dict:
        """Ensure CGB/CDB/ICP key-rate time series are available for spread generation."""
        env_ts = self.env_ts if isinstance(self.env_ts, dict) else {}
        if 'CGB' in env_ts and 'CDB' in env_ts and 'ICP' in env_ts:
            return env_ts

        try:
            db = pd.read_pickle(os.path.join(DIR_INPUT, 'database-px.pkl'))
            if isinstance(db, dict):
                if 'CGB' in db and 'CGB' not in env_ts:
                    env_ts['CGB'] = db['CGB']
                if 'CDB' in db and 'CDB' not in env_ts:
                    env_ts['CDB'] = db['CDB']
                if 'ICP' in db and 'ICP' not in env_ts:
                    env_ts['ICP'] = db['ICP']
                if 'LGB' in db and 'LGB' not in env_ts:
                    env_ts['LGB'] = db['LGB']
                if 'MTN' in db and 'MTN' not in env_ts:
                    env_ts['MTN'] = db['MTN']
                if 'IRS' in db and 'SwapTS' not in env_ts:
                    env_ts['SwapTS'] = db['IRS']
                self.env_ts = env_ts
        except Exception:
            pass
        return env_ts

    # ---------------------- Bonds (TBond/CBond) ----------------------
    def compute_bond_and_swap_spreads(self) -> None:
        for btype in ['TBond', 'CBond']:
            env = loadInstrumentDefinition(btype)

            curve_objs = updatePKL({}, os.path.join(DIR_INPUT, f'{btype}-cvobj.pkl'))
            bond_px = updatePKL({}, os.path.join(DIR_INPUT, f'{btype}-cvpx.pkl'))
            ref = loadRefData(btype)
            curve = curve_objs[self.dp]
            # Use full history (not self.start:self.da) so Spread/BondCarry retain
            # all available history for seasonal charting; statAnalysis_BC/_BS
            # internally restrict OU/z-score calibration to a rolling window.
            bonds = bond_px['ytm_quo'].columns.intersection(env['Def'].index)
            df_act = bond_px['ytm_act'].loc[:self.da, bonds].drop_duplicates()
            df_quo = bond_px['ytm_quo'].loc[:self.da, bonds].drop_duplicates()
            
            # Clean data to handle byte strings and invalid values before statistical analysis
            df_act = df_act.apply(pd.to_numeric, errors='coerce')
            df_quo = df_quo.apply(pd.to_numeric, errors='coerce')

            # Remove affine model calibration jumps caused by reference bond rollovers
            df_quo = _suppress_model_jumps(df_quo, df_act)

            irs_key_ts = self.env_ts['SwapTS'].loc[df_act.index[0]:df_act.index[-1]]

            # Build bond par-yield key-rate DataFrame for roll computation.
            # Columns = tenor in years (float); values = par yield in % at that tenor.
            # TBond uses CGB key rates; CBond uses CDB key rates.
            _cnbd_bond_ts = self.env_ts.get('CGB' if btype == 'TBond' else 'CDB')
            _tenor_years = [1, 2, 3, 4, 5, 7, 10, 20, 30]
            bond_key_ts_df = None
            if isinstance(_cnbd_bond_ts, pd.DataFrame):
                _curve_cols = self._resolve_curve_column_map(_cnbd_bond_ts, _tenor_years)
                _avail = {t: _cnbd_bond_ts[col] for t, col in _curve_cols.items()}
                if _avail:
                    bond_key_ts_df = pd.DataFrame(_avail).loc[df_act.index[0]:df_act.index[-1]]

            # Compute and persist spread stats
            stat_bc = st.statAnalysis_BC(env, df_act, df_quo)
            stat_bs = st.statAnalysis_BS(env, df_act, irs_key_ts, bond_key_ts=bond_key_ts_df)
            bond_spd = {'BondCurve': stat_bc, 'BondSwap': stat_bs}
            
            updatePKL(bond_spd, os.path.join(DIR_INPUT, f'{btype}-spds.pkl'))
            # import pdb; pdb.set_trace()
            # Build spot TS
            self.spot_ts[btype] = ref['Spot']
            spot_dp = curve.fitting()['SpotRate']
            spot_dp.index = [f"{btype}-{t}Y" for t in spot_dp.index]
            clist_ = list(self.spot_ts[btype].columns)
            self.spot_ts[btype].loc[self.dp, clist_] = spot_dp.loc[clist_]
            self.spot_ts[btype] = self.spot_ts[btype].astype(float)

            curve_data_path = os.path.join(DIR_INPUT, f'{btype}-cvdata.pkl')
            curve_data = updatePKL({}, curve_data_path)
            if not isinstance(curve_data, dict):
                curve_data = {}
            fitted = curve.fitting()
            if 'spot' not in curve_data or not isinstance(curve_data.get('spot'), pd.DataFrame):
                curve_data['spot'] = pd.DataFrame()
            if 'forward' not in curve_data or not isinstance(curve_data.get('forward'), pd.DataFrame):
                curve_data['forward'] = pd.DataFrame()
            curve_data['spot'].loc[self.dp, fitted['SpotRate'].index] = fitted['SpotRate'].values
            curve_data['forward'].loc[self.dp, fitted['ForwardRate'].index] = fitted['ForwardRate'].values
            updatePKL(curve_data, curve_data_path)

            # Bond groups by tenor buckets
            bond_common = df_act.columns.intersection(env['Def'].index)
            env['Def'] = env['Def'].loc[bond_common]
            self.bond_groups[btype + '5Y'] = df_act[env['Def'][(env['Def']['剩余期限'] >= 4.0)
                                                              & (env['Def']['剩余期限'] <= 5.5)].index]
            self.bond_groups[btype + '10Y'] = df_act[env['Def'][(env['Def']['剩余期限'] >= 9.0)
                                                               & (env['Def']['剩余期限'] <= 10.0)].index]
            self.bond_groups[btype + '30Y'] = df_act[env['Def'][(env['Def']['剩余期限'] >= 27.0)
                                                               & (env['Def']['剩余期限'] <= 30.0)].index]

            # Cache TBond env and df_act for later regression stage
            if btype == 'TBond':
                self.env_tbond = env
                self.df_act_tbond = df_act

        # Add 20Y/30Y to TBond spot from CGB
        date_common = self.spot_ts['TBond'].index.intersection(
            self.env_ts['CGB']['中债国债到期收益率:30年'].index
        )
        self.spot_ts['TBond']['TBond-20.0Y'] = self.env_ts['CGB']['中债国债到期收益率:20年'].loc[date_common]
        self.spot_ts['TBond']['TBond-30.0Y'] = self.env_ts['CGB']['中债国债到期收益率:30年'].loc[date_common]

    # ---------------------- IRS ----------------------
    def compute_irs_spreads(self, full_history: bool = False) -> None:
        btype = 'IRS'
        irs_px = updatePKL({}, os.path.join(DIR_INPUT, f'{btype}-cvpx.pkl'))
        if full_history:
            df_act_irs = irs_px['ytm_act'].reindex(columns=IRSConfig.IRS_LIST).drop_duplicates()
            df_quo_irs = irs_px['ytm_quo'].reindex(columns=IRSConfig.IRS_LIST).drop_duplicates()
        else:
            df_act_irs = irs_px['ytm_act'].loc[self.start:self.da, IRSConfig.IRS_LIST].drop_duplicates()
            df_quo_irs = irs_px['ytm_quo'].loc[self.start:self.da, IRSConfig.IRS_LIST].drop_duplicates()

        # Clean data to handle byte strings and invalid values
        df_act_irs = df_act_irs.apply(pd.to_numeric, errors='coerce')
        df_quo_irs = df_quo_irs.apply(pd.to_numeric, errors='coerce')

        # When processing full history, filter out columns with insufficient coverage
        # (< 30% non-NaN values) to avoid generating meaningless spreads from sparse data.
        # This allows spreads to be generated from the earliest common date across
        # all available instruments.
        if full_history and len(df_act_irs) > 0:
            coverage = df_act_irs.notna().sum() / len(df_act_irs)
            available_cols = coverage[coverage >= 0.3].index.tolist()
            if available_cols:
                df_act_irs = df_act_irs[available_cols]
                df_quo_irs = df_quo_irs[available_cols]
                first_valid_idx = max(df_act_irs[col].first_valid_index() for col in available_cols if df_act_irs[col].notna().any())
                df_act_irs = df_act_irs.loc[first_valid_idx:]
                df_quo_irs = df_quo_irs.loc[first_valid_idx:]

        cvpx_stat = st.statAnalysis_IRS(df_act_irs, df_quo_irs)

        cpr = irs_px.get('carry3m', pd.DataFrame()) + irs_px.get('roll3m', pd.DataFrame())
        from curves.calibration.irscurves import irsSpreads
        spds_cpr = irsSpreads(cpr)

        cvpx_stat['CarryRoll3m'] = spds_cpr
        updatePKL(cvpx_stat, os.path.join(DIR_INPUT, f'{btype}-pxspds.pkl'), rewrite=full_history)

        # Keep the shared IRS curve-data cache in sync with the daily generator path.
        # This persists IRS-cvdata.pkl for the previous business day used by curve pricing.
        try:
            irs_ref = {
                'r7d': list(IRSConfig.R7D_LIST.keys()),
                's3m': list(IRSConfig.S3M_LIST.keys()),
            }
            irs.genIRSCurves(self.env_ts['SwapTS'], irs_ref, self.d)
        except Exception as exc:
            print(f'WARN: Could not refresh IRS-cvdata.pkl from daily generator: {exc}')

        # Use a filtered copy instead of mutating config.irs_terms
        excluded = {'SHIBOR3M.IR', 'SHI3MS7Y.IR', 'SHI3MS10Y.IR', 'FR007S7Y.IR', 'FR007S10Y.IR'}
        _irs_terms = IRSConfig.get_irs_terms()
        filtered_terms = [k for k in _irs_terms.keys() if k not in excluded]
        self.spot_ts[btype] = self.env_ts['SwapTS'][filtered_terms]

    def compute_irs_spreads_from_raw(self) -> None:
        """Compute IRS spreads directly from raw quotes in database-px.pkl.

        This skips curve calibration and creates spreads from close quotes directly.
        Useful for building historical time series when curve-calibrated data is unavailable.
        """
        from curves.calibration.irscurves import irsSpreads

        db_path = os.path.join(DIR_INPUT, 'database-px.pkl')
        try:
            db = pd.read_pickle(db_path)
            if not isinstance(db, dict) or 'IRS' not in db:
                print("ERROR: No IRS data in database-px.pkl")
                return

            irs_db = db['IRS']
            if not isinstance(irs_db, pd.DataFrame) or irs_db.empty:
                print("ERROR: IRS data is empty")
                return

            # Filter to columns that are in IRSConfig.IRS_LIST
            available_cols = [c for c in IRSConfig.IRS_LIST if c in irs_db.columns]
            if not available_cols:
                print("ERROR: No matching IRS columns found")
                return

            df_irs = irs_db[available_cols].copy()
            df_irs = df_irs.apply(pd.to_numeric, errors='coerce')

            # Build spreads output directly without needing statAnalysis_IRS
            # (which requires two different time series for bid/ask or similar)
            spds = irsSpreads(df_irs)

            # Build StatInfo for the spreads using OU calibration
            stat_info_spds = st.OU_calibrate(spds)
            for b in stat_info_spds.index:
                stat_info_spds.loc[b, 'max'] = stat_info_spds.loc[b, 'max'] - stat_info_spds.loc[b, 'mean']
                stat_info_spds.loc[b, 'min'] = stat_info_spds.loc[b, 'min'] - stat_info_spds.loc[b, 'mean']

            # Structure matches IRS-pxspds.pkl format
            cvpx_stat = {
                'StatInfo': stat_info_spds,
                'Spread': pd.concat([df_irs, spds], axis=1),
                'CloseYield': df_irs,
                'CurveYield': df_irs,
                'CarryRoll3m': pd.DataFrame(),
            }

            updatePKL(cvpx_stat, os.path.join(DIR_INPUT, f'IRS-pxspds.pkl'), rewrite=True)
            print(f"✓ IRS spreads computed from raw data: {df_irs.shape[0]} days, {len(available_cols)} instruments")
            print(f"  Date range: {df_irs.index[0]} to {df_irs.index[-1]}")

        except Exception as exc:
            print(f"ERROR in compute_irs_spreads_from_raw: {exc}")
            raise

    def rebuild_irs_spreads_history(self) -> None:
        """Recompute IRS-pxspds.pkl from raw close quotes in database-px.pkl.

        Computes spreads directly from raw IRS closing quotes without requiring
        curve calibration. This creates a clean historical time series from available data.
        """
        print("─" * 80)
        print("Rebuilding IRS-pxspds.pkl from raw data")
        print("─" * 80)
        self.compute_irs_spreads_from_raw()

    # ---------------------- Other sectors ----------------------
    def compute_other_bond_spreads(self) -> None:
        for obtype in BondConfig.INCLUDE_FILTERS.keys():
            env_obond = loadInstrumentDefinition(obtype)
            obond_px = updatePKL({}, os.path.join(DIR_INPUT, f'{obtype}-cvpx.pkl'))

            # Use full history (not self.start:self.da) so Spread retains all
            # available history for seasonal charting; statAnalysis_BC internally
            # restricts OU/z-score calibration to a rolling window.
            bonds_obond = obond_px['ytm_quo'].columns.intersection(env_obond['Def'].index)
            df_act_obond = obond_px['ytm_act'].loc[:self.da, bonds_obond].drop_duplicates()
            df_quo_obond = obond_px['ytm_quo'].loc[:self.da, bonds_obond].drop_duplicates()
            
            # Clean data to handle byte strings and invalid values
            df_act_obond = df_act_obond.apply(pd.to_numeric, errors='coerce')
            df_quo_obond = df_quo_obond.apply(pd.to_numeric, errors='coerce')

            # Remove affine model calibration jumps caused by reference bond rollovers
            df_quo_obond = _suppress_model_jumps(df_quo_obond, df_act_obond)

            ob_spread = {obtype + 'Spread': st.statAnalysis_BC(env_obond, df_act_obond, df_quo_obond)}
            updatePKL(ob_spread, os.path.join(DIR_INPUT, f'{obtype}-spds.pkl'))

            # tenor groups
            self.bond_groups[obtype + '10Y'] = obond_px['ytm_act'][env_obond['Def'][(env_obond['Def']['剩余期限'] >= 9.0)
                                                                                   & (env_obond['Def']['剩余期限'] <= 10.0)].index]
            self.bond_groups[obtype + '30Y'] = obond_px['ytm_act'][env_obond['Def'][(env_obond['Def']['剩余期限'] >= 27.0)
                                                                                   & (env_obond['Def']['剩余期限'] <= 30.0)].index]

    # ---------------------- Spread regression ----------------------
    @staticmethod
    def _fast_linear_fit(y: pd.Series) -> Tuple[float, float, float, np.ndarray]:
        """Fast OLS for y ~ a + b x using NumPy; return (level_pred, slope, intercept, residuals)."""
        yv = y.dropna().to_numpy()
        if yv.size < 4:
            return np.nan, np.nan, np.nan, np.array([])
        x = np.arange(yv.size, dtype=float)
        X = np.vstack([np.ones_like(x), x]).T
        beta, _, _, _ = np.linalg.lstsq(X, yv, rcond=None)
        intercept, slope = beta[0], beta[1]
        y_hat = X @ beta
        res = yv - y_hat
        level_pred = intercept + slope * (x[-1] + 1)
        return float(level_pred), float(slope), float(intercept), res

    def compute_spread_regression(self) -> None:
        assert self.env_tbond is not None and self.df_act_tbond is not None

        # Choose anchors from TBond universe
        bonds_tor = self.env_tbond['Def'][self.env_tbond['Def']['证券全称'].str.contains('国债')].copy()
        bonds_tor['换手率'] = bonds_tor['成交量'] / bonds_tor['债券余额:亿'] / 1e8
        ymap = {'5Y': (4.0, 5.0), '10Y': (9.0, 10.0), '30Y': (25.0, 30.0)}
        anchor: Dict[str, str] = {}
        for k, (lo, hi) in ymap.items():
            df_ = bonds_tor[(bonds_tor['剩余期限'] > lo) & (bonds_tor['剩余期限'] < hi)]
            df_ = df_.sort_values(by='换手率', ascending=False)
            if df_.shape[0] > 0:
                anchor[k] = df_.index[0]

        # Use full history (not self.start:) so Spread retains all available
        # history for seasonal charting; the linear-fit/OU calibration below is
        # restricted to the rolling self.start:self.da window for freshness.
        bond_ts = self.df_act_tbond.apply(pd.to_numeric, errors='coerce')
        spreads_bi: dict[str, pd.DataFrame] = {}
        # Term spreads (10Y-5Y, 30Y-10Y)
        term_cols = list(anchor.values())
        spreads_bi['Term'] = bond_ts[term_cols].diff(axis=1).dropna(how='all', axis=1)
        spreads_bi['Term'].columns = [f"{anchor['10Y']}-{anchor['5Y']}", f"{anchor['30Y']}-{anchor['10Y']}"]

        # Bucketed spreads vs anchor
        for k in self.bond_groups.keys():
            t = k[-2:] if '5' in k else k[-3:]
            group_df = self.bond_groups[k].apply(pd.to_numeric, errors='coerce')
            spreads_bi[k] = group_df.sub(bond_ts[anchor[t]], axis=0)

        spreads_b_full = pd.concat(spreads_bi, axis=1).droplevel(0, axis=1).sort_index()
        spreads_b_full.drop(columns=list(anchor.values()), inplace=True, errors='ignore')
        spreads_b_stats = spreads_b_full.loc[self.start:self.da]  # rolling window for calibration

        # Fast linear fit per series (calibrated on rolling window only)
        stat0 = pd.DataFrame(index=spreads_b_stats.columns)
        resi_cols = {}
        for k in self.bond_groups.keys():
            for c in self.bond_groups[k].columns:
                if c not in anchor.values():
                    stat0.loc[c, 'label'] = k
        for col in spreads_b_stats.columns:
            series = spreads_b_stats[col].dropna().reset_index(drop=True)
            level_pred, slope, intercept, res = self._fast_linear_fit(series)
            if not np.isnan(level_pred):
                stat0.loc[col, 'level'] = level_pred
                stat0.loc[col, 'slope'] = slope
                stat0.loc[col, 'intercept'] = intercept
                # R2 using residuals
                if res.size:
                    ss_res = float(np.sum(res ** 2))
                    ss_tot = float(np.sum((series - series.mean()) ** 2))
                    stat0.loc[col, 'R2'] = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
                    resi_cols[col] = pd.Series(res, index=range(res.size))

        resi = pd.DataFrame(resi_cols)
        stat1 = st.OU_calibrate(resi)
        stat_ = pd.concat([stat0, stat1], axis=1)
        # Use raw historical spread mean and std for Z-score (not linear trend extrapolation).
        # This keeps Z-scores stable regardless of when the generator was last run.
        # Calibrated on the rolling window, matching stat0/stat1 above.
        raw_mean = spreads_b_stats.mean()
        raw_std  = spreads_b_stats.std()
        stat_['mean'] = raw_mean.reindex(stat_.index)
        stat_['vol']  = raw_std.reindex(stat_.index)
        stat_.drop('level', axis=1, inplace=True)

        # Save to Excel
        # with pd.ExcelWriter(os.path.join(DIR_OUTPUT, 'PairSpreads.xlsx')) as writer:
        #     stat_.to_excel(writer)

        # Persist in spreads dict for downstream use. Spread keeps full history
        # for the seasonal chart; StatInfo reflects only the rolling-window calibration.
        self.spreads['BinarySpread'] = {
            'StatInfo': stat_,
            'Spread': spreads_b_full,
            'Anchor': anchor,
        }

    # ---------------------- PCA spreads ----------------------
    def compute_pca_spreads(self) -> None:
        spot_ts_all = pd.concat(self.spot_ts, axis=1).droplevel(level=0, axis=1).sort_index()
        spot_ts_all = spot_ts_all.loc[self.start1y:self.da].dropna()
        
        # Clean data to handle byte strings and invalid values before PCA
        spot_ts_all = spot_ts_all.apply(pd.to_numeric, errors='coerce').dropna()
        
        # Z-score standardization
        mu = spot_ts_all.mean()
        sigma = spot_ts_all.std().replace(0, np.nan)
        spot_standardized = (spot_ts_all - mu) / sigma
        pca = PCA(n_components=2)
        pcs = pca.fit_transform(spot_standardized)
        recon = pca.inverse_transform(pcs)
        resid = spot_standardized - recon

        pca_spd = {
            'Spot': spot_ts_all,
            'Spread': pd.DataFrame(resid, index=spot_standardized.index, columns=spot_standardized.columns),
            'StatInfo': st.OU_calibrate(pd.DataFrame(resid, index=spot_standardized.index, columns=spot_standardized.columns)),
        }
        self.spreads['PCASpread'] = pca_spd
        updatePKL(self.spreads, os.path.join(DIR_INPUT, 'Misc-spds.pkl'))

    # ── helpers for futures analytics ─────────────────────────────────────────

    # Match each futures contract type to the same-tenor FR007-based IRS leg.
    # FR007 IRS is quoted out to 10Y, so TL (30Y) uses the longest available 10Y
    # anchor as the closest matched-tenor proxy.
    _CTYPE_IRS = {
        'TS': 'FR007S2Y.IR',
        'TF': 'FR007S5Y.IR',
        'T':  'FR007S10Y.IR',
        'TL': 'FR007S10Y.IR',
    }

    # ── main futures stats method ──────────────────────────────────────────────
    def compute_futures_stats(self) -> None:
        """Compute Bond-Futures, Term Basis, Futures-Swap and persist to futures-spds.pkl.

        Sources Wind bond-futures analytics directly from ``futures-analytics.pkl``
        (built by FuturesAnalyticsGenerator), per ctype ('T','TF','TS','TL'):

          * Bond-Futures (key ``NetBasis``): IRR − repo, where repo = FR007 +
            FUNDING_BASIS_BP.  In bp.
          * Term Basis (key ``TermBasis``): front − next-season close
            (``futures_close − next_close``).  In price points (yuan/100 face).
          * Futures-Swap (key ``FuturesSwap``): FYTM − matched-tenor FR007 IRS.
            In bp.
        """
        from curves.utils.file import loadPKL as _loadPKL
        btype = 'futures'

        analytics = _loadPKL(os.path.join(DIR_INPUT, 'futures-analytics.pkl'))
        if not analytics:
            # Leave any existing futures-spds.pkl untouched rather than wiping
            # accumulated history with an empty placeholder.
            print('compute_futures_stats: futures-analytics.pkl missing/empty — skipping.')
            return

        swap_ts = self.env_ts.get('SwapTS')
        fr007_ts: Optional[pd.Series] = None
        if isinstance(swap_ts, pd.DataFrame) and 'FR007.IR' in swap_ts.columns:
            fr007_ts = pd.to_numeric(swap_ts['FR007.IR'], errors='coerce')
            fr007_ts.index = pd.DatetimeIndex(fr007_ts.index)

        funding_pct = FuturesConfig.FUNDING_BASIS_BP / 100.0  # bp → percent

        spreads: dict = {'NetBasis': {}, 'NetIRR': {}, 'TermBasis': {}, 'FuturesSwap': {}}
        nb_cols: dict[str, pd.Series] = {}   # for the flat NetIRR mirror
        tb_cols: dict[str, pd.Series] = {}

        start_ts = pd.Timestamp(self.start)
        da_ts    = pd.Timestamp(self.da)

        for ctype in FuturesConfig.CONTRACT_TYPES:
            df_full = analytics.get(ctype)
            if not isinstance(df_full, pd.DataFrame) or df_full.empty:
                continue
            df_full = df_full.copy()
            df_full.index = pd.DatetimeIndex(df_full.index)

            # For StatInfo (OU calibration, z-scores): use rolling window for freshness
            df_stats = df_full.loc[start_ts:da_ts]
            if df_stats.empty:
                continue

            # For Spread timeseries: use full history for seasonal chart
            tenor = FuturesConfig.CONTRACT_TENOR.get(ctype, 5.0)
            irr_full   = pd.to_numeric(df_full['irr'],  errors='coerce')
            fytm_full  = pd.to_numeric(df_full['fytm'], errors='coerce')
            irr_stats  = pd.to_numeric(df_stats['irr'],  errors='coerce')
            fytm_stats = pd.to_numeric(df_stats['fytm'], errors='coerce')

            # Null out bad-CTD artifact days: deeply negative IRR (< -0.5 %) is
            # a clear data error for CNY treasury futures (genuine negative carry is
            # at most a few bp).  Also null fytm on those same days since it
            # reflects the same bad CTD pricing.
            _irr_bad_full   = irr_full < -0.5
            _irr_bad_stats  = irr_stats < -0.5
            irr_full   = irr_full.where(~_irr_bad_full)
            fytm_full  = fytm_full.where(~_irr_bad_full)
            irr_stats  = irr_stats.where(~_irr_bad_stats)
            fytm_stats = fytm_stats.where(~_irr_bad_stats)

            # ── Term Basis: front − next-season close (price points) ──────────
            # Use full history for Spread, rolling window for stats
            _fc_full = pd.to_numeric(df_full['futures_close'], errors='coerce')
            _nc_full = pd.to_numeric(df_full['next_close'],   errors='coerce')
            _fc_stats = pd.to_numeric(df_stats['futures_close'], errors='coerce')
            _nc_stats = pd.to_numeric(df_stats['next_close'],   errors='coerce')
            # Null out rows where either price is frozen for >= 3 consecutive days
            # (stale close artifact after contract roll).
            _STALE_W = 3
            _fc_stale_full = _fc_full.rolling(_STALE_W).apply(
                lambda x: (x.max() - x.min()) < 1e-8, raw=True
            ).fillna(0).astype(bool)
            _nc_stale_full = _nc_full.rolling(_STALE_W).apply(
                lambda x: (x.max() - x.min()) < 1e-8, raw=True
            ).fillna(0).astype(bool)
            term_full = (_fc_full - _nc_full).where(~(_fc_stale_full | _nc_stale_full))

            _fc_stale_stats = _fc_stats.rolling(_STALE_W).apply(
                lambda x: (x.max() - x.min()) < 1e-8, raw=True
            ).fillna(0).astype(bool)
            _nc_stale_stats = _nc_stats.rolling(_STALE_W).apply(
                lambda x: (x.max() - x.min()) < 1e-8, raw=True
            ).fillna(0).astype(bool)
            term_stats = (_fc_stats - _nc_stats).where(~(_fc_stale_stats | _nc_stale_stats))

            if term_full.notna().sum() > 20:
                tb_cols[ctype] = term_full

            # ── Bond-Futures: IRR − repo (FR007 + funding), in bp ─────────────
            if fr007_ts is not None:
                repo_full = fr007_ts.reindex(df_full.index).ffill() + funding_pct  # %
                bf_spread_full = ((irr_full - repo_full) * 100).dropna()            # bp (full history)

                repo_stats = fr007_ts.reindex(df_stats.index).ffill() + funding_pct  # %
                bf_spread_stats = ((irr_stats - repo_stats) * 100).dropna()          # bp (rolling window)

                if bf_spread_full.notna().sum() >= 30:
                    nb_cols[ctype] = bf_spread_full
                    si = st.OU_calibrate(bf_spread_stats.to_frame(ctype))  # calibrate on rolling window
                    si.loc[ctype, 'tenor']       = tenor
                    si.loc[ctype, 'ttm']         = tenor
                    # 3m cash-and-carry pickup from the annual IRR−repo spread (use latest value).
                    si.loc[ctype, 'carry_3m_bp'] = float(bf_spread_full.iloc[-1]) * (90.0 / 360.0)
                    last = df_stats.dropna(subset=['ctd_code']).iloc[-1] if df_stats['ctd_code'].notna().any() else None
                    if last is not None:
                        si.loc[ctype, 'ctd_code'] = last['ctd_code']
                        si.loc[ctype, 'futures']  = last.get('contract_code', ctype)
                    spreads['NetBasis'][ctype] = {
                        'StatInfo': si,
                        'Spread'  : bf_spread_full.to_frame(ctype),  # full history for seasonal chart
                    }

            # ── Futures-Swap: FYTM − matched-tenor FR007 IRS, in bp ───────────
            irs_ticker = self._CTYPE_IRS.get(ctype)
            if isinstance(swap_ts, pd.DataFrame) and irs_ticker in (swap_ts.columns if swap_ts is not None else []):
                irs_s_full = pd.to_numeric(swap_ts[irs_ticker], errors='coerce')
                irs_s_full.index = pd.DatetimeIndex(irs_s_full.index)
                irs_s_full = irs_s_full.reindex(df_full.index).ffill()
                fs_spread_full = ((fytm_full - irs_s_full) * 100).dropna()  # bp (full history)

                irs_s_stats = pd.to_numeric(swap_ts[irs_ticker], errors='coerce')
                irs_s_stats.index = pd.DatetimeIndex(irs_s_stats.index)
                irs_s_stats = irs_s_stats.reindex(df_stats.index).ffill()
                fs_spread_stats = ((fytm_stats - irs_s_stats) * 100).dropna()  # bp (rolling window)

                if fs_spread_full.notna().sum() >= 30:
                    si = st.OU_calibrate(fs_spread_stats.to_frame(ctype))  # calibrate on rolling window
                    si.loc[ctype, 'tenor'] = tenor
                    # 3m carry of pay-fixed-IRS / long-futures: FYTM − IRS pickup (use latest).
                    carry_ts = ((fytm_full - irs_s_full).dropna() * (90.0 / 360.0) * 100)
                    si.loc[ctype, 'carry_3m_bp'] = float(carry_ts.iloc[-1]) if len(carry_ts) else np.nan
                    spreads['FuturesSwap'][ctype] = {
                        'StatInfo'   : si,
                        'Spread'     : fs_spread_full.to_frame(ctype),  # full history for seasonal chart
                        'CarryRoll3m': carry_ts,
                    }

        # Term Basis: flat StatInfo across ctypes (calibrated on rolling window, Spread from full history)
        if tb_cols:
            tb_df_full = pd.DataFrame(tb_cols).apply(pd.to_numeric, errors='coerce')  # full history
            tb_df_stats = tb_df_full.loc[start_ts:da_ts]  # rolling window for calibration
            stat_result = st.statAnalysis(tb_df_stats.dropna(how='all'))  # calibrate on rolling window
            spreads['TermBasis'] = {
                'Spread': tb_df_full.dropna(how='all'),      # full history for seasonal chart
                'StatInfo': stat_result['StatInfo'],          # calibrated on rolling window
            }

        # NetIRR: flat DataFrame mirror of the Bond-Futures (IRR−repo) spread,
        # kept for legacy web/core consumers that read futures-spds['NetIRR'].
        if nb_cols:
            spreads['NetIRR'] = pd.DataFrame(nb_cols).apply(pd.to_numeric, errors='coerce')
        else:
            spreads['NetIRR'] = pd.DataFrame()

        # Merge (not overwrite): StatInfo/Spread are computed on a rolling
        # self.start:self.da window for calibration freshness, but persisting
        # with rewrite=True would discard everything older than that window on
        # every run. updatePKL's default merge keeps history (by date index)
        # while StatInfo rows still refresh to the latest calibration.
        updatePKL(spreads, os.path.join(DIR_INPUT, f'{btype}-spds.pkl'))
        print(f'compute_futures_stats: BondFutures={list(spreads["NetBasis"].keys())}, '
              f'TermBasis={list(spreads.get("TermBasis", {}).get("StatInfo", pd.DataFrame()).index)}, '
              f'FuturesSwap={list(spreads["FuturesSwap"].keys())}')

    # ---------------------- Tenor spreads ----------------------
    def compute_tenor_spreads(self) -> None:
        """Build tenor-spread (CGB/CDB slope, CDBCGB cross-sector, bond-vs-repo
        and CD-vs-repo cross-curve) time series, compute carry+roll (3m, %) for
        each instrument, run OU statistics, and persist to ``Tenor-spds.pkl``.

        File structure::

            Tenor-spds.pkl  →  dict
              'TenorSpread'
                'Spread'       : pd.DataFrame  — annual yield diff in %  (index=date, cols=instruments)
                'CarryRoll3m'  : pd.DataFrame  — 3m carry in % for a BUY trade
                                               (XsYs: negated; cross-curve: positive)
                'StatInfo'     : pd.DataFrame  — OU statistics per instrument
        """
        env_ts = self._ensure_cgb_cdb_timeseries()
        if not isinstance(env_ts, dict) or 'CGB' not in env_ts or 'CDB' not in env_ts:
            print('Warning: CGB/CDB key-rate data not available — skipping tenor spreads.')
            return

        cgb = env_ts['CGB']
        cdb = env_ts['CDB']
        icp = env_ts.get('ICP')
        swap_ts = env_ts.get('SwapTS')
        lgb = env_ts.get('LGB')  # local government bonds
        mtn = env_ts.get('MTN')  # medium-term notes

        # Column name helpers — allow the function to work even if a key is missing.
        def _series(src: dict, key: Optional[str]):
            """Return src[key] as a float Series, or None if missing."""
            v = src.get(key)
            if v is None:
                return None
            return pd.to_numeric(v, errors='coerce')

        def _icp_col(months: int) -> Optional[str]:
            if not isinstance(icp, pd.DataFrame):
                return None
            if months % 12 == 0:
                col = f'中债商业银行同业存单到期收益率(AAA):{months // 12}年'
            else:
                col = f'中债商业银行同业存单到期收益率(AAA):{months}个月'
            return col if col in icp.columns else None

        def _swap_col(tag: str) -> Optional[str]:
            if not isinstance(swap_ts, pd.DataFrame):
                return None
            col = f'FR007S{tag}.IR'
            return col if col in swap_ts.columns else None

        cgb_cols = self._resolve_curve_column_map(cgb, [1, 2, 3, 5, 10, 20, 30])
        cdb_cols = self._resolve_curve_column_map(cdb, [5, 10])
        lgb_cols = self._resolve_curve_column_map(lgb, [5, 10, 30]) if lgb is not None else {}
        mtn_cols = self._resolve_curve_column_map(mtn, [1, 3, 5]) if mtn is not None else {}

        cgb1  = _series(cgb, cgb_cols.get(1))
        cgb2  = _series(cgb, cgb_cols.get(2))
        cgb3  = _series(cgb, cgb_cols.get(3))
        cgb5  = _series(cgb, cgb_cols.get(5))
        cgb10 = _series(cgb, cgb_cols.get(10))
        cgb20 = _series(cgb, cgb_cols.get(20))
        cgb30 = _series(cgb, cgb_cols.get(30))
        cdb5  = _series(cdb, cdb_cols.get(5))
        cdb10 = _series(cdb, cdb_cols.get(10))
        lgb5  = _series(lgb, lgb_cols.get(5))  if lgb is not None else None
        lgb10 = _series(lgb, lgb_cols.get(10)) if lgb is not None else None
        lgb30 = _series(lgb, lgb_cols.get(30)) if lgb is not None else None
        mtn1  = _series(mtn, mtn_cols.get(1))  if mtn is not None else None
        mtn3  = _series(mtn, mtn_cols.get(3))  if mtn is not None else None
        mtn5  = _series(mtn, mtn_cols.get(5))  if mtn is not None else None

        icp3m  = _series(icp, _icp_col(3))  if icp is not None else None
        icp6m  = _series(icp, _icp_col(6))  if icp is not None else None
        icp9m  = _series(icp, _icp_col(9))  if icp is not None else None
        icp1y  = _series(icp, _icp_col(12)) if icp is not None else None

        repo1y  = _series(swap_ts, _swap_col('1Y'))  if swap_ts is not None else None
        repo2y  = _series(swap_ts, _swap_col('2Y'))  if swap_ts is not None else None
        repo5y  = _series(swap_ts, _swap_col('5Y'))  if swap_ts is not None else None
        repo10y = _series(swap_ts, _swap_col('10Y')) if swap_ts is not None else None
        repo3m  = _series(swap_ts, _swap_col('3M'))  if swap_ts is not None else None
        repo6m  = _series(swap_ts, _swap_col('6M'))  if swap_ts is not None else None
        repo9m  = _series(swap_ts, _swap_col('9M'))  if swap_ts is not None else None

        instruments = {}
        if cgb5  is not None and cgb10 is not None: instruments['CGB-5s10s']  = cgb10  - cgb5
        if cgb10 is not None and cgb20 is not None: instruments['CGB-10s20s'] = cgb20  - cgb10
        if cgb10 is not None and cgb30 is not None: instruments['CGB-10s30s'] = cgb30  - cgb10
        if cdb5  is not None and cdb10 is not None: instruments['CDB-5s10s']  = cdb10  - cdb5
        if cdb5  is not None and cgb5  is not None: instruments['CDBCGB-5y']  = cdb5   - cgb5
        if cdb10 is not None and cgb10 is not None: instruments['CDBCGB-10y'] = cdb10  - cgb10

        # LGB (local government bond) vs CGB cross-sector spreads.
        if lgb5  is not None and cgb5  is not None: instruments['LGBCGB-5y']  = lgb5   - cgb5
        if lgb10 is not None and cgb10 is not None: instruments['LGBCGB-10y'] = lgb10  - cgb10
        if lgb30 is not None and cgb30 is not None: instruments['LGBCGB-30y'] = lgb30  - cgb30

        # MTN (medium-term note) vs CGB cross-sector spreads.
        if mtn1 is not None and cgb1 is not None: instruments['MTNCGB-1y'] = mtn1 - cgb1
        if mtn3 is not None and cgb3 is not None: instruments['MTNCGB-3y'] = mtn3 - cgb3
        if mtn5 is not None and cgb5 is not None: instruments['MTNCGB-5y'] = mtn5 - cgb5

        # Bond-vs-Repo cross-curve: CGB key-rate yield minus matched-tenor FR007 IRS rate
        if cgb1  is not None and repo1y  is not None: instruments['CGBRepo7d-1y']  = cgb1  - repo1y
        if cgb2  is not None and repo2y  is not None: instruments['CGBRepo7d-2y']  = cgb2  - repo2y
        if cgb5  is not None and repo5y  is not None: instruments['CGBRepo7d-5y']  = cgb5  - repo5y
        if cgb10 is not None and repo10y is not None: instruments['CGBRepo7d-10y'] = cgb10 - repo10y

        # CD-vs-Repo cross-curve: NCD (AAA) yield minus matched-tenor FR007 IRS rate
        if icp3m is not None and repo3m is not None: instruments['ICPRepo7d-3m'] = icp3m - repo3m
        if icp6m is not None and repo6m is not None: instruments['ICPRepo7d-6m'] = icp6m - repo6m
        if icp9m is not None and repo9m is not None: instruments['ICPRepo7d-9m'] = icp9m - repo9m
        if icp1y is not None and repo1y is not None: instruments['ICPRepo7d-1y'] = icp1y - repo1y

        if not instruments:
            print('Warning: Could not build any tenor-spread series.')
            return

        # Spread DataFrame: annual yield diff in % (e.g. 0.30 for 30bp)
        # Keep full history for seasonal chart, use rolling window only for calibration
        df_spread_full = pd.DataFrame(instruments).apply(pd.to_numeric, errors='coerce').sort_index()
        df_spread_stats = df_spread_full.loc[self.start:self.da]  # rolling window for OU calibration

        # Carry+Roll (3m) in %:
        #   XsYs (CGB-10s30s etc.)        BUY = long short-tenor, short long-tenor
        #     → carry = Y_short − Y_long = −spread  → CR3m = −spread × 0.25
        #   Cross-curve (CDBCGB, *Repo7d-*) BUY = long the bond/CD leg, short the swap/CGB leg
        #     → carry = Y_leg1 − Y_leg2 = +spread   → CR3m = +spread × 0.25
        df_cr3m_full = df_spread_full.copy() * (90.0 / 360.0)
        for col in df_cr3m_full.columns:
            if re.search(r'\d+s\d+', col, re.IGNORECASE):
                df_cr3m_full[col] = -df_cr3m_full[col]

        # OU statistics on spread levels (using rolling window only)
        try:
            stat_info = st.OU_calibrate(df_spread_stats.dropna(how='all'))
        except Exception as exc:
            print(f'Warning: OU calibration for tenor spreads failed: {exc}')
            stat_info = pd.DataFrame(index=df_spread_full.columns)

        tenor_spds = {
            'TenorSpread': {
                'Spread':      df_spread_full,     # full history for seasonal chart
                'CarryRoll3m': df_cr3m_full,
                'StatInfo':    stat_info,          # calibrated on rolling window
            }
        }
        # Merge (not overwrite): Spread/StatInfo are computed on a rolling
        # self.start:self.da window for calibration freshness, but persisting
        # with rewrite=True would discard everything older than that window on
        # every run. updatePKL's default merge keeps history (by date index)
        # while StatInfo still refreshes to the latest calibration.
        out_path = os.path.join(DIR_INPUT, 'Tenor-spds.pkl')
        updatePKL(tenor_spds, out_path)
        
    def compute_seasonal_screener(self) -> None:
        """Precompute per-instrument monthly seasonality stats for the screener.

        Reads the same *-spds.pkl files that the web Spread subtab consumes and runs
        :func:`monthly_seasonal_stats` for every instrument in each spread type.
        Writes ``seasonal-spds.pkl`` with structure::

            {
              spread_type: pd.DataFrame   # index=instrument, columns=month_1..month_12
                                          # each cell = dict(avg_chg_bp, consistency,
                                          #                  direction, p_value, n_years)
            }

        The screener callback reads this file directly (mtime-cached) so it never
        recomputes across hundreds of instruments on every click.
        """
        try:
            from web.tabs.alpha.seasonal import monthly_seasonal_stats
        except ImportError as exc:
            print(f'compute_seasonal_screener: cannot import seasonal module — {exc}')
            return

        _SPREAD_TYPE_SOURCES: list[tuple[str, str, str | None]] = [
            # (spread_type, pkl_file, inner_key_or_None)
            # inner_key=None means the pkl is directly {spread_type: {'Spread': df}}
            ('TenorSpread',  'Tenor-spds.pkl',    'TenorSpread'),
            ('TBondSwap',    'TBond-spds.pkl',     'BondSwap'),
            ('CBondSwap',    'CBond-spds.pkl',     'BondSwap'),
            ('TBondCurve',   'TBond-spds.pkl',     'BondCurve'),
            ('CBondCurve',   'CBond-spds.pkl',     'BondCurve'),
            ('SwapSpread',   'IRS-pxspds.pkl',     'SwapSpread'),
            ('NetBasis',     'futures-spds.pkl',   None),
            ('TermBasis',    'futures-spds.pkl',   None),
            ('FuturesSwap',  'futures-spds.pkl',   None),
        ]

        result: dict[str, pd.DataFrame] = {}

        for stype, pkl_name, inner_key in _SPREAD_TYPE_SOURCES:
            pkl_path = os.path.join(DIR_INPUT, pkl_name)
            try:
                data = pd.read_pickle(pkl_path)
            except Exception:
                continue

            # Navigate to the Spread DataFrame
            spread_df: pd.DataFrame | None = None
            try:
                if inner_key is None:
                    # futures-spds.pkl: {stype: {ticker: {'Spread': df, ...}}}
                    bucket = data.get(stype, {})
                    if isinstance(bucket, dict):
                        frames = {}
                        for tk, d in bucket.items():
                            if isinstance(d, dict):
                                sp = d.get('Spread')
                            elif isinstance(d, pd.DataFrame):
                                sp = d
                            else:
                                continue
                            if isinstance(sp, pd.DataFrame) and not sp.empty:
                                col = sp.iloc[:, 0]
                                frames[tk] = pd.to_numeric(col, errors='coerce')
                        if frames:
                            spread_df = pd.DataFrame(frames)
                    # TermBasis has a flat structure: {'Spread': wide_df, 'StatInfo': ...}
                    if spread_df is None and stype == 'TermBasis':
                        tb = data.get('TermBasis', {})
                        sp = tb.get('Spread') if isinstance(tb, dict) else None
                        if isinstance(sp, pd.DataFrame) and not sp.empty:
                            spread_df = sp.apply(pd.to_numeric, errors='coerce')
                else:
                    nested = data.get(inner_key, {})
                    if isinstance(nested, dict):
                        sp = nested.get('Spread')
                    elif isinstance(nested, pd.DataFrame):
                        sp = nested
                    else:
                        sp = None
                    if isinstance(sp, pd.DataFrame) and not sp.empty:
                        spread_df = sp.apply(pd.to_numeric, errors='coerce')
            except Exception as exc:
                print(f'compute_seasonal_screener: error loading {stype}: {exc}')
                continue

            if spread_df is None or spread_df.empty:
                continue

            # Compute monthly stats per instrument
            stat_rows: dict[str, dict] = {}
            for inst in spread_df.columns:
                s = spread_df[inst].dropna()
                if len(s) < 180:  # need at least ~3 years of trading days
                    continue
                try:
                    stats = monthly_seasonal_stats(s, min_years=3)
                except Exception:
                    continue
                if stats.empty:
                    continue
                stat_rows[inst] = {
                    f'm{m}': {
                        'avg_chg_bp':  float(row['avg_chg_bp']),
                        'consistency': float(row['consistency']),
                        'direction':   str(row['direction']),
                        'p_value':     float(row['p_value']),
                        'n_years':     int(row['n_years']),
                    }
                    for m, row in stats.iterrows()
                }

            if not stat_rows:
                continue

            # Flatten to a DataFrame: index=instrument, columns=m1..m12
            # Each cell stores the dict; the screener callback unpacks what it needs.
            result[stype] = pd.DataFrame.from_dict(stat_rows, orient='index')

        if not result:
            print('compute_seasonal_screener: no data produced — skipping write.')
            return

        out_path = os.path.join(DIR_INPUT, 'seasonal-spds.pkl')
        updatePKL(result, out_path, rewrite=True)
        print(f'compute_seasonal_screener: wrote {len(result)} spread types → {out_path}')

    # ---------------------- Orchestration ----------------------
    def run_all(self) -> None:
        self.compute_bond_and_swap_spreads()
        self.compute_irs_spreads()
        self.compute_other_bond_spreads()
        self.compute_spread_regression()
        self.compute_pca_spreads()
        self.compute_tenor_spreads()
        self.compute_futures_stats()
        self.compute_seasonal_screener()
        print('\nFinish initialising statistics at：', datetime.datetime.now().strftime('%H:%M:%S'))

    @classmethod
    def main(cls, date: Optional[str] = None, *, rebuild_irs_spreads: bool = False):
        """Main entry point for the StatGenerator.

        Args:
            date: Optional date string in YYYYMMDD format. Defaults to today.
        """
        asof = None
        if date:
            try:
                asof = datetime.datetime.strptime(date, '%Y%m%d').date()
            except (ValueError, TypeError):
                pass
        instance = cls(asof=asof)
        if rebuild_irs_spreads:
            instance.rebuild_irs_spreads_history()
        else:
            instance.run_all()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Generate or rebuild statistics artifacts')
    parser.add_argument('--date', default=None, help='Target date in YYYYMMDD or YYYY-MM-DD format')
    parser.add_argument('--rebuild-irs-spreads', action='store_true', help='Rebuild IRS-pxspds.pkl from full history')
    args = parser.parse_args()
    StatGenerator.main(date=args.date, rebuild_irs_spreads=args.rebuild_irs_spreads)