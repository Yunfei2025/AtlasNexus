# Beta factor model — improvement log and next steps

Status: **living record.** Covers the walk-forward factor model in `multiasset/factor_model.py`
(IC-weighted linear model, 12-month train window, 1/5/20-day horizon ensemble). Written 2026-10-14
after a day of feature A/B tests; complements `docs/plans/beta_book_exposure_vs_capital.md`
(sizing / capital usage) and `docs/plans/portfolio_construction_beta_alpha.md`.

> **ACCOUNTING CHANGE 2026-10-17 (section 3.14, results in 3.15).** Carry, cash and funding are now accrued per CALENDAR
> day (previously about 68% of each year's carry was booked), cash earns FR007 on every CNY not deployed (buffer included) and
> on short-bond proceeds, and the headline "post-funding" Sharpe is now the excess over a cash benchmark ("Sharpe (vs cash)").
> **(2026-10-18: factor_scaling no longer screens factors monthly; results for pools larger than P06 in 3.15-3.17 are on the screened basis, see 3.20.)**
> **Every post-funding Sharpe, reported return, carry and capital-usage figure written before 2026-10-17 in sections 3.5-3.13 and
> 6.x is on the OLD basis (and sections 3.15 and earlier on the old CAPITAL rule, shorts counted in full; see 3.16) and not comparable with the new one; use the 3.15 table.** Price-only Sharpe and factor-level
> results are unaffected. Conclusions that survived the re-run are marked in 3.15.

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

### 3.8 FX of foreign bonds: explicit overlay (2026-10-17, user decision)

The base currency is CNY, so a foreign bond carries rates AND its currency (FXDL.<ccy>CNY = 1.0 x notional).
Design (option A): the optimizer sees both factors (unchanged `get_default_sensitivities`), the currency leg is
neutralised by a forward netted against the FX sleeve, and a currency view comes only from the FXDL sleeve.
- `multiasset/book/fx.py`: per currency `bond` (embedded), `hedge` (= -bond), `sleeve` (FXDL view, crosses split
  into two currencies), `net_forward` (= sleeve - bond, the one ticket) and `net_exposure` (= sleeve).
- Backtest: `BookPnL.fx_embedded` / `fx_hedge` book the embedded spot move and the hedge's offset (cancel exactly,
  so book totals are unchanged); `metrics['fx_overlay']` reports average notionals (% of capital) and the gross
  FX P&L being hedged. Portfolio tab: "FX Hedge Ticket" panel under the IRDL hedge.
- Hedge carry is already charged: the funding hurdle bills foreign notional at the foreign overnight rate (= CNY
  funding + forward points). Fix: SOFR/TONAR/ESTR start 2018-04/2020-01/2021-01 and were charged 0 before that;
  they are now backfilled with the 1Y government yield minus its first-year spread to the overnight rate.
  Cross-currency basis is still not modelled (no forward-point data).
- A/B, 2017-2026, post-funding Sharpe before -> after: P06 1.42 -> 1.42; +IRDL4 0.98 -> 1.00; +SC8 1.72 -> 1.72;
  +all12 1.70 -> 1.70; risk_parity P06 0.74 -> 0.74 (others within 0.01). The change is accounting/visibility, not alpha.
- Size of the hedged FX move (ann., % of capital): factor_scaling +IRDL4 0.03, +SC8 0.33, +all12 0.78;
  risk_parity +IRDL4 -0.94, +SC8 -1.28, +all12 -1.09. Unhedged, this would be a material, unrewarded return source.
  Average embedded notional per currency is 7-12% of capital (US 7-8, JP 11-12, UK 11, EU 9).

### 3.9 Negative IRDL.CN (net short duration overlay) - portfolio test (2026-10-17)

Question: does letting IRDL.CN go short (via TF/T/TS or pay-fixed swaps, no shorting cash bonds) lift portfolio Sharpe
and return? Test: rebuild IRDL.CN positions from the SAVED walk-forward predictions (`build_position_series`,
`long_only=False`; no retraining, so only the sizing step changes), feed them into `factor_scaling`, 2017-01-02..2026-10-13,
unlevered, post-funding Sharpe. Shorts are booked as short cash bonds (pay yield, earn FR007 through the funding
hurdle), which has the same economics as a pay-fixed swap without the swap-spread/futures basis. Scripts are session
scratch only. "Tenor floor" = `SHORT_END_LONG_ONLY_TENORS`. "Bull floor" = the existing 0.40 minimum position when 60d and
120d yield momentum are both negative.

| Variant | P06 Sharpe / ann ret / maxDD | P11 Sharpe / ann ret / maxDD |
|---|---|---|
| A current (IRDL long-only + bull floor, tenor floor ON) | 1.42 / 2.85% / -1.2% | 1.31 / 2.70% / -1.6% |
| B same, tenor floor OFF | 1.41 / 2.01% / -1.0% | 1.24 / 1.69% / -1.5% |
| C IRDL long-short, no bull floor, tenor floor OFF | 1.26 / 1.68% / -2.1% | 1.09 / 1.59% / -3.0% |
| D IRDL long-short + bull floor, tenor floor OFF | 1.48 / 2.02% / -1.0% | 1.32 / 1.70% / -1.5% |
| E IRDL long-short + bull floor, tenor floor ON | 1.45 / 2.89% / -1.2% | 1.36 / 2.75% / -1.6% |

- Negative IRDL is NOT a clear lever. Best case E vs A: +0.03 (P06) / +0.05 (P11) Sharpe, +0.04 / +0.05 pt return.
  Six-month windows (19): E beats A in 12/19 and 11/19, median delta +0.002 / +0.0003; D vs B 8/19 and 7/19, median -0.001.
  The means (+0.03 to +0.12) come from a few windows. This is inside the +-0.1-0.15 noise floor (section 3).
- Removing the bull floor (C) hurts: Sharpe -0.14 / -0.21, drawdown doubles. Model-driven shorts that fight a rally cost
  more than the shorts earn.
- The short side earned +0.0023 in IRDL.CN factor units over 279 short days, and 87% of it is 2017 (yields +93bp);
  2022 is the only other positive year; 2025 (yields +25bp, 60 short days) earned ~0. CN yields fell in most of the
  sample, so this test has very little bear-market data to judge the short side on.
- The tenor floor (A vs B) is the carry lever: ON adds ~0.9-1.0 pt of annual return at about the same Sharpe. Its
  cost is the short-end shorts that pay carry. Under an overlay those shorts would be swap/futures legs, so the real
  comparison is the plan's P2 (route the floored residual into TS/TF), not IRDL sign.
- Capital usage is 82-90% in every variant, not 95%: the binding constraint on carry is not the IRDL sign.
- Caveat: shorts here count toward gross capital (|notional|); an overlay would not, which would free capital for the
  carry book. Not tested.

#### 3.9b Foreign IRDL (US/DE/JP/UK) long-short (2026-10-17)

US yields rose ~107bp in 2026 (IRDL.US 3.94 -> 5.01; US10Y 4.18% -> 5.19%). Long-only IRDL.US lost 0.13% (factor units) YTD
at mean position 0.21; long-short turned short on only 50 days and made ~0. Same method as 3.9, tenor floor ON, post-funding:

| Pool | Long-only (current) | LS + bull floor | LS, no bull floor |
|---|---|---|---|
| P06 (reference, no foreign) | 1.42 | | |
| P06 + IRDL.US | 1.20 / 2.49% | 1.14 / 2.30% | **1.41** / 2.60% / DD -0.9% |
| P06 + IRDL.US/DE/JP/UK | 1.00 / 1.87% | 0.91 / 1.43% | **1.40** / 1.90% / DD -0.9% |

- Unlike CN, dropping the bull floor HELPS the foreign factors: six-month windows 13/19 (US, median +0.23) and 16/19
  (all four, median +0.47); better in 8/10 and 7/10 calendar years. Factor-level IRDL.US price Sharpe 0.18 -> 0.33.
- But it only repairs the dilution: foreign IRDL long-only took P06 from 1.42 to 1.00; long-short no-floor returns to ~1.40,
  i.e. no better than leaving the foreign IRDL out (return 1.9-2.6% vs 2.85%).
- 2026 YTD contribution is small: +0.10 pt (US) / +0.12 pt (all four) of capital vs long-only, because the sleeves are small and
  the model was short on few days. Direction right, size modest.
- Next check if pursued: an overlay leg with real swap/futures carry for the shorts, and the FX/hedge leg (section 3.8).

#### 3.9c Decision: IRDL is long-short everywhere, with a symmetric trend floor (2026-10-17, user)

User wants one universal rule (CN included, "we may face a similar environment"). All five IRDL factors replaced at once;
tenor floor ON; post-funding Sharpe / ann. return / max DD, 2017-2026, factor_scaling:

| Pool | Long-only (was) | LS no floor | LS bull floor | **LS symmetric floor** |
|---|---|---|---|---|
| P06 | 1.42 / 2.85% / -1.2% | 1.29 / 2.93% / -2.7% | 1.45 / 2.89% / -1.2% | **1.47** / 2.85% / -1.9% |
| P11 | 1.31 / 2.70% / -1.6% | 1.20 / 2.98% / -3.7% | 1.36 / 2.75% / -1.6% | **1.41** / 2.77% / -1.7% |
| P06 + IRDL US/DE/JP/UK | 1.00 / 1.87% / -1.0% | 1.01 / 1.54% / -1.6% | 0.96 / 1.49% / -1.2% | **1.47** / 1.18% / -0.7% |
| P11 + IRDL US/DE/JP/UK | 1.02 / 1.96% / -1.3% | 1.10 / 1.65% / -1.2% | 1.15 / 1.65% / -1.0% | **1.56** / 1.24% / -0.7% |

- Symmetric floor = best Sharpe in all four pools (+0.05, +0.10, +0.47, +0.54 vs long-only). No-floor long-short is worse on CN;
  the bull-only floor did not help the foreign factors; only the mirrored floor works for both.
- Robustness is weaker than the headline: six-month windows vs long-only 6/19 and 8/19 on CN-only pools (median -0.01), 12/19
  and 14/19 with the foreign factors (median +0.21 / +0.51); calendar years better 3-6 of 10. CN-only gain is within noise.
- Cost: with the foreign factors, annual return falls ~0.7 pt (1.87 -> 1.18%, 1.96 -> 1.24%) while drawdown halves. The floor
  is active on 73-75% of days, so the book is largely trend-following with the ML model setting size beyond +-0.4. Factor-level
  price Sharpe: IRDL.CN 0.96 -> 1.13, IRDL.US 0.18 -> 0.73.
- 2026 YTD (post-funding, % of capital): P06 0.36 -> 0.28, P06+IRDL4 0.23 -> 0.31, P11+IRDL4 0.42 -> 0.26: no 2026 benefit
  overall (CN yields fell ~17bp in 2026; the US sell-off was captured late).
- Implementation: `_LONG_ONLY_PREFIXES` is now empty; `apply_trend_floor` (factor_model.py) is shared by
  `run_factor_model_backtest` and the saved-model prediction path (`_rfbt_train_helpers.py`), which previously had NO floor
  while the backtest did. `FactorModelConfig.trend_floor_symmetric=False` restores the bull-only floor. Tests:
  `tests/test_irdl_long_short.py`.
- NOT done: the saved `factor-backtest.pkl` / models still hold long-only IRDL positions until the Factor-tab backtest is rerun
  (or the IRDL positions are rebuilt from the saved predictions). `scalar_to_coeff` still treats IRDL as long-only (legacy path,
  only the Risk Budget panel display and tests use it); the live sleeves use the raw position. Shorts are modelled as short
  cash bonds (pay yield, earn FR007 via the hurdle), i.e. swap-like without the basis.

### 3.10 Overlay instruments: futures vs FR007 swaps (2026-10-17)

How well each instrument tracks the CGB cash yield the beta book actually holds. Swap rate change (FR007 IRS, `database-px.pkl`
IRS, from 2022-02) regressed on the same-tenor CGB yield change; futures return regressed on -modDur*dy of the cash CGB (annuity
duration proxy, same method as `beta_book_short_end_futures_hedge.md` sec 6). 2022-03..2026-10, R2 / hedge ratio (beta):

| Tenor | Futures, monthly | FR007 swap, monthly | swap daily / weekly R2 |
|---|---|---|---|
| 1Y | none | 0.62 / 0.61 | 0.33 / 0.47 |
| 2Y | TS 0.71 / 0.84 (daily 0.49) | 0.64 / 0.82 | 0.48 / 0.55 |
| 3Y | none | 0.73 / 0.86 | 0.40 / 0.57 |
| 5Y | **TF 0.87 / 0.90** (daily 0.62, weekly 0.73) | 0.83 / 1.00 | 0.74 / 0.77 |
| 7Y | none | 0.54 / 0.88 | 0.03 / 0.24 |
| 10Y | **T 0.77 / 0.74** (daily 0.60) | 0.32 / 0.80 | 0.00 / 0.03 |
| 30Y | TL (data from 2023-04, not measured) | none | |

- TF and the 5Y swap are equivalent hedges of CGB 5Y (0.87 vs 0.83 is inside the noise of ~55 monthly points); TF is exchange-traded,
  margin-only, no clearing/CSA, history from 2015. At 10Y the futures are clearly better (swap 7Y/10Y daily R2 ~0 looks like stale quotes).
  Swaps only add 1Y and 3Y, which have no futures.
- Futures reference the CGB CTD, the swap references FR007: a swap hedge of CGB cash carries the swap-spread basis.
- Gaps: no margin-rate assumption (do not invent one), no CTD/conversion-factor data (duration is a proxy), the swap series is short.

### 3.11 Overlay instrument registry and margin (2026-10-17, user decisions)

- Done: the five IRDL.* position columns in `factor-backtest.pkl` were rebuilt from the saved predictions with the long-short
  symmetric-floor rule (old rule first reproduced the saved positions exactly, max diff 0.0; the other 39 factors and all
  predictions are byte-identical; backup kept in the session scratchpad). The Risk Budget panel now treats IRDL as directional
  (`scalar_to_coeff`: coefficient = signed position; a flat saved signal shows 0 exposure).
- Routing: China rates use futures/swaps; US/DE/JP/UK have no derivative data, so their shorts are short cash bonds
  (`hedge_route`). Futures DV01 = annuity-formula duration proxy (no CTD data).
- `multiasset/book/hedge_instruments.py` (definitions + sizing only): TS (2Y), TF (5Y), T (10Y), TL (30Y) futures, FR007 swaps
  only for the 1Y and 3Y gaps (no 5Y swap). `split_dv01` spreads a DV01 over the neighbouring available instruments by tenor
  (7Y -> 60% TF / 40% T), respecting data start dates (TS 2018-08, TL 2023-04, swaps 2022-02).
  CFFEX face values TS 2,000,000 and TF/T/TL 1,000,000 (confirmed by the user 2026-10-17).
- Margin 3% of |notional| counts as used capital: usage = cash gross + margin, capped at 95% (`capital_usage`, `cash_headroom`).
  At the latest CGB yields (2Y 1.26%, 5Y 1.39%, 10Y 1.65%) and 10bn capital: offsetting 2.5 MM/bp of DV01 needs 12.9bn TS
  (margin 3.9%), 5.3bn TF (1.6%), 2.8bn T (0.8%), or a 50/50 TF+T mix (4.0bn, margin 1.2%); at 5 MM/bp the TF+T mix costs 2.4%.
  Margin per unit DV01 is highest at the short end (low duration per notional), so prefer TF/T and use TS sparingly.
- The binding limit is variation margin, not initial margin: a 100bp rally costs a short hedge 2.5% (2.5 MM/bp) to 5% (5 MM/bp)
  of capital in daily cash settlement while the bond gains are unrealised. With a 5% buffer, margin + a 50bp stress is about
  1.0% of capital per MM/bp, i.e. a derivative DV01 cap of roughly 5 MM/bp per 10bn.
- Not yet built: futures/swap P&L leg (roll/basis and fixed-vs-FR007 carry), margin inside `weights_to_notional`, the bucketed
  DV01 solve, routing negative CN IRDL to the registry, and re-running the sweeps with these costs.

### 3.12 Futures / swap overlay in the backtest and P&L (2026-10-17)

Implemented: `multiasset/book/overlay.py::route_cn_shorts`, `RiskModelConfig.ROUTE_CN_SHORTS_TO_OVERLAY` (default True,
factor_scaling only). Negative CN-bond notional is traded with TS/TF/T/TL (+1Y/3Y FR007 swaps), DV01-matched with the annuity
duration proxy (yesterday's yield, like the cash sizing); foreign shorts stay short cash bonds. Differences from a short bond,
all modelled: (1) P&L is the instrument's own series (futures: contracts x face x dF/100 on the back-adjusted continuous
contract, so roll and basis are inside; swap: notional x [(rate - FR007)/365 - modDur x d rate], negative = pay fixed);
(2) no bond carry and no repo credit, and the funding hurdle is not applied to overlay notional; (3) margin 3% of |notional|
is used capital (earns nothing) inside the 95% cap, and the DV01 scaling (`scale_sleeve_to_dv01_target`) and
`weights_to_notional` charge routed shorts at the margin rate only; (4) overlay legs have their own P&L columns, tx cost,
class 'Overlay' in the attribution and `metrics['duration_overlay']` (basis vs a short bond, margin, worst 20-day P&L).

A/B on the rebuilt long-short IRDL signals, 2017-2026, factor_scaling, post-funding Sharpe / ann. return / avg capital usage:

| Pool | X0 short bonds, floor ON (previous) | X1 overlay, floor ON | X2 short bonds, floor OFF | X3 overlay, floor OFF |
|---|---|---|---|---|
| P06 | 1.47 / 2.85% / 0.85 | 1.36 / 3.05% / 0.80 | 1.45 / 1.79% / 0.91 | 1.38 / 2.88% / 0.74 |
| P11 | 1.41 / 2.77% / 0.81 | 1.31 / 2.95% / 0.78 | 1.35 / 1.58% / 0.89 | 1.22 / 2.60% / 0.71 |
| P06 + IRDL4 | 1.22 / 1.16% / 0.94 | 1.16 / 1.19% / 0.94 | 1.18 / 0.78% / 0.95 | 1.07 / 1.08% / 0.93 |
| P11 + IRDL4 | 1.19 / 1.15% / 0.94 | 1.08 / 1.16% / 0.94 | 1.09 / 0.80% / 0.95 | 0.97 / 1.09% / 0.93 |

- LESSON: a first run that charged routed shorts full notional in the DV01 scaling left capital idle (usage 0.62) and showed
  X3 at Sharpe 1.69 / 1.61 / 1.42 / 1.31. That was an artifact of low deployment (less hurdle, less vol); with the freed
  capital deployed X3 is below X0 in every pool. Always read Sharpe together with capital usage.
- The overlay is a worse hedge than the bond it replaces: overlay P&L minus (short-bond P&L + repo credit) is -0.06 to -0.09
  pt/yr, and the daily P&L R2 versus the short bond is only 0.42-0.56 (the hedge carries 45% gross notional, margin 1.4%).
  Worst 20-day overlay P&L is -1.0% to -1.7% of capital (variation margin).
- Routing adds ~+0.2 pt gross return with the floor ON (more long carry and cash income from freed capital) but costs ~0.05-0.11
  Sharpe (basis noise, more deployed capital against the funding hurdle). Keep the short-end tenor floor ON even with the overlay.
- Capital usage is not the lever: CGB yield minus FR007 averaged 2Y +0.1/+0.4 (2017-21) but -0.17/-0.29 in 2025-26 (5Y
  -0.14/+0.02; 10Y +0.04/+0.29; only 30Y stays +0.3/+0.8). Deploying more into the short/mid curve earns ~nothing over funding now.
- Not done: the live Portfolio tab still shows CN shorts as signed bond DV01 (no futures ticket); the 3x3 bucketed solve is a
  simple tenor split; backtest allocation tables still show pre-routing signed CN notional.

### 3.13 Revised CN short routing: short bonds for 5Y+, swaps for 1Y/2Y (2026-10-17, user)

User: 5Y/10Y/30Y bonds are easy to short; use swaps for 1Y/2Y. Default is now `RiskModelConfig.CN_SHORT_ROUTING`
(1Y -> SWAP1Y, 2Y -> SWAP2Y, 5Y/10Y/20Y/30Y -> short cash bond; ordered preference lists, so swap tenors fall back to the
short bond before the swap history starts, 2022-02-28; futures can be selected per tenor). Only 1Y/2Y shorts cost margin in
the cap; `SHORT_BOND_BORROW_COST_BP` (default 0, not yet specified by the user) charges a fee on short cash bonds, since the
backtest otherwise credits a short bond with repo and no borrow cost, which flatters bond shorting (so 3.12's "overlay worse
than a short bond" is conditional on that). Post-funding Sharpe / ann. return / usage, factor_scaling, long-short IRDL:

| 2017-2026 | R0 bonds, floor 1/2/5Y | R1 bonds, no floor | R2 swaps 1-2Y, no floor | R3 swaps, floor 5Y only |
|---|---|---|---|---|
| P06 | **1.47** / **2.85%** / 0.85 | 1.45 / 1.79% / 0.91 | 1.38 / 1.94% / 0.86 | 1.33 / 1.99% / 0.86 |
| P11 | **1.41** / **2.77%** / 0.81 | 1.35 / 1.58% / 0.89 | 1.28 / 1.74% / 0.84 | 1.24 / 1.78% / 0.84 |
| P06 + IRDL4 | **1.22** / **1.16%** / 0.94 | 1.18 / 0.78% / 0.95 | 1.22 / 0.91% / 0.94 | 1.20 / 0.94% / 0.94 |
| P11 + IRDL4 | **1.19** / **1.15%** / 0.94 | 1.09 / 0.80% / 0.95 | 1.12 / 0.92% / 0.94 | 1.09 / 0.93% / 0.94 |

On the window where swaps exist throughout (2022-03 .. 2026-10), P06 / P06+IRDL4: R0 0.98 / 1.34 (ret 2.04% / 1.36%),
R1 0.97 / 1.06 (1.37% / 0.87%), R2 0.91 / 1.19 (1.74% / 1.19%), R3 0.91 / 1.21 (1.83% / 1.24%).
- The short-end floor is the dominant effect: dropping the 1Y/2Y/5Y short legs adds ~1.0 pt of return and keeps Sharpe highest,
  whichever instrument would have carried those shorts. Swaps recover only 0.15 pt (full sample) to 0.3-0.4 pt (swap window)
  of the ~1 pt the short legs cost, i.e. routing is useful only if the floor is removed. With the floor on (production), no
  1Y/2Y/5Y shorts exist and the routing is inert.
- A 1Y/2Y swap behaves like the short bond in expectation (overlay minus short-bond P&L 0.00 to +0.03 pt/yr in the swap
  window; pay-fixed carry (swap - FR007) is ~0 because FR007 ~ the 1Y/2Y swap rate) but tracks it with daily R2 of only
  0.50-0.55, which lowers price-only Sharpe in CN-only pools (0.96 -> 0.80) and helps once foreign IRDL shorts are in.
- A 20bp borrow fee on short bonds lowers Sharpe 0.01-0.04 in CN-only pools and 0.07-0.11 with foreign IRDL (more short
  bonds); it does not change the ranking.

#### 3.13b Decision and borrow fee (2026-10-17, user)

Decision: keep SHORT BONDS with the short-end floor ON (1Y/2Y/5Y), the highest Sharpe and return in every pool; the swap routing
stays in the code but is inert while the floor is on. Borrow fee on short cash bonds (`SHORT_BOND_BORROW_COST_BP`, per market and
tenor): CN 10Y 40bp, CN 30Y 100bp; unlisted tenors (CN 20Y, floored 1Y/2Y/5Y, all foreign markets) are 0. The fee is netted into
the cash/financing P&L line (`funding.short_bond_borrow_cost_daily`; `metrics['borrow_cost']` reports it per asset).

Production config (short bonds, floor on, long-short IRDL), 2017-2026, post-funding Sharpe / ann. return, no fee -> with fee:
P06 1.470 / 2.85% -> 1.455 / 2.83%; P11 1.411 / 2.77% -> 1.398 / 2.76%; P06+IRDL4 1.219 / 1.16% -> 1.210 / 1.16%;
P11+IRDL4 1.195 / 1.15% -> 1.185 / 1.14%. Fee cost 0.006-0.025 pt/yr: P06 averages 4.5% of capital short in CN10Y (0.012 pt/yr)
and 1.9% in CN30Y (0.013 pt/yr); CN20Y averages 2.0% short and is unpriced (a 70bp midpoint would add ~0.014 pt/yr).

#### 3.13c CN 20Y shorts are held as 30Y shorts (2026-10-17, user)

CN 20Y is illiquid to short, so `RiskModelConfig.CN_SHORT_SUBSTITUTE = {20.0: 30.0}`: the NEGATIVE 20Y notional moves to CN30Y,
scaled by modDur20 / modDur30 (about 0.7x the notional; yesterday's yields) so the DV01 is preserved, netting against any 30Y long
(`overlay.substitute_shorts`, applied before routing and P&L; longs untouched; factor_scaling only). The moved short takes the 30Y
borrow fee (100bp). Production config (short bonds, floor on, fee table), 2017-2026, post-funding Sharpe / ann. return,
20Y short held (unpriced) -> substituted: P06 1.455 / 2.83% -> 1.471 / 2.86%; P11 1.398 / 2.76% -> 1.408 / 2.78%;
P06+IRDL4 1.210 / 1.16% -> 1.218 / 1.17%; P11+IRDL4 1.185 / 1.14% -> 1.186 / 1.15%. No cost despite the fee: the 30Y short
averages 3.3% of capital in P06 (was 1.9%) and the total fee rises from 0.025 to 0.035 pt/yr.

### 3.14 DONE 2026-10-17 (results in 3.15): carry accrual and Sharpe basis ("P0b"; NOT the section 6.2 P0, which was return attribution and is done)

Two accounting defects in the book metrics, both reproduced with the real functions on 2026-10-17. They bias every comparison in
this document, so fixing them comes before further tuning of capital usage, floors or overlays.

**Defect 1 - carry, cash and funding are accrued per trading-day row.** `calculate_daily_returns_series` books `yield/100/365` on
each ROW of a business-day series, so a Monday row (3 calendar days) earns one day. Measured: CN10Y 2019/2021/2023 booked carry
2.169/2.075/1.866% against average yields of 3.179/3.029/2.724% - ratio 0.682/0.685/0.685 = rows/365. About 31.5% of every year's carry
never reaches the P&L. `cash_return_daily` and `book_funding_cost_daily` use the same /365-per-row convention, and `compute_metrics`
then annualises the hurdle as `mean * 252`, so cash and funding are scaled by the same ~0.69 (a consistent error in the Sharpe, a
level error in reported return and carry attribution).

**Defect 2 - the post-funding Sharpe numerator is not an excess over cash.** P&L includes FR007 on UNDEPLOYED capital
(`cash_return_daily`), while the hurdle charges FR007 only on DEPLOYED notional. Test with bond yield == FR007 == 2.0%, zero price
risk (true excess = 0 at any deployment); numerator = Ann. Return - Ann. Funding Cost:

| deployed | Ann. return | Ann. funding | numerator (should be 0) |
|---|---|---|---|
| 0% | 1.318% | 0.000% | 1.318% |
| 50% | 1.319% | 0.689% | 0.630% |
| 95% | 1.320% | 1.309% | 0.011% |

An idle book is credited with the risk-free rate as "excess", and each deployed CNY pays FR007 twice (lost cash interest plus the
hurdle). Under-deployment is therefore rewarded: this is the mechanism behind the 1.69 -> 1.38 "artifact" in 3.12 (capital usage 0.62),
not just lower volatility. Shorts have the mirror problem (counted in abs gross, so they also lose cash interest, and their
proceeds earn nothing in P&L while the hurdle credits repo).

**Fix (proposed).**
1. Accrue by calendar days: carry, cash, borrow fee and funding for a row = rate/100/365 x (calendar days since the previous row;
   first row = 1). Apply in `calculate_daily_returns_series` (bond, credit, FX-rate carry), `cash_return_daily`,
   `book_funding_cost_daily`, `short_bond_borrow_cost_daily`, the swap carry in the overlay. The hurdle annualisation in
   `compute_metrics` (mean x 252) is correct once each row carries its calendar days, so it is unchanged. Factor-level (price-only)
   code is untouched. Booked carry rises x 1.466 (365/249).
2. Define the post-funding numerator as excess over a cash benchmark: P&L (including cash interest) minus FR007 x benchmark capital
   (decision below) minus the foreign hedge carry (foreign notional x (foreign overnight rate - FR007), as now), so a book that earns
   exactly FR007 on everything scores 0 at any deployment. Decide the short-proceeds treatment at the same time (credit repo on short
   notional in P&L and charge only margin/haircut in capital, or keep abs-gross and drop the hurdle credit).
3. Keep `Sharpe (gross)` and price-only Sharpe unchanged for comparability; add the new basis as the app KPI.

**Decisions needed from the user:** (a) benchmark capital: total capital, or 95% x capital (the 5% buffer idle)? (b) short proceeds:
earn FR007 in P&L with a margin-only capital charge, or stay abs-gross? (c) OK that all documented baselines are re-run and replaced.

**Tests:** (1) a 252-row business-day series accrues yield x (calendar days)/365 per year for bond, cash and funding; (2) the
y == FR007 synthetic above gives numerator 0 +- 1e-6 at 0/50/95% deployment, long and short; (3) golden check that price-only Sharpe,
turnover and attribution price/class shares are unchanged; (4) foreign hedge carry unchanged in sign and scale.

**Then re-run:** ERC vs legacy (6.11/6.12), IRDL long-short rule (3.9c), floor ON/OFF and swap routing (3.13), overlay A/B (3.12), FX
overlay (3.8). Expect higher carry-driven returns, a larger cost for short-end shorts (their negative carry scales up 1.47x), and
possibly different floor/overlay rankings.

### 3.15 Baselines re-run under the corrected accounting (2026-10-17)

Implemented per 3.14 (user decisions: benchmark = total capital, the buffer is cash and earns FR007; short-bond proceeds earn FR007
in P&L while the cap still counts shorts at full notional; replace all baselines). `calendar_gap_days` (data.py) accrues bond, FX
and FX-cross carry, `cash_return_daily` (cash incl. buffer, bond-short proceeds, derivative margin earns nothing),
`benchmark_hurdle_daily` (FR007 x capital + foreign notional x (foreign rate - FR007)), borrow fee and swap carry. The hurdle is
divided by PREVIOUS-DAY NAV (`hurdle_rate_on_nav`), the same base `compute_portfolio_metrics` uses for returns.
Tests: `tests/test_book_funding.py` (a book earning exactly the cash rate scores 0 +- 0.05% excess at 0/50/95% deployment, long and
short; foreign hedged excess = yield - foreign short rate; the same on a compounding NAV). KPI panel: "Sharpe (vs cash)",
"Cash Benchmark". The dirty-price point (user): the 95% cap is untouched; the buffer needs only about the accrued interest (roughly
half a coupon on average), so a cap of about 98% would suffice when no derivatives are used. Not changed.

**LESSON (bug found the same day):** the first re-run divided the hurdle by INITIAL capital while returns are NAV.pct_change(). NAV
compounds (~+12% over the sample) so the hurdle was too large by ~hurdle x NAV growth (~0.3 pt/yr at a 2.3% cash rate), which cut
every Sharpe by ~0.2 and hit books with a bigger hurdle (foreign shorts) hardest. It made long-short IRDL look worse in the foreign
pools (-0.04/-0.11) when it is better (+0.24/+0.17). The old hurdle was small enough to hide the mismatch. Staged diagnosis for
P06+IRDL4 (long-short vs long-only Sharpe): old accounting +0.23; calendar accrual only +0.07 (1.18 vs 1.11 on the NAV base);
full new accounting, correct base +0.24. Any future hurdle must be a rate on the same base as the returns it is subtracted from.

Production = long-short IRDL with symmetric floor, short bonds, short-end floor 1/2/5Y, borrow fees, 20Y->30Y substitution, ERC
budgets. Sharpe (vs cash) / ann. return % / max DD %, 2017-01-02..2026-10-13, factor_scaling, unlevered:

| Config | P06 | P11 | P14 | P17 | P06+IRDL4 | P11+IRDL4 |
|---|---|---|---|---|---|---|
| **E1 production** | 1.17 / 3.55 / -1.6 | 1.08 / 3.45 / -1.5 | 1.08 / 3.49 / -1.4 | 0.66 / 2.95 / -1.6 | 1.04 / 2.99 / -0.6 | 1.00 / 2.93 / -0.6 |
| E2 IRDL long-only (old rule) | 1.17 / 3.44 / -1.1 | 1.02 / 3.29 / -1.5 | 1.04 / 3.37 / -1.3 | 0.75 / 2.98 / -1.7 | 0.80 / 2.39 / -1.0 | 0.82 / 2.48 / -1.2 |
| E3 floor OFF (swaps 1-2Y) | 1.09 / 3.11 / -0.9 | 0.94 / 2.94 / -1.4 | 0.94 / 2.95 / -1.1 | 0.60 / 2.62 / -1.2 | 1.01 / 2.85 / -0.6 | 0.89 / 2.81 / -0.6 |
| E4 floor 5Y only (swaps) | 1.03 / 3.07 / -1.0 | 0.89 / 2.91 / -1.5 | 0.90 / 2.94 / -1.1 | 0.55 / 2.58 / -1.4 | 1.00 / 2.86 / -0.6 | 0.86 / 2.80 / -0.6 |
| E5 legacy sleeve budgets | 0.79 / 5.17 / -5.9 | 0.13 / 2.79 / -20.6 | 0.24 / 3.45 / -18.7 | 0.32 / 3.71 / -10.4 | 0.82 / 4.18 / -3.0 | 0.40 / 3.94 / -7.7 |
| E6 futures routing 10Y/30Y | 1.12 / 3.56 / -1.6 | 1.03 / 3.45 / -1.5 | 1.04 / 3.51 / -2.0 | 0.63 / 2.95 / -1.7 | 1.02 / 2.99 / -0.6 | 0.97 / 2.94 / -0.6 |

E1 detail: price-only Sharpe 1.42 / 1.32 / 1.32 / 0.98 / 1.32 / 1.29; capital usage 0.84 / 0.81 / 0.81 / 0.79 / 0.94 / 0.94;
cash benchmark 1.9% (2.3% with foreign shorts); P06 simple annual contributions: price 2.35, carry 1.10, cash 0.68, tx -0.03.

What the re-run shows:
- Levels. Reported return is higher (P06 2.85% -> 3.55%: carry is fully booked) and the headline Sharpe is lower (1.47 -> 1.17): it
  is now an excess over cash and no longer rewards idle capital. Compare only within the new basis.
- HOLDS: short-end floor ON is best in every pool (E1 > E3/E4 by 0.03-0.14); ERC beats the legacy budgets in 5 of 6 pools with a
  far smaller drawdown (exception P06+IRDL4: legacy 0.82 vs 1.04 is lower too, but earns 4.18% at a -3.0% drawdown vs 2.99% at
  -0.6%); short bonds beat futures routing by 0.01-0.05.
- HOLDS: long-short IRDL is noise for CN-only pools (P06 0.00, P11 +0.06, P14 +0.04, P17 -0.09) and a clear improvement once the
  foreign IRDL factors are in the pool (+0.24 and +0.17 Sharpe, +0.5-0.6 pt return, price-only Sharpe 1.32/1.29 vs 0.97/1.02): the
  short side removes the drag of long-only foreign duration in a rising-rate sample.
- Foreign IRDL legs: with long-only they dilute badly (P06 1.17 -> 0.80); with long-short they still do not add (1.04 vs 1.17 for
  P06 alone), they only stop being a drag. Return is lower (2.99% vs 3.55%) at a smaller drawdown.
- Absolute outcome: about 1.6 pt a year over cash at ~1.4% vol with a drawdown under 2%; most of reported return is the 1.9% cash rate.

### 3.16 Shorts consume no capital (2026-10-17, user) and the singularity question

Rule: `RiskModelConfig.SHORT_CAPITAL_RATE = 0`. The 95% cap limits LONG size only; a short uses no capital and longs and shorts are
never netted against each other. Derivative shorts still tie up margin. Applies in `weights_to_notional`, `scale_sleeve_to_dv01_target`
(the "negligible day" test now uses GROSS size, so a short-only day is still scaled to the DV01 target), the overlay cap
enforcement, `cash_return_daily` (non-bond shorts no longer use cash) and the capital-usage KPI. Rate 1.0 restores the old counting.
The binding limits become the 95% long cap and the GROSS DV01 cap (`MAX_DV01_PER_CAPITAL` = 5 MM/bp per 10bn); nothing else bounds
the short book. Default pool: foreign rate factors stay OUT (the default pool is CN IR + USDCNY + AU/AL).

Sharpe (vs cash) / ann. return % / max DD %  [avg long % / short % of capital, turnover], 2017-2026:

| Config | P06 | P11 | P14 | P17 | P06+IRDL4 | P11+IRDL4 |
|---|---|---|---|---|---|---|
| C2 shorts counted in full (previous) | 1.17 / 3.55 / -1.6 | 1.08 / 3.45 / -1.5 | 1.08 / 3.49 / -1.4 | 0.66 / 2.95 / -1.6 | 1.04 / 2.99 / -0.6 | 1.00 / 2.93 / -0.6 |
| **C1 shorts free (new default)** | 1.22 / 4.84 / -2.3 [73/30, 42x] | 1.04 / 4.94 / -2.0 [71/29, 42x] | 0.99 / 4.13 / -4.0 [72/27, 40x] | 0.79 / 4.10 / -4.0 [73/32, 51x] | 0.97 / 3.54 / -1.4 [68/81, 120x] | 0.84 / 3.48 / -1.6 [69/81, 124x] |
| C3 shorts free, IRDL long-only | 1.05 / 4.08 / -3.0 | 0.99 / 3.95 / -2.6 | 0.39 / 5.20 / -9.6 [77/62, 229x] | 0.81 / 3.94 / -4.5 | 0.82 / 2.70 / -1.6 | -0.08 / 1.37 / -14.2 |
| C4 shorts free, floor OFF | 1.34 / 3.94 / -1.5 [66/53] | 1.08 / 3.63 / -1.7 | 1.09 / 3.70 / -1.5 | 0.83 / 3.63 / -2.2 | 0.92 / 3.38 / -1.4 | 0.81 / 3.34 / -1.4 |

- Freeing shorts mostly buys MORE RISK AND RETURN, not a better Sharpe: return +0.5 to +1.5 pt, Sharpe -0.16 to +0.13 (flat on
  average), drawdown larger (-2.0% to -4.0% in CN-only pools). The long book averages only ~73% of capital: the DV01 cap, not the
  95%, now binds on many days.
- Long-only IRDL with free shorts is unstable (P14 drawdown -9.6%, turnover 229x; P11+IRDL4 -14.2%): the sleeves go net long and the
  IRSL/IRCV short legs balloon. Long-short IRDL (C1) is what makes the free-short rule workable.
- OPEN: with shorts free the short-end floor no longer wins everywhere (C4 vs C1: P06 +0.12 Sharpe but -0.9 pt return, P14 +0.10,
  P11 +0.04, foreign pools -0.03 to -0.05). The floor decision (3.13b) was taken under the old capital rule and should be revisited.
- The short book is bounded only by the gross DV01 cap: 81% of capital short in the foreign-IRDL pools. Consider an explicit
  short-size cap if borrow capacity is finite.
- NOT updated: the live Portfolio tab (`apply_factor_scaling`) still renormalises weights by gross |weight| (shorts consume
  capital), so it disagrees with the backtest until changed.

**Singularity.** The only optimisation in `factor_scaling` is the pool-level ERC on the covariance of FACTOR returns
(`erc_sleeve_budgets`; it repairs tiny eigenvalues and falls back to the legacy rule if unusable). Position signs, long/short and
the capital rule never enter it: sleeve capital = ERC budget x position. Measured at every monthly rebalance 2017-2026 (12M EWMA,
lambda 0.94, effective sample ~32 observations): the ERC never fell back (0/118) in any pool. Correlation-matrix condition number
(scale-free), median / max: P06 8 / 39; P11 32 / 100; P06+IRDL4 13 / 69; P14 and P17 304-352 / 3.7k-4.9k (driven by one pair, IF/IH: median EWMA correlation 0.95; IF/IC 0.86, IC/IH 0.72, see 3.20); P17 plus every foreign IR factor (29 factors) 757 / 10.9k. The raw covariance condition numbers (1e5-5e7) are
unit differences between slope and commodity variances, not collinearity. What WOULD be singular: long and short legs of the same
factor as separate assets (rank 6 of 12 for P06; condition ~1e302), or a sign-free asset-level risk parity. The code does neither;
the asset-level SLSQP risk parity (risk_parity mode, RP base) stays long-only. Caveat: ERC is parity at |position| = 1; with small
positions realised risk is not parity (a design property, not a numerical problem).

### 3.17 Short-size cap, floor revisited, Portfolio tab aligned (2026-10-17, user)

**Short-size cap.** `RiskModelConfig.SHORT_SIZE_MAX_RATIO = 1.0`: total |short| (every asset class, derivative notional included) may
not exceed the same 95% ceiling as the long book; long and short are capped independently and never netted. Enforced in
`weights_to_notional`, `scale_sleeve_to_dv01_target` and the overlay cap check. With the cap the uncapped shorts-free book of 3.16
shrinks (P06: 1.22 / 4.84% -> 1.29 / 3.95%, drawdown -2.3% -> -1.6%).

**Floor revisited under the new capital rule** (short bonds 5Y+, swaps 1Y/2Y when shorts are allowed, ERC, long-short IRDL, fees;
Sharpe vs cash / ann. return % / max DD %; 6-month windows vs the current floor):

| Variant | P06 | P11 | P14 | P17 | P06+IRDL4 |
|---|---|---|---|---|---|
| **F0 floor 1/2/5Y (current)** | 1.29 / 3.95 / -1.6 | 1.20 / 3.85 / -1.6 | 1.17 / 3.88 / -1.8 | 0.82 / 3.37 / -1.7 | 1.10 / 3.30 / -0.6 |
| F1 no floor, swaps 1-2Y | 1.26 / 3.41 / -0.9 | 1.10 / 3.25 / -1.3 | 1.14 / 3.30 / -1.2 | 0.82 / 2.96 / -1.6 | 1.07 / 3.09 / -0.6 |
| F2 floor 5Y only | 1.20 / 3.37 / -0.9 | 1.03 / 3.20 / -1.3 | 1.09 / 3.27 / -1.2 | 0.79 / 2.95 / -1.6 | 1.05 / 3.09 / -0.6 |
| F3 floor 1/2Y only (5Y shorts allowed) | 1.39 / 3.93 / -1.6 | 1.32 / 3.88 / -1.5 | 1.21 / 3.81 / -1.2 | 0.84 / 3.31 / -1.8 | 1.14 / 3.29 / -0.6 |
| F4 no floor, all short bonds | 1.28 / 3.43 / -0.9 | 1.11 / 3.26 / -1.3 | 1.16 / 3.32 / -1.2 | 0.85 / 2.99 / -1.6 | 1.08 / 3.10 / -0.6 |

- Dropping the floor (F1/F2/F4) does not beat F0: Sharpe equal or lower, return ~0.5 pt lower; windows 8-12 of 19 with negative means
  (P11 F1: 10/19, median +0.13 but mean -0.18). The "floor OFF is better" signal of 3.16 came from the uncapped book and does not survive.
- F3 (floor only 1Y/2Y, allow 5Y shorts) is higher in all five pools (+0.02 to +0.12 Sharpe at equal return) but its windows are a
  coin flip (8-9 of 19, medians ~0): unproven. DECISION: keep floor 1/2/5Y, short bonds for 10Y/30Y (20Y -> 30Y), swaps unused.

**Portfolio tab (factor_scaling) now follows the backtest rules:** floor 1/2/5Y; 20Y shorts held as DV01-equivalent 30Y shorts
(`signed_sleeve_weights_snapshot`); the signed shape is sized with `scale_sleeve_to_dv01_target` (DV01 target, 95% long ceiling,
95% short ceiling, up or down); DV01 is GROSS (the old cap summed signed DV01, netting shorts against longs); lots round toward
zero (`np.floor` made a short bigger); weights shown are the final sized capital; the TOTAL row is the LONG size and the status line
reports Long % / Short % / gross, long and short DV01; the FX hedge ticket uses the final sized capital. Other allocation modes
keep their weights (long-only) and are only scaled down to the DV01 limit. NOT changed: the Risk tab's beta tables still sum signed
capital (`web/tabs/risk/books/beta_table.py`), and the harness-checked default pool excludes foreign rate factors.

**Risk tab fixed (2026-10-17).** It assumed the beta book was always long. Now: the beta table shows a LONG total (capital used, with
the volume and the additive MtM of all positions) and a separate SHORT total (size, no capital), never netted
(`helpers.beta_long_short_totals`); trade tickets and the inventory use `beta_direction` (SELL for negative capital, was a hard-coded
BUY); MtM flips sign for a short; the sector inventory shows long / short per sector instead of a net. Net position by instrument and
the DV01 ladders stay NET by design (they are exposure views across books: a short 10Y does offset a long 10Y). Tests:
`tests/test_risk_tab_long_short.py`.

**MtM sign and gross view (2026-10-17, user).** Beta MtM is now `- direction x volume x duration x (close yield - open yield) / 10000`
(`helpers.beta_mtm_mm`): rates up, a long loses and a short gains (it was positive for a long when yields rose). The SCALE was
100x too small (volume in MM CNY, yields in percent: 1000 MM at duration 5 and a 10bp rise loses 1000 x 5 x 0.0001 x 10 = 5.0 MM,
the formula gave 0.05 MM) and was fixed to /100 on 2026-10-17 at the user's request.
Gross views added to the Risk subtab: a Net / Gross dropdown on "Position by Instrument" (long right, short left per instrument,
hover shows gross and net) and on the DV01 ladder (long DV01 stacks up, short down, label shows gross and net per tenor), both
respecting the Mixed / Beta / Alpha filter; the Total DV01 KPI reads "MM/bp net · gross X". The default stays Net.
Example (P06, 10bn, last saved signals): long 54.0%, short 5.2%, gross DV01 4.97 (long 4.57 / short 0.40) vs limit 5.0.

### 3.18 Consistency audit: backtest vs Portfolio tab vs the design (2026-10-17)

Checked rule by rule. **Backtest** (P06, P11, P14, 2017-2026, daily): long size <= 95% and short size <= 95% every day; gross DV01 <=
5.0 MM/bp (binding exactly on many days, zero violations); no shorts in CN1Y/2Y/5Y, none in CN20Y (held as 30Y); bond shorts only
in CN10Y/CN30Y, other shorts only in FX/commodity/equity. **Signals**: the saved IRDL positions follow the symmetric trend floor on
every date for all five markets (zero violations) and stay within [-1, 1]; the live snapshot scalars come from the same position
function; the default pool has no foreign rate factor. **Accounting**: calendar accrual, cash incl. buffer and short proceeds,
benchmark hurdle on previous-day NAV (tests in `tests/test_book_funding.py`).

**Live vs backtest on identical inputs** (same signals, same date): found and fixed four divergences.
1. **Duration basis.** The tab sized and reported DV01 with the default table durations (CN 30Y 17.0, 20Y 13.0, 10Y 8.5); the backtest
   prices and sizes with the annuity duration at current yields (21.8, 15.9, 9.0). The tab understated 30Y/20Y DV01 by 22%/18% and
   overstated US bonds by 17-24%, so its "5.0 MM/bp" cap was really ~6 on the backtest basis (P06: long 54.0% -> 43.7% once fixed).
   `live_mod_durations` now uses the annuity basis.
2. **Class caps.** `RiskModelConfig.CLASS_CAPS` (Rates 40% of the shape...) was applied in the live path only; the signed-sleeve
   backtest dropped it, yet the config comment still said the backtest uses it. CN1Y (tiny duration, big weight) was clipped, so the
   live book held 43.7% long where the backtest holds 82.8%. Caps now apply only to assets that keep a plain risk-parity weight.
3. **Missing assets.** The live commodity universe lacked Rebar (CMDL.RB) and Coking_Coal (CMDL.JM), which the backtest trades in P11+;
   their sleeves were silently dropped. Added. Soda_Ash, Live_Hog and European_Gas remain out (short history, excluded from every tested pool).
4. **Netting / counting** (3.16-3.17, earlier today): gross DV01, toward-zero rounding, long and short reported separately.

After the fixes the live book matches the backtest within lot rounding: P06 CN1Y 6,180 vs 6,192 MM, long 82.5% vs 82.8%, short
3.9% vs 4.0%; P11 Rebar 215 vs 215, Coking_Coal -128 vs -129, long 87.9% vs 88.2%, short 5.1% vs 5.2%, gross DV01 4.97.
Tools: `tests/test_live_backtest_consistency.py` (fast regression: live == backtest sizing, limits hold) and
`scripts/audit_design_conformance.py [P06 P11 P14]` (full daily audit; writes nothing to the input folder).

Known remaining differences (by design or out of scope; see 3.19 for the screen): the backtest budgets only a monthly screened subset of the pool
(P11 averages 9.6 of 11 factors, P14 10.3 of 14), while the live tab uses the pool the user selected (which the Candidates tab's
low-correlation screen normally produces); lot rounding; the backtest lags durations one day; in risk_parity / user_defined modes the
backtest applies no DV01 scaling while the tab only scales down to the DV01 limit; the Risk tab's net-by-instrument views stay net.

### 3.19 Should the live tab apply the backtest's monthly correlation screen? (2026-10-18) - no; drop it from the backtest instead

What the screen is: every month the factor_scaling backtest keeps only the factors that appear in the `top_pairs` (UI default 10, range
5-20) lowest-|correlation| pairs of factor changes (Pearson, 1Y window), and ONLY those get a sleeve. The live tab has no such step; its
pool is whatever the user selected, and the Factor tab's "add diversified assets to pool" button is a one-off, different screen (it first
forces one cheapest pair per asset class, then fills by lowest correlation). On current data the two screens agree almost completely
(P11 identical; P14 differ only on USDCNY).

A/B, 2017-2026, factor_scaling, Sharpe vs cash / ann. return / max DD (in-memory RP cache, nothing written to the shared cache):

| Pool | top_pairs 5 | top_pairs 10 (current) | top_pairs 20 | no screen (all pool factors) |
|---|---|---|---|---|
| P11 | | 1.20 / 3.85% / -1.6 | | **1.25** / 3.98% / -1.7 |
| P14 | 0.51 / 2.75% / -1.9 | 1.17 / 3.88% / -1.8 | 1.33 / 4.12% / -1.6 | **1.35** / 4.19% / -1.6 |

- Monotone: the stricter the screen, the worse. top_pairs=5 keeps ~6.9 of 14 factors and halves the Sharpe (0.51); top_pairs=20 keeps
  13; no screen is best. Six-month windows vs the current screen: no screen 11/19 (P11, median +0.13) and 11/19 (P14, median +0.06), better
  in 6/10 and 5/10 calendar years - not a significant win, but never worse; top_pairs=5 loses 15 of 19 windows (median -0.78).
- The screen is unstable: the screened set changes in 77% (P11) to 93% (P14) of months (Jaccard churn 0.12-0.22 at top_pairs=10, 0.42
  at 5); factors such as CU, ZN and the IF/IC/IH index futures are in only ~52-67% of months, and the core IRDL.CN is dropped in ~12% of
  months in P11.
- It is NOT a passive filter: it decides capital allocation. The monthly step (month-start rebalance dates, built up front and independent of
  the screen) recomputes the sleeve budgets, and the screen picks the factors that enter that ERC; a screened-out factor gets a ZERO budget
  that month and its share moves to the others. Measured on P14 (12M EWMA, monthly 2017-2026), screened vs ERC over all 14 pool factors:
  the screen re-assigns on average 16% of capital between sleeves each month (p90 45%); the budget turnover is 18.4% a month with the
  screen vs 5.0% without; and the core duration sleeve IRDL.CN has a zero budget in 25% of months (IRSL.CN 6%, IRCV.CN 8%, USDCNY 14%,
  the IF/IC/IH index futures ~43%, Cu 48%). Mean budgets: IRDL.CN 0.31 screened vs 0.39 unscreened, IRCV.CN 0.30 vs 0.24.
- Why the full-pool ERC is enough: it already handles correlated factors by letting them share one risk budget, so the diversification
  the screen is meant to buy comes from the covariance, without switching sleeves on and off.
RECOMMENDATION (implemented in 3.20): do not port the screen to the live tab; make factor_scaling use every factor of the pool in both places (the backtest
then equals the live tab by construction, and results stop depending on an arbitrary `top_pairs`). Practical bonus: with no screen the
factor_scaling backtest no longer needs the Stage-1 SLSQP solve (several minutes per new pool/date range) except for the rebalance-date
list and holdings display. The pure risk-parity mode keeps its screen (asset selection). Not implemented: needs your decision.
Side finding: `beta_rp_cache.pkl` keeps only the 5 most recent entries in TOTAL (`_prune_lru(max_versions=5)` over one family), so any
backtest run with new parameters can evict cached entries of other pools/dates (cost: recompute time).

### 3.20 Implemented: month-begin pool risk parity over ALL instruments, daily factor scaling (2026-10-18, user)

User statement of the design: for the selected portfolio the backtest includes every instrument of the pool, runs risk parity at month
start, and the factor model scales daily on top of it. The earlier code kept the original "correlation-based" strategy's monthly screen
(an inheritance from the old risk-parity-mode design; the comment even said "the pool's OWN screened factors"), so it deviated from this
and from the live tab. Done: `RiskModelConfig.FACTOR_SCALING_CORR_SCREEN = False` (default). In factor_scaling the orchestrator now builds
the month-begin pool directly from all pool factors, the sleeve ERC budgets (unchanged `pool_sleeve_budgets`, 12M EWMA window ending at
each month start) cover all of them, and the factor model scales the sleeves daily. Months with < 20 rows in the window are skipped as
before. There is no correlation screen and no Stage-1 solve (a full backtest drops from several minutes to 8-17 s), and the shared
`beta_rp_cache.pkl` is neither read nor written. `True` restores the legacy screen; the pure risk_parity mode always screens.
Tests: `tests/test_month_begin_pool_risk_parity.py` (all 11 factors budgeted every month; a guard raises if the RP cache is touched).

Production numbers under the new default (Sharpe vs cash / ann. return / max DD, 2017-2026; previous screened value in brackets):
P06 1.29 / 3.95% / -1.6 (unchanged); P11 1.25 / 3.98% / -1.7 (1.20 / 3.85%); P14 1.35 / 4.19% / -1.6 (1.17 / 3.88%);
P17 1.44 / 4.38% / -1.5 (0.82 / 3.37%); P06+IRDL4 1.21 / 3.35% / -0.6 (1.10 / 3.30%). The design audit
(`scripts/audit_design_conformance.py P06 P11 P14`) still passes. The tables in 3.15-3.17 for pools larger than P06 are on the
SCREENED basis and are superseded by these; P17 was hurt most by the screen. Side effect: factor_scaling runs no longer evict
entries of the 5-entry RP cache.

#### 3.20b Near-duplicate factor warning (diagnostic only)

Nothing is filtered: every pool factor gets a sleeve and the risk parity makes correlated factors share one risk budget. A warning is
raised when two pool factors have |correlation| >= `RiskModelConfig.COLLINEAR_WARN_CORR` (0.90) on the same annualised EWMA covariance the
allocation uses (`sizing.collinear_factor_pairs`). Backtest: a banner above the holdings table and `result['collinear_pairs']` list the pairs
flagged in at least half of the months (with the % of months and the last correlation). Live Portfolio tab: an info note in the status
line for the current window. Calibration on the 21 candidate factors, monthly 2017-2026 (12M EWMA, price-return space): only
EQDL.IF/EQDL.IH is a near-duplicate (median 0.95; >= 0.90 in 86% of months, >= 0.95 in 47%); EQDL.IF/EQDL.IC 0.86 (>= 0.90 in 25%);
CMDL.AU/CMDL.AG 0.76; EQDL.IC/EQDL.IH 0.72; every other pair is below 0.65. A 0.95 threshold would almost never fire, 0.90 flags IF/IH
and nothing spurious. Tests: `tests/test_collinear_pairs.py`.

### 3.21 P5 holdout check of the design decisions (2026-10-18)

Tool: `scripts/holdout_validation.py [--holdout-start 2025-04-01] [--since DATE] [--pools ...]`. For each decision it runs the full
2017-2026 backtest with the production rule and with the alternative, splits the daily excess-return stream (over the cash benchmark,
previous-NAV base) at the holdout start, and reports DEV (2017-01-02..2025-03-31) and HOLD (2025-04-01..2026-10-13, 18 months) Sharpe.
LIMIT: the holdout was visible when the decisions were taken (a SOFT holdout), and 18 months is short: the standard error of an
18-month Sharpe is ~0.8-1.1, so gaps of a few tenths cannot be told apart from noise.

Production, Sharpe vs cash: P06 DEV 1.39 -> HOLD 0.40 (excess 0.59%/yr, maxDD -1.1%); P11 1.36 -> 0.39 (0.60%/yr); P14 1.47 -> 0.16 (0.19%/yr);
P06+IRDL4 1.05 -> 1.78 (1.43%/yr, maxDD -0.2%). The CN-only books earned little over cash in the last 18 months; the book that includes the
foreign IRDL factors (long-short, rising US/EUR/JP/UK yields) had its best period. Production minus alternative, DEV / HOLD:

| Decision (production vs alternative) | P06 | P11 | P14 | P06+IRDL4 | Verdict |
|---|---|---|---|---|---|
| shorts free of capital vs counted in full | +0.11 / +0.25 | +0.13 / +0.27 | +0.14 / +0.36 | +0.03 / +0.17 | holds everywhere |
| ERC budgets vs legacy | +0.35 / -0.14 | +0.99 / +0.40 | +0.87 / +0.83 | +0.24 / +1.03 | holds in 3 of 4 (P06 HOLD slightly favours legacy) |
| short bonds vs futures for 10Y/30Y | -0.00 / +0.07 | +0.00 / +0.06 | +0.00 / +0.07 | -0.00 / +0.07 | tiny, same sign in HOLD |
| long-short vs long-only IRDL | +0.01 / -0.13 | +0.13 / -0.22 | +0.07 / -0.25 | +0.14 / +1.44 | CN-only: HOLD slightly against; with foreign IRDL: strongly for |
| floor 1/2/5Y vs none | +0.01 / -0.12 | +0.00 / -0.04 | +0.03 / -0.05 | +0.02 / +0.01 | no difference |
| floor 1/2/5Y vs 1/2Y only | -0.13 / +0.00 | -0.13 / -0.00 | -0.08 / -0.01 | -0.02 / +0.02 | no difference |
| no correlation screen vs screen (P11 only) | | +0.11 / -0.34 | | | not robust: HOLD favoured the screen |

Sign agreement between DEV and HOLD: 13 of 25 comparisons, i.e. coin-flip for the small decisions (floor variants, screen, futures, IRDL
long-only in CN pools: gaps <= ~0.25, inside the noise). Only the large effects carry information: shorts-free (all four pools, both periods),
ERC over legacy (3 of 4), and long-short IRDL once foreign factors are in the pool.

Reading: (1) the full-sample CN-only Sharpe of ~1.3 is mostly 2017-2024; the recent edge is thin (consistent with 6.12's "edge has thinned").
(2) Keep the robust decisions. (3) The floor, the screen and IRDL long-short in CN-only pools are UNPROVEN either way; none should be
re-litigated on this evidence. (4) The earlier choice to keep foreign IRDL OUT of the default pool rests on the full-sample result
(P06 1.29 vs P06+IRDL4 1.21); the holdout (0.40 vs 1.78) points the other way but is one 18-month rising-rate regime, so it is a
reason to re-test with a clean forward period, not to switch now.

Forward test: the production configuration is frozen at the commit that adds `scripts/holdout_validation.py` (branch
`beta-longshort-overlay-accounting`). The first clean out-of-sample day is 2026-10-14. After at least 6 months of new data run
`python scripts/holdout_validation.py --holdout-start 2026-10-14` (the HOLD columns are then genuinely fresh) before touching any rule above.
No decision may be justified by the 2025-04..2026-10 window alone.

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

### 6.9 Decision (2026-10-17, user): keep the as-coded sleeve budgets for now

Keep `pool_sleeve_budgets` (IR capital ∝ sqrt(vol), other sleeves equal capital). Rationale: the current commodity set is only
AU and AL, so an equal-risk solve has too little to balance and starves them (~1%); true risk-parity budgets are
expected to work once the pool is broader (more commodities, equity indices, more FX pairs). Credit stays out of the
default pool (lowers return; 6.8). Revisit: when the pool is broadened, re-run the as-coded vs RP-budget comparison
(6.7) on the app's post-funding Sharpe before switching. Near-term lever for return is signal quality on AU/AL/FX.

### 6.10 Broader pool: as coded vs RP budgets (2017-01-02..2026-10-13, app metrics, factor_scaling, unlevered)

Nested pools on top of the 3 CN rates + USDCNY + AU + AL base. Added: P09 +AG,CU,ZN; P11 +RB,JM; P14 +IF,IC,IH;
P17 +EURCNY,JPYCNY,GBPCNY. Excluded (data too short): SC 2018-03, SA 2019-12, IM 2022, LC/EC 2023. Standalone
Sharpe (2018+) of the additions is weak: AG 0.15, CU 0.12, ZN 0.11, RB 0.20, JM -0.14, IF 0.42, IC 0.05, IH -0.07,
EURCNY 0.21, JPYCNY 0.03, GBPCNY 0.47 (base: AU 0.43, AL 0.08, USDCNY 0.78). "RP" = Stage-1 budgets renormalised over the pool.

| Pool | As coded: Sharpe post-fund / net return / maxDD | RP budgets: Sharpe post-fund / net return / maxDD | Realised risk share (RP): rates/comm/eq/FX |
|---|---|---|---|
| P06 | 1.01 / 4.33% / -6.2% | **1.25** / 1.48% / -1.9% | 53 / 35 / - / 12 |
| P09 | 0.47 / 2.91% / -10.9% | **0.97** / 1.65% / -1.9% | 23 / 71 / - / 6 |
| P11 | 0.40 / 3.13% / -13.0% | **1.09** / 1.89% / -1.7% | 22 / 73 / - / 5 |
| P14 | 0.56 / 3.99% / -15.6% | **0.96** / 2.55% / -3.2% | 12 / 25 / 62 / 2 |
| P17 | 0.62 / 3.59% / -8.9% | **0.86** / 2.25% / -3.2% | 11 / 22 / 63 / 5 |

- Broadening with these (mostly weak) assets lowers the as-coded design's Sharpe (1.01 -> 0.40-0.62) and deepens drawdowns
  (-6% -> -9% to -16%): equal capital goes to sleeves with little edge, and risk concentrates in commodities/equities.
- RP budgets keep a higher Sharpe at every breadth and smaller drawdowns; their net return rises with breadth
  (1.48 -> 2.55%) while as-coded stays higher in return (the gap narrows from 2.9pt to ~1.3pt).
- **The RP-budget rule is not real risk parity**: realised P&L risk is 71-73% commodities (P09/P11) and 62-63%
  equities (P14/P17, three highly correlated index sleeves), not balanced. The budgets come from the global 48-factor
  Stage-1 ERC renormalised over the pool, not a pool-level ERC. Next: a pool-level ERC (EWMA covariance incl.
  correlations, IRSL/IRCV tied to level by sqrt(vol)) and check realised risk balance before comparing again.

### 6.11 Pool-level equal-risk-contribution sleeve budgets - implemented (2026-10-17)

User decision: switch to real risk parity. `multiasset/book/sizing.py::erc_sleeve_budgets` (damped-Newton ERC on the
pool's own EWMA covariance, correlations included; IRSL/IRCV tied to IRDL, and CRSL/CRCV to CRDL, by sqrt(vol) so an
IR/credit group is ONE risk unit). `pool_sleeve_budgets(factors, vol_map, cov=None)` uses it when
`RiskModelConfig.SLEEVE_BUDGET_RULE == 'erc'` (new default) and a usable covariance is passed; otherwise the legacy
rule ('sqrt_vol_equal') applies. Wired into the backtest orchestrator and the live Portfolio tab
(`compute_factor_cov` in `web/tabs/beta/data.py`) so both use the same rule. The factor model (training, signals,
positions) is unchanged; only each sleeve's capital share changes. Tests in `tests/test_signed_sleeves.py`.

App metrics, 2017-2026, factor_scaling, unlevered. Sharpe = post-funding; net = CAGR - funding:

| Pool | As coded (legacy) | Stage-1 RP budgets | **Pool-level ERC** | Realised risk share R/C/E/FX (ERC) |
|---|---|---|---|---|
| P06 (6) | 1.01 / 4.33% / -6.2% | 1.25 / 1.48% / -1.9% | **1.42** / 1.88% / -1.2% | 33 / 42 / - / 25 |
| P11 (11) | 0.40 / 3.13% / -13.0% | 1.09 / 1.89% / -1.7% | **1.30** / 1.89% / -1.8% | 29 / 49 / - / 22 |
| P14 (14) | 0.56 / 3.99% / -15.6% | 0.96 / 2.55% / -3.2% | **1.35** / 1.96% / -1.8% | 30 / 38 / 16 / 17 |
| P17 (17) | 0.62 / 3.59% / -8.9% | 0.86 / 2.25% / -3.2% | **1.19** / 1.66% / -1.8% | 25 / 32 / 15 / 28 |

- Realised risk is now spread across classes (equities 63% -> 15-16%, commodities 73% -> 32-49%), and Sharpe stays
  at 1.2-1.4 as the pool broadens, where the legacy rule collapsed to 0.4-0.6.
- Realised class shares are not exactly the ex-ante equal split (e.g. P14: rates 30% vs ~8% ex-ante for one unit of
  12) because sleeve P&L also depends on each factor's average position size; the balance is far better than before
  but not exact.
- Cost: net return 1.7-2.0% vs 3.1-4.3% for the legacy rule: the Sharpe-vs-return dial (6.7) moved to the Sharpe end.
  Unlevered return remains bounded by the book's carry plus the risk its sleeves can take.
- One 9.8-year window, no window sweep and no frozen holdout yet (P5). Pools exclude SC, SA, IM, LC, EC (short data).

### 6.12 Stability check of the ERC sleeve rule vs legacy (2026-10-17)

Daily post-funding streams (price + carry + cash - funding), 2017-01-02..2026-10-13, nested pools P06/P11/P14/P17. No
untouched data remains (the full history has been inspected many times), so stability is shown by sub-period, not a
true holdout; the ERC rule itself has no fitted parameters.

- Six-month windows (25): ERC beats legacy on Sharpe in 15/25 (P06), 18/25 (P11), 16/25 (P14), 17/25 (P17); median
  dSharpe +0.8 to +1.3. ERC is higher in both halves of the sample in every pool; it wins 6-8 of 10 calendar years;
  worst calendar year -1.5% or better vs legacy -3.7% to -9.3% (P06: +0.55% vs -0.44%).
- Return: legacy has the higher full-sample return (3.7-5.4% vs 1.9-2.3% a year) but the daily return difference is
  not significant (|t| <= 1.1; P06 t = -1.98).
- **Legacy's return advantage is a 2017-2020 effect.** Post-funding annual return / max drawdown, ERC vs legacy:

| Pool | 2017-2020 | 2021-2026 | 2023-2026 |
|---|---|---|---|
| P06 | 2.98% / -1.5% vs 7.97% / -5.9% | 1.76% / -1.4% vs 3.67% / -9.3% | 1.23% vs 3.52% |
| P11 | 3.10% / -1.9% vs 11.36% / -10.9% | 1.66% / -2.5% vs **-1.70%** / -19.8% | 1.19% vs 0.17% |
| P14 | 3.43% / -2.0% vs 16.07% / -8.8% | 1.58% / -2.5% vs **-3.02%** / -27.0% | 0.95% vs -0.66% |
| P17 | 2.30% / -1.9% vs 11.01% / -6.2% | 1.68% / -2.4% vs **-0.46%** / -13.1% | 0.86% vs -0.34% |

  In the broader pools legacy lost money after 2020 (drawdown -13% to -27%) while ERC kept earning ~1.6-1.7% a year with
  drawdown <= 2.5%. Only the 6-factor pool still earned more under legacy in 2021-2026 (3.67% vs 1.76%, at a -9.3% drawdown).
- Caveat: ERC's own edge has thinned - 2023-2026 Sharpe 0.6-0.85 and ~1% a year - so the book's signal quality, not its
  sizing, is now the binding constraint (plan P4).

### 6.13 Signal quality (P4): diagnostics and the ensemble test (2026-10-17)

"Signal" = the factor model's predicted return and the position derived from it (what scales each sleeve).

**Diagnostic (17 factors, saved factor-backtest.pkl, 5-day rank IC of predicted return vs outcome):** skill is thin but
stable - median IC 0.084 (2017-20), 0.074 (2021-26), 0.074 (2023-26); daily direction hit rate ~50-51%. The median
per-factor Sharpe fell 0.50 -> 0.09 (2021-26) -> 0.18 (2023-26), but it is a rotation, not a uniform decay: skill
fell in AU (IC 0.11 -> -0.03), JM (0.23 -> -0.03), RB (0.14 -> -0.06), IC index; it rose in USDCNY (Sharpe -0.08 -> 0.94),
IRSL.CN (0.42 -> 0.91), AG, AL. The ERC book leans on rates/FX, whose signals held up.

**Ensemble over training windows (9/12/18 months), averaged predictions through the model's own position logic - NOT
supported.** Predictions from different windows are only weakly correlated (median 0.43 between 9m and 18m), yet:

| | Median factor Sharpe | Mean factor Sharpe | Equal-risk 17-factor book (Sharpe / ann / maxDD) | Book 2021-26 |
|---|---|---|---|---|
| 12m model (current) | 0.24 | 0.31 | **1.31** / 4.06% / -5.1% | 0.88 |
| Ensemble 9/12/18 | 0.21 | 0.24 | 1.11 / 3.53% / -5.4% | 0.66 |
| 9m | 0.13 | 0.21 | 1.04 / 3.13% / -7.0% | 0.92 |
| 18m | 0.21 | 0.24 | 1.11 / 3.52% / -4.4% | 0.56 |

Ensemble beats the 12m model in 8/17 factors (mean dSharpe -0.07) and 193/405 = 48% of factor-windows; IC is unchanged
(0.062 -> 0.069). Caveat: 12 months was the historical default and may be favoured by earlier tuning on this same
history, so this is not proof that a 12m window is optimal - only that averaging windows does not improve it.
Window-averaging is dropped. Remaining ideas (untested): asset-specific information for the sleeves that lost skill
(e.g. gold: US real yields / USD), and sleeve inclusion by rolling edge.

### 6.14 Gold-specific drivers (2026-10-17) - no meaningful improvement

Diagnostic (rank IC vs gold forward return, 2017-20 / 2021-26): US10Y 252d z-score -0.10/-0.10 (5d), -0.18/-0.15 (20d);
US2Y 20d change -0.11/-0.06; SOFR-FR007 20d change -0.03/-0.09; US 2s10s 20d change +0.03/+0.11; gold/silver ratio z
+0.11/+0.04 (fading). No inflation-linked yields available, so "real yields" are proxied by nominal US yields. 13
candidates were screened, so some of this is luck.

Walk-forward A/B with a US-rates block (US10Y z252, US2Y chg20, SOFR-FR007 chg20, US 2s10s chg20) added to the features
(12m model, same config as the saved backtest), gold + silver, with aluminium/copper as controls:

| Factor | Sharpe 2017-26 base -> +US rates | 2021-26 | 2023-26 | IC5 2021-26 | Windows vs base |
|---|---|---|---|---|---|
| AU | 0.62 -> 0.65 | 0.10 -> 0.24 | 0.01 -> 0.22 | 0.006 -> 0.019 | 13/24, median +0.00 |
| AG | 0.05 -> 0.02 | 0.24 -> 0.21 | 0.24 -> 0.19 | 0.104 -> 0.111 | 12/23, +0.00 |
| AL (control) | 0.23 -> 0.28 | 0.08 -> 0.15 | 0.28 -> 0.36 | 0.069 -> 0.073 | 11/24, -0.00 |
| CU (control) | 0.20 -> 0.20 | -0.03 -> 0.01 | 0.26 -> 0.33 | 0.074 -> 0.078 | 17/25, +0.00 |

Median window deltas of zero mean the positions are mostly unchanged: the IC-based feature selection rarely picks the
new features within a 12-month window. Gold's recent Sharpe rises a little but its IC stays ~0, and the controls move
by similar amounts. Not adopted. Forcing the features in, or trading the yield signal as its own sleeve, would be a
new in-sample-discovered strategy and is not recommended without fresh data.

**Status of signal work:** six generic or asset-specific feature tests plus the window ensemble are null. The model's
edge is thin (IC ~0.07) and is not improved by more inputs of this kind.

### 6.15 Rolling-edge gating - skipped on evidence (2026-10-17)

Question: does a factor's recent edge predict its next edge? (If not, budget gating by recent edge cannot add value.)
17 factors, 12m model, month-ends 2017-07..2026-04; trailing 12m vs next 6m (no look-ahead: trailing IC only uses
forward returns realised before the decision date).

- Rank IC: pooled corr(trailing, next) = -0.06; cross-sectional (non-overlapping 6-monthly dates, n=18) mean -0.11,
  t = -1.94, positive in 7/18 - if anything mild reversal. Next-6m IC is HIGHER when trailing IC <= 0 (0.143, n=61) than
  when > 0 (0.118, n=233). Per-factor time-series correlations are mostly negative (13 of 17).
- Strategy Sharpe: pooled +0.04; cross-sectional mean +0.08, t = +1.27, positive in 12/18; next-6m Sharpe -0.04 after a
  negative trailing year vs +0.03 after a positive one - a tiny, insignificant tilt.

No usable persistence: gating by recent IC would cut factors just before they recover, and gating by recent Sharpe has
no reliable edge. Not built. This matches the within-factor ICIR gate already in `build_position_series` being the most
that recent-skill information can do.

