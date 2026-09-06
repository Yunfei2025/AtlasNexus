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

**Found 2026-09-05: `curve.py`'s `freq == 0` handling silently defeats
`pricingYield.py`'s own short-end branch.** Three call sites —
`Curve.affinePricing` (`curve.py:148-155`) and two more in `Curve.Pricing`
(`curve.py:200-211`, `:251-255`) — do this for a genuine zero-coupon bond:

```python
if freq == 0.:
    coup = 0.
    freq = round((365/(mate-mats).days), 0)   # fabricates a synthetic frequency
```

That mutated, nonzero `freq` is then passed into `yd.scheduleDate(mats, mate,
name, freq)`. `scheduleDate`'s own `if f == 0.0 or '贴现' in name:` check
(`pricingYield.py:36`) — the short-end two-date/simple-interest branch this
document already points to as the right target for discount instruments —
never fires, because `f` is no longer `0` by the time it gets there (unless
the bond's name happens to contain `贴现`). Instead the bond falls into the
periodic `FREQ_MAPPING` coupon-schedule builder with a fake, arbitrarily
chosen periodicity (e.g. a 6-month zero gets `freq≈2`, a 3-month zero gets
`freq≈4`), and is then discounted compound-periodically at that synthetic
frequency with `coup=0` in `pricing()`/`pricingAffine` — not the simple-
interest, actual-days convention the short end of the CNY market actually
uses (and not the annually-compounded convention a longer zero would use
either). This bug is independent of, and upstream of, the bootstrap
mismatch above: even after 1.1 fixes `bootstrap.py`, any zero-coupon
reference bond reaching `Curve.affinePricing`/`Curve.Pricing` would still be
priced under this fabricated frequency. Fix belongs in the same 1.1 item:
`curve.py` should leave `freq == 0` (or detect `贴现` in the name) and route
straight to the short-end two-date/simple-interest formula, never synthesize
a `freq` to force it through the periodic-coupon path.

**F14. Ex-coupon-day double-discounting produced ~130-470bp spot spikes
(FIXED 2026-09-05).** `pricing()`'s single-payment branch computed the
remaining period count as `nt = dres/TS + floor(dres/TS)`. For a bond in its
FINAL coupon period priced ON its coupon date, the schedule `ffill` lands
exactly on that coupon date, so `dres == TS` (the whole final period) and
`nt` became **2.0 instead of 1.0** — discounting the bond over two years
instead of one, understating the dirty price by roughly one coupon, and
making the bootstrap emit a roughly **doubled** 1y zero for that single day.
Fixed to `nt = dres / TS`, which is identical whenever `dres < TS` (every
non-ex-coupon case) and correct on the boundary.

Traced from a 44.5bp single-day fit blow-up (2026-05-15, `240010.IB`: 1Y spot
printed 2.5735% between neighbours at ~1.27%). **The market data was not at
fault** — the CNBD input yield that day was a perfectly smooth 1.175%; the
spike was manufactured entirely inside our own bootstrap. Scanning the full
961-day history found 8 such cells in 8,649 (0.09%), but **6 of 8 landed in
the 1Y bucket** — inside the traded 1-10Y range — with a worst case of
470bp, and all shared this signature (`ttm ≈ 1.000`, reference bond
unchanged across the spike). Effect on TBond 1-10Y anchor fit: despiking the
inputs was worth RMSE −29% and max error 104bp → 9bp; after the actual fix
the live curve improved 3.20 → **2.13bp** RMSE, max 6.92 → 4.84bp.

Note the existing `_suppress_model_jumps` guard protects `ytm_quo` (model
*output*); nothing validated `RefSpot` (model *input*) before fitting, which
is why a single corrupt anchor could propagate freely into the fit.

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
- `_solve_regularized_factors` / `_solve_regularized_system` were written to
  stabilize near-rank-deficient solves but were never called from the fit
  loop (plain `np.linalg.pinv` batch instead). **Confirmed 2026-09-05: no
  longer present in the codebase at all** (already removed before this pass),
  so no wire-in-or-delete action remains here — `docs/report/AtlasNexus_Model_Methodology.md`
  should still be checked and corrected if it describes the regularized path
  as live.

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

**A 7Y bucket existed before and was removed — separately, its retired data
was leaking into the live UI as a stale/frozen value.** `git log -p` on
`settings/fixed_income.py` shows `TERM_BUCKETS` briefly included
`7: [6.0, 8.5]` before being reverted to the current 9-bucket set with no
7Y (commit `0e81766`, message "update", no rationale recorded) — so today's
config genuinely has no 7Y anchor, matching this finding as written.
However, the Market Monitor → Curves reference-bond table (via
`web/tabs/market/data.py::_load_reference_bonds` reading
`{TBond,CBond}-cvref.pkl`) was still showing a `Term near 7Y` row with a
value frozen at the same number for months. Root cause, found and fixed
2026-09-05: `curves/utils/file.py::updatePKL`'s merge
(`new_df.combine_first(target_df)` then `.ffill()`) unions columns and
forward-fills, so once a bucket is removed from `TERM_BUCKETS`, its column
in `RefSpot`/`RefTerm` is never dropped — it just keeps getting silently
carried forward with its last real pre-removal value on every future
update, indistinguishable from live data in the UI. Confirmed **both**
TBond and CBond `cvref.pkl` also still carried stale `Term near 20Y` /
`Term near 30Y` columns from an even earlier, wider bucket set. Fixed in
`curves/calibration/selector.py::compute_spot_term_panels`: after each
`updatePKL` merge, `RefSpot`/`RefTerm` are trimmed back to the columns
implied by the current `TERM_BUCKETS` (via `botr.columns`, already
correctly trimmed for `RefBond`), and the full on-disk dict (not just the
two trimmed frames) is rewritten so `Factors`/`ImpliedVol`/`Spot` are
preserved. One-off cleanup applied directly to the live
`{TBond,CBond}-cvref.pkl` the same day (originals backed up to
`*.pkl.bak-20260905`) so the UI stopped showing the stale rows immediately,
without waiting for the next natural refresh. See
`tests/test_stale_reference_bucket_columns.py`. This is a separate bug from
the "should a 7Y bucket exist" design question above — fixing the leak does
not itself re-add 7Y; that recommendation is unchanged.

**Evaluated 2026-09-05: does adding a 7Y anchor actually tighten the
fit?** Tested directly against real TBond data — selecting the day's most
liquid bond in [6.0, 8.0] as the 7Y point, both (a) an isolated 3-factor
shape fit at a single date (5 dates tested) and (b) the full production
model (`calAffineCov`'s fitted `S2` from a real 63-day trailing window, 4
windows tested) — comparing anchor-fit RMSE/MaxAbsErr with vs. without the
7Y point. **Result: negligible and inconsistently signed.** Isolated-shape
test: RMSE improved on 4/5 dates (mean −0.17bp) but MaxAbsErr worsened on
4/5 dates (mean +0.02bp). Full-model test: RMSE improved on 2/4 windows,
MaxAbsErr improved on 1/4 (mean −0.06bp / −0.19bp respectively, but with a
lot of window-to-window sign-flipping). No test showed the curve becoming
systematically more distorted, nor meaningfully tighter — the effect size
in every test was at or below ~1bp, i.e. within the noise of this exercise.
**Revised recommendation: do not add a 7Y bucket now.** The one-point
addition doesn't meaningfully narrow the 6Y–8.5Y interpolation gap in a
3-factor smooth model (the gap is still mostly resolved by the neighboring
5Y/10Y points either way), while it does add a new point that can hit the
staleness gate (F9) and a new source of reference-switch instability (F6)
on days its cheapest-to-anchor bond changes — real, ongoing operational
cost for a benefit that measured as noise-level here. Item 3.1 below is
downgraded accordingly: not worth doing on its own; only reconsider
alongside F9's liquidity/staleness gate if the 6-8.5Y sector's interpolation
error becomes a documented problem in practice (e.g. via F6's
reference-switch event logging), not preemptively.

**F13. Coupon-driven yield dispersion at the short end (CGB, <1Y) makes the
reference-bond curve non-monotonic and unstable, independent of the F1
compounding fix.**

Checked 2026-09-05 against real TBond data (`TBond-px.pkl` CBDirty, current
instrument defs), excluding discount bills (`freq==0`/`贴现`, a separate
convention bucket, see F1). At nearly every short-end tenor there are two
coupon "vintages" quoting far apart:

| bond | T (yrs) | coupon % | quoted YTM % |
|---|---|---|---|
| 240024 | 0.28 | 1.06 | 1.159 |
| 220002 | 0.38 | **2.37** | **1.017** |
| 260009 | 0.64 | 1.06 | 1.145 |
| 220007 | 0.61 | **2.48** | **0.987** |
| 240016 | 0.95 | 1.62 | 1.147 |
| 220016 | 0.89 | **2.50** | **1.057** |

High-coupon 2022/2023-vintage bonds price 9–16bp *lower* in quoted YTM than
low-coupon 2024–2026-vintage bonds of similar maturity, at every short-end
point checked. `filter_bonds_by_term`/`get_most_liquid_bond` (F5) can land on
either vintage almost at random by that day's turnover, so the reference curve
see-saws by tenor rather than moving smoothly — this is very likely the "no
monotonic upward trend" / "highly reverted or deviated at short end"
short-end instability observed in practice, and plausibly propagates into
long-end factor estimates too (the level/slope/curvature fit sees the
see-saw as false curvature).

*Is this a coupon tax-rebate effect?* Researched 2026-09-05 before designing
a fix, since a wrong causal model would bias the fix's structure:

- A direct check — solving for the after-tax YTM that would make a
  high-coupon and low-coupon bond agree, under a uniform coupon tax — predicts
  the **opposite sign** of what the data shows: taxing coupons should make a
  high-coupon bond's *pretax quoted* YTM *higher* than a low-coupon peer (a
  smaller share of its return survives the tax, so the market clears at a
  higher pretax number to compensate), not lower. This rules out a simple
  "marginal investor pays income tax on CGB coupons" story as the direct
  mechanism, at least under a uniform tax rate.
- The well-documented China rates-market tax effect ("隐含税率捐" / implied tax
  rate) is a **cross-issuer** phenomenon — CGB coupons are fully tax-exempt
  (VAT + income tax) while CDB/policy-bank bond coupons are VAT-exempt but
  income-tax-liable for many holders, producing a persistent CGB-vs-CDB yield
  gap (historically ~13-15%, up to ~23% implied tax rate) — not a same-issuer,
  same-maturity, coupon-level effect within CGB itself.
- The CGB literature attributes same-issuer high-coupon-vs-low-coupon gaps to
  **on-the-run/off-the-run liquidity and vintage effects** instead: newer
  (often lower-coupon, since coupons track the falling-rate cycle) bonds are
  more liquid; older high-coupon bonds trade thin and can sit rich or cheap
  until arbitraged back toward the same-maturity level. Lower-coupon bonds
  also mechanically carry higher duration/convexity at the same YTM, so the
  same dollar mispricing shows up as a *larger* YTM swing for the low-coupon
  bond — compounding the appearance of a coupon effect even with no tax
  mechanism at all.
- **New, dated structural break to track separately:** as of 2025-08-08, newly
  issued CGB/local-government/financial-bond coupons lose the VAT exemption
  going forward (bonds issued before that date keep it). This will split the
  CGB universe into a legacy tax-exempt cohort and a taxed new-issue cohort,
  which is a genuine, real tax effect worth its own diagnostic once enough
  post-8/8 issuance exists — separate from the pre-existing coupon-vintage
  puzzle above, and should not be conflated with it.

**Recommended fix — empirical, not a theoretical tax formula.** Since no
clean formula reproduces the observed sign/magnitude, fit the coupon
sensitivity from the day's own cross-section rather than assuming a
mechanism:

1. Each date, on the reference-bucket candidate set (or the full short-end
   universe), regress `ytm_i ≈ level(T_i) + β · coupon_i + ε_i` (or a simpler
   pairwise adjustment against the bucket's lowest-coupon/most-recent bond).
2. Bootstrap / fit the affine curve on the de-couponed `ytm_i − β · coupon_i`
   rather than the raw quoted YTM, so the curve threads a coupon-neutral
   level through the short end instead of see-sawing with whichever vintage
   is liquid that day.
3. Store `β` per date as a diagnostic time series. A real, slowly-varying
   liquidity/vintage (or post-2025-08-08 tax-status) effect should produce a
   stable/smooth `β`; a noisy `β` would instead indicate the regression is
   just absorbing reference-selection noise (F5) rather than a structural
   effect, and should be investigated before being trusted as a correction.

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
| 1.1 | Unify discounting around the repo's current CNY bond pricing convention: rewrite `bootstrap.py` so coupon-bearing instruments bootstrap zero/spot rates with the same bond-frequency compounding already used by `pricingYield.py` / `pricingAffine` (`(1 + r/freq)^(-freq·T)` in year terms, or the equivalent period-based formula). Keep genuine discount / zero-coupon short instruments as an explicit separate short-end case rather than forcing them through the coupon-bearing formula. Also fix `curve.py`'s `freq == 0` handling (`affinePricing` and both branches of `Pricing`), which currently fabricates a synthetic `freq` and defeats `scheduleDate`'s existing `f == 0` short-end branch — it should leave `freq == 0` (or detect `贴现`) and route straight to the simple-interest two-date formula instead. Add a round-trip test: bootstrap a synthetic flat curve, reprice the input bonds, assert < 0.1bp error; add a zero-coupon round-trip test too. | `bootstrap.py`, `pricingYield.py`, `curve.py`, `tests/` | F1 |
| 1.2 | Use actual schedule dates in `pricingAffine` instead of `i·TS + dres`. | `pricingYield.py` | F10 |
| 1.3 | Fix `filter_bonds_by_term`: symmetric widening, iteration cap, empty-result warning; extend duplicate check to all previously selected buckets. | `selector.py` | F5, F12 |
| 1.4 | Replace `SystemExit` with a domain exception; resolve the zero-coupon filter comment/code mismatch. | `selector.py` | F12 |
| 1.5 | Convergence: Frobenius-norm criterion + non-convergence warning flag stored on `Curve` (`_solve_regularized_factors` confirmed already removed — no action needed there). | `affine.py`, `curve.py` | F3 |
| 1.6 | Test suite: round-trip pricing, Model A/B loading regression values, selector bucket edge cases, bid≥ofr sanity on synthetic data. | `tests/` | F12 |
| 1.7 | **Implemented and ENABLED for TBond 2026-09-05.** Fit a per-date coupon-sensitivity term `β` from the reference cross-section and bootstrap/fit the curve on the de-couponed `ytm_i − β·coupon_i`. Config: `BondConfig.APPLY_COUPON_ADJUSTMENT = {'TBond': True, 'CBond': False}`, resolved via `selector.coupon_adjustment_enabled(bond_type)`; per-date `β` is persisted to `{bond_type}-cvref.pkl['CouponBeta']` as a monitorable diagnostic. **Why per asset class:** fitting β over the full 961-day history gives TBond 2024 −0.029 (sd .051), 2025 −0.055 (sd .077), 2026 −0.086 (sd .017, negative on 99% of days), but CBond ≈0 in every year (2026: +0.008, sd .013) despite comparable coupon dispersion — the effect is CGB-specific, matching the documented tax/liquidity vintage story, so enabling it for CDB would only add noise. β is exactly 0 before 2024 for both (coupons were homogeneous), so the adjustment self-disables over that history. **Measured effect on TBond 1-10Y anchor-fit RMSE:** 2025 3.48→1.49bp (−57%), 2026 YTD 5.22→4.40bp (−16%), last 120d 5.51→5.09bp (−8%). By band over 120d: 0.25-1Y 3.95→3.30, 1-3Y 6.86→6.12, but 3-10Y 1.37→2.51 — i.e. it is a *redistribution* that helps 1-3Y (where the coupon-vintage dispersion lives) at some cost to the already-tight long end, net positive across 1-10Y. **Deployment prerequisite:** the stored RefSpot/RefTerm history and curve objects must be rebuilt on the SAME convention — a mixed adjusted-anchors / unadjusted-history state measured WORSE (8.60bp) than either convention applied consistently. Backups: `{TBond,CBond}-cvref.pkl.bak-coupon-20260905`. | `selector.py`, `settings/fixed_income.py` | F13 |

### Phase 2 — Model estimation quality

| # | Item | Files | Finding |
|---|------|-------|---------|
| 2.1 | **Implemented 2026-09-05 as an opt-in only — NOT the default, per a real-data stability finding.** `calAffineCov` gained `use_innovations: bool = False` (default unchanged from before this item): when `True`, `S2_new = np.cov(np.diff(x_arr, axis=0)) * ANNUALIZATION_DAYS` (252 trading days) instead of `np.cov(x_arr)` on levels. **Validated against real production history** (`TBond-cvref.pkl`'s `RefTerm`/`RefSpot`, 961 daily obs, 9 buckets ≤10Y matching `BondConfig.TERM_BUCKETS`/`FIT_MAX_TTM`) as this evaluation explicitly asked for: tested 5 different 63-day (`SIGMA_WINDOW_MONTHS`) rolling windows. Result: the fixed-point loop (`S2 → x(S2) → S2(x) → ...`) **diverges to NaN/Inf in 4 of 5 windows** — innovation covariance is dominated by day-to-day noise in the 9-point cross-sectional inversion, and feeding that noisy estimate back through the same circular solve amplifies rather than damps, blowing up geometrically instead of converging. The one window that did converge still moved the fitted curve by **10–36bp across the term structure** (e.g. −36bp at 10Y, +27bp at 5Y vs. the level-based fit) — far too large for what should be a small, smooth convexity correction, and not something to trust without further work. **Conclusion: F2's theoretical premise is correct (levels are the wrong basis, and the old code never annualized at all), but this straightforward fix is not numerically safe in production as implemented.** Needs a stabilizing follow-up (e.g. shrinkage toward a diagonal target, decoupling S2 estimation from the x-solve iteration, or a damped/regularized update step) before `use_innovations=True` can become the default. Kept as an explicit, clearly-documented opt-in for research/comparison only. | `affine.py` | F2 |

**What "innovation" means here, for reference.** For a daily factor series `x_t`,
the innovation is the one-step change `Δx_t = x_t − x_{t-1}` — the part of
today's value not predictable from yesterday's. **Level covariance**
(`Cov(x_t, x_t)`, the original/reverted-to default) measures how spread out
the *raw values* are across the whole window — if the factor is trending
(e.g. rates drifting for two months), that trend alone inflates this number
even on days where nothing unusual happened. **Innovation covariance**
(`Cov(Δx_t, Δx_t)`, `use_innovations=True`) measures how spread out the
*day-to-day changes* are, stripping out the slow trend — this is the
quantity the AFNS convexity term `a(τ)` is actually supposed to be built
from (an Ito integral of the instantaneous/diffusion variance), not a
window's level dispersion. The two numbers are on different scales, which
is why the innovation estimate must be annualized (×~252 trading days) to
be comparable at all — the pre-2.1 code used level covariance and never
annualized anything, conflating "the market trended" with "yields are
volatile." That theoretical direction is correct; the problem found above is
purely that feeding a noisy 9-point innovation estimate back through the
same circular fixed-point solve is not numerically stable yet.
| 2.2 | **NOT RECOMMENDED as originally scoped — evaluated 2026-09-05, do not implement.** Original proposal: monthly γ re-estimation via profile grid search (γ ∈ [0.3, 1.2]) minimizing in-sample cross-sectional yield RMSE over the trailing (63-day) window. **Overfitting risk raised and confirmed against real TBond history** (`TBond-cvref.pkl`, 9 reference buckets, 4 simulated monthly windows): (1) the RMSE-minimizing γ pins against the grid's lower boundary (0.30) in 2 of 4 windows — a classic sign the "optimum" isn't a real interior optimum, the search just ran out of room; (2) the RMSE-vs-γ profile is very flat — in the most recent window, RMSE only ranges 0.057–0.084 across the entire grid, and the within-5%-of-optimal band spans γ≈0.40–0.60, nearly half the search range. With only 9 cross-sectional points already fitting 3 factors + `S2` from the same data, γ is a 4th free parameter the data cannot reliably identify — monthly re-optimization on in-sample RMSE would very likely chase whichever way that day's specific 9 points happened to lean, not a genuine shift in the market's curvature hump. **Decision: keep `GeneralConfig.GAMMA = 0.62` fixed; do not implement monthly γ re-calibration as scoped.** If revisited, it needs one or more of: a materially larger/denser reference set (this bug is a sample-size problem, not a methodology problem per se), a regularizing prior pulling γ toward its current value unless the data strongly disagrees, or an out-of-sample/cross-validated objective instead of in-sample RMSE (which will always prefer more flexibility) — these are prerequisites for a future attempt, not near-term follow-ups. | `affine.py`, `generators/rates.py`, `settings/general.py` | F4 |
| 2.3 | **Implemented 2026-09-05.** Optional weighted factor extraction: weight reference points by quote quality (live vs CNBD, bid-ofr width, volume) instead of the binary keep/drop of the MAD screen. `getAffineFactors` gained an optional `weights` param (standard WLS via row scaling; `None` reproduces the old unweighted fit exactly). `Curve.extractFactorsRobust` gained a matching `weights` param, applied to both the first-pass and post-MAD-screen refit (a downweighted point still counts in proportion to its weight; the binary MAD screen still fully drops genuine outliers on top). New `curve.quote_quality_weights(is_live, spread_bp, volume, ...)` maps live-vs-CNBD / bid-ofr spread / turnover into a bounded (min_weight, 1.0] weight per point, volume ranked (not raw-magnitude) to avoid one very liquid point dominating. Wired into `BondCurveRefresher._price_mid` (item 4.1) via new `_mid_ref_quality_weights`, sourcing live/CNBD + spread from `BondRT` and volume from `env['Def']['成交量']` (confirmed `BondRT` itself carries no volume column — only 买价收益率/卖价收益率/成交收益率, see `curves/utils/retrieve.py::_normalize_bondrt_frame`). The EOD generator's `extractFactorsRobust` call (`generators/rates.py`) is left unweighted — F9's live-vs-CNBD distinction is an intraday-refresh concept with no live BondRT signal at EOD. | `curve.py`, `refreshers/rates.py` | F9 |
| 2.4 | **Partially implemented 2026-09-05.** Deleted the dead SymPy analytic path (`_calAB_analytic_cached`, `calAB_analytic`, `calAB_matrix`, `intI`, and the now-unused `_matrix_to_tuple`/`_tuple_to_matrix` helpers) — confirmed zero external callers (`Affine()`, `getAffineFactors()`, `calAffineCov()` already used the NumPy path exclusively via `calAB_np`/`_compute_IB_cached`); any future formula correction now only needs to be made once. **Deliberately not done:** removing SymPy from the public return types (`calAffineCov`/`getAffineFactors` still return `sp.Matrix` for `Curve.S2`/`Curve.factors`, pickled to `-cvrt.obj` today) — that is a materially bigger, separate change (touches `curve.py`, `pricingYield.py`, every `isinstance(S2, sp.MatrixBase)` check, and needs a load-time shim for existing pickled `Curve` artifacts) that was explicitly deferred as its own follow-up rather than bundled into this pass. | `affine.py`, `curve.py`, `pricingYield.py` | F11 |

### Phase 3 — RV signal layer (the arbitrage product)

| # | Item | Files | Finding |
|---|------|-------|---------|
| 3.1 | **DOWNGRADED 2026-09-05 — do not implement preemptively.** Originally: add a 7Y bucket ([6.0, 8.0]) gated on a liquidity/staleness quality check (reuse F9's turnover/quote-age concept). Evaluated directly against real TBond data (single-date and 63-day rolling-window full-model tests, see F7 above): adding a well-chosen 7Y anchor moved anchor-fit RMSE/MaxAbsErr by ≤~1bp, inconsistently signed across dates/windows — no measurable, consistent improvement, and no measurable distortion either. Given the ongoing operational cost (a new point exposed to the staleness gate, F9, and a new source of reference-switch instability, F6, whenever its cheapest-to-anchor bond changes day to day) against a benefit that measured as noise, this is not worth doing on its own. Reconsider only if the 6–8.5Y interpolation gap shows up as a documented, material problem in practice (e.g. via F6's reference-switch event logging or an observed RV residual issue in that sector) — not as a standalone preemptive change. | `settings/fixed_income.py`, `selector.py` | F7 |
| 3.2 | **Implemented 2026-09-05.** Reference-change event series in the `cvref` artifact. `RefBondSelector.select_reference_bonds` now detects, per bucket, when the day's actually-selected bond differs from the previous actual selection (compared before ffill, so a gap day with no candidate never looks like two rolls) and records `{date, bucket, old_bond, new_bond}`. Persisted as a new `RefBondChange` key in `{bond_type}-cvref.pkl`, MultiIndex `(date, bucket)` so same-day rolls across multiple buckets don't collapse under a plain-date index; added `RefBondChange` to `curves/utils/file.py::_NO_FFILL_KEYS` since forward-filling an event log is meaningless. History-seeded: a roll on the very first date of a given run is still detected against the prior on-disk selection, not miscounted as a fresh bucket. Does not itself change any residual/z-score calculation — that consumption is item 3.3. | `selector.py`, `utils/file.py` | F6 |
| 3.3 | **Implemented 2026-09-05.** New module `curves/calibration/residual_stats.py::compute_residual_stats` (+ `compute_residual_stats_panel` for a bond universe). Per the 2026-09-05 clarification: fixed OU/AR(1)-fitted stationary mean as the fair-value anchor (only when ADF confirms stationarity; falls back to the fitted window's plain mean otherwise, matching `OU_calibrate`'s own fallback) + EWMA(`ZSCORE_EWM_VOL_SPAN`) volatility — not a fully rolling and not a fully static z-score. Also computes mean-reversion half-life (AR(1)) and rolldown (`spot(T) - spot(T-horizon)` off a `Curve.fitting()` forward-curve DataFrame; sign convention: positive = upward-sloping curve = carry-positive for a long). **Wires directly into item 3.2's event log:** accepts the `RefBondChange` table and a bucket name, and when a roll falls inside the residual history, restarts OU/half-life/EWMA-vol estimation strictly after the roll date instead of fitting across the discontinuity — verified on a synthetic roll (mean recovered to within 0.02 of the true post-roll level vs. a naive fit pulled toward the blended pre/post average). Deliberately NOT wired into the existing live `BondCurve` z-score in `curves/refreshers/alpha_snapshot.py` (which currently uses `Zscore = spread/ewm_vol` with an implicit mean of 0 and `roll_bp` hardcoded to 0.0) — that integration is a separate decision affecting a live production signal, left for a follow-up rather than silently changed here. 9 unit tests (OU-parameter recovery, roll-restart, rolldown sign/magnitude, panel wrapper). | `curves/calibration/residual_stats.py` (new) | goal 1 |
| 3.4 | **Partially implemented 2026-09-06** (pair construction done; cost-aware ranking still outstanding). Goal restated by the user: trade the OFR{k}-vs-OFR1 bond residual, long cheap / short expensive by z-score. Three defects found and fixed on production TBond data. **(a) Frozen bonds passed every filter.** `_adf_result` returned `stationary='YES'` with p=0.0 for a constant series, so dead instruments passed `statAnalysis_BC`'s `dropna(subset=['stationary'])` and their ~0 vol became the z-score divisor. 26 of 131 'live' TBond bonds had bit-identical residuals for 20+ days (one for 612), median |residual| 73.8bp vs 5.9bp for live bonds, producing a -44.8 z-score. Two independent upstream causes: `ytm_act` is written from a possibly-stale `InstrumentInfo` (the failure mode already documented at `retrieve.py::updateInstrumentDef`), and `ytm_quo` is absent from `_NO_FFILL_KEYS` so `updatePKL`'s unbounded `ffill()` carries the last model yield forward forever. Fixed: `_adf_result` now reports `'NO'`; new `_drop_stale_residual_bonds` gates on universe membership (valid 剩余期限) and a `MAX_FROZEN_OBS=5` trailing-freeze check. Drops exactly the 38 non-universe bonds, keeping all 93 live ones. **(b) Pair spreads ignored their own reference leg.** For episodes shorter than `MIN_EPISODE_ROWS` (~65% of them), `_episode_rows_to_pair_frames` fell back to `_bond_own_rank_history`, which pairs the OFRk bond against *whichever* bond was OFR1 on each date. The resulting series is independent of the pair's named OFR1, so all 160 pair rows collapsed onto one spread per leg-A: across 33 leg-A bonds appearing in multiple pairs, 0 varied by partner, and the stored value was just leg A's own bond-vs-curve residual. Fallback removed. **(c) Raw yields instead of residuals.** The pair used `y_k - y_1`, which retains the curve slope between two maturities — that moves with the curve and does not mean-revert. Now `pair(t) = (y_k - curve_k) - (y_1 - curve_1)` via `_load_residual_panel`/`_residual_pair_series`. Differencing residuals also cancels the affine model's common level bias, which is why no cross-sectional demeaning is applied for this signal: measured -7bp median residual drifting -1.9bp (2023) → -8.7bp (2026), too slow for a 252-day OU mean to track (fitted per-bond `mean` median +0.02bp against a -7.20bp residual median). Display and calibration series always fall back together so `spread` and `mean`/`vol` are never on mixed scales. A `MIN_ZSCORE_VOL=0.003` (0.3bp) floor guards the tighter pair vol. **Measured effect (TBond, 160 pairs):** stationary 9% → 47%; half-life fitted on 14 → 74 pairs (median 7.0d); max |z| 44.8 → 8.5; |z|>5 outliers 28/149 → 19/158; 26 pairs now pass a tradeable `stationary=YES & |z|>2` screen. All 160 pairs verified to equal `resid_k - resid_1` exactly. 9 new tests in `tests/test_otr_ofr_residual_pairs.py`. **Still outstanding:** DV01-neutral sizing off `hedge.py`'s Greek1 machinery, and cost-aware ranking (bid-ofr crossing from item 4.2's spread model + `BondConfig.BORROW_COST` extended beyond 5Y/10Y). | `stat.py`, `otr_ofr_rv.py`, tests | goal 1 |
| 3.5 | Long-end extension study: 15/20/30Y buckets with a dedicated liquidity/staleness regime — separate work item, off the critical path. | settings + selector | F7 |

### Phase 4 — Market-making track (parallel after Phase 1)

| # | Item | Files | Finding |
|---|------|-------|---------|
| 4.1 | **Implemented 2026-09-05.** Mid-curve fit: single factor extraction from filtered mid (average of stale-screened bid/ofr reference YTMs) replacing the two independent side fits. `BondCurveRefresher._price_one_side` (per-side fit + full-universe pricing) removed; new `_build_mid_ref_series`/`_price_mid` build one mid reference series (per bond: average of Bid/Ofr where both survive `_drop_stale_refs`, falling back to whichever single side survives) and fit/price once. `credit.py`'s separate `CreditSpreadRefresher._price_one_side` is untouched — out of scope, does not produce `CvBid`/`CvOfr`. | `refreshers/rates.py` | F8 |
| 4.2 | **Implemented 2026-09-05.** Spread model: quoted half-spread = f(tenor, liquidity tier, ref-quote quality, staleness age) with a `MIN_HALF_SPREAD_BP` non-crossing floor; publishes `bid = mid + h`, `ofr = mid − h` in yield terms via `apply_spread_to_mid`. Simple piecewise-linear tenor table (0.5Y-10Y knots) times a reference/off-reference liquidity-tier multiplier, times a stale-quote multiplier, plus age-based widening — calibrated by hand as a starting point per the doc's own "start simple, iterate later," not yet fit to historical quoted spreads. Wired into `BondCurveRefresher.run()` via `_quoted_bid_ofr_quotes`, which reproduces the `{'Bid': df, 'Ofr': df}` shape `statAdjust` expects so `CvBid`/`CvOfr` and all downstream consumers (`curves/refreshers/stat.py`'s `CurveYield = (CvBid+CvOfr)/2`) keep working unchanged, but now derived from one non-crossing mid instead of two independently-noisy curves. | new module `curves/calibration/spread.py` | F8 |
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

**Bootstrap audit (2026-09-05).** Since the bootstrap is the cornerstone of
everything downstream, it was audited end-to-end after the F14 fix. Clean:

- **Self-consistency** — repricing each reference bond by discounting its own
  cashflows on the bootstrapped zero curve reproduces the input dirty price to
  within **0.0023 price units (~0.02bp)** across all 9 buckets.
- **Insertion order** — results are identical for shuffled vs sorted input
  (`get_maturities()` sorts internally).
- **Incremental caching** — the `_last_calculated_maturity` fast path matches a
  full recompute exactly.
- **Coupon-date continuity** — after F14, sweeping a bond across its coupon
  date holds the implied zero flat at the input yield (no kink).
- **Extreme inputs** — par/deep-discount/high-premium bonds all solve to
  arithmetically correct zeros.

Two residual issues, both minor and NOT fixed (documented for completeness):

1. **Redemption-leg timing (~0.5bp).** The redemption is discounted at `ttm`
   (derived from the *unadjusted* maturity) while the actual payment falls 1-2
   days later after `getNextTradingDate` business-day adjustment. Measured on
   today's TBond set: 2 of 9 bonds affected, price error 0.003-0.007 units, i.e.
   **~0.5bp** of implied zero. Below the noise floor of everything else in this
   document, but it is a genuine convention inconsistency.
2. **`instruments` is keyed by float maturity `T`**, so two reference bonds
   with identical `ttm` silently overwrite (second wins). F5/1.3's duplicate
   guard prevents this upstream today; the collision remains latent if that
   guard is ever bypassed.

Also worth noting: coupons falling *before* the shortest bootstrapped node are
discounted by `np.interp`, which **clamps** (flat extrapolation) rather than
extrapolating or erroring — acceptable, but it means the very short end is
implicitly flat below the first anchor.

## 3b. Measured: what actually drives fit quality (2026-09-05)

Effort ranking for improving the spot-curve fit, by *measured* impact on
TBond 1-10Y anchor-fit RMSE — not by theoretical appeal:

| rank | lever | measured impact |
|---|---|---|
| 1 | Ex-coupon double-discount bug (F14) | RMSE −29%, max error 104bp → 9bp |
| 2 | Coupon-vintage adjustment (F13 / 1.7) | 1-3Y −0.7bp; 2025 −57%, 2026 −16% |
| 3 | Reference-switch handling (F6 / 3.2) | not yet quantified |
| — | S2 / AFNS convexity term | **≤0.04bp — not worth effort** |

**AFNS vs plain Nelson-Siegel.** Measured over 250 days on TBond 1-10Y:

| model | RMSE |
|---|---|
| AFNS (with `a(τ)` convexity) | 4.151bp |
| plain NS (`S2 = 0`) | **4.131bp** |

Plain NS is *marginally better*. The whole `a(τ)` term spans only −0.08bp
(0.5Y) to −1.44bp (10Y), and because factors are re-solved from today's
anchors *after* `a(τ)` is subtracted, the fit absorbs nearly any S2 error
into `x`. Concretely: deleting S2 entirely shifts fitted yields by 0.04bp on
average; a 10× wrong S2 costs 0.36bp; a **one-year-stale** S2 still fits at
2.49bp vs 1.90bp fresh, even though the S2 norm drifts ~8× over that year.

Two consequences worth recording:
- S2 staleness is a non-issue. It is recalibrated every EOD run on a
  trailing 3-month window anyway, and even gross misspecification is
  sub-bp.
- The justification for keeping AFNS is theoretical no-arbitrage
  consistency (relevant if the curve ever prices derivatives or needs an
  arbitrage-free forward curve), **not** cash-bond fit quality. Keep it —
  it is harmless — but stop treating S2 as a tuning target. This also
  retroactively settles item 2.1 and the Kalman non-goal below: both target
  a term that provably cannot move results by more than ~1bp.

---

## 3c. Reference-switch contamination — quantified (2026-09-05)

Item 3.2's premise (F6) was **confirmed, but only at the bucket level**, and
an aggregate test initially hid it:

- Aggregate view (mean across all 9 buckets): switch days move the fitted
  curve 3.11bp vs 0.82bp on normal days (3.8×) — but after netting off what
  the underlying reference spots actually did that day, the excess
  attributable to the switch is only **+0.07bp**. Switches *coincide* with
  volatile days rather than causing the whole-curve move.
- **Per-bucket view — this is the real effect.** When a bucket rolls, its own
  spot jumps far beyond its normal daily variation:

| bucket | n rolls | mean abs move on roll day | on normal days | ratio |
|---|---|---|---|---|
| 1Y | 34 | 7.77bp | 4.01bp | 1.9× |
| 1.5Y | 26 | 4.88bp | 1.15bp | 4.2× |
| 2Y | 15 | 5.46bp | 0.92bp | 5.9× |
| 3Y | 19 | 13.86bp | 0.47bp | **29×** |
| 5Y | 17 | 5.86bp | 0.18bp | **32×** |
| 10Y | 16 | 6.93bp | 0.20bp | **35×** |

These are step-changes in the reference bond's *identity*, not market moves.

**Impact on the RV signal.** The step-change contaminates the rolling
volatility estimate that every z-score divides by. Measured on real history,
the naive (roll-unaware) `ewm_vol` is inflated **1.5-6.6×** versus the
roll-aware estimate (1Y 1.5×, 2Y 2.3×, 5Y 2.3×, 10Y 6.6×). An inflated
denominator *suppresses* genuine dislocations — the opposite failure from the
one F6 anticipated, and worth stating plainly: the risk is missed entries,
not just false ones.

**Caution on the naive `max|z|` metric.** Measuring "max |z| after a roll"
makes the roll-aware version look *worse* (e.g. 5Y 3.05 → 3.60), because a
smaller, correct denominator produces larger z. That metric rewards the
inflated vol and should not be used to judge this fix; the vol-contamination
comparison above is the right test.

**Bug found while evaluating (FIXED).** `residual_stats._most_recent_roll_date`
compared a `DatetimeIndex` against a `datetime.date`. The cvref pickles index
by `datetime.date` while the `RefBondChange` log is built from Timestamps, and
pandas raises `TypeError` on that comparison rather than coercing — so the
roll-reset guard would have failed on real production data despite passing its
original synthetic tests. Both sides are now normalised; regression tests added
using a `date`-indexed history.

---

## 3d. Plan for the two open items (2026-09-05)

### (1) Bootstrap: redemption-leg timing — DO IT, small and contained

**Sized.** The redemption is discounted at `T` (from the *unadjusted*
maturity) while the actual payment lands 1-2 days later after
`getNextTradingDate` adjustment. Across the last 250 days of TBond reference
selections this bites on **24.6% of bond-days** (not the 2-of-9 a single
snapshot suggested), mean 1.55 days, max 2 days.

Error scales as `z·gap/(365·T)`, so it is worst at the short end:

| ttm band | mean err | max err | affected obs |
|---|---|---|---|
| 0-1y | 0.49bp | 0.79bp | 136 |
| 1-3y | 0.38bp | 0.71bp | 307 |
| 3-10y | 0.15bp | 0.15bp | 1 |

So: **≤0.79bp, concentrated exactly in the 1-3Y region that matters for RV.**
Small, but systematic and one-directional (never self-cancelling), and it sits
in the cornerstone routine.

**Cause.** `T` does double duty in `BootstrapYieldCurve`: it is both the curve
node label (`self.instruments[T]`, `get_maturities()`) *and* the redemption
discount time (`dT = (1.0 + r) ** (-T)`, bootstrap.py:228).

**Plan.** Decouple the two. Extend `add_instrument` with an optional
`redemption_time` (defaulting to `T`, so every existing caller is unchanged),
carry it in the instrument tuple, and use it for the `dT` discount only —
never for the node key or interpolation grid. `selector.build_curve` then
passes the real business-day-adjusted final flow time it already computes for
`flow_times`. Low risk: additive signature, default preserves today's numbers
exactly, and the existing self-consistency test (currently 0.0023 price units)
is the natural regression check — it should tighten.

**Also fold in** the two latent items from the audit: assert on duplicate `T`
keys in `add_instrument` rather than silently overwriting, and document the
`np.interp` clamp below the first node.

### (2) Reference-switch: wire F6/3.2 into live scoring — DO IT, but SPLICE, not reset

**Justified by measurement.** The roll step-change inflates the `ewm_vol` that
every z-score divides by, by **1.5-6.6×** — which *suppresses* genuine
dislocations (missed entries), not just creates false ones.

**But the naive hard reset is wrong here, and the data says so.** Rolls are far
more frequent than the design assumed — median gap between rolls is only
**12-50 days** per bucket, and **94-100% of all days sit within 252 days of a
roll**. If estimation restarts at every roll:

| bucket | median obs available | % of days below `min_points=20` |
|---|---|---|
| 0.5Y | 13 | 63.9% |
| 1Y | 18 | 52.9% |
| 5Y | 46 | 24.1% |
| 10Y | 60 | 22.0% |

The estimator would return NaN or wildly noisy stats on **22-64% of days** —
strictly worse than the contamination it removes. `residual_stats`'s existing
`change_events` reset is therefore appropriate only where roll gaps are long;
it must not be switched on blindly for the bond-curve path.

**Plan — level-adjust (splice) instead.** At each roll, drop that day's
*return* and re-cumulate, so the series stays level-continuous and the **full
history remains usable**. Verified on real data: splicing keeps the whole
window where a hard reset would leave 3-4 observations for 1Y/5Y today.

Insertion point is contained: `stat.statAnalysis_BC` already truncates its
input (`spread.iloc[-zscore_lookback:]`) before calling `OU_calibrate`; the
splice slots in alongside that line, on the *input series*. Deliberately do
**not** change `OU_calibrate`'s signature — it has **10 call sites** across
bond/IRS/spread/OTR-OFR paths, and this finding concerns only the bond-curve
residual.

**Sequencing.** Do (1) first — it is smaller, lower-risk, and changes the
bootstrapped spots that (2)'s residual history is built from, so doing (2)
first would mean re-validating it afterwards.

---

## 3e. Both items IMPLEMENTED (2026-09-05)

### (1) Redemption-leg timing — done

`BootstrapYieldCurve.add_instrument` gained an optional `redemption_time`
(defaults to `T`, so every existing caller is byte-identical). `T` remains the
curve node label / interpolation key; `redemption_time` is used only for the
final-cashflow discount and the two terminal-solve fallbacks.
`selector.build_curve` passes the real business-day-adjusted final schedule
date it already computes for `flow_times`. Also: `add_instrument` now **warns**
on a duplicate `T` key instead of silently overwriting an anchor.

**Impact (no regression):** latest-date reference spots moved by at most
**0.50bp** (mean 0.10bp) for TBond and **0.00bp** for CBond — matching the
predicted ≤0.79bp. 120-day anchor-fit RMSE 4.0992 → 4.1453bp for TBond
(+0.046bp) and unchanged for CBond. The RMSE is deliberately *not* the success
metric here: the anchors are now discounted at their true payment dates, so
the bootstrap is correct where it was previously ~0.4bp biased on a quarter of
all bond-days. Self-consistency measured against true payment times holds at
0.0023 price units.

### (2) Reference-switch splicing — done

New `stat.splice_reference_rolls(spread, roll_dates)` drops the roll-day
*return* and re-cumulates, then re-anchors to the original ending level (so
`close`/`mean` stay on the raw scale). Applied in `statAnalysis_BC` to the
**series the stats are fit on only** — the returned `Spread` stays raw for
charting. `statAnalysis_BC` gained `roll_dates=None`; omitting it is a no-op,
so the other three callers are unchanged. `generators/stat.py` feeds it the
`RefBondChange` dates written by item 3.2, degrading gracefully (warn +
continue) if that key is absent.

**Deliberately NOT a hard reset.** `OU_calibrate`'s signature is untouched (10
call sites across bond/IRS/spread/OTR-OFR). Verified on a synthetic roll:
splicing recovers the true noise scale (**vol 0.164 → 0.0098** against a true
sd of 0.010, a 17x contamination removed) while retaining **all 120
observations**, where a hard reset would have left 59.

**Live pipeline after both fixes:** TBond 1-10Y RMSE **2.13bp** (max 4.97bp),
CBond **3.72bp** (max 6.44bp) — unchanged versus before, i.e. the corrections
improve internal accuracy without disturbing the fit quality already achieved.
Full suite: 116 tests passing.

---

## 4. Explicit non-goals (for now)

- Full Kalman-filter AFNS estimation (measurement + transition). **Re-evaluated
  2026-09-05, confirmed as a non-goal — do not revisit.** This item's own
  stated trigger ("innovation-based S2 still shows instability") is now
  technically true: item 2.1's real-data validation found the naive
  innovations-based fixed-point iteration diverges to NaN/Inf in 4 of 5
  tested historical windows. But that is a numerical-stability defect in one
  specific iterative solve, not a limitation of the cross-sectional-OLS
  architecture — the right fix is the smaller one already flagged for 2.1
  (shrinkage toward a diagonal target, decoupling the S2 estimate from the
  factor-solve loop, or damping the fixed-point step), not escalating to a
  full state-space model. Two further reasons a Kalman filter would be a
  poor trade even setting that aside: (1) this is a same-day cross-sectional
  RV signal (`ytm_act - ytm_quo`) — a Kalman filter's core advantage is
  smoothing across time via the transition equation, which works against
  catching a same-day dislocation unless very carefully detuned; (2) item
  2.2's real-data check already found the 9-point reference cross-section
  cannot reliably identify a 4th free parameter (γ) on top of the existing
  3 factors + S2 — a full Kalman AFNS has strictly more free parameters
  (transition matrix, measurement noise) to fit from the same thin
  cross-section, so the data-sufficiency problem gets worse, not better,
  under this heavier framework. The cross-sectional OLS design remains
  adequate for residual-RV at daily/intraday horizons and much easier to
  reason about and debug.
- More than 3 factors. Adding a 4th factor would absorb the very mispricings
  the strategy trades; keep the curve deliberately stiff.
- Credit curves beyond CDB (other policy banks) — extension of
  `filter_bonds_by_type`, separate effort.


