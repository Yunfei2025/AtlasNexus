# AtlasNexus — Executive Summary

> One page. **Audience:** management, investment committee, prospective partners.

---

## What it is

**AtlasNexus** is a systematic investment platform for fixed income and
multi-strategy trading. It unifies curve calibration, factor (beta) allocation,
relative-value (alpha) trading, futures strategies, multi-asset risk, and
derivatives pricing into **one web terminal** — replacing a fragmented stack of
spreadsheets and standalone scripts with a single, auditable system.

## The problem it solves

Fixed-income desks typically run research and production on **different code** —
the backtested model is not the model that trades. Risk and P&L for systematic
(beta) and relative-value (alpha) books live in separate tools with no common
source of truth, and daily processes are manual and error-prone.

## How it works

- **One engine, two consoles.** A deterministic end-of-day pipeline calibrates
  curves, generates factor signals, and builds books once per day; the **Daily**
  and **Intraday** consoles render the resulting artifacts — they never recompute
  on the fly.
- **Five books.** *Market* (calibrated rates/credit state) → *Beta Book*
  (systematic macro factor allocation) → *Alpha Book* (market-neutral relative
  value) → *Summary* (combined desk risk/P&L) → *Run Center* (operations).
- **Research = production.** The same walk-forward factor model that is
  backtested in the Beta Book is the one that generates live signals — model
  training is a deliberate, versioned step, decoupled from the daily run.
- **Isolated, auditable steps.** Each calibration step is independently logged;
  a failure in one module never aborts the rest of the run. Every run is
  persisted as a versioned, inspectable artifact set.

## What's under the hood

- **Curves:** affine factor models with regularized, numerically robust calibration.
- **Beta:** leakage-aware walk-forward factor model (purge/embargo, IC-based
  selection, causal vol-targeted sizing) plus factor risk-parity allocation.
- **Alpha:** regression-based pairs/spread trading with statistically validated
  entry/exit signals, plus a volatility/RV book.
- **Futures & derivatives:** dedicated strategy and options-pricing engines.

## Why it matters

| Conventional desk | AtlasNexus |
|---|---|
| Backtest ≠ live model | Same engine, both modes |
| Spreadsheet sprawl | One terminal |
| Manual, opaque EOD | Logged, isolated, versioned pipeline |
| Asset-weighted risk | Factor risk-parity |

## Status & next steps

The platform is live and running the daily fixed-income workflow end-to-end.
Near-term priorities: broaden the factor/macro universe, integrate live execution
into the Tickets workflow, extend RV coverage to additional asset classes, and
formalize periodic model-risk review of the factor model's selection and sizing
hyperparameters.

*Full detail: see the User Manual, Model Methodology, and Presentation documents
in this folder.*
```
