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
from curves.utils.file import updatePKL
from settings.paths import DIR_INPUT, DIR_OUTPUT 
from settings.fixed_income import BondConfig, IRSConfig
from settings.general import GeneralConfig, DateConfig 
from settings.futures import FuturesConfig

def _suppress_model_jumps(
    df_quo: pd.DataFrame,
    df_act: pd.DataFrame,
    jump_threshold: float = 0.08,
    ratio_threshold: float = 5.0,
) -> pd.DataFrame:
    """Suppress affine model calibration artifacts (discontinuous factor shifts) in ytm_quo.

    A calibration jump is flagged when ytm_quo changes by more than `jump_threshold` (in %)
    while ytm_act barely moves (ratio of changes exceeds `ratio_threshold`).
    Flagged entries are replaced with NaN then linearly interpolated.
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

    def __init__(self) -> None:
        # Dates and windows
        dates = DateConfig.get_date_mappings()
        self.d: datetime.date = dates['d'].date()
        self.dp: datetime.date = dates['dp'].date()
        self.start: datetime.date = (self.d - relativedelta(months=GeneralConfig.STAT_WINDOW))
        self.start1y: datetime.date = (self.d - relativedelta(years=1))
        self.da: datetime.datetime = self.d - timedelta(hours=1)

        # Global env time series
        self.env_ts: dict = loadCNBDTS()

        # In-memory state
        self.spot_ts: dict = {}
        self.bond_groups: dict = {}
        self.spreads: dict = {}

        # Cache TBond env/series explicitly to avoid implicit variable leakage
        self.env_tbond: Optional[dict] = None
        self.df_act_tbond: Optional[pd.DataFrame] = None

    # ---------------------- Bonds (TBond/CBond) ----------------------
    def compute_bond_and_swap_spreads(self) -> None:
        for btype in ['TBond', 'CBond']:
            env = loadInstrumentDefinition(btype)

            curve_objs = updatePKL({}, os.path.join(DIR_INPUT, f'{btype}-cvobj.pkl'))
            bond_px = updatePKL({}, os.path.join(DIR_INPUT, f'{btype}-cvpx.pkl'))
            ref = loadRefData(btype)

            bonds = bond_px['ytm_quo'].columns.intersection(env['Def'].index)
            df_act = bond_px['ytm_act'].loc[self.start:self.da, bonds].drop_duplicates()
            df_quo = bond_px['ytm_quo'].loc[self.start:self.da, bonds].drop_duplicates()
            
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
            _col_prefix = '中债国债到期收益率:' if btype == 'TBond' else '中债国开债到期收益率:'
            _tenor_years = [1, 2, 3, 4, 5, 7, 10, 20, 30]
            bond_key_ts_df = None
            if isinstance(_cnbd_bond_ts, pd.DataFrame):
                _avail = {
                    t: _cnbd_bond_ts[f'{_col_prefix}{t}年']
                    for t in _tenor_years
                    if f'{_col_prefix}{t}年' in _cnbd_bond_ts.columns
                }
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
            curve0 = curve_objs[self.dp]
            spot_dp = curve0.fitting()['SpotRate']
            spot_dp.index = [f"{btype}-{t}Y" for t in spot_dp.index]
            clist_ = list(self.spot_ts[btype].columns)
            self.spot_ts[btype].loc[self.dp, clist_] = spot_dp.loc[clist_]
            self.spot_ts[btype] = self.spot_ts[btype].astype(float)

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
    def compute_irs_spreads(self) -> None:
        btype = 'IRS'
        irs_px = updatePKL({}, os.path.join(DIR_INPUT, f'{btype}-cvpx.pkl'))
        df_act_irs = irs_px['ytm_act'].loc[self.start:self.da, IRSConfig.IRS_LIST].drop_duplicates()
        df_quo_irs = irs_px['ytm_quo'].loc[self.start:self.da, IRSConfig.IRS_LIST].drop_duplicates()

        # Clean data to handle byte strings and invalid values
        df_act_irs = df_act_irs.apply(pd.to_numeric, errors='coerce')
        df_quo_irs = df_quo_irs.apply(pd.to_numeric, errors='coerce')
        
        cvpx_stat = st.statAnalysis_IRS(df_act_irs, df_quo_irs)

        cpr = irs_px['carry3m'] + irs_px['roll3m']
        from curves.calibration.irscurves import irsSpreads
        spds_cpr = irsSpreads(cpr)

        cvpx_stat['CarryRoll3m'] = spds_cpr
        updatePKL(cvpx_stat, os.path.join(DIR_INPUT, f'{btype}-pxspds.pkl'))

        # Use a filtered copy instead of mutating config.irs_terms
        excluded = {'SHIBOR3M.IR', 'SHI3MS7Y.IR', 'SHI3MS10Y.IR', 'FR007S7Y.IR', 'FR007S10Y.IR'}
        _irs_terms = IRSConfig.get_irs_terms()
        filtered_terms = [k for k in _irs_terms.keys() if k not in excluded]
        self.spot_ts[btype] = self.env_ts['SwapTS'][filtered_terms]

    # ---------------------- Other sectors ----------------------
    def compute_other_bond_spreads(self) -> None:
        for obtype in BondConfig.INCLUDE_FILTERS.keys():
            env_obond = loadInstrumentDefinition(obtype)
            obond_px = updatePKL({}, os.path.join(DIR_INPUT, f'{obtype}-cvpx.pkl'))

            bonds_obond = obond_px['ytm_quo'].columns.intersection(env_obond['Def'].index)
            df_act_obond = obond_px['ytm_act'].loc[self.start:self.da, bonds_obond].drop_duplicates()
            df_quo_obond = obond_px['ytm_quo'].loc[self.start:self.da, bonds_obond].drop_duplicates()
            
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

        bond_ts = self.df_act_tbond.loc[self.start:].apply(pd.to_numeric, errors='coerce')
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

        spreads_b = pd.concat(spreads_bi, axis=1).droplevel(0, axis=1).sort_index()
        spreads_b.drop(columns=list(anchor.values()), inplace=True, errors='ignore')
        spreads_b = spreads_b.loc[self.start:self.da]

        # Fast linear fit per series
        stat0 = pd.DataFrame(index=spreads_b.columns)
        resi_cols = {}
        for k in self.bond_groups.keys():
            for c in self.bond_groups[k].columns:
                if c not in anchor.values():
                    stat0.loc[c, 'label'] = k
        for col in spreads_b.columns:
            series = spreads_b[col].dropna().reset_index(drop=True)
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
        raw_mean = spreads_b.mean()
        raw_std  = spreads_b.std()
        stat_['mean'] = raw_mean.reindex(stat_.index)
        stat_['vol']  = raw_std.reindex(stat_.index)
        stat_.drop('level', axis=1, inplace=True)

        # Save to Excel
        with pd.ExcelWriter(os.path.join(DIR_OUTPUT, 'PairSpreads.xlsx')) as writer:
            stat_.to_excel(writer)

        # Persist in spreads dict for downstream use
        self.spreads['BinarySpread'] = {
            'StatInfo': stat_,
            'Spread': spreads_b,
            'Anchor': anchor,
        }

    # ---------------------- PCA spreads ----------------------
    def compute_pca_spreads(self) -> None:
        spot_ts_all = pd.concat(self.spot_ts, axis=1).droplevel(level=0, axis=1).sort_index()
        spot_ts_all = spot_ts_all.loc[self.start1y:].dropna()
        
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

    # ---------------------- Futures ----------------------
    def compute_futures_stats(self) -> None:
        btype = 'futures'
        env = loadInstrumentDefinition(btype)
        env_ts = updatePKL({}, os.path.join(DIR_INPUT, f'{btype}-px.pkl'))

        spreads = {'NetBasis': {}, 'NetIRR': {}}
        fundrate = self.env_ts['SwapTS']['FR007.IR']

        # Term basis across seasons
        termbasis = {}
        for season in FuturesConfig.SEASONS.values():
            if season == 'NQ1':
                continue
            for i in range(len(env['Bucket']['NQ1'])):
                c0 = env['Bucket']['NQ1'][i]
                c = env['Bucket'][season][i]
                key = f"{c}-{c0}"
                termbasis[key] = env_ts['close'][season][c].sub(env_ts['close']['NQ1'][c0], axis=0)
        termbasis_df = pd.DataFrame(termbasis)
        
        # Clean data to handle byte strings and invalid values
        termbasis_df = termbasis_df.apply(pd.to_numeric, errors='coerce')
        
        spreads['TermBasis'] = st.statAnalysis(termbasis_df)

        # Net basis and IRR by season
        for season in FuturesConfig.SEASONS.values():
            # Clean netbasis data before statistical analysis
            netbasis_clean = env_ts['netbasis'][season].apply(pd.to_numeric, errors='coerce')
            spreads['NetBasis'][season] = st.statAnalysis(netbasis_clean)
            irr = env_ts['irr'][season].subtract(fundrate, axis=0)
            irr.dropna(axis=0, how='all', inplace=True)
            spreads['NetIRR'][season] = irr

        # Annotate ttm and futures name
        statinfo_by_season = {}
        for season in FuturesConfig.SEASONS.values():
            for f in env['Bucket'][season]:
                for t in env['DeliveryPool'][f].index:
                    spreads['NetBasis'][season]['StatInfo'].loc[t, 'ttm'] = env['DeliveryPool'][f].loc[t, 'term']
                    spreads['NetBasis'][season]['StatInfo'].loc[t, 'futures'] = f
            statinfo_by_season[season] = spreads['NetBasis'][season]['StatInfo']

        # Disabled for current workflow: do not generate FuturesStatInfo.xlsx
        # with pd.ExcelWriter(os.path.join(DIR_OUTPUT, 'FuturesStatInfo.xlsx')) as writer:
        #     for k, df in statinfo_by_season.items():
        #         df.to_excel(writer, sheet_name=k)

        updatePKL(spreads, os.path.join(DIR_INPUT, f'{btype}-spds.pkl'), rewrite=True)

    # ---------------------- Tenor spreads ----------------------
    def compute_tenor_spreads(self) -> None:
        """Build tenor-spread (CGB/CDB slope + CDBCGB cross-sector) time series,
        compute carry+roll (3m, %) for each instrument, run OU statistics, and
        persist to ``Tenor-spds.pkl``.

        File structure::

            Tenor-spds.pkl  →  dict
              'TenorSpread'
                'Spread'       : pd.DataFrame  — annual yield diff in %  (index=date, cols=instruments)
                'CarryRoll3m'  : pd.DataFrame  — 3m carry in % for a BUY trade
                                               (XsYs: negated; CDBCGB: positive)
                'StatInfo'     : pd.DataFrame  — OU statistics per instrument
        """
        env_ts = self.env_ts
        if not isinstance(env_ts, dict) or 'CGB' not in env_ts or 'CDB' not in env_ts:
            print('Warning: CGB/CDB key-rate data not available — skipping tenor spreads.')
            return

        cgb = env_ts['CGB']
        cdb = env_ts['CDB']

        # Column name helpers — allow the function to work even if a key is missing.
        def _series(src: dict, key: str):
            """Return src[key] as a float Series, or None if missing."""
            v = src.get(key)
            if v is None:
                return None
            return pd.to_numeric(v, errors='coerce')

        cgb5  = _series(cgb, '中债国债到期收益率:5年')
        cgb10 = _series(cgb, '中债国债到期收益率:10年')
        cgb20 = _series(cgb, '中债国债到期收益率:20年')
        cgb30 = _series(cgb, '中债国债到期收益率:30年')
        cdb5  = _series(cdb, '中债国开债到期收益率:5年')
        cdb10 = _series(cdb, '中债国开债到期收益率:10年')
        cdb30 = _series(cdb, '中债国开债到期收益率:30年')

        instruments = {}
        if cgb5  is not None and cgb10 is not None: instruments['CGB-5s10s']  = cgb10  - cgb5
        if cgb10 is not None and cgb30 is not None: instruments['CGB-10s30s'] = cgb30  - cgb10
        if cgb10 is not None and cgb20 is not None: instruments['CGB-10s20s'] = cgb20  - cgb10
        if cdb5  is not None and cdb10 is not None: instruments['CDB-5s10s']  = cdb10  - cdb5
        if cdb10 is not None and cdb30 is not None: instruments['CDB-10s30s'] = cdb30  - cdb10
        if cdb5  is not None and cgb5  is not None: instruments['CDBCGB-5y']  = cdb5   - cgb5
        if cdb10 is not None and cgb10 is not None: instruments['CDBCGB-10y'] = cdb10  - cgb10
        if cdb30 is not None and cgb30 is not None: instruments['CDBCGB-30y'] = cdb30  - cgb30

        if not instruments:
            print('Warning: Could not build any tenor-spread series.')
            return

        # Spread DataFrame: annual yield diff in % (e.g. 0.30 for 30bp)
        df_spread = pd.DataFrame(instruments).apply(pd.to_numeric, errors='coerce')
        df_spread = df_spread.loc[self.start:].sort_index()

        # Carry+Roll (3m) in %:
        #   XsYs (CGB-10s30s etc.)  BUY = long short-tenor, short long-tenor
        #     → carry = Y_short − Y_long = −spread  → CR3m = −spread × 0.25
        #   CDBCGB cross-sector     BUY = long CDB, short CGB
        #     → carry = Y_CDB − Y_CGB = +spread     → CR3m = +spread × 0.25
        df_cr3m = df_spread.copy() * (90.0 / 360.0)
        for col in df_cr3m.columns:
            if re.search(r'\d+s\d+', col, re.IGNORECASE):
                df_cr3m[col] = -df_cr3m[col]

        # OU statistics on spread levels
        try:
            stat_info = st.OU_calibrate(df_spread.dropna(how='all'))
        except Exception as exc:
            print(f'Warning: OU calibration for tenor spreads failed: {exc}')
            stat_info = pd.DataFrame(index=df_spread.columns)

        tenor_spds = {
            'TenorSpread': {
                'Spread':      df_spread,
                'CarryRoll3m': df_cr3m,
                'StatInfo':    stat_info,
            }
        }
        out_path = os.path.join(DIR_INPUT, 'Tenor-spds.pkl')
        updatePKL(tenor_spds, out_path, rewrite=True)
        print(f'  Tenor-spds.pkl written: {list(instruments.keys())}')

    # ---------------------- Orchestration ----------------------
    def run_all(self) -> None:
        self.compute_bond_and_swap_spreads()
        self.compute_irs_spreads()
        self.compute_other_bond_spreads()
        self.compute_spread_regression()
        self.compute_pca_spreads()
        self.compute_tenor_spreads()
        # self.compute_futures_stats()
        print('\nFinish initialising statistics at：', datetime.datetime.now().strftime('%H:%M:%S'))

    @classmethod
    def main(cls):
        """Main entry point for the StatGenerator"""
        instance = cls()
        instance.run_all()


if __name__ == '__main__':
    StatGenerator.main()