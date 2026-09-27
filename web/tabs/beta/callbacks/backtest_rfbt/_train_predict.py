# -*- coding: utf-8 -*-
"""Orchestration for the Factor tab's Train Model / Predict callback.

Split out of backtest_rfbt.py's train_factor_model_for_factor_tab, which was
~430 lines nested inside the single register_backtest_rfbt_callbacks
function. This module holds the branching train/predict logic as plain
functions; register.py wires it to the @app.callback and translates results
into Dash outputs."""

from __future__ import annotations

import os
from datetime import date as _date

from dash import html

from settings.paths import DIR_INPUT

from ._rfbt_train_helpers import (
    _config_matches,
    _build_results_from_saved_artifact,
)
from ...data import THEME


class NoModelForCurrentMonth(Exception):
    """Raised on Predict when no current-month model artifact exists yet."""

    def __init__(self, expected_key, stale_data_warning=None):
        self.expected_key = expected_key
        self.stale_data_warning = stale_data_warning


class SavedModelParamsMismatch(Exception):
    """Raised on Predict when the saved model's config != the UI's config."""


class FactorsNotInSavedModel(Exception):
    """Raised on Predict when selected factors are absent from the saved model."""

    def __init__(self, missing_factors):
        self.missing_factors = missing_factors


class NoResultsProduced(Exception):
    """Raised when the backtest/prediction produced no results at all."""


def maybe_refresh_factor_data():
    """Refreshing factor files can invoke external market-data work and
    block the Dash request long enough for the browser to abandon it.
    The saved current-month model remains immediately usable; opt in to
    the refresh (FI_REFRESH_FACTOR_DATA=1) when an interactive user
    explicitly needs it."""
    if os.environ.get("FI_REFRESH_FACTOR_DATA", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return

    try:
        from multiasset.factor_backtest import update_factor_rates
        _, n_new = update_factor_rates(DIR_INPUT)
        if n_new:
            print(f"factor-rates.pkl: +{n_new} new day(s) appended before predict/train")
    except Exception as _ufr_exc:
        print(f"Warning: factor-rates incremental update failed: {_ufr_exc}")

    try:
        from multiasset.factor_backtest import update_factor_credit
        _, n_new_cr = update_factor_credit(DIR_INPUT)
        if n_new_cr:
            print(f"factor-credit.pkl: +{n_new_cr} new day(s) appended before predict/train")
    except Exception as _ufc_exc:
        print(f"Warning: factor-credit incremental update failed: {_ufc_exc}")


def build_stale_data_warning():
    """Train/Predict only refresh factor-rates.pkl / factor-credit.pkl when
    FI_REFRESH_FACTOR_DATA is set — otherwise they train on whatever's
    cached, which can silently lag the raw market data by weeks and produce
    a model keyed to an earlier month than expected. Returns an html.Div
    warning, or None if the cache isn't stale (or its staleness can't be
    determined)."""
    try:
        import pandas as _pd
        _rates_path = os.path.join(str(DIR_INPUT), 'factor-rates.pkl')
        if not os.path.exists(_rates_path):
            return None
        _rates_df = _pd.read_pickle(_rates_path)
        _last_date = _rates_df.index.max()
        _staleness_days = (_date.today() - _last_date.date()).days
        if _staleness_days <= 7:
            return None
        return html.Div([
            html.Div(
                f"⚠️ factor-rates.pkl / factor-credit.pkl last updated "
                f"{_last_date.date().isoformat()} ({_staleness_days} days stale). "
                "Training now will produce a model keyed to that stale "
                "month, not the current month.",
                style={'marginBottom': '6px', 'fontWeight': '600'},
            ),
            html.Div(
                'Refresh first: click "Generate Factor Series" in Execution Center -> DataBACKFILL or run `python main.py update-data` in a terminal, '
                'or set FI_REFRESH_FACTOR_DATA=1 before starting the web app so '
                'Train Model refreshes the cache automatically.',
            ),
        ], style={
            'color': THEME['warning'], 'backgroundColor': 'rgba(240, 120, 40, 0.12)',
            'border': '1px solid rgba(240, 120, 40, 0.5)', 'borderRadius': '6px',
            'padding': '12px 14px', 'marginBottom': '12px', 'fontSize': '11px',
            'lineHeight': '1.5',
        })
    except Exception as _stale_exc:
        print(f"Warning: could not check factor-rates.pkl staleness: {_stale_exc}")
        return None


def collect_selected_factors(store_data) -> list:
    store_data = store_data or {}
    return list(dict.fromkeys(
        store_data.get('ir', []) +
        store_data.get('cr', []) +
        store_data.get('fx', []) +
        store_data.get('eq', []) +
        store_data.get('cmd', [])
    ))


def build_current_config(fm_train, fm_ic, fm_topn) -> dict:
    from multiasset.factor_model import FactorModelConfig as _FMCfgDefaults
    return {
        'train_months': int(fm_train or 12),
        'ic_threshold': float(fm_ic or 0.05),
        'top_n': int(fm_topn or 8),
        'sizing_mode': _FMCfgDefaults().sizing_mode,
        'position_smooth_window': 10,
    }


def run_predict(factors, current_cfg, end_date):
    """Predict action: load the current-month model artifact and predict
    from it. Returns (results, latest_artifact, persist_note, header_note).
    Raises NoModelForCurrentMonth / SavedModelParamsMismatch /
    FactorsNotInSavedModel on the same conditions the original inline
    callback returned early for."""
    from multiasset.factor_backtest import run_factor_backtest
    from multiasset.factor_model import load_current_month_model, current_month_model_key

    latest_artifact, latest_month_key = load_current_month_model()
    if not latest_artifact:
        raise NoModelForCurrentMonth(current_month_model_key())

    saved_cfg = latest_artifact.get('metadata', {}).get('config', {})
    if not _config_matches(saved_cfg, current_cfg):
        raise SavedModelParamsMismatch()
    smooth_days = int(saved_cfg.get('signal_smooth_days', 1))

    # ── Split: factors already in artifact vs newly selected ──
    artifact_factors = {k for k in latest_artifact if k != 'metadata'}
    covered_factors = [f for f in factors if f in artifact_factors]
    missing_factors = [f for f in factors if f not in artifact_factors]

    if missing_factors:
        raise FactorsNotInSavedModel(missing_factors)

    # Predict covered factors from saved artifact (fast, no retrain)
    results = _build_results_from_saved_artifact(
        latest_artifact, smooth_days, factors, factor_subset=covered_factors
    )
    active_artifact = latest_artifact  # passed to _build_top_drivers

    # (branch kept for legacy compatibility — missing_factors is always empty here now)
    if missing_factors:
        results_new, merged_artifact, _ = run_factor_backtest(
            factors=missing_factors,
            strategy='FactorModel',
            start_date=None,
            end_date=end_date,
            input_dir=DIR_INPUT,
            save=True,           # merges into existing .joblib on disk
            save_latest_only=True,
            **current_cfg,
        )
        results.update(results_new)
        if merged_artifact:
            # merged_artifact already contains old + new factors
            active_artifact = merged_artifact
            n_cached = len(covered_factors)
            n_new = len(missing_factors)
            persist_note = (
                f"saved model: {latest_month_key} · "
                f"{n_cached} from cache + {n_new} newly trained & merged"
            )
            header_note = (
                f"🔮 {n_cached} factor(s) predicted from saved model · "
                f"🆕 {n_new} new factor(s) trained, saved & merged: "
                f"{', '.join(missing_factors)}"
            )
        else:
            persist_note = (
                f"saved model: {latest_month_key} · "
                f"warning: new factors may not have saved correctly"
            )
            header_note = (
                f"🔮 Predicted from saved model; some new factors may be "
                f"missing (insufficient data or error)."
            )
    else:
        n_cached = len(covered_factors)
        persist_note = (
            f"saved model: {latest_month_key} · "
            f"all {n_cached} factor(s) from cache (no new factors)"
        )
        header_note = (
            f"🔮 Predicted from saved model through {latest_month_key} "
            f"(no retrain — all {n_cached} factors already trained)."
        )

    return results, active_artifact, persist_note, header_note


def run_train(factors, current_cfg, end_date):
    """Train action: retrain any factors not already covered by an
    up-to-date current-month model, reusing cached results for the rest.
    Returns (results, latest_artifact, persist_note, header_note)."""
    from multiasset.factor_backtest import run_factor_backtest
    from multiasset.factor_model import load_current_month_model

    existing_artifact, existing_month_key = load_current_month_model()
    if existing_artifact and _config_matches(
        existing_artifact.get('metadata', {}).get('config', {}), current_cfg
    ):
        artifact_factors = {k for k in existing_artifact if k != 'metadata'}
        factors_to_train = [f for f in factors if f not in artifact_factors]
        cached_factors = [f for f in factors if f in artifact_factors]
    else:
        factors_to_train = factors
        cached_factors = []
        existing_artifact = None

    if factors_to_train:
        results_new, latest_artifact, _ = run_factor_backtest(
            factors=factors_to_train,
            strategy='FactorModel',
            start_date=None,
            end_date=end_date,
            input_dir=DIR_INPUT,
            save=True,
            save_latest_only=True,
            **current_cfg,
        )
    else:
        results_new, latest_artifact = {}, existing_artifact

    # Pull cached factor results from the saved artifact for display
    results = results_new.copy()
    if cached_factors and (latest_artifact or existing_artifact):
        art = latest_artifact or existing_artifact
        smooth_days = int(
            (art.get('metadata') or {}).get('config', {}).get('signal_smooth_days', 1)
        )
        cached_results = _build_results_from_saved_artifact(
            art, smooth_days, factors, factor_subset=cached_factors
        )
        results.update(cached_results)

    mkey = (latest_artifact or {}).get('metadata', {}).get('train_end_date', '?')
    n_new = len(factors_to_train)
    n_cached = len(cached_factors)
    if n_cached and n_new:
        persist_note = (
            f"saved model: {mkey} · "
            f"{n_new} newly trained + {n_cached} from cache"
        )
        header_note = (
            f"⚡ {n_new} factor(s) trained through {end_date} · "
            f"🔮 {n_cached} factor(s) loaded from saved model "
            f"({', '.join(cached_factors)})"
        )
    elif n_cached:
        persist_note = f"saved model: {mkey} · all {n_cached} factor(s) already trained (no retrain needed)"
        header_note = (
            f"🔮 All {n_cached} selected factor(s) already exist in the saved model "
            f"({mkey}) — no retraining required."
        )
    else:
        persist_note = f"saved model: {mkey}" if mkey != '?' else "model save not found"
        header_note = (
            f"⚡ Model trained on data through {end_date} (month-start cutoff — "
            "no recent daily data used to avoid overfitting)."
        )

    return results, latest_artifact, persist_note, header_note


def _bucket_label(c):
    if c == 0:
        return 'Neutral'
    mag = abs(c)
    strength = 'Strong ' if mag >= 0.8 else ('' if mag >= 0.4 else 'Mild ')
    return f"{strength}{'Long' if c > 0 else 'Short'}"


def build_snapshot_records(factor_stats) -> list:
    """Build records for the Portfolio tab's factor-signals-snapshot-store.

    Uses 'last_position' (the actual backtest-held exposure), not
    'last_signal' (mere sign of that exposure). They only coincide
    under sizing_mode='discrete'; the live default is 'continuous',
    where signal is just sign(position) and collapses every factor
    to exactly -1/0/+1 — which silently discarded all conviction
    sizing here and made Factor Model Scaling apply the same coeff
    to a barely-positive and a maximally-positive signal alike.
    last_position already lives on the backtest's own leverage
    scale (continuous: [-max_leverage, max_leverage]; discrete: the
    quantised level itself), matching what Candidates displays.
    """
    snapshot_records = []
    for _f, _s in factor_stats.items():
        _z = _s.get('z_score', 0.0)
        _lp = _s.get('last_position', _s.get('last_signal', 0.0))
        _icir = _s.get('icir', 0.0)
        _scalar = -float(_lp) if _f.startswith('IRSL.') else float(_lp)
        # IRSL is displayed as steepener on the positive side; flip the
        # stored scalar so Factor Model Scaling keeps the same convention.
        _bucket = _bucket_label(_scalar)
        _conf = (abs(_icir) >= 0.5) and 1.0 or (abs(_icir) >= 0.25) and 0.5 or 0.2
        snapshot_records.append({
            'risk_factor': _f,
            'scalar': _scalar,
            'signal': float(_z),
            'bucket_label': _bucket,
            'confidence': _conf,
            'risk_budget': 0.0,
        })
    return snapshot_records


def build_status_message(action, factor_stats, persist_note) -> str:
    mean_icir = (sum(s['icir'] for s in factor_stats.values()) /
                 len(factor_stats)) if factor_stats else 0.0
    status_prefix = "🔮 Model predicted" if action == 'predict' else "⚡ Model trained"
    _data_dates = [
        s['last_data_date'] for s in factor_stats.values()
        if s.get('last_data_date') is not None
    ]
    data_date_note = ""
    if _data_dates:
        _latest_data_date = max(_data_dates)
        try:
            _latest_data_date_str = _latest_data_date.strftime('%Y%m%d')
        except AttributeError:
            _latest_data_date_str = str(_latest_data_date)
        data_date_note = f" · using data on {_latest_data_date_str}"
    return f"{status_prefix}{data_date_note} · {persist_note} · Mean ICIR: {mean_icir:.2f}"
