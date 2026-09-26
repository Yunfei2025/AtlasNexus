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

import os
import traceback

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

from multiasset.data import load_raw_market_data, get_asset_type
from multiasset.main import create_custom_portfolio
from multiasset.risk_loader import RiskFactorLoader
from multiasset.factor_optimizer import FactorRiskParityOptimizer
from multiasset.factor_backtest import compute_portfolio_metrics
from multiasset.config import RiskModelConfig
from multiasset.backtest_cache import (
    RPCacheParams, FactorTiltCacheParams,
    load_rp, save_rp, load_factor_tilt, save_factor_tilt,
    scalar_to_coeff, rp_hash,
)
from settings.paths import DIR_INPUT

from ...data import SELECTED_FACTOR_POOL, get_assets_from_factors, FACTOR_TO_ASSET_MAP
from ._signals import (
    load_factor_signal_series, factor_signal_asof,
    build_trend_factor_by_asset, trend_sign_asof,
)
from ._pnl import (
    build_returns_matrix, build_daily_allocation, compute_daily_pnl_m,
    compute_turnover_and_tx_cost,
)


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
        rp_h = rp_hash(rp_params)
        print(f"  RP base: cache hit ({rp_h})")
    else:
        rp_weights_by_date = {}  # rebalance_date -> {asset_name: weight}
        asset_pools_by_date = {}
        screened_factors_by_date = {}  # rebalance_date -> [factor_code, ...]

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

            print(f"  {rebalance_date.date()}: {len(selected_asset_names)} assets, {len(low_corr_factors_list)} screened factors (of {len(available_factors)} total)")

        rp_h = save_rp(input_dir, rp_params, rp_weights_by_date, asset_pools_by_date, screened_factors_by_date, last_corr_matrix)
        print(f"  RP base: computed and cached ({rp_h})")

    # ── Step B: factor-scaling tilts — cached per factor, each keyed on
    #    the RP base it was tilted from. Adding factor N+1 only computes
    #    factor N+1's tilt; previously-cached factors are reused as-is.
    factor_tilts_by_factor: dict = {}
    if alloc_mode == 'factor_scaling':
        try:
            signal_pkl_mtime = os.path.getmtime(os.path.join(str(input_dir), 'factor-backtest.pkl'))
        except OSError:
            signal_pkl_mtime = 0.0

        for f_code in sorted(factor_signal_series.keys()):
            tilt_params = FactorTiltCacheParams(
                factor_code=f_code,
                scalar_to_coeff_version="v2",  # v2: FXDL is now directional (can short)
                factor_to_asset_map_version="v1",
                signal_pkl_mtime=signal_pkl_mtime,
                class_caps_version="RiskModelConfig.v1",
            )
            cached_tilt = load_factor_tilt(input_dir, rp_h, tilt_params)
            if cached_tilt is not None:
                factor_tilts_by_factor[f_code] = cached_tilt['tilt_weights_by_date']
                print(f"  Factor {f_code}: cache hit")
                continue

            tilt_rows = {}
            for rebalance_date, weights in rp_weights_by_date.items():
                # Only tilt with this factor on dates where it was actually
                # screened in (low_corr_factors_list) — matches the original
                # per-date asset_to_factors gating exactly.
                if f_code not in screened_factors_by_date.get(rebalance_date, ()):
                    continue
                mapped_assets = {a['name'] for a in FACTOR_TO_ASSET_MAP.get(f_code, [])}
                sig = _factor_signal_asof(f_code, pd.Timestamp(rebalance_date))
                if sig is None:
                    continue
                coeff = scalar_to_coeff(sig, f_code)
                tilt_rows[rebalance_date] = {
                    name: weight * coeff for name, weight in weights.items()
                    if name in mapped_assets
                }
            tilt_df = pd.DataFrame(tilt_rows).T
            factor_tilts_by_factor[f_code] = tilt_df
            save_factor_tilt(input_dir, rp_h, tilt_params, tilt_df)
            print(f"  Factor {f_code}: computed and cached")

    # ── Step C: blend per-date — average each asset's tilted weight
    #    across the factors that touch it, falling back to the RP
    #    weight for assets touched by zero factors, then renormalise,
    #    apply class caps, and finally apply capital ONCE to the
    #    blended vector (never per-factor, so summing contributions
    #    from N factors cannot inflate total deployed capital).
    class_caps = RiskModelConfig.CLASS_CAPS

    for rebalance_date, weights in rp_weights_by_date.items():
        if alloc_mode == 'factor_scaling' and factor_tilts_by_factor:
            blended = {}
            for name, rp_weight in weights.items():
                tilted_vals = []
                for f_code, tilt_df in factor_tilts_by_factor.items():
                    if rebalance_date in tilt_df.index and name in tilt_df.columns:
                        v = tilt_df.loc[rebalance_date, name]
                        if pd.notna(v):
                            tilted_vals.append(float(v))
                blended[name] = float(np.mean(tilted_vals)) if tilted_vals else rp_weight

            # FXDL is directional (scalar_to_coeff can return a negative
            # coefficient), so a bearish tilt can leave `blended[name]`
            # negative for an FX asset. Normalise by GROSS exposure
            # (sum of |v|), not net sum — net-sum normalisation would
            # distort every other asset's weight whenever a short
            # partially offsets the book's net total, and could blow up
            # if the net total crosses zero.
            total_scaled = sum(abs(v) for v in blended.values())
            if total_scaled > 1e-9:
                weights = {k: v / total_scaled for k, v in blended.items()}
                # Apply per-class caps then renormalise (iterate to spread
                # any excess evenly across uncapped assets). FX keeps a
                # signed cap [-cap, +cap] since it's directional; every
                # other class stays long-only clamped to [0, cap].
                for _ in range(3):
                    capped = {}
                    for k, v in weights.items():
                        cap = class_caps.get(get_asset_type(k), RiskModelConfig.CLASS_CAP_DEFAULT)
                        lo = -cap if get_asset_type(k) == 'FX' else 0.0
                        capped[k] = max(lo, min(v, cap))
                    cap_total = sum(abs(v) for v in capped.values())
                    if cap_total > 1e-9:
                        weights = {k: v / cap_total for k, v in capped.items()}
            else:
                print(f"  {rebalance_date.date()}: All signals zero, using RP weights")
                # weights already set from RP optimizer above, leave unchanged
        else:
            # Pure Risk Parity: no directional signal drives this mode, so it
            # otherwise holds every FX pair and commodity long unconditionally.
            # Zero out (long-only, so "short" isn't representable) any FX/
            # commodity asset whose 3M momentum is negative, then redistribute
            # the freed capital across the remaining assets. Factor Model
            # Scaling is untouched — it already gets FX/commodity direction
            # from the FactorModel signal via scalar_to_coeff.
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

        all_assets_ever.update(weights.keys())

        # Calculate allocations — capital applied once, on the final
        # (blended + capped, or pure-RP) weight vector.
        row = {'Date': rebalance_date}
        current_allocations = {}
        for name, weight in weights.items():
            alloc = weight * total_capital_cny
            row[name] = alloc / 1_000_000  # Store in millions for chart
            current_allocations[name] = alloc

        history_data.append(row)
        allocations_by_date[rebalance_date] = current_allocations
        final_weights_by_date[rebalance_date] = dict(weights)

    if not history_data:
        raise BacktestInputError(
            "No valid rebalance periods found", "No valid periods", themed=False,
        )

    # Use user-selected date range for display (we already validated it's valid)
    display_start = start_date
    display_end = end_date

    # --- Calculate Daily PnL ---
    all_dates = sorted(risk_factors.loc[(risk_factors.index >= start_date) & (risk_factors.index <= end_date)].index)
    sorted_rebalance_dates = sorted(allocations_by_date.keys())

    # --- Vectorised daily PnL ---
    daily_idx = pd.DatetimeIndex(all_dates)
    rets_matrix = build_returns_matrix(all_assets_ever, market_data, start_date, end_date, daily_idx)
    alloc_daily = build_daily_allocation(allocations_by_date, rets_matrix.columns, daily_idx)
    daily_pnl_m = compute_daily_pnl_m(alloc_daily, rets_matrix)

    turnover_by_date, tx_cost_m, total_tx_cost_m = compute_turnover_and_tx_cost(
        allocations_by_date, rets_matrix.columns, daily_idx, total_capital_cny,
    )
    n_years = max((end_date - start_date).days / 365.25, 1e-3)
    ann_turnover = float(turnover_by_date.sum()) / n_years

    gross_daily = daily_pnl_m.sum(axis=1)
    cumulative_m = daily_pnl_m.cumsum()
    cumulative_m.insert(0, 'Date', daily_idx)
    cumulative_m['Total'] = gross_daily.cumsum()
    cumulative_m['Total (net)'] = (gross_daily - tx_cost_m.values).cumsum()

    df_history = pd.DataFrame(history_data)
    df_pnl = cumulative_m.reset_index(drop=True)

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
        portfolio_values = initial_capital + df_pnl['Total']
        net_portfolio_values = initial_capital + df_pnl['Total (net)']
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
        annualized_return = perf.get('Ann. Return', 0.0)
        sharpe_ratio = perf.get('Sharpe', 0.0) or 0.0
        max_drawdown = perf.get('Max Drawdown', 0.0)
        sharpe_net = perf_net.get('Sharpe', 0.0) or 0.0

        metrics = {
            'annualized_return': annualized_return,
            'sharpe_ratio': sharpe_ratio,
            'sharpe_net': sharpe_net,
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
                for d, v in zip(df_pnl['Date'], df_pnl['Total'])
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
