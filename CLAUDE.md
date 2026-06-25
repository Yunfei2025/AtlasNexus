# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Quick Start

**FIEngine** is a Python-based fixed-income and multi-strategy systematic investment platform with a web dashboard (Dash).

```bash
# Start development environment
conda activate dev    # or 'prod' on Windows
python main.py        # starts daily-web on port 8080 (AtlasNexus Daily Console)
```

**Key commands:**
- `python main.py daily-web` → Dash app (http://localhost:8080)
- `python main.py intraday-web` → Intraday Dash app (http://localhost:8081)
- `python main.py eod` → Run daily EOD pipeline
- `python main.py eod --update-data` → Fetch fresh data, then run pipeline

See `main.py` for full CLI reference and `README.md` for environment setup.

---

## Architecture Overview

### High-Level Structure

```
FIEngine (bin-v4.0/)
├── engine/           Strategy orchestration: CLI, pipelines, artifact store
├── web/              Dash dashboards: daily + intraday consoles
├── curves/           Curve calibration (TBond, CBond, IRS, credit, stat)
├── factors/          Factor model: training, prediction, regime inference
├── futures/          Daily/intraday/backtest strategies
├── pairs/            Spread trading: regression, stats, signals
├── multiasset/       Universe construction, risk parity, optimizer
├── derivatives/      Options pricing + vol analysis
├── portfolio/        Portfolio construction (nlopt-based)
├── surface/          Yield surface calibration
├── settings/         Configuration (trading hours, symbols, paths)
├── data/             Data loaders, Wind provider, file I/O
├── utils/            Cross-cutting utilities (logging, plotting)
└── runs/             **Gitignored** artifact store (runs/<run_id>/*)
```

### Data Flow: EOD Pipeline

```
engine/pipeline/eod.py (orchestrates all steps)
  ├─ curves.interface.calibrate()     → runs/*/curves_result.json
  ├─ factors.interface.calibrate()    → runs/*/factors_result.json
  ├─ pairs.interface.calibrate()      → runs/*/pairs_result.json
  ├─ futures.interface.calibrate()    → runs/*/futures_result.json
  ├─ multiasset.interface.calibrate() → runs/*/multiasset_result.json
  ├─ derivatives.interface.calibrate()→ runs/*/derivatives_result.json
  └─ factor_signals step             → runs/*/factor_signals.json
```

Each module is **isolated**; if one fails, others still run. Artifact naming follows `<module>_result.json`.

### Web Layer: Dash Dashboard

```
web/
├── apps/
│   ├── atlasnexus_daily.py       Port 8080: daily console
│   └── atlasnexus_intraday.py    Port 8081: intraday console
├── tabs/                         Tab layout definitions
│   ├── alpha/                    Alpha Book (6 sub-tabs)
│   ├── beta/                     Beta Book (strategic allocations)
│   ├── atlas_*.py                Shared tabs (FI, Volatility, Trend, etc.)
│   └── atlas_components.py       Dash component helpers (button, card, badge, etc.)
├── core/
│   ├── server.py                 Shared Dash server instance
│   ├── styles.py                 Design constants + Plotly theme
│   ├── content.py                Static HTML (headers, footers)
│   └── load.py                   Data loaders for UI
└── assets/                       CSS, fonts, JS
    ├── design.css   Main design system (colors, spacing, typography)
    ├── colors.css, spacing.css, typography.css   **Canonical tokens**
    └── *.js                       Interactive scripts (resize iframes, etc.)
```

**Key patterns:**
- Layouts are defined in `web/tabs/<module>/<module>.py` (e.g., `alpha/layouts.py`).
- Dash callbacks live in `web/tabs/<module>/callbacks/` if there are many.
- Component helpers in `atlas_components.py` reduce boilerplate: `button("text", id="x")` instead of inline HTML.
- Pre-computed artifacts are loaded via `web/services/artifacts.load_step_result("futures")`.

---

## Configuration & Settings

All configuration lives in `settings/`:

| Module | Purpose |
|--------|---------|
| `settings/general.py` | Trading hours, app colors |
| `settings/paths.py` | `DIR_INPUT`, `DIR_OUTPUT`, `DIR_DATA`, `DIR_MODELS` (relative to project root) |
| `settings/futures.py` | Futures symbols, contract specs |
| `settings/wind.py` | Wind data provider config |
| `settings/fixed_income.py` | FI instrument definitions |

**Data directories** (see `settings/paths.py`):
- `../input/` — Artifacts (pickle, JSON)
- `../output/` — Reports and exports
- `../database/` — Raw historical data
- `../input/models/` — Trained factor models

---

## Design System & Styling

### Token Files (Canonical Source)

Located in `web/assets/`:

| File | Purpose | Scope |
|------|---------|-------|
| `colors.css` | Color tokens (`--accent-blue`, `--surface-panel`, etc.) | All colors; aliased to `--an-*` |
| `spacing.css` | Spacing (`--app-pad-x`, `--radius-md`, etc.) | Layout spacing, gaps, padding |
| `typography.css` | Typography (`--font-sans`, `--fs-body`, etc.) | Fonts, sizes, weights, line-height |

These are CSS custom properties (variables). **Do not hardcode colors/spacing in component files.**

### Dash Component Helpers (`atlas_components.py`)

Thin wrappers around Dash HTML/DCC components that apply consistent styling.

```python
from web.tabs.atlas_components import button, card, badge, label_field

# Instead of:
html.Button("Run", style={"background": "#...", "color": "#...", ...})

# Use:
button("Run", id="my-btn", variant="primary")  # variants: primary, secondary, success, danger, warning
```

**Constants in `atlas_components.py`:**
- `_NAVY_800`, `_NAVY_700`, `_BORDER`, `_BLUE`, `_AMBER`, `_TEXT`, `_MUTED`, etc. — **use these, not hardcoded hex**.

### Design Philosophy

- **Accent colors:**
  - Alpha Book: `--accent-amber` (`#e0a23c`)
  - Beta Book: `--accent-blue` (`#3d8bd4`)
  - Futures/Trend: `--accent-green` (`#2f9d6b`)
  - Volatility/Vol: `--accent-cyan` (`#45b6e6`)

- **Typography:** use `--type-label` (uppercase labels), `--type-body` (regular text), `--type-th` (table headers).

- **Layout:** panels are `--navy-700` (`#122a4c`), inputs are `--navy-600` (`#17345c`), borders are `--border-default` (`#1e3a5f`).

---

## Alpha & Beta Books

### Alpha Book (6 sub-tabs)

Located in `web/tabs/alpha/`:

| Tab | File | Purpose |
|-----|------|---------|
| Candidates | `candidates.py` | Select instruments via Z-score, seasonal gate |
| Portfolio | `portfolio.py` | Build allocations; risk parity optimizer |
| Backtest | `backtest.py` | Backtest individual spreads + portfolios |
| Spread | `spread.py` | Visual exploration of spread dynamics |
| Pairs | `pairs.py` | Interactive pairs regression, confidence bands |
| Volatility | `volatility.py` | Vol trading strategy KPIs, returns analysis |

**Subdirectories:**
- `alpha/callbacks/` — Dash callbacks (stateful interactions)
- `alpha/backtest/` — Backtest engine + dashboard

**Alpha Book optimization:** See `docs/dev/ALPHA_BOOK_OPTIMISATION.md` for layout improvements (Z-Score+Direction unified panel, collapsible seasonal gate, 2-column sidebar for Spread tab, etc.).

### Beta Book (Strategic)

Located in `web/tabs/beta/`:
- Top-down multi-asset allocation
- Factor tilts and regime views
- Risk budgeting

---

## Web Modules by Responsibility

### Shared Components & Utilities

| Module | Responsibility |
|--------|-----------------|
| `web/core/server.py` | Dash app instance (shared by all apps) |
| `web/core/styles.py` | Design constants (colors, Plotly template, etc.) |
| `web/core/content.py` | Static HTML (page headers, footers, modals) |
| `web/core/load.py` | Data loaders for UI (loads artifacts into memory) |
| `web/core/graphs.py` | Common chart builders |
| `web/core/funcs.py` | Helper utilities (format numbers, etc.) |
| `web/tabs/atlas_components.py` | Reusable Dash components with styling |
| `web/tabs/atlas_styles.py` | Design tokens + Plotly theming |

### Service Layer

| Module | Responsibility |
|--------|-----------------|
| `web/services/artifacts.py` | Read pre-computed results: `load_step_result("futures")`, `find_latest_run()` |
| `web/services/jobs.py` | Job queue for long-running engine tasks (eod, intraday) |

### Tab Modules (Specific Content)

Each `atlas_*_tabs.py` file is a tab definition:
- **atlas_fi_tabs.py** — Fixed-income curves, pairs, spreads
- **atlas_volatility_tabs.py** — Vol strategy KPIs + charts
- **atlas_trend_tabs.py** — Trend/momentum strategies
- **atlas_pricer_tab.py** — Option pricer
- **atlas_market_data_tab.py** — Data overview
- **atlas_multiasset_tabs.py** — Asset universe
- **atlas_factor_backtest_tabs.py** — Factor model backtest results
- **atlas_alpha_tabs.py** — Router to alpha submodule (see `alpha/`)

---

## Artifact Loading Pattern

Pre-computed results live in `runs/<run_id>/` (one directory per EOD/intraday run).

```python
from web.services.artifacts import load_step_result, find_latest_run

# Load the latest futures backtest result
futures_result = load_step_result("futures")
# → parses runs/<latest-eod>/futures_result.json

# Find metadata of the last run
run_meta = find_latest_run()
```

**Result files are JSON** (not pickle) — human-readable for debugging. Schema defined in `engine/schema.py`.

---

## Key Dependencies

| Package | Use |
|---------|-----|
| `dash`, `plotly` | Web dashboard, interactive charts |
| `pandas`, `numpy`, `scipy` | Data analysis, numerical computing |
| `scikit-learn`, `statsmodels` | ML models, statistical tests |
| `nlopt` | Portfolio optimization |
| `matplotlib` | Static plots (fallback) |
| `requests` | HTTP client (data APIs) |
| `openpyxl`, `xlsxwriter` | Excel I/O |
| `chinese-calendar` | Market holidays |

**Optional (install separately):**
- **WindPy** — Wind terminal SDK (not on PyPI). Provides live/historical market data.
- **TA-Lib** — Technical analysis (used in `futures/backtest/`). Requires C library.

---

## Module Interface Pattern

Each strategy module (`curves/`, `factors/`, `pairs/`, etc.) provides:

```python
# In curves/__init__.py (or curves/interface.py)
def calibrate(cfg: RunConfig) -> CurvesResult:
    """Calibrate curves; return result dict."""
    # Computation
    return CurvesResult(...)

# In curves/retrieve.py (optional)
def run(cfg: RunConfig):
    """Data retrieval for curves module. Called by engine/data_update.py."""
    pass
```

**EOD pipeline** calls all `interface.calibrate()` functions and writes artifacts.

---

## CSS Conventions

All styling is **CSS custom properties** (variables). Never hardcode colors or spacing.

**File organization:**
- `design.css` — Main design system (panels, buttons, tables, modebar, etc.)
- `atlasnexus_tabs.css` — Tab-specific overrides
- `app.css`, `style.css` — Legacy/global styles (prefer tokens)

**When adding a new component:**
1. Define layout in Python (e.g., `html.Div([...], className="my-panel")`)
2. Add styles to `design.css` using variables: `background: var(--surface-panel)`
3. Use `atlas_components.py` helpers instead of inline styles

**Example:**
```css
/* design.css */
.my-panel {
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  padding: var(--panel-pad);
}
```

```python
# Python layout
html.Div([...], className="my-panel")
```

---

## Module-Specific Development

### Standalone Module Testing

Each strategy module can run independently for development:

```bash
python futures/daily/main.py           # Futures analysis
python futures/backtest/dashboard.py   # Backtest dashboard
python derivatives/vol/main.py         # Vol strategy
python pairs/main.py                   # Pairs regression
python factors/main.py                 # Factor training
python multiasset/main.py              # Universe + optimizer
```

These are useful for **isolated debugging** without running the full EOD pipeline.

### Data Retrieval (`retrieve.py`)

Many modules have a `retrieve.py` script that pulls raw data. The engine aggregates them:

```bash
python main.py update-data
python main.py update-data --modules curves.retrieve futures.retrieve
python main.py update-data --force    # Ignore cache; refresh everything
```

---

## Testing

No formal test suite exists yet. For critical functionality:

1. Run the module standalone (e.g., `python futures/daily/main.py`).
2. Inspect output pickles with `python utils/dataviewer.py file.pkl`.
3. Check `runs/<run_id>/` artifacts after `python main.py eod`.

---

## Environment Variables

| Variable | Default | Effect |
|----------|---------|--------|
| `FI_SHOW_LOG_WINDOW` | platform-dependent | `1` to force Tk log window, `0` to suppress |
| `FI_DISABLE_WINDOWS_CURVE_MP` | `0` | `1` to force serial curve backtest on Windows |
| `WEB_LOG_TIMINGS` | `0` | `1` to log request/response times |

---

## Debugging Tips

1. **Inspect artifacts:** `python utils/dataviewer.py runs/<run_id>/curves_result.json`
2. **Watch logs:** `tail -f logs/` (if log files are present)
3. **Reload module:** Dash hot-reloads CSS/JS; Python changes require app restart.
4. **Check run metadata:** `cat runs/<run_id>/run_meta.json` (shows step status)
5. **Web browser console:** Check F12 → Console for Plotly/JS errors.

---

## Common Tasks

### Add a new Dash tab

1. Create `web/tabs/atlas_mynew_tab.py` with a `build_layout()` function.
2. Register in the app:
   ```python
   # In web/apps/atlasnexus_daily.py
   from web.tabs.atlas_mynew_tab import build_layout as build_mynew
   tabs.append(dcc.Tab(label="My New Tab", children=build_mynew()))
   ```
3. Add callbacks in `web/tabs/atlas_mynew_tab.py` or in a separate `callbacks/` directory.

### Use a component helper

```python
from web.tabs.atlas_components import button, card, badge, label_field

button("Scan", id="btn-scan", variant="primary")
card(children=[...], title="Results", accent="blue")
badge("BUY", tone="buy")  # tone: buy, sell, neutral
label_field("Threshold", dcc.Input(...))
```

### Load a pre-computed artifact

```python
from web.services.artifacts import load_step_result

@app.callback(
    Output("graph-id", "figure"),
    Input("tab-id", "value"),
)
def update_graph(tab):
    result = load_step_result("futures")
    # result is a dict parsed from JSON
    return build_chart(result["data"])
```

### Update CSS without restarting

1. Edit `web/assets/design.css`.
2. Refresh the browser (Cmd+R / Ctrl+R).
3. Dash auto-detects CSS changes.

---

## Gotchas & Best Practices

- **Avoid circular imports:** `web/core/` should not import from strategy modules (`curves/`, `futures/`, etc.).
- **Stateless callbacks:** Dash callbacks should be pure functions — no global state. Use `dcc.Store` for client-side state.
- **Use artifact caching:** Don't re-run computations in the UI. Load pre-computed `runs/<run_id>/` artifacts instead.
- **Color constants:** Always use `_NAVY_700`, `_BLUE`, `_AMBER`, etc. from `atlas_components.py`. Never hardcode hex.
- **Wind data:** If `WindPy` is not installed, some data providers will error gracefully. Check logs.
- **Windows multiprocessing:** Some curve backtests use multiprocessing; set `FI_DISABLE_WINDOWS_CURVE_MP=1` if needed.

---

## Documentation References

- **README.md** — Quick start, CLI commands, directory structure
- **engine/README.md** — Orchestration layer concepts
- **docs/dev/** — Implementation guides (e.g., `ALPHA_BOOK_OPTIMISATION.md`)
- `requirements/production.txt` — Full dependency list with notes

---

## Remote Access

The app can be exposed publicly via Cloudflare tunnel:

```bash
# Terminal 1:
python main.py daily-web

# Terminal 2:
server.bat    # Windows only; starts cloudflared tunnel
```

This proxies `http://localhost:8080` publicly.
