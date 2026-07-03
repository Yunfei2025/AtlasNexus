# Factor Model Improvement Plan

**Scope**: both factor models on the platform —
1. the single-instrument model in `factors/` (§0–§6): monthly walk-forward IC-weighted combiner over a generated factor zoo (price/momentum/vol/volume/carry/value/yield-curve/macro + high-order), predicting next-day returns for `T.CFE`, backtested via `factors/backtest/runner.py`;
2. the multiasset risk-factor combiner in `multiasset/factor_model.py` (§7): its remaining backlog, merged in from the retired `factor-model-improvement-plan.md` (implemented items dropped after verification against the code).

**Goal**: a high-Sharpe, high-return strategy whose backtest numbers survive transaction costs and out-of-sample deployment.

---

## 0. Review findings — what limits performance today

Ordered by expected impact. Items marked **BUG** are correctness defects, not tuning choices; fix these before believing any backtest number.

### 0.1 **BUG — sign-blind factor weights destroy the signal**
`ModelConfig.weighting_method = 'max_sharpe'` maps (via `get_model_parameters()`, `factors/config/__init__.py`) to `('ic_weighted', 'ic_abs')`. In `_calculate_ic_weights()` (`factors/engine/predictor.py`) the `ic_abs` branch assigns every selected factor a **positive** weight equal to |IC| — a factor that *negatively* predicts returns still enters the combination with a positive sign. The prediction is then Σ(scaled factor × |IC|), which ignores the direction of each factor's relationship with returns. Unless every selected factor happens to have positive IC, this systematically cancels signal.
Neither `'max_sharpe'` nor `'risk_parity'` is actually implemented as named — both silently degrade to |IC| weighting.

### 0.2 **BUG — position threshold is hard-coded to zero**
`create_simple_portfolio()` (`factors/processing/position.py:37`): `threshold = 0.0 * predictions.std()`. The configured `ModelConfig.threshold = 0.45` is never used. Every prediction, however tiny, produces a full ±1 position, so the strategy flips on every sign change of a noisy next-day forecast → maximal turnover.

### 0.3 **BUG — backtest is gross of all costs**
`run_backtest()` (`factors/backtest/runner.py`) computes `strategy_returns = positions × returns` with **no transaction cost, slippage, or roll cost**. Combined with 0.2 (daily ±1 flips), the reported Sharpe is not attainable. `friction_cost` exists in config but is only used inside the smooth-portfolio parameter grid search, never in the headline backtest.

### 0.4 **BUG — train/serve skew in the EOD path**
Training scales factors with `scale_factors_rolling(all_factors, train_end)` before the model's `StandardScaler` is fit (`factor_engine.analyze_single_period`). The live path `run_eod_calibration()` loads raw factors from `load_and_prepare_factors()` and applies only the saved `StandardScaler` — `scale_factors_rolling` is skipped. Daily production signals are therefore on a different scale (and potentially different sign magnitude) than anything that was backtested.

### 0.5 Multiple-testing / selection noise
The factory generates hundreds of candidates (base + up to 100 high-order + macro), then each month the selector picks the top 5 by |IC| computed on a **6-month** training window (`lookback_window = 6` ⇒ ~120 obs). At n=120, an IC of 0.08 has t ≈ 0.87 — far from significant. Ranking hundreds of noise-dominated ICs and picking the extreme tail is classic backtest overfitting; the selected set churns every month and OOS IC will collapse toward zero.

### 0.6 No purge/embargo in the walk-forward
`generate_analysis_periods()` sets `train_end = test_start − 1 day`, and the label is `returns.shift(-1)`: the last training sample's forward-return window touches the test period. One-day overlap is small but free to remove; the sibling model (multiasset) already implements purge/embargo.

### 0.7 Metric and accounting inconsistencies
- `relative_returns = strategy_returns / aligned_prices.shift(1)` (`runner.py:101`) divides day-t PnL by the price at t−1; should be the price at position entry (t).
- `win_rate` compares prediction sign vs return sign — it's directional accuracy of the *forecast*, not the hit rate of the *positions* actually held (post smoothing/risk management).
- `annual_return = (1 + mean_daily)^252 − 1` (compounded) over `std × √252` (simple) mixes conventions; use arithmetic mean × 252 / (std × √252) for Sharpe, report CAGR separately.
- `calculate_ir()` computes std of *overlapping* 20-day rolling ICs — heavily autocorrelated, so IR is inflated; use non-overlapping monthly ICs.

### 0.8 Structural limits on Sharpe
- **Breadth = 1.** One instrument (`T.CFE`), one horizon (1-day). By the fundamental law (IR ≈ IC·√breadth), even a genuinely good IC of 0.05 on a single daily series caps Sharpe around 0.7–0.8 gross. High Sharpe requires more independent bets, not a better single-name model.
- Config sprawl: ~60 `ModelConfig` parameters, many unused (`threshold`, `correlation_threshold` vs `max_factor_correlation`, `position_buckets`…) or misleading (`max_sharpe`). This makes sweeps untrustworthy and invites silent dead switches.
- `config._precomputed_data` smuggles full DataFrames through the config object into each spawn-mode worker — repickled per task, memory-heavy, and fragile.
- Model artifacts (`trained_model_*.joblib`) live in the package directory, keyed only by date, single-ticker.

---

## 1. Phase 1 — Correctness: make the backtest believable (highest priority)

No alpha work until the measurement is honest. Everything below is low-effort.

| # | Change | Where |
|---|--------|-------|
| 1.1 | Use **signed** IC weights: change the `'max_sharpe'`/`'risk_parity'` mapping to `('ic_weighted', 'ic_signed')`, or implement real max-Sharpe weights (w ∝ Σ⁻¹·IC). Sign-correct each factor before any abs-weighting. | `config.get_model_parameters()`, `predictor._calculate_ic_weights()` |
| 1.2 | Wire `config.threshold` into `create_simple_portfolio` as a fraction of prediction std (dead zone → position 0); keep 0 available for A/B. | `processing/position.py` |
| 1.3 | Charge costs in the backtest: `net = pos.shift-aligned PnL − |Δposition| × cost`, with cost in price ticks for T.CFE (≈ 0.005 CNY tick, ~0.5–1 tick round trip + fees). Report **gross and net** Sharpe side by side (the multiasset model already does this — reuse the pattern). | `backtest/runner.py` |
| 1.4 | Fix `relative_returns` denominator to entry price (t), and compute win rate from realized position PnL. Standardize Sharpe = mean·252 / (std·√252). | `backtest/runner.py` |
| 1.5 | Apply `scale_factors_rolling(all_factors, asof)` in `run_eod_calibration` before predicting, and persist the scaling window inside the joblib artifact so live = backtest bit-for-bit. Add a unit test that pushes the same window through both paths. | `engine/factor_engine.py` |
| 1.6 | Purge 1 + H days between train_end and test_start; optional 5-day embargo (config-gated, default on). | `utils/helpers.generate_analysis_periods`, `processing/loader.split_data_by_periods` |
| 1.7 | Re-run the 2020–2025 walk-forward and record the honest net baseline in this doc. Expect the current headline numbers to drop — that drop is the measurement error we're removing, not lost alpha. | — |

**Acceptance**: reproducible net-of-cost baseline; EOD signal equals backtest signal on the same date; tests in `tests/` covering 1.1–1.5.

## 2. Phase 2 — Statistical hygiene: stop mining noise

| # | Change | Detail |
|---|--------|--------|
| 2.1 | Lengthen the IC estimation window to 24 months (keep monthly refit). 6 months of daily data cannot rank hundreds of factors. Optionally EWMA-weight recent observations. | `lookback_window` |
| 2.2 | Replace the raw IC threshold with **FDR control** (Benjamini–Hochberg on IC t-stats) in `FactorSelector._filter_by_significance`, so the cut adapts to how many candidates were tested. | `engine/selector.py` |
| 2.3 | Enforce the (currently unused) **stability screen**: require same-sign IC in ≥ 2 of the last 3 training windows before a factor is eligible (`use_factor_stability` exists in config but is never consumed by the selector — wire it up). | `engine/selector.py` |
| 2.4 | Shrink IC weights toward zero: `w = IC × max(0, 1 − λ/|t|)` or a simple Bayesian shrink by n. Raw sample ICs from 120–500 obs need shrinkage before use as weights. | `predictor._calculate_ic_weights` |
| 2.5 | Prune the factor zoo: cap high-order factors (they are combinatorial recombinations of the same bases and dominate the multiple-testing burden); keep an economically-motivated core (carry, momentum 5/20/60, value/level z-score, vol, curve slope/curvature, macro spillover). Target ≤ ~80 candidates. | `generator/factory.py` |
| 2.6 | Report **Deflated Sharpe** alongside Sharpe (count of configs/factors tried is known); track rolling OOS IC vs in-sample IC per month, alert when ratio < 0.5. | `analysis/metrics.py`, dashboard |
| 2.7 | Fix `calculate_ir` to non-overlapping monthly ICs. | `analysis/metrics.py` |

**Acceptance**: month-over-month selected-factor turnover drops materially (< ~40%); mean OOS IC within 0.5× of in-sample IC; net Sharpe from Phase 1 does not degrade.

## 3. Phase 3 — Signal & sizing: convert IC into return efficiently

| # | Change | Detail |
|---|--------|--------|
| 3.1 | **Continuous sizing** as the default portfolio method: `position = tanh(pred / (κ·σ_pred))`, vol-targeted (`volatility_target = 0.15` already in config) — replaces binary ±1. Keep `simple` for A/B. | `processing/position.py` |
| 3.2 | **Cost-aware trading filter**: only adjust position when `|target − held| × E[edge] > 2 × cost`; this is the turnover-filter pattern already proven in `multiasset/factor_model.py` (`build_position_series`). | `processing/position.py` |
| 3.3 | **Window ensemble**: train the combiner on 6M / 12M / 24M windows, blend by OOS ICIR. Cheap variance reduction, ~15–20% ICIR lift in the sibling model's experience. | `engine/factor_engine.py` |
| 3.4 | **ElasticNet ensemble member** with `TimeSeriesSplit`-CV'd alpha as a second model beside IC-weighting (the plumbing already exists in `train_model`); average predictions by OOS ICIR. | `engine/predictor.py` |
| 3.5 | **Multi-horizon labels**: predict 5-day (overlapping, purged) as well as 1-day returns; blended horizon reduces noise and turnover simultaneously. | `predictor.train_model` |
| 3.6 | Hook up the existing but dormant `calculate_regime_conditional_ic` (HMM trending/mean-reverting from `futures.backtest.regime`) behind `use_regime_aware_ic`; evaluate as an overlay, not a default. | `engine/predictor.py` |

**Acceptance**: net Sharpe ≥ 1.5× the Phase-1 baseline with turnover ≤ 0.5× the binary baseline; ensemble beats every single-window member OOS.

## 4. Phase 4 — Breadth: the only reliable route to "high Sharpe"

A single 1-day-horizon series caps achievable Sharpe regardless of model quality. Extend the same engine cross-sectionally:

| # | Change | Detail |
|---|--------|--------|
| 4.1 | Run the pipeline per instrument across the CFFEX curve — `TS.CFE`, `TF.CFE`, `T.CFE`, `TL.CFE` — plus the pair/fly tickers the loader already supports (`'Pair:T.CFE-TS.CFE'`, `'Fly:…'`). Outrights + spreads + flies give ~6–8 semi-independent bets. | `run_analysis` loop, config per ticker |
| 4.2 | Combine sleeves with risk parity (inverse realized vol, 60d) and a portfolio-level vol target; correlation-aware combination can reuse `multiasset/factor_optimizer.py`. | new `factors/portfolio.py` or via `portfolio/` |
| 4.3 | Cross-sectional signals: rank instruments by carry/momentum and go long-rich/short-cheap duration-neutral — orthogonal to the per-name time-series signal. | new generator |
| 4.4 | Persist per-ticker model artifacts under `DIR_MODELS` (not the package dir), keyed `{ticker}_{train_end}`, with the manifest recording factor list + scaling stats. | `utils/helpers.save_final_model` |

**Acceptance**: portfolio net Sharpe > best single sleeve by ≥ 30%; drawdown < single-sleeve drawdown; artifacts relocate to `DIR_MODELS` without breaking `run_eod_calibration`.

## 5. Phase 5 — Validation protocol & production hardening

- **CPCV** (combinatorial purged CV) for the final config, so the headline Sharpe is a distribution, not one path.
- A frozen **holdout** (e.g. the last 12 months) never touched during Phases 2–4 tuning; report it once at the end.
- Live monitoring: daily OOS IC tracker; auto-deactivate (flat) when 60-day mean OOS IC < 0 — plumb into the EOD artifact so the Beta Book tab shows it.
- Engineering cleanup: pass data to workers explicitly (not via `config._precomputed_*`); delete dead config switches surfaced in 0.8; replace `print` with the project logger; add `tests/test_factors_backtest.py` covering cost accounting, purge boundaries, and train/serve parity.

## 6. Sequencing and expected payoff

| Order | Phase | Effort | Expected effect on *honest* net Sharpe |
|-------|-------|--------|----------------------------------------|
| 1 | Correctness (§1) | ~2–3 days | Baseline drops to truth, then +0.2–0.4 back from signed weights + dead zone |
| 2 | Statistical hygiene (§2) | ~3–5 days | +0.1–0.3, mostly by stopping OOS decay |
| 3 | Sizing & ensemble (§3) | ~1 week | +0.2–0.4 |
| 4 | Breadth (§4) | ~1–2 weeks | ×1.3–1.8 multiplicative (√breadth) |
| 5 | Validation (§5) | ongoing | keeps it real |

Realistic destination for a CGB-futures multi-sleeve systematic book: **net Sharpe ~1.0–1.5** with vol targeted at 10–15% ⇒ low-to-mid-teens annual return. Numbers materially above that from a single-instrument daily model should be treated as a measurement bug (see §0) until proven otherwise.

## 7. Multiasset combiner (`multiasset/factor_model.py`) — remaining backlog

Merged from the retired `factor-model-improvement-plan.md`. Current baseline: walk-forward signed-Spearman-IC linear combiner over IRDL / IRSL / IRCV / FXDL / CMDL, Sharpe ~0.1–0.5 gross.

**Already implemented (verified in code, dropped from the plan):** bulk feature engineering in `build_features()` (z-scores, multi-horizon momentum, slope/curvature + z-scores, carry spreads, vol ratio, cross-factor diffs); continuous ICIR-weighted position sizing with per-factor vol scaling and turnover filter (`build_position_series`, `sizing_mode`); DV01-aware transaction costs with gross/net series; purge + embargo in the walk-forward (`purge_days`/`embargo_days`).

> Legend for `doc §x.y` comments in `multiasset/factor_model.py` (they cite the retired plan's numbering, all implemented): §3.1 = continuous ICIR sizing, §3.3 = turnover filter, §4.2 = purge/embargo, §5.1 = DV01-aware costs.

### 7.1 Remaining feature work
- Carry × Momentum *product* interaction term (only additive features today)
- IR–FX correlation regime indicator (rates vs USD/CNY decouple vs co-move)
- FX carry-adjusted return (strip rate-differential drift)
- Term-premium proxy: IRSL minus its 5Y rolling average
- Carry-to-vol ratio per factor; trend-strength (ADX-equivalent) directional filter

### 7.2 Model architecture / ensembling
- **Window ensemble**: train over 6M / 12M / 24M windows, blend by OOS ICIR (~15–20% ICIR lift)
- **Model race**: Ridge / ElasticNet (CV-tuned alpha; Lasso zeroes low-IC features) and LightGBM / GBR for non-linear regimes (needs ≥36M training) — combine by OOS-ICIR weights, trees as members not replacements
- **Regime-conditional models**: HMM / realised-vol state detection, separate sub-models per regime (+0.1–0.3 Sharpe historically in FI systematic work)
- Rolling 18M training window with EWMA observation weighting (vs current expanding)

### 7.3 Sizing & portfolio construction
- Covariance-aware combination risk parity: per-factor vol scaling is done, but cross-factor risk parity still lives only in `factor_optimizer.py` — unify, or replace with **HRP** (no matrix inversion, better OOS stability)
- **Ledoit-Wolf / Bayesian shrinkage** of the covariance feeding `compute_ewma_factor_covariance`
- Portfolio-level vol targeting + drawdown-control overlay
- **Kelly-fraction sizing** (`f ≈ ICIR × IC_hitrate × const`, capped at 2× target vol) as alternative to the tanh-ICIR gate

### 7.4 Costs & execution
- Estimated daily roll cost for continuous positions (bid-ask leg is done)
- Cost-aware signal threshold: trade only if `|predicted_return| × DV01_scale × size > 2 × tx_cost`

### 7.5 Validation & monitoring
- CPCV + Deflated/Probabilistic Sharpe (same protocol as §5 — build the utilities once, share across both models)
- OOS-IC decay monitoring: alert/deactivate when mean OOS IC < 0.02 for ≥30 consecutive days (revert to carry-only)

### 7.6 Advanced signal construction (applies to both models)
- **Meta-labeling**: secondary classifier for bet size / trade-or-not on top of the directional signal
- **Fractional differencing**: stationary features that preserve memory (better than full `diff()`)
- **Feature neutralization**: residualise signals against known risk factors to isolate incremental alpha

## 8. References

- Bailey & López de Prado (2014), *The Deflated Sharpe Ratio*
- López de Prado (2018), *Advances in Financial Machine Learning* — purged CV, CPCV, meta-labeling, fractional differencing
- López de Prado (2016), *Building Diversified Portfolios that Outperform Out-of-Sample* — Hierarchical Risk Parity
- Grinold & Kahn, *Active Portfolio Management* — fundamental law (IC × √breadth)
- Benjamini & Hochberg (1995) — FDR control for factor screening
- Asness, Moskowitz, Pedersen (2013), *Value and Momentum Everywhere* — AQR signal combination framework
- Ilmanen (2011), *Expected Returns* — Ch. 9, fixed income factor premia
- Maillard, Roncalli, Teïletche (2010), *On the Properties of Equally-Weighted Risk Contributions Portfolios*
- Ledoit & Wolf (2004), *Honey, I Shrunk the Sample Covariance Matrix*
