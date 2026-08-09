# -*- coding: utf-8 -*-
"""Phase 3 (Artifacts) of docs/dev/tbondcurve-30y-otr-ofr-plan.md.

Aggregates the per-asset-class NIB/OTR/OFR-ladder universe artifacts built by
``curves.calibration.otr_ofr_universe`` (``{asset_class}-newissue.pkl``) into
the single dashboard-facing artifact ``BondNewIssue-spds.pkl``, mirroring the
``{Prefix}-spds.pkl`` convention consumed by ``web/tabs/alpha/data/loaders.py``
(``{'BondNewIssue': {'StatInfo': df, 'Spread': df}}``).

BondNewIssue is the front-of-ladder rotation event strategy, modeled as two
stages (see plan's "Canonical Definitions"):

- ``nib_otr``: challenger (NIB) vs incumbent (OTR), only meaningful when the
  existence-of-lag gate confirms a live migration (``lag_exists``).
- ``otr_ofr1``: incumbent (OTR) vs its immediate off-the-run successor (OFR1).

- ``StatInfo``: one row per currently-active (asset_class, tenor_bucket, stage)
  — the live snapshot shown in the Alpha Book dropdown/table.
- ``Spread``: date-indexed, one column per historical (stage, episode)
  instrument id, since each stage's instrument identity rebinds at every rank
  change and has no single continuous column across rolls.

Never fabricates a spread value for a date before an episode's rank was
selected; each episode column is only populated over its own live date range.
"""
from __future__ import annotations

import os
from typing import Dict

import numpy as np
import pandas as pd

from settings.paths import DIR_INPUT
from settings.fixed_income import NewIssueConfig
from curves.calibration.otr_ofr_universe import refresh_new_issue_universe
from curves.utils.file import loadPKL, updatePKL

from utils.log_window import get_logger
logger = get_logger(__name__)

OUT_FILE = 'BondNewIssue-spds.pkl'

# Per-stage column mapping: instrument_id column, spread column, direction.
# Direction convention (see plan): nib_otr bets NIB overtakes OTR (long NIB,
# short OTR); otr_ofr1 bets OTR's premium over OFR1 keeps eroding (long OFR1,
# short OTR) as OTR approaches displacement.
_STAGES = {
    'nib_otr': {
        'instrument_col': 'instrument_id_nib_otr', 'spread_col': 'spread_nib_otr',
        'age_col': 'nib_age_days', 'leg1_col': 'nib_id', 'leg2_col': 'otr_id',
        'dv01_ratio_col': 'dv01_ratio_otr_nib', 'direction': 'BUY',
    },
    'otr_ofr1': {
        'instrument_col': 'instrument_id_otr_ofr1', 'spread_col': 'spread_otr_ofr1',
        'age_col': 'otr_rank_age_days', 'leg1_col': 'otr_id', 'leg2_col': 'ofr1_id',
        'dv01_ratio_col': 'dv01_ratio_ofr1_otr', 'direction': 'SELL',
    },
}

STAT_INFO_COLUMNS = [
    'asset_class', 'issuer_class', 'tenor_bucket', 'stage',
    'nib_id', 'otr_id', 'ofr1_id', 'ofr2_id', 'event_age_days',
    'lag_exists', 'lag_gap', 'otr_roll_flag', 'dv01_ratio',
    'quote_ok_nib', 'quote_ok_otr', 'quote_ok_ofr1', 'rejection_reason',
    'spread', 'mean', 'vol',
    'style', 'direction', 'data_ready',
]


def _asset_universe(asset_class: str, refresh: bool, daily: bool) -> Dict[str, pd.DataFrame]:
    if refresh:
        return refresh_new_issue_universe(asset_class, daily=daily, update=True)
    out_file = os.path.join(DIR_INPUT, f'{asset_class}-newissue.pkl')
    data = loadPKL(out_file)
    return {k: v for k, v in data.items() if isinstance(v, pd.DataFrame)}


def build_stat_info(universe_by_asset: Dict[str, Dict[str, pd.DataFrame]]) -> pd.DataFrame:
    """Latest-row snapshot across all (asset_class, tenor_bucket, stage) combos.

    ``mean``/``vol`` are left NaN: BondNewIssue is EventDriven (no stable OU
    mean to score against), but the columns are kept present so legacy
    consumers that join against them (e.g. web/core/scripts.py's fallback bar
    chart) do not KeyError.
    """
    rows = {}
    for asset_class, buckets in universe_by_asset.items():
        for tenor_bucket, df in buckets.items():
            if df is None or df.empty:
                continue
            last = df.sort_index().iloc[-1]
            for stage, cfg in _STAGES.items():
                inst = last.get(cfg['instrument_col'])
                if pd.isna(inst) or not inst:
                    continue
                if stage == 'nib_otr' and not bool(last.get('lag_exists', False)):
                    # No live migration to trade for this cohort (existence-of-lag gate).
                    continue
                entry = {
                    'asset_class': asset_class, 'issuer_class': last.get('issuer_class'),
                    'tenor_bucket': tenor_bucket, 'stage': stage,
                    'nib_id': last.get('nib_id'), 'otr_id': last.get('otr_id'),
                    'ofr1_id': last.get('ofr1_id'), 'ofr2_id': last.get('ofr2_id'),
                    'event_age_days': last.get(cfg['age_col']),
                    'lag_exists': last.get('lag_exists'), 'lag_gap': last.get('lag_gap'),
                    'otr_roll_flag': last.get('otr_roll_flag'),
                    'dv01_ratio': last.get(cfg['dv01_ratio_col']),
                    'quote_ok_nib': last.get('quote_ok_nib'), 'quote_ok_otr': last.get('quote_ok_otr'),
                    'quote_ok_ofr1': last.get('quote_ok_ofr1'),
                    'rejection_reason': last.get('rejection_reason'),
                    'spread': last.get(cfg['spread_col']),
                    'mean': np.nan, 'vol': np.nan,
                    'style': 'EventDriven',
                    'direction': cfg['direction'],
                    'data_ready': NewIssueConfig.is_data_ready(asset_class, tenor_bucket),
                }
                rows[inst] = entry
    if not rows:
        return pd.DataFrame(columns=STAT_INFO_COLUMNS)
    return pd.DataFrame(rows).T


def build_spread_panel(universe_by_asset: Dict[str, Dict[str, pd.DataFrame]]) -> pd.DataFrame:
    """Date x (stage, episode-instrument_id) spread panel, NaN outside each
    episode's live range."""
    columns = {}
    for _asset_class, buckets in universe_by_asset.items():
        for _tenor_bucket, df in buckets.items():
            if df is None or df.empty:
                continue
            for stage, cfg in _STAGES.items():
                inst_col, spread_col = cfg['instrument_col'], cfg['spread_col']
                if inst_col not in df.columns or spread_col not in df.columns:
                    continue
                for inst_id, group in df.groupby(inst_col):
                    if pd.isna(inst_id) or not inst_id:
                        continue
                    s = pd.to_numeric(group[spread_col], errors='coerce').dropna()
                    if s.empty:
                        continue
                    if inst_id in columns:
                        columns[inst_id] = columns[inst_id].combine_first(s)
                    else:
                        columns[inst_id] = s
    if not columns:
        return pd.DataFrame()
    return pd.DataFrame(columns).sort_index()


def refresh_new_issue_spreads(
    refresh_universe: bool = True, update: bool = True, daily: bool = True,
) -> Dict[str, pd.DataFrame]:
    """Build/persist the BondNewIssue-spds.pkl artifact from both asset classes.

    `daily=True` (production default) fetches live BondRT quotes via
    retrieveEnvRT; pass `daily=False` for offline/test runs against the
    already-persisted CNBD/BondRT snapshot only.
    """
    universe_by_asset = {
        asset_class: _asset_universe(asset_class, refresh_universe, daily)
        for asset_class in NewIssueConfig.ISSUER_CLASS_MAP.keys()
    }

    stat_info = build_stat_info(universe_by_asset)
    spread_panel = build_spread_panel(universe_by_asset)
    result = {'BondNewIssue': {'StatInfo': stat_info, 'Spread': spread_panel}}

    if update:
        out_path = os.path.join(DIR_INPUT, OUT_FILE)
        updatePKL(result, out_path, rewrite=True)

    return result


def main():
    try:
        result = refresh_new_issue_spreads(refresh_universe=True, update=True)
        n = len(result.get('BondNewIssue', {}).get('StatInfo', []))
        logger.info("BondNewIssue-spds.pkl refreshed: %d active episode(s).", n)
    except Exception as e:
        logger.error("Error refreshing BondNewIssue spreads: %s", e)
        raise


if __name__ == '__main__':
    main()
