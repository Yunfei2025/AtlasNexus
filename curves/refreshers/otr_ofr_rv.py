# -*- coding: utf-8 -*-
"""Mature-pair relative value (``otr_ofr_rv``) under existing ``TBondCurve`` /
``CBondCurve`` (see docs/dev/tbondcurve-30y-otr-ofr-plan.md).

Restricted to the turnover-ranked OFR ladder only (OFR1..OFR{depth}) — this
module never touches NIB or OTR, so it cannot overlap with the BondNewIssue
rotation-ladder event strategy by construction (see the plan's "Overlap
Avoidance and Portfolio Netting"). Reuses the same point-in-time OFR-ladder
history already captured by ``curves.calibration.otr_ofr_universe``
(``{asset_class}-newissue.pkl``). Every historical (ofr1_id, ofrk_id) episode
with enough own history is exposed as an extra pair-instrument row/column
merged into the existing ``{asset_class}-spds.pkl['BondCurve']`` structure,
so it shows up in the same TBondCurve/CBondCurve dropdown as ordinary
bond-vs-curve instruments (distinguished by ``|`` in the ID:
``<ofrk_id>|<ofr1_id>``).

Each episode's mean/vol/halflife/stationary is computed from its own spread
history only — never spliced across a rank-ladder promotion (see plan's
cold-start policy and turnover-rank persistence rule).
"""
from __future__ import annotations

import os
from typing import Dict

import numpy as np
import pandas as pd

from settings.paths import DIR_INPUT
from settings.fixed_income import NewIssueConfig
from curves.calibration.stat import OU_calibrate
from curves.utils.loader import loadInstrumentDefinition
from curves.utils.file import loadPKL, updatePKL

from utils.log_window import get_logger
logger = get_logger(__name__)

MIN_EPISODE_ROWS = 20  # matches OU_calibrate's own stationarity-test floor


def _episode_rows_to_pair_frames(df: pd.DataFrame) -> Dict[str, Dict[str, pd.Series]]:
    """Group a per-bucket universe history into OFR-ladder pair episodes.

    For each rung k = 2..OFR_LADDER_DEPTH, groups rows by the (ofr1_id, ofrk_id)
    identity pair (an "episode" persists while both rungs' confirmed identity
    stays the same) and exposes ``ofr{k} - ofr1`` as the mature-RV spread.
    """
    out: Dict[str, Dict[str, pd.Series]] = {}
    if df is None or df.empty or 'ofr1_id' not in df.columns:
        return out
    depth = NewIssueConfig.OFR_LADDER_DEPTH
    for k in range(2, depth + 1):
        id_col, ytm_col = f'ofr{k}_id', f'ytm_ofr{k}'
        if id_col not in df.columns or ytm_col not in df.columns:
            continue
        pair_key = df['ofr1_id'].astype(str) + '|' + df[id_col].astype(str)
        for _pair, group in df.groupby(pair_key):
            g = group.sort_index()
            ofr1 = pd.to_numeric(g['ytm_ofr1'], errors='coerce')
            ofrk = pd.to_numeric(g[ytm_col], errors='coerce')
            spread = (ofrk - ofr1).dropna()
            if len(spread) < MIN_EPISODE_ROWS:
                continue
            ofr1_id = str(g['ofr1_id'].iloc[-1])
            ofrk_id = str(g[id_col].iloc[-1])
            if pd.isna(ofr1_id) or ofr1_id in ('nan', '') or pd.isna(ofrk_id) or ofrk_id in ('nan', ''):
                continue
            pair_id = f'{ofrk_id}|{ofr1_id}'
            out[pair_id] = {
                'ofr1_id': ofr1_id, 'ofrk_id': ofrk_id,
                'CloseYield': ofrk.reindex(spread.index),
                'CurveYield': ofr1.reindex(spread.index),
                'Spread': spread,
            }
    return out


def build_otr_ofr_rv_rows(asset_class: str) -> Dict[str, Dict[str, pd.Series]]:
    """Collect mature OFR-ladder pair rows across all active tenor buckets for one asset_class."""
    out_file = os.path.join(DIR_INPUT, f'{asset_class}-newissue.pkl')
    data = loadPKL(out_file)
    merged: Dict[str, Dict[str, pd.Series]] = {}
    for tenor_bucket in NewIssueConfig.active_tenor_buckets(asset_class):
        df = data.get(tenor_bucket)
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        merged.update(_episode_rows_to_pair_frames(df))
    return merged



def refresh_otr_ofr_rv_spreads(asset_class: str, update: bool = True) -> Dict[str, pd.DataFrame]:
    """Merge mature OFR-ladder pair rows into ``{asset_class}-spds.pkl['BondCurve']``.

    Any previously-merged pair rows (index containing ``|``) are dropped and
    rebuilt fresh each call so stale/closed episodes do not linger.
    """
    pairs = build_otr_ofr_rv_rows(asset_class)

    spds_file = os.path.join(DIR_INPUT, f'{asset_class}-spds.pkl')
    spds = loadPKL(spds_file)
    bond_curve = spds.get('BondCurve') if isinstance(spds, dict) else None
    if not isinstance(bond_curve, dict):
        logger.warning("%s missing BondCurve; skipping otr_ofr_rv merge for %s.", spds_file, asset_class)
        return {}

    stat_info = bond_curve.get('StatInfo')
    close_yield = bond_curve.get('CloseYield')
    curve_yield = bond_curve.get('CurveYield')
    spread = bond_curve.get('Spread')
    if not isinstance(stat_info, pd.DataFrame):
        stat_info = pd.DataFrame()
    if not isinstance(close_yield, pd.DataFrame):
        close_yield = pd.DataFrame()
    if not isinstance(curve_yield, pd.DataFrame):
        curve_yield = pd.DataFrame()
    if not isinstance(spread, pd.DataFrame):
        spread = pd.DataFrame()

    # Drop stale pair rows/columns from a previous merge before rebuilding.
    stat_info = stat_info.loc[[i for i in stat_info.index if '|' not in str(i)]] if not stat_info.empty else stat_info
    close_yield = close_yield.loc[:, [c for c in close_yield.columns if '|' not in str(c)]] if not close_yield.empty else close_yield
    curve_yield = curve_yield.loc[:, [c for c in curve_yield.columns if '|' not in str(c)]] if not curve_yield.empty else curve_yield
    spread = spread.loc[:, [c for c in spread.columns if '|' not in str(c)]] if not spread.empty else spread

    if not pairs:
        bond_curve['StatInfo'] = stat_info
        bond_curve['CloseYield'] = close_yield
        bond_curve['CurveYield'] = curve_yield
        bond_curve['Spread'] = spread
        spds['BondCurve'] = bond_curve
        if update:
            updatePKL(spds, spds_file, rewrite=True)
        return bond_curve

    env = loadInstrumentDefinition(asset_class)
    df_def = env['Def']

    new_close_cols, new_curve_cols, new_spread_cols = {}, {}, {}
    new_stat_rows = {}
    for pair_id, series in pairs.items():
        new_close_cols[pair_id] = series['CloseYield']
        new_curve_cols[pair_id] = series['CurveYield']
        new_spread_cols[pair_id] = series['Spread']

        stat = OU_calibrate(pd.DataFrame({pair_id: series['Spread']}))
        row = stat.loc[pair_id].to_dict() if pair_id in stat.index else {}
        ofr1_id = series['ofr1_id']
        ttm = np.nan
        if ofr1_id in df_def.index:
            ttm = pd.to_numeric(df_def.loc[ofr1_id].get('剩余期限'), errors='coerce')
        row['ttm'] = float(ttm) if pd.notna(ttm) else np.nan
        row['vol_ratio'] = np.nan
        row['close'] = float(series['CurveYield'].iloc[-1] + row.get('mean', np.nan)) if pd.notna(row.get('mean', np.nan)) else np.nan
        new_stat_rows[pair_id] = row

    stat_info = pd.concat([stat_info, pd.DataFrame(new_stat_rows).T]) if not stat_info.empty else pd.DataFrame(new_stat_rows).T
    stat_info.index.name = 'ID'
    close_yield = close_yield.combine_first(pd.DataFrame(new_close_cols)) if not close_yield.empty else pd.DataFrame(new_close_cols)
    curve_yield = curve_yield.combine_first(pd.DataFrame(new_curve_cols)) if not curve_yield.empty else pd.DataFrame(new_curve_cols)
    spread = spread.combine_first(pd.DataFrame(new_spread_cols)) if not spread.empty else pd.DataFrame(new_spread_cols)

    bond_curve['StatInfo'] = stat_info
    bond_curve['CloseYield'] = close_yield
    bond_curve['CurveYield'] = curve_yield
    bond_curve['Spread'] = spread
    spds['BondCurve'] = bond_curve

    if update:
        updatePKL(spds, spds_file, rewrite=True)

    return bond_curve


def refresh_otr_ofr_rv_realtime(asset_class: str, update: bool = True) -> pd.DataFrame:
    """Merge mature OFR-ladder pair rows into ``{asset_class}-spdsrt.pkl['BondCurve']``.

    This is the file the legacy "Spread Analysis" bar chart
    (web/core/scripts.py::refresh) reads directly, so pairs must be merged
    here too (in addition to ``{asset_class}-spds.pkl``) to appear there.
    """
    pairs = build_otr_ofr_rv_rows(asset_class)

    rt_file = os.path.join(DIR_INPUT, f'{asset_class}-spdsrt.pkl')
    rt = loadPKL(rt_file)
    df_bc = rt.get('BondCurve') if isinstance(rt, dict) else None
    if not isinstance(df_bc, pd.DataFrame):
        logger.warning("%s missing BondCurve; skipping otr_ofr_rv realtime merge for %s.", rt_file, asset_class)
        return pd.DataFrame()

    df_bc = df_bc.loc[[i for i in df_bc.index if '|' not in str(i)]] if not df_bc.empty else df_bc
    if not pairs:
        rt['BondCurve'] = df_bc
        if update:
            updatePKL(rt, rt_file, rewrite=True)
        return df_bc

    env = loadInstrumentDefinition(asset_class)
    df_def = env['Def']

    rows = {}
    for pair_id, series in pairs.items():
        sp = series['Spread']
        stat = OU_calibrate(pd.DataFrame({pair_id: sp}))
        row = stat.loc[pair_id].to_dict() if pair_id in stat.index else {}
        ofr1_id = series['ofr1_id']
        ttm = pd.to_numeric(df_def.loc[ofr1_id].get('剩余期限'), errors='coerce') if ofr1_id in df_def.index else np.nan
        row['ttm'] = float(ttm) if pd.notna(ttm) else np.nan
        row['CloseYield'] = float(series['CloseYield'].iloc[-1])
        row['CurveYield'] = float(series['CurveYield'].iloc[-1])
        row['spread'] = float(sp.iloc[-1])
        mean_v, vol_v = row.get('mean', np.nan), row.get('vol', np.nan)
        row['Zscore'] = float((row['spread'] - mean_v) / vol_v) if pd.notna(mean_v) and pd.notna(vol_v) and vol_v else np.nan
        rows[pair_id] = row

    new_rows = pd.DataFrame(rows).T
    df_bc = pd.concat([df_bc, new_rows]) if not df_bc.empty else new_rows
    df_bc.index.name = 'ID'
    rt['BondCurve'] = df_bc

    if update:
        updatePKL(rt, rt_file, rewrite=True)

    return df_bc


def main():
    for asset_class in ('TBond', 'CBond'):
        try:
            n = len(build_otr_ofr_rv_rows(asset_class))
            refresh_otr_ofr_rv_spreads(asset_class, update=True)
            refresh_otr_ofr_rv_realtime(asset_class, update=True)
            logger.info("otr_ofr_rv merged for %s: %d mature pair(s).", asset_class, n)
        except Exception as e:
            logger.error("Error refreshing otr_ofr_rv for %s: %s", asset_class, e)
            raise


if __name__ == '__main__':
    main()
