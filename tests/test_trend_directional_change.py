import pandas as pd
import numpy as np

from web.tabs.alpha.backtest.engine_trend import _z_momentum_state


def test_z_momentum_state_handles_inverted_series_without_freezing():
    index = pd.date_range('2026-01-01', periods=180, freq='D')
    base = np.sin(np.arange(180) / 8.0) * 4.0
    drift = np.linspace(-2.0, 3.0, 180)
    raw_spread = pd.Series(base + drift, index=index)

    raw_state, _, _ = _z_momentum_state(raw_spread, theta_z=1.0, mom_window=20, vol_window=60)
    inverted_state, _, _ = _z_momentum_state(-raw_spread, theta_z=1.0, mom_window=20, vol_window=60)

    nonzero = raw_state.ne(0.0) & inverted_state.ne(0.0)
    assert bool(nonzero.any())
    assert ((raw_state[nonzero] + inverted_state[nonzero]).abs() < 1e-9).all()
    assert raw_state.nunique() > 1