"""Tests for the Beta/Alpha Portfolio Combination card's rolling-correlation
diagnostic (docs/plans/portfolio_construction_beta_alpha.md §5.1).

Covers ``build_combination``'s ``rolling_correlation`` / ``worst_window_correlation``
fields only -- the pre-existing capital-split / margin-ratio math they sit
alongside is unchanged and untested here.
"""
import numpy as np
import pandas as pd

from web.tabs.risk.books import combination as combo_mod


def _beta_result(n, seed=0, start='2024-01-01'):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=n)
    cum = np.cumsum(rng.normal(0, 1.0, n))
    return {
        'equity_series': [{'date': d.isoformat(), 'value': v} for d, v in zip(dates, cum)],
        'total_capital': 1000.0,
    }


def _alpha_result(n, seed=1, start='2024-01-01'):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=n)
    cum_bp = np.cumsum(rng.normal(0, 50.0, n))
    return {
        'equity_ts': pd.Series(cum_bp, index=dates),
        'instruments': [
            {'ID': 'A', 'spread_type': 'TenorSpread', 'weight': 0.5},
            {'ID': 'B', 'spread_type': 'TenorSpread', 'weight': 0.5},
        ],
    }


def _patch_margin(monkeypatch):
    """Stub the duration/margin lookups build_combination reaches into, so the
    test doesn't depend on real market data being available."""
    import web.tabs.alpha.data as alpha_data
    monkeypatch.setattr(alpha_data, '_get_duration_mult', lambda inst_id, stype: 5.0)
    monkeypatch.setattr(alpha_data, 'estimate_margin_mm', lambda notional_mm, duration: 0.02 * notional_mm * duration)


def test_rolling_correlation_present_with_enough_history(monkeypatch):
    _patch_margin(monkeypatch)
    n = 300  # comfortably above ROLLING_CORR_WINDOW (120)
    result = combo_mod.build_combination(
        _beta_result(n), _alpha_result(n), total_capital_mm=1000.0, alpha_margin_share=0.3,
    )

    assert 'error' not in result
    assert result['rolling_correlation'] is not None
    assert not result['rolling_correlation'].empty
    assert result['rolling_correlation_window'] == combo_mod.ROLLING_CORR_WINDOW
    assert result['rolling_correlation_flag'] == combo_mod.ROLLING_CORR_FLAG

    worst = result['worst_window_correlation']
    assert worst is not None
    assert -1.0 <= worst <= 1.0
    # worst-window is the max of the rolling series, not an independent stat.
    assert worst == result['rolling_correlation'].max()


def test_rolling_correlation_none_below_window_but_above_floor(monkeypatch):
    _patch_margin(monkeypatch)
    n = 80  # >= build_combination's 60-day full-sample floor, < 120d rolling window
    result = combo_mod.build_combination(
        _beta_result(n), _alpha_result(n), total_capital_mm=1000.0, alpha_margin_share=0.3,
    )

    assert 'error' not in result
    # daily returns lose one observation to diff().dropna(), so n_days is n-1.
    assert result['n_days'] == n - 1
    assert result['rolling_correlation'] is None
    assert result['worst_window_correlation'] is None
    # Full-sample correlation is still computed even without a rolling view.
    assert -1.0 <= result['correlation'] <= 1.0


def test_rolling_correlation_flags_a_known_spike(monkeypatch):
    """A rolling window realigned to move in lockstep with beta should read a
    correlation right at the top of the window it dominates, clearing the
    flag threshold -- a sanity check that the rolling calc actually tracks a
    real relationship, not just noise."""
    _patch_margin(monkeypatch)
    n = 260
    rng = np.random.default_rng(2)
    dates = pd.bdate_range('2024-01-01', periods=n)

    beta_daily = rng.normal(0, 1.0, n)
    beta_result = {
        'equity_series': [{'date': d.isoformat(), 'value': v}
                           for d, v in zip(dates, np.cumsum(beta_daily))],
        'total_capital': 1000.0,
    }

    # Alpha mirrors beta's daily moves exactly over the back half of the
    # series (in bp terms), and is independent noise over the front half.
    alpha_daily_bp = rng.normal(0, 50.0, n)
    mirror_from = n - combo_mod.ROLLING_CORR_WINDOW
    alpha_daily_bp[mirror_from:] = beta_daily[mirror_from:] * 50.0
    alpha_result = {
        'equity_ts': pd.Series(np.cumsum(alpha_daily_bp), index=dates),
        'instruments': [{'ID': 'A', 'spread_type': 'TenorSpread', 'weight': 1.0}],
    }

    result = combo_mod.build_combination(
        beta_result, alpha_result, total_capital_mm=1000.0, alpha_margin_share=0.3,
    )

    assert 'error' not in result
    assert result['worst_window_correlation'] >= combo_mod.ROLLING_CORR_FLAG
