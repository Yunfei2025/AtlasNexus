# -*- coding: utf-8 -*-
"""Historical Portfolio Allocation backtest — orchestration logic.

Extracted as a PLAIN, TESTABLE function (`run_historical_allocation`) from
what was previously the body of a single Dash callback
(backtest_hist.py:219-1056, no `@app.callback` decorator here). The Dash
wiring itself lives in register.py; this module has no Dash import and can
be called directly from tests or a future daily-resizing loop.

No behaviour change from the original — this is Step 1 of
docs/plans/beta_book_exposure_vs_capital.md (pure file split). Carry/capital
split, daily resizing, funding, and the capital constraint all land in later
steps.
"""

from __future__ import annotations

import traceback

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

from multiasset.data import load_raw_market_data, get_asset_type
from multiasset.main import create_custom_portfolio
from multiasset.risk_loader import RiskFactorLoader
from multiasset.factor_optimizer import FactorRiskParityOptimizer
from multiasset.factor_backtest import compute_portfolio_metrics, compute_metrics
from multiasset.config import RiskModelConfig
from multiasset.backtest_cache import RPCacheParams, load_rp, save_rp, rp_hash
from settings.paths import DIR_INPUT

from ...data import SELECTED_FACTOR_POOL, get_assets_from_factors, FACTOR_TO_ASSET_MAP
from ._signals import (
    load_factor_signal_series, factor_signal_asof,
    build_trend_factor_by_asset, trend_sign_asof,
)
from ._pnl import compute_turnover_and_tx_cost
from multiasset.book.pnl import compute_book_pnl
from multiasset.book.capital import weights_to_notional


class NoSignalsAvailable(Exception):
    """Raised when alloc_mode == 'factor_scaling' but factor-backtest.pkl has
    no saved FactorModel signals — caller (register.py) renders the
    "run Individual Factors first" message instead of a traceback."""


class BacktestInputError(Exception):
    """Raised for user-facing input problems (too few factors, no data for
    the selected period, etc.). Carries the figure title and div message
    SEPARATELY, since the original single-file callback used different text
    for each at every call site (e.g. figure title "No risk factor data
    available" but div text "No data") — register.py renders both exactly
    as the original did, not `str(exc)` twice."""

    def __init__(self, fig_title: str, div_message: str, themed: bool = True):
        super().__init__(fig_title)
        self.fig_title = fig_title
        self.div_message = div_message
        # `themed` distinguishes the two original layout variants: some
        # error figures only set `title` + `template` (themed=False), others
        # additionally set paper_bgcolor/plot_bgcolor/font (themed=True).
        self.themed = themed


def _all_selected_factors() -> list:
    all_factors = []
    all_factors.extend(SELECTED_FACTOR_POOL.get('ir_factors', []))
    all_factors.extend(SELECTED_FACTOR_POOL.get('sp_factors', []))
    all_factors.extend(SELECTED_FACTOR_POOL.get('cr_factors', []))
    all_factors.extend(SELECTED_FACTOR_POOL.get('fx_factors', []))
    all_factors.extend(SELECTED_FACTOR_POOL.get('cmd_factors', []))
    all_factors.extend(SELECTED_FACTOR_POOL.get('eq_factors', []))
    return all_factors


def run_historical_allocation(
    total_capital, capital_unit, start_date, end_date,
    corr_lookback, top_pairs, alloc_mode,
    input_dir=DIR_INPUT,
) -> dict:
    """Run the Historical Portfolio Allocation backtest.

    Correlation-Based Historical Allocation Strategy:
    1. At each month start, run correlation analysis on risk factors
    2. Select assets with lowest correlations for diversification
    3. Run Risk Parity (1/Vol) allocation on the selected assets
    4. Track asset pool changes over time

    Returns a dict with keys: fig_alloc_data, fig_pnl_data, metrics, results_payload,
    asset_holdings_rows, sorted_rebalance_dates, all_assets_ever, display_start,
    display_end — everything register.py/figures.py need to render, with zero
    Dash objects constructed here so this function stays plain and testable.

    Raises NoSignalsAvailable / BacktestInputError for the user-facing error
    cases the original callback rendered as an error figure; raises any
    other exception verbatim (caller decides how to report it).
    """
    alloc_mode = alloc_mode or 'risk_parity'

    # ── Factor Model Scaling: load saved per-factor signal series ──────────
    # When factor scaling is requested, each asset's risk-parity weight is
    # tilted by the FactorModel signal (`position` in ~[-1, 1]) of the
    # factor(s) it maps from, as of each rebalance date. Signals come from
    # the walk-forward factor backtest persisted in factor-backtest.pkl.
    factor_signal_series = {}
    if alloc_mode == 'factor_scaling':
        try:
            factor_signal_series = load_factor_signal_series(input_dir)
        except Exception as e:
            print(f"  Warning: Could not load factor model signals: {e}")

        if not factor_signal_series:
            raise NoSignalsAvailable("No FactorModel signals found in factor-backtest.pkl.")

    # Parse dates
    start_date = pd.to_datetime(start_date) if start_date else None
    end_date = pd.to_datetime(end_date) if end_date else None
    top_pairs = int(top_pairs) if top_pairs else 10

    # Load risk factor data
    loader = RiskFactorLoader(input_dir)
    risk_factors = loader.load_risk_factors(use_cache=True)
    risk_factors.index = pd.to_datetime(risk_factors.index)
    # Some factor columns carry stray None entries (vs NaN), which makes the
    # column object-dtype and breaks .diff() with "unsupported operand
    # type(s) for -: 'NoneType' and 'float'". Coerce to numeric so gaps are
    # proper NaN.
    risk_factors = risk_factors.apply(pd.to_numeric, errors='coerce')
    market_data = load_raw_market_data()

    if risk_factors.empty:
        raise BacktestInputError("No risk factor data available", "No data", themed=False)

    trend_factor_by_asset = build_trend_factor_by_asset(FACTOR_TO_ASSET_MAP)

    def _factor_signal_asof(factor_code, asof_date):
        return factor_signal_asof(factor_signal_series, factor_code, asof_date)

    def _trend_sign_asof(asset_name, asof_date):
        return trend_sign_asof(asset_name, asof_date, risk_factors, trend_factor_by_asset)

    # Get selected factors from global factor pool (set in Factor tab)
    selected_factors = _all_selected_factors()

    if len(selected_factors) < 2:
        raise BacktestInputError(
            "⚠️ Please select at least 2 factors in the Factor tab first",
            "Go to Factor tab and select factors for the analysis pool.",
        )

    print(f"Using factor pool from Factor tab: {selected_factors}")

    # Filter risk_factors to only include selected factors that exist in data
    available_factors = [f for f in selected_factors if f in risk_factors.columns]
    if len(available_factors) < 2:
        missing = [f for f in selected_factors if f not in risk_factors.columns]
        raise BacktestInputError(
            f"⚠️ Only {len(available_factors)} of selected factors found in data",
            f"Missing factors: {missing}",
        )

    # Get the actual data range for selected factors
    # Use dropna(how='any') to ensure ALL selected factors have data
    selected_factor_data = risk_factors[available_factors].dropna(how='any')
    factor_data_start = selected_factor_data.index.min()
    factor_data_end = selected_factor_data.index.max()

    # Find which factor limits the start date (latest starting factor)
    limiting_factors = []
    for f in available_factors:
        f_start = risk_factors[f].dropna().index.min()
        if f_start is not None and f_start >= factor_data_start - pd.Timedelta(days=30):
            limiting_factors.append((f, f_start.date()))
    limiting_factors.sort(key=lambda x: x[1], reverse=True)

    print(f"Available factors in data: {available_factors}")
    print(f"Selected factor data range (ALL factors): {factor_data_start.date()} to {factor_data_end.date()}")
    if limiting_factors:
        print(f"Limiting factors (latest start): {limiting_factors[:3]}")

    # Set date range
    if not end_date:
        end_date = factor_data_end
    if not start_date:
        start_date = end_date - relativedelta(years=1)

    # Determine correlation lookback period and factor vol lookback
    if corr_lookback == '3M':
        corr_lookback_delta = relativedelta(months=3)
        vol_lookback_months = 3
    elif corr_lookback == '6M':
        corr_lookback_delta = relativedelta(months=6)
        vol_lookback_months = 6
    elif corr_lookback == '1Y':
        corr_lookback_delta = relativedelta(years=1)
        vol_lookback_months = 12
    else:
        corr_lookback_delta = relativedelta(months=3)
        vol_lookback_months = 3

    # Calculate earliest valid rebalance date based on selected factor data
    earliest_valid_date = factor_data_start + corr_lookback_delta

    # Auto-adjust start date if it's before the minimum supported date
    if start_date < earliest_valid_date:
        print(f"⚠️  Start date {start_date.date()} is before earliest valid date {earliest_valid_date.date()}")
        print(f"   Using earliest valid date: {earliest_valid_date.date()}")
        start_date = earliest_valid_date

    # Generate rebalance dates (beginning of each month) - starting from earliest valid date
    rebalance_dates = []
    current_date = start_date.replace(day=1)
    while current_date <= end_date:
        rebalance_dates.append(current_date)
        current_date += relativedelta(months=1)

    if not rebalance_dates:
        raise BacktestInputError(
            "Not enough historical data for the selected period", "Insufficient data", themed=False,
        )

    # Convert capital
    total_capital_value = float(total_capital) if total_capital else 100
    if capital_unit == 'billion':
        total_capital_value *= 1_000
    total_capital_cny = total_capital_value * 1_000_000  # Convert to CNY

    # Track allocations and asset changes
    history_data = []
    allocations_by_date = {}
    asset_pools_by_date = {}  # Track asset pool changes
    final_weights_by_date = {}  # rebalance_date -> {asset_name: blended weight fraction}
    all_assets_ever = set()

    print(f"\n{'='*60}")
    print(f"Running Correlation-Based Backtest: {start_date.date()} to {end_date.date()}")
    print(f"Rebalance dates: {len(rebalance_dates)}")
    print(f"First rebalance: {rebalance_dates[0].date() if rebalance_dates else 'N/A'}")
    print(f"Last rebalance: {rebalance_dates[-1].date() if rebalance_dates else 'N/A'}")
    print(f"{'='*60}")

    # ── Step A: pure risk-parity (RP) weights — cached, independent of
    #    factor-scaling selection. Adding/removing a factor from the
    #    scaling pool never forces this to recompute.
    rp_params = RPCacheParams(
        rebalance_dates=tuple(sorted(d.strftime('%Y-%m-%d') for d in rebalance_dates)),
        corr_lookback=corr_lookback or '3M',
        top_pairs=top_pairs,
        factor_pool=tuple(sorted(available_factors)),
        factor_model_lookback_years=1.0,
        ewma_lambda=RiskModelConfig.FACTOR_VOL_EWMA_LAMBDA,
        use_vol_sqrt_budgets=True,
        use_dv01_shape=True,
        bounds_version="RiskModelConfig.v3",
    )
    rp_h = None
    last_corr_matrix = None
    cached_rp = load_rp(input_dir, rp_params)
    if cached_rp is not None:
        rp_weights_by_date = cached_rp['weights_by_date']
        asset_pools_by_date = cached_rp['asset_pools_by_date']
        screened_factors_by_date = cached_rp['screened_factors_by_date']
        last_corr_matrix = cached_rp.get('last_corr_matrix')
        stage2_ctx_by_date = cached_rp.get('stage2_ctx_by_date', {})
        rp_h = rp_hash(rp_params)
        print(f"  RP base: cache hit ({rp_h})")
    else:
        rp_weights_by_date = {}  # rebalance_date -> {asset_name: weight}
        asset_pools_by_date = {}
        screened_factors_by_date = {}  # rebalance_date -> [factor_code, ...]
        # rebalance_date -> Stage2Context | None (None when fit_and_calculate
        # took the _optimize_weights branch). Lets Step 4's daily loop
        # rebuild per-tenor weights with a rescaled factor budget without
        # re-running Stage 1's SLSQP solve — see
        # docs/plans/beta_book_exposure_vs_capital.md Step 4.
        stage2_ctx_by_date = {}

        # Cache of portfolio+optimizer keyed by frozenset of asset names.
        # Re-using objects avoids redundant construction for recurring asset sets
        # while still allowing the asset set to change month-to-month.
        optimizer_cache: dict = {}

        for rebalance_date in rebalance_dates:
            # --- Step 1: Rolling correlation screen on the lookback window ---
            corr_end = rebalance_date
            corr_start = rebalance_date - corr_lookback_delta

            df_subset = risk_factors.loc[corr_start:corr_end,
                                         [f for f in available_factors if f in risk_factors.columns]]
            if df_subset.empty or len(df_subset) < 20:
                print(f"  {rebalance_date.date()}: Skipped (insufficient data)")
                continue

            df_changes = df_subset.diff().dropna()
            if df_changes.empty:
                continue

            corr_matrix = df_changes.corr()
            last_corr_matrix = corr_matrix

            # Find the `top_pairs` lowest-correlation factor pairs in this window
            mask = np.triu(np.ones(corr_matrix.shape), k=1).astype(bool)
            corr_stacked = corr_matrix.where(mask).stack().reset_index()
            corr_stacked.columns = ['Factor A', 'Factor B', 'Correlation']
            corr_stacked['AbsCorrelation'] = corr_stacked['Correlation'].abs()
            bottom_pairs = corr_stacked.sort_values('AbsCorrelation').head(top_pairs)

            low_corr_factors = (
                set(bottom_pairs['Factor A']) | set(bottom_pairs['Factor B'])
            )
            low_corr_factors_list = sorted(low_corr_factors)

            # --- Step 2: Map screened factors → assets ---
            selected_assets = get_assets_from_factors(low_corr_factors_list)

            if not selected_assets:
                print(f"  {rebalance_date.date()}: Skipped (no mappable assets)")
                continue

            selected_asset_names = [a['name'] for a in selected_assets]

            # --- Step 3: Optimise with time-varying EWMA covariance ---
            # Re-use a cached portfolio/optimizer when the asset set is the same
            # as a previous month; the rolling vol window still changes because
            # fit_and_calculate() slices by rebalance_date.
            key = frozenset(selected_asset_names)
            if key not in optimizer_cache:
                try:
                    port = create_custom_portfolio(selected_asset_names, use_deterministic=True)
                    opt = FactorRiskParityOptimizer(
                        portfolio=port,
                        input_dir=str(input_dir),
                        factor_model_lookback_years=1.0,
                        vol_lookback_months=vol_lookback_months,
                        ewma_lambda=RiskModelConfig.FACTOR_VOL_EWMA_LAMBDA,
                    )
                    optimizer_cache[key] = opt
                except Exception as e:
                    print(f"  {rebalance_date.date()}: Portfolio creation failed: {e}")
                    continue

            try:
                weights_series, _ = optimizer_cache[key].fit_and_calculate(
                    pd.Timestamp(rebalance_date),
                    use_vol_sqrt_budgets=True,
                    # use_dv01_shape=True (default): two-stage — ERC across factors
                    # (stage 1, rolling covariance) then a DV01-anchored, ridge-
                    # regularised tilt within each factor group (stage 2) that lets
                    # the tenor split respond to how slope/curvature budgets move
                    # relative to level, controlled by tilt_lambda (default from
                    # RiskModelConfig.TENOR_TILT_LAMBDA).
                )
                weights = weights_series.to_dict()
            except Exception as e:
                print(f"  {rebalance_date.date()}: Factor risk optimization failed: {e}")
                continue

            if not weights or sum(weights.values()) == 0:
                print(f"  {rebalance_date.date()}: Skipped (invalid weights)")
                continue

            # Filter out negligible weights (floating point precision artifacts)
            weights = {k: v for k, v in weights.items() if abs(v) >= 1e-6}

            # Renormalize weights after filtering
            weight_sum = sum(weights.values())
            if weight_sum > 0:
                weights = {k: v / weight_sum for k, v in weights.items()}
            else:
                continue

            rp_weights_by_date[rebalance_date] = weights
            filtered_assets = [a for a in selected_assets if a['name'] in weights]
            asset_pools_by_date[rebalance_date] = filtered_assets
            screened_factors_by_date[rebalance_date] = low_corr_factors_list
            stage2_ctx_by_date[rebalance_date] = optimizer_cache[key].stage2_context()

            print(f"  {rebalance_date.date()}: {len(selected_asset_names)} assets, {len(low_corr_factors_list)} screened factors (of {len(available_factors)} total)")

        rp_h = save_rp(input_dir, rp_params, rp_weights_by_date, asset_pools_by_date, screened_factors_by_date, last_corr_matrix, stage2_ctx_by_date)
        print(f"  RP base: computed and cached ({rp_h})")

    # ── Step B/C: daily positions. Stage 1 (above) stays MONTHLY and is the
    #    Pure Risk Parity base. factor_scaling does NOT resize that long-only
    #    base any more: it holds signed per-factor sleeves (each factor's own
    #    mimicking portfolio x its lagged FactorModel position), rebuilt daily
    #    — see multiasset.book.sizing.signed_sleeve_weights_daily. The old
    #    resize-the-RP-base path could not express short/flat level views or
    #    slope/curvature long-short factor returns, so it scored ~0.03 Sharpe
    #    against ~1.36 for the same signals traded as factors.
    all_dates = sorted(risk_factors.loc[(risk_factors.index >= start_date) & (risk_factors.index <= end_date)].index)
    daily_idx = pd.DatetimeIndex(all_dates)

    unreplicated_factors: list = []
    if alloc_mode == 'factor_scaling':
        # Signed factor sleeves: each factor holds budget_f x position_f x its
        # own mimicking portfolio (see multiasset.book.sizing), so the book
        # earns the combination of the Individual Factors strategies instead
        # of a long-only bond book that can't express short/flat or
        # slope/curvature views. Stage 1's monthly reference budget (the
        # vol^0.5-constrained ERC) still sets each factor's capital share.
        from multiasset.book.sizing import signed_sleeve_weights_daily, pool_sleeve_budgets
        from multiasset.factor_backtest import compute_ewma_factor_vols

        # Sleeve capital budgets over the pool's OWN screened factors each
        # month (vol^0.5 for IR, equal otherwise — same rule as the
        # Portfolio tab), from EWMA vol on data up to the rebalance date.
        budget_by_rebalance_date = {}
        for rebalance_date, pool_factors in screened_factors_by_date.items():
            window = risk_factors.loc[
                (risk_factors.index >= rebalance_date - relativedelta(months=vol_lookback_months))
                & (risk_factors.index <= rebalance_date), list(pool_factors)
            ]
            vol_map = compute_ewma_factor_vols(window, ewma_lambda=RiskModelConfig.FACTOR_VOL_EWMA_LAMBDA)
            budget_by_rebalance_date[rebalance_date] = pool_sleeve_budgets(pool_factors, vol_map)
        weights_daily, mod_dur_daily, unreplicated_factors = signed_sleeve_weights_daily(
            budget_by_rebalance_date, factor_signal_series, daily_idx,
            FACTOR_TO_ASSET_MAP, market_data,
            long_only_assets=RiskModelConfig.SHORT_END_LONG_ONLY_TENORS,
        )
        if unreplicated_factors:
            print(f"  factor_scaling: no sleeve (not replicable or no saved signal): {unreplicated_factors}")
        if weights_daily.empty or not weights_daily.abs().to_numpy().any():
            raise BacktestInputError(
                "No valid rebalance periods found", "No valid periods", themed=False,
            )
        all_assets_ever.update(weights_daily.columns)

        # Scale the sleeve book up toward a DV01 target — signed_sleeve_
        # weights_daily's weights are DV01-equalised PER FACTOR UNIT, not
        # sized to any capital/risk target (unscaled, the book sits at
        # whatever gross the vol^0.5 budgets happen to produce — measured
        # ~11% average for a 3-factor CN pool). See scale_sleeve_to_dv01_target.
        from multiasset.book.sizing import scale_sleeve_to_dv01_target
        weights_daily = scale_sleeve_to_dv01_target(
            weights_daily, mod_dur_daily, total_capital_cny,
            RiskModelConfig.MAX_DV01_PER_CAPITAL, RiskModelConfig.CAPITAL_UTILISATION_MAX,
        )
        # Kept for the 'book_dv01_mm' KPI below — the DV01 actually achieved
        # after scaling, in MM CNY/bp, same units as the Portfolio tab's
        # DV01 display and RiskModelConfig.MAX_DV01_PER_CAPITAL's target.
        book_dv01_daily_mm = ((weights_daily * mod_dur_daily).abs().sum(axis=1)
                              * (total_capital_cny / 1e10))
    else:
        book_dv01_daily_mm = None
        # Pure Risk Parity: no directional signal drives this mode, so it
        # otherwise holds every FX pair and commodity long unconditionally.
        # Zero out (long-only, so "short" isn't representable) any FX/
        # commodity asset whose 3M momentum is negative, then redistribute
        # the freed capital across the remaining assets. Evaluated ONLY at
        # each rebalance_date (monthly), same as before Step 4 of
        # docs/plans/beta_book_exposure_vs_capital.md — unlike
        # factor_scaling's FactorModel signal, the trend veto's cadence was
        # never part of that step's scope (it materially changes results —
        # measured ~28% of days across ~60% of months differ between daily
        # and monthly evaluation on a 3yr window — and wasn't a decision
        # made for this refactor), so it stays exactly as it was: computed
        # once per rebalance month, then forward-filled onto every trading
        # day until the next rebalance.
        monthly_weights: dict = {}
        for rebalance_date, weights in rp_weights_by_date.items():
            trended = {
                k: v for k, v in weights.items()
                if _trend_sign_asof(k, pd.Timestamp(rebalance_date)) > 0
            }
            trended_sum = sum(trended.values())
            if trended_sum > 1e-9:
                weights = {k: v / trended_sum for k, v in trended.items()}
            # else: every trend-filtered asset was vetoed (all momentum
            # negative) — keep the unfiltered RP weights rather than
            # producing an empty allocation for this rebalance.
            monthly_weights[rebalance_date] = weights
            all_assets_ever.update(weights.keys())

        rp_dates = sorted(monthly_weights.keys())
        weights_rows: dict = {}
        rb_idx = 0
        current_rb = None
        for d in daily_idx:
            while rb_idx < len(rp_dates) and rp_dates[rb_idx] <= d:
                current_rb = rp_dates[rb_idx]
                rb_idx += 1
            if current_rb is None:
                continue
            weights_rows[d] = pd.Series(monthly_weights[current_rb])

        weights_daily = pd.DataFrame(weights_rows).T if weights_rows else pd.DataFrame()
        if weights_daily.empty:
            raise BacktestInputError(
                "No valid rebalance periods found", "No valid periods", themed=False,
            )

    # Capital applied once, on the daily weight matrix (never per-factor,
    # so summing contributions from N factors cannot inflate total deployed
    # capital), via weights_to_notional's long-only (except FX)
    # utilisation-capped sizing — see
    # docs/plans/beta_book_exposure_vs_capital.md Step 7. Applied ROW BY
    # ROW (once per day), not once per rebalance — a single day where
    # several factors' daily coefficients spike together must still be
    # caught and scaled back to the 95% ceiling, independent of how the
    # monthly reference budget was sized (see
    # test_single_day_spike_across_multiple_factors_still_respects_cap in
    # tests/test_capital_constraint.py). This is the change that lets a
    # bearish day genuinely de-risk (gross < 95%, remainder in cash — see
    # multiasset.book.funding.cash_return_daily) instead of always being
    # renormalised back up to 100% invested, which is what the pre-Step-7
    # code did unconditionally.
    weights_daily = weights_daily.fillna(0.0)
    asset_class_of_capital = {
        name: {'Commodities': 'comm', 'FX': 'fx', 'Credit': 'credit'}.get(get_asset_type(name), 'bond')
        for name in weights_daily.columns
    }
    # factor_scaling holds signed sleeves (shorts are part of the replicated
    # strategies); Pure Risk Parity stays long-only except FX.
    signed_classes = ('fx', 'bond', 'comm', 'credit') if alloc_mode == 'factor_scaling' else ('fx',)
    notional_rows = {
        d: weights_to_notional(weights_daily.loc[d], total_capital_cny,
                               asset_class_of=asset_class_of_capital, signed_classes=signed_classes)
        for d in weights_daily.index
    }
    allocations_daily = pd.DataFrame(notional_rows).T.reindex(columns=weights_daily.columns).fillna(0.0)

    # history_data / allocations_by_date / final_weights_by_date stay
    # MONTHLY (one row per rebalance date) for the allocation chart and the
    # "final weights" payload used elsewhere — sampling the (now daily)
    # weights_daily at each rebalance date reproduces exactly what those
    # consumers expect, while the P&L path below uses the full daily series.
    for rebalance_date in sorted(rp_weights_by_date.keys()):
        # rebalance_date is the 1st of the month, which is frequently not a
        # trading day (weekend/holiday) and so is never itself a row in
        # weights_daily (indexed by actual trading days from daily_idx) —
        # sample the first trading day ON OR AFTER it instead. This mirrors
        # what the old monthly forward-fill implicitly did (a rebalance on
        # a non-trading day took effect on the next trading day).
        candidates = weights_daily.index[weights_daily.index >= rebalance_date]
        if len(candidates) == 0:
            continue
        sample_date = candidates[0]
        row_weights = weights_daily.loc[sample_date]
        # Use the capital-constrained notional (allocations_daily), not a
        # fresh weight*capital recompute — a day where gross weight exceeds
        # the utilisation ceiling has already been scaled down by
        # weights_to_notional above, and the displayed/saved allocation
        # must reflect that, not the pre-cap weight.
        row_alloc = allocations_daily.loc[sample_date]
        row = {'Date': rebalance_date}
        current_allocations = {}
        for name, alloc in row_alloc.items():
            if alloc == 0.0:
                continue
            row[name] = float(alloc) / 1_000_000  # Store in millions for chart
            current_allocations[name] = float(alloc)
        history_data.append(row)
        allocations_by_date[rebalance_date] = current_allocations
        final_weights_by_date[rebalance_date] = {k: float(v) for k, v in row_weights.items() if v != 0.0}

    if not history_data:
        raise BacktestInputError(
            "No valid rebalance periods found", "No valid periods", themed=False,
        )

    # Use user-selected date range for display (we already validated it's valid)
    display_start = start_date
    display_end = end_date
    sorted_rebalance_dates = sorted(allocations_by_date.keys())

    # --- Vectorised daily PnL, split into capital gain vs carry ───────────
    # allocations_daily is already a genuinely daily (not monthly-forward-
    # filled) CNY notional matrix — see Step B/C above.
    # compute_book_pnl (Step 5, multiasset/book/pnl.py) reads each asset's
    # calculate_daily_returns_series ONCE and keeps ['carry','capital','total']
    # together — capital_gain[d,a] = notional[d,a]*capital[d,a] (== DV01 x dy),
    # carry[d,a] = notional[d,a]*carry[d,a] (== notional x yield/365), and
    # `other` for FX/commodity assets where no clean split exists (their
    # whole P&L, unsplit — see returns_split_is_exact). `daily_pnl_m` below
    # is BookPnL.total (all three combined) in millions CNY, matching the
    # pre-Step-5 combined-return convention exactly — nothing downstream of
    # this changes shape; the split components are exposed in the returned
    # dict for callers that want to report them separately (e.g. a future
    # carry/capital-gain breakdown panel), but this function's own NAV/
    # Sharpe/turnover math is unaffected either way.
    alloc_daily = (
        allocations_daily
        .reindex(daily_idx)
        .reindex(columns=sorted(all_assets_ever))
        .fillna(0.0)
    )
    book_pnl = compute_book_pnl(alloc_daily, market_data, start_date, end_date)
    daily_pnl_m = book_pnl.total / 1_000_000

    # ── Step 6: funding hurdle (Sharpe only, never in P&L) + cash return
    #    on undeployed capital (decision #7 — real earned return, IS added
    #    to P&L). See docs/plans/beta_book_exposure_vs_capital.md Step 6 /
    #    multiasset/book/funding.py.
    from multiasset.book.funding import build_domicile_of, book_funding_cost_daily, cash_return_daily
    domicile_of = build_domicile_of(alloc_daily.columns, market_data)
    funding_cost_cny = book_funding_cost_daily(alloc_daily, domicile_of)
    # Decimal RATE series (not CNY) for compute_portfolio_metrics's
    # funding_hurdle param — that function annualises and subtracts it from
    # the Sharpe numerator only, never from Ann. Return/Vol (see its
    # docstring for why: funding must never enter the vol denominator).
    funding_hurdle_rate = (funding_cost_cny / total_capital_cny).reindex(daily_idx).fillna(0.0)
    # cash_return_daily needs Step 7's max_utilisation to know how much
    # capital is "undeployed" — Step 7 hasn't landed yet, so this call uses
    # the default (0.95) as a placeholder; it will start reflecting actual
    # de-risking once weights_to_notional enforces that ceiling upstream.
    cash_daily_cny = cash_return_daily(alloc_daily, total_capital_cny)
    cash_daily_m = cash_daily_cny.reindex(daily_idx).fillna(0.0) / 1_000_000

    # Average capital usage / cash income — for the KPI panel, so a modest
    # DV01 target (or a signal that's often flat) is visible as "most of the
    # book sits in cash, earning FR007" rather than a mysteriously low
    # post-funding Sharpe with no explanation.
    avg_capital_usage = float((alloc_daily.abs().sum(axis=1) / total_capital_cny).mean())
    avg_cash_income_pct = float(cash_daily_cny.sum() / total_capital_cny
                                / max((end_date - start_date).days / 365.25, 1e-3))

    # Step 8: turnover/tx-cost on DAILY notional deltas (alloc_daily is
    # already the capital-constrained notional from Step 7), not monthly
    # weight deltas — positions can move every day since Step 4, so a cost
    # model that only charges at rebalance dates silently missed every
    # day's actual trading.
    turnover_daily, tx_cost_m, total_tx_cost_m = compute_turnover_and_tx_cost(alloc_daily)
    n_years = max((end_date - start_date).days / 365.25, 1e-3)
    # turnover_daily is raw CNY notional traded; ann_turnover is reported as
    # a MULTIPLE of total capital (e.g. "487%" via the KPI grid's `.0%`
    # formatting) — divide by total_capital_cny, not just by n_years, or
    # this comes out in raw CNY units (previously this was already a weight
    # fraction, since the pre-Step-8 version worked on wt_df, not notional).
    ann_turnover = float(turnover_daily.sum()) / total_capital_cny / n_years

    gross_daily = daily_pnl_m.sum(axis=1) + cash_daily_m
    cumulative_m = daily_pnl_m.cumsum()
    cumulative_m.insert(0, 'Date', daily_idx)
    cumulative_m['Total'] = gross_daily.cumsum()
    cumulative_m['Total (net)'] = (gross_daily - tx_cost_m.values).cumsum()

    df_history = pd.DataFrame(history_data)
    df_pnl = cumulative_m.reset_index(drop=True)
    # Unrounded copy for NAV/Sharpe/drawdown — the rounding below is for
    # display only. Computing metrics on whole-million P&L quantised a
    # 100MM book to 1% NAV steps and distorted every Sharpe/drawdown.
    df_pnl_exact = df_pnl.copy()

    # Round time series to integers (million CNY)
    for col in df_history.columns:
        if col != 'Date':
            df_history[col] = df_history[col].round().astype('Int64')
    for col in df_pnl.columns:
        if col != 'Date':
            df_pnl[col] = df_pnl[col].round().astype('Int64')

    # --- NAV index (base 1000) and Performance Metrics ---
    metrics = None
    nav_series = None
    nav_net_series = None
    if not df_pnl.empty and len(df_pnl) > 1:
        initial_capital = total_capital_cny / 1_000_000
        portfolio_values = initial_capital + df_pnl_exact['Total']
        net_portfolio_values = initial_capital + df_pnl_exact['Total (net)']
        nav_series = (portfolio_values / portfolio_values.iloc[0]) * 1000
        nav_net_series = (net_portfolio_values / net_portfolio_values.iloc[0]) * 1000

        perf = compute_portfolio_metrics(
            portfolio_values,
            risk_free_rate=RiskModelConfig.RISK_FREE_RATE,
        )
        perf_net = compute_portfolio_metrics(
            net_portfolio_values,
            risk_free_rate=RiskModelConfig.RISK_FREE_RATE,
        )
        # portfolio_values has a plain RangeIndex (df_pnl was reset_index'd),
        # while funding_hurdle_rate is indexed by daily_idx (Timestamps) —
        # compute_metrics's internal .reindex(rets.index) would silently
        # zero the hurdle on a type mismatch, so align positionally here
        # (funding_hurdle_rate and daily_pnl_m/df_pnl are already built off
        # the same daily_idx, so position i in one corresponds to position i
        # in the other).
        funding_hurdle_for_metrics = pd.Series(
            funding_hurdle_rate.to_numpy(), index=portfolio_values.index,
        )
        # risk_free_rate=0.0 here, NOT RiskModelConfig.RISK_FREE_RATE: FR007
        # (funding_hurdle, the book's actual position-weighted repo cost) and
        # the flat 2% risk-free rate are both proxies for "what CNY cash
        # could otherwise earn" — subtracting both double-counts the same
        # opportunity cost. Sharpe (gross)/(net tx) above still use the flat
        # hurdle (they have no funding line to compare against instead);
        # post-funding's hurdle IS the funding cost, already computed from
        # real notional x real FR007 (see book_funding_cost_daily), which is
        # the more accurate of the two for this line.
        perf_post_funding = compute_portfolio_metrics(
            portfolio_values,
            risk_free_rate=0.0,
            funding_hurdle=funding_hurdle_for_metrics,
        )
        annualized_return = perf.get('Ann. Return', 0.0)
        sharpe_ratio = perf.get('Sharpe', 0.0) or 0.0
        max_drawdown = perf.get('Max Drawdown', 0.0)
        sharpe_net = perf_net.get('Sharpe', 0.0) or 0.0
        sharpe_post_funding = perf_post_funding.get('Sharpe', 0.0) or 0.0
        ann_funding_cost = perf_post_funding.get('Ann. Funding Cost', 0.0) or 0.0

        # Sharpe on the SAME basis as the Individual Factors tab: price-only
        # P&L (no carry, no cash on undeployed capital), rf = 0. This is the
        # number to compare against the per-factor Sharpes; the gross/net/
        # post-funding Sharpes above are total-return book metrics.
        price_pnl = (book_pnl.capital_gain.sum(axis=1)
                     .add(book_pnl.other.sum(axis=1), fill_value=0.0)
                     .reindex(daily_idx).fillna(0.0))
        perf_price_only = compute_metrics(
            (price_pnl / total_capital_cny).rename('strategy_returns').to_frame(),
            risk_free_rate=0.0, geometric_annualisation=True,
        )
        sharpe_price_only = perf_price_only.get('Sharpe', 0.0) or 0.0

        # Average book DV01 achieved (factor_scaling only) — compare against
        # RiskModelConfig.MAX_DV01_PER_CAPITAL * total_capital_cny/1e10, the
        # target scale_sleeve_to_dv01_target aims for. None for risk_parity
        # (no sleeve DV01 series is built for that mode).
        avg_book_dv01_mm = (
            float(book_dv01_daily_mm.reindex(daily_idx).fillna(0.0).mean())
            if book_dv01_daily_mm is not None else None
        )

        metrics = {
            'annualized_return': annualized_return,
            'sharpe_ratio': sharpe_ratio,
            'sharpe_net': sharpe_net,
            'sharpe_post_funding': sharpe_post_funding,
            'sharpe_price_only': sharpe_price_only,
            'avg_book_dv01_mm': avg_book_dv01_mm,
            'avg_capital_usage': avg_capital_usage,
            'avg_cash_income_pct': avg_cash_income_pct,
            'unreplicated_factors': unreplicated_factors,
            'ann_funding_cost': ann_funding_cost,
            'max_drawdown': max_drawdown,
            'n_rebalances': len(allocations_by_date),
            'ann_turnover': ann_turnover,
            'total_tx_cost_m': total_tx_cost_m,
        }

    # --- Build Monthly Holdings rows ---
    asset_holdings_rows = []
    for rb_date in sorted_rebalance_dates:
        assets = asset_pools_by_date.get(rb_date, [])
        current_assets = sorted([a['name'] for a in assets])
        asset_holdings_rows.append({
            'Date': rb_date.strftime('%Y-%m'),
            'Asset Count': len(current_assets),
            'Holdings': ", ".join(current_assets) if current_assets else "-"
        })

    results_payload = None
    sorted_rb = sorted(final_weights_by_date.keys())
    if sorted_rb:
        # Serialize the last rebalance corr_matrix (factor-level) for the report
        corr_payload = None
        if last_corr_matrix is not None and not last_corr_matrix.empty:
            labels = list(last_corr_matrix.columns)
            values = [[round(float(v), 4) for v in row]
                      for row in last_corr_matrix.values]
            corr_payload = {'labels': labels, 'values': values}

        results_payload = {
            'weights_final': final_weights_by_date[sorted_rb[-1]],
            'weights_prev': final_weights_by_date[sorted_rb[-2]] if len(sorted_rb) > 1 else {},
            'rebalance_date': sorted_rb[-1].strftime('%Y-%m-%d'),
            'nav_dates': [d.strftime('%Y-%m-%d') for d in df_pnl['Date']],
            'nav_gross_values': nav_series.round(4).tolist() if nav_series is not None else [],
            'nav_net_values': nav_net_series.round(4).tolist() if nav_net_series is not None else [],
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d'),
            'alloc_mode': alloc_mode,
            'corr_matrix': corr_payload,
            # For the "Save Result" button -> multiasset.storage.save_backtest_result,
            # which the beta+alpha combination panel reads via load_last_backtest_result.
            'equity_series': [
                {'date': d.strftime('%Y-%m-%d'), 'value': float(v)}
                for d, v in zip(df_pnl_exact['Date'], df_pnl_exact['Total'])
            ] if not df_pnl.empty else [],
            'sharpe': float(metrics['sharpe_ratio']) if metrics is not None else 0.0,
            'annualized_return': float(metrics['annualized_return']) if metrics is not None else 0.0,
            'max_drawdown': float(metrics['max_drawdown']) if metrics is not None else 0.0,
            'asset_pool': sorted(all_assets_ever),
            'total_capital': float(total_capital_cny) / 1_000_000,
        }

    return {
        'df_history': df_history,
        'df_pnl': df_pnl,
        'nav_series': nav_series,
        'nav_net_series': nav_net_series,
        'metrics': metrics,
        'asset_holdings_rows': asset_holdings_rows,
        'results_payload': results_payload,
        'all_assets_ever': all_assets_ever,
        'display_start': display_start,
        'display_end': display_end,
    }
