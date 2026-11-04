from web.tabs.alpha.callbacks.backtest_state import carry_needs_negate


def test_swapspread_carry_is_already_engine_long():
    # IRS-pxspds CarryRoll3m is stored BUY-side (receive the higher-yield leg),
    # which profits when the series falls = engine LONG on the inverted series.
    for name in ('Repo7d-1y5y', 'Repo7d-3m1y', 'Basis-5y', 'Repo7d-1y2y5y'):
        assert carry_needs_negate('SwapSpread', name) is False
