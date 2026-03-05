"use client";

import { useState, useMemo } from "react";
import {
  Search, ChevronRight, BookOpen, Key, Database, BarChart2,
  SlidersHorizontal, Brain, TrendingUp, LayoutDashboard, Settings,
  HelpCircle, Lightbulb, AlertTriangle, Info, CheckCircle2,
  Eye, Bell, Newspaper, Star,
} from "lucide-react";

/* ─── Types ───────────────────────────────────────── */
interface GuideSection {
  id: string;
  title: string;
  icon: React.ReactNode;
  topics: GuideTopic[];
}

interface GuideTopic {
  id: string;
  title: string;
  content: React.ReactNode;
}

/* ─── Callout Components ──────────────────────────── */
function Tip({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/8 px-4 py-3 my-3">
      <Lightbulb className="h-4 w-4 shrink-0 mt-0.5 text-emerald-400" />
      <p className="text-sm text-emerald-300/90">{children}</p>
    </div>
  );
}

function Warning({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex gap-3 rounded-xl border border-amber-500/30 bg-amber-500/8 px-4 py-3 my-3">
      <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5 text-amber-400" />
      <p className="text-sm text-amber-300/90">{children}</p>
    </div>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex gap-3 rounded-xl border border-blue-500/30 bg-blue-500/8 px-4 py-3 my-3">
      <Info className="h-4 w-4 shrink-0 mt-0.5 text-blue-400" />
      <p className="text-sm text-blue-300/90">{children}</p>
    </div>
  );
}

function Step({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <div className="flex gap-3 items-start mb-3">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent text-[11px] font-bold text-black mt-0.5">
        {n}
      </span>
      <span className="text-sm text-foreground/80">{children}</span>
    </div>
  );
}

function H2({ children }: { children: React.ReactNode }) {
  return <h2 className="text-lg font-semibold text-foreground mt-6 mb-3 first:mt-0">{children}</h2>;
}
function H3({ children }: { children: React.ReactNode }) {
  return <h3 className="text-sm font-semibold text-foreground mt-4 mb-2">{children}</h3>;
}
function P({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-foreground/75 leading-relaxed mb-2">{children}</p>;
}
function UL({ items }: { items: string[] }) {
  return (
    <ul className="space-y-1 mb-3">
      {items.map((item, i) => (
        <li key={i} className="flex items-start gap-2 text-sm text-foreground/75">
          <ChevronRight className="h-3.5 w-3.5 shrink-0 mt-0.5 text-accent" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}
function Code({ children }: { children: React.ReactNode }) {
  return <code className="rounded bg-background/80 border border-card-border px-1.5 py-0.5 text-xs text-accent font-mono">{children}</code>;
}
function Badge({ color, children }: { color: string; children: React.ReactNode }) {
  return <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium ${color}`}>{children}</span>;
}

/* ─── Guide Content ───────────────────────────────── */
const GUIDE_SECTIONS: GuideSection[] = [
  /* ================================================================
     SECTION 1 — GETTING STARTED
     ================================================================ */
  {
    id: "getting-started",
    title: "Getting Started",
    icon: <BookOpen className="h-4 w-4" />,
    topics: [
      {
        id: "what-is",
        title: "What is FlowrexAlgo?",
        content: (
          <>
            <H2>What is FlowrexAlgo?</H2>
            <P>
              FlowrexAlgo is an all-in-one algorithmic trading platform. It lets you build, test, optimize, and deploy trading strategies — without writing a single line of code if you choose not to.
            </P>
            <P>
              The platform brings together everything a systematic trader needs in one dashboard: live market data, a no-code strategy builder, a professional backtesting engine, an AI-powered optimizer, ML agent support, and direct broker connectivity.
            </P>
            <Tip>If you are completely new, start with the <strong>Data</strong> page to fetch a dataset, then head to <strong>Strategies</strong> to create your first strategy, and finally run a <strong>Backtest</strong> to see how it performs.</Tip>
            <H3>Key Concepts</H3>
            <UL items={[
              "Strategy — a set of rules that define when to buy and when to sell.",
              "Backtest — a simulation of your strategy on historical data to see how it would have performed.",
              "Optimization — automatically testing many parameter combinations to find the best settings.",
              "Algo Agent — an automated bot that runs your strategy live, in paper mode, or in confirmation mode.",
              "ML Agent — an AI model that can generate or refine trading signals.",
            ]} />
            <H3>Supported Markets</H3>
            <UL items={[
              "Forex — XAUUSD, EURUSD, GBPUSD, etc. via Oanda or MetaTrader 5.",
              "Crypto — BTC, ETH, etc. via Coinbase.",
              "Futures — US30, NAS100, etc. via Tradovate.",
              "Any instrument supported by your connected broker.",
            ]} />
          </>
        ),
      },
      {
        id: "navigating",
        title: "Navigating the App",
        content: (
          <>
            <H2>Navigating the App</H2>
            <P>The main navigation lives in the collapsible sidebar on the left. You can expand or collapse it with the toggle button.</P>
            <H3>Pages at a Glance</H3>
            <UL items={[
              "Dashboard — overview of your portfolio, open positions, recent trades, and active agents.",
              "Data — upload CSV files or fetch historical candle data from a connected broker.",
              "Strategies — create, edit, organise, import, and manage trading strategies.",
              "Backtest — run historical simulations and review detailed performance reports.",
              "Optimize — find the best parameter settings using Bayesian or Genetic algorithms.",
              "ML Lab — train machine learning models to generate or enhance trading signals.",
              "Trading — live chart with real-time prices, place orders, manage positions, run Algo Agents.",
              "Watchlist — create symbol watchlists and set price alerts.",
              "News — economic calendar, news feed with sentiment analysis, and AI-powered analysis.",
              "Documents (you are here) — learning materials, quizzes, and this user guide.",
              "Settings — account, appearance, AI config, broker connections, notifications, and more.",
            ]} />
            <Tip>Press <strong>Ctrl + K</strong> at any time to open the Command Palette and quickly jump to any page, switch themes, or search for features.</Tip>
          </>
        ),
      },
    ],
  },

  /* ================================================================
     SECTION 2 — BROKER SETUP
     ================================================================ */
  {
    id: "broker",
    title: "Broker Setup & API Keys",
    icon: <Key className="h-4 w-4" />,
    topics: [
      {
        id: "connecting-broker",
        title: "Connecting a Broker",
        content: (
          <>
            <H2>Connecting a Broker</H2>
            <P>FlowrexAlgo supports four brokers. You connect them via <strong>Settings → Trading</strong> (Broker Credentials section) or directly from the Trading page.</P>
            <H3>Supported Brokers</H3>
            <div className="grid grid-cols-2 gap-2 mt-2 mb-3">
              {[
                ["MetaTrader 5 (MT5)", "Forex, metals, indices. Requires MT5 terminal running."],
                ["Oanda", "Forex & CFDs. REST API. Paper & live accounts."],
                ["Coinbase", "Crypto (BTC, ETH, etc). REST API with key + secret + passphrase."],
                ["Tradovate", "Futures (ES, NQ, YM, GC). Username + password + account ID."],
              ].map(([name, desc]) => (
                <div key={name as string} className="rounded-lg border border-card-border bg-card-bg p-3">
                  <div className="text-xs font-semibold text-foreground mb-1">{name}</div>
                  <div className="text-xs text-muted-foreground">{desc}</div>
                </div>
              ))}
            </div>
            <Step n={1}>Go to <strong>Settings</strong> in the left sidebar.</Step>
            <Step n={2}>Select the <strong>Trading</strong> tab.</Step>
            <Step n={3}>Scroll down to <strong>Broker Credentials</strong>.</Step>
            <Step n={4}>Select the broker from the dropdown and enter the required fields (see below).</Step>
            <Step n={5}>Click <strong>Save Credentials</strong>. The broker will appear as connected.</Step>
            <Warning>Never share your API keys with anyone. FlowrexAlgo stores them securely on the backend, but you should still use keys with only the permissions you need.</Warning>
          </>
        ),
      },
      {
        id: "api-keys",
        title: "Finding Your API Keys",
        content: (
          <>
            <H2>Finding Your API Keys</H2>
            <P>Every broker generates API keys from within their web portal. Here is where to find them:</P>

            <H3>MetaTrader 5</H3>
            <UL items={[
              "Terminal Path — the full path to your MT5 installation folder (e.g. C:\\Program Files\\MetaTrader 5).",
              "Account Number — your MT5 login number.",
              "Password — your MT5 trading password.",
              "Server — the broker server name (e.g. ICMarkets-Demo).",
            ]} />
            <Note>MT5 must be installed and the terminal must be running for the connection to work. FlowrexAlgo communicates directly with the MT5 process.</Note>

            <H3>Oanda</H3>
            <Step n={1}>Log in to your Oanda account at <strong>fxTrade</strong> or <strong>fxTrade Practice</strong>.</Step>
            <Step n={2}>Go to <strong>Manage API Access</strong> in your account settings.</Step>
            <Step n={3}>Generate a new personal access token (API key). Copy it immediately — it is only shown once.</Step>
            <Step n={4}>Your Account ID is shown in the account dropdown (e.g. <Code>101-001-12345678-001</Code>).</Step>
            <Step n={5}>Choose <strong>Practice</strong> or <strong>Live</strong> environment in FlowrexAlgo to match.</Step>
            <Tip>Oanda has separate Practice and Live environments. Always start with Practice to test your setup.</Tip>

            <H3>Coinbase</H3>
            <Step n={1}>Log in to <strong>Coinbase Advanced</strong>.</Step>
            <Step n={2}>Go to <strong>Settings → API</strong>.</Step>
            <Step n={3}>Create a new API key. You will receive an <strong>API Key</strong>, <strong>API Secret</strong>, and <strong>Passphrase</strong>.</Step>
            <Warning>The passphrase is only shown once during creation. Store it safely — you cannot retrieve it later.</Warning>

            <H3>Tradovate</H3>
            <UL items={[
              "Username — your Tradovate login username.",
              "Password — your Tradovate password.",
              "Account ID — found in your Tradovate dashboard.",
            ]} />
          </>
        ),
      },
    ],
  },

  /* ================================================================
     SECTION 3 — DATA SOURCES
     ================================================================ */
  {
    id: "data",
    title: "Data Sources",
    icon: <Database className="h-4 w-4" />,
    topics: [
      {
        id: "data-overview",
        title: "Data Sources Overview",
        content: (
          <>
            <H2>Data Sources Overview</H2>
            <P>The <strong>Data</strong> page is where you manage all the market data FlowrexAlgo uses for backtesting, optimization, and ML training. Without data, strategies cannot be tested.</P>
            <H3>How to Get Data</H3>
            <UL items={[
              "CSV Upload — drag and drop your own OHLCV CSV files directly onto the page.",
              "Fetch from Broker — download historical candle data from any connected broker (MT5, Oanda, Coinbase, Tradovate).",
            ]} />
            <H3>Your Data Library</H3>
            <P>All uploaded/fetched data appears in a table showing the instrument name, timeframe, number of candles, date range, source, and file size. Click any row to expand it and see:</P>
            <UL items={[
              "Instrument Profile — detailed statistics about the dataset.",
              "Data Preview — the first 10 rows of OHLCV data in a table.",
              "Download — export the data as a CSV file.",
              "Delete — remove the data source.",
            ]} />
          </>
        ),
      },
      {
        id: "csv-upload",
        title: "Uploading CSV Data",
        content: (
          <>
            <H2>Uploading CSV Data</H2>
            <P>You can upload your own historical data from any source. The CSV file must follow a specific format:</P>
            <Step n={1}>Navigate to the <strong>Data</strong> page from the sidebar.</Step>
            <Step n={2}>Drag and drop one or more <Code>.csv</Code> files onto the upload area, or click to browse.</Step>
            <Step n={3}>FlowrexAlgo will automatically detect the symbol and timeframe from the filename.</Step>
            <H3>CSV Format Requirements</H3>
            <P>Your CSV must contain these columns (case-insensitive):</P>
            <div className="rounded-lg bg-background/80 border border-card-border p-3 font-mono text-xs text-accent mb-3">
              date, open, high, low, close, volume
            </div>
            <H3>Filename Convention</H3>
            <P>For automatic symbol/timeframe detection, name your files like:</P>
            <div className="rounded-lg bg-background/80 border border-card-border p-3 font-mono text-xs text-accent mb-3">
              XAUUSD_M15.csv &nbsp;or&nbsp; BTCUSD_H1.csv
            </div>
            <Note>Dates can be in ISO format (<Code>YYYY-MM-DD HH:MM:SS</Code>) or MT5 dot format (<Code>YYYY.MM.DD HH:MM:SS</Code>). A column named <Code>tick_volume</Code> is automatically renamed to <Code>volume</Code>.</Note>
            <Warning>Rows with missing values will be dropped. Make sure your data is clean before uploading for best results.</Warning>
          </>
        ),
      },
      {
        id: "fetch-broker",
        title: "Fetching from Broker",
        content: (
          <>
            <H2>Fetching Data from a Broker</H2>
            <P>If you have a broker connected, you can download historical candle data directly without needing CSV files.</P>
            <Step n={1}>On the <strong>Data</strong> page, click the <strong>Fetch from Broker</strong> button.</Step>
            <Step n={2}>Select the <strong>Broker</strong> (MT5, Oanda, Coinbase, or Tradovate).</Step>
            <Step n={3}>Enter the <strong>Symbol</strong> (e.g. <Code>XAUUSD</Code>, <Code>BTCUSD</Code>, <Code>US30</Code>).</Step>
            <Step n={4}>Select the <strong>Timeframe</strong>: M1, M5, M15, M30, H1, H4, or D1.</Step>
            <Step n={5}>Set the number of <strong>Bars</strong> to download (default: 5000).</Step>
            <Step n={6}>Click <strong>Fetch Data</strong>. The data will be downloaded and added to your library.</Step>
            <H3>Supported Timeframes</H3>
            <UL items={["M1 — 1 Minute", "M5 — 5 Minutes", "M15 — 15 Minutes", "M30 — 30 Minutes", "H1 — 1 Hour", "H4 — 4 Hours", "D1 — Daily"]} />
            <Tip>For backtesting on shorter timeframes (M1–M15), fetch as many bars as possible (10000+). Longer data history gives more reliable backtest results.</Tip>
            <Note>Make sure you have saved your broker credentials in <strong>Settings → Trading</strong> before trying to fetch. The modal will remind you if credentials are missing.</Note>
          </>
        ),
      },
    ],
  },

  /* ================================================================
     SECTION 4 — STRATEGY BUILDER
     ================================================================ */
  {
    id: "strategies",
    title: "Strategy Builder",
    icon: <BookOpen className="h-4 w-4" />,
    topics: [
      {
        id: "create-strategy",
        title: "Creating a Strategy",
        content: (
          <>
            <H2>Creating a Strategy</H2>
            <P>Strategies are the heart of FlowrexAlgo. A strategy is a set of rules: when to enter a trade, when to exit, and how much to risk.</P>
            <Step n={1}>Go to the <strong>Strategies</strong> page.</Step>
            <Step n={2}>Click <strong>+ New Strategy</strong>.</Step>
            <Step n={3}>Give your strategy a name and optional description.</Step>
            <Step n={4}>Define your <strong>Entry Conditions</strong> — the rules that trigger a buy (long) or sell (short) signal. Example: &ldquo;SMA(20) crosses above SMA(50)&rdquo;.</Step>
            <Step n={5}>Define your <strong>Exit Conditions</strong> — rules to close the position. Example: &ldquo;Take profit at 3× ATR&rdquo; or &ldquo;Opposite signal&rdquo;.</Step>
            <Step n={6}>Set <strong>Risk Management</strong> parameters: lot size, stop-loss, take-profit, max positions, and daily loss limit.</Step>
            <Step n={7}>Click <strong>Save</strong>.</Step>
            <Tip>You can duplicate an existing strategy by clicking the three-dot menu on any strategy card. This is a great way to experiment with variations without losing your original.</Tip>
            <H3>Strategy Organisation</H3>
            <UL items={[
              "Folders — group strategies into folders for organisation. Click 'New Folder' and drag strategies into them.",
              "Search — use the search bar at the top to filter strategies by name, description, or type.",
              "Rename — double-click a strategy name to rename it in-place.",
              "Delete — deleting a strategy will also remove all associated backtests, agents, and ML models.",
            ]} />
          </>
        ),
      },
      {
        id: "ai-import",
        title: "AI Strategy Import",
        content: (
          <>
            <H2>AI Strategy Import</H2>
            <P>FlowrexAlgo can automatically convert a TradingView Pine Script or a plain-text strategy description into a FlowrexAlgo strategy — powered by AI.</P>
            <Step n={1}>On the <strong>Strategies</strong> page, click the <strong>AI Import</strong> button (sparkle icon).</Step>
            <Step n={2}>Either <strong>upload a Pine Script file</strong> or <strong>type/paste a strategy description</strong> in plain text.</Step>
            <Step n={3}>Click <strong>Import</strong>. The AI will parse your rules and create a FlowrexAlgo strategy automatically.</Step>
            <Step n={4}>Review the generated strategy. Make adjustments if needed, then save.</Step>
            <Note>AI import works best with clear, specific descriptions. For example: &ldquo;Buy when RSI(14) drops below 30 and MACD histogram turns positive. Sell when RSI(14) goes above 70. Use 1.5 ATR stop-loss and 3.0 ATR take-profit.&rdquo;</Note>
            <Warning>Always review AI-imported strategies before backtesting. The AI may interpret ambiguous rules differently than you intended.</Warning>
          </>
        ),
      },
      {
        id: "conditions",
        title: "Indicators & Conditions",
        content: (
          <>
            <H2>Indicators &amp; Conditions</H2>
            <P>Conditions are logical rules built from <strong>indicators</strong> compared with each other or with fixed thresholds. They determine when your strategy enters and exits trades.</P>
            <H3>Adding a Condition</H3>
            <Step n={1}>Inside the strategy editor, click <strong>+ Add Condition</strong> in the Entry or Exit section.</Step>
            <Step n={2}>Choose the <strong>left-hand side</strong>: an indicator or price value (e.g. <Code>RSI(14)</Code>, <Code>Close</Code>).</Step>
            <Step n={3}>Choose the <strong>operator</strong>: <Code>&gt;</Code>, <Code>&lt;</Code>, <Code>crosses above</Code>, <Code>crosses below</Code>, <Code>==</Code>.</Step>
            <Step n={4}>Choose the <strong>right-hand side</strong>: another indicator, a fixed number, or a price level.</Step>
            <Step n={5}>Add multiple conditions. By default all must be true (<strong>AND logic</strong>). Toggle to <strong>OR</strong> if any one condition should trigger.</Step>

            <H3>Available Indicators</H3>
            <P>FlowrexAlgo includes 18 built-in indicators across two categories:</P>
            <div className="grid grid-cols-2 gap-2 mt-2 mb-3">
              {[
                ["Overlay Indicators", "SMA, EMA, Bollinger Bands, VWAP, Parabolic SAR, SuperTrend, Ichimoku Cloud, Keltner Channel, Donchian Channel"],
                ["Oscillator Indicators", "MACD, RSI, ATR, Stochastic, ADX, CCI, Williams %R, OBV, MFI"],
              ].map(([cat, inds]) => (
                <div key={cat as string} className="rounded-lg border border-card-border bg-card-bg p-3">
                  <div className="text-xs font-semibold text-foreground mb-1">{cat}</div>
                  <div className="text-xs text-muted-foreground">{inds}</div>
                </div>
              ))}
            </div>
            <Note><strong>Overlay indicators</strong> are drawn on top of the price chart (like moving averages). <strong>Oscillator indicators</strong> appear in a separate pane below the chart (like RSI). You can add multiple of each on the Trading page chart.</Note>
          </>
        ),
      },
      {
        id: "risk-management",
        title: "Risk Management",
        content: (
          <>
            <H2>Risk Management</H2>
            <P>Risk management controls how much capital is allocated per trade and how losses are limited. These settings are configured within each strategy.</P>
            <H3>Key Parameters</H3>
            <UL items={[
              "Lot Size — the position size for each trade (e.g. 0.01, 0.1, 1.0 lots).",
              "Stop-Loss — an ATR-multiple or fixed-pip distance to limit losses per trade.",
              "Take-Profit — an ATR-multiple or fixed-pip distance to lock in gains.",
              "Max Positions — the maximum number of open trades at one time.",
              "Daily Loss Limit — automatically pause the strategy if daily losses exceed this amount.",
            ]} />
            <Warning>Always use a stop-loss. Strategies without defined exits can experience catastrophic drawdowns during unexpected market events.</Warning>
            <Tip>A common approach is to use ATR-based stops. For example: stop-loss = 1.5× ATR and take-profit = 3.0× ATR. This adapts automatically to market volatility.</Tip>
          </>
        ),
      },
    ],
  },

  /* ================================================================
     SECTION 5 — BACKTESTING
     ================================================================ */
  {
    id: "backtest",
    title: "Backtesting",
    icon: <BarChart2 className="h-4 w-4" />,
    topics: [
      {
        id: "run-backtest",
        title: "Running a Backtest",
        content: (
          <>
            <H2>Running a Backtest</H2>
            <P>A backtest simulates how your strategy would have performed on historical data. It is the primary tool for evaluating a strategy before risking real money.</P>
            <Step n={1}>Go to the <strong>Backtest</strong> page.</Step>
            <Step n={2}>Click <strong>New Backtest</strong> to open the configuration dialog.</Step>
            <Step n={3}>Select the <strong>Strategy</strong> to test from the dropdown.</Step>
            <Step n={4}>Select the <strong>Data Source</strong> (this is the historical data you uploaded or fetched).</Step>
            <Step n={5}>Set the <strong>Initial Balance</strong> (the starting account balance for the simulation, e.g. $10,000).</Step>
            <Step n={6}>Click <strong>Run Backtest</strong>.</Step>
            <Note>The backtest uses the strategy&apos;s built-in risk parameters (lot size, SL, TP). If you want to test different risk settings, edit the strategy first or duplicate it.</Note>
          </>
        ),
      },
      {
        id: "reading-results",
        title: "Understanding Results",
        content: (
          <>
            <H2>Understanding Backtest Results</H2>
            <P>After a backtest completes, you see a comprehensive dashboard with several sections:</P>
            <H3>Stats Cards</H3>
            <UL items={[
              "Net Profit — total profit or loss in currency and percentage.",
              "Win Rate — percentage of trades that were profitable.",
              "Profit Factor — gross profit ÷ gross loss. Above 1.5 is healthy.",
              "Max Drawdown — the largest peak-to-trough decline in equity. Smaller is better.",
              "Total Trades — the total number of completed trades.",
              "Sharpe Ratio — return per unit of risk. Above 1.0 is good, above 2.0 is excellent.",
              "Avg Win / Avg Loss — compare these: a low win rate can still be profitable if Avg Win >> Avg Loss.",
              "Expectancy — how much you can expect to make per trade on average.",
            ]} />
            <H3>Charts &amp; Visualisations</H3>
            <UL items={[
              "Equity Curve — shows portfolio value over time. Look for a smooth upward slope.",
              "Drawdown Chart — visualises periods of decline from peak equity.",
              "Monthly Returns Heatmap — colour-coded table showing performance by month and year.",
              "Trade Chart — overlays buy/sell arrows on the candle chart so you can see exactly where trades happened.",
            ]} />
            <H3>Trade Log</H3>
            <P>A detailed table of every trade: entry/exit dates, prices, side (long/short), profit, holding time, and more. You can sort and filter the table.</P>
            <Warning>A strategy that looks perfect on backtests may be overfitted. Always validate on out-of-sample data or use walk-forward testing before going live.</Warning>
            <Tip>Use the <strong>Equity Curve</strong> to spot if a strategy stopped working. A flat or declining curve in recent months is a red flag.</Tip>
          </>
        ),
      },
    ],
  },

  /* ================================================================
     SECTION 6 — OPTIMIZATION
     ================================================================ */
  {
    id: "optimization",
    title: "Optimization",
    icon: <SlidersHorizontal className="h-4 w-4" />,
    topics: [
      {
        id: "what-is-optimization",
        title: "What Does Optimization Do?",
        content: (
          <>
            <H2>What Does Optimization Do?</H2>
            <P>Optimization automatically runs your strategy <em>hundreds or thousands of times</em> with different parameter values, then ranks all combinations by a performance metric to find the best settings.</P>
            <P>For example: if your strategy uses SMA(20) and SMA(50), optimization can test every combination of periods from 5–100 to find which pair historically performed best.</P>
            <Warning>Optimization can lead to <strong>overfitting</strong> — where parameters are tuned so precisely to past data that they fail in the future. Always validate optimized parameters on out-of-sample data.</Warning>
            <H3>Optimization Methods</H3>
            <UL items={[
              "Bayesian Optimization (Optuna) — intelligently focuses on promising areas using probability models. Best balance of speed and thoroughness. Recommended.",
              "Genetic Algorithm (DEAP) — evolves populations of parameter sets using crossover and mutation, inspired by natural selection. Good for complex, multi-parameter spaces.",
            ]} />
            <H3>Objective Metrics</H3>
            <P>You choose what to maximize:</P>
            <UL items={[
              "Sharpe Ratio — maximise risk-adjusted return.",
              "Net Profit — maximise total return.",
              "Profit Factor — maximise win/loss ratio.",
              "Custom — combine multiple metrics with weights.",
            ]} />
          </>
        ),
      },
      {
        id: "run-optimization",
        title: "Running an Optimization",
        content: (
          <>
            <H2>Running an Optimization</H2>
            <Step n={1}>Go to the <strong>Optimize</strong> page.</Step>
            <Step n={2}>Select the <strong>Strategy</strong> to optimize.</Step>
            <Step n={3}>Select the <strong>Data Source</strong>.</Step>
            <Step n={4}>Click <strong>Define Parameters</strong>. For each parameter you want to optimize, set a <em>min value</em>, <em>max value</em>, and <em>step size</em>.</Step>
            <Step n={5}>Choose the <strong>optimization method</strong> (Bayesian or Genetic).</Step>
            <Step n={6}>Choose the <strong>objective metric</strong> to maximize.</Step>
            <Step n={7}>Set any <strong>constraints</strong> (e.g. minimum trade count, maximum drawdown limit).</Step>
            <Step n={8}>Click <strong>Start Optimization</strong>. Progress is shown in real time.</Step>
            <Step n={9}>When complete, review the <strong>Results Table</strong>, then click <strong>Apply Best Parameters</strong> to update your strategy.</Step>
            <Tip>Start with wide ranges to get a general picture, then narrow down around the best region. This is faster than a fine grid over the full range.</Tip>
          </>
        ),
      },
      {
        id: "robustness",
        title: "Robustness Testing",
        content: (
          <>
            <H2>Robustness Testing</H2>
            <P>After optimization finds the best parameters, robustness testing checks whether those parameters generalise across different time periods — or only work on the specific data they were optimized on.</P>
            <H3>How It Works</H3>
            <UL items={[
              "The optimized parameters are tested on multiple time windows: full period, yearly splits, first half, second half, and the most recent 25%.",
              "Each window is run as a separate backtest and scored on profit factor, net profit, and trade count.",
              "A window passes if the profit factor > 1.2 AND net profit > 0.",
              "The robustness score is the percentage of windows that pass.",
            ]} />
            <H3>Interpreting Robustness</H3>
            <div className="rounded-xl border border-card-border overflow-hidden mb-3">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-card-bg border-b border-card-border">
                    <th className="text-left px-3 py-2 text-muted-foreground">Score</th>
                    <th className="text-left px-3 py-2 text-muted-foreground">Rating</th>
                    <th className="text-left px-3 py-2 text-muted-foreground">Meaning</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    ["60%+", "✅ GOOD", "Strategy works across most time periods. Ready for paper trading."],
                    ["40–59%", "⚠️ MARGINAL", "Works in some periods. More testing recommended."],
                    ["< 40%", "❌ POOR", "Likely overfitted to specific market conditions. Avoid live trading."],
                  ].map(([score, rating, meaning]) => (
                    <tr key={score as string} className="border-b border-card-border/50 last:border-0">
                      <td className="px-3 py-2 text-foreground/80 font-mono">{score}</td>
                      <td className="px-3 py-2 text-foreground">{rating}</td>
                      <td className="px-3 py-2 text-muted-foreground">{meaning}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Warning>Never deploy a strategy with a POOR robustness score to live trading. It is likely to lose money in real market conditions.</Warning>
          </>
        ),
      },
    ],
  },

  /* ================================================================
     SECTION 7 — ML LAB
     ================================================================ */
  {
    id: "ml",
    title: "ML Lab & AI Agents",
    icon: <Brain className="h-4 w-4" />,
    topics: [
      {
        id: "ml-overview",
        title: "ML Lab Overview",
        content: (
          <>
            <H2>ML Lab Overview</H2>
            <P>The ML Lab lets you train machine learning models that can enhance or replace rule-based strategies. Models learn patterns from historical data and can adapt to changing market conditions.</P>
            <H3>Three Levels of ML</H3>
            <div className="grid grid-cols-1 gap-2 mt-2 mb-3">
              {[
                ["Level 1: Adaptive Parameters", "Automatically adjusts strategy parameters (like SMA length or RSI thresholds) based on recent market conditions. Easiest to use — no ML knowledge required."],
                ["Level 2: Signal Prediction", "Trains a classification model to predict whether the next bar will go up or down. Uses technical indicators as features. Medium complexity."],
                ["Level 3: Advanced ML", "Full-featured model training with custom feature engineering, multiple architectures (XGBoost, Neural Network, etc.), and ensemble methods. For advanced users."],
              ].map(([name, desc]) => (
                <div key={name as string} className="rounded-lg border border-card-border bg-card-bg p-3">
                  <div className="text-xs font-semibold text-foreground mb-1">{name}</div>
                  <div className="text-xs text-muted-foreground">{desc}</div>
                </div>
              ))}
            </div>
            <Tip>If you are new to ML, start with <strong>Level 1</strong>. It requires no configuration and can improve any existing strategy&apos;s parameters automatically.</Tip>
          </>
        ),
      },
      {
        id: "train-model",
        title: "Training a Model",
        content: (
          <>
            <H2>Training a Model</H2>
            <Step n={1}>Go to the <strong>ML Lab</strong> page.</Step>
            <Step n={2}>Select the <strong>ML Level</strong> tab (L1, L2, or L3).</Step>
            <Step n={3}>Choose the <strong>Strategy</strong> and <strong>Data Source</strong> to train on.</Step>
            <Step n={4}>For L2/L3: configure the <strong>feature set</strong> — which indicators and price data to feed the model.</Step>
            <Step n={5}>Set the <strong>train/test split</strong> (e.g. 80% training, 20% out-of-sample validation).</Step>
            <Step n={6}>Click <strong>Train Model</strong>. Training progress is shown in real time.</Step>
            <Step n={7}>Once trained, review the <strong>accuracy, precision, and recall</strong> metrics.</Step>
            <Note>ML models require more data to train than rule-based strategies. Plan on at least 2000+ candles (bars) for reliable results.</Note>
            <H3>Model Comparison</H3>
            <P>You can train multiple models and compare them side-by-side. The ML Lab tracks accuracy, profit factor, and other metrics for each model version.</P>
            <Warning>A high training accuracy but low validation accuracy means the model is overfitting. Try reducing the number of features or using more training data.</Warning>
          </>
        ),
      },
    ],
  },

  /* ================================================================
     SECTION 8 — LIVE & PAPER TRADING
     ================================================================ */
  {
    id: "trading",
    title: "Live & Paper Trading",
    icon: <TrendingUp className="h-4 w-4" />,
    topics: [
      {
        id: "trading-overview",
        title: "Trading Page Overview",
        content: (
          <>
            <H2>Trading Page Overview</H2>
            <P>The <strong>Trading</strong> page is your command centre for live market activity. It combines a real-time chart, order management, position tracking, and Algo Agent deployment in one view.</P>
            <H3>Key Sections</H3>
            <UL items={[
              "Chart — a full-featured candlestick chart powered by TradingView Lightweight Charts. Add indicators, change timeframes, and switch between data sources.",
              "Account Info — shows your broker balance, equity, margin, and P&L once connected.",
              "Positions — all currently open positions with real-time P&L.",
              "Orders — pending orders waiting to be filled.",
              "Trade History — recently closed trades with entry/exit details.",
              "Algo Agents — deploy, monitor, and manage automated trading bots.",
            ]} />
            <H3>Connecting to a Broker</H3>
            <P>Click the <strong>Connect Broker</strong> button on the Trading page. Select your broker, enter credentials if not already saved, and choose Practice or Live mode.</P>
            <Note>You can also save credentials once in <strong>Settings → Trading</strong> so you only need to click connect next time.</Note>
          </>
        ),
      },
      {
        id: "chart-indicators",
        title: "Chart & Indicators",
        content: (
          <>
            <H2>Chart &amp; Indicators</H2>
            <P>The trading chart supports multiple data sources and real-time streaming.</P>
            <H3>Changing the Symbol &amp; Timeframe</H3>
            <UL items={[
              "Symbol — type or select the instrument (e.g. XAUUSD, EURUSD, BTCUSD).",
              "Timeframe — select from M1, M5, M15, M30, H1, H4, D1.",
              "Data Source — choose between Broker data, CSV data, or Databento (if configured).",
            ]} />
            <H3>Adding Indicators</H3>
            <Step n={1}>Click the <strong>Indicators</strong> dropdown on the chart toolbar.</Step>
            <Step n={2}>Select from <strong>Overlays</strong> (drawn on the chart): SMA, EMA, Bollinger Bands, VWAP, Parabolic SAR, SuperTrend, Ichimoku, Keltner, Donchian.</Step>
            <Step n={3}>Or select from <strong>Oscillators</strong> (drawn below the chart): MACD, RSI, ATR, Stochastic, ADX, CCI, Williams %R, OBV, MFI.</Step>
            <Step n={4}>Configure the indicator parameters (period, etc.) in the dropdown. Changes apply immediately.</Step>
            <Tip>You can add multiple indicators at the same time. Each oscillator gets its own pane below the main chart. Remove indicators by clicking the X next to them.</Tip>
          </>
        ),
      },
      {
        id: "placing-orders",
        title: "Placing Orders",
        content: (
          <>
            <H2>Placing Orders</H2>
            <P>When connected to a broker, you can place orders directly from the Trading page.</P>
            <Step n={1}>Click <strong>New Order</strong> on the Trading page.</Step>
            <Step n={2}>Select the <strong>Symbol</strong> and <strong>Side</strong> (Buy or Sell).</Step>
            <Step n={3}>Enter the <strong>Size</strong> (units/lots).</Step>
            <Step n={4}>Choose <strong>Order Type</strong>: Market (fill immediately at current price) or Limit (fill at a specific price).</Step>
            <Step n={5}>Optionally set <strong>Stop-Loss</strong> and <strong>Take-Profit</strong> prices.</Step>
            <Step n={6}>Choose which broker to route the order to.</Step>
            <Step n={7}>Click <strong>Place Order</strong> to submit.</Step>
            <Warning>Market orders execute immediately at the best available price. In fast-moving markets, the fill price may differ from the displayed price (slippage).</Warning>
          </>
        ),
      },
      {
        id: "algo-agents",
        title: "Algo Agents",
        content: (
          <>
            <H2>Algo Agents</H2>
            <P>Algo Agents are automated bots that run your strategies in real time. They monitor the market, generate signals, and can execute trades automatically based on your rules.</P>
            <H3>Creating an Algo Agent</H3>
            <Step n={1}>On the <strong>Trading</strong> page, go to the <strong>Agents</strong> tab.</Step>
            <Step n={2}>Click <strong>New Agent</strong>.</Step>
            <Step n={3}>Select the <strong>Strategy</strong> to automate.</Step>
            <Step n={4}>Select the <strong>Symbol</strong> and <strong>Timeframe</strong>.</Step>
            <Step n={5}>Choose the <strong>Mode</strong> (see below).</Step>
            <Step n={6}>Configure risk settings: lot size, max daily loss, max positions.</Step>
            <Step n={7}>Click <strong>Start</strong>.</Step>

            <H3>Three Agent Modes</H3>
            <div className="grid grid-cols-1 gap-2 mt-2 mb-3">
              {[
                ["🛡️ Confirmation Mode", "The agent generates signals but waits for YOUR manual approval before placing any trade. You review each signal and click Approve or Reject. Safest mode — recommended when starting out."],
                ["📄 Paper Trade Mode", "The agent runs with simulated (fake) money. All trades are tracked but no real orders are sent to the broker. Use this to validate strategy performance in live market conditions risk-free."],
                ["⚡ Autonomous Mode", "The agent automatically executes trades without any manual intervention. Only use this after extensive paper trading and confirmation testing. Real money at risk."],
              ].map(([name, desc]) => (
                <div key={name as string} className="rounded-lg border border-card-border bg-card-bg p-3">
                  <div className="text-xs font-semibold text-foreground mb-1">{name}</div>
                  <div className="text-xs text-muted-foreground">{desc}</div>
                </div>
              ))}
            </div>
            <Tip>Follow this progression: <strong>Backtest → Paper Trade (2–4 weeks) → Confirmation Mode (2–4 weeks) → Autonomous Mode</strong>. Do not skip steps.</Tip>
            <H3>Monitoring Agents</H3>
            <UL items={[
              "Each agent shows its status (running, paused, stopped), current P&L, trade count, and last signal.",
              "Click an agent to view its detailed log of all signals and trades.",
              "You can pause, resume, or stop agents at any time.",
              "If an agent hits the daily loss limit, it automatically pauses until the next trading day.",
            ]} />
          </>
        ),
      },
    ],
  },

  /* ================================================================
     SECTION 9 — WATCHLIST
     ================================================================ */
  {
    id: "watchlist",
    title: "Watchlist & Alerts",
    icon: <Star className="h-4 w-4" />,
    topics: [
      {
        id: "watchlists",
        title: "Creating Watchlists",
        content: (
          <>
            <H2>Creating Watchlists</H2>
            <P>The <strong>Watchlist</strong> page lets you organise symbols into custom lists for quick reference.</P>
            <Step n={1}>Go to the <strong>Watchlist</strong> page.</Step>
            <Step n={2}>Click <strong>New Watchlist</strong>.</Step>
            <Step n={3}>Enter a name (e.g. &ldquo;Gold &amp; Silver&rdquo;, &ldquo;Crypto Pairs&rdquo;).</Step>
            <Step n={4}>Optionally add initial symbols as a comma-separated list (e.g. <Code>XAUUSD, XAGUSD</Code>).</Step>
            <Step n={5}>Click <strong>Create</strong>.</Step>
            <H3>Managing Symbols</H3>
            <UL items={[
              "Click the + button on a watchlist to add a new symbol.",
              "Click the × next to a symbol to remove it.",
              "Rename a watchlist by clicking the edit icon.",
              "Delete a watchlist with the trash icon.",
            ]} />
          </>
        ),
      },
      {
        id: "price-alerts",
        title: "Price Alerts",
        content: (
          <>
            <H2>Price Alerts</H2>
            <P>Set alerts to be notified when a symbol reaches a specific price level or moves by a certain percentage.</P>
            <Step n={1}>On the <strong>Watchlist</strong> page, click <strong>New Alert</strong>.</Step>
            <Step n={2}>Enter the <strong>Symbol</strong> (e.g. <Code>XAUUSD</Code>).</Step>
            <Step n={3}>Select the <strong>Condition</strong>:</Step>
            <UL items={[
              "Price Above — triggers when price rises above a level.",
              "Price Below — triggers when price drops below a level.",
              "% Change — triggers when price moves by a percentage.",
            ]} />
            <Step n={4}>Enter the <strong>Threshold</strong> value.</Step>
            <Step n={5}>Click <strong>Create Alert</strong>.</Step>
            <P>Active alerts appear in a list showing the symbol, condition, threshold, and whether they have been triggered. You can delete alerts that are no longer needed.</P>
            <Note>If you have Telegram notifications enabled in Settings, triggered alerts will also be sent to your Telegram.</Note>
          </>
        ),
      },
    ],
  },

  /* ================================================================
     SECTION 10 — NEWS & EVENTS
     ================================================================ */
  {
    id: "news",
    title: "News & Events",
    icon: <Newspaper className="h-4 w-4" />,
    topics: [
      {
        id: "economic-calendar",
        title: "Economic Calendar",
        content: (
          <>
            <H2>Economic Calendar</H2>
            <P>The economic calendar shows upcoming and past economic events that can move markets (e.g. Non-Farm Payrolls, CPI, interest rate decisions).</P>
            <H3>Features</H3>
            <UL items={[
              "Impact Filters — filter events by High, Medium, or Low impact.",
              "Country/Currency — see which country and currency each event affects.",
              "Actual vs Estimate — compare the actual release with the market estimate and previous value.",
              "Time Until — see how long until each upcoming event.",
            ]} />
            <Tip>High-impact events (marked in red) can cause sudden, large price moves. Consider pausing Algo Agents during these events or tightening stop-losses.</Tip>
          </>
        ),
      },
      {
        id: "news-feed",
        title: "News Feed & AI Analysis",
        content: (
          <>
            <H2>News Feed &amp; AI Analysis</H2>
            <P>The news feed aggregates financial headlines from multiple sources. Each article shows the headline, summary, source, time, and related symbols.</P>
            <H3>Sentiment Analysis</H3>
            <P>FlowrexAlgo automatically analyses the sentiment of news articles:</P>
            <UL items={[
              "Bullish (green) — positive sentiment likely to push prices up.",
              "Bearish (red) — negative sentiment likely to push prices down.",
              "Neutral (grey) — no strong directional bias.",
            ]} />
            <P>The Sentiment Panel shows aggregate bullish/bearish percentages for each symbol based on recent articles.</P>
            <H3>AI Trading Analysis</H3>
            <P>Click <strong>AI Analysis</strong> on any article to get an AI-powered breakdown including:</P>
            <UL items={[
              "Key Points — the most important facts from the article.",
              "Impact Assessment — how this news may affect markets.",
              "Affected Symbols — which instruments are likely impacted.",
              "Recommendation — a suggested trading stance (bullish/bearish/neutral) with confidence level.",
            ]} />
            <Note>AI analysis requires an LLM provider to be configured in <strong>Settings → AI Settings</strong>.</Note>
          </>
        ),
      },
    ],
  },

  /* ================================================================
     SECTION 11 — DASHBOARD
     ================================================================ */
  {
    id: "dashboard",
    title: "Dashboard & Portfolio",
    icon: <LayoutDashboard className="h-4 w-4" />,
    topics: [
      {
        id: "reading-dashboard",
        title: "Reading the Dashboard",
        content: (
          <>
            <H2>Reading the Dashboard</H2>
            <P>The Dashboard is the first page you see after logging in. It provides a real-time snapshot of your portfolio and active strategies.</P>
            <H3>Account Overview</H3>
            <P>The top section shows account information from your connected broker:</P>
            <UL items={[
              "Balance — your total account balance.",
              "Equity — current equity (balance + unrealised P&L).",
              "Margin — used margin and free margin available.",
              "Open P&L — unrealised profit/loss across all positions.",
            ]} />
            <H3>Stats Cards</H3>
            <UL items={[
              "Active Agents — how many Algo Agents are currently running.",
              "Total Strategies — total strategies in your library.",
              "Backtests Run — number of completed backtests.",
              "ML Models — number of trained ML models.",
            ]} />
            <H3>Tables</H3>
            <UL items={[
              "Open Positions — all currently held positions with symbol, side, size, entry price, and P&L.",
              "Recent Trades — the last few closed trades.",
              "Active Agents — summary of running agents with strategy name, symbol, and status.",
            ]} />
          </>
        ),
      },
    ],
  },

  /* ================================================================
     SECTION 12 — SETTINGS
     ================================================================ */
  {
    id: "settings",
    title: "Settings & Account",
    icon: <Settings className="h-4 w-4" />,
    topics: [
      {
        id: "profile-settings",
        title: "Profile & Security",
        content: (
          <>
            <H2>Profile &amp; Security</H2>
            <P>The <strong>Profile</strong> tab in Settings lets you manage your account.</P>
            <H3>Display Name &amp; Contact</H3>
            <UL items={[
              "Change your display name.",
              "Update your email address and phone number.",
              "Save contact info for notification delivery.",
            ]} />
            <H3>Password</H3>
            <Step n={1}>Enter your current password.</Step>
            <Step n={2}>Enter and confirm your new password.</Step>
            <Step n={3}>Click <strong>Update Password</strong>.</Step>
            <H3>Two-Factor Authentication (2FA)</H3>
            <P>Enable 2FA for extra security using an authenticator app (Google Authenticator, Authy, etc.):</P>
            <Step n={1}>Click <strong>Enable 2FA</strong>.</Step>
            <Step n={2}>Scan the QR code with your authenticator app.</Step>
            <Step n={3}>Enter the 6-digit code from the app to verify.</Step>
            <Note>Once enabled, you will need to enter a 2FA code every time you log in.</Note>
            <H3>Admin Tools</H3>
            <P>Admin users have additional tools for managing invitations, user access, and the platform seed data.</P>
          </>
        ),
      },
      {
        id: "appearance",
        title: "Appearance & Themes",
        content: (
          <>
            <H2>Appearance &amp; Themes</H2>
            <P>FlowrexAlgo ships with 8 built-in colour themes:</P>
            <div className="grid grid-cols-2 gap-2 mt-2 mb-3">
              {[
                ["Midnight Teal", "Default dark theme with cyan accents"],
                ["Ocean Blue", "Deep blue tones"],
                ["Emerald Trader", "Green finance feel"],
                ["Sunset Gold", "Warm amber tones"],
                ["Neon Purple", "Vibrant purple"],
                ["Classic Dark", "Neutral & minimal"],
                ["Warm Stone", "Earthy warm tones"],
                ["Arctic Light", "Cool & crisp"],
              ].map(([name, desc]) => (
                <div key={name as string} className="rounded-lg border border-card-border bg-card-bg p-2.5">
                  <div className="text-xs font-semibold text-foreground">{name}</div>
                  <div className="text-[11px] text-muted-foreground">{desc}</div>
                </div>
              ))}
            </div>
            <Step n={1}>Go to <strong>Settings → Appearance</strong>.</Step>
            <Step n={2}>Click a theme card to preview and apply it.</Step>
            <Step n={3}>Or customise individual colours: accent, background, card background, and border.</Step>
            <Step n={4}>Click <strong>Save Appearance</strong>.</Step>
            <Tip>You can also switch themes from the Command Palette (<strong>Ctrl + K</strong>).</Tip>
          </>
        ),
      },
      {
        id: "ai-settings",
        title: "AI Settings",
        content: (
          <>
            <H2>AI Settings</H2>
            <P>Configure which AI/LLM provider powers the platform&apos;s AI features (chat assistant, strategy import, news analysis).</P>
            <H3>Supported LLM Providers</H3>
            <UL items={[
              "Claude (Anthropic) — recommended for strategy analysis and code generation.",
              "OpenAI (GPT-4, GPT-3.5) — general-purpose AI with strong reasoning.",
              "Gemini (Google) — fast and capable alternative.",
            ]} />
            <Step n={1}>Go to <strong>Settings → AI Settings</strong>.</Step>
            <Step n={2}>Select your <strong>LLM Provider</strong> from the dropdown.</Step>
            <Step n={3}>Enter your <strong>API Key</strong> for the selected provider.</Step>
            <Step n={4}>Optionally select the specific <strong>Model</strong> (e.g. claude-3-5-sonnet, gpt-4).</Step>
            <Step n={5}>Set the <strong>Temperature</strong> (lower = more deterministic, higher = more creative).</Step>
            <Step n={6}>Click <strong>Save</strong>.</Step>
            <Note>The AI Chat Assistant (bottom-right corner on every page) uses this configuration. Without an LLM key, chat and AI import features will be unavailable.</Note>
          </>
        ),
      },
      {
        id: "trading-settings",
        title: "Trading & Broker Settings",
        content: (
          <>
            <H2>Trading &amp; Broker Settings</H2>
            <P>The <strong>Trading</strong> tab contains default parameters and broker credential management.</P>
            <H3>Default Trading Parameters</H3>
            <P>These defaults are pre-filled when creating new backtests or strategies:</P>
            <UL items={[
              "Default Symbol — the instrument to use by default (e.g. XAUUSD).",
              "Default Timeframe — the chart timeframe to default to (e.g. H1).",
              "Default Initial Balance — starting balance for backtests (e.g. $10,000).",
              "Default Lot Size — position size for new strategies.",
            ]} />
            <H3>Broker Credentials</H3>
            <P>Save your broker API keys here so you don&apos;t have to re-enter them every time you connect:</P>
            <Step n={1}>Select the broker from the dropdown (MT5, Oanda, Coinbase, Tradovate).</Step>
            <Step n={2}>Enter the required fields for that broker.</Step>
            <Step n={3}>Click <strong>Save Credentials</strong>.</Step>
            <P>Saved credentials are stored encrypted on the server. You can update or delete them at any time.</P>
          </>
        ),
      },
      {
        id: "notifications",
        title: "Notifications & Telegram",
        content: (
          <>
            <H2>Notifications &amp; Telegram</H2>
            <P>The <strong>Notifications</strong> tab lets you configure how you receive alerts about trading activity.</P>
            <H3>Email Notifications</H3>
            <P>Toggle email notifications on/off and set your preferred delivery frequency.</P>
            <H3>Telegram Notifications</H3>
            <P>Get instant push notifications on your phone via Telegram:</P>
            <Step n={1}>In Settings → Notifications, find the <strong>Telegram</strong> section.</Step>
            <Step n={2}>Enter your <strong>Telegram @username</strong> (e.g. @myusername).</Step>
            <Step n={3}>Click <strong>Link Telegram</strong>.</Step>
            <Step n={4}>Open Telegram and send <Code>/start</Code> to <strong>@FlowrexAgent_bot</strong>.</Step>
            <Step n={5}>The bot will confirm the link. You are now connected!</Step>
            <H3>Telegram Bot Commands</H3>
            <UL items={[
              "/start — link your account to Telegram.",
              "/status — check connection status.",
              "/disconnect — unlink your Telegram from FlowrexAlgo.",
              "/help — show available commands.",
            ]} />
            <H3>Event Notifications</H3>
            <P>Choose which events trigger notifications:</P>
            <UL items={[
              "Trade Opened / Trade Closed — when an order fills.",
              "Signal Generated — when a strategy produces a buy/sell signal.",
              "Agent Started / Stopped / Error — Algo Agent lifecycle events.",
              "Backtest Complete / Optimization Complete — background task completions.",
              "Alert Triggered / Price Alert — when a watchlist alert fires.",
            ]} />
          </>
        ),
      },
      {
        id: "webhooks",
        title: "Webhooks",
        content: (
          <>
            <H2>Webhooks</H2>
            <P>Webhooks let you receive HTTP POST notifications when events occur, useful for integrating FlowrexAlgo with external systems (Discord bots, logging services, custom dashboards, etc.).</P>
            <Step n={1}>In Settings → Notifications, scroll to <strong>Webhook Endpoints</strong>.</Step>
            <Step n={2}>Click <strong>Add Webhook</strong>.</Step>
            <Step n={3}>Enter a <strong>Name</strong> and <strong>URL</strong> (the endpoint that will receive POST requests).</Step>
            <Step n={4}>Optionally set a <strong>Secret</strong> for HMAC-SHA256 request signing.</Step>
            <Step n={5}>Select which <strong>Events</strong> to subscribe to (or leave empty for all events).</Step>
            <Step n={6}>Click <strong>Create</strong>.</Step>
            <H3>Testing &amp; Monitoring</H3>
            <UL items={[
              "Test — sends a test payload to verify your endpoint is reachable.",
              "Logs — view recent delivery attempts with status codes and response times.",
              "Status indicators: green (healthy), amber (some failures), red (failing).",
            ]} />
          </>
        ),
      },
      {
        id: "data-management",
        title: "Data Management",
        content: (
          <>
            <H2>Data Management</H2>
            <P>The <strong>Data Management</strong> tab shows storage usage and the Recycle Bin.</P>
            <H3>Storage</H3>
            <P>See how much disk space your data sources, backtests, and ML models are using.</P>
            <H3>Recycle Bin</H3>
            <P>Deleted items (strategies, data sources, backtests, agents, ML models, articles, conversations) go to the Recycle Bin instead of being permanently deleted. You can:</P>
            <UL items={[
              "Restore — bring a deleted item back.",
              "Permanent Delete — remove it forever (cannot be undone).",
              "Clear All — empty the entire recycle bin.",
            ]} />
            <Note>Items in the Recycle Bin still use storage space until permanently deleted.</Note>
          </>
        ),
      },
      {
        id: "platform",
        title: "Platform Settings",
        content: (
          <>
            <H2>Platform Settings</H2>
            <P>The <strong>Platform</strong> tab contains server-level configuration options:</P>
            <UL items={[
              "Market Data Provider — choose the default data provider (Oanda, Databento, etc.).",
              "Session Timeout — how long before idle sessions are logged out.",
              "Admin controls — manage platform-wide settings (admin users only).",
            ]} />
          </>
        ),
      },
    ],
  },

  /* ================================================================
     SECTION 13 — TROUBLESHOOTING & FAQ
     ================================================================ */
  {
    id: "faq",
    title: "Troubleshooting & FAQ",
    icon: <HelpCircle className="h-4 w-4" />,
    topics: [
      {
        id: "common-errors",
        title: "Common Errors",
        content: (
          <>
            <H2>Common Errors</H2>
            <H3>❌ &quot;Broker connection failed&quot;</H3>
            <P>Check that your API key and credentials are correct in <strong>Settings → Trading</strong>. For MT5, ensure the terminal application is running. For Oanda, verify you are using the correct environment (Practice vs Live).</P>

            <H3>❌ &quot;No data available&quot; / Backtest shows 0 trades</H3>
            <P>The selected data source may not have data for the period, or your entry conditions are too restrictive. Check:</P>
            <UL items={[
              "Go to the Data page and verify the date range of your dataset.",
              "Ensure your indicator conditions are not logically contradictory.",
              "Try loosening conditions (e.g. a wider RSI threshold).",
            ]} />

            <H3>❌ Chart not updating / showing stale data</H3>
            <P>Try refreshing the page. If using broker data, verify the broker is connected (green status). For MT5, ensure the terminal is open and logged in.</P>

            <H3>❌ Optimization too slow</H3>
            <UL items={[
              "Reduce the parameter ranges (smaller min/max, larger step size).",
              "Use Bayesian optimization instead of Grid search — it is much faster for large spaces.",
              "Use shorter data periods for the optimization run.",
            ]} />

            <H3>❌ ML model training failed</H3>
            <P>Common causes: insufficient data (need 2000+ bars), features that produce NaN values, or mismatch between training and prediction data. Check the error message in the ML Lab for specifics.</P>

            <H3>❌ Telegram bot not responding</H3>
            <P>Make sure you: (1) entered your @username correctly in Settings, (2) sent <Code>/start</Code> to <strong>@FlowrexAgent_bot</strong>, and (3) waited a few seconds for the link to register.</P>
          </>
        ),
      },
      {
        id: "faq",
        title: "Frequently Asked Questions",
        content: (
          <>
            <H2>Frequently Asked Questions</H2>

            <H3>Do I need coding knowledge?</H3>
            <P>No. The Strategy Builder, Optimization, and ML Lab are all no-code. However, advanced users can describe strategies in text and use AI Import to create them.</P>

            <H3>Can I use FlowrexAlgo without a broker?</H3>
            <P>Yes. You can build strategies, upload CSV data, run backtests, optimize parameters, and train ML models entirely offline without a broker connection. A broker is only required for live/paper trading.</P>

            <H3>What is the difference between paper trading and backtesting?</H3>
            <P>Backtesting runs on historical data all at once — it is a simulation. Paper trading runs in real time with live prices but simulated money — each signal is generated bar-by-bar as the market moves. Paper trading is more realistic because it captures timing effects and execution conditions that a backtest cannot replicate.</P>

            <H3>How many strategies can I run simultaneously?</H3>
            <P>There is no hard limit on the number of Algo Agents. However, running many agents increases broker API usage. Monitor your broker&apos;s rate limits if running more than a few agents.</P>

            <H3>Will my data be saved if I close the browser?</H3>
            <P>Yes. All strategies, backtests, data sources, ML models, and settings are saved to the server-side database. You can close the browser and return — everything will be there.</P>

            <H3>Can I trade crypto?</H3>
            <P>Yes, via Coinbase. Connect your Coinbase API key in Settings and you can fetch crypto data, backtest, and trade BTC, ETH, and other supported coins.</P>

            <H3>Can I trade futures?</H3>
            <P>Yes, via Tradovate. Connect your Tradovate account and trade instruments like ES, NQ, YM, GC, and more.</P>

            <H3>How often should I re-optimize my strategies?</H3>
            <P>Quarterly or when a strategy&apos;s live performance deviates significantly from backtest expectations. Markets change, and parameters that worked 6 months ago may need adjustment.</P>

            <H3>Is there a mobile app?</H3>
            <P>Currently, FlowrexAlgo is a web application. It works on tablets but complex pages like the Strategy Builder are best used on desktop. You can receive mobile alerts via the Telegram bot.</P>

            <H3>How do I reset my password?</H3>
            <Step n={1}>On the login screen, click <strong>Forgot Password</strong>.</Step>
            <Step n={2}>Enter your registered email address.</Step>
            <Step n={3}>Open the reset email and click the link.</Step>
            <Step n={4}>Enter and confirm your new password.</Step>
            <CheckCircle2 className="h-4 w-4 text-green-400 inline-block mr-1" />
            <span className="text-sm text-foreground/75">The reset link expires after 30 minutes.</span>
          </>
        ),
      },
    ],
  },
];

/* ─── Flatten all topics for search ────────────────── */
function flatTopics() {
  return GUIDE_SECTIONS.flatMap((s) =>
    s.topics.map((t) => ({ ...t, sectionId: s.id, sectionTitle: s.title }))
  );
}

/* ═══════════════════════════════════════════════════ */
export default function UserGuide() {
  const [activeSectionId, setActiveSectionId] = useState(GUIDE_SECTIONS[0].id);
  const [activeTopicId, setActiveTopicId] = useState(GUIDE_SECTIONS[0].topics[0].id);
  const [searchQuery, setSearchQuery] = useState("");

  const allTopics = useMemo(() => flatTopics(), []);

  const searchResults = useMemo(() => {
    if (!searchQuery.trim()) return null;
    const q = searchQuery.toLowerCase();
    return allTopics.filter(
      (t) =>
        t.title.toLowerCase().includes(q) ||
        t.sectionTitle.toLowerCase().includes(q)
    );
  }, [searchQuery, allTopics]);

  const activeSection = GUIDE_SECTIONS.find((s) => s.id === activeSectionId)!;
  const activeTopic = activeSection?.topics.find((t) => t.id === activeTopicId) ?? activeSection?.topics[0];

  const selectTopic = (sectionId: string, topicId: string) => {
    setActiveSectionId(sectionId);
    setActiveTopicId(topicId);
    setSearchQuery("");
  };

  return (
    <div className="flex gap-0 h-[calc(100vh-8rem)] overflow-hidden rounded-xl border border-card-border bg-card-bg">
      {/* ── Left Sidebar ── */}
      <div className="w-64 shrink-0 flex flex-col border-r border-card-border bg-background/30">
        {/* Search */}
        <div className="p-3 border-b border-card-border">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search guide…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full rounded-lg border border-card-border bg-background/60 pl-8 pr-3 py-1.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:border-accent/60 transition-colors"
            />
          </div>
        </div>

        {/* Nav */}
        <div className="flex-1 overflow-y-auto py-2">
          {searchResults ? (
            <div>
              <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Results ({searchResults.length})
              </div>
              {searchResults.length === 0 ? (
                <div className="px-3 py-4 text-xs text-muted-foreground text-center">No matches found</div>
              ) : (
                searchResults.map((t) => (
                  <button
                    key={`${t.sectionId}-${t.id}`}
                    onClick={() => selectTopic(t.sectionId, t.id)}
                    className="w-full text-left px-3 py-2 hover:bg-accent/10 transition-colors"
                  >
                    <div className="text-xs font-medium text-foreground/80">{t.title}</div>
                    <div className="text-[10px] text-muted-foreground">{t.sectionTitle}</div>
                  </button>
                ))
              )}
            </div>
          ) : (
            GUIDE_SECTIONS.map((section) => (
              <div key={section.id} className="mb-1">
                <button
                  onClick={() => selectTopic(section.id, section.topics[0].id)}
                  className={`w-full flex items-center gap-2 px-3 py-2 text-xs font-semibold transition-colors ${
                    activeSectionId === section.id
                      ? "text-accent"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <span className={activeSectionId === section.id ? "text-accent" : "text-muted-foreground"}>
                    {section.icon}
                  </span>
                  {section.title}
                </button>
                {activeSectionId === section.id &&
                  section.topics.map((topic) => (
                    <button
                      key={topic.id}
                      onClick={() => selectTopic(section.id, topic.id)}
                      className={`w-full flex items-center gap-1.5 pl-8 pr-3 py-1.5 text-xs transition-colors rounded ${
                        activeTopicId === topic.id
                          ? "bg-accent/10 text-accent"
                          : "text-muted-foreground hover:text-foreground hover:bg-accent/5"
                      }`}
                    >
                      <ChevronRight className={`h-3 w-3 shrink-0 transition-transform ${activeTopicId === topic.id ? "rotate-90" : ""}`} />
                      {topic.title}
                    </button>
                  ))}
              </div>
            ))
          )}
        </div>
      </div>

      {/* ── Content Area ── */}
      <div className="flex-1 overflow-y-auto p-6">
        {activeTopic?.content}
      </div>
    </div>
  );
}
