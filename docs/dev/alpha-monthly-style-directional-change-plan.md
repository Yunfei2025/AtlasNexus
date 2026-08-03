# Alpha Book: Monthly Style Review and Directional-Change Entry Plan

**Status:** Approved individual-trade design; portfolio walk-forward extension planned

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
| Trend | Enter long after an upward confirmed directional-change event; enter short after a downward confirmed event when shorts are enabled. | Exit on an opposite confirmed directional-change event or the existing volatility trailing stop. | Accrue in realized PnL and use in ranking, but do not confirm, veto, or reverse entry. |

Trend entries must use an **absolute** directional-change threshold in spread units.
This is required for stable behavior on inverted yield spreads and near-zero or
zero-crossing series.

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

Update [web/tabs/alpha/backtest/engine_trend.py](../../web/tabs/alpha/backtest/engine_trend.py):

- Replace relative directional-change generation with the canonical absolute
  generator from [curves/calibration/trend.py](../../curves/calibration/trend.py).
- Remove normalized-momentum confirmation from entry logic.
- Remove spread-level `carry_buffer` gating from entry and signal exits.
- Retain directional-change reversal, volatility trailing stop, minimum-hold policy,
  carry accrual, borrow costs, and the existing result contract where applicable.
- Rename or remove diagnostics and UI text that imply momentum confirmation.

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
2. apply the fixed MR or DC-trend rule for new entries;
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
  affect DC threshold, trailing stop, minimum hold, and short permission.
- Render monthly review markers or a compact review audit table.
- Route portfolio trades by their own point-in-time monthly style schedule; do not
   introduce daily regime switching in portfolio mode. The portfolio implementation
   details are specified in the Portfolio Walk-Forward Extension below.

### 6. Candidate scoring separation

Update [curves/refreshers/alpha_scoring.py](../../curves/refreshers/alpha_scoring.py)
and [curves/refreshers/alpha_candidates.py](../../curves/refreshers/alpha_candidates.py):

- Candidate expected-return scores remain cross-sectional ranking and allocation
  measures.
- A trend/regime agreement multiplier must not act as a hidden entry filter. Remove
  the current `regime_boost`, or replace it with a separately documented ranking-only
  adjustment.
- Preserve regime details only for the monthly review decision and audit trail.

### 7. Documentation

Update [docs/report/AtlasNexus_Model_Methodology.md](../report/AtlasNexus_Model_Methodology.md)
to describe the monthly review process, z-score-only MR entry, absolute
directional-change-only trend entry, and the monthly style-change closure rule.
Remove claims about daily hybrid routing, momentum confirmation, and spread-level
carry gates.

## Test Plan

Add or extend tests under [tests](../../tests):

1. Absolute directional-change state is correct for positive, inverted, and
   near-zero spread series.
2. Trend entry occurs after a confirmed DC event without momentum or carry gating.
3. No trend entry occurs before the first confirmed DC event.
4. DC reversal and trailing-stop exits remain correct.
5. Monthly style uses only data available on or before its review date.
6. Style remains constant within a calendar month.
7. A changed style closes an open trade exactly once with
   `monthly_style_change`; an unchanged style does not force an exit.
8. MR entries follow z-score thresholds regardless of carry values.
9. The UI/callback path no longer accepts the removed `hybrid` selection.

## Validation Sequence

1. Run focused directional-change and monthly-style tests.
2. Run the full `pytest` suite.
3. Use a deterministic two-month fixture to inspect review timestamps, style
   schedule, and forced style-change exits.
4. Backtest both a yield-based inverted spread and a non-inverted spread, verifying
   that they use the same absolute DC definition.
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
   stop, DC state, trailing-stop, and carry functions. Refactor their common position
   transition logic only enough to expose a daily state transition; do not maintain
   separate rules for individual and portfolio execution.

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

## Trend-Conditioned Z-Score Research

The proposed rule, stated generically as ``buy in a downward trend when z-score is
positive, sell in an upward trend when z-score is negative'', is a **counter-trend
turning-point** rule, not a trend-following rule, when a long position profits from an
increase in the normalized spread. It attempts to fade a still-rich falling spread or a
still-cheap rising spread. It may be a valid relative-value signal, but it can also
systematically enter before a persistent trend has ended. For yield-based spreads,
apply the platform's normalized economic sign before interpreting long/short; raw
yield labels are otherwise easy to reverse.

Treat this as a separately named research strategy rather than an untested amendment
to the baseline DC trend engine. Evaluate three mutually exclusive specifications:

| Variant | Long entry | Short entry | Interpretation |
| --- | --- | --- | --- |
| DC continuation baseline | confirmed upward DC state | confirmed downward DC state | Follow the confirmed move. |
| Trend-following pullback | upward DC state and $z_{min} \le z_t \le z_{max}$ after a pullback/reconfirmation | symmetric | Join the trend at a less extended level; avoids buying the most overextended continuation. |
| Trend-conditioned fade | downward DC state and $z_t \ge z_{entry}$ | upward DC state and $z_t \le -z_{entry}$ | The proposed logic; fades a trend only when the moving-average dislocation remains large. |

For the fade variant, require a separate reversal confirmation before entry, such as a
DC reversal, a short-horizon slope reversal, or a close back through an entry band.
Without that confirmation, ``downtrend plus positive z-score'' can be merely the early
part of a large continued decline. Exits should be a hard adverse move/volatility stop,
mean reversion to a defined z-score target, a maximum holding period, and a regime
change. Never optimize the entry z-score, moving-average lookback, DC threshold, and
stop separately per instrument.

Select among the baseline and research variants only with family-level, anchored
walk-forward tests, next-bar fills, costs, turnover/capacity limits, and a final held-out
period. Report incremental net return, downside risk, turnover, and parameter stability;
do not promote a variant solely because its in-sample Sharpe is higher.