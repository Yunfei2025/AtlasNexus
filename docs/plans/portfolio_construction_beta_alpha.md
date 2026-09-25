# Portfolio Construction — Beta (Factor) + Alpha (TenorSpread core + satellites)

Status: §5.1 and §5.2 implemented and tested. §5.1:
`web/tabs/risk/books/combination.py`, `combination_callbacks.py`,
`tests/test_beta_alpha_combination.py`. §5.2: `web/tabs/alpha/data/core_seed.py`,
`select_diverse_instruments`'s `locked` parameter in `scoring.py`,
`correlation_callbacks.py` wiring, `tests/test_alpha_core_seed_correlation.py`.
§5.3 closed, descoped — no code change (see §6a). §5.4 checklist + tool
implemented (see §6b): `utils/margin_ratio_check.py`,
`tests/test_margin_ratio_check.py`. §5.5 closed after review — turned out to
already exist in Summary > Risk, not previously reviewed (see §6c). All five
workstreams now closed.
Scope: how the Beta book (`multiasset` factor optimizer), the Alpha core book
(`TenorSpread`, `build_default_category_portfolio`), and Alpha satellite spread
types (Carry, Trend, New-Issue, PCA, etc.) fit together as one client
portfolio, and what Summary > Books > Portfolio Combination already does about
it.

## 1. Current architecture (as-built, not aspirational)

Three independent construction layers, connected only by a display page:

| Layer | Module | Sizing basis | Universe selection |
|---|---|---|---|
| Beta | `multiasset.factor_optimizer` | `total_capital` typed into Beta Portfolio Run panel (unlevered, notional = capital) | Bond + spread universe from `multiasset.main`, factor risk-parity / min-vol / tilt |
| Alpha core | `curves`/`web/tabs/alpha` — `build_default_category_portfolio('TenorSpread')` | Own margin sizing (`estimate_margin_mm`), independent capital figure | **Full** long-history TenorSpread universe, MR-only, risk-parity weighted — no correlation filter |
| Alpha satellites | Candidates → Correlation Check (`select_diverse_instruments`) | Same alpha capital pool as core, manually sized | Scan/score candidates from other spread types (Carry, Trend, New-Issue, PCA…), diversity-filtered by pairwise |corr| against **other selected candidates**, not against the core book |

Cross-book linkage exists in **two** places — the original version of this
plan only reviewed the first one (see §6c for the correction):

- **`web/tabs/risk/books/combination.py`** (Summary > Books > Portfolio
  Combination) — the **return-level** view:
  - reconciles units (beta = unlevered notional, alpha = margined book) via a
    fitted margin ratio (`estimate_alpha_book_margin_ratio`, single-leg DV01
    proxy with a ~2.5x netting correction — see `estimate_margin_mm`),
    converts a requested "alpha margin share of total capital" into a
    notional blend weight;
  - computes realised correlation and a diversification ratio between the two
    books' **saved backtest** daily return series, inner-joined on
    overlapping dates;
  - sweeps the margin share to chart a Sharpe frontier, and reports Max-Sharpe
    and Risk-Parity split suggestions, snapped to a 5% tick (deliberately
    coarse — see `SUGGESTED_SPLIT_TICK` docstring).
- **`web/tabs/risk/dashboard.py`** (Summary > Risk) — the **exposure-level**
  view, point-in-time rather than backtest-based:
  - Net Position by Instrument: signed capital and DV01 netted per instrument
    code across both books (Beta positions always long; Alpha legs
    long/short by BUY/SELL direction), filterable by Beta/Alpha/Mixed.
  - DV01 Duration Ladder: tenor-bucketed (3M-30Y) DV01 split into
    Bonds/Swaps/Futures/Other, with Alpha spreads leg-resolved (both legs,
    duration-matched, direction-signed) rather than treated as one blob.
  - Factor Risk Attribution chart (from the Beta factor model) and a full
    Position Inventory table.

These two views aren't cross-referenced — a return-correlation read from the
Combination card and a same-day exposure-concentration read from the Risk
subtab have to be checked separately, in two different subtabs.

This is the load-bearing piece for "is alpha actually diversifying beta, or
duplicating risk," and it already does the hard part (unit reconciliation)
correctly. What it does *not* do is checked in §2.

## 2. Gaps identified in review

Ranked by how much they could silently invalidate the combination card's
headline numbers:

1. **Single full-sample correlation, no regime conditioning.** `corr` and
   `diversification_ratio` are one scalar over the full overlapping window.
   Alpha core is duration/curve-adjacent (TenorSpread = bond-vs-curve,
   bond-vs-repo, cross-curve); Beta's Rates sleeve is also duration-driven.
   Both could plausibly decorrelate in calm markets and correlate hard in a
   rates stress event — exactly when the diversification benefit is needed
   most and least available. A single full-sample number can't distinguish
   "diversifying" from "diversifying except in the tail."
2. **Suggested split is in-sample over the same window used to measure
   correlation.** Max Sharpe / Risk Parity splits are picked from the same
   saved-backtest overlap that produced the correlation estimate — no
   walk-forward or out-of-sample check on the split itself, unlike the
   discipline already applied to individual alpha spreads (no param tuning
   per [[alpha-backtest-no-param-tuning]]).
3. **`margin_ratio` depends on current book composition** and a fitted
   constant (2.5x netting correction) — reasonable, but not something we've
   confirmed is still calibrated to the *current* TenorSpread mix (composition
   has moved: trend leg dropped, stop-loss re-entry lockout added — see
   [[alpha-trend-leg-abandoned]], [[alpha-mr-stop-loss-was-noop]]). Worth a
   periodic sanity check, not a one-time fit-and-forget.
4. ~~**Return-correlation only, no exposure netting.**~~ **Corrected in
   review (see §6c) — this gap doesn't exist.** Summary > Risk
   (`web/tabs/risk/dashboard.py`, not reviewed when this gap was first
   written) already nets instrument-level capital and DV01 across both books,
   with a leg-resolved, tenor-bucketed DV01 ladder and a Beta/Alpha/Mixed
   filter. The real gap is narrower: that netting view and the Combination
   card's return-correlation view are two disconnected subtabs, not that
   netting is missing.
5. **Satellite correlation check doesn't use the core book as its seed.**
   Separate from the Beta/Alpha combination card: `select_diverse_instruments`
   (candidates workflow) diversifies new candidates against *other selected
   candidates*, not against the live default TenorSpread core holdings. A
   Carry/Trend candidate can pass the correlation-check screen while being
   highly correlated with a large existing core position, with no warning.

## 3. What's *not* being reopened

- The unit-reconciliation approach (beta notional : alpha margin, not
  notional : notional) is correct and stays as-is.
- The 5% coarse tick on suggested splits stays — a split precise to 1% is
  false precision given one noisy sample's Sharpe estimate.
- No change to how the Alpha core book itself is constructed (full TenorSpread
  universe, no correlation filter) — that's intentional per
  [[alpha-single-spread-sharpe-ceiling]] / [[alpha-strategy-vs-level-correlation]]:
  the core's Sharpe comes from combining ~14 instruments, and level-based
  filtering was already shown to destroy it.

## 4. Candidate workstreams

| # | Workstream | Addresses gap | Effort | Priority |
|---|---|---|---|---|
| 5.1 | Rolling / regime-conditional correlation view on the Combination card | #1 | Medium | **First** |
| 5.2 | Seed satellite correlation-check against live core holdings, not just other candidates | #5 | Medium | Second |
| 5.3 | Walk-forward / out-of-sample check on suggested split | #2 | High | **Closed, descoped** — see §6a |
| 5.4 | Periodic re-validation of the margin-ratio netting correction against current book composition | #3 | Low — tool built, running it is the ongoing part | **Tool done, see §6b**; running it is ongoing |
| 5.5 | ~~Exposure-netting diagnostic~~ — already exists (Summary > Risk); rescoped to a review | #4 | Low — review only | **Closed, review only, see §6c** |

## 5. Scoped for implementation now: 5.1 — rolling/regime correlation view

### Goal
Add a second view next to the existing single-scalar correlation/diversification
ratio: how that relationship behaves over time, so a "looks diversifying
on average" conclusion can't hide "correlates hard exactly in stress."

### Approach
- Compute a rolling correlation of `r_beta` vs `r_alpha` (already produced by
  `build_combination`) over a fixed window, default **120 trading days**
  (~half a year). Rationale for 120d over the originally-floated 60d:
  - Standard error of a sample correlation at n=60 is ~0.13 — a 60d rolling
    series would swing on noise alone and generate false spike flags. At
    n=120 that drops to ~0.09, a meaningfully cleaner signal while still
    short enough to move visibly across a backtest's history.
  - 60d is also the combination card's existing *full-sample* minimum-overlap
    gate (`build_combination` requires `len(common) >= 60`) — using the same
    number as a *rolling* window would mean the first rolling point needs the
    entire minimum history, leaving no room to see it move. 120d keeps the
    rolling view a strict "needs more history than the floor" tier above that
    gate, not equal to it.
  - A genuine rates-stress correlation shift plays out over weeks, not days;
    120d is short enough to distinguish such an episode from the full-sample
    average without being dominated by single-day noise.
- Plot it as a time series under/beside the existing Diversification Frontier
  chart in `combination_callbacks.py`, sharing the same overlapping date range
  already computed (`result['returns']`). Don't plot any rolling point until
  ≥120 days of overlap are available; below that, show a "not enough history
  for rolling view yet" fallback distinct from the existing full-sample error.
- Flag (visually, e.g. shaded band or marker) periods where rolling
  correlation exceeds **+0.5** — a simple first pass, not a statistical regime
  model.
- Surface the *worst-window* correlation (max over the rolling series) as a
  headline number next to the existing full-sample correlation stat, so the
  strip shows both "average" and "worst case seen so far" rather than only
  the number that looks best.
- No change to `build_combination`'s existing return values — additive only,
  new keys in the result dict (e.g. `rolling_correlation`, `worst_window_corr`).

### Explicit non-goals for this pass
- No attempt to build a real regime classifier (rates level/vol regime, etc.)
  — that's a much bigger project and not needed to get the main benefit here.
- No change to the suggested-split logic (Max Sharpe / Risk Parity) — this is
  a diagnostic addition, not a re-optimization.
- No retroactive changes to margin ratio or capital-split math.

### Decided (subject to revisit once real data is seen)
- Rolling window: **120 trading days**, per rationale above.
- Correlation-spike flag threshold: **+0.5**.

Both are first-pass defaults, not tuned — revisit once the rolling view has
been looked at against actual saved beta/alpha backtest history.

## 6. Scoped for implementation now: 5.2 — seed satellite correlation-check off the live core

### Goal
When checking a Carry/Trend/New-Issue/other-category candidate for
diversification, compare it against the Alpha **core book's actual current
holdings** (the default TenorSpread book), not only against whatever else
happens to be selected in the candidate list at that moment. Today a
satellite candidate can pass the correlation screen while being highly
correlated with a large existing core position, with no warning — see gap #5
in §2.

### What's stable vs. what should stay live
Two different things were being conflated in earlier discussion of this
workstream, worth separating explicitly:
- **Core book *membership*** (which instruments are in the default TenorSpread
  book) — this is structurally stable. It only changes when an instrument
  crosses `build_default_category_portfolio`'s `min_history_days` (1200 days)
  threshold or drops out of the universe entirely; day-to-day it's the same
  set of ~14 instruments even though each one's BUY/SELL direction flips with
  its current z-score sign. Checking this on every "Check Correlation" click
  is unnecessary churn.
- **The correlation matrix itself** (today's duration-adjusted price-change
  correlations) — this should stay live, computed against current price
  history on the existing lookback window, same as today. Only the *seed
  list of instrument IDs* is cached, not the correlation values computed
  against them.

### Approach
- Cache the core book's instrument membership (`spread_type`, `ID` pairs from
  `build_default_category_portfolio('TenorSpread')`) to a small file (e.g.
  `alpha_core_seed.pkl` under `DIR_INPUT`), refreshed on a **90-day
  (quarterly) time-based expiry** — not on every page load, not manually
  triggered. On cache miss/expiry, rebuild by calling
  `build_default_category_portfolio` once and persist the instrument list
  (and the mtime/build date) to the cache file.
- In `check_correlation` (`web/tabs/alpha/callbacks/correlation_callbacks.py`),
  load the cached core seed list and merge it into the correlation matrix
  construction alongside `all_candidates` — the core instruments' price series
  go into the same duration-adjusted correlation matrix already being built.
- Change `select_diverse_instruments` (or add a variant) to accept a
  `locked: list[str]` parameter: instruments in `locked` are treated as
  already selected from the start (like the current `seed` step), never
  competing for one of the `n` candidate slots, so the core book doesn't
  crowd out satellite picks — only its correlation exposure counts. New
  candidates from `all_candidates` are then greedily selected same as today,
  but their max-|corr| check is against `locked ∪ selected_so_far`, not just
  `selected_so_far`.
- Surface which locked core instruments are driving a rejection: when a
  candidate is dropped for exceeding `max_abs_corr`, the UI should be able to
  say *which* instrument it was too correlated with (core or satellite) —
  today's rejection is silent (the candidate just doesn't appear in
  `diverse_keys`). This is a small addition to the existing warning text
  (`high_corr` pairs), not a new mechanism.

### Explicit non-goals for this pass
- No change to how the core book itself is built, weighted, or backtested —
  `build_default_category_portfolio` stays a full-universe, no-correlation-filter
  book by design (§3).
- No automatic re-triggering of the correlation check when the cache expires
  — expiry only affects what the *next* click uses as the seed.
- No UI toggle to disable core-seeding — per your steer, this should just be
  how the check works going forward, not an opt-in.

### Implementation notes
- Cache: `web/tabs/alpha/data/core_seed.py`, pickle at
  `DIR_INPUT / 'alpha_core_seed.pkl'`, wall-clock 90-day expiry from the
  stored `built_at` timestamp, checked on every `check_correlation` call
  (`load_core_seed()` — cheap read/compare, only rebuilds the actual default
  category portfolio on a cache miss/expiry).
- `select_diverse_instruments` gained a `locked: list[dict] | None` parameter
  (same `{ID, spread_type, ...}` shape as `candidates`). Locked instruments
  seed `selected`/`selected_stypes` before the greedy loop runs, are excluded
  from `n`, and are stripped from the returned list.
- **Bug found and fixed during implementation**: the pre-existing "seed" step
  (picking the first instrument purely by highest |z-score|) did not check
  `max_abs_corr` against anything already selected. With no `locked` set this
  only mattered on the very first pick of an otherwise-empty selection (no
  effect). Once `locked` seeds `selected` before this step runs, the bug meant
  a satellite candidate could be chosen as the "seed" purely for having the
  highest z-score even while highly correlated with a locked core holding —
  defeating the entire point of locking. Fixed by restricting the seed
  candidate pool to those passing the same `max_abs_corr` check the main loop
  already applies. Covered by
  `test_candidate_too_correlated_with_locked_core_is_rejected` in
  `tests/test_alpha_core_seed_correlation.py`.
- `check_correlation` (`correlation_callbacks.py`) merges the core seed's
  price series into the same duration-adjusted correlation matrix used for
  scanned candidates (both the candidate-timeseries branch and the
  category-pickle/`compute_spread_correlation` fallback branch), then passes
  `locked=core_seed` to `select_diverse_instruments`. The heatmap includes the
  locked core columns, and a status line reports how many core holdings were
  included, the cache's age, and how many were dropped for lacking price
  history at the selected lookback.

## 6a. §5.3 closed: no walk-forward check on the suggested split

Decision: don't build this. The suggested-split tick size (5%, `SUGGESTED_SPLIT_TICK`)
and the fact that it's picked in-sample over the same window used for the
correlation estimate are two different concerns — closing this doesn't touch
the tick, which stays as-is (already correctly sized against the noise in a
single Sharpe estimate, see §5.1's rationale for the same kind of argument).

Reasoning for closing rather than building an OOS check:
- The suggested split is explicitly framed as "a real-world capital allocation
  meant to be set roughly annually" (see `SUGGESTED_SPLIT_TICK`'s docstring),
  not a precise, continuously re-optimized target. A rough annual-rebalance
  guide doesn't carry the same overfitting risk as a signal that gets acted on
  daily — the failure mode (locking in a split that happened to look good over
  one sample) is bounded by how infrequently it's actually used to move
  capital.
- A real walk-forward/rolling-origin check needs meaningfully more overlapping
  saved-backtest history per book than a single split-half or two would give
  here (see the existing 60-day full-sample floor and 120-day rolling window
  from §5.1 — both already stretch what's typically available); building it
  now would likely just report "not enough history" more often than it
  reports something useful.
- The Max Sharpe / Risk Parity numbers are already labeled "Suggested Splits,"
  not prescriptive targets, and sit next to the "Selected" split the user
  actually chose — the UI doesn't present them as validated recommendations.

If this is revisited later, the trigger should be "enough saved-backtest
history has accumulated that a rolling-origin check would have more than one
or two folds to work with," not a fixed date.

## 6b. §5.4 — margin-ratio netting-correction re-validation

### What's being checked
`estimate_margin_mm` (`web/tabs/alpha/data/duration.py`) scales a single-leg
DV01 proxy by `_MARGIN_NETTING_MULTIPLIER = 2.5` to correct for the fact that
it only sees one leg's notional/duration while the real (leg-resolved) margin
model grosses up every leg. That constant was fit once, against
`summary_alpha_portfolio.parquet`'s 25 live TenorSpread/SwapSpread rows on
2026-09-15 (median ratio 2.49x; see the constant's docstring for the full
fit detail: mean 3.40x, IQR 2.0-4.0x, range 0.53x-11.2x). It directly feeds
the Beta/Alpha Combination card's capital split (`margin_ratio` in
`combination.py`) — see gap #3 in §2. Nothing re-checks it as the book's
actual composition drifts over time (instruments added/dropped, tenor mix
shifting).

### Tool: `utils/margin_ratio_check.py`
Reproduces the original fit methodology against whatever
`summary_alpha_portfolio.parquet` currently holds:
- Re-derives `actual_margin_mm / single_leg_dv01_estimate` per row, excluding
  floor-bound rows (rows where the margin charge is just the notional floor
  carry no information about the netting multiplier — including them would
  bias the ratio toward 1.0 for the wrong reason).
- Reports median (what the constant is set from), mean, IQR, range, and
  sample size — explicitly warns when the sample is too small (`--min-rows`,
  default 15; the original fit used 25) to treat the result as re-fit-worthy
  rather than merely indicative.
- Flags instrument types outside the original fit's scope (e.g. `TBondCurve`,
  a bond-vs-curve margin regime, not a derivative DV01 charge) so they aren't
  silently averaged into a comparison they don't belong in.
- Reports drift of the current re-derived median from `_MARGIN_NETTING_MULTIPLIER`
  and only recommends action when drift exceeds a threshold (`--drift-threshold`,
  default 25%) **and** the sample is large enough — small-sample noise alone
  produced 100%+ apparent drift on a 5-row snapshot during testing, correctly
  suppressed by the sample-size gate.
- Does not change the constant itself — a re-fit, if warranted, is a manual
  edit to `_MARGIN_NETTING_MULTIPLIER` (with its docstring updated to record
  the new fit date/sample), same as the original.

### Checklist (run periodically — no fixed schedule beyond "often enough that
composition drift would be caught before it meaningfully skews the Combination
card's capital split," e.g. alongside a quarterly review)
1. Run `python utils/margin_ratio_check.py`.
2. If usable rows (`n`) is below `--min-rows` (15): the book doesn't have
   enough margined positions right now to say anything — note the date and
   defer, don't force a re-fit off a thin sample.
3. If `n` is adequate and drift is flagged: look at the per-instrument detail
   table for outliers/type mix shifts before changing anything — a re-fit
   should use a similarly-scoped sample to the original (TenorSpread/SwapSpread,
   not every spread type), same exclusions (floor-bound rows dropped).
4. If a re-fit is warranted: update `_MARGIN_NETTING_MULTIPLIER` in
   `web/tabs/alpha/data/duration.py` and its docstring (new median, new fit
   date, new sample composition) — mirroring how the original fit was
   documented, so the next re-validation has the same trail to compare against.
5. If no re-fit is warranted: nothing to change; the check itself isn't logged
   anywhere persistent — this plan doc is the record that periodic checks are
   expected, not a log of each run.

## 6c. §5.5 closed: exposure netting already exists, corrected the record instead

The original gap #4 ("return-correlation only, no exposure netting") and
§5.5's scoping as a high-effort build were both wrong — written without
reviewing `web/tabs/risk/dashboard.py` (Summary > Risk), which already does
this. Corrected in §1 and §2 above rather than left standing.

What actually exists, in case this is re-scoped again later without
re-discovering it:
- Net Position by Instrument (`build_net_position_fig` in `charts.py`,
  computed in `update_risk_tables`): per-instrument-code signed capital and
  DV01, summed across both books via `_add_net`, Beta always long / Alpha
  legs signed by BUY-SELL direction, with a Beta/Alpha/Mixed filter.
- DV01 Duration Ladder (`build_dv01_ladder_fig`): tenor-bucketed
  (`_TENOR_ORDER` = 3M..30Y) DV01, split into Bonds/Swaps/Futures/Other.
  Alpha spreads are leg-resolved (`_resolve_legs`, `_leg_volume_ratio`,
  `_leg_duration_years`) so a mixed bond/swap trade splits its DV01 across
  the right buckets rather than being counted once at one duration.
  Duration-matched leg2 volume is rounded to the nearest 10MM tick to match
  the Alpha Portfolio Allocation Snapshot convention.
- Factor Risk Attribution chart (`build_factor_risk_fig`), sourced from the
  Beta factor model's `factor_risk` output.
- KPI strip + full Position Inventory table (leg-level detail, expandable).

What's genuinely still missing, and was the only real content in gap #4: this
Risk-subtab exposure view and the Books-subtab Combination (return
correlation) view are not cross-referenced. Decision: **don't build a
connector now** — per your steer, review and correct the plan rather than add
new scope. If a concrete need for the connection comes up later (e.g. someone
actually gets confused reading one view without the other, or a real stress
episode makes the disconnect costly), revisit then with a specific trigger
rather than building speculatively.

## 7. Next steps

All five identified workstreams (§5.1-§5.5) are now closed:

1. ~~§5.1~~ — implemented and tested (rolling/regime correlation view).
2. ~~§5.2~~ — implemented and tested (core-seed correlation check).
3. ~~§5.3~~ — closed, descoped, no code change (see §6a).
4. ~~§5.4~~ — tool built and tested (see §6b); the checklist itself remains an
   ongoing/periodic task, not a one-time completion.
5. ~~§5.5~~ — closed after review; already existed, plan doc corrected (see §6c).

No open implementation items remain from this plan. Future work here should
start from a new, specific trigger (e.g. real usage surfacing a gap) rather
than a fresh top-to-bottom architecture review.
