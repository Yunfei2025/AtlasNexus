from dash import Dash

from web.tabs.beta.callbacks import register_multiasset_callbacks
from web.tabs.beta.callbacks.backtest_futures import register_backtest_futures_callbacks


def test_multiasset_callbacks_are_idempotent():
    app = Dash(__name__)

    register_multiasset_callbacks(app)
    before = len(app.callback_map)

    register_multiasset_callbacks(app)

    assert len(app.callback_map) == before
    assert app._atlasnexus_multiasset_callbacks_registered is True

    futures_app = Dash(__name__)
    register_backtest_futures_callbacks(futures_app)
    futures_before = len(futures_app.callback_map)

    register_backtest_futures_callbacks(futures_app)

    assert len(futures_app.callback_map) == futures_before
    assert futures_app._atlasnexus_backtest_futures_callbacks_registered is True
    assert any('bf-results-container' in key for key in futures_app.callback_map)
    assert any('bf-perf-results-container' in key for key in futures_app.callback_map)
