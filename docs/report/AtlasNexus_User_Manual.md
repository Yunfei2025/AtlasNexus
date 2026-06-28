# AtlasNexus — User Manual

> **AtlasNexus · Systematic Investment Platform**
> A fixed-income and multi-strategy systematic investment terminal covering curve
> calibration, factor (beta) allocation, relative-value (alpha) trading, futures
> strategies, multi-asset portfolio construction, and derivatives pricing —
> delivered through a single unified web console.

**Document type:** User Manual (operations & day-to-day use)
**Audience:** Portfolio managers, traders, quant researchers, and operators running the desk.
**Status:** Draft for review — to be polished in Claude Design.

---

## 1. What AtlasNexus Is

AtlasNexus is the front-end and orchestration layer of the **FIEngine** platform.
It turns a library of fixed-income quant models into a working desk terminal with
two consoles:

| Console | Port | Purpose |
|---------|------|---------|
| **Daily Console** | `8080` | End-of-day (EOD) reporting, historical analysis, overnight risk, model training, and backtesting. The primary workspace. |
| **Intraday Console** | `8081` | High-frequency monitoring, real-time pricing, and intraday strategy execution. |

Both consoles read **pre-computed artifacts** produced by the engine pipelines, so
the dashboard stays responsive — it displays results rather than recomputing them
on every click.

The terminal is organised into five **Books** (top-level tabs), each with its own
accent colour and sub-tabs:

| Book | Accent | What it covers |
|------|--------|----------------|
| **Market** | cyan | Live/EOD market data, pricer, curves, surface, trend |
| **Beta Book** | blue | Factor selection, factor model training, risk allocation, beta portfolio |
| **Alpha Book** | amber | Relative-value scanner, spreads, pairs, volatility, candidates |
| **Summary** | cyan | Combined book P&L, positions, risk, tickets |
| **Run Center** | teal | Daily pipeline control, data backfill, status & logs |

---

## 2. Getting Started

### 2.1 Launching the platform

**macOS**
```bash
./START_mac.command        # double-click in Finder, or run in Terminal
```

**Windows**
```bat
START_win.bat
```

**Direct (any OS)**
```bash
python main.py             # same as daily-web → http://localhost:8080
python main.py daily-web   # Daily Console  → http://localhost:8080
python main.py intraday-web# Intraday Console → http://localhost:8081
```

On launch the Daily Console opens automatically in your browser. A small live
**log window** appears (macOS/Windows) showing startup progress; you can suppress
it with the `FI_SHOW_LOG_WINDOW=0` environment variable.

### 2.2 Requirements

- **Python 3.9+**, conda environment `dev` (macOS/Linux) or `prod` (Windows).
- Install dependencies: `pip install -r requirements/production.txt`
- **Optional, for live data:** WindPy (Wind terminal SDK) and TA-Lib.
  Without Wind, the platform runs on cached/historical data and skips live
  retrieval gracefully.

### 2.3 First-run checklist

1. Activate the environment and launch the Daily Console.
2. Open **Run Center** → confirm the latest EOD run status is green.
3. If data is stale, run **Update Data**, then **Run EOD** (see §6).
4. Browse the **Market** book to confirm curves and prices loaded.

---

## 3. The Market Book

The Market book is the analyst's starting point — it shows the calibrated state of
the rates and credit markets.

| Sub-tab | What it shows | Typical use |
|---------|---------------|-------------|
| **Data** | Money-market rates, on-the-run & reference bonds, IRS forward rates with in-cell bars | Sanity-check today's market levels |
| **Pricer** | Bid/offer/mid pricing for TBond, CBond, LBond, GBond, FR007 IRS, repo pairs, butterflies, futures basis | Quote an instrument, read carry/roll greeks |
| **Curves** | Calibrated yield and forward curves (TBond, CBond, IRS, credit) | Inspect curve shape, fits, residuals |
| **Surface** | Yield surface across tenor × maturity | Spot rich/cheap pockets on the surface |
| **Trend** | Momentum and trend indicators, breakout signals | Directional context |

**Pricer key columns:** Ticker, Coupon, Maturity Year, Current Yield, **Z-Score**
(statistical rich/cheap measure), **Stationarity** status, Bid/Offer/Mid, price
changes in **bp** (basis points), and greeks: **Carry (3M)**, **Roll (3M)**, **Total
= Carry + Roll**.

**Interactions:** dropdowns for asset type and term range (1–3Y, 3–5Y, 5–7Y,
7–10Y, 10–30Y), sortable/filterable tables, and interval-based live updates on the
Intraday Console.

---

## 4. The Beta Book

The Beta Book runs the systematic **factor (beta) allocation** workflow — choosing
which macro risk factors to take, training the model that sizes them, and building
the resulting portfolio.

| Sub-tab | What it does |
|---------|--------------|
| **Candidates** | Factor selection pool across IR / FX / EQ / CM. Pick the factor universe, then **Train** or **Predict**. |
| **Factor** | Factor model detail — information coefficients (IC), feature weights, regimes. |
| **Backtest** | Walk-forward backtest of the factor model. Two sheets: **Individual Factors** (single-factor risk-factor backtest, "RFBT") and **Portfolio** (multi-asset). |
| **Portfolio** | Factor risk-parity portfolio construction and current beta allocation. |
| **Bond / Futures** | Instrument-level expression of the beta book. |
| **Risk** | DV01 ladders, factor risk attribution. |

### 4.1 Running a factor-model backtest

In **Beta Book → Backtest → Individual Factors**:

1. Select a factor.
2. Set parameters:
   - **Train window (months)** — rolling training window (default 12).
   - **IC threshold** — minimum information coefficient to keep a feature (default 0.05).
   - **Top N features** — feature cap after selection (default 8).
   - **Backtest period (years)** — out-of-sample window (default 2).
3. Click **▶️ Run Backtest & Save**.

The result shows an IC table and a 5-panel chart set (signal, predicted vs. realised
return, equity curve, drawdown, exposure). The trained model is persisted to
`input/models/factor_model_<YYYYMMDD>.joblib` for daily signal generation.

> **Note:** Model **training** is a deliberate, periodic action done here in the
> Beta Book. The daily EOD pipeline does **not** retrain — it only generates signals
> from the latest saved model.

---

## 5. The Alpha Book

The Alpha Book is the **relative-value (RV)** workspace — market-neutral spread,
pairs, and volatility trades.

| Sub-tab | What it does |
|---------|--------------|
| **Candidates** | RV scanner: z-score slider, signal clusters, rich/cheap ranking |
| **Spread** | Spread analysis — sector PCA spreads, spread regression, treasury/policy/local/corporate, swap spreads, bond-swap spreads, futures term/net basis |
| **Pairs** | Pairs/spread trading: regression fit, hedge ratio, residual z-score, entry/exit signals |
| **Volatility** | Implied vs. historical vol surfaces, term structure, skew/smile, vega exposure |
| **Portfolio** | Alpha book allocation and current RV positions |
| **Backtest** | Historical RV strategy simulation, equity curves, drawdowns |

### 5.1 Reading a pairs signal

The Pairs tab fits a regression of one instrument on another, then monitors the
**residual z-score** against configurable entry/exit bands. A residual beyond the
entry band flags a candidate; mean-reversion of the residual to zero is the exit.
Confidence bands are derived from the residual standard deviation (see the
Methodology document for the statistics).

---

## 6. Run Center — Daily Operations

The **Run Center** is the operator's control panel. From here you drive the daily
pipeline and watch status/logs.

### 6.1 The standard daily flow

```
1. Update Data   →  pull fresh market data (Wind / local providers)
2. Run EOD       →  calibrate curves, generate factor signals, build books
3. Review        →  check Summary book and per-step status
```

### 6.2 Equivalent CLI commands

Everything in Run Center is also available from the command line:

| Command | Description |
|---------|-------------|
| `python main.py update-data` | Run data retrieval routines only |
| `python main.py update-data --force` | Force refresh even if data is current today |
| `python main.py eod` | Run the daily EOD pipeline (all strategy steps) |
| `python main.py eod --update-data` | Pull fresh data, then run EOD |
| `python main.py intraday` | Run the intraday pipeline |
| `python main.py refresh` | Run the intraday refresh chain (rates → credit → IRS → stat) |
| `python main.py refresh --steps rates irs` | Run specific refresh steps |
| `python main.py scheduler --interval 300 --mode refresh` | Periodic refresh during trading hours |
| `python main.py curve-backtest --btype IRS --start 2024-01-01 --end 2024-12-31` | Run a curve backtest |
| `python main.py refresh-instruments` | Refresh instrument definitions |
| `python main.py futures-analytics-backfill --start 2023-01-01` | Rebuild futures analytics history |

### 6.3 What the EOD pipeline produces

Each EOD run writes a folder `runs/<run_id>/` containing one JSON artifact per step:

```
runs/<run_id>/
├── run_meta.json           # run manifest: mode, as-of date, per-step status
├── curves_result.json      # curve calibration status
├── factors_result.json     # factor signal summary + backtest metrics
├── pairs_result.json       # pairs count and names
├── futures_result.json     # futures strategy metrics + equity curves
├── multiasset_result.json  # universe counts and names
├── derivatives_result.json # option greeks
└── factor_signals.json     # factor signal snapshot
```

Each step is **isolated** — if one step fails it is logged and skipped without
aborting the rest. The web tabs read these artifacts directly.

---

## 7. The Summary Book

The Summary book aggregates the Beta and Alpha books into a desk-level view.

| Sub-tab | What it shows |
|---------|---------------|
| **Books** | Combined portfolio KPIs + beta/alpha allocation tables |
| **Risk** | KPI strip (Total Long / Short / Net Exposure / Total DV01), net position by instrument, DV01 duration ladder (1Y–30Y), factor risk attribution, full position inventory |
| **Tickets** | Trade tickets generated from current target vs. actual positions |

The **Risk** sub-tab is the consolidated risk picture: a DV01 ladder stacked by
Bonds / Swaps / Futures, and factor risk attribution shown on a √-scale so that
large level factors do not visually dwarf small commodity factors.

---

## 8. Data, Directories & Configuration

### 8.1 Data directories (`settings/paths.py`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `DIR_INPUT` | `../input/` | Shared artifact store (pickle, JSON) |
| `DIR_OUTPUT` | `../output/` | Generated reports and exports |
| `DIR_DATA` | `../database/` | Raw historical market data |
| `DIR_MODELS` | `../input/models/` | Trained factor models (`.joblib`) |

### 8.2 Environment variables

| Variable | Default | Effect |
|----------|---------|--------|
| `FI_SHOW_LOG_WINDOW` | platform-dependent | `1` forces the log window, `0` suppresses it |
| `FI_DISABLE_WINDOWS_CURVE_MP` | `0` | `1` forces serial curve backtest on Windows |

### 8.3 Standalone module testing

Every strategy module can be run independently for development/debugging:

```bash
python futures/daily/main.py         # Futures portfolio strategy
python derivatives/pricer/main.py    # Option pricer
python pairs/main.py                 # Pairs regression (standalone)
python factors/main.py               # Factor model training
python multiasset/main.py            # Multi-asset universe + optimizer
python utils/dataviewer.py file.pkl  # Inspect any pickle artifact
```

---

## 9. Remote Access

`server.bat` starts a Cloudflare tunnel exposing the local app publicly:

```bat
python main.py daily-web    # terminal 1 — start the app
server.bat                  # terminal 2 — proxy 127.0.0.1:8080 via cloudflared
```

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Curves/prices empty | Data not retrieved (Wind unavailable / outside trading hours) | Run **Update Data** first, or use cached data |
| EOD step shows failed | Single step error (isolated) | Check Run Center logs; rerun that step |
| Browser shows `0.0.0.0` unreachable | Server binds all interfaces | Use `http://localhost:8080` (the platform resolves a real host automatically) |
| Backtest slow on Windows | Multiprocessing fallback | Set `FI_DISABLE_WINDOWS_CURVE_MP=1` for serial mode |
| Log window won't show | Platform default | Set `FI_SHOW_LOG_WINDOW=1` |

---

## 11. Glossary

- **EOD** — End of day; the daily batch calibration/reporting run.
- **Beta** — Systematic exposure to macro risk factors (the Beta Book).
- **Alpha** — Market-neutral relative-value return (the Alpha Book).
- **DV01** — Dollar value of 1 basis point; interest-rate sensitivity per bp.
- **IC** — Information coefficient; rank correlation between a feature and forward return.
- **ICIR** — IC information ratio; IC mean / IC std, a signal-quality measure.
- **Carry / Roll** — Return from holding (carry) and from the curve rolling down (roll).
- **Z-score** — Standardised deviation from a rolling mean; the rich/cheap gauge.
- **RV** — Relative value; market-neutral spread/pairs trading.
- **CTD / IRR / Net basis** — Cheapest-to-deliver, implied repo rate, and futures basis terms.
```
