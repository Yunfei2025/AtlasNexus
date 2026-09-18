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

## 7. Implementation plan (scoped: simple pro-rata tilt, not the §4 anchor template)

**Scope decision, revised:** a standalone comparison test (real CGB data, 2026-09-16, see §7.5) showed the §4 anchor template (bullet/spread/butterfly solved as a 3×3 linear system) adds real complexity — picking a slope leg and curvature wings that don't degenerate, solving a linear system per rebalance — for a benefit that turned out to be small: a much simpler **pro-rata tilt toward the single best-rolldown tenor** reproduces almost all of the effect, at the cost of a small, quantified drift in the Slope/Curvature risk budget. Given CN rates currently only gives us one reliable roll-down read (`T*`), that complexity isn't earning its keep yet. §4's anchor template stays documented as the natural next step if the tilt's factor drift turns out to matter in backtest, or once multiple tenors' roll-down estimates are trusted simultaneously (at which point §3's general optimizer is the real target, not the anchor template either).

### 7.1 The math, worked through on real CGB data (2026-09-16)

Two separate calculations, easy to conflate — kept separate deliberately so carry/rolldown never changes *how much* risk is taken, only *which tenor* carries it.

**Step A — Stage 1, `e*` (how much risk, per factor).** Unchanged from §2, and untouched by carry: closed-form risk parity across Level/Slope/Curvature using PC vols from trailing daily yield changes. Carry never enters this step.

**Step B — carry + rolldown per tenor (which tenor is "cheap to hold").**

```
carry(T)  = yield(T) − yield(funding tenor)                     # yield pickup, bp
roll(T)   = duration(T) × [yield(T) − yield(T − 3m)] × 4         # price gain from sliding down the curve, annualized
```

`yield(T − 3m)` is read off the same curve by linear interpolation between quoted tenors. Worked example, CN 1Y used as the funding proxy:

| Tenor | Duration | Carry (bp) | Roll (bp) | Total (bp) |
|---|---|---|---|---|
| 1Y | 0.95 | 0 | 0 | 0 |
| 2Y | 1.90 | 1.4 | 2.6 | 4.0 |
| 5Y | 4.50 | 18.0 | 25.0 | 43.0 |
| 10Y | 8.50 | 45.6 | 46.8 | 92.4 |
| **20Y** | 13.00 | **90.0** | **57.8** | **147.8** |
| 30Y | 17.00 | 90.7 | 1.2 | 91.9 |

`T* = argmax(risk-adjusted total)` → **20Y**. Note 30Y has almost the same carry as 20Y but almost no roll, because the curve is nearly flat 20Y→30Y — carry alone would have missed this; roll-down is what separates them.

**Step C — the tilt itself (where the rolldown weight enters the portfolio).**

```
w_tilted            = w_baseline                              # start from Stage-1's no-rolldown weights
w_tilted[T*]        += tilt_pct × Σ|w_baseline|                # add capital at the best-rolldown tenor
w_tilted[other t]    -= tilt_pct × |w_baseline[t]|              # funded pro-rata to each tenor's existing weight
```

With `tilt_pct = 20%` on the real book (`Σ|w_baseline| = 753.4`), 150.7 DV01-units move onto 20Y (130.2 → 280.9), funded by shrinking every other tenor 20% of its own weight (e.g. 30Y: 330.1 → 250.3, a cut of 79.8).

**Why this only costs a *little* factor drift, not a lot:** funding is proportional to each tenor's existing weight, and on the CN grid every tenor has equal Level loading (`CN_DETERMINISTIC_WEIGHTS['Level'] = [1/6]*6`), so the pro-rata cut exactly preserves total Level exposure — no drift there by construction. Slope and Curvature loadings are *not* equal across tenors, so parking extra capital at 20Y (which has non-trivial Slope/Curvature loading) does pull those off target: in the worked example, Slope drifted +11.8% and Curvature −9.6% from `e*`. That drift is the entire price of skipping the §4 anchor template's equality constraint — nothing else changes.

### 7.2 What already exists (reuse, don't rebuild)

- `multiasset/pca_analyzer.py:34,47` `CN_IR_TENORS`, `CN_DETERMINISTIC_WEIGHTS` — Level/Slope/Curvature loadings `B` on the CGB 6-tenor grid (1/2/5/10/20/30Y).
- `multiasset/utils.py` `get_default_sensitivities(tenor)['IRDL']` — modified duration per tenor, used directly in the roll formula above.
- `multiasset/config.py:150` `CURVE_CONFIG['CN']` → `database-px.pkl['CGB']` — real CGB yield history, no Wind dependency, used as-is in the test.
- `multiasset/factor_backtest.py` `compute_ewma_factor_vols`/`compute_ewma_factor_covariance` — production PC-vol source for Stage 1 (`σ_k`); the test used a simple trailing-1y std as a stand-in, production should use these instead.
- None of the above currently touches carry/rolldown — confirmed no reuse conflict.

### 7.3 Status

Built and merged — this is not a plan anymore, it's what's in the repo:

- [x] `multiasset/rolldown.py` — `carry_rolldown`, `select_t_star`, `tilt_weights`, `factor_drift`, `run_rolldown_tilt`. Pure functions, no I/O, ~140 lines total.
- [x] `multiasset/interface.py::calibrate_rolldown(cfg, store)` — loads real CGB data via `cfg.input_dir`, runs Stage 1 + the tilt, returns a JSON-serializable dict for `BacktestResult.meta`. `cfg.params['cgb_rolldown_tilt_pct']` overrides the tilt fraction (default 0.20).
- [x] Wired into `engine/pipeline/eod.py` as its own gated step (`cgb_rolldown`), isolated the same way `otr_ofr` is — a failure here doesn't break the rest of the EOD run.
- [x] `tests/test_multiasset_rolldown.py` — 4 tests against a synthetic CGB-shaped curve, verifying the belly-vs-flat-long-end carry/roll behavior, `T*` selection, and that the tilt preserves Level exactly while Slope/Curvature drift as expected.

That's the whole implementation. There is exactly **one** genuinely open item, and it's not a build task:

- [ ] **Calibrate `tilt_pct` via backtest.** Currently a guess (20%) picked to make the worked example legible, not derived from data. Before this feeds a live book, run it through `curve-backtest`-style history to sanity-check: realized carry+rolldown captured vs. no-tilt, how often `T*` flips day to day (a noisy `T*` would whipsaw the book — if so, add a minimum-holding-period rule), and whether Slope/Curvature drift ever gets large in stress periods. This is analysis, not new code — the module already takes `tilt_pct` as a parameter.

Everything else previously listed here (tenor-grid reconciliation for IRS, γ carry-tilt on Stage 1, the §4 anchor template, cvxpy/§3) is explicitly **not** being built now — see §7.4.

### 7.4 Explicit non-goals for this pass

- No §4 anchor template (bullet/spread/butterfly, 3×3 linear solve) — only revisit if backtest shows the drift matters.
- No cvxpy, no residual-covariance matrix, no turnover-penalty calibration (§3, §5 items on `λ`/`κ`).
- No `γ` carry-tilt on Stage 1 budgets (§2.1) — Stage 1 stays pure risk parity; carry enters only via the Step C tilt.
- No IRS/FR007 tenor-grid reconciliation yet — this pass is CGB-only, which has one native, un-mapped tenor grid, sidestepping that problem entirely.

### 7.5 Resolved from earlier open questions

- **Module placement:** inside `multiasset/` (not a new top-level package) — it reuses `pca_analyzer.py`/`factor_backtest.py`/`utils.py` directly, and a new top-level package would need cross-package imports for no benefit at this scope.
- **`portfolio/` vs `multiasset/` per CLAUDE.md:** confirmed via code search that no `portfolio/` directory exists; the nlopt-based description in CLAUDE.md is stale — the real risk-parity/optimizer code lives in `multiasset/factor_optimizer.py` using `scipy.optimize.SLSQP`. Flagging for a separate CLAUDE.md correction, out of scope for this doc.
- **Validated end-to-end:** the full calculation above (carry/roll table, `T*` selection, pro-rata tilt, factor-drift check) was run against real `database-px.pkl['CGB']` data with no synthetic inputs and no Wind dependency — see the standalone script referenced in the implementation PR.
