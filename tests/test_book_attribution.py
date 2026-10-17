import numpy as np
import pandas as pd

from multiasset.book.attribution import attribute_book_return
from multiasset.book.pnl import BookPnL


def _frames(n=504, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range('2020-01-01', periods=n)
    cols = ['CN10Y', 'USDCNY', 'Gold']
    cg = pd.DataFrame(rng.normal(0, 1e5, (n, 3)), index=idx, columns=cols); cg['USDCNY'] = 0.0; cg['Gold'] = 0.0
    other = pd.DataFrame(0.0, index=idx, columns=cols)
    other['USDCNY'] = rng.normal(2e3, 2e5, n); other['Gold'] = rng.normal(5e3, 8e5, n)
    carry = pd.DataFrame(0.0, index=idx, columns=cols); carry['CN10Y'] = 3e3
    alloc = pd.DataFrame({'CN10Y': 3e8, 'USDCNY': 1e8, 'Gold': 2e8}, index=idx)
    cash = pd.Series(100.0, index=idx)
    return BookPnL(capital_gain=cg, carry=carry, other=other, cash=pd.Series(0.0, index=idx)), alloc, cash


def test_components_sum_and_risk_shares_sum_to_100():
    pnl, alloc, cash = _frames()
    cls = {'CN10Y': 'Rates', 'USDCNY': 'FX', 'Gold': 'Commodities'}.get
    out = attribute_book_return(pnl, alloc, cash, None, 1e9, 0.03, cls)
    s = out['simple_annual_pct']
    assert abs(s['gross_total'] - (s['price'] + s['carry'] + s['cash'])) < 1e-9
    assert abs(sum(c['risk_share_pct'] for c in out['by_class'].values()) - 100.0) < 1e-6
    assert abs(out['compounding_drag_pct'] - (3.0 - s['gross_total'])) < 1e-9
    # gold has the biggest vol here, so it must carry the biggest risk share
    shares = {k: v['risk_share_pct'] for k, v in out['by_class'].items()}
    assert max(shares, key=shares.get) == 'Commodities'


def test_tx_cost_is_subtracted_only_from_net():
    pnl, alloc, cash = _frames()
    tx = pd.Series(1e3, index=alloc.index)
    out = attribute_book_return(pnl, alloc, cash, tx, 1e9, 0.0, {'CN10Y': 'Rates', 'USDCNY': 'FX', 'Gold': 'Commodities'}.get)
    s = out['simple_annual_pct']
    assert s['tx_cost'] < 0 and abs(s['net_total'] - (s['gross_total'] + s['tx_cost'])) < 1e-9
