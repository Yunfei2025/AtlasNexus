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
