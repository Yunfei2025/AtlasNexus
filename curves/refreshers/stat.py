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

# local libraries
PATH = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(PATH))

from curves.utils import loader as ld
from curves.utils import retrieve as rd
from settings.paths import DIR_INPUT, DIR_OUTPUT
from settings.general import DateConfig, GeneralConfig
from settings.fixed_income import IRSConfig, BondConfig
from curves.calibration import irscurves as irs
from curves.calibration import hedge as h

class StatRefresher:
    """Refresh bond and swap statistics with OOP structure and performance improvements."""
    def __init__(self, skip_excel_update: bool = False) -> None:
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
        order = np.argsort(x)
        x_sorted, y_sorted = np.asarray(x)[order], np.asarray(y)[order]
        y_new = np.interp(x_new.values.astype(float), x_sorted, y_sorted)
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
        with open(os.path.join(DIR_INPUT, filename), 'wb') as f:
            pickle.dump(obj, f)

    def refresh_bonds_and_swaps(self) -> None:
        print('\nRefresh spreads at：', self.now.strftime('%H:%M:%S'))

        write_to_sheet = {}
        for btype in ['CBond', 'TBond']:
            # Inputs
            with open(os.path.join(DIR_INPUT, f'{btype}-cvrt.obj'), 'rb') as f:
                curve = pickle.load(f)
            pxrt = pd.read_pickle(os.path.join(DIR_INPUT, f'{btype}-rtquo.pkl'))
            #
            ytm_quote = pxrt['Quote'][['ID', 'Bid', 'Ofr']].dropna().set_index('ID')
            self.spot_ref[btype] = pxrt['Curve']['SpotRate'][self.tenor]
            self.spot_ref[btype].index = [f'{btype}-{i}Y' for i in self.spot_ref[btype].index]

            env = rd.retrieveEnvRT(ld.loadInstrumentDefinition(btype), btype)
            stat_his = ld.loadStatData(btype)

            stat_his = h.BondHedge(stat_his, env, ytm_quote, curve, pxrt['Sen'], btype)
            stat_his = h.SwapHedge(stat_his, env, ytm_quote)

            spreads = {t: stat_his[t] for t in ['BondCurve', 'BondSwap']}
            cvpx = (ytm_quote['Bid'] + ytm_quote['Ofr']) / 2

            # IRS RT mid and interpolation terms
            px_irs_rt = irs.get_swap_mid_quotes(env['SwapRT'], self.filtered_irs)

            self.px_irs_rt = px_irs_rt
            _dates = DateConfig.get_date_mappings()
            _irs_terms = IRSConfig.get_irs_terms()
            terms = np.array([(_dates['d'] + _irs_terms[i] - _dates['d']).days / GeneralConfig.YN for i in px_irs_rt.index])

            # Filter and clip bond terms, then interpolate using numpy
            env['Def'] = env['Def'][env['Def']['剩余期限'] > 3 / 12]
            bond_term = env['Def']['剩余期限'].clip(upper=5.0)
            px_bs_rt = self._np_interp(bond_term, terms, px_irs_rt.values)

            self.px_bond_rt[btype] = (env['BondRT']['买价收益率'] + env['BondRT']['卖价收益率']) / 2
            spreads['BondCurve']['CloseYield'] = self.px_bond_rt[btype]
            spreads['BondCurve']['CurveYield'] = cvpx
            spreads['BondCurve']['spread'] = spreads['BondCurve']['CloseYield'] - spreads['BondCurve']['CurveYield']
            spreads['BondSwap']['spread'] = self.px_bond_rt[btype] - px_bs_rt

            for k in spreads.keys():
                mean_ = spreads[k]['mean'] if 'mean' in spreads[k].columns else 0
                spreads[k]['Zscore'] = (spreads[k]['spread'] - mean_) / spreads[k]['vol']

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

        spreads_all = {}
        for obtype in BondConfig.INCLUDE_FILTERS.keys():
            opxrt = pd.read_pickle(os.path.join(DIR_INPUT, f'{obtype}-rtquo.pkl'))
            ytm_quote = opxrt['Quote'][['ID', 'Bid', 'Ofr']].dropna().set_index('ID')
            
            oenv = rd.retrieveEnvRT(ld.loadInstrumentDefinition(obtype), obtype)
            stat_his = ld.loadStatData(obtype)
            stat_his = h.BondHedge(stat_his, oenv, ytm_quote, curve, opxrt['Sen'], obtype)
            self.px_bond_rt[obtype] = (oenv['BondRT']['买价收益率'] + oenv['BondRT']['卖价收益率']) / 2
            px_cnbd = oenv['Def']['估价收益率:%(中债)']
            self.px_bond_rt[obtype] = self.px_bond_rt[obtype].fillna(px_cnbd)
            spreads_all[obtype + 'Spread'] = stat_his[obtype + 'Spread']
            cvpx = (ytm_quote['Bid'] + ytm_quote['Ofr']) / 2
            spreads_all[obtype + 'Spread']['spread'] = self.px_bond_rt[obtype] - cvpx
            for t in spreads_all.keys():
                spreads_all[t]['Zscore'] = (spreads_all[t]['spread']) / spreads_all[t]['vol']
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
            if isinstance(label, str):
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
    def main(cls, skip_excel_update=False):
        """Main entry point for the StatRefresher"""
        instance = cls(skip_excel_update=skip_excel_update)
        instance.run_all()


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Refresh bond and swap statistics')
    parser.add_argument('--skip-excel', action='store_true', 
                       help='Skip Excel dashboard updates')
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
    StatRefresher.main(skip_excel_update=args.skip_excel)