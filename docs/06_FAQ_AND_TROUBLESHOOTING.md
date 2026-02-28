# FAQ & Troubleshooting

Quick answers to common questions and solutions to problems.

## Getting Started

### Q: Do I need coding knowledge to use TradeForge?

**A**: No. The Strategy Builder is fully visual/form-based. No code required.

### Q: Can I use TradeForge on Mac/Linux?

**A**: Yes, but most features require a Windows PC for MT5 support. Oanda, Coinbase, Tradovate work on all platforms.

### Q: What's the minimum starting capital?

**A**: Depends on your broker. Generally:
- **Forex (Oanda)**: $100 minimum (micro lots)
- **Metals (MT5)**: $500 recommended
- **Crypto (Coinbase)**: $50 minimum
- **Futures (Tradovate)**: $2,000 minimum

### Q: Is backtesting accurate?

**A**: 80-90% accurate. Real trading differs due to slippage, commissions, market gaps, and liquidity. Always paper-trade first.

---

## Broker & Connectivity

### Q: How do I get an Oanda API key?

**A**: See [Broker Setup Guide](./01_BROKER_SETUP.md#oanda) for detailed steps.

### Q: What's the difference between MT5 demo and live?

**A**: Demo = practice with fake money, live = real money. Demo accounts reset and have fixed balance ($100k); live accounts are tied to your real trading account.

### Q: Can I connect multiple brokers?

**A**: Yes, but strategies run on one broker at a time. You choose which broker when creating an Algo Agent.

### Q: Why doesn't MT5 data update in real-time?

**A**: 
- MT5 terminal must be open and logged in
- "Allow live trading" must be enabled in Tools → Options
- Check network connection
- Verify chart is visible (minimize, don't close)

### Q: How often does Oanda update prices?

**A**: Every 2-3 seconds via REST API polling. WebSocket support (faster) is planned.

---

## Strategies

### Q: How do I know if my strategy is good?

**A**: Good strategies have:
- Profit Factor > 1.5
- Win Rate > 50% (or large win size compensates)
- Max Drawdown < 20%
- Sharpe Ratio > 1.0
- Consistent monthly profits

### Q: What's the difference between SMA and EMA?

**A**: 
- **SMA** = simple average (all bars weighted equally)
- **EMA** = exponential average (recent bars weighted more)
- EMA responds faster to recent price changes

### Q: Should I use many indicators or few?

**A**: Few is better.
- 1-2 indicators: Fast, clear signals, less overfitting ✅
- 3-5 indicators: Reasonable balance
- 6+ indicators: Likely overfitted, contradictory signals ❌

### Q: Can I backtest multiple symbols at once?

**A**: No, backtest one symbol at a time. But you can optimize same strategy on different symbols separately.

---

## Backtesting

### Q: Why does my backtest show 0 trades?

**A**: Entry rule never triggered. Check:
1. Rule conditions (e.g., "SMA(20) > SMA(50)")
2. Date range contains data
3. SMA(20) indicator is enabled
4. Data quality (no gaps)

Debug: Manually check if condition is true right now in the chart.

### Q: Results show great profit, but live trading lost money. Why?

**A**: 
- **Overfitting** — strategy fit to historical noise
- **Market change** — conditions shifted since backtest
- **Slippage** — didn't account for real-world execution costs
- **Commissions** — forgot to include broker fees

**Solution**: Add more slippage/commission to backtest settings, re-test, and paper-trade longer.

### Q: How many years of data should I backtest?

**A**: At least 1-2 years to capture different market regimes. 3-5 years is ideal.

### Q: What does "Max Drawdown" mean?

**A**: Largest peak-to-trough decline. If equity drops from $12k to $10k, max DD = -16.7%. Smaller is safer.

---

## Optimization

### Q: How many parameters should I optimize?

**A**: 2-3 max. Optimizing 10+ parameters nearly guarantees overfitting.

### Q: Should I use Bayesian or Genetic algorithm?

**A**:
- **Bayesian**: Fast, use when time-limited or few parameters (2-3)
- **Genetic**: Thorough, use when time available and many parameters (4+)

### Q: My optimized parameters don't work live. What went wrong?

**A**: Likely overfitting. Solutions:
1. Use wider date range (include bear markets, trending periods)
2. Test out-of-sample (optimize on 2022-2023, validate on 2024)
3. Use fewer parameters
4. Use round numbers (20, 50, 100, not 23.7)

### Q: How often should I re-optimize?

**A**: Quarterly or when strategy stops working. Markets change; old parameters may need adjustment.

---

## Live Trading

### Q: What's the difference between Confirmation Mode and Autonomous Mode?

**A**:
- **Confirmation**: Bot signals but waits for your approval (safer, slower)
- **Paper**: Bot trades simulated, no real money (risk-free testing)
- **Autonomous**: Bot trades real money automatically (fastest, most risky)

Start with Confirmation or Paper. Switch to Autonomous after 4+ weeks of testing.

### Q: Can I stop an Algo Agent mid-trade?

**A**: Yes. Go to **Trading** → **Algo Agents** → **Stop**. Existing trades stay open; close manually if needed.

### Q: How do I set stop loss for live trades?

**A**: Define exit rules in strategy:
- Fixed pips: "Exit at -30 pips"
- ATR-based: "Exit at Entry - (2 × ATR)"
- Time-based: "Exit after 4 hours"

The strategy will auto-close when rules trigger.

### Q: Can I manually override an Algo Agent?

**A**: Yes, in Confirmation Mode you approve/reject each signal. In Autonomous Mode, you can only stop the agent or manually close trades.

### Q: My account is small ($500). Can I still trade?

**A**: Yes, but:
- Use small lot sizes (0.01 lots)
- Risk < 1% per trade
- Avoid leverage initially
- Build slowly

### Q: How much can I make with a strategy?

**A**: Depends on:
- Profit Factor (1.5x → 50% annual gains possible)
- Capital ($1k vs $100k = 100x difference in dollars)
- Risk per trade (1% vs 3% = 3x difference)
- Market conditions (trending markets better for some strategies)

**Realistic expectation**: 10-30% annual return for good strategies.

---

## Data & CSVs

### Q: What format should my CSV file be in?

**A**: Columns: DateTime, Open, High, Low, Close, Volume

Example:
```
DateTime,Open,High,Low,Close,Volume
2024-01-01 09:00:00,2050.25,2055.75,2050.00,2053.50,1250
2024-01-01 10:00:00,2053.50,2058.00,2052.75,2057.25,1425
```

### Q: Can I upload data from TradingView?

**A**: Yes. Export as CSV from TradingView and upload to TradeForge.

### Q: Why does my data import fail?

**A**:
- Check column names (must be DateTime, Open, High, Low, Close, Volume)
- Check datetime format (ISO 8601: YYYY-MM-DD HH:MM:SS)
- Check for missing rows (all rows must have all columns)
- Max file size: 500MB

---

## Performance & Troubleshooting

### Q: Backtests are slow. How do I speed up?

**A**:
- Use smaller date range (instead of 10 years, try 1-2 years)
- Use larger timeframe (D1 faster than M1)
- Close other apps to free RAM
- Upgrade to more RAM (8GB+ recommended)

### Q: Chart won't load. What's wrong?

**A**:
1. Refresh page (Ctrl+R)
2. Check backend running: `http://localhost:8000/api/health`
3. Verify broker connected (connection status green dot)
4. Check browser console (F12) for errors
5. Clear cache (Ctrl+Shift+Delete) and refresh

### Q: "Cannot update oldest data" error on chart

**A**: Usually happens with weekend markets (MT5 replays old ticks). System auto-filters these now, but if it persists:
1. Refresh chart
2. Switch timeframe
3. Check data quality for gaps

### Q: Live prices not updating

**A**:
- Check WebSocket connected (small indicator in top right)
- Verify broker connected
- Check MT5 terminal open (if using MT5)
- Verify "Allow live trading" enabled in MT5
- Try refreshing page

### Q: Optimization takes too long

**A**:
- Reduce parameter ranges (5-50 instead of 1-200)
- Use Bayesian algorithm (faster)
- Use larger timeframe or shorter date range
- Close other apps to free CPU

### Q: Out of memory error

**A**:
- Close browser tabs
- Stop other processes
- Use smaller date range
- Reduce optimization search space
- Upgrade system RAM

---

## Account & Settings

### Q: How do I change my password?

**A**: Go to **Settings** → **Profile** → **Change Password**

### Q: Can I have multiple accounts?

**A**: Yes. Create separate invitations in **Settings** → **Admin** for each user.

### Q: Can I export my backtest results?

**A**: Currently view-only in app. Feature coming soon for CSV export.

### Q: How do I backup my data?

**A**: Go to **Settings** → **Data Management** → **Backup Database** (coming soon). For now, your strategy configs are stored in database; regularly screenshot/document custom settings.

---

## Advanced

### Q: Can I use external data sources?

**A**: Yes, CSV upload supports any OHLCV data. Future: integration with Polygon.io, Databento for real-time feeds.

### Q: Does TradeForge support crypto futures?

**A**: Yes via Coinbase (for spot) and Tradovate (for futures). MT5 also offers some CFD tokens.

### Q: Can I use leverage?

**A**: Yes, but carefully. Leverage multiplies both gains and losses. Start with 1:1 (no leverage) until experienced.

### Q: How do I report bugs?

**A**: 
1. GitHub Issues: https://github.com/DemasJ2k/Tradeforge/issues
2. Include: What happened, expected behavior, steps to reproduce
3. Screenshots/logs help!

---

## Still Have Questions?

- **[Getting Started Guide](./00_GETTING_STARTED.md)** — Complete walkthrough
- **[Broker Setup](./01_BROKER_SETUP.md)** — Connect your broker
- **[Strategy Builder](./02_STRATEGY_BUILDER.md)** — Create strategies
- **[Backtesting](./03_BACKTESTING.md)** — Test your ideas
- **[Live Trading](./04_LIVE_TRADING.md)** — Deploy strategies
- **[Optimization](./05_OPTIMIZATION.md)** — Find best parameters

---

**Happy Trading! 📈**
