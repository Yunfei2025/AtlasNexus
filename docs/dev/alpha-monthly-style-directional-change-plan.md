# Alpha Book: Monthly Style Review and Directional-Change Entry Plan

**Status:** Approved implementation plan

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
- Keep portfolio backtests fixed to each candidate's stored style; do not introduce
  daily regime switching in portfolio mode.

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