# -*- coding: utf-8 -*-
"""Phase 6 (Execution and Release) of docs/dev/tbondcurve-30y-otr-ofr-plan.md.

This platform has no live order-management/execution venue integration —
it is a research and signal-generation system. This module implements the
plan's gating and state-machine logic as pure, auditable data (not order
routing): it evaluates the mandatory gates against a BondNewIssue universe
row and reports the reached state plus rejection reasons, for shadow/paper
tracking only. It never submits, cancels, or connects to any execution venue.

State machine (subset relevant to a system with no live OMS):
    DISCOVERED -> DATA_VALIDATED -> SIGNAL_READY -> RISK_APPROVED -> ORDER_ELIGIBLE

`ORDER_ELIGIBLE` is the terminal state this module can certify: everything
past it (ORDER_SUBMITTED, FILLED, OPEN, CLOSED, ...) requires an execution
venue this codebase does not have, and must not be fabricated here.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from settings.fixed_income import NewIssueConfig

STATES = [
    'DISCOVERED',
    'DATA_VALIDATED',
    'SIGNAL_READY',
    'RISK_APPROVED',
    'ORDER_ELIGIBLE',
]


def evaluate_gates(
    row: Dict[str, Any],
    entry_percentile: float | None = None,
    entry_percentile_max: float = 60.0,
    min_dv01_ratio: float = 0.5,
    max_dv01_ratio: float = 2.0,
    stage: str = 'otr_ofr1',
) -> Dict[str, Any]:
    """Evaluate the plan's mandatory gates against one BondNewIssue universe row.

    `row` is a single episode's latest record (e.g. one row of a
    per-tenor-bucket universe DataFrame from curves.calibration.otr_ofr_universe,
    or a `BondNewIssue-spds.pkl` StatInfo row) with at least: asset_class,
    tenor_bucket, rejection_reason, quote_ok_nib/otr/ofr1, dv01_ratio,
    an age field for the relevant `stage`, and (for `stage='nib_otr'`)
    `lag_exists`.

    `stage` is `'nib_otr'` (Stage 1: challenger vs incumbent) or `'otr_ofr1'`
    (Stage 2: incumbent retiring) — see docs/dev/tbondcurve-30y-otr-ofr-plan.md
    "Canonical Definitions". Gate order and rank-age field differ per stage.

    Returns {'state': str, 'rejections': list[str]}. `state` is the highest
    state reached; any failed gate freezes the state at the last passed step
    and records why in `rejections` (state never regresses past a failure).
    """
    rejections: List[str] = []

    # DISCOVERED: the row exists at all (a candidate universe entry was built).
    state = 'DISCOVERED'

    # DATA_VALIDATED: constituent selection gate — a valid rank identity exists.
    if row.get('rejection_reason'):
        rejections.append(f"constituent_selection:{row['rejection_reason']}")
        return {'state': state, 'rejections': rejections}
    state = 'DATA_VALIDATED'

    # Existence-of-lag gate (Stage 1 only): skip cohorts where NIB has already
    # coincided with OTR (or never lagged) — no migration left to harvest.
    if stage == 'nib_otr' and not row.get('lag_exists', False):
        rejections.append('signal_ready:no_lag')
        return {'state': state, 'rejections': rejections}

    # SIGNAL_READY: within the rank-age entry window and (if provided) cohort
    # score confirmed — otr_ofr_rv uses a different readiness ladder (see plan);
    # this gate is BondNewIssue-specific.
    age_field = 'nib_age_days' if stage == 'nib_otr' else 'otr_rank_age_days'
    age = row.get(age_field)
    if age is None or pd.isna(age) or not (NewIssueConfig.ENTRY_AGE_MIN_DAYS <= age <= NewIssueConfig.ENTRY_AGE_MAX_DAYS):
        rejections.append('signal_ready:outside_entry_age_window')
        return {'state': state, 'rejections': rejections}
    if entry_percentile is not None and entry_percentile > entry_percentile_max:
        rejections.append('signal_ready:cohort_score_not_confirmed')
        return {'state': state, 'rejections': rejections}
    state = 'SIGNAL_READY'

    # RISK_APPROVED: fresh two-sided quotes and DV01 hedge tolerance for the
    # two legs relevant to this stage.
    leg1_ok, leg2_ok = (
        ('quote_ok_nib', 'quote_ok_otr') if stage == 'nib_otr' else ('quote_ok_otr', 'quote_ok_ofr1')
    )
    if not row.get(leg1_ok) or not row.get(leg2_ok):
        rejections.append('risk_approved:quote_not_executable')
        return {'state': state, 'rejections': rejections}
    dv01_ratio = row.get('dv01_ratio')
    if pd.isna(dv01_ratio) or not (min_dv01_ratio <= dv01_ratio <= max_dv01_ratio):
        rejections.append('risk_approved:dv01_hedge_out_of_tolerance')
        return {'state': state, 'rejections': rejections}
    state = 'RISK_APPROVED'

    # ORDER_ELIGIBLE: bucket-level data-readiness gate — approval for one
    # (asset_class, tenor_bucket) never unlocks any other bucket, and passing
    # one stage never unlocks the other (see plan's "Production Operating Model").
    asset_class = row.get('asset_class')
    tenor_bucket = row.get('tenor_bucket')
    if not NewIssueConfig.is_data_ready(asset_class, tenor_bucket):
        rejections.append(f'order_eligible:bucket_not_data_ready:{asset_class}/{tenor_bucket}')
        return {'state': state, 'rejections': rejections}
    state = 'ORDER_ELIGIBLE'

    return {'state': state, 'rejections': rejections}
