# -*- coding: utf-8 -*-
"""FactorModel signal lookup and pure-RP trend-veto helpers.

Split out of the historical-allocation orchestrator (formerly
backtest_hist.py) as PLAIN FUNCTIONS taking their state explicitly (the
signal series / risk-factor frame) rather than closures over callback-local
variables. This is a prerequisite for the daily-resizing work: a plain
function can be called once per day from a vectorised loop, whereas a
closure captured inside a single monthly-cadence callback body cannot.
"""

from __future__ import annotations

import pandas as pd

from multiasset.factor_backtest import load_factor_backtest
from settings.paths import DIR_INPUT

# Pure-RP trend filter lookback — see trend_sign_asof docstring.
TREND_LOOKBACK_DAYS = 63  # ~3 trading months


def load_factor_signal_series(input_dir=DIR_INPUT) -> dict:
    """Load the daily FactorModel `position` series for every factor with a
    saved walk-forward backtest.

    Returns {factor_code: pd.Series} sorted by date, DatetimeIndex. Empty
    dict (not an exception) if factor-backtest.pkl is missing or has no
    'FactorModel' strategy — callers decide how to handle "no signals".
    """
    factor_signal_series: dict[str, pd.Series] = {}
    fm_results = load_factor_backtest(input_dir).get('FactorModel', {})
    for f_code, f_df in fm_results.items():
        if 'position' in f_df.columns:
            s = f_df['position'].dropna()
            if not isinstance(s.index, pd.DatetimeIndex):
                s.index = pd.to_datetime(s.index)
            factor_signal_series[f_code] = s.sort_index()
    return factor_signal_series


def factor_signal_asof(factor_signal_series: dict, factor_code: str,
                       asof_date) -> float | None:
    """Most-recent FactorModel position for `factor_code` on/before `asof_date`.

    Accepts ANY date, not just a rebalance date — this is what makes it
    reusable for daily resizing (see docs/plans/beta_book_exposure_vs_capital.md
    Step 4), unlike the original which was only ever called with
    `rebalance_date`.
    """
    s = factor_signal_series.get(factor_code)
    if s is None:
        return None
    s = s.loc[s.index <= asof_date]
    return float(s.iloc[-1]) if len(s) else None


def build_trend_factor_by_asset(factor_to_asset_map: dict) -> dict:
    """asset_name -> FXDL/CMDL factor_code, for trend_sign_asof's lookup.

    Only FX and commodity factors carry a trend veto in Pure-RP mode (see
    trend_sign_asof) — rates/credit/spread assets are untouched, RP's job
    there is duration risk parity, not direction.
    """
    trend_factor_by_asset: dict[str, str] = {}
    for f_code, assets in factor_to_asset_map.items():
        if f_code.startswith('FXDL.') or f_code.startswith('CMDL.'):
            for a in assets:
                trend_factor_by_asset[a['name']] = f_code
    return trend_factor_by_asset


def trend_sign_asof(asset_name: str, asof_date, risk_factors: pd.DataFrame,
                    trend_factor_by_asset: dict,
                    lookback_days: int = TREND_LOOKBACK_DAYS) -> float:
    """Sign of trailing `lookback_days`-day change in `asset_name`'s FXDL/CMDL
    factor level as of `asof_date`; +1/-1, or +1 (long, i.e. no-op) if
    undetermined (not an FX/commodity asset, or not enough history yet).

    Pure Risk Parity has no directional signal, so it would otherwise hold
    every FX pair and commodity long unconditionally — for FX this means an
    unconditional long-foreign-currency book that bleeds during a sustained
    CNY appreciation trend. This sign, multiplied into the asset's RP
    weight, zeroes a position whose 3-month momentum has turned negative.
    """
    factor_code = trend_factor_by_asset.get(asset_name)
    if factor_code is None or factor_code not in risk_factors.columns:
        return 1.0
    s = risk_factors[factor_code].loc[risk_factors.index <= asof_date].dropna()
    if len(s) < lookback_days + 1:
        return 1.0
    change = float(s.iloc[-1] - s.iloc[-(lookback_days + 1)])
    if change == 0.0:
        return 1.0
    return 1.0 if change > 0 else -1.0
