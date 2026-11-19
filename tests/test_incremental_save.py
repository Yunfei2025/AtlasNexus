# -*- coding: utf-8 -*-
"""Backtest saves are incremental (2026-11-19): a new run is spliced onto the saved one by
date, the new run wins on overlapping days, and nothing older is dropped."""
import numpy as np
import pandas as pd
import pytest

import multiasset.storage as st
from multiasset.factor_backtest import merge_factor_frames
from multiasset.storage import merge_backtest_results


def _result(start, end, daily, capital=100.0, mode='factor_scaling', cash=0.002, pool=('A',)):
    idx = pd.bdate_range(start, end)
    pnl = pd.Series(daily(idx), index=idx)
    cum = pnl.cumsum()
    return {
        'sharpe': 1.0, 'annualized_return': 0.05, 'max_drawdown': -0.02,
        'asset_pool': list(pool), 'total_capital': capital, 'alloc_mode': mode,
        'start_date': start, 'end_date': end,
        'equity_series': [{'date': d.strftime('%Y-%m-%d'), 'value': float(v)} for d, v in cum.items()],
        'cash_benchmark': [{'date': d.strftime('%Y-%m-%d'), 'value': cash} for d in idx],
    }


def _pnl(res):
    s = pd.Series([r['value'] for r in res['equity_series']],
                  index=pd.to_datetime([r['date'] for r in res['equity_series']]))
    p = s.diff(); p.iloc[0] = s.iloc[0]
    return p


def test_first_save_is_stored_as_is():
    new = _result('2024-01-01', '2024-03-29', lambda i: np.ones(len(i)))
    out = merge_backtest_results(None, new)
    assert out['merge_info']['mode'] == 'fresh' and out['equity_series'] == new['equity_series']


def test_overlap_is_overwritten_and_older_days_kept():
    old = _result('2024-01-01', '2024-06-28', lambda i: np.full(len(i), 1.0))
    new = _result('2024-05-01', '2024-09-30', lambda i: np.full(len(i), 3.0))
    out = merge_backtest_results(old, new)
    p = _pnl(out)
    assert out['start_date'] == '2024-01-01' and out['end_date'] == '2024-09-30'
    assert (p.loc[:'2024-04-30'] == 1.0).all()            # old-only days untouched
    assert (p.loc['2024-05-01':] == 3.0).all()            # overlap + new days = new run
    # cumulative is continuous across the splice (not restarted at the new run's start)
    cum = pd.Series([r['value'] for r in out['equity_series']])
    assert (cum.diff().dropna() > 0).all()
    assert cum.iloc[-1] == pytest.approx(p.sum())
    info = out['merge_info']
    assert info['mode'] == 'merged' and info['runs'] == 2
    assert info['overwrote_days'] == len(pd.bdate_range('2024-05-01', '2024-06-28'))
    assert info['gaps'] == []


def test_run_before_the_saved_range_is_prepended():
    old = _result('2024-06-03', '2024-09-30', lambda i: np.full(len(i), 2.0))
    new = _result('2024-01-01', '2024-03-29', lambda i: np.full(len(i), 1.0))
    out = merge_backtest_results(old, new)
    assert out['start_date'] == '2024-01-01' and out['end_date'] == '2024-09-30'
    assert _pnl(out).loc['2024-06-03':].eq(2.0).all()
    assert out['merge_info']['gaps']                       # Apr-May is missing -> reported


def test_gap_contributes_no_pnl():
    old = _result('2023-01-02', '2023-03-31', lambda i: np.ones(len(i)))
    new = _result('2024-01-01', '2024-03-29', lambda i: np.ones(len(i)))
    out = merge_backtest_results(old, new)
    assert out['merge_info']['gaps'] == [['2023-03-31', '2024-01-01']]
    p = _pnl(out)
    assert p.sum() == pytest.approx(len(old['equity_series']) + len(new['equity_series']))


@pytest.mark.parametrize('field,value', [('capital', 50.0), ('mode', 'risk_parity')])
def test_incompatible_results_are_replaced_not_mixed(field, value):
    old = _result('2024-01-01', '2024-03-29', lambda i: np.ones(len(i)))
    kw = {'capital': value} if field == 'capital' else {'mode': value}
    new = _result('2024-04-01', '2024-06-28', lambda i: np.ones(len(i)), **kw)
    out = merge_backtest_results(old, new)
    assert out['merge_info']['mode'] == 'fresh' and out['merge_info']['reason']
    assert out['start_date'] == '2024-04-01'


def test_old_save_without_mode_still_merges_and_pool_is_unioned():
    old = _result('2024-01-01', '2024-03-29', lambda i: np.ones(len(i)), pool=('A', 'B'))
    old.pop('alloc_mode')
    new = _result('2024-03-01', '2024-06-28', lambda i: np.ones(len(i)), pool=('B', 'C'))
    out = merge_backtest_results(old, new)
    assert out['merge_info']['mode'] == 'merged' and out['asset_pool'] == ['A', 'B', 'C']


def test_partial_cash_benchmark_is_dropped_not_zero_filled():
    old = _result('2024-01-01', '2024-03-29', lambda i: np.ones(len(i)))
    old.pop('cash_benchmark')
    new = _result('2024-03-01', '2024-06-28', lambda i: np.ones(len(i)))
    out = merge_backtest_results(old, new)
    assert 'cash_benchmark' not in out and out['merge_info']['cash_note']


def test_merged_stats_use_the_merged_curve():
    rng = np.random.default_rng(0)
    old = _result('2024-01-01', '2024-06-28', lambda i: rng.normal(0.05, 0.2, len(i)))
    new = _result('2024-05-01', '2024-12-31', lambda i: rng.normal(0.05, 0.2, len(i)))
    new['sharpe'] = 99.0
    out = merge_backtest_results(old, new)
    assert out['sharpe'] != 99.0 and np.isfinite(out['sharpe'])
    assert out['merge_info']['last_run']['sharpe'] == 99.0


def test_save_writes_history_per_run_and_a_merged_last(tmp_path, monkeypatch):
    monkeypatch.setattr(st, 'BACKTEST_DIR', tmp_path)
    monkeypatch.setattr(st, 'LAST_BACKTEST_FILE', tmp_path / 'last.json')
    r1 = _result('2024-01-01', '2024-06-28', lambda i: np.ones(len(i)))
    r2 = _result('2024-05-01', '2024-09-30', lambda i: np.full(len(i), 2.0))
    for r in (r1, r2):
        st.save_backtest_result(r['equity_series'], r['sharpe'], r['annualized_return'], r['max_drawdown'],
                                r['asset_pool'], r['total_capital'], r['start_date'], r['end_date'],
                                r['cash_benchmark'], alloc_mode=r['alloc_mode'])
    last = st.load_last_backtest_result()
    assert last['start_date'] == '2024-01-01' and last['end_date'] == '2024-09-30'
    assert 'merged' in st.describe_last_save()
    kinds = [p.name for p in tmp_path.glob('backtest_*.json')]
    assert len(kinds) >= 1                                  # run snapshots kept (same-second names may collide)
    st.save_backtest_result(r2['equity_series'], 1, 0, 0, ['A'], r2['total_capital'], r2['start_date'],
                            r2['end_date'], merge_with_last=False)
    assert st.load_last_backtest_result()['start_date'] == '2024-05-01'     # opt-out replaces


def test_factor_frames_merge_rebuilds_cumulative():
    idx1 = pd.bdate_range('2024-01-01', periods=100)
    idx2 = pd.bdate_range(idx1[60], periods=100)
    mk = lambda idx, v: pd.DataFrame({'strategy_returns': v, 'position': 0.5,
                                      'cumulative_returns': (1 + pd.Series(v, index=idx)).cumprod()}, index=idx)
    prev, new = mk(idx1, 0.001), mk(idx2, 0.002)
    m = merge_factor_frames(prev, new)
    assert len(m) == len(idx1.union(idx2))
    assert (m.loc[idx2[0]:, 'strategy_returns'] == 0.002).all()               # new wins on overlap
    assert (m.loc[:idx1[59], 'strategy_returns'] == 0.001).all()
    expect = (1 + m['strategy_returns']).cumprod()
    assert np.allclose(m['cumulative_returns'], expect)                       # no restart at the splice
