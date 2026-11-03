# -*- coding: utf-8 -*-
"""Summary > Books > Portfolio Combination must score the beta book over cash, like the beta backtest's
"Sharpe (vs cash)": the beta equity curve contains the FR007 it earns on idle capital, so a raw Sharpe
counted ~2%/yr of cash income as skill (4.0 in the tab against 1.85 in the backtest)."""

import numpy as np
import pandas as pd
import pytest

from web.tabs.risk.books.combination import _beta_cash_hurdle, _metrics, build_combination

CAPITAL_MM = 10_000.0
DAILY_CASH = 0.02 / 365.0            # a flat 2% cash rate on every calendar day


def _beta_result(daily_pnl_mm, with_benchmark=True, seed=0):
    idx = pd.bdate_range('2022-01-03', periods=len(daily_pnl_mm))
    cum = np.cumsum(daily_pnl_mm)
    res = {'total_capital': CAPITAL_MM,
           'equity_series': [{'date': d.strftime('%Y-%m-%d'), 'value': float(v)} for d, v in zip(idx, cum)]}
    if with_benchmark:
        gap = pd.Series(idx).diff().dt.days.fillna(1).to_numpy()
        res['cash_benchmark'] = [{'date': d.strftime('%Y-%m-%d'), 'value': float(CAPITAL_MM * DAILY_CASH * g)}
                                 for d, g in zip(idx, gap)]
    return res, idx


def _alpha_result(idx, seed=1):
    rng = np.random.default_rng(seed)
    eq = pd.Series(np.cumsum(rng.normal(0.4, 3.0, len(idx))), index=idx)
    return {'equity_ts': eq, 'instruments': [{'ID': 'CGB-5s10s', 'spread_type': 'TenorSpread', 'weight': 1.0}]}


def test_hurdle_leaves_vol_return_and_drawdown_alone():
    rng = np.random.default_rng(3)
    r = pd.Series(rng.normal(0.0002, 0.001, 500), index=pd.bdate_range('2022-01-03', periods=500))
    h = pd.Series(0.00008, index=r.index)
    raw, vs_cash = _metrics(r), _metrics(r, h)
    for k in ('vol', 'ann_return', 'total_return', 'max_drawdown'):
        assert vs_cash[k] == pytest.approx(raw[k])
    assert vs_cash['sharpe'] == pytest.approx((raw['ann_return'] - 0.00008 * 252) / raw['vol'])
    assert _metrics(r, None)['sharpe'] == pytest.approx(raw['sharpe'])      # no hurdle: unchanged (alpha path)


def test_a_cash_only_beta_book_has_zero_sharpe_over_cash_not_a_huge_one():
    rng = np.random.default_rng(5)
    n = 700
    idx = pd.bdate_range('2022-01-03', periods=n)
    gap = pd.Series(idx).diff().dt.days.fillna(1).to_numpy()
    # tiny noise around exactly the cash accrual
    pnl = CAPITAL_MM * DAILY_CASH * gap + rng.normal(0.0, 0.5, n)
    beta, _ = _beta_result(pnl)
    out = build_combination(beta, _alpha_result(idx), 20_000.0, 0.0)
    assert out['beta_benchmark'] == 'saved'
    assert abs(out['beta']['sharpe']) < 0.6                                   # raw Sharpe of this curve is ~20+
    assert out['beta']['ann_return'] > 0.015                                  # the cash income is still reported
    assert out['combined']['sharpe'] == pytest.approx(out['beta']['sharpe'])  # 100% beta = the beta book


def test_blend_hurdle_scales_with_the_beta_share_and_alpha_is_untouched():
    rng = np.random.default_rng(7)
    n = 700
    pnl = rng.normal(2.0, 8.0, n)
    beta, idx = _beta_result(pnl)
    alpha = _alpha_result(idx)
    out = build_combination(beta, alpha, 20_000.0, 0.5)
    r = out['returns']
    h = _beta_cash_hurdle(beta, r['beta'].index)[0]
    assert out['combined']['sharpe'] == pytest.approx(_metrics(r['combined'], 0.5 * h)['sharpe'])
    assert out['alpha']['sharpe'] == pytest.approx(_metrics(r['alpha'])['sharpe'])      # spread P&L: no hurdle
    # every sweep point uses its own beta share of the hurdle: 0% alpha is the beta book's Sharpe
    sw = out['sweep'].set_index('alpha_margin_share')
    assert sw.loc[0.0, 'sharpe'] == pytest.approx(out['beta']['sharpe'])


def test_old_saved_results_without_a_benchmark_fall_back_to_fr007():
    beta, idx = _beta_result(np.full(300, 1.0), with_benchmark=False)
    h, source = _beta_cash_hurdle(beta, idx)
    if source == 'none':
        pytest.skip('FR007 unavailable in this environment')
    assert source == 'fr007'
    assert 0.0 < h.mean() * 365 < 0.06                                        # a sane annual cash rate
