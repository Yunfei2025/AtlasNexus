# Leg Mapping Implementation Summary

## Overview
Added comprehensive leg (underlying instrument) mapping to the Portfolio Allocation Snapshot in the Alpha Book. The Portfolio Snapshot now displays the underlying instruments (Leg 1 and Leg 2) for each spread trade.

## Changes Made

### 1. **Added Leg Resolution Functions to `/web/tabs/alpha/data.py`**

#### Core Functions Added:
- **`resolve_legs(stype, tid, duration=0.0, ld=None)`** - Main function that maps spread types to their underlying legs
- **`_load_leg_data()`** - Loads instrument reference data (on-the-run bonds, futures definitions, IRS mapping)
- **`_parse_repo_spread_legs(spread_id)`** - Parses Repo7d and Basis spreads into their component IRS rates
- **`_tenor_str_to_years(tenor)`** - Utility to convert tenor strings (e.g., "6M", "1Y") to years

#### Supported Spread Types and Mappings:

| Spread Type | Example | Leg 1 | Leg 2 |
|---|---|---|---|
| **TenorSpread** | CGB-10s30s | OTR CGB 10Y | OTR CGB 30Y |
| **TenorSpread** | CDBCGB-10y | OTR CDB 10Y | OTR CGB 10Y |
| **TenorSpread** | CDB-5s10s | OTR CDB 5Y | OTR CDB 10Y |
| **SwapSpread** | Repo7d-9m2y | FR007S9M.IR | FR007S2Y.IR |
| **SwapSpread** | Basis-5y | SHI3MS5Y.IR | FR007S5Y.IR |
| **NetBasis** | T, TF, TS, TL | CTD Bond Code | Futures Contract |
| **TermBasis** | T, TF, TS, TL | Front Contract | Next Quarter Contract |
| **FuturesSwap** | T | T2609 (front) | FR007S10Y.IR |
| **FuturesSwap** | TF | TF2609 (front) | FR007S5Y.IR |
| **FuturesSwap** | TS | TS2609 (front) | FR007S2Y.IR |
| **FuturesSwap** | TL | TL2609 (front) | FR007S10Y.IR |
| **TBondCurve** | Bond ID | Bond Code | Nearest Duration Reference Bond |
| **TBondSwap** | Bond ID | Bond Code | Nearest Duration Reference Bond |
| **CBondCurve** | Bond ID | Bond Code | Nearest Duration Reference Bond |
| **CBondSwap** | Bond ID | Bond Code | Nearest Duration Reference Bond |

### 2. **Updated `/web/tabs/alpha/callbacks/portfolio.py`**

#### Changes:
1. **Added Imports:**
   ```python
   from ..data import (
       ...
       resolve_legs, _load_leg_data,
   )
   ```

2. **Added Step F - Leg Resolution in `run_scoring` callback:**
   - Loads leg data once per optimization run
   - Iterates through each trade in the portfolio
   - Calls `resolve_legs()` for each spread with its duration
   - Adds `Leg1` and `Leg2` columns to the result DataFrame

3. **Updated Display Columns:**
   - Added `'Leg1'` and `'Leg2'` to `display_cols` list
   - Positioned after spread_type and before style for logical grouping

4. **Updated Column Labels:**
   - Added `'Leg1': 'leg 1'` and `'Leg2': 'leg 2'` to `_port_col_labels` dictionary

## Usage

### In Portfolio Allocation Snapshot
When you run the optimization in the Portfolio subtab, the resulting table now shows:

```
ID                | type          | leg 1        | leg 2        | regime | direction | ...
CGB-10s30s        | TenorSpread   | 260010.IB    | 2600002.IB   | ...    | BUY       | ...
CDBCGB-10y        | TenorSpread   | 260205.IB    | 260010.IB    | ...    | SELL      | ...
Repo7d-9m2y       | SwapSpread    | FR007S9M.IR  | FR007S2Y.IR  | ...    | BUY       | ...
T                 | FuturesSwap   | T2609        | FR007S10Y.IR | ...    | BUY       | ...
```

## Technical Details

### Data Loading
- **OTR Bond Selection:** Uses turnover ratio (volume/balance) within tenor bands (1Y-30Y) to identify most liquid on-the-run bond
- **Reference Bonds:** Loads credit valuation reference (cvref) data to find nearest duration reference bond for bond-curve/swap trades
- **Futures Info:** Loads futures instrument definitions to resolve contract codes and identify front/next contracts
- **IRS Mapping:** Pre-defined mapping for futures-swap trades:
  - TS (2Y) → FR007S2Y.IR
  - TF (5Y) → FR007S5Y.IR  
  - T (10Y) → FR007S10Y.IR
  - TL (30Y) → FR007S10Y.IR (no 30Y swap, use 10Y)

### Error Handling
- Graceful fallback if leg data fails to load (returns empty strings)
- Validation of duration values and tenor conversions
- Handles missing or malformed instrument definitions

## Testing
All functions tested and verified:
- ✓ Repo7d spread parsing (Repo7d-6m1y, Repo7d-9m2y)
- ✓ Basis spread parsing (Basis-5y)
- ✓ Leg data loading structure validation
- ✓ Import and integration with callback system

## Notes for Future Use

1. **On-the-Run Selection:** The OTR selection is based on turnover within tenor bands and recomputed each time `_load_leg_data()` is called. Consider caching if performance becomes an issue.

2. **Basis Spread Extension:** The Basis spread implementation currently handles Basis-5y. Additional basis spreads (e.g., Basis-2y, Basis-10y) can be added by extending the tenor mapping.

3. **Shared with Beta Book:** The same leg resolution logic can be imported and used in the Beta book's Risk table if needed (it's currently duplicated in `web/tabs/beta/callbacks/risk.py`).

4. **Column Width:** The leg columns display instrument codes which can be long (e.g., "260010.IB"). The Dash table's horizontal scrolling will accommodate this.
