"""
Simple pickle viewer for project data files.

Usage:
  python dataviewer.py file.pkl
  python dataviewer.py file.pkl --key path.to.data
  python dataviewer.py file.pkl --keys  # list all keys
"""

import os
import sys
from pathlib import Path
import pandas as pd
import json
import numpy as np

# Add project path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from settings.paths import DIR_DATA, DIR_INPUT


def preview_object(obj, *, max_rows: int = 20, max_cols: int = 12) -> str:
  if isinstance(obj, pd.DataFrame):
    with pd.option_context(
      'display.max_rows', max_rows,
      'display.max_columns', max_cols,
      'display.width', 200,
    ):
      return obj.to_string()
  if isinstance(obj, pd.Series):
    with pd.option_context('display.max_rows', max_rows, 'display.width', 200):
      return obj.to_string()
  if isinstance(obj, dict):
    keys = list(obj.keys())
    preview_keys = keys[:max_rows]
    suffix = '' if len(keys) <= max_rows else f" ... (+{len(keys) - max_rows} more)"
    return f"dict[{len(keys)}]: {preview_keys}{suffix}"
  return repr(obj)

#%%
if __name__ == "__main__":
    # Example usage when run directly
    # TBond prices demo
    file_path = os.path.join(DIR_INPUT, 'database-px.pkl')
    key = 'IRS'
    dps = '2025-08-01'
    ds = '2025-10-15'
    bond = '2500002.IB'
    data = pd.read_pickle(file_path)
    dp = pd.to_datetime(dps).date()
    d = pd.to_datetime(ds).date()
    bond_data = data[key]#.loc[dp:d]
    af = bond_data[bond].dropna()


    # CBond reference demo
    file_path = os.path.join(DIR_INPUT, 'IRS-pxspds.pkl')
    data = pd.read_pickle(file_path)
    key = 'BondCurve'
    bond_data = data[key]


    # TBond cvpx demo
    file_path = os.path.join(DIR_DATA, 'CBond-px.pkl')
    key = 'Volume'
    date_str = '2025-08-01'
    bond = ['180206.IB','2202002.IB']
    data = pd.read_pickle(file_path)
    d = pd.to_datetime(date_str).date()
    bond_data = data[key]
    af = bond_data[bond]#.dropna()

    file_path = os.path.join(DIR_DATA, "pool", "CBondPool20260416.pkl")
    data = pd.read_pickle(file_path)
    bond_data = data.loc[bond].dropna()

    # CBond bondpool demo
    file_path = os.path.join(DIR_INPUT, 'futures-dailyK_con.pkl')
    key = 'TL.CFE'
    data = pd.read_pickle(file_path)
    bond_data = data[key].dropna()
    
    file_path = os.path.join(DIR_DATA, "futures", "JM2605.pkl")
    bond = '092302002.IB'
    data = pd.read_pickle(file_path)
    bond_data = data.loc[bond].dropna()

    print(preview_object(bond_data))
