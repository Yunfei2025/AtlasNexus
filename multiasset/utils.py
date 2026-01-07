# -*- coding: utf-8 -*-
"""
Created on Tue Nov 25 20:23:03 2025

@author: CMBC
"""
import os
import pandas as pd
import pickle

tenorlist = ["1Y","2M","5Y","10Y", "30Y"]
countrylist = ["US","JP","DE","UK"]

wdstring = "G0000886,G0000887,G0000889,G0000891,G0000893,\
G1235655,G1235656,G1235659,G1235664,G1235668,\
V8579294,K3585162,A6910824,A5540027,A1410477,\
G1306752,G4161196,G0006352,G0006353,G1306755"
wdlist = wdstring.split(",")          

ticker_dict = {}
i = 0
for c in countrylist:
    ticker_dict[c] = []
    for t in tenorlist:
        ticker_dict[c].append(wdlist[i])
        i += 1


def get_default_sensitivities(tenor: str) -> dict:
    """
    Get default sensitivities for bond tenor.
    
    Configure the sensitivities for IRDL (yield level), IRSL (yield slope),
    IRCV (yield curvature), and FXDL (FX) risk factors for each tenor.
    
    Args:
        tenor: Tenor string (e.g., '1Y', '2Y', '5Y', '10Y', '30Y')
        
    Returns:
        Dict with default IRDL, IRSL, IRCV, and FXDL sensitivities
    """
    # Mapping of tenors to approximate durations and curve sensitivities
    # IRDL: Duration sensitivity to parallel shifts
    # IRSL: Sensitivity to slope changes (10Y-1Y spread)
    # IRCV: Sensitivity to curvature changes (2×5Y - 2Y - 10Y butterfly)
    # FXDL: FX sensitivity (1.0 = full currency exposure)
    defaults = {
        '1Y': {'IRDL': 0.95, 'IRSL': 0.0, 'IRCV': 0.0, 'FXDL': 1.0},   # Short end: level only
        '2Y': {'IRDL': 1.90, 'IRSL': 0.15, 'IRCV': -0.5, 'FXDL': 1.0}, # Short: negative curvature exposure
        '5Y': {'IRDL': 4.50, 'IRSL': 0.50, 'IRCV': 1.0, 'FXDL': 1.0},  # Belly: positive curvature exposure
        '10Y': {'IRDL': 8.50, 'IRSL': 1.00, 'IRCV': -0.5, 'FXDL': 1.0}, # Long: negative curvature exposure
        '30Y': {'IRDL': 17.0, 'IRSL': 2.00, 'IRCV': 0.0, 'FXDL': 1.0},  # Ultra long: minimal curvature
    }
    
    return defaults.get(tenor, {'IRDL': 5.0, 'IRSL': 3.0, 'IRCV': 0.0, 'FXDL': 1.0})
        
def updatePKL(dictn,file_path,rewrite=False):
    if rewrite:
        with open(file_path, 'wb') as file:
            pickle.dump(dictn, file, protocol=pickle.HIGHEST_PROTOCOL)
        return dictn
    else:
        if os.path.exists(file_path):
            # Load existing object using safe loading
            dict_ = pd.read_pickle(file_path)
            if dict_ is None:
                print(f"Starting with empty dictionary for {file_path}")
                dict_ = {}

            # Helper updaters to avoid per-date loops
            def _update_dataframe(target_df, new_df):
                if target_df is None or not isinstance(target_df, pd.DataFrame):
                    target_df = pd.DataFrame()
                # Ensure both index and columns cover the union before assignment
                union_idx = target_df.index.union(new_df.index)
                union_cols = target_df.columns.union(new_df.columns)
                target_df = target_df.reindex(index=union_idx, columns=union_cols)
                target_df.loc[new_df.index, new_df.columns] = new_df
                target_df = target_df.sort_index().dropna(axis=0, how="all")
                return target_df

            def _update_series(target_ser, new_ser):
                if target_ser is None or not isinstance(target_ser, pd.Series):
                    target_ser = pd.Series(dtype=float)
                union_idx = target_ser.index.union(new_ser.index)
                target_ser = target_ser.reindex(union_idx)
                target_ser.loc[new_ser.index] = new_ser
                target_ser = target_ser.sort_index().dropna(axis=0, how="all")
                return target_ser

            def _update_value(target_val, new_val):
                # For strings or scalars, prefer new value
                return new_val

            def _update_dict(target_dict, new_dict):
                if target_dict is None or not isinstance(target_dict, dict):
                    target_dict = {}
                for sub_key, sub_new in new_dict.items():
                    sub_old = target_dict.get(sub_key)
                    if isinstance(sub_new, pd.DataFrame):
                        target_dict[sub_key] = _update_dataframe(sub_old, sub_new)
                    elif isinstance(sub_new, pd.Series):
                        target_dict[sub_key] = _update_series(sub_old, sub_new)
                    elif isinstance(sub_new, dict):
                        target_dict[sub_key] = _update_dict(sub_old, sub_new)
                    else:
                        target_dict[sub_key] = _update_value(sub_old, sub_new)
                return target_dict

            for k, v in dictn.items():
                if isinstance(v, pd.DataFrame):
                    dict_[k] = _update_dataframe(dict_.get(k), v)
                elif isinstance(v, pd.Series):
                    dict_[k] = _update_series(dict_.get(k), v)
                elif isinstance(v, dict):
                    dict_[k] = _update_dict(dict_.get(k), v)
                else:
                    dict_[k] = _update_value(dict_.get(k), v)

            with open(file_path, 'wb') as file:
                pickle.dump(dict_, file, protocol=pickle.HIGHEST_PROTOCOL)
            return dict_
        else:
            with open(file_path, 'wb') as file:
                pickle.dump(dictn, file, protocol=pickle.HIGHEST_PROTOCOL)
            return dictn