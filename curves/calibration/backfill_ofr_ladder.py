# -*- coding: utf-8 -*-
"""One-off repair for historical TBond/CBond-newissue.pkl rows where the
OFR-ladder ranking bug (fixed in ``otr_ofr_universe._rank_ladder_raw``) let a
turnover-ranked OFR{k} slot collide with ``nib_id`` (or, transitively,
``otr_id``).

The persisted history only stores each date's *confirmed* identities, not the
per-bond turnover ratios that produced them, so the fixed ranking algorithm
cannot be replayed from scratch for past dates. Instead this walks each
bucket's rows in date order and, whenever a rank (1..depth) collides with
nib_id/otr_id, carries forward the last known-good (non-colliding) value for
that SAME rank -- mirroring the persistence rule the live builder already
uses elsewhere ("keep the incumbent until a real challenger is confirmed").
This is the correct repair because the bug only ever injects a phantom
collision; it never represents a genuine rank change, so the bond that held
that rank immediately before the bug hit is still the right one to report,
not whatever happened to be recorded one rank lower that day.

A rank with no prior known-good value to fall back on (e.g. the bug appears
on the very first row of a bucket's history) instead pulls the next lower
rank's column-set up to fill the gap, same as before, since there is nothing
else on record for that rank yet.

``spread_otr_ofr1`` / ``instrument_id_otr_ofr1`` are recomputed from the
corrected ofr1 values; ``dv01_ratio_ofr1_otr`` cannot be recomputed (its DV01
proxy inputs were never persisted) and is cleared on any changed row.

``otr_id`` itself is never altered: NIB legitimately becomes OTR once its
turnover overtakes the incumbent (see otr_ofr_universe.py docstring and the
lag_exists gate), so nib_id == otr_id is expected, valid data.

Usage: python -m curves.calibration.backfill_ofr_ladder [--dry-run]
"""

from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd

from settings.paths import DIR_INPUT
from curves.calibration.otr_ofr_universe import _RANK_NAMES, instrument_id
from curves.utils.file import loadPKL

from utils.log_window import get_logger
logger = get_logger(__name__)


_RANK_COLS = ('raw_id', 'id', 'since_date', 'rank_age_days', 'turnover', 'quote_ok', 'ytm')


def _rank_colset(row: pd.Series, name: str) -> dict:
    return {col: row.get(f'{name}_{col}') for col in _RANK_COLS}


def _write_rank_colset(row: pd.Series, name: str, colset: dict) -> None:
    for col, val in colset.items():
        row[f'{name}_{col}'] = val


def _clear_rank_colset(row: pd.Series, name: str) -> None:
    for col in _RANK_COLS:
        row[f'{name}_{col}'] = np.nan


def _repair_bucket_df(df: pd.DataFrame, depth: int) -> tuple[pd.DataFrame, int]:
    """Sequentially repair one bucket's rows, carrying forward each rank's
    last known-good value across any nib_id/otr_id collision."""
    df = df.sort_index()
    last_good: dict[int, dict] = {}  # rank -> last non-colliding column-set
    out_rows = []
    n_changed = 0

    for _, row in df.iterrows():
        row = row.copy()
        nib_id = row.get('nib_id')
        otr_id = row.get('otr_id')
        exclude = {v for v in (nib_id, otr_id) if pd.notna(v)}

        current = {k: _rank_colset(row, _RANK_NAMES[k]) for k in range(1, depth + 1)}
        colliding = {
            k for k, cs in current.items()
            if pd.notna(cs['id']) and cs['id'] in exclude
        }

        if colliding:
            fallback_pool = [
                current[k] for k in range(1, depth + 1)
                if k not in colliding and pd.notna(current[k]['id']) and current[k]['id'] not in exclude
            ]
            fallback_iter = iter(fallback_pool)
            for k in sorted(colliding):
                name = _RANK_NAMES[k]
                prior = last_good.get(k)
                if prior is not None and pd.notna(prior['id']) and prior['id'] not in exclude:
                    _write_rank_colset(row, name, prior)
                else:
                    nxt = next(fallback_iter, None)
                    if nxt is not None:
                        _write_rank_colset(row, name, nxt)
                    else:
                        _clear_rank_colset(row, name)
            n_changed += 1

        for k in range(1, depth + 1):
            name = _RANK_NAMES[k]
            rid = row.get(f'{name}_id')
            if pd.notna(rid) and rid not in exclude:
                last_good[k] = _rank_colset(row, name)

        if colliding:
            ofr1_id = row.get('ofr1_id')
            ytm_otr = row.get('ytm_otr')
            ytm_ofr1 = row.get('ytm_ofr1')
            row['spread_otr_ofr1'] = (
                (ytm_otr - ytm_ofr1) if (pd.notna(ytm_otr) and pd.notna(ytm_ofr1)) else np.nan
            )
            row['instrument_id_otr_ofr1'] = (
                instrument_id(row['tenor_bucket'], 'otr_ofr1', otr_id, ofr1_id) if pd.notna(ofr1_id) else np.nan
            )
            row['dv01_ratio_ofr1_otr'] = np.nan

        out_rows.append(row)

    out = pd.DataFrame(out_rows)
    out.index = df.index
    out.index.name = df.index.name
    return out, n_changed


def backfill(asset_classes=('TBond', 'CBond'), depth: int = 3, dry_run: bool = False) -> None:
    for asset_class in asset_classes:
        path = os.path.join(DIR_INPUT, f'{asset_class}-newissue.pkl')
        data = loadPKL(path)
        if not isinstance(data, dict) or not data:
            logger.warning("No data at %s; skipping.", path)
            continue

        new_data = {}
        total_changed = 0
        for tenor_bucket, df in data.items():
            if not isinstance(df, pd.DataFrame) or df.empty:
                new_data[tenor_bucket] = df
                continue
            fixed_df, n_changed = _repair_bucket_df(df, depth)
            new_data[tenor_bucket] = fixed_df
            total_changed += n_changed
            logger.info("%s/%s: repaired %d/%d rows.", asset_class, tenor_bucket, n_changed, len(df))

        if dry_run:
            logger.info("%s: dry-run, %d total rows repaired (not written).", asset_class, total_changed)
            continue

        if total_changed == 0:
            logger.info("%s: no collisions found, file left untouched.", asset_class)
            continue

        with open(path, 'wb') as f:
            import pickle
            pickle.dump(new_data, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info("%s: wrote %d total repaired rows to %s.", asset_class, total_changed, path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Report counts without writing.')
    args = parser.parse_args()
    backfill(dry_run=args.dry_run)
