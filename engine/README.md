## 
Multi-asset (beta / top-down): typically “allocate across broad risk premia” (rates duration, credit, equity, commodity, FX carry, etc.), then refine to sectors/curves/instruments. The objective is usually risk budgeting + diversification with clear exposure intent.
Multi-strategy (alpha / bottom-up): typically “allocate to independent return streams” (pairs, RV, intraday trend, vol carry), with the objective of uncorrelated alpha, controlled by backtest/live diagnostics and risk limits.
Refinements / suggestions
Beta vs alpha is not binary

Many strategies are “beta-like” but implemented bottom-up (e.g., equity momentum across futures).
Some “top-down” views can be expressed as alpha overlays (tactical tilts) on top of a strategic beta portfolio. A good architecture treats everything as strategies producing target exposures, then a portfolio allocator blends them.
Use a two-layer portfolio construction

Layer A (Beta book / Strategic): long-horizon allocations (weekly/monthly), regime-aware tilts via factors.
Layer B (Alpha book / Tactical): market-neutral / RV / intraday strategies, sized by estimated Sharpe, drawdown, turnover capacity.
A final risk aggregator (your multiasset + portfolio) produces:
final targets
risk report
trade tickets (manual execution)
Intraday should be treated as a separate “clock” Intraday systems need:

separate data ingestion/caching
separate slippage/turnover limits
separate risk limits (max intraday loss, max position time, max number of trades) Even if execution is manual, you’ll want intraday signal snapshots + suggested orders.

## engine/

This package is the **orchestration layer** for FIEngine.

- Strategy logic stays in existing packages: `portfolio/`, `multiasset/`, `factors/`, `curves/`, `pairs/`, `futures/`, `derivatives/`, etc.
- `engine/` provides a consistent way to run daily EOD and intraday workflows, write artifacts, and feed the `web/` dashboards.

### Key ideas


- **Artifact-first**: each run writes to `runs/<run_id>/` so results are reproducible and the UI can load the latest artifacts.
- **Manual execution supported**: the intended output is signals/targets/tickets instead of automated broker routing.
- **Retriever integration**: many packages already have `retrieve.py` scripts.
  `engine.data_update` provides a single place to call them.

### CLI entrypoint

The CLI lives in `engine/cli.py`. It currently supports:

- `eod` (daily pipeline stub)
- `intraday` (intraday pipeline stub)
- `update-data` (best-effort aggregator for `retrieve.py` modules)

### Data retrieval (`retrieve.py`)

By convention, `engine.data_update` attempts to import and call any of these functions if present:

- `run(cfg)`
- `main(cfg)`
- `retrieve(cfg)`

If a module does not match, add a thin adapter inside `engine/data_update.py`.

### Next wiring steps

1. In `engine/pipeline/eod.py`, call:
   - `portfolio` to build universe / investment pool
   - `factors` to infer regime and compute factor signals
   - `curves` for FI pricing / RV computations
   - `pairs` + `futures.daily` + `derivatives.vol` for strategy signals
   - `multiasset` to aggregate and size targets and compute risk
2. Write artifacts (`signals/`, `targets`, `risk`, `tickets`) into `runs/<run_id>/`.
3. Update `web/` dashboards to read artifacts instead of recomputing.
