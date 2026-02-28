# Broker Setup Guide

This guide explains how to connect each supported broker to TradeForge. Each broker requires obtaining API credentials and configuring them in the platform.

## Table of Contents

1. [MetaTrader5 (MT5)](#metatrader5-mt5)
2. [Oanda](#oanda)
3. [Coinbase Advanced Trade](#coinbase-advanced-trade)
4. [Tradovate](#tradovate)
5. [Troubleshooting](#troubleshooting)

---

## MetaTrader5 (MT5)

MetaTrader5 is the most complete integration for TradeForge, providing:
- Live price streaming
- Real-time chart data
- Order placement and management
- Position tracking

### Prerequisites

- **Windows PC** (MetaTrader5 Python library is Windows-only)
- **MetaTrader5 Terminal** installed (free from broker)
- Active trading account with a broker that supports MT5

### Step 1: Set Up MetaTrader5 Terminal

1. **Download MetaTrader5** from your broker's website or [MetaTrader.com](https://www.metatrader5.com)
2. **Install** the application
3. **Login** with your trading account credentials
   - Account Number (your trading account ID)
   - Password (trading password, NOT investor password)
   - Server (broker server, e.g., "Exness-MT5 1")
4. **Enable Auto-Trading**: Tools → Options → Expert Advisors → check "Allow live trading"
5. **Note** the exact **Server Name** (displayed in terminal title bar)

### Step 2: Add MT5 to TradeForge

1. Go to **Settings** (sidebar)
2. Go to **Broker Connections** tab (or **Trading Defaults** → scroll to Broker section)
3. Under **MetaTrader5** section:
   - **Terminal Path**: `C:\Program Files\MetaTrader5\terminal.exe` (default on Windows)
   - **Account Number**: Your MT5 account number (e.g., `1234567`)
   - **Password**: Your MT5 trading password
   - **Server**: Exact server name from terminal (e.g., `Exness-MT5 1`)
4. Click **Test Connection**
   - Green checkmark = success
   - Red error = check credentials and server name
5. Enable **Auto-Connect on Startup** (optional) to auto-login when TradeForge starts

### Step 3: Verify Connection

1. Go to **Dashboard**
2. Look for the **Account Info** widget — should show:
   - Account balance and equity
   - Margin used
   - Broker name (MT5)
3. Go to **Trading** page
   - Data source should show "MT5 Live"
   - Live price ticker should update every 1-2 seconds
   - Chart should populate with candlesticks

### Features Enabled

✅ Live chart streaming  
✅ Place/modify/close orders  
✅ View open positions  
✅ Run strategies on MT5 instruments (XAUUSD, XAGUUSD, US30, NAS100, etc.)  
✅ Fetch historical data for backtesting  

### Troubleshooting MT5

| Problem | Solution |
|---------|----------|
| "Cannot connect to terminal" | Ensure MT5 terminal is open and logged in |
| "Invalid password" | Use trading password, not investor password; check caps lock |
| "Unknown server name" | Copy exact server name from terminal title bar |
| "Live updates not arriving" | Verify "Allow live trading" is enabled in Tools → Options |
| "No instruments visible" | Ensure instruments are added to Market Watch in MT5 |

---

## Oanda

Oanda provides forex and CFD trading via REST API. TradeForge supports Oanda v20 API.

### Prerequisites

- Oanda trading account (sign up at [oanda.com](https://oanda.com))
- API access enabled (usually enabled by default)

### Step 1: Get Your Oanda API Key

1. Log in to **Oanda Account Manager**: [account.oanda.com](https://account.oanda.com)
2. Go to **Manage API Access**
3. Under **API Key Management**:
   - Note your **Account ID** (format: `123-456-7890`)
   - Generate a new **API Token** (or use existing one):
     - Click **Generate Token** if creating new
     - Name: `TradeForge` (for identification)
     - Permissions: Select all (read/write account, read/write trades)
     - Copy the token immediately (you can't view it again)
4. Note the **Environment**:
   - **fxTrade** = Live trading (real money)
   - **fxTrade Practice** = Demo account (sandbox)

### Step 2: Add Oanda to TradeForge

1. Go to **Settings** → **Broker Connections** (or **Trading Defaults**)
2. Under **Oanda** section:
   - **API Key**: Paste your API token
   - **Account ID**: Your account ID (e.g., `123-456-7890`)
   - **Environment**: Choose **fxTrade** (live) or **fxTrade Practice** (demo)
3. Click **Test Connection**
   - Green checkmark = success
   - Red error = check API key and account ID
4. Enable **Auto-Connect on Startup** (optional)

### Step 3: Verify Connection

1. Go to **Dashboard**
2. Account info widget should show Oanda balance/equity
3. Go to **Trading** → Symbol dropdown
   - Oanda symbols: `EUR_USD`, `GBP_USD`, `GOLD`, `XAU_USD`, etc.
   - (Format uses underscores, not slashes)

### Features Enabled

✅ Live price streaming (via REST polling, ~2 sec latency)  
✅ Place/modify/close orders  
✅ Access 100+ forex and CFD pairs  
✅ Fetch historical candle data  

### Supported Instruments

**Forex**: EUR_USD, GBP_USD, USD_JPY, etc.  
**Metals**: XAU_USD (Gold), XAG_USD (Silver)  
**Indices**: US30, NAS100, SPX500  
**Commodities**: WTICRUDE, NATGAS  
**Crypto**: Bitcoin, Ethereum (where available)  

Full list: See [Oanda API Instruments](https://docs.oanda.com/forex-trading-oanda-api-v20/reference/pricing-tools/getinstruments)

### Troubleshooting Oanda

| Problem | Solution |
|---------|----------|
| "Invalid API key" | Check key hasn't expired; regenerate if needed |
| "Account not found" | Verify account ID format: `123-456-7890` |
| "Live updates are slow" | Oanda REST API updates every 2-3 seconds; this is normal |
| "Symbol not found" | Verify symbol format uses underscores: `EUR_USD` not `EURUSD` |

---

## Coinbase Advanced Trade

Coinbase provides crypto trading via REST and WebSocket APIs.

### Prerequisites

- Coinbase account (sign up at [coinbase.com](https://coinbase.com))
- Verified account with funding enabled
- API access enabled

### Step 1: Generate Coinbase API Key

1. Log in to **Coinbase**: [coinbase.com](https://coinbase.com)
2. Click your profile → **Settings**
3. Go to **API** tab
4. Click **Create API Key**
5. Select scope: **Trade** (or **Full** for complete access)
6. Set IP Whitelist: Add your IP or leave blank for unrestricted
7. Confirm identity (2FA required)
8. Copy the following immediately (can't be viewed again):
   - **API Key** (public key)
   - **API Secret** (private key)
   - **Passphrase** (set during creation)

### Step 2: Add Coinbase to TradeForge

1. Go to **Settings** → **Broker Connections**
2. Under **Coinbase** section:
   - **API Key**: Your public API key
   - **API Secret**: Your private API secret
   - **Passphrase**: Your passphrase
   - **Sandbox Mode**: Toggle ON for testing, OFF for live
3. Click **Test Connection**
   - Green checkmark = success
   - Red error = check credentials
4. Enable **Auto-Connect on Startup** (optional)

### Step 3: Verify Connection

1. Go to **Dashboard**
2. Account info widget should show Coinbase balance
3. Go to **Trading** → Symbol dropdown
   - Coinbase symbols: `BTC-USD`, `ETH-USD`, `SOL-USD`, etc.

### Features Enabled

✅ Live price streaming  
✅ Place market/limit orders  
✅ View positions and balances  
✅ Trade 100+ crypto pairs  

### Supported Pairs

**Major**: BTC-USD, ETH-USD, USDC-USD  
**Alt Coins**: SOL-USD, XRP-USD, ADA-USD, DOT-USD, etc.  
**Stablecoins**: USDC-USD, USDT-USD, DAI-USD  

Full list: See [Coinbase API Products](https://api.coinbase.com/v1/products)

### Sandbox Testing

To test without real money:
1. Enable **Sandbox Mode** in settings
2. Create a sandbox account at [sandbox.coinbase.com](https://sandbox.coinbase.com)
3. Use sandbox API credentials
4. Same API format as live, but trades are simulated

### Troubleshooting Coinbase

| Problem | Solution |
|---------|----------|
| "Invalid API key" | Regenerate key and copy again (check for trailing spaces) |
| "Passphrase required" | You must provide the passphrase set during API creation |
| "Insufficient permissions" | Ensure API key has **Trade** scope enabled |
| "IP not whitelisted" | Add your IP to whitelist in Coinbase settings, or remove IP whitelist |

---

## Tradovate

Tradovate provides futures trading via REST API and WebSocket.

### Prerequisites

- Tradovate account (sign up at [tradovate.com](https://tradovate.com))
- Funded account with live or demo trading enabled
- API access enabled

### Step 1: Get Tradovate API Credentials

1. Log in to **Tradovate Account**: [tradovate.com](https://tradovate.com)
2. Go to **Account Settings** → **API**
3. Under **API Credentials**:
   - **Account ID** or **Username**: Your trading account name
   - **Password**: API password (may differ from account password)
   - Generate/copy **Device Token** (optional, for persistent sessions)
4. Note the **API Endpoint**:
   - **Live**: `https://api.tradovate.net`
   - **Demo**: `https://demo.tradovate.net`

### Step 2: Add Tradovate to TradeForge

1. Go to **Settings** → **Broker Connections**
2. Under **Tradovate** section:
   - **Username**: Your Tradovate account name
   - **Password**: Your API password
   - **Account ID**: Your account number
   - **Environment**: Choose **Live** or **Demo**
3. Click **Test Connection**
   - Green checkmark = success
   - Red error = check credentials and environment
4. Enable **Auto-Connect on Startup** (optional)

### Step 3: Verify Connection

1. Go to **Dashboard**
2. Account info widget should show Tradovate balance
3. Go to **Trading** → Symbol dropdown
   - Tradovate futures: `/ES` (S&P 500), `/MES` (Micro S&P), `/NQ` (Nasdaq), etc.

### Features Enabled

✅ Live futures trading  
✅ Access 100+ commodity, index, and currency futures  
✅ Real-time streaming prices  
✅ Place/modify/cancel orders  

### Supported Contracts

**Index Futures**: /ES, /MES, /NQ, /MNQ  
**Energy**: /CL (crude oil), /NG (natural gas)  
**Metals**: /GC (gold), /SI (silver)  
**Agriculture**: /ZW (wheat), /ZC (corn)  
**Currency**: /6E (EUR), /6J (JPY)  

Full list: See [Tradovate Contract List](https://www.tradovate.com/contracts)

### Demo Trading

1. Use **Demo** environment to paper-trade without real money
2. Demo accounts reset regularly; use for testing only
3. Switch to **Live** when ready with real capital

### Troubleshooting Tradovate

| Problem | Solution |
|---------|----------|
| "Invalid credentials" | Verify username is your account name (not email); use API password |
| "Contract not found" | Verify contract name starts with `/` (e.g., `/ES` not `ES`) |
| "Demo account expired" | Create new demo account in Tradovate settings |
| "Insufficient margin" | Ensure account has enough buying power for contract size |

---

## Troubleshooting

### General Issues

**"Broker connection fails after 1-2 days"**
- API tokens may expire; regenerate and update in TradeForge
- Auto-reconnect is in development

**"Data is delayed or missing"**
- Free APIs have rate limits; premium plans have better latency
- Oanda REST API updates ~2 sec; WebSocket is planned for faster updates

**"Can't place orders"**
- Verify account has trading enabled (not demo/sandbox only)
- Check available margin/balance
- Verify instrument is available on your account

**"Different prices on chart vs broker"**
- Broker platforms may use different data sources
- Small differences (few pips) are normal due to latency
- Large differences indicate data feed issue — check connection

### Getting Help

1. Check the [Getting Started Guide](./00_GETTING_STARTED.md#troubleshooting)
2. Check broker's API documentation:
   - [Oanda API Docs](https://docs.oanda.com)
   - [Coinbase API Docs](https://docs.cloud.coinbase.com)
   - [Tradovate API Docs](https://api.tradovate.com)
3. Open an issue on [GitHub Issues](https://github.com/DemasJ2k/Tradeforge/issues)

---

## Security Best Practices

1. **Never share API keys** — treat them like passwords
2. **Use API Key Permissions** — limit scope to what's needed (trading only, no account modification)
3. **Whitelist IPs** (where available) — restrict API access to your machine
4. **Regenerate keys regularly** — if exposed, immediately revoke and create new
5. **Store safely** — TradeForge encrypts API keys at rest; don't commit to git
6. **Enable 2FA** — on broker accounts for additional security

---

**Next Steps**: See [Strategy Builder Guide](./02_STRATEGY_BUILDER.md) to create your first trading strategy.
