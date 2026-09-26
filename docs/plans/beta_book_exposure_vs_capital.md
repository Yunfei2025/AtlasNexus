# Beta Book — separate risk exposure from capital usage

Status: **plan only, not implemented.** Supersedes nothing; complements
`docs/plans/portfolio_construction_beta_alpha.md` (which describes how Beta and Alpha books combine)
and `docs/dev/rates_risk_budget_rolldown_approach1.md` (the Stage-1/Stage-2 risk-budget design this
plan extends to a daily cadence).

Scope: restructure the Beta-book portfolio backtest
(`web/tabs/beta/callbacks/backtest_hist.py`) so that exposure P&L, carry, funding and capital usage are
computed on their own correct bases, and so the daily FactorModel signal actually drives the book.

---

## 1. Why (problem statement)

Capital gain scales with **DV01** (a risk quantity); carry scales with **notional held** (a capital
quantity). The current code carries one weight vector and so forces them equal. Three concrete
consequences, all verified in the current code:

1. **Slope/curvature carry is missing.** `_yield_carry` (`multiasset/factor_backtest.py:198`) returns
   carry only for `_LEVEL_FACTOR_PREFIXES = {'IRDL','SPDL','CRDL'}` (line 130) and exactly zero for
   IRSL/IRCV/CRSL/CRCV. The book accrues no carry on tenor legs it genuinely holds, and IRDL's Sharpe is
   inflated relative to IRSL/IRCV purely from having a carry term they lack — which biases the Stage-1
   risk-parity budget toward IRDL.
2. **The daily signal is sampled monthly.** `factor_signal_series` is a *daily* `position` series
   (`backtest_hist.py:256-265`), but `_factor_signal_asof` is called with `rebalance_date`
   (`backtest_hist.py:630`), so the book freezes for a month and the signal does almost nothing.
3. **The book is always 100% invested.** Lines 672 and 685 renormalise by `sum(abs(w)) == 1`, so a
   bearish signal can only *rotate* the book, never de-risk it. There is no notional, leverage or
   utilisation accounting anywhere in `multiasset/`.

**Outcome:** factor-level backtests become pure price return; carry/funding/capital usage move to the
book level on real per-tenor notional; the daily signal resizes the book on top of a monthly risk-parity
base; and deployed capital may fall below full investment, with the remainder earning the cash rate.

## 2. Approved design decisions

| # | Decision |
|---|---|
| 1 | Factor-level backtests are **price-only**; `_yield_carry` returns zero for all factors. |
| 2 | **Two cadences**: Stage 1 (ERC/SLSQP) monthly = reference base; Stage 2 (tenor tilt) daily. |
| 3 | **Per-factor daily coefficient, then pool**: `scaled[f] = ref[f] * scalar_to_coeff(signal_f(t), f)`, then pool IRDL/IRSL/IRCV per country into `group_sub_budget`. |
| 4 | **Split P&L**: capital gain (DV01×Δy) and carry (notional×y/365) computed separately; aggregated by domicile/type for *display only*. |
| 5 | **Absolute-return P&L** — gross carry, no funding netted in. Funding deducted **only in Sharpe**, per domicile (FR007/SOFR/ESTR/SONIA/TONAR). |
| 6 | **Long-only, unlevered**: `sum(notional) <= 0.95 * total_capital`. **FX is the one exception** — keeps its existing signed cap, since a currency view is inherently two-sided. |
| 7 | **De-risking allowed**: gross may fall below 95%; undeployed cash earns FR007. |
| 8 | Transaction cost **0.1bp** (from 0.5bp), on **daily** notional turnover. |

## 3. Measured facts that shaped the design

**Removing factor-level carry barely moves the risk model.** Measured over a 2yr window: factor vols
change by **≤0.50%, typically <0.2%**; IRSL/IRCV/CRSL/CRCV change by **0.000%** (already carry-free). So
Stage-1 budgets shift negligibly — no mitigation needed, but the RP cache **must** be version-bumped or
the change is invisible.

**Daily Stage 2 is NOT free if implemented naively.** Measured cost of `rebuild_asset_weights` per call
on a realistic 40-asset book:

| Component | Per call | Cause |
|---|---|---|
| `_tilt_group_shape` × ~10 groups | ~0.24ms | closed-form solve; genuinely cheap |
| **capital-cap clip→renorm** | **~1.3ms** | **10 unconditional iterations of a pure-Python loop over every asset** (`factor_optimizer.py:395-400`) |
| violations assertion pass | ~0.1ms | second full per-asset pass (lines 405-415) |
| group→asset scatter | ~0.4ms | Python loop (line 330) |

→ **~2.0ms/call = ~5.1s** for a 10yr daily backtest, on the interactive Dash path. The capital cap is
~65% of it. Also wasteful per-call: the `isinstance` class sets (lines 346-359) and
`RiskModelConfig.scaled_bounds` (line 360) are rebuilt daily from inputs that only change monthly.

**The key simplification — carry does not need a daily tenor solve.** Because `tilt_lambda` anchors the
tenor shape near DV01-equal, the **capital-weighted yield of a group is nearly invariant** to the daily
budget. Measured across level ∈ [0.02, 0.30] × slope ∈ [−0.05, +0.05] × curve ∈ [−0.02, +0.02]:

```
capital-weighted yield range: 2.0383% .. 2.0391%   (spread 0.00085pp)
carry error if the tenor mix is frozen monthly:  0.021%
```

0.02% of carry is a rounding error. **So Stage 2 runs monthly, producing per-group tenor shares and a
blended capital-weighted yield; the daily step is a vectorised scalar multiply.**

| Approach | 10yr daily cost |
|---|---|
| Naive: call `rebuild_asset_weights` every day | 5.1s |
| Vectorise the cap loop | 1.8s |
| + hoist `(AᵀA)⁻¹` into monthly context | 0.62s |
| **Chosen: monthly Stage 2 + daily scalar (fully vectorised, no day loop)** | **0.026s** |

**None of these numbers is a feasibility concern.** Stage 1's monthly SLSQP ERC solve (unchanged by this
plan, ~120 calls over 10yr with correlation-matrix computation and asset screening on top) already
dominates total backtest runtime by a wide margin — even the *naive* 5.1s daily-Stage-2 row above would
be a rounding error next to it. The "monthly Stage 2 + daily scalar" design is chosen because it is both
simpler to implement (a vectorised outer product, no per-day linear solve, no per-day Python loop) and
because it happens to also be the most accurate option for the tenor mix — not because the slower options
were too slow to ship. A counter-check on a *wrong* shortcut, for the record: using a **flat average**
tenor yield instead of the capital-weighted one overstates carry by **21% (43bp annualised)**, because
DV01-equal weighting puts ~51% of capital in 1Y. The approximation that works is "freeze the *mix*
monthly"; the one that fails is "ignore the mix."

---

## 4. Steps

### Step 1 — Pure file splits, zero behaviour change

`backtest_hist.py` (1089 lines) → package `web/tabs/beta/callbacks/backtest_hist/`. Only one import site
(`callbacks/__init__.py:12`), so this is low-risk.

| Module | Moved contents |
|---|---|
| `__init__.py` | re-export `register_backtest_hist_callbacks` (keeps the existing import working) |
| `register.py` | the 6 `@app.callback` declarations; bodies delegate |
| `_ui_callbacks.py` | lines 36-202 (pure UI callbacks) |
| `_signals.py` | `_factor_signal_asof` (291-297), `_trend_sign_asof` (316+) — **promoted from closures to module functions** taking state explicitly; prerequisite for Step 4 |
| `_stage1_rp.py` | Step A (465-596) → `compute_rp_base(...)` |
| `_stage2_tilt.py` | Step B (598-641) + Step C (643-721) |
| `_pnl.py` | daily P&L (730-770) + turnover/tx (772-802) |
| `_figures.py` | 804-1000 figure/KPI/table builders |
| `_payload.py` | `results_payload` (1000-1056) + `save_historical_backtest_result` |
| `orchestrator.py` | thinned `update_historical_allocation`, **extracted as a plain testable function** (no Dash decorator) — it has zero test coverage today and Steps 4-8 change it heavily |

Also scaffold `multiasset/book/` (`__init__.py`, `sizing.py`, `pnl.py`, `carry.py`, `funding.py`,
`capital.py`) — docstrings only, so Steps 3-8 are pure additions. Gives CLAUDE.md's phantom `portfolio/`
reference a real home.

**Leave `factor_model.py` (1956 lines) alone** — orthogonal; its only touchpoint is a 4-line deletion in
Step 3.

**Verify:** full suite unchanged (284 pass, 1 known pre-existing `test_alpha_layouts` failure).
**Capture a golden NAV series from a manual UI run first** — afterwards a split bug is indistinguishable
from an intended change.

### Step 2 — `Stage2Context`: monthly Stage 2, reusable daily

New frozen dataclasses in `multiasset/factor_optimizer.py`:
- `GroupStage2Spec` — `suffix`, `asset_names`, `asset_indices`, `loadings` (n_tenors×3), `level_factor`,
  `slope_factor`, `curve_factor`, `is_credit`, **`tenor_shares`** (Stage-2 output),
  **`capital_weighted_yield`** (the §3 invariant), **`durations`**
- `Stage2Context` — `rebalance_date`, `asset_names`, `factor_names`, `reference_factor_budget`, `groups`,
  `nonrate`, `tilt_lambda`, **`lo_arr`/`hi_arr`** (precomputed bound arrays, replacing per-asset
  `isinstance` dispatch), `asset_class_of`

Split `_two_stage_weights` into:
```python
def _stage1_context(self, factor_vols, factor_cov=None, tilt_lambda=None,
                    rebalance_date=None) -> Stage2Context:
    """EXPENSIVE, monthly. SLSQP ERC + group/loadings bookkeeping + Stage-2 tenor
    solve + bound-array precompute. Body = current 167-330 + 346-365."""

@staticmethod
def rebuild_asset_weights(ctx, factor_budget=None) -> pd.Series:
    """factor_budget=None reproduces ctx.reference_factor_budget EXACTLY.
    Vectorised clip->renorm with early convergence exit. Body = 332-344 + 390-424."""

def _two_stage_weights(self, ...) -> pd.Series:      # SIGNATURE UNCHANGED
    return self.rebuild_asset_weights(self._stage1_context(...))
```
`rebuild_asset_weights` is a **staticmethod** so the daily path never touches `self.portfolio`. Expose
the context via a `self._stage2_ctx` attribute + `stage2_context()` accessor rather than changing
`fit_and_calculate`'s return arity (callers in `allocate_capital`, `portfolio_run.py`, `dashboard.py`).
`_tilt_group_shape` needs **zero changes**.

Optimisations (pure hoisting/vectorisation of unchanged math):
- precompute `lo_arr`/`hi_arr`, the class sets and `scaled_bounds` into the context (monthly)
- vectorise clip→renorm to `np.clip(w, lo_arr, hi_arr)` with an **early convergence exit** (converges in
  2-3 of 10 iterations)
- move the violations-assertion pass to **monthly only** — it warns about infeasible *floor
  configuration*, which cannot change day to day

**Critical semantic fix — `budget_group` must use level only.** `scalar_to_coeff` returns `[-1.5, 1.5]`
for directional factors, so today's level+slope+curve *sum* can go negative, inverting a group's
direction under `sum(abs(v))` normalisation. Instead:
```python
budget_group      = max(factor_budget.get(g.level_factor, 0.0), 0.0)   # capital SCALE
group_sub_budget  = np.array([level, slope, curve])                    # SHAPE (signed is correct)
```
Slope/curve views then bend the tenor curve without scaling capital — correct for a long-only unlevered
book, and what makes decision #6 satisfiable. Document at the site; it is a real change from today.

**Verify:** `tests/test_stage2_context.py` — `rebuild_asset_weights(ctx, None)` **bit-identical** to
`_two_stage_weights` (`atol=0, rtol=0`); **write this test before the optimisations and re-run after each
one**, so vectorisation drift is caught immediately rather than blamed on Step 3; 250 calls < 0.5s;
long-only + caps hold; golden-file guard on Step-1's monthly `allocations_by_date`.

### Step 3 — Carry → zero at factor level; funding out of factor P&L

**One commit** — splitting them leaves IRDL with funding drag and no carry (structurally negative drift).

`multiasset/factor_backtest.py`:
- `_yield_carry` (198) → `return pd.Series(0.0, index=level.index)` unconditionally. **Keep the function
  and signature** — its 2 call sites (284, 597) become mechanically price-only; the diff stays reviewable
  and the revert trivial. Docstring points at `multiasset/book/carry.py`.
- **Delete** `_apply_funding_cost` (605-620) and its **6** call sites: `factor_backtest.py:653, 714, 747,
  804`; `factor_model.py:1653`; `_rfbt_train_helpers.py:364`. Each reverts to plain
  `position.shift(1) * returns`.
- **Keep** `funding_cost_series` (217-266) and `_load_funding_rate` (164) — Step 6 needs them. Promote
  `_load_funding_rate` → public `load_funding_rate`; keep a private alias.

Funding hurdle moves into Sharpe — extend `compute_metrics` (~975) with
`funding_hurdle: Optional[pd.Series] = None`:
`excess = ann_return - risk_free_rate - ann_funding`, **`ann_vol` unchanged** (funding never enters the
denominator — precisely why the earlier flat-rate attempt swung Sharpe +4.6 → −5.4). New keys
`'Ann. Funding Cost'`, `'Sharpe (gross of funding)'`. Thread through `compute_portfolio_metrics`.

Rewrite `tests/test_yield_carry.py` → `tests/test_factor_price_only_returns.py`; invert the 4 tests
asserting nonzero Level carry (lines 73, 84, 93, 215). Sharpest new assertion: on a **flat** yield series
`_yield_to_return` is exactly `0.0` for every factor code. Keep all `funding_cost_series` tests (108-164).

**Bump the RP cache in this commit**: `RPCacheParams.bounds_version` → `"RiskModelConfig.v4"` plus a new
`returns_convention: str = "price_only_v1"`. Otherwise Step 3 silently reuses carry-contaminated weights.

**Verify:** full suite. Numeric: `run_ma_yield_strategy` on IRDL.CN over 5yr — `Ann. Return` drops ~2.8pp
(the average yield level) and **`Ann. Vol` unchanged to ~1e-12**.

**Risk:** changes *every* factor-level backtest shown anywhere. `_rfbt_train_helpers.py:364` *trains on*
`strategy_returns` — **persisted RFBT artifacts go stale; retrain or re-validate before Step 4.**

### Step 4 — Daily resizing (vectorised, no day loop)

New in `multiasset/book/sizing.py`:
```python
def scaled_factor_budgets_daily(reference_budget, signal_asof, daily_index,
                                screened_factors) -> pd.DataFrame:
    """scaled[d, f] = reference_budget[f] * scalar_to_coeff(signal_asof(f, d), f)
    Unscreened factor or None signal on date d -> keeps its reference budget.
    NOT renormalised: the sum is gross risk appetite, consumed by
    capital.weights_to_notional(), not normalised away here."""

def notional_daily_from_context(ctx_by_month, budgets_daily, total_capital,
                               max_utilisation=0.95) -> pd.DataFrame:
    """Per-asset, per-DAY notional, without a per-day Stage-2 solve.

    What is frozen monthly is ONLY the within-group tenor PROPORTIONS
    (tenor_shares from Stage 2). The notional itself is fully daily and is
    NOT an estimate:

        group_notional[d, g] = budgets_daily[d, level_factor(g)] * total_capital
        notional[d, a]       = group_notional[d, g(a)] * tenor_shares[g][a]

    Output is a full (n_days x n_assets) matrix; every tenor's notional
    moves every day with the signal. Carry downstream (Step 5) is then
    EXACT per tenor per day -- notional[d,a] * yield[d,a]/365, using each
    tenor's own actual daily yield -- never a blended/estimated yield. The
    only approximation is the tenor MIX being fixed within the month
    (measured 0.021% carry error, section 3); carry itself is not
    approximated.

    CAPITAL CONSTRAINT ENFORCED HERE, DAILY, NOT JUST AT THE MONTHLY
    REFERENCE LEVEL: `budgets_daily` (from scaled_factor_budgets_daily) is
    NOT pre-normalised -- a strong day can push the raw sum of
    group_notional past total_capital. So after building notional[d, :]:

        gross_d = notional[d, :].abs().sum()
        if gross_d > max_utilisation * total_capital:
            notional[d, :] *= (max_utilisation * total_capital) / gross_d

    applied INDEPENDENTLY FOR EVERY DAY d (not once per month), so
    `notional.abs().sum(axis=1) <= max_utilisation * total_capital + eps`
    holds on every single row of the output, even on days where the daily
    coefficient scales the reference budget above what Stage 1 originally
    sized for. This scaling step is the same one Step 7's
    `capital.weights_to_notional()` implements; calling it out here
    because this is the function that actually needs to invoke it on
    every day of the loop, not just at rebalance."""
```
`_factor_signal_asof` already accepts arbitrary dates; only the caller's date changes.

**Drop the daily tilt cache.** Delete `FactorTiltCacheParams`, `factor_hash`, `load_factor_tilt`,
`save_factor_tilt` from `multiasset/backtest_cache.py` (keep `scalar_to_coeff` and the RP cache). At
0.026s recompute, a multi-MB pickle load + LRU prune + rewrite is strictly slower, and the cache would
otherwise hold an `n_factors × n_days × n_assets` cube × 5 LRU versions. Update the module docstring
(1-22); leave `beta_factor_tilt_cache.pkl` orphaned rather than auto-deleting user data.

Add `stage2_ctx_by_date` to the `save_rp`/`load_rp` payload (numpy arrays + plain dicts pickle cleanly);
`load_rp` treats its absence as a **cache miss** so old entries don't half-hydrate.

**Verify:** `tests/test_daily_factor_budget.py` — constant signal for a month ⇒ daily weights identical to
old monthly weights every day (new path subsumes old); mid-month signal jump ⇒ weights move on the jump
date, not the 1st (**the bug-2 regression test**); negative IRSL ⇒ tenor shares shift with
`sum(notional)` unchanged (shape-vs-scale separation); all weights `>= -1e-9` except FX.
Plus `test_frozen_tenor_mix_carry_error_under_5bp` pinning the §3 approximation.

### Step 5 — Split P&L: capital gain vs carry

`calculate_daily_returns_series` (`multiasset/data.py:435`) **already** returns a clean
`carry + capital == total` on the bond path (479-511). Do not restructure it. Add a contract guard:
```python
def returns_split_is_exact(asset_name: str) -> bool:
    """True for bonds. False for FX / FX-cross / commodities, where capital is
    hardcoded 0.0 and the whole price return lives in 'total'
    (data.py:513-552, 362-433)."""
```
**This is the likeliest way to break non-rates assets** — naive use of the split silently drops all FX and
commodity P&L; callers must fall back to `total` when it returns `False`.

`multiasset/book/pnl.py`:
```python
@dataclass
class BookPnL:
    capital_gain: pd.DataFrame   # notional * data.py 'capital'  (== DV01 x dy)
    carry:        pd.DataFrame   # notional * data.py 'carry'    (== y/365)
    other:        pd.DataFrame   # FX/commodity 'total' (unsplittable)
    cash:         pd.Series      # undeployed capital * FR007/365 (decision #7)
    @property
    def total(self) -> pd.DataFrame: ...

def compute_book_pnl(notional_daily, market_data, start_date, end_date) -> BookPnL: ...
def aggregate_for_display(pnl, asset_names) -> pd.DataFrame:   # (domicile, type), DISPLAY ONLY
```
**Reuse, don't reimplement:** the annuity modified-duration formula stays sole-sourced in
`data.py:486-491`. Do **not** derive DV01 from `get_default_sensitivities` — that gives two divergent
duration definitions.

**Verify:** `tests/test_book_pnl_split.py` — bonds-only: `(capital_gain + carry).sum().sum()` equals
legacy `(alloc_daily * rets['total']).sum().sum()` to 1e-9. With one FX asset: total still matches
(catches the `capital=0.0` trap).

### Step 6 — Funding in Sharpe only; cash earns FR007

`multiasset/book/funding.py`:
```python
_DOMICILE_ALIASES = {'EU': 'DE'}

def normalise_domicile(code): ...
    """data.py:231/607 map 'DE Gov Bond' -> 'EU' but
    _IRDL_FUNDING_RATE_MACRO_COL keys 'DE'. Without this, Bund funding is
    silently ZERO. Single reconciliation point."""

def book_funding_cost_daily(notional_daily, domicile_of) -> pd.Series:
    """cost[d] = sum_a notional[d-1,a] * rate[domicile_a][d-1]/100/365
    /365 matches the book's carry convention (data.py:484), NOT the /252 of the
    factor-level funding_cost_series -- book P&L accrues on calendar days,
    factor returns on business days. INTENTIONAL; comment at both sites."""

def cash_return_daily(notional_daily, total_capital, max_utilisation=0.95) -> pd.Series:
    """Decision #7: cash[d] = (0.95*capital - notional[d].sum()) * FR007[d]/100/365
    so de-risking doesn't forfeit the risk-free return."""
```
`book_funding_cost_daily` is **never subtracted from `daily_pnl`** — it is passed as `funding_hurdle` to
Step-3's `compute_metrics`. `cash_return_daily` **is** added to P&L (real earned return). KPI grid gains
`"Sharpe (post-funding)"` and `"Ann. Funding Cost"`.

**Verify:** `tests/test_book_funding.py` — monkeypatched rates; CN+US+DE book charges three different
rates; **`'DE Gov Bond'` gets a nonzero ESTR charge** (EU/DE regression); `daily_pnl` byte-identical with
and without the hurdle while `Sharpe` differs.

### Step 7 — Long-only unlevered capital constraint

`multiasset/book/capital.py`:
```python
def weights_to_notional(weights, total_capital, max_utilisation=0.95,
                        signed_classes=('FX',)) -> pd.Series:
    """1. clip long-only at 0 EXCEPT signed_classes (FX keeps [-cap,+cap], decision #6)
       2. gross = weights.abs().sum()
       3. if gross <= max_utilisation: notional = w * total_capital   # SCALE-PRESERVING
          else:                        notional = w * total_capital * (max_utilisation/gross)
       4. invariant: notional.abs().sum() <= max_utilisation*total_capital + eps

    Step 3 is the substantive change: today's code (backtest_hist.py:672, 685)
    ALWAYS renormalises to sum(abs(w))==1, so the book is always fully invested and
    a bearish signal can only reallocate. Preserving gross < 0.95 is what makes
    decision #3's daily scaling meaningful."""
```
Cap-layer ownership:
- **Keep** the 10-iteration clip→renorm (now vectorised, `factor_optimizer.py:390-424`) inside
  `rebuild_asset_weights` — it enforces class concentration on the *shape*, where sum-to-1 is correct.
- **Remove** the `CLASS_CAPS` 3-iteration loop (`backtest_hist.py:677-685`). Its `sum(abs(v))` renorm is
  exactly what defeats de-risking. Two cap layers with different renorm semantics is how you get a book
  that is fully invested regardless of signal.
- **Keep** the FX signed cap (`lo = -cap`, line 681) per decision #6.

Add `RiskModelConfig.CAPITAL_UTILISATION_MAX = 0.95`, `TX_COST_BP = 0.1`.

**Verify:** `tests/test_capital_constraint.py` — all-bullish ⇒ `sum(notional) == 0.95*capital` exactly;
**all-bearish ⇒ strictly less (the de-risking test)**; bond notionals `>= 0`, FX may be negative;
`(notional.abs().sum(axis=1) <= 0.95*cap + 1e-6).all()` over 5yr — **checked row-by-row on the full daily
output, not just at monthly rebalance dates**, since `scalar_to_coeff` can return up to 2.0x on a
long-only factor: a single day where several factors' daily coefficients spike together must still be
caught and scaled back to the 95% ceiling by `notional_daily_from_context`'s per-day scaling (Step 4),
not merely by the monthly Stage-1 sizing that preceded it. Add
`test_single_day_spike_across_multiple_factors_still_respects_cap`: hold the monthly reference budget at
a moderate level, then set every factor's daily signal to its max (coeff=2.0) on one single day only —
assert that day's `notional.abs().sum() <= 0.95*capital + eps` while adjacent days (coeff=1.0) may sit at
a different, lower utilisation. This is the test that would fail if the cap were wired in only at Step 2
(monthly context) instead of also at Step 4's daily loop.

### Step 8 — Transaction cost: 0.1bp on daily turnover

In `_pnl.py`, `_TX_COST_BP 0.5 → 0.1` (promoted to `RiskModelConfig`). Replace the monthly block
(776-802):
```python
turnover_daily = (notional_daily - notional_daily.shift(1)).abs().sum(axis=1)   # CNY one-way
tx_cost_m = turnover_daily.fillna(0.0) * (RiskModelConfig.TX_COST_BP / 1e4) / 1e6
tx_cost_m.iloc[0] += notional_daily.iloc[0].abs().sum() * rate / 1e6   # initial build DOES cost
```
Turnover is now measured in **notional** (what actually trades), not weight-fraction × capital. The old
code got the day-1 charge implicitly via `_wt_df_prev.fillna(0.0)`; make it explicit. "Ann. Turnover"
will jump ~an order of magnitude — expected, and should be called out in the UI.

**Verify:** `tests/test_daily_tx_cost.py` — static book charges day-1 only; daily-flipping book ~252×
per-day; cost scales linearly in `TX_COST_BP`.

### Step 9 — Reconciliation (acceptance gate)

`tests/test_book_pnl_reconciliation.py`:

1. **`test_outright_only_book_reconciles_with_legacy_total`** — IRDL.CN only, CN1Y..CN30Y, **constant**
   signal (cadence can't contaminate), constant notional, funding excluded. New `(capital_gain + carry)`
   matches legacy `total`-based P&L to `<1e-6` relative. For an outright book the old level carry was
   economically *right*; it just lived in the wrong layer.
2. **`test_slope_curve_book_diverges_and_new_number_is_correct`** — add IRSL.CN/IRCV.CN. Books **must**
   diverge, and the direction is diagnostic: legacy `_yield_carry` returned 0.0 for IRSL/IRCV, so the
   legacy book **under-accrued**. Assert `new_carry.sum() > legacy_equivalent` **and**
   `new_capital_gain ≈ legacy_capital_component`. **This pair is load-bearing** — it isolates carry as the
   sole source of divergence and proves capital gain is untouched. If `capital_gain` moved too, that is a
   sizing bug, not a carry improvement.
3. **`test_capital_plus_carry_equals_total_for_bond_only_books`** — permanent invariant guarding Step-5
   drift.

Capture the legacy baseline with a `_legacy_total_pnl()` helper **in the test file** (the exact old line
770), so no dead code remains in `multiasset/`.

---

## 5. Ordering constraints (hard)

```
1 (splits) ──> 2 (Stage2Context) ──> 4 (daily resize) ──> 7 (capital) ──> 8 (tx cost)
                     │                      │                  │
3 (carry/funding) ───┴──────────────────────┘                  │
       │                                                       │
       └──> 5 (P&L split) ──> 6 (funding/cash) ──> 9 (reconciliation)
```
- **1 first**; its golden NAV capture is what makes Step 2's exactness test meaningful.
- **Step 2's exactness test is written before its optimisations** and re-run after each.
- **3 before 5** — otherwise carry is double-counted (in the factor vols feeding Stage 1 *and* at book level).
- **3's RP cache bump lands with Step 3.**
- **7 before 8** — tx cost is computed on notional, which 7 defines.
- **9 last** — acceptance gate.

## 6. Risks

1. **RFBT trained artifacts go stale after Step 3** (trainer learns on `strategy_returns`). Retrain or re-validate before Step 4.
2. **`'EU'` vs `'DE'`** silently zeroes Bund funding — fixed in one place, regression-tested in Step 6.
3. **FX/commodity `capital == 0.0`** — naive split use drops all non-bond P&L; guarded by `returns_split_is_exact`.
4. **`/252` (factor) vs `/365` (book)** is deliberate — comment both sites or someone will "fix" it.
5. **NAV semantics change** once gross can be <95%: "Ann. Return" becomes return-on-*capital*, not return-on-*deployed*. Report both or relabel.
6. **Frozen-monthly tenor mix is an approximation** (0.021% carry error, §3). If `TENOR_TILT_LAMBDA` is ever lowered substantially (shape chases the budget harder), re-measure — `test_frozen_tenor_mix_carry_error_under_5bp` is the tripwire.
7. **No existing test coverage** for `update_historical_allocation` — mitigated by extracting the orchestrator as a plain function in Step 1.

## 7. Verification

Per-step tests above, plus after every step:
`conda run -n prod python -m pytest` — expect 284+ passing and the single known pre-existing
`test_alpha_layouts::test_individual_backtest_layout_is_not_locked_to_76px_columns` failure (confirmed to
predate this work).

End-to-end: `python main.py daily-web`, Beta → Backtest tab, run a 10yr IRDL.CN + IRSL.CN + IRCV.CN book
in `factor_scaling` mode and confirm: NAV plausible; `sum(notional) <= 0.95*capital` every day;
carry / capital-gain / cash / funding reported as separate lines; Sharpe (post-funding) < Sharpe (gross);
and the run completes without a noticeable slowdown versus the monthly-cadence baseline.
