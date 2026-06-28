# AtlasNexus — Platform Presentation

> **Slide-style narrative deck.** Each `## Slide` is one slide; bullets are talking
> points. Intended to be polished into a visual deck in Claude Design.
> **Audience:** management, investment committee, prospective partners/clients.

---

## Slide 1 — Title

# AtlasNexus
### Systematic Investment Platform for Fixed Income & Multi-Strategy

*Curve calibration · Factor allocation · Relative value · Futures · Multi-asset · Derivatives*

One terminal. From raw market data to risk-managed positions.

---

## Slide 2 — The Problem

- Fixed-income desks juggle **fragmented tools**: separate spreadsheets for curves,
  factor models, RV scanners, and risk.
- Research and production **drift apart** — the model that's backtested is rarely the
  model that trades.
- **No single source of truth** for positions, risk, and P&L across beta and alpha books.
- Manual, error-prone EOD processes that don't scale across asset classes.

---

## Slide 3 — The Solution

**AtlasNexus unifies the entire desk workflow into one platform:**

- A **library of quant models** (curves, factors, pairs, futures, multi-asset,
  derivatives) behind a **single Dash web terminal**.
- A **deterministic EOD engine** that calibrates everything once and persists
  versioned artifacts the dashboard reads.
- **Research = production**: the same engine that backtests generates the daily signals.
- Two consoles — **Daily** (EOD/research) and **Intraday** (live monitoring).

---

## Slide 4 — Architecture at a Glance

```
        ┌──────────────────────────────────────────────┐
        │          AtlasNexus Web Terminal (Dash)        │
        │  Market · Beta Book · Alpha Book · Summary ·   │
        │                  Run Center                    │
        └───────────────▲───────────────────────────────┘
                        │ reads versioned artifacts
        ┌───────────────┴───────────────────────────────┐
        │            Engine — Orchestration Layer        │
        │   EOD · Intraday · Refresh pipelines           │
        │   ArtifactStore → runs/<id>/*.json             │
        └───────────────▲───────────────────────────────┘
                        │ calls thin interfaces
   ┌────────┬───────────┼──────────┬──────────┬──────────┐
   │ Curves │  Factors  │  Pairs   │ Futures  │Multiasset│ Derivatives
   └────────┴───────────┴──────────┴──────────┴──────────┘
                        ▲
                        │
                  Market Data (Wind / local providers)
```

- **Isolated steps** — a failing module is logged and skipped, never aborts the run.
- **Pure artifacts** — the UI never recomputes; it renders pre-computed JSON.

---

## Slide 5 — The Five Books

| Book | Colour | Mandate |
|------|--------|---------|
| **Market** | cyan | Calibrated curves, pricer, surface, trend — the market state |
| **Beta Book** | blue | Systematic macro **factor** allocation (training → sizing → portfolio) |
| **Alpha Book** | amber | Market-neutral **relative-value** (spreads, pairs, vol) |
| **Summary** | cyan | Desk-level combined P&L, positions, risk, tickets |
| **Run Center** | teal | Daily pipeline control, data backfill, status & logs |

> One mental model: **Beta** = take the right macro risks. **Alpha** = harvest
> mispricings market-neutral. **Summary** = see them together.

---

## Slide 6 — Asset & Instrument Coverage

- **Bonds:** Treasury (TBond), Policy Bank (CBond), Local Gov (LBond), Green (GBond)
- **Rates:** FR007 IRS, repo pairs, butterfly spreads
- **Futures:** term basis, net basis, CTD/IRR analytics
- **Credit:** sector spreads, credit curves
- **Derivatives:** bond & IRS options pricing, vol surfaces, greeks
- **Cross-asset factors:** IR / FX / EQ / CM for the factor model

---

## Slide 7 — Beta Book: The Factor Engine

**A walk-forward, leakage-aware factor model — research-grade, in production.**

- Rich **feature library** per factor: momentum, value/mean-reversion, volatility,
  carry/curve (slope, curvature, roll-down), cross-factor, and macro features.
- **Walk-forward** monthly training with **purge gap + embargo** to prevent leakage.
- **IC-based selection**: keep features with significant Spearman IC, diversify, VIF-filter, cap at top-N.
- **Regime-aware**: z-score/value features are vetoed inside strong trends.
- **Causal position sizing**: ICIR-weighted, vol-targeted, leverage-capped.
- Every trained model is **versioned and persisted** for daily signal generation.

---

## Slide 8 — Alpha Book: Relative Value

- **RV scanner** ranks instruments rich/cheap by residual z-score.
- **Pairs / spreads** fit a hedge ratio by regression; trade the mean-reverting residual.
- **Spread families**: sector PCA, treasury/policy/local/corporate, swap spreads,
  bond-swap, futures term/net basis.
- **Volatility** book: implied vs. historical surfaces, skew/smile, vega monitoring.
- Statistically grounded: stationarity checks, confidence bands from residual dispersion.

---

## Slide 9 — Curve Calibration

- **Affine factor curve models** with PSD-projected covariance and Tikhonov
  regularization — robust fits even on sparse/noisy quotes.
- Full daily chain: **Trend → BondCurve (TBond/CBond) → CreditSpread → IRS → Stat → Pairs**.
- Bootstrap and pricing-yield engines for instrument-level valuation.
- A dedicated **curve backtest** harness validates calibration stability over history.

---

## Slide 10 — Multi-Asset Risk & Allocation

- **Factor risk-parity optimizer** — equalises *factor* risk contribution, not asset weight.
- **vol^0.5 risk budgeting** — between equal-risk and vol-proportional, giving level
  factors more budget than slope/curvature without over-concentrating.
- **EWMA factor covariance** and PCA risk-factor analysis.
- Consolidated **DV01 ladder** and factor risk attribution at the desk level.

---

## Slide 11 — A Day on the Desk

```
Morning   →  Update Data → Run EOD → review Summary book
Intraday  →  Intraday Console: live pricing, refresh scheduler
Research  →  Beta Book backtest, retrain factor model, save version
Execution →  Summary → Tickets: target vs. actual → trade
```

- **One-click EOD** from Run Center; identical CLI for automation/cron.
- **Isolated, resumable** steps; **versioned runs** for full auditability.

---

## Slide 12 — Why It's Different

| Conventional setup | AtlasNexus |
|--------------------|-----------|
| Backtest ≠ live model | Same engine for both |
| Spreadsheet sprawl | One terminal, five books |
| Recompute on every click | Pre-computed, versioned artifacts |
| Opaque, manual EOD | Isolated, logged, auditable pipeline |
| Asset weighting | Factor risk-parity |
| Leakage-prone backtests | Purge/embargo, walk-forward, OOS-only |

---

## Slide 13 — Technology

- **Python 3.9+**, **Dash** web framework, **multiprocessing** for parallel calibration.
- Numerical stack: NumPy / pandas / SciPy / statsmodels / SymPy / nlopt.
- **Wind** market-data integration (optional); graceful fallback to cached data.
- Cross-platform: macOS, Windows, Linux. Remote access via Cloudflare tunnel.
- ~36 fast CI tests; pure-python schema layer testable without market data.

---

## Slide 14 — Roadmap (placeholder — fill from product plan)

- Expand factor universe and macro feature set.
- Live execution / OMS integration for the Tickets workflow.
- Additional asset classes and cross-currency RV.
- Enhanced attribution and scenario/stress analytics.
- Productionised model-monitoring and drift alerts.

---

## Slide 15 — Summary

**AtlasNexus turns a quant model library into a working systematic desk.**

- One terminal, five books, two consoles.
- Research-grade models running in production, unchanged.
- Versioned, auditable, isolated EOD engine.
- Fixed income today; multi-asset by design.

*From raw market data to risk-managed positions — in one platform.*
```
