# -*- coding: utf-8 -*-
"""Mature-pair relative value (``otr_ofr_rv``) under existing ``TBondCurve`` /
``CBondCurve`` (see docs/dev/tbondcurve-30y-otr-ofr-plan.md).

Restricted to the turnover-ranked OFR ladder only (OFR1..OFR{depth}) — this
module never touches NIB or OTR, so it cannot overlap with the BondNewIssue
rotation-ladder event strategy by construction (see the plan's "Overlap
Avoidance and Portfolio Netting"). Reuses the same point-in-time OFR-ladder
history already captured by ``curves.calibration.otr_ofr_universe``
(``{asset_class}-newissue.pkl``). Every current (ofr1_id, ofrk_id) episode is
exposed as an extra pair-instrument row/column merged into the existing
``{asset_class}-spds.pkl['BondCurve']`` structure, so it shows up in the same
TBondCurve/CBondCurve dropdown as ordinary bond-vs-curve instruments
(distinguished by ``|`` in the ID: ``<ofrk_id>|<ofr1_id>``).

The traded object for each pair is the difference of the two legs' affine-curve
residuals against that pair's own OFR1:

    pair(t) = (y_k(t) - curve_k(t)) - (y_1(t) - curve_1(t))

Differencing residuals rather than raw yields removes the curve slope between
the two maturities (which moves with the curve and does not mean-revert) and
cancels the affine model's common cross-sectional level bias, since both legs
carry it. The series spans the full overlap of the two legs' residual
histories, so it is not limited to the current episode's length.

A prior implementation fell back, for episodes shorter than MIN_EPISODE_ROWS,
to the OFRk bond's own rank history paired against whichever bond was OFR1 on
each date. That series does not depend on the pair's named OFR1, so every pair
sharing a leg-A collapsed onto one identical spread; with ~65% of episodes
below the threshold it was the active path for most rows. It has been removed.
"""
from __future__ import annotations

import os
from typing import Dict, Optional

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

#: Floor (in %) on the z-score's volatility divisor, i.e. 0.3bp. A residual
#: pair is a much tighter series than a single bond's residual, so an
#: unusually quiet estimation window can drive ewm_vol close to zero and turn
#: an economically trivial move into a double-digit z-score. Floor the divisor
#: rather than dropping the row, so the pair stays visible but cannot dominate
#: the ranking on scale alone.
MIN_ZSCORE_VOL = 0.003


def _load_residual_panel(asset_class: str) -> pd.DataFrame:
    """Per-bond affine-curve residual panel (``ytm_act - ytm_quo``, in %).

    The RV object for an OFR{k}-vs-OFR1 pair is the difference of the two
    legs' curve residuals, not the difference of their raw yields:

        pair(t) = (y_k - curve_k) - (y_1 - curve_1)

    Differencing raw yields (the previous behaviour) leaves in the genuine
    curve slope between two different maturities, which moves with the curve
    and does not mean-revert. Differencing residuals removes that slope --
    and also cancels the affine model's cross-sectional level bias, which is
    common to both legs (measured on TBond: a -7bp median residual that
    drifted from -1.9bp in 2023 to -8.7bp in 2026, i.e. far too slow for any
    252-day OU mean to track).
    """
    try:
        px = loadPKL(os.path.join(DIR_INPUT, f'{asset_class}-cvpx.pkl'))
    except Exception as exc:  # pragma: no cover - defensive I/O
        logger.warning("Could not load %s-cvpx.pkl for residual pairs: %s", asset_class, exc)
        return pd.DataFrame()
    act, quo = px.get('ytm_act'), px.get('ytm_quo')
    if not isinstance(act, pd.DataFrame) or not isinstance(quo, pd.DataFrame):
        return pd.DataFrame()
    act = act.apply(pd.to_numeric, errors='coerce')
    quo = quo.apply(pd.to_numeric, errors='coerce').reindex(index=act.index, columns=act.columns)
    return act - quo


def _residual_pair_series(residuals: pd.DataFrame, ofrk_id: str, ofr1_id: str) -> pd.Series:
    """``resid(ofrk) - resid(ofr1)`` on the dates both legs are observed.

    Returns an empty Series when either leg is missing from the panel, so the
    caller can fall back rather than fabricate a one-legged spread.
    """
    if residuals.empty or ofrk_id not in residuals.columns or ofr1_id not in residuals.columns:
        return pd.Series(dtype=float)
    return (residuals[ofrk_id] - residuals[ofr1_id]).dropna()


def _bond_own_rank_history(df: pd.DataFrame, bond_id: str, depth: int) -> pd.DataFrame:
    """This bond's own (yield, paired-OFR1-id, paired-OFR1-yield) history across
    every date it held any rank OFR2..OFR{depth} -- never OFR1 (a different
    economic role: OFR1 is the reference leg every other rung is priced
    against, not itself an RV leg). A bond that was previously OFR1 before
    rolling down the ladder only contributes its OFR2+ dates.
    """
    rows = []
    for j in range(2, depth + 1):
        id_col, ytm_col = f'ofr{j}_id', f'ytm_ofr{j}'
        if id_col not in df.columns or ytm_col not in df.columns:
            continue
        mask = df[id_col].astype(str) == bond_id
        if not mask.any():
            continue
        sub = df.loc[mask, [ytm_col, 'ofr1_id', 'ytm_ofr1']].rename(
            columns={ytm_col: 'ytm_own'}
        )
        rows.append(sub)
    if not rows:
        return pd.DataFrame(columns=['ytm_own', 'ofr1_id', 'ytm_ofr1'])
    combined = pd.concat(rows, axis=0)
    # A bond can hold at most one rank on a given date; keep first occurrence
    # if the ladder ever double-counts (defensive, shouldn't normally happen).
    combined = combined[~combined.index.duplicated(keep='first')].sort_index()
    return combined


def _episode_rows_to_pair_frames(df: pd.DataFrame, residuals: Optional[pd.DataFrame] = None) -> Dict[str, Dict[str, pd.Series]]:
    """Group a per-bucket universe history into OFR-ladder pair episodes.

    For each rung k = 2..OFR_LADDER_DEPTH, groups rows by the (ofr1_id, ofrk_id)
    identity pair (an "episode" persists while both rungs' confirmed identity
    stays the same) and exposes ``ofr{k} - ofr1`` as the mature-RV spread.

    The traded object is the difference of the two legs' affine-curve
    residuals against THIS pair's own OFR1 (see _residual_pair_series), which
    removes the curve slope between the two maturities and cancels the model's
    common level bias. ``CalibrationSpread`` is that residual pair whenever the
    two legs overlap for at least MIN_EPISODE_ROWS observations, else the
    episode's raw-yield spread.
    """
    out: Dict[str, Dict[str, pd.Series]] = {}
    if df is None or df.empty or 'ofr1_id' not in df.columns:
        return out
    if residuals is None:
        residuals = pd.DataFrame()
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
            if spread.empty:
                continue
            ofr1_id = str(g['ofr1_id'].iloc[-1])
            ofrk_id = str(g[id_col].iloc[-1])
            if pd.isna(ofr1_id) or ofr1_id in ('nan', '') or pd.isna(ofrk_id) or ofrk_id in ('nan', ''):
                continue
            # A mature RV pair must contain two distinct instruments.  A
            # repeated identifier creates a synthetic self-spread with zero
            # economic leg difference and must never enter the candidate set.
            if ofrk_id == ofr1_id:
                continue

            # Residual pair against THIS pair's named OFR1, extended over the
            # full overlapping history of the two legs. This replaces the old
            # `_bond_own_rank_history` fallback, which paired the OFRk bond
            # against *whichever* bond happened to be OFR1 on each date: that
            # made the resulting series independent of the pair's own OFR1, so
            # every pair sharing a leg-A collapsed to one identical spread
            # (observed: 33 leg-A bonds spanning 160 pair rows, 0 of which
            # varied across their different OFR1 partners). Because ~65% of
            # episodes are shorter than MIN_EPISODE_ROWS, that fallback was the
            # active path for most rows.
            resid_pair = _residual_pair_series(residuals, ofrk_id, ofr1_id)

            # Calibrate on the residual pair whenever it is long enough; fall
            # back to the episode's own raw-yield spread only when the residual
            # panel cannot cover this pair (missing leg or too little overlap),
            # never to a series built against a different reference bond.
            # `mean`/`vol` must describe the SAME series the live `spread` is
            # measured against, so the display and calibration series always
            # fall back together -- mixing a residual level against a
            # raw-yield mean would silently corrupt the z-score.
            use_residual = len(resid_pair) >= MIN_EPISODE_ROWS
            calibration_spread = resid_pair if use_residual else spread

            display_close = ofrk.reindex(spread.index)
            display_curve = ofr1.reindex(spread.index)
            display_spread = resid_pair if use_residual else spread

            pair_id = f'{ofrk_id}|{ofr1_id}'
            out[pair_id] = {
                'ofr1_id': ofr1_id, 'ofrk_id': ofrk_id,
                'CloseYield': display_close,
                'CurveYield': display_curve,
                'Spread': display_spread,
                'CalibrationSpread': calibration_spread,
            }
    return out


# (asset_class, tenor_bucket) combos EXCLUDED from the TBondCurve/CBondCurve
# mature-RV pair rows this module builds. (TBond, 30Y) moved to the
# New-Issue OTR/OFR Event tab as its own OFR{k}OFR1-CGB30Y stage family
# (curves/refreshers/newissue_spreads.py's _STAGES / _STAGE_SCOPE,
# web/tabs/alpha/data/loaders.py's OFR{k}OFR1 label support) per the
# 2026-09-06 decision -- the OFR ladder gets its own home there rather than
# living alongside ordinary bond-vs-curve spreads under TBondCurve.
_EXCLUDED_BUCKETS = {('TBond', '30Y')}


def build_otr_ofr_rv_rows(asset_class: str) -> Dict[str, Dict[str, pd.Series]]:
    """Collect mature OFR-ladder pair rows across all active tenor buckets for one asset_class."""
    out_file = os.path.join(DIR_INPUT, f'{asset_class}-newissue.pkl')
    data = loadPKL(out_file)
    merged: Dict[str, Dict[str, pd.Series]] = {}
    residuals = _load_residual_panel(asset_class)
    for tenor_bucket in NewIssueConfig.active_tenor_buckets(asset_class):
        if (asset_class, tenor_bucket) in _EXCLUDED_BUCKETS:
            continue
        df = data.get(tenor_bucket)
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        merged.update(_episode_rows_to_pair_frames(df, residuals))
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

        calibration_spread = series.get('CalibrationSpread', series['Spread'])
        stat = OU_calibrate(pd.DataFrame({pair_id: calibration_spread}))
        row = stat.loc[pair_id].to_dict() if pair_id in stat.index else {}
        ofr1_id = series['ofr1_id']
        ttm = np.nan
        if ofr1_id in df_def.index:
            ttm = pd.to_numeric(df_def.loc[ofr1_id].get('剩余期限'), errors='coerce')
        row['ttm'] = float(ttm) if pd.notna(ttm) else np.nan
        # Display label omits the fixed OFR1 reference leg (implied for every
        # row in this ladder); pair_id itself (ofrk_id|ofr1_id) remains the
        # real lookup key everywhere else (StatInfo index, click handler
        # customdata, backtest/portfolio instrument IDs).
        row['label'] = series['ofrk_id']
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
        calibration_spread = series.get('CalibrationSpread', sp)
        stat = OU_calibrate(pd.DataFrame({pair_id: calibration_spread}))
        row = stat.loc[pair_id].to_dict() if pair_id in stat.index else {}
        ofr1_id = series['ofr1_id']
        ttm = pd.to_numeric(df_def.loc[ofr1_id].get('剩余期限'), errors='coerce') if ofr1_id in df_def.index else np.nan
        row['ttm'] = float(ttm) if pd.notna(ttm) else np.nan
        # Display label omits the fixed OFR1 reference leg (implied for every
        # row in this ladder); pair_id itself (ofrk_id|ofr1_id) remains the
        # real lookup key everywhere else (StatInfo index, click handler
        # customdata, backtest/portfolio instrument IDs).
        row['label'] = series['ofrk_id']
        row['CloseYield'] = float(series['CloseYield'].iloc[-1])
        row['CurveYield'] = float(series['CurveYield'].iloc[-1])
        row['spread'] = float(sp.iloc[-1])
        mean_v = row.get('mean', np.nan)
        # Prefer ewm_vol (EWMA(60), matches the backtest engines' entry-signal
        # scale) over the static full-sample 'vol'; see alpha_snapshot.py's
        # BondCurve block for the full rationale.
        vol_v = row.get('ewm_vol', np.nan)
        if not pd.notna(vol_v):
            vol_v = row.get('vol', np.nan)
        if pd.notna(vol_v):
            vol_v = max(float(vol_v), MIN_ZSCORE_VOL)
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
