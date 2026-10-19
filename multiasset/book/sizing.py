# -*- coding: utf-8 -*-
"""Daily per-factor coefficient -> per-asset daily weights, driven by the
monthly Stage2Context (see multiasset.factor_optimizer.Stage2Context) and
the daily FactorModel signal.

See docs/plans/beta_book_exposure_vs_capital.md Step 4. Two problems this
module fixes relative to the previous factor_scaling implementation:

1. The daily FactorModel `position` series was only ever sampled at the
   MONTHLY rebalance_date (backtest_hist's old Step B), so the signal was
   effectively frozen for a month at a time.
2. Weights were always renormalised to sum(abs(w)) == 1 (backtest_hist's
   old Step C), so the book was always 100% invested regardless of how
   bearish the signal was — a bearish signal could only rotate the book,
   never de-risk it.

This module fixes (1) by resampling scalar_to_coeff daily. Fixing (2) is
capital.py's job (Step 7) — this module produces per-asset WEIGHTS (which
may sum to something other than 1), not notional; weights_to_notional then
decides how much of that sum is actually capital-deployed.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from multiasset.backtest_cache import scalar_to_coeff
from multiasset.factor_optimizer import FactorRiskParityOptimizer, Stage2Context


def scaled_factor_budgets_daily(
    reference_budget: Dict[str, float],
    signal_asof: Callable[[str, pd.Timestamp], Optional[float]],
    daily_index: pd.DatetimeIndex,
    screened_factors: Sequence[str],
) -> pd.DataFrame:
    """Per-factor daily scaled budget.

        scaled[d, f] = reference_budget[f] * scalar_to_coeff(signal_asof(f, d), f)

    Per decision #3 in the plan: EACH factor gets its own daily coefficient
    from its OWN signal, computed independently, before Stage 2 pools
    IRDL/IRSL/IRCV per country into a group budget (that pooling happens
    inside ``rebuild_asset_weights``, not here) — this preserves each
    factor's own signal exactly as Stage 1 intended, rather than blending
    three signals into one before scaling.

    A factor not in ``screened_factors`` (i.e. it wasn't selected by the
    correlation screen for this book) or with no signal available on a
    given day keeps its unscaled ``reference_budget`` value on that day —
    matching the original per-date gating in the old Step B (a factor the
    correlation screen didn't pick for this rebalance month never gets a
    tilt applied).

    Deliberately NOT renormalised: the row sum is the book's gross risk
    appetite for that day (can be more or less than the reference budget's
    sum of 1.0, since scalar_to_coeff ranges [0, 2] for long-only factors
    and [-1.5, 1.5] for directional ones) — capital.weights_to_notional()
    (Step 7) is what turns that gross appetite into a capital-constrained
    notional, not this function.

    Returns a DataFrame(index=daily_index, columns=sorted(reference_budget)).
    """
    screened = set(screened_factors)
    factors = sorted(reference_budget.keys())
    rows: Dict[pd.Timestamp, Dict[str, float]] = {}
    for d in daily_index:
        row = {}
        for f in factors:
            ref = reference_budget[f]
            if f not in screened:
                row[f] = ref
                continue
            sig = signal_asof(f, d)
            if sig is None:
                row[f] = ref
                continue
            row[f] = ref * scalar_to_coeff(sig, f)
        rows[d] = row
    return pd.DataFrame(rows).T.reindex(columns=factors)


def daily_weights_from_context(
    ctx_by_rebalance_date: Dict[pd.Timestamp, Optional[Stage2Context]],
    budgets_by_rebalance_date: Dict[pd.Timestamp, pd.DataFrame],
    daily_index: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Per-asset daily WEIGHTS (not yet capital-constrained notional), one
    row per date in ``daily_index``, rebuilt from each rebalance month's
    Stage2Context using that day's per-factor scaled budget.

    For each day, uses the Stage2Context from the most recent rebalance
    date on/before it (the monthly-fixed "base"), combined with
    ``budgets_by_rebalance_date[that_rebalance_date]``'s row for that day
    (the daily-varying per-factor scale). This is the two-cadence split
    from decision #2: Stage 1 (which Stage2Context encodes) stays monthly;
    Stage 2's redistribution (``FactorRiskParityOptimizer.rebuild_asset_weights``
    — a staticmethod: cheap, no SLSQP, no live optimizer/Portfolio instance
    needed at all, since ``ctx.asset_class_of`` carries everything the
    asset-class bound lookup needs) runs once per day. This is exactly why
    ``rebuild_asset_weights`` is a staticmethod rather than an instance
    method — it lets this function work equally well against a
    freshly-computed context or one deserialised from the RP cache with no
    optimizer instance in sight.

    A day whose rebalance-month has no context (fit_and_calculate took the
    non-two-stage path that month, or the month was skipped entirely — see
    the "insufficient data" / "no mappable assets" continues in the
    orchestrator's Step A loop) produces no row for that day — callers
    treat a missing day the same as the old code's "skip this rebalance
    date" behaviour (the daily allocation matrix's forward-fill/reindex
    step handles gaps the same way the old monthly one did).

    Returns a DataFrame(index=<subset of daily_index with a valid
    rebalance base>, columns=ctx.asset_names for whichever ctx applied).
    """
    rebalance_dates = sorted(ctx_by_rebalance_date.keys())
    rows: Dict[pd.Timestamp, pd.Series] = {}

    rb_idx = 0
    current_rb = None
    for d in daily_index:
        while rb_idx < len(rebalance_dates) and rebalance_dates[rb_idx] <= d:
            current_rb = rebalance_dates[rb_idx]
            rb_idx += 1
        if current_rb is None:
            continue

        ctx = ctx_by_rebalance_date.get(current_rb)
        budgets_df = budgets_by_rebalance_date.get(current_rb)
        if ctx is None or budgets_df is None or d not in budgets_df.index:
            continue

        factor_budget = budgets_df.loc[d].to_dict()
        rows[d] = FactorRiskParityOptimizer.rebuild_asset_weights(ctx, factor_budget)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).T


# ── Signed factor sleeves (factor_scaling mode) ───────────────────────────
#
# The Individual Factors backtest trades each factor's own mimicking
# portfolio: P&L_f = position_f[t-1] * r_f[t], with r_f = -Δ(Σ w_i y_i)/100
# for yield factors (deterministic Level/Slope/Curvature weights) and the
# price pct-change for FX/commodity/equity factors. Holding notional
# N_i = K * w_i / modD_i on each tenor reproduces K * r_f exactly under the
# book's own bond pricing (capital = -modD * Δy/100, multiasset.data), so a
# book built as Σ_f budget_f * position_f * sleeve_f earns the combination
# of the standalone strategies by construction. The old long-only
# construction could not: it clipped short/flat level views and could only
# bend a long-only tenor mix for slope/curvature, never hold the long-short
# factor portfolio those strategies are scored on.

_IR_BASIS = {'IRDL': 'Level', 'IRSL': 'Slope', 'IRCV': 'Curvature'}
_CREDIT_BASIS = {'CRDL': 'Level', 'CRSL': 'Slope', 'CRCV': 'Curvature'}
_PRICE_PREFIXES = ('FXDL', 'CMDL', 'EQDL')


def factor_mimicking_weights(factor_code: str,
                             factor_to_asset_map: dict) -> Optional[tuple]:
    """(``{asset_name: w_i}``, is_yield) for ``factor_code``'s mimicking
    portfolio, or ``None`` when it can't be replicated with tradable assets
    (e.g. an IR/credit tenor with no mapped asset at all).

    IR weights come from pca_analyzer's deterministic grid — the same
    vectors that define the factor level in factor-rates.pkl. Tenor ->
    asset names come from the country's IRDL entry in factor_to_asset_map
    (IRDL lists every tenor; IRSL/IRCV list only their loading tenors).

    Credit (CRDL/CRSL/CRCV) weights come from the same log-tenor-space
    Level/Slope/Curvature decomposition (multiasset.config.get_credit_weights)
    that CRDL/CRSL/CRCV's own factor level is built from
    (multiasset.factor_backtest._credit_weighted_duration uses the same
    call) — the mimicking portfolio here holds each universe's own bond
    outright at that weight, unhedged against CGB (see
    multiasset.data.get_asset_yield_series's Credit branch), matching how
    the Individual Factors tab prices CRDL/CRSL/CRCV: -D_mod * d(spread)/100,
    which only requires the own-leg duration, not a CGB hedge leg.
    """
    from multiasset.pca_analyzer import get_deterministic_ir_tenors, get_deterministic_ir_weights

    prefix, _, suffix = factor_code.partition('.')
    if prefix in _IR_BASIS:
        tenors = get_deterministic_ir_tenors(suffix)
        weights = get_deterministic_ir_weights(suffix)[_IR_BASIS[prefix]]
        by_tenor = {a.get('sector'): a['name'] for a in factor_to_asset_map.get(f'IRDL.{suffix}', [])}
        out = {}
        for tenor, w in zip(tenors, weights):
            if abs(w) < 1e-12:
                continue
            if tenor not in by_tenor:
                return None
            out[by_tenor[tenor]] = float(w)
        return (out, True) if out else None
    if prefix in _CREDIT_BASIS:
        from multiasset.config import CREDIT_CONFIG, get_credit_weights, CREDIT_NO_CURVATURE

        if suffix not in CREDIT_CONFIG:
            return None
        basis = _CREDIT_BASIS[prefix]
        if basis == 'Curvature' and suffix in CREDIT_NO_CURVATURE:
            return None
        tenor_cols = CREDIT_CONFIG[suffix][2]
        tenor_years = [t for _, _, t in tenor_cols]
        include_curvature = suffix not in CREDIT_NO_CURVATURE
        weights_by_basis = get_credit_weights(tenor_years, include_curvature=include_curvature)
        weights = weights_by_basis.get(basis)
        if weights is None:
            return None
        by_tenor = {a.get('sector'): a['name']
                    for a in factor_to_asset_map.get(f'CRDL.{suffix}', [])}
        out = {}
        for t, w in zip(tenor_years, weights):
            if abs(w) < 1e-12:
                continue
            tenor_label = f"{t:g}Y" if t >= 1 else f"{int(t * 12)}M"
            if tenor_label not in by_tenor:
                return None
            out[by_tenor[tenor_label]] = float(w)
        return (out, True) if out else None
    if prefix in _PRICE_PREFIXES:
        names = [a['name'] for a in factor_to_asset_map.get(factor_code, [])]
        return ({n: 1.0 / len(names) for n in names}, False) if names else None
    return None


def _with_credit_floor(long_only_assets, assets) -> list:
    """``long_only_assets`` plus every credit asset (CDB/LGB/MTN/NCD) in ``assets`` when
    ``RiskModelConfig.CREDIT_LONG_ONLY`` - credit bonds cannot be shorted in practice."""
    from multiasset.config import RiskModelConfig
    from multiasset.data import get_asset_type
    out = list(long_only_assets or [])
    if RiskModelConfig.CREDIT_LONG_ONLY:
        out += [a for a in assets if a not in out and get_asset_type(a) == 'Credit']
    return out


def signed_sleeve_weights_daily(
    budget_by_rebalance_date: Dict[pd.Timestamp, Dict[str, float]],
    factor_signal_series: Dict[str, pd.Series],
    daily_index: pd.DatetimeIndex,
    factor_to_asset_map: dict,
    market_data,
    long_only_assets: Optional[Sequence[str]] = None,
) -> tuple:
    """Signed per-asset daily weights (fraction of capital) for the
    factor_scaling book, plus each bond's modified duration and the list of
    factors that couldn't be replicated (they contribute nothing).

        weight[d, i] = Σ_f budget_f(month of d) * position_f[d-1] * w_{f,i} / modD_i[d-1]

    ``/ modD_i`` applies to yield factors only. ``position`` is lagged one
    trading day, matching the standalone backtest's
    ``position.shift(1) * returns``. A factor with no saved signal holds no
    sleeve (flat), mirroring the Individual Factors tab, where there is no
    strategy for it either. Weights are deliberately signed — shorts are
    part of the strategy being replicated.

    ``long_only_assets``: asset names (e.g. short-end tenors like CN1Y/CN2Y/
    CN5Y) whose NET summed weight across all factors is floored at 0 —
    IRSL/IRCV's steepener/curvature trades short one end of the curve and go
    long the other, and days the short end nets negative pay away carry
    instead of collecting it. Floored here means: this asset is dropped
    from the trade on days its net weight would be negative, not shorted
    via another instrument (there is no IRS asset in this codebase yet —
    see docs/plans/beta_book_exposure_vs_capital.md for a hedge-instrument
    panel that would let the short leg be re-expressed via a 1-5Y swap
    instead of simply dropped). The other legs of the SAME trade (e.g.
    IRSL's long 10Y/30Y leg on a day CN2Y's floor bites) are untouched —
    only the floored asset's own weight changes, so the tilt is no longer
    exactly DV01-neutral across the trade on those days.

    Returns ``(weights, mod_dur, skipped)``. ``mod_dur`` (same index/columns
    as ``weights``, 0 for non-bond assets) is each bond's modified duration
    — the caller (orchestrator.py) uses it to size the whole day's notional
    to a DV01 budget, since these weights are DV01-EQUALISED PER FACTOR
    UNIT (Σ w_i/modD_i = 1 per factor), not sized to any capital or risk
    target: two factors with different average duration would otherwise
    deploy very different DV01 for the same budget share.
    """
    from multiasset.data import get_asset_yield_series

    if not budget_by_rebalance_date:
        return pd.DataFrame(), pd.DataFrame(), []

    rb_dates = sorted(budget_by_rebalance_date)
    factors = sorted({f for b in budget_by_rebalance_date.values() for f in b})
    budget = (pd.DataFrame([budget_by_rebalance_date[d] for d in rb_dates], index=pd.DatetimeIndex(rb_dates))
              .reindex(columns=factors).fillna(0.0))
    budget = budget.reindex(budget.index.union(daily_index)).ffill().reindex(daily_index)

    replicable, skipped = {}, []
    for f in factors:
        spec = factor_mimicking_weights(f, factor_to_asset_map)
        if spec is None or f not in factor_signal_series:
            skipped.append(f)
        else:
            replicable[f] = spec
    if not replicable:
        return pd.DataFrame(), pd.DataFrame(), skipped

    pos = pd.DataFrame({
        f: factor_signal_series[f].reindex(factor_signal_series[f].index.union(daily_index)).ffill().reindex(daily_index)
        for f in replicable
    }).shift(1).fillna(0.0)

    assets = sorted({a for w, _ in replicable.values() for a in w})
    inv_dur, mod_dur = {}, {}
    for a in assets:
        if not any(is_y and a in w for w, is_y in replicable.values()):
            continue
        series, n, _, is_bond = get_asset_yield_series(a, market_data)
        if series is None or not is_bond or not n:
            continue
        y = pd.Series(series, dtype=float) / 100.0
        y.index = pd.to_datetime(y.index)
        mod_d = (1 - (1 + y) ** (-n)) / (y * (1 + y))
        mod_d_lagged = mod_d.reindex(mod_d.index.union(daily_index)).ffill().reindex(daily_index).shift(1)
        mod_dur[a] = mod_d_lagged
        inv_dur[a] = 1.0 / mod_d_lagged

    weights = pd.DataFrame(0.0, index=daily_index, columns=assets)
    for f, (w, is_yield) in replicable.items():
        scale = budget[f] * pos[f]
        for a, w_i in w.items():
            if is_yield:
                if a not in inv_dur:
                    continue
                weights[a] += scale * w_i * inv_dur[a].fillna(0.0)
            else:
                weights[a] += scale * w_i
    long_only_assets = _with_credit_floor(long_only_assets, weights.columns)
    if long_only_assets:
        floor_cols = [a for a in long_only_assets if a in weights.columns]
        if floor_cols:
            weights[floor_cols] = weights[floor_cols].clip(lower=0.0)
    mod_dur_df = pd.DataFrame(mod_dur, index=daily_index).reindex(columns=assets).fillna(0.0)
    return weights, mod_dur_df, skipped


def signed_sleeve_weights_snapshot(
    budget: Dict[str, float],
    position_by_factor: Dict[str, float],
    factor_to_asset_map: dict,
    market_data,
    long_only_assets: Optional[Sequence[str]] = None,
) -> Tuple[Dict[str, float], list]:
    """One-shot (single point in time) version of ``signed_sleeve_weights_daily``
    for the live Portfolio tab's "Run Analysis" — no daily index, no lag: uses
    ``position_by_factor``'s value and each bond's CURRENT duration directly
    (there is no "yesterday" in a one-shot live view the way there is in a
    backtest's daily loop).

        weight[i] = Σ_f budget[f] * position[f] * w_{f,i} / modD_i

    Returns ``({asset_name: weight}, skipped)`` — weights are a FRACTION OF
    ``sum(budget.values())``'s capital envelope (same convention as
    ``rebuild_asset_weights``'s output), not yet DV01-sized or capital-class
    capped; the caller does that the same way it does for the non-factor-
    scaling weights. See ``signed_sleeve_weights_daily``'s docstring for
    ``long_only_assets``'s semantics — identical here, just for one date
    instead of a daily series.
    """
    from multiasset.data import get_asset_yield_series

    replicable, skipped = {}, []
    for f in budget:
        spec = factor_mimicking_weights(f, factor_to_asset_map)
        if spec is None or f not in position_by_factor:
            skipped.append(f)
        else:
            replicable[f] = spec

    weights: Dict[str, float] = {}
    if not replicable:
        return weights, skipped

    inv_dur: Dict[str, float] = {}
    cn_by_tenor: Dict[float, str] = {}                 # CN government-bond asset by tenor (years)
    for f, (w, is_yield) in replicable.items():
        if not is_yield:
            continue
        for a in w:
            if a in inv_dur:
                continue
            series, n, country, is_bond = get_asset_yield_series(a, market_data)
            if series is None or not is_bond or not n:
                continue
            y = float(pd.Series(series, dtype=float).dropna().iloc[-1]) / 100.0
            mod_d = (1 - (1 + y) ** (-n)) / (y * (1 + y)) if y > 0 else 0.0
            if mod_d > 0:
                inv_dur[a] = 1.0 / mod_d
                if country == 'CN':
                    cn_by_tenor[float(n)] = a

    for f, (w, is_yield) in replicable.items():
        scale = budget[f] * position_by_factor[f]
        for a, w_i in w.items():
            if is_yield:
                if a not in inv_dur:
                    continue
                weights[a] = weights.get(a, 0.0) + scale * w_i * inv_dur[a]
            else:
                weights[a] = weights.get(a, 0.0) + scale * w_i

    long_only_assets = _with_credit_floor(long_only_assets, weights)
    if long_only_assets:
        for a in long_only_assets:
            if a in weights and weights[a] < 0.0:
                weights[a] = 0.0

    # Illiquid CN tenors cannot be shorted (RiskModelConfig.CN_SHORT_SUBSTITUTE, 20Y -> 30Y):
    # the short moves to the target tenor DV01-equivalently (weight x modDur_from / modDur_to),
    # netting against any long already there - same rule as multiasset.book.overlay.substitute_shorts.
    from multiasset.config import RiskModelConfig
    for t_from, t_to in RiskModelConfig.CN_SHORT_SUBSTITUTE.items():
        a, b = cn_by_tenor.get(float(t_from)), cn_by_tenor.get(float(t_to))
        if a is None or b is None or weights.get(a, 0.0) >= 0.0:
            continue
        moved = weights[a] * (inv_dur[b] / inv_dur[a])            # modDur_a / modDur_b = inv_dur[b] / inv_dur[a]
        weights[b] = weights.get(b, 0.0) + moved
        weights[a] = 0.0

    return weights, skipped


def collinear_factor_pairs(cov: pd.DataFrame, threshold: Optional[float] = None) -> list:
    """Factor pairs whose |correlation| is at least ``threshold`` (default
    ``RiskModelConfig.COLLINEAR_WARN_CORR``), strongest first, as ``(a, b, corr)``.

    Takes the same annualised EWMA covariance the sleeve risk parity uses, so the warning matches the
    allocation. It is a diagnostic only: nothing is filtered (the risk parity makes near-duplicates
    share one risk budget). Returns [] for an empty / unusable covariance."""
    if cov is None or cov.empty or cov.shape[0] < 2:
        return []
    if threshold is None:
        from multiasset.config import RiskModelConfig
        threshold = RiskModelConfig.COLLINEAR_WARN_CORR
    sd = np.sqrt(np.clip(np.diag(cov.values), 0.0, None))
    with np.errstate(divide='ignore', invalid='ignore'):
        corr = cov.values / np.outer(sd, sd)
    names, out = list(cov.index), []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            c = corr[i, j]
            if np.isfinite(c) and abs(c) >= threshold:
                out.append((names[i], names[j], float(c)))
    return sorted(out, key=lambda t: -abs(t[2]))


# Slope / curvature factor -> the level factor it is tied to inside an IR / credit group.
_LEVEL_OF = {'IRSL': 'IRDL', 'IRCV': 'IRDL', 'CRSL': 'CRDL', 'CRCV': 'CRDL'}


def _newton_erc(C: np.ndarray, iters: int = 200, tol: float = 1e-12) -> np.ndarray:
    """Equal-risk-contribution weights x > 0 for covariance ``C``.

    Solves the convex problem  min 0.5 x'Cx - (1/K) sum(log x)  by damped Newton;
    its stationarity condition is x_k (Cx)_k = 1/K for every k, i.e. every
    variable contributes the same share of portfolio variance. The solution is
    unique for positive-definite ``C`` (Spinu 2013), so no starting-point luck.
    """
    K = C.shape[0]
    b = np.full(K, 1.0 / K)
    x = 1.0 / np.sqrt(np.maximum(np.diag(C), 1e-18))      # inverse-vol start
    x = x / np.sqrt(x @ C @ x)
    for _ in range(iters):
        g = C @ x - b / x
        if np.max(np.abs(x * (C @ x) - b)) < tol:
            break
        H = C + np.diag(b / x ** 2)
        step = np.linalg.solve(H, g)
        t = 1.0
        while np.any(x - t * step <= 0):                  # stay strictly positive
            t *= 0.5
        x = x - t * step
    return x


def erc_sleeve_budgets(factors: Sequence[str], cov: pd.DataFrame) -> Optional[Dict[str, float]]:
    """Pool-level equal-risk-contribution capital budgets (the "real" risk parity).

    Risk units are every factor EXCEPT a slope / curvature factor whose level
    factor (same country / issuer) is also in the pool: those are tied to their
    level factor by sqrt(vol), ``e_slope / e_level = sqrt(vol_slope / vol_level)``
    - the convention Stage 1 already uses - so an IR (or credit) group is ONE
    risk unit that gets the same share of portfolio risk as, say, USDCNY or gold.
    Correlations enter through ``cov`` (annualised, price-return space, as from
    ``compute_ewma_factor_covariance``).

    Returns fractions summing to 1, or ``None`` when the covariance cannot be
    used (fewer than two factors, a factor missing, non-positive variances) so
    the caller can fall back to the legacy rule.
    """
    factors = list(factors)
    if len(factors) < 2 or cov is None or cov.empty:
        return None
    if any(f not in cov.index or f not in cov.columns for f in factors):
        return None
    S = cov.loc[factors, factors].to_numpy(dtype=float)
    S = (S + S.T) / 2.0
    var = np.diag(S).copy()
    if not np.all(np.isfinite(S)) or np.any(var <= 0):
        return None
    w_, v_ = np.linalg.eigh(S)                            # repair tiny negative eigenvalues
    S = (v_ * np.maximum(w_, 1e-10 * w_.max())) @ v_.T
    sigma = np.sqrt(np.diag(S))
    idx = {f: i for i, f in enumerate(factors)}

    columns, tied = [], {}
    for f in factors:
        prefix, _, suffix = f.partition('.')
        lvl = f'{_LEVEL_OF[prefix]}.{suffix}' if prefix in _LEVEL_OF else None
        if lvl is not None and lvl in idx:
            tied.setdefault(lvl, []).append(f)
        else:
            columns.append(f)
    V = np.zeros((len(factors), len(columns)))
    for k, f in enumerate(columns):
        V[idx[f], k] = 1.0
        for g in tied.get(f, []):
            V[idx[g], k] = np.sqrt(sigma[idx[g]] / sigma[idx[f]])
    x = _newton_erc(V.T @ S @ V)
    e = V @ x
    e = e / e.sum()
    return {f: float(e[idx[f]]) for f in factors}


def pool_sleeve_budgets(factors: Sequence[str], vol_map: Dict[str, float],
                        cov: Optional[pd.DataFrame] = None) -> Dict[str, float]:
    """Capital budget per factor sleeve over the book's OWN factor pool —

    ``RiskModelConfig.SLEEVE_BUDGET_RULE == 'erc'`` (default) with a usable ``cov``
    gives the pool-level equal-risk-contribution budgets (``erc_sleeve_budgets``).
    Otherwise (rule ``'sqrt_vol_equal'``, no covariance, or a covariance that
    cannot be used) the legacy rule below applies.

    Legacy rule:
    the same rule the Portfolio tab uses for RP Max (see
    web/tabs/beta/callbacks/portfolio_run/_run_analysis._fallback_rp_budgets):
    IR factors (IRDL/IRSL/IRCV) share an n_ir/n capital envelope in
    proportion to sqrt(vol) (Level > Slope > Curvature); other factors get
    an equal share of the remaining envelope. Sums to 1.

    Stage 1's reference_factor_budget is NOT used for sleeves: its ERC runs
    over every globally-known factor, so a pool's own factors can receive
    near-zero shares (IRDL.CN measured at ~2e-19 for a CN-only pool).
    """
    from multiasset.budget import derive_vol_sqrt_budgets

    factors = list(factors)
    if not factors:
        return {}
    from multiasset.config import RiskModelConfig
    if cov is not None and getattr(RiskModelConfig, 'SLEEVE_BUDGET_RULE', 'erc') == 'erc':
        erc = erc_sleeve_budgets(factors, cov)
        if erc is not None:
            return erc
    ir = [f for f in factors if f.split('.')[0] in _IR_BASIS]
    other = [f for f in factors if f not in ir]
    n = len(factors)
    out: Dict[str, float] = {}
    if ir:
        ir_budgets, _ = derive_vol_sqrt_budgets(ir, vol_map)
        out.update({f: b * len(ir) / n for f, b in ir_budgets.items()})
    out.update({f: 1.0 / n for f in other})
    return out


def scale_sleeve_to_dv01_target(
    weights_daily: pd.DataFrame,
    mod_dur_daily: pd.DataFrame,
    total_capital_cny: float,
    max_dv01_per_capital: float,
    max_utilisation: float,
    overlay_assets: Sequence[str] = (),
    overlay_margin_rate: float = 0.0,
    short_capital_rate: Optional[float] = None,
    short_max: Optional[float] = None,
) -> pd.DataFrame:
    """Scale each day's signed sleeve weights (``signed_sleeve_weights_daily``'s
    output) by a single per-day scalar so the book's DV01 reaches
    ``max_dv01_per_capital * total_capital_cny / 1e10`` (the Portfolio tab's
    "max_duration" convention: a 10BN book with max_dv01_per_capital=10 may
    hold up to 10 MM CNY/bp), without ever pushing gross notional past
    ``max_utilisation * total_capital_cny`` — for this factor pool's sleeve
    construction (Level/Slope/Curvature spread across all six CN tenors,
    never concentrated in the long end), the gross cap binds on effectively
    every day at a DV01 target much above ~5 MM/bp on a 10BN book, so it is
    the gross cap — not this function's own safety floor below — that
    determines the achieved DV01 in practice; there is no leverage involved
    in reaching it.

    The whole day's weights are scaled by ONE number — the cross-tenor and
    cross-factor SHAPE (the long/short structure that replicates each
    factor) is preserved exactly; only the overall size changes.

    A day where the sleeves' long/short legs happen to nearly cancel (raw
    gross weight near zero, e.g. IRSL/IRCV signals offsetting IRDL's) is
    left FLAT (dv01_scale=1, i.e. unscaled from signed_sleeve_weights_daily's
    already-tiny raw weight) rather than scaled to the target: with gross
    itself near zero, ``max_utilisation / raw_gross`` is enormous, so scaling
    to IT (not just to the DV01 target) would turn noise-level weights into
    an arbitrary large position — measured ~5% of days for a 3-factor CN
    pool, gross down to 2+ orders of magnitude below the daily median.
    """
    target_dv01_mm = max_dv01_per_capital * (total_capital_cny / 1e10)
    raw_dv01_mm = (weights_daily * mod_dur_daily).abs().sum(axis=1) * (total_capital_cny / 1e10)
    # Capital usage: LONG size plus ``short_capital_rate`` (default RiskModelConfig.
    # SHORT_CAPITAL_RATE = 0) of the short size; longs and shorts are never netted. Shorts in
    # ``overlay_assets`` will be traded with futures / swaps (multiasset.book.overlay): they tie
    # up margin, so they count at ``overlay_margin_rate``. DV01 below stays GROSS (long + short).
    if short_capital_rate is None:
        from multiasset.config import RiskModelConfig
        short_capital_rate = RiskModelConfig.SHORT_CAPITAL_RATE
    ov = [a for a in overlay_assets if a in weights_daily.columns]
    rest = [c for c in weights_daily.columns if c not in ov]
    shorts = weights_daily.clip(upper=0.0).abs()
    raw_gross = (weights_daily.clip(lower=0.0).sum(axis=1)
                 + short_capital_rate * shorts[rest].sum(axis=1)
                 + overlay_margin_rate * shorts[ov].sum(axis=1))

    # A day whose raw gross is negligible relative to the book's typical day
    # carries no meaningful signal to scale up — treat it as flat rather
    # than dividing by a near-zero raw_gross/raw_dv01 below. Threshold is
    # relative (5% of the trailing/whole-window median), so it adapts to
    # whatever scale the caller's weights are in.
    # "Negligible" is judged on the GROSS size (long + short), NOT on the capital-usage
    # ``raw_gross`` above: with shorts free, a day of large shorts and almost no longs has a
    # tiny usage but a perfectly real book, and must still be scaled to the DV01 target.
    abs_gross = weights_daily.abs().sum(axis=1)
    median_gross = abs_gross[abs_gross > 0].median()
    negligible = pd.Series(False, index=weights_daily.index)
    if pd.notna(median_gross) and median_gross > 0:
        negligible = abs_gross < 0.05 * median_gross

    dv01_scale = pd.Series(1.0, index=weights_daily.index)
    has_dv01 = (raw_dv01_mm > 1e-9) & ~negligible
    dv01_scale[has_dv01] = target_dv01_mm / raw_dv01_mm[has_dv01]

    # dv01_scale must never exceed what keeps gross <= max_utilisation (a
    # low-average-duration day would otherwise scale gross past the capital
    # ceiling trying to hit the DV01 target) — this is what actually
    # determines the achieved DV01 on almost every day for this sleeve
    # construction (see docstring).
    has_gross = (raw_gross > 1e-9) & ~negligible
    max_scale_for_gross = pd.Series(np.inf, index=weights_daily.index)
    max_scale_for_gross[has_gross] = max_utilisation / raw_gross[has_gross]
    # ... nor push the SHORT book past its own ceiling (same as the long book by default).
    from multiasset.config import RiskModelConfig as _R
    if short_max is None:
        short_max = _R.SHORT_SIZE_MAX_RATIO * max_utilisation
    short_size = shorts.sum(axis=1)
    has_short = (short_size > 1e-9) & ~negligible
    max_scale_for_short = pd.Series(np.inf, index=weights_daily.index)
    max_scale_for_short[has_short] = short_max / short_size[has_short]
    dv01_scale = dv01_scale.clip(upper=np.minimum(max_scale_for_gross, max_scale_for_short))

    return weights_daily.mul(dv01_scale, axis=0)
