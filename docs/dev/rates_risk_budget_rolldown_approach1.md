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
