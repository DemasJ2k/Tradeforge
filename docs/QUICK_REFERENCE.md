# TradeForge Quick Reference

Cheat sheet with common tasks, shortcuts, and quick lookups.

## Navigation Shortcuts

| Action | Location |
|--------|----------|
| View account balance | **Dashboard** or top right corner |
| Create strategy | **Strategies** → **New Strategy** |
| Run backtest | **Backtest** → Choose strategy → Run |
| Optimize parameters | **Optimize** → Define ranges → Start |
| Deploy algo agent | **Trading** → **Algo Agents** → **New Agent** |
| Connect broker | **Settings** → **Broker Connections** |
| Change password | **Settings** → **Profile** → **Change Password** |
| Upload data | **Data** → **Upload CSV** |
| View trade history | **Dashboard** → **Recent Trade History** or **Trading** page |

---

## Common Indicators

### SMA (Simple Moving Average)

**Formula**: Average of last N prices

**Use**: Identify trend, support/resistance

**Default Periods**: 20 (short), 50 (medium), 200 (long)

**Entry Signal**: SMA(20) crosses above SMA(50) = BUY

**Exit Signal**: SMA(20) crosses below SMA(50) = SELL

---

### EMA (Exponential Moving Average)

**Formula**: Weighted average (recent prices weighted more)

**Use**: Faster trend following than SMA

**Default Periods**: 9 (fast), 21 (medium), 55 (slow)

**Entry Signal**: Close crosses above EMA(50) = BUY

**Exit Signal**: Close crosses below EMA(50) = SELL

---

### RSI (Relative Strength Index)

**Formula**: 100 - (100 / (1 + RS))

**Range**: 0-100

**Interpretation**:
- **RSI > 70**: Overbought (potential sell)
- **RSI < 30**: Oversold (potential buy)
- **RSI 40-60**: Neutral

**Entry Signal**: RSI < 30 = mean reversion BUY

**Exit Signal**: RSI > 70 = take profit/exit

---

### MACD (Moving Average Convergence Divergence)

**Components**:
- **MACD Line**: EMA(12) - EMA(26)
- **Signal Line**: EMA(9) of MACD
- **Histogram**: MACD - Signal

**Interpretation**:
- **MACD > Signal**: Bullish (histogram positive)
- **MACD < Signal**: Bearish (histogram negative)

**Entry Signal**: MACD crosses above signal line = BUY

**Exit Signal**: MACD crosses below signal line = SELL

---

### Bollinger Bands

**Components**:
- **Upper Band**: SMA(20) + (2 × StdDev)
- **Middle**: SMA(20)
- **Lower Band**: SMA(20) - (2 × StdDev)

**Interpretation**:
- **Price touches upper**: Overbought
- **Price touches lower**: Oversold
- **Band squeeze**: Low volatility (breakout coming)

**Entry Signal**: Close > Upper Band = breakout BUY

**Exit Signal**: Close < Lower Band = stop loss / exit

---

### ATR (Average True Range)

**Purpose**: Measures volatility

**Use Cases**:
- Dynamic stop loss: `SL = Entry - (2 × ATR)`
- Position sizing: Adjust size based on volatility
- Volatility filter: Only trade when ATR > threshold

**Interpretation**:
- **High ATR**: Volatile (wide swings)
- **Low ATR**: Quiet (tight consolidation)

---

## Strategy Templates

### Template 1: Simple Moving Average Crossover

**Indicators**: SMA(20), SMA(50)

**Entry**:
- BUY: SMA(20) > SMA(50)
- SELL: SMA(20) < SMA(50)

**Exit**:
- SL: -30 pips
- TP: +100 pips OR opposite signal

**Risk**: Risk 2% per trade, max 3 positions

**Timeframe**: H1 or D1 (best for trend following)

---

### Template 2: RSI Mean Reversion

**Indicators**: RSI(14), SMA(50)

**Entry**:
- BUY: RSI < 30 AND Close > SMA(50)
- SELL: RSI > 70 AND Close < SMA(50)

**Exit**:
- TP: +50 pips
- SL: -25 pips OR after 5 bars

**Risk**: Risk 1.5% per trade, max 2 positions

**Timeframe**: M15 or H1 (mean reversion happens quickly)

---

### Template 3: MACD Momentum

**Indicators**: MACD(12,26,9), SMA(50)

**Entry**:
- BUY: MACD > Signal AND MACD > 0
- SELL: MACD < Signal AND MACD < 0

**Exit**:
- Exit when MACD crosses opposite direction OR opposite signal

**Risk**: Risk 2% per trade, max 3 positions

**Timeframe**: H1 (capture trending moves)

---

## Risk Management Quick Calc

### Position Sizing by Risk

```
Account: $10,000
Risk per trade: 2% = $200
Stop loss distance: 50 pips
Pip value (varies): $10 per pip (XAUUSD)

Lot size = Risk $ / (SL pips × Pip value)
         = $200 / (50 × $10)
         = $200 / $500
         = 0.4 lots
```

### Risk/Reward Ratio

```
Entry: 2050.50
Stop: 2048.00 (SL = -50 pips)
Target: 2055.50 (TP = +100 pips)

Risk/Reward = TP distance / SL distance
            = 100 / 50
            = 2.0 (excellent, 1:2 ratio)
```

### Profit Factor

```
Total Wins: $5,000
Total Losses: $2,000

Profit Factor = Wins / Losses
              = $5,000 / $2,000
              = 2.5 (excellent)
```

---

## Backtest Checklist

Before deploying live, verify backtest shows:

- [ ] Positive total return (> 5% ideally)
- [ ] Win rate > 50%
- [ ] Profit factor > 1.5
- [ ] Max drawdown < 20%
- [ ] Sharpe ratio > 1.0
- [ ] Consistent monthly profits (no months with large losses)
- [ ] At least 50 trades (sample size)
- [ ] 1-2 years of data (different market conditions)

---

## Live Trading Checklist

Before going live, verify:

- [ ] Backtest passed all checks above
- [ ] Paper traded 2-4 weeks successfully
- [ ] Results match backtest closely
- [ ] Risk limits set (max daily loss, drawdown)
- [ ] Position size calculated
- [ ] Broker connected and tested
- [ ] Kill switch plan ready (how to stop quickly)
- [ ] Time to monitor daily
- [ ] Comfort with potential losses

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+K` | Open AI Assistant |
| `Ctrl+B` | Collapse sidebar |
| `Ctrl+R` | Refresh page |
| `F12` | Open browser console (for debugging) |
| `Escape` | Close modals/dialogs |

---

## Broker API Key Locations

### MetaTrader5
- **Where**: Terminal itself (no API key needed)
- **Setup**: Login to terminal, enable "Allow live trading" in Tools → Options

### Oanda
- **Where**: https://account.oanda.com → Manage API Access
- **Get**: Account ID + API Token
- **Format**: Token looks like: `8s7a9d7f9as8df9as8df9as8df`

### Coinbase
- **Where**: https://coinbase.com → Settings → API
- **Get**: API Key + API Secret + Passphrase
- **Format**: Key/Secret are long alphanumeric strings

### Tradovate
- **Where**: https://tradovate.com → Account Settings → API
- **Get**: Username + Password + Account ID
- **Format**: Same as login credentials

---

## Data Format Requirements

### CSV Upload Format

**Required columns**: DateTime, Open, High, Low, Close, Volume

**Example**:
```
DateTime,Open,High,Low,Close,Volume
2024-01-01 09:00:00,2050.25,2055.75,2050.00,2053.50,1250
2024-01-01 10:00:00,2053.50,2058.00,2052.75,2057.25,1425
```

**DateTime format**: YYYY-MM-DD HH:MM:SS (ISO 8601)

**Note**: Must include headers, all rows complete, no missing values

---

## Performance Metrics Reference

| Metric | Formula | Good Value | What It Means |
|--------|---------|------------|---------------|
| **Profit Factor** | Gross Profit / Gross Loss | > 1.5 | For every $1 lost, make $1.50 |
| **Win Rate** | Wins / Total Trades | > 50% | More wins than losses |
| **Sharpe Ratio** | (Return - Risk-Free) / Volatility | > 1.0 | Return per unit of risk |
| **Max Drawdown** | (Low - Peak) / Peak | < 20% | Largest equity decline |
| **Return** | (Final - Initial) / Initial | > 10% annually | Overall gain/loss % |
| **Avg Win** | Total Wins / Win Count | Higher better | Average profit per win |
| **Avg Loss** | Total Losses / Loss Count | Lower better | Average loss per loss |

---

## Optimization Tips

### Do's ✅
- ✅ Use round numbers (20, 50, 100)
- ✅ Optimize 2-3 critical parameters
- ✅ Test on 2+ years of data
- ✅ Validate on out-of-sample data
- ✅ Use wider ranges first, then narrow down

### Don'ts ❌
- ❌ Optimize 10+ parameters (overfitting)
- ❌ Use fractional values (20.3, not 20)
- ❌ Test only 3 months of data
- ❌ Ignore out-of-sample validation
- ❌ Optimize too tightly (e.g., L1=18.7)

---

## Common Error Solutions

| Error | Fix |
|-------|-----|
| "Invalid API key" | Regenerate key, check for spaces, verify not expired |
| "Cannot connect to broker" | Check API key/password, broker online, network connection |
| "Backtest 0 trades" | Check entry conditions are met, verify data quality |
| "Chart won't load" | Refresh (Ctrl+R), check broker connected, clear cache |
| "Live updates slow" | Normal for REST API; WebSocket planned for faster updates |
| "Out of memory" | Close tabs, reduce optimization range, upgrade RAM |

---

## Quick Decision Tree

### "Should I deploy this strategy live?"

```
Backtest shows positive return?
├─ No → Revise strategy, test again
└─ Yes → Continue

Win rate > 50%?
├─ No → Revise entry/exit rules
└─ Yes → Continue

Max drawdown < 20%?
├─ No → Increase stop loss or reduce position size
└─ Yes → Continue

Profit factor > 1.5?
├─ No → Improve win rate or risk/reward ratio
└─ Yes → Continue

Tested on 2+ years of data?
├─ No → Extend backtest period
└─ Yes → Continue

✅ All checks passed → Paper trade 2-4 weeks first!
```

---

## Monthly Review Checklist

Every month, review:

- [ ] Total P&L (profit or loss for month)
- [ ] Trade count (consistent with expectations)
- [ ] Win rate this month (compare to average)
- [ ] Largest win (is it reasonable?)
- [ ] Largest loss (within max risk?)
- [ ] Margin used (within limits?)
- [ ] Broker connection stable (no drops?)
- [ ] Any unusual market conditions?
- [ ] Need to re-optimize?
- [ ] Still comfortable with risk settings?

---

## Useful External Links

- **MT5**: https://www.metatrader5.com
- **Oanda API Docs**: https://docs.oanda.com
- **Coinbase API Docs**: https://docs.cloud.coinbase.com
- **Tradovate API**: https://api.tradovate.com
- **TradingView Data**: https://tradingview.com/data
- **TradeForge GitHub**: https://github.com/DemasJ2k/Tradeforge

---

## Time-Based Trading Guide

### Best Times to Trade (by Asset)

**Forex (EUR_USD, GBP_USD)**:
- London session: 08:00-17:00 GMT (most liquid)
- New York overlap: 12:00-17:00 GMT (very volatile)
- Avoid: 22:00-02:00 GMT (low liquidity)

**Metals (XAUUSD, XAGUSD)**:
- Best: 08:00-17:00 GMT (overlap hours)
- Good: All sessions (trades 24/5)
- Note: Weekends = gap risk, low spreads

**Crypto (BTC-USD, ETH-USD)**:
- 24/7 trading, weekends included
- Avoid: Major economic news windows
- Note: More volatile than forex

**Indices (US30, NAS100)**:
- US market hours: 14:30-21:00 GMT
- Pre-market: 13:00-14:30 GMT (low volume)
- After-hours: 21:00-04:00 GMT (wide spreads)

---

## Strategy Strength Rating

Rate your strategy 1-5 stars based on:

```
★ Rating = (WinRate + ProfitFactor/2 + Sharpe + Consistency) / 4

Example:
WinRate: 60% = 3 stars
ProfitFactor: 2.0 = 4 stars
Sharpe: 1.5 = 4 stars
Consistency: Good monthly profits = 4 stars

Average: (3 + 4 + 4 + 4) / 4 = 3.75 stars ✅ Good

Recommendation:
⭐ 1-2: Poor, don't trade live
⭐⭐ 2-3: Marginal, paper trade only
⭐⭐⭐ 3-4: Good, ready for live (with caution)
⭐⭐⭐⭐ 4-5: Excellent, deploy with confidence
```

---

## Remember

✅ **Always paper trade first**  
✅ **Backtest thoroughly**  
✅ **Risk management first, profits second**  
✅ **Start small, scale slowly**  
✅ **Monitor daily**  
✅ **Keep learning**  

---

**Good luck trading! 📈**
