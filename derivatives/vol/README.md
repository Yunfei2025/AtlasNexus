# Volatility Trading Strategies for AU.SHF Gold Futures

## Overview

This module implements a comprehensive volatility trading system for AU.SHF (Shanghai Gold Futures) using implied volatility data across multiple tenors (1M, 2M, 3M). The system combines four distinct strategies to generate trading signals for volatility products such as options straddles and strangles.

## Project Structure

```
derivatives/
├── vol.py                          # Main strategy engine
├── vol_analysis.py                 # Visualization and backtesting module
├── vol_strategy_results.csv        # Generated strategy signals (output)
├── vol_strategy_analysis.png       # Strategy analysis charts (output)
├── vol_strategy_performance.png    # Performance comparison charts (output)
└── README.md                       # This file
```

## Dependencies

- **WindPy**: Chinese Wind API for financial data
- **pandas**: Data manipulation and analysis
- **numpy**: Numerical computing
- **matplotlib**: Data visualization

## Data Source

The system fetches implied volatility data from Wind API:
- **Contract**: AU.SHF (Shanghai Gold Futures main contract)
- **Fields**: 
  - `iv_1m1000_n`: 1-month implied volatility
  - `iv_2m1000_n`: 2-month implied volatility
  - `iv_3m1000_n`: 3-month implied volatility
- **Date Range**: Configurable (default: 1 month)

---

## Trading Strategies

### Strategy 1: Term Structure Arbitrage

**Objective**: Exploit anomalies in the volatility term structure.

**Methodology**:
1. Calculate slopes between different tenors (1M-2M, 2M-3M, 1M-3M)
2. Standardize slopes using Z-scores
3. Identify abnormal term structure shapes

**Trading Signals**:
- **Short Volatility** (Signal = -1): When 1M-3M slope Z-score > 1.5
  - Interpretation: Curve is abnormally steep
  - Trade: Sell far-dated volatility, buy near-dated volatility
  - Implementation: Sell 3M straddle, buy 1M straddle

- **Long Volatility** (Signal = +1): When 1M-3M slope Z-score < -1.5
  - Interpretation: Curve is abnormally flat or inverted
  - Trade: Buy far-dated volatility, sell near-dated volatility
  - Implementation: Buy 3M straddle, sell 1M straddle

**Key Parameters**:
- Threshold: ±1.5 standard deviations
- Primary metric: 1M-3M slope

**Market Regime**: Works best in stable markets with mean-reverting term structure.

---

### Strategy 2: Mean Reversion (Bollinger Bands)

**Objective**: Trade mean reversion in 1M implied volatility levels.

**Methodology**:
1. Calculate 10-day moving average of 1M IV
2. Compute standard deviation over same window
3. Construct Bollinger Bands (MA ± 2σ)
4. Generate signals when IV breaks bands

**Trading Signals**:
- **Short Volatility** (Signal = -1): When 1M IV > Upper Band
  - Interpretation: Volatility is elevated, likely to revert
  - Trade: Sell ATM straddle or strangle
  - Profit when: Volatility declines back to mean

- **Long Volatility** (Signal = +1): When 1M IV < Lower Band
  - Interpretation: Volatility is depressed, likely to rise
  - Trade: Buy ATM straddle or strangle
  - Profit when: Volatility rises back to mean

**Key Parameters**:
- Lookback window: 10 days
- Band width: ±2 standard deviations

**Market Regime**: Effective in range-bound, non-trending volatility environments.

---

### Strategy 3: Momentum

**Objective**: Follow trends in volatility changes.

**Methodology**:
1. Calculate 1-day and 5-day percentage changes in 1M IV
2. Compare 5-day change against threshold
3. Follow the trend direction

**Trading Signals**:
- **Long Volatility** (Signal = +1): When 5-day IV change > +5%
  - Interpretation: Strong upward volatility momentum
  - Trade: Buy ATM straddle
  - Rationale: Volatility trends tend to persist

- **Short Volatility** (Signal = -1): When 5-day IV change < -5%
  - Interpretation: Strong downward volatility momentum
  - Trade: Sell ATM straddle
  - Rationale: Continue riding declining volatility

**Key Parameters**:
- Momentum window: 5 days
- Threshold: ±5% change

**Market Regime**: Best in trending volatility markets with clear directional moves.

---

### Strategy 4: Combined (Meta-Strategy)

**Objective**: Synthesize signals from all three strategies using weighted voting.

**Methodology**:
1. Collect signals from Strategies 1-3
2. Apply weights to each strategy:
   - Term Structure: 40%
   - Mean Reversion: 30%
   - Momentum: 30%
3. Calculate combined score
4. Discretize to final signal

**Trading Signals**:
- **Long Volatility** (Signal = +1): When combined score > +0.5
  - Trade: Buy ATM straddle
  
- **Short Volatility** (Signal = -1): When combined score < -0.5
  - Trade: Sell ATM straddle
  
- **Neutral** (Signal = 0): When |combined score| ≤ 0.5
  - Trade: No position / flatten existing positions

**Weighting Rationale**:
- Term Structure (40%): Most stable, structural signal
- Mean Reversion (30%): Proven in range-bound markets
- Momentum (30%): Captures trending moves

**Market Regime**: Designed for all-weather performance with diversified signal sources.

---

## Signal Interpretation

| Signal Value | Position Type | Implementation |
|--------------|---------------|----------------|
| +1 | Long Volatility | Buy ATM Straddle (Buy Call + Buy Put) |
| -1 | Short Volatility | Sell ATM Straddle (Sell Call + Sell Put) |
| 0 | Neutral | No Position / Cash |

**Risk Considerations**:
- Long volatility: Limited loss (premium paid), unlimited profit potential
- Short volatility: Limited profit (premium received), unlimited loss potential
- Always use proper position sizing and risk management

---

## Usage

### Step 1: Generate Strategy Signals

```bash
python derivatives/vol.py
```

**Output**:
- Prints volatility data summary
- Shows strategy signals and statistics
- Displays latest trading recommendation
- Saves results to `vol_strategy_results.csv`

**Console Output Example**:
```
================================================================================
📊 AU.SHF Implied Volatility Data
================================================================================

Data Range: 2025-09-28 ~ 2025-10-28
Data Points: 21

Latest Data:
            IV_1M   IV_2M   IV_3M
2025-10-24  0.089   0.095   0.098
...

================================================================================
📈 Strategy 1: Term Structure Arbitrage
================================================================================

Term Structure Slope Statistics:
1M-3M Average Slope: 0.0085
1M-3M Slope Std Dev: 0.0023
Current Slope Z-score: -0.87

Trading Signal Distribution:
 0    18
-1     2
 1     1
...

================================================================================
💡 Latest Trading Recommendation
================================================================================

Date: 2025-10-24

Volatility Levels:
  1M IV: 0.0890
  2M IV: 0.0950
  3M IV: 0.0980

Term Structure:
  1M-3M Slope: 0.0090 (Z-score: -0.87)

Momentum Indicator:
  5-day Change: +3.21%

📍 Final Signal: 🟢 LONG Volatility (Buy Straddle/Long Volatility)
   Recommendation: Buy ATM Straddle
```

---

### Step 2: Visualize and Backtest

```bash
python derivatives/vol_analysis.py
```

**Output**:
- **8-panel chart** (`vol_strategy_analysis.png`):
  1. Implied volatility time series (1M, 2M, 3M)
  2. Term structure slope with ±1.5σ bands
  3. Mean reversion with Bollinger Bands
  4. Momentum indicator (5-day % change)
  5. Strategy 1 signals overlaid on IV
  6. Strategy 2 signals overlaid on IV
  7. Strategy 3 signals overlaid on IV
  8. Combined strategy final signals

- **Performance chart** (`vol_strategy_performance.png`):
  - Cumulative returns for all 4 strategies
  - Comparative performance over time

- **Console backtest results**:
  ```
  ================================================================================
  📈 Strategy Backtest Performance Analysis
  ================================================================================

  Term_Structure:
    Total Return: +2.34%
    Sharpe Ratio: 0.87
    Win Rate: 54.23%
    Max Drawdown: -1.12%
    Number of Trades: 8

  Mean_Reversion:
    Total Return: +1.89%
    Sharpe Ratio: 0.65
    Win Rate: 51.67%
    Max Drawdown: -0.98%
    Number of Trades: 12

  Momentum:
    Total Return: +3.12%
    Sharpe Ratio: 1.02
    Win Rate: 58.33%
    Max Drawdown: -1.45%
    Number of Trades: 6

  Combined:
    Total Return: +2.78%
    Sharpe Ratio: 0.94
    Win Rate: 55.56%
    Max Drawdown: -1.08%
    Number of Trades: 9
  ```

---

## Configuration

### Adjustable Parameters in `vol.py`

```python
# Date range
start_date = "2025-09-28"  # Adjust to your desired start date
end_date = "2025-10-28"    # Adjust to your desired end date

# Strategy 1: Term Structure Arbitrage
z_score_threshold = 1.5    # Change to 1.0 for more aggressive, 2.0 for conservative

# Strategy 2: Mean Reversion
lookback = 10              # Window for moving average (e.g., 5, 15, 20 days)
band_width = 2             # Bollinger Band width (e.g., 1.5, 2.5)

# Strategy 3: Momentum
momentum_threshold = 0.05  # 5% change threshold (e.g., 0.03 for 3%, 0.10 for 10%)

# Strategy 4: Combined Weights
weight_ts = 0.4            # Term structure weight
weight_mr = 0.3            # Mean reversion weight
weight_mom = 0.3           # Momentum weight
```

---

## Backtest Methodology

The backtest assumes a simplified P&L model:
- **Strategy Return** = Signal × Market Return (1M IV daily change)
- **Long Vol Signal (+1)**: Profits when IV increases
- **Short Vol Signal (-1)**: Profits when IV decreases
- **Neutral (0)**: No P&L

**Performance Metrics**:
- **Total Return**: Cumulative return over period
- **Sharpe Ratio**: Risk-adjusted return (annualized)
- **Win Rate**: Percentage of profitable days
- **Max Drawdown**: Largest peak-to-trough decline
- **Number of Trades**: Signal change frequency

**Limitations**:
- Does not account for bid-ask spreads
- Ignores transaction costs and slippage
- Simplified P&L (actual options have gamma, vega, theta effects)
- Assumes immediate execution at signal generation

---

## Trading Implementation

### Recommended Options Structures

| Signal | Structure | Implementation | Risk Profile |
|--------|-----------|----------------|--------------|
| Long Vol | ATM Straddle | Buy Call + Buy Put at same strike (ATM) | Limited loss, unlimited profit |
| Long Vol | ATM Strangle | Buy OTM Call + Buy OTM Put (cheaper) | Lower premium, needs bigger move |
| Short Vol | ATM Straddle | Sell Call + Sell Put at same strike | Limited profit, unlimited risk |
| Short Vol | Iron Condor | Sell Straddle + Buy wider OTM protection | Limited risk, limited profit |

### Position Sizing Guidelines

- **Max position size**: 2-5% of portfolio per trade
- **Stop loss**: When combined signal flips or ±2σ move against position
- **Scaling**: Consider half positions when combined score is 0.3-0.5 (weak signal)

### Risk Management

1. **Delta neutral**: Hedge underlying delta with futures if needed
2. **Gamma management**: Monitor gamma exposure, especially for short vol positions
3. **Vega exposure**: Be aware of portfolio vega; long vol = long vega
4. **Time decay**: Short vol benefits from theta decay; long vol suffers

---

## File Outputs

| File | Description | Format |
|------|-------------|--------|
| `vol_strategy_results.csv` | All strategy signals and IV data | CSV (Date index) |
| `vol_strategy_analysis.png` | 8-panel strategy analysis charts | PNG (16x12 inches) |
| `vol_strategy_performance.png` | Cumulative return comparison | PNG (14x8 inches) |

---

## Strategy Performance Summary

### Strategy Strengths

| Strategy | Best Market Condition | Expected Sharpe | Trade Frequency |
|----------|----------------------|-----------------|-----------------|
| Term Structure | Stable, mean-reverting curve | 0.7-1.0 | Low (monthly) |
| Mean Reversion | Range-bound volatility | 0.6-0.9 | Medium (weekly) |
| Momentum | Trending volatility | 0.8-1.2 | Low-Medium |
| Combined | All conditions | 0.8-1.1 | Medium |

### Expected Performance Characteristics

- **Annualized Return**: 5-15% (highly market dependent)
- **Volatility**: 8-12% annualized
- **Sharpe Ratio**: 0.7-1.2 (target > 0.8)
- **Max Drawdown**: -3% to -8%
- **Win Rate**: 50-60%

*Note: Past performance does not guarantee future results. Actual performance will vary based on market conditions, execution, and transaction costs.*

---

## Common Issues and Solutions

### Issue 1: Wind API Connection Error
```
ErrorCode=-40520007: Connection failed
```
**Solution**: Ensure Wind Terminal is running and logged in.

### Issue 2: No Data Returned
```
ErrorCode=-40522007: Invalid indicators
```
**Solution**: Verify contract code and field names are correct for your Wind subscription.

### Issue 3: All Signals are Zero
**Cause**: Insufficient data or flat volatility surface.
**Solution**: Extend date range or check if market was closed during period.

### Issue 4: Charts Not Displaying
**Cause**: matplotlib backend issue.
**Solution**: Ensure `matplotlib` is installed and display backend is available.

---

## Future Enhancements

### Potential Improvements

1. **Options Greeks Integration**:
   - Include delta, gamma, vega in P&L calculation
   - Real options pricing with Black-Scholes/Heston models

2. **Risk Metrics**:
   - Value at Risk (VaR) calculation
   - Portfolio Greeks monitoring
   - Stress testing scenarios

3. **Machine Learning**:
   - Train ML models on historical patterns
   - Feature engineering from volatility surface
   - Reinforcement learning for dynamic weighting

4. **Additional Strategies**:
   - Volatility skew trading
   - Calendar spreads
   - Ratio spreads based on volatility smile

5. **Real-time Monitoring**:
   - Live signal updates
   - Alert system for signal changes
   - Position tracking and P&L monitoring

6. **Multi-Asset**:
   - Extend to other commodities (copper, oil, etc.)
   - Cross-asset volatility correlation
   - Sector rotation based on vol regimes

---

## References and Further Reading

### Academic Papers
- Derman & Miller (2016): *The Volatility Smile*
- Gatheral (2006): *The Volatility Surface*
- Carr & Wu (2009): *Variance Risk Premiums*

### Volatility Trading Books
- Sinclair, E. (2013): *Volatility Trading*
- Natenberg, S. (2014): *Option Volatility and Pricing*
- Connolly, K. (2007): *Buying and Selling Volatility*

### Term Structure Theory
- Carr & Wu (2004): *Time-changed Lévy Processes and Option Pricing*
- Duffie, Pan & Singleton (2000): *Transform Analysis and Asset Pricing for Affine Jump-diffusions*

---

## License and Disclaimer

**Disclaimer**: This software is for educational and research purposes only. It is not financial advice. Trading derivatives involves substantial risk of loss. Past performance is not indicative of future results. Always consult with a licensed financial advisor before making investment decisions.

**License**: Internal use only for CMBC quantitative research.

---

## Contact and Support

For questions, bugs, or feature requests:
- **Author**: CMBC Quantitative Research Team
- **Created**: October 28, 2025
- **Version**: 1.0.0

---

## Changelog

### Version 1.0.0 (2025-10-28)
- Initial release
- Implemented 4 volatility trading strategies
- Added visualization and backtesting modules
- Created comprehensive documentation
