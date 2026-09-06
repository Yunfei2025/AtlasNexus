# -*- coding: utf-8 -*-
"""Phase 7 tests for docs/dev/tbondcurve-30y-otr-ofr-plan.md (BondNewIssue).

Covers: instrument ID parsing/legs, point-in-time NIB (issuance) vs
turnover-based OTR/OFR-ladder selection, rank persistence, existence-of-lag,
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
    """rows: {bond_id: (start_date, maturity_date, orig_term, name, turnover)}
    `turnover` is expressed as 成交量:万元 with 债券余额:亿 fixed at 100.0 —
    tests only care about relative ordering, not absolute values.
    """
    data = {
        '起息日期': {}, '到期日期': {}, '期限': {}, '证券全称': {},
        '债券余额:亿': {}, '成交量:万元': {}, '修正久期': {}, '收盘价:元（全价）': {},
        '估价收益率:%(中债)': {},
    }
    for bond_id, (start, maturity, term, name, turnover) in rows.items():
        data['起息日期'][bond_id] = pd.Timestamp(start)
        data['到期日期'][bond_id] = pd.Timestamp(maturity)
        data['期限'][bond_id] = term
        data['证券全称'][bond_id] = name
        data['债券余额:亿'][bond_id] = 100.0
        data['成交量:万元'][bond_id] = turnover
        data['修正久期'][bond_id] = 25.0
        data['收盘价:元（全价）'][bond_id] = 100.0
        data['估价收益率:%(中债)'][bond_id] = 3.0
    return pd.DataFrame(data)


def test_bucket_candidates_filters_by_original_term_and_outstanding():
    df_def = _make_def({
        'A': ('2020-01-01', '2050-01-01', 30, '国债A', 10.0),   # 30Y, outstanding
        'B': ('2021-01-01', '2031-01-01', 10, '国债B', 10.0),   # wrong bucket (10Y)
        'C': ('2026-01-01', '2056-01-01', 30, '国开债C', 10.0),  # wrong asset (CBond)
        'D': ('2030-01-01', '2060-01-01', 30, '国债D', 10.0),    # not started yet
    })
    cands = _bucket_candidates(df_def, 'TBond', '30Y', pd.Timestamp('2026-08-05').date())
    assert list(cands) == ['A']


def test_select_otr_ofr_distinguishes_nib_from_turnover_based_otr():
    """NIB (newest issuance) need not be OTR (turnover leader) — a fresh issue
    that hasn't yet gathered liquidity should not be confused with the
    incumbent on-the-run bond."""
    df_def = _make_def({
        'NIB': ('2026-06-25', '2056-06-25', 30, '国债NIB', 100.0),     # newest, thin volume
        'INCUMBENT': ('2025-01-01', '2055-01-01', 30, '国债INC', 15000.0),  # still most liquid
        'OFR2': ('2024-01-01', '2054-01-01', 30, '国债OFR2', 8000.0),
    })
    df_def.loc['NIB', '估价收益率:%(中债)'] = 2.10
    df_def.loc['INCUMBENT', '估价收益率:%(中债)'] = 2.00
    df_def.loc['OFR2', '估价收益率:%(中债)'] = 1.95

    row = _select_otr_ofr_for_date(df_def, None, 'TBond', '30Y', pd.Timestamp('2026-08-05').date())
    assert row['nib_id'] == 'NIB'
    assert row['otr_id'] == 'INCUMBENT'  # turnover leader, not the newest issue
    assert row['ofr1_id'] == 'OFR2'
    assert row['rejection_reason'] is None
    assert row['spread_nib_otr'] == pytest.approx(2.10 - 2.00)
    assert row['spread_otr_ofr1'] == pytest.approx(2.00 - 1.95)
    assert row['lag_exists'] is True  # big turnover gap between NIB and OTR
    assert row['instrument_id_nib_otr'] == instrument_id('30Y', 'nib_otr', 'NIB', 'INCUMBENT')
    assert row['instrument_id_otr_ofr1'] == instrument_id('30Y', 'otr_ofr1', 'INCUMBENT', 'OFR2')


def test_select_otr_ofr_no_lag_when_nib_already_leads_turnover():
    """If a new issue is absorbed into liquidity immediately, NIB and OTR
    coincide and there is no migration lag to trade (Stage 1's precondition)."""
    df_def = _make_def({
        'NIB': ('2026-06-25', '2056-06-25', 30, '国债NIB', 80.0),   # newest AND most liquid
        'OFR1': ('2025-01-01', '2055-01-01', 30, '国债OFR1', 20.0),
    })
    row = _select_otr_ofr_for_date(df_def, None, 'TBond', '30Y', pd.Timestamp('2026-08-05').date())
    assert row['nib_id'] == 'NIB'
    assert row['otr_id'] == 'NIB'
    assert row['lag_exists'] is False


def test_select_otr_ofr_reports_insufficient_bucket_bonds():
    df_def = _make_def({'ONLY': ('2026-01-01', '2056-01-01', 30, '国债ONLY', 10.0)})
    row = _select_otr_ofr_for_date(df_def, None, 'TBond', '30Y', pd.Timestamp('2026-08-05').date())
    assert row['rejection_reason'] == 'insufficient_bucket_bonds'
    assert pd.isna(row['nib_id'])


def _history_row(otr_raw_id, otr_id, since_date):
    return {
        'otr_raw_id': otr_raw_id, 'otr_id': otr_id, 'otr_since_date': pd.Timestamp(since_date),
    }


def test_otr_promotion_requires_persistent_turnover_leadership():
    """A one-day turnover spike must not immediately flip the confirmed OTR —
    the challenger must lead for OTR_RANK_PERSISTENCE_DAYS consecutive rows."""
    df_def = _make_def({
        'OLD': ('2025-01-01', '2055-01-01', 30, '国债OLD', 10.0),
        'CHALLENGER': ('2025-06-01', '2055-06-01', 30, '国债CHA', 90.0),  # today's raw leader
        'NIB': ('2026-06-25', '2056-06-25', 30, '国债NIB', 5.0),
    })
    # History: OLD confirmed as OTR for a while; CHALLENGER only just started
    # raw-leading today (no prior persistence yet) -> should NOT be promoted.
    history_df = pd.DataFrame([
        _history_row('OLD', 'OLD', '2025-07-01'),
        _history_row('OLD', 'OLD', '2025-07-02'),
    ])
    row = _select_otr_ofr_for_date(df_def, None, 'TBond', '30Y', pd.Timestamp('2025-07-03').date(), history_df)
    assert row['otr_id'] == 'OLD'
    assert row['otr_roll_flag'] is False

    # Once CHALLENGER has raw-led for the required number of consecutive prior
    # rows too, the confirmed OTR should roll over.
    history_df_persisted = pd.DataFrame([
        _history_row('CHALLENGER', 'OLD', '2025-07-01'),
        _history_row('CHALLENGER', 'OLD', '2025-07-02'),
    ])
    row2 = _select_otr_ofr_for_date(df_def, None, 'TBond', '30Y', pd.Timestamp('2025-07-03').date(), history_df_persisted)
    assert row2['otr_id'] == 'CHALLENGER'
    assert row2['otr_roll_flag'] is True


def _episode_frame(episode_id, group_col, start_col, start_date, age_col, spread_col, ages_and_spreads):
    rows = []
    for age, spread in ages_and_spreads:
        rows.append({
            group_col: episode_id,
            start_col: pd.Timestamp(start_date),
            age_col: age,
            spread_col: spread,
        })
    idx = [pd.Timestamp(start_date) + pd.Timedelta(days=a) for a, _ in ages_and_spreads]
    return pd.DataFrame(rows, index=idx)


def test_segment_episodes_splits_by_otr_id():
    df = pd.concat([
        _episode_frame('EP1', 'otr_id', 'otr_since_date', '2025-01-01', 'otr_rank_age_days', 'spread_otr_ofr1', [(0, 0.0), (10, 0.01)]),
        _episode_frame('EP2', 'otr_id', 'otr_since_date', '2026-01-01', 'otr_rank_age_days', 'spread_otr_ofr1', [(0, 0.0), (10, 0.02)]),
    ])
    episodes = segment_episodes(df, group_col='otr_id')
    assert set(episodes.keys()) == {'EP1', 'EP2'}
    assert list(episodes['EP1']['otr_rank_age_days']) == [0, 10]


def test_cohort_percentile_causal_excludes_future_and_self_episodes():
    episodes = {
        'EP1': _episode_frame('EP1', 'otr_id', 'otr_since_date', '2024-01-01', 'otr_rank_age_days', 'spread_otr_ofr1', [(10, 0.01)]),
        'EP2': _episode_frame('EP2', 'otr_id', 'otr_since_date', '2024-06-01', 'otr_rank_age_days', 'spread_otr_ofr1', [(10, 0.02)]),
        'EP3': _episode_frame('EP3', 'otr_id', 'otr_since_date', '2025-01-01', 'otr_rank_age_days', 'spread_otr_ofr1', [(10, 0.03)]),
        # EP4 starts AFTER the target (EP3) and must be excluded (no lookahead).
        'EP4': _episode_frame('EP4', 'otr_id', 'otr_since_date', '2026-01-01', 'otr_rank_age_days', 'spread_otr_ofr1', [(10, 0.10)]),
    }
    result = cohort_percentile_causal(episodes, 'EP3', target_age_days=10, target_spread=0.03, min_episodes=2)
    assert result['n_episodes'] == 2  # EP1, EP2 only — EP3 (self) and EP4 (future) excluded
    assert result['reason'] is None
    assert result['percentile'] == pytest.approx(100.0)  # 0.03 >= both prior values


def test_cohort_percentile_causal_insufficient_episodes():
    episodes = {'EP1': _episode_frame('EP1', 'otr_id', 'otr_since_date', '2025-01-01', 'otr_rank_age_days', 'spread_otr_ofr1', [(10, 0.01)])}
    result = cohort_percentile_causal(episodes, 'EP1', target_age_days=10, target_spread=0.01, min_episodes=3)
    assert result['reason'] == 'insufficient_episodes'
    assert np.isnan(result['percentile'])


def test_resolve_legs_bond_new_issue_parses_stage_and_legs():
    leg1, leg2 = resolve_legs('BondNewIssue', '30Y:otr_ofr1:2600004.IB|2600002.IB')
    assert (leg1, leg2) == ('2600004.IB', '2600002.IB')

    leg1b, leg2b = resolve_legs('BondNewIssue', '30Y:nib_otr:2600006.IB|2600004.IB')
    assert (leg1b, leg2b) == ('2600006.IB', '2600004.IB')


def test_evaluate_gates_full_pass_reaches_order_eligible():
    row = {
        'rejection_reason': None,
        'otr_rank_age_days': 30,
        'quote_ok_otr': True,
        'quote_ok_ofr1': True,
        'dv01_ratio': 1.0,
        'asset_class': 'TBond',
        'tenor_bucket': '30Y',
    }
    result = evaluate_gates(row, entry_percentile=40.0, stage='otr_ofr1')
    assert result['state'] == 'ORDER_ELIGIBLE'
    assert result['rejections'] == []


def test_evaluate_gates_blocks_on_bucket_not_data_ready():
    row = {
        'rejection_reason': None,
        'otr_rank_age_days': 30,
        'quote_ok_otr': True,
        'quote_ok_ofr1': True,
        'dv01_ratio': 1.0,
        'asset_class': 'CBond',
        'tenor_bucket': '30Y',
    }
    result = evaluate_gates(row, stage='otr_ofr1')
    assert result['state'] == 'RISK_APPROVED'
    assert any('bucket_not_data_ready' in r for r in result['rejections'])


def test_evaluate_gates_stops_at_constituent_selection_failure():
    row = {'rejection_reason': 'insufficient_bucket_bonds'}
    result = evaluate_gates(row)
    assert result['state'] == 'DISCOVERED'
    assert result['rejections'] == ['constituent_selection:insufficient_bucket_bonds']


def test_evaluate_gates_nib_otr_blocks_without_lag():
    row = {
        'rejection_reason': None,
        'nib_age_days': 10,
        'lag_exists': False,
        'quote_ok_nib': True,
        'quote_ok_otr': True,
        'dv01_ratio': 1.0,
        'asset_class': 'TBond',
        'tenor_bucket': '30Y',
    }
    result = evaluate_gates(row, stage='nib_otr')
    assert result['state'] == 'DATA_VALIDATED'
    assert result['rejections'] == ['signal_ready:no_lag']


def test_evaluate_gates_nib_otr_passes_with_lag():
    row = {
        'rejection_reason': None,
        'nib_age_days': 10,
        'lag_exists': True,
        'quote_ok_nib': True,
        'quote_ok_otr': True,
        'dv01_ratio': 1.0,
        'asset_class': 'TBond',
        'tenor_bucket': '30Y',
    }
    result = evaluate_gates(row, entry_percentile=40.0, stage='nib_otr')
    assert result['state'] == 'ORDER_ELIGIBLE'
    assert result['rejections'] == []



def test_add_ofr_ladder_spreads_computes_each_rung_vs_ofr1():
    """spread_ofr{k}_ofr1 = ytm_ofr{k} - ytm_ofr1 for every rung k=2..depth,
    with instrument_id following the same <tenor>:<stage>:<leg1>|<leg2>
    convention as spread_otr_ofr1."""
    from curves.calibration.otr_ofr_universe import _add_ofr_ladder_spreads
    from settings.fixed_income import NewIssueConfig

    row = {'ytm_ofr1': 2.0}
    confirmed = {1: 'OFR1_BOND'}
    for k in range(2, NewIssueConfig.OFR_LADDER_DEPTH + 1):
        row[f'ytm_ofr{k}'] = 2.0 + 0.1 * k
        confirmed[k] = f'OFR{k}_BOND'

    _add_ofr_ladder_spreads(row, confirmed, '30Y')

    for k in range(2, NewIssueConfig.OFR_LADDER_DEPTH + 1):
        assert row[f'spread_ofr{k}_ofr1'] == pytest.approx(0.1 * k)
        assert row[f'instrument_id_ofr{k}_ofr1'] == f'30Y:ofr{k}_ofr1:OFR{k}_BOND|OFR1_BOND'


def test_add_ofr_ladder_spreads_skips_self_match_and_missing_rungs():
    """A rung that collapses onto OFR1 itself, or has no confirmed bond yet,
    must contribute NaN -- never a synthetic self-spread."""
    from curves.calibration.otr_ofr_universe import _add_ofr_ladder_spreads

    row = {'ytm_ofr1': 2.0, 'ytm_ofr2': 2.0}  # ofr2 collapses onto ofr1's yield too
    confirmed = {1: 'SAME_BOND', 2: 'SAME_BOND'}  # and the SAME bond id
    _add_ofr_ladder_spreads(row, confirmed, '30Y')
    assert pd.isna(row['spread_ofr2_ofr1'])
    assert pd.isna(row['instrument_id_ofr2_ofr1'])

    row2 = {'ytm_ofr1': 2.0}  # ofr3 never confirmed (no ytm_ofr3, no id)
    confirmed2 = {1: 'OFR1_BOND'}
    _add_ofr_ladder_spreads(row2, confirmed2, '30Y')
    assert pd.isna(row2['spread_ofr3_ofr1'])
    assert pd.isna(row2['instrument_id_ofr3_ofr1'])


def test_ofr_ladder_bucket_excluded_from_tbondcurve_pairs():
    """(TBond, 30Y) must never contribute mature-RV pair rows to TBondCurve --
    that data moved to the New-Issue OTR/OFR Event tab as its own
    OFR{k}OFR1-CGB30Y stage family (curves/refreshers/newissue_spreads.py)."""
    from curves.refreshers.otr_ofr_rv import _EXCLUDED_BUCKETS
    assert ('TBond', '30Y') in _EXCLUDED_BUCKETS


def test_ofr_ladder_stage_scoped_to_tbond_30y_only():
    """ofr{k}_ofr1 stages must be gated to (TBond, 30Y) -- 5Y/10Y TBond and
    every CBond bucket keep using the old TBondCurve/CBondCurve mature-RV
    pairs unchanged."""
    from curves.refreshers.newissue_spreads import _stage_scope_ok, _STAGES
    from settings.fixed_income import NewIssueConfig

    assert 'ofr2_ofr1' in _STAGES
    assert _stage_scope_ok('ofr2_ofr1', 'TBond', '30Y') is True
    assert _stage_scope_ok('ofr2_ofr1', 'TBond', '10Y') is False
    assert _stage_scope_ok('ofr2_ofr1', 'CBond', '30Y') is False
    # The original two stages are unscoped (every active bucket).
    assert _stage_scope_ok('otr_ofr1', 'TBond', '10Y') is True
    assert _stage_scope_ok('nib_otr', 'CBond', '5Y') is True


def test_ofr_ladder_label_round_trip():
    """to_newissue_stage_label / _parse_newissue_stage_label must round-trip
    OFR{k}OFR1-{issuer}{tenor} labels the same way OTROFR1/NIBOTR already do."""
    from web.tabs.alpha.data.loaders import (
        to_newissue_stage_label, _parse_newissue_stage_label, _newissue_stage_columns,
    )

    raw = '30Y:ofr2_ofr1:2500006.IB|2600002.IB'
    label = to_newissue_stage_label(raw)
    assert label == 'OFR2OFR1-CGB30Y'

    parsed = _parse_newissue_stage_label(label)
    assert parsed == ('ofr2_ofr1', '30Y', 'CGB')

    # OFR1 is always the reference leg (leg2), matching spread_ofr{k}_ofr1's
    # ytm_ofr{k} - ytm_ofr1 convention in otr_ofr_universe.py.
    leg1_ytm, leg2_ytm, leg1_id, leg2_id = _newissue_stage_columns('ofr3_ofr1')
    assert (leg1_ytm, leg2_ytm, leg1_id, leg2_id) == ('ytm_ofr3', 'ytm_ofr1', 'ofr3_id', 'ofr1_id')


def test_ofr_ladder_label_unqualified_issuer():
    from web.tabs.alpha.data.loaders import _parse_newissue_stage_label
    parsed = _parse_newissue_stage_label('OFR5OFR1-30Y')
    assert parsed == ('ofr5_ofr1', '30Y', None)


def test_short_newissue_label_ofr_ladder_no_underscore():
    """web/core/scripts.py's _short_newissue_label is a SEPARATE implementation
    from web/tabs/alpha/data/loaders.py's to_newissue_stage_label (used by the
    Daily Spread Statistics bar chart, not the Spread Time Series chart) and
    had its own stage_map that only knew nib_otr/otr_ofr1, falling back to
    stage.replace('_','').upper()/stage.upper() for anything else -- for
    'ofr2_ofr1' that gave 'OFR2_OFR1' (underscore kept from stage.upper()
    alone) instead of the intended 'OFR2OFR1'."""
    from web.core.scripts import _short_newissue_label

    label = _short_newissue_label('30Y:ofr2_ofr1:2500006.IB|2600002.IB', 'CGB')
    assert label == 'OFR2OFR1-CGB30Y'
    assert '_' not in label

    for k in (3, 4, 5):
        label_k = _short_newissue_label(f'30Y:ofr{k}_ofr1:A.IB|B.IB', 'CGB')
        assert label_k == f'OFR{k}OFR1-CGB30Y'


def test_load_newissue_current_episode_returns_pair_label(tmp_path, monkeypatch):
    """load_newissue_current_episode must return (series, 'leg1|leg2') so
    callers (the Spread Time Series chart) can show the actual bond codes
    even when load_newissue_pair_history's richer cvpx.pkl lookup comes up
    empty -- which it always does for legs outside the standard pricing
    universe (e.g. 30Y OFR-ladder bonds, capped at
    BondConfig.PRICING_MAX_TTM=10.0)."""
    import web.tabs.alpha.data.loaders as loaders

    idx = pd.date_range('2026-08-01', periods=5, freq='D')
    df = pd.DataFrame({
        'ofr2_id': ['A.IB', 'A.IB', 'A.IB', 'A.IB', 'A.IB'],
        'ofr1_id': ['B.IB', 'B.IB', 'B.IB', 'B.IB', 'B.IB'],
        'ytm_ofr2': [2.0, 2.0, 2.0, 2.0, 2.0],
        'ytm_ofr1': [1.9, 1.9, 1.9, 1.9, 1.9],
    }, index=idx)

    monkeypatch.setattr(loaders, '_load_pickle_safe',
                        lambda path: {'30Y': df} if 'TBond-newissue' in str(path) else None)

    result = loaders.load_newissue_current_episode('OFR2OFR1-CGB30Y')
    assert result is not None
    s, pair_label = result
    assert pair_label == 'A.IB|B.IB'
    assert len(s) == 5


def test_load_newissue_current_episode_skips_self_match():
    """A trailing run where the OFR rung has collapsed onto OFR1 itself
    (leg1_id == leg2_id) must not be reported as the 'current episode' --
    the function should resolve to the last genuinely distinct pairing
    instead of a meaningless self-spread."""
    import web.tabs.alpha.data.loaders as loaders

    idx = pd.date_range('2026-08-01', periods=6, freq='D')
    df = pd.DataFrame({
        'ofr2_id':  ['A.IB', 'A.IB', 'A.IB', 'A.IB', 'C.IB', 'C.IB'],
        'ofr1_id':  ['B.IB', 'B.IB', 'B.IB', 'B.IB', 'C.IB', 'C.IB'],
        'ytm_ofr2': [2.0,    2.0,    2.0,    2.0,    2.1,    2.1],
        'ytm_ofr1': [1.9,    1.9,    1.9,    1.9,    2.1,    2.1],
    }, index=idx)

    import types
    def _fake_load(path):
        return {'30Y': df} if 'TBond-newissue' in str(path) else None

    orig = loaders._load_pickle_safe
    loaders._load_pickle_safe = _fake_load
    try:
        result = loaders.load_newissue_current_episode('OFR2OFR1-CGB30Y')
    finally:
        loaders._load_pickle_safe = orig

    assert result is not None
    s, pair_label = result
    assert pair_label == 'A.IB|B.IB'
    assert len(s) == 4
