# FlowrexAlgo — Complete User Guide

> **Version 1.0** · Last updated: 2026-03-05
>
> This guide covers every page, feature, setting, and interaction in FlowrexAlgo.
> Whether you are a beginner trader or an experienced algo developer, this document
> will help you get the most out of the platform.

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Getting Started](#2-getting-started)
3. [Dashboard](#3-dashboard)
4. [Data Sources](#4-data-sources)
5. [Strategies](#5-strategies)
6. [Backtesting](#6-backtesting)
7. [Optimization](#7-optimization)
8. [ML Lab](#8-ml-lab)
9. [Trading](#9-trading)
10. [Watchlist](#10-watchlist)
11. [News & Events](#11-news--events)
12. [Documents & Knowledge Base](#12-documents--knowledge-base)
13. [Settings](#13-settings)
14. [AI Chat Assistant](#14-ai-chat-assistant)
15. [Command Palette](#15-command-palette)
16. [Keyboard Shortcuts](#16-keyboard-shortcuts)
17. [Glossary](#17-glossary)

---

## 1. Introduction

### What is FlowrexAlgo?

FlowrexAlgo is an all-in-one algorithmic trading platform that combines:

- **Strategy building** — Create trading strategies visually or with code (Python, JSON, Pine Script)
- **Backtesting** — Test your strategies against historical data with detailed performance metrics
- **Optimization** — Find the best parameter combinations and validate robustness
- **Machine Learning** — Train ML models to enhance strategy performance
- **Live trading** — Deploy strategies as automated trading agents on live or paper accounts
- **News & analysis** — Stay updated with economic events, market news, and AI-powered insights
- **Education** — Learn trading concepts with built-in articles and quizzes

### Supported Markets

FlowrexAlgo supports trading on:
- **Forex**: XAUUSD (Gold), XAGUSD (Silver), EURUSD, GBPUSD, and more
- **Indices**: US30 (Dow Jones), NAS100 (Nasdaq), and more
- **Crypto**: BTCUSD (Bitcoin), ETHUSD, and more
- **Futures**: Via CME symbol mapping (optional Databento integration)

### Supported Brokers

- **Oanda** — Default data and execution broker
- **MetaTrader 5 (MT5)** — Via MT5 bridge server
- **Coinbase** — Cryptocurrency trading
- **Tradovate** — Futures trading

---

## 2. Getting Started

### 2.1 Logging In

1. Open the FlowrexAlgo web application in your browser.
2. Enter your **username** and **password** on the login screen.
3. If two-factor authentication (2FA) is enabled, enter the 6-digit code from your authenticator app.
4. You will be taken to the **Dashboard**.

> **First-time users**: Your administrator will provide you with login credentials via an invitation. You may be required to change your password on first login.

### 2.2 Navigation

The left sidebar contains links to all major sections:

| Icon | Page | Description |
|------|------|-------------|
| 📊 | **Dashboard** | Overview of your account, positions, and agents |
| 💾 | **Data** | Upload and manage historical market data |
| 📝 | **Strategies** | Create and manage trading strategies |
| 📈 | **Backtest** | Test strategies against historical data |
| ⚙️ | **Optimize** | Find optimal strategy parameters |
| 🧠 | **ML Lab** | Train and deploy machine learning models |
| 📈 | **Trading** | Live charts, order management, and trading agents |
| 👁️ | **Watchlist** | Track symbols and set price alerts |
| 📰 | **News** | Economic calendar, news feed, and sentiment |
| 📚 | **Documents** | Learning materials and user guide |
| ⚙️ | **Settings** | Account, appearance, brokers, and platform settings |

**Collapsing the sidebar**: Click the collapse icon (top-left) or press `Ctrl+B` to minimize the sidebar to icons only. Click again to expand.

**Mobile**: On small screens, tap the menu icon in the top bar to open the sidebar as a sliding drawer.

### 2.3 Top Bar

The top bar at the top of every page contains:

- **Hamburger menu** (mobile only) — Opens the sidebar
- **AI Chat toggle** — Opens the AI assistant panel
- **Command Palette** — Press `Ctrl+K` to search and navigate quickly

---

## 3. Dashboard

**Path**: `/` (Home page)

The Dashboard is your command center. It provides a real-time overview of your entire trading operation.

### 3.1 Header Bar

At the top you will see:
- **Broker connection status** — Green dot = connected, red dot = no broker
- **WebSocket status** — Shows whether the real-time data feed is active
- **Pending confirmations** — If any trades need your approval, a link appears here

### 3.2 Broker Account Cards

If you have connected one or more brokers, each broker appears as a clickable card showing:
- **Broker name** (e.g., Oanda, MT5)
- **Balance** — Your account cash balance
- **Equity** — Balance plus/minus unrealized profit or loss
- **Open P&L** — Current unrealized profit/loss across all positions
- **Active badge** — Shows which broker is currently selected

Click a broker card to switch the active broker.

### 3.3 Stats Cards

Four summary cards at a glance:

| Card | What It Shows |
|------|---------------|
| **Account Balance** | Current cash balance (or "—" if no broker connected) |
| **Today's PnL** | Profit or loss from today's trades, trade count, and win rate |
| **Open Positions** | Number of currently open positions and unrealized P&L |
| **Running Agents** | Number of active trading agents (total, running, paused) |

### 3.4 Open Positions Table

A live table showing all currently open positions:
- **Symbol** — The instrument (e.g., XAUUSD)
- **Side** — BUY (green) or SELL (red)
- **Size** — Lot size or quantity
- **Entry** — Your entry price
- **Current** — Current market price
- **P&L** — Unrealized profit/loss for this position

Click **"Go to Trading"** to manage positions.

### 3.5 Platform Stats

A quick summary of your platform usage:
- Total strategies (user and system)
- Number of data sources uploaded
- Total backtests run (and date of last backtest)
- Number of agents in paper mode

Quick action buttons let you jump to:
- **New Strategy** → Strategies page
- **Run Backtest** → Backtest page
- **Go to Trading** → Trading page

### 3.6 Recent Trades

Shows your latest completed trades with:
- Symbol, direction (BUY/SELL), lot size, P&L
- **Source badge** — "agent" (automated) or "manual"
- Time of the trade

### 3.7 Trading Agents

Lists all your trading agents with:
- Agent name and status dot (green = running, yellow = paused, gray = stopped, red = error)
- Symbol and timeframe
- **Mode badge** — "paper" (simulated) or "live"
- **Status badge** — running, paused, stopped, or error

Click **"Manage"** to go to the Trading page.

---

## 4. Data Sources

**Path**: `/data`

Before you can backtest or optimize a strategy, you need historical market data. The Data page lets you upload CSV files or fetch data directly from your broker.

### 4.1 Uploading CSV Data

1. **Drag and drop** one or more CSV files onto the upload zone, or **click** to browse.
2. The system automatically detects:
   - **Symbol** and **timeframe** from the filename (e.g., `XAUUSD_M15.csv`)
   - **Date range** from the data
   - **Row count** and file size
3. Supported formats:
   - MT5 export format (dot-datetime)
   - Generic OHLCV (Open, High, Low, Close, Volume)
   - ISO datetime format
   - Tick data

> **Tip**: Name your files as `SYMBOL_TIMEFRAME.csv` (e.g., `XAUUSD_M15.csv`, `BTCUSD_H1.csv`) for automatic detection.

### 4.2 Fetching from Broker

1. Click **"Fetch from Broker"** button.
2. In the dialog, select:
   - **Broker** — MT5, Oanda, Coinbase, or Tradovate
   - **Symbol** — e.g., XAUUSD, EURUSD, NAS100
   - **Timeframe** — M1, M5, M15, M30, H1, H4, or D1
   - **Bars** — Number of candles to fetch (default: 5000, max: 100,000)
3. Click **"Fetch Data"**.
4. The data will appear in your data sources table.

> **Note**: You must first save your broker API credentials in **Settings → Trading** before fetching data.

### 4.3 Data Sources Table

Each uploaded or fetched dataset appears in a table with:
- **Symbol** — The trading instrument
- **Timeframe** — Candle period (M1, M5, M15, etc.)
- **Rows** — Number of data points
- **Date Range** — Start to end date of the data
- **Source** — "Upload" or broker name (e.g., "OANDA")
- **Size** — File size in MB
- **File** — Original filename

### 4.4 Instrument Profile

Click on any data source row to expand it and see:
- **Pip Value** — How much one pip is worth
- **Point Value** — Price per point movement
- **Lot Size** — Standard lot size for the instrument
- **Spread** — Default spread (in points)
- **Commission** — Trading commission and model

### 4.5 Data Preview

When you expand a data source, you also see a **preview of the first 10 rows** of candle data in table format.

### 4.6 Deleting Data

Click the **"Delete"** button on any data source to remove it. Deleted items go to the recycle bin (see Settings → Platform).

---

## 5. Strategies

**Path**: `/strategies`

Strategies are the core of FlowrexAlgo. A strategy defines the rules for when to enter and exit trades.

### 5.1 Strategy Types

| Type | Icon | Description |
|------|------|-------------|
| **Builder** | — | Created with the visual strategy editor |
| **Python** | 🐍 | Custom Python scripts with full flexibility |
| **JSON** | 📋 | JSON-defined rule sets |
| **Pine Script** | 🌲 | TradingView Pine Script strategies |

### 5.2 Creating a New Strategy

1. Click **"New Strategy"** (top right).
2. The **Strategy Editor** opens where you can:
   - Name your strategy
   - Add a description
   - Define **indicators** (e.g., EMA, RSI, MACD, ATR)
   - Set **entry rules** (conditions that trigger a trade)
   - Set **exit rules** (conditions that close a trade)
   - Configure risk management (stop loss, take profit)
3. Click **"Save"** when done.

### 5.3 Uploading a Strategy File

1. Click **"Upload"** button.
2. Drag and drop or browse for a file (`.py`, `.json`, or `.pine`).
3. Optionally enter a name (auto-detected from file if empty).
4. Click **"Upload Strategy"**.
5. Parameters in the file are auto-detected and exposed as editable settings.

### 5.4 AI Strategy Import

1. Click **"AI Import"** button (sparkle icon).
2. Upload a strategy document (`.txt`, `.pine`, `.md`, or `.pdf`).
3. Optionally add instructions (e.g., "Focus on the scalping strategy").
4. Click **"Generate Strategy"**.
5. The AI will parse the document and create a FlowrexAlgo strategy you can review and edit.

> **Requires**: An LLM API key configured in Settings → AI Settings.

### 5.5 Strategy List

Strategies are organized into:
- **System Strategies** (locked, built-in) — Cannot be edited or deleted
- **User Folders** — Create folders to organize your strategies
- **My Strategies** — Root-level user strategies

Each strategy card shows:
- **Name** (with type icon)
- **Description**
- **Verified Performance Badges** (if backtested):
  - ✅ Verified / GOOD / Tested
  - PF (Profit Factor)
  - WR (Win Rate)
  - DD (Max Drawdown)
  - Symbol & Timeframe
  - WF (Walk-Forward Score)
- **Tag badges**: Number of indicators, entry rules, exit rules, and settings

### 5.6 Strategy Actions

Each strategy card has action buttons:

| Button | Action |
|--------|--------|
| **Rename** (Aa) | Rename the strategy (or double-click the name) |
| **Settings** (⚙️) | Open strategy parameter settings |
| **Edit** (✏️) | Open in the strategy editor (builder type) |
| **View** (👁️) | View code (Python/JSON/Pine types) |
| **Duplicate** (📋) | Create a copy of the strategy |
| **Move** (📁) | Move to a different folder |
| **Delete** (🗑️) | Delete the strategy (with confirmation) |

> **Warning**: Deleting a strategy also removes all associated backtests, agents, ML models, and optimizations.

### 5.7 Folders

- Click **"New Folder"** to create a folder.
- Click the folder icon on a strategy to move it.
- Folders are collapsible — click the arrow to expand/collapse.

### 5.8 Search

Use the search bar to filter strategies by name, description, or type.

---

## 6. Backtesting

**Path**: `/backtest`

Backtesting lets you simulate how a strategy would have performed on historical data.

### 6.1 Running a Backtest

1. Click **"New Backtest"** or the configuration button.
2. In the **Backtest Config Dialog**, select:
   - **Strategy** — Which strategy to test
   - **Data Source** — Which historical data to use
   - **Date range** — Start and end dates (defaults to full dataset)
   - **Initial balance** — Starting account balance (default: $10,000)
   - **Risk per trade** — Percentage of account to risk (default: 0.5%)
   - **Commission** — Trading cost per lot
   - **Spread** — Simulated spread in points
3. Click **"Run Backtest"**.

### 6.2 Backtest Dashboard

After a backtest completes, the dashboard shows:

#### Stats Cards
Key performance metrics at a glance:
- **Net Profit** — Total profit/loss
- **Profit Factor** — Gross profit ÷ gross loss (>1.0 = profitable)
- **Win Rate** — Percentage of winning trades
- **Max Drawdown** — Largest peak-to-trough decline
- **Total Trades** — Number of completed trades
- **Sharpe Ratio** — Risk-adjusted return measure
- **SQN** — System Quality Number

#### Equity Curve Chart
A line chart showing your account equity over time. The x-axis is time, the y-axis is account value. A steadily rising curve with small drawdowns indicates a robust strategy.

#### Monthly Heatmap
A color-coded grid showing performance by month:
- **Green cells** = profitable months
- **Red cells** = losing months
- **Darker shades** = larger gains/losses
- Helpful for identifying seasonal patterns.

#### Trade Log Table
A detailed list of every trade with:
- Entry and exit time
- Direction (BUY/SELL)
- Entry and exit prices
- Profit/loss
- Exit reason (stop loss, take profit, signal, etc.)

#### Tearsheet Panel
Advanced statistical analysis including:
- Drawdown analysis
- Return distributions
- Rolling statistics
- Risk metrics

#### Trade Chart Overlay
View trades plotted directly on a candlestick chart. Green arrows mark entries, red marks exits. This helps you visually understand where trades happened.

### 6.3 Run History Sidebar

Previous backtest runs appear in a sidebar on the left. Click any run to load its results. Each entry shows:
- Strategy name
- Symbol and timeframe
- Status (completed, running, failed)
- Date run

---

## 7. Optimization

**Path**: `/optimize`

Optimization finds the best parameter combinations for your strategy.

### 7.1 Creating an Optimization

1. Select a **Strategy** and **Data Source**.
2. Define **Parameter Ranges**:
   - For each strategy parameter, set a minimum, maximum, and step size.
   - Example: Stop Loss from 1.0 to 3.0, step 0.5 → tests 1.0, 1.5, 2.0, 2.5, 3.0
3. Choose the **Optimization Method**:
   - **Grid Search** — Tests every combination (thorough but slow)
   - **Optuna** — Smart search that focuses on promising areas (faster)
4. Click **"Start Optimization"**.

### 7.2 Optimization Results

Results show:
- **Best Parameters** — The parameter combination with the highest score
- **Top 10 Results** — Ranked by optimization score
- **Parameter Importance** — Which parameters had the most impact
- **Score formula**: Sharpe Ratio × √(Total Trades)

### 7.3 Robustness Testing

After finding good parameters, test their robustness:

1. Click **"Run Robustness"** on an optimization result.
2. The system tests the parameters across multiple time windows:
   - Full period
   - First half / second half
   - Yearly windows
   - Last 25% of data
3. Results show:
   - **Pass Rate** — % of windows where the strategy was profitable
   - **Window Details** — Profit factor, win rate, drawdown for each window
   - **Rating**: GOOD (>60%), MARGINAL (40-60%), or POOR (<40%)

### 7.4 Trade Analysis

View detailed trade statistics including:
- Trade log with entry/exit times, prices, and P&L
- Analysis grouped by direction (BUY/SELL)
- Analysis grouped by exit reason
- Distribution charts

### 7.5 Optimization History

All previous optimizations are listed with:
- Strategy and data source
- Status and progress percentage
- Number of parameter combinations tested
- Best score achieved

---

## 8. ML Lab

**Path**: `/ml`

The Machine Learning Lab lets you train models to enhance your trading strategies.

### 8.1 ML Levels

| Level | Name | Description |
|-------|------|-------------|
| **L1** | Adaptive Params | ML adjusts strategy parameters based on market conditions |
| **L2** | Signal Prediction | ML predicts whether a signal will be profitable |
| **L3** | Advanced ML | Full ML-driven trading decisions |

### 8.2 Training a Model

1. Click **"Train New Model"**.
2. Select:
   - **Strategy** — Base strategy to enhance
   - **Data Source** — Training data
   - **ML Level** — L1, L2, or L3
   - **Features** — Input features for the model (price, volume, indicators, etc.)
3. Click **"Start Training"**.
4. Training progress is shown in real-time.

### 8.3 Model List

All trained models are displayed with:
- Model name and status (ready, training, failed)
- ML level badge
- Accuracy / performance metrics
- Action buttons: View details, Run prediction, Compare, Delete

### 8.4 Predictions

Run a trained model on new data:
1. Select a model and click **"Predict"**.
2. Choose a data source.
3. View predictions overlaid on a chart.

### 8.5 Model Comparison

Compare multiple models side by side:
- Select 2+ models to compare
- View comparative metrics (accuracy, F1, precision, recall)
- See which model performs best on different market conditions

---

## 9. Trading

**Path**: `/trading`

The Trading page is where you monitor markets, place orders, and manage automated trading agents.

### 9.1 Chart

The main feature is a **candlestick chart** powered by Lightweight Charts:

- **Symbol selector** — Choose which instrument to display
- **Timeframe selector** — M1, M5, M15, M30, H1, H4, D1
- **Data source toggle** — Switch between broker live data and uploaded data
- **Indicator dropdown** — Add technical indicators to the chart

#### Adding Indicators

Click the indicators button to add overlays:
- **Moving Averages**: SMA, EMA, WMA
- **Bollinger Bands**
- **RSI**, **MACD**, **Stochastic**
- **ATR** (Average True Range)
- **VWAP** (Volume Weighted Average Price)
- **Pivot Points**
- And many more

Each indicator can be customized with parameters (period, color, etc.) and removed individually.

### 9.2 Placing Orders

On the right side of the chart:

1. **Order Panel**:
   - Select **BUY** or **SELL**
   - Enter **lot size**
   - Set **Stop Loss** (in price or pips)
   - Set **Take Profit** (in price or pips)
   - Choose order type: **Market** (instant) or **Limit** (at a specific price)
2. Click **"Place Order"** to execute.

### 9.3 Open Positions

Below the chart, view all open positions:
- Symbol, side, size, entry price, current price
- Unrealized P&L (color-coded: green = profit, red = loss)
- **Close** button to exit the position
- **Modify** to change SL/TP

### 9.4 Open Orders

View pending limit/stop orders:
- Order type, symbol, side, size, price
- **Cancel** button to remove the order

### 9.5 Trade History

View completed trades with:
- Entry and exit details
- P&L for each trade
- Total P&L summary

### 9.6 Trading Agents

Trading agents are automated bots that execute your strategies:

#### Creating an Agent

1. Click **"New Agent"** in the agents panel.
2. Configure:
   - **Name** — A descriptive name
   - **Strategy** — Which strategy to run
   - **Symbol** — Which instrument to trade
   - **Timeframe** — Candle period
   - **Mode** — Paper (simulated) or Live (real money)
   - **Risk per trade** — % of account to risk
3. Click **"Create"**.

#### Managing Agents

Each agent shows:
- Status (running, paused, stopped, error)
- Symbol and timeframe
- Mode (paper/live)
- Trade count and P&L

Agent actions:
- **▶️ Start** — Activate the agent
- **⏸️ Pause** — Temporarily stop trading
- **⏹️ Stop** — Fully stop the agent
- **🗑️ Delete** — Remove the agent

### 9.7 Strategy Overlay

The Strategy Overlay panel lets you visualize how a strategy interprets the current chart:
- Select a strategy
- View entry/exit signals marked on the chart
- See indicator values in real-time

---

## 10. Watchlist

**Path**: `/watchlist`

Watchlists help you organize and monitor trading instruments.

### 10.1 Creating a Watchlist

1. Click **"New Watchlist"**.
2. Enter a **name** (e.g., "Gold & Silver").
3. Enter **symbols** separated by commas (e.g., `XAUUSD, XAGUSD, EURUSD`).
4. Click **"Create"**.

### 10.2 Managing Watchlists

- **Expand/collapse** — Click a watchlist to show/hide its symbols
- **Add symbol** — Click "Add Symbol" inside an expanded watchlist
- **Remove symbol** — Hover over a symbol chip and click the X
- **Rename** — Click the edit icon
- **Delete** — Click the trash icon (with confirmation)

### 10.3 Price Alerts

Set up notifications when prices hit your targets:

1. Click **"New Alert"**.
2. Configure:
   - **Symbol** — e.g., XAUUSD
   - **Condition** — Price Above, Price Below, or % Change
   - **Threshold** — Target price or percentage
3. Click **"Create Alert"**.

Each alert shows:
- Status indicator (green pulse = active, amber = triggered, gray = paused)
- Symbol and condition
- **Active/Paused** toggle
- **Delete** button

---

## 11. News & Events

**Path**: `/news`

Stay informed about market-moving events and news.

### 11.1 Upcoming High-Impact Events

At the top of the page, a red banner shows upcoming high-impact economic events with countdown timers. These are events that could cause significant price movements.

### 11.2 Sentiment Overview

Sentiment cards for major symbols show:
- Bullish / Bearish / Neutral label
- Sentiment score
- Number of articles analyzed

### 11.3 Tabs

#### Economic Calendar

View scheduled economic events organized by date:
- **Impact filter** — Show All, High, Medium, or Low impact events
- **Currency filter** — Filter by currency (USD, EUR, etc.)
- Each event shows: time, currency, event name, forecast, previous value, and actual (if released)
- Impact is color-coded: 🔴 High, 🟡 Medium, 🔵 Low

#### Market News

A feed of the latest market news articles:
- **Search** — Filter by headline, summary, or related symbols
- **Category** — General, Forex, or Crypto
- Each article shows: headline, source, time, related symbols, sentiment badge
- **Click an article** to open the detail modal

#### Article Detail Modal

When you click a news article:
- Full headline and summary
- Sentiment bar (Bullish/Bearish/Neutral with score)
- Source link
- **AI Trading Analysis** — Click "Run AI Analysis" to get:
  - Key Points
  - Impact Assessment
  - Affected Symbols
  - Trading Recommendation with confidence score
  - Reasoning

> **Requires**: LLM API key configured in Settings → AI Settings.

#### Sentiment Tab

Detailed sentiment data for tracked symbols, powered by Alpha Vantage.

> **Requires**: `ALPHAVANTAGE_API_KEY` environment variable.

---

## 12. Documents & Knowledge Base

**Path**: `/knowledge`

The Documents page has two tabs: **Knowledge** and **User Guide**.

### 12.1 Knowledge Base

A built-in learning system with trading education:

#### Categories
- **Basics** — Fundamental trading concepts
- **Technical Analysis (TA)** — Chart patterns, indicators, price action
- **Fundamental Analysis (FA)** — Economic data, earnings, macro analysis
- **Risk Management** — Position sizing, stop losses, portfolio management
- **Psychology** — Trading mindset, discipline, emotional control
- **Platform** — How to use FlowrexAlgo

#### Articles

Each article has:
- **Difficulty level**: Beginner (green), Intermediate (amber), Advanced (red)
- **Category** indicator
- **Quiz** — Test your knowledge after reading

#### Taking a Quiz

1. Open an article and read it.
2. Click **"Take Quiz"** at the bottom.
3. Answer all multiple-choice questions.
4. Click **"Submit Answers"**.
5. See your score with:
   - Correct/incorrect marks
   - Correct answers highlighted
   - Explanations for each question

#### Progress Tracking

Your learning progress is tracked:
- Total articles available
- Quizzes taken
- Average quiz score
- Recent quiz attempts with scores

#### Seeding Content

If the knowledge base is empty, click **"Load Starter Content"** to populate it with beginner-friendly articles.

### 12.2 User Guide

An in-app version of this guide, accessible directly from the Documents page.

---

## 13. Settings

**Path**: `/settings`

The Settings page is organized into tabs on the left sidebar.

### 13.1 Profile

#### Account Information
- View your username, email, and phone number.
- Update email and phone number.

#### Change Password
1. Enter your **current password**.
2. Enter your **new password**.
3. Click **"Change Password"**.

#### Two-Factor Authentication (2FA)

Enable 2FA for extra security:

1. Click **"Enable 2FA"**.
2. Scan the QR code with your authenticator app (Google Authenticator, Authy, etc.).
3. Enter the 6-digit code from the app.
4. Click **"Verify"**.

To disable:
1. Enter a valid 2FA code.
2. Click **"Disable 2FA"**.

#### Admin Tools (Admin Only)

If you are an administrator, additional sections appear:

**Invite Users**:
1. Enter the new user's email, username, and temporary password.
2. Click **"Send Invitation"**.
3. The user will receive an invitation and must change their password on first login.

**Manage Users**:
- View all registered users.
- See their role (admin/user) and registration date.
- Delete users (with confirmation).

**Password Reset Requests**:
- View pending password reset requests from users.
- Manually reset a user's password.

### 13.2 Appearance

#### Theme Presets

Choose from 8 built-in color themes:

| Theme | Accent Color | Description |
|-------|-------------|-------------|
| Midnight Teal | Cyan | Default dark theme |
| Ocean Blue | Blue | Deep blue tones |
| Emerald Trader | Green | Green finance feel |
| Sunset Gold | Amber | Warm amber tones |
| Neon Purple | Purple | Vibrant purple |
| Classic Dark | Gray | Neutral & minimal |
| Warm Stone | Stone | Earthy warm tones |
| Arctic Light | Sky Blue | Cool & crisp |

Click a theme card to apply it instantly. The active theme has a highlighted border and dot indicator.

#### Chart Colors

Customize the candlestick chart colors:
- **Bullish candle color** — Color for up candles (default: green)
- **Bearish candle color** — Color for down candles (default: red)

### 13.3 AI Settings

Configure the AI assistant that powers chat, strategy analysis, and news insights.

#### LLM Provider

Choose your AI provider:
- **Claude** (Anthropic) — Claude Sonnet 4, Claude Opus 4, Claude 3.5 Haiku
- **OpenAI** — GPT-4o, GPT-4o Mini, o3-mini
- **Gemini** (Google) — Gemini 2.5 Pro, Gemini 2.0 Flash

#### API Key

Enter your API key for the selected provider. The key is stored securely and never displayed after saving.

#### Test Connection

Click **"Test"** to verify your API key and model selection work correctly. You will see either:
- ✓ Success message with model name
- ✗ Error message if the connection fails

### 13.4 Trading

#### Broker Credentials

Configure connections to supported brokers:

**Oanda**:
- Account ID
- API Key (Token)
- Practice/Live environment toggle

**MetaTrader 5**:
- Server address
- Login number
- Password

**Coinbase**:
- API Key
- API Secret

**Tradovate**:
- Username
- Password
- API Key

For each broker:
- **Save Credentials** — Stores them securely
- **Connect** — Tests the connection and establishes a live link
- **Auto-connect** toggle — Automatically connect on startup
- **Delete** — Remove stored credentials

#### Trade Defaults

Set default values for new orders:
- Default risk per trade
- Default stop loss distance
- Default take profit distance
- Confirmation requirements for live trades

### 13.5 Data Management

#### Storage Information

View how much disk space is being used:
- Database size
- Data uploads size
- Total storage used

#### Backup & Restore

- **Export Backup** — Downloads a full backup of your settings, strategies, data sources, and agents as a JSON file (`flowrexalgo_backup_YYYY-MM-DD.json`).
- **Import Backup** — Upload a previously exported backup file to restore your data.

### 13.6 Notifications

#### Email Notifications

- **Enable/disable** email notifications.
- Set which events trigger email alerts.
- **Test** — Send a test email to verify delivery.

#### Telegram Notifications

Connect FlowrexAlgo to Telegram for instant notifications:

1. Enter your **Telegram @username** (without the @ sign).
2. Click **"Save"**.
3. Open Telegram and search for **@FlowrexAgent_bot**.
4. Send the `/start` command to the bot.
5. The bot will automatically link your account and confirm the connection.
6. The status badge will change to **"Connected"** (green).

**Bot Commands**:
| Command | Description |
|---------|-------------|
| `/start` | Link your Telegram account |
| `/status` | Check connection status |
| `/disconnect` | Unlink your account |
| `/help` | Show available commands |

- **Test** — Send a test notification through Telegram (only available when connected).

#### Webhook Notifications

Set up HTTP POST notifications to external services:

1. Click **"Add Webhook"**.
2. Configure:
   - **Name** — A descriptive label
   - **URL** — The endpoint to receive notifications
   - **Secret** (optional) — For HMAC-SHA256 request signing
   - **Events** — Which events to subscribe to (or leave empty for all)
   - **Enabled** toggle

Available webhook events:
- Trade Opened / Closed
- Signal Generated
- Agent Started / Stopped / Error
- Backtest Complete
- Optimization Complete
- Alert Triggered
- Price Alert

For each webhook:
- **Test** — Send a test payload
- **Logs** — View recent delivery logs with status codes
- **Edit** — Modify settings
- **Delete** — Remove the webhook

Status indicators:
- 🟢 Green = healthy
- 🟡 Amber = some failures
- 🔴 Red = consistently failing
- ⚫ Gray = disabled

### 13.7 Platform

#### Recycle Bin

When you delete items (strategies, data sources, backtests, agents, ML models, articles, conversations), they go to the recycle bin instead of being permanently deleted.

In the recycle bin:
- **Restore** — Bring an item back
- **Delete** — Permanently remove an item (cannot be undone)
- **Clear All** — Permanently delete everything in the bin

Each item shows:
- Type icon (strategy, data source, backtest, etc.)
- Name
- Time since deletion

---

## 14. AI Chat Assistant

The AI Chat Assistant is available on every page via the chat icon in the top bar.

### 14.1 What the AI Can Do

- **Answer questions** about trading concepts
- **Explain strategies** and their logic
- **Help build strategies** — Describe what you want and the AI creates it
- **Analyze data** — Ask about your backtest results or market conditions
- **News analysis** — Get AI insights on news articles
- **Platform help** — Ask how to use any feature

### 14.2 Using the Chat

1. Click the chat icon in the top bar to open the panel.
2. Type your question or request.
3. The AI responds in real-time.
4. Previous conversations are saved and can be resumed.

### 14.3 Chat Helpers

On most pages, you will see **chat helper buttons** at the bottom. These are pre-written prompts tailored to the current page. For example:
- On the Dashboard: "Summarize my trading performance"
- On Strategies: "Help me build a strategy for XAUUSD"
- On Backtest: "Explain these results"

---

## 15. Command Palette

Press **`Ctrl+K`** (or `Cmd+K` on Mac) to open the Command Palette.

The Command Palette lets you:
- **Navigate** to any page quickly by typing its name
- **Search** for strategies, data sources, or settings
- **Run actions** like creating a new strategy or starting a backtest

---

## 16. Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+K` | Open Command Palette |
| `Ctrl+B` | Toggle sidebar |
| `Escape` | Close modals and dialogs |

---

## 17. Glossary

| Term | Definition |
|------|------------|
| **Agent** | An automated trading bot that executes a strategy |
| **ATR** | Average True Range — a measure of volatility |
| **Backtest** | Simulating a strategy on historical data |
| **Drawdown** | The decline from a peak to a trough in account value |
| **EMA** | Exponential Moving Average — gives more weight to recent prices |
| **Equity** | Account balance plus unrealized profit/loss |
| **Lot Size** | The quantity of an instrument in a trade |
| **MACD** | Moving Average Convergence Divergence — trend and momentum indicator |
| **Optimization** | Finding the best parameter values for a strategy |
| **Paper Trading** | Simulated trading without real money |
| **Pip** | The smallest standard price movement for a currency pair |
| **Profit Factor** | Gross profit divided by gross loss (>1.0 = profitable) |
| **Robustness** | How well a strategy performs across different time periods |
| **RSI** | Relative Strength Index — momentum oscillator (0-100) |
| **Sharpe Ratio** | Risk-adjusted return (higher is better) |
| **SL** | Stop Loss — an order that closes a losing trade at a set price |
| **SMA** | Simple Moving Average |
| **SQN** | System Quality Number — measure of strategy quality |
| **TP** | Take Profit — an order that closes a winning trade at a set price |
| **VWAP** | Volume Weighted Average Price |
| **Walk-Forward** | Testing optimized parameters on unseen future data |
| **Win Rate** | Percentage of trades that were profitable |

---

## Need Help?

- **In-app AI**: Click the chat icon on any page to ask questions.
- **Knowledge Base**: Visit Documents → Knowledge for trading education.
- **Telegram Bot**: Message @FlowrexAgent_bot for status updates.
- **Contact Admin**: Reach out to your FlowrexAlgo administrator for account issues.

---

*FlowrexAlgo v1.0 — Built for traders, by traders.*
