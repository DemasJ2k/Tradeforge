# Strategy Builder Guide

The Strategy Builder is a form-based interface for creating trading strategies without writing code. Define entry rules, exit rules, risk management, and filters visually.

## Table of Contents

1. [Overview](#overview)
2. [Creating a Strategy](#creating-a-strategy)
3. [Indicator Reference](#indicator-reference)
4. [Entry/Exit Rules](#entryexit-rules)
5. [Risk Management](#risk-management)
6. [Filters](#filters)
7. [Examples](#examples)

---

## Overview

A trading strategy in TradeForge consists of:

| Component | Purpose |
|-----------|---------|
| **Name** | Unique strategy identifier |
| **Indicators** | Technical analysis tools (SMA, EMA, RSI, MACD, Bollinger, ATR) |
| **Entry Rules** | Conditions that trigger opening a position |
| **Exit Rules** | Conditions that trigger closing a position |
| **Risk Settings** | Position sizing, max loss, max drawdown |
| **Filters** | Additional constraints (time-of-day, volatility, correlation) |

---

## Creating a Strategy

### Step 1: Open Strategy Builder

1. Go to **Strategies** page
2. Click **+ New Strategy**

### Step 2: Name Your Strategy

- **Strategy Name**: e.g., "SMA Golden Cross", "RSI Mean Reversion", "MACD Trend"
- **Description** (optional): Brief notes about the strategy

### Step 3: Add Indicators

In the **Indicators** section, select which technical indicators to use:

- [ ] **SMA** (Simple Moving Average) — Length: `20` (default)
- [ ] **EMA** (Exponential Moving Average) — Length: `50` (default)
- [ ] **RSI** (Relative Strength Index) — Length: `14`, Overbought: `70`, Oversold: `30`
- [ ] **MACD** (Moving Average Convergence Divergence) — Fast: `12`, Slow: `26`, Signal: `9`
- [ ] **Bollinger Bands** — Length: `20`, Std Dev: `2`
- [ ] **ATR** (Average True Range) — Length: `14`
- [ ] **Stochastic** — K-period: `14`, D-period: `3`

**Example**: To create a moving average crossover strategy, enable **SMA** and **EMA**.

### Step 4: Define Entry Rules

Click **+ Add Entry Rule** to create conditions for opening trades.

#### Entry Rule Syntax

Each rule is: **Condition** [AND/OR] **Condition** → **Direction** (BUY/SELL)

**Example Entry Rules:**

1. **"SMA(20) crosses above SMA(50)"** → **BUY**
   - Means: When 20-period MA crosses above 50-period MA, open a BUY position
   
2. **"RSI > 70"** → **SELL**
   - Means: When RSI goes above 70 (overbought), open a SELL position
   
3. **"Close > Bollinger Upper Band"** → **SELL**
   - Means: When price breaks above upper Bollinger Band, open a SELL (fade the breakout)

4. **"(MACD crosses above signal line) AND (RSI < 50)"** → **BUY**
   - Means: Open BUY only when MACD bullish AND RSI confirms (not overbought)

#### Comparison Operators

| Operator | Meaning | Example |
|----------|---------|---------|
| `>` | Greater than | `RSI > 70` (overbought) |
| `<` | Less than | `RSI < 30` (oversold) |
| `>=` | Greater or equal | `Close >= EMA(50)` (above average) |
| `<=` | Less or equal | `ATR <= 10` (low volatility) |
| `crosses above` | MA bullish cross | `SMA(20) crosses above SMA(50)` |
| `crosses below` | MA bearish cross | `SMA(20) crosses below SMA(50)` |
| `touches` | Price touches level | `Close touches Bollinger Upper Band` |

### Step 5: Define Exit Rules

Click **+ Add Exit Rule** to create conditions for closing trades.

#### Exit Rule Types

**Type 1: Opposite Signal** (exit when entry signal reverses)
- Example: Entry was "SMA(20) > SMA(50)" → Exit is "SMA(20) < SMA(50)"

**Type 2: Take Profit (TP)**
- **Fixed Pips**: e.g., "Close +50 pips" (exact profit target)
- **Fixed Amount**: e.g., "Profit = $100" (absolute money target)
- **Percent Equity**: e.g., "Profit = 2% of account"

**Type 3: Stop Loss (SL)**
- **Fixed Pips**: e.g., "Stop at -30 pips" (max loss)
- **Percent**: e.g., "Stop at -1% of entry"
- **ATR Multiple**: e.g., "Stop = Entry - (2 × ATR)" (dynamic, adjusts with volatility)

**Type 4: Time-Based Exit**
- **Bars**: e.g., "Exit after 10 bars" (hold for N candlesticks)
- **Minutes**: e.g., "Exit after 60 minutes"
- **End of Session**: Exit at market close (for day trading)

**Type 5: Indicator-Based**
- **Bollinger Bands**: "Exit when price touches lower band"
- **RSI**: "Exit when RSI > 80 (overbought)"
- **MACD**: "Exit when MACD histogram turns red"

#### Example Exit Rules

1. **Take Profit**: Close when profit reaches 100 pips
2. **Stop Loss**: Close when loss exceeds 30 pips
3. **Time Exit**: Close if trade is open after 4 hours
4. **Trailing Stop**: Stop loss follows price up, stays fixed if price falls
5. **Opposite Signal**: Exit when MACD crosses below signal line

### Step 6: Set Risk Management

Define how much you risk per trade and max drawdown limits.

#### Position Sizing

- **Fixed Lot**: Always open same size (e.g., 0.1 lots per trade)
- **Risk % of Balance**: Risk a % of account per trade (e.g., 2% risk → size adjusted by SL)
- **Dynamic Scaling**: Increase size in winning streaks, reduce after losses (optional)

#### Risk Limits

- **Max Positions**: How many trades open at once (e.g., 3)
- **Max Daily Loss**: Stop trading for the day after losing X% (e.g., 5%)
- **Max Drawdown**: Stop trading if equity falls X% below peak (e.g., 10%)
- **Max Exposure**: Total lot size limit (e.g., 1.0 lots max)

#### Example Risk Config

```
Position Sizing: Risk 2% per trade
Stop Loss: 30 pips (for XAUUSD)
↓ Size = Account × 2% / (30 × 100 pips) = adjusted automatically

Limits:
- Max Positions: 3 (never more than 3 open trades)
- Max Daily Loss: 5% (stop trading if loss > 5% today)
- Max Drawdown: 10% (circuit breaker for equity decline)
```

### Step 7: Add Filters (Optional)

Filters restrict when the strategy can trade.

#### Time Filters

- **Trading Session**: e.g., "Only 09:00-17:00 EST" (avoid low-liquidity hours)
- **Days of Week**: e.g., "No Mondays" (avoid Monday gaps)
- **Time of Day**: e.g., "No trading 22:00-02:00" (quiet hours)

#### Market Condition Filters

- **Volatility**: e.g., "Only trade when ATR > 10" (sufficient movement)
- **Trend**: e.g., "Only trade with trend (SMA(20) > SMA(50))" (only long in uptrends)
- **Correlation**: e.g., "Don't trade if correlated asset is falling" (diversification)

#### Example Filters

1. Only trade forex during London/New York overlap (08:00-17:00 GMT)
2. Don't trade on Fridays (avoid weekend gaps)
3. Only trade if volatility (ATR) is above average
4. Only trade in the direction of the major trend

### Step 8: Save Strategy

Click **Save Strategy**. The strategy is now available for:
- Backtesting
- Optimization (find best parameters)
- Live deployment as an Algo Agent

---

## Indicator Reference

### SMA (Simple Moving Average)

**What it does**: Calculates the average price over N periods.

**Formula**: `SMA(20) = (Close[0] + Close[1] + ... + Close[19]) / 20`

**Use cases**:
- Identify trend direction (price above SMA = uptrend)
- Support/resistance levels
- Crossover signals (SMA(20) > SMA(50) = bullish)

**Parameters**:
- **Length**: 5-200 (smaller = more responsive, more whipsaws; larger = smoother, slower)

**Example**: "SMA(20) crosses above SMA(50)" signals a bullish trend change

---

### EMA (Exponential Moving Average)

**What it does**: Moving average that gives more weight to recent prices.

**Formula**: `EMA = Price × K + EMA[previous] × (1 - K)` where `K = 2 / (Length + 1)`

**Difference from SMA**: EMA responds faster to price changes (better for momentum strategies)

**Use cases**:
- Faster trend identification than SMA
- Entry/exit signals in trend-following strategies
- Momentum confirmation (price above EMA(50) = strong momentum)

**Parameters**:
- **Length**: 5-200 (typically 20, 50, 200 for trends)

**Example**: "Close > EMA(50)" means price is above the 50-period exponential average (bullish)

---

### RSI (Relative Strength Index)

**What it does**: Measures overbought/oversold conditions on a 0-100 scale.

**Formula**: `RSI = 100 - (100 / (1 + RS))` where `RS = avg of gains / avg of losses`

**Interpretation**:
- **RSI > 70**: Overbought (potential sell signal)
- **RSI < 30**: Oversold (potential buy signal)
- **RSI 40-60**: Neutral (no clear signal)

**Use cases**:
- Mean reversion (buy oversold, sell overbought)
- Divergence signals (price makes new high but RSI doesn't)
- Confirmation (RSI > 50 confirms uptrend)

**Parameters**:
- **Length**: 14 (standard)
- **Overbought**: 70 (customizable, 60-80 common)
- **Oversold**: 30 (customizable, 20-40 common)

**Example**: "RSI < 30" means oversold; "RSI > 70" means overbought

---

### MACD (Moving Average Convergence Divergence)

**What it does**: Momentum indicator showing trend and momentum strength.

**Consists of**:
- **MACD Line**: EMA(12) - EMA(26)
- **Signal Line**: EMA(9) of MACD line
- **Histogram**: MACD - Signal (visual momentum)

**Interpretation**:
- **MACD > Signal**: Bullish (histogram positive/green)
- **MACD < Signal**: Bearish (histogram negative/red)
- **Crosses**: When MACD crosses signal line, trend change

**Use cases**:
- Trend identification (MACD above zero = uptrend)
- Entry signals (MACD crosses above signal = buy)
- Exit signals (MACD crosses below signal = sell)

**Parameters**:
- **Fast**: 12 (faster line)
- **Slow**: 26 (slower line)
- **Signal**: 9 (average of MACD)

**Example**: "MACD crosses above signal line" = bullish momentum signal

---

### Bollinger Bands

**What it does**: Volatility bands around a moving average (typically SMA(20)).

**Consists of**:
- **Upper Band**: SMA(20) + (2 × StdDev)
- **Middle Band**: SMA(20)
- **Lower Band**: SMA(20) - (2 × StdDev)

**Interpretation**:
- **Price outside bands**: Volatility breakout (potential trend start)
- **Price touches lower band**: Oversold (mean reversion opportunity)
- **Price touches upper band**: Overbought (potential pullback)
- **Band squeeze**: Low volatility (breakout coming)

**Use cases**:
- Volatility breakout strategies
- Mean reversion (buy at lower band, sell at upper band)
- Support/resistance (bands act as dynamic levels)

**Parameters**:
- **Length**: 20 (periods for MA)
- **Std Dev**: 2.0 (standard; 2.0 covers ~95% of price, 3.0 covers ~99%)

**Example**: "Price > Bollinger Upper Band" means volatility breakout to upside

---

### ATR (Average True Range)

**What it does**: Measures market volatility.

**Formula**: Average of the True Range over N periods

**Interpretation**:
- **High ATR**: High volatility (big swings, wider stops needed)
- **Low ATR**: Low volatility (tight consolidation, trending conditions)

**Use cases**:
- Dynamic stop loss sizing (SL = Entry - (2 × ATR))
- Position sizing (risk same $ on all trades by adjusting ATR-based SL)
- Volatility filtering (only trade when ATR > threshold)

**Parameters**:
- **Length**: 14 (standard)

**Example**: "Stop Loss = Entry - (2 × ATR(14))" gives a stop 2 ATRs below entry (dynamic)

---

### Stochastic

**What it does**: Momentum oscillator (0-100) showing position within recent range.

**Consists of**:
- **K Line**: Raw stochastic (default 14 period)
- **D Line**: EMA(3) of K (smoothed)

**Interpretation**:
- **Stoch > 80**: Overbought
- **Stoch < 20**: Oversold
- **K crosses above D**: Bullish signal
- **K crosses below D**: Bearish signal

**Use cases**:
- Mean reversion (buy at < 20, sell at > 80)
- Momentum confirmation (K > D = up momentum)
- Divergence signals (price makes new high, Stoch doesn't)

**Parameters**:
- **K-Period**: 14 (main look-back)
- **D-Period**: 3 (smoothing)

---

## Entry/Exit Rules

### Golden Cross (Bullish Trend)

**Entry**: SMA(20) crosses above SMA(50)  
**Exit**: SMA(20) crosses below SMA(50)  
**Direction**: LONG only  
**Best For**: Trending markets

### Mean Reversion (Oscillator Bounce)

**Entry**: RSI < 30 (oversold)  
**Exit**: RSI > 70 (overbought) OR after 20 bars  
**Direction**: LONG  
**Best For**: Range-bound markets

### MACD Momentum

**Entry**: MACD crosses above signal line  
**Exit**: MACD crosses below signal line  
**Direction**: LONG (or SELL if bearish cross)  
**Best For**: Trending markets with momentum

### Bollinger Breakout

**Entry**: Close > Bollinger Upper Band  
**Exit**: Take profit at +100 pips OR stop loss at entry - (2 × ATR)  
**Direction**: LONG (going with breakout)  
**Best For**: Volatile markets

### Dual Confirmation

**Entry**: (SMA(20) > SMA(50)) AND (RSI > 50) → BUY  
**Exit**: Take profit at +75 pips OR stop loss at -25 pips  
**Direction**: LONG  
**Best For**: Lower whipsaw, higher probability

---

## Risk Management

### Example: SMA Crossover with Risk Config

```
Entry: SMA(20) > SMA(50)
Exit: Take profit at 100 pips OR stop loss at 30 pips

Risk Config:
- Position Sizing: Risk 2% per trade
- Account: $10,000
- ATR: 15 pips (typical)

Calculation:
Risk per trade = $10,000 × 2% = $200
Stop loss distance = 30 pips
1 pip value for XAUUSD = ~10 (varies by lot size)
Lot size = $200 / (30 pips × 10) = 0.067 lots ≈ 0.1 lots

Result: Each trade risks exactly $200 (2% of account)
```

### Position Management

- **Max Positions: 3** → Never open more than 3 simultaneous trades
  - Prevents over-concentration
  - Limits total margin usage

- **Max Daily Loss: 5%** → Stop trading after losing 5% in one day
  - Protects against cascading losses
  - Prevents "revenge trading"

- **Max Drawdown: 10%** → Stops trading if equity falls 10% from peak
  - Long-term capital protection
  - Prevents burnout of account

---

## Examples

### Example 1: Simple SMA Crossover

**Name**: SMA 20/50 Crossover  
**Indicators**: SMA(20), SMA(50)  

**Entry**:
- BUY when SMA(20) crosses above SMA(50)
- SELL when SMA(20) crosses below SMA(50)

**Exit**:
- Exit when opposite signal triggers
- Take profit at 100 pips
- Stop loss at 30 pips

**Risk**: Risk 2% per trade, max 3 positions

**Filter**: Only trade 08:00-17:00 (avoid low liquidity)

---

### Example 2: RSI Mean Reversion

**Name**: RSI Mean Reversion  
**Indicators**: RSI(14), SMA(50)

**Entry**:
- BUY when RSI < 30 AND Close > SMA(50) (oversold + above trend)
- SELL when RSI > 70 AND Close < SMA(50) (overbought + below trend)

**Exit**:
- Take profit when profit reaches 50 pips
- Stop loss at 25 pips
- Exit after 5 bars (don't hold too long)

**Risk**: Risk 1.5% per trade, max 2 positions

**Filter**: Only when ATR > 8 (sufficient volatility)

---

### Example 3: MACD + RSI Confirmation

**Name**: MACD Trend + RSI Confirm  
**Indicators**: MACD, RSI(14)

**Entry**:
- BUY when (MACD crosses above signal) AND (RSI < 70)
- SELL when (MACD crosses below signal) AND (RSI > 30)

**Exit**:
- Take profit at 2× risk (if risk is 30 pips, TP is 60 pips)
- Stop loss at entry - 30 pips
- Time exit after 10 hours

**Risk**: Risk 2% per trade, max 3 positions, max daily loss 5%

**Filter**: Trade all sessions

---

## Next Steps

- **Backtest**: Test your strategy on historical data ([Backtesting Guide](./03_BACKTESTING.md))
- **Optimize**: Find best parameters ([Optimization Guide](./04_OPTIMIZATION.md))
- **Deploy**: Run live with Algo Agent ([Live Trading Guide](./05_LIVE_TRADING.md))

---

**Happy Strategy Building! 📊**
