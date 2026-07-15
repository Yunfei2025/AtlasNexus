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

> Related roadmap: `docs/dev/factors-package-improvement-plan.md` (§7 covers this model).

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

### 4.3 Alpha Portfolio → Backtest: style-routed spread strategies

The Alpha Book backtest in `web/tabs/alpha/` evaluates individual relative-value
spreads and combines the current Portfolio allocation into an indicative book
equity curve. It has two distinct strategy types, selected from the candidate's
stored `style` field in portfolio mode or selected/auto-suggested from the latest
60-day regime snapshot in individual mode:

| Strategy type | Engine | Economic hypothesis | Core entry confirmation |
|---------------|--------|---------------------|-------------------------|
| **Mean-reverting (MR)** | `backtest/engine_mr.py::run_spread_backtest` | A statistically rich/cheap spread will revert toward its local equilibrium. | A 120-day rolling z-score, adjusted by a bounded 30-day carry/volatility term. |
| **Trending / momentum** | `backtest/engine_trend.py::run_trend_backtest_dc` | A confirmed directional move, supported by momentum, will persist long enough to exceed a volatility-scaled trailing stop. | Directional-change state, 20-day momentum normalized by 60-day daily-change volatility, and a carry-level gate. |

#### 4.3.1 Regime selection and scope

`curves/calibration/regime.py::compute_regime_features` computes four rolling,
60-day indicators on first differences: Kaufman efficiency ratio, a single-scale
R/S Hurst estimate, a variance-ratio proxy, and lag-1 autocorrelation. Each casts a
trend / mean-reversion / neutral vote. A net vote of at least $+2$ selects
`trending`; at most $-2$ selects `mean_reverting`; otherwise the result is
`uncertain`. In the individual UI, a certain result locks the matching style. For
an uncertain result, the sign of the latest carry/roll edge is a tiebreaker
(positive selects MR; non-positive selects trend when available).

This is a **point-in-time routing aid**, not a rolling adaptive backtest: portfolio
mode reads each candidate's current stored `style` and applies that one engine over
the whole selected historical period. Its results therefore answer, “how would the
current book's style assignment have behaved?”, rather than “how would a
historically available regime classifier have switched styles each day?”

#### 4.3.2 Mean-reversion model and defaults

For a spread level $s_t$, the MR engine uses a fixed internal lookback of 120
observations:

$$
z_t = \frac{s_t - \operatorname{mean}_{120}(s)}
                 {\operatorname{sd}_{120}(s)}, \qquad
CS_t = z_t - \operatorname{clip}\left(
  \frac{CR_t\,(30/90)}{\operatorname{sd}_{120}(s)}, -1.5, 1.5
\right).
$$

Here $CR_t$ is the aligned carry/roll series (or a snapshot fallback); the 30/90
scaling translates the stored three-month convention into the scoring horizon. The
engine enters long when $CS_t \leq -z_{entry}$ and short when
$CS_t \geq z_{entry}$. A signal exit is allowed only after `min_hold`; it occurs
when the composite score has reverted inside the exit band. A $z$-score stop is
always active, including during the minimum holding period. Closed-trade PnL is
spread change times the duration multiplier plus accrued carry/roll; the latter
includes direction-aware borrow adjustments for the supported spread families.

| Parameter | Standard default | Tenor-spread preset | Role |
|-----------|------------------|---------------------|------|
| Internal z-score lookback | 120 observations | 120 observations | Local equilibrium and dispersion; not UI-configurable. |
| `entry_z` | 2.0 | 2.5 | Absolute composite-score entry threshold. |
| `exit_z` | 0.5 | 0.25 | Reversion band used after the minimum hold. |
| `stop_z` | 4.0 | 5.0 | Adverse z-score stop. |
| `min_hold` | 7 calendar days | 10 calendar days | Minimum holding period for signal exits; stop remains active. |
| Carry score horizon | 30 days | 30 days | Fixed carry-adjustment horizon. |

The `trade_style` argument currently has identical entry logic for its non-MR
branch; the UI routes trend selections to the separate trend engine. It should not
be interpreted as a third hybrid signal.

#### 4.3.3 Trending / momentum model and defaults

The trend engine derives a persistent directional-change state
$D_t \in \{-1,0,1\}$, then requires it to agree with normalized momentum:

$$
m_t = s_t-s_{t-20}, \qquad
m_t^{norm} = \frac{m_t}{\operatorname{sd}_{60}(\Delta s)}, \qquad
D_t m_t^{norm} > 0, \quad |m_t^{norm}| \geq 0.5.
$$

`D_t` is obtained from the relative directional-change generator using `theta`.
Long entry also requires the spread level to meet `carry_buffer`; short entry is
permitted when `allow_short` is enabled. An open position exits on a directional
state flip or carry-gate failure after `min_hold`, or immediately on a trailing
stop of `trailing_mult × sd_60(Δs)` from the best favourable level. As in MR,
closed PnL combines duration-scaled spread movement and carry accrual.

| Parameter | Standard default | Tenor-spread preset | Role |
|-----------|------------------|---------------------|------|
| `theta` | 0.02 | 0.03 | Relative directional-change threshold in the backtest engine. |
| `mom_window` | 20 observations | 30 observations | Momentum lookback. |
| `vol_window` | 60 observations | 90 observations | Daily-change volatility lookback. |
| Momentum threshold | 0.5 | 0.5 | Fixed internal threshold for $|m_t^{norm}|$; not UI-configurable. |
| `trailing_mult` | 1.5 | 2.0 | Favourable-excursion trailing-stop multiple. |
| `carry_buffer` | 0.0 | 0.0 | Spread-level gate for long entries. |
| `min_hold` | 7 calendar days | 10 calendar days | Minimum hold before flip/carry exits. |
| `allow_short` | enabled | enabled | Allows short-spread entries. |

For yield-based spread families, the callback negates the series before passing it
to both engines so a positive internal PnL direction corresponds to an economic
narrowing/price-long trade; display signs are restored afterwards. This convention
must be retained when reviewing direction, carry, and threshold settings.

#### 4.3.4 Portfolio aggregation and measurement limitations

Portfolio mode loads the persisted current Alpha snapshot, normalizes the positive
candidate weights across instruments with available overlapping history, and sums
their weighted daily mark-to-market PnL in basis points. It forwards the MR
entry/exit/stop/minimum-hold controls, but trend assets use the trend engine's
function defaults rather than the individual-screen trend controls. The resulting
book is a useful **current-book sanity view**, not a fully parameterized historical
simulation.

The portfolio screen accepts initial capital and a transaction-cost input (default
100 MM and 0.5 bp), but these values are parsed and are not applied to PnL in the
current callback. Likewise, the trend path in portfolio mode does not receive its
spread-type/borrow-cost arguments. Reported portfolio return is consequently
weighted cumulative PnL in bp, rather than capital-normalized net return. The
individual engines report a trade-PnL Sharpe,
$\operatorname{mean}(pnl)/\operatorname{sd}(pnl)\times\sqrt{\min(N_{trades},20)}$,
whereas the portfolio screen reports a daily-PnL Sharpe annualized by
$\sqrt{252}$. These are not comparable with each other or directly with the
platform-wide return-based convention in §1.

#### 4.3.5 Performance-improvement plan — documentation only

No implementation is made by this document. The following sequence is recommended
before interpreting optimization results or increasing risk:

1. **Make performance measurement investable first.** Apply instrument- and
direction-specific bid/ask, fees, financing, borrow, and conservative next-bar
execution assumptions on every entry, exit, reversal, and portfolio rebalance;
then make capital and the configured transaction cost operational. Report gross
and net results, turnover, capacity/DV01, and return-based daily Sharpe using one
shared convention.
2. **Validate both models with a genuinely walk-forward design.** Freeze all
parameters and style/routing decisions using only information available at each
date; refit/reselect on rolling training windows; reserve a final untouched period.
Use purged, embargoed or anchored walk-forward folds where overlapping holding
periods make ordinary splits optimistic. Compare against always-MR, always-trend,
and no-trade baselines.
3. **Repair and calibrate regime routing before relying on it.** The current
variance-ratio calculation compares variances estimated over unequal samples and
scales the short-window variance by the window ratio; it is not a Lo--MacKinlay
multi-period variance ratio and is biased toward a trend vote. The single-scale
60-day R/S Hurst estimate also has finite-sample bias. Calibrate all thresholds to
simulated/random-walk and instrument-family null distributions, add regime
hysteresis/confidence gating, and demonstrate that conditional engine performance
beats the static baselines.
4. **Align parameter units with the traded object.** The trend backtest currently
uses the relative DC generator while the live snapshot trend signal uses an
absolute generator. Relative thresholds are unstable for inverted or near-zero
spreads, and `theta=0.02` therefore has a different meaning from a 2 bp absolute
threshold. Use one causal, spread-unit-consistent definition, preferably a
volatility-scaled absolute threshold; normalize momentum over its horizon (or
calibrate the existing statistic) and replace the spread-level `carry_buffer` with
direction-aware carry/roll expected edge.
5. **Estimate parameters by spread family and reversion speed, not global UI
presets.** Estimate an out-of-sample OU half-life/stationarity diagnostic per
instrument; trade MR only when its half-life fits the intended 1-week to 1-month
holding horizon and set the z-score lookback from that estimate. For trend, select
DC, momentum, volatility, and stop horizons by robust family-level grids or
Bayesian/regularized selection, scoring stability across folds rather than the
single best historical Sharpe.
6. **Improve portfolio construction after signals are credible.** Preserve the
historically available allocation at each rebalance; volatility-target gross DV01;
cap key-rate/issuer/leg and correlated-family exposure; net shared legs; and apply
drawdown, liquidity, and event-risk overlays. Add cross-sectional rich/cheap
signals within a spread family to reduce common level-factor risk that a collection
of independent time-series signals cannot diversify away.

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

#### 6.3.1 Two-stage allocation and the Stage-2 tenor tilt (`_two_stage_weights`)

The default backtest/live path (`use_dv01_shape=True`, `risk_budgets=None`) solves
in two stages rather than one joint optimization, because a single min-variance
solve is **rank-deficient** for bond groups: *N* tenors in one country/universe
group (e.g. CN's 1Y/2Y/5Y/10Y/20Y/30Y) all load on only 3 rate factors
(`IRDL.xx`, `IRSL.xx`, `IRCV.xx` — level, slope, curvature), so the asset
covariance `Σ = B·C_f·Bᵀ` has rank 3 and an (N−3)-dimensional null space. An
unconstrained min-variance solve over that null space has no unique optimum —
empirically it lands on an arbitrary bound corner and can jump between
unrelated corners from one rebalance to the next as the covariance estimate
moves by noise (verified by disabling the shape lock: `CN1Y`/`CN2Y` stayed
pinned at a corner in 6 of 7 monthly rebalances, then jumped to a different
corner for one month and back — not usable as a live/backtest allocation).

**Stage 1 — factor-level ERC.** Solve for a per-factor capital budget `e` (one
weight per risk factor, e.g. `IRDL.CN`, `IRSL.CN`, `IRCV.CN`, `CMDL.AU`, ...)
that equalises each factor's contribution to portfolio variance under the
rolling EWMA factor covariance `C_f`:

```
minimize   Σ_k ( e_k·(C_f e)_k / sqrt(eᵀC_f e)  −  mean(·) )²
subject to Σ_k e_k = 1,  e_k ≥ 0
```

This budget is genuinely time-varying: over a 6-month sample the `IRCV.CN`
budget alone was observed to move `0.022 → 0.108` across monthly rebalances,
several-fold, tracking real shifts in the rolling covariance.

**Stage 2 — DV01-anchored ridge tilt to tenors (`_tilt_group_shape`).** Each
rate group's pooled Stage-1 budget (level + slope + curvature budgets summed)
must be split across its tenors. The prior implementation used a purely
static split, `w_i ∝ 1/|IRDL_i|` (equal DV01 per tenor, from the modified
durations in `multiasset/utils.py::get_default_sensitivities`) — mechanically
well-posed (breaks the null space by construction) but **insensitive to
Stage 1**: since duration doesn't change month to month, the tenor *shape*
within a group was frozen regardless of how the level/slope/curvature budgets
moved, which is what produced a near-flat allocation chart across monthly
backtest rebalances even though Stage 1 was moving underneath it.

The current implementation keeps the DV01 shape as the base case but tilts it
toward the group's realised (level, slope, curvature) budget split via a
ridge-regularised, equality-constrained least-squares solve:

```
minimize   ‖ w − w_dv01 ‖²
subject to  loadings_g ᵀ w = target_g       (match the group's factor budget)
            Σ w = 1
```

where `w_dv01` is the existing inverse-duration shape, `loadings_g` is the
group's tenor × {level, slope, curvature} loading sub-matrix, and `target_g`
is `w_dv01`'s own exposure plus a nudge of size `group_sub_budget / λ` (so as
`λ → ∞` the nudge vanishes and `w → w_dv01` exactly; smaller `λ` pulls the
shape further toward matching the realised budget split). Both constraints
are linear in `w`, so — unlike the unconstrained min-variance case — this has
a **unique closed-form solution** (solved via the normal equations,
`multiasset/factor_optimizer.py::_tilt_group_shape`), with no null-space
degeneracy or corner-jumping.

`λ` is `RiskModelConfig.TENOR_TILT_LAMBDA` (default **4.0**), overridable via
`fit_and_calculate(..., tilt_lambda=...)`. Empirically (7 monthly rebalances,
CN 1Y–30Y curve): `λ=4` keeps tenor weights close to DV01 with modest
month-to-month movement (~1pp range on mid-tenors); `λ≈0.5` produces clearly
visible, still-smooth monthly reshaping (~2–3pp range); `λ→0` approaches the
least-squares-exact factor-budget match (largest reshaping, still smooth — no
NaNs or corner jumps observed down to `λ=0.05`). No repo test suite exercises
this path yet; validate numerically per §6.3 review focus before relying on
values below the shipped default.

Non-rate assets (commodities, FX, single-tenor instruments) still receive
their Stage-1 budget directly with an equal split, unaffected by the tilt.

> **Review focus:** appropriateness of a single scalar `λ` vs. a
> per-group/per-tenor schedule; whether the ridge-to-DV01 prior should also
> penalize roughness of the *shape* of the deviation (a second-difference /
> curve-smoothness term in log-tenor space, consistent with
> `multiasset/config.py::get_credit_weights`) rather than only its magnitude —
> deferred as unnecessary complexity for the initial fix, since the target
> exposure vector is itself smooth and no roughness was observed empirically.

#### 6.3.2 Group-aware bond/credit caps (`RiskModelConfig.scaled_bounds`)

Even with the Stage-2 tilt (§6.3.1) able to respond to Stage-1's budget, the
tenor weights in a multi-tenor group were still separately clipped by
`RiskModelConfig.scaled_bounds`, which sized every asset-class cap off
`eq = 1/n_assets` — i.e. treating **each individual tenor** as one
independent bounding unit. For a pool with one 6-tenor CN group among 10
total assets, that gave every CN tenor the same `cap_bond = min(0.40, (1/10)
× 3.0) = 0.30` as a single unrelated commodity position. Because DV01
equalisation (`w ∝ 1/duration`) inherently concentrates weight in the
shortest tenor — confirmed empirically, the *unclipped* Stage-2 output wanted
`CN1Y ≈ 0.52` for this pool — CN1Y (and to a lesser extent CN2Y) hit that cap
in all 7 of 7 monthly rebalances tested, regardless of what Stage 1/Stage 2
computed. This, not covariance stability, was the dominant reason the
backtest allocation chart looked flat: 8 of 10 assets (2 pinned at the bond
cap, 4 pinned at the commodity/FX floor) were saturated most months, leaving
only the untouched mid-tenors visibly free to move.

`scaled_bounds` now takes optional `n_bond_groups` / `n_credit_groups`
arguments and uses them **only for the cap**, not the floor:

```
cap_bond   = min(ABS_CAP_BOND,   (1 / n_bond_groups)   × CAP_RATIO_BOND)
floor_bond = max(ABS_FLOOR_BOND, (1 / n_assets)        × FLOOR_RATIO_BOND)   # unchanged
```

`n_bond_groups` counts one unit per multi-tenor rate group (e.g. the whole CN
curve = 1, computed in `_two_stage_weights` from the same factor-suffix
grouping used for the Stage-2 tilt) plus one unit per ungrouped single-tenor
bond — so a 6-tenor group gets the concentration allowance of **one bond
position**, not six. The floor deliberately keeps scaling off `n_assets`
(individual tenors): a floor exists to stop the optimizer from zeroing out a
specific instrument, and scaling it off `n_bond_groups` would force every
tenor in a group to individually hold the floor share, which can sum to more
than 100% for large groups. `n_bond_groups=None` (the default) reproduces the
old per-asset behaviour, so any caller not yet passing group counts is
unaffected. `_optimize_weights` (the `use_dv01_shape=False` / risk-budget
path) has **not** been updated to pass group counts — its intra-group
shape-locked bonds already bypass the per-tenor cap by construction (relaxed
to `(0, 1)`), so the fix was scoped to `_two_stage_weights` only.

With the wider group cap (`ABS_CAP_BOND = 0.40` is the binding ceiling for a
single-group 10-asset pool), CN1Y still sits at ~0.40 in the same 7-date
test — that is the economically correct DV01 answer for a bond with ~1-year
duration, not an artifact of the bound, and is a risk-policy choice (how much
single-tenor concentration to allow) rather than something the math alone
determines. CN2Y through CN30Y, and the commodity/FX floor-pinned assets, are
now free to move with Stage 1 rather than being frozen at the old, tighter
per-tenor bound.

> **Review focus:** whether `ABS_CAP_BOND = 0.40` remains the right risk
> ceiling for a single dominant short-tenor position now that the group cap
> can actually reach it (previously masked by the tighter per-asset cap); and
> whether `_optimize_weights`'s `use_dv01_shape=False` path — already flagged
> in §6.3.1 as numerically unstable (rank-deficient, corner-jumping) — should
> be retired or fixed rather than left as a documented-but-unrecommended
> option, since it does not benefit from this grouping fix.

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
