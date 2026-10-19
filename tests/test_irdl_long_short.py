# -*- coding: utf-8 -*-
"""IRDL is long-short in every market, with a symmetric confirmed-trend floor
(multiasset.factor_model.apply_trend_floor). Decision 2026-10-17; see
docs/plans/factor_model_improvement.md 3.9."""

import numpy as np
import pandas as pd
import pytest

from multiasset.factor_model import (
    FactorModelConfig, _has_trend_floor, _is_long_only, apply_trend_floor, build_position_series,
)


def _idx(n=400):
    return pd.bdate_range('2020-01-01', periods=n)


def test_irdl_is_not_long_only_in_any_market():
    for c in ('CN', 'US', 'DE', 'JP', 'UK'):
        assert not _is_long_only(f'IRDL.{c}')
        assert _has_trend_floor(f'IRDL.{c}')
    assert not _has_trend_floor('FXDL.USDCNY') and not _has_trend_floor('IRSL.CN')


def test_irdl_position_can_go_short():
    idx = _idx()
    rets = pd.Series(0.0, index=idx)
    pred = pd.Series(-0.002, index=idx)           # persistently bearish
    cfg = FactorModelConfig(sizing_mode='binary')
    pos = build_position_series(pred, rets, cfg, long_only=_is_long_only('IRDL.CN'))['position']
    assert pos.min() == -1.0
    # the same call with the old long-only flag clips the short away
    assert build_position_series(pred, rets, cfg, long_only=True)['position'].min() == 0.0


def test_trend_floor_is_symmetric():
    idx = _idx()
    cfg = FactorModelConfig()
    flat = pd.Series(0.0, index=idx)
    falling = pd.Series(np.linspace(4.0, 2.0, len(idx)), index=idx)   # yields down: confirmed rally
    rising = pd.Series(np.linspace(2.0, 4.0, len(idx)), index=idx)    # yields up: confirmed sell-off

    p_bull, el_bull = apply_trend_floor(flat, falling, cfg)
    p_bear, el_bear = apply_trend_floor(flat, rising, cfg)
    assert p_bull.iloc[-1] == cfg.long_floor and el_bull.iloc[-1]
    assert p_bear.iloc[-1] == -cfg.long_floor and el_bear.iloc[-1]
    # no trend confirmation in the first 120 days -> untouched
    assert (p_bull.iloc[:100] == 0).all() and not el_bull.iloc[:100].any()


def test_trend_floor_does_not_override_a_stronger_view_and_bull_only_mode():
    idx = _idx()
    falling = pd.Series(np.linspace(4.0, 2.0, len(idx)), index=idx)
    rising = pd.Series(np.linspace(2.0, 4.0, len(idx)), index=idx)
    cfg = FactorModelConfig()
    strong_long = pd.Series(0.9, index=idx)
    strong_short = pd.Series(-0.9, index=idx)
    assert apply_trend_floor(strong_long, falling, cfg)[0].iloc[-1] == 0.9      # floor only lifts
    assert apply_trend_floor(strong_short, rising, cfg)[0].iloc[-1] == -0.9     # mirror only lowers

    import dataclasses
    bull_only = dataclasses.replace(cfg, trend_floor_symmetric=False)
    assert apply_trend_floor(pd.Series(0.0, index=idx), rising, bull_only)[0].iloc[-1] == 0.0


def test_irdl_coefficient_is_directional_and_commodities_stay_long_only():
    from multiasset.backtest_cache import scalar_to_coeff

    assert scalar_to_coeff(-0.6, 'IRDL.US') == -0.6
    assert scalar_to_coeff(2.0, 'IRDL.CN') == 1.5
    assert scalar_to_coeff(0.0, 'IRDL.CN') == 0.0
    assert scalar_to_coeff(-0.5, 'CMDL.AU') == 0.5
