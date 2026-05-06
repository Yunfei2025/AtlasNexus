"""
Data loading and processing module
Includes Wind data loading, local file loading, and data preprocessing
"""

import pandas as pd
import os
import re
from datetime import datetime
import functools
from settings.paths import DIR_DATA, DIR_INPUT

from data.providers.retrieve import _is_trading_hours

def init_wind():
    """Initialize Wind API connection"""
    if not _is_trading_hours():
        return False
    try:
        from WindPy import w
    except ImportError:
        return False
    if not w.isconnected():
        w.start()
    return True


@functools.lru_cache(maxsize=32)
def load_wind_data(symbol, start_date, end_date):
    """Load minute data from Wind API"""
    if not init_wind():
        return None, "Wind API connection failed"
        
    try:
        from WindPy import w
        # w.wsi returns a WindData object
        wind_data = w.wsi(symbol, "open,high,low,close,volume", start_date, end_date, "")
        
        if wind_data.ErrorCode != 0:
            return None, f"Wind data fetch failed, error code: {wind_data.ErrorCode}, message: {wind_data.Data}"
            
        if not wind_data.Data:
            return None, f"No data retrieved for {symbol}"
            
        # Convert WindData to DataFrame
        df = pd.DataFrame(wind_data.Data, index=wind_data.Fields, columns=wind_data.Times).T
        
        # Rename columns
        df.columns = [c.lower() for c in df.columns]
        df.index.name = 'datetime'
        
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required_cols):
             return None, f"Wind data missing required fields. Returned fields: {df.columns.tolist()}"

        df['last'] = df['close']
        return df, None
        
    except Exception as e:
        return None, f"Wind data retrieval error: {e}"


def get_file_list(directory='.'):
    """Get all .pkl files in directory"""
    try:
        files = [f for f in os.listdir(directory) if f.endswith('.pkl')]
        return sorted(files)
    except:
        return []


def discover_pkl_files():
    """
    Discover and aggregate .pkl files from common directories:
    - <project_root>/input/futures-dailyK_con.pkl (only this file)
    - <project_root>/database/futures/*.pkl (all pkl files)
    - Current working directory
    
    Note: project_root is the parent folder of bin-v3.0
    Returns Dash Dropdown options list: [{label, value}], where value is absolute path, label is basename.
    """
    try:
        script_dir = os.path.dirname(__file__)
        # project_root should be the parent folder of bin-v3.0 (one level above bin-v3.0)
        project_root = os.path.abspath(os.path.join(script_dir, '..', '..', '..'))
        
        candidate_dirs = [
            os.path.join(project_root, 'input'),
            os.path.join(project_root, 'database', 'futures'),
        ]

        options = []
        seen = set()

        for d in candidate_dirs:
            if os.path.isdir(d):
                for f in os.listdir(d):
                    if not f.endswith('.pkl'):
                        continue

                    if os.path.normpath(d) == os.path.normpath(os.path.join(project_root, 'input')):
                        if f != 'futures-dailyK_con.pkl':
                            continue

                    full = os.path.join(d, f)
                    if full not in seen:
                        seen.add(full)
                        # Display friendly label: show filename only (basename)
                        label = os.path.basename(full)
                        options.append({'label': label, 'value': full})

        # Also include .pkl files from current working directory (if any)
        cwd = os.getcwd()
        if os.path.isdir(cwd):
            for f in os.listdir(cwd):
                if not f.endswith('.pkl'):
                    continue
                full = os.path.join(cwd, f)
                if full not in seen:
                    seen.add(full)
                    label = os.path.basename(full)
                    options.append({'label': label, 'value': full})

        options.sort(key=lambda x: x['label'])
        return options
    except Exception:
        return []


@functools.lru_cache(maxsize=32)
def load_raw_file(file_path):
    """Load raw file content (cached)"""
    try:
        return pd.read_pickle(file_path)
    except Exception as e:
        return None


def get_file_structure(file_path):
    """Analyze file structure, return type, key list, and date range"""
    data = load_raw_file(file_path)
    if data is None:
        return "error", [], None, None
        
    if not isinstance(data, dict):
        return "unknown", [], None, None
        
    keys = list(data.keys())
    if not keys:
        return "empty", [], None, None
        
    first_key = keys[0]
    
    # Check if it's a contract dictionary
    is_contract_dict = False
    try:
        pd.to_datetime(first_key)
        is_contract_dict = False
    except:
        is_contract_dict = True
        
    if isinstance(first_key, (datetime, pd.Timestamp)):
        is_contract_dict = False
        
    # If it's a contract dictionary, return contract list
    if is_contract_dict:
        # Try to get time range from first contract as default
        try:
            first_df = data[keys[0]]
            if isinstance(first_df, pd.DataFrame):
                # Try to convert index to datetime
                idx = pd.to_datetime(first_df.index, errors='coerce')
                if idx.notna().any():
                    min_date = idx.min().date()
                    max_date = idx.max().date()
                    return "contract_dict", sorted(keys), min_date, max_date
        except:
            pass
        return "contract_dict", sorted(keys), None, None
        
    # If it's a date dictionary, calculate overall time range
    try:
        dates = pd.to_datetime(keys)
        min_date = dates.min().date()
        max_date = dates.max().date()
        return "date_dict", [], min_date, max_date
    except:
        return "unknown", [], None, None


def load_local_data_processed(file_path, contract_key=None):
    """Load and process local data"""
    try:
        data_dict = load_raw_file(file_path)
        if data_dict is None:
            return None, "Unable to read file"
            
        keys = list(data_dict.keys())
        if not keys:
            return None, "File content is empty"
            
        first_key = keys[0]
        
        # Determine structure
        is_contract_key = False
        try:
            pd.to_datetime(first_key)
        except:
            is_contract_key = True
        if isinstance(first_key, (datetime, pd.Timestamp)):
            is_contract_key = False

        # Case 1: Contract dictionary
        if is_contract_key:
            target_key = contract_key
            if not target_key or target_key not in data_dict:
                # Default fallback logic
                for preferred in ['TL.CFE', 'T.CFE', 'TF.CFE']:
                    if preferred in data_dict:
                        target_key = preferred
                        break
                if not target_key:
                    target_key = keys[0]
            
            df = data_dict[target_key].copy()
            # Standardize column names
            df.columns = [c.lower() for c in df.columns]
            df.index.name = 'datetime'
            
            if 'last' not in df.columns and 'close' in df.columns:
                df['last'] = df['close']
            
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index, errors='coerce')
            
            # Ensure required columns exist
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col not in df.columns:
                    if 'last' in df.columns: df[col] = df['last']
                    elif 'close' in df.columns: df[col] = df['close']
            
            return df, None

        # Case 2: Date dictionary (original logic)
        all_data = []
        dates = sorted(list(data_dict.keys()))
        for date in dates:
            df = data_dict[date]
            df.columns = [c.lower() for c in df.columns]
            
            if 'last' not in df.columns and 'close' in df.columns:
                df['last'] = df['close']
                
            if 'last' not in df.columns:
                continue
            all_data.append(df)
        
        if not all_data:
            return None, "File content is empty or format is incorrect"
            
        merged_df = pd.concat(all_data, axis=0)
        
        if not isinstance(merged_df.index, pd.DatetimeIndex):
            merged_df.index = pd.to_datetime(merged_df.index, errors='coerce')
            merged_df = merged_df[merged_df.index.notna()]
            
        merged_df = merged_df.sort_index()
        
        for col in ['last', 'volume']:
            if col in merged_df.columns:
                merged_df[col] = pd.to_numeric(merged_df[col], errors='coerce')
        
        merged_df = merged_df.dropna(subset=['last'])
        
        merged_df['close'] = merged_df['last']
        if 'open' not in merged_df.columns: merged_df['open'] = merged_df['last']
        if 'high' not in merged_df.columns: merged_df['high'] = merged_df['last']
        if 'low' not in merged_df.columns: merged_df['low'] = merged_df['last']
        
        return merged_df, None
    except Exception as e:
        return None, f"File read error: {e}"


def get_local_file_path(symbol, timeframe):
    """
    Construct file path based on symbol and timeframe.
    
    Args:
        symbol: Symbol/contract code (e.g., 'TL.CFE')
        timeframe: Timeframe selection (e.g., '1D', '5T', '1H')
    
    Returns:
        Absolute file path to the pkl file
    """
    try:
        if timeframe == '1D':
            # Daily data: use futures-dailyK_con.pkl from input folder
            return os.path.join(DIR_INPUT, 'futures-dailyK_con.pkl')
        else:
            # Intraday data: use symbol.pkl from database/futures folder
            file_name = symbol.split('.')[0]  # Remove extension if any
            return os.path.join(DIR_DATA, 'futures', f'{file_name}.pkl')
    except Exception as e:
        return None


def resample_data(df, rule):
    """Resample data to specified time frequency"""
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, errors='coerce')
        df = df[df.index.notna()]
    
    # Normalize minute alias: pandas deprecates 'T' in favor of 'min'
    if isinstance(rule, str) and 'T' in rule:
        # convert patterns like '1T', '5T' -> '1min', '5min'
        rule = re.sub(r'(?<=\d)T\b', 'min', rule)

    df_resampled = df['close'].resample(rule).ohlc()
    df_resampled['volume'] = df['volume'].resample(rule).sum()
    df_resampled = df_resampled.dropna()
    return df_resampled
