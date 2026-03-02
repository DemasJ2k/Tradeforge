"use client";

import { useState, useMemo } from "react";
import { Search, ChevronRight, BookOpen, Key, Database, BarChart2, SlidersHorizontal, Brain, TrendingUp, LayoutDashboard, Settings, HelpCircle, Lightbulb, AlertTriangle, Info, CheckCircle2 } from "lucide-react";

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
              "Paper Trading — trading with fake money in real-time to validate before going live.",
              "ML Agent — an AI model that can generate or refine trading signals.",
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
            <P>The main navigation lives in the collapsible sidebar on the left. You can expand or collapse it with the toggle button (<strong>Ctrl + B</strong>).</P>
            <H3>Pages at a Glance</H3>
            <UL items={[
              "Dashboard — overview of your portfolio, open positions, and recent activity.",
              "Data — fetch, upload, or connect live market data sources.",
              "Strategies — create and manage trading strategies.",
              "Backtest — run historical simulations of your strategies.",
              "Optimize — find the best parameter settings for a strategy.",
              "ML Lab — train and manage machine learning trading agents.",
              "Trading — paper trade or go live with a connected broker.",
              "Documents (you are here) — learning materials and this user guide.",
              "Settings — account, API keys, broker connections, and preferences.",
            ]} />
            <Tip>Press <strong>Ctrl + K</strong> at any time to open the Command Palette and jump to any page instantly.</Tip>
          </>
        ),
      },
    ],
  },
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
            <P>FlowrexAlgo supports multiple brokers for live and paper trading. You connect a broker via the <strong>Settings → Broker Connections</strong> section or directly from the <strong>Trading</strong> page.</P>
            <Step n={1}>Go to <strong>Settings</strong> in the left sidebar.</Step>
            <Step n={2}>Select the <strong>Broker Connections</strong> tab.</Step>
            <Step n={3}>Click <strong>Add Broker</strong> and choose your provider (e.g. Alpaca, Interactive Brokers).</Step>
            <Step n={4}>Enter your API Key and Secret (see below for where to find these).</Step>
            <Step n={5}>Click <strong>Save & Test Connection</strong>. A green checkmark confirms the connection.</Step>
            <Warning>Never share your API keys with anyone. FlowrexAlgo stores them encrypted, but you should still use keys with only the permissions you need (e.g. read + trade, not withdraw).</Warning>
          </>
        ),
      },
      {
        id: "api-keys",
        title: "Finding Your API Keys",
        content: (
          <>
            <H2>Finding Your API Keys</H2>
            <P>Every broker generates API keys from within their web portal. Here is where to find them for the most common brokers:</P>

            <H3>Alpaca Markets</H3>
            <Step n={1}>Log in to <strong>app.alpaca.markets</strong>.</Step>
            <Step n={2}>Click your name in the top-right corner → <strong>Your API Keys</strong>.</Step>
            <Step n={3}>Click <strong>Generate New Key</strong>. Copy both the <Code>API Key ID</Code> and the <Code>Secret Key</Code> — the secret is only shown once.</Step>
            <Note>Alpaca has two environments: <strong>Paper</strong> (fake money, for testing) and <strong>Live</strong> (real money). Make sure you use Paper keys first.</Note>

            <H3>Interactive Brokers (IBKR)</H3>
            <Step n={1}>Log in to <strong>Client Portal</strong> at <strong>clientportal.ibkr.com</strong>.</Step>
            <Step n={2}>Go to <strong>Settings → User Settings → API</strong>.</Step>
            <Step n={3}>Enable the API and generate a token.</Step>
            <Tip>IBKR requires the TWS (Trader Workstation) or IB Gateway desktop application to be running for API access.</Tip>

            <H3>General Tips</H3>
            <UL items={[
              "Create a separate API key for each application you use — easier to revoke if needed.",
              "Set IP restrictions on your key when possible.",
              "Rotate your keys every 90 days as a security best practice.",
            ]} />
            <Warning>If you accidentally expose a key (e.g. in a screenshot), revoke it immediately from your broker portal and generate a new one.</Warning>
          </>
        ),
      },
    ],
  },
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
            <P>The <strong>Data</strong> page is where you manage all the market data FlowrexAlgo uses for backtesting and live signal generation. Without data, strategies cannot be tested or run.</P>
            <H3>Types of Data Sources</H3>
            <UL items={[
              "CSV Upload — upload your own OHLCV (Open, High, Low, Close, Volume) files.",
              "Live Broker Feed — stream real-time or delayed data via a connected broker.",
              "Built-in Providers — fetch historical data from supported providers (e.g. Yahoo Finance, Polygon.io).",
            ]} />
          </>
        ),
      },
      {
        id: "fetch-data",
        title: "How to Fetch Data",
        content: (
          <>
            <H2>How to Fetch Data</H2>
            <Step n={1}>Navigate to the <strong>Data</strong> page from the sidebar.</Step>
            <Step n={2}>Click <strong>Add Data Source</strong>.</Step>
            <Step n={3}>Choose your source type: <em>CSV Upload</em>, <em>Broker Feed</em>, or <em>Provider</em>.</Step>
            <Step n={4}>For a Provider: enter the <strong>ticker symbol</strong> (e.g. <Code>AAPL</Code>, <Code>BTC/USD</Code>), select the <strong>timeframe</strong> (1m, 5m, 1h, 1d), and the <strong>date range</strong>.</Step>
            <Step n={5}>Click <strong>Fetch</strong>. The data will download and appear in your data library.</Step>
            <Note>Data is stored locally in the application database. Large date ranges (years of 1-minute data) can take a moment to download and may require significant storage.</Note>
            <Tip>For backtesting purposes, use daily or hourly bars to keep file sizes reasonable and backtests fast. Switch to minute bars only when you need intraday precision.</Tip>
            <H3>Supported Timeframes</H3>
            <UL items={["1m — 1 Minute", "5m — 5 Minutes", "15m — 15 Minutes", "1h — 1 Hour", "4h — 4 Hours", "1d — Daily", "1w — Weekly"]} />
            <H3>CSV Format Requirements</H3>
            <P>If uploading a CSV, it must contain at minimum these columns (case-insensitive):</P>
            <div className="rounded-lg bg-background/80 border border-card-border p-3 font-mono text-xs text-accent mb-3">
              date, open, high, low, close, volume
            </div>
            <Warning>Dates must be in ISO format (<Code>YYYY-MM-DD</Code> or <Code>YYYY-MM-DD HH:MM:SS</Code>). Rows with missing values will be dropped automatically.</Warning>
          </>
        ),
      },
    ],
  },
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
            <Step n={2}>Click <strong>New Strategy</strong>.</Step>
            <Step n={3}>Give your strategy a name and description.</Step>
            <Step n={4}>Select the <strong>data source</strong> (the ticker + timeframe to trade).</Step>
            <Step n={5}>Define your <strong>Entry Conditions</strong> — the rules that trigger a buy (long) or sell (short) signal.</Step>
            <Step n={6}>Define your <strong>Exit Conditions</strong> — the rules that close the position.</Step>
            <Step n={7}>Set <strong>Risk Management</strong> parameters: position size, stop-loss, take-profit.</Step>
            <Step n={8}>Click <strong>Save Strategy</strong>.</Step>
            <Tip>You can duplicate an existing strategy by clicking the three-dot menu on any strategy card. This is a great way to experiment with variations.</Tip>
          </>
        ),
      },
      {
        id: "conditions",
        title: "Conditions & Indicators",
        content: (
          <>
            <H2>Conditions & Indicators</H2>
            <P>Conditions are logical rules built from <strong>indicators</strong> (calculated values) compared with each other or with fixed thresholds.</P>
            <H3>Adding a Condition</H3>
            <Step n={1}>Inside a strategy, click <strong>+ Add Condition</strong> in either the Entry or Exit section.</Step>
            <Step n={2}>Choose the <strong>left-hand side</strong>: an indicator or price value (e.g. <Code>RSI(14)</Code>, <Code>Close</Code>).</Step>
            <Step n={3}>Choose the <strong>operator</strong>: <Code>&gt;</Code>, <Code>&lt;</Code>, <Code>crosses above</Code>, <Code>crosses below</Code>, <Code>==</Code>.</Step>
            <Step n={4}>Choose the <strong>right-hand side</strong>: another indicator, a fixed number, or a price level.</Step>
            <Step n={5}>Repeat to add multiple conditions. By default all conditions must be true (<strong>AND logic</strong>). Toggle to <strong>OR</strong> if any one condition should trigger the signal.</Step>

            <H3>Available Indicators</H3>
            <div className="grid grid-cols-2 gap-2 mt-2 mb-3">
              {[
                ["Trend", "SMA, EMA, WMA, DEMA, TEMA, HMA"],
                ["Momentum", "RSI, MACD, Stochastic, CCI, ROC"],
                ["Volatility", "Bollinger Bands, ATR, Keltner Channel"],
                ["Volume", "OBV, VWAP, MFI, CMF"],
                ["Support/Resistance", "Pivot Points, Donchian Channel"],
                ["Oscillators", "Williams %R, Ultimate Oscillator"],
              ].map(([cat, inds]) => (
                <div key={cat} className="rounded-lg border border-card-border bg-card-bg p-3">
                  <div className="text-xs font-semibold text-foreground mb-1">{cat}</div>
                  <div className="text-xs text-muted-foreground">{inds}</div>
                </div>
              ))}
            </div>
            <Note>Indicator parameters (e.g. period length) can be edited by clicking the indicator chip after adding it. These parameters can later be optimized automatically.</Note>
          </>
        ),
      },
      {
        id: "risk-management",
        title: "Risk Management",
        content: (
          <>
            <H2>Risk Management</H2>
            <P>Risk management controls how much capital is allocated per trade and how losses are limited.</P>
            <H3>Position Sizing</H3>
            <UL items={[
              "Fixed Quantity — always trade a set number of shares/contracts.",
              "Fixed Dollar Amount — always risk a fixed dollar value per trade.",
              "Percent of Equity — trade a percentage of your total account balance.",
              "Kelly Criterion — automatically size based on win rate and risk/reward.",
            ]} />
            <H3>Stop-Loss & Take-Profit</H3>
            <UL items={[
              "Fixed Price — exit at a specific price level.",
              "Percent-based — exit when the trade moves X% against (stop) or in your favour (target).",
              "ATR-based — stop-loss set as a multiple of Average True Range (adapts to volatility).",
              "Trailing Stop — stop-loss that follows the price as it moves in your favour.",
            ]} />
            <Warning>Always use a stop-loss. Strategies without defined exits can experience catastrophic drawdowns during unexpected market events.</Warning>
          </>
        ),
      },
    ],
  },
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
            <Step n={2}>Select the <strong>strategy</strong> to test from the dropdown.</Step>
            <Step n={3}>Select the <strong>data source</strong> (ticker + timeframe).</Step>
            <Step n={4}>Set the <strong>date range</strong> (start and end date).</Step>
            <Step n={5}>Set the <strong>initial capital</strong> (the starting account balance for the simulation).</Step>
            <Step n={6}>Choose the <strong>engine</strong>: V1 (standard) or V2 (recommended — see below).</Step>
            <Step n={7}>Click <strong>Run Backtest</strong>. Results appear when complete.</Step>
            <Note>Backtests with large datasets or complex conditions may take 10–30 seconds. The progress bar shows the current status.</Note>
          </>
        ),
      },
      {
        id: "v2-engine",
        title: "What is the V2 Engine?",
        content: (
          <>
            <H2>What is the V2 Engine?</H2>
            <P>The <strong>V2 Engine</strong> is the second-generation backtesting engine built into FlowrexAlgo. It is significantly more accurate and feature-rich than the original V1 engine.</P>
            <H3>Key Differences vs V1</H3>
            <div className="rounded-xl border border-card-border overflow-hidden mb-3">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-card-bg border-b border-card-border">
                    <th className="text-left px-3 py-2 text-muted-foreground">Feature</th>
                    <th className="text-left px-3 py-2 text-muted-foreground">V1</th>
                    <th className="text-left px-3 py-2 text-accent">V2</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    ["Slippage Modelling", "None", "✅ Realistic fill model"],
                    ["Commission", "Basic flat fee", "✅ Per-share + min/max"],
                    ["Order Types", "Market only", "✅ Market, Limit, Stop"],
                    ["Portfolio Mode", "Single asset", "✅ Multi-asset portfolio"],
                    ["Walk-Forward", "❌", "✅ Built-in"],
                    ["Speed", "Baseline", "✅ ~3× faster"],
                  ].map(([feat, v1, v2]) => (
                    <tr key={feat as string} className="border-b border-card-border/50 last:border-0">
                      <td className="px-3 py-2 text-foreground/80">{feat}</td>
                      <td className="px-3 py-2 text-muted-foreground">{v1}</td>
                      <td className="px-3 py-2 text-foreground">{v2}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Tip>Always use the V2 Engine for final evaluations. Use V1 only if you need to reproduce an older result.</Tip>
            <H3>Walk-Forward Testing (V2 Only)</H3>
            <P>Walk-forward testing splits your historical data into rolling in-sample (training) and out-of-sample (testing) windows. It is a much more realistic way to evaluate whether a strategy generalises beyond the data it was built on — helping avoid overfitting.</P>
          </>
        ),
      },
      {
        id: "reading-results",
        title: "Interpreting Backtest Results",
        content: (
          <>
            <H2>Interpreting Backtest Results</H2>
            <H3>Key Metrics Explained</H3>
            <UL items={[
              "Total Return % — the overall profit/loss as a percentage of initial capital.",
              "CAGR — Compound Annual Growth Rate; the annualised return.",
              "Max Drawdown — the largest peak-to-trough decline. Smaller is better.",
              "Sharpe Ratio — return per unit of risk (vs. risk-free rate). Above 1.0 is considered good, above 2.0 is excellent.",
              "Sortino Ratio — like Sharpe but only penalises downside volatility.",
              "Win Rate — percentage of trades that are profitable. Does not need to be above 50% if your winners are larger than your losers.",
              "Profit Factor — gross profit ÷ gross loss. Above 1.5 is healthy.",
              "Avg Win / Avg Loss — compare these: a low win rate can still be profitable if Avg Win >> Avg Loss.",
            ]} />
            <Warning>A strategy that looks perfect on backtests has likely been overfit. Always check out-of-sample performance or use walk-forward testing to validate.</Warning>
            <Tip>Use the <strong>Equity Curve</strong> chart to visually spot if a strategy stopped working at some point in history. A flat or declining curve in recent years is a red flag.</Tip>
          </>
        ),
      },
    ],
  },
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
            <P>Optimization automatically runs your strategy <em>hundreds or thousands of times</em> with different parameter values, then ranks all combinations by a performance metric (e.g. Sharpe Ratio) to find the best settings.</P>
            <P>For example: if your RSI strategy uses a period of 14 and an overbought threshold of 70, optimization might test every combination of periods from 5–30 and thresholds from 60–80 to find the combination that historically performed best.</P>
            <Warning>Optimization is a powerful tool but can lead to <strong>overfitting</strong> — where parameters are tuned so precisely to past data that they fail in the future. Always validate optimized parameters on out-of-sample data.</Warning>
            <H3>Optimization Methods</H3>
            <UL items={[
              "Grid Search — test every possible combination. Thorough but slow for large parameter spaces.",
              "Random Search — randomly sample combinations. Faster, good for large spaces.",
              "Bayesian Optimization — intelligently focuses on promising areas. Best balance of speed and thoroughness.",
              "Walk-Forward Optimization — optimizes on rolling windows, then validates on the next window. Most robust method.",
            ]} />
          </>
        ),
      },
      {
        id: "run-optimization",
        title: "How to Run Optimization",
        content: (
          <>
            <H2>How to Run Optimization</H2>
            <Step n={1}>Go to the <strong>Optimize</strong> page.</Step>
            <Step n={2}>Select the <strong>strategy</strong> to optimize.</Step>
            <Step n={3}>Select the <strong>data source</strong>.</Step>
            <Step n={4}>Click <strong>Define Parameters</strong>. For each indicator parameter you want to optimize, set a <em>min value</em>, <em>max value</em>, and <em>step size</em>.</Step>
            <Step n={5}>Choose the <strong>optimization method</strong> (Grid, Random, Bayesian, or Walk-Forward).</Step>
            <Step n={6}>Choose the <strong>objective metric</strong> — what you want to maximize (e.g. Sharpe Ratio, Total Return, Profit Factor).</Step>
            <Step n={7}>Set any <strong>constraints</strong> (e.g. minimum trade count, maximum drawdown limit).</Step>
            <Step n={8}>Click <strong>Start Optimization</strong>. Progress is shown in real time.</Step>
            <Step n={9}>When complete, review the <strong>Results Table</strong> and <strong>Heatmap</strong>, then click <strong>Apply Best Parameters</strong> to update your strategy.</Step>
            <Tip>Start with a coarse grid (large step sizes) to get a general picture, then narrow down with a finer grid around the best region. This is faster than a fine grid over the full range.</Tip>
            <Note>Optimization can take from seconds to many minutes depending on the parameter space size, data length, and your hardware. Complex strategies with many parameters may take longer.</Note>
          </>
        ),
      },
    ],
  },
  {
    id: "trading",
    title: "Live & Paper Trading",
    icon: <TrendingUp className="h-4 w-4" />,
    topics: [
      {
        id: "paper-trading",
        title: "Paper Trading Mode",
        content: (
          <>
            <H2>Paper Trading Mode</H2>
            <P>Paper trading simulates live trading using real-time market data but with <strong>no real money</strong>. It is the best way to validate a strategy in live market conditions before going live.</P>
            <Step n={1}>Go to the <strong>Trading</strong> page.</Step>
            <Step n={2}>Ensure you have a broker connected (even a paper account).</Step>
            <Step n={3}>Toggle the mode to <Badge color="bg-amber-500/20 text-amber-400">Paper</Badge>.</Step>
            <Step n={4}>Select the strategy to run.</Step>
            <Step n={5}>Click <strong>Start Paper Trading</strong>.</Step>
            <Tip>Run paper trading for at least 2–4 weeks before going live. This gives you a meaningful sample of real-market trades, including slippage and partial fills.</Tip>
            <Note>Paper trading results differ from backtesting because prices are real and orders are simulated in sequence — making it a much more accurate performance indicator than a backtest.</Note>
          </>
        ),
      },
      {
        id: "live-trading",
        title: "Going Live",
        content: (
          <>
            <H2>Going Live</H2>
            <Warning>Live trading uses real money. Only proceed if you understand the risks and have thoroughly tested your strategy in paper mode.</Warning>
            <Step n={1}>Make sure your live broker account is connected in <strong>Settings → Broker Connections</strong> (not a paper account).</Step>
            <Step n={2}>On the <strong>Trading</strong> page, select your broker and switch the mode to <Badge color="bg-green-500/20 text-green-400">Live</Badge>.</Step>
            <Step n={3}>Confirm the risk settings (max daily loss limit, position size limits).</Step>
            <Step n={4}>Select the strategy and click <strong>Start Live Trading</strong>.</Step>
            <H3>Monitoring Live Trades</H3>
            <UL items={[
              "Open Positions panel — all currently held positions with P&L.",
              "Order Log — every order sent to the broker with fill status.",
              "Daily P&L chart — running performance since session start.",
              "Risk Alerts — automatic alerts if daily loss limits are approached.",
            ]} />
            <Tip>Enable <strong>email/push notifications</strong> in Settings so you are alerted when trades are opened, closed, or if something goes wrong.</Tip>
          </>
        ),
      },
      {
        id: "managing-positions",
        title: "Managing Positions",
        content: (
          <>
            <H2>Managing Positions</H2>
            <P>The <strong>Trading</strong> page gives you full visibility and control over all active positions.</P>
            <H3>Manual Override</H3>
            <P>You can manually close any position at any time by clicking the <strong>Close</strong> button next to a position. This sends a market order to the broker immediately.</P>
            <Warning>Manually closing a position does not pause the strategy. If the strategy&apos;s entry conditions are met again, it will re-enter the trade. Pause or stop the strategy first if you want to stop trading.</Warning>
            <H3>Emergency Stop</H3>
            <P>The red <strong>Emergency Stop</strong> button halts the strategy immediately and closes all open positions with market orders. Use this only when you need to exit all trades instantly.</P>
          </>
        ),
      },
    ],
  },
  {
    id: "ml",
    title: "ML Lab & AI Agents",
    icon: <Brain className="h-4 w-4" />,
    topics: [
      {
        id: "what-are-agents",
        title: "What are ML Agents?",
        content: (
          <>
            <H2>What are ML Agents?</H2>
            <P>ML Agents are machine learning models trained to generate trading signals. Unlike rule-based strategies, ML agents <em>learn patterns from data</em> and can adapt to market regimes that fixed indicators might miss.</P>
            <H3>Agent Types</H3>
            <UL items={[
              "Signal Classifier — predicts whether the next bar will go up or down.",
              "Regime Detector — identifies whether the market is trending, ranging, or volatile.",
              "Reinforcement Learning Agent — learns a trading policy by maximizing a reward function over many simulated episodes.",
              "Ensemble Agent — combines multiple models for more robust predictions.",
            ]} />
            <Note>ML agents require more data to train than rule-based strategies. Plan on at least 2–3 years of daily data, or 6+ months of hourly data, for reliable results.</Note>
          </>
        ),
      },
      {
        id: "setup-agents",
        title: "Setting Up & Training Agents",
        content: (
          <>
            <H2>Setting Up & Training an ML Agent</H2>
            <Step n={1}>Go to the <strong>ML Lab</strong> page.</Step>
            <Step n={2}>Click <strong>New Agent</strong>.</Step>
            <Step n={3}>Choose the <strong>agent type</strong> (Classifier, Regime Detector, etc.).</Step>
            <Step n={4}>Select the <strong>data source</strong> for training.</Step>
            <Step n={5}>Configure the <strong>feature set</strong> — which indicators and price data to feed the model.</Step>
            <Step n={6}>Set the <strong>train/test split</strong> (e.g. 80% training, 20% out-of-sample validation).</Step>
            <Step n={7}>Click <strong>Train Agent</strong>. Training progress is shown with a loss curve.</Step>
            <Step n={8}>Once trained, review the <strong>precision, recall, and accuracy</strong> on the validation set.</Step>
            <Step n={9}>If satisfied, click <strong>Deploy Agent</strong> to make it available as a signal source in Strategy Builder.</Step>
            <Tip>Retrain your agents regularly — at least monthly for live strategies — to keep them adapted to current market conditions.</Tip>
            <Warning>A high training accuracy but low validation accuracy means the model is overfitting. Try reducing the number of features or using a simpler model architecture.</Warning>
          </>
        ),
      },
    ],
  },
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
            <H3>Dashboard Cards</H3>
            <UL items={[
              "Total Portfolio Value — the current market value of all open positions plus cash.",
              "Today's P&L — unrealised and realised profit/loss for the current trading day.",
              "Active Strategies — how many strategies are currently running (live or paper).",
              "Open Positions — count and summary of all currently held positions.",
              "Recent Signals — the latest buy/sell signals generated by your strategies.",
              "Performance Chart — equity curve showing portfolio growth over time.",
            ]} />
            <Tip>Click on any card to drill down into more detail. For example, clicking <strong>Open Positions</strong> takes you directly to the Trading page filtered to your open trades.</Tip>
          </>
        ),
      },
      {
        id: "portfolio-metrics",
        title: "Portfolio Metrics",
        content: (
          <>
            <H2>Portfolio Metrics</H2>
            <P>The Portfolio section of the Dashboard shows aggregate statistics across all your strategies.</P>
            <H3>Metrics Explained</H3>
            <UL items={[
              "Gross Exposure — total market value of all open positions (long + short).",
              "Net Exposure — long positions minus short positions. A measure of directional bias.",
              "Beta — how much your portfolio moves relative to a benchmark (e.g. S&P 500).",
              "Alpha — excess return above the benchmark, attributed to your strategy.",
              "Correlation — how correlated your strategies are with each other and with the market.",
            ]} />
            <Note>Low correlation between your strategies is desirable — it means they do not all lose money at the same time, reducing overall drawdown.</Note>
          </>
        ),
      },
    ],
  },
  {
    id: "settings",
    title: "Settings & Account",
    icon: <Settings className="h-4 w-4" />,
    topics: [
      {
        id: "profile-settings",
        title: "Profile & Account Settings",
        content: (
          <>
            <H2>Profile & Account Settings</H2>
            <Step n={1}>Click <strong>Settings</strong> in the left sidebar.</Step>
            <Step n={2}>The <strong>Profile</strong> tab lets you update your display name, email address, and password.</Step>
            <Step n={3}>To change your password: enter your current password, then your new password twice, and click <strong>Update Password</strong>.</Step>
            <Note>Email changes require re-verification. A confirmation link will be sent to the new address.</Note>
            <H3>Notification Settings</H3>
            <UL items={[
              "Trade Executed — notified whenever a buy or sell order is filled.",
              "Strategy Stopped — if a strategy halts due to an error or daily loss limit.",
              "Daily Summary — end-of-day report of performance.",
              "Risk Alert — if a position approaches its stop-loss level.",
            ]} />
          </>
        ),
      },
      {
        id: "theme-settings",
        title: "Appearance & Theme",
        content: (
          <>
            <H2>Appearance & Theme</H2>
            <P>FlowrexAlgo ships with 8 built-in colour themes. You can switch them at any time:</P>
            <Step n={1}>Go to <strong>Settings → Appearance</strong>.</Step>
            <Step n={2}>Choose a preset theme from the palette (Midnight Teal, Ocean Blue, Emerald Trader, etc.).</Step>
            <Step n={3}>Or use <strong>Custom Theme</strong> to pick exact accent, background, and text colours.</Step>
            <Tip>You can also switch themes instantly using <strong>Ctrl + K</strong> → type a theme name in the Command Palette.</Tip>
          </>
        ),
      },
    ],
  },
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
            <H3>❌ &quot;No data available for this date range&quot;</H3>
            <P>The selected data source does not have data for the requested dates. Go to the <strong>Data</strong> page and verify the date range of your dataset, or fetch a new one with the correct range.</P>

            <H3>❌ &quot;Broker connection failed&quot;</H3>
            <P>Check that your API key and secret are correct and have not expired. Also ensure your broker account is active and that you are using Paper vs Live keys correctly.</P>
            <Step n={1}>Go to Settings → Broker Connections.</Step>
            <Step n={2}>Click the edit icon next to your broker.</Step>
            <Step n={3}>Re-enter your API keys and click <strong>Test Connection</strong>.</Step>

            <H3>❌ &quot;Strategy produced 0 trades&quot;</H3>
            <P>This usually means your conditions are too restrictive. Check that:</P>
            <UL items={[
              "Your indicator conditions are not logically contradictory.",
              "The data covers a period where the conditions could have been met.",
              "Your entry and exit conditions are not identical (they would cancel each other).",
            ]} />

            <H3>❌ &quot;Optimization returned only 1 result&quot;</H3>
            <P>This happens when the parameter ranges are set to a single value (min = max). Ensure your min and max values are different, and that the step size divides the range into more than one point.</P>

            <H3>❌ &quot;ML model training failed&quot;</H3>
            <P>Most common causes: insufficient data (need at least a few hundred rows after feature engineering), a feature that produces all NaN values, or a mismatch between training and prediction data schemas. Check the error log for the specific message.</P>
          </>
        ),
      },
      {
        id: "faq",
        title: "Frequently Asked Questions",
        content: (
          <>
            <H2>Frequently Asked Questions</H2>

            <H3>Can I use FlowrexAlgo without a broker?</H3>
            <P>Yes. You can build strategies, run full backtests, and use the ML Lab entirely offline without a broker connection. A broker is only required for live and paper trading.</P>

            <H3>What is the difference between paper trading and backtesting?</H3>
            <P>Backtesting runs on historical data all at once. Paper trading runs in real time with live prices — each signal is generated bar-by-bar as the market moves. Paper trading is more realistic because it captures slippage, partial fills, and timing effects that a backtest cannot fully replicate.</P>

            <H3>How many strategies can I run simultaneously?</H3>
            <P>There is no hard limit. However, running many strategies in live mode increases broker API usage. Monitor your broker&apos;s API rate limits in the Trading page&apos;s status panel.</P>

            <H3>Do I need coding knowledge?</H3>
            <P>No. The Strategy Builder, Optimization, and ML Lab are all no-code. However, advanced users can inject custom Python logic via the code editor available in the Strategy Builder&apos;s <strong>Advanced</strong> tab.</P>

            <H3>Will my strategies and data be saved if I close the browser?</H3>
            <P>Yes. All strategies, backtests, data sources, and settings are saved to the server-side database. You can close the browser and return at any time — everything will be there.</P>

            <H3>Is there a mobile app?</H3>
            <P>Currently, FlowrexAlgo is a web application optimised for desktop. The interface is responsive and usable on tablets, but complex pages like the Strategy Builder work best on larger screens.</P>

            <H3>How do I reset my password?</H3>
            <Step n={1}>On the login screen, click <strong>Forgot Password</strong>.</Step>
            <Step n={2}>Enter your registered email address.</Step>
            <Step n={3}>Open the reset email and click the link.</Step>
            <Step n={4}>Enter and confirm your new password.</Step>
            <CheckCircle2 className="h-4 w-4 text-green-400 inline-block mr-1" />
            <span className="text-sm text-foreground/75">The link expires after 30 minutes.</span>
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
