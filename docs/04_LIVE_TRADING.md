# Live Trading Guide

Deploy strategies as autonomous Algo Agents to automatically execute trades based on your rules.

## Table of Contents

1. [Overview](#overview)
2. [Creating an Algo Agent](#creating-an-algo-agent)
3. [Trading Modes](#trading-modes)
4. [Risk Management](#risk-management)
5. [Monitoring](#monitoring)
6. [Best Practices](#best-practices)

---

## Overview

An **Algo Agent** is an automated trading bot that:
- Monitors price feed for your symbol/timeframe
- Evaluates strategy entry/exit rules every new candle
- Places, modifies, and closes trades automatically
- Tracks performance and logs all actions

### Before You Deploy Live

⚠️ **Critical Checklist**:
1. ☑️ Backtest strategy (2+ years of data)
2. ☑️ Paper-trade for 2-4 weeks
3. ☑️ Results match expectations
4. ☑️ Understand max loss tolerance
5. ☑️ Review risk settings
6. ☑️ Have kill-switch plan (how to stop quickly)

---

## Creating an Algo Agent

### Step 1: Go to Algo Agents

1. Go to **Trading** page
2. Scroll to **Algo Agents** section
3. Click **+ New Agent**

### Step 2: Select Strategy & Instrument

| Setting | Example | Notes |
|---------|---------|-------|
| **Strategy** | SMA Golden Cross | Must be tested and approved |
| **Symbol** | XAUUSD | Must be available on broker |
| **Timeframe** | H1 | Smallest is M1, largest is D1 |
| **Broker** | MT5 | Must be connected |

### Step 3: Choose Trading Mode

TradeForge offers 3 modes:

#### Mode 1: Confirmation Mode ⚙️ (Recommended for beginners)

- Bot **identifies signals** but **pauses for approval**
- You see signal details: direction, entry price, SL, TP
- **You click "Approve"** to execute
- **You click "Reject"** to skip the trade

**Best for**: Learning, high-risk trades, manual oversight

**Example workflow**:
```
14:30 Signal Generated:
  Direction: BUY
  Entry: 2050.50
  Stop: 2048.00 (-50 pips)
  Target: 2055.50 (+100 pips)
  
You: [✓ Approve] [✗ Reject]
→ You approve, order placed
```

#### Mode 2: Paper Trade Mode 📋 (Recommended for testing)

- Bot executes trades **simulated** (not real money)
- Tracks P&L as if trades were real
- Useful for 1-2 weeks of testing before going live
- Zero risk (no real money spent)

**Best for**: Verifying strategy works, testing risk settings, building confidence

**Results**:
```
Paper Trade Results (not real):
Total Trades: 45
Profit: $1,250 (simulated)
Win Rate: 62%
Status: ✅ Ready to go live?
```

#### Mode 3: Autonomous Mode 🚀 (Advanced, use with caution)

- Bot executes trades **automatically** without waiting
- Fastest execution (no human delay)
- **High risk** if strategy or risk settings are wrong
- Only use after 4+ weeks of paper trading

**Best for**: Experienced traders with proven strategies

---

## Risk Management

### Setting Risk Parameters

When creating an agent, configure:

| Setting | Description | Example | Impact |
|---------|-------------|---------|--------|
| **Lot Size** | Contracts per trade | 0.1 lots | Smaller = lower risk |
| **Risk %** | Max loss per trade | 2% of balance | Automatic position sizing |
| **Max Positions** | Simultaneous trades | 3 | Limits exposure |
| **Max Daily Loss** | Stop trading after loss | 5% | Circuit breaker |
| **Max Drawdown %** | Stop after decline | 10% | Equity protection |
| **Max Exposure** | Total active lots | 1.0 | Prevents over-leverage |

### Example Risk Config

```
Account: $10,000
Strategy: SMA Crossover on XAUUSD

Risk Settings:
├─ Lot Size: Fixed 0.1 lots per trade
├─ Max Positions: 3 (never >3 open trades)
├─ Max Daily Loss: 5% ($500 loss → stop trading)
├─ Max Drawdown: 10% ($1,000 drop from peak → stop)
└─ Max Exposure: 1.0 lots total (max 10 open)

Trade 1: BUY 0.1 lot → Risk: 0.1 × 50 pips = $50
Trade 2: BUY 0.1 lot → Risk: 0.1 × 50 pips = $50
Trade 3: BUY 0.1 lot → Risk: 0.1 × 50 pips = $50
├─ Total: 3 trades, 0.3 lots, $150 max daily risk ✅

Trade 4: Rejected (max positions = 3) ❌
```

### Kill Switches

**Emergency Stop Button**: If something goes wrong:
1. Go to **Trading** → **Algo Agents**
2. Click **Stop** on the agent card (red button)
3. No new trades will be placed
4. Existing trades stay open (manually close if needed)

**Daily Limit**: Agent auto-stops if daily loss > 5%
- Prevents cascading losses
- Automatically resets next day

**Drawdown Limit**: Agent auto-stops if equity drops 10% from peak
- Long-term capital protection

---

## Monitoring

### Live Agent Dashboard

Each agent shows:
- **Status**: Running / Paused / Stopped
- **Symbol**: Current instrument
- **Timeframe**: Chart period
- **Mode**: Confirmation / Paper / Autonomous
- **Live P&L**: Current profit/loss
- **Trades**: Open positions count
- **Last Signal**: Time of last entry

### Trade Confirmations

When agent generates signal in **Confirmation Mode**:

```
⏰ 14:30:00 Signal Generated

📊 Entry Details:
   Direction: BUY
   Symbol: XAUUSD
   Entry Price: 2050.50
   Stop Loss: 2048.00 (-50 pips)
   Take Profit: 2055.50 (+100 pips)
   Risk/Reward: 1:2
   
💰 Position Size:
   Lot Size: 0.1
   Max Risk: $50
   Max Profit: $100

[✓ APPROVE] [✗ REJECT]
```

**Actions**:
- **Approve**: Execute trade immediately
- **Reject**: Skip this signal, wait for next one
- **Pause Agent**: Stop generating signals temporarily

### Live Log Feed

The agent log shows every action:

```
15:45:00 Bar closed at 2051.25
15:45:01 Entry signal detected: SMA(20) > SMA(50)
15:45:02 Risk manager approved (within daily loss limits)
15:45:03 Confirmation pending...
15:45:15 User approved signal
15:45:16 Order placed: BUY 0.1 XAUUSD @ 2050.50
15:45:20 Order filled @ 2050.62 (+0.12 slippage)
16:10:00 Exit signal: SMA(20) < SMA(50)
16:10:01 Exit order placed @ 2051.50
16:10:05 Position closed, P&L: +$44 ✅
```

### Performance Stats

During a trading day, agent tracks:

- **Trades Placed**: 5
- **Trades Closed**: 3
- **Trades Open**: 2
- **Daily P&L**: +$125 ✅
- **Daily Loss**: $50 (under 5% limit)
- **Largest Win**: +$120
- **Largest Loss**: -$65
- **Win Rate**: 60% (3 wins, 2 pending)

---

## Best Practices

### Practice 1: Start with Paper Trading

1. Deploy agent in **Paper Mode**
2. Run for 1-4 weeks
3. Monitor results daily
4. If results meet expectations, proceed to confirmation mode
5. After 2-4 weeks of confirmation mode, consider autonomous

**Timeline**:
```
Week 1-4:   Paper Trade Mode
Week 5-8:   Confirmation Mode
Week 9+:    Autonomous Mode (if confident)
```

### Practice 2: Use Confirmation Mode for First Real Trades

**Confirmation Mode** gives you:
- Last chance to review each signal
- Learning opportunity (understand why bot trades)
- Easy pause if something feels wrong

**Example week 1 live**:
- 5 confirmations per day
- You approve 90% (reject 1-2 weekly)
- Gradually gain confidence

### Practice 3: Set Conservative Risk at First

- **Start**: 1% risk per trade
- **After 4 weeks**: 1.5%
- **After 8 weeks**: 2%
- **Max**: 3% risk per trade (exceeds this, reconsider)

### Practice 4: Monitor Daily

**Morning routine** (before market opens):
1. Check agent status ✅
2. Review overnight logs ✅
3. Set max daily loss limit ✅

**Evening routine** (after market closes):
1. View day's P&L
2. Review trade quality
3. Any signals rejected? Why?
4. Adjust risk if needed

### Practice 5: Have a Backup Plan

**If agent fails**:
1. Can you manually close positions quickly?
2. Do you have time zone coverage?
3. Is there a colleague/partner to monitor?

**Failsafe setup**:
- Phone alert when trade placed
- 15-minute review check-in
- Kill switch password (prevents accidental stop)

### Practice 6: Review Weekly

Every Friday, review:

| Item | Action |
|------|--------|
| **Win Rate** | > 50%? ✅ |
| **Profit Factor** | > 1.2? ✅ |
| **Drawdown** | < Max limit? ✅ |
| **Surprises** | Any unexpected losses? |
| **Market Changes** | Did market regime change? |
| **Risk Config** | Still appropriate? |

---

## Troubleshooting

### "Agent places trades but they instantly fail"

- **Cause**: Insufficient margin or balance
- **Fix**: Increase account balance or reduce lot size

### "Confirmation signals never arrive"

- **Cause**: Entry rules not matching price data
- **Fix**: Review entry rule conditions in strategy editor
- **Debug**: Manually check if SMA(20) > SMA(50) right now

### "Live results differ from backtest"

- **Cause**: Real slippage, commissions, market gaps
- **Fix**: Add more slippage/commission to backtest settings
- **Normal**: Expect ±10-15% variance from backtest

### "Agent stops unexpectedly"

- **Cause**: Daily loss limit or drawdown limit reached
- **Fix**: Check agent logs for "Circuit breaker activated"
- **Action**: Increase limits or review risk settings

---

## Example: SMA Crossover Live Trading

### Setup

```
Strategy: SMA(20) vs SMA(50) Crossover
Symbol: XAUUSD
Timeframe: H1
Mode: Confirmation (first week)
Risk: 2% per trade, max 3 positions, daily limit 5%
```

### Day 1: Monday

```
09:00 - Agent started ✅
09:15 - Entry signal: SMA(20) crossed above SMA(50)
        Confirmation waiting...
09:20 - You approve → BUY 0.1 XAUUSD @ 2050.50
09:45 - Trade open +45 pips ✅
10:30 - Exit signal: SMA(20) crossed below SMA(50)
        → SELL 0.1 XAUUSD @ 2051.80
        P&L: +$65 ✅

12:00 - Entry signal: SMA(20) > SMA(50) again
        You reject (already had 1 win, cautious)
        → Signal skipped
```

### Day 1 Result

```
Trades Placed: 1 ✅
Trades Closed: 1 ✅
Daily P&L: +$65
Confidence: 📈 Growing
```

---

## Next Steps

- **[Optimization](./04_OPTIMIZATION.md)**: Find best parameters before deploying
- **[ML Lab](./06_ML_LAB.md)**: Add ML signals for better entries
- **[Knowledge Base](./08_KNOWLEDGE_BASE.md)**: Trading psychology and risk management

---

**Trade with Discipline! 🎯**
