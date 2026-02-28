# Backtesting Guide

Backtesting allows you to test strategies on historical data to evaluate performance before risking real money.

## Table of Contents

1. [What is Backtesting?](#what-is-backtesting)
2. [Running a Backtest](#running-a-backtest)
3. [Understanding Results](#understanding-results)
4. [Key Metrics](#key-metrics)
5. [Common Pitfalls](#common-pitfalls)
6. [Best Practices](#best-practices)

---

## What is Backtesting?

Backtesting simulates trading your strategy on historical data to answer:
- ✅ Does the strategy make money?
- ✅ How often does it win vs. lose?
- ✅ What's the maximum drawdown?
- ✅ Is it worth deploying live?

### Important Notes

- **Historical ≠ Future**: Past performance does not guarantee future results
- **Data Quality**: Results depend on data accuracy
- **Slippage & Commissions**: Real trading incurs costs; backtest includes estimates
- **Overfitting**: Testing many parameters can fit noise, not genuine patterns

---

## Running a Backtest

### Step 1: Select Strategy

1. Go to **Backtest** page
2. Click **Choose Strategy**
3. Select from existing strategies or create new one

### Step 2: Configure Backtest

| Setting | Description | Example |
|---------|-------------|---------|
| **Symbol** | Trading instrument | XAUUSD, BTCUSD, EUR_USD |
| **Timeframe** | Candle period | M1, M5, M15, H1, D1 |
| **Data Source** | Where to load bars | Uploaded CSV or broker data |
| **Start Date** | Test beginning | 2023-01-01 |
| **End Date** | Test ending | 2024-01-01 |
| **Initial Balance** | Starting capital | $10,000 |
| **Commission** | Cost per trade | $2 (or % of trade) |
| **Slippage** | Slippage estimate | 2 pips |
| **Leverage** | Position sizing multiplier | 1:1 (no leverage) |

### Step 3: Run Backtest

1. Click **Run Backtest**
2. Progress bar shows completion
3. Results load when done

---

## Understanding Results

### Overview Stats

| Metric | Meaning | Good Value |
|--------|---------|------------|
| **Total Return** | Profit/loss in % | > 10% per year |
| **Number of Trades** | Total buy/sell signals | Depends on strategy |
| **Win Rate** | % of profitable trades | > 50% (50%+ is breakeven) |
| **Profit Factor** | Gross profit / gross loss | > 1.5 (at least 50% more profit than loss) |
| **Sharpe Ratio** | Risk-adjusted return | > 1.0 (higher is better) |
| **Max Drawdown** | Largest peak-to-trough decline | < 20% (less is safer) |

### Equity Curve

- **Green line** = Account balance over time
- Should trend **upward overall**
- Smooth curve = consistent profits
- Jagged curve = high variance between trades

### Drawdown Chart

- **Red areas** = Period where account lost value from peak
- **Duration**: How long it took to recover
- Example: 15% max drawdown = account fell $1,500 on $10k capital

### Trade Log

Each row shows:

| Column | Example | Meaning |
|--------|---------|---------|
| **Date** | 2024-01-15 | Trade opened |
| **Symbol** | XAUUSD | Instrument |
| **Direction** | BUY/SELL | Long or short |
| **Entry Price** | 2050.50 | Open price |
| **Exit Price** | 2055.75 | Close price |
| **Profit/Loss** | +52.50 | $ P&L |
| **% Return** | +0.25% | % gain/loss |
| **Duration** | 2h 30m | Time in trade |

### Monthly Returns Heatmap

- **Green cells** = Profitable month
- **Red cells** = Loss month
- Shows consistency across different periods

---

## Key Metrics Explained

### Profit Factor

**Formula**: Gross Profit / Gross Loss

**Example**:
- Total Wins: $5,000
- Total Losses: $2,000
- Profit Factor = 5,000 / 2,000 = 2.5 ✅ (excellent)

**Interpretation**:
- **PF < 1.0**: More losses than gains ❌ (unprofitable)
- **PF = 1.0-1.2**: Marginal, not viable ⚠️
- **PF = 1.2-1.5**: Acceptable ✅
- **PF > 1.5**: Good ✅✅
- **PF > 2.0**: Excellent ✅✅✅

### Win Rate

**Formula**: (Number of Winning Trades) / (Total Trades) × 100%

**Example**:
- Winning trades: 60
- Losing trades: 40
- Total: 100 trades
- Win Rate = 60 / 100 × 100% = 60% ✅

**Interpretation**:
- **50% win rate**: Breakeven (if equal size losses and gains)
- **60-70% win rate**: Good momentum strategy
- **30-40% win rate**: Good trend-following (wins are large, losses small)
- **80%+ win rate**: Potentially overfitted (too good to be true)

### Sharpe Ratio

**Measures**: Risk-adjusted returns (how much return per unit of risk)

**Formula**: (Return - Risk-Free Rate) / Volatility

**Interpretation**:
- **< 0.5**: Poor (returns don't justify volatility)
- **0.5 - 1.0**: Acceptable
- **1.0 - 2.0**: Good
- **> 2.0**: Excellent

**Example**: Sharpe Ratio of 1.5 means for every 1% of volatility, you get 1.5% return.

### Max Drawdown

**Measures**: Largest peak-to-trough decline during backtest

**Formula**: (Lowest Equity - Peak Equity) / Peak Equity × 100%

**Example**:
- Peak equity: $12,000
- Lowest equity: $10,000
- Max DD = ($10,000 - $12,000) / $12,000 × 100% = -16.7%

**Interpretation**:
- **< 10%**: Excellent, minimal downside
- **10-20%**: Good, acceptable risk
- **20-30%**: High risk, needs attention
- **> 30%**: Very risky, consider revising

### Sortino Ratio

**Similar to Sharpe**, but only penalizes **downside** volatility (ignores upside swings)

**Interpretation**: Like Sharpe, but more favorable if you have volatility on upside.

---

## Common Pitfalls

### Overfitting

**Problem**: Strategy works great in backtest but fails live.

**Cause**: Too many parameters optimized to fit historical noise.

**Example**:
```
❌ Bad: SMA1: 17, SMA2: 53, RSI: 29, Threshold: 67.3
✅ Good: SMA1: 20, SMA2: 50, RSI: 30, Threshold: 70
```

**Solution**:
- Use **round numbers** (20, 50, 100)
- Prefer fewer parameters
- Use walk-forward validation (optimize on subset, test on holdout)

### Look-Ahead Bias

**Problem**: Using future data to make current decisions.

**Example**: ❌ "Exit when I know price will be higher tomorrow"

**Solution**: TradeForge automatically prevents this; rules only use past/current bar data.

### Insufficient Historical Data

**Problem**: Only testing 3 months of data; results not representative.

**Solution**: Backtest at least **1-2 years** to capture different market conditions.

### Ignoring Real-World Costs

**Problem**: Backtest assumes 0 slippage and 0 commission.

**Solution**: Add realistic values:
- **Slippage**: 2-5 pips (bid/ask spread + execution delay)
- **Commission**: 2-5 pips (broker fee)
- **Spread**: Already included in bid/ask

### Curve Fitting to Time Period

**Problem**: Strategy works only in one market condition (bull, bear, sideways).

**Solution**: Test multiple timeframes:
- 2020 (bull market)
- 2022 (bear market)
- 2024 (mixed)

---

## Best Practices

### Practice 1: Start Simple

- ✅ Begin with one moving average cross
- ❌ Don't start with 10 indicators

### Practice 2: Test Multiple Timeframes

- Test M5, M15, H1, D1
- What works on D1 may not work on M5 (and vice versa)

### Practice 3: Use Walk-Forward Validation

**Concept**: Optimize on old data, validate on new data.

**Example**:
```
Optimize on: 2022-2023
Validate on: 2023-2024

If 2024 results match 2022-23, strategy generalizes well ✅
If 2024 results are much worse, it was overfitted ❌
```

### Practice 4: Check Trade Distribution

- Look at **monthly returns** heatmap
- Good strategy: Profit in most months
- Bad strategy: Profits cluster in 1-2 months

### Practice 5: Risk/Reward Ratio

- For each trade: Calculate average win / average loss
- Ideal: At least 1:2 (win size is 2× loss size)
- Example: Avg win = $100, Avg loss = $50 → Ratio = 2.0 ✅

### Practice 6: Account for Commissions

- Never backtest with 0 commission
- Use realistic values for your broker
- Even small commissions ($2 per trade) compound over 1000 trades

### Practice 7: Forward Test First

Before deploying live:
1. **Paper trade** (simulate) for 2-4 weeks
2. Verify results match backtest
3. If live differs significantly, revise and re-test

---

## Example Backtest Analysis

### Scenario: SMA Crossover on XAUUSD

**Backtest Parameters**:
- Strategy: SMA(20) vs SMA(50) crossover
- Symbol: XAUUSD (Gold)
- Timeframe: H1 (hourly)
- Period: 2022-2024 (2 years)
- Initial Capital: $10,000
- Commission: $1 per trade

**Results**:

```
Total Return:           +25% ($2,500 profit)
Number of Trades:       120
Win Rate:               58%
Average Win:            $45
Average Loss:           $30
Profit Factor:          2.1
Max Drawdown:           12%
Sharpe Ratio:           1.2
```

**Interpretation** ✅:
- ✅ Positive return
- ✅ Win rate > 50%
- ✅ Profit factor > 1.5 (good)
- ✅ Max DD < 15% (acceptable)
- ✅ Sharpe > 1.0 (decent)

**Conclusion**: Ready to paper-trade and potentially deploy live.

---

## Troubleshooting

### "Backtest shows 0 trades"

- Check entry rule conditions are met in data
- Verify date range contains data
- Example: If looking for SMA crosses, need at least SMA length + 1 bars

### "Results don't match live trading"

- Live includes slippage and spread that backtest estimates
- Market conditions may have changed
- Strategy may have overfitted to historical period

### "Trades execute at unrealistic prices"

- Increase slippage estimate (try 5-10 pips)
- Add commission (try $2-5 per trade)
- Check data quality (missing bars or spikes)

---

## Next Steps

- **[Optimize](./04_OPTIMIZATION.md)**: Find best parameters
- **[Deploy Live](./05_LIVE_TRADING.md)**: Run strategy as Algo Agent
- **[ML Training](./06_ML_LAB.md)**: Add ML signals to strategy

---

**Happy Backtesting! 📊**
