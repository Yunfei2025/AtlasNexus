# -*- coding: utf-8 -*-
"""Point-in-time NIB/OTR/OFR-ladder universe builder for BondNewIssue and
mature otr_ofr_rv (see docs/dev/tbondcurve-30y-otr-ofr-plan.md).

Three distinct identities are tracked per (asset_class, tenor_bucket), never
conflated (see the plan's "Rank Definitions"):

- NIB (new-issue bond): newest issuance, ranked by `起息日期` descending. Stable
  identity — issuance order never changes.
- OTR (on-the-run): highest-turnover bond in the bucket, i.e. the same
  liquidity definition ``RefBondSelector`` uses for curve calibration
  (``get_most_liquid_bond`` in ``curves/calibration/selector.py``).
- OFR-ladder (OFR1..OFR{depth}): turnover ranks below OTR, via
  ``get_offtherun_bond(turnover, n_exclude=k)``.

NIB and OTR are usually, but not always, different bonds — a new issue only
becomes OTR once its turnover overtakes the incumbent. OTR/OFR identities are
confirmed via a persistence rule (a challenger must lead for
``NewIssueConfig.OTR_RANK_PERSISTENCE_DAYS`` consecutive observations) so a
single noisy trade cannot flip the ladder and splice pair history.

This is deliberately separate from ``RefBondSelector``: that selector buckets
by *remaining* maturity for affine curve calibration, whereas this module
buckets by fixed *original* issuance tenor, independent of curve fitting.

Persists to ``{bond_type}-newissue.pkl`` under DIR_INPUT as
``{tenor_bucket: DataFrame}``, one row per processed date. See
``UNIVERSE_ROW_COLUMNS`` for the full column set.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from settings.paths import DIR_INPUT, DIR_DATA
from settings.general import DateConfig
from settings.fixed_income import NewIssueConfig
from curves.utils.loader import loadInstrumentDefinition
from curves.utils.retrieve import retrieveEnvRT
from curves.utils.file import loadPKL, updatePKL
from curves.calibration.selector import (
    filter_bonds_by_type, _as_scalar_bond_id, get_most_liquid_bond, get_offtherun_bond,
)

from utils.log_window import get_logger
logger = get_logger(__name__)


# rank 0 = OTR (turnover leader), rank k>=1 = OFR{k} (k-th turnover runner-up).
_RANK_NAMES: Dict[int, str] = {0: 'otr'}
_RANK_NAMES.update({k: f'ofr{k}' for k in range(1, NewIssueConfig.OFR_LADDER_DEPTH + 1)})


def _ofr_rank_columns() -> List[str]:
    cols: List[str] = []
    for rank, name in _RANK_NAMES.items():
        cols += [
            f'{name}_raw_id', f'{name}_id', f'{name}_since_date', f'{name}_rank_age_days',
            f'{name}_turnover', f'quote_ok_{name}', f'ytm_{name}',
        ]
    return cols


def _ofr_ladder_stage_columns() -> List[str]:
    """Per-rung OFR{k}-vs-OFR1 spread/instrument columns for k=2..depth.

    OFR1 vs itself (k=1) is meaningless and excluded, matching the same
    ofrk_id == ofr1_id guard used elsewhere (see curves/refreshers/
    otr_ofr_rv.py). These mirror spread_otr_ofr1/instrument_id_otr_ofr1's
    shape exactly so curves/refreshers/newissue_spreads.py's _STAGES dict can
    treat 'ofr{k}_ofr1' like any other stage.
    """
    cols: List[str] = []
    for k in range(2, NewIssueConfig.OFR_LADDER_DEPTH + 1):
        cols += [f'spread_ofr{k}_ofr1', f'instrument_id_ofr{k}_ofr1']
    return cols


UNIVERSE_ROW_COLUMNS = [
    'asset_class', 'issuer_class', 'tenor_bucket',
    'nib_id', 'nib_start_date', 'nib_age_days', 'quote_ok_nib', 'nib_turnover', 'ytm_nib',
    *_ofr_rank_columns(),
    'otr_roll_flag', 'lag_gap', 'lag_exists',
    'dv01_ratio_otr_nib', 'dv01_ratio_ofr1_otr',
    'spread_nib_otr', 'spread_otr_ofr1',
    'instrument_id_nib_otr', 'instrument_id_otr_ofr1',
    *_ofr_ladder_stage_columns(),
    'rejection_reason',
]


def instrument_id(tenor_bucket: str, stage: str, leg1_id: Any, leg2_id: Any) -> str:
    """Canonical BondNewIssue instrument label:
    ``<tenor_bucket>:<stage>:<leg1_id>|<leg2_id>``, where ``stage`` is
    ``nib_otr``, ``otr_ofr1``, or ``ofr{k}_ofr1`` (k=2..OFR_LADDER_DEPTH)."""
    return f'{tenor_bucket}:{stage}:{leg1_id}|{leg2_id}'


def _add_ofr_ladder_spreads(row: Dict[str, Any], confirmed: Dict[int, Any], tenor_bucket: str) -> None:
    """Populate spread_ofr{k}_ofr1 / instrument_id_ofr{k}_ofr1 for k=2..depth.

    Mirrors the otr_ofr1 stage's own convention: spread is leg1 - leg2 with
    OFR1 as the reference leg (row['spread_otr_ofr1'] = ytm_otr - ytm_ofr1,
    i.e. incumbent minus successor), so here spread = ytm_ofr{k} - ytm_ofr1.
    A rung with no confirmed bond yet (still NaN this early in the ladder's
    life) or one that collapses onto OFR1 itself contributes NaN/None rather
    than a synthetic self-spread, matching curves/refreshers/otr_ofr_rv.py's
    ofrk_id == ofr1_id guard.
    """
    ofr1_id = confirmed.get(1, np.nan)
    ytm_ofr1 = row.get('ytm_ofr1', np.nan)
    for k in range(2, NewIssueConfig.OFR_LADDER_DEPTH + 1):
        ofrk_id = confirmed.get(k, np.nan)
        ytm_ofrk = row.get(f'ytm_ofr{k}', np.nan)
        valid = (
            pd.notna(ofrk_id) and pd.notna(ofr1_id) and str(ofrk_id) != str(ofr1_id)
            and pd.notna(ytm_ofrk) and pd.notna(ytm_ofr1)
        )
        row[f'spread_ofr{k}_ofr1'] = (ytm_ofrk - ytm_ofr1) if valid else np.nan
        row[f'instrument_id_ofr{k}_ofr1'] = (
            instrument_id(tenor_bucket, f'ofr{k}_ofr1', ofrk_id, ofr1_id) if valid else np.nan
        )


def _empty_row(asset_class: str, tenor_bucket: str, rejection_reason: str) -> Dict[str, Any]:
    row = {c: np.nan for c in UNIVERSE_ROW_COLUMNS}
    bool_fields = ['quote_ok_nib', 'otr_roll_flag', 'lag_exists']
    bool_fields += [f'quote_ok_{name}' for name in _RANK_NAMES.values()]
    row.update({f: False for f in bool_fields})
    row.update({
        'asset_class': asset_class,
        'issuer_class': NewIssueConfig.issuer_class(asset_class),
        'tenor_bucket': tenor_bucket,
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


def _rank_ladder_raw(turnover: pd.Series, depth: int, nib_id: Any = None) -> Dict[int, Any]:
    """Raw (unconfirmed) turnover-rank ladder for one date: 0=OTR challenger,
    1..depth=OFR{k} challengers. Sparse buckets (fewer bonds than a given rank
    needs) return NaN for that rank rather than aliasing to a lower rank.

    NIB may legitimately win OTR (rank 0) once its turnover overtakes the
    incumbent -- but it is always excluded from the OFR-ladder pool (ranks
    1+), even when it also happens to be OTR: a bond fresh off auction can
    spike to high turnover for a few days without being a genuine off-the-run
    rung, and NIB/OFR must stay distinct identities per this module's design
    (see module docstring).
    """
    if turnover.empty:
        return {r: np.nan for r in range(depth + 1)}
    otr_id = get_most_liquid_bond(turnover)
    raw: Dict[int, Any] = {0: otr_id}
    exclude_ids = {i for i in (nib_id, otr_id) if i is not None and pd.notna(i)}
    ofr_pool = turnover.drop(index=[i for i in exclude_ids if i in turnover.index])
    for k in range(1, depth + 1):
        raw[k] = get_offtherun_bond(ofr_pool, n_exclude=k - 1) if len(ofr_pool) > k - 1 else np.nan
    return raw


def _confirm_rank_id(
    history_df: Optional[pd.DataFrame],
    raw_col: str,
    confirmed_col: str,
    since_col: str,
    candidate_id: Any,
    calc_date: date,
    persistence_days: int,
) -> Tuple[Any, Optional[pd.Timestamp], bool]:
    """Confirm a turnover-ranked identity (OTR or an OFR rung) using a simple
    persistence rule: a challenger only replaces the incumbent once its raw
    turnover-leader rank has held for `persistence_days` consecutive prior
    observations (see docs/dev/tbondcurve-30y-otr-ofr-plan.md "Rank
    Definitions"). Returns (confirmed_id, since_date, changed)."""
    if pd.isna(candidate_id):
        return np.nan, pd.NaT, False

    prev_confirmed = None
    prev_since = None
    if history_df is not None and len(history_df) > 0 and confirmed_col in history_df.columns:
        last = history_df.iloc[-1]
        prev_confirmed = last.get(confirmed_col)
        prev_since = last.get(since_col)

    if prev_confirmed is None or pd.isna(prev_confirmed):
        # No prior confirmed identity — accept the first observed candidate immediately.
        return candidate_id, pd.Timestamp(calc_date), True

    if candidate_id == prev_confirmed:
        since = pd.Timestamp(prev_since) if pd.notna(prev_since) else pd.Timestamp(calc_date)
        return prev_confirmed, since, False

    since = pd.Timestamp(prev_since) if pd.notna(prev_since) else pd.Timestamp(calc_date)
    if persistence_days <= 1 or history_df is None or raw_col not in history_df.columns:
        return candidate_id, pd.Timestamp(calc_date), True

    recent_raw = history_df[raw_col].tail(persistence_days - 1)
    if len(recent_raw) < persistence_days - 1 or not bool((recent_raw == candidate_id).all()):
        # Challenger not yet persisted long enough — keep the incumbent.
        return prev_confirmed, since, False

    confirmed_since = pd.Timestamp(calc_date) - pd.Timedelta(days=persistence_days - 1)
    return candidate_id, confirmed_since, True


def _select_otr_ofr_for_date(
    df_def: pd.DataFrame,
    bond_rt: Optional[pd.DataFrame],
    asset_class: str,
    tenor_bucket: str,
    calc_date: date,
    history_df: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Compute one date's NIB / OTR / OFR-ladder row for a single
    (asset_class, tenor_bucket). NIB is ranked by issuance recency; OTR and the
    OFR ladder are ranked by turnover and confirmed via a persistence rule
    against `history_df` (the bucket's prior rows) so a single noisy trade
    cannot flip the ladder (see plan's "Rank Definitions")."""
    candidates = _bucket_candidates(df_def, asset_class, tenor_bucket, calc_date)
    if len(candidates) == 0:
        return _empty_row(asset_class, tenor_bucket, 'no_bonds_in_bucket')
    if len(candidates) < 2:
        return _empty_row(asset_class, tenor_bucket, 'insufficient_bucket_bonds')

    # NIB: newest issuance, independent of liquidity.
    start_dates = pd.to_datetime(df_def.loc[candidates, '起息日期'])
    issuance_ranked = start_dates.sort_values(ascending=False).index
    nib_id = _as_scalar_bond_id(issuance_ranked[0])
    nib_start = pd.Timestamp(start_dates.loc[nib_id])
    nib_age_days = int((pd.Timestamp(calc_date) - nib_start).days)

    row: Dict[str, Any] = {
        'asset_class': asset_class,
        'issuer_class': NewIssueConfig.issuer_class(asset_class),
        'tenor_bucket': tenor_bucket,
        'nib_id': nib_id,
        'nib_start_date': nib_start,
        'nib_age_days': nib_age_days,
        'quote_ok_nib': _quote_ok(df_def, bond_rt, nib_id),
        'ytm_nib': _mid_yield(df_def, bond_rt, nib_id),
        'rejection_reason': None,
    }

    # OTR / OFR ladder: turnover-ranked, confirmed via persistence.
    turnover = pd.Series({b: _turnover_ratio(df_def, b) for b in candidates}).dropna()
    row['nib_turnover'] = turnover.get(nib_id, np.nan)
    depth = NewIssueConfig.OFR_LADDER_DEPTH
    persistence_days = NewIssueConfig.OTR_RANK_PERSISTENCE_DAYS
    raw_ladder = _rank_ladder_raw(turnover, depth, nib_id=nib_id)

    confirmed: Dict[int, Any] = {}
    prev_otr_id = history_df.iloc[-1].get('otr_id') if (history_df is not None and len(history_df) > 0) else None
    for rank, raw_id in raw_ladder.items():
        name = _RANK_NAMES[rank]
        confirmed_id, since, changed = _confirm_rank_id(
            history_df, f'{name}_raw_id', f'{name}_id', f'{name}_since_date',
            raw_id, calc_date, persistence_days,
        )
        confirmed[rank] = confirmed_id
        rank_age = int((pd.Timestamp(calc_date) - since).days) if pd.notna(since) else np.nan
        row[f'{name}_raw_id'] = raw_id
        row[f'{name}_id'] = confirmed_id
        row[f'{name}_since_date'] = since
        row[f'{name}_rank_age_days'] = rank_age
        row[f'{name}_turnover'] = turnover.get(confirmed_id, np.nan) if pd.notna(confirmed_id) else np.nan
        row[f'quote_ok_{name}'] = _quote_ok(df_def, bond_rt, confirmed_id) if pd.notna(confirmed_id) else False
        row[f'ytm_{name}'] = _mid_yield(df_def, bond_rt, confirmed_id) if pd.notna(confirmed_id) else np.nan
        if rank == 0:
            row['otr_roll_flag'] = bool(changed and prev_otr_id is not None and pd.notna(prev_otr_id))

    otr_id = confirmed[0]
    ofr1_id = confirmed.get(1, np.nan)

    # Existence-of-lag gate input (Stage 1 precondition): some auctions are
    # absorbed into liquidity immediately, so NIB and OTR already coincide —
    # that cohort has no migration lag to trade.
    otr_turnover = row.get('otr_turnover', np.nan)
    nib_turnover = row['nib_turnover']
    lag_gap = (otr_turnover - nib_turnover) if (pd.notna(otr_turnover) and pd.notna(nib_turnover)) else np.nan
    lag_exists = bool(
        pd.notna(lag_gap) and nib_id != otr_id and lag_gap > NewIssueConfig.LAG_TURNOVER_GAP_THRESHOLD
    )
    row['lag_gap'] = lag_gap
    row['lag_exists'] = lag_exists

    ytm_nib = row['ytm_nib']
    ytm_otr = row.get('ytm_otr', np.nan)
    ytm_ofr1 = row.get('ytm_ofr1', np.nan)
    row['dv01_ratio_otr_nib'] = _safe_ratio(_dv01_proxy(df_def, otr_id), _dv01_proxy(df_def, nib_id))
    row['dv01_ratio_ofr1_otr'] = (
        _safe_ratio(_dv01_proxy(df_def, ofr1_id), _dv01_proxy(df_def, otr_id)) if pd.notna(ofr1_id) else np.nan
    )
    # Stage 1 (nib_otr): y_NIB - y_OTR. Stage 2 (otr_ofr1): y_OTR - y_OFR1 (see plan doc).
    row['spread_nib_otr'] = (ytm_nib - ytm_otr) if (pd.notna(ytm_nib) and pd.notna(ytm_otr)) else np.nan
    row['spread_otr_ofr1'] = (ytm_otr - ytm_ofr1) if (pd.notna(ytm_otr) and pd.notna(ytm_ofr1)) else np.nan
    row['instrument_id_nib_otr'] = instrument_id(tenor_bucket, 'nib_otr', nib_id, otr_id)
    row['instrument_id_otr_ofr1'] = (
        instrument_id(tenor_bucket, 'otr_ofr1', otr_id, ofr1_id) if pd.notna(ofr1_id) else np.nan
    )
    _add_ofr_ladder_spreads(row, confirmed, tenor_bucket)
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
                row = _select_otr_ofr_for_date(df_def, bond_rt, asset_class, tenor_bucket, current_date, existing_df)
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
                    "BondNewIssue universe %s/%s: NIB=%s OTR=%s rejection=%s",
                    asset_class, tenor_bucket,
                    new_df.iloc[-1]['nib_id'] if len(new_df) else None,
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
    """Point-in-time issuance-recency identity only (no live quotes, no turnover
    history). Used by the close-yield backfill path only, where NIB and OTR
    cannot be distinguished (no historical turnover panel) so OTR is a naive
    stand-in for NIB — never used for live gating (see `rejection_reason`)."""
    candidates = _bucket_candidates(df_def, asset_class, tenor_bucket, calc_date)
    if len(candidates) < 2:
        return None
    start_dates = pd.to_datetime(df_def.loc[candidates, '起息日期'])
    ranked = start_dates.sort_values(ascending=False).index
    nib_id = _as_scalar_bond_id(ranked[0])
    ofr1_id = _as_scalar_bond_id(ranked[1])
    ofr2_id = _as_scalar_bond_id(ranked[2]) if len(ranked) > 2 else np.nan
    return {'nib_id': nib_id, 'ofr1_id': ofr1_id, 'ofr2_id': ofr2_id, 'nib_start': pd.Timestamp(start_dates.loc[nib_id])}


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
            nib_id, ofr1_id, ofr2_id = ident['nib_id'], ident['ofr1_id'], ident['ofr2_id']
            # No historical turnover panel exists, so OTR/OFR1 are naive
            # issuance-rank stand-ins here (nib_id doubles as otr_id) — flagged
            # via rejection_reason, never used for live gating.
            otr_id = nib_id
            ytm_otr = float(close.loc[calc_date, otr_id]) if otr_id in close.columns else np.nan
            ytm_ofr1 = float(close.loc[calc_date, ofr1_id]) if ofr1_id in close.columns else np.nan
            ytm_ofr2 = float(close.loc[calc_date, ofr2_id]) if (pd.notna(ofr2_id) and ofr2_id in close.columns) else np.nan
            if pd.isna(ytm_otr) or pd.isna(ytm_ofr1):
                continue
            nib_age_days = int((calc_date - ident['nib_start']).days)
            roll_flag = bool(prev_otr_id is not None and prev_otr_id != otr_id)
            rows[calc_date] = {
                'asset_class': asset_class,
                'issuer_class': NewIssueConfig.issuer_class(asset_class),
                'tenor_bucket': tenor_bucket,
                'nib_id': nib_id, 'otr_id': otr_id, 'ofr1_id': ofr1_id, 'ofr2_id': ofr2_id,
                'nib_start_date': ident['nib_start'], 'nib_age_days': nib_age_days,
                'otr_roll_flag': roll_flag,
                'dv01_ratio_otr_nib': 1.0,
                'dv01_ratio_ofr1_otr': _safe_ratio(_dv01_proxy(df_def, ofr1_id), _dv01_proxy(df_def, otr_id)),
                'nib_turnover': np.nan, 'otr_turnover': np.nan, 'ofr1_turnover': np.nan,
                'quote_ok_nib': False, 'quote_ok_otr': False, 'quote_ok_ofr1': False,
                'lag_exists': False, 'lag_gap': np.nan,
                'rejection_reason': 'backfilled_close_yield_only',
                'ytm_nib': ytm_otr, 'ytm_otr': ytm_otr, 'ytm_ofr1': ytm_ofr1, 'ytm_ofr2': ytm_ofr2,
                'spread_nib_otr': 0.0,
                'spread_otr_ofr1': ytm_ofr1 - ytm_otr,
                'instrument_id_nib_otr': instrument_id(tenor_bucket, 'nib_otr', nib_id, otr_id),
                'instrument_id_otr_ofr1': instrument_id(tenor_bucket, 'otr_ofr1', otr_id, ofr1_id),
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


def _load_balance_history(asset_class: str) -> pd.DataFrame:
    """Point-in-time outstanding-balance history (date-indexed, columns=bond_id,
    values=债券余额:亿 in 100mm CNY units).

    Reconstructed from periodic ``{asset_class}-bondpool_<start>-<end>.pkl``
    snapshot files (as-of the end date encoded in the filename) plus the
    current ``{asset_class}-bondpool.pkl`` (as-of today). Balance only moves
    on redemption/reopening events (observed cadence: roughly quarterly), so
    callers should asof-match (forward-fill from the latest snapshot <= date)
    rather than interpolate.
    """
    import glob
    import re as _re

    db_dir = str(DIR_DATA)
    snapshots: Dict[pd.Timestamp, pd.Series] = {}

    for path in glob.glob(os.path.join(db_dir, f'{asset_class}-bondpool_*.pkl')):
        m = _re.search(r'(\d{8})-(\d{8})\.pkl$', os.path.basename(path))
        if not m:
            continue
        asof = pd.Timestamp(m.group(2))
        df = loadPKL(path)
        if not isinstance(df, pd.DataFrame) or '债券余额:亿' not in df.columns:
            continue
        snapshots[asof] = pd.to_numeric(df['债券余额:亿'], errors='coerce')

    current_path = os.path.join(db_dir, f'{asset_class}-bondpool.pkl')
    if os.path.exists(current_path):
        df = loadPKL(current_path)
        if isinstance(df, pd.DataFrame) and '债券余额:亿' in df.columns:
            snapshots[pd.Timestamp.today().normalize()] = pd.to_numeric(df['债券余额:亿'], errors='coerce')

    if not snapshots:
        return pd.DataFrame()

    panel = pd.DataFrame(snapshots).T.sort_index()
    panel.index.name = 'asof_date'
    return panel


def _balance_asof(balance_panel: pd.DataFrame, calc_date: pd.Timestamp) -> pd.Series:
    """Latest balance snapshot at or before ``calc_date``; falls back to the
    earliest available snapshot for dates older than any snapshot on file."""
    if balance_panel.empty:
        return pd.Series(dtype=float)
    prior = balance_panel.index[balance_panel.index <= calc_date]
    return balance_panel.loc[prior.max()] if len(prior) else balance_panel.iloc[0]


def backfill_new_issue_universe_turnover(
    asset_class: str,
    tenor_buckets: Optional[List[str]] = None,
    start: Optional[pd.Timestamp] = None,
    end: Optional[pd.Timestamp] = None,
    update: bool = True,
) -> Dict[str, pd.DataFrame]:
    """Reconstruct historical NIB/OTR/OFR-ladder identities using REAL
    historical turnover (daily volume / asof outstanding-balance), instead of
    the naive issuance-recency stand-in used by ``backfill_new_issue_universe``.

    Data sources (all under DIR_DATA, the raw database — not DIR_INPUT):
      - ``{asset_class}-px.pkl['Volume']``: daily traded volume per bond (CNY).
      - ``{asset_class}-bondpool_<start>-<end>.pkl`` / ``{asset_class}-bondpool.pkl``:
        periodic outstanding-balance snapshots (亿), asof-matched per date.

    OTR/OFR ranks are confirmed via the same persistence rule as the live
    daily builder (``_confirm_rank_id``) so a single noisy trading day cannot
    flip the ladder — this makes NIB (issuance-recency) and OTR (turnover
    leader) genuinely distinct bonds historically, unlike the naive
    close-yield-only backfill.
    """
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
    volume = px['Volume']
    volume.index = pd.to_datetime(volume.index)

    balance_panel = _load_balance_history(asset_class)
    if balance_panel.empty:
        logger.warning("No balance-history snapshots for %s; cannot compute historical turnover.", asset_class)
        return {}

    dates = close.index.sort_values()
    if start is not None:
        dates = dates[dates >= pd.Timestamp(start)]
    if end is not None:
        dates = dates[dates <= pd.Timestamp(end)]

    out_file = os.path.join(DIR_INPUT, f'{asset_class}-newissue.pkl')
    existing_data = loadPKL(out_file)

    depth = NewIssueConfig.OFR_LADDER_DEPTH
    persistence_days = NewIssueConfig.OTR_RANK_PERSISTENCE_DAYS

    result: Dict[str, pd.DataFrame] = {}
    for tenor_bucket in tenor_buckets:
        rows: Dict[pd.Timestamp, Dict[str, Any]] = {}
        recent_window: List[Dict[str, Any]] = []  # rolling tail, bounded by persistence_days

        for calc_date in dates:
            candidates = _bucket_candidates(df_def, asset_class, tenor_bucket, calc_date.date())
            if len(candidates) < 2 or calc_date not in volume.index:
                continue

            vol_cols = [c for c in candidates if c in volume.columns]
            vol_row = pd.to_numeric(volume.loc[calc_date, vol_cols], errors='coerce')
            bal_row = _balance_asof(balance_panel, calc_date).reindex(vol_row.index)
            turnover = (vol_row / pd.to_numeric(bal_row, errors='coerce') / 1e8).dropna()
            if turnover.empty:
                continue

            start_dates = pd.to_datetime(df_def.loc[candidates, '起息日期'])
            issuance_ranked = start_dates.sort_values(ascending=False).index
            nib_id = _as_scalar_bond_id(issuance_ranked[0])
            nib_start = pd.Timestamp(start_dates.loc[nib_id])
            ytm_nib = float(close.loc[calc_date, nib_id]) if nib_id in close.columns else np.nan

            raw_ladder = _rank_ladder_raw(turnover, depth)
            history_df = pd.DataFrame(recent_window) if recent_window else None
            prev_otr_id = recent_window[-1].get('otr_id') if recent_window else None

            row: Dict[str, Any] = {
                'asset_class': asset_class,
                'issuer_class': NewIssueConfig.issuer_class(asset_class),
                'tenor_bucket': tenor_bucket,
                'nib_id': nib_id, 'nib_start_date': nib_start,
                'nib_age_days': int((calc_date - nib_start).days),
                'ytm_nib': ytm_nib, 'nib_turnover': turnover.get(nib_id, np.nan),
                'quote_ok_nib': False,
            }
            for rank, raw_id in raw_ladder.items():
                name = _RANK_NAMES[rank]
                confirmed_id, since, changed = _confirm_rank_id(
                    history_df, f'{name}_raw_id', f'{name}_id', f'{name}_since_date',
                    raw_id, calc_date.date(), persistence_days,
                )
                row[f'{name}_raw_id'] = raw_id
                row[f'{name}_id'] = confirmed_id
                row[f'{name}_since_date'] = since
                row[f'{name}_rank_age_days'] = int((calc_date - since).days) if pd.notna(since) else np.nan
                row[f'{name}_turnover'] = turnover.get(confirmed_id, np.nan) if pd.notna(confirmed_id) else np.nan
                row[f'quote_ok_{name}'] = False
                row[f'ytm_{name}'] = (
                    float(close.loc[calc_date, confirmed_id])
                    if (pd.notna(confirmed_id) and confirmed_id in close.columns) else np.nan
                )
                if rank == 0:
                    row['otr_roll_flag'] = bool(changed and prev_otr_id is not None and pd.notna(prev_otr_id))

            otr_id, ofr1_id = row['otr_id'], row.get('ofr1_id', np.nan)

            otr_turnover, nib_turnover = row.get('otr_turnover', np.nan), row['nib_turnover']
            lag_gap = (otr_turnover - nib_turnover) if (pd.notna(otr_turnover) and pd.notna(nib_turnover)) else np.nan
            row['lag_gap'] = lag_gap
            row['lag_exists'] = bool(
                pd.notna(lag_gap) and nib_id != otr_id and lag_gap > NewIssueConfig.LAG_TURNOVER_GAP_THRESHOLD
            )
            row['dv01_ratio_otr_nib'] = _safe_ratio(_dv01_proxy(df_def, otr_id), _dv01_proxy(df_def, nib_id))
            row['dv01_ratio_ofr1_otr'] = (
                _safe_ratio(_dv01_proxy(df_def, ofr1_id), _dv01_proxy(df_def, otr_id)) if pd.notna(ofr1_id) else np.nan
            )
            ytm_otr, ytm_ofr1 = row.get('ytm_otr', np.nan), row.get('ytm_ofr1', np.nan)
            row['spread_nib_otr'] = (ytm_nib - ytm_otr) if (pd.notna(ytm_nib) and pd.notna(ytm_otr)) else np.nan
            row['spread_otr_ofr1'] = (ytm_otr - ytm_ofr1) if (pd.notna(ytm_otr) and pd.notna(ytm_ofr1)) else np.nan
            row['instrument_id_nib_otr'] = instrument_id(tenor_bucket, 'nib_otr', nib_id, otr_id)
            row['instrument_id_otr_ofr1'] = (
                instrument_id(tenor_bucket, 'otr_ofr1', otr_id, ofr1_id) if pd.notna(ofr1_id) else np.nan
            )
            _add_ofr_ladder_spreads(
                row, {rank: row.get(f'{name}_id') for rank, name in _RANK_NAMES.items() if name != 'otr'},
                tenor_bucket,
            )
            row['rejection_reason'] = 'backfilled_with_turnover'

            rows[calc_date] = row
            recent_window.append(row)
            if len(recent_window) > persistence_days:
                recent_window.pop(0)

        if not rows:
            continue
        new_df = pd.DataFrame(rows).T
        new_df.index.name = 'date'

        existing_df = existing_data.get(tenor_bucket)
        if isinstance(existing_df, pd.DataFrame) and len(existing_df) > 0:
            # Turnover-based rows are strictly better than both the naive
            # close-yield-only backfill and any pre-existing row for the same
            # date — they win on overlap.
            combined = pd.concat([existing_df, new_df])
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
