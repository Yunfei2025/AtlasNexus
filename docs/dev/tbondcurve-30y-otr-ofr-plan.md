# OTR/OFR Relative Value and New-Issue Strategy Plan

## Decision

The OTR/OFR initiative has two related but distinct strategies:

1. Mature-pair relative value (`otr_ofr_rv`) under existing `TBondCurve` / `CBondCurve` using `signal_variant`.
2. New-issue roll-pressure event strategy as one unified spread type: `BondNewIssue`.

`BondNewIssue` replaces separate `TBondNewIssue` and `CBondNewIssue` names.
Asset distinction is carried by metadata, not spread type name:

```text
spread_type: BondNewIssue
asset_class: TBond | CBond
issuer_class: CGB | CDB
tenor_bucket: 5Y | 10Y | 30Y | ...
instrument: <tenor_bucket>:<new_otr_id>|<first_ofr_id>
```

This keeps naming concise while preserving independent controls by asset and tenor.

## Why BondNewIssue Is Separate From TBondCurve/CBondCurve

`TBondCurve`/`CBondCurve` consumers assume a fixed instrument ID with a continuous calendar-indexed series that supports z-score and MR/trend routing. The new-issue trade does not satisfy that contract:

- Instrument identity is role-based (`OTR`, `1st-OFR`, `2nd-OFR`) and rebinds at each roll.
- Entry logic is issuance-age cohort percentile, not stationary MR/trend z-score.
- Legs come from event mapping, not model-curve duration-nearest lookup.

Therefore `BondNewIssue` must remain a dedicated spread type with `EventDriven` style.

## Scope and Generalization

The design is not 30Y-only. It is parameterized across active OTR buckets:

- CGB (TBond): 5Y, 10Y, 30Y
- CDB (CBond): 5Y, 10Y, 30Y

All model activation, data quality checks, and release gates are evaluated per `(asset_class, tenor_bucket)`. A pass for one bucket does not unlock another.

Do not extend affine model fitting range. Existing `BondConfig.PRICING_MIN_TTM`, `PRICING_MAX_TTM`, and `FIT_MAX_TTM` remain 1–10Y and unchanged.

## Canonical Definitions

### Mature RV (`otr_ofr_rv`, under TBondCurve/CBondCurve)

```text
spread_type: TBondCurve | CBondCurve
signal_variant: model_curve | otr_ofr_rv
instrument: <ofr_id>|<otr_id>
spread: ytm_ofr - ytm_otr
```

For OFR notional $N_{OFR}$:

$$
N_{OTR} = N_{OFR}\frac{DV01_{OFR}}{DV01_{OTR}}
$$

### New-Issue Event (`BondNewIssue`)

```text
spread_type: BondNewIssue
asset_class: TBond | CBond
tenor_bucket: 5Y | 10Y | 30Y | ...
instrument: <tenor_bucket>:<new_otr_id>|<first_ofr_id>
spread: ytm_1ofr - ytm_otr
```

Economic position is long new OTR, short first OFR, DV01-neutral, with entry/exit keyed by OTR age window.

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

## BondNewIssue Model

### Event Hypothesis and Sign

With yield convention:

$$
s_t^{1OFR-OTR} = y_t^{1OFR} - y_t^{OTR}
$$

new issuance typically widens this spread in early event age. Event strategy is directional (not MR entry).

### Cohort Method

Build point-in-time issuance cohort panel by `(asset_class, tenor_bucket)`:

- select new OTR, first OFR, second OFR using only information available on date $t$
- align outcomes in event time (OTR age)
- score live event as out-of-sample percentile against historical cohort
- leave each issuance out of its own training sample (walk-forward)

### Data Readiness

As of 2026-07-31, only 30Y CGB has been audited enough for prototype research. Other buckets require independent audit before any production enablement.

Current 30Y CGB caveat:

- limited issuance episodes
- historical store is mainly close/volume
- no full historical executable bid/offer/repo/borrow/auction panel

So event strategy remains shadow or capped pilot until execution-quality data and episode-count thresholds are met.

## Style Policy

- `TBondCurve`/`CBondCurve` with `model_curve` and mature `otr_ofr_rv`: MR default with existing regime process.
- `BondNewIssue`: fixed `EventDriven` style, never MR/trend-routed.
- Backtest and production must use identical gate logic.

## Production Operating Model

Both strategy families are independently enabled:

- `otr_ofr_rv` under `TBondCurve`/`CBondCurve`
- `BondNewIssue` under `(asset_class, tenor_bucket)` controls

No strategy/bucket can become tradeable because another passed validation.

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

- `otr_ofr_rv`: pair history and routing readiness
- `BondNewIssue`: within entry age window and cohort score confirmed

`RISK_APPROVED` criteria for both:

- fresh two-sided quotes
- turnover and quote-quality thresholds
- borrow/funding availability
- DV01 hedge tolerance
- gross/notional and concentration limits

### Mandatory Gates

1. Constituent selection gate (point-in-time)
2. Quote freshness and executable width gate
3. Liquidity gate
4. Funding/borrow gate (missing borrow blocks)
5. Risk limit gate
6. Versioned model/data cutoff gate
7. Kill-switch gate (data failure, recall, delist, failed hedge, etc.)

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

Build unified OTR/OFR builder parameterized by `(asset_class, tenor_bucket)` and persist:

- OTR/OFR identities by date
- event age
- roll markers
- DV01 ratio
- quote/turnover quality flags
- rejection reason

### Phase 3: Artifacts

- Mature RV remains in `BondCurve` branches with `signal_variant=otr_ofr_rv`
- New issue persists under dedicated `NewIssue` branches keyed by asset and tenor
- never feed rolled analogue panel into live pair z-score history

### Phase 4: Alpha Loaders, Candidates, Legs, Risk

- loader branch for `spread_type == 'BondNewIssue'`
- `legs.py` branch resolves `(new_otr_id, first_ofr_id)` from event mapping
- show `asset_class`, `tenor_bucket`, OTR age, event score, roll status
- keep DV01 and convexity reporting fully leg-based

### Phase 5: Backtest

- separate backtest path for `BondNewIssue`
- no MR z-score entry for event type
- enforce all gates with date-causal data only
- report by strategy and by `(asset_class, tenor_bucket)`

### Phase 6: Execution and Release

- linked-leg execution, hedge reconciliation, residual-risk alerts
- shadow trading must separate observed execution costs vs proxy assumptions
- release sequence: mature RV first, then BondNewIssue bucket-by-bucket

### Phase 7: Tests and Documentation

Add tests for:

- ID parsing and spread sign
- point-in-time OTR/OFR selection
- roll events
- gate enforcement
- walk-forward cohort exclusion
- linked-leg ticketing and kill switches

Update report/help docs to reflect unified `BondNewIssue` naming.

## Delivery Order

1. Config/schema
2. Universe/artifacts
3. Candidate/legs/risk plumbing
4. Backtest
5. Execution/shadow
6. Bucket-by-bucket release
7. UI/docs

No production allocation before strategy-specific and bucket-specific release gates are met.
