# -*- coding: utf-8 -*-
"""LGB mean-reversion blend, execution delay/cost and walk-forward warm-up
(2026-11-19, see FactorModelConfig.mr_blend / warmup_months)."""
import numpy as np
import pandas as pd

from multiasset.factor_model import (
    FactorModelConfig, _has_mr_blend, apply_execution_model, apply_mr_blend,
    mean_reversion_position,
)


def _level(n=300, seed=0):
    rng = np.random.default_rng(seed)
    return pd.Series(15 + np.cumsum(rng.normal(0, 0.02, n)),
                     index=pd.bdate_range('2023-01-02', periods=n))


def test_blend_routing_is_credit_only():
    for u in ('CDB', 'LGB', 'MTN', 'NCD'):
        for p in ('CRDL', 'CRSL', 'CRCV'):
            assert _has_mr_blend(f'{p}.{u}')
    for f in ('IRDL.CN', 'IRSL.CN', 'FXDL.USDCNY', 'CMDL.AU', 'CRDL.XYZ'):
        assert not _has_mr_blend(f)


def test_blend_noop_when_off_or_unrouted():
    lvl = _level()
    pos = pd.Series(0.3, index=lvl.index)
    cfg = FactorModelConfig()
    assert apply_mr_blend(pos, lvl, 'IRDL.CN', cfg).equals(pos)
    off = FactorModelConfig(mr_blend=False)
    assert apply_mr_blend(pos, lvl, 'CRDL.LGB', off).equals(pos)


def test_blend_is_weighted_and_falls_back_before_mr_defined():
    lvl = _level()
    pos = pd.Series(0.3, index=lvl.index)
    cfg = FactorModelConfig()
    out = apply_mr_blend(pos, lvl, 'CRDL.LGB', cfg)
    mr = mean_reversion_position(lvl, cfg)
    # first window: MR undefined (rolling smooth keeps NaN) -> model position
    assert (out.iloc[:cfg.mr_window - 1] == 0.3).all()
    t = lvl.index[-1]
    assert np.isclose(out[t], 0.5 * 0.3 + 0.5 * mr[t])
    assert out.abs().max() <= 1.0


def test_mr_position_is_causal():
    lvl = _level()
    cfg = FactorModelConfig()
    full = mean_reversion_position(lvl, cfg)
    cut = mean_reversion_position(lvl.iloc[:200], cfg)
    assert np.allclose(full.iloc[:200].dropna(), cut.dropna())


def test_execution_model_defaults_match_legacy_and_apply_delay_cost():
    idx = pd.bdate_range('2024-01-01', periods=10)
    pos = pd.Series([0, 1, 1, -1, -1, 0, 0, 1, 1, 1], index=idx, dtype=float)
    ret = pd.Series(0.001, index=idx)
    base = apply_execution_model(pos, ret, FactorModelConfig())
    assert base.equals(pos.shift(1) * ret)
    delayed = apply_execution_model(pos, ret, FactorModelConfig(exec_delay_days=2))
    assert delayed.equals(pos.shift(2).shift(1) * ret)
    costly = apply_execution_model(pos, ret, FactorModelConfig(cost_bp=1.0))
    # total cost = turnover * 1bp
    turnover = pos.diff().abs().fillna(0).sum()
    assert np.isclose((base - costly).sum(), turnover * 1e-4)
