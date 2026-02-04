# Alpha Book Scoring System

## Overview

The Alpha Book uses a **dual-scoring approach** to balance performance across different stages:

1. **Scan-Time Preview Score** - Fast, lightweight ranking during candidate discovery
2. **Portfolio Allocation Score** - Authoritative scoring with full parameters at sizing time

This separation ensures:
- Fast candidate scanning without I/O overhead
- Flexible parameter tuning at portfolio construction
- Single source of truth for allocation decisions

---

## 1. Scan-Time Preview Score

**Purpose**: Rank and filter candidates during the initial scan without loading historical time series.

**Location**: `compute_scan_score()` in `web/atlas_alpha_tabs.py`

### Formula

For all candidates, the preview score represents **expected edge per unit risk**:

```
edge/risk = expected_move / vol
```

#### Mean-Reversion Trades

```
expected_move = |spread - mean| / halflife
composite_score_preview = max(0, expected_move / vol)
```

- **spread**: Current spread value (bp)
- **mean**: Historical mean of the spread (bp)
- **halflife**: Mean-reversion half-life in days
- **vol**: Historical volatility (bp)

**Interpretation**: How fast the spread is expected to revert to mean, normalized by risk.

#### Carry/Trend Trades

```
expected_move = carry_roll * direction_sign
composite_score_preview = max(0, expected_move / vol)
```

- **carry_roll**: 3-month carry/roll (bp) from the spread data
- **direction_sign**: +1 for BUY, -1 for SELL
- **vol**: Historical volatility (bp)

**Interpretation**: Directional carry return per unit risk.

### Usage

- Computed during `Scan Candidates` button click
- Displayed as `composite_score_preview` column in scan results
- Used for sorting when generator-side `score` is not available
- Enables fast filtering (e.g., "top 20 MR + top 20 Carry/Trend")
- Input for low-correlation diversification

### Limitations

- Does **not** include momentum (requires historical series I/O)
- Does **not** allow tuning of carry vs. MR balance
- Purely for ranking and initial filtering

---

## 2. Portfolio Allocation Score (Authoritative)

**Purpose**: Compute final scores with full parameters for risk-parity and allocation sizing.

**Location**: `compute_unified_edge_vol_score()` in `web/atlas_alpha_tabs.py`

### Formula

Unified formula for **expected daily edge** per unit risk:

```
composite_score = max(0, expected_move_per_day / risk)
```

#### Mean-Reversion Trades

```
expected_move_per_day = |spread - mean| / halflife
composite_score = max(0, expected_move_per_day / vol)
```

Same as preview, but recomputed at portfolio time with latest data.

#### Carry/Trend Trades

```
expected_move_per_day = (carry_roll + k * momentum_per_day) * direction_sign
composite_score = max(0, expected_move_per_day / vol)
```

**New component: Momentum**

```
momentum_per_day = (spread_t - spread_{t-m}) / m
```

- **m**: Momentum window (default 20 days)
- **k**: Momentum weight coefficient (default 1.0)
- **spread_t**: Current spread value
- **spread_{t-m}**: Spread value m days ago

The momentum term captures recent trend strength and direction.

### Direction Alignment

For Carry/Trend trades:

- **BUY**: `expected_move_per_day = +(carry_roll + k*momentum)`
- **SELL**: `expected_move_per_day = -(carry_roll + k*momentum)`

This ensures positive expected edge aligns with the intended trade direction. Negative expected edge after direction adjustment results in `composite_score = 0` (filtered out).

### Portfolio-Time Parameters

Adjustable in the Portfolio tab UI (currently hidden but accessible via callback):

- **mom_window** (default 20): Days for momentum calculation
- **mom_k** (default 1.0): Weight on momentum vs. carry

### Usage

1. Triggered by `RUN OPTIMIZATION` button in Portfolio tab
2. Loads historical spread series for each candidate (I/O intensive)
3. Computes momentum from time series
4. Outputs:
   - `expected_move_per_day`: Expected edge (bp/day)
   - `edge`: Same as `expected_move_per_day`
   - `risk`: Volatility (bp)
   - `composite_score`: Final score used for allocation

### Allocation Methods

After scoring, portfolio weights are computed:

| Method | Description | Formula |
|--------|-------------|---------|
| **Risk Parity** (default) | Equal risk contribution | Iterative optimization: minimize variance of `w_i * (Σ @ w) / √(w'Σw)` |
| **Score-Weighted** | Proportional to score | `w_i = score_i / Σ(score)` |
| **Inverse Volatility** | Proportional to 1/vol | `w_i = (1/vol_i) / Σ(1/vol)` |
| **Equal Weight** | Uniform allocation | `w_i = 1/N` |

---

## Score Interpretation

### Range

- **Minimum**: 0 (negative edge is clipped; trade is dropped or assigned zero weight)
- **Maximum**: Unbounded (higher = better risk-adjusted edge)

### Typical Values

| Score Range | Interpretation |
|-------------|----------------|
| 0.0 - 0.1 | Low edge; marginal trade |
| 0.1 - 0.3 | Moderate edge; acceptable |
| 0.3 - 0.5 | Strong edge; high conviction |
| > 0.5 | Exceptional edge; rare |

### Use Cases

- **Filtering**: Drop candidates with `composite_score < 0.05`
- **Ranking**: Sort by score descending for top-N selection
- **Weighting**: Allocate capital proportional to score
- **Risk Budgeting**: Combine score with risk-parity for balanced allocation

---

## Example Calculations

### Mean-Reversion Trade

```
Spread: TBond210009.IB-TBondCurve5Y
Current: 3.15 bp
Mean: 0.50 bp
Halflife: 12 days
Vol: 2.0 bp
Direction: SELL (spread > mean)

Scan-time:
  expected_move = |3.15 - 0.50| / 12 = 0.221 bp/day
  composite_score_preview = 0.221 / 2.0 = 0.110

Portfolio-time: (same, no momentum for MR)
  composite_score = 0.110
```

### Carry/Trend Trade

```
Spread: FR007S5Y-FR007S10Y (5s10s swap spread)
Carry: 1.5 bp/quarter → 0.5 bp/month
Vol: 3.0 bp
Direction: BUY
Mom window: 20 days
Current spread: 15.0 bp
Spread 20d ago: 12.0 bp

Scan-time:
  expected_move = 0.5 * (+1) = 0.5 bp/month (no momentum)
  composite_score_preview = 0.5 / 3.0 = 0.167

Portfolio-time:
  momentum_per_day = (15.0 - 12.0) / 20 = 0.15 bp/day
  expected_move_per_day = (0.5/30 + 1.0*0.15) * (+1) = 0.167 bp/day
  composite_score = 0.167 / 3.0 = 0.056
```

(Note: In the second example, carry is monthly so divided by 30 for daily; momentum boosts the edge.)

---

## Implementation Notes

### Data Sources

- **Scan-time**: Uses pre-computed statistics from `Alpha-spreadsrt.pkl` (StatInfo tables)
- **Portfolio-time**: Loads time series from source pickle files (e.g., `TBond-spds.pkl`, `IRS-pxspds.pkl`)

### Performance

- **Scan**: ~0.5-2 seconds for 50 candidates (no file I/O for each candidate)
- **Portfolio**: ~3-10 seconds for 50 candidates (loads historical series for momentum)

### Future Enhancements

1. **Carry Penalty**: Add a parameter to penalize trades with negative carry (e.g., `carry_factor = max(0, carry)`)
2. **Halflife Filter**: Skip MR trades with halflife > 60 days (too slow)
3. **Exit Z-score**: Add expected edge reduction when z-score approaches exit threshold
4. **Transaction Costs**: Subtract estimated bid-ask spread from expected edge

---

## References

- **Main implementation**: `web/atlas_alpha_tabs.py`
  - `compute_scan_score()`: Lines ~671-750
  - `compute_unified_edge_vol_score()`: Lines ~752-850
  - `scan_candidates()` callback: Lines ~1254-1570
  - `run_scoring()` callback: Lines ~1900-2100

- **Data generators**: `curves/refreshers/alpha.py`
  - `load_alpha_candidates()`: Scans all spread types and pre-filters

- **Allocation engine**: `web/atlas_alpha_tabs.py`
  - `_compute_risk_parity_weights()`: Lines ~478-604

---

**Last Updated**: 2026-02-04  
**Author**: AtlasNexus Alpha Book Team
