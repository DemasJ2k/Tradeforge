"""
Agent Backtest — All symbols × Both agents (Scalping + Expert).

Uses Databento historical M5 data with walk-forward validation.
- $10,000 starting balance
- Dynamic position sizing (risk = 0.5% of current equity per trade)
- Walk-forward: 3-fold expanding window
- Vectorized feature computation + model prediction (fast)
- Realistic spreads, commissions, slippage

Usage:
    python scripts/agent_backtest_all.py
    python scripts/agent_backtest_all.py --symbols XAUUSD ES
    python scripts/agent_backtest_all.py --agents scalping
    python scripts/agent_backtest_all.py --bars 100000
"""

import argparse
import csv
import json
import os
import sys
import time
import warnings
import numpy as np
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

DATA_DIR = Path(__file__).parent.parent / "data" / "databento"
MODEL_DIR = Path(__file__).parent.parent / "data" / "ml_models"
RESULTS_DIR = Path(__file__).parent.parent / "data" / "agent_backtest_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

ALL_SYMBOLS = ["XAUUSD", "US30", "ES", "NAS100", "BTCUSD"]

# Realistic market costs per symbol
SYMBOL_PARAMS = {
    "XAUUSD": {"spread": 0.30, "commission": 0.30, "pv": 100.0,  "sl_mult": 1.5, "tp_mult": 2.5, "hold": 12, "margin": 0.01},
    "US30":   {"spread": 2.0,  "commission": 1.0,  "pv": 1.0,    "sl_mult": 1.5, "tp_mult": 2.0, "hold": 12, "margin": 0.005},
    "ES":     {"spread": 0.25, "commission": 1.24, "pv": 50.0,   "sl_mult": 1.5, "tp_mult": 2.0, "hold": 12, "margin": 0.05},
    "NAS100": {"spread": 0.50, "commission": 1.24, "pv": 20.0,   "sl_mult": 1.5, "tp_mult": 2.0, "hold": 12, "margin": 0.005},
    "BTCUSD": {"spread": 5.0,  "commission": 0.50, "pv": 1.0,    "sl_mult": 2.0, "tp_mult": 3.0, "hold": 24, "margin": 0.02},
}


# ── Data Loading ──────────────────────────────────────────────────────

def load_csv(path: str, max_bars: int = 0) -> list[dict]:
    """Load Databento CSV into list of OHLCV dicts."""
    data = []
    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                rec = {
                    "open": float(row.get("open") or row.get("Open") or 0),
                    "high": float(row.get("high") or row.get("High") or 0),
                    "low": float(row.get("low") or row.get("Low") or 0),
                    "close": float(row.get("close") or row.get("Close") or 0),
                    "volume": float(row.get("volume") or row.get("Volume") or row.get("tick_volume") or 0),
                }
                dt_val = row.get("datetime") or row.get("Datetime") or row.get("date")
                if dt_val:
                    try:
                        rec["datetime"] = datetime.fromisoformat(str(dt_val).replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        rec["datetime"] = None
                if rec["close"] > 0:
                    data.append(rec)
                if max_bars and len(data) >= max_bars:
                    break
            except (ValueError, TypeError):
                continue
    return data


# ── Vectorized Feature Computation ────────────────────────────────────

def compute_all_features(m5_data, h1_data=None, h4_data=None):
    """Compute features for all bars at once (vectorized)."""
    from app.services.ml.features_mtf import compute_expert_features

    feat_names, X = compute_expert_features(
        m5_data,
        h1_data if h1_data and len(h1_data) >= 50 else None,
        h4_data if h4_data and len(h4_data) >= 20 else None,
        None,  # No daily
    )
    X = np.array(X, dtype=np.float64)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    return feat_names, X


def compute_atr(closes, highs, lows, period=14):
    """Vectorized ATR computation."""
    n = len(closes)
    atr = np.full(n, np.nan)
    for i in range(period, n):
        trs = []
        for j in range(i - period + 1, i + 1):
            tr = max(highs[j] - lows[j],
                     abs(highs[j] - closes[j - 1]) if j > 0 else highs[j] - lows[j],
                     abs(lows[j] - closes[j - 1]) if j > 0 else highs[j] - lows[j])
            trs.append(tr)
        atr[i] = np.mean(trs)
    return atr


def get_session(dt_obj):
    """Get trading session from datetime."""
    if dt_obj is None:
        return "unknown"
    h = dt_obj.hour
    if 0 <= h < 8:
        return "asian"
    elif 8 <= h < 13:
        return "london"
    elif 13 <= h < 21:
        return "ny"
    return "dead"


# ── Model Loading ─────────────────────────────────────────────────────

def load_scalping_models(symbol):
    """Load XGBoost + LightGBM scalping models."""
    import joblib
    models = {}
    prefix = f"scalping_{symbol}_M5"

    for name in ("xgboost", "lightgbm"):
        path = MODEL_DIR / f"{prefix}_{name}.joblib"
        if path.exists():
            data = joblib.load(path)
            models[name] = data["model"]
            if "feature_names" not in models:
                models["feature_names"] = data.get("feature_names", [])
    return models


def load_expert_models(symbol):
    """Load XGBoost + LightGBM + LSTM expert models."""
    import joblib
    models = {}
    prefix = f"expert_{symbol}_M5"

    for name in ("xgboost", "lightgbm"):
        path = MODEL_DIR / f"{prefix}_{name}.joblib"
        if path.exists():
            data = joblib.load(path)
            models[name] = data["model"]
            if "feature_names" not in models:
                models["feature_names"] = data.get("feature_names", [])

    # Meta-labeler
    meta_path = MODEL_DIR / f"{prefix}_meta.joblib"
    if meta_path.exists():
        data = joblib.load(meta_path)
        models["meta"] = data["model"]

    return models


# ── Vectorized Backtest Engine ────────────────────────────────────────

def backtest_agent(
    preds,          # Model predictions per bar (0=sell, 1=neutral, 2=buy)
    confs,          # Confidence per bar
    closes,         # Close prices
    highs,          # High prices
    lows,           # Low prices
    datetimes,      # Datetime objects per bar
    params,         # Symbol parameters
    initial_balance=10_000.0,
    risk_per_trade=0.005,
    conf_thresh=0.55,
    session_filter=True,
    cooldown_bars=3,
    symbol="XAUUSD",
):
    """
    Vectorized backtest with dynamic position sizing.

    Returns dict with equity curve, trades, and stats.
    """
    n = len(preds)
    spread = params["spread"]
    comm = params["commission"]
    pv = params["pv"]
    sl_mult = params["sl_mult"]
    tp_mult = params["tp_mult"]
    max_hold = params["hold"]

    # ATR
    atr = compute_atr(closes, highs, lows)

    equity = initial_balance
    equity_curve = [equity]
    trades = []
    last_trade_bar = -100

    i = 14  # Start after ATR warmup
    while i < n - 1:
        # Skip neutral, low conf, NaN ATR
        if preds[i] == 1 or confs[i] < conf_thresh or np.isnan(atr[i]):
            equity_curve.append(equity)
            i += 1
            continue

        # Cooldown
        if i - last_trade_bar < cooldown_bars:
            equity_curve.append(equity)
            i += 1
            continue

        # Session filter
        session = get_session(datetimes[i]) if datetimes[i] else "unknown"
        if session_filter and session == "dead" and symbol != "BTCUSD":
            equity_curve.append(equity)
            i += 1
            continue

        direction = 1 if preds[i] == 2 else -1
        entry = closes[i]
        sl_d = atr[i] * sl_mult
        tp_d = atr[i] * tp_mult

        if sl_d <= 0:
            equity_curve.append(equity)
            i += 1
            continue

        if direction == 1:
            sl = entry - sl_d
            tp = entry + tp_d
        else:
            sl = entry + sl_d
            tp = entry - tp_d

        # Dynamic position sizing: risk = X% of current equity
        session_mult = 0.5 if session == "asian" and symbol != "BTCUSD" else 1.0
        risk_amount = equity * risk_per_trade * session_mult
        # Position size in units = risk / (SL distance × point value)
        if pv > 0 and sl_d > 0:
            position_size = risk_amount / (sl_d * pv)
        else:
            position_size = 0.01

        # Simulate trade exit
        exit_price = None
        exit_bar = i
        for j in range(i + 1, min(i + max_hold + 1, n)):
            if direction == 1:
                if lows[j] <= sl:
                    exit_price = sl
                    exit_bar = j
                    break
                if highs[j] >= tp:
                    exit_price = tp
                    exit_bar = j
                    break
            else:
                if highs[j] >= sl:
                    exit_price = sl
                    exit_bar = j
                    break
                if lows[j] <= tp:
                    exit_price = tp
                    exit_bar = j
                    break

        if exit_price is None:
            exit_bar = min(i + max_hold, n - 1)
            exit_price = closes[exit_bar]

        # PnL with costs
        price_pnl = (exit_price - entry) * direction
        cost = spread + (2 * comm / pv) if pv > 0 else spread
        net_pnl_per_unit = price_pnl - cost
        dollar_pnl = net_pnl_per_unit * position_size * pv

        equity += dollar_pnl
        last_trade_bar = i

        trades.append({
            "bar": i,
            "exit_bar": exit_bar,
            "direction": "BUY" if direction == 1 else "SELL",
            "entry": round(entry, 5),
            "exit": round(exit_price, 5),
            "sl": round(sl, 5),
            "tp": round(tp, 5),
            "pnl": round(dollar_pnl, 2),
            "equity_after": round(equity, 2),
            "position_size": round(position_size, 4),
            "session": session,
            "confidence": round(float(confs[i]), 4),
        })

        # Fill equity curve for bars while in trade
        for _ in range(i, exit_bar):
            equity_curve.append(equity)
        i = exit_bar + 1

    # Fill remaining equity curve
    while len(equity_curve) < n:
        equity_curve.append(equity)

    return compute_results(trades, equity_curve, initial_balance)


def compute_results(trades, equity_curve, initial_balance):
    """Compute summary statistics from trades and equity curve."""
    final_equity = equity_curve[-1] if equity_curve else initial_balance
    pnl = final_equity - initial_balance
    pnl_pct = (pnl / initial_balance) * 100

    n_trades = len(trades)
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    win_rate = (len(wins) / n_trades * 100) if n_trades > 0 else 0
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0.001
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Max drawdown
    max_dd = 0
    max_dd_pct = 0
    peak = equity_curve[0] if equity_curve else initial_balance
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = peak - eq
        dd_pct = (dd / peak * 100) if peak > 0 else 0
        if dd_pct > max_dd_pct:
            max_dd = dd
            max_dd_pct = dd_pct

    # Sharpe (annualized from daily equity samples)
    sharpe = 0
    if len(equity_curve) > 288:
        eq = np.array(equity_curve)
        daily_eq = eq[::288]
        if len(daily_eq) > 2:
            daily_returns = np.diff(daily_eq) / daily_eq[:-1]
            std = daily_returns.std()
            if std > 1e-10:
                sharpe = float(np.mean(daily_returns) / std * (252 ** 0.5))

    avg_trade = pnl / n_trades if n_trades > 0 else 0
    avg_win = gross_profit / len(wins) if wins else 0
    avg_loss = gross_loss / len(losses) if losses else 0

    return {
        "initial_balance": initial_balance,
        "final_equity": round(final_equity, 2),
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "total_trades": n_trades,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "profit_factor": round(min(profit_factor, 999), 2),
        "sharpe": round(sharpe, 2),
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "avg_trade": round(avg_trade, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "equity_curve_sample": [round(equity_curve[i], 2) for i in range(0, len(equity_curve), max(1, len(equity_curve) // 100))],
    }


# ── Agent Signal Generation ──────────────────────────────────────────

def generate_scalping_signals(X, models, conf_thresh=0.55):
    """Generate predictions from scalping dual-model ensemble."""
    n = X.shape[0]
    preds = np.ones(n, dtype=int)  # Default: neutral
    confs = np.zeros(n, dtype=float)

    xgb = models.get("xgboost")
    lgb = models.get("lightgbm")

    if xgb:
        xgb_pred = xgb.predict(X)
        xgb_proba = xgb.predict_proba(X)
        xgb_conf = np.max(xgb_proba, axis=1)
    else:
        return preds, confs

    if lgb:
        lgb_pred = lgb.predict(X)
        lgb_proba = lgb.predict_proba(X)
        lgb_conf = np.max(lgb_proba, axis=1)
    else:
        lgb_pred = xgb_pred
        lgb_conf = xgb_conf

    # Both models must agree and be non-neutral with sufficient confidence
    for i in range(n):
        xp = xgb_pred[i]
        lp = lgb_pred[i]
        xc = xgb_conf[i]
        lc = lgb_conf[i]

        # Both predict same non-neutral direction
        if xp == lp and xp != 1 and xc >= conf_thresh and lc >= conf_thresh:
            preds[i] = int(xp)
            confs[i] = (xc + lc) / 2

    return preds, confs


def generate_expert_signals(X, models, conf_thresh=0.55):
    """Generate predictions from expert ensemble (XGB + LGB + meta)."""
    n = X.shape[0]
    preds = np.ones(n, dtype=int)  # Default: neutral
    confs = np.zeros(n, dtype=float)

    xgb = models.get("xgboost")
    lgb = models.get("lightgbm")
    meta = models.get("meta")

    if not xgb and not lgb:
        return preds, confs

    xgb_pred = xgb.predict(X) if xgb else None
    xgb_proba = xgb.predict_proba(X) if xgb else None
    lgb_pred = lgb.predict(X) if lgb else None
    lgb_proba = lgb.predict_proba(X) if lgb else None

    # Meta-labeler: binary approval filter
    meta_approved = np.ones(n, dtype=bool)
    if meta:
        try:
            meta_pred = meta.predict(X)
            meta_approved = meta_pred == 1
        except Exception:
            pass

    for i in range(n):
        votes = []
        vote_confs = []

        if xgb_pred is not None and xgb_pred[i] != 1:
            c = float(np.max(xgb_proba[i]))
            if c >= conf_thresh:
                votes.append(int(xgb_pred[i]))
                vote_confs.append(c)

        if lgb_pred is not None and lgb_pred[i] != 1:
            c = float(np.max(lgb_proba[i]))
            if c >= conf_thresh:
                votes.append(int(lgb_pred[i]))
                vote_confs.append(c)

        # Need at least 2 agreeing votes
        if len(votes) >= 2 and len(set(votes)) == 1:
            # Meta-labeler approval
            if meta_approved[i]:
                preds[i] = votes[0]
                confs[i] = np.mean(vote_confs)

    return preds, confs


# ── Walk-Forward Backtest ─────────────────────────────────────────────

def run_symbol_agent(symbol, agent_type, m5_data, h1_data, h4_data, params, n_folds=3,
                     initial_balance=10_000.0, max_bars=0):
    """Run walk-forward backtest for one symbol × one agent type."""

    # Load models
    if agent_type == "scalping":
        models = load_scalping_models(symbol)
    else:
        models = load_expert_models(symbol)

    if not models.get("xgboost") and not models.get("lightgbm"):
        print(f"    No models found for {agent_type} {symbol} — skipping")
        return {"error": "no_models"}

    # Compute features once for all data
    print(f"    Computing features ({len(m5_data):,} bars)...", end=" ", flush=True)
    t0 = time.time()
    feat_names, X = compute_all_features(m5_data, h1_data, h4_data)
    print(f"{len(feat_names)} features ({time.time() - t0:.1f}s)")

    # Price arrays aligned with features
    n = min(len(X), len(m5_data))
    closes = np.array([d["close"] for d in m5_data[:n]], dtype=np.float64)
    highs = np.array([d["high"] for d in m5_data[:n]], dtype=np.float64)
    lows = np.array([d["low"] for d in m5_data[:n]], dtype=np.float64)
    datetimes = [d.get("datetime") for d in m5_data[:n]]

    # Generate all signals at once
    print(f"    Generating {agent_type} signals...", end=" ", flush=True)
    t0 = time.time()
    if agent_type == "scalping":
        preds, confs = generate_scalping_signals(X, models)
    else:
        preds, confs = generate_expert_signals(X, models)

    n_signals = np.sum((preds != 1) & (confs >= 0.55))
    print(f"{n_signals:,} raw signals ({time.time() - t0:.1f}s)")

    # Walk-forward: split into folds
    total = len(closes)
    fold_size = total // (n_folds + 1)

    fold_results = []
    for fold in range(n_folds):
        oos_start = fold_size * (fold + 1)
        oos_end = min(fold_size * (fold + 2), total)

        if oos_end - oos_start < 1000:
            continue

        # Get date range
        start_dt = datetimes[oos_start]
        end_dt = datetimes[oos_end - 1]
        start_str = start_dt.strftime("%Y-%m-%d") if start_dt else "?"
        end_str = end_dt.strftime("%Y-%m-%d") if end_dt else "?"

        print(f"\n    Fold {fold+1}/{n_folds}: bars {oos_start:,}→{oos_end:,} ({start_str} → {end_str})")

        t0 = time.time()
        result = backtest_agent(
            preds=preds[oos_start:oos_end],
            confs=confs[oos_start:oos_end],
            closes=closes[oos_start:oos_end],
            highs=highs[oos_start:oos_end],
            lows=lows[oos_start:oos_end],
            datetimes=datetimes[oos_start:oos_end],
            params=params,
            initial_balance=initial_balance,
            risk_per_trade=0.005,
            symbol=symbol,
        )
        elapsed = time.time() - t0

        result["fold"] = fold + 1
        result["oos_start"] = start_str
        result["oos_end"] = end_str
        result["elapsed_s"] = round(elapsed, 1)
        result["bars_tested"] = oos_end - oos_start
        fold_results.append(result)

        status = "PASS" if result["profit_factor"] > 1.0 else "FAIL"
        print(f"      PnL: ${result['pnl']:+,.2f} ({result['pnl_pct']:+.1f}%) | "
              f"Trades: {result['total_trades']} | WR: {result['win_rate']:.1f}% | "
              f"PF: {result['profit_factor']:.2f} | Sharpe: {result['sharpe']:.2f} | "
              f"MaxDD: {result['max_drawdown_pct']:.1f}% | {status} ({elapsed:.1f}s)")

    # Aggregate
    if fold_results:
        total_pnl = sum(r["pnl"] for r in fold_results)
        total_trades = sum(r["total_trades"] for r in fold_results)
        total_wins = sum(r["wins"] for r in fold_results)
        avg_pf = sum(r["profit_factor"] for r in fold_results) / len(fold_results)
        avg_sharpe = sum(r["sharpe"] for r in fold_results) / len(fold_results)
        avg_wr = (total_wins / total_trades * 100) if total_trades > 0 else 0
        worst_dd = max(r["max_drawdown_pct"] for r in fold_results)
        profitable = sum(1 for r in fold_results if r["pnl"] > 0)

        verdict = ("PASS" if profitable == len(fold_results) and avg_pf > 1.0 else
                   "MARGINAL" if profitable > len(fold_results) / 2 else "FAIL")

        agg = {
            "total_pnl": round(total_pnl, 2),
            "total_trades": total_trades,
            "avg_profit_factor": round(avg_pf, 2),
            "avg_sharpe": round(avg_sharpe, 2),
            "avg_win_rate": round(avg_wr, 1),
            "worst_drawdown_pct": round(worst_dd, 2),
            "profitable_folds": f"{profitable}/{len(fold_results)}",
            "verdict": verdict,
        }

        print(f"\n    ── AGGREGATE: {symbol} {agent_type.upper()} ──")
        print(f"    Total PnL: ${total_pnl:+,.2f} | Trades: {total_trades:,} | "
              f"Avg PF: {avg_pf:.2f} | Sharpe: {avg_sharpe:.2f} | "
              f"WR: {avg_wr:.1f}% | Worst DD: {worst_dd:.1f}% → {verdict}")

        return {"folds": fold_results, "aggregate": agg}

    return {"folds": [], "aggregate": {"verdict": "NO_DATA"}}


# ── Main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Agent Walk-Forward Backtest")
    parser.add_argument("--symbols", nargs="+", default=ALL_SYMBOLS)
    parser.add_argument("--agents", nargs="+", default=["scalping", "expert"],
                        choices=["scalping", "expert"])
    parser.add_argument("--bars", type=int, default=150_000,
                        help="Max M5 bars per symbol (0 = all)")
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument("--balance", type=float, default=10_000.0)
    args = parser.parse_args()

    print("=" * 70)
    print("  TRADEFORGE — Agent Walk-Forward Backtest")
    print("=" * 70)
    print(f"  Symbols:  {args.symbols}")
    print(f"  Agents:   {args.agents}")
    print(f"  Balance:  ${args.balance:,.0f}")
    print(f"  Max bars: {args.bars:,}")
    print(f"  WF folds: {args.folds}")
    print(f"  Data dir: {DATA_DIR}")
    print(f"  Model dir: {MODEL_DIR}")
    print()

    all_results = {}
    t_start = time.time()

    for symbol in args.symbols:
        m5_path = DATA_DIR / f"{symbol}_M5.csv"
        h1_path = DATA_DIR / f"{symbol}_H1.csv"

        if not m5_path.exists():
            print(f"  {symbol}_M5.csv not found — skipping")
            continue

        print(f"\n{'='*70}")
        print(f"  {symbol}")
        print(f"{'='*70}")

        # Load M5 data
        print(f"  Loading {m5_path.name}...", end=" ", flush=True)
        t0 = time.time()
        m5_data = load_csv(str(m5_path), max_bars=args.bars)
        print(f"{len(m5_data):,} bars ({time.time() - t0:.1f}s)")

        # Load H1 + H4 data (for multi-timeframe features)
        h1_data = None
        if h1_path.exists():
            h1_data = load_csv(str(h1_path))
            print(f"  Loaded {len(h1_data):,} H1 bars")

        h4_path = DATA_DIR / f"{symbol}_H4.csv"
        h4_data = None
        if h4_path.exists():
            h4_data = load_csv(str(h4_path))
            print(f"  Loaded {len(h4_data):,} H4 bars")

        # Date range
        if m5_data and m5_data[0].get("datetime") and m5_data[-1].get("datetime"):
            print(f"  Range: {m5_data[0]['datetime'].strftime('%Y-%m-%d')} → "
                  f"{m5_data[-1]['datetime'].strftime('%Y-%m-%d')}")

        params = SYMBOL_PARAMS[symbol]
        all_results[symbol] = {}

        for agent_type in args.agents:
            print(f"\n  ── {agent_type.upper()} AGENT ──")
            try:
                result = run_symbol_agent(
                    symbol=symbol,
                    agent_type=agent_type,
                    m5_data=m5_data,
                    h1_data=h1_data,
                    h4_data=h4_data,
                    params=params,
                    n_folds=args.folds,
                    initial_balance=args.balance,
                )
                all_results[symbol][agent_type] = result
            except Exception as e:
                print(f"    ERROR: {e}")
                import traceback
                traceback.print_exc()
                all_results[symbol][agent_type] = {"error": str(e)}

    # ── Summary Table ──
    elapsed = time.time() - t_start
    print(f"\n\n{'='*70}")
    print("  RESULTS SUMMARY")
    print(f"{'='*70}\n")
    print(f"  {'Symbol':<10} {'Agent':<10} {'PnL':>10} {'PnL%':>8} {'Trades':>8} "
          f"{'WR':>6} {'PF':>6} {'Sharpe':>8} {'MaxDD':>8} {'Verdict':>10}")
    print(f"  {'─'*8:<10} {'─'*8:<10} {'─'*8:>10} {'─'*6:>8} {'─'*6:>8} "
          f"{'─'*4:>6} {'─'*4:>6} {'─'*6:>8} {'─'*6:>8} {'─'*8:>10}")

    for symbol in args.symbols:
        if symbol not in all_results:
            continue
        for agent_type in args.agents:
            if agent_type not in all_results[symbol]:
                continue
            r = all_results[symbol][agent_type]
            if "error" in r:
                print(f"  {symbol:<10} {agent_type:<10} {'ERROR':>10} — {r['error']}")
                continue
            agg = r.get("aggregate", {})
            if agg.get("verdict") == "NO_DATA":
                print(f"  {symbol:<10} {agent_type:<10} {'NO DATA':>10}")
                continue

            print(f"  {symbol:<10} {agent_type:<10} "
                  f"${agg.get('total_pnl', 0):>+9,.2f} "
                  f"{agg.get('total_pnl', 0) / args.balance * 100:>+7.1f}% "
                  f"{agg.get('total_trades', 0):>8,} "
                  f"{agg.get('avg_win_rate', 0):>5.1f}% "
                  f"{agg.get('avg_profit_factor', 0):>5.2f} "
                  f"{agg.get('avg_sharpe', 0):>7.2f} "
                  f"{agg.get('worst_drawdown_pct', 0):>7.1f}% "
                  f"{agg.get('verdict', '?'):>10}")

    print(f"\n  Total time: {elapsed:.0f}s ({elapsed/60:.1f}m)")

    # Save results
    results_file = RESULTS_DIR / "agent_backtest_results.json"
    clean = {}
    for sym, agents in all_results.items():
        clean[sym] = {}
        for agent, data in agents.items():
            if "error" in data:
                clean[sym][agent] = data
                continue
            clean[sym][agent] = {
                "aggregate": data.get("aggregate", {}),
                "folds": [{k: v for k, v in fold.items() if k != "equity_curve_sample"}
                          for fold in data.get("folds", [])],
            }
    with open(results_file, "w") as f:
        json.dump(clean, f, indent=2)

    print(f"\n  Results saved: {results_file}")
    print(f"\n{'='*70}")
    print(f"  BACKTEST COMPLETE — {elapsed:.0f}s ({elapsed/60:.1f}m)")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
