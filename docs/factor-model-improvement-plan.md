# Factor Model Improvement Plan

**Scope**: Multi-factor combination model predicting risk-factor price returns  
**Current baseline**: Walk-forward **IC-weighted linear combiner** (signed-Spearman-IC feature weights, *not* Ridge) over IRDL / IRSL / IRCV / FXDL / CMDL, with `FactorSelector` doing IC-threshold + VIF + significance + diversification filtering. See [`multiasset/factor_model.py`](../multiasset/factor_model.py) (`_train_ic_model`, `build_features`, `run_factor_model_backtest`).  
**Current Sharpe**: 0.1 – 0.5 gross (reasonable for a first-generation systematic fixed-income model)

> **Status note (kept current with code):** Section 1 (Feature Engineering) is **largely implemented** in `build_features()`. The active quick-win sprint is continuous position sizing (§3.1), risk-parity vol scaling (§3.2), the turnover filter (§3.3) and purge/embargo (§4.2) — now wired into the live backtest via `build_position_series()`. Advanced techniques are catalogued in §8.

---

## 1. Feature Engineering — ✅ largely IMPLEMENTED

Most of this layer already exists in `build_features()` (`multiasset/factor_model.py`). Status is tracked per item below.

### 1.1 Signal Transformations
| Item | Status | Where in code |
|------|--------|---------------|
| Rolling z-score over 60/120/252-day window | ✅ Done | `_value_features` (`_rolling_zscore`) |
| Multiple lags / multi-horizon momentum (5/10/20/60) + EMA crossover | ✅ Done | `_momentum_features` |
| Slope, slope-change (Δslope), slope z-score | ✅ Done | `_carry_features` (`_Slope`, `_SlopeMom20`, `_SlopeZ60`) |
| Curvature + curvature z-score | ✅ Done | `_carry_features` (`_Curv`, `_CurvZ60`) |
| Roll-down / carry adjacent-tenor spreads | ✅ Done | `_carry_features` (`_Carry_*`) |
| FX carry-adjusted return (strip rate-differential drift) | ☐ TODO | — |

### 1.2 Cross-Factor Interactions
- ✅ **Cross-factor diffs** (same-asset-class relative momentum) — `_cross_factor_features`.
- ✅ **Volatility ratio** (short/long realised vol) — `_volatility_features` (`_VolRatio`).
- ☐ **Carry × Momentum** *product* interaction term — TODO (only additive features today).
- ☐ **IR–FX correlation regime** indicator (rates vs USD/CNY decouple vs co-move) — TODO.

### 1.3 Derived Features
- ☐ **Term-premium proxy**: IRSL minus its 5Y rolling average — TODO.
- ☐ **Carry-to-vol ratio** per factor (expected carry / realised vol) — TODO.
- ☐ **Trend strength** (ADX-equivalent) directional filter — TODO.

> Net: the remaining feature work is a handful of *interaction / derived* terms, not the bulk transformations — those are done.

---

## 2. Model Architecture

### 2.1 Regularisation Tuning
- Current: Ridge (L2) with fixed `alpha`
- Improvement: Cross-validate `alpha` on each walk-forward training window using `TimeSeriesSplit`
- Add Lasso or ElasticNet variants — Lasso naturally zeroes out low-IC features, reducing overfitting
- Target: expand feature set to 20-30 candidates, let Lasso select the effective 5-8

### 2.2 Ensemble Averaging
- Train 3 models per factor with different window lengths: 6M, 12M, 24M
- Final prediction = weighted average: `w_i ∝ ICIR_i` from out-of-sample validation period
- Effect: ~15-20% ICIR improvement vs. best single-window model (reduces model estimation variance)

### 2.3 Tree-Based Alternative
- Try `GradientBoostingRegressor` or `LightGBM` for capturing non-linear regime switches
- Constraint: requires longer training window (≥36 months) to avoid overfitting
- Best used as a second model in the ensemble, not as a replacement

### 2.4 Regime-Conditional Models
- Identify regimes using realised vol of IRDL (or VIX proxy):
  - **High-vol regime** (VIX-equivalent top quartile): train separate model; momentum signals tend to reverse faster
  - **Low-vol regime**: carry and trend models dominate
- At prediction time, select the appropriate trained model based on current regime
- Effect: historically this "regime-switching" structure adds 0.1–0.3 Sharpe in fixed income systematic work

---

## 3. Signal Combination & Position Sizing

### 3.1 ICIR-Weighted Signal — ✅ IMPLEMENTED (`build_position_series`)
Was: binary signal (−1 / 0 / +1) baked into PnL; the ICIR/vol "scalar" was display-only.  
Now: continuous position = `z(pred) × tanh(ICIR/κ) × vol_scale`, leverage-capped and turnover-filtered, used directly in `strategy_returns`. Toggle via `FactorModelConfig.sizing_mode` (`'binary'` reproduces the legacy path exactly).

```
vol_scale_i   = target_vol / realised_vol_i(60d)        # risk parity normalisation
icir_weight_i = tanh(ICIR_i / 0.25)                     # smooth sigmoid, saturates at ±1
position_i    = predicted_return_i × icir_weight_i × vol_scale_i
```

This replaces the discrete signal card with a continuous, ICIR-adjusted size.

### 3.2 Risk Parity Across IR Sub-factors — ⚙️ PARTIAL
Per-factor `vol_scale = target_vol / realised_vol` is now applied inside `build_position_series` (each factor sized to equal stand-alone risk). Cross-factor *combination* risk parity (covariance-aware) still lives only at the asset-allocation layer in [`factor_optimizer.py`](../multiasset/factor_optimizer.py); unifying the two is a future-phase item (§8, HRP).

IRDL / IRSL / IRCV have vol ratio ≈ **7 : 2 : 1**.  
Applying `1/vol_i` scaling ensures each contributes equal risk to the portfolio:

```python
sigma = factor_rates[ir_factors].pct_change().rolling(60).std().iloc[-1]
rp_weights = (1 / sigma) / (1 / sigma).sum()
combined_ir_signal = (signals[ir_factors] * rp_weights).sum()
```

This is standard practice at macro systematic funds (Bridgewater All Weather, AQR Risk Parity).

### 3.3 Turnover Filter — ✅ IMPLEMENTED
Only update the held position when `|raw − held| > turnover_threshold` (`FactorModelConfig.turnover_threshold`, default 0.10), inside `build_position_series`. Reduces round-trip costs for signals that flip frequently (low-IC IRSL).

### 3.4 Kelly Fraction
Optimal position size under Kelly criterion: `f* = μ / σ²`  
For a practical implementation: `f = ICIR × IC_hitrate × scaling_constant`  
Cap at 2× target vol to avoid over-concentration.

---

## 4. Walk-Forward Validation Improvements

### 4.1 Expanding vs. Rolling Window
- **Expanding window** (current): more stable but slow to adapt to regime changes
- **Rolling window** (12M, 24M): faster adaptation but noisier coefficients
- **Recommendation**: use rolling 18M window with EWMA weighting of observations (recent months get higher weight)

### 4.2 Purging & Embargoing — ✅ IMPLEMENTED
To avoid look-ahead bias in walk-forward CV (now in `run_factor_model_backtest`):
- **Purge**: `train_end = test_start − (1 + purge_days + H)` so the last train sample's forward-return window cannot overlap the test set.
- **Embargo**: drop the first `embargo_days` rows of each test set (Lopéz de Prado 2018).
- Both gated by `FactorModelConfig.purge_days` / `embargo_days` (set to 0 to reproduce legacy behaviour).

### 4.3 Out-of-Sample IC Monitoring
- Track rolling OOS IC (60-day) and compare to in-sample IC
- If `OOS_IC / IS_IC < 0.5` consistently → model has overfit; reduce features or widen training window
- Alert threshold: mean OOS IC < 0.02 for ≥30 consecutive days → deactivate signal, revert to carry-only

---

## 5. Transaction Cost & Execution

### 5.1 Cost Modelling — ✅ IMPLEMENTED (DV01-aware)
`strategy_returns = position.shift(1) × returns − |turnover| × cost_per_unit`, with a gross series (`strategy_returns_gross`) retained so the dashboard shows gross vs net Sharpe side by side. `cost_per_unit` comes from `factor_tx_cost_per_unit()` and is quoted in each factor's **native convention**:
- **Yield / spread factors** — bid-ask in *yield bp* (`tx_cost_yield_bp`, default 0.5), converted to price-return via the factor's modified duration (`get_factor_duration`). This is the DV01-aware cost: trading the rate costs `D × Δyield_bp`, not a flat price bp.
- **FX / commodity factors** — bid-ask in *price bp* (`tx_cost_price_bp`, default 1.0).
- ☐ TODO: add estimated daily roll cost for continuous positions.

### 5.2 Cost-Aware Signal Threshold
Only trade when expected daily PnL > 2× estimated cost:
```
expected_pnl ≈ |predicted_return| × DV01_scale × position_size
trade_only_if: expected_pnl > 2 × tx_cost_per_unit
```

---

## 6. Roadmap Priority

| Status | Item | Est. Sharpe Lift | Effort |
|--------|------|------------------|--------|
| ✅ Done | ICIR-weighted continuous position sizing (§3.1) | +0.1–0.2 | Low |
| ✅ Done | Risk-parity vol scaling per factor (§3.2) | +0.05–0.15 | Low |
| ✅ Done | Turnover filter (§3.3) | +0.05–0.1 (net cost) | Low |
| ✅ Done | Transaction-cost-aware net PnL (§5.1) | (net cost) | Low |
| ✅ Done | Purge & embargo in walk-forward (§4.2) | robustness | Low |
| ✅ Done | Feature engineering: z-scores / momentum / carry / curve (§1) | — | — |
| 🟡 Next | Cross-factor interaction & derived features (§1.2–1.3) | +0.05–0.15 | Medium |
| 🟡 Next | Ensemble averaging across windows / models (§8) | +0.1–0.2 | Medium |
| 🟢 Future | Regime-conditional model switching (§8) | +0.1–0.3 | High |
| 🟢 Future | LightGBM ensemble member (§8) | +0.0–0.2 | Medium |
| 🟢 Future | CPCV + Deflated Sharpe evaluation (§8) | robustness | Medium |
| 🟢 Future | Covariance-aware combination risk parity / HRP (§8) | +0.05–0.15 | High |

**Completed sprint** (this change): continuous sizing + risk-parity vol scale + turnover filter + costs + purge/embargo — cumulative target ≈ +0.2–0.4 Sharpe (validate via the §verification backtest). **Next sprint**: §1.2–1.3 feature terms, then §8 ensembling.

---

## 7. References

- Lopéz de Prado (2018) *Advances in Financial Machine Learning* — Ch. 7 (cross-validation in finance), Ch. 10 (ensemble methods)
- Asness, Moskowitz, Pedersen (2013) *Value and Momentum Everywhere* — AQR signal combination framework
- Ilmanen (2011) *Expected Returns* — Ch. 9 (fixed income factor premia)
- Risk Parity methodology: Maillard, Roncalli, Teïletche (2010) *On the Properties of Equally-Weighted Risk Contributions Portfolios*
- López de Prado (2016) *Building Diversified Portfolios that Outperform Out-of-Sample* — Hierarchical Risk Parity
- Bailey & López de Prado (2014) *The Deflated Sharpe Ratio*
- Ledoit & Wolf (2004) *Honey, I Shrunk the Sample Covariance Matrix*

---

## 8. Advanced Techniques — hedge-fund toolkit (future phases)

A catalog of techniques commonly used at systematic macro / multi-strategy funds, beyond the quick-win sprint above. Not yet scheduled; listed roughly by expected value-for-effort.

### 8.1 Ensemble / model-averaging
- **Window ensemble**: train the IC combiner over 6M / 12M / 24M windows; blend predictions weighted by out-of-sample ICIR (reduces estimation variance, ~15–20% ICIR lift).
- **Model race**: run IC-weighted **and** `Ridge` / `ElasticNet` (CV-tuned `alpha`, Lasso zeroes low-IC features) **and** `LightGBM` / `GradientBoostingRegressor` for non-linear regime capture (needs ≥36M training). Combine by OOS-ICIR weights; use trees as ensemble members, not replacements.

### 8.2 Regime-conditional models
- Detect regimes via realised-vol state (e.g. top-quartile IRDL vol) or a **Hidden Markov / Markov regime-switching** model. Train separate sub-models per regime (momentum reverses faster in high-vol; carry/trend dominate low-vol) and select at prediction time. Historically +0.1–0.3 Sharpe in FI systematic work.

### 8.3 Robust validation & evaluation (López de Prado)
- **Combinatorial Purged Cross-Validation (CPCV)** for path-robust performance distributions instead of a single walk-forward path.
- **Deflated / Probabilistic Sharpe Ratio** to discount the Sharpe for multiple-testing / non-normality — guards against backtest-overfitting when sweeping configs.
- **OOS-IC decay monitoring**: alert/deactivate when mean OOS-IC < 0.02 for ≥30 consecutive days (revert to carry-only).

### 8.4 Signal construction
- **Meta-labeling**: a secondary classifier decides *bet size* (and whether to trade) on top of the primary directional signal.
- **Fractional differencing**: make level series stationary while preserving memory (better than full `diff()` for feature inputs).
- **Feature neutralization / orthogonalization**: residualise signals against known risk factors to isolate incremental alpha.

### 8.5 Portfolio construction
- **Hierarchical Risk Parity (HRP)** as a robust alternative to the SLSQP ERC in `factor_optimizer.py` (no matrix inversion, better OOS stability).
- **Ledoit-Wolf / Bayesian shrinkage** of the factor covariance feeding `compute_ewma_factor_covariance`.
- **Portfolio-level vol targeting + drawdown control** overlay on aggregated factor positions.
- **Kelly-fraction sizing** (`f ≈ ICIR × IC_hitrate × const`, capped at 2× target vol) as an alternative to the tanh-ICIR gate.
