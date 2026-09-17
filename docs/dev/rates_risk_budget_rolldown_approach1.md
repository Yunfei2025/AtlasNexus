# Rates Portfolio Construction: Two-Stage Risk Budgeting + Carry/Roll-Down Optimization

**Status:** Draft v1 — for further development
**Approach:** Factor risk parity (Stage 1) → carry-optimal instrument mapping (Stage 2)

---

## 1. Motivation

The portfolio has two decisions that live in different spaces:

- **How much risk to hold** — allocated across level, slope, curvature (3 factors, from PCA on the curve).
- **Which instruments deliver that risk** — allocated across N tenors (10–15 points).

With 3 factor constraints and N tenors, there are `N − 3` degrees of freedom left after the risk budget is satisfied. Carry and roll-down should be optimized inside that leftover space, not layered on top in an ad hoc way. This note fixes that structure as a two-stage problem.

---

## 2. Stage 1 — Factor Risk Budget (closed form)

With orthogonal PCs, the factor covariance is diagonal, so risk parity has a closed-form solution — no need to solve the general nonconvex risk-parity problem.

For factor `k` with budget `b_k` and PC volatility `σ_k`, targeting portfolio vol `σ_p`:

```
e_k = sign_k · sqrt(b_k) · σ_p / σ_k
```

- `e_k` — target exposure to PC k, in PC units
- `σ_k` — volatility of PC k (level/slope/curvature)
- `σ_p` — target total portfolio vol
- `sign_k` — direction, set from a view or to keep carry positive

Output of Stage 1: a vector `e* = (e_1, e_2, e_3)`.

### 2.1 Optional: carry-tilted budgets

Rather than equal budgets `b_k`, tilt using factor-level carry-to-risk. For each PC, compute the minimum-residual mimicking portfolio:

```
W = Σ_ε⁻¹ B (Bᵀ Σ_ε⁻¹ B)⁻¹
μ_k = (c + r)ᵀ W[:, k]
```

Standardize to `z_k = (μ_k/σ_k)`, then tilt:

```
b_k ∝ b_k⁰ · exp(γ · z_k)
```

`γ = 0` recovers pure risk parity. This is a Black–Litterman-style blend: risk parity is the prior, carry-to-risk is the view. **To be developed:** how `γ` is calibrated/backtested (see §5).

---

## 3. Stage 2 — Carry-Optimal Instrument Mapping (convex)

Given `e*` from Stage 1, solve for DV01 weights `w` across tenors:

```
max_w   (c + r)ᵀw − λ · wᵀΣ_ε w − κ · ‖w − w_prev‖₁

s.t.    Bᵀw = e*
        gross / liquidity / tenor limits
```

- `B` — N×3 loading matrix (PCA loadings)
- `c + r` — carry + roll-down per unit DV01, net of repo/funding
- `Σ_ε` — residual (non-PC) covariance
- `λ` — residual-risk penalty (**critical** — see §4)
- `κ` — turnover penalty vs. previous weights `w_prev`

### 3.1 Reference implementation (cvxpy)

```python
import cvxpy as cp
import numpy as np

# Inputs
# B          : (N, 3) PCA loadings
# Sigma_pc   : (3,)   PC vols [level, slope, curvature]
# Sigma_resid: (N, N) residual covariance
# carry_roll : (N,)   carry + roll-down per unit DV01
# w_prev     : (N,)   previous weights
# b          : (3,)   risk budgets (from Stage 1, possibly tilted)
# view_sign  : (3,)   direction per factor
# sigma_p    : float  target portfolio vol

e_star = view_sign * np.sqrt(b) * sigma_p / Sigma_pc   # Stage 1 output

w = cp.Variable(B.shape[0])
lam, kappa = 5.0, 0.02          # placeholders — calibrate, see §5

obj = cp.Maximize(
    carry_roll @ w
    - lam * cp.quad_form(w, Sigma_resid)
    - kappa * cp.norm1(w - w_prev)
)
cons = [
    B.T @ w == e_star,
    cp.norm1(w) <= gross_limit,
    cp.abs(w) <= liq_limit,
]
cp.Problem(obj, cons).solve()
```

---

## 4. Anchoring around the best roll-down tenor `T*`

Rather than relying purely on the optimizer to find the roll-down pocket, make the structure explicit and legible:

| Factor | Instrument template |
|---|---|
| Level | Bullet concentrated at `T*` |
| Slope | Spread with one leg at `T*` (choose side by which has better carry: `2s–T*` vs `T*–10s`) |
| Curvature | PCA-weighted butterfly, body at `T*` |

The Stage 2 optimizer is then used only for **residual fine-tuning** around this template, with a penalty on deviation from it. This keeps a risk committee able to see "why" the book looks the way it does, rather than treating it as a black-box optimizer output.

---

## 5. Open items / next steps

- [ ] Calibrate `λ` (residual penalty) and `κ` (turnover penalty) jointly via backtest — these trade off against each other (low λ + high carry tilt → book that looks great until a curve dislocation).
- [ ] Calibrate `γ` (carry tilt strength in §2.1) — backtest realized vs. static carry assumption, split by regime (bull flattener / bear steepener / range-bound).
- [ ] Decide rolling window for PCA re-estimation of `B` (60–120 days typical for local curves); track loading stability.
- [ ] Build instrument-level carry vectors correctly: CTD/basis adjustment for futures; fixing-vs-repo carry for swaps (e.g., FR007 vs. actual funding) — **do not** use naive static carry.
- [ ] Turnover attribution: decompose realized turnover into (a) Stage 1 re-estimation of `e*`, (b) `B` re-estimation, (c) carry/roll-down target moving.
- [ ] Ex-post risk decomposition: realized P&L variance back into 3 PC buckets + residual, check against budget `b_k` and flag if residual is chronically over-budget → raise `λ` or add tenors.

---

## 6. One-line framing

Risk budgeting decides **how much** risk to hold per factor; roll-down decides **with what** instruments to express it, using the degrees of freedom the risk budget leaves free — with an explicit residual-risk penalty so carry-harvesting can't hide directional curve risk that PCA doesn't see.

---

## 7. Implementation plan (scoped: anchor-only Stage 2)

**Scope decision:** because CN rates currently only gives us one reliable roll-down read (`T*`, the best-carry point on the curve), Stage 2 is scoped to the **§4 anchoring template only** — bullet / spread / butterfly built around `T*` — not the general N-tenor cvxpy program in §3. §3 stays documented as the natural extension once we trust roll-down estimates at multiple tenors simultaneously. This keeps the first version legible to a risk committee (explicit template, not a black-box QP) and avoids inventing a residual-covariance/turnover-penalty calibration exercise before Stage 1 is even wired to carry.

### 7.1 What already exists (reuse, don't rebuild)

Stage 1 (factor risk parity) is already ~90% built in `multiasset/`, just not exposed as a standalone rates-only module:

- `multiasset/pca_analyzer.py:475` `PCARiskFactorAnalyzer` — PCA loadings `B` (level/slope/curvature) and PC vols, fit per country including `'CN'`.
- `multiasset/factor_backtest.py` — `compute_ewma_factor_vols`, `compute_ewma_factor_covariance` — gives `σ_k` and factor covariance for the closed-form Stage 1 formula in §2.
- `multiasset/factor_optimizer.py:206` — SLSQP-based ERC solve; §2's closed-form solution can bypass this entirely since PCs are already orthogonal (no need to call the general optimizer for Stage 1).
- `multiasset/budget.py:18` `derive_vol_sqrt_budgets` — reusable for `b_k` if we want vol^0.5 budgets instead of equal budgets.

None of the above currently touches carry/rolldown — Stage 1 output (`e*`, target PC exposures) is the clean handoff point into the new Stage 2 module.

Carry/rolldown building blocks exist but are **not tenor-DV01-vectorized** for CN IRS:

- `curves/calibration/irs/valuation.py:20` `evalueContract` — per-contract `Carry(3m,bp)` and `Roll(3m,bp)` (via `_calculate_roll_returns`, L64) off the fitted CN IRS spot curve. This is the right source of truth for roll-down (uses the actual fitted curve, not a naive static spread).
- `curves/generators/irs.py:186-187` — persists `Carry(3m,bp)`/`Roll(3m,bp)` per instrument into the stat-curve time series.

### 7.2 New work required

1. **Tenor-grid reconciliation.** `IRSConfig` (`settings/fixed_income.py:305`) quotes FR007 at 1M/3M/6M/9M/1Y/2Y/3Y/4Y/5Y/7Y/10Y; `CN_IR_TENORS`/`CN_DETERMINISTIC_WEIGHTS` (`multiasset/pca_analyzer.py:34,47`) use a 1/2/5/10/20/30Y PCA grid. Before anything else, build a small mapping/interpolation layer so a roll-down value computed at an IRS-quoted tenor can be located against the PCA tenor grid (needed to pick `T*` and to know which PC loadings apply there).

2. **Per-tenor carry+rolldown vector for CN IRS.** Wrap `evalueContract`'s `Roll(3m,bp)`/`Carry(3m,bp)` outputs into a single function producing a `(N,)` vector aligned to the reconciled tenor grid, net of funding (FR007 fixing vs. actual repo, per §5 open item — do not use static carry). This is new code but should live next to `curves/calibration/irs/valuation.py`, not duplicate the bond-swap (`stat.py`) or factor (`factors/generator/carry.py`) carry logic.

3. **`T*` selection.** Pick the tenor on the reconciled grid with the best risk-adjusted carry+rolldown (e.g. `(carry+roll)/local curve vol` at that point). This is a simple argmax over the vector from (2) — no optimizer needed.

4. **Instrument template construction (§4), CN-specific:**
   - Level: bullet at `T*`, sized to hit `e*_level` from Stage 1.
   - Slope: spread with one leg at `T*`; choose `2s–T*` vs `T*–10s` by comparing which side's carry+rolldown vector value is more favorable; size to hit `e*_slope`.
   - Curvature: PCA-weighted butterfly (weights from `B` at neighboring PCA tenors), body at `T*`; size to hit `e*_curvature`.
   - Solve the 3-instrument-to-3-factor mapping as a small linear system (`B_template^T @ w = e*`), not a general QP — this is exactly the "residual fine-tuning" DOF-elimination in §4, minus the optimizer since we've fixed the instrument choice up front.

5. **Module shape / integration**, following repo conventions:
   - New module, e.g. `rates_portfolio/` (or `multiasset/rates_rolldown.py` if kept inside multiasset — needs a naming decision, see open question) exposing `interface.calibrate(cfg, store)` per the `interface.py` convention.
   - Output: weights per instrument, `e*` vs. realized PC exposure, `T*` and the carry+rolldown value that drove it — serialize into `BacktestResult.meta` (`engine/schema.py:133`), since there's no dedicated schema field for this yet and none should be added prematurely.
   - Wire into `engine/pipeline/eod.py` alongside the other `*.interface.calibrate()` calls, gated so a failure here doesn't break the rest of the pipeline (existing convention).

6. **Backtest / validation**, before this replaces any live book logic:
   - Use `curve-backtest --btype IRS` to sanity-check that `T*` selection and the fitted-curve roll-down number are stable, not noisy re-picks day to day (whipsawing `T*` would be worse than a static template).
   - Compare realized carry+rolldown captured by the template vs. a naive "always 5Y bullet" or "always the on-the-run belly" baseline.

### 7.3 Explicit non-goals for this pass

- No cvxpy dependency, no residual-covariance matrix, no turnover penalty calibration (§3, §5 items on `λ`/`κ`) — deferred until multi-tenor roll-down estimates are trusted enough to optimize over jointly.
- No `γ` carry-tilt on Stage 1 budgets (§2.1) — Stage 1 stays pure risk parity for now; carry enters only in Stage 2 via the template choice.

### 7.4 Open questions before starting

- [ ] Where should the new module live — new top-level `rates_portfolio/` (cleaner, matches other strategy dirs like `pairs/`, `futures/`) vs. inside `multiasset/` (reuses `pca_analyzer.py`/`factor_backtest.py` without cross-package imports)?
- [ ] Repo has no `portfolio/` directory despite CLAUDE.md describing one as nlopt-based — confirm whether that's stale documentation or a module that hasn't been created yet, since it affects where this should sit architecturally.
- [ ] Confirm FR007-vs-repo funding basis data is available for a proper carry net-of-funding number (§5 flags this as a known gap in the existing carry code).
