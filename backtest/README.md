# Backtest Module

Object-oriented backtesting framework for bonds, IRS contracts, and portfolios.

## Module Structure

```
backtest/
├── __init__.py           # Module exports and public API
├── __main__.py           # Main entry point with examples
├── base.py               # Abstract base Backtester class
├── attribution.py        # Campisi attribution models
├── metrics.py            # Performance metrics calculator
├── bond.py               # Bond backtester
├── irs.py                # IRS backtester
├── portfolio.py          # Portfolio backtester
├── visualization.py      # Interactive Plotly visualizations
└── README.md             # This file
```

## Components

### 1. Base Classes (`base.py`)
- **`Backtester`**: Abstract base class defining the backtesting interface

### 2. Attribution (`attribution.py`)
- **`CampisiAttribution`**: Abstract base for Campisi attribution model
- **`BondAttribution`**: Attribution for fixed-rate bonds
- **`IRSAttribution`**: Attribution for interest rate swaps

Decomposes returns into:
- **Carry**: Income/accrual component
- **Roll-down**: Time passage effect
- **Rate Change**: Interest rate impact
- **Residual**: Other effects

### 3. Metrics (`metrics.py`)
- **`PerformanceMetrics`**: Calculates comprehensive performance metrics
  - Total return (compounded)
  - Annualized return & volatility
  - Sharpe ratio
  - Maximum drawdown
  - Win rate

### 4. Backtesters

#### Bond Backtester (`bond.py`)
- **`BondBacktester`**: Backtest fixed-rate bonds
- Loads bond data and YTM time series
- Calculates clean prices and durations
- Performs attribution analysis

#### IRS Backtester (`irs.py`)
- **`IRSBacktester`**: Backtest interest rate swaps
- Supports R7D and Shibor3M curves
- Contract valuation with fixing/spot data
- Metadata tracking for contract parameters

#### Portfolio Backtester (`portfolio.py`)
- **`PortfolioBacktester`**: Combined bond and IRS positions
- Add multiple positions with different notionals
- Aggregated PnL and attribution
- Portfolio-level metrics

## Usage Examples

### 1. Bond Backtest

```python
from backtest import BondBacktester

bond = "190408.IB"
backtester = BondBacktester(bond, start_date, end_date)
backtester.run()

print(backtester.metrics)
print(backtester.attribution)
```

### 2. IRS Backtest

```python
from backtest import IRSBacktester

irs = "FR007S1Y.IR"
backtester = IRSBacktester(irs, start_date, end_date, notional=1.0)
backtester.run()

print(f"PnL: {backtester.pnl}")
print(f"Metrics: {backtester.metrics}")
```

### 3. Portfolio Backtest

```python
from backtest import PortfolioBacktester

portfolio = PortfolioBacktester(start_date, end_date)
portfolio.add_bond_position("190408.IB", 100)    # Long 100M
portfolio.add_irs_position("FR007S1Y.IR", -100)  # Short 100M (pay fixed)
portfolio.run()

results = portfolio.get_results()
print(results['position_summary'])
print(results['metrics'])
```

### 4. Convenience Function

```python
from backtest import backtest_bond_irs_portfolio

results = backtest_bond_irs_portfolio(
    bond="190408.IB",
    irs="FR007S1Y.IR",
    bond_notional=100,      # Long 100M
    irs_notional=-100,      # Short 100M (pay fixed)
    start=start_date,
    end=end_date
)
```

### 5. Interactive Visualization

```python
from backtest import backtest_bond_irs_portfolio, plot_backtest_dashboard

# Run backtest
results = backtest_bond_irs_portfolio(
    bond="190408.IB",
    irs="FR007S1Y.IR",
    bond_notional=100,
    irs_notional=-100,
    start=start_date,
    end=end_date
)

# Create interactive dashboard
fig = plot_backtest_dashboard(
    pnl=results['pnl'],
    attribution=results['attribution'],
    metrics=results['metrics'],
    capital=results['total_capital'],
    title="Portfolio Dashboard"
)

# Save and show
fig.write_html("dashboard.html")
fig.show()
```

## Position Sign Conventions

### Bonds
- **Positive notional** (+100): Long position → gains when price rises
- **Negative notional** (-100): Short position → gains when price falls

### IRS
- **Positive notional** (+100): Receive fixed / Short → gains when rates rise
- **Negative notional** (-100): Pay fixed / Long → gains when rates fall

## Running the Module

```bash
# Run all examples
python -m backtest

# Or import in your code
from backtest import BondBacktester, IRSBacktester, PortfolioBacktester
```

## Key Features

1. **Modular Design**: Each component in its own file for easy maintenance
2. **OOP Architecture**: Clean inheritance hierarchy with abstract base classes
3. **Attribution Analysis**: Comprehensive return decomposition
4. **Performance Metrics**: Full suite of risk/return metrics
5. **Portfolio Support**: Combine multiple instruments
6. **Backward Compatible**: All functionality preserved from original module

## Benefits of Modular Structure

- **Easier to Navigate**: ~150-200 lines per file vs 850+ in monolithic file
- **Better Testing**: Each component can be tested independently
- **Clearer Dependencies**: Import only what you need
- **Improved Maintenance**: Changes isolated to specific files
- **Enhanced Reusability**: Individual components can be used separately
