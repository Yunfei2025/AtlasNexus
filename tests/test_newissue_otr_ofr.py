# -*- coding: utf-8 -*-
"""Phase 7 tests for docs/dev/tbondcurve-30y-otr-ofr-plan.md (BondNewIssue).

Covers: instrument ID parsing/legs, point-in-time OTR/OFR bucket selection,
roll events, walk-forward cohort exclusion, and gate/state-machine enforcement.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from curves.calibration.otr_ofr_universe import (
    _bucket_candidates,
    _select_otr_ofr_for_date,
    instrument_id,
)
from curves.calibration.newissue_cohort import segment_episodes, cohort_percentile_causal
from curves.calibration.newissue_state import evaluate_gates
from web.tabs.alpha.data.legs import resolve_legs


def _make_def(rows: dict) -> pd.DataFrame:
    """rows: {bond_id: (start_date, maturity_date, orig_term, name)}"""
    data = {
        '起息日期': {}, '到期日期': {}, '期限': {}, '证券全称': {},
        '债券余额:亿': {}, '成交量:万元': {}, '修正久期': {}, '收盘价:元（全价）': {},
        '估价收益率:%(中债)': {},
    }
    for bond_id, (start, maturity, term, name) in rows.items():
        data['起息日期'][bond_id] = pd.Timestamp(start)
        data['到期日期'][bond_id] = pd.Timestamp(maturity)
        data['期限'][bond_id] = term
        data['证券全称'][bond_id] = name
        data['债券余额:亿'][bond_id] = 100.0
        data['成交量:万元'][bond_id] = 10.0
        data['修正久期'][bond_id] = 25.0
        data['收盘价:元（全价）'][bond_id] = 100.0
        data['估价收益率:%(中债)'][bond_id] = 3.0
    return pd.DataFrame(data)


def test_bucket_candidates_filters_by_original_term_and_outstanding():
    df_def = _make_def({
        'A': ('2020-01-01', '2050-01-01', 30, '国债A'),   # 30Y, outstanding
        'B': ('2021-01-01', '2031-01-01', 10, '国债B'),   # wrong bucket (10Y)
        'C': ('2026-01-01', '2056-01-01', 30, '国开债C'),  # wrong asset (CBond)
        'D': ('2030-01-01', '2060-01-01', 30, '国债D'),    # not started yet
    })
    cands = _bucket_candidates(df_def, 'TBond', '30Y', pd.Timestamp('2026-08-05').date())
    assert list(cands) == ['A']


def test_select_otr_ofr_ranks_by_issuance_recency_and_computes_spread():
    df_def = _make_def({
        'NEW': ('2026-06-25', '2056-06-25', 30, '国债NEW'),
        'OFR1': ('2025-01-01', '2055-01-01', 30, '国债OFR1'),
        'OFR2': ('2024-01-01', '2054-01-01', 30, '国债OFR2'),
    })
    df_def.loc['NEW', '估价收益率:%(中债)'] = 2.10
    df_def.loc['OFR1', '估价收益率:%(中债)'] = 2.00
    df_def.loc['OFR2', '估价收益率:%(中债)'] = 1.95

    row = _select_otr_ofr_for_date(df_def, None, 'TBond', '30Y', pd.Timestamp('2026-08-05').date())
    assert row['otr_id'] == 'NEW'
    assert row['ofr1_id'] == 'OFR1'
    assert row['ofr2_id'] == 'OFR2'
    assert row['rejection_reason'] is None
    assert row['spread'] == pytest.approx(2.00 - 2.10)
    assert row['instrument_id'] == instrument_id('30Y', 'NEW', 'OFR1')


def test_select_otr_ofr_reports_insufficient_bucket_bonds():
    df_def = _make_def({'ONLY': ('2026-01-01', '2056-01-01', 30, '国债ONLY')})
    row = _select_otr_ofr_for_date(df_def, None, 'TBond', '30Y', pd.Timestamp('2026-08-05').date())
    assert row['rejection_reason'] == 'insufficient_bucket_bonds'
    assert pd.isna(row['otr_id'])


def test_roll_flag_set_only_when_otr_changes():
    df_def = _make_def({
        'OLD': ('2025-01-01', '2055-01-01', 30, '国债OLD'),
        'MID': ('2025-06-01', '2055-06-01', 30, '国债MID'),
        'NEW': ('2026-06-25', '2056-06-25', 30, '国债NEW'),
    })
    row_no_roll = _select_otr_ofr_for_date(df_def, None, 'TBond', '30Y', pd.Timestamp('2026-08-05').date(), prev_otr_id='NEW')
    assert row_no_roll['roll_flag'] is False

    row_roll = _select_otr_ofr_for_date(df_def, None, 'TBond', '30Y', pd.Timestamp('2026-08-05').date(), prev_otr_id='MID')
    assert row_roll['roll_flag'] is True


def _episode_frame(otr_id, start_date, ages_and_spreads):
    rows = []
    for age, spread in ages_and_spreads:
        rows.append({
            'otr_id': otr_id,
            'otr_start_date': pd.Timestamp(start_date),
            'event_age_days': age,
            'spread': spread,
        })
    idx = [pd.Timestamp(start_date) + pd.Timedelta(days=a) for a, _ in ages_and_spreads]
    return pd.DataFrame(rows, index=idx)


def test_segment_episodes_splits_by_otr_id():
    df = pd.concat([
        _episode_frame('EP1', '2025-01-01', [(0, 0.0), (10, 0.01)]),
        _episode_frame('EP2', '2026-01-01', [(0, 0.0), (10, 0.02)]),
    ])
    episodes = segment_episodes(df)
    assert set(episodes.keys()) == {'EP1', 'EP2'}
    assert list(episodes['EP1']['event_age_days']) == [0, 10]


def test_cohort_percentile_causal_excludes_future_and_self_episodes():
    episodes = {
        'EP1': _episode_frame('EP1', '2024-01-01', [(10, 0.01)]),
        'EP2': _episode_frame('EP2', '2024-06-01', [(10, 0.02)]),
        'EP3': _episode_frame('EP3', '2025-01-01', [(10, 0.03)]),
        # EP4 starts AFTER the target (EP3) and must be excluded (no lookahead).
        'EP4': _episode_frame('EP4', '2026-01-01', [(10, 0.10)]),
    }
    result = cohort_percentile_causal(episodes, 'EP3', target_age_days=10, target_spread=0.03, min_episodes=2)
    assert result['n_episodes'] == 2  # EP1, EP2 only — EP3 (self) and EP4 (future) excluded
    assert result['reason'] is None
    assert result['percentile'] == pytest.approx(100.0)  # 0.03 >= both prior values


def test_cohort_percentile_causal_insufficient_episodes():
    episodes = {'EP1': _episode_frame('EP1', '2025-01-01', [(10, 0.01)])}
    result = cohort_percentile_causal(episodes, 'EP1', target_age_days=10, target_spread=0.01, min_episodes=3)
    assert result['reason'] == 'insufficient_episodes'
    assert np.isnan(result['percentile'])


def test_resolve_legs_bond_new_issue_parses_otr_and_ofr1():
    leg1, leg2 = resolve_legs('BondNewIssue', '30Y:2600004.IB|2600002.IB')
    assert (leg1, leg2) == ('2600004.IB', '2600002.IB')


def test_evaluate_gates_full_pass_reaches_order_eligible():
    row = {
        'rejection_reason': None,
        'event_age_days': 30,
        'quote_ok_otr': True,
        'quote_ok_ofr1': True,
        'otr_turnover': 0.01,
        'ofr1_turnover': 0.01,
        'dv01_ratio_ofr1_otr': 1.0,
        'asset_class': 'TBond',
        'tenor_bucket': '30Y',
    }
    result = evaluate_gates(row, entry_percentile=40.0)
    assert result['state'] == 'ORDER_ELIGIBLE'
    assert result['rejections'] == []


def test_evaluate_gates_blocks_on_bucket_not_data_ready():
    row = {
        'rejection_reason': None,
        'event_age_days': 30,
        'quote_ok_otr': True,
        'quote_ok_ofr1': True,
        'otr_turnover': 0.01,
        'ofr1_turnover': 0.01,
        'dv01_ratio_ofr1_otr': 1.0,
        'asset_class': 'CBond',
        'tenor_bucket': '30Y',
    }
    result = evaluate_gates(row)
    assert result['state'] == 'RISK_APPROVED'
    assert any('bucket_not_data_ready' in r for r in result['rejections'])


def test_evaluate_gates_stops_at_constituent_selection_failure():
    row = {'rejection_reason': 'insufficient_bucket_bonds'}
    result = evaluate_gates(row)
    assert result['state'] == 'DISCOVERED'
    assert result['rejections'] == ['constituent_selection:insufficient_bucket_bonds']
