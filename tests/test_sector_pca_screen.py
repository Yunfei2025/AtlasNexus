# -*- coding: utf-8 -*-
"""Tests for web/tabs/alpha/sector_pca_screen.py's direction convention and

pair ordering. Regression coverage for a 2026-09-19 bug: the screen had the
BUY/SELL direction inverted (zscore < 0 was treated as oversold/BUY) and
sorted pairs by pass/fail + reason-count first, combined |Z| second --
producing a near-duplicate-tenor cross-product order rather than "most
extreme pair first".

Sign convention under test: `zscore` is a single instrument's own YIELD
residual (spot yield vs. its 2-PC reconstruction). A POSITIVE residual means
yield sits ABOVE the model's prediction -- the instrument is CHEAP (yield
too high / price too low) -> BUY. A NEGATIVE residual means yield sits BELOW
prediction -- RICH (yield too low / price too high) -> SELL. Matches
alpha_candidates.py's composite_z convention ("BUY profits when the spread
falls, so an extreme HIGH z-score is a BUY") applied to a single instrument's
yield-vs-fair-value gap instead of a two-leg spread.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from web.tabs.alpha.sector_pca_screen import (
    screen_sector_pca_pairs, _tenor_years, LegScreen, MIN_ABS_ZSCORE,
)


# ---------------------------------------------------------------------------
# _tenor_years (unaffected by the direction fix, kept as a sanity baseline)
# ---------------------------------------------------------------------------

def test_tenor_years_parses_bond_tickers():
    assert _tenor_years('TBond-10.0Y') == 10.0
    assert _tenor_years('CBond-7.0Y') == 7.0


def test_tenor_years_parses_swap_tickers_not_confused_by_embedded_digits():
    """SHI3MS4Y.IR must parse as 4Y, not 3M (the '3' in SHI3M is not a tenor)."""
    assert _tenor_years('SHI3MS4Y.IR') == 4.0
    assert _tenor_years('FR007S3M.IR') == pytest.approx(0.25)


def test_tenor_years_bare_index_has_no_tenor():
    assert _tenor_years('FR007.IR') is None


# ---------------------------------------------------------------------------
# Direction convention: this is the actual bug under regression test.
# ---------------------------------------------------------------------------

def _make_book(
    n_days: int = 300,
    tickers_and_final_z: "dict[str, float]" = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build a synthetic (stat_info, resid_ts) pair for N tickers, each an

    AR(1) mean-reverting residual series ending near the requested z-score,
    with stationary='YES', a sane halflife, high R^2, and a series shape
    that satisfies _residual_turned (a recent pullback off the extreme).
    """
    rng = np.random.default_rng(7)
    idx = pd.bdate_range('2025-01-01', periods=n_days)
    resid_cols = {}
    stat_rows = {}
    for ticker, target_z in tickers_and_final_z.items():
        vol = 1.0
        # AR(1) path that mean-reverts toward 0, then peaks BEYOND the
        # target z and pulls back TO it over the trailing window, so
        # _residual_turned reads True (today's value is not the window's
        # most-extreme point, and the target itself is the final/current
        # value _screen_leg's z-score reads).
        path = np.zeros(n_days)
        phi = 0.9
        for i in range(1, n_days - 15):
            path[i] = phi * path[i - 1] + rng.normal(0, 0.15)
        target = target_z * vol
        overshoot = target + np.sign(target) * 1.5 * vol
        path[n_days - 15:n_days - 5] = np.linspace(path[n_days - 16], overshoot, 10)
        path[n_days - 5:] = np.linspace(overshoot, target, 5)
        resid_cols[ticker] = path
        stat_rows[ticker] = {
            'mean': 0.0, 'vol': vol, 'ewm_vol': vol,
            'stationary': 'YES', 'halflife': 5.0, 'R2': 0.8,
        }

    resid_ts = pd.DataFrame(resid_cols, index=idx)
    stat_info = pd.DataFrame(stat_rows).T
    return stat_info, resid_ts


def test_positive_zscore_leg_is_buy_negative_is_sell(monkeypatch):
    """Regression test for the inverted-direction bug: an instrument whose
    yield sits ABOVE its PCA-predicted level (positive residual/z, cheap)
    must be the BUY leg; one whose yield sits BELOW prediction (negative
    residual/z, rich) must be the SELL leg."""
    import web.tabs.alpha.sector_pca_screen as mod

    stat_info, resid_ts = _make_book(tickers_and_final_z={
        'CHEAP_HIGH_YIELD': 2.5,    # positive z -> cheap -> BUY
        'RICH_LOW_YIELD': -2.5,     # negative z -> rich -> SELL
    })
    monkeypatch.setattr(mod, 'load_spread_data', lambda st: stat_info)
    monkeypatch.setattr(mod, 'load_spread_timeseries', lambda st: resid_ts)

    candidates = screen_sector_pca_pairs(top_n=3)
    assert len(candidates) == 1
    pair = candidates[0]

    assert pair.cheap.ticker == 'CHEAP_HIGH_YIELD'
    assert pair.cheap.zscore > 0
    assert pair.rich.ticker == 'RICH_LOW_YIELD'
    assert pair.rich.zscore < 0


def test_direction_matches_tbond_shi3m_worked_example(monkeypatch):
    """Reproduces the user's exact worked example: TBond-8.0Y's yield sits
    too LOW (rich, negative residual) -> must be SELL. SHI3MS5Y.IR's rate
    sits too HIGH (cheap, positive residual) -> must be BUY."""
    import web.tabs.alpha.sector_pca_screen as mod

    stat_info, resid_ts = _make_book(tickers_and_final_z={
        'SHI3MS5Y.IR': 1.08,    # too high -> cheap -> BUY
        'TBond-8.0Y': -1.77,    # too low -> rich -> SELL
    })
    monkeypatch.setattr(mod, 'load_spread_data', lambda st: stat_info)
    monkeypatch.setattr(mod, 'load_spread_timeseries', lambda st: resid_ts)
    monkeypatch.setattr(mod, 'MIN_ABS_ZSCORE', 1.0)  # both legs are just above 1.0 in this fixture

    candidates = screen_sector_pca_pairs(top_n=3)
    assert len(candidates) == 1
    pair = candidates[0]
    assert pair.cheap.ticker == 'SHI3MS5Y.IR'
    assert pair.rich.ticker == 'TBond-8.0Y'


# ---------------------------------------------------------------------------
# Pair ordering: most extreme (combined |Z|) first, not pass/fail-grouped.
# ---------------------------------------------------------------------------

def test_pairs_ranked_by_combined_abs_zscore_descending(monkeypatch):
    """With multiple candidates on each side, the returned list must be
    sorted by combined |Z| (cheap + rich) descending -- most extreme pair
    first -- not grouped by pass/fail status first."""
    import web.tabs.alpha.sector_pca_screen as mod

    stat_info, resid_ts = _make_book(tickers_and_final_z={
        'CHEAP_A': 3.0, 'CHEAP_B': 2.2,
        'RICH_A': -3.0, 'RICH_B': -2.1,
    })
    monkeypatch.setattr(mod, 'load_spread_data', lambda st: stat_info)
    monkeypatch.setattr(mod, 'load_spread_timeseries', lambda st: resid_ts)

    candidates = screen_sector_pca_pairs(top_n=4)
    assert len(candidates) >= 2

    combined = [abs(c.cheap.zscore) + abs(c.rich.zscore) for c in candidates]
    assert combined == sorted(combined, reverse=True)

    # The single most extreme pair (CHEAP_A + RICH_A, |Z| sum ~6.0) must be first.
    assert candidates[0].cheap.ticker == 'CHEAP_A'
    assert candidates[0].rich.ticker == 'RICH_A'
