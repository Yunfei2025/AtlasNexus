# -*- coding: utf-8 -*-
"""Phase 3 (Artifacts) of docs/dev/tbondcurve-30y-otr-ofr-plan.md.

Aggregates the per-asset-class OTR/OFR universe artifacts built by
``curves.calibration.otr_ofr_universe`` (``{asset_class}-newissue.pkl``) into
the single dashboard-facing artifact ``BondNewIssue-spds.pkl``, mirroring the
``{Prefix}-spds.pkl`` convention consumed by ``web/tabs/alpha/data/loaders.py``
(``{'BondNewIssue': {'StatInfo': df, 'Spread': df}}``).

- ``StatInfo``: one row per currently-active (asset_class, tenor_bucket)
  episode — the live snapshot shown in the Alpha Book dropdown/table.
- ``Spread``: date-indexed, one column per historical episode
  (``instrument_id``), since BondNewIssue's instrument identity rebinds at
  every roll and has no single continuous column across rolls.

Never fabricates a spread value for a date before an episode's OTR was
selected; each episode column is only populated over its own live date range.
"""
from __future__ import annotations

import os
from typing import Dict

import pandas as pd

from settings.paths import DIR_INPUT
from settings.fixed_income import NewIssueConfig
from curves.calibration.otr_ofr_universe import refresh_new_issue_universe
from curves.utils.file import loadPKL, updatePKL

from utils.log_window import get_logger
logger = get_logger(__name__)

OUT_FILE = 'BondNewIssue-spds.pkl'

STAT_INFO_COLUMNS = [
    'asset_class', 'issuer_class', 'tenor_bucket', 'otr_id', 'ofr1_id', 'ofr2_id',
    'event_age_days', 'roll_flag', 'dv01_ratio_ofr1_otr', 'otr_turnover', 'ofr1_turnover',
    'quote_ok_otr', 'quote_ok_ofr1', 'rejection_reason', 'ytm_otr', 'ytm_ofr1', 'spread',
    'style', 'direction', 'data_ready',
]


def _asset_universe(asset_class: str, refresh: bool, daily: bool) -> Dict[str, pd.DataFrame]:
    if refresh:
        return refresh_new_issue_universe(asset_class, daily=daily, update=True)
    out_file = os.path.join(DIR_INPUT, f'{asset_class}-newissue.pkl')
    data = loadPKL(out_file)
    return {k: v for k, v in data.items() if isinstance(v, pd.DataFrame)}


def build_stat_info(universe_by_asset: Dict[str, Dict[str, pd.DataFrame]]) -> pd.DataFrame:
    """Latest-row snapshot across all (asset_class, tenor_bucket) buckets."""
    rows = {}
    for asset_class, buckets in universe_by_asset.items():
        for tenor_bucket, df in buckets.items():
            if df is None or df.empty:
                continue
            last = df.sort_index().iloc[-1]
            inst = last.get('instrument_id')
            if pd.isna(inst) or not inst:
                continue
            entry = {c: last.get(c) for c in STAT_INFO_COLUMNS if c not in ('style', 'direction', 'data_ready')}
            entry['style'] = 'EventDriven'
            # Directional convention (see plan): long new OTR, short 1st-OFR —
            # a bet that the post-issuance widening in spread=ytm_1ofr-ytm_otr
            # continues, not a mean-reversion entry.
            entry['direction'] = 'BUY'
            entry['data_ready'] = NewIssueConfig.is_data_ready(asset_class, tenor_bucket)
            rows[inst] = entry
    if not rows:
        return pd.DataFrame(columns=STAT_INFO_COLUMNS)
    return pd.DataFrame(rows).T


def build_spread_panel(universe_by_asset: Dict[str, Dict[str, pd.DataFrame]]) -> pd.DataFrame:
    """Date x episode-instrument_id spread panel (NaN outside each episode's live range)."""
    columns = {}
    for _asset_class, buckets in universe_by_asset.items():
        for _tenor_bucket, df in buckets.items():
            if df is None or df.empty or 'instrument_id' not in df.columns:
                continue
            for inst_id, group in df.groupby('instrument_id'):
                if pd.isna(inst_id) or not inst_id:
                    continue
                s = pd.to_numeric(group['spread'], errors='coerce').dropna()
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
