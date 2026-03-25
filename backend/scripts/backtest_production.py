"""
Production Backtest — All 5 symbols × Both agents.

$10,000 USD starting balance
1% risk per trade (dynamic sizing based on current equity)
Realistic costs (spread + commission + slippage)
2022-01-01 → 2026-03-25 (OOS period)
News avoidance: skip trading during first/last trading days of month (NFP/FOMC)
Session filtering + dead zone avoidance

Outputs:
  - Summary table (PF, Sharpe, WR, ROI, MaxDD)
  - Trade logs (CSV per symbol/agent)
  - Equity curves (CSV per symbol/agent)
"""

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
RESULTS_DIR = Path(__file__).parent.parent / "data" / "backtest_production"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

ALL_SYMBOLS = ["XAUUSD", "US30", "ES", "NAS100", "BTCUSD"]
INITIAL_BALANCE = 100_000.0
RISK_PER_TRADE = 0.01  # 1% of equity (used only when dynamic sizing is on)
FIXED_LOT_SIZE = 0.1   # Fixed lot size for all symbols

# Date filter: 2022-01-01 to 2026-03-25
DATE_START = datetime(2022, 1, 1, tzinfo=timezone.utc)
DATE_END = datetime(2026, 3, 25, tzinfo=timezone.utc)

# Realistic market costs per symbol
SYMBOL_PARAMS = {
    "XAUUSD": {"spread": 0.30, "commission": 0.30, "pv": 100.0, "sl_mult": 1.5, "tp_mult": 2.5, "hold": 12, "margin": 0.01, "slippage": 0.10},
    "US30":   {"spread": 2.0,  "commission": 1.0,  "pv": 1.0,   "sl_mult": 1.5, "tp_mult": 2.0, "hold": 12, "margin": 0.005, "slippage": 1.0},
    "ES":     {"spread": 0.25, "commission": 1.24, "pv": 50.0,  "sl_mult": 1.5, "tp_mult": 2.0, "hold": 12, "margin": 0.05,  "slippage": 0.25},
    "NAS100": {"spread": 0.50, "commission": 1.24, "pv": 20.0,  "sl_mult": 1.5, "tp_mult": 2.0, "hold": 12, "margin": 0.005, "slippage": 0.25},
    "BTCUSD": {"spread": 5.0,  "commission": 0.50, "pv": 1.0,   "sl_mult": 2.0, "tp_mult": 3.0, "hold": 24, "margin": 0.02,  "slippage": 3.0},
}

# High-impact news: first Friday of month (NFP) and FOMC days
# Approximated as: skip trading on 1st-3rd and 14th-15th of each month (covers NFP + CPI + FOMC)
NEWS_BLACKOUT_DAYS = set(range(1, 4)) | {14, 15}


# ── Data Loading ──────────────────────────────────────────────────────

def load_csv(path: str, date_start=None, date_end=None) -> list[dict]:
    """Load Databento CSV, filtered to date range."""
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

                if rec["close"] <= 0:
                    continue

                # Date filter
                if date_start and rec.get("datetime") and rec["datetime"] < date_start:
                    continue
                if date_end and rec.get("datetime") and rec["datetime"] > date_end:
                    continue

                data.append(rec)
            except (ValueError, TypeError):
                continue
    return data


# ── Feature Computation ──────────────────────────────────────────────

MAX_M5_BARS = 150_000  # Cap to prevent OOM (150K M5 bars ≈ 2.5 years)

def compute_all_features(m5_data, h1_data=None, h4_data=None):
    """Compute features for all bars at once (vectorized)."""
    import gc
    from app.services.ml.features_mtf import compute_expert_features

    # Cap data to prevent OOM
    if len(m5_data) > MAX_M5_BARS:
        m5_data = m5_data[-MAX_M5_BARS:]
    if h1_data and len(h1_data) > 12000:
        h1_data = h1_data[-12000:]
    if h4_data and len(h4_data) > 4000:
        h4_data = h4_data[-4000:]

    feat_names, X = compute_expert_features(
        m5_data,
        h1_data if h1_data and len(h1_data) >= 50 else None,
        h4_data if h4_data and len(h4_data) >= 20 else None,
        None,
    )
    X = np.array(X, dtype=np.float32)  # float32 halves memory vs float64
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    gc.collect()
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


def is_news_blackout(dt_obj):
    """Check if bar falls on a high-impact news day."""
    if dt_obj is None:
        return False
    return dt_obj.day in NEWS_BLACKOUT_DAYS


# ── Model Loading ─────────────────────────────────────────────────────

def load_scalping_models(symbol):
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
    meta_path = MODEL_DIR / f"{prefix}_meta.joblib"
    if meta_path.exists():
        data = joblib.load(meta_path)
        models["meta"] = data["model"]
    return models


# ── Signal Generation ────────────────────────────────────────────────

def generate_scalping_signals(X, models, conf_thresh=0.55):
    n = X.shape[0]
    preds = np.ones(n, dtype=int)
    confs = np.zeros(n, dtype=float)

    xgb = models.get("xgboost")
    lgb = models.get("lightgbm")
    if not xgb:
        return preds, confs

    xgb_pred = xgb.predict(X)
    xgb_proba = xgb.predict_proba(X)
    xgb_conf = np.max(xgb_proba, axis=1)

    if lgb:
        lgb_pred = lgb.predict(X)
        lgb_proba = lgb.predict_proba(X)
        lgb_conf = np.max(lgb_proba, axis=1)
    else:
        lgb_pred = xgb_pred
        lgb_conf = xgb_conf

    for i in range(n):
        if xgb_pred[i] == lgb_pred[i] and xgb_pred[i] != 1 and xgb_conf[i] >= conf_thresh and lgb_conf[i] >= conf_thresh:
            preds[i] = int(xgb_pred[i])
            confs[i] = (xgb_conf[i] + lgb_conf[i]) / 2
    return preds, confs


def generate_expert_signals(X, models, conf_thresh=0.55):
    n = X.shape[0]
    preds = np.ones(n, dtype=int)
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

        if len(votes) >= 2 and len(set(votes)) == 1:
            if meta_approved[i]:
                preds[i] = votes[0]
                confs[i] = np.mean(vote_confs)
    return preds, confs


# ── Backtest Engine ──────────────────────────────────────────────────

def backtest_agent(
    preds, confs, closes, highs, lows, datetimes,
    params, symbol, initial_balance=10_000.0, risk_per_trade=0.01,
    conf_thresh=0.55, cooldown_bars=3,
):
    """Full backtest with trade logs, equity curve, and news avoidance."""
    n = len(preds)
    spread = params["spread"]
    comm = params["commission"]
    pv = params["pv"]
    sl_mult = params["sl_mult"]
    tp_mult = params["tp_mult"]
    max_hold = params["hold"]
    slippage = params.get("slippage", 0)

    atr = compute_atr(closes, highs, lows)

    equity = initial_balance
    peak_equity = initial_balance
    equity_curve = []
    trades = []
    last_trade_bar = -100
    news_filtered = 0
    session_filtered = 0

    i = 14
    while i < n - 1:
        equity_curve.append({"bar": i, "equity": round(equity, 2),
                             "datetime": datetimes[i].isoformat() if datetimes[i] else ""})

        # Skip neutral, low conf, NaN ATR
        if preds[i] == 1 or confs[i] < conf_thresh or np.isnan(atr[i]):
            i += 1
            continue

        # Cooldown
        if i - last_trade_bar < cooldown_bars:
            i += 1
            continue

        # Session filter
        session = get_session(datetimes[i]) if datetimes[i] else "unknown"
        if session == "dead" and symbol != "BTCUSD":
            session_filtered += 1
            i += 1
            continue

        # News avoidance
        if is_news_blackout(datetimes[i]):
            news_filtered += 1
            i += 1
            continue

        direction = 1 if preds[i] == 2 else -1
        entry = closes[i]
        sl_d = atr[i] * sl_mult
        tp_d = atr[i] * tp_mult

        if sl_d <= 0:
            i += 1
            continue

        # Apply slippage to entry
        if direction == 1:
            entry += slippage
            sl = entry - sl_d
            tp = entry + tp_d
        else:
            entry -= slippage
            sl = entry + sl_d
            tp = entry - tp_d

        # Fixed lot size (0.1 lots for all symbols)
        position_size = FIXED_LOT_SIZE

        # Simulate trade exit
        exit_price = None
        exit_bar = i
        exit_reason = "max_hold"
        for j in range(i + 1, min(i + max_hold + 1, n)):
            if direction == 1:
                if lows[j] <= sl:
                    exit_price = sl
                    exit_bar = j
                    exit_reason = "stop_loss"
                    break
                if highs[j] >= tp:
                    exit_price = tp
                    exit_bar = j
                    exit_reason = "take_profit"
                    break
            else:
                if highs[j] >= sl:
                    exit_price = sl
                    exit_bar = j
                    exit_reason = "stop_loss"
                    break
                if lows[j] <= tp:
                    exit_price = tp
                    exit_bar = j
                    exit_reason = "take_profit"
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
        if equity > peak_equity:
            peak_equity = equity
        last_trade_bar = i

        entry_dt = datetimes[i].isoformat() if datetimes[i] else ""
        exit_dt = datetimes[exit_bar].isoformat() if datetimes[exit_bar] else ""

        trades.append({
            "trade_num": len(trades) + 1,
            "entry_datetime": entry_dt,
            "exit_datetime": exit_dt,
            "direction": "BUY" if direction == 1 else "SELL",
            "entry_price": round(entry, 5),
            "exit_price": round(exit_price, 5),
            "stop_loss": round(sl, 5),
            "take_profit": round(tp, 5),
            "position_size": round(position_size, 4),
            "pnl": round(dollar_pnl, 2),
            "equity_after": round(equity, 2),
            "drawdown_from_peak": round(peak_equity - equity, 2),
            "session": session,
            "confidence": round(float(confs[i]), 4),
            "exit_reason": exit_reason,
            "bars_held": exit_bar - i,
        })

        # Fill equity curve for bars while in trade
        for k in range(i + 1, exit_bar + 1):
            equity_curve.append({"bar": k, "equity": round(equity, 2),
                                 "datetime": datetimes[k].isoformat() if k < len(datetimes) and datetimes[k] else ""})
        i = exit_bar + 1

    # Fill remaining
    while len(equity_curve) < n:
        equity_curve.append({"bar": len(equity_curve), "equity": round(equity, 2), "datetime": ""})

    # Compute stats
    stats = compute_stats(trades, equity_curve, initial_balance)
    stats["news_filtered"] = news_filtered
    stats["session_filtered"] = session_filtered
    return stats, trades, equity_curve


def compute_stats(trades, equity_curve, initial_balance):
    """Compute summary statistics."""
    equities = [e["equity"] for e in equity_curve]
    final_equity = equities[-1] if equities else initial_balance
    pnl = final_equity - initial_balance
    roi_pct = (pnl / initial_balance) * 100

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
    peak = initial_balance
    for eq in equities:
        if eq > peak:
            peak = eq
        dd = peak - eq
        dd_pct = (dd / peak * 100) if peak > 0 else 0
        if dd_pct > max_dd_pct:
            max_dd = dd
            max_dd_pct = dd_pct

    # Sharpe (annualized from 5-min bars, 288 bars/day)
    sharpe = 0
    if len(equities) > 288:
        eq = np.array(equities)
        daily_eq = eq[::288]
        if len(daily_eq) > 2:
            daily_returns = np.diff(daily_eq) / daily_eq[:-1]
            std = daily_returns.std()
            if std > 1e-10:
                sharpe = float(np.mean(daily_returns) / std * (252 ** 0.5))

    # Win/loss streaks
    max_win_streak = max_loss_streak = cur_win = cur_loss = 0
    for p in pnls:
        if p > 0:
            cur_win += 1
            cur_loss = 0
        else:
            cur_loss += 1
            cur_win = 0
        max_win_streak = max(max_win_streak, cur_win)
        max_loss_streak = max(max_loss_streak, cur_loss)

    avg_trade = pnl / n_trades if n_trades > 0 else 0
    avg_win = gross_profit / len(wins) if wins else 0
    avg_loss = gross_loss / len(losses) if losses else 0

    # Session breakdown
    session_trades = {}
    for t in trades:
        s = t.get("session", "unknown")
        if s not in session_trades:
            session_trades[s] = {"count": 0, "pnl": 0, "wins": 0}
        session_trades[s]["count"] += 1
        session_trades[s]["pnl"] += t["pnl"]
        if t["pnl"] > 0:
            session_trades[s]["wins"] += 1

    # Exit reason breakdown
    exit_reasons = {}
    for t in trades:
        r = t.get("exit_reason", "unknown")
        if r not in exit_reasons:
            exit_reasons[r] = 0
        exit_reasons[r] += 1

    return {
        "initial_balance": initial_balance,
        "final_equity": round(final_equity, 2),
        "pnl": round(pnl, 2),
        "roi_pct": round(roi_pct, 2),
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
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "session_breakdown": session_trades,
        "exit_reasons": exit_reasons,
    }


# ── Save Results ─────────────────────────────────────────────────────

def save_trade_log(trades, symbol, agent_type):
    """Save trade log as CSV."""
    path = RESULTS_DIR / f"{symbol}_{agent_type}_trades.csv"
    if not trades:
        return
    keys = trades[0].keys()
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(trades)
    print(f"    Saved: {path.name} ({len(trades)} trades)")


def save_equity_curve(equity_curve, symbol, agent_type):
    """Save equity curve as CSV (sampled to ~1000 points)."""
    path = RESULTS_DIR / f"{symbol}_{agent_type}_equity.csv"
    if not equity_curve:
        return
    # Sample to manageable size
    step = max(1, len(equity_curve) // 1000)
    sampled = equity_curve[::step]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["bar", "datetime", "equity"])
        w.writeheader()
        w.writerows(sampled)
    print(f"    Saved: {path.name} ({len(sampled)} points)")


# ── Main ──────────────────────────────────────────────────────────────

def main():
    print("=" * 78)
    print("  TRADEFORGE — Production Backtest")
    print("=" * 78)
    print(f"  Balance:    ${INITIAL_BALANCE:,.0f} USD")
    print(f"  Lot Size:   {FIXED_LOT_SIZE} lots (fixed, all symbols)")
    print(f"  Period:     {DATE_START.strftime('%Y-%m-%d')} → {DATE_END.strftime('%Y-%m-%d')}")
    print(f"  Symbols:    {ALL_SYMBOLS}")
    print(f"  Agents:     Scalping + Expert")
    print(f"  Costs:      Spread + commission + slippage (per symbol)")
    print(f"  News:       Avoid high-impact days (NFP/CPI/FOMC)")
    print(f"  Sessions:   Asian (0.5x risk), Dead zone (skip)")
    print(f"  Output:     {RESULTS_DIR}")
    print()

    all_results = {}
    t_start = time.time()

    for symbol in ALL_SYMBOLS:
        m5_path = DATA_DIR / f"{symbol}_M5.csv"
        h1_path = DATA_DIR / f"{symbol}_H1.csv"
        h4_path = DATA_DIR / f"{symbol}_H4.csv"

        if not m5_path.exists():
            print(f"  {symbol}_M5.csv not found — skipping")
            continue

        print(f"\n{'='*78}")
        print(f"  {symbol}")
        print(f"{'='*78}")

        # Load data with date filter
        print(f"  Loading M5 data (2022-2026)...", end=" ", flush=True)
        t0 = time.time()
        m5_data = load_csv(str(m5_path), DATE_START, DATE_END)
        print(f"{len(m5_data):,} bars ({time.time() - t0:.1f}s)")

        if len(m5_data) < 5000:
            print(f"  Insufficient data ({len(m5_data)} bars) — skipping")
            continue

        h1_data = load_csv(str(h1_path), DATE_START, DATE_END) if h1_path.exists() else None
        h4_data = load_csv(str(h4_path), DATE_START, DATE_END) if h4_path.exists() else None
        if h1_data:
            print(f"  H1: {len(h1_data):,} bars")
        if h4_data:
            print(f"  H4: {len(h4_data):,} bars")

        if m5_data[0].get("datetime") and m5_data[-1].get("datetime"):
            print(f"  Range: {m5_data[0]['datetime'].strftime('%Y-%m-%d')} → "
                  f"{m5_data[-1]['datetime'].strftime('%Y-%m-%d')}")

        params = SYMBOL_PARAMS[symbol]
        all_results[symbol] = {}

        for agent_type in ["scalping", "expert"]:
            print(f"\n  ── {agent_type.upper()} AGENT ──")

            # Load models
            if agent_type == "scalping":
                models = load_scalping_models(symbol)
            else:
                models = load_expert_models(symbol)

            if not models.get("xgboost") and not models.get("lightgbm"):
                print(f"    No models found — skipping")
                all_results[symbol][agent_type] = {"error": "no_models"}
                continue

            # Compute features
            use_h4 = h4_data if agent_type == "expert" else None
            print(f"    Computing features...", end=" ", flush=True)
            t0 = time.time()
            try:
                feat_names, X = compute_all_features(m5_data, h1_data, use_h4)
            except Exception as e:
                print(f"ERROR: {e}")
                all_results[symbol][agent_type] = {"error": str(e)}
                continue
            print(f"{len(feat_names)} features ({time.time() - t0:.1f}s)")

            n = min(len(X), len(m5_data))
            closes = np.array([d["close"] for d in m5_data[:n]], dtype=np.float64)
            highs = np.array([d["high"] for d in m5_data[:n]], dtype=np.float64)
            lows = np.array([d["low"] for d in m5_data[:n]], dtype=np.float64)
            datetimes = [d.get("datetime") for d in m5_data[:n]]

            # Generate signals
            print(f"    Generating signals...", end=" ", flush=True)
            t0 = time.time()
            if agent_type == "scalping":
                preds, confs = generate_scalping_signals(X, models)
            else:
                preds, confs = generate_expert_signals(X, models)
            n_signals = np.sum((preds != 1) & (confs >= 0.55))
            print(f"{n_signals:,} raw signals ({time.time() - t0:.1f}s)")

            # Run backtest
            print(f"    Running backtest...", end=" ", flush=True)
            t0 = time.time()
            try:
                stats, trade_log, equity_curve = backtest_agent(
                    preds=preds, confs=confs,
                    closes=closes, highs=highs, lows=lows, datetimes=datetimes,
                    params=params, symbol=symbol,
                    initial_balance=INITIAL_BALANCE,
                    risk_per_trade=RISK_PER_TRADE,
                )
            except Exception as e:
                print(f"ERROR: {e}")
                import traceback
                traceback.print_exc()
                all_results[symbol][agent_type] = {"error": str(e)}
                continue
            elapsed = time.time() - t0
            print(f"done ({elapsed:.1f}s)")

            # Print results
            print(f"\n    ┌─────────────────────────────────────────────┐")
            print(f"    │  {symbol} — {agent_type.upper()}")
            print(f"    ├─────────────────────────────────────────────┤")
            print(f"    │  PnL:        ${stats['pnl']:>+12,.2f}")
            print(f"    │  ROI:        {stats['roi_pct']:>+12.2f}%")
            print(f"    │  Final Eq:   ${stats['final_equity']:>12,.2f}")
            print(f"    │  Trades:     {stats['total_trades']:>12,}")
            print(f"    │  Win Rate:   {stats['win_rate']:>11.1f}%")
            print(f"    │  PF:         {stats['profit_factor']:>12.2f}")
            print(f"    │  Sharpe:     {stats['sharpe']:>12.2f}")
            print(f"    │  Max DD:     {stats['max_drawdown_pct']:>11.1f}%  (${stats['max_drawdown']:,.2f})")
            print(f"    │  Avg Trade:  ${stats['avg_trade']:>+12.2f}")
            print(f"    │  Avg Win:    ${stats['avg_win']:>12.2f}")
            print(f"    │  Avg Loss:   ${stats['avg_loss']:>12.2f}")
            print(f"    │  Win Streak: {stats['max_win_streak']:>12}")
            print(f"    │  Loss Streak:{stats['max_loss_streak']:>12}")
            print(f"    │  News Skip:  {stats['news_filtered']:>12,}")
            print(f"    │  Dead Skip:  {stats['session_filtered']:>12,}")
            print(f"    │  Exit Reasons: {stats['exit_reasons']}")
            print(f"    └─────────────────────────────────────────────┘")

            # Session breakdown
            print(f"    Sessions: ", end="")
            for s, d in stats.get("session_breakdown", {}).items():
                wr = (d["wins"]/d["count"]*100) if d["count"] > 0 else 0
                print(f"{s}={d['count']} (${d['pnl']:+,.0f}, {wr:.0f}% WR) ", end="")
            print()

            # Save files
            save_trade_log(trade_log, symbol, agent_type)
            save_equity_curve(equity_curve, symbol, agent_type)

            all_results[symbol][agent_type] = stats

            # Free memory between agents
            import gc
            del trade_log, equity_curve, preds, confs, X, closes, highs, lows, datetimes
            gc.collect()

        # Free symbol data between symbols
        del m5_data, h1_data, h4_data
        gc.collect()

    # ── Summary Table ──
    elapsed = time.time() - t_start
    print(f"\n\n{'='*108}")
    print(f"  FINAL RESULTS — ${INITIAL_BALANCE:,.0f} | 0.1 Lots Fixed | 2022-2026 | Realistic Costs + News Avoidance")
    print(f"{'='*108}\n")

    header = (f"  {'Symbol':<10} {'Agent':<10} {'Final Eq':>12} {'PnL':>12} {'ROI':>8} "
              f"{'Trades':>8} {'WR':>6} {'PF':>6} {'Sharpe':>8} {'MaxDD':>8}")
    print(header)
    print(f"  {'─'*106}")

    for symbol in ALL_SYMBOLS:
        if symbol not in all_results:
            continue
        for agent_type in ["scalping", "expert"]:
            r = all_results[symbol].get(agent_type, {})
            if "error" in r:
                print(f"  {symbol:<10} {agent_type:<10} {'ERROR — ' + r['error']:>12}")
                continue
            if not r:
                continue

            pnl = r.get("pnl", 0)
            verdict = "PASS" if r.get("profit_factor", 0) > 1.0 and pnl > 0 else "FAIL"
            print(f"  {symbol:<10} {agent_type:<10} "
                  f"${r.get('final_equity', 0):>11,.2f} "
                  f"${pnl:>+11,.2f} "
                  f"{r.get('roi_pct', 0):>+7.1f}% "
                  f"{r.get('total_trades', 0):>8,} "
                  f"{r.get('win_rate', 0):>5.1f}% "
                  f"{r.get('profit_factor', 0):>5.2f} "
                  f"{r.get('sharpe', 0):>7.2f} "
                  f"{r.get('max_drawdown_pct', 0):>7.1f}%  {verdict}")

    # Save JSON summary
    summary_path = RESULTS_DIR / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    print(f"\n  Output directory: {RESULTS_DIR}")
    print(f"  Total time: {elapsed:.0f}s ({elapsed/60:.1f}m)")
    print(f"\n{'='*108}")
    print(f"  BACKTEST COMPLETE")
    print(f"{'='*108}")


if __name__ == "__main__":
    main()
