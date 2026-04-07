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
from settings.general import DateConfig
from settings.paths import DIR_INPUT
from settings.fixed_income import BondConfig, IRSConfig

def swap_dv01(term_years, rate=0.015, freq=4):
    """Approximate swap DV01 using a simple annuity formula."""
    alpha = 1.0 / freq
    n = int(round(term_years * freq))
    v = 1.0 / (1.0 + rate / freq)  # discount per period
    annuity = alpha * (v * (1 - v**n) / (1 - v)) if n > 0 else 0.0
    return annuity

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


def _prepare_instruments(mdur_irs: pd.Series) -> tuple:
    """Load inputs, compute CR metrics, and assemble instrument table.

    Returns
    - instr: DataFrame indexed by instrument code with columns 'CR(3m,bp)', 'CRShort(3m,bp)', 'Mdur'
    - common_short: list of instruments eligible for short leg
    - group_list: instruments excluding common_short (eligible long leg)
    """
    rfr = pd.read_pickle(os.path.join(DIR_INPUT, "database-px.pkl"))['IRS']['FR001.IR'].iloc[-1]

    out = {}
    btype_list = ["TBond", "CBond"] + list(BondConfig.INCLUDE_FILTERS.keys()) + ["IRS"]
    short_list = []

    def _filter_short_codes(codes):
        # Exclude tenors containing '7Y' or '10Y'
        try:
            return [c for c in codes if ('7Y' not in str(c)) and ('10Y' not in str(c))]
        except Exception:
            # If non-iterable or other issues, return empty
            return []

    for btype in btype_list:
        results = pd.read_pickle(os.path.join(DIR_INPUT, f"{btype}-spdsrt.pkl"))
        if btype in ["TBond", "CBond"]:
            spreads = results["BondCurve"]
            new_list = pd.read_pickle(os.path.join(DIR_INPUT, f"{btype}-cvref.pkl"))['RefBond'].iloc[-1][-4:]
            short_list.extend(_filter_short_codes(list(new_list)))
        elif btype == "IRS":
            spreads = results['spreads'].loc[IRSConfig.IRS_LIST]
        else:
            spreads = results
        # Initialize with spreads index to guarantee consistent alignment
        out[btype] = pd.DataFrame(index=spreads.index.copy())
        out[btype]['CR(3m,bp)'] = (spreads['Carry(3m,bp)'] + spreads['Roll(3m,bp)']).reindex(out[btype].index)

        if btype != "IRS":
            env = loadInstrumentDefinition(btype)
            # Align Mdur to the DataFrame index
            out[btype]['Mdur'] = env['Def']['修正久期'].reindex(out[btype].index)
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
            short_list.extend(_filter_short_codes(list(new_list)))
        else:
            # Align IRS Mdur to the DataFrame index
            out[btype]['Mdur'] = mdur_irs.reindex(out[btype].index)
            out[btype]['CRShort(3m,bp)'] = spreads['Carry(3m,bp)'] + spreads['Roll(3m,bp)']
            short_list.extend(_filter_short_codes(list(out[btype].index)))

    # Explicitly keep keys to guarantee a MultiIndex, then drop it for backward compatibility
    instr = pd.concat(out, axis=0, keys=list(out.keys())).dropna()
    instr.index = instr.index.droplevel(0)
    common_short = list(instr.index.intersection(short_list))
    group_list = [b for b in instr.index if b not in common_short]
    return instr, common_short, group_list


def compute_cr_df(instr: pd.DataFrame, group_list: list, common_short: list) -> pd.DataFrame:
    """Vectorized computation of CR pairs into a long DataFrame.

    For long instrument b and short instrument s:
      if Mdur[b] >= Mdur[s]:
          CR = CR[b] + floor(Mdur[b]/Mdur[s]) * CRShort[b]; Ratio = floor(Mdur[b]/Mdur[s])
      else:
          CR = CR[b] + CRShort[b] / floor(Mdur[s]/Mdur[b]); Ratio = 1 / floor(Mdur[s]/Mdur[b])
    """
    if not group_list or not common_short:
        return pd.DataFrame(columns=['Long', 'Short', 'CR', 'Ratio'])

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

    df = pd.DataFrame({
        'Long': longs,
        'Short': shorts,
        'CR': cr_flat,
        'Ratio': ratio_flat,
    })
    return df.sort_values('CR', ascending=False).reset_index(drop=True)


# Build artifacts at import time (preserve prior behavior)
_mdur_irs = _compute_mdur_irs()
_instr, _common_short, _group_list = _prepare_instruments(_mdur_irs)
cr_df = compute_cr_df(_instr, _group_list, _common_short).iloc[:20]
