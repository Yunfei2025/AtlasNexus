# TBondCurve: 30Y CGB OTR/OFR Relative-Value Implementation Plan

## Decision

Implement the 30Y China Government Bond (CGB) on/off-the-run strategy **within the existing `TBondCurve` spread type**.

Do not extend the current fitted Treasury curve beyond 10 years. The existing curve pricing filter and calibration range are deliberately limited to 1–10 years (`BondConfig.PRICING_MIN_TTM`, `PRICING_MAX_TTM`, and `FIT_MAX_TTM`). The new strategy is a cash-bond, on/off-the-run liquidity relative-value signal, not a 30Y model-curve residual.

Represent the distinction explicitly in data and artifacts:

```text
spread_type: TBondCurve
signal_variant: model_curve | otr_ofr_event | otr_ofr_rv
instrument: <ofr_bond_id>|<otr_bond_id>
leg1: OFR bond
leg2: OTR bond
spread: ytm_ofr - ytm_otr
```

`model_curve` is the existing 1–10Y fitted-curve residual. `otr_ofr_event` is the
short-horizon, new-issue roll-pressure trade; `otr_ofr_rv` is the mature-pair
liquidity-premium relative-value trade. This retains the existing Alpha candidate,
sizing, portfolio, and backtest plumbing while keeping the strategy economically
auditable.

`otr_ofr_rv` and `model_curve` may share the existing `TBondCurve` statistical-test
and parameter-calibration framework, but they must retain `signal_variant` in every
input, output, and performance report. Pool standardized residuals or use partial
pooling for family-level parameters (for example, minimum history, z-score
lookbacks, cost buffers, and risk caps); do not pool raw spread levels or silently
assume that the two variants have identical dispersion, stationarity, turnover, or
post-roll behavior. Validation and promotion remain variant-level, with pooled
parameters adopted only when they improve out-of-sample net performance for both
variants or do not degrade either one.

## Economic Definition

For an eligible pair, define the raw yield spread as:

$$
s_t = y_t^{OFR} - y_t^{OTR}.
$$

A positive/wide spread means the OFR bond is cheap relative to the OTR bond. The mean-reversion trade is:

- buy the OFR bond;
- sell the OTR bond;
- hedge the cash legs DV01-neutral.

For an OFR notional $N_{OFR}$, calculate the OTR notional as:

$$
N_{OTR} = N_{OFR}\frac{DV01_{OFR}}{DV01_{OTR}}.
$$

The candidate must expose residual duration, convexity, gross notional, all-in funding cost, OTR borrow cost, bid/offer, and liquidity diagnostics. `TL` futures can be a secondary residual long-end hedge, but must not replace cash-leg DV01 hedging because it adds CTD and conversion-factor basis risk.

## Cold-Start and Historical-Data Policy

### Do not splice unrelated pairs into a synthetic z-score

A new OTR changes one of the constituents. Its new OTR/OFR pair has zero pair-specific observations on the issuance/roll date. Historical OTR/OFR spreads are useful for research and threshold calibration, but they are **not** a substitute for the new pair's own history.

Maintain two distinct datasets:

1. **Pair history** — the actual time series for a fixed OFR/OTR pair. This is the only history used for pair z-scores, stationarity, and live signal generation.
2. **Rolled historical panel** — point-in-time historical OTR/OFR observations, including the eligible pair at each date and its OTR age. It supports research, cohort statistics, and walk-forward threshold calibration only.

Never select an OTR/OFR constituent using later information when constructing the rolled historical panel.

### Cold-start states

| State | Minimum valid post-roll observations | Behaviour |
|---|---:|---|
| `event_eligible` | 0–19 | Allow only the separately validated `otr_ofr_event` signal, with a small risk cap, a completed historical issuance-cohort calibration, live executable quotes, and available borrow. Otherwise observe only. Never generate a pair z-score. |
| `descriptive` | 20–59 | Calculate pair diagnostics. The issuance-event position may run only to its pre-specified event horizon; the mature-pair RV strategy remains untradeable. |
| `regime_ready` | 60–119 | Run the monthly regime classifier for diagnostics, but keep the pair untradeable because it lacks an MR z-score history. |
| `trade_ready` | 120+ | Allow the `otr_ofr_rv` candidate to use standard `TBondCurve` scoring and style routing, subject to liquidity/cost filters. |

An OTR roll must close the predecessor pair or record an explicit `otr_roll` close/replace event. Do not silently concatenate predecessor and successor series.

### Analogue prior

Build a monitoring-only historical analogue distribution from prior 30Y OTR/OFR pairs conditioned on:

- OTR age since issuance;
- OTR and OFR remaining-maturity buckets;
- DV01 hedge ratio;
- turnover/quote-quality bucket;
- available borrow/repo state where available.

Expose its percentile as `analogue_percentile`; use the distribution for family-level entry-cost buffers and threshold research. It must not generate a synthetic pair z-score, stationarity statistic, or trade before `trade_ready`.

## New-Issue Roll-Pressure Variant (`otr_ofr_event`)

### Economic hypothesis and sign convention

The issuance event can itself be traded, provided it is represented as a distinct,
short-horizon event strategy. A rush to buy the new OTR and to sell or short the
prior OTR (which becomes first OFR) normally makes the new OTR rich and the first
OFR cheap. With the yield convention

$$
s^{1OFR-OTR}_t = y^{1OFR}_t - y^{OTR}_t,
$$

the expected initial effect is a **widening** of $s^{1OFR-OTR}$: the first-OFR yield
rises while the new-OTR yield falls. If the first OFR is compared with the second OFR,

$$
s^{1OFR-2OFR}_t = y^{1OFR}_t - y^{2OFR}_t,
$$

selling pressure concentrated in the first OFR also normally widens this yield spread.
The apparently opposite ``narrowing'' description can arise when a price spread is
used instead. All artifacts and user interfaces must retain the yield convention and
display the sign explicitly.

The event trade is long the new OTR and short the first OFR, sized DV01-neutral. It
is a directional, event-driven position, not a mean-reversion entry. It may be opened
only after the new OTR is identified and the current pair passes executable quote,
turnover, and borrow checks. Its entry window, stop, and forced exit are measured in
OTR trading age, rather than in a pair z-score. The mature `otr_ofr_rv` strategy has
the opposite economic objective when an observed OTR premium later normalizes: long
first OFR and short OTR.

### Cohort model

Build a point-in-time historical issuance-event panel. For each historical 30Y
issuance, select that date's new OTR, first OFR, and second OFR using only data known
at the date, then align returns and yield spreads by OTR age (for example, $-5$ to
$+60$ trading days). This is **event-time seasonality**, not calendar-month
seasonality: day $+k$ is the $k$th trading day after issuance, and the model asks
whether the new-OTR versus first-OFR spread historically tends to widen, peak, or
decay at that issuance age. The trading object remains the DV01-neutral pair (long
new OTR / short first OFR), never a standalone bond. Estimate an expected path and
dispersion conditional on:

- OTR age, auction size/tail/bid-cover when available, and issue characteristics;
- OTR/first-OFR/second-OFR turnover and quote quality;
- prevailing long-end volatility and rate-direction regime;
- residual maturity, DV01 hedge ratio, and available funding/borrow state.

The live event score is an out-of-sample percentile against this historical cohort,
not a fabricated z-score of the new pair. Walk-forward calibration must leave each
issuance episode out of its own training sample. The model should use a small
event-risk budget until it has a sufficient number of independent issuance episodes
and demonstrates positive performance after bid/offer, financing, borrow, and roll
costs.

### Data readiness as of 2026-07-31

The local data support a **prototype event study**, but not a production-ready,
feature-conditioned event model:

- `database/TBond-px.pkl` contains daily close prices from 2019-09-10 through
   2026-06-30 (1,654 rows) and daily volume from 2019-01-02 through 2026-06-30
   (1,815 rows).
- Current `TBond-InstrumentInfo.pkl` contains 15 identifiable 30Y CGB issues from
   2021-10 through 2026-06; 14 have historical close/volume coverage in the local
   database. This is roughly 14 observable issuance episodes, with a denser issuance
   cadence only from 2024 onward.
- The historical price store contains `Close`, `Volume`, `CBClean`, and `CBDirty`;
   it does **not** contain historical executable bid/offer, repo, short-borrow, or
   auction-result fields.
- The current instrument-definition file does not by itself provide the earlier 30Y
   issuance cohorts needed for a robust multi-cycle study.

Accordingly, use the present data to validate OTR selection, identify roll dates,
construct DV01-neutral close-to-close prototypes, and estimate broad unconditional
event paths. Do not optimize several conditional features or approve live event
allocation from approximately 14 episodes. Before production, retrieve and archive
older 30Y CGB definitions and daily yield/quote history, auction data, and where
possible repo/borrow proxies. Set a pre-declared minimum number of independent
issuance episodes for production approval (recommended: at least 30--40, covering
multiple rate-volatility and supply regimes).

### Secondary-market-only fallback before primary-market history is available

The absence of historical auction, executable bid/offer, repo, and borrow data does
not prevent a research or shadow-trading implementation, but it prevents a claim of
fully executable historical net performance. Until the primary-market dataset is
obtained, use the following deliberately conservative fallback:

1. Define the event date from the instrument's carry/issue date and use the first
   available secondary-market trading day as event day $0$.
2. Select the new OTR and first OFR point-in-time from issue metadata plus observed
   secondary-market turnover; retain the second OFR as a diagnostic control, not as
   a replacement trading leg.
3. Convert historical clean/dirty closes to yields using the recorded coupon and
   cash-flow convention where reliable; otherwise calculate the DV01-neutral pair's
   close-to-close PnL directly in price space. Do not mix price and yield signs.
4. Build an unconditional issuance-age expected path and robust dispersion from the
   available episodes. With the current small sample, use this only as a direction
   and timing prior, not as a heavily segmented machine-learning model.
5. Require live confirmation before an event trade: valid two-sided current quotes,
   positive turnover in both legs, a widening of the yield spread consistent with the
   historical event path, and a conservative assumed all-in cost/stress buffer.
6. Run the signal in paper/shadow mode while capturing prospective bid/offer, quote
   timestamps, repo, borrow, and any auction observations. These prospective records
   become the production-quality event dataset.
7. Keep event allocation at zero until the pre-declared issuance-episode and
   execution-data gates are satisfied. If an exploratory live pilot is ever approved,
   it must use a separately approved, capped research risk budget rather than normal
   Alpha allocation.

## Style Policy

The default economic hypothesis is **mean reversion**, after the new-issue liquidity premium has stabilized. An OFR can trade cheap to an OTR because of benchmark demand, liquidity, and financing; the spread may normalize after the initial issuance period.

Fresh-issue periods can nevertheless be trending due to auction supply, dealer inventory, index demand, special repo, or a short squeeze. Therefore:

1. The default `TBondCurve` family style stays `MeanReversion` for `model_curve` and mature `otr_ofr_rv` candidates.
2. `otr_ofr_event` is a separately labelled event-driven directional strategy, available only during its configured post-issuance window and only after cohort validation.
3. Cold-start/uncertain pairs are not forced into the mature MR or trend engines.
4. Once 60 observations exist, the existing monthly point-in-time regime process can classify the mature pair.
5. Only after 120 observations can the mature `otr_ofr_rv` pair be allocated through standard Alpha scoring. A mature `trending` classification may use the trend engine; a mature `mean_reverting` classification uses the MR engine.
6. The backtest must use the same event eligibility, post-roll availability gates, and roll events as production.

## Production Trading Operating Model

The two OTR/OFR variants must be implemented as independently enabled, executable
strategies under the common `TBondCurve` type. They may share data plumbing and
portfolio risk controls, but neither variant may become tradeable merely because the
other passes validation.

### Candidate-to-order state machine

Every OTR/OFR candidate must persist one of the following states in the Alpha
artifact, with a machine-readable `block_reason` whenever it is not order-eligible:

```text
DISCOVERED
  -> DATA_VALIDATED
  -> SIGNAL_READY
  -> RISK_APPROVED
  -> ORDER_ELIGIBLE
  -> ORDER_SUBMITTED
  -> FILLED | PARTIALLY_FILLED | CANCELLED | REJECTED
  -> OPEN
  -> EXIT_PENDING
  -> CLOSED
```

`otr_ofr_rv` reaches `SIGNAL_READY` only with pair-specific post-roll history,
the appropriate mature-pair style/routing decision, and a net-of-cost expected edge.
`otr_ofr_event` reaches `SIGNAL_READY` only during its configured OTR-age entry
window, after a valid walk-forward cohort score and live event-path confirmation.
`RISK_APPROVED` requires both variants to pass the same live checks: two-sided quotes,
fresh quote timestamps, turnover/liquidity thresholds, leg eligibility, short/borrow
availability, margin/funding assumptions, DV01-neutral sizing, gross/notional limits,
and portfolio correlation/concentration limits.

The order ticket must include both leg identifiers, buy/sell side, DV01 ratio,
target notional, maximum permitted execution spread, expected all-in cost, current
signal score, variant, OTR age, and the full decision timestamp. The execution layer
must submit, amend, cancel, and reconcile the two legs as a linked pair; it must not
leave an unhedged first leg open beyond an explicitly configured short execution
window. Any residual fill creates an immediate hedge alert and is counted against a
separate temporary unhedged-risk limit.

### Variant-specific production rules

| Control | `otr_ofr_rv` (mature liquidity RV) | `otr_ofr_event` (new-issue roll pressure) |
|---|---|---|
| Trading legs | First OFR vs current OTR | New OTR vs first OFR |
| Entry model | Pair z-score / mature monthly MR-or-trend routing | Walk-forward issuance-age cohort score plus live widening confirmation |
| Minimum pair history | 120 valid post-roll observations | No pair history required; historical-cohort approval required |
| Entry window | Any eligible mature trading day | Configured OTR-age window only |
| Mandatory exit | Signal exit, stop, loss of leg eligibility, or next roll | Event-horizon exit, stop, loss of leg eligibility, or next roll |
| Initial risk budget | Small production sleeve after variant-specific validation | Zero until execution-quality dataset and issuance-episode gate are met; then separately approved capped pilot |
| Performance attribution | Pair alpha, carry/roll, borrow/funding, execution, residual DV01/convexity | The same fields plus cohort-score, OTR-age, and event-window attribution |

### Data, execution, and risk gates

The following gates are mandatory configuration values, not informal operator
judgement. A failed gate blocks the candidate and writes a reason to the run artifact:

1. **Constituent gate:** current OTR, first OFR, and optional second-OFR control are
   determined point-in-time from the eligible 30Y CGB universe.
2. **Quote gate:** both trade legs have fresh bid and offer quotes, and the estimated
   executable pair bid/offer is no wider than the configured maximum.
3. **Liquidity gate:** both legs exceed configured recent turnover and minimum
   observable trading-day thresholds; stale close-only observations cannot pass.
4. **Funding gate:** shortability/borrow and financing inputs are present and their
   stressed cost leaves a positive expected net edge. A missing borrow observation is
   a block, not a zero-cost assumption.
5. **Risk gate:** actual leg DV01s generate a hedge ratio within tolerance; gross
   notional, single-trade DV01, residual convexity, sector concentration, and alpha
   correlation remain inside limits.
6. **Model gate:** the exact versioned parameters, eligible universe, and historical
   data cut-off are stored before an order can be created.
7. **Kill-switch gate:** invalid quote, leg delisting, borrow recall, failed hedge
   fill, or data-feed failure blocks new orders and creates an immediate review alert.

### Release criteria

`otr_ofr_rv` may progress from shadow trading to a capped production sleeve after:

- point-in-time backtest and walk-forward validation including all OTR rolls;
- a prospective shadow period that records executable quotes and fill simulations;
- positive net performance after conservative cost/borrow assumptions across a
  pre-declared evaluation period;
- documented risk-limit approval and successful order/hedge/reconciliation tests.

`otr_ofr_event` has an additional prerequisite: the historical issuance cohort must
meet its pre-declared minimum episode count and contain execution-quality data. The
current close/volume-only history can support implementation and shadow monitoring,
but not production event allocation. Once the data gate is met, release first to a
small, separately approved pilot sleeve; expand only after the prospective pilot
confirms that observed execution costs and event timing agree with the model.

### Daily operating workflow

1. Refresh instrument definitions, historical/real-time quotes, turnover, and
   funding/borrow inputs.
2. Rebuild the point-in-time OTR/OFR universe and identify roll events.
3. Calculate both variants, run all gates, and persist blocked as well as eligible
   candidates.
4. Generate pair tickets only for `ORDER_ELIGIBLE` candidates.
5. Reconcile fills, recompute the actual DV01 hedge ratio, and alert on residual
   unhedged exposure.
6. Mark open positions, carry, funding, borrow, realized/unrealized PnL, and
   variant-specific attribution.
7. At end of day, archive the full decision/market-data snapshot so every live trade
   can be replayed without look-ahead.

## Implementation Phases

### Phase 1 — Configuration and canonical identifiers

1. Add `TBOND_CURVE_VARIANTS = {"model_curve", "otr_ofr_event", "otr_ofr_rv"}` and 30Y OTR/OFR parameters in `settings/fixed_income.py`.
2. Parameters should include:
   - target tenor: `30.0` years;
   - eligible OTR-age floor/ceiling;
   - OFR maturity-distance tolerance;
   - minimum valid turnover;
   - maximum bid/offer width;
   - maximum allowed OTR borrow cost;
   - 20/60/120 observation gates;
   - entry-cost buffer.
   - event-entry age window, forced exit age, event-risk cap, and event stop;
   - minimum number of historical issuance episodes before event strategy activation.
3. Keep `TBondCurve` as the external spread type. Add `signal_variant` rather than adding a second dropdown spread type.
4. Define one canonical pair ID and spread sign, for example `OFR_ID|OTR_ID`, with `spread = ytm_ofr - ytm_otr`.
5. Extend the shared `TBondCurve` calibration schema with `signal_variant`; support
   pooled standardized-residual calibration with variant-level diagnostics and
   independent out-of-sample acceptance tests.

**Acceptance criteria**

- A pair can be serialized/deserialized without ambiguity.
- Existing `TBondCurve` model-curve artifacts remain readable with `signal_variant=model_curve` as the backward-compatible default.
- Every candidate can be assigned a state and a specific order-blocking reason.

### Phase 2 — Data expansion and point-in-time OTR/OFR universe builder

1. Retrieve and archive older 30Y CGB definitions, daily yield/quote history, auction results, and funding/borrow proxies before production approval of `otr_ofr_event`.
2. Add a dedicated builder, proposed path: `curves/generators/otr_ofr.py`.
3. For each historical date, select the OTR from the eligible 30Y CGB universe using only that date's available issuance, quote, turnover, and liquidity information.
4. Select first- and second-OFR candidates from prior eligible 30Y CGB issues; prefer similar remaining maturity and executable quotes.
5. Save per-date constituent metadata:
   - `asof`, `otr_id`, `ofr_id`, `otr_issue_date`, `otr_age_days`;
   - TTM, modified duration, convexity, turnover, bid/offer, and quote timestamps;
   - DV01 hedge ratio and eligibility-rejection reason.
6. Produce fixed-pair histories, the rolled mature-pair panel, and the issuance-event panel indexed by OTR age.
7. Implement the secondary-market fallback initially and persist explicit data-quality
   flags showing whether a result uses observed execution data or a conservative proxy.

**Acceptance criteria**

- A historical replay for date $t$ never uses future bond data.
- OTR roll dates are explicit and reproducible.
- Rejected pairs state the precise failing liquidity, quote, borrow, or maturity condition.
- Event activation is blocked until the data-quality and issuance-episode minimum are met.

### Phase 3 — Spread, carry, and execution-cost artifacts

1. Persist a new `TBond-spds.pkl["BondCurve"]["OTROFR"]` branch, or an equivalent versioned sub-branch, without changing the current model-curve branch.
2. For each fixed pair calculate:
   - raw spread and first difference;
   - DV01-neutral leg ratio;
   - residual DV01 and convexity;
   - bid-side and offer-side executable spread;
   - coupon carry, roll-down, funding, borrow, and estimated transaction cost.
3. Persist `history_state`, `signal_variant`, `event_score`, `otr_age_days`, and `roll_event` in snapshot and time-series artifacts.
4. Create the rolled analogue panel separately; do not feed it as the live pair's history.

**Acceptance criteria**

- A current pair with fewer than 120 valid observations is visible but never eligible for allocation.
- All-in expected benefit can be checked against executable, not midpoint-only, costs.

### Phase 4 — Alpha loaders, candidates, legs, and portfolio risk

1. Update `web/tabs/alpha/data/loaders.py` so `TBondCurve` loads both variants and preserves `signal_variant`.
2. Update candidate construction to:
   - apply history-state gating;
   - display OTR, first OFR, second OFR, OTR age, analogue percentile, event score, and roll status;
   - use pair-specific z-score only once `trade_ready`.
3. Update `web/tabs/alpha/data/legs.py` so `TBondCurve` with `signal_variant=otr_ofr` resolves directly to `(ofr_id, otr_id)` rather than to the nearest model-curve reference bond.
4. Update duration/risk helpers to use both actual leg durations and the stored DV01 hedge ratio; do not approximate the strategy with one bond's TTM.
5. Update Alpha Portfolio allocation output to label the trade as `30Y OTR/OFR` and show both legs, gross/net notional, DV01, convexity, margin, and borrow assumptions.
6. Add the production candidate state machine, gate evaluation, and pair-ticket payload;
   persist all inputs and `block_reason` in the EOD/intraday artifacts.

**Acceptance criteria**

- Existing `TBondCurve` model-curve candidates and legs behave unchanged.
- OTR/OFR allocation is DV01-neutral to configured tolerance.
- The UI never labels the strategy as credit spread.
- A blocked candidate cannot generate a pair ticket, and every generated ticket is
   fully reproducible from its saved artifact.

### Phase 5 — Backtest and style routing

1. Extend individual and portfolio backtests to process pair-level time series only across each pair's effective interval.
2. Add a separate `otr_ofr_event` backtest path that opens only within its configured OTR-age window using the walk-forward cohort score; do not reuse the MR z-score engine as its entry rule.
3. On an OTR roll, close/replace the trade using an explicit `otr_roll` event and modeled bid/offer/transaction cost.
4. Enforce the event eligibility plus 20/60/120 mature-pair gates using only observations available at the simulated date.
5. Keep the `TBondCurve` static default as MR for mature pairs, but apply the existing monthly regime classifier only once the pair reaches `regime_ready`; allow trend routing only after `trade_ready`.
6. Report separate performance for:
   - all mature OTR/OFR pairs;
   - issuance-event and mature-RV variants;
   - individual OTR cycles;
   - OTR-age buckets;
   - gross versus net of funding/borrow/transaction costs;
   - observed versus proxy execution-cost assumptions;
   - roll-day and non-roll-day returns.

**Acceptance criteria**

- No z-score, regime, or analogue calculation has look-ahead bias.
- No event score is trained on its own issuance episode or on future issuance data.
- Roll costs and predecessor/successor transitions materially affect reported PnL where applicable.
- The strategy can be compared with the existing 1–10Y model-curve `TBondCurve` variant without mixing their histories.

### Phase 6 — Execution integration, shadow trading, and production release

1. Integrate `ORDER_ELIGIBLE` pair-ticket payloads with the existing order/ticket
   workflow; implement linked-leg submit/amend/cancel/reconciliation and temporary
   unhedged-exposure alerts.
2. Build a shadow-trading report that uses live bid/offer, observed fills where
   available, and conservative proxy costs otherwise.
3. Add monitoring for stale quotes, failed hedge fills, borrow changes, roll events,
   limit breaches, and daily variant-level PnL attribution.
4. Implement configuration-controlled kill switches for each variant and for the
   overall OTR/OFR sleeve.
5. Complete the variant-specific release checklist above; release `otr_ofr_rv`
   before `otr_ofr_event` unless their independent gates are both satisfied.

**Acceptance criteria**

- The ticket layer never sends a one-leg order without the configured linked-pair
  protection and residual-risk monitoring.
- Shadow results distinguish observed execution from proxy assumptions.
- Production enablement is configuration-controlled, auditable, and independently
  approved for each variant.

### Phase 7 — Tests and documentation

1. Add unit tests for canonical ID parsing, OTR selection, first/second-OFR selection, fixed-pair spread sign, DV01 ratio, and roll events.
2. Add point-in-time tests proving that future issuance cannot alter historical OTR selection.
3. Add backtest tests for event eligibility, each cold-start threshold, walk-forward cohort exclusion, and mandatory close/replace at a roll.
4. Update `docs/report/04_pairs_spread.tex` and the Alpha UI help text with the strategy definition, cold-start policy, and MR-versus-trend policy.
5. Add integration tests for the candidate state machine, each mandatory gate,
   linked-ticket construction, rejected/partial-fill handling, hedge reconciliation,
   and kill switches.

## Delivery Order

Implement and review in this order:

1. configuration + data schema;
2. historical OTR/OFR universe and artifacts;
3. candidate/leg/risk plumbing;
4. backtest with roll handling;
5. execution integration and shadow trading;
6. variant-specific production release;
7. UI and documentation.

Do not expose either variant for production allocation until its individual release
criteria, point-in-time validation, net-cost validation, and execution controls have
passed. The mature RV variant and issuance-event variant have separate enable flags
and separate approval gates.
