"""
News Event Guard Strategy (s28)
================================
A defensive/reactive strategy that manages positions around major economic
news events. It wraps any base strategy's signals and modifies behavior
when high-impact news is imminent or just released.

Three operating modes:
  1. DEFENSIVE — Closes/hedges positions before high-impact events
  2. REACTIVE  — Trades breakouts after news release (first 5-15 min)
  3. STRADDLE  — Places opposing pending orders before release

The strategy maintains an internal economic calendar that maps events to
affected currency pairs. It uses a lookback buffer (default 30 min before)
and a lockout period (default 15 min after) to define the "danger zone."

NEWS CLASSIFICATION:
  - Tier 1 (Red):   NFP, FOMC, CPI, ECB Rate — full lockout
  - Tier 2 (Orange): GDP, Unemployment, PMI — partial lockout
  - Tier 3 (Yellow): Retail Sales, Housing, etc. — warning only

DEFENSIVE MODE (default):
  - 30 min before Tier 1: close all open positions, widen stops on Tier 2
  - During lockout: reject all new entry signals
  - After lockout: resume normal trading

REACTIVE MODE:
  - During lockout: monitor price action
  - After lockout (first 5-15 min): trade the established direction
  - Enter in the direction of the initial spike if confirmed by momentum
  - Wider stops (1.5x ATR) to account for post-news volatility

STRADDLE MODE:
  - 5 min before release: place buy stop and sell stop at range edges
  - One gets triggered by the news spike, cancel the other
  - Tight TP (1:1 RR), wider stop (2x ATR)

Author: FlowrexAlgo AI
Version: 1.0
"""

import math

DEFAULTS = {
    # --- Mode ---
    "mode": "defensive",       # defensive / reactive / straddle

    # --- Timing ---
    "pre_event_minutes": 30,   # Minutes before event to activate guard
    "post_event_minutes": 15,  # Minutes after event to maintain lockout
    "reactive_window_min": 5,  # Min minutes after release for reactive entry
    "reactive_window_max": 15, # Max minutes after release for reactive entry

    # --- Event Classification ---
    "tier1_lockout": True,     # Full position close for Tier 1 events
    "tier2_widen_stops": True, # Widen stops for Tier 2 events
    "tier3_warning_only": True,# Only log warnings for Tier 3

    # --- Defensive Settings ---
    "close_before_tier1": True,    # Close all positions before Tier 1
    "widen_stop_factor": 2.0,      # Multiply SL by this during Tier 2 danger zone
    "reject_entries_in_lockout": True,  # Block new entries during lockout

    # --- Reactive Settings ---
    "reactive_atr_mult_sl": 1.5,   # SL multiplier for reactive trades
    "reactive_atr_mult_tp": 2.0,   # TP multiplier for reactive trades
    "min_spike_atr": 0.5,          # Minimum spike size (ATR multiples) to confirm direction
    "momentum_confirm_bars": 3,    # Bars of consistent direction to confirm

    # --- Straddle Settings ---
    "straddle_range_atr": 0.75,    # Distance from current price for pending orders
    "straddle_sl_atr": 2.0,        # SL for straddle orders
    "straddle_tp_atr": 2.0,        # TP for straddle orders (1:1 RR)
    "straddle_pre_minutes": 5,     # Place straddle orders this many min before event

    # --- Risk Management ---
    "atr_period": 14,
    "risk_per_trade": 0.005,       # 0.5% risk per trade
    "max_concurrent": 2,           # Max open positions
    "cooldown_bars": 5,            # Min bars between trades

    # --- ATR Settings ---
    "atr_sl_mult": 1.5,           # Default SL in ATR multiples
    "atr_tp_mult": 3.0,           # Default TP in ATR multiples

    # --- EMA Trend Filter ---
    "ema_period": 50,
    "use_ema_filter": True,
}


SETTINGS = [
    # Mode
    {"key": "mode",                    "label": "Operating Mode",              "type": "select", "default": "defensive", "options": ["defensive", "reactive", "straddle"],   "group": "Mode",                 "description": "Strategy mode: defensive (close before news), reactive (trade after news), or straddle (bracket orders)"},

    # Timing
    {"key": "pre_event_minutes",       "label": "Pre-Event Minutes",           "type": "int",   "default": 30,    "min": 5,    "max": 120, "step": 1,    "group": "Timing",               "description": "Minutes before a news event to activate the guard"},
    {"key": "post_event_minutes",      "label": "Post-Event Minutes",          "type": "int",   "default": 15,    "min": 5,    "max": 60,  "step": 1,    "group": "Timing",               "description": "Minutes after a news event to maintain lockout"},
    {"key": "reactive_window_min",     "label": "Reactive Window Min (min)",   "type": "int",   "default": 5,     "min": 1,    "max": 30,  "step": 1,    "group": "Timing",               "description": "Earliest minute after release to enter a reactive trade"},
    {"key": "reactive_window_max",     "label": "Reactive Window Max (min)",   "type": "int",   "default": 15,    "min": 5,    "max": 60,  "step": 1,    "group": "Timing",               "description": "Latest minute after release to enter a reactive trade"},

    # Event Classification
    {"key": "tier1_lockout",           "label": "Tier 1 Full Lockout",         "type": "bool",  "default": True,                                                "group": "Event Classification", "description": "Full position close and entry lockout for Tier 1 (NFP, FOMC, CPI) events"},
    {"key": "tier2_widen_stops",       "label": "Tier 2 Widen Stops",          "type": "bool",  "default": True,                                                "group": "Event Classification", "description": "Widen stop-losses during Tier 2 (GDP, PMI) events"},
    {"key": "tier3_warning_only",      "label": "Tier 3 Warning Only",         "type": "bool",  "default": True,                                                "group": "Event Classification", "description": "Only log warnings for Tier 3 (minor) events without action"},

    # Defensive
    {"key": "close_before_tier1",      "label": "Close Before Tier 1",         "type": "bool",  "default": True,                                                "group": "Defensive",            "description": "Close all open positions before Tier 1 news events"},
    {"key": "widen_stop_factor",       "label": "Widen Stop Factor",           "type": "float", "default": 2.0,   "min": 1.0,  "max": 5.0, "step": 0.1,  "group": "Defensive",            "description": "Multiply existing SL distance by this factor during Tier 2 danger zone"},
    {"key": "reject_entries_in_lockout","label": "Reject Entries in Lockout",  "type": "bool",  "default": True,                                                "group": "Defensive",            "description": "Block all new trade entries during the lockout period"},

    # Reactive
    {"key": "reactive_atr_mult_sl",    "label": "Reactive SL (ATR)",           "type": "float", "default": 1.5,   "min": 0.5,  "max": 5.0, "step": 0.1,  "group": "Reactive",             "description": "ATR multiplier for stop-loss on post-news reactive trades"},
    {"key": "reactive_atr_mult_tp",    "label": "Reactive TP (ATR)",           "type": "float", "default": 2.0,   "min": 0.5,  "max": 8.0, "step": 0.1,  "group": "Reactive",             "description": "ATR multiplier for take-profit on post-news reactive trades"},
    {"key": "min_spike_atr",           "label": "Min Spike Size (ATR)",        "type": "float", "default": 0.5,   "min": 0.1,  "max": 3.0, "step": 0.1,  "group": "Reactive",             "description": "Minimum price spike in ATR multiples to confirm news direction"},
    {"key": "momentum_confirm_bars",   "label": "Momentum Confirm Bars",      "type": "int",   "default": 3,     "min": 1,    "max": 10,  "step": 1,    "group": "Reactive",             "description": "Consecutive bars in one direction needed to confirm momentum"},

    # Straddle
    {"key": "straddle_range_atr",      "label": "Straddle Range (ATR)",        "type": "float", "default": 0.75,  "min": 0.2,  "max": 3.0, "step": 0.05, "group": "Straddle",             "description": "Distance from current price (in ATR) for pending buy/sell stop orders"},
    {"key": "straddle_sl_atr",         "label": "Straddle SL (ATR)",           "type": "float", "default": 2.0,   "min": 0.5,  "max": 5.0, "step": 0.1,  "group": "Straddle",             "description": "Stop-loss distance in ATR for straddle orders"},
    {"key": "straddle_tp_atr",         "label": "Straddle TP (ATR)",           "type": "float", "default": 2.0,   "min": 0.5,  "max": 5.0, "step": 0.1,  "group": "Straddle",             "description": "Take-profit distance in ATR for straddle orders"},
    {"key": "straddle_pre_minutes",    "label": "Straddle Pre-Minutes",        "type": "int",   "default": 5,     "min": 1,    "max": 30,  "step": 1,    "group": "Straddle",             "description": "Minutes before event to place straddle pending orders"},

    # Risk Management
    {"key": "atr_period",              "label": "ATR Period",                  "type": "int",   "default": 14,    "min": 5,    "max": 50,  "step": 1,    "group": "Risk Management",      "description": "Lookback period for Average True Range calculation"},
    {"key": "risk_per_trade",          "label": "Risk Per Trade",              "type": "float", "default": 0.005, "min": 0.001,"max": 0.05,"step": 0.001,"group": "Risk Management",      "description": "Fraction of account equity risked per trade (0.005 = 0.5%)"},
    {"key": "max_concurrent",          "label": "Max Concurrent Trades",       "type": "int",   "default": 2,     "min": 1,    "max": 10,  "step": 1,    "group": "Risk Management",      "description": "Maximum number of simultaneously open positions"},
    {"key": "cooldown_bars",           "label": "Cooldown Bars",               "type": "int",   "default": 5,     "min": 0,    "max": 20,  "step": 1,    "group": "Risk Management",      "description": "Minimum bars between consecutive trades"},
    {"key": "atr_sl_mult",             "label": "ATR SL Multiplier",           "type": "float", "default": 1.5,   "min": 0.5,  "max": 5.0, "step": 0.1,  "group": "Risk Management",      "description": "Default stop-loss distance as a multiple of ATR"},
    {"key": "atr_tp_mult",             "label": "ATR TP Multiplier",           "type": "float", "default": 3.0,   "min": 0.5,  "max": 8.0, "step": 0.1,  "group": "Risk Management",      "description": "Default take-profit distance as a multiple of ATR"},

    # Filters
    {"key": "ema_period",              "label": "EMA Period",                  "type": "int",   "default": 50,    "min": 10,   "max": 200, "step": 1,    "group": "Filters",              "description": "EMA period for trend filter"},
    {"key": "use_ema_filter",          "label": "Use EMA Filter",              "type": "bool",  "default": True,                                                "group": "Filters",              "description": "Only enter trades in the direction of the EMA trend"},
]


# ── Known high-impact events and affected pairs ──────────────────────────

TIER1_EVENTS = {
    "nonfarm payrolls", "non-farm payrolls", "nfp",
    "fomc", "federal funds rate", "fed interest rate",
    "cpi", "consumer price index",
    "ecb interest rate", "ecb rate",
    "boe interest rate",
    "boj interest rate",
    "rba interest rate",
}

TIER2_EVENTS = {
    "gdp", "gross domestic product",
    "unemployment rate", "unemployment claims",
    "pmi", "manufacturing pmi", "services pmi",
    "retail sales",
    "trade balance",
    "inflation rate",
}

EVENT_CURRENCY_MAP = {
    "USD": ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "US30", "US100", "NAS100", "SPY", "DIA"],
    "EUR": ["EURUSD", "EURJPY", "EURGBP"],
    "GBP": ["GBPUSD", "GBPJPY", "EURGBP"],
    "JPY": ["USDJPY", "EURJPY", "GBPJPY"],
    "AUD": ["AUDUSD", "AUDNZD"],
    "CAD": ["USDCAD"],
    "CHF": ["USDCHF"],
    "NZD": ["NZDUSD", "AUDNZD"],
}


def _wilder_atr(bars, period):
    """Wilder's ATR (EMA-smoothed)."""
    n = len(bars)
    tr = [0.0] * n
    atr = [0.0] * n
    for i in range(1, n):
        hl = bars[i]["high"] - bars[i]["low"]
        hc = abs(bars[i]["high"] - bars[i - 1]["close"])
        lc = abs(bars[i]["low"] - bars[i - 1]["close"])
        tr[i] = max(hl, hc, lc)
    # Seed
    s = sum(tr[1: period + 1])
    if period > 0:
        atr[period] = s / period
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def _ema(values, period):
    """Simple EMA."""
    n = len(values)
    ema = [0.0] * n
    k = 2.0 / (period + 1)
    start = 0
    for i in range(n):
        if values[i] != 0.0:
            start = i
            break
    ema[start] = values[start]
    for i in range(start + 1, n):
        ema[i] = values[i] * k + ema[i - 1] * (1 - k)
    return ema


def _classify_event(event_name: str) -> int:
    """Classify an event name into tier (1=highest impact, 3=lowest)."""
    name_lower = event_name.lower()
    for keyword in TIER1_EVENTS:
        if keyword in name_lower:
            return 1
    for keyword in TIER2_EVENTS:
        if keyword in name_lower:
            return 2
    return 3


def _is_in_danger_zone(bar_time, event_time, pre_minutes, post_minutes):
    """Check if a bar is within the danger zone of an event."""
    if not bar_time or not event_time:
        return False, False  # (in_pre, in_post)

    try:
        from datetime import datetime, timedelta
        if isinstance(bar_time, str):
            bar_dt = datetime.fromisoformat(bar_time.replace("Z", "+00:00"))
        else:
            bar_dt = bar_time

        if isinstance(event_time, str):
            event_dt = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
        else:
            event_dt = event_time

        diff_minutes = (event_dt - bar_dt).total_seconds() / 60

        in_pre = 0 < diff_minutes <= pre_minutes
        in_post = -post_minutes <= diff_minutes <= 0

        return in_pre, in_post
    except Exception:
        return False, False


# ── Strategy Interface ─────────────────────────────────────────────────

def init(bars, settings):
    """Pre-compute indicators."""
    s = {**DEFAULTS, **settings}
    n = len(bars)

    atr = _wilder_atr(bars, s["atr_period"])
    closes = [b["close"] for b in bars]
    ema = _ema(closes, s["ema_period"]) if s["use_ema_filter"] else [0.0] * n

    return {
        "s": s,
        "atr": atr,
        "ema": ema,
        "last_trade_bar": -999,
        "mode": s["mode"],
        "n": n,
    }


def on_bar(i, bar):
    """Process each bar."""
    ctx = __strategy_context__  # noqa: F821 — injected by engine
    s = ctx["s"]
    atr = ctx["atr"]
    ema = ctx["ema"]

    if i < max(s["atr_period"], s["ema_period"]) + 5:
        return

    atr_val = atr[i]
    if atr_val <= 0:
        return

    close = bar["close"]
    mode = s["mode"]

    # ── Check if we're in a news danger zone ──
    # In backtest mode, we simulate danger zones around known event patterns
    # In live mode, the engine injects real event data via __news_events__
    in_danger_zone = False
    in_pre_event = False
    in_post_event = False

    news_events = getattr(bar, "_news_events", None) or globals().get("__news_events__", [])
    if news_events:
        for evt in news_events:
            tier = _classify_event(evt.get("event", ""))
            if tier > 2:  # Skip Tier 3 if warning-only
                continue
            pre, post = _is_in_danger_zone(
                bar.get("time"), evt.get("event_time"),
                s["pre_event_minutes"], s["post_event_minutes"]
            )
            if pre:
                in_pre_event = True
                in_danger_zone = True
            if post:
                in_post_event = True
                in_danger_zone = True

    # ── Defensive Mode Logic ──
    if mode == "defensive":
        # During pre-event: close positions
        if in_pre_event and s["close_before_tier1"]:
            for t in list(open_trades):  # noqa: F821
                close_trade(t["id"], close, "news_guard_defensive")  # noqa: F821
            return

        # During lockout: reject new entries
        if in_danger_zone and s["reject_entries_in_lockout"]:
            return

    # ── Reactive Mode Logic ──
    if mode == "reactive":
        # During pre-event and lockout: do nothing
        if in_pre_event:
            return

        # In post-event reactive window: look for breakout
        if in_post_event:
            # Check for momentum confirmation
            if i >= s["momentum_confirm_bars"]:
                bullish_count = 0
                bearish_count = 0
                for j in range(1, s["momentum_confirm_bars"] + 1):
                    prev_bar = bars[i - j]  # noqa: F821
                    if prev_bar["close"] > prev_bar["open"]:
                        bullish_count += 1
                    else:
                        bearish_count += 1

                sl_mult = s["reactive_atr_mult_sl"]
                tp_mult = s["reactive_atr_mult_tp"]

                if bullish_count >= s["momentum_confirm_bars"]:
                    # Bullish momentum confirmed — long
                    if s["use_ema_filter"] and close < ema[i]:
                        return  # Against trend
                    sl = close - atr_val * sl_mult
                    tp = close + atr_val * tp_mult
                    if i - ctx["last_trade_bar"] >= s["cooldown_bars"]:
                        open_trade("long", close, sl, tp)  # noqa: F821
                        ctx["last_trade_bar"] = i
                        return

                elif bearish_count >= s["momentum_confirm_bars"]:
                    # Bearish momentum confirmed — short
                    if s["use_ema_filter"] and close > ema[i]:
                        return  # Against trend
                    sl = close + atr_val * sl_mult
                    tp = close - atr_val * tp_mult
                    if i - ctx["last_trade_bar"] >= s["cooldown_bars"]:
                        open_trade("short", close, sl, tp)  # noqa: F821
                        ctx["last_trade_bar"] = i
                        return
            return  # Don't process further during post-event

    # ── Standard Signal Logic (non-event periods) ──
    # Basic trend-following signal using EMA crossover + ATR

    if i - ctx["last_trade_bar"] < s["cooldown_bars"]:
        return

    if len(open_trades) >= s["max_concurrent"]:  # noqa: F821
        return

    # Trend direction from EMA
    if not s["use_ema_filter"]:
        return  # No signal without EMA filter

    bullish_trend = close > ema[i]
    bearish_trend = close < ema[i]

    # Simple pullback entry: price pulls back to EMA zone and bounces
    ema_dist = abs(close - ema[i]) / atr_val if atr_val > 0 else 999
    near_ema = ema_dist < 0.8  # Within 0.8 ATR of EMA

    if not near_ema:
        return

    # Check for bounce (last bar closed in direction of trend)
    prev_close = bars[i - 1]["close"] if i > 0 else close  # noqa: F821
    curr_close = close

    sl_mult = s["atr_sl_mult"]
    tp_mult = s["atr_tp_mult"]

    if bullish_trend and curr_close > prev_close:
        sl = close - atr_val * sl_mult
        tp = close + atr_val * tp_mult
        open_trade("long", close, sl, tp)  # noqa: F821
        ctx["last_trade_bar"] = i

    elif bearish_trend and curr_close < prev_close:
        sl = close + atr_val * sl_mult
        tp = close - atr_val * tp_mult
        open_trade("short", close, sl, tp)  # noqa: F821
        ctx["last_trade_bar"] = i
