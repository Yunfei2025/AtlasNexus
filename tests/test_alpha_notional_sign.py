import pandas as pd
import pytest

from web.tabs.alpha.callbacks.portfolio import _scale_notionals_to_capital


def _scaled_and_signed(directions, sizes, capital=1000.0, lot=10.0):
    sign = pd.Series([-1.0 if d == 'SELL' else 1.0 for d in directions])
    mask = pd.Series([True] * len(directions))
    mag = _scale_notionals_to_capital(pd.Series(sizes, dtype=float), sign, mask, capital, lot)
    return mag, mag * sign                                  # Step C: BUY +, SELL -


def test_buy_heavy_book_keeps_buy_positive_sell_negative():
    mag, signed = _scaled_and_signed(['BUY', 'BUY', 'SELL'], [500, 300, 100])
    assert (mag >= 0).all()
    assert signed[0] > 0 and signed[1] > 0 and signed[2] < 0
    assert signed.sum() == pytest.approx(1000.0, abs=30)    # net == capital, within lot rounding


def test_sell_heavy_book_is_not_flipped():
    # SELLs outweigh BUYs, so the raw net is negative -- this used to flip every sign
    mag, signed = _scaled_and_signed(['SELL', 'SELL', 'BUY'], [500, 300, 100])
    assert (mag >= 0).all()
    assert signed[0] < 0 and signed[1] < 0 and signed[2] > 0
    assert signed.sum() == pytest.approx(-1000.0, abs=30)   # net short, magnitude == capital


def test_only_masked_rows_are_scaled():
    sign = pd.Series([1.0, -1.0, 1.0])
    mask = pd.Series([True, True, False])
    out = _scale_notionals_to_capital(pd.Series([100.0, 50.0, 70.0]), sign, mask, 200.0, 10.0)
    assert out[2] == 70.0                                   # unmasked row untouched
    assert out[0] > 100.0 and out[1] > 50.0
