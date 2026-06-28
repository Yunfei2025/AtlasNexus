# AtlasNexus — Model Methodology

> **Document type:** Model methodology & technical reference.
> **Purpose:** Independent review/validation, model-risk assessment, and onboarding
> for further development.
> **Audience:** Quant researchers, model-risk reviewers, and engineers extending the platform.
> **Status:** Draft for review — to be polished in Claude Design.

This document describes *what the models do and why*. It cross-references the
implementing modules so a reviewer can trace every claim to code. Where a parameter
default is given, it is the shipped default and is configurable.

---

## 0. System Overview & Data Flow

AtlasNexus is structured as a **library of strategy modules** behind a thin
**engine orchestration layer** and a **Dash presentation layer**.

```
Market data (Wind / local providers)
        │  retrieve.py modules
        ▼
Engine pipelines  (engine/pipeline/{eod,intraday,refresh}.py)
        │  thin interfaces: <module>.interface.calibrate(cfg, store)
        ▼
Strategy modules: curves · factors · pairs · futures · multiasset · derivatives
        │  write JSON-serializable summaries
        ▼
ArtifactStore → runs/<run_id>/*.json   (engine/artifacts.py, engine/schema.py)
        │  read-only
        ▼
Web terminal (web/) — renders pre-computed artifacts
```

**Design invariants relevant to model risk:**

1. **Step isolation** — each module's `calibrate()` is wrapped; a failure is logged
   and skipped, so one model error cannot silently corrupt another's output.
2. **Artifact contract** — `engine/schema.py` defines versioned dataclasses
   (`PerformanceMetrics`, `BacktestResult`, `RunManifest`) with explicit JSON
   (de)serialization. `SCHEMA_VERSION` is bumped on non-additive changes.
3. **Train/serve separation** — factor *models are trained deliberately* in the Beta
   Book and persisted (`input/models/factor_model_<YYYYMMDD>.joblib`); the EOD
   pipeline only *generates signals* from the latest saved model. This prevents
   look-ahead retraining inside the daily run.

---

## 1. Performance & Risk Metric Conventions

Defined in `engine/schema.py` (`PerformanceMetrics`), matching
`futures/backtest/metrics.py`:

| Metric | Definition |
|--------|-----------|
| `total_return` | Geometric: `prod(1 + r) − 1` |
| `ann_return` | Arithmetic annualized: `mean(r) · periods_per_year` |
| `ann_vol` | `std(r, ddof=1) · sqrt(periods_per_year)` |
| `sharpe` | `(ann_return − rf) / ann_vol` |
| `max_drawdown` | Most-negative `(equity − cummax)/cummax`, ≤ 0 |
| `calmar` | `ann_return / |max_drawdown|` |

> **Reviewer note:** Sharpe uses **arithmetic** annualization while `total_return`
> is **geometric** — this is an intentional, documented convention. When comparing
> across modules, confirm `periods_per_year` matches the return frequency.

---

## 2. Curve Calibration (`curves/`)

### 2.1 Daily calibration chain

`curves.interface.calibrate()` → `curves.initialise.main()` runs sequentially:

```
Trend → BondCurve(TBond) → BondCurve(CBond) → CreditSpread → IRS → Stat → Pairs
```

Each generator writes pickle artifacts to `DIR_INPUT`. If upstream data retrieval
is unavailable (Wind down / outside trading hours / quota), calibration is
**skipped gracefully** and reported as a warning rather than failing the run.

### 2.2 Affine factor curve model (`curves/affine/affine.py`)

The bond/IRS curves use an **affine factor model**. Numerical robustness is built in:

- **PSD projection** (`_project_to_psd`) — symmetrizes the covariance and clips
  eigenvalues to `≥ 1e-10`, guaranteeing a valid covariance even from noisy inputs.
- **Tikhonov-regularized solve** (`_solve_regularized_system`) — ridge term scaled to
  the trace of `BᵀB` (`ridge_scale = 1e-8`), with `lstsq` fallback and an
  `max_abs_factor = 1e6` clamp to suppress blow-ups on ill-conditioned systems.
- Sympy-based symbolic matrices are cached via hashable-tuple conversion for speed.

Supporting engines: `curves/affine/bootstrap.py` (zero-curve bootstrap),
`curves/affine/pricingYield.py` (instrument pricing/yield), `curves/affine/curve.py`.

### 2.3 Calibration utilities (`curves/calibration/`)

- `irscurves.py`, `irs/` — IRS curve construction (FR007).
- `regime.py` — regime detection used by trend/selection logic.
- `stat.py` — statistical (rich/cheap) layer feeding z-scores and stationarity flags.
- `trend.py`, `selector.py`, `hedge.py` — trend, instrument selection, hedge ratios.

### 2.4 Curve backtest (`curves/backtest/`)

`Backtestor` (driven by `python main.py curve-backtest`) revalues the calibration
over a historical window with configurable parallelism. Use it to assess **fit
stability** and **parameter sensitivity** of the curve models.

> **Review focus:** (a) sensitivity of fitted curves to the ridge scale and PSD
> floor; (b) behaviour at sparse-quote tenors; (c) consistency of the skip-on-missing-
> data path so backtests are not silently run on stale inputs.

---

## 3. Factor (Beta) Model (`factors/`, `multiasset/factor_model.py`)

This is the platform's most elaborate model and the primary review target. It is a
**walk-forward, IC-driven, regime-aware factor model** with causal position sizing.

### 3.1 Layering

| Layer | File | Responsibility |
|-------|------|----------------|
| EOD signal generation | `factors/interface.py`, `factors/engine/factor_engine.py` | Generate daily signals from the latest saved model (no training) |
| Backtest orchestration | `multiasset/factor_backtest.py` | `run_factor_backtest` dispatch; yield→return conversion; `factor-rates.pkl` |
| The model | `multiasset/factor_model.py` | `run_factor_model_backtest` (walk-forward), `build_features`, `_train_ic_model`, `build_position_series` |
| Selection | `factors/engine/selector.py` | `FactorSelector` — IC threshold, significance, diversification, VIF, top-N |
| Inputs | `input/factor-rates.pkl`, `data/macro-px.pkl`, curve `*.pkl` | Factor levels, macro series, raw tenor curves |

### 3.2 Feature library (`build_features`, computed once on full history)

- **Momentum:** 5/10/20/60/120/252-day, plus EMA crosses.
- **Value / mean-reversion:** rolling z-score (60/120/252), percentile rank, value-momentum.
- **Volatility:** 10/20/60-day realised vol and vol ratios.
- **Carry / curve** *(yield factors only)*: slope, curvature, roll-down.
- **Cross-factor:** differences within the same asset class.
- **Macro:** `MACRO_*` level and percent-change from `data/macro-px.pkl`.
- Columns with **>50% NaN are dropped**.

### 3.3 Targets

- **Yield factor:** `r = −D · Δy / 100` (duration-adjusted return).
- **Price factor:** `r = pct_change`.
- Forward returns computed for horizons **H ∈ {1, 5, 20}** days.

### 3.4 Walk-forward training (leakage controls)

Monthly test windows, with explicit anti-leakage gaps:

```
train window = [cursor − train_months,  cursor − purge_gap]
test  window = [cursor,  cursor + 1 month)   ── drop first `embargo_days`
```

Per test window, for each horizon H:

1. `_compute_ic_metrics()` — **Spearman IC**, EWMA-weighted (halflife 63 days).
2. **Trend-regime veto** — zero out z-score/value features when in a trend
   (prevents fading a strong directional move).
3. `FactorSelector.select_factors()` — keep features with `IC ≥ threshold`
   (default 0.05), passing significance, diversification, and **VIF** filters; cap
   at **top-N** (default 8).
4. `_train_ic_model()` — feature weight = **signed Spearman IC** of that feature vs.
   forward return H (an IC-weighted linear combination, not OLS — robust to outliers/scale).
5. `_predict_ic_model(test)` — out-of-sample predicted return.

Horizons are **blended by mean |IC|** into a single `predicted_return`. The trained
model is persisted to `input/models/factor_model_<YYYYMMDD>.joblib`.

### 3.5 Position sizing (`build_position_series`, causal)

```
smoothed  = rolling_mean(pred, signal_smooth_days)
pred_z    = rolling_zscore(smoothed, 60)
icir_w    = tanh(ICIR / 0.25).shift(1)        # signal-quality weight, lagged
vol_scale = (target_vol / realised_vol_60d).shift(1)  # vol target, capped at max_leverage
position  ∝ pred_z · icir_w · vol_scale
```

Every term that could introduce look-ahead is **`.shift(1)`-lagged**, making sizing
strictly causal. ICIR-weighting down-sizes low-quality signals; vol-targeting holds
risk roughly constant; leverage is capped.

### 3.6 UI parameters → `FactorModelConfig`

| UI control | Field | Default |
|------------|-------|---------|
| Train window (months) | `train_months` | 12 |
| IC threshold | `ic_threshold` | 0.05 |
| Top N features | `top_n` | 8 |
| Backtest period (years) | `period_years` | 2 |

### 3.7 Bias & overfitting audit (for reviewers)

The companion dev note `docs/dev/beta-backtest-factor-model-workflow.md` audits this
path. Key questions a validator should confirm:

- **Leakage:** are `purge_gap` and `embargo_days` large enough relative to the
  longest feature lookback (252d) and longest horizon (20d)?
- **Selection bias:** IC threshold + top-N applied **per walk-forward window** on
  training data only — confirm no full-sample selection leaks into OOS.
- **Multiple testing:** many features × horizons → confirm significance filtering
  and diversification/VIF adequately control false discovery.
- **Regime veto:** validate the trend detector itself is causal.
- **Sizing robustness:** sensitivity of Sharpe to `signal_smooth_days`, the
  `tanh(ICIR/0.25)` shape, `target_vol`, and `max_leverage`.

> Related roadmap: `docs/dev/factor-model-improvement-plan.md`.

---

## 4. Relative Value: Pairs & Spreads (`pairs/`)

### 4.1 Regression (`pairs/stats.py`)

A pair is modelled by OLS (via `statsmodels`) of one leg on another, encapsulated in
`RegressionResults`:

- Stores `intercept`, `slope_per_step` (the **hedge ratio**), `r2`, `n_obs`.
- **Residual dispersion** uses `std(residuals, ddof=2)` (correct degrees of freedom
  for a two-parameter regression) to build **confidence bands**.
- Signals are driven by the **residual z-score** vs. configurable entry/exit bands;
  mean-reversion of the residual is the exit.

### 4.2 Spread families (Alpha Book → Spread)

Sector PCA spreads, spread regression, treasury/policy/local/corporate spreads, swap
spreads, bond-swap spreads, and futures term/net basis. The statistical layer
(`curves/calibration/stat.py`) supplies stationarity flags and z-scores so candidates
are only flagged when the relationship is statistically stable.

> **Review focus:** stationarity/cointegration testing rigor, lookback choice for the
> regression window, and stability of the hedge ratio through regime shifts.

---

## 5. Futures Strategies (`futures/`)

| Sub-package | Role |
|-------------|------|
| `futures/daily/` | Daily portfolio strategy: `strategy_system.py`, `selector.py`, `blender.py`, `backtester.py`, `portfolio.py` |
| `futures/backtest/` | Backtest engine: `strategies.py`, `metrics.py`, `regime.py`, `data_loader.py` |
| `futures/intraday/` | Intraday monitoring and execution |

Futures analytics (IRR / FYTM / CTD / contract closes) are maintained via
`python main.py futures-analytics-backfill`, which refreshes `futures-db.pkl` and
rebuilds `futures-analytics.pkl` (incremental append or full rewrite).

> **Review focus:** roll/CTD assumptions, the regime classifier feeding strategy
> selection, and the blender's combination logic. Note futures uses **TA-Lib**
> (optional dependency).

---

## 6. Multi-Asset Risk & Allocation (`multiasset/`)

### 6.1 Universe (`multiasset/main.py`)

`create_bond_universe()` and `create_spread_universe()` build the bond and spread
asset sets (`MultiFactorBondAsset`, `Asset`).

### 6.2 vol^0.5 risk budgeting (`multiasset/budget.py`)

`derive_vol_sqrt_budgets()` converts a factor-vol map to **vol^0.5 risk budgets**:
higher-vol factors (Level > Slope > Curvature) get more budget, but the model sits
**between equal-risk and vol-proportional**, avoiding over-concentration in the
highest-vol factor. Missing factors fall back to `ESTIMATED_FALLBACK_VOL`.

### 6.3 Factor risk-parity optimizer (`multiasset/factor_optimizer.py`)

`FactorRiskParityOptimizer` allocates capital so that **each risk factor contributes
equally to total portfolio risk** (not equal asset weight). At each rebalance:

1. Load the configured portfolio risk factors.
2. Convert factor levels into price-return-space volatility estimates.
3. Estimate **EWMA factor vols** (`ewma_lambda = 0.94`) and EWMA covariance.
4. Solve (SciPy `minimize`) for weights equalising factor risk contribution.

PCA risk-factor analysis (`pca_analyzer.py`) supports the factor decomposition.

> **Review focus:** EWMA λ choice and lookback windows; covariance conditioning;
> the level→return-space conversion for yield factors; and whether the √-vol budget
> is the intended risk philosophy vs. strict equal risk.

---

## 7. Derivatives (`derivatives/`)

- `derivatives/pricer/` — option pricing for bond and IRS underlyings; greeks
  (delta, gamma, vega, theta).
- `derivatives/vol/` — implied vs. historical volatility, surfaces, skew/smile,
  vega exposure.
- `derivatives.interface.calibrate()` emits option greeks to `derivatives_result.json`.

> **Review focus:** pricing model assumptions (lognormal vs. normal/Bachelier for
> rates), day-count/discounting conventions, and surface construction/interpolation.

---

## 8. Yield Surface (`surface/`)

A standalone yield-surface calibration and visualization module
(`surface/app.py`, `config.py`, `data.py`, `callbacks.py`, `layout.py`) rendering the
calibrated surface across tenor × maturity for rich/cheap inspection.

---

## 9. Reproducibility & Auditability

- **Versioned runs:** every EOD writes `runs/<run_id>/run_meta.json` (mode, as-of
  date, per-step status) plus one JSON per step. Runs are immutable records.
- **Schema versioning:** `SCHEMA_VERSION` in `engine/schema.py` gates artifact-shape
  changes; the web layer reads a stable contract.
- **Model versioning:** factor models carry the training date in the filename.
- **Deterministic pipeline:** given the same inputs, the EOD chain is reproducible;
  `OMP_NUM_THREADS=1` is set in the factor engine to stabilize numerics.
- **CI:** ~36 fast tests, including a pure-python schema-layer suite that needs no
  market data (`pytest tests/test_engine_schema.py`).

---

## 10. Known Limitations & Development Notes

| Area | Limitation / open item |
|------|------------------------|
| Data dependency | Live calibration needs Wind; without it, runs use cached data and skip live steps. Backtests must confirm input freshness. |
| Factor model | Sharpe is sensitive to sizing hyperparameters (§3.7); selection/embargo settings need periodic revalidation. |
| Annualization | Mixed arithmetic/geometric conventions (§1) — keep consistent when adding metrics. |
| Optional deps | TA-Lib (futures) and WindPy are not on PyPI; features degrade if absent. |
| Windows MP | Curve backtest multiprocessing can require serial fallback (`FI_DISABLE_WINDOWS_CURVE_MP=1`). |

### Suggested review sequence for a validator

1. Read this document end-to-end, then `docs/dev/beta-backtest-factor-model-workflow.md`.
2. Trace one factor through `build_features → walk-forward → build_position_series`.
3. Reproduce a backtest from the Beta Book and confirm OOS metrics match the artifact.
4. Stress the leakage controls (vary `purge_gap`, `embargo_days`) and observe Sharpe.
5. Inspect a `runs/<id>/` folder and validate each artifact against `engine/schema.py`.

---

## Appendix A — Module → Responsibility Map

| Module | Core methodology |
|--------|------------------|
| `curves/` | Affine factor curves, PSD/Tikhonov-regularized calibration, bootstrap, curve backtest |
| `factors/` | EOD signal generation from saved factor models |
| `multiasset/factor_model.py` | Walk-forward IC factor model, feature library, causal sizing |
| `multiasset/factor_optimizer.py` | Factor risk-parity (EWMA covariance) |
| `multiasset/budget.py` | vol^0.5 risk budgeting |
| `pairs/` | OLS hedge-ratio regression, residual z-score signals |
| `futures/` | Daily/intraday futures strategies, CTD/IRR analytics, backtest |
| `derivatives/` | Bond & IRS option pricing, vol surfaces, greeks |
| `surface/` | Yield-surface calibration & visualization |
| `engine/` | Orchestration, artifact store, schema/versioning, scheduler |

## Appendix B — Key Configuration Surfaces

| Config | Location |
|--------|----------|
| `FactorModelConfig` | `multiasset/factor_model.py` (UI-overridable) |
| `RiskModelConfig` | `multiasset/config.py` (EWMA λ, fallback vol) |
| Paths (`DIR_INPUT/OUTPUT/DATA/MODELS`) | `settings/paths.py` |
| Trading hours, colours | `settings/general.py` |
| Futures symbols/contracts | `settings/futures.py` |
| Wind data source | `settings/wind.py` |
| FI instrument definitions | `settings/fixed_income.py` |
```
