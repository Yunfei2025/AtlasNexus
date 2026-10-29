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


from web.tabs.alpha.callbacks.portfolio import _fit_notionals_to_margin


def _gross_margin(n):                      # un-netted: 5% of gross notional
    return float(n.abs().sum()) * 0.05


def _netted_margin(n):                     # nets opposite-sign trades, like Step H across a shared bond
    return abs(float(n.sum())) * 0.05 + float(n.abs().sum()) * 0.01


def test_fit_leaves_a_book_already_under_the_cap_untouched():
    n = pd.Series([100.0, -80.0])
    assert _fit_notionals_to_margin(n, _gross_margin, 100.0, 10.0).equals(n)


def test_fit_rounds_buys_and_sells_symmetrically_toward_zero():
    n = pd.Series([99.0, -99.0])            # gross margin 9.9 -> cap 4.5
    out = _fit_notionals_to_margin(n, _gross_margin, 4.5, 10.0)
    assert out[0] == -out[1]                # np.floor on signed values made the SELL bigger than the BUY
    assert (out.abs() <= n.abs()).all()     # nothing grows when scaling down
    assert _gross_margin(out) <= 4.5


def test_fit_enforces_the_cap_when_shrinking_does_not_shrink_the_netted_margin():
    n = pd.Series([4000.0, -3000.0, 2000.0, -1500.0])
    cap = 0.8 * _netted_margin(n)
    out = _fit_notionals_to_margin(n, _netted_margin, cap, 10.0)
    assert _netted_margin(out) <= cap + 1e-9
    assert (out.abs() <= n.abs()).all() and (out % 10.0 == 0).all()
