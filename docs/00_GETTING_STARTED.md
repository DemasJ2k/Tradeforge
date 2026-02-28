# TradeForge — Getting Started Guide

Welcome to **TradeForge**, a professional web-based trading platform for backtesting, optimization, and live trading across multiple brokers and instruments.

## Table of Contents

1. [What is TradeForge?](#what-is-tradeforge)
2. [System Requirements](#system-requirements)
3. [Quick Start — Local Setup](#quick-start--local-setup)
4. [Login & First Steps](#login--first-steps)
5. [Common Tasks](#common-tasks)
6. [Troubleshooting](#troubleshooting)

---

## What is TradeForge?

TradeForge is an all-in-one trading platform that combines:

- **Live Chart Analysis** — Real-time price feeds with technical indicators (MA, EMA, MACD)
- **Strategy Builder** — Form-based strategy creation with entry/exit rules, indicators, and risk parameters
- **Backtesting Engine** — Tick-level strategy simulation across historical data
- **Optimization** — Bayesian + Genetic algorithm hybrid to find optimal parameters
- **Algo Trading** — Autonomous strategy execution with confirmation mode and paper-trading
- **Multi-Broker Support** — MetaTrader5 (MT5), Oanda, Coinbase, Tradovate
- **ML Training** — Predictive models from simple to advanced (Random Forest → LSTM → Ensemble)
- **Knowledge Base** — Educational content, strategy examples, trading psychology

---

## System Requirements

### Local Development

- **Windows 10+** or **Linux/Mac** (most features work; MT5 requires Windows)
- **Node.js 18+** (frontend)
- **Python 3.9+** (backend)
- **Git** (for cloning the repository)
- **MetaTrader5** (Windows-only, optional — for live MT5 trading)
- **Modern web browser** (Chrome, Firefox, Edge, Safari)

### Hardware

- **Minimum**: 4GB RAM, dual-core CPU (for backtesting small datasets)
- **Recommended**: 8GB+ RAM, quad-core CPU (for optimization runs and large backtests)

---

## Quick Start — Local Setup

### 1. Clone the Repository

```bash
git clone https://github.com/DemasJ2k/Tradeforge.git
cd Tradeforge
```

### 2. Set Up the Backend (Python)

```bash
cd backend

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Set Up the Frontend (Node.js)

```bash
cd frontend

# Install dependencies
npm install

# Build the app
npm run build
```

### 4. Start Both Servers

From the root `tradeforge/` directory, use the provided launcher:

**Windows:**
```bash
start.bat
```

**macOS/Linux:**
```bash
./start.sh
```

This will:
- Start the backend on `http://localhost:8000`
- Start the frontend on `http://localhost:3000`

### 5. Verify Installation

Open your browser and go to:
```
http://localhost:3000
```

You should see the **TradeForge Login** page.

---

## Login & First Steps

### Default Admin Account

**Username:** `TradeforgeAdmin`  
**Password:** `admin123`

⚠️ **IMPORTANT**: Change this password immediately in Settings → Profile.

### First Time Setup

1. **Login** with the admin account
2. **Go to Settings** (bottom left sidebar)
3. **Broker Connections** tab:
   - Connect to **MT5** (if you use MetaTrader5), or
   - Connect to **Oanda** (forex/CFDs), **Coinbase** (crypto), or **Tradovate** (futures)
   - See [Broker Setup Guide](./01_BROKER_SETUP.md) for detailed instructions
4. **Create Invitations** (Admin tab) to add team members

### Navigation

| Page | Purpose |
|------|---------|
| **Dashboard** | Overview of account, open positions, recent trades, running agents |
| **Trading** | Live chart with real-time data, place orders, create algo agents |
| **Data** | Upload CSV files, fetch historical data from brokers |
| **Strategies** | Create, view, and manage trading strategies |
| **Backtest** | Run backtests on historical data, analyze results |
| **Optimize** | Find optimal strategy parameters using Bayesian/genetic algorithms |
| **ML Lab** | Train predictive models from simple (Random Forest) to advanced (LSTM) |
| **Knowledge** | Educational articles, quizzes, strategy templates |
| **Settings** | Profile, appearance, broker credentials, LLM setup, API keys |

---

## Common Tasks

### Task 1: Connect Your Broker

See [Broker Setup Guide](./01_BROKER_SETUP.md) for step-by-step instructions for:
- **MetaTrader5** (most complete, live data + trading)
- **Oanda** (forex, CFDs)
- **Coinbase** (crypto)
- **Tradovate** (futures)

### Task 2: Upload Historical Data

1. Go to **Data** page
2. Click **Upload CSV**
3. Select a file with columns: `DateTime`, `Open`, `High`, `Low`, `Close`, `Volume`
4. Confirm symbol, timeframe, and date range
5. File is stored and available for backtesting

### Task 3: Create a Strategy

1. Go to **Strategies** → **New Strategy**
2. Give it a name
3. **Entry Rules**: Add conditions like:
   - "When SMA(20) crosses above SMA(50)"
   - "When RSI > 70"
4. **Exit Rules**: Add like:
   - "When price hits take-profit: +100 pips"
   - "When SMA(20) crosses below SMA(50)"
5. **Risk Settings**: Lot size, max positions, max daily loss
6. **Save**

### Task 4: Backtest a Strategy

1. Go to **Backtest**
2. Select **Strategy**, **Symbol**, **Timeframe**, **Date Range**
3. Click **Run Backtest**
4. View results: equity curve, trade log, statistics

### Task 5: Optimize Parameters

1. Go to **Optimize**
2. Select **Strategy** and **Parameter Ranges**
   - Example: SMA1 Length: 5-50, SMA2 Length: 50-200
3. Click **Start Optimization**
4. View results: best parameters, importance ranking, OOS validation

### Task 6: Deploy Strategy as Algo Agent

1. Go to **Trading** → **Algo Agents** → **New Agent**
2. Select **Strategy**, **Symbol**, **Timeframe**
3. Choose **Mode**:
   - **Confirmation**: Each trade requires manual approval
   - **Paper Trade**: Simulated trading (tracks PnL but no real money)
   - **Auto** (advanced): Executes automatically (use with caution)
4. Set **Risk Config**: lot size, max positions, max daily loss
5. Click **Start**
6. Monitor live log and trade confirmations

### Task 7: Use the AI Assistant

1. Click **AI Assistant** (bottom right or Ctrl+K)
2. Ask questions like:
   - "What is the best SMA period for XAUUSD?"
   - "Explain my backtest results"
   - "Generate a strategy from this description..."
3. AI provides guidance, explanations, and suggestions

### Task 8: Train an ML Model

1. Go to **ML Lab**
2. Select **Level** (1 = Simple, 2 = Intermediate, 3 = Advanced)
3. Choose **Data Source** (uploaded CSV or broker data)
4. Adjust **Parameters** (sequence length, train/test split, epochs)
5. Click **Train**
6. Use trained model as a signal in strategies

---

## Troubleshooting

### "Cannot connect to broker"

1. Verify API keys are correct in Settings → Broker Connections
2. Check broker is online and API is enabled
3. For MT5: verify terminal is running, login is correct, and network connection is stable
4. See [Broker Setup Guide](./01_BROKER_SETUP.md)

### "Chart not updating"

1. Check connection status indicator (green dot = live, yellow = reconnecting, gray = static)
2. Verify broker is connected and streaming data
3. Check browser console (F12) for errors
4. Refresh the page (Ctrl+R)

### "Backtest runs very slowly"

1. Large datasets (1000s of bars) take longer — this is normal
2. Try a smaller date range first
3. Close other applications to free RAM
4. For optimization, use Bayesian method (faster than Genetic)

### "Error: 'Cannot update oldest data'"

1. This usually means historical data has a gap or MT5 is replaying old ticks (weekend markets)
2. The system now auto-filters these — no action needed
3. If it persists, refresh the chart

### "Login fails"

1. Verify username and password are correct
2. Check Caps Lock is off
3. Clear browser cache (Ctrl+Shift+Delete) and refresh
4. Check backend is running: `http://localhost:8000/api/health`

### "Backend won't start"

1. Make sure port 8000 is not in use: `netstat -ano | findstr :8000` (Windows)
2. Kill any process on that port and try again
3. Check Python is installed: `python --version`
4. Reinstall dependencies: `pip install -r requirements.txt`

### "Frontend won't start"

1. Make sure port 3000 is not in use
2. Check Node.js is installed: `node --version`
3. Reinstall dependencies: `npm install`
4. Clear build cache: `rm -rf .next` and `npm run build`

---

## Next Steps

- **[Broker Setup Guide](./01_BROKER_SETUP.md)** — Detailed instructions for each broker
- **[Strategy Builder Guide](./02_STRATEGY_BUILDER.md)** — How to create trading strategies
- **[Backtesting Guide](./03_BACKTESTING.md)** — Comprehensive backtest analysis
- **[Optimization Guide](./04_OPTIMIZATION.md)** — Parameter optimization and walk-forward validation
- **[Live Trading Guide](./05_LIVE_TRADING.md)** — Algo agents, confirmations, risk management
- **[ML Lab Guide](./06_ML_LAB.md)** — Machine learning model training and prediction
- **[API Reference](./07_API_REFERENCE.md)** — Backend API endpoints for developers

---

## Support & Contributing

- **Issues**: Report bugs on GitHub Issues
- **Discussions**: Ask questions on GitHub Discussions
- **Contributing**: Submit pull requests with improvements

---

**Happy Trading! 📈**
