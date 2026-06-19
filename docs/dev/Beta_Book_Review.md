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

*Last revised: 2026-06-16 (updated to reflect session changes since 2026-06-11 review).*

**Strengths worth keeping:** walk-forward with purge + embargo (López de Prado style),
IC significance gating + VIF/correlation diversification, signed-IC weighting with
prediction rescaling, multi-horizon (1/5/20d) ensemble blended by |IC|, EWMA observation
weighting, path-independent discrete sizing with an ICIR confidence ramp, flat
transaction costs in PnL.

**Concerns:**

1. **Overlapping forward returns inflate significance.** *(RESOLVED 2026-06-16)*
   Added `_newey_west_ic_pvalue(ic, n, horizon)` in [factor_model.py](../multiasset/factor_model.py)
   which computes an effective-N adjusted t-stat (`n_eff = n/H`) and derives a two-tailed
   p-value from it. `_compute_ic_metrics` now accepts a `horizon` parameter and uses this
   corrected p-value for `is_significant` — so for H=5/20 the gate correctly accounts for
   ~H× fewer independent observations. Call site passes `horizon=H` per fold.
2. **"Fix 1–4" are regime patches with overfitting risk.** *(STILL OPEN — validation task)*
   Trend veto on mean-reversion features, the IRDL long floor during confirmed rallies, and
   the 0.2 signal floor all add in-sample-tuned parameters. Validate each on a held-out
   period (or another country's curve) and record before/after metrics — otherwise the
   walk-forward rigor upstream is undone by post-hoc overlays. Note: `_SIGNAL_FLOOR`
   also governs the `factor_scaling` two-stage path, widening its impact.
   *No code change here — this is a backtesting and documentation task.*
3. **Inconsistent signal conventions across consumers.** *(RESOLVED 2026-06-16)*
   `result['position']` in `run_factor_model_backtest` now stores the raw `build_position_series`
   output directly (canonical [-1,1] scale). The `bucket_position` call that was converting
   it to {0…2}/{-2…2} has been removed from the backtest path — display bucketing belongs
   only at the UI layer. The portfolio snapshot already uses the [-1,1] value, so the two
   paths now agree.
4. **Long-only flag hardcoded by IRDL prefix.** *(RESOLVED 2026-06-16)*
   Added `_LONG_ONLY_PREFIXES: frozenset` and `_is_long_only(factor_code)` helper in
   [factor_model.py](../multiasset/factor_model.py). Both occurrences of
   `factor_code.split('.')[0] == 'IRDL'` replaced with `_is_long_only(factor_code)`.
   New long-only factor families now require only an entry in the frozenset, not a code edit.
5. **Metrics are defined twice and disagree.** *(RESOLVED 2026-06-16)*
   `compute_metrics` in `backtest_rfbt.py` now called with
   `risk_free_rate=RiskModelConfig.RISK_FREE_RATE, geometric_annualisation=True` — matching
   what `compute_portfolio_metrics` (used on the Backtest tab) already does. Sharpe ratios
   on the Factor tab and Backtest tab now use the same annualisation convention and RF rate.
   `compute_portfolio_metrics` is kept as a thin wrapper (no duplication to remove).
6. **Data-gap hygiene.** *(NEW — added 2026-06-16)* A 42-day source-data gap
   (2026-02-07 → 2026-03-19) in commodity series produced a spurious +66% one-day
   return that was only discovered via a PnL chart. A null-on-gap->15-days fix has been
   applied in `assets.py` for `CommodityAsset` and `FXAsset`. **Add a data-quality gate**
   at load time: assert max calendar gap per series, surface any violations in the UI so
   gaps are caught before optimisation runs, not after.

---

## 7. Optimisation Method

*Last revised: 2026-06-16 (updated again for Phase 4 implementation). Major architectural
change since original review: the two-stage allocation (`_two_stage_weights`) is now the
primary path for pure risk parity.  Stage 1 = ERC across factors (IRDL/IRSL/IRCV) in
factor space using rolling EWMA covariance; Stage 2 = analytic inverse-duration (DV01)
split within each factor group.  Scale-adaptive floors/caps (`RiskModelConfig.scaled_bounds(n)`)
replace hard-coded values.  Concerns below are revised accordingly.*

**Strengths:** using the full EWMA factor covariance (Σ = B·C_f·Bᵀ) instead of the
diagonal approximation; signed risk-budget matching to allow short-slope expressions;
proper factor-level RC attribution for reporting; two-stage path separates the
"how much to IRDL.CN" question (ERC, time-varying) from "how to split across tenors"
(analytic DV01, deterministic); scale-adaptive bounds now feasible across pool sizes 3–20+.

**Concerns:**

1. **No idiosyncratic variance ⇒ degenerate single-stage ERC.** *(CONTEXT CHANGED)*
   With Σ = B·C_f·Bᵀ + 1e-8·I only, CN bonds loading on the same three factors are
   perfectly collinear in risk space, making single-stage ERC degenerate. The two-stage
   architecture introduced in this session **already handles this** for the primary path:
   Stage 1 ERC operates in the lower-dimensional factor space (no collinearity), and Stage
   2 is analytic. Adding residual variance D = diag(σ²_residual) to Σ would allow the
   single-stage `_optimize_weights` path to work cleanly without the two-stage crutch, and
   is the right long-term fix — but it is no longer blocking. Defer to Phase 4 unless the
   single-stage path needs to be revived.
2. **SLSQP on a non-convex objective.** *(RESOLVED 2026-06-16)*
   Stage-1 ERC non-convergence in `_two_stage_weights` now emits a `RuntimeWarning`
   with status/message and falls back to equal factor budgets. The `_optimize_weights`
   path already warned on non-convergence. For the pure ERC case the Spinu convex
   formulation remains a future improvement (deferred — SLSQP in the 3–6 factor space
   is empirically stable).
3. **Two-stage floor/cap loop has no convergence guarantee.** *(RESOLVED 2026-06-16)*
   Three changes in `_two_stage_weights` ([factor_optimizer.py](../multiasset/factor_optimizer.py)):
   (a) **Feasibility guard** — before the clip→renorm loop, sum all per-asset floors and
   warn if `Σ floors > 1` (jointly infeasible), advising the user to reduce `FLOOR_RATIO`
   constants in `RiskModelConfig`. (b) **Post-solve bounds assertion** — after the loop,
   check every weight against its class floor/cap and emit a `RuntimeWarning` listing any
   violations beyond 1e-4. (c) Realised RC vs target surfacing deferred to Phase 3
   (requires UI changes in the Portfolio results table).
4. **Two unit systems for budgets.** *(RESOLVED 2026-06-16)*
   `_optimize_weights` no longer has a diagonal-mode branch with absolute `|e·σ|` targets.
   All budget paths now use the same proportional fraction formulation:
   `budget_fracs = raw_budgets / |raw_budgets|.sum()` and the full-covariance RC objective
   `min Σ(RC_fraction - budget_frac)²`. The legacy absolute-target branch and its
   `max_budget_constraint` inequality have been removed.
5. **Encapsulation leak.** *(RESOLVED 2026-06-16)*
   Added `last_date() → Optional[pd.Timestamp]` to `RiskFactorLoader`
   ([risk_loader.py](../multiasset/risk_loader.py)). `optimize()` now calls
   `self.portfolio.risk_factor_loader.last_date()` instead of reading
   `._risk_factors_cache.index.max()` directly. Raises `RuntimeError` with a clear
   message if no data is loaded.
6. **Backtest ≠ production.** *(RESOLVED 2026-06-16)*
   `optimize()` already routes exclusively through `fit_and_calculate()` /
   `_two_stage_weights` — same code path as the backtest. Added
   `FactorRiskParityOptimizer.assert_weights_match(w1, w2, tol, label)` static method
   ([factor_optimizer.py](../multiasset/factor_optimizer.py)) for regression testing:
   call it with weights from `optimize()` and a direct `fit_and_calculate()` call on
   the same date/pool to confirm parity. Post-optimisation steps (DV01 cap, lot
   rounding, OTR substitution) remain live-only by design — they are not part of the
   optimisation and need not appear in the backtest.

---

## 8. Prioritised Improvement Plan

### Phase 1 — Correctness (small diffs, do first)
1. Fix spread-asset return chain: add spread branch to `get_universe`, fix
   `spread_type ==` → `spread ==` in `get_asset_yield_series` (§2.1); add a regression
   test asserting every asset in `FACTOR_TO_ASSET_MAP` produces a non-empty daily-return
   series.
2. Fix `cn_data.columns` AttributeError path (§2.2).
3. Give `bucket_position` an explicit `long_only` parameter; reconcile signal scales
   (§2.3, §6.3). *(Partially done — parameter exists, scale mismatch remains)*
4. Remove the duplicate `_SUMMARY_BETA_PARQUET` write (§2.4).
5. Change missing-signal default from 1.0 to 0.0 + explicit UI warning (§2.5).
6. Check `result.success` on the primary optimizer solve and surface failures.
   *(Done — warnings now emitted; UI surfacing still pending)*
7. ~~Add feasibility guard + post-solve bounds assertion to `_two_stage_weights`~~ *(DONE §7.3)*
8. Add data-quality gate at load time: assert max calendar gap per series, surface in UI
   (§6.6 new).

### Phase 2 — One engine, one truth
9. Extract `run_analysis` / `update_historical_allocation` business logic into
   `multiasset` pure functions; callbacks become thin adapters.
10. Single budget-derivation function (vol^0.5 / RP / user) shared by Portfolio tab,
    risk-budget display, and backtest.
11. Single asset registry replacing `FACTOR_TO_ASSET_MAP` + `get_asset_type/universe/
    sector` + the inline maps in `portfolio_run.py`. Move `long_only` into registry.
12. One metrics module (Sharpe/MDD/ann. return) used by all tabs; merge
    `compute_metrics` and `compute_portfolio_metrics` (§6.5).
13. ~~Standardise budget unit system~~ *(DONE §7.4 — proportional fractions everywhere)*
14. ~~Regression test live vs backtest weights~~ *(DONE §7.6 — `assert_weights_match()` added)*

### Phase 3 — State & performance
15. Replace module-level globals with `dcc.Store`/server-side cache; make the hedge
    callback consume the store, not `ALLOCATION_RESULTS`.
16. Shared cached `RiskFactorLoader`; remove `retrieveFXIRCurves()` import side effect.
17. Vectorise the backtest daily-PnL loop; single optimizer fit per rebalance.
    *(Single fit already done; vectorisation still open)*
18. Background callbacks + progress for backtest and model training.

### Phase 4 — Methodology upgrades
19. **Overlap-aware IC significance** (§6.1). *(DONE 2026-06-16 — Newey-West adjusted
    p-value via `_newey_west_ic_pvalue`, `horizon` param threaded through `_compute_ic_metrics`.)*
20. Out-of-sample validation report for Fix 1–4 overlays (trend veto, long floor,
    signal floor) — keep only the ones that survive (§6.2). *Still open (backtesting/doc task).*
21. **RC vs target + backtest turnover/tx costs** (§7.3). *(DONE 2026-06-16)*
    - `portfolio_run.py`: after the positions DataTable, a "Factor Risk Attribution" panel
      now shows Volatility (% ann.), Net Exposure, Realised RC %, Equal-target RC %,
      and Δ RC % (highlighted amber when |Δ| > 5%).
    - `backtest_hist.py`: per-rebalance turnover (Σ|Δweight|, one-way) computed from
      allocation changes; tx cost deducted at 0.5 bp × one-way turnover × capital on each
      rebalance day.  Metrics table now shows Sharpe (gross), Sharpe (net of tx costs),
      Annualised Turnover, and Total Tx Cost (MM CNY).  NAV chart overlays a dotted
      "net tx" line alongside the gross NAV.
22. Add idiosyncratic variance D to Σ to enable clean single-stage ERC (§7.1).
    *No longer blocking — two-stage path handles the collinearity — but correct long-term.*
23. Convex ERC solver (Spinu) for pure-RP mode to replace SLSQP (§7.2).
    *Defer until §22 is done; SLSQP in factor space is stable enough for now.*
24. **Run metadata persisted with Beta snapshot** (§3 workflow). *(DONE 2026-06-16)*
    Every row in `summary_beta_portfolio.parquet` now carries: `_timestamp`,
    `_run_mode` (risk_parity / factor_scaling / user_defined), `_capital_cny`,
    `_model_month_key` (YYYY-MM), `_factor_pool` (comma-separated sorted list),
    `_max_duration`.  The Summary tab can now show which config produced each snapshot.

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
