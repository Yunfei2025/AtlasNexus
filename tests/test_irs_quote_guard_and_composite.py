import numpy as np
import pandas as pd

from curves.calibration.irs.quotes import get_swap_quote_frame
from curves.calibration.irs.spreads import irsSpreadComposite, irsSpreads


def _rt(bid, ofr, traded):
    return pd.DataFrame({'买价收益率': bid, '卖价收益率': ofr, '成交收益率': traded},
                        index=['FR007S5Y.IR', 'FR007S7Y.IR'])


def test_wide_market_with_stale_trade_falls_back():
    rt = _rt([1.475, 1.30], [1.4775, 2.50], [1.4725, 1.90])
    fb = pd.Series({'FR007S5Y.IR': 1.465, 'FR007S7Y.IR': 1.505})
    mid = get_swap_quote_frame(rt, fallback_quotes=fb)['Mid']
    assert mid['FR007S7Y.IR'] == 1.505
    assert mid['FR007S5Y.IR'] == (1.475 + 1.4775) / 2


def test_wide_market_with_trade_near_fallback_keeps_trade():
    rt = _rt([1.475, 1.40], [1.4775, 1.60], [1.4725, 1.51])
    fb = pd.Series({'FR007S5Y.IR': 1.465, 'FR007S7Y.IR': 1.45})
    mid = get_swap_quote_frame(rt, fallback_quotes=fb)['Mid']
    assert np.isclose(mid['FR007S7Y.IR'], 1.50)  # print agrees with fallback: keep live mid


def test_composite_timeseries_matches_single_date():
    cols = ['FR007S1Y.IR', 'FR007S5Y.IR', 'FR007S2Y.IR', 'FR007S3M.IR', 'FR007S6M.IR',
            'FR007S9M.IR', 'FR007S3Y.IR', 'FR007S4Y.IR', 'FR007S7Y.IR', 'FR007S10Y.IR']
    rng = np.random.default_rng(0)
    cost = pd.DataFrame(rng.normal(size=(3, len(cols))), columns=cols)
    names = ['Repo7d-1y5y', 'Repo7d-1y2y5y']
    ts = irsSpreadComposite(names, cost)
    one = irsSpreadComposite(names, cost.iloc[1])
    assert np.allclose(ts.iloc[1], one)
    # DV01-neutral: 1y5y is 5y minus 5x 1y
    assert np.isclose(one['Repo7d-1y5y'], cost.iloc[1]['FR007S5Y.IR'] - 5 * cost.iloc[1]['FR007S1Y.IR'])


def test_wide_leg_is_flagged_and_spread_uses_last_close():
    from curves.calibration.irs.spreads import _irs_quote_spread_weights
    rt = _rt([1.475, 1.30], [1.4775, 2.50], [1.4725, 1.90])
    fb = pd.Series({'FR007S5Y.IR': 1.465, 'FR007S7Y.IR': 1.505})
    frame = get_swap_quote_frame(rt, fallback_quotes=fb)
    assert frame['Fallback'].tolist() == [False, True]
    assert 'FR007S7Y.IR' in _irs_quote_spread_weights('Repo7d-5y7y')
