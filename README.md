# AtlasNexus（资产汇策：多资产策略中枢平台）

> **AtlasNexus** is a multi-asset, multi-strategy investment & trading decision system.
> It supports **EOD (daily)** portfolio construction and **Intraday** (higher-frequency) signal workflows.
> **Execution is manual**: the system outputs **targets, risk diagnostics, and trade tickets**.


## System logic (two-book architecture)

You maintain two conceptual books that are built differently, but combined under a single risk view.

- **Beta book (top-down hierarchy)**: **asset class → curve sector → instrument**
  - Designed for directional / risk-premia exposures.
  - “Sector” in this project means **rates curve sectors** (e.g., 2Y/5Y/10Y/30Y buckets, curve structures, country curves).

- **Alpha book (bottom-up hierarchy)**: **trade → strategy sleeve → portfolio**
  - Designed for market-neutral / RV / arbitrage / intraday return streams.

A key design idea is: **hierarchical construction + nexus-style risk aggregation**.

---

## Repository map (what each folder is responsible for)

- `engine/`
  - Orchestration layer (CLI), shared domain objects, artifact I/O.
  - Runs EOD/Intraday pipelines and produces outputs under `runs/<run_id>/`.

- `web/`
  - Dash dashboards for monitoring and operating the system.
  - Recommended to run as two apps: **Daily Console** + **Intraday Console**.

- `portfolio/`
  - Defines the investment pool (multi-asset universe), constraints, and portfolio construction/risk control policy.
  - Owns “budget intent” (how much risk you want per asset class / curve sector).

- `multiasset/`
  - Cross-asset sensitivities and position sizing.
  - Acts as the “risk nexus”: converts exposures into comparable risk units (vol, DV01, beta, FX), aggregates across books.

- `factors/`
  - Factor modeling and market regime detection.
  - Produces regime/trend signals used to tilt beta budgets and gate/scale alpha risk.

- `curves/`
  - Rates curve analytics and pricing engine for selection.
  - Supports curve-sector definition, carry/rolldown/relative value metrics for instrument selection.

- `pairs/`
  - Bond pair trading strategies (relative value / spread trading).

- `derivatives/`
  - Options pricers, vol surfaces, and volatility strategies.

- `futures/`
  - Futures trading strategies.
  - `futures/daily/` focuses on EOD signals.
  - `futures/intraday/` focuses on higher-frequency trading workflows.

- `surface/`
  - Treasury curve surface visualization / analysis.

- `backtest/`
  - Backtesting & analytics.
  - Recommended usage: weekly/monthly calibration for alpha allocation & parameter tuning.

- `data/` and `*/retrieve.py`
  - Data retrieval / update scripts exist in multiple packages (`curves/utils/retrieve.py`, `futures/intraday/retrieve.py`, etc.).
  - `engine/data_update.py` provides a unified runner.

---

## Workflow overview

### A) EOD (daily) workflow

1. **Universe & curve sectors** (top-down)
   - Select **asset class** and **rates curve sectors**.
   - Define constraints (max DV01, max beta, currency exposure limits, concentration).

2. **Factor model / regime detection**
   - Run `factors/` to infer regime/trend/confidence.

3. **Risk budgeting (per sector)**
   - Set base budgets (strategic) and apply regime tilts (tactical).

4. **Portfolio construction → target exposures**
   - Convert budgets into target exposures/weights.

5. **Position sizing & instrument selection**
   - Use `multiasset/` to normalize risk and compute suggested sizing.
   - Use `curves/` for FI selection (carry/rolldown/RV) to pick instruments that implement desired sector exposure.

6. **Tickets (manual execution)**
   - Convert targets into trade tickets (rebalance list) vs current positions.

### B) Intraday workflow

Intraday runs are separated due to different refresh frequency and risk controls.

1. Load intraday data (high frequency)
2. Compute intraday signals (e.g., `futures/intraday/`)
3. Apply intraday-specific risk caps (session limits, max trades, holding time)
4. Generate intraday tickets (open/close suggestions)

### C) Alpha book calibration (weekly/monthly)

Backtests are integrated as **calibration jobs** (not part of daily UI refresh):

- Run `backtest/` periodically to produce:
  - strategy weights/caps
  - turnover estimates
  - correlation/crowding metrics
  - selected parameter sets

Daily EOD/Intraday runs then consume these calibration outputs.

---

## How beta & alpha are combined

Recommended pattern:

1. Run **beta** and **alpha** independently (modular, different cadence).
2. Aggregate using a single risk layer (the “nexus”):
   - net overlapping instruments/exposures
   - enforce global limits
   - scale down sleeves if limits bind
3. Output **combined targets** and **tickets**.

This produces a clean audit trail: `beta → alpha → aggregate → tickets`.

---

## Run commands (PowerShell)

### Start dashboards

```pwsh
# Daily console (existing)
python .\main.py web

# Yield surface viewer
python .\main.py surface
```

### Run engine pipelines

```pwsh
# EOD run (optionally update data first)
python .\main.py eod --asof 2026-01-04 --update-data

# Intraday snapshot run
python .\main.py intraday --asof 2026-01-04 --update-data

# Run data updaters only (module list optional)
python .\main.py update-data
python .\main.py update-data --modules curves.utils.retrieve futures.intraday.retrieve
```

---

## Artifacts and outputs

Engine runs write to:

- `runs/<run_id>/run_meta.json`

Planned (to be wired as pipelines mature):

- `runs/<run_id>/beta/*` (beta targets, beta risk)
- `runs/<run_id>/alpha/*` (alpha targets, alpha risk)
- `runs/<run_id>/aggregate/*` (combined targets + tickets)
- `runs/<run_id>/tickets.csv` (manual execution list)

---

## Next suggested improvements

- Add a **status.json + log file** per run for dashboard polling.
- Add a **positions store** (positions.csv/SQLite) and a **ticket state machine** (Draft → Approved → Executed).
- Build two Dash apps:
  - Daily Console: portfolio construction, risk budgets, sector view, ticket manager
  - Intraday Console: fast-refresh monitoring, intraday tickets, session risk
