"""
Walk-Forward Backtest — All 4 Scalping Models on Databento Data
================================================================
$10K starting balance | Dynamic position sizing | Realistic costs

Models:
  1. XAUUSD XGBoost   (scalping_XAUUSD_M5_xgboost.joblib)
  2. XAUUSD LightGBM  (scalping_XAUUSD_M5_lightgbm.joblib)
  3. US30 XGBoost      (scalping_US30_M5_xgboost.joblib)
  4. US30 LightGBM     (scalping_US30_M5_lightgbm.joblib)

Walk-forward: 5-fold expanding window on FULL Databento dataset.
Dynamic sizing: risk 1% of current equity per trade, sized via ATR-based SL.

Usage:
    python run_wf_backtest_10k.py
    python run_wf_backtest_10k.py --symbols XAUUSD
"""

import csv
import json
import math
import os
import sys
import time
import warnings
import numpy as np
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Configuration ──────────────────────────────────────

INITIAL_BALANCE = 10_000.0
RISK_PER_TRADE_PCT = 1.0   # 1% of equity risked per trade
MAX_RISK_PCT = 2.0          # hard cap on single-trade risk
MIN_LOT = 0.01
MAX_LOT = 5.0

DATA_DIR = Path(__file__).parent / "data" / "databento"
MODEL_DIR = Path(__file__).parent / "data" / "ml_models"
RESULTS_DIR = Path(__file__).parent / "data" / "scalping_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

N_WF_FOLDS = 5
CONFIDENCE_THRESHOLD = 0.55

SYMBOL_PARAMS = {
    "XAUUSD": {
        "commission_per_lot": 0.30,
        "spread_points": 0.30,
        "point_value": 100.0,       # $100 per 1.0 move per standard lot
        "atr_sl_mult": 1.5,
        "atr_tp_mult": 2.5,
        "max_holding_bars": 12,
        "contract_size": 100,       # 100 oz per lot
    },
    "US30": {
        "commission_per_lot": 1.0,
        "spread_points": 2.0,
        "point_value": 1.0,
        "atr_sl_mult": 1.5,
        "atr_tp_mult": 2.0,
        "max_holding_bars": 12,
        "contract_size": 1,
    },
}


# ── Data Loading ───────────────────────────────────────

def load_csv(path: str) -> list[dict]:
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
            except (ValueError, TypeError):
                continue
    return data


def compute_features_for_data(m5_data, h1_data):
    from app.services.ml.features_mtf import compute_expert_features
    feature_names, feature_matrix = compute_expert_features(m5_data, h1_data, None, None)
    return feature_names, np.array(feature_matrix, dtype=np.float64)


def compute_targets(m5_data, params):
    from app.services.ml.features import compute_targets as ct
    closes = [d["close"] for d in m5_data]
    highs = [d["high"] for d in m5_data]
    lows = [d["low"] for d in m5_data]
    target_config = {
        "type": "triple_barrier",
        "horizon": params["max_holding_bars"],
        "sl_atr_mult": params["atr_sl_mult"],
        "tp_atr_mult": params["atr_tp_mult"],
        "max_holding_bars": params["max_holding_bars"],
    }
    _, values = ct(closes, target_config, highs, lows)
    return np.array(values, dtype=np.float64)


def clean_xy(X, y):
    valid = np.isfinite(y)
    if X.ndim == 2:
        valid &= np.all(np.isfinite(X), axis=1)
    return X[valid], y[valid], valid


def map_targets_to_classes(y):
    unique = np.unique(y[np.isfinite(y)])
    label_map = {v: i for i, v in enumerate(sorted(unique))}
    return np.array([label_map.get(v, 1) for v in y], dtype=np.int64), label_map


# ── Dynamic Position Sizing ───────────────────────────

def compute_lot_size(equity, atr, sl_mult, point_value, risk_pct=RISK_PER_TRADE_PCT):
    """
    Kelly-inspired dynamic sizing: risk X% of equity per trade.

    lot_size = (equity * risk%) / (ATR * sl_mult * point_value)
    """
    risk_amount = equity * (risk_pct / 100.0)
    sl_distance_dollars = atr * sl_mult * point_value

    if sl_distance_dollars <= 0:
        return MIN_LOT

    lots = risk_amount / sl_distance_dollars
    lots = max(MIN_LOT, min(MAX_LOT, round(lots, 2)))
    return lots


# ── Walk-Forward Backtest Engine ──────────────────────

def walk_forward_backtest(
    model_path: str,
    X: np.ndarray,
    y: np.ndarray,
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    timestamps: list,
    symbol: str,
    params: dict,
    n_folds: int = N_WF_FOLDS,
) -> dict:
    """
    Walk-forward backtest with $10K equity tracking and dynamic sizing.

    Uses expanding window: train on all data up to fold boundary,
    predict on the next chunk. Track dollar equity throughout.
    """
    import joblib

    saved = joblib.load(model_path)
    model_type = saved["model_type"]
    feature_names = saved["feature_names"]

    n = len(X)
    fold_size = n // (n_folds + 1)

    pv = params["point_value"]
    spread = params["spread_points"]
    commission = params["commission_per_lot"]
    sl_mult = params["atr_sl_mult"]
    tp_mult = params["atr_tp_mult"]
    max_bars = params["max_holding_bars"]

    # Precompute ATR(14) on full dataset
    atr = np.full(n, np.nan)
    for i in range(14, n):
        tr_vals = []
        for j in range(i - 13, i + 1):
            tr = max(
                highs[j] - lows[j],
                abs(highs[j] - closes[j - 1]) if j > 0 else highs[j] - lows[j],
                abs(lows[j] - closes[j - 1]) if j > 0 else highs[j] - lows[j],
            )
            tr_vals.append(tr)
        atr[i] = np.mean(tr_vals)

    print(f"\n{'='*70}")
    print(f"  Walk-Forward Backtest: {symbol} {model_type.upper()}")
    print(f"  Balance: ${INITIAL_BALANCE:,.0f} | Risk/trade: {RISK_PER_TRADE_PCT}%")
    print(f"  Samples: {n:,} | Folds: {n_folds} | Fold size: {fold_size:,}")
    print(f"{'='*70}")

    # Equity tracking
    equity = INITIAL_BALANCE
    peak_equity = INITIAL_BALANCE
    max_dd = 0.0
    max_dd_pct = 0.0

    all_trades = []
    equity_curve = [INITIAL_BALANCE]
    fold_results = []
    monthly_pnl = {}

    for fold in range(n_folds):
        train_end = fold_size * (fold + 2)
        val_start = train_end
        val_end = min(val_start + fold_size, n)

        if val_end <= val_start + 100:
            print(f"\n  Fold {fold+1}: skipped (insufficient data)")
            continue

        X_train, y_train = X[:train_end], y[:train_end]
        X_val = X[val_start:val_end]

        print(f"\n  Fold {fold+1}/{n_folds}: train[0:{train_end:,}] → test[{val_start:,}:{val_end:,}]")

        # Retrain model on expanding window
        t0 = time.time()
        if model_type == "xgboost":
            from xgboost import XGBClassifier
            model = XGBClassifier(
                **saved["best_params"],
                use_label_encoder=False,
                eval_metric="mlogloss",
                random_state=42,
                n_jobs=-1,
            )
        else:
            from lightgbm import LGBMClassifier
            model = LGBMClassifier(
                **saved["best_params"],
                random_state=42,
                n_jobs=-1,
                verbose=-1,
            )

        model.fit(X_train, y_train)
        train_time = time.time() - t0

        # Predict on OOS fold
        pred = model.predict(X_val)
        proba = model.predict_proba(X_val)
        conf = np.max(proba, axis=1)

        # --- Simulate trades on this fold with dynamic sizing ---
        fold_trades = []
        fold_equity_start = equity
        i = 0

        while i < len(pred) - 1:
            global_idx = val_start + i
            p = pred[i]
            c = conf[i]

            # Only trade directional signals with high confidence
            if p == 1 or c < CONFIDENCE_THRESHOLD or np.isnan(atr[global_idx]):
                i += 1
                continue

            direction = 1 if p == 2 else -1
            entry_price = closes[global_idx]
            current_atr = atr[global_idx]
            sl_dist = current_atr * sl_mult
            tp_dist = current_atr * tp_mult

            # Dynamic lot sizing
            lot_size = compute_lot_size(equity, current_atr, sl_mult, pv)

            if direction == 1:
                sl_price = entry_price - sl_dist
                tp_price = entry_price + tp_dist
            else:
                sl_price = entry_price + sl_dist
                tp_price = entry_price - tp_dist

            # Simulate forward bar-by-bar
            exit_price = None
            exit_bar_local = None
            exit_reason = None

            for j in range(i + 1, min(i + max_bars + 1, len(pred))):
                gj = val_start + j
                if gj >= n:
                    break

                if direction == 1:
                    if lows[gj] <= sl_price:
                        exit_price = sl_price
                        exit_reason = "SL"
                        exit_bar_local = j
                        break
                    if highs[gj] >= tp_price:
                        exit_price = tp_price
                        exit_reason = "TP"
                        exit_bar_local = j
                        break
                else:
                    if highs[gj] >= sl_price:
                        exit_price = sl_price
                        exit_reason = "SL"
                        exit_bar_local = j
                        break
                    if lows[gj] <= tp_price:
                        exit_price = tp_price
                        exit_reason = "TP"
                        exit_bar_local = j
                        break

            if exit_price is None:
                exit_bar_local = min(i + max_bars, len(pred) - 1)
                gj = val_start + exit_bar_local
                if gj < n:
                    exit_price = closes[gj]
                else:
                    exit_price = entry_price
                exit_reason = "TIME"

            # PnL calculation
            pnl_points = (exit_price - entry_price) * direction
            spread_cost = spread * lot_size  # spread in price points * lots
            commission_cost = 2 * commission * lot_size  # RT commission
            net_pnl_dollar = (pnl_points * pv * lot_size) - spread_cost - commission_cost

            # Update equity
            equity += net_pnl_dollar
            equity_curve.append(equity)

            # Track drawdown
            if equity > peak_equity:
                peak_equity = equity
            dd = peak_equity - equity
            dd_pct = (dd / peak_equity * 100) if peak_equity > 0 else 0
            if dd > max_dd:
                max_dd = dd
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

            # Get timestamp for monthly tracking
            ts = timestamps[global_idx] if global_idx < len(timestamps) and timestamps[global_idx] else None
            month_key = ts.strftime("%Y-%m") if ts else "unknown"
            monthly_pnl[month_key] = monthly_pnl.get(month_key, 0) + net_pnl_dollar

            trade_rec = {
                "fold": fold + 1,
                "entry_bar": global_idx,
                "exit_bar": val_start + exit_bar_local if exit_bar_local else global_idx,
                "direction": "LONG" if direction == 1 else "SHORT",
                "entry_price": round(entry_price, 2),
                "exit_price": round(exit_price, 2),
                "sl": round(sl_price, 2),
                "tp": round(tp_price, 2),
                "lot_size": lot_size,
                "pnl_points": round(pnl_points, 4),
                "net_pnl": round(net_pnl_dollar, 2),
                "equity_after": round(equity, 2),
                "exit_reason": exit_reason,
                "confidence": round(c, 4),
                "atr": round(current_atr, 4),
                "month": month_key,
            }
            fold_trades.append(trade_rec)
            all_trades.append(trade_rec)

            # Skip ahead past exit bar to avoid overlapping trades
            i = exit_bar_local + 1 if exit_bar_local else i + 1
            continue

        # Fold summary
        fold_pnl = equity - fold_equity_start
        fold_wins = len([t for t in fold_trades if t["net_pnl"] > 0])
        fold_losses = len([t for t in fold_trades if t["net_pnl"] <= 0])
        fold_wr = fold_wins / len(fold_trades) * 100 if fold_trades else 0
        fold_gross_p = sum(t["net_pnl"] for t in fold_trades if t["net_pnl"] > 0)
        fold_gross_l = abs(sum(t["net_pnl"] for t in fold_trades if t["net_pnl"] <= 0))
        fold_pf = fold_gross_p / fold_gross_l if fold_gross_l > 0 else 999

        avg_lot = np.mean([t["lot_size"] for t in fold_trades]) if fold_trades else 0

        fold_res = {
            "fold": fold + 1,
            "trades": len(fold_trades),
            "wins": fold_wins,
            "losses": fold_losses,
            "win_rate": round(fold_wr, 2),
            "profit_factor": round(fold_pf, 2),
            "net_pnl": round(fold_pnl, 2),
            "equity_end": round(equity, 2),
            "avg_lot_size": round(avg_lot, 3),
            "train_time": round(train_time, 1),
        }
        fold_results.append(fold_res)

        print(f"    Trained in {train_time:.1f}s | {len(fold_trades)} trades")
        print(f"    WR={fold_wr:.1f}% | PF={fold_pf:.2f} | P&L=${fold_pnl:+,.2f} | Equity=${equity:,.2f} | AvgLot={avg_lot:.3f}")

    # ── Aggregate Stats ────────────────────────────────
    total_trades = len(all_trades)
    if total_trades == 0:
        return {"error": "No trades generated"}

    wins = [t for t in all_trades if t["net_pnl"] > 0]
    losses = [t for t in all_trades if t["net_pnl"] <= 0]
    pnls = [t["net_pnl"] for t in all_trades]

    total_win_pnl = sum(t["net_pnl"] for t in wins)
    total_loss_pnl = abs(sum(t["net_pnl"] for t in losses))
    net_profit = equity - INITIAL_BALANCE
    roi_pct = (net_profit / INITIAL_BALANCE) * 100

    profit_factor = total_win_pnl / total_loss_pnl if total_loss_pnl > 0 else 999
    win_rate = len(wins) / total_trades * 100

    pnl_arr = np.array(pnls)
    avg_pnl = np.mean(pnl_arr)
    std_pnl = np.std(pnl_arr, ddof=1) if len(pnl_arr) > 1 else 1.0
    sharpe = (avg_pnl / std_pnl) * np.sqrt(252) if std_pnl > 1e-10 else 0

    avg_win = total_win_pnl / len(wins) if wins else 0
    avg_loss = -total_loss_pnl / len(losses) if losses else 0
    largest_win = max(pnls) if pnls else 0
    largest_loss = min(pnls) if pnls else 0
    expectancy = avg_pnl

    # Calmar ratio (annualized return / max DD)
    calmar = 0
    if max_dd_pct > 0:
        calmar = roi_pct / max_dd_pct

    # Consecutive wins/losses
    consec_w = consec_l = max_consec_w = max_consec_l = 0
    for t in all_trades:
        if t["net_pnl"] > 0:
            consec_w += 1
            consec_l = 0
            max_consec_w = max(max_consec_w, consec_w)
        else:
            consec_l += 1
            consec_w = 0
            max_consec_l = max(max_consec_l, consec_l)

    # Yearly breakdown
    yearly_pnl = {}
    for t in all_trades:
        year = t["month"][:4] if t["month"] != "unknown" else "unknown"
        yearly_pnl[year] = yearly_pnl.get(year, 0) + t["net_pnl"]

    # Grade
    grade = grade_result(profit_factor, win_rate, max_dd_pct, sharpe, total_trades, net_profit)

    result = {
        "symbol": symbol,
        "model_type": model_type,
        "grade": grade,
        "initial_balance": INITIAL_BALANCE,
        "final_equity": round(equity, 2),
        "net_profit": round(net_profit, 2),
        "roi_pct": round(roi_pct, 2),
        "total_trades": total_trades,
        "winners": len(wins),
        "losers": len(losses),
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2),
        "sharpe": round(sharpe, 2),
        "calmar": round(calmar, 2),
        "max_dd_usd": round(max_dd, 2),
        "max_dd_pct": round(max_dd_pct, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "largest_win": round(largest_win, 2),
        "largest_loss": round(largest_loss, 2),
        "expectancy": round(expectancy, 2),
        "max_consec_wins": max_consec_w,
        "max_consec_losses": max_consec_l,
        "avg_lot_size": round(np.mean([t["lot_size"] for t in all_trades]), 3),
        "risk_per_trade": f"{RISK_PER_TRADE_PCT}%",
        "folds": fold_results,
        "yearly_pnl": {k: round(v, 2) for k, v in sorted(yearly_pnl.items())},
        "equity_curve_len": len(equity_curve),
        "equity_start": equity_curve[0],
        "equity_end": equity_curve[-1],
    }

    return result


def grade_result(pf, wr, dd_pct, sharpe, trades, net):
    score = 0
    if pf >= 2.0: score += 3
    elif pf >= 1.5: score += 2
    elif pf >= 1.1: score += 1

    if wr >= 55: score += 2
    elif wr >= 45: score += 1

    if dd_pct <= 10: score += 3
    elif dd_pct <= 20: score += 2
    elif dd_pct <= 30: score += 1

    if sharpe >= 2.0: score += 3
    elif sharpe >= 1.0: score += 2
    elif sharpe >= 0.5: score += 1

    if trades >= 500: score += 2
    elif trades >= 100: score += 1

    if net > 0: score += 1

    if score >= 12: return "A+"
    if score >= 10: return "A"
    if score >= 8:  return "B"
    if score >= 6:  return "C"
    if score >= 4:  return "D"
    return "F"


# ── Main ─────────────────────────────────────────────

def run_symbol(symbol: str):
    """Run backtest for both models of a symbol."""
    params = SYMBOL_PARAMS[symbol]

    m5_path = DATA_DIR / f"{symbol}_M5.csv"
    h1_path = DATA_DIR / f"{symbol}_H1.csv"

    if not m5_path.exists():
        print(f"  ERROR: {m5_path} not found")
        return []

    print(f"\n  Loading {symbol} Databento data...")
    m5_data = load_csv(str(m5_path))
    h1_data = load_csv(str(h1_path)) if h1_path.exists() else None

    # Use full dataset for proper walk-forward
    MAX_BARS = 200_000  # ~3.4 years of M5
    if len(m5_data) > MAX_BARS:
        m5_data = m5_data[-MAX_BARS:]
    if h1_data and len(h1_data) > MAX_BARS // 12:
        h1_data = h1_data[-(MAX_BARS // 12):]

    print(f"  M5: {len(m5_data):,} bars | H1: {len(h1_data):,} bars" if h1_data else f"  M5: {len(m5_data):,} bars")

    # Compute features
    print("  Computing features...", end="", flush=True)
    t0 = time.time()
    feature_names, X = compute_features_for_data(m5_data, h1_data)
    print(f" {len(feature_names)} features in {time.time()-t0:.1f}s")

    # Compute targets
    print("  Computing triple-barrier targets...", end="", flush=True)
    t0 = time.time()
    y_raw = compute_targets(m5_data, params)
    print(f" done in {time.time()-t0:.1f}s")

    # Clean
    X_clean, y_clean, valid_mask = clean_xy(X, y_raw)
    y_classes, label_map = map_targets_to_classes(y_clean)
    print(f"  Clean samples: {len(X_clean):,}")

    # Price arrays aligned to clean data
    closes_all = np.array([d["close"] for d in m5_data], dtype=np.float64)
    highs_all = np.array([d["high"] for d in m5_data], dtype=np.float64)
    lows_all = np.array([d["low"] for d in m5_data], dtype=np.float64)
    timestamps_all = [d.get("datetime") for d in m5_data]

    closes = closes_all[valid_mask]
    highs = highs_all[valid_mask]
    lows = lows_all[valid_mask]
    timestamps = [timestamps_all[i] for i in range(len(timestamps_all)) if valid_mask[i]]

    results = []

    for model_type in ["xgboost", "lightgbm"]:
        model_path = MODEL_DIR / f"scalping_{symbol}_M5_{model_type}.joblib"
        if not model_path.exists():
            print(f"  Model not found: {model_path}")
            continue

        result = walk_forward_backtest(
            str(model_path), X_clean, y_classes,
            closes, highs, lows, timestamps,
            symbol, params,
        )
        results.append(result)

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=["XAUUSD", "US30"])
    args = parser.parse_args()

    print()
    print("#" * 72)
    print("  TRADEFORGE — WALK-FORWARD BACKTEST ($10K | DYNAMIC SIZING)")
    print("  Data: Databento CME Futures | Models: Optuna-tuned Scalping")
    print("#" * 72)
    print(f"  Starting Balance:  ${INITIAL_BALANCE:,.0f}")
    print(f"  Risk per trade:    {RISK_PER_TRADE_PCT}% of equity")
    print(f"  Walk-Forward:      {N_WF_FOLDS} folds, expanding window")
    print(f"  Confidence cutoff: {CONFIDENCE_THRESHOLD}")
    print(f"  Data source:       {DATA_DIR}")
    print()

    all_results = []

    for symbol in args.symbols:
        if symbol not in SYMBOL_PARAMS:
            print(f"  Unknown symbol: {symbol}")
            continue

        print(f"\n{'#'*72}")
        print(f"  {symbol}")
        print(f"{'#'*72}")

        results = run_symbol(symbol)
        all_results.extend(results)

    # ── Final Summary Table ─────────────────────────────
    print(f"\n\n{'='*120}")
    print("  FINAL RESULTS — $10K Walk-Forward Backtest with Dynamic Sizing")
    print(f"{'='*120}")
    print(f"{'Model':<28} {'Grade':>5} {'Trades':>7} {'WR%':>6} {'PF':>6} "
          f"{'Net P&L':>12} {'ROI%':>8} {'MaxDD%':>7} {'Sharpe':>7} {'Calmar':>7} "
          f"{'AvgWin':>8} {'AvgLoss':>8} {'AvgLot':>7}")
    print("-" * 120)

    for r in all_results:
        if "error" in r:
            print(f"  {r.get('symbol','?')} {r.get('model_type','?')}: {r['error']}")
            continue

        label = f"{r['symbol']} {r['model_type'].upper()}"
        print(f"[{r['grade']:>2}] {label:<24} {r['total_trades']:>7} {r['win_rate']:>5.1f}% "
              f"{r['profit_factor']:>6.2f} ${r['net_profit']:>+10,.2f} {r['roi_pct']:>+7.1f}% "
              f"{r['max_dd_pct']:>6.1f}% {r['sharpe']:>7.2f} {r['calmar']:>7.2f} "
              f"${r['avg_win']:>7.2f} ${r['avg_loss']:>7.2f} {r['avg_lot_size']:>7.3f}")

    # ── Per-Fold Breakdown ──────────────────────────────
    print(f"\n{'='*100}")
    print("  PER-FOLD BREAKDOWN")
    print(f"{'='*100}")
    for r in all_results:
        if "error" in r:
            continue
        print(f"\n  {r['symbol']} {r['model_type'].upper()}:")
        for f in r.get("folds", []):
            print(f"    Fold {f['fold']}: {f['trades']:>5} trades | WR={f['win_rate']:>5.1f}% | "
                  f"PF={f['profit_factor']:>5.2f} | P&L=${f['net_pnl']:>+10,.2f} | "
                  f"Equity=${f['equity_end']:>12,.2f} | AvgLot={f['avg_lot_size']:.3f}")

    # ── Yearly PnL ──────────────────────────────────────
    print(f"\n{'='*100}")
    print("  YEARLY P&L BREAKDOWN")
    print(f"{'='*100}")
    for r in all_results:
        if "error" in r:
            continue
        print(f"\n  {r['symbol']} {r['model_type'].upper()}:")
        yearly = r.get("yearly_pnl", {})
        for year, pnl in sorted(yearly.items()):
            bar = "+" * int(min(pnl / 100, 50)) if pnl > 0 else "-" * int(min(abs(pnl) / 100, 50))
            print(f"    {year}: ${pnl:>+10,.2f}  {bar}")

    # ── Risk Analysis ───────────────────────────────────
    print(f"\n{'='*100}")
    print("  RISK ANALYSIS")
    print(f"{'='*100}")
    for r in all_results:
        if "error" in r:
            continue
        print(f"\n  {r['symbol']} {r['model_type'].upper()}:")
        print(f"    Max Drawdown:       ${r['max_dd_usd']:>10,.2f} ({r['max_dd_pct']:.1f}%)")
        print(f"    Max Consec Wins:    {r['max_consec_wins']}")
        print(f"    Max Consec Losses:  {r['max_consec_losses']}")
        print(f"    Expectancy/trade:   ${r['expectancy']:>+.2f}")
        print(f"    Largest Win:        ${r['largest_win']:>+,.2f}")
        print(f"    Largest Loss:       ${r['largest_loss']:>+,.2f}")

    # ── Save Results ────────────────────────────────────
    output_path = RESULTS_DIR / "wf_backtest_10k_results.json"
    save_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "initial_balance": INITIAL_BALANCE,
            "risk_per_trade_pct": RISK_PER_TRADE_PCT,
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "n_folds": N_WF_FOLDS,
            "data_source": "Databento CME Futures",
        },
        "results": [r for r in all_results if "error" not in r],
    }
    with open(output_path, "w") as f:
        json.dump(save_data, f, indent=2, default=str)
    print(f"\n  Results saved: {output_path}")

    print(f"\n{'#'*72}")
    print("  BACKTEST COMPLETE")
    print(f"{'#'*72}")


if __name__ == "__main__":
    main()
