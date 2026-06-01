# -*- coding: utf-8 -*-
"""
Created on Tue Mar 12 21:50:28 2024

Refactored to OOP and optimized for performance.
"""
import os
import sys
import pickle
import pathlib
from datetime import datetime
import numpy as np
import pandas as pd
import xlwings as xw

# local libraries000
PATH = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(PATH))

from curves.utils import loader as ld
from curves.utils import retrieve as rd
from settings.paths import DIR_INPUT, DIR_OUTPUT
from settings.general import DateConfig, GeneralConfig
from settings.fixed_income import IRSConfig, BondConfig
from curves.calibration import irscurves as irs
from curves.calibration import hedge as h
import curves.calibration.stat as st
from curves.generators.stat import _suppress_model_jumps

class StatRefresher:
    """Refresh bond and swap statistics with OOP structure and performance improvements."""
    def __init__(self, skip_excel_update: bool = True) -> None:
        self.now = DateConfig.get_date_mappings()['d']
        self.d = self.now.date()
        self.dp = DateConfig.get_date_mappings()['dp'].date()
        self.tenor = list(np.linspace(1, 10, 10))
        _terms = IRSConfig.get_irs_terms()
        self.filtered_irs = [
            k for k in _terms.keys()
            if k not in {
                'SHIBOR3M.IR', 'SHI3MS7Y.IR', 'SHI3MS10Y.IR', 'FR007.IR', 'FR007S7Y.IR', 'FR007S10Y.IR'
            }
        ]
        
        # Configuration
        self.skip_excel_update = skip_excel_update

        # In-memory state shared across steps
        self.spot_ref: dict[str, pd.Series] = {}
        self.px_bond_rt: dict[str, pd.Series] = {}
        self.px_irs_rt: pd.Series | None = None

    @staticmethod
    def _np_interp(x_new: pd.Series, x: np.ndarray, y: np.ndarray) -> pd.Series:
        x_arr = np.asarray(x, dtype=float)
        y_arr = np.asarray(y, dtype=float)
        x_new_arr = np.asarray(x_new, dtype=float)
        order = np.argsort(x_arr)
        x_sorted, y_sorted = x_arr[order], y_arr[order]
        y_new = np.interp(x_new_arr, x_sorted, y_sorted)
        return pd.Series(y_new, index=x_new.index)

    @staticmethod
    def _update_excel(bonddata: pd.DataFrame, sheet_name: str) -> None:
        """Update Excel dashboard with bond data using simplified robust approach."""
        try:
            dashboard = os.path.join(PATH.parent, 'Dashboard.xlsm')
            
            if not os.path.exists(dashboard):
                print(f"Warning: Dashboard file not found at {dashboard}")
                return
            
            print("INFO: Preparing to write bond data to Dashboard.xlsm...")
            
            # Check if file is already open by another Excel instance
            existing_wb = None
            for app in xw.apps:
                for book in app.books:
                    if book.fullname.lower() == str(dashboard).lower():
                        print(f"INFO: Dashboard.xlsm is already open in another Excel instance")
                        existing_wb = book
                        break
                if existing_wb:
                    break
            
            if existing_wb:
                print("INFO: Using already open Dashboard.xlsm instance")
                wb = existing_wb
                app = wb.app
                should_close = False
            else:
                app = xw.App(visible=False, add_book=False)
                app.display_alerts = False
                app.screen_updating = False
                print("INFO: Opening Dashboard.xlsm...")
                wb = app.books.open(str(dashboard), update_links=False, read_only=False)
                should_close = True
            
            original_calc = app.calculation
            app.calculation = 'manual'
            
            try:
                # Get or create BondData sheet
                try:
                    sheet = wb.sheets[sheet_name]
                except:
                    sheet = wb.sheets.add(sheet_name)
                    print(f"INFO: Created {sheet_name} sheet")
                
                # Clear existing content
                print("INFO: Clearing existing sheet contents...")
                try:
                    sheet.clear_contents()
                except Exception as clear_err:
                    print(f"WARN: Could not clear sheet, will overwrite: {clear_err}")
                
                # Convert DataFrame to simple types to avoid COM conversion issues
                bonddata_clean = bonddata.reset_index()
                
                # Convert all numeric columns to float (avoid numpy types that COM can't handle)
                for col in bonddata_clean.columns:
                    if bonddata_clean[col].dtype in ['float64', 'int64']:
                        bonddata_clean[col] = bonddata_clean[col].astype(float)
                    elif bonddata_clean[col].dtype == 'object':
                        bonddata_clean[col] = bonddata_clean[col].astype(str)
                
                print("INFO: Writing data to excel sheet...")
                # Write header separately
                sheet.range('A1').value = list(bonddata_clean.columns)
                
                # Write data rows starting at A2
                sheet.range('A2').value = bonddata_clean.values.tolist()
                print("INFO: Successfully wrote bond data")
                
                # Save workbook
                print("INFO: Saving Dashboard.xlsm...")
                try:
                    wb.save()
                    print("SUCCESS: Dashboard.xlsm saved successfully")
                except Exception as save_error:
                    print(f"ERROR: Error saving workbook: {save_error}")
                    # Try alternative save method
                    try:
                        wb.api.Save()
                        print("SUCCESS: Dashboard saved via API")
                    except Exception as api_save_error:
                        print(f"ERROR: API save also failed: {api_save_error}")
                        raise
                
            finally:
                app.calculation = original_calc
                app.screen_updating = True
                if should_close:
                    try:
                        wb.close()
                        app.quit()
                    except:
                        pass
                        
        except Exception as e:
            print(f"ERROR: Critical error in _update_excel: {e}")


    def _write_pickle(self, obj, filename: str) -> None:
        path = os.path.join(DIR_INPUT, filename)
        with open(path, 'wb') as file:
            pickle.dump(obj, file, protocol=pickle.HIGHEST_PROTOCOL)

    @staticmethod
    def _repair_reference_sensitivities(curve, env: dict, sen: pd.DataFrame) -> tuple[pd.DataFrame, int]:
        """Backfill missing curve-reference sensitivities via TTM interpolation."""
        if sen is None or not isinstance(sen, pd.DataFrame) or sen.empty:
            return sen, 0
        if not hasattr(curve, 'reference') or not isinstance(curve.reference, pd.Series):
            return sen, 0

        df_def = env.get('Def', pd.DataFrame()) if isinstance(env, dict) else pd.DataFrame()
        if '剩余期限' not in df_def.columns:
            return sen, 0

        ref_ids = [bond_id for bond_id in curve.reference.dropna().tolist() if bond_id in df_def.index]
        missing_refs = [bond_id for bond_id in ref_ids if bond_id not in sen.index]
        if not missing_refs:
            return sen, 0

        source_terms = pd.to_numeric(df_def.reindex(sen.index)['剩余期限'], errors='coerce')
        source_sen = sen.apply(pd.to_numeric, errors='coerce')
        valid_rows = source_terms.notna() & source_sen.notna().all(axis=1)
        source_terms = source_terms.loc[valid_rows]
        source_sen = source_sen.loc[valid_rows]
        if len(source_sen) < 2:
            return sen, 0

        source_df = source_sen.copy()
        source_df['剩余期限'] = source_terms.astype(float)
        source_df = source_df.sort_values('剩余期限').drop_duplicates(subset='剩余期限', keep='last')
        if len(source_df) < 2:
            return sen, 0

        x = source_df['剩余期限'].to_numpy(dtype=float)
        repaired = sen.copy()
        filled_count = 0
        for bond_id in missing_refs:
            target_term = pd.to_numeric(pd.Series([df_def.loc[bond_id, '剩余期限']]), errors='coerce').iloc[0]
            if pd.isna(target_term):
                continue
            repaired.loc[bond_id, ['Greek1', 'Greek2', 'Greek3']] = [
                float(np.interp(float(target_term), x, source_df[greek].to_numpy(dtype=float)))
                for greek in ['Greek1', 'Greek2', 'Greek3']
            ]
            filled_count += 1

        return repaired.apply(pd.to_numeric, errors='coerce').dropna(how='all'), filled_count

    def refresh_bonds_and_swaps(self) -> None:
        print('\nRefresh spreads at：', self.now.strftime('%H:%M:%S'))

        write_to_sheet = {}
        for btype in ['CBond', 'TBond']:
            # Inputs
            with open(os.path.join(DIR_INPUT, f'{btype}-cvrt.obj'), 'rb') as f:
                curve = pickle.load(f)
            pxrt = pd.read_pickle(os.path.join(DIR_INPUT, f'{btype}-rtquo.pkl'))
            bond_px = pd.read_pickle(os.path.join(DIR_INPUT, f'{btype}-cvpx.pkl'))
            #
            ytm_quote = pxrt['Quote'][['ID', 'Bid', 'Ofr']].dropna().set_index('ID')
            ytm_quote_cv = pxrt['Quote'][['ID', 'CvBid', 'CvOfr']].dropna().set_index('ID')
            # Exclude bonds where the affine model produced no valid quote (CvBid=CvOfr=0);
            # these would otherwise give CurveYield=0 and a huge spurious spread/z-score.
            ytm_quote_cv = ytm_quote_cv[(ytm_quote_cv['CvBid'] > 0) & (ytm_quote_cv['CvOfr'] > 0)]
            # Exclude bonds where the model yield is implausibly far from the market yield
            # (|CvMid - MktMid| > 50bp indicates a calibration artifact, e.g. factor overflow).
            _cv_mid = (ytm_quote_cv['CvBid'] + ytm_quote_cv['CvOfr']) / 2
            _mkt_mid = ((ytm_quote['Bid'] + ytm_quote['Ofr']) / 2).reindex(ytm_quote_cv.index)
            ytm_quote_cv = ytm_quote_cv[(_cv_mid - _mkt_mid).abs() <= 0.5]
            self.spot_ref[btype] = pxrt['Curve']['SpotRate'][self.tenor]
            self.spot_ref[btype].index = [f'{btype}-{i}Y' for i in self.spot_ref[btype].index]

            env = rd.retrieveEnvRT(ld.loadInstrumentDefinition(btype), btype)
            stat_his = ld.loadStatData(btype)

            repaired_sen, repaired_count = self._repair_reference_sensitivities(curve, env, pxrt.get('Sen'))
            if repaired_count:
                pxrt['Sen'] = repaired_sen
                with open(os.path.join(DIR_INPUT, f'{btype}-rtquo.pkl'), 'wb') as f:
                    pickle.dump(pxrt, f)
                print(f"INFO: Backfilled {repaired_count} missing hedge sensitivities for {btype}.")

            try:
                bonds_hist = bond_px['ytm_quo'].columns.intersection(env['Def'].index)
                df_act_hist = bond_px['ytm_act'].loc[:, bonds_hist].apply(pd.to_numeric, errors='coerce')
                df_quo_hist = bond_px['ytm_quo'].loc[:, bonds_hist].apply(pd.to_numeric, errors='coerce')
                df_quo_hist = _suppress_model_jumps(df_quo_hist, df_act_hist)
                fresh_bc = st.statAnalysis_BC(env, df_act_hist, df_quo_hist).get('StatInfo', pd.DataFrame())
                if isinstance(fresh_bc, pd.DataFrame) and not fresh_bc.empty:
                    stat_his['BondCurve'] = fresh_bc
            except Exception as exc:
                print(f"WARN: Could not refresh {btype} BondCurve stats from historical cvpx: {exc}")

            stat_his = h.BondHedge(stat_his, env, ytm_quote, curve, pxrt['Sen'], btype)
            stat_his = h.SwapHedge(stat_his, env, ytm_quote)

            spreads = {t: stat_his[t] for t in ['BondCurve', 'BondSwap']}
            cvpx = (ytm_quote['Bid'] + ytm_quote['Ofr']) / 2

            # IRS RT mid and interpolation terms
            px_irs_rt = irs.get_swap_mid_quotes(env['SwapRT'], self.filtered_irs)

            self.px_irs_rt = px_irs_rt
            _dates = DateConfig.get_date_mappings()
            _irs_terms = IRSConfig.get_irs_terms()
            terms = np.asarray([(_dates['d'] + _irs_terms[i] - _dates['d']).days / GeneralConfig.YN for i in px_irs_rt.index], dtype=float)

            # Filter and clip bond terms, then interpolate using numpy
            env['Def'] = env['Def'][env['Def']['剩余期限'] > 3 / 12]
            bond_term = pd.to_numeric(env['Def']['剩余期限'].clip(upper=5.0), errors='coerce')
            px_bs_rt = self._np_interp(bond_term, terms, np.asarray(px_irs_rt.values, dtype=float))

            self.px_bond_rt[btype] = (env['BondRT']['买价收益率'] + env['BondRT']['卖价收益率']) / 2
            spreads['BondCurve']['CloseYield'] = self.px_bond_rt[btype]
            # Use affine model mid (CvBid/CvOfr) not market mid (Bid/Ofr) as CurveYield
            spreads['BondCurve']['CurveYield'] = (ytm_quote_cv['CvBid'] + ytm_quote_cv['CvOfr']) / 2
            spreads['BondCurve']['spread'] = spreads['BondCurve']['CloseYield'] - spreads['BondCurve']['CurveYield']
            spreads['BondSwap']['spread'] = self.px_bond_rt[btype] - px_bs_rt

            for k, df_k in spreads.items():
                vol_ = pd.to_numeric(df_k['vol'], errors='coerce') if 'vol' in df_k.columns else pd.Series(np.nan, index=df_k.index)
                if not isinstance(vol_, pd.Series):
                    vol_ = pd.Series(vol_, index=df_k.index)
                vol_ = vol_.where(vol_.abs() > 1e-6)
                if k == 'BondCurve':
                    # CurveYield already incorporates the historical mean adjustment
                    # (affine model output), so normalise the raw spread directly.
                    df_k['Zscore'] = df_k['spread'] / vol_
                else:
                    # BondSwap: the IRS rate is market-observed without mean adjustment,
                    # so subtract the OU mean before normalising.
                    mean_ = pd.to_numeric(df_k['mean'], errors='coerce') if 'mean' in df_k.columns else pd.Series(0.0, index=df_k.index)
                    if not isinstance(mean_, pd.Series):
                        mean_ = pd.Series(mean_, index=df_k.index)
                    df_k['Zscore'] = (df_k['spread'] - mean_) / vol_

            write_to_sheet[btype] = stat_his['BondCurve']
            write_to_sheet[btype + 'Swap'] = stat_his['BondSwap']
            self._write_pickle(spreads, f'{btype}-spdsrt.pkl')

        bondcurvedata = pd.concat([write_to_sheet['TBond'], write_to_sheet['CBond']], axis=0)
        bondswapdata = pd.concat([write_to_sheet['TBondSwap'], write_to_sheet['CBondSwap']], axis=0)
        # Push to Dashboard
        if not self.skip_excel_update:
            self._update_excel(bondcurvedata, "BondData")
            self._update_excel(bondswapdata, "BondSwapData")

    def refresh_other_bonds(self) -> None:
        # Use TBond curve as reference
        with open(os.path.join(DIR_INPUT, 'TBond-cvrt.obj'), 'rb') as f:
            curve = pickle.load(f)
        tbond_pxrt = pd.read_pickle(os.path.join(DIR_INPUT, 'TBond-rtquo.pkl'))
        tbond_hedge_sen = tbond_pxrt.get('Sen', pd.DataFrame())

        spreads_all = {}
        for obtype in BondConfig.INCLUDE_FILTERS.keys():
            opxrt = pd.read_pickle(os.path.join(DIR_INPUT, f'{obtype}-rtquo.pkl'))
            ytm_quote = opxrt['Quote'][['ID', 'Bid', 'Ofr']].dropna().set_index('ID')
            
            oenv = rd.retrieveEnvRT(ld.loadInstrumentDefinition(obtype), obtype)
            stat_his = ld.loadStatData(obtype)
            combined_sen = opxrt['Sen']
            if isinstance(tbond_hedge_sen, pd.DataFrame) and not tbond_hedge_sen.empty:
                combined_sen = pd.concat([combined_sen, tbond_hedge_sen], axis=0)
                combined_sen = combined_sen.loc[~combined_sen.index.duplicated(keep='first')]
            stat_his = h.BondHedge(stat_his, oenv, ytm_quote, curve, combined_sen, obtype)
            self.px_bond_rt[obtype] = (oenv['BondRT']['买价收益率'] + oenv['BondRT']['卖价收益率']) / 2
            px_cnbd = oenv['Def']['估价收益率:%(中债)']
            self.px_bond_rt[obtype] = self.px_bond_rt[obtype].fillna(px_cnbd)
            spreads_all[obtype + 'Spread'] = stat_his[obtype + 'Spread']
            cvpx = (ytm_quote['Bid'] + ytm_quote['Ofr']) / 2
            spreads_all[obtype + 'Spread']['spread'] = self.px_bond_rt[obtype] - cvpx
            for t in spreads_all.keys():
                mean_ = spreads_all[t]['mean'] if 'mean' in spreads_all[t].columns else 0
                spreads_all[t]['Zscore'] = (spreads_all[t]['spread'] - mean_) / spreads_all[t]['vol']
            spreads_all[obtype + 'Spread']['bondtype'] = obtype
            self._write_pickle(spreads_all[obtype + 'Spread'], f'{obtype}-spdsrt.pkl')

        spread_df = pd.concat(spreads_all, axis=0).droplevel(0)
        # Disabled for current workflow: do not generate OBondHedgings.xlsx
        # with pd.ExcelWriter(os.path.join(DIR_OUTPUT, 'OBondHedgings.xlsx')) as writer:
        #     spread_df.to_excel(writer)

    def refresh_misc_spreads(self) -> None:
        stat = ld.loadStatData('Misc')
        spreads = {}

        # Binary spreads
        spot30Y = self.px_bond_rt['TBond'].loc[stat['BinaryAnchor']['30Y']]
        spreads['BinarySpread'] = stat['BinarySpread']
        for b in spreads['BinarySpread'].index:
            label = spreads['BinarySpread'].loc[b, 'label']
            # Compound tickers (e.g. '260005.IB-250014.IB') must be handled as
            # pair spreads regardless of any label inherited from updatePKL merges.
            is_compound = isinstance(b, str) and '.IB-' in b
            if isinstance(label, str) and not is_compound:
                bt, yt = label[:5], label[5:]
                anchor = stat['BinaryAnchor'][yt]
                if b in self.px_bond_rt[bt].index:
                    spreads['BinarySpread'].loc[b, 'spread'] = self.px_bond_rt[bt].loc[b] - self.px_bond_rt['TBond'].loc[anchor]
            else:
                anchors = b.split('-')
                try:
                    spreads['BinarySpread'].loc[b, 'spread'] = self.px_bond_rt['TBond'].loc[anchors[0]] - self.px_bond_rt['TBond'].loc[anchors[1]]
                except Exception:
                    print('Missing', b)

        # PCA spread – combine TBond/CBond spot and IRS RT
        if self.px_irs_rt is None:
            raise RuntimeError('IRS RT series not initialised')
        spot = pd.concat([
            self.spot_ref['TBond'],
            pd.Series(spot30Y, index=['TBond-30.0Y']),
            self.spot_ref['CBond'],
            self.px_irs_rt,
        ], axis=0)
        spot0 = stat['SpotTS'].loc[self.dp].loc[spot.index]
        spreads['PCASpread'] = stat['PCASpread'].loc[spot.index]
        spreads['PCASpread']['spread'] = stat['SpreadTS'].loc[self.dp].loc[spot.index] + spot - spot0

        for t in spreads.keys():
            spreads[t]['Zscore'] = (spreads[t]['spread'] - spreads[t]['mean']) / spreads[t]['vol']
            if t != 'PCASpread':
                spreads[t].sort_index(inplace=True)

        # Rename decimal tenors: TBond-1.0Y -> TBond-1Y, CBond-2.0Y -> CBond-2Y
        import re as _re_stat
        spreads['PCASpread'].index = [
            _re_stat.sub(r'(-\d+)\.0(Y)$', r'\1\2', idx)
            for idx in spreads['PCASpread'].index
        ]

        self._write_pickle(spreads, 'Misc-spdsrt.pkl')

    def run_all(self) -> None:
        self.refresh_bonds_and_swaps()
        self.refresh_other_bonds()
        self.refresh_misc_spreads()

        # Build normalized alpha snapshot for Atlas UI candidate scanning.
        # Keep this non-fatal to avoid breaking the refresh pipeline.
        try:
            from curves.refreshers.alpha import save_alpha_spreads_snapshot

            save_alpha_spreads_snapshot(DIR_INPUT, rewrite=True)
            print('INFO: Saved Alpha-spreadsrt.pkl')
        except Exception as e:
            print(f'WARN: Failed to build Alpha-spreadsrt.pkl: {e}')

        print('\nFinish refreshing statistics at：', datetime.now().strftime('%H:%M:%S'))

    @classmethod
    def main(cls, skip_excel_update=True):
        """Main entry point for the StatRefresher"""
        instance = cls(skip_excel_update=skip_excel_update)
        instance.run_all()


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Refresh bond and swap statistics')
    parser.add_argument('--skip-excel', action='store_true', 
                       help='Skip Excel dashboard updates')
    parser.add_argument('--write-excel', action='store_true',
                       help='Opt in to legacy Dashboard.xlsm updates')
    parser.add_argument('--diagnose', action='store_true',
                       help='Run Excel diagnostics before processing')
    
    args = parser.parse_args()
    
    # Run diagnostics if requested
    if args.diagnose:
        try:
            from data.excel.excel_utils import diagnose_dashboard_issues
            diagnose_dashboard_issues()
        except ImportError:
            print("Excel diagnostics not available")
    
    # Run the refresher
    StatRefresher.main(skip_excel_update=(not args.write_excel) or args.skip_excel)