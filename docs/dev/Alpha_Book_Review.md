# Alpha Book Tab — Code & Methodology Review

*Review date: 2026-06-12. Scope: `web/tabs/alpha/` (data, scoring, layouts, callbacks,
backtest engines), the legacy subtabs mounted under the Alpha Book
(`web/tabs/atlas_fi_tabs.py` Spread/Pairs, `web/tabs/atlas_volatility_tabs.py`), and
their wiring in `web/apps/atlasnexus_daily.py:383-402`. Companion to
`Beta_Book_Review.md` (2026-06-11).*

*Status pass: 2026-07-03. Every item below re-verified against the current tree.
Resolved items are marked ✅ with the commit-era evidence; open items keep their
original numbering with refreshed file/line references. Net: §2.2 and all of Phase 3
are done; §2.1 (the highest-priority item) is still unresolved and the sign
mismatch is confirmed unchanged. One new finding: **there is no `tests/` directory
in this tree** (`pytest` in CLAUDE.md currently has nothing to run), which blocks
"add a unit test" asks in Phase 1 until test scaffolding is recreated.*

---

## 1. Overall Assessment

The Alpha Book is structurally **healthier than the Beta Book**: cross-tab state lives
in `dcc.Store` components instead of module globals, the backtest engines
(`backtest/engine_mr.py`, `engine_trend.py`) are separated from the Dash callbacks, and
the carry/borrow-cost model is genuinely sophisticated — direction-aware borrow costs,
per-instrument carry+roll time series, financing adjustments for DV01-hedged tenor
trades. The workflow (Scan → Correlation → Curate → Optimize → Backtest → Summary) is
coherent and the regime auto-detection UX is a nice touch.

The main weaknesses (2026-07-03 status in brackets):

1. **[⚠️ still open] The TenorSpread financing adjustment is implemented twice with
   opposite signs** (Candidates scan vs Backtest) — the carry shown when you pick a
   trade and the carry used when you backtest it disagree. Confirmed unchanged and
   remains the top-priority fix.
2. **[✅ fixed] The curated-table edit/delete callbacks index the wrong rows** once a
   saved position filters the rendered list — now keyed by `{stype, inst}`.
3. **[⚠️ still open] The portfolio backtest's capital and transaction-cost inputs are
   dead** — parsed and never used.
4. **[✅ fixed] The data layer re-reads and re-normalizes whole pickles on every call**,
   and `_get_duration_mult` triggers a full pickle load per table row — `data/io.py`
   now has an mtime-keyed cache and loops that used to reload per-row now cache
   per-spread-type.
5. **[⚠️ still open] Three Sharpe definitions and multiple risk-parity approaches**
   coexist across the alpha and beta books — results are not comparable between tabs
   (risk-parity unit-mixing was partially addressed, §6.4; Sharpe was not touched).

The Alpha Book also has a quiet identity question: half its subtabs (Spread, Pairs,
Volatility) are legacy layouts living outside `web/tabs/alpha/`, with their own data
path (`web.core.graphs`) and styling. Worth deciding whether they are part of the alpha
workflow (then migrate them in) or a separate explorer (then label them so).

---

## 2. Correctness Bugs (fix first)

### 2.1 TenorSpread financing adjustment: two implementations, opposite signs — ⚠️ STILL OPEN
*(2026-07-03: unresolved, unchanged in substance. Highest-priority item.)*

The same economic adjustment (financing of the DV01-hedged long leg at FR007) still
exists in two places with conflicting formulas — `data.py` was split into a package
since the original review, so file/line references have moved, but the bug itself is
identical:

- Candidates scan — [candidates.py:404,417](web/tabs/alpha/callbacks/candidates.py#L404):
  `_fin_adj = 0.5 × (FR007_bp − y_long_bp)`, applied to the raw (un-negated) carry:
  `_cr_annual_adjusted = _cr_ts_annual + _fin_adj − _bc_adj × 4.0`.
- Backtest — [backtest_tab.py:403-411](web/tabs/alpha/callbacks/backtest_tab.py#L403-L411):
  `fin_adj_annual_pct = (1 − 0.5) × (y_long_pct − fr007_pct)` — the **opposite sign**
  from candidates — applied to carry that **was already negated** by the yield-based
  flip a few lines above (`backtest_tab.py:378-381`). The two sign flips compound, so
  the backtest's adjusted carry ends up an exact negative of what candidates computes
  for the same instrument/direction.

Both sites still hardcode the 2:1 hedge ratio (`0.5`) and the 137 bp FR007 fallback
independently, and neither has a shared `tenor_spread_carry_adjustment()` helper. No
test pins the BUY/SELL sign convention — and there is currently no `tests/` directory
in this tree to hold one (see status note at top). Recommendation unchanged: extract
one function into `web/tabs/alpha/data/`, write down the sign convention (BUY
steepener = short the long-tenor bond ⇒ …), make both callers use it, and add a
regression test once test scaffolding exists.

### 2.2 Curated table edits/deletes hit the wrong row after filtering — ✅ FIXED
*(2026-07-03: resolved.)* The pattern-matching ids for curated rows are now keyed by
`{'stype': spread_type, 'inst': instrument}` instead of positional index — see
[candidates.py:1237](web/tabs/alpha/callbacks/candidates.py#L1237) (regime dropdown),
[candidates.py:1247](web/tabs/alpha/callbacks/candidates.py#L1247) (direction dropdown),
and [candidates.py:1264](web/tabs/alpha/callbacks/candidates.py#L1264) (delete button),
matched by `Input({'type': 'curated-del', 'stype': ALL, 'inst': ALL}, ...)` etc. at
[candidates.py:951](web/tabs/alpha/callbacks/candidates.py#L951) and
[:1025-1026](web/tabs/alpha/callbacks/candidates.py#L1025-L1026). Edits/deletes now hit
the correct entry regardless of what's filtered out of the rendered table.

### 2.3 Portfolio backtest ignores its capital and transaction-cost inputs — ⚠️ STILL OPEN
*(2026-07-03: unresolved.)* `run_portfolio_backtest` still parses `capital` and
`txn_cost_bp` ([backtest_tab.py:607-608](web/tabs/alpha/callbacks/backtest_tab.py#L607-L608))
and never references either again afterward. The UI still advertises an
initial-capital and per-trade cost model; the result is still cost-free PnL in bp.
Either wire them in or remove the inputs.

### 2.4 The high-correlation warning can't see high correlations — ⚠️ STILL OPEN
*(2026-07-03: unresolved as originally described, though a related safeguard now
exists downstream.)* `check_correlation` still ranks the **10 lowest** |corr| pairs and
warns about pairs in that bottom-10 exceeding `max_corr`
([candidates.py:825-826](web/tabs/alpha/callbacks/candidates.py#L825-L826)) — still
structurally close to dead. Mitigating: `select_diverse_instruments`
([candidates.py:830-833](web/tabs/alpha/callbacks/candidates.py#L830-L833)) now enforces
`max_abs_corr` when building the curated list, so highly correlated pairs are excluded
from curation regardless of what the warning says — but the warning panel itself is
still computed on the wrong subset and should be fixed or removed to avoid misleading
the user reading it.

### 2.5 `trade_style` does nothing in the MR engine — ⚠️ STILL OPEN
*(2026-07-03: unresolved, unchanged.)* In `run_spread_backtest` the
`if trade_style == 'mr':` entry block and its `else:` branch remain character-identical
([engine_mr.py:164-185](web/tabs/alpha/backtest/engine_mr.py#L164-L185)).

### 2.6 Smaller verified items — mixed
- Add-trade dedup still ignores spread type: `any(e['instrument'] == instrument …)`
  ([candidates.py:976](web/tabs/alpha/callbacks/candidates.py#L976)) — ⚠️ still open.
- Date-index alignment by `astype(str)` still present at use sites
  ([scoring.py:234-235](web/tabs/alpha/scoring.py#L234-L235),
  [candidates.py:791](web/tabs/alpha/callbacks/candidates.py#L791)) — ⚠️ still open.
  (`data.py` was split into `web/tabs/alpha/data/`; the mtime-cached loader lives in
  `data/io.py` now, see §5, but it doesn't normalize the index type.)
- Dead code still present with zero callers (re-verified by grep across `web/`,
  `curves/`, `futures/`): `risk_parity_weights` (iterative solver, `scoring.py:158`),
  `compute_candidate_scores` (`scoring.py:373`), `compute_unified_edge_vol_score`
  (`scoring.py:590`), `select_diversified_trades` (`scoring.py:734`),
  `DIVERSIFIED_TRADE_RECOMMENDATIONS` (`data/constants.py:127`) — ⚠️ still open, delete
  or wire in.
  - `_TENOR_RATIO = 2.0` is no longer dead — it's now read at
    [candidates.py:386](web/tabs/alpha/callbacks/candidates.py#L386) as part of the
    (still-buggy, §2.1) financing calc.

---

## 3. Workflow

**What works:** the Candidates → Portfolio → Backtest pipeline maps cleanly onto how an
RV book is actually run (screen, de-correlate, size, validate); `dcc.Store` keeps state
per-session instead of per-process (the beta tab should copy this); saved positions
round-trip through `alpha_book_positions.parquet` so the book survives restarts; the
Backtest tab pulling the persisted Summary snapshot (`_load_portfolio_snapshot`) keeps
Backtest and Summary consistent.

**Issues:**

- **Split-brain subtabs.** *(2026-07-03: unchanged.)* Spread, Pairs and Volatility are
  still mounted under the Alpha Book (`an-alpha-subtabs`, confirmed at
  [atlasnexus_daily.py:498](web/apps/atlasnexus_daily.py#L498) and
  [:1107](web/apps/atlasnexus_daily.py#L1107)) but still live in
  `web/tabs/atlas_fi_tabs.py` / `atlas_volatility_tabs.py`
  ([imports at atlasnexus_daily.py:45,73](web/apps/atlasnexus_daily.py#L45)), render
  from a different data path and don't share the alpha stores. No "add to candidates"
  bridge exists (grep confirms zero hits for it in `atlas_fi_tabs.py`).
- **Cross-book coupling via parquet.** *(2026-07-03: unchanged.)* The Beta tab's
  `risk.py` still reads *and rewrites* `summary_alpha_portfolio.parquet` and
  `alpha_book_positions.parquet` directly — confirmed at
  [risk.py:132](web/tabs/beta/callbacks/risk.py#L132),
  [:137-152](web/tabs/beta/callbacks/risk.py#L137-L152),
  [:307-337](web/tabs/beta/callbacks/risk.py#L307-L337),
  [:701-753](web/tabs/beta/callbacks/risk.py#L701-L753), and
  [:1999-2001](web/tabs/beta/callbacks/risk.py#L1999-L2001). Two tabs owning one file
  with different schemas is how the beta summary-file bug happened; give the file one
  owner and an explicit API.
- **Weights are applied retroactively in the portfolio backtest.** Today's optimized
  weights (from today's scores) are used to weight trade equity curves over the past
  year — a look-ahead structure. Fine as a "how would the current book have done"
  sanity view, but label it as such; it is not a strategy backtest.
- **`_REGIME_LOOKUP_CACHE` never invalidates** — ✅ FIXED. *(2026-07-03)* The cache now
  tracks the snapshot pickle's mtime (`_REGIME_CACHE_MTIME`,
  [candidates.py:40-53](web/tabs/alpha/callbacks/candidates.py#L40-L53)) and rebuilds
  when the file changes, instead of only invalidating on process restart.

---

## 4. Code Structure

**What works:** clean module split (`data` / `scoring` / `layouts` / `callbacks/*` /
`backtest/*`); engines take plain Series + scalars and return dicts — easily testable;
`_carry.py` shared by both engines instead of duplicated.

**Issues:**

- **Three near-identical dispatch ladders — still open.** *(2026-07-03: `data.py` was
  refactored into a `data/` package since the original review, but the ladders
  themselves weren't collapsed.)* `load_spread_data`
  ([data/loaders.py:14](web/tabs/alpha/data/loaders.py#L14)),
  `load_spread_timeseries` ([data/loaders.py:223](web/tabs/alpha/data/loaders.py#L223)),
  `load_realtime_spreads` ([data/loaders.py:385](web/tabs/alpha/data/loaders.py#L385))
  each still re-enumerate every spread type with its pickle path and nested key. One
  improvement: `load_spread_data` now tries a centralized
  `curves.refreshers.alpha.get_alpha_spread_table()` first
  ([data/loaders.py:19-29](web/tabs/alpha/data/loaders.py#L19-L29)) before falling back
  to the per-type ladder — a step toward a registry but not the registry itself.
- **`scan_candidates` has grown, not shrunk.** *(2026-07-03)* Now ~380 lines in
  `candidates.py` (file is 1277 lines total, up from the review-era size), still mixing
  data load, the buggy carry adjustment (§2.1), breakeven filtering, and table styling.
- **Duplicated `_upsert_snapshot` — still open**, confirmed unchanged at
  [alpha/callbacks/portfolio.py:30](web/tabs/alpha/callbacks/portfolio.py#L30) and
  [beta/callbacks/_common.py:36](web/tabs/beta/callbacks/_common.py#L36).
  **THEME duplication has gotten worse**, not better: it's now defined independently
  in 7 files (`data/constants.py:14` for alpha, `beta/data.py:55`,
  `atlas_trend_tabs.py:20`, `atlas_market_data_tab.py:31`, `atlas_pricer_tab.py:37`,
  `atlas_factor_backtest_tabs.py:24`, `atlas_volatility_tabs.py:32`), up from the 2
  copies noted in the original review.
- **Magic numbers without a home — still open**, unchanged: FR007 fallback `137.0` bp
  still appears independently in both §2.1 sites; hedge ratio `0.5`/`_TENOR_RATIO = 2.0`
  ([candidates.py:386](web/tabs/alpha/callbacks/candidates.py#L386)); MR lookback `120`
  ([engine_mr.py:40](web/tabs/alpha/backtest/engine_mr.py#L40)). None moved to
  `settings`.
- `except Exception: pass` is still widespread — 22 occurrences across 8 files in
  `web/tabs/alpha/` as of 2026-07-03 (candidates.py, backtest_tab.py, scoring.py,
  data/loaders.py, data/duration.py, data/legs.py, seasonal.py, backtest/_carry.py).
  `print` instead of `logging` still used throughout.

---

## 5. Performance — ✅ Phase 3 largely resolved (2026-07-03)

- **mtime caching — ✅ FIXED.** `data.py` is now a package
  (`web/tabs/alpha/data/`), and [data/io.py](web/tabs/alpha/data/io.py) implements
  `_load_pickle_cached` keyed by file mtime
  ([data/io.py:56-90](web/tabs/alpha/data/io.py#L56-L90)), adopting the pattern from
  `atlas_fi_tabs.py`. `_load_pickle_safe` now delegates to it
  ([data/io.py:94-96](web/tabs/alpha/data/io.py#L94-L96)), so repeated calls within a
  cache window no longer re-read or re-normalize the pickle.
- **`_get_duration_mult` per-row pickle loads — ✅ effectively resolved** by the mtime
  cache above; the call path is unchanged (`data/duration.py`,
  `portfolio.py:289-292`-equivalent) but each underlying `load_spread_data` call is now
  cache-served rather than a fresh read.
- **Repeated full-pickle loads inside loops — ✅ FIXED.** `check_correlation` now
  builds a `_ts_cache: dict[str, pd.DataFrame | None]` keyed by spread type and loads
  each type once before iterating candidate rows
  ([candidates.py:775-787](web/tabs/alpha/callbacks/candidates.py#L775-L787)), matching
  the pattern `_compute_risk_parity_weights` already used.
- `iterrows()` in the scan — still present, still fine at current row counts, no action
  needed.
- The engines' per-day Python loops — unchanged, still acceptable. No action needed.

---

## 6. Methodology

**Strengths worth keeping:** the carry framework (per-instrument daily 3m carry+roll,
direction-dependent borrow costs from `BondConfig.BORROW_COST` buckets, financing
adjustment for hedged tenor trades, BondSwap direction asymmetry); the carry-adjusted
composite entry signal `z − carry_σ` so MR trades don't fight negative carry; min-hold
with always-on stops; equity marked-to-market daily including open-trade carry; regime
auto-detection feeding the default trade style with an edge-sign tiebreaker.

**Concerns:**

1. **No execution friction anywhere — ⚠️ still open.** *(2026-07-03)* Entries and exits
   still fill at the signal-day close; no bid/offer, no slippage; the portfolio cost
   input is still dead (§2.3, confirmed unchanged).
2. **Non-standard Sharpe — ⚠️ still open, confirmed all three definitions coexist.**
   `(pnls.mean()/pnls.std()) × sqrt(min(n_trades, 20))` in
   [engine_mr.py:271](web/tabs/alpha/backtest/engine_mr.py#L271) and identically in
   [engine_trend.py:267](web/tabs/alpha/backtest/engine_trend.py#L267); the portfolio
   backtest uses daily `× sqrt(252)`
   ([backtest_tab.py:758](web/tabs/alpha/callbacks/backtest_tab.py#L758)); the vol
   subtab has its own daily `sqrt(252)` variant too
   ([atlas_volatility_tabs.py:239](web/tabs/atlas_volatility_tabs.py#L239)). Still no
   shared metrics module.
3. **MR statistics use a single 120-day window — ⚠️ still open, unchanged**
   ([engine_mr.py:40](web/tabs/alpha/backtest/engine_mr.py#L40)), not exposed in the UI.
4. **Risk parity on raw bp changes mixes units — 🟡 partially addressed, different
   approach than recommended.** *(2026-07-03)* `_compute_risk_parity_weights` now
   standardizes each spread series by its own std before computing the covariance
   matrix ([scoring.py:312-324](web/tabs/alpha/scoring.py#L312-L324)) — this fixes the
   unit-scale domination the review flagged (raw bp vs raw CNY-point series no longer
   let the larger-unit series dominate), but via correlation-structure ERC rather than
   the DV01-scaled return series originally suggested; duration-scaled risk is still
   not explicitly represented. **The post-clip rescale issue is fixed**: risk
   contributions are now recomputed from the final clipped-and-renormalized weights
   ([scoring.py:362-364](web/tabs/alpha/scoring.py#L362-L364):
   `risk_contrib = _risk_contribution(weights_array, cov)` runs after the clip/rescale,
   not before).
5. **Portfolio aggregation ignores entry timing — ⚠️ still open, unchanged.** No
   "sanity view" label was added to the panel title.
6. **Trade-style taxonomy is stringly typed — ⚠️ still open.** `_style_to_regime`
   ([candidates.py:56](web/tabs/alpha/callbacks/candidates.py#L56)) plus two separate
   inline `_style_to_regime_label` closures
   ([candidates.py:499](web/tabs/alpha/callbacks/candidates.py#L499),
   [portfolio.py:436](web/tabs/alpha/callbacks/portfolio.py#L436)) still exist
   independently. No enum.

---

## 7. Prioritised Improvement Plan

*Status legend as of 2026-07-03: ✅ done · 🟡 partial/different approach · ⚠️ not started.*

### Phase 1 — Correctness (small diffs)
1. ⚠️ Reconcile the TenorSpread financing adjustment into one shared function with a
   written sign convention; add a unit test pinning the BUY/SELL carry signs (§2.1).
   **Still the top-priority open item** — confirmed sign mismatch unchanged, and there
   is no `tests/` directory to hold the regression test yet.
2. ✅ Key the curated-table pattern-matching ids by `spread_type|instrument`, not
   position (§2.2). Done — ids now use `{'stype', 'inst'}`.
3. ⚠️ Wire up or remove the portfolio backtest capital / txn-cost inputs (§2.3).
4. ⚠️ Fix the high-correlation warning to scan all pairs (§2.4). Mitigated indirectly
   by `select_diverse_instruments` enforcing `max_abs_corr` at curation time, but the
   warning panel itself is unchanged.
5. ⚠️ Resolve or remove the dead `trade_style` branch in `run_spread_backtest` (§2.5).
6. ⚠️ Delete verified dead code in `scoring.py` / `data/` (§2.6). All four dead
   functions and `DIVERSIFIED_TRADE_RECOMMENDATIONS` still present with zero callers.

### Phase 2 — One source of truth
7. ⚠️ Spread-source registry replacing the three dispatch ladders in `data/loaders.py`.
   Not done, though `load_spread_data` now tries a centralized
   `get_alpha_spread_table()` before falling back to the ladder.
8. ⚠️ Shared metrics module (one Sharpe/MDD definition). Still three+ definitions
   coexist (confirmed: engine_mr, engine_trend, backtest_tab, atlas_volatility_tabs).
9. ⚠️ Move `_upsert_snapshot` and THEME to one shared module; single owner for the
   alpha parquets. **Regressed** — THEME is now duplicated across 7 files (was 2);
   `_upsert_snapshot` duplication and the beta `risk.py` cross-writes are unchanged.
10. ⚠️ One style/regime enum + normalizer. Still ≥3 independent normalizers.
11. ⚠️ Constants (duration proxy, FR007 fallback, hedge ratio, MR lookback, clip
    levels) into settings. Still inline and independently duplicated (§2.1).

### Phase 3 — Performance & state — ✅ done
12. ✅ mtime-cached pickle loader — implemented in `web/tabs/alpha/data/io.py`
    (`_load_pickle_cached`); `_REGIME_LOOKUP_CACHE` now invalidates on snapshot mtime
    (`candidates.py:40-53`).
13. ✅ Hoisted per-row pickle loads out of loops — `check_correlation` now caches by
    spread type (`candidates.py:775-787`); duration-mult lookups benefit from the
    mtime cache in #12.

### Phase 4 — Methodology
14. ⚠️ Per-spread-type transaction costs + optional next-day fills in both engines.
    Not started.
15. 🟡 Risk parity: unit-mixing addressed via per-column std-normalization before
    covariance (not the originally-suggested DV01 scaling); post-clip risk
    contributions **are now correctly recomputed** (`scoring.py:362-364`).
16. ⚠️ Expose the MR lookback; unify snapshot z and backtest z. Not started.
17. ⚠️ Relabel the portfolio backtest as a current-book sanity view, or rebuild as a
    true walk-forward. Not started.
18. ⚠️ Connect the Spread explorer subtab to the Candidates workflow. Not started — no
    "add to candidates" affordance exists in `atlas_fi_tabs.py`.

### New finding (2026-07-03)
19. ⚠️ **No `tests/` directory exists in this tree.** CLAUDE.md documents `pytest`
    running ~36 tests in ~2s, but there is currently nothing for it to run. This
    blocks item #1's "add a unit test" ask and likely affects other modules beyond
    the Alpha Book — worth a separate look at whether test scaffolding was removed
    or never committed to this branch.

---

## 8. Regime Detection & Trend Signal Model Review (added 2026-07-03)

*Scope: the regime classifier
([curves/calibration/regime.py](curves/calibration/regime.py) rule-based ensemble;
[futures/backtest/regime.py](futures/backtest/regime.py) HMM variant + shared helpers),
the directional-change trend signal
([curves/calibration/trend.py](curves/calibration/trend.py)), the trend backtest engine
([engine_trend.py](web/tabs/alpha/backtest/engine_trend.py)), and their wiring through
the EOD snapshot ([alpha_scoring.py](curves/refreshers/alpha_scoring.py)) and the UI
([backtest_tab.py:110-230](web/tabs/alpha/callbacks/backtest_tab.py#L110)). Evaluated
against the intended trading frequency of **~1 week to 1 month holding periods**
(mid-low frequency).*

**What's sound:** the overall architecture is right for this horizon — a cheap,
interpretable 4-indicator voting ensemble (ER / Hurst / VR / autocorr) on 60-day
windows for style selection, a trend model that requires triple confirmation
(DC trend state + vol-normalized momentum + carry filter), trailing stops in vol
units, `min_hold=7` with always-on stops, and the "uncertain → carry-edge tiebreak"
default in the UI. `_HORIZON_DAYS = 30` and the 20d momentum / 60d vol windows are
consistent with a 1w–1m book. The problems are in the calibration and the wiring.

### 8.1 Verified bugs (fix first)

1. **The regime-conditional score boost is dead — key mismatch.**
   `compute_trend_signal` returns its state under the key `"trend_state"`
   ([trend.py:193](curves/calibration/trend.py#L193)), but the snapshot enrichment
   reads `ts.get("state", 0.0)`
   ([alpha_scoring.py:145](curves/refreshers/alpha_scoring.py#L145)) — so the
   `trend_state` column is **always 0.0**. Downstream in
   `_add_unified_score_preview`, the 1.3× boost for trend-agreeing trending
   candidates and the 0.6× penalty for trend-opposing ones
   ([alpha_scoring.py:387-391](curves/refreshers/alpha_scoring.py#L387-L391)) can
   never fire (`trend_agrees` is always False; the penalty requires
   `trend_st.ne(0)`). Only the 0.5× uncertain-regime penalty works. One-character
   class of fix; add a test.

2. **The variance-ratio vote is mis-scaled and votes "trending" almost always.**
   [regime.py:73-77](curves/calibration/regime.py#L73-L77) computes
   `vr = short_var × (window/short_w) / long_var` where both variances are of
   **1-day** changes over different sample windows. For stationary vol,
   `short_var ≈ long_var`, so `vr ≈ window/short_w = 4.0` — against thresholds of
   1.05/0.95. The MR vote would require recent 15d variance below ~24% of the 60d
   variance; in practice this indicator is a permanent +1 trending vote. A proper
   Lo–MacKinlay VR compares the variance of *q-day* changes to q× the variance of
   1-day changes: `s.diff(q).var() / (q × s.diff().var())` — no extra scale factor.
   The same mis-scaling exists in the shared helper
   [`_calculate_variance_ratio`](futures/backtest/regime.py#L95-L119) used by the
   futures HMM features, and in the rolling variant
   ([regime.py:144-149](curves/calibration/regime.py#L144-L149)).

3. **The Hurst estimate is single-scale R/S with no finite-sample correction.**
   [`_estimate_hurst`](futures/backtest/regime.py#L17-L51) returns
   `log(R/S)/log(n)` at a single n instead of regressing log(R/S) on log(n) across
   sub-sample sizes. For a pure random walk at n=60 the expected value of this
   statistic is ≈0.55–0.58, not 0.5 — i.e. sitting at/above the 0.55 "trending"
   threshold, while the 0.45 MR threshold is far below the finite-sample null.
   Combined with bug #2, **two of the four votes are structurally biased toward
   "trending" for a memoryless series**, while the ER vote is biased the other way
   (a random walk's expected ER at n=60 is ≈0.13, below the 0.20 MR threshold), and
   the ±0.05 autocorr thresholds are well inside the null's ±1σ ≈ 0.13 noise band.
   Net effect: regime labels are largely artifacts of per-indicator bias, and the
   ensemble plausibly labels random walks "trending" — which then auto-selects the
   trend engine in the UI. Fix: Monte-Carlo the 60-day random-walk null for each
   indicator and set thresholds at its quantiles (or use Anis–Lloyd-corrected R/S /
   a proper VR z-stat), and pin with a test that a simulated random walk votes ≈0.

4. **The trend engine uses relative-threshold DC on inverted, zero-crossing
   series.** `_dc_trend_state` imports the *relative* `generate`
   ([engine_trend.py:17,30](web/tabs/alpha/backtest/engine_trend.py#L17)) —
   `(price − ext)/ext ≥ θ` — although `generate_absolute` was written precisely
   because "spread series can hover near zero where a relative threshold is
   undefined or unstable" ([trend.py:64-79](curves/calibration/trend.py#L64-L79)).
   Both backtest callers pass the **negated** series for yield-based spreads
   ([backtest_tab.py:445](web/tabs/alpha/callbacks/backtest_tab.py#L445),
   [:673](web/tabs/alpha/callbacks/backtest_tab.py#L673)), so `ext` is typically
   negative (flipping the inequality semantics) and near-zero levels make θ=0.02
   hypersensitive (2% of a −0.4 level = 0.8 bp). Meanwhile the snapshot signal path
   `compute_trend_signal` uses `generate_absolute` with θ interpreted as **2 bp**
   ([trend.py:183](curves/calibration/trend.py#L183)) — so the trend state shown at
   scan time and the trend state the backtest trades come from two different DC
   definitions with incompatible θ units. Same split-brain pattern as §2.1. Fix:
   engine uses `generate_absolute`; make θ per-spread-type in vol units (e.g.
   θ = k × 60d daily σ) so DC event frequency matches the 1w–1m target.

5. **The `carry_buffer` gate blocks all long entries on inverted spreads.** Entry
   requires `px >= carry_buffer` (default 0.0)
   ([engine_trend.py:178](web/tabs/alpha/backtest/engine_trend.py#L178)), using the
   spread *level* as a carry proxy. After the yield-based inversion, a
   typically-positive raw spread (e.g. 10s30s ≈ +40 bp) is always negative in
   engine space → the long side (narrowing bet) can **never** enter; the engine
   only ever shorts. The level-as-carry assumption only holds on the raw,
   non-inverted series. The engine already receives the real `carry_roll_ts` —
   gate on that instead (or apply the buffer in raw-spread space with direction
   awareness).

6. **Signed `regime_score` is stored as `regime_confidence`.**
   [alpha_scoring.py:134](curves/refreshers/alpha_scoring.py#L134) stores
   `regime_score` (∈ [−1, +1]) into the `regime_confidence` column, ignoring the
   `regime_confidence = abs(score)` that `classify()` already provides — so
   mean-reverting instruments carry *negative* "confidence" into the snapshot and
   the UI badge. Cosmetic but confusing; pick one.

### 8.2 Horizon-fit and methodology concerns (1w–1m frequency)

7. **Regime is snapshot-only; backtests never switch styles.** The rolling
   classifier `compute_regime_features_series` / `classify_series`
   ([regime.py:118-208](curves/calibration/regime.py#L118-L208)) is fully
   implemented and has **zero callers**. Today's regime label selects one engine
   which then trades the entire lookback window in that single style — the same
   retroactive structure as the portfolio weights (§6.5). For a 1w–1m book the
   meaningful validation is walk-forward regime switching: at each date, classify
   with data-to-date and route to the MR or trend rule accordingly. The building
   block already exists; wire it into the engines (or at least offer it as a
   third "adaptive" style in the backtest UI).

8. **No regime hysteresis.** The lightweight vote flips the label the moment the
   score crosses ±2 — no dwell time, no confirmation. At this trading frequency a
   style flip is a trade decision (unwind MR book, enter trend book), so
   day-to-day label whipsaw between EOD runs is costly. The HMM path already has
   `predict_with_confidence` smoothing
   ([futures/backtest/regime.py:292-345](futures/backtest/regime.py#L292-L345));
   the rule-based path used by the alpha book has none. Add persistence (e.g.
   require 2–3 consecutive days at the new label, or |vote| ≥ 3 to switch).

9. **Three different stat windows describe the same trade.** Candidate z is
   regression-based over 30d (`_REG_LOOKBACK_DAYS`,
   [alpha_snapshot.py:38](curves/refreshers/alpha_snapshot.py#L38)); the regime is
   classified over 60d (`DEFAULT_REGIME_WINDOW`); the MR engine trades a 120d z
   ([engine_mr.py:40](web/tabs/alpha/backtest/engine_mr.py#L40), §6.3). For 5–21
   day holds, pick one primary window (~60d, i.e. ≥2–3× max holding period) or
   expose the triple as a single settings block so scan, regime, and backtest stay
   consistent.

10. **No validation that the regime label earns its keep.** There is no
    diagnostic comparing engine-vs-regime performance (e.g. each instrument
    backtested under both engines, bucketed by regime label). Given bugs #2/#3
    bias labels toward "trending", a small "regime accuracy" panel — MR-engine vs
    trend-engine PnL conditioned on the label, plus label persistence stats —
    would show whether the classifier beats an always-MR baseline before more
    tuning effort is spent.

11. **Trade-frequency calibration is implicit.** Nothing ties θ, `mom_window`,
    `min_hold`, and the 120d MR z-window to the stated 1w–1m target; `avg_hold`
    is already computed by both engines but not surfaced as a design constraint.
    Suggest: display avg/median hold next to backtest results and tune θ (in vol
    units, #4) and entry thresholds until median hold lands in the 5–21
    business-day band.

### 8.3 Suggested order of work

1. Fix the `"state"` → `"trend_state"` key (bug #1) — one line, restores the
   regime boost.
2. Fix the VR scaling and re-calibrate all four vote thresholds against a
   simulated random-walk null (bugs #2, #3); add the null test.
3. Switch the trend engine to `generate_absolute` with vol-scaled θ and fix the
   `carry_buffer` gate for inverted series (bugs #4, #5) — until then, trend
   backtest results for yield-based spreads (all TenorSpread/BondCurve/BondSwap)
   are not meaningful: longs are structurally blocked.
4. Wire `classify_series` into a walk-forward regime-switching backtest mode
   (#7) and add hysteresis (#8).
5. Unify the 30/60/120 windows into one settings block (#9, overlaps §7 item 11)
   and add the regime-accuracy diagnostic (#10).

---

## 9. Return & Sharpe Roadmap (added 2026-07-03)

*Context: §8's fixes are necessary but not sufficient for high Sharpe/return — they
remove active bleeds (blocked longs, mis-routed regime, retroactive/cost-free
backtests that overstate performance) and make the numbers trustworthy, but they
don't by themselves create edge. This section lists what would. Ranked by expected
Sharpe impact; return is addressed separately at the end since it is primarily a
sizing decision once Sharpe is real, not a modeling one.*

1. **Match each instrument's reversion speed to the holding horizon.** Every MR
   trade currently uses the same 120-day z-window (§6.3, §8.2 item 9) regardless
   of how fast that specific spread actually reverts. Fit an OU half-life per
   instrument (one-line AR(1) regression: `Δs_t = α + β·s_{t-1} + ε`, half-life
   `= -ln(2)/ln(1+β)`), then (a) only trade instruments whose half-life falls
   inside the 1w–1m band — a 6-month-half-life spread will hit min-hold/stops
   long before it reverts — and (b) set each instrument's z-lookback to ~3–5×
   its own half-life instead of the global 120d. This replaces the ad-hoc window
   with a principled filter that defines the actual edge for this book: "reverts
   at the speed I trade."

2. **Cross-sectional relative value within spread families.** Currently every
   trade is a time-series bet against its own history. Within a family (e.g. all
   CDB–CGB tenors, all swap-spread tenors) rank rich/cheap against the family's
   fitted curve (the `curves/` surface-fitting code already produces this) and
   go long the cheapest vs. short the richest. This nets out the common factor
   (parallel spread-level moves with policy) that correlates the whole
   time-series book — exactly the tail risk that currently caps Sharpe when
   everything sells off/rallies together.

3. **Volatility-target the book.** Scale gross DV01 so trailing realized
   portfolio vol hits a fixed target (`target_vol / realized_vol`, capped at
   ~2× leverage, recomputed weekly). Currently PnL vol simply inherits whatever
   the rates market is doing — calm periods under-earn, stressed periods
   overrun the risk budget. The DV01-scaled covariance work already recommended
   (§6.4, §7 item 15) is the direct input this needs.

4. **Turnover discipline: trade only when edge clears cost.** Once per-spread-type
   costs are wired in (§6, concern 1 / §7 item 14), gate entries on
   `expected_edge > 2 × round_trip_cost` and widen the exit-z band to reduce
   churn around the mean. On entry style, consider a passive rule — enter only
   once the spread extends a further 0.3–0.5σ past the signal level — since in
   mean-reverting instruments patience is systematically paid at this
   trade-PnL-per-bp scale (2–5bp average per the review's methodology section).

5. **Netting and key-rate exposure limits.** Spreads share legs (a 10s30s
   steepener and a 5s10s flattener partially offset in the 10y). Aggregate net
   DV01 per key tenor across the book and cap it — this both surfaces hidden
   concentration (raising effective breadth → raising Sharpe) and occasionally
   frees up capacity where legs cancel.

6. **Condition gross exposure on funding/policy state.** For CNY rates spreads
   the dominant common factor is liquidity policy. A scaling overlay — reduce
   gross when R007–DR007 blows out, ahead of MLF/LPR dates, during heavy
   CGB/local-bond supply weeks — protects the carry engine from the weeks that
   produce spread RV's worst drawdowns. `load_macro_series` already exists for
   this; it needs a multiplier rule, not a new model.

7. **Enforce book-level positive carry, not just trade-level.** Extend the
   `z − carry_σ` composite entry idea (§6, strengths) into a portfolio
   constraint: net book carry+roll must stay positive. Individual negative-carry
   trades are fine given enough reversion edge, but a book that earns nothing
   while waiting depends entirely on timing luck — positive net carry is what
   makes 1w–1m holding periods survivable through a slow reversion.

**On return:** once Sharpe is real (§8 fixes landed, costs and walk-forward in
place) and stable under items 1–7, return is a leverage/DV01-budget decision, not
a modeling one — raise the vol target (#3) and return scales with it, funded
against the carry-positive book (#7). Scaling *before* the measurement is honest
(§8 concern 1, no execution friction; §6 concern 5, retroactive weighting) just
multiplies an unknown number.

**Suggested next step:** item 1 (per-instrument half-life filter) is the smallest,
most self-contained addition — a new column in `alpha_scoring.py`'s enrichment
step, no engine changes required — and directly improves candidate quality ahead
of everything else on this list.

---

## 10. Quick Reference — Files Cited

| Area | File |
|---|---|
| Loaders, mtime cache, THEME/constants *(was `data.py`, now a package as of 2026-07-03)* | `web/tabs/alpha/data/` (`io.py`, `loaders.py`, `constants.py`, `duration.py`, `legs.py`) |
| Correlation, risk parity, scan scoring | `web/tabs/alpha/scoring.py` |
| Scan / correlation / curated list callbacks | `web/tabs/alpha/callbacks/candidates.py` |
| Scoring & allocation callback, snapshot upsert | `web/tabs/alpha/callbacks/portfolio.py` |
| Individual & portfolio backtest callbacks | `web/tabs/alpha/callbacks/backtest_tab.py` |
| Mean-reversion engine | `web/tabs/alpha/backtest/engine_mr.py` |
| Trend (directional-change) engine | `web/tabs/alpha/backtest/engine_trend.py` |
| Carry accrual | `web/tabs/alpha/backtest/_carry.py` |
| Results display | `web/tabs/alpha/backtest/display.py` |
| Regime classifier (rule-based ensemble) | `curves/calibration/regime.py` |
| Regime HMM + shared Hurst/VR helpers | `futures/backtest/regime.py` |
| Directional-change trend signal | `curves/calibration/trend.py` |
| EOD snapshot enrichment (regime + trend cols) | `curves/refreshers/alpha_scoring.py` |
| Spread / Pairs legacy subtabs | `web/tabs/atlas_fi_tabs.py` |
| Subtab wiring | `web/apps/atlasnexus_daily.py` |
