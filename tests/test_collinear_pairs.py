# -*- coding: utf-8 -*-
"""Near-duplicate factor warning: diagnostic only, on the same EWMA covariance the sleeve risk parity uses."""

import numpy as np
import pandas as pd
import pytest

from multiasset.book.sizing import collinear_factor_pairs, pool_sleeve_budgets
from multiasset.config import RiskModelConfig


def _cov(corr_if_ih=0.96, corr_if_ic=0.60):
    names = ['EQDL.IF', 'EQDL.IC', 'EQDL.IH', 'CMDL.AU']
    sd = np.array([0.20, 0.25, 0.18, 0.15])
    c = np.eye(4)
    c[0, 2] = c[2, 0] = corr_if_ih
    c[0, 1] = c[1, 0] = corr_if_ic
    c[1, 2] = c[2, 1] = 0.55
    return pd.DataFrame(np.outer(sd, sd) * c, index=names, columns=names)


def test_flags_pairs_at_or_above_the_threshold_strongest_first():
    out = collinear_factor_pairs(_cov(0.96, 0.92), threshold=0.90)
    assert [(a, b) for a, b, _ in out] == [('EQDL.IF', 'EQDL.IH'), ('EQDL.IF', 'EQDL.IC')]
    assert out[0][2] == pytest.approx(0.96)
    assert collinear_factor_pairs(_cov(0.85, 0.60), threshold=0.90) == []


def test_negative_correlation_counts_and_default_threshold_comes_from_config():
    out = collinear_factor_pairs(_cov(-0.97, 0.10))
    assert out and out[0][2] == pytest.approx(-0.97)                      # |corr| is what matters
    assert RiskModelConfig.COLLINEAR_WARN_CORR == 0.90


def test_bad_inputs_return_nothing_and_the_check_never_filters_factors():
    assert collinear_factor_pairs(None) == [] and collinear_factor_pairs(pd.DataFrame()) == []
    cov = _cov(0.99, 0.60)
    one = cov.iloc[:1, :1]
    assert collinear_factor_pairs(one) == []
    # a diagnostic only: the budgets still cover EVERY factor, including both near-duplicates
    budgets = pool_sleeve_budgets(list(cov.index), {f: 0.2 for f in cov.index}, cov=cov)
    assert set(budgets) == set(cov.index) and all(v > 0 for v in budgets.values())
    assert sum(budgets.values()) == pytest.approx(1.0)
