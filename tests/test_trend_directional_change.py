import pandas as pd

from web.tabs.alpha.backtest.engine_trend import _dc_trend_state


def test_relative_dc_state_handles_inverted_series_without_freezing():
    index = pd.date_range('2026-01-01', periods=5, freq='D')
    raw_spread = pd.Series([100.0, 90.0, 100.0, 110.0, 120.0], index=index)

    raw_state = _dc_trend_state(raw_spread, theta=0.03)
    inverted_state = _dc_trend_state(-raw_spread, theta=0.03)

    assert raw_state.iloc[-1] == 1.0
    assert inverted_state.iloc[-1] == -1.0
    assert inverted_state.nunique() > 1