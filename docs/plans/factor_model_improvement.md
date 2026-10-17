# Beta factor model — improvement log and next steps

Status: **living record.** Covers the walk-forward factor model in `multiasset/factor_model.py`
(IC-weighted linear model, 12-month train window, 1/5/20-day horizon ensemble). Written 2026-10-14
after a day of feature A/B tests; complements `docs/plans/beta_book_exposure_vs_capital.md`
(sizing / capital usage) and `docs/plans/portfolio_construction_beta_alpha.md`.

---

## 1. Evaluation protocol (use this for every future change)

A full-sample Sharpe is not enough. Every candidate on this page that looked good full-sample and
failed the window sweep did so by a few windows (2022, 2023, 2025).

1. Run the walk-forward for base and variant on the same factors (`run_factor_model_backtest`,
   variant via a config flag; ~1 min per factor-variant, parallelise 6 wide).
2. Compare **price-only Sharpe, rf = 0, from 2016-09-01** (the Factor-tab basis).
3. **Window sweep:** 26 six-month windows, start dates every 4 months from 2016-09 to 2025-03.
   Walk-forward output is causal, so slice one full run instead of re-running per start date.
   Report wins / n and the **median** Sharpe delta. A change is only real if the median is positive.
4. **Whole-book view:** equal-risk book (each factor vol-scaled to 10% with trailing 252d vol,
   lagged one day, floored at 25% of full-sample vol). A feature that helps one factor and hurts
   another is judged on the book.
5. Include holdout factors from other asset classes; the choice of *where* to enable a feature is a
   post-hoc selection and must be flagged as such.

Per project notes: do not tune parameters of one factor to fit its history (see memory
`alpha-backtest-no-param-tuning`).

## 2. What was tested (2016-09 .. 2026-09, price-only, rf = 0)

| Change | Flag | Default | Result |
|---|---|---|---|
| **Macro composites** (Growth / Inflation / RiskApp idx + 20/60d chg, Cu/Au) on commodities | `macro_composite_features` (+ `_MACRO_COMPOSITE_PREFIXES = {CMDL}`) | **ON, CMDL only** | 16-factor book Sharpe 1.38 -> 1.58, ann 4.39% -> 4.98%, 16/26 windows (median +0.13), 9/11 years. Commodity sub-book 0.31 -> 0.56 |
| Stretch-tail (overbought/oversold) features | `stretch_tail_features` | off | CN book 1.58 -> 1.66 full-sample, but 13/26 windows, median 0.00. Only USDCNY consistent (17/24). Hurts EQDL.IF (0.32 -> 0.15), so `EQDL` excluded |
| Halve-on-exhaustion position overlay | not implemented | - | +-0.02, nothing |
| Trend-veto removed | `trend_veto_zscore=False` | on (unchanged) | Mixed; big loss on IF |
| Growth macro block (42 per-series + composite features) | `macro_growth_features` | off | CN book 1.60 but median window delta -0.14; swings regime years (2023 -0.32 -> +2.58, 2022 0.75 -> 0.20); hurts IRDL, IF, CRCV |
| Liquidity macro (FR007-DR001, SHIBOR3M-FR007, FR007 chg) | `macro_liquidity_features` | off | Inert (CN book 1.54, median +0.01) |
| Bond-futures roll + implied-repo-minus-FR007 (T/TF/TS) | `bond_futures_features` | off | Whole book 1.58 -> 1.61 but 11/26 windows, median -0.02 |

### Diagnostics worth remembering

- **Stretch vs forward return (model-free):** IRDL.CN is *momentum* (IC +0.08..+0.17, ~115% of its
  P&L is made when >2 sigma overbought); IRCV.CN is strong *reversal* (IC -0.3..-0.5 in tails);
  IRSL.CN reverts only on long windows. A blanket "fade extremes" rule would have hurt IRDL.
- **Commodity composites are mostly a sector-trend signal.** Removing a commodity's own price from
  the inputs erases most of the gain (0.56 -> 0.30). Legitimate, but not a clean growth/inflation read.
- **Bond-futures roll vs IRDL:** the IC of -0.28 seen on 2023-26 data was a regime artifact; over
  2015-26 it flips sign by year (+0.17 pooled, +0.63 in 2020). Roll vs IRSL is negative in 11/12
  years but overlaps the slope/carry features already in the model.
- **Current macro usage:** selected-feature share is ~11% macro for IRDL.CN, ~35% for IRSL/IRCV.CN,
  mostly 1-day `_pct` columns (noise); the rest is momentum / cross-factor / vol.
- **Conclusion for CN rates:** five rounds of price-derived features (stretch, growth, liquidity,
  futures roll/IRR, composites) produced no robust gain. The limit looks like the linear
  feature-selection structure, not the feature set.

## 3. Open work

### 3.1 Immediate
1. **Retrain — DONE 2026-10-14** (Train action replica: 35-factor pool, `save_latest_only=True`,
   ~2.5h, wrote `factor-backtest.pkl` + `factor_model_20261031.joblib`; 32 trained, SPDL.CDB and
   CRDL/CRSL.ICP not in `factor-rates` so their old cache entries were kept as-is). Comparing old vs
   new cache is NOT like-for-like on the full window: the old cache had only ~1,270-1,470 rows for
   many factors (history from ~2020-21) vs up to 2,600+ now. On the common window from 2021-10-15:
   16+ factor equal-risk book Sharpe 1.67 -> 1.73, ann 2.90% -> 3.80%; commodity sub-book -0.12 -> 0.00;
   CN rates 1.19 -> 1.10 with NO code change for CN (a run-to-run / data-vintage noise floor of
   roughly +-0.1-0.15 per book, larger per factor). Treat the retrain gain as modest and mostly from
   longer history, not proven model improvement. Backups of the pre-retrain artifacts are in the
   session scratchpad only (not durable).
2. **US rate factors returned empty — FIXED 2026-10-14 (data, not model).** `IRDL/IRSL/IRCV.US`
   (and .DE/.JP/.UK) had only 3-135 valid points in `factor-rates.pkl`. Root cause chain:
   `fxcurve_ts.pkl` had a pandas-3 BlockManager defect (aliased blocks) -> `_safe_read_pickle` set it
   aside as `fxcurve_ts.pkl.bak_corrupt_mgr` -> `multiasset.utils.updatePKL` (merge mode) saw "no file"
   and wrote only the newest 7 rows, dropping 2015-2026 history. Repaired by loading the backup with
   `load_pickle_with_blockmanager_repair`, then filling holes from Wind EDB (full-history fetch matched
   the stored US/JP/DE values to 0.0000). Also found: the old file's `*2M` column is really the 2Y
   yield (mislabelled; matches Wind 2Y exactly), and it had a hole 2026-06-17..07-15. UK stored values
   differ from today's Wind series (mean 0.04-0.09, max 1.4 in 2022) — old values kept, only gaps filled.
   `updatePKL` now tries the repair loader first so history cannot be dropped this way again.
   After the fix the foreign-rate factors train (~2,700 days each) but are weak under the current
   'continuous' sizing: 2016-09+ Sharpe IRDL.US 0.22, IRSL.US -0.02, IRCV.US 0.42, IRDL.DE 0.00,
   IRDL.JP -1.05, IRDL.UK 0.11. (An older code comment quotes US 0.99 / DE 1.22 under 'discrete'
   sizing — not re-verified.)
3. Watch the commodity sleeve out of sample ("commodities only" was chosen after seeing results).

### 3.2 Model structure (next real lever for rates)
- Regime-conditional weights instead of one global signed IC weight per feature.
- Shrink / regularise the IC weights; revisit the 1/5/20-day horizon blend.
- Untested, post-hoc candidate: rolling-z-score of implied repo minus FR007 for IRCV (positive IC in
  10 of 11 years, only +0.06 pooled).

### 3.3 Sizing (probably larger than any signal change)
- Signed sleeves use only ~11% of capital, so total-return Sharpe is cash-dominated until a
  leverage / risk-target rule is chosen. See `beta_book_exposure_vs_capital.md`.

### 3.4 Housekeeping
- 3 failing tests: `test_alpha_layouts.py::test_individual_backtest_layout_is_not_locked_to_76px_columns`,
  two in `test_startup_eod.py`. Unconfirmed whether they predate this work.
- `tests/test_beta_book_capital_snapshot.py` has a collection error: missing
  `_normalize_beta_capital_columns` in `web/tabs/risk/books/beta_table.py`.
- `python main.py futures-analytics-backfill --rewrite` is **unsafe**: if the Wind fetch fails it
  rebuilds `futures-analytics.pkl` from the stale `futures-db.pkl` and drops rows (it dropped 84
  per contract once). Back up first, or change it to abort.

### 3.5 Foreign rate factors: discrete sizing (done 2026-10-16)

After the data repair (3.1 item 2) the 12 foreign rate factors (IRDL/IRSL/IRCV x US/DE/JP/UK) were weak
under 'continuous' sizing. Tested the older 'discrete' mode (same data, 2016-09..2026-10, full family,
no per-factor tuning):

| | continuous | discrete | windows (wins, median delta) |
|---|---|---|---|
| 12-factor equal-risk book | 0.55 (ann 2.0%) | **0.90 (ann 3.4%)** | 16/26, +0.61 |
| DE+JP+UK (9) | 0.44 | 0.90 | 17/26, +0.67 |
| US (3) | 0.38 | 0.33 | 13/26, +0.05 (no gain) |
| Level factors IRDL x4 | -0.56 | -0.03 | 17/26, +0.44 (still no edge) |
| CN rates + foreign 50/50 | 1.66 | 1.83 (maxDD -5.2% -> -4.2%) | |

Gain is concentrated in IRSL.UK (0.58 -> 1.37) and IRSL.DE (0.32 -> 0.67); IRCV.UK collapses
(1.08 -> 0.11) and IRSL.US is ~0 either way. Implemented as `_FOREIGN_RATE_DISCRETE` in
`_FACTOR_SIZING_OVERRIDES`; `run_factor_model_backtest` now applies overrides unless the caller picked a
non-default mode (the Train action always passes the default explicitly, which previously bypassed
overrides and would have made the backtest disagree with the saved-artifact predict path).
Limitation: explicitly choosing the default mode for an overridden factor is indistinguishable from
unset. Open: the four foreign level factors have ~no edge in either mode - decide whether they should
carry any weight in the beta book. The 50/50 line lowers annual return vs CN alone (7.5% vs 11.1%) at
equal per-leg risk; it improves Sharpe and drawdown, so it only helps if the book is sized by risk.

### 3.6 Foreign factors in the real portfolio (2026-10-17)

Portfolio-level A/B via `run_historical_allocation(..., alloc_mode='factor_scaling')`, 2017-01-02..2026-10-13,
default pool (IRDL/IRSL/IRCV.CN + FXDL.USDCNY + CMDL.AU + CMDL.AL) vs the same plus foreign rate factors.
Price-only rf=0 Sharpe is the Factor-tab-comparable number.

| Pool | Sharpe (price-only) | Total-return Sharpe | Post-funding Sharpe | Ann. return | Max DD |
|---|---|---|---|---|---|
| Default | **0.93** | 0.64 | 1.01 | **4.75%** | -6.2% |
| + IRDL.US/DE/JP/UK | 0.60 | 0.28 | 0.64 | 3.05% | -6.4% |
| + 8 slope/curve (IRSL/IRCV x 4) | **1.07** | 0.38 | 1.09 | 2.95% | **-3.2%** |
| + all 12 | 0.82 | 0.20 | 0.84 | 2.51% | -5.2% |

- Factor-level add-one (equal-risk legs, saved pkl) agrees: adding the 4 IRDL legs takes the 6-factor
  book Sharpe 1.84 -> 1.39, ann 9.9% -> 5.8%, 7/26 windows (median -0.46). They are uncorrelated with the
  book (|corr| ~0.0-0.03), so this is dilution by near-zero-edge legs, not a diversification failure.
  IRDL.JP is the worst (standalone -0.82; adding it alone 1.84 -> 1.51).
- Slope/curve sleeves improve Sharpe and halve the drawdown but lower annual return in this sizing.
- **Bug found and fixed:** `FACTOR_TO_ASSET_MAP['IRDL.US']` had no `US1Y` asset although the US IR grid has a
  1Y tenor, so `factor_mimicking_weights` returned None and ALL THREE US factors silently got no sleeve in
  `factor_scaling` ("unreplicated"). Added `US1Y`. Anyone who previously ran US factors in the portfolio
  was running without them.
- Caveat: Stage-1 `beta_rp_cache.pkl` is keyed on pool/dates/params, not on `FACTOR_TO_ASSET_MAP`; a
  fresh recompute gave identical numbers here, but clear it after editing the map.
- Not yet checked: FX exposure and hedging of the foreign bonds, and carry-minus-funding by country.

### 3.7 Foreign factors: FX / hedge / capital findings (2026-10-17)

- **FX:** `calculate_daily_returns_series` treats every foreign bond as fully CNY-hedged (`fx` recorded but
  excluded from `total`), so the book has no spot FX P&L or exposure by construction. A real implementation
  needs forward hedges on the net notional: IRDL.US/DE/JP/UK average +34% of capital net long (US 11.9,
  UK 9.7, DE 8.5, JP 4.2); the 8 slope/curve sleeves are near-neutral (net +0.5/0.0/1.7/0.4% of capital, gross
  10-26% per country).
- **Hedge cost is not charged.** The code comment cites an interest-rate-parity cost but `total = carry +
  capital` credits the full foreign yield. Estimated omission (foreign overnight rate minus DR001, x signed
  notional): +IRDL4 0.11%/yr of capital (US 0.03, UK 0.09, DE 0.01, JP -0.03), +SC8 0.03%/yr. Immaterial, but
  an under-estimate: overnight-rate series only start 2018 (US), 2020 (JP), 2021 (DE) so earlier years cost 0,
  and the cross-currency basis (large for JPY/EUR) is not modelled.
- **The book is gross-capped, not risk-sized.** `scale_sleeve_to_dv01_target` + `weights_to_notional`
  (default `max_utilisation` bound at import = 0.95) hold gross notional at ~91-95% of capital on almost every
  day. Long/short slope-curve sleeves use a lot of gross for little risk, so under the cap they are
  capital-inefficient. Price-only decomposition, 2017-2026, % of capital:

| Book | gross | price ann | carry | price vol | price maxDD | Sharpe |
|---|---|---|---|---|---|---|
| Default @0.95 | 91% | 5.36 | 0.44 | 5.72 | -9.4 | 0.94 |
| Default + SC8 @0.95 | 95% | 3.12 | 0.23 | 2.92 | -4.3 | 1.07 |
| Default @1.9 | 178% | 10.55 | 0.85 | 11.27 | -17.4 | 0.94 |
| Default + SC8 @1.9 | 188% | 6.18 | 0.46 | 5.81 | -8.7 | 1.06 |

  At matched risk (SC8 @1.9 vs default @0.95): price return 6.2% vs 5.4%, max DD -8.7% vs -9.4%. The
  smoother book keeps its return only with ~1.9x gross (futures/swaps or a margin-based capital definition).
  Reported `annualized_return` is net of items not decomposed here (price+carry exceeds it by ~1pt).
- **Optimal SC8 share disagrees by level.** Factor-level equal-risk sweep peaks at ~25-35% risk share
  (Sharpe 1.87 -> 2.1, 20-21/26 windows); in the portfolio engine, scaling the SC8 capital share to 15/25/35%
  gave price-only Sharpe 0.80/0.87/0.92 vs 1.07 at the default (~half) share. Treat the gain as roughly
  +0.1-0.2 Sharpe, not precise.
- To test a modified cap: patch `orch.weights_to_notional` (the `RiskModelConfig.CAPITAL_UTILISATION_MAX`
  default is bound at import, patching the config alone only changes the DV01 scaling step).

## 4. Candidate new factors for the pool (all untested)

Current pool: CN/US rates (level, slope, curve), CDB/LGB credit, CDB spread, four FX pairs,
~11 commodities, four equity-index futures. Each candidate below uses data already collected and
must pass section 1 before it is added.

| Candidate | Data | Rationale |
|---|---|---|
| Swap spread (IRS minus bond yield) | IRS + bond curves | Funding / liquidity driven; diversifies duration factors |
| Equity style spreads (IC-IH size, IF-IC) | Index futures | Market-neutral; a different return source than direction |
| Convertible-bond equity factor | CBond data | Equity exposure with a bond floor |
| Commodity spreads (RB vs JM margin, crack) | Commodity futures | Real-economy signal, less trend-dominated |
| CN-US rate spread / carry | CN + US curves | Rates / FX linkage for USDCNY |
| Credit-quality spread (AAA vs AA, CDB vs LGB) | Credit curves | Risk-appetite signal |
| Bond-futures calendar spread / basis as its own factor | Backfilled futures history | Tradable positioning signal rather than a duration feature |

Data not collected today (would need sourcing): repo turnover volume, bond-fund leverage / duration,
bond-futures open interest history (`futures-px.pkl` has ~5 months), monthly macro releases
(CPI / PPI / PMI / credit impulse; need release-date alignment to avoid look-ahead).

## 5. Code map

- `multiasset/factor_model.py`: `FactorModelConfig` flags (`stretch_tail_*`, `macro_*`,
  `bond_futures_features`), `_stretch_tail_features`, `_macro_growth_features`,
  `_macro_liquidity_features`, `_bond_futures_features`, `_MACRO_COMPOSITE_PREFIXES`,
  `_STRETCH_TAIL_EXCLUDE_PREFIXES`, `_BOND_FUTURES_PREFIXES`.
- `build_features()` always computes the optional columns (so any saved model can be rebuilt at
  predict time); the config flags only control what the walk-forward training sees.
- `curves/utils/retrieve.py`: fixed two backfill bugs (Timestamp-vs-date comparison; closes fetched
  only for first-day contracts).
- Data: `../input/futures-analytics.pkl` now covers T/TF from 2015-03, TS from 2018-08, TL from
  2023-04 (implied repo / implied yield from 2016-01).

---

## 6. Plan: improving the whole multi-asset portfolio's Sharpe (2026-10-17)

### 6.1 What the diagnostics say

The same 6 factors (default pool) give price-only Sharpe **1.84 as an equal-risk factor book** but only
**0.93 inside the portfolio** (2017-2026, `factor_scaling`). The gap is portfolio construction, not signal
quality. One-at-a-time levers on the portfolio (price-only Sharpe / max DD / reported ann. return):

| Variant | Sharpe | Max DD | Ann. return (reported) |
|---|---|---|---|
| Current (IR sleeves ~ vol^0.5 capital, others equal) | 0.93 | -6.2% | 4.75% |
| Equal capital per sleeve | 0.94 | -6.2% | 4.85% |
| **Inverse-vol sleeve capital (risk-parity sleeves)** | **1.31** | **-1.2%** | 2.50% |
| No short-end long-only floor | 1.01 | -4.8% | 4.55% |
| Inverse-vol + no floor | 1.31 | -1.3% | 1.46% |
| Inverse-vol + 1.9x gross + DV01 target 20 | 1.20 | -3.0% | 4.10% |
| Inverse-vol + no floor + 1.9x gross + DV01 20 | 1.28 | -2.9% | 1.55% |

- Transaction costs are not the problem: ~3.1M over ~10 years on 1bn (annual turnover ~32x notional).
- Risk-parity sleeve budgets are the largest measured lever (+0.38 Sharpe). They also shrink risk, so
  reported return falls; leverage in the engine is not free (Sharpe 1.31 -> 1.20-1.28 at 1.9x).
- The reported `annualized_return` mixes price, carry, cash/financing and costs and is not linear in size
  (price + carry exceeded it by ~1pt; doubled DV01 left it flat in one variant). It cannot yet be used to
  tune "annual PnL" - see P0.

### 6.2 Ordered plan

**P0 - Return attribution (prerequisite, small).** Decompose reported annual return into price, carry,
cash/financing, tx cost and funding, per sleeve and per day, and expose it in the backtest output. Until
then, return-targeted tuning is guesswork.

**P1 - Sleeve sizing / risk target (biggest lever).** Replace capital-share budgets with risk-based
sleeve budgets (start with inverse-vol of the sleeve's own P&L, EWMA; then covariance-aware ERC), and size
the book to a target volatility instead of "gross = 95%". Validate with the 26-window sweep (not the
full-sample number). Decide the target vol and whether leverage/futures-swaps implementation is allowed
(user decision). Acceptance: price-only Sharpe up AND window median delta > 0 AND a defined return at the
chosen risk target.

**P2 - Short-end floor.** `SHORT_END_LONG_ONLY_TENORS` removal: Sharpe +0.08, DD -6.2% -> -4.8%, return
-0.2pt on the current budgets, none under inverse-vol. Re-test under P1 sizing and decide with the
swap-hedge intent (floor protects carry; user plans to hedge via 1-5Y swaps).

**P3 - Pool composition (re-run after P1, because the pool results depend on the budget rule).**
- Credit factors are absent from the default pool but strong standalone in the retrained cache
  (CRCV.LGB 1.36, CRSL.LGB 1.28, CRDL.LGB 1.06, CRDL.MTN 0.80; price-only, 2016-09+). Test them in the
  portfolio.
- Foreign slope/curve (8) at risk-based budgets (they were crowded out under capital budgets); exclude the
  four foreign IRDL.
- Decide the foreign-FX treatment (hedge cost not charged, no cross-currency basis) before any live use.

**P4 - Signal robustness.** Walk-forward noise floor is ~+-0.1-0.15 Sharpe per book with no code change.
Reduce variance by ensembling model runs (train windows 9/12/18 months, or bagged windows) before adding
features; feature additions on CN rates are exhausted (5 null tests). Structural options: regime-conditional
weights, IC-weight shrinkage, horizon blend.

**P5 - Validation discipline.** Many tests have been run on the same 2016-2026 history. Freeze the last
12-18 months as a holdout that is only touched for final confirmation of whichever P1-P4 changes are
adopted; keep the window sweep as the release gate.

**P6 - Cross-book.** Beta/Alpha combination (`web/tabs/risk/books/combination.py`) was not examined in
this work; re-run the margin-share Sharpe frontier after P1 changes the beta book's return series.

### 6.3 Update 2026-10-17: P0 done; the portfolio is a commodity-risk book; unlevered frontier

User constraints (recorded): **no leverage in the beta book** (futures/swaps only to hedge; leverage lives in
the alpha book). Sleeve sizing is therefore a choice of a point on an unlevered return/Sharpe frontier.

**P0 (done):** `multiasset/book/attribution.py` + `metrics['attribution']` in the backtest orchestrator
(display-only, wrapped in try/except), `tests/test_book_attribution.py`. Default pool, 2017-2026:
price 5.36 + carry 0.44 + cash 0.06 = **5.86% simple annual** (% of initial capital); tx cost -0.03;
reported `annualized_return` 4.75% is the geometric CAGR of NAV -> **compounding drag -1.11pt** (not a missing
cost).

**Current sleeve rule is NOT risk parity.** `pool_sleeve_budgets` gives IR sleeves capital ∝ sqrt(vol)
("higher budget to higher-vol factors") and every other sleeve equal capital. Realised P&L risk by class
(default pool, 2017-2026):

| Class | Avg gross | Price vol | Risk share | Price ann. |
|---|---|---|---|---|
| Commodities (AU, AL) | 41% | 5.57% | **94.0%** | 3.72% |
| FX (USDCNY) | 20% | 1.42% | 5.4% | 1.24% |
| Rates (CN IRDL/IRSL/IRCV) | 30% | 0.45% | **0.6%** | 0.39% (+0.44 carry) |

The 0.93-1.0 portfolio Sharpe is essentially the gold/aluminium Sharpe; the CN rates sleeves (factor-level
Sharpe 0.6-1.0) carry almost no risk because DV01-scaled bond sleeves have tiny vol per unit of capital.

**Unlevered frontier** (class-level sleeve multipliers on the current run, daily gross capped at 95%, price +
carry, % of capital; multipliers are Rates/FX/Commodities):

| Design | Sharpe | Ann. | Vol | Max DD | Worst yr | Windows vs A (wins, median dSharpe) |
|---|---|---|---|---|---|---|
| A current (1,1,1) | 1.01 | 5.80% | 5.7% | -9.2% | -0.1% | - |
| E (2,3,1) | 1.18 | 5.02% | 4.3% | -5.5% | +1.1% | 16/25, +0.15 |
| C (2,1,0.5) | 1.37 | 4.13% | 3.0% | -3.3% | +1.4% | 21/25, +0.38 |
| D (3,2,0.35) | 1.63 | 3.94% | 2.4% | -2.1% | +0.3% | 19/25, +0.63 |
| F (3.3,0.5,0.1) | 2.22 | 2.77% | 1.2% | -1.2% | +0.3% | 21/25, +1.09 |

C, D, F beat A in both halves of the sample (e.g. D: 2.03 vs 1.56 first half, 1.31 vs 0.53 second half).
Caveats: class-level scaling assumes the within-class mix is unchanged; a ~280-cell grid on one 10-year history
overstates the peak (use designs, not the max cell); E leans on 3x the single-pair USDCNY sleeve (policy-managed
pair, concentration); the choice between A..F is a return-vs-smoothness decision for the user.

**Next (P1 implementation, after the user picks a design):** express the chosen class risk shares as sleeve
budgets (replace `pool_sleeve_budgets`' capital-share rule), keep gross <= 95% / no leverage, validate with the
window sweep and the frozen holdout (P5), then re-test the credit and foreign slope/curve pools under it (P3).

### 6.4 Update 2026-10-17 (later): Pure Risk Parity mode vs factor-scaling vs design C

Comparison missed in 6.3. Same pool, 2017-2026, price + carry, unlevered, gross <= 95%
(`alloc_mode='risk_parity'` = monthly long-only RP across assets; `'factor_scaling'` = signed sleeves):

| Book | Sharpe | Ann. | Vol | Max DD | Worst yr | Avg gross | Risk share R/F/C |
|---|---|---|---|---|---|---|---|
| **Pure Risk Parity mode** | **2.04** | 2.63% | 1.3% | -2.7% | +0.2% | 95% (rates 90%) | 61/3/36 |
| Factor-scaling current (A) | 1.01 | 5.80% | 5.7% | -9.2% | -0.1% | 91% | 1/5/94 |
| Design C (fixed 2/1/0.5) | 1.37 | 4.13% | 3.0% | -3.3% | +1.4% | 84% | ~8/20/72 avg |

Neither C nor A dominates the RP mode: RP has the higher Sharpe and smaller drawdown but less return.
Basis caveat: RP's reported price-only Sharpe is 0.87 (no carry); its 2.04 includes bond carry and the
2017-2026 CN bond rally. Rising-yield regimes would hurt a 90%-duration book.

**Combination (RP-mode rates book + slices of the factor-mode FX and commodity sleeves, gross <= 95%):**
this beats both RP and C. Multipliers: RP rates book x R, factor-mode FX sleeve x F, commodity sleeve x C.

| Combo (R,F,C) | Sharpe | Ann. | Max DD | Windows vs RP (wins, median dSharpe) |
|---|---|---|---|---|
| RP mode | 2.04 | 2.63% | -2.7% | - |
| (1, 0.5, 0.1) | 2.35 | 2.83% | -2.3% | 16/25, +0.08 |
| (1, 1, 0.2) | 2.10 | 3.25% | -2.4% | 16/25, +0.38 |
| (1, 2, 0.3) | 1.85 | 3.63% | -2.5% | 15/25, +0.21 |
| (0.9, 2, 0.5) | 1.62 | 4.03% | -2.8% | 13/25, +0.14 |
| (0.8, 2, 0.75) | 1.41 | 4.51% | -3.9% | 13/25, +0.11 |

(0.9, 2, 0.5) has similar return to design C with higher Sharpe (1.62 vs 1.37) and smaller drawdown. Gains over
RP are modest in window terms (median +0.1 to +0.4). Combos were selected on the same 10 years: confirm on the
frozen holdout (P5). **Design C is superseded** by "RP core + small FX/commodity signal sleeves".

### 6.5 Audit of the two methods (2026-10-17)

Method 1 = Pure Risk Parity (`alloc_mode='risk_parity'`: Stage-1 factor ERC + Stage-2 tenor shape, monthly,
then 3M-momentum veto on FX/commodity + class caps). Method 2 = factor model on top of risk parity
(`'factor_scaling'`). Default 6-factor pool, 2017-2026, price + carry, unlevered:

| Book | Sharpe | Ann. | Vol | Max DD | Worst yr | Gross R/F/C | Risk share R/F/C |
|---|---|---|---|---|---|---|---|
| M1 Stage-1/2 weights, before veto/caps | 1.95 | 2.55% | 1.3% | -2.6% | +0.2% | 85/5/5 | 53/4/43 |
| **M1 live (veto + caps)** | **2.04** | **2.63%** | 1.3% | -2.7% | +0.2% | 90/2/4 | 61/3/36 |
| M2 as coded (signed sleeves, IR capital ∝ sqrt(vol), others equal) | 1.01 | 5.80% | 5.7% | -9.2% | -0.1% | 30/20/41 | 1/5/94 |
| **M2 on the RP budgets** (Stage-1 ERC budget renormalised over the pool, signed by factor signal) | 1.95 | 2.54% | 1.3% | **-1.9%** | **+1.0%** | 72/5/3 | 53/12/35 |

Findings:
- M1 works as designed at the capital level (rates ~85-90% of gross because rate sleeves have tiny vol), but
  realised ex-post risk is not equal across factors (rates ~53-61%, commodities 36-43%, FX 3-4%). The veto and
  class caps are NOT the cause (Sharpe 1.95 -> 2.04 with them).
- Stage-1 ERC solves over ~48 global factors (`reference_factor_budget`); a pool's own factors receive small,
  arbitrary absolute budgets (e.g. IRDL.CN 0.001, USDCNY 0.01, AU 0.001 in 2021-12). Relative budgets inside the
  pool are workable for IR but tiny for FX/commodities. A direct 6-factor equal-risk re-solve was attempted but my
  solver was unreliable, so no quantitative claim is made about the size of this distortion.
- **M2 as coded is not "risk parity adjusted by the factor model".** `factor_scaling` ignores Stage-1 budgets
  (docstring: global ERC gives pool factors near-zero shares) and uses `pool_sleeve_budgets`; it produces a
  commodity-risk book. The older RP-budget x signal design (`scalar_to_coeff`, `rebuild_asset_weights`) still
  exists in code but was replaced by signed sleeves (2026-09-26).
- **M2 on RP budgets ~ M1 on Sharpe and return (1.95 vs 2.04, 2.54% vs 2.63%) but smoother**: drawdown -1.9% vs
  -2.7%, worst year +1.0% vs +0.2%. The factor model adds drawdown protection, not return/Sharpe, because RP gives
  FX/commodities (where the models earn) only ~5-8% of capital.
- Unlevered return is bounded by the carry of what the book holds (~2.5%). More return needs either more
  commodity/FX risk (Sharpe falls; see 6.4 combos) or higher-yielding assets (credit) - untested under RP budgets
  (P3).

**Is the factor model worse than pure risk parity? No - not distinguishable (tested 2026-10-17).** M2 (signals on RP
budgets) vs M1 (pure RP), 2017-2026, unlevered, price + carry:
- Daily return difference -0.09%/yr, t-stat -0.21 (indistinguishable from zero). 6-month windows (n=25): M2 beats M1
  on Sharpe in 13, on return in 12; median dSharpe +0.16, median dReturn -0.14pt.
- By year M2 wins 2017 (+2.6pt), 2020 (+1.5), 2022 (+0.25) and loses 2021 (-1.75), 2023 (-1.9), 2024 (-1.3); the
  pattern is consistent with the signals sometimes standing aside in strong bond-rally years (cost of carry), not
  verified.
- Daily P&L correlation 0.43 -> a plain 50/50 mix of the two is better than either: Sharpe 2.36, ann 2.58%, maxDD
  -1.67%, worst year +1.17%, 16/25 windows vs M1 (median +0.39). Return is not improved, risk is lower.
- "M2 as coded" (Sharpe 1.01) is a different sizing rule, not a test of the signals.

### 6.6 CORRECTION (2026-10-17): the 6.3-6.5 comparisons used the wrong Sharpe basis

Sections 6.3-6.5 ranked books on **price + carry, risk-free 0, no funding charge**. That basis credits a long-bond
book (Pure Risk Parity: ~90% CN bonds, ~2% carry) with carry but never charges the cost of financing it, so it
flatters Pure RP (Sharpe 2.04). The app's headline KPI is **Sharpe (post-funding)** (`_figures.py`), which subtracts
the book's actual repo funding cost. Same pool/dates (2017-01-02..2026-10-13), the app's own metrics:

| Book | Sharpe post-funding | Sharpe price-only | Sharpe total (rf 2%) | CAGR | Funding | Max DD |
|---|---|---|---|---|---|---|
| Pure Risk Parity | 0.84 | 0.87 | 0.32 | 2.4% | 1.4%/yr | -2.5% |
| Factor scaling as coded | 1.01 | 0.93 | 0.64 | 4.75% | 0.4%/yr | -6.2% |
| Factor scaling on RP budgets | **1.25** | **1.13** | 0.42 | 2.5% | 1.0%/yr | -1.9% |

- The factor model is NOT worse than Pure RP and its signals are not useless: on every funding-aware measure and
  on price-only Sharpe, both factor-scaling variants rank at or above Pure RP; signed sleeves also avoid paying
  funding on idle bond notional (0.4-1.0%/yr vs 1.4%). Net of funding, CAGR is roughly RP 1.0%, factor scaling as
  coded 4.35%, factor scaling on RP budgets 1.5%.
- Superseded / to be redone on the post-funding basis: the "Pure RP is best (2.04)" claim, design C being
  "superseded", the RP-core + satellite combination table (6.4), and the 50/50 mix result (6.5). The earlier finding
  that the current factor-scaling sleeve rule makes a gold/aluminium-dominated risk profile (94% of P&L variance)
  stands - it is a risk-composition fact, independent of the Sharpe basis.
- Every Sharpe in this plan must name its basis (post-funding is the app headline; price-only is the Factor-tab
  basis). Do not use price + carry at rf = 0 to rank books with different bond exposure.

### 6.7 Sleeve-budget floors for non-IR factors (2026-10-17, app metrics, 2017-2026)

`pool_sleeve_budgets` (as coded) has no explicit floor but gives every non-IR factor an equal 1/n share, which acts
as a large implicit floor. Pure RP mode (Stage-2 `rebuild_asset_weights`) does have per-asset floors (commodity/FX
>= max(2%, 20% of equal share); bonds >= max(1%, 30%)) and caps; removing the commodity/FX floors LOWERS pure RP
(post-funding Sharpe 0.84 -> 0.71). Test: RP budgets for rates, minimum budget f for each of USDCNY/AU/AL
(f=0 is the RP-budget version; as coded for reference):

| Min budget f per non-IR sleeve | Sharpe post-funding | Sharpe price-only | CAGR | Funding | CAGR - funding | Max DD | Risk share R/F/C |
|---|---|---|---|---|---|---|---|
| 0% (RP budgets) | **1.25** | 1.13 | 2.50% | 1.02% | 1.48% | -1.9% | 53/12/35 |
| 3% | 0.83 | 0.77 | 2.72% | 0.86% | 1.86% | -3.7% | 9/7/84 |
| 6% | 0.84 | 0.78 | 3.22% | 0.72% | 2.51% | -4.8% | 4/6/90 |
| 10% | 0.89 | 0.83 | 3.78% | 0.58% | 3.20% | -5.4% | 2/6/93 |
| 16.7% | 0.96 | 0.88 | 4.49% | 0.40% | 4.09% | -6.3% | 1/5/94 |
| as coded (IR by sqrt(vol), 16.7% others) | 1.01 | 0.93 | 4.75% | 0.40% | 4.35% | -6.2% | 1/5/94 |

No intermediate floor improves both Sharpe and return: gold/aluminium vol is ~10-20x that of rate sleeves, so even
3% each takes commodity risk from 35% to 84% of the book. The family is a return-vs-Sharpe dial with the best Sharpe
at f=0 and the best return at the as-coded end; small floors are dominated. One in-sample period, no window sweep.

### 6.8 Credit factors in the portfolio (2026-10-17, app metrics, factor_scaling, unlevered)

Hypothesis: credit sleeves (CDB/LGB/MTN) lift return of the RP-budget book. **Not supported.** LGB and MTN factor data
start 2020-01-02 (all sources agree), so pools with them are tested on 2020-01-02..2026-10-13 (6.8y); CDB also on 2017+.
"as coded" = pool_sleeve_budgets; "RP" = Stage-1 budgets renormalised over the pool. Net = CAGR - funding.

| Pool (2020+) | as coded: Sharpe post-fund / CAGR / net / maxDD | RP budgets: Sharpe post-fund / CAGR / net / maxDD |
|---|---|---|
| Base 6 factors | 0.60 / 3.43% / 3.05% / -7.9% | **1.33** / 2.33% / 1.47% / -1.0% |
| + CDB (3) | 0.52 / 2.10% / 1.90% / -4.3% | 0.50 / 0.77% / 0.37% / -1.3% |
| + LGB (3) | 0.61 / 2.25% / 2.08% / -4.6% | 1.32 / 1.37% / 0.91% / -0.9% |
| + MTN (3) | 0.42 / 1.66% / 1.48% / -5.2% | 1.23 / 1.15% / 0.73% / -0.7% |
| + all 9 credit | 0.70 / 1.71% / 1.63% / -2.7% | **1.58** / 0.71% / 0.52% / -0.4% |
| + CDB, 2017+ | 0.87 / 2.71% / 2.53% / -3.8% | 1.13 / 1.02% / 0.68% / -1.2% |

- Credit lowers CAGR and net return in every case (dilution: credit sleeves take budget but earn little per unit of
  capital), even though their standalone factor Sharpe is 1.0-1.4. It adds smoothness: with RP budgets all-9 credit
  gives the best Sharpe (1.58) and drawdown (-0.4%) at the lowest return (0.5% net). CDB alone does not help.
- So credit is a diversifier, not a return source. Unlevered return in this book comes from the gold/aluminium
  (and FX) sleeves: 94% of P&L risk in the as-coded design. Improving those signals is the lever for return;
  the budget rule only moves the book along the Sharpe-vs-return dial (6.7).
- Single window, no window sweep; the 9-credit Sharpe is driven by credit being 49% of the risk of a very low-vol book.

