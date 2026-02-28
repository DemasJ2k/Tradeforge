# TradeForge Documentation

Complete guide to the TradeForge trading platform.

## 📚 Documentation Index

### Getting Started
- **[Getting Started Guide](./00_GETTING_STARTED.md)** — Installation, login, first steps, system requirements

### Configuration
- **[Broker Setup Guide](./01_BROKER_SETUP.md)** — Connect MT5, Oanda, Coinbase, Tradovate with API keys

### Trading
- **[Strategy Builder](./02_STRATEGY_BUILDER.md)** — Create strategies visually with indicators, entry/exit rules, risk management
- **[Backtesting Guide](./03_BACKTESTING.md)** — Test strategies on historical data, understand metrics
- **[Optimization Guide](./05_OPTIMIZATION.md)** — Find optimal parameters using Bayesian/Genetic algorithms
- **[Live Trading Guide](./04_LIVE_TRADING.md)** — Deploy strategies as Algo Agents, manage risk, monitor trades

### Help & Reference
- **[FAQ & Troubleshooting](./06_FAQ_AND_TROUBLESHOOTING.md)** — Common questions, error solutions, tips
- **[Quick Reference](./QUICK_REFERENCE.md)** — Cheat sheet, keyboard shortcuts, common workflows

---

## 🚀 Quick Start

### 1. Install & Run

```bash
# Clone
git clone https://github.com/DemasJ2k/Tradeforge.git
cd Tradeforge

# Backend
cd backend && pip install -r requirements.txt

# Frontend
cd frontend && npm install

# Run (from root directory)
# Windows: start.bat
# Mac/Linux: ./start.sh
```

Open `http://localhost:3000`

### 2. Login

**Username:** `TradeforgeAdmin`  
**Password:** `admin123`

⚠️ Change password in Settings immediately.

### 3. Connect Broker

Go to **Settings** → **Broker Connections**
- **MT5**: Terminal path, account, password, server
- **Oanda**: API key, account ID, environment
- **Coinbase**: API key, secret, passphrase
- **Tradovate**: Username, password, account ID

### 4. Create Strategy

Go to **Strategies** → **New Strategy**
1. Add indicators (SMA, EMA, RSI, MACD)
2. Define entry rules (e.g., "SMA(20) > SMA(50)")
3. Define exit rules (take profit, stop loss, opposite signal)
4. Set risk management (lot size, max positions, daily loss limit)
5. Save

### 5. Backtest

Go to **Backtest**
1. Choose strategy, symbol, timeframe, date range
2. Click **Run Backtest**
3. Review results: profit, win rate, drawdown, metrics

### 6. Optimize (Optional)

Go to **Optimize**
1. Define parameter ranges (e.g., SMA1: 5-50, SMA2: 30-150)
2. Click **Start Optimization**
3. Find best parameters

### 7. Deploy Live

Go to **Trading** → **Algo Agents** → **New Agent**
1. Choose strategy, symbol, timeframe
2. Select mode: **Confirmation** (manual approval), **Paper Trade** (simulated), or **Autonomous** (automatic)
3. Set risk config (lot size, max daily loss, max positions)
4. Click **Start**

---

## 📖 Guide Selection

**Choose your guide based on what you want to do:**

| Goal | Guide |
|------|-------|
| Set up TradeForge for first time | [Getting Started](./00_GETTING_STARTED.md) |
| Connect broker (API keys, setup) | [Broker Setup](./01_BROKER_SETUP.md) |
| Create trading strategy | [Strategy Builder](./02_STRATEGY_BUILDER.md) |
| Test strategy on historical data | [Backtesting](./03_BACKTESTING.md) |
| Find best parameters | [Optimization](./05_OPTIMIZATION.md) |
| Deploy strategy for live trading | [Live Trading](./04_LIVE_TRADING.md) |
| Find answer to quick question | [FAQ](./06_FAQ_AND_TROUBLESHOOTING.md) |
| Quick commands & shortcuts | [Quick Reference](./QUICK_REFERENCE.md) |

---

## 🎯 Common Workflows

### Workflow 1: Test & Trade a Strategy

```
1. Strategy Builder → Create "SMA Crossover"
   ↓
2. Backtest → Run on 2022-2024 data
   ↓
3. Review results → Win rate 60%, profit factor 1.8 ✅
   ↓
4. Optimize → Find best SMA lengths
   ↓
5. Backtest again → Validate optimized parameters
   ↓
6. Algo Agent → Deploy in Paper Trade mode
   ↓
7. Monitor 2-4 weeks → Track simulated P&L
   ↓
8. Confirmation Mode → Switch to manual approval
   ↓
9. 2-4 more weeks → Approve/reject signals, build confidence
   ↓
10. Autonomous Mode → Go live (optional, advanced)
```

### Workflow 2: Analyze Backtest Results

```
1. Backtest → Run strategy on historical data
   ↓
2. View results → Check:
   - Net profit > 0% ✅
   - Win rate > 50% ✅
   - Max DD < 20% ✅
   - Profit factor > 1.5 ✅
   ↓
3. Trade log → Look for:
   - Consistent wins across months
   - No 3+ consecutive losses
   - Risk/reward ratio > 1:1
   ↓
4. Decide:
   - Looks good → Backtest on different timeframe
   - Needs work → Adjust rules, re-test
```

### Workflow 3: Set Up Algo Agent for Autonomous Trading

```
1. Paper Trade 2-4 weeks → Verify strategy works
   ↓
2. Switch to Confirmation Mode → 2-4 weeks manual approval
   ↓
3. Monitor daily:
   - Check agent status ✅
   - Review logs ✅
   - Track P&L ✅
   ↓
4. Weekly review:
   - Win rate on track? ✅
   - Unexpected losses? ❌
   - Risk limits appropriate? ✅
   ↓
5. After 4+ weeks confidence → Switch to Autonomous (optional)
```

---

## 💡 Key Concepts

### Strategy
A set of rules defining when to enter and exit trades.
- **Entry Rule**: e.g., "SMA(20) crosses above SMA(50)" → BUY
- **Exit Rule**: e.g., "Profit +100 pips" OR "Loss -30 pips"
- **Risk Settings**: Position size, max positions, daily loss limit

### Backtest
Simulating strategy on historical data to evaluate performance.
- Tests dozens/hundreds of trades
- Shows profit, win rate, drawdown, consistency
- **Important**: Backtest doesn't guarantee live results

### Optimization
Automatically finding best parameters for a strategy.
- Tests 10s-100s of parameter combinations
- Finds configuration with highest objective (e.g., max profit)
- **Careful**: Can overfit (fit to noise, not real patterns)

### Algo Agent
Automated trading bot executing strategy rules.
- Runs 24/5 or on market hours
- Monitors chart for entry/exit signals
- **Three modes**:
  - **Confirmation**: Bot signals, you approve (safest)
  - **Paper**: Simulated trading (risk-free)
  - **Autonomous**: Auto-executes (fastest, most risky)

### Walk-Forward Validation
Testing strategy on multiple periods to verify consistency.
- Optimize on 2022-2023 → Test on 2024
- If 2024 results similar to 2022-23: strategy generalizes ✅
- If 2024 results much worse: strategy overfitted ❌

---

## 🔗 Related Resources

### External Tools & APIs

- **[MetaTrader5](https://www.metatrader5.com)** — Trading terminal
- **[Oanda](https://oanda.com)** — Forex/CFD broker, REST API
- **[Coinbase](https://coinbase.com)** — Crypto exchange, REST API
- **[Tradovate](https://tradovate.com)** — Futures broker, REST API
- **[TradingView](https://tradingview.com)** — Chart data, educational

### Technical Stack

- **Frontend**: Next.js, React, TypeScript, TailwindCSS
- **Backend**: FastAPI, Python, SQLAlchemy, PostgreSQL
- **Charts**: lightweight-charts (TradingView)
- **Optimization**: Optuna (Bayesian), DEAP (Genetic)
- **ML**: scikit-learn, XGBoost, TensorFlow/Keras, PyTorch

### GitHub

- **Repository**: https://github.com/DemasJ2k/Tradeforge
- **Issues**: Report bugs
- **Discussions**: Ask questions
- **Contributing**: Submit PRs

---

## ❓ FAQ

**Q: Do I need coding knowledge?**  
A: No, Strategy Builder is fully visual.

**Q: Is backtesting accurate?**  
A: 80-90% accurate. Always paper-trade first.

**Q: Can I use multiple brokers?**  
A: Yes, one broker per Algo Agent.

**Q: How much money can I make?**  
A: Depends on profit factor, capital, and risk per trade. 10-30% annual return is realistic for good strategies.

**Q: Can I trade crypto?**  
A: Yes via Coinbase.

**Q: Can I trade futures?**  
A: Yes via Tradovate.

**Q: How often should I re-optimize?**  
A: Quarterly or when strategy stops working.

More questions? See [FAQ Guide](./06_FAQ_AND_TROUBLESHOOTING.md)

---

## 🛠️ Troubleshooting

| Problem | Solution |
|---------|----------|
| Can't login | Check username/password, clear cache |
| Broker won't connect | Verify API key, account ID, permissions |
| Chart not updating | Refresh, check broker connected, verify MT5 open |
| Backtest 0 trades | Check entry rule conditions, verify data quality |
| Optimization too slow | Reduce parameter ranges, use Bayesian algorithm |
| Live trades lose money | Likely overfitting; paper-trade longer, use walk-forward validation |

---

## 📞 Support

- **Documentation**: See guides above
- **FAQ**: [FAQ & Troubleshooting](./06_FAQ_AND_TROUBLESHOOTING.md)
- **GitHub Issues**: https://github.com/DemasJ2k/Tradeforge/issues
- **Email**: (Contact info coming soon)

---

## 📄 License

TradeForge is proprietary software. All rights reserved.

---

## 🙏 Acknowledgments

Built with love for traders. Powered by community feedback.

---

**Last Updated:** March 2026  
**Version:** 0.1.0

For latest updates, see [GitHub Releases](https://github.com/DemasJ2k/Tradeforge/releases)
