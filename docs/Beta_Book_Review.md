# Beta Book Tab — Code & Methodology Review

*Review date: 2026-06-11. Scope: `web/tabs/beta/` (layouts + callbacks) and the supporting
`multiasset/` engine (`factor_optimizer.py`, `factor_model.py`, `factor_backtest.py`,
`data.py`, `main.py`, `pca_analyzer.py`).*

---

## 1. Overall Assessment

The Beta Book is a coherent, end-to-end factor-allocation workstation: deterministic
Level/Slope/Curvature risk factors → walk-forward predictive factor model → factor risk
parity / risk-budget optimisation → tradable position table with DV01 caps, OTR
substitution and a hedge-ticket overlay. The methodology is thoughtful in several places
(purged/embargoed walk-forward, EWMA-weighted IC, full factor covariance Σ = B·C_f·Bᵀ,
path-independent discrete sizing). The main weaknesses are:

1. **Several silent correctness bugs in the data layer** (spread assets produce no PnL).
2. **Two parallel implementations of "the strategy"** — the live Run Analysis path and the
   historical backtest path diverge, so the backtest does not validate what you trade.
3. **Module-level global state and import-time side effects** that will break under
   multi-user / multi-worker Dash deployment.
4. **A factor covariance with no idiosyncratic risk**, which makes the ERC problem
   degenerate and forced a cascade of ad-hoc weight floors/caps.
5. **Heavy duplicated logic and 200–800 line callbacks** that mix business logic,
   persistence, and UI rendering — hard to test, hard to keep consistent.

---

## 2. Correctness Bugs (fix first)

### 2.1 Spread assets silently contribute zero PnL in the backtest
`multiasset/data.py`:

- `get_universe()` (lines 80–113) has **no branch for spread assets** (`IRS*`, `CDB*`,
  `ICP*`) — they fall through to `'N/A'`, so `get_asset_yield_series()` returns `None`
  for every spread asset.
- Even if universe were fixed, `get_asset_yield_series()` compares the **dict** to a
  string: `if spread_type == 'CDB':` (line 192) — `spread_type` is the mapping dict;
  the comparison is always `False`. It should be `if spread == 'CDB':` (same for
  `'IRS'`/`'ICP'`).

Effect: in `backtest_hist.py` the per-asset `try/except` around
`calculate_daily_returns_series` swallows the failure with a print warning, so any
backtest including SPDL/SPSL factors shows allocations but **no PnL** for those assets.
Unnoticed today because the default `SELECTED_FACTOR_POOL` has `sp_factors: []`.

### 2.2 `calculate_asset_monthly_return` always returns 0 for CN bonds
`multiasset/data.py:449` — `col not in cn_data.columns`, but `cn_data` is a **dict** of
DataFrames; `.columns` raises `AttributeError`, which the enclosing
`except Exception` converts into `(0, 0, 0, 0)`. CN rates monthly returns from this
function are silently zero.

### 2.3 `bucket_position` is asymmetric for long-short factors
`multiasset/factor_model.py:653-717` — long-only vs long-short is detected per-value via
`position >= 0`. A long-short factor at **+0.3 buckets to 0.5** (long-only scale) while
**−0.3 buckets to −1** (long-short scale). Positive positions always get the long-only
mapping, so displayed/scaled signals are biased between the long and short side. The
function needs an explicit `long_only` argument (the caller knows it: `IRDL` prefix),
not value-based detection. Note also the scale mismatch: `discrete_target_level`
produces targets in [−1, 1] while `bucket_position` emits levels up to ±2 — and
`backtest_hist.py` multiplies RP weights by this value, i.e. a "+2" doubles the weight.
Pick one convention and document it.

### 2.4 `_SUMMARY_BETA_PARQUET` written twice per run with different schemas
`portfolio_run.py`: `run_analysis` writes the summary-format table at lines 586–595
(`to_parquet`, full overwrite), then at lines 680–697 **upserts a differently-shaped
snapshot into the same file**. The second write merges against the first, producing a
union-schema file with half-empty rows. Decide which representation the Summary tab
owns and write it once.

### 2.5 Missing-signal default is "full long"
`portfolio_run.py:256-260` — when a factor has no snapshot record, `get_coeff` returns
`1.0` ("full long placeholder"). Combined with mode `factor_scaling`, a user who forgot
to hit *Predict* gets maximum exposure with only a small status hint. A missing signal
should degrade to neutral (0) or block the run, not max conviction.

---

## 3. Workflow

**What works:** the Factor → Candidates/Predict → Portfolio → Summary pipeline is a
sensible separation of signal generation from allocation; the three allocation modes
(pure RP / factor scaling / user-defined) with the mode hint (3.8) are clear; persisting
positions to parquet so the Summary/Risk tab survives restarts is pragmatic.

**Issues:**

- **Hidden coupling via globals and files.** Tab-to-tab state flows through module-level
  globals (`SELECTED_FACTOR_POOL`, `ALLOCATION_RESULTS`, `DIVERSIFICATION_RECOMMENDATIONS`
  in `web/tabs/beta/data.py`) and pickle/parquet files (`factor-backtest.pkl`,
  `summary_beta_portfolio.parquet`). Globals are per-process: with `gunicorn -w N` or
  any second user, the Factor tab selection seen by the Backtest tab is whichever worker
  handled the request. The IRDL hedge callback reads `ALLOCATION_RESULTS` instead of the
  `portfolio-data-store` it nominally depends on — stale across sessions/restarts.
  → Move cross-tab state into `dcc.Store` (session) or a server-side cache keyed by
  session id; treat files only as deliberate persistence, not IPC.
- **Step-skipping is silent.** Run Analysis works even when signals were never generated
  (defaults to scalar 1.0, §2.5) and the backtest only warns in stdout when factors are
  missing returns. Make preconditions explicit in the UI (disable Run buttons with a
  reason, surface skipped assets/factors in the result panel rather than the console).
- **No run metadata.** Saved snapshots only carry `_timestamp`. Save the config that
  produced them (mode, capital, factor pool, model month-key) so a Summary table is
  reproducible and auditable.

---

## 4. Code Structure

**What works:** the split into `layouts/` + `callbacks/` with per-domain modules and
`register_*` functions is the right shape; `_common.py` for shared paths/upsert; the
engine code lives in `multiasset/` rather than in callbacks.

**Issues:**

- **Callbacks are too big and impure.** `run_analysis` (~280 lines) does budget
  derivation, optimisation, lot rounding, DV01 capping, two parquet writes and DataTable
  construction in one function; `update_historical_allocation` (~630 lines) is the whole
  backtest engine inline in a callback. Extract pure, testable functions
  (`derive_risk_budgets(mode, …) -> dict`, `round_to_lots(df) -> df`,
  `apply_dv01_cap(df, cap) -> (df, msg)`, `run_allocation_backtest(cfg) -> BacktestResult`)
  and keep callbacks as thin adapters: parse inputs → call engine → render.
- **Triplicated vol^0.5 budget logic.** The sqrt-vol budget computation exists in
  `update_risk_budget_inputs`, in `run_analysis` (`factor_scaling` branch), and again as
  a two-pass fit in `backtest_hist.py`. One function in `multiasset` should own it.
- **Duplicated asset/factor mappings.** `rates_map`/`comm_map`/`fx_map` inside
  `update_risk_budget_inputs` re-derive what `FACTOR_TO_ASSET_MAP` already encodes
  (inverted), and `get_asset_type/get_universe/get_sector` do fragile substring matching
  (`'CN' in name`) as a third source of truth. Build a single asset registry
  (name → type, universe, sector, factors, lot size, tenor map column) and derive all
  mappings from it. This also removes the hardcoded Chinese column names repeated in 3+
  places in `multiasset/data.py`.
- **Import-time side effects.** `multiasset/main.py:30-33` calls `retrieveFXIRCurves()`
  at import. Every module importing anything from `multiasset.main` may trigger data
  retrieval. Move it into an explicit `ensure_data()` call.
- **`web/tabs/beta/data.py` is a grab-bag** — theme, globals, futures-backtest imports,
  factor map, vol helper. Split: `theme.py`, `state.py`, `mappings.py`.
- **Magic numbers scattered**: 15% estimated commodity vol, 3% min weight, 25/20/15%
  class caps (which differ between `factor_optimizer.py` and the `_CLASS_CAPS` in
  `backtest_hist.py`!), 0.2 signal floor, 10MM/1MM lot units, 2% risk-free rate.
  Consolidate in `RiskModelConfig` so live and backtest can't drift.
- **`print` instead of `logging`**, and many `except Exception: pass` blocks that
  swallow real failures (e.g. user-data parquet load). Use a logger and narrow the
  exceptions.

---

## 5. Performance

- **Loader instances are recreated per callback.** `compute_factor_vol_map`,
  `backtest_hist`, `_get_beta_close_prices` each build a fresh `RiskFactorLoader` whose
  cache is instance-level — the risk-factor pickle is re-read/re-derived on every
  callback fire. `multiasset/main.py` already has `_SHARED_LOADER`; route everything
  through it (or an `lru_cache`d accessor with a file-mtime key).
- **The backtest fits the optimizer twice per rebalance date.**
  `backtest_hist.py:405-414` calls `fit_and_calculate` once just to get factor vols and
  again with sqrt-vol budgets. The vols are available from
  `compute_ewma_factor_vols` directly — one SLSQP solve per date, not two. Also,
  `compute_ewma_factor_covariance` computes the full `ewm().cov()` MultiIndex history
  and keeps only the last slice — for a T×F window this is O(T·F²) with large pandas
  overhead; computing the EWMA covariance recursively or with `np.einsum` on the last
  window is much cheaper when called once per rebalance date.
- **The daily PnL loop is pure-Python O(days × assets)** with per-cell
  `trading_day in ret_df.index` checks (`backtest_hist.py:527-558`). Vectorise: build a
  returns matrix (`pd.concat` of return series, columns = assets), forward-fill the
  allocation matrix to daily frequency, then `(alloc * rets).cumsum()`. This typically
  turns minutes into milliseconds and removes the most fragile code in the file.
- **Long jobs run inside synchronous callbacks.** A 10Y backtest or a FactorModel batch
  train blocks the Dash worker and risks browser timeouts. Use Dash
  `background=True` callbacks (DiskCache/Celery manager) with progress output for
  Run Historical Analysis / Train.
- **`predict_factor_signals` rebuilds full-history features per factor** just to use the
  recent rows. Restrict feature construction to a trailing window (max lookback any
  feature needs is 252 + buffer).

---

## 6. Factor Model (algorithms)

**Strengths worth keeping:** walk-forward with purge + embargo (López de Prado style),
IC significance gating + VIF/correlation diversification, signed-IC weighting with
prediction rescaling, multi-horizon (1/5/20d) ensemble blended by |IC|, EWMA observation
weighting, path-independent discrete sizing with an ICIR confidence ramp, flat
transaction costs in PnL.

**Concerns:**

1. **Overlapping forward returns inflate significance.** For H=5/20 the targets
   `returns.rolling(H).sum().shift(-H)` overlap daily, so the `spearmanr` p-value used
   as the gate (`p < 0.05`) assumes ~H× more independent observations than exist. Use
   non-overlapping samples for the test, a block bootstrap, or a Newey–West-adjusted
   IC t-stat. Right now the feature-selection gate is much weaker than it looks.
2. **"Fix 1–4" are regime patches with overfitting risk.** Trend veto on mean-reversion
   features, the IRDL long floor during confirmed rallies, and the 0.2 signal floor in
   the backtest all read like responses to one specific historical episode (the CN bond
   bull). Each one adds parameters (`trend_veto_mom_sigma`, `long_floor`,
   `long_floor_confirm_window`, `_SIGNAL_FLOOR`) tuned in-sample. Validate each fix on a
   held-out period (or another country's curve) and record the before/after — otherwise
   the walk-forward rigor upstream is undone by post-hoc overlays.
3. **Inconsistent signal conventions across consumers** (§2.3): engine target ∈ [−1,1] in
   0.2 ticks; `bucket_position` display levels ∈ {−2…+2}; backtest scaling treats the
   bucketed level as a multiplicative weight (up to 2×); portfolio snapshot scalar is the
   [−1,1] value. Define one canonical signal (suggest: the [−1,1] discrete target) and
   convert at the display edge only.
4. **Long-only handling is hardcoded by prefix** (`IRDL`) in two places
   (`run_factor_model_backtest`, snapshot path). Put `long_only` in the factor metadata
   alongside duration/yield-vs-price so new factor families don't need code edits.
5. **Metrics are defined twice and disagree**: `factor_backtest.compute_metrics` uses
   arithmetic annualisation and no risk-free rate; `backtest_hist` uses geometric
   annualisation with rf = 2%. A Sharpe shown on the Factor tab is not comparable to one
   on the Backtest tab. One metrics module, one definition.

---

## 7. Optimisation Method

**Strengths:** using the full EWMA factor covariance (Σ = B·C_f·Bᵀ) instead of the
diagonal approximation; signed risk-budget matching to allow short-slope expressions;
proper factor-level RC attribution for reporting; the two-stage fallback when the hedge
solve fails.

**Concerns:**

1. **No idiosyncratic variance ⇒ degenerate ERC.** With Σ = B·C_f·Bᵀ only, the six CN
   bonds that load on the same three factors are *perfectly* collinear in risk space —
   the optimizer comment itself notes the "degenerate ERC landscape". The 3% min-weight
   floor, the 25/20/15% class caps and the 1e-8 ridge are all compensating for this.
   The cleaner fix is Σ = B·C_f·Bᵀ + D with per-asset residual variances (from
   regressing asset returns on factor returns, or even a small fixed fraction of asset
   vol). That restores a unique ERC solution and lets you relax most of the ad-hoc
   bounds.
2. **SLSQP on a non-convex objective.** Squared RC-deviation under box constraints has
   local minima; results can depend on `w0`. For pure ERC, the Spinu formulation
   (`min ½wᵀΣw − Σ bᵢ ln wᵢ`) is convex and solvable with Newton/CCD — deterministic
   answer, no floors needed for positivity. Keep SLSQP only for the signed-budget case.
   At minimum, check `result.success` on the primary path (it is currently checked only
   when hedges are present) and surface non-convergence to the UI.
3. **Bounds likely dominate the solution.** With ~10 assets, floor 3% and cap 25%, the
   feasible region is narrow — the output is closer to "capped inverse-vol" than to risk
   parity. That may be fine (it's an investment choice), but the UI labels it Risk
   Parity; report realised RC vs target budgets in the results table so the user sees
   how binding the constraints were. Also note the equality constraint `Σw = 1` can be
   infeasible with caps when an asset list is short (e.g. 3 assets × 25% cap) — guard
   for that.
4. **Two unit systems for budgets.** Full-covariance mode treats budgets as *fractions*;
   legacy diagonal mode treats them as absolute `|e·σ|` targets scaled by capital. The
   silent switch between semantics depending on whether `factor_cov` happens to be
   non-empty is a trap; pick the proportional formulation everywhere.
5. **Encapsulation leak:** `optimize()` reads
   `self.portfolio.risk_factor_loader._risk_factors_cache` (private) to find the data
   max date — add a public `last_date()` to the loader.
6. **Backtest ≠ production.** The live path (`run_risk_parity_allocation` with budgets,
   DV01 cap, lot rounding, OTR substitution) and the backtest path (two-pass sqrt-vol
   budgets, per-class cap loop, no DV01 cap, no rounding, no costs) are different
   strategies. Backtest results therefore neither validate nor predict the live book.
   Unify into one `AllocationEngine.run(date, pool, mode, signals, cfg)` used by both,
   and add turnover/transaction costs to the historical backtest while you're there.

---

## 8. Prioritised Improvement Plan

### Phase 1 — Correctness (small diffs, do first)
1. Fix spread-asset return chain: add spread branch to `get_universe`, fix
   `spread_type ==` → `spread ==` in `get_asset_yield_series` (§2.1); add a regression
   test asserting every asset in `FACTOR_TO_ASSET_MAP` produces a non-empty daily-return
   series.
2. Fix `cn_data.columns` AttributeError path (§2.2).
3. Give `bucket_position` an explicit `long_only` parameter; reconcile signal scales
   (§2.3, §6.3).
4. Remove the duplicate `_SUMMARY_BETA_PARQUET` write (§2.4).
5. Change missing-signal default from 1.0 to 0.0 + explicit UI warning (§2.5).
6. Check `result.success` on the primary optimizer solve and surface failures.

### Phase 2 — One engine, one truth
7. Extract `run_analysis` / `update_historical_allocation` business logic into
   `multiasset` pure functions; callbacks become thin adapters.
8. Single budget-derivation function (vol^0.5 / RP / user) shared by Portfolio tab,
   risk-budget display, and backtest.
9. Single asset registry replacing `FACTOR_TO_ASSET_MAP` + `get_asset_type/universe/
   sector` + the inline maps in `portfolio_run.py`.
10. One metrics module (Sharpe/MDD/ann. return) used by all tabs.
11. Move magic numbers (caps, floors, est. vols, lot sizes, rf rate) into
    `RiskModelConfig`.

### Phase 3 — State & performance
12. Replace module-level globals with `dcc.Store`/server-side cache; make the hedge
    callback consume the store, not `ALLOCATION_RESULTS`.
13. Shared cached `RiskFactorLoader`; remove `retrieveFXIRCurves()` import side effect.
14. Vectorise the backtest daily-PnL loop; single optimizer fit per rebalance.
15. Background callbacks + progress for backtest and model training.

### Phase 4 — Methodology upgrades
16. Add idiosyncratic variance to Σ; relax weight floors/caps accordingly; convex ERC
    solver for the pure-RP mode.
17. Overlap-aware IC significance (non-overlapping or Newey–West) for H=5/20.
18. Out-of-sample validation report for Fix 1–4 overlays (trend veto, long floor,
    signal floor) — keep only the ones that survive.
19. Transaction costs + turnover stats in the historical allocation backtest; report
    realised RC vs budget in the Portfolio results.
20. Persist run metadata (config hash, model month-key, factor pool) with every saved
    snapshot for reproducibility.

---

## 9. Quick Reference — Files Cited

| Area | File |
|---|---|
| Run Analysis / budgets / hedge | `web/tabs/beta/callbacks/portfolio_run.py` |
| Historical backtest | `web/tabs/beta/callbacks/backtest_hist.py` |
| Globals / theme / factor-asset map | `web/tabs/beta/data.py` |
| Shared paths / upsert | `web/tabs/beta/callbacks/_common.py` |
| Optimizer (ERC / budgets) | `multiasset/factor_optimizer.py` |
| Predictive factor model | `multiasset/factor_model.py` |
| Factor returns / vols / strategies | `multiasset/factor_backtest.py` |
| Asset return data layer | `multiasset/data.py` |
| Portfolio construction / hedge defs | `multiasset/main.py` |
