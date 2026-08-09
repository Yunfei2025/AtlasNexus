# OTR/OFR Relative Value and New-Issue Strategy Plan

## Decision

The OTR/OFR initiative has two related but distinct strategies, split along a single
liquidity-rank ladder so they never trade the same pair:

1. New-issue rotation-ladder event strategy (`BondNewIssue`) — covers the front of
   the ladder, where bond identity is still migrating: `NIB -> OTR -> OFR1`.
2. Mature-pair relative value (`otr_ofr_rv`) under existing `TBondCurve` /
   `CBondCurve` using `signal_variant` — covers the tail of the ladder, among
   bonds that have already settled into an off-the-run rank:
   `OFR1 -> OFR2 -> OFR3 -> ...`.

`BondNewIssue` replaces separate `TBondNewIssue` and `CBondNewIssue` names.
Asset distinction is carried by metadata, not spread type name:

```text
spread_type: BondNewIssue
asset_class: TBond | CBond
issuer_class: CGB | CDB
tenor_bucket: 5Y | 10Y | 30Y | ...
instrument: <tenor_bucket>:<stage>:<leg1_id>|<leg2_id>
stage: nib_otr | otr_ofr1
```

`stage` distinguishes the two rotation legs (see "Rank Definitions" and
"Canonical Definitions" below) so both can be scored and released
independently. This keeps naming concise while preserving independent controls
by asset, tenor, and rotation stage.

## Why BondNewIssue Is Separate From TBondCurve/CBondCurve

`TBondCurve`/`CBondCurve` consumers assume a fixed instrument ID with a continuous calendar-indexed series that supports z-score and MR/trend routing. The new-issue rotation trade does not satisfy that contract:

- Instrument identity is role-based (`NIB`, `OTR`, `1st-OFR`) and rebinds at each rank change, not just at auction.
- Entry logic is rank-age cohort percentile (time since a bond attained its current rank), not stationary MR/trend z-score.
- Legs come from event/rank mapping, not model-curve duration-nearest lookup.

Therefore `BondNewIssue` must remain a dedicated spread type with `EventDriven` style.

## Scope and Generalization

The design is not 30Y-only. It is parameterized across active OTR buckets:

- CGB (TBond): 5Y, 10Y, 30Y
- CDB (CBond): 5Y, 10Y, 30Y

All model activation, data quality checks, and release gates are evaluated per `(asset_class, tenor_bucket)`. A pass for one bucket does not unlock another.

Do not extend affine model fitting range. Existing `BondConfig.PRICING_MIN_TTM`, `PRICING_MAX_TTM`, and `FIT_MAX_TTM` remain 1–10Y and unchanged.

## Rank Definitions

Three distinct bond identities exist per `(asset_class, tenor_bucket)`. They must
never be confused, and code that calls something "OTR" must mean liquidity rank,
not issuance recency:

- **NIB (new-issue bond):** the most recently issued bond in the bucket, ranked
  by `起息日期` (start date) descending. Stable identity — issuance order never
  changes. Selected the same way as today's `_select_otr_ofr_for_date` ranking
  in `curves/calibration/otr_ofr_universe.py`, but this rank is *not*
  automatically "OTR" — see below.
- **OTR (on-the-run):** the bond with the highest turnover in the bucket, i.e.
  `RefBondSelector.get_most_liquid_bond(turnover)` in
  `curves/calibration/selector.py`. This is the definition the rest of the app
  (curve calibration) already uses.
- **OFR-ladder (off-the-run rungs):** `OFR1, OFR2, OFR3, ...` ranked by turnover
  below OTR, i.e. `get_offtherun_bond(turnover, n_exclude=k)` for
  `k = 1, 2, 3, ...` in `curves/calibration/selector.py` (already generalizes
  past `n_exclude=1`).

**NIB and OTR are usually, but not always, different bonds.** Immediately after
auction a new bond is NIB but not yet OTR; it becomes OTR once its turnover
overtakes the incumbent. Some auctions are absorbed instantly (NIB == OTR from
day one) — that cohort has no migration lag to trade (see "Existence-of-Lag
Gate" under "BondNewIssue Model").

Turnover rank is noisier than issuance rank (a single large trade can flip
adjacent ranks). Promoting/demoting a bond's OFR-ladder rank requires a
persistence rule (e.g. N consecutive days of leadership) before the change is
accepted — otherwise the mature RV pair history gets spliced across a false
roll.

## Canonical Definitions

### Rotation Ladder (`BondNewIssue`, two stages)

The front of the ladder is one connected rotation, modeled as two stages under
the same `EventDriven` event framework, both keyed by *rank age* (days since a
bond attained its current rank), not issuance date:

```text
spread_type: BondNewIssue
asset_class: TBond | CBond
tenor_bucket: 5Y | 10Y | 30Y | ...
instrument: <tenor_bucket>:nib_otr:<nib_id>|<otr_id>
            <tenor_bucket>:otr_ofr1:<otr_id>|<ofr1_id>
```

**Stage 1 (`nib_otr`):** challenger vs incumbent.

$$
s_t^{NIB-OTR} = y_t^{NIB} - y_t^{OTR}
$$

Bets that NIB's liquidity migration continues and it eventually overtakes OTR.
Only tradeable if the "Existence-of-Lag Gate" confirms a live migration lag
exists for this cohort.

**Stage 2 (`otr_ofr1`):** incumbent retiring.

$$
s_t^{OTR-OFR1} = y_t^{OTR} - y_t^{OFR1}
$$

Bets that OTR's premium over OFR1 continues to erode as OTR approaches
displacement. Because OTR is a shared leg with Stage 1, see "Overlap Avoidance
and Portfolio Netting" before running both stages concurrently.

For notional $N_{leg1}$ on the first leg of a stage, size the second leg
DV01-neutral:

$$
N_{leg2} = N_{leg1}\frac{DV01_{leg1}}{DV01_{leg2}}
$$

### Mature RV (`otr_ofr_rv`, under TBondCurve/CBondCurve)

Restricted to the OFR ladder only — never touches NIB or OTR, so it cannot
overlap with `BondNewIssue` by construction.

```text
spread_type: TBondCurve | CBondCurve
signal_variant: model_curve | otr_ofr_rv
instrument: <ofr_k_id>|<ofr_1_id>      # k = 2, 3, 4, ...
spread: ytm_ofr_k - ytm_ofr_1
```

Assumed stationary/mean-reverting (generic liquidity-decay carry among bonds
already settled off-the-run), fit with `OU_calibrate`. For OFR1 notional
$N_{OFR1}$:

$$
N_{OFR_k} = N_{OFR1}\frac{DV01_{OFR1}}{DV01_{OFR_k}}
$$

## Cold-Start Policy (Mature RV Only)

This section applies to `otr_ofr_rv` only.

- `cold_start` (0–19): observe only, no z-score
- `descriptive` (20–59): diagnostics only
- `regime_ready` (60–119): regime diagnostics allowed, still untradeable
- `trade_ready` (120+): standard scoring and style routing allowed

Rules:

- Never splice predecessor/successor pairs into one synthetic z-score history.
- Record explicit `otr_roll` close/replace event.
- Keep analogue distributions for monitoring/research only; no synthetic live z-score.
- Apply the turnover-rank persistence rule from "Rank Definitions" before
  accepting an OFR-ladder rank change; a rank flip that fails persistence is
  not an `otr_roll` event.

## BondNewIssue Model

### Event Hypothesis and Sign

Two directional legs, one rotation cycle (see "Canonical Definitions" for the
spread sign per stage). Both are directional entries, not MR entries — the
position is held through the event, not scored against a stable mean.

### Existence-of-Lag Gate (Stage 1 precondition)

Not every auction produces a tradeable Stage 1: some new issues are absorbed
into liquidity immediately, so NIB and OTR already coincide from day one.
Before treating a cohort as having a live migration to trade:

- require a minimum turnover gap between OTR and NIB at cohort discovery
  (`otr_turnover - nib_turnover > gap_threshold`), or equivalently that NIB has
  not yet reached OTR's rank
- if the gap is already closed (or never opened) by the first observation, mark
  the cohort `no_lag` and skip Stage 1 for it — do not force an entry inside
  the age window regardless

This gate sits ahead of the existing rank-age window check, not in place of it.

### Cohort Method

Build point-in-time rank cohort panels by `(asset_class, tenor_bucket, stage)`:

- select NIB/OTR/OFR1 identities using only information available on date $t$
  (turnover-based for OTR/OFR1, issuance-based for NIB — see "Rank
  Definitions")
- align outcomes in event time using *rank age* (days since the bond attained
  the rank relevant to that stage), not days since issuance
- score live event as out-of-sample percentile against historical cohort, per
  stage
- leave each rotation cycle out of its own training sample (walk-forward)

### Data Readiness

As of 2026-07-31, only 30Y CGB has been audited enough for prototype research. Other buckets require independent audit before any production enablement.

Current 30Y CGB caveat:

- limited issuance episodes
- historical store is mainly close/volume
- no full historical executable bid/offer/repo/borrow/auction panel

So event strategy remains shadow or capped pilot until execution-quality data and episode-count thresholds are met.

## Overlap Avoidance and Portfolio Netting

The ladder split (`BondNewIssue` = front, `otr_ofr_rv` = tail) guarantees the
two *strategies* never hold the same pair. It does not guarantee zero shared
single-name exposure within `BondNewIssue` itself:

- Stage 1 (`nib_otr`) and Stage 2 (`otr_ofr1`) share the OTR leg whenever both
  are live for the same bucket at the same time (OTR is incumbent in Stage 1
  and is being displaced in Stage 2).
- This is expected — they are two halves of one rotation cycle — but net OTR
  exposure across both open legs must be aggregated at the portfolio layer,
  not assumed independent.
- Direction convention: confirm sign/notional so that concurrently open Stage 1
  and Stage 2 legs on the same OTR bond net (or intentionally compound)
  exposure by design, not by accident.

If only one stage is enabled for a bucket (e.g. Stage 1 only during initial
rollout), this section is moot until Stage 2 is released for that bucket.

## Style Policy

- `TBondCurve`/`CBondCurve` with `model_curve` and mature `otr_ofr_rv` (OFR-ladder only): MR default with existing regime process.
- `BondNewIssue` (both rotation stages): fixed `EventDriven` style, never MR/trend-routed.
- Backtest and production must use identical gate logic.

## Production Operating Model

Strategy families are independently enabled:

- `otr_ofr_rv` under `TBondCurve`/`CBondCurve` (OFR-ladder only)
- `BondNewIssue` Stage 1 (`nib_otr`) and Stage 2 (`otr_ofr1`) under
  `(asset_class, tenor_bucket)` controls, each with its own gate outcome

No strategy/bucket/stage can become tradeable because another passed validation.

### State Machine

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

`SIGNAL_READY` criteria:

- `otr_ofr_rv`: OFR-ladder pair history and routing readiness
- `BondNewIssue` Stage 1 (`nib_otr`): existence-of-lag gate passed, within rank-age entry window, and cohort score confirmed
- `BondNewIssue` Stage 2 (`otr_ofr1`): within rank-age entry window and cohort score confirmed

`RISK_APPROVED` criteria for both:

- fresh two-sided quotes
- turnover and quote-quality thresholds
- borrow/funding availability
- DV01 hedge tolerance
- gross/notional and concentration limits

### Mandatory Gates

1. Constituent selection gate (point-in-time; turnover-based for OTR/OFR-ladder, issuance-based for NIB)
2. Existence-of-lag gate (`BondNewIssue` Stage 1 only — skip cohorts with no live NIB/OTR migration)
3. Quote freshness and executable width gate
4. Liquidity gate
5. Funding/borrow gate (missing borrow blocks)
6. Risk limit gate
7. Versioned model/data cutoff gate
8. Kill-switch gate (data failure, recall, delist, failed hedge, etc.)

## Implementation Phases

### Phase 1: Config and Schema

- keep `TBOND_CURVE_VARIANTS = {"model_curve", "otr_ofr_rv"}`
- add `BondNewIssue` config keyed by `(asset_class, tenor_bucket)`
- add canonical fields: `asset_class`, `issuer_class`, `tenor_bucket`
- update dropdown/category:

```text
SPREAD_CATEGORIES['New-Issue']
  types: ['BondNewIssue']
  style: EventDriven
```

### Phase 2: Point-in-Time Universe Builder

Build unified rank-ladder builder parameterized by `(asset_class, tenor_bucket)` and persist:

- NIB identity by date (issuance-recency ranked)
- OTR and OFR1..N identities by date (turnover ranked, via
  `RefBondSelector.get_most_liquid_bond` / `get_offtherun_bond`)
- rank age per identity (days since attaining current rank), separate from
  issuance age
- rank-change markers, gated by the turnover persistence rule (see "Rank
  Definitions") before being accepted as a real roll
- DV01 ratio per stage
- quote/turnover quality flags
- rejection reason, including `no_lag` for Stage 1 cohorts that never had a
  migration to trade

### Phase 3: Artifacts

- Mature RV remains in `BondCurve` branches with `signal_variant=otr_ofr_rv`,
  built only from OFR1..N (never NIB/OTR)
- New issue persists under dedicated `NewIssue` branches keyed by asset, tenor,
  and stage (`nib_otr` / `otr_ofr1`)
- never feed rolled analogue panel into live pair z-score history

### Phase 4: Alpha Loaders, Candidates, Legs, Risk

- loader branch for `spread_type == 'BondNewIssue'`
- `legs.py` branch resolves `(nib_id, otr_id)` for `nib_otr` and
  `(otr_id, ofr1_id)` for `otr_ofr1` from event mapping
- show `asset_class`, `tenor_bucket`, stage, rank age, event score, roll status
- aggregate net OTR exposure across concurrently open stages (see "Overlap
  Avoidance and Portfolio Netting")
- keep DV01 and convexity reporting fully leg-based

### Phase 5: Backtest

- separate backtest path for `BondNewIssue`, run per stage (`nib_otr`,
  `otr_ofr1`)
- no MR z-score entry for event type
- enforce all gates with date-causal data only, including the
  existence-of-lag gate for Stage 1
- report by strategy, by `(asset_class, tenor_bucket)`, and by stage

### Phase 6: Execution and Release

- linked-leg execution, hedge reconciliation, residual-risk alerts
- shadow trading must separate observed execution costs vs proxy assumptions
- release sequence: mature RV (OFR-ladder) first, then BondNewIssue
  bucket-by-bucket, Stage 1 before Stage 2 within each bucket

### Phase 7: Tests and Documentation

Add tests for:

- ID parsing and spread sign, per stage
- point-in-time NIB (issuance) vs OTR/OFR-ladder (turnover) selection
- turnover-rank persistence and existence-of-lag gate
- roll events
- gate enforcement
- walk-forward cohort exclusion
- linked-leg ticketing and kill switches
- portfolio-level netting of shared OTR exposure across concurrent stages

Update report/help docs to reflect unified `BondNewIssue` naming and the
NIB/OTR/OFR-ladder rank definitions.

## Delivery Order

1. Config/schema
2. Universe/artifacts
3. Candidate/legs/risk plumbing
4. Backtest
5. Execution/shadow
6. Bucket-by-bucket release
7. UI/docs

No production allocation before strategy-specific and bucket-specific release gates are met.
