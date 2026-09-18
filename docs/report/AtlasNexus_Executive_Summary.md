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

- **One engine, one terminal.** A deterministic end-of-day pipeline calibrates
  curves, generates factor signals, and builds books once per day; the console
  renders the resulting artifacts — it never recomputes on the fly.
- **Five books.** *Market Monitor* (calibrated rates/credit state and pricing) →
  *Beta Portfolio* (systematic macro factor allocation) → *Alpha Portfolio*
  (market-neutral relative value across spreads, pairs and volatility) →
  *Portfolio Summary* (combined desk risk/P&L and tickets) → *Execution Center*
  (daily run, data backfill, artifact inspection).
- **Research = production.** The same walk-forward factor model that is
  backtested in the Beta Portfolio is the one that generates live signals — model
  training is a deliberate, versioned step, decoupled from the daily run.
- **Isolated, auditable steps.** Each calibration step is independently logged;
  a failure in one module never aborts the rest of the run. Every run is
  persisted as a versioned, inspectable artifact set.

## What's under the hood

- **Curves:** affine factor models with regularized, numerically robust calibration.
- **Beta:** leakage-aware walk-forward factor model (purge/embargo, IC-based
  selection, causal vol-targeted sizing) plus factor risk-parity allocation.
- **Alpha:** regression-based pairs/spread trading with statistically validated
  entry/exit signals, across mean-reversion, monthly and seasonal engines, plus a
  volatility/RV book.
- **Futures & derivatives:** dedicated strategy and options-pricing engines.

## Recent additions

- **Capital allocation between books.** The Portfolio Summary now sizes Beta
  against Alpha on a like-for-like basis — beta notional versus alpha *margin*,
  since the RV book is margined — and sweeps every split to plot a
  **diversification frontier** with the maximum-Sharpe point marked. It reports
  combined Sharpe, correlation, and a diversification ratio that makes explicit
  whether the two books genuinely offset each other.
- **CMBC FICC Allocation Index (民生FICC配置指数).** A rules-based FICC allocation
  index with a published rulebook, generated from the Beta Portfolio and exported
  as a formatted monthly PDF report directly from the terminal.
- **Deeper alpha backtesting.** Separate mean-reversion, monthly and seasonal
  engines with candidate scoring, replacing a single generic backtest path.
- **Carry and roll-down in rates allocation.** Curve analytics surface the best
  roll-down term, and the daily pipeline now computes a carry/roll-down-aware
  tilt for the China government bond curve (engine-side; not yet surfaced in the
  terminal).

## Why it matters

| Conventional desk | AtlasNexus |
|---|---|
| Backtest ≠ live model | Same engine, both modes |
| Spreadsheet sprawl | One terminal |
| Manual, opaque EOD | Logged, isolated, versioned pipeline |
| Asset-weighted risk | Factor risk-parity |
| Books sized by intuition | Margin-aware diversification frontier |

## Status & next steps

The platform is live and running the daily fixed-income workflow end-to-end.
Trade tickets are currently *inferred from positions* — there is no order or fill
connectivity — so building a genuine execution path is the main operational gap.
Other near-term priorities: broaden the factor/macro universe, surface the
carry/roll-down tilt in the terminal and calibrate its sizing against history,
extend RV coverage to additional asset classes, complete the planned intraday
console, and formalize periodic model-risk review of the factor model's selection
and sizing hyperparameters.

*Full detail: see the User Manual, Model Methodology, and Presentation documents
in this folder.*
