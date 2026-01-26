# Alpha Book — Non-Mean-Reverting RV (Bond-Swap) + Concrete CGB–FR007 Trend Signal

This note consolidates the discussion on **non-mean-reverting** RV trades (esp. bond-swap) and defines a **concrete trend/carry signal** for the CGB–FR007 swap spread used in AtlasNexus.

## 1) Why bond-swap is often not mean-reverting
Bond-swap (bond vs IRS) can trend because it is driven by slow-moving and regime-dependent forces:

- Funding / repo conditions and balance sheet constraints
- Policy expectations and term premium shifts
- Supply–demand (issuance, bank demand, flow-driven markets)
- Hedging pressure (swap receiving/paying waves)

So a pure OU/z-score entry can be structurally wrong: the “mean” can drift for months.

## 2) Framework for non-MR RV trades in Alpha Book
Treat bond-swap trades as **Carry/Trend style**, not MR.

### A) Two-layer signal: Trend + Carry
- **Trend** answers “directional drift exists?”
- **Carry** answers “are we being paid to hold the position while waiting?”

Only size up when both agree; size down when they disagree.

### B) Regime gating (optional but recommended)
Before taking trend signals, require “trend-friendly” regimes, e.g.:

- Efficiency Ratio (Kaufman) above a threshold (trend strength)
- Positive serial correlation (autocorr of daily changes)
- Optionally: Hurst / Variance Ratio / ADX-like proxies if you have OHLC

Reference implementation ideas exist in:
- `bin-v4.0/futures/backtest/regime.py`

### C) Correlation gating (same idea as Beta Book)
Even “market-neutral” RV trades can crowd together. Use:

- 1Y+ correlation of **daily changes** (`diff`), not `pct_change`
- Gate or scale positions if max |corr| exceeds threshold (e.g. 0.3–0.5)

(Alpha Book Candidates tab already follows this “diff + heatmap + low-corr pairs” pattern.)

---

## 3) Concrete signal: CGB–FR007 (example uses 5Y)

### 3.1 Define the tradable spread series
Use the same definition already present in the repo trend generator:

- `bin-v4.0/curves/generators/trend.py`

For 5Y:

\[
S_t = y^{CGB}_{t,5Y} - r^{FR007}_{t,5Y}
\]

In code terms this corresponds to: `TBond-FR007:5Y`.

(There is also `TBond-FR007:1Y`.)

Interpretation:
- Level of \(S_t\) is a carry proxy for a “bond vs swap package” (spread pickup).
- Changes in \(S_t\) reflect bond–swap basis drifting (not necessarily mean reverting).

### 3.2 Trend state: Directional-Change confirmation (primary)
Use the repo’s directional-change event logic:

- `bin-v4.0/curves/calibration/trend.py`

It emits events:
- `Upward Trend Confirmed`
- `Downward Trend Confirmed`
- plus local extrema markers

**Trend state machine**
- If the most recent event is `Upward Trend Confirmed` ⇒ `trend_state = +1`
- If the most recent event is `Downward Trend Confirmed` ⇒ `trend_state = -1`
- Otherwise keep previous state

**Threshold parameter**
- The function uses a *relative* threshold `theta` on the series level.
- Practical starting default: `theta = 0.02`.

If your \(S_t\) is stored in bp and can be near zero, prefer an absolute-threshold variant (recommended enhancement): trigger on `abs(S_t - ext) >= theta_bp`.

### 3.3 Carry filter (secondary)
Define a simple carry condition from the level:

- `carry_ok = (S_t >= 0)`
- Optional robustness: require `S_t` above a small buffer, e.g. `S_t >= +2bp`

### 3.4 Momentum confirmation (secondary)
To avoid whipsaws, confirm that recent drift agrees with trend state:

- Compute 20d change: \( M_{20}(t) = S_t - S_{t-20} \)
- Require: `sign(M20) == trend_state`
- Optional normalization: \( m_{20} = M_{20} / \sigma_{60} \) and require `|m20| >= 0.5`

### 3.5 Entry rule (daily, EOD)
Open/hold position on the spread series \(S\) as:

- If `trend_state = +1` and `carry_ok` and momentum-confirmed ⇒ **LONG spread**
- If `trend_state = -1` and (optional) `S_t <= 0` and momentum-confirmed ⇒ **SHORT spread**
- Otherwise ⇒ **FLAT** or **HALF SIZE** (depending on risk appetite)

Note: “LONG spread” means your PnL is aligned to \(+\Delta S\). Map this to execution legs (bond + swap hedge) using your DV01 matching convention.

### 3.6 Exit rules
Exit to flat when any triggers:

1) Opposite directional-change confirmation event appears
2) Carry invalidates:
   - long-spread exit if \(S_t\) falls below 0 (or below buffer)
3) Trailing stop on spread move:
   - Track best favorable \(S\) since entry; exit if drawdown exceeds `1.5 * rolling_std_60` (spread units)
4) Time stop:
   - exit after `max_hold = 60` trading days if trend hasn’t progressed

### 3.7 Risk sizing (risk-parity friendly)
Size each active bond-swap trade by a target risk unit:

- Estimate daily vol of spread changes: `sigma = std(diff(S), 60)`
- Set weight \( w \propto 1/\sigma \) (inverse-vol proxy) or use a covariance-based risk parity across selected trades
- Cap per-trade DV01 / notional using desk limits

### 3.8 Correlation gating (must-have for baskets)
For the Alpha basket:

- Compute correlations on daily changes: `corr(diff(S_i), diff(S_j))` over 252d+
- Enforce:
  - hard gate: require max |corr| ≤ 0.3–0.5
  - or soft scale: `weight_i *= max(0, 1 - (|corr|max - thd)/(1-thd))`

---

## 4) Default parameter set (starter)

- Tenor: 5Y (also track 1Y as a cross-check)
- Directional-change threshold: `theta = 0.02` (relative)
- Momentum: 20d; normalization vol: 60d; require `|m20| >= 0.5`
- Time stop: 60d
- Trailing stop: `1.5 * std_60` (spread units)
- Correlation lookback: 252d; max |corr|: 0.3–0.5

## 5) Where this lives in the repo (pointers)

- Trend series construction: `bin-v4.0/curves/generators/trend.py`
- Directional-change events: `bin-v4.0/curves/calibration/trend.py`
- Regime feature inspiration: `bin-v4.0/futures/backtest/regime.py`
- Alpha Book UI: `bin-v4.0/web/atlas_alpha_tabs.py`

## 6) Recommended next enhancement (optional)
The current Alpha backtest “Carry” mode is still z-score-centric. For bond-swap, add a true trend-mode backtest:

- directional-change trend state + carry filter + trailing stop + time stop
- evaluate by spread PnL proxy and correlation-adjusted basket performance
