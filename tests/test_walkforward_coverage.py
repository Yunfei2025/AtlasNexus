# -*- coding: utf-8 -*-
"""Walk-forward out-of-sample coverage guards.

Regression tests for a defect where ``embargo_days`` was applied to the head
of every *test* window. Because test windows are contiguous, that silently
discarded ``embargo_days`` out-of-sample days per period (~49% of all days at
the default test_months=1 / embargo_days=10), produced a discontiguous return
series, and made reported Sharpe depend on where month boundaries fell
relative to the start date.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from multiasset.factor_model import FactorModelConfig, build_position_series


def _synthetic_levels(n: int = 1500, seed: int = 0) -> pd.DataFrame:
    """A smooth synthetic yield series on business days."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range('2015-01-05', periods=n)
    level = 3.0 + np.cumsum(rng.normal(0, 0.01, n))
    return pd.DataFrame({'IRDL.CN': level}, index=idx)


def test_embargo_does_not_drop_test_rows():
    """The embargo must shrink the training window, never the test window."""
    from multiasset.factor_model import run_factor_model_backtest

    levels = _synthetic_levels()
    common = dict(sizing_mode='discrete', target_horizons=[1])

    no_embargo = run_factor_model_backtest(
        'IRDL.CN', levels, config=FactorModelConfig(embargo_days=0, **common),
    )
    with_embargo = run_factor_model_backtest(
        'IRDL.CN', levels, config=FactorModelConfig(embargo_days=10, **common),
    )

    if no_embargo.empty or with_embargo.empty:
        pytest.skip("backtest produced no periods for the synthetic series")

    # Changing the embargo may shift when predictions can first be made, but it
    # must not punch holes in the out-of-sample series: the row counts should be
    # close, never halved as they were with the test-side embargo.
    ratio = len(with_embargo) / len(no_embargo)
    assert ratio > 0.9, (
        f"embargo removed {100 * (1 - ratio):.0f}% of out-of-sample rows "
        f"({len(with_embargo)} vs {len(no_embargo)}) — it must not drop test days"
    )


def test_backtest_covers_most_available_days():
    """The OOS series should cover ~all trading days within its own span."""
    from multiasset.factor_model import run_factor_model_backtest

    levels = _synthetic_levels()
    df = run_factor_model_backtest(
        'IRDL.CN', levels,
        config=FactorModelConfig(sizing_mode='discrete', target_horizons=[1]),
    )
    if df.empty:
        pytest.skip("backtest produced no periods for the synthetic series")

    span = levels.loc[df.index.min():df.index.max()]
    coverage = len(df) / len(span)
    assert coverage > 0.9, (
        f"backtest covers only {coverage:.0%} of trading days inside its own "
        f"span ({len(df)}/{len(span)}) — indicates dropped test windows"
    )


def test_tilt_sizing_never_goes_flat():
    """'tilt' holds a baseline: a weak signal must not collapse the position."""
    idx = pd.bdate_range('2020-01-01', periods=400)
    rng = np.random.default_rng(1)
    pred = pd.Series(rng.normal(0, 1e-4, len(idx)), index=idx)
    rets = pd.Series(rng.normal(0, 2e-4, len(idx)), index=idx)

    cfg = FactorModelConfig(sizing_mode='tilt', tilt_base=0.6, tilt_amp=0.2)
    pos = build_position_series(pred, rets, cfg, long_only=True)['position']

    assert (pos > 0).all(), "tilt sizing must never go flat"
    assert pos.min() >= 0.6 - 0.2 - 1e-9
    assert pos.max() <= 0.6 + 0.2 + 1e-9
