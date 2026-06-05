# FIEngine (bin-v4.0) — Cleanup & Refactor Plan

> Status: **PLAN ONLY** — no code changed yet. This document is the agreed checklist.
> Scope: `bin-v4.0/` — ~71.6k LOC of Python across 13 top-level packages, unified
> AtlasNexus Dash app (`web/`) plus an orchestration layer (`engine/`).

## 0. How the system is actually wired (baseline)

- **Production entry point:** `main.py` → `web/apps/atlasnexus_daily.py` (port 8080) and
  `atlasnexus_intraday.py` (8081). CLI subcommands (`eod`, `intraday`, `update-data`,
  `refresh`, `scheduler`, `curve-backtest`) route through `engine/cli.py`.
- **Unified UI:** `web/tabs/**` is the real, current dashboard surface. It imports the
  *compute internals* of each strategy package (e.g. `multiasset.factor_model`,
  `curves.refreshers.*`, `futures.backtest.*`, `pairs.manager`).
- **Per-package standalone `dashboard.py` / `main.py`:** mostly legacy `if __name__ ==
  "__main__"` dev launchers that predate the unified `web/` app. Most are no longer
  imported anywhere (see §2).

---

## 1. Redundant / removable files (low risk, do first)

| Item | Finding | Action |
|------|---------|--------|
| `logs/app.log` | **Tracked in git** and shows as modified every run | `git rm --cached`, add `logs/` to `.gitignore` |
| Generated HTML committed | `backtest/portfolio_dashboard.html`, `backtest/portfolio_dashboard_output.html`, `backtest/templates/portfolio_dashboard.html`, `derivatives/vol/vol_strategy_analysis.html`, `pairs/regression_plots.html` are regenerable outputs (some already in `.gitignore` but still tracked) | `git rm --cached` the generated ones; keep only a real template if one is needed |
| `.venv/` (681 MB) | Not committed (good) but living inside the repo dir; bloats backups/searches | Confirm it stays out of git; optionally move outside project |
| `runs/` (5.7 MB, ~280 dirs) | Gitignored ✓ but accumulating locally | Add a `make clean-runs` / retention step (keep last N) |
| `.DS_Store` | Ignored ✓ — fine | none |
| Root `requirements.txt` **vs** `requirements/base.txt` | **Conflict:** root pins `dash==4.1.0`, `pandas==3.0.2`, `numpy==2.4.4`; base says `dash>=2.14.0`, `pandas>=1.3.0`. Two sources of truth | Pick one. Recommend `requirements/{base,development,production}.txt` as canonical; delete root `requirements.txt` or make it `-r requirements/production.txt` |

## 2. Redundant / legacy *code* (keep standalone for independent testing)

- **Per-module `dashboard.py` / `main.py` → KEEP** for standalone dev/test entry points.
  These are used for independent testing and debugging of individual strategy modules.
  Keep: `backtest/`, `derivatives/`, `factors/`, `futures/`, and others.
- **Still imported in production — keep:** `pairs/dashboard.py`, `pairs/main.py`,
  `multiasset/main.py`, `multiasset/layout.py`, `surface/{callbacks,layout}.py`.
- **`interface.py` (6 files) → KEEP ALL.** All 6 are actively used: 5 as EOD pipeline
  adapters (`engine/pipeline/eod.py` calls `calibrate(cfg, store)` on each), 1
  (`curves/interface.py`) by the intraday refresh pipeline. These are well-designed.
- **Per-module launchers:** `factors/START_FACTOR_DASHBOARD.bat`,
  `backtest/START_PORTFOLIO_SERVER.bat` — keep with their dashboards.
  Keep the top-level `START.sh` / `START_mac.command` / `START_win.bat` in any case.
- **Removed:** `web/tabs/inspect_data2.py` — misplaced debug script, no importers. ✓
- **Pending decision:** `utils/migrate_cvobj.py` + `utils/migrate_pkl.py` — one-shot
  pickle migration scripts. Remove once migrations are confirmed done.

> ⚠️ Each removal in this section must be preceded by a repo-wide import grep + one app
> smoke-run. Do them in a dedicated branch, one package at a time.

## 3. Duplicated logic (audit + design decision)

**Conclusion: Keep architectures separate.**

- **Backtest engines (6+ implementations):** `curves/backtest/`, `futures/backtest/`,
  `factors/backtest/`, `multiasset/factor_backtest.py`, `derivatives/vol/backtest.py`,
  `web/tabs/alpha/backtest/`. ✓ **KEEP SEPARATE — different instruments, different logic.**
  - Curves/bonds: fixed-income math, duration, convexity, carry decomposition
  - Futures: high-frequency signals, momentum/trend, intraday re-hedge logic
  - Factors: cross-sectional rank/decay, IC decay, exposure dynamics
  - Each domain's backtest logic is fundamentally different; consolidating would be over-engineering.
  - **Better approach (Step 4):** Define a **consistent output format** (`backtest_result.json`)
    so UI can read results uniformly without reimplementing metrics on load.

- **Performance metrics:** `futures/backtest/metrics.py` (portfolio Sharpe/Calmar) vs
  `factors/analysis/metrics.py` (factor IC/IR) are **fundamentally different.**
  No consolidation needed. ✓

- **`portfolio.py` ×5, `plot.py` ×5, `layout.py` ×5:** ✓ **KEEP SEPARATE — domain-specific.**
  No consolidation value without violating separation of concerns.

## 4. Architecture improvements (high-value, no consolidation)

1. **Finish the `engine/` artifact-first vision** (per `engine/README.md`). Key insight: each
   backtest engine should write a **standardized result format** (e.g., `backtest_result.json`
   with common fields: `returns`, `pnl`, `metrics.sharpe`, `metrics.calmar`, `metrics.max_dd`).
   Then `web/` reads artifacts instead of reimplementing metrics in callbacks.
   - Pipeline writes: `runs/<run_id>/{signals,targets,backtest_results,risk,tickets}`
   - UI reads and renders without heavy compute
   - This removes most latency from the request path without forcing backtest engines to unify.

2. **Standardize pipeline outputs.** Define schema for:
   - Backtest results (curves, futures, factors, multiasset)
   - Risk snapshots (VaR, Greeks, factor exposures)
   - Signal snapshots (factor signals, pair signals, regime)
   - This lets UI be data-driven, not compute-driven.

3. **One UI surface.** `web/` is the only production UI. Per-package dashboards/mains remain
   as standalone dev/test tools (as you chose in §2).

4. **Separate the intraday "clock"** (per engine README): distinct data cache, risk limits,
   and refresh scheduler from EOD.

## 5. Performance opportunities

- **Move compute out of Dash callbacks** → precomputed artifacts (§4.1). Biggest latency win.
- **Cache discipline:** there's already `diskcache`/`cache.db`; ensure expensive curve/factor
  computations are memoized with explicit keys + invalidation, not recomputed per tab load.
- **Vectorize / parallelize backtests:** the consolidated engine (§3) should use vectorized
  pandas/numpy and reuse the existing multiprocessing pattern from `curves/backtest/workers.py`.
- **Lazy imports:** `main.py` already lazy-imports heavy apps; extend this so starting one
  console doesn't import every strategy package.

## 6. Testing & tooling (currently absent)

- **There are effectively zero unit tests.** Add `tests/` with, at minimum, golden-master
  tests for: metrics math, one backtest end-to-end, curve calibration, factor model output.
- Add `ruff` + `black` config and a pre-commit hook; the 168 TODO markers and inconsistent
  layout suggest no linter is enforced.
- Add a top-level `README.md` (none exists) documenting the entry points in §0.

---

## Suggested execution order (each = its own PR)

### Completed ✓
1. **Step 1 — Hygiene** (§1): untrack logs/HTML, fix `.gitignore`, consolidate requirements. ✓
2. **Step 2 — Dead-code sweep** (§2): remove unused files, keep standalone dashboards for testing. ✓

### Recommended next
3. **Step 3 — Top-level README** (§6 partial): document entry points, CLI, package roles. **Fast, high-signal.**
4. **Step 4 — Engine artifact-first design** (§4): define output schema (backtest_results.json, risk_snapshot.json, etc.), have pipelines write artifacts, update UI to read them. **Strategic win — moves compute out of callbacks.**
5. **Step 5 — Testing baseline** (§6 partial): add pytest fixtures for golden-master backtest, risk snapshot, metrics. **Protects refactoring.**
6. **Step 6 — Performance tuning** (§5): caching/memoization, vectorization, lazy imports.

**Key decision:** Do you want to tackle **Step 3 (README)** next for clarity, or jump to **Step 4 (artifact-first)** for the architectural win?
