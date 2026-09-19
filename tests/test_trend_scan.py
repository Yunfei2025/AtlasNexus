# -*- coding: utf-8 -*-
"""Tests for curves/calibration/trend_scan.py -- the periodic (monthly/

quarterly) TREND_ROUTED_INSTRUMENTS re-validation scan. Covers the pure
threshold logic and the young-instrument / degenerate-recent-window guards;
does not exercise the live scan_instrument() -> engine_mr/engine_trend path
(that's an integration concern, covered by manually running the module
against real book data -- see the module docstring's Usage section).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from curves.calibration.trend_scan import (
    _MR_MAX_TRADES_FOR_SPARSE, _MR_MAX_SHARPE_FOR_LOSING,
    _TREND_MIN_SHARPE, _TREND_MIN_TRADES, _MIN_TOTAL_OBS,
    _mr_sparse_or_losing, _trend_convincing,
)


# ---------------------------------------------------------------------------
# _mr_sparse_or_losing
# ---------------------------------------------------------------------------

def test_mr_sparse_or_losing_true_when_trade_count_at_or_below_floor():
    result = {'n_trades': _MR_MAX_TRADES_FOR_SPARSE, 'sharpe': 2.0}  # high Sharpe, but too few trades
    assert _mr_sparse_or_losing(result) is True


def test_mr_sparse_or_losing_true_when_sharpe_at_or_below_zero():
    result = {'n_trades': 50, 'sharpe': _MR_MAX_SHARPE_FOR_LOSING}
    assert _mr_sparse_or_losing(result) is True


def test_mr_sparse_or_losing_false_when_active_and_profitable():
    result = {'n_trades': _MR_MAX_TRADES_FOR_SPARSE + 1, 'sharpe': 0.01}
    assert _mr_sparse_or_losing(result) is False


def test_mr_sparse_or_losing_handles_missing_keys_as_zero():
    assert _mr_sparse_or_losing({}) is True  # 0 trades, 0.0 sharpe -> both floors trip


# ---------------------------------------------------------------------------
# _trend_convincing
# ---------------------------------------------------------------------------

def _trend_result(n_trades: int, sharpe: float) -> dict:
    return {'n_trades': n_trades, 'sharpe': sharpe}


def test_trend_convincing_requires_both_windows_to_clear_the_bar():
    full = _trend_result(_TREND_MIN_TRADES, _TREND_MIN_SHARPE)
    recent = _trend_result(_TREND_MIN_TRADES, _TREND_MIN_SHARPE)
    assert _trend_convincing(full, recent) is True


def test_trend_convincing_false_if_full_window_fails():
    full = _trend_result(1, 0.05)  # too few trades, too low Sharpe
    recent = _trend_result(_TREND_MIN_TRADES, _TREND_MIN_SHARPE)
    assert _trend_convincing(full, recent) is False


def test_trend_convincing_false_if_recent_window_fails():
    """A trend that only looked good historically but has since decayed must
    not be promoted -- both windows independently must clear the bar."""
    full = _trend_result(_TREND_MIN_TRADES, _TREND_MIN_SHARPE)
    recent = _trend_result(1, 0.0)
    assert _trend_convincing(full, recent) is False


def test_trend_convincing_false_when_recent_window_defaults_to_empty():
    """scan_instrument's degenerate-recent-window guard falls back to
    {'n_trades': 0, 'sharpe': 0.0} when the recent slice isn't a genuine
    distinct sub-period -- that must never pass _trend_convincing."""
    full = _trend_result(50, 1.0)
    recent = _trend_result(0, 0.0)
    assert _trend_convincing(full, recent) is False


# ---------------------------------------------------------------------------
# scan_instrument: minimum-history and degenerate-recent-window guards
# (these are the actual bugs caught while building this scan: a young
# instrument's tiny trade count masquerading as a trend signal, and the
# recent window silently duplicating the full-history window when there
# isn't enough history before the cutoff)
# ---------------------------------------------------------------------------

def test_min_total_obs_floor_is_well_above_bare_regime_warmup():
    """_MIN_TOTAL_OBS must be materially larger than
    compute_regime_features_dual's own LONG_REGIME_WINDOW+5 (~265 obs)
    warm-up floor -- that floor only guarantees the regime classifier can
    run, not that the full-vs-recent backtest comparison is meaningful for
    a freshly-issued bond with <18 months of history."""
    from curves.calibration.regime import LONG_REGIME_WINDOW
    assert _MIN_TOTAL_OBS > (LONG_REGIME_WINDOW + 5) * 1.5


def test_scan_instrument_returns_none_below_min_total_obs(monkeypatch):
    import curves.calibration.trend_scan as trend_scan

    idx = pd.bdate_range('2026-01-01', periods=_MIN_TOTAL_OBS - 10)
    s = pd.Series(np.linspace(0, 1, len(idx)), index=idx)

    result = trend_scan.scan_instrument('TBondCurve', 'SHORT_HISTORY.IB', s, currently_whitelisted=False)
    assert result is None


def test_scan_instrument_flags_degenerate_recent_window_when_barely_above_floor(monkeypatch):
    """An instrument whose total history clears _MIN_TOTAL_OBS but not by
    enough to leave a genuine pre-cutoff slice must fall back to the
    zero-trade/zero-sharpe recent result and record the guard note, not
    silently reuse the full-history result as 'recent' (which would let
    trend_full == trend_recent trivially satisfy _trend_convincing)."""
    import curves.calibration.trend_scan as trend_scan

    class _StubMR:
        @staticmethod
        def run_spread_backtest(spread_ts, **kwargs):
            return {'n_trades': 0, 'sharpe': -1.0}

    class _StubTrend:
        @staticmethod
        def run_trend_backtest(spread_ts, **kwargs):
            return {'n_trades': 50, 'sharpe': 1.5}

    monkeypatch.setattr('web.tabs.alpha.backtest.engine_mr.run_spread_backtest', _StubMR.run_spread_backtest)
    monkeypatch.setattr('web.tabs.alpha.backtest.engine_trend.run_trend_backtest', _StubTrend.run_trend_backtest)

    # Total history just barely clears _MIN_TOTAL_OBS, but recent_years=3
    # leaves almost nothing before the cutoff -- recent window must be
    # treated as non-distinct, not silently equal to the full window.
    idx = pd.bdate_range('2026-01-01', periods=_MIN_TOTAL_OBS + 5)
    s = pd.Series(np.linspace(0, 1, len(idx)) + np.sin(np.arange(len(idx)) / 10.0), index=idx)

    result = trend_scan.scan_instrument(
        'TBondCurve', 'BARELY_ENOUGH.IB', s, currently_whitelisted=False, recent_years=10,
    )
    assert result is not None
    assert 'recent_window_not_a_distinct_subperiod' in result.notes
    assert result.trend_recent_n_trades == 0
    assert result.trend_recent_sharpe == 0.0
    # trend_full looks great (stubbed) but the degenerate recent window must
    # still block promotion -- recommend_trend_route requires BOTH windows.
    assert result.recommend_trend_route is False


def test_scan_instrument_recommends_when_both_checks_agree(monkeypatch):
    import curves.calibration.trend_scan as trend_scan

    def _fake_run_mr(spread_ts, **kwargs):
        return {'n_trades': 1, 'sharpe': -2.0}

    def _fake_run_trend(spread_ts, **kwargs):
        return {'n_trades': 20, 'sharpe': 1.0}

    monkeypatch.setattr('web.tabs.alpha.backtest.engine_mr.run_spread_backtest', _fake_run_mr)
    monkeypatch.setattr('web.tabs.alpha.backtest.engine_trend.run_trend_backtest', _fake_run_trend)

    # Long enough that recent_years=2 leaves a genuine pre-cutoff slice too.
    idx = pd.bdate_range('2020-01-01', periods=_MIN_TOTAL_OBS + 700)
    trend = np.linspace(0, 5, len(idx))
    s = pd.Series(trend, index=idx)

    result = trend_scan.scan_instrument(
        'TenorSpread', 'SYNTHETIC-TREND', s, currently_whitelisted=False, recent_years=2,
    )
    assert result is not None
    assert 'recent_window_not_a_distinct_subperiod' not in result.notes
    assert result.mr_sparse_or_losing is True
    assert result.trend_convincing is True
    assert result.recommend_trend_route is True


# ---------------------------------------------------------------------------
# print_report / diff logic (pure formatting, exercised via InstrumentScanResult)
# ---------------------------------------------------------------------------

def test_event_driven_types_excluded_from_scan_universe():
    from curves.calibration.trend_scan import _EVENT_DRIVEN_TYPES
    assert 'BondNewIssue' in _EVENT_DRIVEN_TYPES
    assert 'TermBasisEvent' in _EVENT_DRIVEN_TYPES
