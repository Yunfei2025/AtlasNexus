import numpy as np
import pandas as pd

from web.tabs.alpha import scoring as scoring_mod


def _fake_snapshot():
    return pd.DataFrame(
        {
            'Zscore': [-2.1, 1.8, 0.05],
            'carry_roll': [5.0, -3.0, 1.0],
            'vol': [0.02, 0.03, 0.025],
            'spread': [0.01, -0.02, 0.0],
            'mean': [0.0, 0.0, 0.0],
            'halflife': [10.0, 12.0, np.nan],
            'stationary': ['YES', 'YES', 'NO'],
            'category': ['Tenor-Spread'] * 3,
            'spread_type': ['TenorSpread'] * 3,
            'carry_basis_days': [90.0, 90.0, 90.0],
        },
        index=['CHEAP-A', 'RICH-B', 'FLAT-C'],
    )


def _fake_timeseries(n=1300):
    idx = pd.bdate_range('2019-01-01', periods=n)
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            'CHEAP-A': rng.normal(0, 1, n).cumsum() * 0.001,
            'RICH-B': rng.normal(0, 1, n).cumsum() * 0.001,
            'FLAT-C': rng.normal(0, 1, n).cumsum() * 0.001,
        },
        index=idx,
    )


def test_build_default_category_portfolio_direction_from_zscore(monkeypatch):
    monkeypatch.setattr(scoring_mod, 'load_spread_timeseries', lambda st: _fake_timeseries())

    import web.tabs.alpha.data as data_mod
    monkeypatch.setattr(data_mod, 'load_spread_data', lambda st: _fake_snapshot())

    recs = scoring_mod.build_default_category_portfolio('TenorSpread', zscore_min_abs=0.0)
    by_id = {r['ID']: r for r in recs}

    assert set(by_id) == {'CHEAP-A', 'RICH-B', 'FLAT-C'}
    # Negative z (cheap) -> BUY; positive z (rich) -> SELL.
    assert by_id['CHEAP-A']['direction'] == 'BUY'
    assert by_id['RICH-B']['direction'] == 'SELL'

    total_weight = sum(r['weight'] for r in recs)
    assert abs(total_weight - 1.0) < 1e-6
    assert all(r['weight'] > 0 for r in recs)
    assert all(r['spread_type'] == 'TenorSpread' for r in recs)


def test_build_default_category_portfolio_filters_short_history(monkeypatch):
    monkeypatch.setattr(scoring_mod, 'load_spread_timeseries', lambda st: _fake_timeseries(n=200))

    import web.tabs.alpha.data as data_mod
    monkeypatch.setattr(data_mod, 'load_spread_data', lambda st: _fake_snapshot())

    recs = scoring_mod.build_default_category_portfolio('TenorSpread', min_history_days=1200)
    assert recs == []


def test_build_default_category_portfolio_carry_flipped_for_sell(monkeypatch):
    monkeypatch.setattr(scoring_mod, 'load_spread_timeseries', lambda st: _fake_timeseries())

    import web.tabs.alpha.data as data_mod
    monkeypatch.setattr(data_mod, 'load_spread_data', lambda st: _fake_snapshot())

    recs = scoring_mod.build_default_category_portfolio('TenorSpread', zscore_min_abs=0.0)
    by_id = {r['ID']: r for r in recs}

    # RICH-B is SELL; its stored BUY-side carry_roll of -3.0 should be flipped to +3.0.
    assert by_id['RICH-B']['carry_roll'] == 3.0
    # CHEAP-A is BUY; carry_roll stays as-is.
    assert by_id['CHEAP-A']['carry_roll'] == 5.0
