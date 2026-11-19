# -*- coding: utf-8 -*-
"""Sizing must be causal: the position on day t may not change when data after
day t is removed. rolling_icir grades IC against H-day forward returns, so for
H > 1 it must only use pairs whose forward window is complete (2026-11-19 fix)."""
import numpy as np
import pandas as pd
import pytest

from multiasset.factor_model import FactorModelConfig, build_position_series, rolling_icir


def _data(n=500, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range('2022-01-03', periods=n)
    ret = pd.Series(rng.normal(0, 0.001, n), index=idx)
    # prediction correlated with the FUTURE 10d return -> a leak would be rewarded
    fwd = ret.rolling(10).sum().shift(-10).fillna(0.0)
    pred = 0.3 * fwd + pd.Series(rng.normal(0, 0.002, n), index=idx)
    return pred, ret


@pytest.mark.parametrize('mode', ['continuous', 'discrete'])
@pytest.mark.parametrize('horizon', [1, 5, 'series'])
def test_position_unchanged_when_future_removed(mode, horizon):
    pred, ret = _data()
    cfg = FactorModelConfig(sizing_mode=mode)
    eff = pd.Series(11.0, index=pred.index) if horizon == 'series' else None
    kw = {'effective_horizon': eff} if eff is not None else {}
    full = build_position_series(pred, ret, cfg, **kw)['position']
    for T in (pred.index[250], pred.index[380]):
        cut = pred.index <= T
        kw_cut = {'effective_horizon': eff[cut]} if eff is not None else {}
        part = build_position_series(pred[cut], ret[cut], cfg, **kw_cut)['position']
        assert np.allclose(part.to_numpy(), full.loc[:T].to_numpy(), atol=1e-12), \
            f'{mode}/{horizon}: position at/before {T.date()} depends on later data'


def test_scalar_h_icir_matches_series_h_and_h1_unchanged():
    pred, ret = _data()
    a = rolling_icir(pred, ret, 60, horizon=5)
    b = rolling_icir(pred, ret, 60, horizon=pd.Series(5.0, index=pred.index))
    assert np.allclose(a.dropna().to_numpy(), b.dropna().to_numpy())
    h1 = rolling_icir(pred, ret, 60)
    assert np.allclose(h1.dropna().to_numpy(), rolling_icir(pred, ret, 60, horizon=1).dropna().to_numpy())
