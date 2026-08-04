# Alpha Book: Monthly Style Review and Trend-Signal Plan

**Status:** Approved individual-trade design (trend signal: MAD/z-score momentum
hysteresis, see Implementation Scope item 2); portfolio walk-forward extension
planned.

## Objective

Simplify Alpha spread-trade signal generation and remove daily adaptive regime
switching from the Backtest experience.

- Assign each trade one style, **mean reversion** or **trend**, at a monthly review.
- Keep that style fixed for the rest of the calendar month.
- Use one transparent entry signal for each style.
- Keep candidate scores for ranking and allocation only, rather than using them as
  intramonth entry confirmations.

## Approved Trading Rules

| Style | Entry rule | Exit rule | Carry treatment |
| --- | --- | --- | --- |
| Mean reversion | Enter from the z-score threshold only. | Exit when the z-score reverts through its exit band; retain the adverse z-score stop. | Accrue in realized PnL and use in ranking, but do not adjust entry. |
| Trend | Enter long when the hysteresis-banded z-score of trend momentum crosses above `+theta_z`; enter short when it crosses below `-theta_z` (shorts enabled). | Exit on an opposite hysteresis crossing or the existing volatility trailing stop. | Accrue in realized PnL and use in ranking, but do not confirm, veto, or reverse entry. |

Trend entries use a rolling z-score of medium-horizon momentum, normalized by a
continuously updated robust volatility estimate (Implementation Scope item 2). Because
the signal is a normalized *difference*, not a ratio to the spread's own level, it is
well-defined on inverted yield spreads and near-zero or zero-crossing series without
the extremum-scaling care the earlier directional-change (DC) generator needed.

## Monthly Style Review

1. On the first available trading day of each calendar month, classify the spread
   from data available through that review date only.
2. Map the result to canonical `mr` or `trend` style and hold it unchanged through
   month-end.
3. If the classifier is uncertain or has insufficient history, retain the prior
   monthly style. Before any valid classification, use the spread category's static
   default style.
4. If an open position's style differs from the new monthly assignment, close it at
   the review observation with `exit_reason='monthly_style_change'`.
5. If the style is unchanged, retain the position and do not force a month-end or
   month-start exit.

This classification runs across every eligible candidate in the universe, not only
currently open trades: the same monthly regime label feeds both this per-trade style
schedule and the candidate ranking in Implementation Scope item 6a.

The result must expose an auditable monthly style schedule containing review date,
assigned style, classifier result, confidence/score, and fallback reason where used.

## Implementation Scope

### 1. Monthly style scheduler

Add a small, testable helper that invokes the existing point-in-time regime
classifier only on monthly review dates. It must not produce a daily style-routing
signal. The helper should return both the monthly assignments and review metadata.

Likely location: [curves/calibration/regime.py](../../curves/calibration/regime.py),
or a focused Alpha backtest helper if keeping calendar scheduling out of the
classifier module is cleaner.

### 2. Trend engine

Replace the directional-change (DC) extremum/reversal state machine in
[web/tabs/alpha/backtest/engine_trend.py](../../web/tabs/alpha/backtest/engine_trend.py)
with a MAD/z-score momentum hysteresis state machine (see item 2b for the design
decision and the deferred alternatives it was chosen over).

**Signal:**

1. `momentum_t = s_t - s_{t-k}`, the k-day change in the spread level (`k` = the
   existing `mom_window` parameter, e.g. 20 days) — this repurposes a parameter that
   carried no weight in the DC design.
2. `sigma_t` = a continuously updated robust volatility estimate of `momentum_t`
   (reuse the existing MAD-based `_robust_daily_scale` helper, scaled to the
   `k`-day horizon), recomputed **every day**, not frozen monthly. This removes the
   need for `_build_monthly_theta_schedule`: the old design could go stale for up to
   a month after a volatility regime shift; a daily rolling normalization cannot.
3. `z_t = momentum_t / sigma_t`.
4. **Hysteresis state machine** (Schmitt trigger, single parameter `theta_z`, e.g.
   1.0–1.5): flip to `+1` (uptrend) when `z_t >= +theta_z`; flip to `-1` (downtrend)
   when `z_t <= -theta_z`; otherwise hold the previous state. State starts at `0`
   before the first crossing. Implement as a vectorised forward-fill exactly like
   `trend_state_machine` in
   [curves/calibration/trend.py](../../curves/calibration/trend.py) — no
   extremum-tracking loop is required, so this is simpler and fully vectorizable.

**Everything downstream of the trend-state series is unchanged:** entry
(`state > 0` → long, `allow_short and state < 0` → short), exit (opposite state flip,
gated by `min_hold`; volatility trailing stop, ungated), carry accrual, and borrow
costs. Only the function producing `trend_state` changes — `run_trend_backtest_dc`'s
trade loop itself does not need to change.

- Remove `_build_monthly_theta_schedule` and `_dc_trend_state` from the trend engine.
  Keep `generate_absolute`/`trend_state_machine` in `curves/calibration/trend.py` only
  if still needed by `compute_trend_signal` in the candidate-scoring path — confirm
  before deleting.
- Drop the now fully unused `carry_buffer` parameter. `mom_window` is repurposed as
  the momentum horizon `k` above, not removed.
- No position sizing exists today (every trade is unit ±1 regardless of `sigma_t`);
  an inverse-vol size using the same estimate above is a natural follow-up, but is
  **not required for this plan**.
- Add a re-entry cooldown (N bars) after a stop/flip exit before allowing re-entry in
  the same direction, to reduce whipsaw-driven turnover.
- The volatility trailing stop and the hysteresis-flip exit are independent and not
  reconciled; log which `exit_reason` actually dominates once backtested at scale —
  the design assumes they are complementary, not redundant.
- `theta_z` is a single global default; if some spread families are structurally
  noisier or quieter than others, consider a per-family `theta_z` before assuming one
  value fits all.
- Rename or remove diagnostics and UI text that reference DC events, momentum
  confirmation, or the monthly theta schedule.

### 2b. Design decision and deferred research variants

**Decision:** the trend engine's baseline signal is the MAD/z-score momentum
hysteresis state machine above, replacing the DC extremum/reversal state machine.
Rationale: DC's stability came from a retracement-from-extreme threshold that was
only rescaled once a month, so a mid-month volatility regime shift could leave it
stale for weeks; the frozen theta was also an opaque chain (base bp → monthly
MAD-ratio rescale → clip) versus one interpretable z-threshold. The z-momentum design
keeps the same hysteresis-for-stability mechanism, re-normalizes volatility every day,
and needs no extremum-tracking loop.

Two variants remain **deferred research**, not implementation targets, and may only
replace or augment the z-momentum baseline after anchored, family-level walk-forward
tests with next-bar execution, costs, turnover/capacity limits, and a held-out period.
Never optimize their thresholds/lookbacks separately per instrument, and never promote
one solely because its in-sample Sharpe is higher.

| Variant | Long entry | Short entry | Interpretation | Status |
| --- | --- | --- | --- | --- |
| Z-momentum continuation (baseline) | hysteresis state `> 0` | hysteresis state `< 0` | Follow the confirmed move; see item 2. | **Implementation target** |
| Trend-following pullback overlay | baseline state `> 0` and a mild pullback/reconfirmation within a configured z-band (full daily-timing spec in item 6a) | symmetric | Delays entry to a less extended level inside a confirmed trend; strictly adds lag versus the baseline in exchange for a better average fill. | Deferred research |
| Trend-conditioned fade | downtrend state and $z_t \ge z_{entry}$ | uptrend state and $z_t \le -z_{entry}$ | Counter-trend turning-point rule: fades a still-rich falling spread or a still-cheap rising spread. Can systematically enter before a persistent trend has ended; requires a separate reversal confirmation (state flip, slope reversal, or close back through an entry band) before entry. For yield-based spreads, apply the platform's normalized economic sign first — raw yield labels are otherwise easy to reverse. | Deferred research |

Exits for either deferred variant should still include a hard adverse-move/volatility
stop, a defined mean-reversion target, a maximum holding period, and a regime change —
never rely on the entry condition alone to imply a safe exit.

### 3. Mean-reversion engine

Update [web/tabs/alpha/backtest/engine_mr.py](../../web/tabs/alpha/backtest/engine_mr.py)
so that entry is governed by the z-score threshold only. Preserve carry and borrow
economics in realized PnL, but remove carry from the entry-score adjustment.

### 4. Backtest orchestration

Replace the daily adaptive routing in
[web/tabs/alpha/backtest/engine_hybrid.py](../../web/tabs/alpha/backtest/engine_hybrid.py)
with a monthly fixed-style orchestrator, preferably under a name such as
`run_monthly_style_backtest`.

For each historical month, the orchestrator must:

1. obtain the point-in-time monthly assignment;
2. apply the fixed MR or trend rule for new entries, selecting each candidate's
   engine from its own monthly regime (see Implementation Scope item 6a);
3. never switch styles within the month;
4. close an open position only when the following month's assigned style changes;
5. return `style_schedule` and style/review data alongside existing trade and equity
   results.

The former adaptive `hybrid` engine should be removed from the user-facing product,
not retained as a legacy option.

### 5. UI and callback wiring

Update [web/tabs/alpha/callbacks/backtest_tab.py](../../web/tabs/alpha/callbacks/backtest_tab.py)
and its associated layout:

- Remove the `Auto Regime (MR / Trend)` / `hybrid` selector and dispatch path.
- Display current monthly style, effective review date, and next review date.
- Remove obsolete momentum and carry-entry controls. Retain controls that still
  affect the trend hysteresis threshold (`theta_z`), trailing stop, minimum hold, and
  short permission.
- Render monthly review markers or a compact review audit table.
- Route portfolio trades by their own point-in-time monthly style schedule; do not
   introduce daily regime switching in portfolio mode. The portfolio implementation
   details are specified in the Portfolio Walk-Forward Extension below.

### 6. Candidate scoring separation

Update [curves/refreshers/alpha_scoring.py](../../curves/refreshers/alpha_scoring.py)
and [curves/refreshers/alpha_candidates.py](../../curves/refreshers/alpha_candidates.py):

- Candidate expected-return scores remain cross-sectional ranking and allocation
  measures, computed with one shared method for candidates of every regime (see 6a).
- A trend/regime agreement multiplier must not act as a hidden entry filter. Remove
  the current `regime_boost`, or replace it with a separately documented ranking-only
  adjustment.
- Preserve regime details only for the monthly review decision and audit trail.

### 6a. Monthly candidate ranking and regime-routed backtest selection

At each monthly review, first classify every eligible candidate in the universe —
not only currently open trades — into `trending`, `mean_reverting`, or `uncertain`
using only information available through the review close (the same classifier used
for the per-trade Monthly Style Review above). This produces one shared regime label
per candidate per month that feeds both the trade-level style schedule and the
ranking below; it is not a daily entry confirmation.

- **Scoring:** score every classified candidate with the platform's existing combined
   carry + z-score expected-return score, regardless of regime. Do not introduce a
   separate scoring formula for trend candidates; reuse one method so rankings stay
   comparable across regimes, subject to stationarity and execution-feasibility
   requirements.
   - **Open decision, needs validation:** rank `trending` and `mean_reverting`
     candidates **within their own bucket** (two separate leaderboards) or
     **together as one cross-sectional ranking** before allocation. Start with
     separate within-regime ranking, since entry/exit rules are already
     regime-specific, and validate the pooled alternative only with
     family-level walk-forward evidence.
   - `uncertain` candidates score and rank under the spread category's static
     default style; they do not form their own third ranking tier.
- **Extreme-score filter:** after ranking, exclude any candidate whose score implies
   entering against an extended dislocation — buying an already-rich level or selling
   an already-cheap level relative to its assigned direction. This reuses the
   chase-prevention stretch-bound concept defined for the daily continuation-timing
   signal below, applied here as a monthly universe-level filter rather than a daily
   one. Document the stretch bound and report how many candidates it removes each
   month.
- Apply correlation, capacity, DV01, and margin constraints after the regime-specific
   rank and extreme-score filter. Persist the review date, source-data as-of
   timestamp, factor inputs, regime, score, and selected allocation in the monthly
   snapshot.
- **Backtest routing:** in both the individual-trade and portfolio backtests, select
   the strategy engine from each candidate's own monthly regime —
   `mean_reverting`/default style routes to the z-score-only MR engine, `trending`
   routes to the trend engine — per the Backtest orchestration rules in
   Implementation Scope item 4. Never run a trend candidate's history through the MR
   engine, or vice versa, within the same month.

A direction-specific, risk-normalized carry--momentum rank — for example
$R_{i,d}=w_C z(C_{i,d})+w_M z(M_{i,d})$ with $w_C=w_M=0.5$, where $d$ is BUY or
SELL — remains a possible **research alternative** to the combined carry+z-score
score above for trend candidates specifically. Evaluate it, if at all, only through
the same family-level anchored walk-forward process required for the other research
variants below; do not adopt it as the baseline without that evidence.

For a trend candidate selected at the monthly review, use a separate daily
continuation-timing signal. In economic-PnL orientation, require: (1) positive fast
and slow trend slopes, (2) positive acceleration, (3) a mild pullback that respects
the slow trend, and (4) a reconfirmation through the fast trend estimate. Reject an
entry when the residual z-score is outside a configured absolute stretch bound. The
z-score is a chase-prevention veto, not a directional signal. The short rule is the
sign-symmetric counterpart. Exit on an opposite confirmed trend-state flip, volatility
trailing stop, or persistent slope reversal. Carry and the monthly rank are never
intramonth entry or exit gates.

Treat this trend-following pullback signal as a named research variant alongside the
z-momentum continuation baseline (item 2b). It may replace or augment the baseline
only after anchored, family-level walk-forward tests with next-bar execution, costs,
turnover/capacity limits, and a final held-out period.

### 7. Documentation

Update [docs/report/AtlasNexus_Model_Methodology.md](../report/AtlasNexus_Model_Methodology.md)
to describe the monthly review process, z-score-only MR entry, the z-score momentum
hysteresis trend entry, and the monthly style-change closure rule.
Remove claims about daily hybrid routing, momentum confirmation, and spread-level
carry gates.

## Test Plan

Add or extend tests under [tests](../../tests):

1. Trend hysteresis state is correct for positive, inverted, and near-zero spread
   series (sign flips consistently under negation; no divide-by-zero when volatility
   is flat).
2. Trend entry occurs after a hysteresis crossing without carry gating.
3. No trend entry occurs before the first hysteresis crossing.
4. Hysteresis-flip and trailing-stop exits remain correct.
5. Monthly style uses only data available on or before its review date.
6. Style remains constant within a calendar month.
7. A changed style closes an open trade exactly once with
   `monthly_style_change`; an unchanged style does not force an exit.
8. MR entries follow z-score thresholds regardless of carry values.
9. The UI/callback path no longer accepts the removed `hybrid` selection.

## Validation Sequence

1. Run focused trend-hysteresis and monthly-style tests.
2. Run the full `pytest` suite.
3. Use a deterministic two-month fixture to inspect review timestamps, style
   schedule, and forced style-change exits.
4. Backtest both a yield-based inverted spread and a non-inverted spread, verifying
   that they use the same z-momentum hysteresis definition.
5. Run the dashboard and verify the Backtest tab has no hybrid mode, no unused
   momentum/carry entry controls, and visible monthly-review status.

## Explicitly Out of Scope

- Recalibrating or redesigning the multi-indicator regime classifier.
- Futures HMM regime work.
- Portfolio optimization and allocation methodology.
- Transaction-cost model changes.
- Other unrelated Alpha Book issues.

These should be handled as separate research or implementation workstreams after the
simplified model has a tested baseline.

---

## Portfolio Walk-Forward Extension

### Objective

Backtest the positions in the current Alpha Portfolio as a sequence of historically
available monthly portfolios. Each instrument must use the MR or trend engine selected
from its own point-in-time regime at that month's review. Aggregate only the resulting
daily PnL of positions that were eligible and allocated at that date.

This replaces the current Portfolio Backtest's ``current-book sanity view'': it loads
today's persisted allocation, applies its weights retroactively, and routes an asset to
the trend engine only when its stored style contains the string ``trend''. That is not a
causal portfolio backtest; stored portfolio styles are commonly normalized to
``momentum'', so they can currently fall through to the MR engine.

### Required Decisions

The following conventions must be explicit and shared by individual and portfolio
backtests:

1. **Review schedule:** first available observation of each calendar month; all features
   and allocation inputs are cut off at that close.
2. **Trade timing:** generate a signal at review-close or daily close, then execute at
   the next available close/open with configurable one-bar delay. The baseline should
   use next-bar execution to avoid same-observation fills.
3. **Style lifecycle:** a monthly style change closes an existing position at the
   scheduled execution price before the new style may open a replacement. A style that
   does not change leaves an open position intact.
4. **Allocation lifecycle:** rebalance the portfolio monthly from a point-in-time
   candidate universe. Existing positions removed from the eligible allocation are
   closed; retained positions are resized and new positions may be opened only after
   their own engine emits an entry signal.
5. **Uncertain regime:** choose and record one policy: no new trade, retain the prior
   style for an existing trade, or use the family default. The recommended baseline is
   ``no new trade; retain/close only under the explicit portfolio lifecycle rule''.
6. **Accounting:** use a single net-return convention: position DV01/notional,
   bid--ask and fees on every fill, financing/borrow/carry by day, turnover, gross and
   net PnL, capital return, and daily return-based Sharpe.

### Implementation Steps

1. **Create a stateful single-instrument runner.** Add a pure module under
   `web/tabs/alpha/backtest/` that accepts a daily spread, an ordered monthly style
   schedule, and an optional initial trade state. It must carry position, entry level,
   best favorable level, carry accrual, and engine style across month boundaries.
   Do not stitch independent month-local backtests: that can duplicate trades and does
   not preserve an open position or its stop anchor across a review boundary.

2. **Make monthly style routing canonical.** Move the duplicated schedule helper from
   `backtest_tab.py` into the new backtest module. The schedule row should include
   `review_date`, `effective_date`, `regime`, `regime_score`, `assigned_style`,
   `fallback_reason`, and frozen trend parameters. Resolve style aliases at this
   boundary: `mr`/`mean-reverting` and `trend`/`trending`/`momentum`.

3. **Preserve engine semantics while adding state.** Reuse the existing MR z-score,
   stop, trend-state, trailing-stop, and carry functions. Refactor their common
   position transition logic only enough to expose a daily state transition; do not
   maintain separate rules for individual and portfolio execution.

4. **Build a monthly portfolio snapshot provider.** Persist a dated Alpha allocation
   snapshot after each scoring run, including candidate universe, selected weights,
   direction, style/regime inputs, risk settings, and source-data as-of timestamp.
   Historical runs must read only snapshots available on or before each review; absence
   of an archived snapshot should be reported as a data gap, never silently replaced
   with today's `summary_alpha_portfolio.parquet`.

5. **Add `run_alpha_portfolio_walk_forward`.** Given dated portfolio snapshots and
   price/carry data, run each eligible instrument's stateful schedule, apply weight and
   position sizing at each rebalance, charge entry/exit/rebalance costs, and aggregate
   aligned daily net returns. Return portfolio equity, daily gross/net returns, trade
   ledger, rebalance ledger, monthly regime/style audit, exposure/DV01 series, and
   missing-data diagnostics.

6. **Replace the current Portfolio Backtest callback gradually.** Keep its present
   chart as ``Current-book historical sanity view'' while introducing a distinct
   ``Walk-forward regime portfolio'' mode. The new mode must call the portfolio runner,
   not re-run `run_spread_backtest` or `run_trend_backtest_dc` independently with
   today's weights.

7. **Apply execution and cost inputs.** Wire `bt-initial-capital` and `bt-txn-cost`
   into the portfolio runner. Transaction cost must apply to each initial fill,
   reversal, forced style close, and rebalance resize. The current callback parses both
   values but does not use them in PnL.

8. **Migrate and label reporting.** Display the as-of range, number of historical
   rebalance snapshots, gross/net return, turnover, costs, capacity, and any missing
   snapshot coverage. Do not call a current-allocation replay a portfolio strategy
   backtest.

### Acceptance Tests

1. A monthly regime label and allocation use no observation after their review date.
2. A position remains continuous across a same-style month boundary, retaining entry
   price and trailing-stop high/low watermark.
3. A style change produces exactly one forced close and no double-counted carry or
   transaction cost.
4. A `momentum` portfolio style routes to the trend implementation after canonical
   alias resolution.
5. Changing a historical allocation only affects PnL after that allocation's effective
   date; it cannot revise earlier portfolio weights.
6. A one-bar execution delay changes fills predictably in a deterministic fixture.
7. Gross PnL minus explicit costs equals net PnL, and weighted position returns equal
   aggregate portfolio return each day.
