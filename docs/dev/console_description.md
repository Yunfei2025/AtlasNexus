# AtlasNexus Financial Engineering Console

## Overview
AtlasNexus is a multi-asset fixed-income and derivatives dashboard built in Python (Dash). It provides real-time market analysis, pricing, and portfolio monitoring across multiple asset classes.

## Main Consoles

### Daily Console (Port 8080)
**Purpose:** End-of-day reporting, historical analysis, and overnight risk monitoring.

### Intraday Console (Port 8081)
**Purpose:** High-frequency monitoring, real-time pricing, and intraday strategy execution.

---

## Key Sections & Tabs

### 1. **MARKET** Section - Pricer Tab
**What it shows:**
- Real-time bid/offer pricing for multiple bond types
- Swap pricing and derivatives quotes
- Dynamic filtering by asset type and maturity term

**Asset Classes:**
- **Bonds:** Treasury Bonds (TBond), Policy Bank Bonds (CBond), Local Gov Bonds (LBond), Green Bonds (GBond)
- **Swaps:** Interest Rate Swaps (FR007 IRS), Repo Pairs, Butterfly spreads
- **Futures:** Term basis, net basis contracts

**Key Columns:**
- Ticker, Coupon, Maturity Year, Current Yield
- Z-Score (statistical measure), Stationarity status
- Bid/Offer/Mid prices, price changes (bp = basis points)
- Greeks: Carry (3-month), Roll (3-month), Total (Carry+Roll)

**Interactions:**
- Dropdown selectors for asset type and term range (1-3Y, 3-5Y, 5-7Y, 7-10Y, 10-30Y)
- Table sorting and filtering
- Real-time updates via interval polling (controlled by `GRAPH_INTERVAL` variable)

---

### 2. **SPREAD Analysis** Tab
**What it shows:**
- Multi-dimensional spread analysis across different instrument types
- Pattern recognition and correlation studies

**Available Spread Types:**
- **Bonds:** Sector PCA spreads, Spread Regression, Treasury/Policy/Local/Corporate spreads
- **Swaps:** Swap spreads, Bond-Swap spreads
- **Futures:** Term basis, Net basis

**Key Features:**
- Radio button selection of spread methodology
- Dropdown for filtering (e.g., contract seasons/months)
- Time-series visualization and analytics

---

### 3. **VOLATILITY** Tabs
**What it shows:**
- Implied and historical volatility surfaces
- Term structure analysis
- Volatility skew and smile patterns

**Key Metrics:**
- Vol surfaces for different underlyings
- Greeks: Vega exposure monitoring

---

### 4. **TREND** Tabs
**What it shows:**
- Momentum and trend indicators
- Historical performance trends
- Breakout signals and support/resistance levels

**Key Features:**
- Time-series charting
- Technical indicator overlays
- Statistical anomaly detection

---

### 5. **ALPHA** Tabs
**What it shows:**
- Strategy performance attribution
- Factor exposure analysis
- Excess return (alpha) decomposition

**Key Features:**
- Performance metrics by strategy/book
- Factor-level P&L breakdown
- Risk-adjusted return metrics (Sharpe ratio, Information ratio)

---

### 6. **FACTOR BACKTEST** Tabs
**What it shows:**
- Historical factor performance simulation
- Strategy backtesting results
- Monte Carlo analysis

**Key Features:**
- Backtest period selection
- Parameter sensitivity analysis
- Equity curves and drawdown analysis

---

### 7. **MULTI-ASSET** Tabs
**What it shows:**
- Cross-asset correlation matrices
- Portfolio-level risk aggregation
- Hedge effectiveness analysis

**Key Features:**
- Asset allocation views
- Correlation heatmaps
- Diversification metrics

---

### 8. **FIXED INCOME** (FI) Tabs
**What it shows:**
- Bond curve calibration and analysis
- Interest rate structure modeling
- Credit spread analysis

**Key Features:**
- Curve fitting visualizations
- Scenario analysis (rate shocks, credit events)
- Portfolio duration and convexity metrics

---

## Design Theme (Current)
```
Background (Main):    #082255 (deep navy)
Background (Cards):   #0c2b64 (slightly lighter navy)
Input Fields:         #112e66 (navy)
Text (Primary):       #ffffff (white)
Text (Secondary):     #aab0c0 (light gray)
Accent:              #3498db (bright blue)
Accent Light:        #5dade2 (lighter blue)
Table Header:        #061E44 (very dark navy)
Positive P&L:        #27ae60 (green)
Negative P&L:        #e74c3c (red)
```

---

## Key Interactive Patterns
1. **Radio & Dropdown Selectors** – Filter by asset type, maturity range, methodology
2. **Data Tables** – Sortable, filterable, with color-coded values (red/green for P&L)
3. **Charts & Graphs** – Time-series plots, surface plots, heatmaps
4. **Auto-Refresh** – Data updates every `GRAPH_INTERVAL` seconds (configurable)
5. **Status Headers** – Shows latest run timestamp, data freshness, current selections

---

## Use Case for Claude Design
Use this information to build a **React version** of the AtlasNexus interface. The resulting components can serve as:
- Interactive prototypes for UI/UX feedback
- Reference designs for frontend migration
- Mockups for stakeholder presentations
