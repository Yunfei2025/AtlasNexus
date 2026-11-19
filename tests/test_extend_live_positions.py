# -*- coding: utf-8 -*-
"""The Portfolio backtest takes the latest month's positions from the live rebuild, replacing
leftovers that older runs left in factor-backtest.pkl after the Train cutoff."""
import pandas as pd
import pytest

import multiasset.factor_model as fm
from web.tabs.beta.callbacks.backtest_hist._signals import extend_with_live_positions


def _live(positions, covers=True):
    df = pd.DataFrame({'position': positions})
    return {'F': df}, {'F': {'covers_latest': covers}}


def test_current_month_is_replaced_and_earlier_rows_kept(monkeypatch):
    idx = pd.bdate_range('2026-10-26', '2026-11-18')
    saved = {'F': pd.Series(0.9, index=idx)}                         # includes stale Nov rows
    live_pos = pd.Series(-0.5, index=pd.bdate_range('2026-10-01', '2026-11-19'))
    monkeypatch.setattr(fm, 'build_live_factor_results', lambda *a, **k: _live(live_pos))
    added = extend_with_live_positions(saved, ['F'])
    s = saved['F']
    assert (s.loc[:'2026-10-30'] == 0.9).all()                       # Train-written rows untouched
    assert (s.loc['2026-11-02':] == -0.5).all()                      # whole latest month from live
    assert s.index.max() == pd.Timestamp('2026-11-19') and added[0][0] == 'F'


def test_without_current_month_model_only_the_tail_is_appended(monkeypatch):
    idx = pd.bdate_range('2026-10-26', '2026-11-18')
    saved = {'F': pd.Series(0.9, index=idx)}
    live_pos = pd.Series(-0.5, index=pd.bdate_range('2026-10-01', '2026-11-19'))
    monkeypatch.setattr(fm, 'build_live_factor_results', lambda *a, **k: _live(live_pos, covers=False))
    extend_with_live_positions(saved, ['F'])
    s = saved['F']
    assert (s.loc[:'2026-11-18'] == 0.9).all() and s.loc['2026-11-19'] == -0.5
