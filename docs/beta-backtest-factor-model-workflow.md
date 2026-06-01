# Beta Book → Backtest → Factor Model: Workflow Logic & Bias Audit

**Scope** — The *Backtest* subtab of the **Beta Book** tab, specifically the **Individual
Factors** inner sheet (the "risk-factor model backtest", a.k.a. **RFBT**). This document
maps the end-to-end execution path, then audits it for the kinds of bias and overfitting
that inflate a backtested Sharpe ratio. A separate improvement plan to *raise* the Sharpe
follows in [§5](#5-plan-to-increase-the-sharpe-ratio).

> Companion docs: [`factor-model-improvement-plan.md`](factor-model-improvement-plan.md)
> (the existing roadmap, with §-references that the code comments point to). This file is
> the **workflow + risk** view; that file is the **feature/architecture** roadmap.

---

## 1. Where it lives

| Layer | File | Responsibility |
|-------|------|----------------|
| Layout | [`web/tabs/beta/layouts/backtest.py`](../web/tabs/beta/layouts/backtest.py) | `build_beta_backtest_combined_layout` → two inner sheets: **Individual Factors** (`build_risk_factor_backtest_layout`) and **Portfolio** (`build_multiasset_backtest_layout`). |
| Callback | [`web/tabs/beta/callbacks/backtest_rfbt.py`](../web/tabs/beta/callbacks/backtest_rfbt.py) | `run_risk_factor_backtest` — the "▶️ Run Backtest & Save" handler; builds the IC table + 5-panel charts. |
| Engine (orchestration) | [`multiasset/factor_backtest.py`](../multiasset/factor_backtest.py) | `run_factor_backtest` dispatches `strategy='FactorModel'` to the factor-model engine; also owns yield→return conversion and `factor-rates.pkl` generation. |
| Engine (the model) | [`multiasset/factor_model.py`](../multiasset/factor_model.py) | `run_factor_model_backtest` (walk-forward), `build_features`, `_train_ic_model`, `build_position_series`. |
| Selection | [`factors/engine/selector.py`](../factors/engine/selector.py) | `FactorSelector` — IC threshold + significance + diversification + VIF filtering. |
| Inputs | `input/factor-rates.pkl`, `data/macro-px.pkl`, curve `*.pkl` | Factor level series, macro series, raw tenor curves. |

UI parameters the user controls: **Train window (months)** (`fm_train`, default 12),
**IC threshold** (`fm_ic`, 0.05), **Top N features** (`fm_topn`, 8), **Backtest period**
(`period_years`, 2). These map to `FactorModelConfig`.

---

## 2. End-to-end workflow logic

```
User clicks "Run Backtest & Save"
        │
        ▼
run_risk_factor_backtest()                         [backtest_rfbt.py]
  • factors = [selected single factor]
  • end_date = today;  start_date = today − period_years·365
  • kwargs = {train_months, ic_threshold, top_n}
        │
        ▼
run_factor_backtest(strategy='FactorModel', …)     [factor_backtest.py]
  • load_factor_rates()  → factor-rates.pkl  (regenerate if missing)
  • build FactorModelConfig, apply UI overrides
        │
        ▼
run_factor_model_batch() → run_factor_model_backtest() per factor   [factor_model.py]
  │
  ├─(a) build_features(factor)                      ── ONCE, on full history
  │      momentum (5/10/20/60/120/252 + EMA crosses)
  │      value/mean-rev (z-score 60/120/252, pct-rank, value-mom)
  │      volatility (10/20/60 + vol ratio)
  │      carry/curve (slope, curvature, roll-down)   [yield factors only]
  │      cross-factor diffs (same asset class)
  │      MACRO_* (level + pct_change)                [data/macro-px.pkl]
  │      → drop columns with >50% NaN
  │
  ├─(b) targets: daily return + forward returns for H ∈ {1, 5, 20}
  │      yield factor:  r = −D · Δy / 100   (duration-adjusted)
  │      price factor:  r = pct_change
  │
  ├─(c) WALK-FORWARD loop  (monthly test windows)
  │      train window = [cursor − train_months,  cursor − purge_gap]
  │      test  window = [cursor,  cursor + 1 month);  drop first `embargo_days`
  │      for each horizon H:
  │         _compute_ic_metrics()  ── Spearman IC, EWMA-weighted (halflife 63d)
  │         trend-regime veto → zero out z-score/value features in a trend
  │         FactorSelector.select_factors() → IC≥thr, significance, diversify, VIF, top-N
  │         _train_ic_model() → weight_i = signed Spearman IC(feature_i, fwd_ret_H)
  │         _predict_ic_model(test) → OOS predicted return
  │      blend horizons by mean |IC|  → predicted_return
  │      persist trained model artifact → input/models/factor_model_<YYYYMMDD>.joblib
  │
  ├─(d) build_position_series()   ── continuous sizing (causal)
  │      smoothed = rolling-mean(pred, signal_smooth_days)
  │      pred_z   = rolling z-score(smoothed, 60)
  │      icir_w   = tanh(ICIR / 0.25).shift(1)
  │      vol_scale= (target_vol / realised_vol(60d)).shift(1), capped at max_leverage
  │      position = clip(pred_z · icir_w · vol_scale,  ±max_leverage)
  │      turnover filter: only move when |Δ| > turnover_threshold
  │      IRDL → long_only; "long floor" 0.30 enforced in confirmed bond-bull trend
  │
  └─(e) PnL
         gross  = position.shift(1) · returns
         net    = gross − |turnover| · tx_cost_per_unit
         cumulative = (1 + net).cumprod()
        │
        ▼
Back in the callback:
  • compute_metrics() → Ann Ret/Vol, Sharpe (net & gross), MaxDD, Win%
  • rolling-60d IC, ICIR, IC t-stat, IC hit-rate  → metrics table
  • 5-panel chart per factor: Level · Signal · Position · Rolling IC · Cumulative PnL
  • incremental-merge artifact into the latest .joblib; report Mean ICIR
```

**Key invariant the design gets right:** position sizing is *causal*. Every sizing input
(`pred_z`, `icir_weight`, `vol_scale`) is built from data up to *t* and the position is
applied via `position.shift(1) * returns`, so today's position earns tomorrow's return.
Purge + embargo are implemented. Costs are netted. Gross vs net Sharpe are shown side by
side. This is a genuinely above-average first-generation design — which is exactly why the
*residual* biases below matter: they are the ones that survive a casual review.

---

## 3. Bias & overfitting audit

Severity = how much it is likely inflating the reported Sharpe / overstating confidence.

### 🔴 High severity

**B1 — Macro features carry publication-lag look-ahead bias.**
`MacroFactors.calculate_all()` ([`factors/generator/macro.py`](../factors/generator/macro.py))
loads `macro-px.pkl` and emits `level` + `pct_change` with **no release-lag shift**. Macro
series (CPI, PMI, GDP, etc.) are *stamped at the reference period* but published weeks
later. In `build_features` these become `MACRO_*` columns aligned to the reference date,
then `ffill().fillna(0)`. The model can therefore "see" a CPI print before it was public.
Because IC selection actively favours whatever correlates with forward returns, leaked
macro features are *preferentially* selected → optimistic IC, optimistic OOS PnL.
*Fix:* lag every macro series by its true publication delay (or a conservative blanket
`shift(business-days)`), built as a point-in-time `asof` join.

**B2 — Walk-forward purge uses the wrong horizon (`H_min`, not `H_max`).**
[`factor_model.py:770`](../multiasset/factor_model.py#L770):
`purge_gap = 1 + purge_days + H_min` with `H_min = min(horizons) = 1`. But the multi-horizon
ensemble trains on labels with horizons up to **20** days
(`all_fwd_by_H[H] = daily_returns.rolling(H).sum().shift(-H)`). The last training sample's
20-day forward-return window therefore overlaps the test set by ~13–14 trading days that
the 7-day purge does not remove. This is exactly the leakage purging exists to prevent, and
it inflates the H=5 / H=20 models' apparent OOS IC.
*Fix:* `purge_gap = 1 + purge_days + max(horizons)`.

**B3 — Regime-fitted long bias (trend veto + long floor) tested on the same sample it was tuned on.**
`trend_veto_zscore`, `long_floor = 0.30`, `long_floor_confirm_window = 120`, and the
IRDL `long_only` rule ([`factor_model.py:933-953`](../multiasset/factor_model.py#L933))
all bias the book toward *being long duration during falling-yield regimes*. Over a sample
in which Chinese/global bonds rallied, forcing a long floor mechanically lifts Sharpe — but
that is fitting the realised regime, not out-of-sample skill. The thresholds (`mom_sigma
0.5`, EMA windows `10/30/60`, floor `0.30`) are hand-chosen constants, never cross-validated.
*Fix:* treat these as hyper-parameters set on an *inner* validation split (nested CV), and
report Sharpe with the veto/floor **off** as the honest baseline.

### 🟠 Medium severity

**B4 — Researcher degrees of freedom ("Fix 1–4") with no multiple-testing discount.**
The engine carries four bolt-on "Fixes" (multi-horizon ensemble, trend veto, EWMA-IC,
long-floor + long-horizon momentum), each added to lift performance on the available data.
That is many forks of the analysis on one dataset. The reported Sharpe is **not deflated**
for this search. *Fix:* compute a **Deflated / Probabilistic Sharpe Ratio** (Bailey & López
de Prado) and/or **CPCV** so the headline number accounts for the number of configurations
tried. (Already catalogued as TODO in the improvement plan §8.3.)

**B5 — IC t-statistic is computed on overlapping observations → significance overstated.**
[`backtest_rfbt.py:193-199`](../web/tabs/beta/callbacks/backtest_rfbt.py#L193): the rolling
**60-day** IC series is treated as if its daily values were independent
(`ic_tstat = mean_ic / (ic_std / sqrt(n_ic))`, `n_ic` = number of days). Successive
rolling-60 windows share 59/60 of their data, so the values are ~0.98 autocorrelated and
the effective sample size is a small fraction of `n_ic`. The displayed t-stat (and the
"IC Hit%") can look strongly significant on pure noise. *Fix:* use non-overlapping IC
windows or a Newey-West / Hansen-Hodrick correction; divide `n_ic` by the window length to
get the effective N.

**B6 — Feature pre-screen (`nan_pct < 0.5`) and one-shot `build_features` use full-sample info.**
`build_features` is computed once over the *entire* history, and the >50%-NaN column drop
([`factor_model.py:362-364`](../multiasset/factor_model.py#L362)) is decided on the full
sample. Whether a feature *exists* in the model is thus a function of the whole period,
including the test span. Individual feature *values* are causal (rolling/EWMA), so this is
mild, but the availability decision is not point-in-time. *Fix:* decide column inclusion
inside each training window.

**B7 — Selection of 8 features from a large, correlated candidate set on ~250 obs.**
A 12-month train window is ~250 daily rows; the candidate set (momentum ×8, value ×5,
vol ×4, several carry, cross-factor, plus many `MACRO_*`) can be 40–60 features. Picking
top-N by in-sample IC at a low `ic_threshold = 0.05` is prone to selecting noise that won't
persist OOS. VIF + diversification help but don't fully cure it. *Fix:* shrink the menu
(orthogonalise/neutralise features), raise the effective threshold via significance, or
switch the combiner to Lasso/ElasticNet which zeroes weak features (plan §2.1).

**B8 — Short default OOS window (2 years).**
The RFBT default `period_years = 2` yields a 2-year, single-path walk-forward. With monthly
retrains that is ~24 test windows — too few to distinguish skill from luck, and dominated by
whatever single macro regime spanned those 2 years. *Fix:* default to ≥5 years; report
per-year Sharpe and a CPCV distribution rather than one path.

### 🟡 Low severity / watch-list

- **B9 — Cost realism.** Flat `FACTOR_TX_COST_BP` (≈0.3bp notional) with no market-impact,
  no roll/funding cost on continuously-held positions. Continuous sizing trades small
  amounts often; understated slippage flatters net Sharpe. (Roll cost is a TODO in plan §5.1.)
- **B10 — Train/predict IC inconsistency.** Selection uses EWMA-weighted Spearman IC, but
  `_train_ic_model` weights use *unweighted* `spearmanr` ([`factor_model.py:531-533`](../multiasset/factor_model.py#L531)). Not a leakage, but the trained weights don't match the
  selection criterion.
- **B11 — Survivorship / universe selection.** The factor menu is the set of *currently*
  liquid, currently-interesting factors (hand-listed in the layout). Low concern because
  these are constructed factors with fixed deterministic weights (no PCA refit → no
  construction leakage), but the *choice* of which factors to ship is itself an ex-post
  decision.
- **B12 — `scaling_factor` (`mean|y|/mean|pred|`).** Harmless for sign/Sharpe (monotone
  rescale of a z-scored position) but makes the "predicted return" magnitude in the chart
  non-comparable across factors; don't read it as a real return forecast.

### ✅ Things the model gets right (no action)

- Position sizing is causal; `position.shift(1) * returns` avoids look-ahead.
- `StandardScaler` and `scaling_factor` are fit on **train only**, applied to test.
- Purge + embargo exist (the bug is the *magnitude* in B2, not their absence).
- Deterministic factor construction uses fixed weights — no full-sample PCA refit leakage.
- Gross **and** net PnL are both reported, so cost impact is visible.

---

## 4. Net read

The framework is structurally sound (causal sizing, walk-forward, purge/embargo, costs).
The Sharpe inflation risk is concentrated in **B1 (macro leakage)**, **B2 (purge horizon)**
and **B3 (regime-fitted long bias)**, amplified by **B4–B5 (no multiple-testing discount,
overstated IC significance)**. Until those are addressed, the headline Sharpe should be read
as an **upper bound**, not an estimate. The right sequence is: *fix the leaks → re-baseline
honestly → then chase Sharpe*. The plan below is ordered accordingly.

---

## 5. Plan to increase the Sharpe ratio

Two tracks. **Track A first** — until the leaks are closed, any Sharpe "gain" from Track B
is unmeasurable. Effort: S/M/L. Lift estimates are *net of the honest re-baseline* and
deliberately conservative.

### Track A — Close the leaks & measure honestly (do first; protects, not pads, Sharpe)

| # | Action | Addresses | Effort | Effect |
|---|--------|-----------|--------|--------|
| A1 | **Lag macro features** by true publication delay (point-in-time `asof`); add a config `macro_pub_lag_days`. | B1 | S | Removes look-ahead; *expect headline Sharpe to drop* to its real level. |
| A2 | **Fix purge** to `1 + purge_days + max(horizons)`. | B2 | S (1 line) | Removes 13–14d train/test overlap on H=5/20. |
| A3 | **Deflated / Probabilistic Sharpe + CPCV** evaluation; show DSR next to Sharpe in the table. | B4, B8 | M | Honest confidence; kills false positives from config search. |
| A4 | **Newey-West IC t-stat** + effective-N (÷ window) in the metrics table. | B5 | S | Stops overstated significance on overlapping IC. |
| A5 | **Default OOS ≥ 5y**, report per-year Sharpe and the CPCV Sharpe distribution. | B8 | S | Regime-robust read instead of single-path luck. |
| A6 | **Baseline-with-vetoes-off**: run the model with `trend_veto`/`long_floor` disabled as the reference; only keep them if they survive nested CV. | B3 | M | Separates real skill from regime fit. |

### Track B — Genuinely raise risk-adjusted return (after A re-baseline)

Ordered by value-for-effort. These align with the existing roadmap so the code comments
("doc §…") stay coherent.

| # | Action | Rationale | Effort | Est. Sharpe lift |
|---|--------|-----------|--------|------------------|
| B-1 | **Lasso / ElasticNet combiner** with `TimeSeriesSplit`-CV `alpha`, candidate menu widened to ~30 but effective 5–8 selected. | Cuts B7 overfit; sparse weights generalise better than top-N-by-IC. | M | +0.05–0.15 |
| B-2 | **Window ensemble** (6M/12M/24M) blended by **out-of-sample** ICIR (not in-sample IC). | Reduces coefficient-estimation variance; current blend weights use in-sample IC. | M | +0.10–0.20 |
| B-3 | **Cross-factor & derived features**: carry×momentum product, carry-to-vol ratio, term-premium proxy, trend-strength (ADX). | More orthogonal alpha; cheap given the feature scaffold exists (plan §1.2–1.3). | M | +0.05–0.15 |
| B-4 | **Covariance-aware combination across IR sub-factors** (IRDL/IRSL/IRCV ≈ 7:2:1 vol) via HRP / shrinkage covariance, replacing per-factor-only vol scaling. | Real diversification at the book level, not just stand-alone vol parity. | L | +0.05–0.15 |
| B-5 | **Regime-conditional models** (vol-state or HMM): separate sub-model in high- vs low-vol; momentum reverses faster in stress. | Historically +0.1–0.3 in FI systematic; replaces the hand-tuned trend-veto with a learned switch. | L | +0.10–0.30 |
| B-6 | **Cost-aware trade gate** ("trade only if expected PnL > 2× cost") + roll-cost term. | Lifts *net* Sharpe by cutting low-conviction churn; complements B9. | S | +0.05–0.10 (net) |
| B-7 | **Meta-labeling** sizing layer: a classifier sets bet size on top of the directional signal. | Improves hit-rate-weighted sizing without touching the primary signal. | M | +0.05–0.15 |

### Suggested sequence

1. **Sprint 1 (S, days):** A1, A2, A4, A5 — close leaks, fix stats, lengthen OOS.
2. **Sprint 2 (M):** A3 + A6 — honest evaluation harness + veto/floor ablation → establish the *true* baseline Sharpe.
3. **Sprint 3 (M):** B-1, B-3, B-6 — sparse combiner, derived features, cost gate.
4. **Sprint 4 (M):** B-2 OOS-ICIR window ensemble.
5. **Sprint 5 (L):** B-4 / B-5 — covariance-aware combination and regime switching.

> **Success criterion:** target the *post-leak-fix, deflated* Sharpe, not the current
> headline. A model that goes from an inflated 0.8 to an honest 0.5 and then to a genuine
> 0.8 via Track B is strictly better than one that "kept" 0.8 the whole time.
