# Optimization Guide

Find the best parameters for your strategy using Bayesian and Genetic algorithms.

## Table of Contents

1. [What is Optimization?](#what-is-optimization)
2. [Running an Optimization](#running-an-optimization)
3. [Understanding Results](#understanding-results)
4. [Algorithms Explained](#algorithms-explained)
5. [Best Practices](#best-practices)

---

## What is Optimization?

Optimization automatically tests many parameter combinations to find the best ones.

### Example

**Strategy**: SMA(L1) crossover SMA(L2)

**Manual Testing**:
```
Test 1: L1=10, L2=30 → +5% profit
Test 2: L1=10, L2=50 → +8% profit
Test 3: L1=20, L2=50 → +12% profit
... (100 combinations to test = 100 backtests)
```

**Optimization**:
```
Automatically test 100+ combinations
Find: L1=19, L2=51 → +14% profit ✅
Time: Minutes instead of hours
```

---

## Running an Optimization

### Step 1: Open Optimizer

1. Go to **Optimize** page
2. Click **New Optimization**

### Step 2: Configure

| Setting | Description | Example |
|---------|-------------|---------|
| **Strategy** | Which strategy to optimize | SMA Crossover |
| **Symbol** | Trading instrument | XAUUSD |
| **Timeframe** | Chart period | H1 |
| **Data Range** | Backtest period | 2022-2024 |
| **Objective** | What to maximize | Net Profit, Sharpe Ratio, Profit Factor |
| **Algorithm** | Bayesian (fast) or Genetic (thorough) | Bayesian |

### Step 3: Define Parameter Ranges

For each parameter, specify min/max values:

```
Parameter: SMA Length 1
├─ Min: 5
├─ Max: 50
└─ Step: 1 (test 5, 6, 7, ..., 50)

Parameter: SMA Length 2
├─ Min: 20
├─ Max: 200
└─ Step: 5 (test 20, 25, 30, ..., 200)

Total combinations: 46 × 37 = 1,702 ❌ (too many)
```

**Simplified**:
```
Parameter: SMA Length 1
├─ Min: 5
├─ Max: 50
└─ Step: 5 (test 5, 10, 15, ..., 50)

Parameter: SMA Length 2
├─ Min: 20
├─ Max: 200
└─ Step: 10 (test 20, 30, 40, ..., 200)

Total combinations: 10 × 19 = 190 ✅ (reasonable)
```

### Step 4: Start Optimization

1. Click **Start Optimization**
2. Monitor progress (may take 30 min - 2 hours depending on size)
3. Results display as they complete

---

## Understanding Results

### Best Parameters

The optimizer shows:

```
Rank | L1 | L2 | Net Profit | Sharpe | Win % | Profit Factor
-----|----|----|------------|--------|-------|---------------
 1   | 18 | 52 | +15.2%     | 1.45   | 62%   | 2.1 ✅ Best
 2   | 19 | 51 | +14.8%     | 1.42   | 61%   | 2.0
 3   | 17 | 53 | +14.5%     | 1.40   | 60%   | 1.95
 ...
```

**Interpretation**:
- Rank 1 (L1=18, L2=52) is best for this data
- Top 3 are very similar (variation normal)
- Gap to rank 4+ suggests good parameters found

### Parameter Importance

Shows which parameters most affect results:

```
Importance Score:
├─ SMA Length 1: 72% ⭐⭐⭐
├─ SMA Length 2: 65% ⭐⭐
└─ Risk % per trade: 8% ⭐
```

**Meaning**:
- Changing L1 has biggest impact
- L1 is critical; spend effort tuning it
- Risk % barely matters; use sensible default

### Optimization History

Chart showing how optimizer improved over time:

```
Iteration | Best Profit
----------|----------
1         | +2.1%
10        | +8.5%
50        | +14.2%
100       | +15.2% (plateau - no improvement)
```

**Interpretation**: Optimizer found best parameters by iteration 100; after that, no progress.

---

## Algorithms Explained

### Bayesian Optimization

**How it works**: Probability-based search that learns which regions are promising.

```
Iteration 1: Test random parameters
           Result: L1=10, L2=30 → +3%
                   L1=40, L2=100 → +8%

Iteration 2: Algorithm learns "L1=40, L2=100 region looks good"
           Test nearby: L1=35, L2=105 → +9%
                       L1=45, L2=95 → +10%

Iteration 3: Zoom in on best region
           Continue refining...
```

**Pros**:
- ✅ Fast (fewer backtests)
- ✅ Efficient exploration
- ✅ Good for 2-5 parameters

**Cons**:
- ❌ May miss isolated peaks
- ❌ Can get stuck in local optima

**Use when**: Time is limited, few parameters

### Genetic Algorithm

**How it works**: Simulates evolution (survival of the fittest).

```
Generation 1 (random population):
├─ Individual 1: L1=10, L2=30 → +3% fitness
├─ Individual 2: L1=40, L2=100 → +8% fitness ⭐
├─ Individual 3: L1=25, L2=60 → +6% fitness
└─ Individual 4: L1=50, L2=200 → +2% fitness ❌

Generation 2 (breeding best individuals):
├─ Mutant 1: L1=42, L2=102 (offspring of #2)
├─ Mutant 2: L1=39, L2=98 (offspring of #2)
├─ Mutant 3: L1=27, L2=65 (offspring of #3)
└─ Mutant 4: L1=20, L2=35 (random)

Generation 3-N: Continue until convergence
```

**Pros**:
- ✅ Explores broadly
- ✅ Better at finding global optima
- ✅ Handles complex parameter interactions

**Cons**:
- ❌ Slower (many backtests)
- ❌ Harder to interpret

**Use when**: Time available, many parameters, seeking thorough search

---

## Best Practices

### Practice 1: Avoid Overfitting

**Overfitting**: Optimizing too much until strategy only works on test data.

**Prevention**:
1. Use large date range (2+ years)
2. Use round numbers (L1=20, not L1=23)
3. Optimize only critical parameters
4. Use **out-of-sample** validation

### Out-of-Sample Validation

**Concept**: Optimize on past data, validate on future data.

```
2022-2023: Optimize (find best parameters)
├─ L1=18, L2=52 → +20% profit ✅

2023-2024: Validate (test on unseen data)
├─ L1=18, L2=52 → +8% profit ⚠️
```

**Result**: 20% vs. 8% suggests overfitting.

**Good overfitting tolerance**: <30% drop from in-sample to out-of-sample.

### Practice 2: Start with Reasonable Ranges

❌ **Bad ranges** (too wide):
```
SMA Length 1: 1 to 200 (huge search space)
SMA Length 2: 1 to 200 (exponential combinations)
Risk %: 0.1 to 10 (unrealistic values)
```

✅ **Good ranges** (informed):
```
SMA Length 1: 5 to 50 (typical moving average)
SMA Length 2: 30 to 150 (longer period)
Risk %: 1 to 3 (standard risk sizing)
```

### Practice 3: Optimize in Stages

**Stage 1**: Optimize core parameters
```
SMA Length 1: 5-50
SMA Length 2: 30-150
Algorithm: Bayesian
Result: L1=18, L2=52 best
```

**Stage 2**: Fine-tune around best
```
SMA Length 1: 15-20
SMA Length 2: 50-55
Algorithm: Genetic
Result: L1=19, L2=51 even better
```

### Practice 4: Use Multiple Objectives

Sometimes profit isn't everything:

```
Primary Objective: Net Profit
Secondary Objective: Win Rate > 55%
Filter: Only test parameters with WR > 55%
Result: Slightly lower profit, but more consistent ✅
```

### Practice 5: Re-optimize Quarterly

Markets change; old parameters may not work.

```
Q1 2024: Optimize → Best L1=18, L2=52
Q2 2024: Re-optimize → Best L1=22, L2=48
         (market volatility increased, needs adjustment)
```

### Practice 6: Document Results

Keep a log:

```
Date: 2024-01-15
Strategy: SMA Crossover
Symbol: XAUUSD
In-Sample: 2022-2024
Out-of-Sample: 2024-Q1

Best Parameters Found:
├─ SMA Length 1: 18
├─ SMA Length 2: 52
├─ Risk %: 2

In-Sample Result: +15.2% (profit factor 2.1)
Out-of-Sample Result: +6.8% (profit factor 1.8)

Overfitting Score: 55% drop (acceptable)
Status: ✅ Approved for paper trading
```

---

## Common Pitfalls

### Pitfall 1: Over-Optimizing

**Problem**: Spending hours finding L1=18.3 instead of L1=18.

**Solution**: Use step=1 or step=5. L1=18 and L1=19 are statistically equivalent.

### Pitfall 2: Ignoring Out-of-Sample

**Problem**: Optimizing only 2020-2023, deploying in 2024, then being surprised results drop.

**Solution**: Always validate on held-out future data.

### Pitfall 3: Chasing Recent Performance

**Problem**: "2024 data shows RSI period of 7 is best, so optimize with that."

**Solution**: Use longest available history (2+ years). Recent optimal may not persist.

### Pitfall 4: Too Many Parameters

**Problem**: Optimizing 10 parameters creates enormous search space.

**Solution**: Optimize only 2-3 critical ones. Keep others fixed.

---

## Example: SMA Crossover Optimization

### Setup

```
Strategy: SMA(L1) vs SMA(L2) Crossover
Symbol: XAUUSD
Timeframe: H1
In-Sample: 2022-2024 (2 years)
Out-of-Sample: 2024 (recent 3 months)
Objective: Maximize Net Profit
Algorithm: Bayesian (fast)
```

### Configuration

```
Parameters:
├─ SMA Length 1: min=5, max=50, step=5
├─ SMA Length 2: min=30, max=150, step=10

Search space: 10 × 13 = 130 combinations
Expected time: 30 minutes
```

### Results

```
Best Parameters Found:

Rank | L1 | L2 | In-Sample | Out-Sample | Profit Factor
-----|----|----|-----------|------------|---------------
 1   | 18 | 52 | +20.5%    | +8.2%      | 2.1/1.8 ✅
 2   | 15 | 50 | +19.2%    | +7.9%      | 2.0/1.7
 3   | 20 | 55 | +18.8%    | +8.5%      | 1.9/1.8

Parameter Importance:
├─ L1: 68% (critical)
└─ L2: 62% (important)

Conclusion: L1=18, L2=52 approved for paper trading ✅
```

---

## Next Steps

- **[Backtesting](./03_BACKTESTING.md)**: Test optimized parameters
- **[Live Trading](./04_LIVE_TRADING.md)**: Deploy optimized strategy
- **[ML Lab](./06_ML_LAB.md)**: Add ML signals for better results

---

**Optimize Wisely! 🎯**
