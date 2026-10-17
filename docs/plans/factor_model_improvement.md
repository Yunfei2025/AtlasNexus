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
