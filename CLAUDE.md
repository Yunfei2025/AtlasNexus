# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

FIEngine (AtlasNexus) is a fixed-income and multi-strategy systematic investment platform. The system covers curve calibration, factor analysis, pairs trading, futures strategies, multi-asset portfolio construction, and derivatives pricing, all served through a Dash web dashboard.

## Environment setup

```bash
conda create -n dev python=3.9
conda activate dev
pip install -r requirements/production.txt
```

**macOS/Linux environment name:** `dev`. **Windows:** `prod`.

Optional dependencies that require manual installation:
- **WindPy** — Wind terminal SDK (not on PyPI); install from the Wind financial client
- **TA-Lib** — install the C library first, then `pip install TA-Lib`

## Running the application

```bash
python main.py              # daily web console → http://localhost:8080
python main.py daily-web    # same
python main.py intraday-web # intraday console → http://localhost:8081
python main.py eod          # run daily EOD pipeline
python main.py eod --update-data  # pull fresh data then run EOD
python main.py update-data  # data retrieval only
python main.py refresh      # intraday refresh (rates → OTR/OFR → credit → IRS → stat)
python main.py scheduler    # periodic refresh during trading hours
python main.py curve-backtest --btype IRS --start 2024-01-01 --end 2024-12-31
```

Each strategy module also has a standalone entry point for isolated development:

```bash
python futures/daily/main.py
python futures/backtest/dashboard.py
python derivatives/vol/main.py
python pairs/main.py
python factors/main.py
python multiasset/main.py
python utils/dataviewer.py <file.pkl>   # inspect any pickle artifact
```

## Tests

```bash
pytest            # ~36 tests, ~2s, no market data required
pytest -v
pytest tests/test_engine_schema.py   # schema layer in isolation
```

## Architecture

### Two-layer design

The platform implements a beta/alpha split:
- **Beta book (strategic):** long-horizon allocations via `multiasset/`, regime-aware tilts via `factors/`
- **Alpha book (tactical):** market-neutral / RV / intraday signals via `pairs/`, `futures/`, `derivatives/`

The `engine/` package orchestrates both layers; `portfolio/` runs the final risk aggregation and produces trade tickets.

### Data flow

```
Wind / local files → data/providers/ → DIR_DATA (../database/)
                                           ↓
python main.py eod → engine/pipeline/eod.py
    curves.interface.calibrate()   → runs/<id>/curves_result.json
    factors.interface.calibrate()  → runs/<id>/factors_result.json
    pairs.interface.calibrate()    → runs/<id>/pairs_result.json
    futures.interface.calibrate()  → runs/<id>/futures_result.json
    multiasset.interface.calibrate() → runs/<id>/multiasset_result.json
    derivatives.interface.calibrate() → runs/<id>/derivatives_result.json
                                           ↓
web/services/artifacts.py → web/tabs/ → Dash callbacks
```

Each pipeline step is isolated — a failing step is logged and skipped without aborting the rest.

### Key conventions

**`interface.py` pattern:** every strategy module exposes a single `calibrate()` function in its `interface.py`. The engine calls only this function; all internal logic stays within the module.

**Artifact-first:** the engine writes JSON artifacts to `runs/<run_id>/`; the web layer reads pre-computed artifacts rather than recomputing in Dash callbacks. Use `web/services/artifacts.py` to load them:

```python
from web.services.artifacts import load_step_result
result = load_step_result("futures")  # reads runs/<latest-eod>/futures_result.json
```

**Data retrieval convention:** `engine.data_update` discovers and calls `run(cfg)`, `main(cfg)`, or `retrieve(cfg)` from any module. New retrieval logic should expose one of those names.

**`engine/schema.py` contracts:** `PerformanceMetrics`, `BacktestResult`, and `RunManifest` define the shared artifact shapes. All performance values are plain floats (ratios, not percentages) to round-trip cleanly through JSON. `SCHEMA_VERSION` must be bumped on non-additive changes.

### Directory layout

| Path | Role |
|------|------|
| `engine/` | Orchestration: CLI, pipelines, artifact store, scheduler |
| `web/` | Dash dashboards; tabs under `web/tabs/`, apps in `web/apps/` |
| `curves/` | Curve calibration: TBond, CBond, IRS, credit, stat |
| `factors/` | Factor model training, prediction, backtest |
| `futures/` | Futures strategies: daily + intraday + backtest |
| `pairs/` | Pairs/spread trading: regression, stats, signals |
| `multiasset/` | Multi-asset universe, risk parity, factor optimizer |
| `derivatives/` | Options pricing (bond + IRS) and vol analysis |
| `portfolio/` | Portfolio optimizer (nlopt-based) |
| `surface/` | Yield surface calibration and visualization |
| `settings/` | All configuration (paths, symbols, instrument definitions) |
| `data/` | Data loaders and Wind/local file providers |
| `utils/` | Cross-cutting utilities (logging, I/O, plotting) |
| `runs/` | Engine run output — gitignored |

### External data directories (outside the repo)

Configured in `settings/paths.py` relative to project root (`bin-v4.0/../`):

| Variable | Default | Purpose |
|----------|---------|---------|
| `DIR_INPUT` | `../input/` | Shared artifact store (pickle, JSON) |
| `DIR_OUTPUT` | `../output/` | Generated reports and exports |
| `DIR_DATA` | `../database/` | Raw historical market data |
| `DIR_MODELS` | `../input/models/` | Trained factor models (.joblib) |

### Environment variables

| Variable | Effect |
|----------|--------|
| `FI_SHOW_LOG_WINDOW` | `1` to force Tk log window, `0` to suppress |
| `FI_DISABLE_WINDOWS_CURVE_MP` | `1` to force serial curve backtest on Windows |

## Remote access

`server.bat` starts a Cloudflare tunnel exposing the local app publicly. Start `python main.py daily-web` first, then run `server.bat` in a second terminal.
