# -*- coding: utf-8 -*-
"""Monthly-model live rebuild (2026-11-19): month key, ensemble blend, saved-entry format,
per-factor config resolution. The full backtest-vs-rebuild equality needs market data and
is checked by running the walk-forward and rebuilding from its models_by_month."""
import datetime as _dt

import numpy as np
import pandas as pd
import pytest

import multiasset.factor_model as fm
from multiasset.factor_model import (
    FactorModelConfig, blend_horizon_predictions, has_horizon_models, _resolve_factor_cfg,
)


def test_current_month_model_key_is_month_end_of_current_month(monkeypatch):
    class _D(_dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 19)
    monkeypatch.setattr(_dt, 'date', _D)
    assert fm.current_month_model_key() == '20261130'
    _D.today = classmethod(lambda cls: cls(2027, 2, 3))
    assert fm.current_month_model_key() == '20270228'


class _Scaler:
    def transform(self, X):
        return X.to_numpy()


def _hm(H, weight, coef, feats=('a', 'b')):
    return {'H': H, 'weight': weight,
            'trained_model': {'coefficients': pd.Series(coef, index=list(feats)),
                              'scaling_factor': 1.0, 'scaler': _Scaler(),
                              'feature_names': list(feats)},
            'selected_factors': list(feats)}


def test_blend_is_ic_weighted_with_effective_horizon():
    idx = pd.bdate_range('2026-11-02', periods=5)
    X = pd.DataFrame({'a': np.arange(5.0), 'b': np.ones(5)}, index=idx)
    h1, h20 = _hm(1, 0.25, [1.0, 0.0]), _hm(20, 0.75, [0.0, 2.0])
    out = blend_horizon_predictions(X, [h1, h20])
    expected = 0.25 * X['a'] + 0.75 * 2.0 * X['b']
    assert np.allclose(out['predicted_return'], expected)
    assert np.allclose(out['effective_horizon'], (1 * 0.25 + 20 * 0.75))
    assert (out['n_features'] == 2).all()


def test_blend_skips_models_that_cannot_predict_and_returns_none_if_all_do():
    idx = pd.bdate_range('2026-11-02', periods=3)
    X = pd.DataFrame({'zzz': np.ones(3)}, index=idx)         # none of the model features
    assert blend_horizon_predictions(X, [_hm(1, 1.0, [1.0, 1.0])]) is None
    X2 = pd.DataFrame({'a': np.ones(3), 'b': np.ones(3)}, index=idx)
    out = blend_horizon_predictions(X2, [_hm(1, 1.0, [1.0, 1.0]), _hm(5, 1.0, [1.0], feats=('q',))])
    assert np.allclose(out['effective_horizon'], 1.0)         # only the H=1 model contributed


def test_has_horizon_models_distinguishes_old_and_new_entries():
    assert not has_horizon_models(None)
    assert not has_horizon_models({'trained_model': {}, 'selected_factors': []})     # legacy
    assert has_horizon_models({'horizon_models': [_hm(1, 1, [1, 1])], 'window_start': '2026-11-01',
                               'window_end': '2026-11-30'})
    assert not has_horizon_models({'horizon_models': [_hm(1, 1, [1, 1])]})           # no window


def test_resolve_factor_cfg_applies_family_override_unless_mode_chosen():
    assert _resolve_factor_cfg('FXDL.USDCNY', None).sizing_mode == 'discrete'
    assert _resolve_factor_cfg('IRDL.CN', None).sizing_mode == FactorModelConfig().sizing_mode
    explicit_default = FactorModelConfig()
    assert _resolve_factor_cfg('CMDL.AU', explicit_default).sizing_mode == 'discrete'
    chosen = FactorModelConfig(sizing_mode='tilt')
    assert _resolve_factor_cfg('CMDL.AU', chosen).sizing_mode == 'tilt'


def test_list_model_months_keeps_only_calendar_month_ends(tmp_path):
    for k in ('20260430', '20260507', '20260425', '20260531', '20260228', '20240229', '20261130', 'x', '2026-11-30'):
        (tmp_path / f'factor_model_{k}.joblib').write_bytes(b'')
    assert fm.list_model_months(tmp_path) == ['20240229', '20260228', '20260430', '20260531', '20261130']
