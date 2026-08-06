# -*- coding: utf-8 -*-
"""Point-in-time OTR/OFR universe builder for the BondNewIssue event strategy.

Phase 2 of docs/dev/tbondcurve-30y-otr-ofr-plan.md. Builds and persists, per
(asset_class, tenor_bucket), the daily OTR / 1st-OFR / 2nd-OFR identities used
by the BondNewIssue event strategy. This is deliberately separate from
``RefBondSelector`` (curves/calibration/selector.py): that selector buckets by
*remaining* maturity and picks the most-liquid/off-the-run bond for affine
curve calibration, whereas OTR/OFR identity here is ranked by *issuance
recency* within a fixed *original*-tenor bucket, independent of curve fitting.

Persists to ``{bond_type}-newissue.pkl`` under DIR_INPUT as
``{tenor_bucket: DataFrame}``, one row per processed date, with columns:
    asset_class, issuer_class, tenor_bucket,
    otr_id, ofr1_id, ofr2_id, otr_start_date, event_age_days, roll_flag,
    dv01_ratio_ofr1_otr, dv01_ratio_ofr2_otr,
    otr_turnover, ofr1_turnover, quote_ok_otr, quote_ok_ofr1, rejection_reason,
    ytm_otr, ytm_ofr1, ytm_ofr2, spread, instrument_id
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from settings.paths import DIR_INPUT
from settings.general import DateConfig
from settings.fixed_income import NewIssueConfig
from curves.utils.loader import loadInstrumentDefinition
from curves.utils.retrieve import retrieveEnvRT
from curves.utils.file import loadPKL, updatePKL
from curves.calibration.selector import filter_bonds_by_type, _as_scalar_bond_id

from utils.log_window import get_logger
logger = get_logger(__name__)


UNIVERSE_ROW_COLUMNS = [
    'asset_class', 'issuer_class', 'tenor_bucket',
    'otr_id', 'ofr1_id', 'ofr2_id', 'otr_start_date', 'event_age_days', 'roll_flag',
    'dv01_ratio_ofr1_otr', 'dv01_ratio_ofr2_otr',
    'otr_turnover', 'ofr1_turnover', 'quote_ok_otr', 'quote_ok_ofr1', 'rejection_reason',
    'ytm_otr', 'ytm_ofr1', 'ytm_ofr2', 'spread', 'instrument_id',
]


def instrument_id(tenor_bucket: str, otr_id: Any, ofr1_id: Any) -> str:
    """Canonical BondNewIssue instrument label: ``<tenor_bucket>:<otr_id>|<ofr1_id>``."""
    return f'{tenor_bucket}:{otr_id}|{ofr1_id}'


def _empty_row(asset_class: str, tenor_bucket: str, rejection_reason: str) -> Dict[str, Any]:
    row = {c: np.nan for c in UNIVERSE_ROW_COLUMNS}
    row.update({
        'asset_class': asset_class,
        'issuer_class': NewIssueConfig.issuer_class(asset_class),
        'tenor_bucket': tenor_bucket,
        'roll_flag': False,
        'quote_ok_otr': False,
        'quote_ok_ofr1': False,
        'rejection_reason': rejection_reason,
    })
    return row


def _bucket_candidates(df_def: pd.DataFrame, asset_class: str, tenor_bucket: str, calc_date: date) -> pd.Index:
    """Bonds of `asset_class`, outstanding on `calc_date`, whose *original* term
    (not remaining term) falls in NewIssueConfig.TENOR_BUCKETS[tenor_bucket]."""
    min_term, max_term = NewIssueConfig.TENOR_BUCKETS[tenor_bucket]
    type_filtered = filter_bonds_by_type(df_def['证券全称'], asset_class)
    bonds = df_def.index.intersection(type_filtered)

    start = pd.to_datetime(df_def.loc[bonds, '起息日期'])
    maturity = pd.to_datetime(df_def.loc[bonds, '到期日期'])
    calc_ts = pd.Timestamp(calc_date)
    outstanding_mask = (start < calc_ts) & (maturity > calc_ts)

    orig_term = pd.to_numeric(df_def.loc[bonds, '期限'], errors='coerce')
    term_mask = (orig_term >= min_term) & (orig_term <= max_term)

    return bonds[outstanding_mask.to_numpy() & term_mask.to_numpy()]


def _turnover_ratio(df_def: pd.DataFrame, bond_id: Any) -> float:
    """Same formula as RefBondSelector._prepare_bond_data's single-date branch."""
    try:
        balance = pd.to_numeric(df_def.loc[bond_id, '债券余额:亿'], errors='coerce')
        volume = pd.to_numeric(df_def.loc[bond_id, '成交量:万元'], errors='coerce')
        if pd.isna(balance) or balance == 0 or pd.isna(volume):
            return np.nan
        return float(volume / balance / 1e4)
    except (KeyError, TypeError):
        return np.nan


def _quote_ok(df_def: pd.DataFrame, bond_rt: Optional[pd.DataFrame], bond_id: Any) -> bool:
    """A bond has an executable quote if it is in BondRT with a real (non-fallback) bid/ofr."""
    if bond_rt is None or bond_id not in bond_rt.index:
        return False
    row = bond_rt.loc[bond_id]
    bid = pd.to_numeric(row.get('买价收益率'), errors='coerce')
    ofr = pd.to_numeric(row.get('卖价收益率'), errors='coerce')
    if pd.isna(bid) or pd.isna(ofr):
        return False
    fallback = pd.to_numeric(df_def.loc[bond_id].get('估价收益率:%(中债)'), errors='coerce') if bond_id in df_def.index else np.nan
    eps = 1e-6
    if pd.notna(fallback) and (abs(bid - fallback) < eps or abs(ofr - fallback) < eps):
        return False
    return True


def _mid_yield(df_def: pd.DataFrame, bond_rt: Optional[pd.DataFrame], bond_id: Any) -> float:
    """Bid/ofr mid from BondRT (already CNBD-fallback-normalized by retrieveEnvRT);
    falls back to the static CNBD valuation yield if the bond has no BondRT row."""
    if bond_id not in df_def.index or pd.isna(bond_id):
        return np.nan
    fallback = pd.to_numeric(df_def.loc[bond_id].get('估价收益率:%(中债)'), errors='coerce')
    if bond_rt is not None and bond_id in bond_rt.index:
        row = bond_rt.loc[bond_id]
        bid = pd.to_numeric(row.get('买价收益率'), errors='coerce')
        ofr = pd.to_numeric(row.get('卖价收益率'), errors='coerce')
        if pd.notna(bid) and pd.notna(ofr):
            return float((bid + ofr) / 2.0)
    return float(fallback) if pd.notna(fallback) else np.nan


def _dv01_proxy(df_def: pd.DataFrame, bond_id: Any) -> float:
    """Modified-duration * dirty-price proxy for DV01 (per 100 face); ratio of
    two proxies matches the DV01 ratio in the plan's hedge-ratio formula."""
    if bond_id not in df_def.index:
        return np.nan
    mdur = pd.to_numeric(df_def.loc[bond_id].get('修正久期'), errors='coerce')
    price = pd.to_numeric(df_def.loc[bond_id].get('收盘价:元（全价）'), errors='coerce')
    if pd.isna(price) or price <= 0:
        price = 100.0
    if pd.isna(mdur):
        return np.nan
    return float(mdur) * float(price) / 100.0


def _select_otr_ofr_for_date(
    df_def: pd.DataFrame,
    bond_rt: Optional[pd.DataFrame],
    asset_class: str,
    tenor_bucket: str,
    calc_date: date,
    prev_otr_id: Any = None,
) -> Dict[str, Any]:
    """Compute one date's OTR/1st-OFR/2nd-OFR row for a single (asset_class, tenor_bucket)."""
    candidates = _bucket_candidates(df_def, asset_class, tenor_bucket, calc_date)
    if len(candidates) == 0:
        return _empty_row(asset_class, tenor_bucket, 'no_bonds_in_bucket')
    if len(candidates) < 2:
        return _empty_row(asset_class, tenor_bucket, 'insufficient_bucket_bonds')

    # Rank by issuance recency (newest first): OTR is the most recently issued
    # bond still outstanding in the bucket; 1st/2nd-OFR are the next most recent.
    start_dates = pd.to_datetime(df_def.loc[candidates, '起息日期'])
    ranked = start_dates.sort_values(ascending=False).index
    otr_id = _as_scalar_bond_id(ranked[0])
    ofr1_id = _as_scalar_bond_id(ranked[1])
    ofr2_id = _as_scalar_bond_id(ranked[2]) if len(ranked) > 2 else np.nan

    otr_start = pd.Timestamp(start_dates.loc[otr_id])
    event_age_days = int((pd.Timestamp(calc_date) - otr_start).days)
    roll_flag = bool(prev_otr_id is not None and pd.notna(prev_otr_id) and prev_otr_id != otr_id)

    row = {
        'asset_class': asset_class,
        'issuer_class': NewIssueConfig.issuer_class(asset_class),
        'tenor_bucket': tenor_bucket,
        'otr_id': otr_id,
        'ofr1_id': ofr1_id,
        'ofr2_id': ofr2_id,
        'otr_start_date': otr_start,
        'event_age_days': event_age_days,
        'roll_flag': roll_flag,
        'dv01_ratio_ofr1_otr': _safe_ratio(_dv01_proxy(df_def, ofr1_id), _dv01_proxy(df_def, otr_id)),
        'dv01_ratio_ofr2_otr': _safe_ratio(_dv01_proxy(df_def, ofr2_id), _dv01_proxy(df_def, otr_id)),
        'otr_turnover': _turnover_ratio(df_def, otr_id),
        'ofr1_turnover': _turnover_ratio(df_def, ofr1_id),
        'quote_ok_otr': _quote_ok(df_def, bond_rt, otr_id),
        'quote_ok_ofr1': _quote_ok(df_def, bond_rt, ofr1_id),
        'rejection_reason': None,
    }
    ytm_otr = _mid_yield(df_def, bond_rt, otr_id)
    ytm_ofr1 = _mid_yield(df_def, bond_rt, ofr1_id)
    ytm_ofr2 = _mid_yield(df_def, bond_rt, ofr2_id)
    row.update({
        'ytm_otr': ytm_otr,
        'ytm_ofr1': ytm_ofr1,
        'ytm_ofr2': ytm_ofr2,
        # Canonical BondNewIssue spread: ytm_1ofr - ytm_otr (see plan doc).
        'spread': (ytm_ofr1 - ytm_otr) if (pd.notna(ytm_ofr1) and pd.notna(ytm_otr)) else np.nan,
        'instrument_id': instrument_id(tenor_bucket, otr_id, ofr1_id),
    })
    return row


def _safe_ratio(numerator: float, denominator: float) -> float:
    if pd.isna(numerator) or pd.isna(denominator) or denominator == 0:
        return np.nan
    return float(numerator / denominator)


class OTROFRUniverseBuilder:
    """Builds and persists the point-in-time OTR/OFR universe for BondNewIssue."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def refresh_new_issue_universe(
        self,
        asset_class: str,
        tenor_buckets: Optional[List[str]] = None,
        daily: bool = True,
        update: bool = True,
    ) -> Dict[str, pd.DataFrame]:
        """Refresh the OTR/OFR universe for one asset_class across tenor buckets.

        Parameters
        ----------
        asset_class: 'TBond' or 'CBond'.
        tenor_buckets: subset of NewIssueConfig.TENOR_BUCKETS keys; defaults to
            all buckets active for `asset_class` (NewIssueConfig.ACTIVE_BUCKETS).
        daily: when True (production mode), computes only today's row
            (DateConfig 'dp' — the last completed CN business day) and fetches
            live BondRT quotes via retrieveEnvRT.
        update: when True, merges the new row(s) into the persisted history;
            when False, only returns the newly computed row(s).
        """
        if tenor_buckets is None:
            tenor_buckets = NewIssueConfig.active_tenor_buckets(asset_class)
        else:
            active = set(NewIssueConfig.active_tenor_buckets(asset_class))
            tenor_buckets = [tb for tb in tenor_buckets if tb in active]
        if not tenor_buckets:
            logger.warning("No active BondNewIssue tenor buckets for %s.", asset_class)
            return {}

        env = loadInstrumentDefinition(asset_class)
        if daily:
            env = retrieveEnvRT(env, asset_class)
        df_def = env['Def']
        bond_rt = env.get('BondRT')

        out_file = os.path.join(DIR_INPUT, f'{asset_class}-newissue.pkl')
        existing_data = loadPKL(out_file)

        # Historical backfill (daily=False) is not yet implemented — this
        # builder currently only appends the latest completed business day.
        dates_to_process = [DateConfig.get_date_mappings()['dp'].date()]

        result: Dict[str, pd.DataFrame] = {}
        for tenor_bucket in tenor_buckets:
            existing_df = existing_data.get(tenor_bucket)
            if not isinstance(existing_df, pd.DataFrame):
                existing_df = pd.DataFrame(columns=UNIVERSE_ROW_COLUMNS, index=pd.DatetimeIndex([], name='date'))

            new_rows: Dict[Any, Dict[str, Any]] = {}
            for current_date in dates_to_process:
                prev_dates = existing_df.index[existing_df.index < pd.Timestamp(current_date)]
                prev_otr_id = existing_df.loc[prev_dates[-1], 'otr_id'] if len(prev_dates) > 0 else None
                row = _select_otr_ofr_for_date(df_def, bond_rt, asset_class, tenor_bucket, current_date, prev_otr_id)
                new_rows[pd.Timestamp(current_date)] = row

            new_df = pd.DataFrame(new_rows).T
            new_df.index.name = 'date'
            if len(existing_df) > 0:
                combined = pd.concat([existing_df, new_df])
                combined = combined[~combined.index.duplicated(keep='last')].sort_index()
            else:
                combined = new_df.sort_index()
            result[tenor_bucket] = combined

            if self.verbose:
                logger.info(
                    "BondNewIssue universe %s/%s: OTR=%s rejection=%s",
                    asset_class, tenor_bucket,
                    new_df.iloc[-1]['otr_id'] if len(new_df) else None,
                    new_df.iloc[-1]['rejection_reason'] if len(new_df) else None,
                )

        if update:
            updatePKL(result, out_file)

        return result


def refresh_new_issue_universe(
    asset_class: str,
    tenor_buckets: Optional[List[str]] = None,
    daily: bool = True,
    update: bool = True,
    verbose: bool = False,
) -> Dict[str, pd.DataFrame]:
    """Module-level convenience wrapper around OTROFRUniverseBuilder."""
    builder = OTROFRUniverseBuilder(verbose=verbose)
    return builder.refresh_new_issue_universe(asset_class, tenor_buckets=tenor_buckets, daily=daily, update=update)


def _rank_otr_ofr(df_def: pd.DataFrame, asset_class: str, tenor_bucket: str, calc_date: date) -> Optional[Dict[str, Any]]:
    """Point-in-time OTR/1st-OFR/2nd-OFR identity only (no live quotes)."""
    candidates = _bucket_candidates(df_def, asset_class, tenor_bucket, calc_date)
    if len(candidates) < 2:
        return None
    start_dates = pd.to_datetime(df_def.loc[candidates, '起息日期'])
    ranked = start_dates.sort_values(ascending=False).index
    otr_id = _as_scalar_bond_id(ranked[0])
    ofr1_id = _as_scalar_bond_id(ranked[1])
    ofr2_id = _as_scalar_bond_id(ranked[2]) if len(ranked) > 2 else np.nan
    return {'otr_id': otr_id, 'ofr1_id': ofr1_id, 'ofr2_id': ofr2_id, 'otr_start': pd.Timestamp(start_dates.loc[otr_id])}


def backfill_new_issue_universe(
    asset_class: str,
    tenor_buckets: Optional[List[str]] = None,
    start: Optional[pd.Timestamp] = None,
    end: Optional[pd.Timestamp] = None,
    update: bool = True,
) -> Dict[str, pd.DataFrame]:
    """Reconstruct past OTR/OFR selection + spread history from the historical
    per-bond close-yield panel (``{asset_class}-px.pkl`` under DIR_DATA).

    Unlike the live daily builder (which uses BondRT bid/offer and can only
    append "today"), this uses close-yield history to backfill many past
    dates at once. Quote-quality/turnover fields are not available
    historically and are left NaN/False; these rows are for spread-history
    and statistics only, never for live RISK_APPROVED gating.
    """
    from settings.paths import DIR_DATA
    from curves.utils.loader import _read_pickle_compat

    if tenor_buckets is None:
        tenor_buckets = NewIssueConfig.active_tenor_buckets(asset_class)
    else:
        active = set(NewIssueConfig.active_tenor_buckets(asset_class))
        tenor_buckets = [tb for tb in tenor_buckets if tb in active]
    if not tenor_buckets:
        return {}

    env = loadInstrumentDefinition(asset_class)
    df_def = env['Def']

    px_path = os.path.join(str(DIR_DATA), f'{asset_class}-px.pkl')
    px = _read_pickle_compat(px_path, f'{asset_class}-px.pkl')
    close = px['Close']
    close.index = pd.to_datetime(close.index)

    dates = close.index
    if start is not None:
        dates = dates[dates >= pd.Timestamp(start)]
    if end is not None:
        dates = dates[dates <= pd.Timestamp(end)]
    dates = dates.sort_values()

    out_file = os.path.join(DIR_INPUT, f'{asset_class}-newissue.pkl')
    existing_data = loadPKL(out_file)

    result: Dict[str, pd.DataFrame] = {}
    for tenor_bucket in tenor_buckets:
        rows: Dict[pd.Timestamp, Dict[str, Any]] = {}
        prev_otr_id = None
        for calc_date in dates:
            ident = _rank_otr_ofr(df_def, asset_class, tenor_bucket, calc_date.date())
            if ident is None:
                continue
            otr_id, ofr1_id, ofr2_id = ident['otr_id'], ident['ofr1_id'], ident['ofr2_id']
            ytm_otr = float(close.loc[calc_date, otr_id]) if otr_id in close.columns else np.nan
            ytm_ofr1 = float(close.loc[calc_date, ofr1_id]) if ofr1_id in close.columns else np.nan
            ytm_ofr2 = float(close.loc[calc_date, ofr2_id]) if (pd.notna(ofr2_id) and ofr2_id in close.columns) else np.nan
            if pd.isna(ytm_otr) or pd.isna(ytm_ofr1):
                continue
            event_age_days = int((calc_date - ident['otr_start']).days)
            roll_flag = bool(prev_otr_id is not None and prev_otr_id != otr_id)
            rows[calc_date] = {
                'asset_class': asset_class,
                'issuer_class': NewIssueConfig.issuer_class(asset_class),
                'tenor_bucket': tenor_bucket,
                'otr_id': otr_id, 'ofr1_id': ofr1_id, 'ofr2_id': ofr2_id,
                'otr_start_date': ident['otr_start'],
                'event_age_days': event_age_days,
                'roll_flag': roll_flag,
                'dv01_ratio_ofr1_otr': _safe_ratio(_dv01_proxy(df_def, ofr1_id), _dv01_proxy(df_def, otr_id)),
                'dv01_ratio_ofr2_otr': _safe_ratio(_dv01_proxy(df_def, ofr2_id), _dv01_proxy(df_def, otr_id)),
                'otr_turnover': np.nan, 'ofr1_turnover': np.nan,
                'quote_ok_otr': False, 'quote_ok_ofr1': False,
                'rejection_reason': 'backfilled_close_yield_only',
                'ytm_otr': ytm_otr, 'ytm_ofr1': ytm_ofr1, 'ytm_ofr2': ytm_ofr2,
                'spread': ytm_ofr1 - ytm_otr,
                'instrument_id': instrument_id(tenor_bucket, otr_id, ofr1_id),
            }
            prev_otr_id = otr_id

        if not rows:
            continue
        new_df = pd.DataFrame(rows).T
        new_df.index.name = 'date'

        existing_df = existing_data.get(tenor_bucket)
        # Backfilled rows never override a live (BondRT-quoted) row for the same date.
        if isinstance(existing_df, pd.DataFrame) and len(existing_df) > 0:
            combined = pd.concat([new_df, existing_df])
            combined = combined[~combined.index.duplicated(keep='last')].sort_index()
        else:
            combined = new_df.sort_index()
        result[tenor_bucket] = combined

    if update and result:
        merged = dict(existing_data) if isinstance(existing_data, dict) else {}
        merged.update(result)
        updatePKL(merged, out_file)

    return result


def main(asset_class: str = 'TBond'):
    for ac in (['TBond', 'CBond'] if asset_class == 'all' else [asset_class]):
        try:
            refresh_new_issue_universe(ac, daily=True, update=True, verbose=True)
        except Exception as e:
            logger.error("Error refreshing BondNewIssue universe for %s: %s", ac, e)
            raise


if __name__ == '__main__':
    main()
