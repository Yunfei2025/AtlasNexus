# FIEngine — AtlasNexus Systematic Investment Platform

A fixed-income and multi-strategy systematic investment platform built on Python and Dash.
Covers curve calibration, factor analysis, pairs trading, futures strategies,
multi-asset portfolio construction, and derivatives pricing — all accessible through
a unified web dashboard.

---

## Quick start

```bash
# macOS (double-click or terminal)
./START.sh          # or open START_mac.command

# Windows
START_win.bat

# Direct
python main.py              # same as daily-web
python main.py daily-web    # AtlasNexus Daily Console  → http://localhost:8080
python main.py intraday-web # AtlasNexus Intraday Console → http://localhost:8081
```

**Requires:** Python 3.9+, conda environment named `dev` (macOS/Linux) or `prod` (Windows).

---

## Installation

```bash
# Create environment
conda create -n dev python=3.9
conda activate dev

# Install runtime dependencies
pip install -r requirements/production.txt

# Optional: dev tools (pytest, ruff, black, jupyter)
pip install -r requirements/development.txt
```

**Optional packages (install separately):**
- **WindPy** — Wind terminal SDK (not on PyPI). Install from the Wind financial client.
- **TA-Lib** — Technical analysis C library used in `futures/backtest/`.
  Install the C library first, then `pip install TA-Lib`.

---

## CLI reference

All commands go through `python main.py <command>`.

| Command | Description |
|---------|-------------|
| *(no args)* or `daily-web` | Start AtlasNexus Daily Console (port 8080) |
| `intraday-web` | Start AtlasNexus Intraday Console (port 8081) |
| `eod` | Run the daily EOD pipeline (all strategy modules) |
| `eod --update-data` | Pull fresh data, then run EOD |
| `intraday` | Run the intraday pipeline |
| `update-data` | Run data retrieval routines only |
| `update-data --modules a.b.retrieve c.d.retrieve` | Run specific retrievers |
| `update-data --force` | Force refresh even if data is current |
| `refresh` | Run the intraday refresh chain (rates → credit → IRS → stat) |
| `refresh --steps rates irs` | Run specific refresh steps |
| `scheduler` | Start the periodic refresh scheduler during trading hours |
| `scheduler --interval 300 --mode refresh` | Custom interval / pipeline mode |
| `curve-backtest --btype IRS --start 2024-01-01 --end 2024-12-31` | Run curve backtest |

---

## Project structure

```
bin-v4.0/
├── main.py                     # Entry point — routes CLI to engine or web apps
│
├── engine/                     # Orchestration layer
│   ├── cli.py                  # CLI parser and dispatcher
│   ├── context.py              # RunConfig dataclass
│   ├── artifacts.py            # ArtifactStore (read/write runs/<id>/)
│   ├── schema.py               # Artifact contracts: PerformanceMetrics,
│   │                           #   BacktestResult, RunManifest
│   ├── data_update.py          # Aggregator for retrieve.py modules
│   ├── scheduler.py            # Periodic refresh scheduler
│   └── pipeline/
│       ├── eod.py              # Daily EOD pipeline (6 strategy steps)
│       ├── intraday.py         # Intraday pipeline
│       └── refresh.py         # Intraday refresh pipeline
│
├── web/                        # Unified Dash dashboard
│   ├── apps/
│   │   ├── atlasnexus_daily.py     # Daily console app (port 8080)
│   │   └── atlasnexus_intraday.py  # Intraday console app (port 8081)
│   ├── tabs/                   # Tab definitions (alpha/, beta/, atlas_*.py)
│   ├── core/                   # Shared layout, styles, scripts, load helpers
│   └── services/
│       └── artifacts.py        # find_latest_run(), load_step_result()
│
├── curves/                     # Curve calibration (TBond, CBond, IRS, credit, stat)
├── factors/                    # Factor model: training, prediction, backtest
├── futures/                    # Futures strategies: daily + intraday + backtest
├── pairs/                      # Pairs/spread trading: regression, stats, signals
├── multiasset/                 # Multi-asset universe, risk parity, factor optimizer
├── derivatives/                # Options pricing (bond + IRS) and vol analysis
├── portfolio/                  # Portfolio optimizer (nlopt-based)
├── surface/                    # Yield surface calibration and visualization
│
├── settings/                   # Configuration
│   ├── general.py              # Trading hours, app colours
│   ├── paths.py                # DIR_INPUT, DIR_OUTPUT, DIR_DATA
│   ├── futures.py              # Futures symbols and contract config
│   ├── wind.py                 # Wind data source config
│   └── fixed_income.py        # FI instrument definitions
│
├── data/                       # Data loaders and providers
│   ├── loader/                 # Generic data loading utilities
│   └── providers/              # Wind and local file providers
│
├── utils/                      # Cross-cutting utilities
│   ├── log_window.py           # Tk log window + logging setup
│   ├── io.py                   # File I/O helpers
│   ├── plot.py                 # Common plot utilities
│   └── dataviewer.py           # CLI pickle viewer: python utils/dataviewer.py file.pkl
│
├── runs/                       # Engine run output (gitignored)
│   └── <run_id>/
│       ├── run_meta.json           # Run manifest (mode, asof, step status)
│       ├── curves_result.json      # Curve calibration status
│       ├── factors_result.json     # Factor analysis summary + backtest metrics
│       ├── pairs_result.json       # Pairs count and names
│       ├── futures_result.json     # Futures strategy metrics + equity curves
│       ├── multiasset_result.json  # Universe counts and names
│       ├── derivatives_result.json # Option greeks
│       └── factor_signals.json     # Factor signal snapshot
│
├── requirements/
│   ├── production.txt          # Full runtime (pip install -r this)
│   ├── base.txt                # Minimal core for CI/scripts
│   └── development.txt        # production + testing/linting tools
│
├── tests/                      # Test suite (pytest)
└── docs/                       # Reference documents
```

---

## How the EOD pipeline works

```
python main.py eod
  └── engine/pipeline/eod.py
        ├── curves.interface.calibrate()     → curves_result.json
        ├── factors.interface.calibrate()    → factors_result.json
        ├── pairs.interface.calibrate()      → pairs_result.json
        ├── futures.interface.calibrate()    → futures_result.json
        ├── multiasset.interface.calibrate() → multiasset_result.json
        ├── derivatives.interface.calibrate()→ derivatives_result.json
        └── factor_signals step             → factor_signals.json
```

Each step is isolated — a failing step is logged and skipped without
aborting the rest. Results are persisted to `runs/<run_id>/` so the web
dashboard can read pre-computed artifacts instead of recomputing.

Web tabs can read any step's latest output:

```python
from web.services.artifacts import load_step_result
result = load_step_result("futures")   # reads runs/<latest-eod>/futures_result.json
```

---

## Data directories

Configured in `settings/paths.py` relative to the project root:

| Variable | Default path | Purpose |
|----------|-------------|---------|
| `DIR_INPUT` | `../input/` | Shared artifact store (pickle, JSON) |
| `DIR_OUTPUT` | `../output/` | Generated reports and exports |
| `DIR_DATA` | `../database/` | Raw historical market data |
| `DIR_MODELS` | `../input/models/` | Trained factor models (.joblib) |

---

## Standalone module testing

Every strategy module ships a `dashboard.py` and/or `main.py` that can be
run independently for development and debugging:

```bash
python futures/daily/main.py        # Futures portfolio strategy analysis
python futures/backtest/dashboard.py # Futures backtest Dash app
python derivatives/vol/main.py      # Vol strategy analysis
python derivatives/pricer/main.py   # Option pricer
python pairs/main.py                # Pairs regression (standalone mode)
python factors/main.py              # Factor model training
python multiasset/main.py           # Multi-asset universe + optimizer
python utils/dataviewer.py file.pkl # Inspect any pickle artifact
```

---

## Running tests

```bash
pytest            # 36 tests, ~2s, no market data required
pytest -v         # verbose output
pytest tests/test_engine_schema.py  # schema layer only
```

---

## Remote access

`server.bat` starts a Cloudflare tunnel exposing the local app publicly:

```bat
server.bat   # proxies http://127.0.0.1:8080 via cloudflared
```

Run `python main.py daily-web` first, then `server.bat` in a second terminal.

---

## Environment variables

| Variable | Default | Effect |
|----------|---------|--------|
| `FI_SHOW_LOG_WINDOW` | platform-dependent | `1` to force Tk log window, `0` to suppress |
| `FI_DISABLE_WINDOWS_CURVE_MP` | `0` | `1` to force serial curve backtest on Windows |
