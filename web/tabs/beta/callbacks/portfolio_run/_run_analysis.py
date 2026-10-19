# -*- coding: utf-8 -*-
"""Run Analysis (Portfolio Tab → Results) — the main optimisation
orchestration. Split out of the ~390-line run_analysis callback body in
portfolio_run.py: build_risk_budgets / run_optimization / apply_factor_scaling
/ build_portfolio_table / build_rp_budgets_out / build_allocation_results are
pure(ish) helpers; register.py wires the @app.callback and assembles the
Dash outputs from them."""

from __future__ import annotations

import pathlib
import warnings as _warnings
from datetime import datetime

import numpy as np
import pandas as pd
from dash import html, dash_table
from dash.dash_table.Format import Format, Scheme

from multiasset.data import get_asset_type
from multiasset.layout import prepare_portfolio_table
from multiasset.main import run_risk_parity_allocation
from multiasset.budget import derive_vol_sqrt_budgets
from multiasset.config import RiskModelConfig

from ...data import THEME, ALLOCATION_RESULTS, SELECTED_FACTOR_POOL, FACTOR_TO_ASSET_MAP
from .._common import _BETA_BOOK_POSITIONS_PARQUET
from ._prepare_tables import merge_with_existing_positions

_IR_PREFIXES = ('IRDL', 'IRSL', 'IRCV')


def build_risk_budgets(allocation_mode, budget_ids, budget_values):
    """Build the `risk_budgets` dict passed to run_risk_parity_allocation,
    and the initial `rp_budgets_out` snapshot (only populated up-front for
    user_defined; risk_parity/factor_scaling fill it in after the run)."""
    risk_budgets = None
    rp_budgets_out = {}

    if allocation_mode == 'risk_parity':
        # Pure Risk Parity: optimizer runs unconstrained ERC — always deterministic.
        # rp_budgets_out will be filled from optimizer factor vols after the run.
        pass
    elif allocation_mode == 'factor_scaling':
        # Factor Model Scaling: same as backtest.
        # Step 1 — run the same min-vol + DV01 optimizer as risk_parity (risk_budgets=None).
        # Step 2 — tilt asset weights by their factor signal, renorm, apply class caps.
        # This matches the backtest path in backtest_hist.py exactly.
        pass  # optimizer runs RP/min-vol; signals applied post-hoc below
    else:  # user_defined
        # User Defined: use input-box values exactly; write them back unchanged.
        if budget_ids and budget_values:
            risk_budgets = {}
            for val, id_dict in zip(budget_values, budget_ids):
                factor_name = id_dict['index']
                try:
                    risk_budgets[factor_name] = float(val) if val is not None else 1.0
                except (ValueError, TypeError):
                    pass
        rp_budgets_out = dict(risk_budgets) if risk_budgets else {}

    return risk_budgets, rp_budgets_out


def run_optimization(total_capital_cny, selected_asset_names, risk_budgets):
    """Run run_risk_parity_allocation, capturing convergence warnings to
    surface in the UI. Returns (summary, returns, vols, factor_exp,
    factor_risk, portfolio, opt_warnings)."""
    with _warnings.catch_warnings(record=True) as _caught:
        _warnings.simplefilter("always", RuntimeWarning)
        summary, returns, vols, factor_exp, factor_risk, portfolio = run_risk_parity_allocation(
            total_capital=total_capital_cny, use_cache=True, selected_assets=selected_asset_names,
            risk_budgets=risk_budgets, use_deterministic=True
        )
        opt_warnings = [str(w.message) for w in _caught if issubclass(w.category, RuntimeWarning)]
    return summary, returns, vols, factor_exp, factor_risk, portfolio, opt_warnings


def apply_factor_scaling(summary, signal_snapshot, factor_names_in_pool, total_capital_cny):
    """Signed-sleeve signal tilt + class caps (matches the historical
    backtest's factor_scaling construction — see
    multiasset.book.sizing.signed_sleeve_weights_daily / _snapshot). Mutates
    and returns *summary* in place for the factor_scaling allocation mode.

    A factor whose mimicking portfolio can be replicated (IR Level/Slope/
    Curvature, FX, commodity — see factor_mimicking_weights) has ITS
    assets' weights REPLACED by the signed sleeve construction (each
    factor's own long/short mimicking portfolio x its position, summed
    across factors, short-end floored — same formula and same
    RiskModelConfig.SHORT_END_LONG_ONLY_TENORS floor as the backtest).
    Assets untouched by any replicable factor in the pool (e.g. credit/
    spread) keep their pure-RP weight, exactly as before this rewrite.
    """
    from multiasset.book.sizing import (
        factor_mimicking_weights, pool_sleeve_budgets, signed_sleeve_weights_snapshot,
    )
    from web.tabs.beta.data import compute_factor_vol_map, compute_factor_cov

    _snap_by_rf = ({rec['risk_factor']: rec for rec in signal_snapshot
                    if rec.get('risk_factor')} if signal_snapshot else {})

    # Un-flip IRSL's stored scalar back to its true FactorModel position —
    # build_snapshot_records (backtest_rfbt/_train_predict.py) negates IRSL's
    # position for display ("steepener on the positive side"); the sleeve
    # math needs the TRUE position, matching factor_mimicking_weights' own
    # sign convention (the same one the backtest's daily position series
    # uses, unflipped).
    position_by_factor = {}
    for f in factor_names_in_pool:
        rec = _snap_by_rf.get(f)
        if rec is None:
            continue
        raw = float(rec.get('scalar', 0.0))
        position_by_factor[f] = -raw if f.startswith('IRSL.') else raw

    replicable_factors = [f for f in factor_names_in_pool
                          if factor_mimicking_weights(f, FACTOR_TO_ASSET_MAP) is not None
                          and f in position_by_factor]

    # Assets touched by at least one replicable factor — these get their
    # weight REPLACED by the sleeve below; every other asset keeps its pure
    # RP weight untouched (mirrors the old per-asset "no signal -> coeff=1.0"
    # behaviour, but as a set membership test rather than a neutral coeff,
    # since sleeve weights aren't RP-weight-relative).
    _replicable_assets: set = set()
    for f in replicable_factors:
        w, _ = factor_mimicking_weights(f, FACTOR_TO_ASSET_MAP)
        _replicable_assets.update(w.keys())

    _CLASS_CAPS = RiskModelConfig.CLASS_CAPS
    _scaled = {row['Asset']: float(row['Weight (%)']) / 100.0 for _, row in summary.iterrows()}

    if replicable_factors and total_capital_cny > 0:
        vol_map = compute_factor_vol_map(replicable_factors)
        # Same rule as the backtest (RiskModelConfig.SLEEVE_BUDGET_RULE); cov enables 'erc'.
        budget = pool_sleeve_budgets(replicable_factors, vol_map,
                                     cov=compute_factor_cov(replicable_factors))  # fractions summing to 1
        # market_data is only needed for yield (IR) sleeve legs' /modD
        # duration lookup; load it lazily so a pure-FX/commodity pool never
        # pays load_raw_market_data()'s cost.
        needs_market_data = any(f.split('.')[0] in ('IRDL', 'IRSL', 'IRCV') for f in replicable_factors)
        market_data = None
        if needs_market_data:
            from multiasset.data import load_raw_market_data
            market_data = load_raw_market_data()
        sleeve_weights, _skipped = signed_sleeve_weights_snapshot(
            budget, position_by_factor, FACTOR_TO_ASSET_MAP, market_data,
            long_only_assets=RiskModelConfig.SHORT_END_LONG_ONLY_TENORS,
        )
        for name in _replicable_assets:
            if name in _scaled:
                _scaled[name] = sleeve_weights.get(name, 0.0)

    _total_scaled = sum(abs(v) for v in _scaled.values())
    if _total_scaled > 1e-9:
        _weights = {k: v / _total_scaled for k, v in _scaled.items()}
        for _ in range(3):
            # Per-asset class caps (RiskModelConfig.CLASS_CAPS) apply ONLY to assets that kept their
            # plain risk-parity weight. Sleeve-replicated assets are sized exactly like the backtest
            # (no class cap; the book is limited by the 95% long ceiling, the 95% short ceiling and
            # the gross DV01 cap), otherwise e.g. CN1Y (tiny duration, big weight) was clipped to
            # 40% of the shape and the live book held 44% long where the backtest holds 83%.
            _capped = {
                k: (v if k in _replicable_assets
                    else max(0, min(v, _CLASS_CAPS.get(get_asset_type(k), RiskModelConfig.CLASS_CAP_DEFAULT))))
                for k, v in _weights.items()
            }
            _cap_tot = sum(abs(v) for v in _capped.values())
            if _cap_tot > 1e-9:
                _weights = {k: v / _cap_tot for k, v in _capped.items()}
        # Write scaled weights back into summary
        summary['Weight (%)'] = summary['Asset'].map(lambda a: _weights.get(a, 0.0) * 100.0)
        summary['Allocation (CNY)'] = summary['Weight (%)'] / 100.0 * total_capital_cny
        scaled_count = len(_replicable_assets & set(summary['Asset']))
        print(f"📡 Factor model scaling (signed sleeves) applied to {scaled_count} assets")
    else:
        print("📡 All signals zero — keeping pure RP weights")

    return summary


def live_mod_durations(asset_names, asset_types, default_durations, market_data=None):
    """Modified duration per asset on the SAME basis the backtest prices and sizes with: the
    annuity formula at the asset's latest yield (``multiasset.data.calculate_daily_returns_series``).

    The shared table uses ``get_default_sensitivities`` durations (CN 30Y = 17.0, 20Y = 13.0), which
    at today's yields understate the true duration by ~20% (annuity: 21.8 / 15.9) and overstate US
    bonds by ~20%, so DV01 sizing and the DV01 cap in the tab disagreed with the backtest.
    Only 'Rates' and 'Credit' assets with a yield series are overridden; everything else keeps
    its default (FX/commodity 0, swap spreads untouched)."""
    from multiasset.book.hedge_instruments import mod_duration
    from multiasset.data import get_asset_yield_series, load_raw_market_data
    out = [float(d) for d in default_durations]
    for i, (name, typ) in enumerate(zip(asset_names, asset_types)):
        if typ not in ('Rates', 'Credit'):
            continue
        try:
            if market_data is None:
                market_data = load_raw_market_data()
            series, n, _country, is_bond = get_asset_yield_series(name, market_data)
            if series is None or not is_bond or not n:
                continue
            y = float(pd.Series(series, dtype=float).dropna().iloc[-1])
            if y > 0:
                out[i] = float(mod_duration(y, float(n)))
        except Exception:
            continue
    return np.asarray(out, dtype=float)


def long_short_totals(capital, durations):
    """(long CNY, short CNY, long DV01 MM, short DV01 MM) of signed positions - never netted.
    DV01 in MM CNY per bp (capital x duration / 1e10); shorts are returned as positive sizes."""
    cap = np.asarray(capital, dtype=float)
    dv01 = cap * np.asarray(durations, dtype=float) / 1e10
    return (float(np.clip(cap, 0.0, None).sum()), float(np.abs(np.clip(cap, None, 0.0)).sum()),
            float(np.clip(dv01, 0.0, None).sum()), float(np.abs(np.clip(dv01, None, 0.0)).sum()))


def build_portfolio_table(summary, factor_exp, portfolio, total_capital_cny, max_duration,
                          allocation_mode='risk_parity'):
    """Build the display-ready portfolio table (sized, rounded, DV01-capped) plus
    the raw arrays needed for the totals row and DV01 display.

    Long and short are handled SEPARATELY and never netted (user, 2026-10-17):
    * Capital usage is the LONG size only; shorts consume no capital. The 95% ceiling
      applies to the long book and, independently, to the short book
      (RiskModelConfig.CAPITAL_UTILISATION_MAX x SHORT_SIZE_MAX_RATIO).
    * DV01 is GROSS (|long| + |short|), the same convention as the backtest; long, short and
      gross DV01 are reported.
    * factor_scaling is sized like the backtest (`scale_sleeve_to_dv01_target`): the signed
      shape is scaled to the DV01 target, subject to the two ceilings (up or down). The other
      modes keep their weights and are only scaled DOWN to the DV01 limit.
    * Lot rounding is toward zero, so a short is never rounded to a bigger short.
    * The TOTAL row carries the LONG size (what consumes capital), not a net sum.

    Returns a dict with: portfolio_df, portfolio_table_df, positions_table
    (dash_table.DataTable), total_dv01 (gross), dv01_cap_msg, plus long_cny, short_cny,
    dv01_long, dv01_short and final_capital ({asset: signed rounded CNY}).
    """
    portfolio_df = prepare_portfolio_table(summary, factor_exp, portfolio)
    portfolio_df = merge_with_existing_positions(portfolio_df)
    if not portfolio_df.empty:
        # Same duration basis as the backtest (annuity at the latest yield), not the default table.
        portfolio_df['Duration'] = live_mod_durations(
            portfolio_df['Asset Name'], portfolio_df['Asset Type'], portfolio_df['Duration'])
        portfolio_df['DV01 (MM CNY)'] = (portfolio_df['Capital (CNY)'] * portfolio_df['Duration'] / 1e10).round(4)

    portfolio_enhanced = []
    total_rounded_capital = 0.0
    long_cny = short_cny = dv01_long = dv01_short = 0.0
    final_capital = {}
    dv01_cap_msg = ""
    total_dv01 = 0.0           # safe default — overwritten below when table is non-empty
    _durations = np.array([])  # safe default
    _rounded   = np.array([])

    if not portfolio_df.empty:
        _units = np.where(
            portfolio_df['Asset Type'].isin(('Rates', 'Spread', 'Credit')),
            10_000_000.0,
            1_000_000.0,
        )
        _durations = portfolio_df['Duration'].values
        _raw_cap = portfolio_df['Capital (CNY)'].values.astype(float)
        _size_msg = ""
        if allocation_mode == 'factor_scaling' and total_capital_cny > 0:
            # Same sizing as the backtest: shape -> DV01 target, long and short ceilings.
            from multiasset.book.sizing import scale_sleeve_to_dv01_target
            _names = list(portfolio_df['Asset Name'])
            _w = pd.DataFrame([_raw_cap / total_capital_cny], columns=_names)
            _d = pd.DataFrame([_durations], columns=_names)
            _sized = scale_sleeve_to_dv01_target(
                _w, _d, total_capital_cny, float(max_duration or 5),
                RiskModelConfig.CAPITAL_UTILISATION_MAX,
            ).iloc[0]
            _raw_cap = _sized.to_numpy() * total_capital_cny
        # toward-zero lot rounding: a short must not round into a bigger short
        _rounded = np.trunc(_raw_cap / _units) * _units

        # ── DV01 cap: GROSS DV01 (|long| + |short|, never netted) must stay within the limit;
        # scale down if it does not. Only duration-bearing assets (bonds/spreads) carry DV01, so
        # the scale-down applies to THOSE assets only; zero-duration assets (commodities, FX)
        # keep their allocation.
        _raw_dv01_mm = float(np.abs(_rounded * _durations).sum() / 1e10)
        _max_dur = float(max_duration or 5)
        _max_dv01_mm = total_capital_cny * _max_dur / 1e10
        if _raw_dv01_mm > _max_dv01_mm and _raw_dv01_mm > 0:
            _scale = _max_dv01_mm / _raw_dv01_mm
            _dv01_bearing = _durations > 0
            _rounded = np.where(
                _dv01_bearing,
                np.trunc(_rounded * _scale / _units) * _units,
                _rounded,
            )
            dv01_cap_msg = (f"  ·  DV01 capped: {_raw_dv01_mm:.2f}→{_max_dv01_mm:.2f} MM "
                            f"(scale {_scale:.2%})")

        # Long and short separately - never netted. Capital used = LONG size; the TOTAL row below
        # shows it (a net sum would understate the capital the longs need).
        long_cny, short_cny, dv01_long, dv01_short = long_short_totals(_rounded, _durations)
        total_rounded_capital = long_cny
        _display_df = portfolio_df.copy()
        # Display only: 2 decimals. Sizing and DV01 above/below keep the full-precision durations.
        _display_df['Duration'] = np.round(_durations, 2)
        _display_df['Capital (CNY)'] = [f"{v / 1_000_000:,.2f}" for v in _rounded]
        # Weight = FINAL (sized, rounded) capital as % of total capital, signed per asset.
        _display_df['Weight (%)'] = [f"{v / total_capital_cny * 100.0:.2f}%" if total_capital_cny > 0 else "0.00%"
                                     for v in _rounded]
        # Recompute DV01 on (possibly capped) rounded capital
        _display_df['DV01 (MM CNY)'] = [
            round(v * d / 1e10, 4)
            for v, d in zip(_rounded, _durations)
        ]
        portfolio_enhanced = _display_df.to_dict('records')

    portfolio_table_df = pd.DataFrame(portfolio_enhanced)

    # Add totals row
    if not portfolio_table_df.empty:
        total_dv01 = round(dv01_long + dv01_short, 4)          # GROSS DV01, not a net sum
        final_capital = dict(zip(portfolio_df['Asset Name'], map(float, _rounded)))
        totals = {
            'Asset Type': 'TOTAL', 'Universe': '', 'Sector': '', 'Asset Name': '',
            'Instrument': 'LONG size · shorts excluded · not netted',
            'Duration': None,   # None → NaN, avoids mixed-type parquet issue
            'Capital (CNY)': f"{long_cny / 1_000_000:,.2f}",
            'DV01 (MM CNY)': total_dv01,
            'Weight (%)': f"{(long_cny / total_capital_cny * 100.0) if total_capital_cny > 0 else 0.0:.2f}%"
        }
        portfolio_table_df = pd.concat([portfolio_table_df, pd.DataFrame([totals])], ignore_index=True)

    # Save positions parquet for reference (coerce object columns so pyarrow doesn't choke)
    # The Beta Book Summary parquet is written once below via _upsert_snapshot.
    try:
        _save_df = portfolio_table_df.copy()
        for _c in _save_df.columns:
            if _save_df[_c].dtype == object:
                _save_df[_c] = _save_df[_c].fillna('').astype(str)
        pathlib.Path(_BETA_BOOK_POSITIONS_PARQUET).parent.mkdir(parents=True, exist_ok=True)
        _save_df.to_parquet(_BETA_BOOK_POSITIONS_PARQUET, index=False)
        print(f"✓ beta_book_positions.parquet saved ({len(_save_df)} rows) → {_BETA_BOOK_POSITIONS_PARQUET}")
    except Exception as _se:
        print(f"Warning: Could not save Beta book positions: {_se}")

    # Display-only copy: the saved parquet (read by the Risk tab) is left untouched.
    _display_rows = []
    for _r in portfolio_table_df.to_dict('records'):
        _is_total = _r.get('Asset Type') == 'TOTAL'
        try:
            _cap = float(str(_r.get('Capital (CNY)', '0')).replace(',', ''))
        except ValueError:
            _cap = 0.0
        _r['Side'] = '' if _is_total else ('SHORT' if _cap < 0 else ('LONG' if _cap > 0 else ''))
        _display_rows.append(_r)
    if short_cny > 0:
        _display_rows.append({
            'Asset Type': 'TOTAL', 'Universe': '', 'Sector': '', 'Asset Name': '',
            'Instrument': 'SHORT size · not netted', 'Side': 'SHORT', 'Duration': None,
            'Capital (CNY)': f"-{short_cny / 1_000_000:,.2f}",
            'DV01 (MM CNY)': round(-dv01_short, 4),
            'Weight (%)': f"-{(short_cny / total_capital_cny * 100.0) if total_capital_cny > 0 else 0.0:.2f}%",
        })

    positions_table = dash_table.DataTable(
        data=_display_rows,
        columns=[
            {'name': 'Asset Type',           'id': 'Asset Type'},
            {'name': 'Universe',              'id': 'Universe'},
            {'name': 'Sector',                'id': 'Sector'},
            {'name': 'Asset Name',            'id': 'Asset Name'},
            {'name': 'Instrument',            'id': 'Instrument'},
            {'name': 'Side',                  'id': 'Side'},
            {'name': 'Duration',              'id': 'Duration', 'type': 'numeric',
             'format': Format(precision=2, scheme=Scheme.fixed)},
            {'name': 'Capital (Million CNY)', 'id': 'Capital (CNY)'},
            {'name': 'DV01 (MM CNY)',         'id': 'DV01 (MM CNY)'},
            {'name': 'Weight',                'id': 'Weight (%)'},
        ],
        style_cell={
            'textAlign': 'right',
            'padding': '5px 10px',
            'fontFamily': 'inherit',
            'fontSize': '11px',
            'backgroundColor': '#122a4c',
            'color': '#e9eef8',
            'border': 'none',
        },
        style_cell_conditional=[
            {'if': {'column_id': c}, 'textAlign': 'left'}
            for c in ('Asset Type', 'Universe', 'Sector', 'Asset Name', 'Instrument', 'Side')
        ],
        style_header={
            'backgroundColor': '#0e1d3a',
            'color': '#a4b6d2',
            'fontWeight': '600',
            'fontSize': '9px',
            'textTransform': 'uppercase',
            'letterSpacing': '0.05em',
            'textAlign': 'right',
            'border': 'none',
        },
        style_header_conditional=[
            {'if': {'column_id': c}, 'textAlign': 'left'}
            for c in ('Asset Type', 'Universe', 'Sector', 'Asset Name', 'Instrument', 'Side')
        ],
        style_data_conditional=[
            {'if': {'filter_query': '{Asset Type} = "TOTAL"'},
             'backgroundColor': 'rgba(255,255,255,0.03)', 'color': '#e9eef8', 'fontWeight': '700'},
            {'if': {'row_index': 'odd'}, 'backgroundColor': 'rgba(255,255,255,0.015)'},
            {'if': {'filter_query': '{Side} = "SHORT"'}, 'color': '#ff6b6b'},
            {'if': {'filter_query': '{Side} = "SHORT"', 'column_id': 'Side'}, 'fontWeight': '700'},
        ],
        style_table={'overflowX': 'auto'}
    )

    return {
        'portfolio_df': portfolio_df,
        'portfolio_table_df': portfolio_table_df,
        'positions_table': positions_table,
        'total_dv01': total_dv01,
        'dv01_cap_msg': dv01_cap_msg,
        'long_cny': long_cny, 'short_cny': short_cny,
        'dv01_long': dv01_long, 'dv01_short': dv01_short,
        'final_capital': final_capital,
    }


def _fallback_rp_budgets(factor_names_list, vol_series, cap_m):
    """Derive RP Max from per-factor vol when the optimizer's own risk
    contributions aren't usable (empty/zero total).

    IR factors (IRDL/IRSL/IRCV): √vol-proportional within their capital envelope.
    Non-IR factors (CMDL/FXDL/SPDL): equal share within their envelope.
    """
    _ir = [f for f in factor_names_list if f.split('.')[0] in _IR_PREFIXES]
    _non = [f for f in factor_names_list if f.split('.')[0] not in _IR_PREFIXES]
    n_all = len(factor_names_list) or 1
    ir_cap = cap_m * len(_ir) / n_all
    non_cap = cap_m * len(_non) / n_all
    _vol_m = {f: float(vol_series[f]) for f in factor_names_list
              if f in vol_series and pd.notna(vol_series.get(f)) and float(vol_series[f]) > 0}
    ir_allocs, _ = derive_vol_sqrt_budgets(_ir, _vol_m, total_capital_m=ir_cap)
    non_eq = round(non_cap / len(_non), 2) if _non else 0.0
    return {**ir_allocs, **{f: non_eq for f in _non}}


def build_rp_budgets_out(allocation_mode, rp_budgets_out, factor_risk, vols, total_capital_m):
    """Derive RP Max per factor from actual factor risk contributions
    (pure Risk Parity) or vol-based fallback (Factor Scaling / when the
    optimizer's risk contributions aren't usable)."""
    if allocation_mode == 'risk_parity':
        if (not factor_risk.empty
                and 'Risk Factor' in factor_risk.columns
                and 'Risk Contribution (%)' in factor_risk.columns):
            _valid_rc = factor_risk[pd.notna(factor_risk['Risk Contribution (%)'])]
            rc_map = dict(zip(_valid_rc['Risk Factor'], _valid_rc['Risk Contribution (%)']))
            total_rc = sum(v for v in rc_map.values() if v > 0)
            if total_rc > 1e-6:
                rp_budgets_out = {
                    f: round(total_capital_m * v / total_rc, 2)
                    for f, v in rc_map.items() if v > 0
                }
            else:
                _fnames_erc = list(vols.index) if hasattr(vols, 'index') else []
                rp_budgets_out = _fallback_rp_budgets(_fnames_erc, vols, total_capital_m)
        else:
            _fnames_erc = list(vols.index) if hasattr(vols, 'index') else []
            rp_budgets_out = _fallback_rp_budgets(_fnames_erc, vols, total_capital_m)
    # factor_scaling: derive rp_budgets_out from post-scaled asset weights
    if allocation_mode == 'factor_scaling' and not rp_budgets_out:
        _fnames_erc = list(vols.index) if hasattr(vols, 'index') else []
        rp_budgets_out = _fallback_rp_budgets(_fnames_erc, vols, total_capital_m)
    # user_defined already has rp_budgets_out set above
    return rp_budgets_out


def build_allocation_results(summary, factor_exp, factor_risk, portfolio,
                              portfolio_df, portfolio_table_df,
                              allocation_mode, total_capital_cny, max_duration,
                              run_timestamp):
    """Build the Beta snapshot + allocation-results-store payload.

    Metadata fields: every saved row carries the full run configuration so
    the Summary tab is reproducible and auditable. Snapshot the *final*
    Portfolio Allocation Results — i.e. the rounded, DV01-capped target
    volumes actually shown in the Run Analysis table (portfolio_table_df) —
    not the pre-rounding portfolio_df, so "Add to Portfolio" reflects what
    the user sees.
    """
    _factor_pool_all = (
        SELECTED_FACTOR_POOL.get('ir_factors', [])
        + SELECTED_FACTOR_POOL.get('sp_factors', [])
        + SELECTED_FACTOR_POOL.get('fx_factors', [])
        + SELECTED_FACTOR_POOL.get('eq_factors', [])
        + SELECTED_FACTOR_POOL.get('cmd_factors', [])
    )
    _run_meta = {
        '_timestamp':       run_timestamp.isoformat(),
        '_run_mode':        allocation_mode,
        '_capital_cny':     float(total_capital_cny),
        '_model_month_key': run_timestamp.strftime('%Y-%m'),
        '_factor_pool':     ','.join(sorted(_factor_pool_all)),
        '_max_duration':    float(max_duration or 5),
    }
    _snap_source = portfolio_table_df if not portfolio_table_df.empty else portfolio_df
    _snap_source = _snap_source[_snap_source.get('Asset Type', pd.Series(dtype=object)) != 'TOTAL'] \
        if 'Asset Type' in _snap_source.columns else _snap_source
    _keep_cols = [c for c in [
        'Asset Type', 'Universe', 'Sector', 'Asset Name', 'Instrument',
        'Duration', 'Capital (CNY)', 'DV01 (MM CNY)', 'Weight (%)',
    ] if c in _snap_source.columns]
    _snap = _snap_source[_keep_cols].copy()
    # portfolio_table_df's 'Capital (CNY)' is a display string already
    # in MM CNY (see build_portfolio_table's _display_df above) — convert
    # back to raw CNY so downstream readers (which expect raw CNY / 1e6)
    # stay correct.
    if _snap_source is portfolio_table_df and 'Capital (CNY)' in _snap.columns:
        _snap['Capital (CNY)'] = pd.to_numeric(
            _snap['Capital (CNY)'].astype(str).str.replace(',', ''), errors='coerce',
        ) * 1_000_000.0
    # portfolio_table_df's 'Weight (%)' is likewise a display string
    # ("12.34%") — strip the '%' before the blind pd.to_numeric below, or
    # it silently coerces to NaN (see _upsert_snapshot's numeric-cols pass).
    if _snap_source is portfolio_table_df and 'Weight (%)' in _snap.columns:
        _snap['Weight (%)'] = _snap['Weight (%)'].astype(str).str.replace('%', '')
    for _mk, _mv in _run_meta.items():
        _snap[_mk] = _mv
    for _c in ('Duration', 'Capital (CNY)', 'DV01 (MM CNY)', 'Weight (%)'):
        if _c in _snap.columns:
            _snap[_c] = pd.to_numeric(_snap[_c], errors='coerce')

    _store_factor_risk = (
        factor_risk.to_dict('records')
        if isinstance(factor_risk, pd.DataFrame) and not factor_risk.empty
        else []
    )
    return {
        'summary': summary.to_dict() if isinstance(summary, pd.DataFrame) else {},
        'factor_exposures': factor_exp.to_dict() if isinstance(factor_exp, pd.DataFrame) else {},
        'factor_risk': _store_factor_risk,
        'portfolio': portfolio.to_dict() if isinstance(portfolio, pd.DataFrame) else {},
        'beta_snapshot_display': portfolio_table_df.to_dict('records'),
        'beta_snapshot': _snap.to_dict('records'),
        'beta_snapshot_timestamp': run_timestamp.isoformat(),
        'timestamp': datetime.now().isoformat(),
    }, _store_factor_risk
