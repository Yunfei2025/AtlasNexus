# Alpha Book Spread Calculation Audit

## Summary

**Issue Found**: Direction (BUY/SELL) logic was **inverted** in the Candidates subtab.

**Root Cause**: Two bugs in `web/tabs/alpha/callbacks/candidates.py`:
1. Line 272-274: Direction filters applied inverted z-score thresholds
2. Line 284: Direction assignment inverted the z-score comparison

**Fix Applied**: Corrected both lines to match the industry standard and UI labels.

---

## Industry Standard (Confirmed)

**Spread Definition**: Spreads are computed as **higher-yielding asset minus lower-yielding asset**:
- `CGB-10s30s = Y_30y - Y_10y` (longer tenor minus shorter tenor)
- `CDBCGB-5y = Y_CDB - Y_CGB` (policy bank vs. treasury)
- `CGBRepo7d-1y = Y_CGB - Y_FR007S1Y` (bond vs. funding rate)

**Direction Terminology**:
- **BUY the spread** = spread is WIDE (cheap) (z < -threshold)
  - Action: Buy higher-yielding leg, sell lower-yielding leg
  - Expectation: Spread will **narrow**
  
- **SELL the spread** = spread is TIGHT (expensive) (z > +threshold)
  - Action: Sell higher-yielding leg, buy lower-yielding leg
  - Expectation: Spread will **widen**

---

## Spread Calculations Verified

All spread definitions in `web/tabs/alpha/data.py` are **consistent with industry standard**:

### TenorSpread (lines 137-143)
```python
'CGB-10s30s': CGB[30y] - CGB[10y]  ✓ longer - shorter
'CGB-5s10s': CGB[10y] - CGB[5y]    ✓ longer - shorter
'CDBCGB-5y': CDB[5y] - CGB[5y]     ✓ risky - safe
```

### Bond-vs-Repo (lines 152-158)
```python
'CGBRepo7d-1y': CGB[1y] - FR007S1Y  ✓ bond - funding
'ICPRepo7d-3m': ICP[3m] - FR007S3M  ✓ cd - funding
```

**Conclusion**: Spread calculations follow correct convention. Issue was purely in direction labeling.

---

## Duration Multiplier Usage (Verified)

Duration calculations also follow industry standard:

- **TenorSpread** (line 456): Uses **first (shorter) tenor**
  - `CGB-10s30s` → duration of 10y (shorter leg drives DV01 in steepener position)
  
- **SwapSpread** (line 472): Uses **second (longer) tenor** for pairs/flies
  - `Repo7d-1y3y` → duration of 3y (longer leg drives DV01)
  - `Basis-1y` → duration of 1y (single tenor)

**Note**: Different conventions for different spread types reflects underlying market mechanics:
- Curve steepeners are hedged by the shorter tenor
- Repo basis is hedged by the longer tenor

---

## Borrow Cost Calculation (Verified)

Borrow costs in `_get_borrow_cost_annual_bp()` (lines 495-563) correctly split long/short costs:

**TenorSpread example** (CGB-10s30s):
- **BUY spread** (steepener): Long 30y, short 10y → pay borrow on 30y
- **SELL spread** (flattener): Short 30y, long 10y → pay borrow on 10y
- Cost assignment: `(longer_cost, shorter_cost)` ✓

---

## Fixes Applied

### candidates.py Line 272-274
**Before**:
```python
if direction == 'buy':
    df_all = df_all[(~is_mr_row) | (df_all['Zscore'] >= z_thd)].copy()   # ❌ wrong
elif direction == 'sell':
    df_all = df_all[(~is_mr_row) | (df_all['Zscore'] <= -z_thd)].copy()  # ❌ wrong
```

**After**:
```python
if direction == 'buy':
    df_all = df_all[(~is_mr_row) | (df_all['Zscore'] <= -z_thd)].copy()  # ✓ z < -thd
elif direction == 'sell':
    df_all = df_all[(~is_mr_row) | (df_all['Zscore'] >= z_thd)].copy()   # ✓ z > +thd
```

### candidates.py Line 284
**Before**:
```python
df_all['direction'] = df_all['Zscore'].apply(lambda z: 'BUY' if float(z) > 0 else 'SELL')  # ❌ wrong
```

**After**:
```python
df_all['direction'] = df_all['Zscore'].apply(lambda z: 'BUY' if float(z) < 0 else 'SELL')  # ✓ correct
```

### layouts.py Line 163
Added clarifying note to Direction filter:
```
"BUY: spread is TIGHT (cheap) → expect to widen. SELL: spread is WIDE (expensive) → expect to narrow."
```

---

## Impact

- **Candidates table**: Direction now correctly reflects z-score sign
- **Direction filter**: "BUY" now correctly filters z < -threshold, "SELL" filters z > +threshold
- **Correlation check & portfolio optimization**: Will now use correct directions
- **Risk metrics**: Borrow costs will be applied with correct long/short orientation

---

## Related Code (Not Changed)

All downstream uses of `direction` field are correctly implemented:
- `callbacks.py` line 547-555: Correctly maps BUY→green, SELL→red
- `scoring.py`: Directions used only for display; no calculation impact
- Backtest engine: Uses regime (MR vs trend), not direction field
