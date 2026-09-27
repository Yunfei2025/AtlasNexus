# -*- coding: utf-8 -*-
"""Orchestration for the RFBT "Run Backtest" callback: runs
run_factor_backtest for one factor and computes the IC/performance
statistics shown in the results table and per-factor charts. No Dash
imports here — see register.py for the callback wiring and _figures.py for
chart/table construction."""

from __future__ import annotations

from datetime import date as _date_cls, timedelta
from typing import Dict, Tuple

from settings.paths import DIR_INPUT

from multiasset.factor_model import rolling_spearman_ic, mean_ic_at_effective_horizon


def resolve_date_range(period_years, custom_start, custom_end) -> Tuple[str, str]:
    """Custom date pickers override the lookback dropdown when set."""
    end_date = custom_end if custom_end else _date_cls.today().isoformat()
    if custom_start:
        start_date = custom_start
    else:
        years = int(period_years or 2)
        start_date = (_date_cls.today() - timedelta(days=years * 365)).isoformat()
    return start_date, end_date


def build_factor_model_kwargs(fm_train, fm_ic, fm_topn, fm_sizing, fm_possmooth,
                               fm_tiltbase, fm_tiltamp) -> Dict:
    from multiasset.factor_model import FactorModelConfig
    defaults = FactorModelConfig()

    kwargs = {'train_months': int(fm_train or 12),
              'ic_threshold': float(fm_ic or 0.05),
              'top_n': int(fm_topn or 8),
              'sizing_mode': fm_sizing or defaults.sizing_mode,
              'position_smooth_window': int(fm_possmooth or 10)}
    if (fm_sizing or defaults.sizing_mode) == 'tilt':
        # tilt_base is a policy input; 0.0 is a legitimate tilt_amp (pure
        # baseline, no model lean), so don't use `or` here.
        kwargs['tilt_base'] = (float(fm_tiltbase) if fm_tiltbase is not None
                                else defaults.tilt_base)
        kwargs['tilt_amp'] = (float(fm_tiltamp) if fm_tiltamp is not None
                               else defaults.tilt_amp)
    return kwargs


def run_rfbt_backtest(factor_val, start_date, end_date, kwargs, use_cache=True):
    """Run the FactorModel backtest for one factor, or return a cached result
    if one exists for the exact same (factor, date range, config) — the
    walk-forward retrain is the expensive part of this callback (seconds to
    minutes), so re-clicking Run Backtest with unchanged params should not
    re-run it.

    Returns (results, models_by_month, from_cache) — save=False on an actual
    run, so nothing is written to runs/; see save_rfbt_result for the
    separate Save action. The run-cache itself (rfbt_run_cache.pkl) is a
    distinct, lightweight preview cache — not the persisted factor-backtest
    artifact.
    """
    from ._cache import make_cache_params, load_rfbt_run, save_rfbt_run

    cache_params = make_cache_params(factor_val, start_date, end_date, kwargs)

    if use_cache:
        cached = load_rfbt_run(DIR_INPUT, cache_params)
        if cached is not None:
            return cached['results'], cached['models_by_month'], True

    from multiasset.factor_backtest import run_factor_backtest

    results, _, models_by_month = run_factor_backtest(
        factors=[factor_val],
        strategy='FactorModel',
        start_date=start_date,
        end_date=end_date,
        input_dir=DIR_INPUT,
        save=False,
        **kwargs,
    )

    if results and models_by_month is not None:
        save_rfbt_run(DIR_INPUT, cache_params, results, models_by_month)

    return results, models_by_month, False


def build_run_config(kwargs):
    """Materialize a FactorModelConfig reflecting the UI's *kwargs* — cached
    alongside a run's (results, models_by_month) so Save can persist under
    the exact settings the user ran with."""
    from multiasset.factor_model import FactorModelConfig
    fm_cfg = FactorModelConfig()
    for k, v in kwargs.items():
        if hasattr(fm_cfg, k):
            setattr(fm_cfg, k, type(getattr(fm_cfg, k))(v))
    return fm_cfg


def compute_factor_stats_and_ic(results) -> Dict:
    """Compute per-factor IC statistics and current signal state.

    Mirrors _rfbt_train_helpers._compute_factor_stats but additionally keeps
    'ic_rolling' at H=1 for the per-factor chart's IC panel (the train/predict
    tab's helper already does this — kept as a separate copy here since the
    two callbacks evolved independent output shapes historically; see that
    module for the canonical version used by the Factor tab).
    """
    factor_stats = {}
    for factor, df in results.items():
        pred = df['predicted_return'].dropna()
        sig = df['signal'].dropna()

        last_signal = float(sig.iloc[-1]) if not sig.empty else 0.0
        last_pred_val = float(pred.iloc[-1]) if not pred.empty else 0.0

        # Z-score of latest prediction vs trailing 252 days
        pred_hist = pred.tail(252)
        z_score = ((last_pred_val - pred_hist.mean()) / (pred_hist.std() + 1e-8)
                   if len(pred_hist) > 5 else 0.0)
        scalar = max(0.5, min(2.0, abs(z_score)))

        # IC: 60-day rolling Spearman rank-corr(predicted_return_t, return_{t+1})
        # 60-day window (≈3 months) reduces noise vs 20-day; EWMA added to chart
        # Spearman (not Pearson) to match the IC feature selection/training use.
        # This is always graded at H=1 (next-day) — see mean_ic_eff below for
        # the horizon the model's ensemble is actually blended toward.
        actual_fwd = df['returns'].shift(-1).reindex(df.index)
        ic_rolling = rolling_spearman_ic(df['predicted_return'], actual_fwd, 60).dropna()
        mean_ic = float(ic_rolling.mean()) if len(ic_rolling) > 0 else 0.0
        ic_std = float(ic_rolling.std()) if len(ic_rolling) > 1 else 1.0
        icir = mean_ic / (ic_std + 1e-8)
        ic_hit = float((ic_rolling > 0).mean()) if len(ic_rolling) > 0 else 0.0
        n_ic = len(ic_rolling)
        ic_tstat = mean_ic / (ic_std / (n_ic ** 0.5) + 1e-8) if n_ic > 1 else 0.0

        # IC at the ensemble's own effective (IC-weighted blend) horizon —
        # avoids under-crediting the model when longer horizons (H=5/20)
        # dominate the blend during a trend, since the H=1 IC above only
        # measures next-day accuracy regardless of what the model is
        # actually trying to predict.
        mean_ic_eff = float('nan')
        avg_eff_horizon = float('nan')
        if 'effective_horizon' in df.columns and df['effective_horizon'].notna().any():
            avg_eff_horizon = float(df['effective_horizon'].dropna().mean())
            mean_ic_eff = mean_ic_at_effective_horizon(
                df['predicted_return'], df['returns'], df['effective_horizon'],
            )

        factor_stats[factor] = {
            'last_signal': last_signal,
            'z_score':     z_score,
            'scalar':      scalar,
            'mean_ic':     mean_ic,
            'icir':        icir,
            'ic_hit':      ic_hit,
            'ic_tstat':    ic_tstat,
            'mean_ic_effective_horizon': mean_ic_eff,
            'avg_effective_horizon': avg_eff_horizon,
            'ic_rolling':  ic_rolling,
        }
    return factor_stats


def save_rfbt_result(results, models_by_month, fm_cfg):
    """Persist a previously-run (results, models_by_month) to
    factor-backtest.pkl + the monthly .joblib. Returns a status note."""
    from multiasset.factor_model import save_factor_model_results

    saved_artifact = save_factor_model_results(
        results, models_by_month, input_dir=DIR_INPUT,
        config=fm_cfg, save_latest_only=False,
    )
    n_total = len([k for k in (saved_artifact or {}) if k != 'metadata'])
    n_new = len(results)
    n_kept = n_total - n_new
    return (f"model saved: {n_new} updated + {n_kept} retained = "
            f"{n_total} total factors in .joblib")
