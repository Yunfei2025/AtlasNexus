# Alpha Book Tab — Code & Methodology Review

*Review date: 2026-06-12. Scope: `web/tabs/alpha/` (data, scoring, layouts, callbacks,
backtest engines), the legacy subtabs mounted under the Alpha Book
(`web/tabs/atlas_fi_tabs.py` Spread/Pairs, `web/tabs/atlas_volatility_tabs.py`), and
their wiring in `web/apps/atlasnexus_daily.py:383-402`. Companion to
`Beta_Book_Review.md` (2026-06-11).*

---

## 1. Overall Assessment

The Alpha Book is structurally **healthier than the Beta Book**: cross-tab state lives
in `dcc.Store` components instead of module globals, the backtest engines
(`backtest/engine_mr.py`, `engine_trend.py`) are separated from the Dash callbacks, and
the carry/borrow-cost model is genuinely sophisticated — direction-aware borrow costs,
per-instrument carry+roll time series, financing adjustments for DV01-hedged tenor
trades. The workflow (Scan → Correlation → Curate → Optimize → Backtest → Summary) is
coherent and the regime auto-detection UX is a nice touch.

The main weaknesses:

1. **The TenorSpread financing adjustment is implemented twice with opposite signs**
   (Candidates scan vs Backtest) — the carry shown when you pick a trade and the carry
   used when you backtest it disagree.
2. **The curated-table edit/delete callbacks index the wrong rows** once a saved
   position filters the rendered list.
3. **The portfolio backtest's capital and transaction-cost inputs are dead** — parsed
   and never used.
4. **The data layer re-reads and re-normalizes whole pickles on every call**, and
   `_get_duration_mult` triggers a full pickle load per table row.
5. **Three Sharpe definitions and three risk-parity solvers** now coexist across the
   alpha and beta books — results are not comparable between tabs.

The Alpha Book also has a quiet identity question: half its subtabs (Spread, Pairs,
Volatility) are legacy layouts living outside `web/tabs/alpha/`, with their own data
path (`web.core.graphs`) and styling. Worth deciding whether they are part of the alpha
workflow (then migrate them in) or a separate explorer (then label them so).

---

## 2. Correctness Bugs (fix first)

### 2.1 TenorSpread financing adjustment: two implementations, opposite signs
The same economic adjustment (financing of the DV01-hedged long leg at FR007) exists in
two places with conflicting formulas:

- Candidates scan — [candidates.py:302](web/tabs/alpha/callbacks/candidates.py#L302):
  `_fin_adj = 0.5 × (FR007_bp − y_long_bp)` and the raw carry is **negated**
  (`−_cr_ts_annual`, line 313) before adjusting.
- Backtest — [backtest_tab.py:389](web/tabs/alpha/callbacks/backtest_tab.py#L389):
  `fin_adj = (1 − 0.5) × (y_long_pct − fr007_pct)` — the **opposite sign** — and the
  raw carry series is not negated.

So the carry+roll a user sees in the Candidates table and the carry the backtest
accrues for the same instrument differ in the sign of the financing term. At least one
is wrong; both also hardcode the 2:1 hedge ratio and the 137 bp FR007 fallback
independently. Extract one `tenor_spread_carry_adjustment(instrument, direction)`
into `web/tabs/alpha/data.py`, write down the sign convention (BUY steepener = short
the long-tenor bond ⇒ …), and make both callers use it.

### 2.2 Curated table edits/deletes hit the wrong row after filtering
`render_curated_content` drops instruments that already exist in Saved Positions before
rendering Table A ([candidates.py:849](web/tabs/alpha/callbacks/candidates.py#L849)),
and assigns pattern-matching ids `{'index': i}` based on the **filtered** list. But:

- `update_curated_meta` ([candidates.py:798-806](web/tabs/alpha/callbacks/candidates.py#L798-L806))
  applies `trig_idx` to the **unfiltered** store, and
- `mutate_curated_instruments` deletes `current[idx]` the same way
  ([candidates.py:766-770](web/tabs/alpha/callbacks/candidates.py#L766-L770)).

Whenever at least one store entry is filtered out of the rendered table, every
regime/direction edit and every × delete below it lands on the wrong entry. Use a
stable key (`spread_type|instrument`) as the pattern-matching index instead of the
positional `i`.

### 2.3 Portfolio backtest ignores its capital and transaction-cost inputs
`run_portfolio_backtest` parses `capital` and `txn_cost_bp`
([backtest_tab.py:585-586](web/tabs/alpha/callbacks/backtest_tab.py#L585-L586)) and
never references either again — confirmed by grep, those are the only occurrences. The
UI advertises an initial-capital and per-trade cost model; the result is cost-free PnL
in bp. Either wire them in (deduct `txn_cost_bp` per round-trip in the engines, scale
bp PnL by DV01-based notional for CNY display) or remove the inputs.

### 2.4 The high-correlation warning can't see high correlations
`check_correlation` ranks the **10 lowest** |corr| pairs, then warns about pairs in
that bottom-10 exceeding `max_corr`
([candidates.py:590-591](web/tabs/alpha/callbacks/candidates.py#L590-L591)). By
construction the highly correlated pairs were already excluded, so the warning is
nearly dead. Compute the warning on the full stacked correlation matrix.

### 2.5 `trade_style` does nothing in the MR engine
In `run_spread_backtest` the `if trade_style == 'mr':` entry block and its `else:`
branch are character-identical
([engine_mr.py:163-185](web/tabs/alpha/backtest/engine_mr.py#L163-L185)). Either the
trend-style entry was meant to differ (e.g. enter *with* the signal rather than
against it) or the parameter should be removed.

### 2.6 Smaller verified items
- Add-trade dedup ignores spread type: `any(e['instrument'] == instrument …)`
  ([candidates.py:741](web/tabs/alpha/callbacks/candidates.py#L741)) blocks the same
  instrument id under a second spread type, although the store treats
  (spread_type, instrument) as the key elsewhere.
- Date-index alignment by `astype(str)` in three places
  ([scoring.py:116](web/tabs/alpha/scoring.py#L116),
  [candidates.py:556](web/tabs/alpha/callbacks/candidates.py#L556),
  [portfolio.py:93](web/tabs/alpha/callbacks/portfolio.py#L93)) — papering over mixed
  `datetime.date` / `Timestamp` / string indices in the pickles. Normalize to
  `DatetimeIndex` at load time in `_load_pickle_safe`, not at every use site.
- Dead code: `risk_parity_weights` (the iterative solver),
  `compute_candidate_scores`, `select_diversified_trades`, and
  `compute_unified_edge_vol_score` in `scoring.py` have no callers (grep across
  `web/` and `curves/`); `_TENOR_RATIO = 2.0`
  ([candidates.py:284](web/tabs/alpha/callbacks/candidates.py#L284)) and
  `DIVERSIFIED_TRADE_RECOMMENDATIONS` ([data.py:112](web/tabs/alpha/data.py#L112))
  are unused. Delete or wire in.

---

## 3. Workflow

**What works:** the Candidates → Portfolio → Backtest pipeline maps cleanly onto how an
RV book is actually run (screen, de-correlate, size, validate); `dcc.Store` keeps state
per-session instead of per-process (the beta tab should copy this); saved positions
round-trip through `alpha_book_positions.parquet` so the book survives restarts; the
Backtest tab pulling the persisted Summary snapshot (`_load_portfolio_snapshot`) keeps
Backtest and Summary consistent.

**Issues:**

- **Split-brain subtabs.** Spread, Pairs and Volatility are mounted under the Alpha
  Book (`an-alpha-subtabs` in `web/apps/atlasnexus_daily.py:383-402`) but live in
  `web/tabs/atlas_fi_tabs.py` / `atlas_volatility_tabs.py`, render from a different
  data path (`web.core.graphs` + realtime refresh) and don't share the alpha stores.
  An instrument you find interesting in the Spread explorer can't be sent to the
  Candidates list — that's the most natural workflow link and it doesn't exist.
- **Cross-book coupling via parquet.** The Beta tab's `risk.py` reads *and rewrites*
  `summary_alpha_portfolio.parquet` and `alpha_book_positions.parquet`
  (`web/tabs/beta/callbacks/risk.py:106-126, 179-209`). Two tabs owning one file with
  different schemas is how the beta summary-file bug happened; give the file one owner
  and an explicit API.
- **Weights are applied retroactively in the portfolio backtest.** Today's optimized
  weights (from today's scores) are used to weight trade equity curves over the past
  year — a look-ahead structure. Fine as a "how would the current book have done"
  sanity view, but label it as such; it is not a strategy backtest.
- **`_REGIME_LOOKUP_CACHE` never invalidates**
  ([candidates.py:29](web/tabs/alpha/callbacks/candidates.py#L29)) — after the EOD
  job rewrites the snapshot pickles, regime lookups keep serving the previous values
  until the process restarts.

---

## 4. Code Structure

**What works:** clean module split (`data` / `scoring` / `layouts` / `callbacks/*` /
`backtest/*`); engines take plain Series + scalars and return dicts — easily testable;
`_carry.py` shared by both engines instead of duplicated.

**Issues:**

- **Three near-identical dispatch ladders** in `data.py`: `load_spread_data` (:208),
  `load_spread_timeseries` (:689), `load_realtime_spreads` (:818) each re-enumerate
  every spread type with its pickle path and nested key. A single registry
  (`SPREAD_SOURCES = {stype: (pkl, key, …)}`) collapses ~300 lines and makes adding a
  spread type a one-line change.
- **`scan_candidates` is ~320 lines** (candidates.py:202-518) mixing data load, carry
  adjustment, breakeven filtering, stop/target derivation and table styling; the
  TenorSpread carry block (§2.1) and the breakeven/stop/target derivations belong in
  `data.py`/`scoring.py` as pure functions with unit tests.
- **Duplicated `_upsert_snapshot`** in `web/tabs/alpha/callbacks/portfolio.py:30` and
  `web/tabs/beta/callbacks/_common.py:35` — identical code, two copies. Same for the
  THEME dict (alpha `data.py:17`, beta `data.py:55` — they already diverge in
  `table_header`).
- **Magic numbers without a home**: duration ≈ `ttm × 0.92`; swap annuity at flat
  1.5%/quarterly; FR007 fallback `137.0` bp (twice); hedge ratio 0.5; MR lookback 120;
  carry-sigma clip ±1.5; breakeven-reject rule `breakeven > vol`; momentum entry gate
  `|m| ≥ 0.5` (engine_trend.py:177). Move to a `settings`-level config so scan and
  backtest can't drift (they already have, §2.1).
- `except Exception: pass` throughout `data.py` (e.g. :222, :262, :531, :555) hides
  loader failures as "no data"; log at minimum. `print` instead of `logging`
  everywhere.

---

## 5. Performance

- **No mtime caching in the alpha loaders.** `_load_pickle_safe`
  ([data.py:154](web/tabs/alpha/data.py#L154)) re-reads the pickle *and* runs the
  recursive `Repo-`→`Repo7d-` renormalization over the whole object on every call.
  The Spread subtab next door already has the right pattern —
  `_load_pickle_cached` keyed by mtime
  ([atlas_fi_tabs.py:432](web/tabs/atlas_fi_tabs.py#L432)). Adopt it in
  `data.py` and apply the Repo renormalization once per load, not per call.
- **`_get_duration_mult` loads a pickle per row.** For bond types it calls
  `load_spread_data(spread_type)` internally ([data.py:357-366](web/tabs/alpha/data.py#L357-L366));
  `run_scoring` then applies it row-by-row via `df.apply`
  ([portfolio.py:289-292](web/tabs/alpha/callbacks/portfolio.py#L289-L292)) — a full
  pickle read per table row. With the mtime cache this becomes free; without it,
  pass the snapshot in once.
- **Repeated full-pickle loads inside loops**: `check_correlation` calls
  `load_spread_timeseries(spread_type)` once per candidate row
  ([candidates.py:550](web/tabs/alpha/callbacks/candidates.py#L550)) instead of once
  per spread type (`_compute_risk_parity_weights` already does the per-type
  `ts_cache` correctly — copy that).
- `iterrows()` in the scan over TenorSpread rows and ttm computation
  (candidates.py:296, 331) — fine at ~100 rows, but trivially vectorizable.
- The engines' per-day Python loops are acceptable at one instrument × ~1000 days,
  and the pre-aligned carry lookups (engine_mr.py:61-79) show the O(n²) lesson was
  already learned. No action needed there.

---

## 6. Methodology

**Strengths worth keeping:** the carry framework (per-instrument daily 3m carry+roll,
direction-dependent borrow costs from `BondConfig.BORROW_COST` buckets, financing
adjustment for hedged tenor trades, BondSwap direction asymmetry); the carry-adjusted
composite entry signal `z − carry_σ` so MR trades don't fight negative carry; min-hold
with always-on stops; equity marked-to-market daily including open-trade carry; regime
auto-detection feeding the default trade style with an edge-sign tiebreaker.

**Concerns:**

1. **No execution friction anywhere.** Entries and exits fill at the signal-day close;
   no bid/offer, no slippage, and the portfolio cost input is dead (§2.3). For CGB
   off-the-runs and CDB long-end the bid/offer is a material fraction of the 2-5 bp
   average trade PnL the engines report. Add a per-spread-type round-trip cost (bp)
   and an optional next-day fill.
2. **Non-standard Sharpe.** `mean(pnl)/std(pnl) × sqrt(min(n_trades, 20))`
   ([engine_mr.py:271](web/tabs/alpha/backtest/engine_mr.py#L271)) is a per-trade
   t-statistic with an arbitrary cap, while the portfolio backtest uses daily
   `× sqrt(252)` ([backtest_tab.py:729](web/tabs/alpha/callbacks/backtest_tab.py#L729)),
   beta uses geometric annual minus 2%, and `multiasset.factor_backtest` uses
   arithmetic annual. Standardize on one definition (suggest: daily-equity Sharpe,
   annualized, rf configurable) in one shared metrics module — same recommendation as
   the beta review.
3. **MR statistics use a single 120-day window** for mean, σ and z everywhere
   ([engine_mr.py:40](web/tabs/alpha/backtest/engine_mr.py#L40)) and it is not
   exposed in the UI, while the snapshot side uses its own (`StatInfo`) windows — so
   a 2.0 z in the Candidates table is not the 2.0 z the backtest trades. Expose the
   lookback and reuse the same z computation.
4. **Risk parity on raw bp changes mixes units.** Spread vol in bp is not risk: a
   1 bp move on a 9-duration 10s30s is ~9× the PnL of 1 bp on a 1-year swap spread.
   Weight on **DV01-scaled** return series (Δspread × duration_mult), which the data
   layer already computes. Also: after clipping weights to bounds the code rescales
   without re-solving ([scoring.py:174-175](web/tabs/alpha/scoring.py#L174-L175)),
   so reported risk contributions are pre-clip; recompute them from the final
   weights (one line — `_risk_contribution(weights_array, cov)` is already called,
   just note RC≠target after clipping in the UI).
5. **Portfolio aggregation ignores entry timing.** Summing independently backtested
   equity curves weighted by today's allocation (a) lets every trade run its own
   entries over the full window with no portfolio-level netting or margin, and
   (b) ffills shorter curves with 0 so late-history instruments jump in. Acceptable
   as a correlation sanity check; say so in the panel title.
6. **Trade-style taxonomy is stringly typed.** 'MeanReversion' / 'Mixed' / 'Carry' /
   'trend' / 'momentum' / 'mean-reverting' / 'mean_reverting' are mapped between at
   least four normalizers (`_style_to_regime`, `_style_to_regime_label` ×2, regime
   store values). One enum in `data.py` with one normalizer would remove a whole
   class of silent fallthrough-to-'uncertain'.

---

## 7. Prioritised Improvement Plan

### Phase 1 — Correctness (small diffs)
1. Reconcile the TenorSpread financing adjustment into one shared function with a
   written sign convention; add a unit test pinning the BUY/SELL carry signs (§2.1).
2. Key the curated-table pattern-matching ids by `spread_type|instrument`, not
   position (§2.2).
3. Wire up or remove the portfolio backtest capital / txn-cost inputs (§2.3).
4. Fix the high-correlation warning to scan all pairs (§2.4).
5. Resolve or remove the dead `trade_style` branch in `run_spread_backtest` (§2.5).
6. Delete verified dead code in `scoring.py` / `data.py` (§2.6).

### Phase 2 — One source of truth
7. Spread-source registry replacing the three dispatch ladders in `data.py`.
8. Shared metrics module (one Sharpe/MDD definition) used by alpha engines, alpha
   portfolio backtest, and the beta tabs.
9. Move `_upsert_snapshot` and THEME to one shared module; single owner for the
   alpha parquets (beta reads through it).
10. One style/regime enum + normalizer.
11. Constants (duration proxy, FR007 fallback, hedge ratio, MR lookback, clip
    levels) into settings.

### Phase 3 — Performance & state
12. mtime-cached pickle loader in `data.py` (pattern already in
    `atlas_fi_tabs.py:432`); invalidate `_REGIME_LOOKUP_CACHE` on snapshot mtime.
13. Hoist per-row pickle loads out of loops (`_get_duration_mult`,
    `check_correlation`).

### Phase 4 — Methodology
14. Per-spread-type transaction costs + optional next-day fills in both engines.
15. DV01-scaled covariance for risk parity; report post-clip risk contributions.
16. Expose the MR lookback; unify snapshot z and backtest z.
17. Relabel the portfolio backtest as a current-book sanity view, or rebuild it as a
    true walk-forward (weights recomputed from information available at each date).
18. Connect the Spread explorer subtab to the Candidates workflow ("➕ add to
    candidates" on the selected ticker) — see `Seasonal_Strategy_Ideas.md` for the
    planned seasonal upgrade of that subtab.

---

## 8. Quick Reference — Files Cited

| Area | File |
|---|---|
| Loaders, carry/duration/borrow helpers, THEME | `web/tabs/alpha/data.py` |
| Correlation, risk parity, scan scoring | `web/tabs/alpha/scoring.py` |
| Scan / correlation / curated list callbacks | `web/tabs/alpha/callbacks/candidates.py` |
| Scoring & allocation callback, snapshot upsert | `web/tabs/alpha/callbacks/portfolio.py` |
| Individual & portfolio backtest callbacks | `web/tabs/alpha/callbacks/backtest_tab.py` |
| Mean-reversion engine | `web/tabs/alpha/backtest/engine_mr.py` |
| Trend (directional-change) engine | `web/tabs/alpha/backtest/engine_trend.py` |
| Carry accrual | `web/tabs/alpha/backtest/_carry.py` |
| Results display | `web/tabs/alpha/backtest/display.py` |
| Spread / Pairs legacy subtabs | `web/tabs/atlas_fi_tabs.py` |
| Subtab wiring | `web/apps/atlasnexus_daily.py` |
