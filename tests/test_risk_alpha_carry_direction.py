"""Risk tab alpha carry MtM must follow the trade direction (it used to book BUY carry for SELLs)."""

import pandas as pd
import pytest

import web.tabs.risk.helpers as h


@pytest.fixture
def carry(monkeypatch):
    days = pd.date_range('2026-01-01', periods=90, freq='D')
    buy = pd.DataFrame({'CGB-1s2s5s': 0.9, 'CDBCGB-5y': 0.9}, index=days)   # 3m %, flat
    sell = pd.DataFrame({'CGB-1s2s5s': -1.8}, index=days)                    # TRS spread makes |SELL| != BUY
    monkeypatch.setattr(h, '_load_cr_ts', lambda spread_type: buy)
    monkeypatch.setattr(h, '_alpha_sell_carry_series',
                        lambda st, iid: sell[iid] if iid in sell.columns else None)
    return days[0].strftime('%Y-%m-%d')


def test_buy_uses_buy_series(carry):
    # 90 days x 0.9 / 90 = 0.9% of 100mm = 0.9mm
    assert h._compute_alpha_carry_mtm('TenorSpread', 'CGB-1s2s5s', carry, 100.0, 'BUY') == pytest.approx(0.9)


def test_sell_uses_stored_sell_series(carry):
    assert h._compute_alpha_carry_mtm('TenorSpread', 'CGB-1s2s5s', carry, 100.0, 'SELL') == pytest.approx(-1.8)


def test_sell_without_sell_series_negates_buy(carry):
    assert h._compute_alpha_carry_mtm('TenorSpread', 'CDBCGB-5y', carry, 100.0, 'sell') == pytest.approx(-0.9)
