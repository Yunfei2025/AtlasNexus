# Affine Curve Model & Reference Bond Selection — Review and Improvement Plan

**Date:** 2026-07-03
**Scope:** `curves/affine/` (affine.py, curve.py, pricingYield.py, bootstrap.py),
`curves/calibration/selector.py`, and their use in `curves/generators/rates.py`,
`curves/refreshers/rates.py`, `curves/backtest/core.py`.
**Business goals:** (1) relative-value arbitrage between mispriced bonds with
similar tenors; (2) bid/ofr generation for potential market making.

---

## 1. What the model is (as implemented)

A 3-factor arbitrage-free Nelson-Siegel (AFNS) style affine term structure model:

- Loadings (`Model A`, `affine.py:366-369`) are exactly Nelson-Siegel:
  `B = [1, (1-e^-x)/x, (1-e^-x)/x - e^-x]` with `x = γτ` — level / slope / curvature.
- The intercept `a(τ) = Σ S2_ij · I_ij(γ,τ)` is the AFNS yield-adjustment
  (convexity) term, with `S2` a 3×3 factor covariance matrix.
- Decay `γ = 0.62` is a **fixed global constant** (`settings/general.py:35`),
  shared by TBond and CBond, never re-estimated.
- `S2` is calibrated by fixed-point iteration over a rolling window
  (`SIGMA_WINDOW_MONTHS = 3`): solve per-date factors by pseudo-inverse of the
  loading matrix against bootstrapped reference spots, take the sample
  covariance of the factor series, repeat (`calAffineCov`).
- Daily factors are extracted by OLS (optionally MAD-robust,
  `Curve.extractFactorsRobust`) against ~9 bootstrapped reference spot points.
- All bonds in the 1–10Y pricing band are repriced off the fitted curve
  (`Curve.affinePricing` → `pricingAffine`); the *residual* `ytm_act − ytm_quo`
  is the mispricing / on-off-the-run signal.

The design is sound for its purpose: a deliberately smooth 3-factor curve so
that idiosyncratic bond richness/cheapness shows up as residual. The findings
below are about making the residual a *clean* signal (RV) and a *fast, honest*
one (market making).

---

## 2. Review findings

### 2.1 Critical for RV signal quality

**F1. Compounding-convention mismatch between calibration and pricing.**
Three different conventions coexist in the round trip:

| Stage | Location | Convention |
|---|---|---|
| Bootstrap of reference spots | `bootstrap.py` (`(1+r)^-T`) | Annual compounding |
| Curve display / forwards | `curve.py:342-345` (`exp(-y·τ/100)`) | Continuous |
| Bond repricing | `pricingYield.py:316-319` (`(1+y/freq/100)^(τd/TS)`) | Compounded at the *bond's own coupon frequency* |

The affine factors are fitted to annually-compounded bootstrap spots, but
`pricingAffine` discounts each cashflow at `(1 + y/freq/100)^(-n)` where `freq`
is the bond's coupon frequency. Two bonds with identical maturity but different
coupon frequency (freq=1 vs freq=2) receive *different effective discount
factors from the same curve*. This manufactures a systematic,
coupon-frequency-dependent "mispricing" of several bp — exactly the kind of
false signal a similar-tenor RV strategy would trade on and bleed on. **This is
the single highest-impact fix.**

**Target convention — corrected 2026-08-05.** For coupon-bearing CNY rates
instruments, the target convention here should be the same one already used in
`pricingYield.py`: discount off the bond's own coupon frequency, not annual or
continuous compounding. The repo's plain bond pricer and `pricingAffine` both
already follow that logic via `1 / (1 + y/freq/100)` raised over the remaining
coupon periods. So the model-side repricing convention is the right target,
and the real defect sits in `bootstrap.py`, which solves reference zero/spot
yields under a flat `(1+r)^-T` with `freq` ignored. Those bootstrapped yields
are the affine calibration targets, so reference bonds with different coupon
frequencies are being normalized onto the wrong basis before factor extraction.

There is one short-end caveat: true discount / zero-coupon instruments are a
separate convention bucket. The current code already hints at that split —
`pricingYield.py` treats `f == 0` or names containing `贴现` as a two-date
schedule. So the Phase 1 fix should be: keep coupon-bearing instruments on the
existing freq-compounded YTM convention end-to-end, and handle genuine
discount instruments explicitly as their own short-end case rather than folding
them into the coupon-bearing bootstrap formula.

**F2. `S2` is the covariance of factor *levels*, not innovations.**
`calAffineCov` (`affine.py:125`) computes `np.cov(x_arr)` over the factor
*levels* in the window. The AFNS yield-adjustment term is a convexity
correction that depends on the *instantaneous* (diffusion) covariance — i.e.
the covariance of daily factor *changes*, annualized. Using level covariance
(a) grossly overstates the level factor's contribution because it is highly
persistent, and (b) makes `a(τ)` jump when the window's trend changes, moving
the whole fitted curve and every residual with it. Minimum fix: `np.cov(np.diff
(x_arr, axis=0)) × annualization`; better: estimate from an explicit VAR(1)/
Kalman step (see Plan P2).

**Why this fix matters — summary.** `a(τ)` is meant to be a small, smooth
convexity correction driven by how much the factors *jump day to day*, not by
how spread out their *levels* happen to be over a rolling window. Interest-rate
factors (especially the level factor) are highly persistent, so level variance
accumulates over a window and is typically much larger than the annualized
daily-innovation variance the AFNS formula actually calls for — on top of that,
the current code never annualizes at all. Left uncorrected, `a(τ)` is likely
overstated and shape-distorted (worst at long tenors, where the level-factor
loading grows with `τ²`), and it re-jumps whenever the window's trend shifts
rather than only when volatility genuinely changes. The fix won't visibly
change how well reference/anchor bonds are refit (least squares still solves
`x` to match them), but it should materially change the fitted curve's shape
away from anchors — which is exactly where the RV residual is computed — and
should make the curve/factors noticeably more stable day to day.

**F3. Convergence test compares determinants, and the regularized solver is
dead code.**
- `affine.py:126`: `S_err = |det(S2) − det(S2_new)|` — two very different
  matrices can share a determinant; the test is also scale-dependent. Use a
  relative Frobenius norm `‖S2_new − S2‖_F / ‖S2‖_F`.
- After 20 iterations without convergence the last iterate is used silently —
  no warning, no flag on the curve object.
- `_solve_regularized_factors` / `_solve_regularized_system`
  (`affine.py:33-74`) were written to stabilize near-rank-deficient solves but
  are **never called** — the loop uses a plain `np.linalg.pinv` batch
  (`affine.py:117,124`). Either wire them in or delete them (the methodology
  doc `docs/report/AtlasNexus_Model_Methodology.md` currently describes the
  regularized path as if it were live).

**F4. γ (decay) is a hard-coded constant.**
`GAMMA = 0.62` fixes the tenor where curvature loading peaks (~2.9Y with the
Model A parameterization). If the market's true hump sits elsewhere, the
3-factor fit leaves a *structured* residual across tenors that is
indistinguishable from mispricing. For similar-tenor RV this bias largely nets
out between neighbours but does not vanish; for buckets far from any reference
point (see F7) it dominates. Re-estimate γ periodically (monthly profile grid
search minimizing cross-sectional RMSE) rather than daily, to keep factor
series comparable.

**F5. `filter_bonds_by_term` can loop forever and silently un-buckets.**
`selector.py:53-61`: `while l == 0: max_term += 0.005`. If the candidate set is
empty (e.g. no CDB bond in the 0.3Y band that day), this loop never terminates
— there is no iteration cap and `min_term` is never relaxed. It also widens
only *upward*, so a "5Y" bucket can quietly capture a 6.5Y bond and overlap the
10Y bucket. Cap the widening (e.g. ±0.25y max), widen symmetrically, and return
empty with a warning when exhausted.

**F6. Reference switches are invisible to downstream signals.**
The sticky-selection logic (`selector.py:396-407`) is good — it prevents daily
turnover noise from flipping the reference. But when a reference *does* roll
(bond ages out of its bucket), the fitted curve jumps and every bond's residual
jumps with it. Nothing records the event, so z-scores computed on
`ytm_act − ytm_quo` history see a spurious level shift. Publish a
reference-change event series alongside `RefBond` and either reset or
mean-adjust residual histories at switch dates.

**F7. Tenor bucket gaps: no anchor between 6Y and 8.5Y.**
`TERM_BUCKETS` (`settings/fixed_income.py:96-101`) covers
{0.3, 0.5, 0.7, 1, 1.5, 2, 3, 5, 10} with ranges [4,6] and [8.5,10]. The 7Y
sector — a quoted benchmark tenor in the CNY market — has **no reference
point**; every 6–8.5Y bond's "mispricing" is mostly model interpolation error.
Also nothing beyond 10Y, so the 20/30Y ultra-long sector (where structural
rich/cheap is often largest) is out of scope. Add a 7Y bucket ([6.0, 8.0]) at
minimum; consider 15/20/30Y buckets as a separate long-end extension with its
own liquidity caveats.

**On the 7Y bucket's liquidity — is that a good reason to leave it out?**
Partly, but not on its own. `get_most_liquid_bond`/`filter_bonds_by_term`
already select *whichever* bond in a band has the highest turnover — if the 7Y
sector is thin, that selection can still land on a genuinely low-volume bond,
and anchoring the curve to a stale/thin quote is worse than not anchoring it
at all (it can inject noise and reference-switch instability, F6). That's a
real argument for caution, not for omission: 7Y CGB is a regularly auctioned,
quoted benchmark tenor, so the *sector* isn't illiquid, only sometimes the
day's cheapest-to-anchor bond is. The 2.5Y-wide unanchored gap this leaves
behind is the bigger, structural problem — it affects every bond in that band,
every day, regardless of that day's liquidity. Recommended approach: add the
7Y bucket but gate it on the same liquidity/staleness quality check proposed
for F9 (min turnover or max quote age) — use the bucket when a
liquid-enough candidate exists that day, and fall back to model interpolation
(today's behavior) only on the days it doesn't, rather than choosing between
"always anchor" and "never anchor."

### 2.2 Important for market-making use

**F8. Bid and Ofr curves are fitted independently — they can cross.**
`refreshers/rates.py` fits two full 3-factor curves, one from reference bids
and one from reference offers, then prices the whole universe off each. Because
each side is smoothed independently through ~9 noisy points, nothing guarantees
`ofr_curve(τ) ≥ bid_curve(τ)` at every tenor, and the model bid/ofr spread for
a given bond is an artifact of *reference-bond* spreads, not of that bond's own
liquidity. For quoting: fit **one mid curve** (mid = average of filtered
bid/ofr reference YTMs), then apply a *spread model* — half-spread as a
function of tenor, bond liquidity tier, and inventory skew — with a floor
guaranteeing non-crossing. The existing staleness filter
(`_stale_reference_info`, REF_BID_OFR_MAX_BP) is a good foundation and should
feed the spread model (wide/absent ref quotes ⇒ wider quoted spread, not a
distorted curve).

**F9. CNBD valuations anchor the EOD curve for off-the-run references.**
Selection is by liquidity, but EOD spots come from `估价收益率:%(中债)` — a model
mark. For genuinely illiquid off-the-run refs the CNBD mark can lag the market
by days; the "fair" curve inherits that lag, and residuals against it partially
measure CNBD staleness. Where live/traded data exists (成交收益率, intraday
BondRT), prefer it with an age-based weight; record per-point quote age as a
diagnostic on the curve object.

**F10. Simplified schedules and day counts.**
- `pricingAffine` (`pricingYield.py:306`) assumes all remaining coupon periods
  have the same length as the *next* period (`taus_days = i·TS + dres`); real
  schedules are irregular after `getNextTradingDate` adjustment.
- `τ = days/365` everywhere; no ACT/ACT option. CFETS/CNBD accrued-interest
  conventions are not reproduced exactly.
- For 1–10Y RV in yield space these are second-order (<1bp mostly), but for
  quoting clean prices to counterparties they must match market convention
  exactly. Compute cashflow dates once from the actual schedule (already
  available in `schedule`) instead of the `i·TS + dres` approximation — cost is
  negligible since `calAB_np` is cached.

### 2.3 Code health

**F11. The Model A/B loading and integral formulas exist in three copies**
(`_calAB_analytic_cached`, the symbolic fallback in `calAB_analytic`, and
`_compute_IB_cached`). Any correction must be made three times. The sympy paths
appear to serve only "backward compatibility"; consolidate on the NumPy path
and delete the symbolic branches (callers already convert to float
immediately).

**F12. Assorted smaller items.**
- `selector.py:358`: `raise SystemExit(...)` on missing volume data — kills the
  host process from library code (and the EOD pipeline's step isolation is
  defeated). Raise a domain exception instead.
- `selector.py:369-372`: comment says "zero coupon bonds" but the filter keeps
  `每年付息次数 == 1` (annual coupon). Verify intent — if short discount bonds
  carry freq=0 in `Def`, this filter *excludes* them, contradicting the comment.
- Duplicate-reference protection (`selector.py:381-386`) only checks the
  immediately preceding bucket; with widened bands (F5) a bond can be selected
  in two non-adjacent buckets, and `BootstrapYieldCurve.instruments` is keyed
  by float maturity so the duplicate silently overwrites.
- `calculate_term` (`selector.py:31`) is dead code.
- `print(...)` progress output inside `calAffineCov` / `affinePricing` — route
  through the central logger.
- `Curve.fitting()` display-mode fallback (shrinking S2 when the fit is
  unstable, `curve.py:330-340`) is fine for dashboards but the instability flag
  should be surfaced on the artifact (`affine_unstable: true`) so trading
  logic can refuse to signal off a degraded curve.
- No unit tests cover: price→YTM→price round trip, calAB Model A vs Model B
  consistency, bootstrap vs pricing convention agreement (would have caught
  F1), or selector bucket edge cases (would have caught F5).

---

## 3. Improvement plan

Ordered so that each phase makes the residual signal cleaner before the next
layer consumes it. Phases 1–2 are prerequisites for trusting any backtest of
similar-tenor RV; Phase 4 is the market-making track and can proceed in
parallel after Phase 1.

### Phase 1 — Convention integrity & correctness (highest priority)

| # | Item | Files | Finding |
|---|------|-------|---------|
| 1.1 | Unify discounting around the repo's current CNY bond pricing convention: rewrite `bootstrap.py` so coupon-bearing instruments bootstrap zero/spot rates with the same bond-frequency compounding already used by `pricingYield.py` / `pricingAffine` (`(1 + r/freq)^(-freq·T)` in year terms, or the equivalent period-based formula). Keep genuine discount / zero-coupon short instruments as an explicit separate short-end case rather than forcing them through the coupon-bearing formula. Add a round-trip test: bootstrap a synthetic flat curve, reprice the input bonds, assert < 0.1bp error. | `bootstrap.py`, `pricingYield.py`, `tests/` | F1 |
| 1.2 | Use actual schedule dates in `pricingAffine` instead of `i·TS + dres`. | `pricingYield.py` | F10 |
| 1.3 | Fix `filter_bonds_by_term`: symmetric widening, iteration cap, empty-result warning; extend duplicate check to all previously selected buckets. | `selector.py` | F5, F12 |
| 1.4 | Replace `SystemExit` with a domain exception; resolve the zero-coupon filter comment/code mismatch. | `selector.py` | F12 |
| 1.5 | Convergence: Frobenius-norm criterion + non-convergence warning flag stored on `Curve`; wire in or delete `_solve_regularized_factors`. | `affine.py`, `curve.py` | F3 |
| 1.6 | Test suite: round-trip pricing, Model A/B loading regression values, selector bucket edge cases, bid≥ofr sanity on synthetic data. | `tests/` | F12 |

### Phase 2 — Model estimation quality

| # | Item | Files | Finding |
|---|------|-------|---------|
| 2.1 | Estimate `S2` from factor *innovations* (daily differences, annualized), not levels. Compare fitted curves before/after on history; document the level shift in `a(τ)`. | `affine.py` | F2 |
| 2.2 | Monthly γ re-estimation: profile grid search (e.g. γ ∈ [0.3, 1.2]) minimizing cross-sectional yield RMSE over the trailing window; persist γ per bond type in the curve artifact; keep it piecewise-constant between re-estimations to preserve factor comparability. | `affine.py`, `generators/rates.py`, `settings/general.py` | F4 |
| 2.3 | Optional weighted factor extraction: weight reference points by quote quality (live vs CNBD, bid-ofr width, volume) instead of the binary keep/drop of the MAD screen. | `curve.py`, `refreshers/rates.py` | F9 |
| 2.4 | Consolidate the three copies of the loading/integral formulas onto the NumPy path; remove sympy from the hot path and the public return types (keep a thin shim if pickled `Curve` objects require it). | `affine.py`, `curve.py`, `pricingYield.py` | F11 |

### Phase 3 — RV signal layer (the arbitrage product)

| # | Item | Files | Finding |
|---|------|-------|---------|
| 3.1 | Add a 7Y bucket ([6.0, 8.0]) gated on a liquidity/staleness quality check (reuse F9's turnover/quote-age concept) so a thin-volume day falls back to today's model-interpolation behavior instead of anchoring on a stale bond; re-run the curve backtest to confirm 6–8.5Y residuals tighten on the days it's active. | `settings/fixed_income.py`, `selector.py` | F7 |
| 3.2 | Reference-change event series in the `cvref` artifact; residual z-score engine resets/adjusts at switch dates. | `selector.py`, signal layer | F6 |
| 3.3 | Residual analytics per bond: rolling z-score of `ytm_act − ytm_quo`, mean-reversion half-life (AR(1) fit), and carry/rolldown from the fitted forward curve, so the tradeable signal is *residual net of carry, scaled by half-life*. | new module under `curves/calibration/` or `pairs/` | goal 1 |
| 3.4 | Cost-aware ranking: net expected P&L after bid-ofr crossing (from F8's spread model) and borrow cost (`BondConfig.BORROW_COST` — extend beyond 5Y/10Y). Pair construction: long cheap / short rich within a tenor neighbourhood, DV01-neutral via existing Greek1 hedge machinery (`calibration/hedge.py`). | signal layer | goal 1 |
| 3.5 | Long-end extension study: 15/20/30Y buckets with a dedicated liquidity/staleness regime — separate work item, off the critical path. | settings + selector | F7 |

### Phase 4 — Market-making track (parallel after Phase 1)

| # | Item | Files | Finding |
|---|------|-------|---------|
| 4.1 | Mid-curve fit: single factor extraction from filtered mid (average of stale-screened bid/ofr reference YTMs) replacing the two independent side fits. | `refreshers/rates.py` | F8 |
| 4.2 | Spread model: quoted half-spread = f(tenor, liquidity tier, ref-quote quality, staleness age) with a non-crossing floor; publish `bid = mid + h`, `ofr = mid − h` in yield terms. Start with a simple calibrated table by bucket, iterate later. | new module `curves/calibration/spread.py` | F8 |
| 4.3 | Quote-quality metadata on every curve artifact: per-reference-point source (live/CNBD), age, and the `affine_unstable` flag, so quoting logic can widen or pull quotes on degraded curves. | `curve.py`, `refreshers/rates.py`, artifacts | F9, F12 |
| 4.4 | Inventory/skew hook: accept a per-bond skew input (bp) applied on top of the spread model — mechanism only, policy comes later. | spread module | goal 2 |
| 4.5 | Exact CFETS/CNBD accrued-interest and settlement conventions for the quoted clean price (T+0/T+1 settlement date, ACT/ACT where applicable) — required before quotes go external. | `pricingYield.py` | F10 |

### Sequencing summary

```
Phase 1 (1–2 wks)  ──► Phase 2 (2–3 wks) ──► Phase 3 (RV product)
        └──────────────► Phase 4 (MM track, after 1.1/1.5)
```

Backtest gate: after each of Phases 1 and 2, re-run
`python main.py curve-backtest --btype TBond ...` and compare residual
distributions (mean |residual|, per-bucket bias, residual autocorrelation).
Phase 1 should *reduce cross-sectional bias by coupon frequency*; Phase 2
should *reduce day-to-day curve level jumps* (a-term stability). Only then are
Phase 3 backtests meaningful.

---

## 4. Explicit non-goals (for now)

- Full Kalman-filter AFNS estimation (measurement + transition). Worth
  revisiting after Phase 2 if innovation-based S2 still shows instability, but
  the cross-sectional OLS design is adequate for residual-RV at daily/intraday
  horizons and much easier to reason about.
- More than 3 factors. Adding a 4th factor would absorb the very mispricings
  the strategy trades; keep the curve deliberately stiff.
- Credit curves beyond CDB (other policy banks) — extension of
  `filter_bonds_by_type`, separate effort.


