# -*- coding: utf-8 -*-
"""
Created on Wed Jan 11 11:31:53 2023

@author: 马云飞
"""
import os 
import sys
import pathlib
import importlib
import pandas as pd
import pickle
from datetime import datetime

# Toggle verbose console output for heavy loops
VERBOSE = False


def get_mtime_date(path_obj: pathlib.Path):
    """Get modification date of a file, return None if file doesn't exist."""
    try:
        p = pathlib.Path(path_obj)
        return datetime.fromtimestamp(p.stat().st_mtime).date()
    except FileNotFoundError:
        return None


def parse_date(date_str):
    return datetime.strptime(date_str, '%Y-%m-%d').date()


def dict2excel(fdict,filename):
    with pd.ExcelWriter(filename) as writer:
        for k in fdict.keys():
            fdict[k].to_excel(writer,sheet_name=k)
    
def updatefile(df,file,rewrite=False,dropna=True):
    if rewrite:
        df.to_csv(file)   
        df_ = df

    else:
        if os.path.exists(file):
            df_ = pd.read_csv(file,index_col=0,parse_dates=True)
            #new_dates = [ d for d in df.index if d not in df_.index ]
            new_dates = [ d for d in df.index ]
            for d in new_dates:
                df_.loc[d,df.columns] = df.loc[d]
            df_ = df_.sort_index()       
        else:
            df_ = df  
        if dropna:
            df_ = df_.dropna() 
        df_.to_csv(file)        
    return df_ 


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