# FIEngine Codebase Improvement Plan

**Date:** July 2, 2026  
**Scope:** Performance optimization & structural refactoring  
**Total effort estimate:** 2–3 weeks (incremental, shippable per phase)

---

## Executive Summary

FIEngine (78,954 LOC across 287 files) has three primary issues blocking further development velocity:

1. **Dashboard is slow** — 32 instances of `.iterrows()` in `web/` callbacks (especially `risk.py`, `candidates.py`) iterate DataFrames row-by-row instead of vectorizing. Symptom: multi-second refresh latency on position/candidate tables.
2. **Duplicated quant logic** — Risk-parity weighting, EWMA vol, backtest metrics are re-implemented independently in `factor_optimizer.py`, `curves/backtest/core.py`, and `factor_backtest.py`. Risk: bug fixes and calibration changes must be applied in 3 places or silently diverge.
3. **Zero test coverage** — No unit tests exist (CLAUDE.md claims "~36 tests" but that doc is stale). Refactoring the above is risky without a safety net.

**Recommended sequence:** Safety net → Dashboard perf → Consolidate math → Structural cleanup. All phases are independent after the first, so they can run in parallel if staffed.

---

## Current State Diagnosis

### Repository Statistics

| Directory | LOC | Files | Avg LOC/file | Role |
|-----------|-----|-------|--------------|------|
| web/ | 29,138 | 71 | 410 | Dash UI + callbacks |
| curves/ | 15,507 | ~40 | 388 | Curve calibration, backtest |
| multiasset/ | 8,963 | 19 | 472 | Beta book (factor + RP) |
| factors/ | 7,849 | ~35 | 224 | Factor model, signal generation |
| futures/ | 6,384 | ~20 | 319 | Futures strategies |
| derivatives/ | 4,259 | ~15 | 284 | Options, vol analysis |
| pairs/ | 1,543 | ~12 | 129 | Pairs/spread trading |
| engine/ | 1,378 | 13 | 106 | Orchestration, CLI |
| utils/ | 1,082 | ~15 | 72 | Shared utilities |

**Largest files:**
- `web/tabs/beta/callbacks/risk.py` — 2,152 LOC (Risk/Summary tab, 10× iterrows)
- `web/tabs/atlas_fi_tabs.py` — 1,504 LOC (Main layout)
- `multiasset/factor_model.py` — 1,445 LOC (Feature eng + model + signal)
- `web/tabs/alpha/callbacks/candidates.py` — 1,436 LOC (Pair candidate selection, 6× iterrows)
- `multiasset/factor_optimizer.py` — 1,087 LOC (Two-stage RP weighting, modified in-flight)

---

## Critical Issues

### Issue #1: Dashboard Performance (`.iterrows()` hot spots)

**Problem:**  
32 instances of `.iterrows()` across `web/tabs/` callbacks — each runs on every dashboard refresh. Examples:
- `risk.py:1961` — loop over Beta positions to compute net exposure; should be `groupby().sum()`
- `risk.py:2002` — same for Alpha book
- `candidates.py:418` — loop to score pair candidates
- `portfolio_run.py:705` — position table build

**Impact:**  
Multi-second latency on large position/candidate datasets. Vectorized pandas would reduce this to milliseconds.

**Locations:**
```
web/tabs/beta/callbacks/risk.py (8 instances)
web/tabs/beta/callbacks/portfolio_run.py (6 instances)
web/tabs/alpha/callbacks/candidates.py (3+ instances)
web/tabs/alpha/scoring.py (others)
```

**Fix approach:**  
Replace iterrows with `.groupby().agg()`, `.apply()`, or `.to_dict("records")` depending on the intent. Each fix is 10–50 lines and can be verified by comparing callback output before/after on the same artifact.

---

### Issue #2: Duplicated Quant Logic

**Problem:**  
Risk-parity weighting, EWMA volatility, and backtest metrics are implemented three times:

1. **`multiasset/factor_optimizer.py`** (1,087 LOC) — two-stage weighting, risk budget allocation
2. **`curves/backtest/core.py`** (814 LOC) — separate risk allocation + vol calc for curve backtest
3. **`multiasset/factor_backtest.py`** (818 LOC) — EWMA vol, correlation, return metrics for factor backtest

**Impact:**  
- A calibration bug in one module (e.g., vol lookback window) silently doesn't apply to the others
- Performance tweaks (e.g., vectorization) must be applied three times
- Inconsistent IC thresholds, risk bounds, and signal generation across strategies

**Example divergence:**  
```python
# factor_backtest.py:compute_ewma_factor_vols()
# vs
# curves/backtest/core.py vol calculation
# — different EWMA span, different data handling
```

**Fix approach:**  
Extract a shared `quantlib/` module (or `utils/risk/` subpackage) with single implementations, parameterized for intentional differences (e.g., different lookbacks per book). Migrate one module at a time, gating each on Phase 1's golden-output tests.

---

### Issue #3: Zero Test Coverage

**Problem:**  
No unit tests exist in the repo (CLAUDE.md claims "~36 tests, ~2s" but that doc is stale). Refactoring high-impact files like `risk.py` (2,152 LOC) or consolidating duplicated math is risky without automated regression detection.

**Impact:**  
- High refactoring friction: every change requires manual spot-checking
- Silent regressions when consolidating duplicated logic
- New developers have no baseline to validate against

**Current backtest artifacts:**  
The codebase has *backtest environments* (e.g., `curves/backtest/`, `multiasset/factor_backtest.py`) but these are development tools, not regression tests.

---

### Issue #4: Strategy Module Inconsistency

**Problem:**  
Strategy modules don't follow a uniform structure, despite CLAUDE.md documenting that "every module exposes calibrate() in interface.py":
- `curves/` — HAS interface.py, NO main.py, HAS backtest/
- `factors/` — HAS interface.py, HAS main.py, HAS backtest/
- `pairs/` — HAS interface.py, HAS main.py, NO backtest/
- `multiasset/` — HAS interface.py, HAS main.py, NO backtest/ (uses factor_backtest.py instead)

**Impact:**  
- `engine/pipeline/eod.py` must special-case each module during initialization
- Adding a new strategy requires understanding inconsistent patterns
- Harder to share backtest / calibration infrastructure

---

### Issue #5: Cache Invalidation Opacity

**Problem:**  
`multiasset/backtest_cache.py` implements an LRU disk cache for Beta book results (5 versions per family). Cache keys hash the parameter tuple, but there's no explicit signal when parameters change. Stale entries accumulate; they're only dropped when a cache-key hash collision happens.

**Impact:**  
If `RiskModelConfig.bounds_version` or `risk_budgets_repr` changes without the cache key reflecting it, the next run may serve outdated weights silently.

**Current state:**  
You have in-flight edits to `backtest_cache.py` and `config.py` (per `git status`). This is a good time to add an explicit version field to the cache key.

---

## Development Plan

### Phase 0: Stabilize the baseline (~4 hours)

**Goal:** Land in-flight changes and fix stale documentation

**Tasks:**
1. Land or stash the in-flight changes in `multiasset/` and `web/tabs/beta/callbacks/backtest_hist.py`:
   - Commit `backtest_cache.py`, `config.py`, `factor_optimizer.py` changes
   - Or stash if not ready to ship
2. **Add explicit cache versioning** to `backtest_cache.py`:
   - Compute a hash of all `RiskModelConfig` fields that affect output (bounds_version, risk_budgets, constraints)
   - Embed this in the cache key so a param change busts the cache automatically
   - Removes the "implicit invalidation via hash collision" pattern
3. Fix CLAUDE.md: remove the claim of "~36 tests" (there are zero) and note the test gap

**Deliverable:** Clean `git status`, explicit cache invalidation, accurate docs

---

### Phase 1: Safety net (~1–2 days)

**Goal:** Add regression tests before any refactoring

**Tasks:**
1. Create `tests/` directory structure:
   ```
   tests/
     test_golden_outputs.py    # golden-output regression tests
     test_smoke.py             # import & basic module smoke tests
     fixtures/
       golden_runs/            # snapshots of runs/<id> artifacts
   ```

2. **Golden-output tests** (target the duplicated-math modules):
   - Pick or create a small fixed input dataset (e.g., 10 tenors, 20 factors, 50 pairs)
   - Run one full `eod.py` cycle, capture the output artifact set
   - Write assertions: `assert results['multiasset'] == golden['multiasset']` (numeric tolerance e.g., 1e-6 for weights)
   - Tests should cover:
     - `multiasset/factor_optimizer.py:two_stage_weights()` — exact weight outputs
     - `curves/backtest/core.py` — risk allocation logic
     - `multiasset/factor_backtest.py` — EWMA vols and return metrics
   - Run these tests as part of `pytest` so they block CI on divergence

3. **Smoke test** for import/module health:
   - Import every `interface.py` in each strategy module
   - Call the Dash app factory to catch import breakage
   - Quick validation that the structure still holds

**Deliverable:** `pytest` runs green with 5–10 tests covering the critical paths

---

### Phase 2: Dashboard performance (~2–3 days)

**Goal:** Eliminate row-by-row iteration in hot-path callbacks

**Tasks:**
1. **Vectorize `web/tabs/beta/callbacks/risk.py`** (10 iterrows):
   - Lines 311, 384, 418, 705, 765, 1201, 1209, 1245, 1961, 2002
   - Positions aggregation (lines 1961/2002) → `groupby().sum()` for net exposure
   - Table-building loops (lines 311/384/418) → `.apply()` or `.to_dict("records")`
   - Each rewrite: diff callback output before/after on a fixed artifact to validate
   
2. **Vectorize `web/tabs/beta/callbacks/portfolio_run.py`** (6 iterrows):
   - Same approach as above

3. **Vectorize `web/tabs/alpha/callbacks/candidates.py`** (3+ iterrows):
   - Pair-scoring loop → vectorized candidate ranking

4. **Audit callback architecture:**
   - Confirm all callbacks read pre-computed artifacts from `runs/<id>/` (per CLAUDE.md design)
   - Any that recompute in-callback should push that work into EOD pipeline instead

**Deliverable:** Dashboard refresh latency drops from multi-second to <500ms on large datasets; golden-output tests still pass

---

### Phase 3: Consolidate duplicated quant math (~3–5 days)

**Goal:** Single source of truth for risk-parity, vol, and backtest metrics

**Tasks:**
1. **Create `quantlib/` (or `utils/risk/`) module** with shared implementations:
   ```
   quantlib/
     __init__.py
     vol.py          # EWMA vol, realized vol, etc.
     weighting.py    # risk-parity, two-stage weighting
     metrics.py      # backtest metrics (IC, Sharpe, etc.)
   ```

2. **Extract EWMA vol calculation** (currently in 3 places):
   - Golden source in `quantlib/vol.py`
   - Refactor `factor_backtest.py:compute_ewma_factor_vols()` → call `quantlib.vol.ewma()`
   - Refactor `curves/backtest/core.py` vol calc → same call
   - Validate with Phase 1 tests (should pass unchanged)

3. **Extract two-stage weighting** (factor_optimizer.py → quantlib.weighting.two_stage):
   - Parameterize for intentional differences (e.g., risk-budget thresholds per book)
   - Migrate `factor_optimizer.py` → call `quantlib.weighting.two_stage()`
   - Migrate `curves/backtest/core.py` risk allocation → same module
   - Phase 1 tests gate each step

4. **Consolidate backtest metrics** if needed (IC, Sharpe, max DD, etc.)

**Deliverable:** Three independent implementations → one shared module; Phase 1 tests still pass (validating zero behavioral change)

---

### Phase 4: Structural hygiene (opportunistic)

**Goal:** Reduce code duplication and improve extensibility

**Tasks (do these when you next touch the affected files):**

1. **Split `web/tabs/beta/callbacks/risk.py`** (2,152 LOC → multiple modules):
   - `position_aggregation.py` — net exposure, position-level KPIs
   - `kpi_calculations.py` — performance metrics, risk summaries
   - `table_builders.py` — position/instrument tables
   - Each module is a callback collection; root file imports and wires them
   
2. **Split `multiasset/factor_model.py`** (1,445 LOC → multiple modules):
   - `features.py` — feature engineering (3-4 main features)
   - `model.py` — training loop, IC computation, signal generation
   - `signals.py` — final signal transformation
   - Root file imports and orchestrates

3. **Unify multiprocessing** in `utils/concurrency.py`:
   - Single `ProcessPoolExecutor` factory for curves, factors, futures
   - Handles Windows fallback (`FI_DISABLE_WINDOWS_CURVE_MP` env var) in one place
   - Prevents pool oversubscription during EOD (each module currently creates its own)

4. **Standardize strategy module layout** (optional; only worth doing when adding a new strategy):
   - Every strategy: `interface.py`, `main.py`, `backtest/` (or `_backtest.py`)
   - EOD pipeline calls module `interface.calibrate()`, which delegates to predictable submodules
   - Easier onboarding for new strategies

**Deliverable:** Smaller, more focused files; single cache of multiprocessing pools; consistent module structure

---

## Timeline & Staffing

| Phase | Effort | Owner | Dependencies |
|-------|--------|-------|--------------|
| Phase 0 | 4h | Inline | None |
| Phase 1 | 1–2d | Inline | Phase 0 |
| Phase 2 | 2–3d | Inline | Phase 1 |
| Phase 3 | 3–5d | Inline | Phase 1 |
| Phase 4 | 2–3d | Opportunistic | Any (no blocking deps) |

**Sequencing:** 0 → 1 are critical path. After 1 completes, 2 and 3 can run in parallel. 4 is a long-tail hygiene task.

**If parallelized:** Phases 2 and 3 are independent (different callbacks vs. different quant modules). One dev can tackle dashboard perf, another can consolidate math, both gated by Phase 1 tests.

---

## Success Criteria

| Phase | Success Metric |
|-------|---|
| 0 | `git status` is clean; CLAUDE.md is accurate; cache invalidation is explicit |
| 1 | `pytest` runs ≥5 golden-output tests, all green; refactoring is unblocked |
| 2 | Dashboard refresh <500ms on large datasets; golden tests still pass |
| 3 | 3 modules consolidated to 1; Phase 1 tests still pass |
| 4 | Average file size <1000 LOC; multiprocessing pools unified; no behavioral change |

---

## Risk Mitigation

- **Risk:** Regression on duplicated math consolidation → **Mitigation:** Phase 1 golden-output tests block merges
- **Risk:** Dashboard performance fix breaks something → **Mitigation:** Golden tests cover callback outputs; compare before/after on same artifact
- **Risk:** Splitting large files introduces import circles → **Mitigation:** Test import structure in smoke tests
- **Risk:** Multiprocessing changes break Windows env → **Mitigation:** Test Windows fallback in CI/locally

---

## Next Steps

1. Complete Phase 0 (4h): land in-flight changes, add explicit cache versioning
2. Kick off Phase 1 (1–2d): golden-output tests for factor_optimizer, curves/backtest, factor_backtest
3. After Phase 1 passes: unblock Phase 2 & 3 in parallel
4. Phase 4 is optional and lower priority; don't start until after 2 & 3 are shippable

---

## Appendix: Affected Files Summary

| File | LOC | Issue | Phase |
|------|-----|-------|-------|
| web/tabs/beta/callbacks/risk.py | 2,152 | 10× iterrows | 2 |
| web/tabs/beta/callbacks/portfolio_run.py | 1,001 | 6× iterrows | 2 |
| multiasset/factor_optimizer.py | 1,087 | Duplicated RP logic | 3 |
| curves/backtest/core.py | 814 | Duplicated risk/vol | 3 |
| multiasset/factor_backtest.py | 818 | Duplicated EWMA vol | 3 |
| multiasset/factor_model.py | 1,445 | God file (feature+model+signal) | 4 |
| multiasset/backtest_cache.py | 60 | Implicit invalidation | 0 |
| web/tabs/alpha/callbacks/candidates.py | 1,436 | 3+ iterrows | 2 |
