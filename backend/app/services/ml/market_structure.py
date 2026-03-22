"""
Market Structure Detector — Smart Money Concepts for ML feature engineering.

Detects institutional trading patterns that expert traders use:
  - Swing Highs/Lows (fractals)
  - Break of Structure (BOS) — continuation pattern
  - Change of Character (CHoCH) — reversal pattern
  - Order Blocks (OB) — institutional supply/demand zones
  - Fair Value Gaps (FVG) — imbalance zones
  - Liquidity Sweeps — stop hunts before reversals

All outputs are numerical arrays suitable for ML model input.
"""

import numpy as np
from typing import Optional


# ── Swing Detection ────────────────────────────────────

def detect_swings(
    highs: np.ndarray,
    lows: np.ndarray,
    lookback: int = 5,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Detect swing highs and swing lows using fractal logic.

    A swing high at bar i means highs[i] is the highest high
    in the window [i-lookback, i+lookback].

    Returns:
        swing_high_idx: array of bar indices where swing highs occur
        swing_high_val: corresponding high values
        swing_low_idx: array of bar indices where swing lows occur
        swing_low_val: corresponding low values
    """
    n = len(highs)
    sh_idx, sh_val = [], []
    sl_idx, sl_val = [], []

    for i in range(lookback, n - lookback):
        # Swing high: highest in window
        window_highs = highs[i - lookback: i + lookback + 1]
        if highs[i] == np.max(window_highs):
            sh_idx.append(i)
            sh_val.append(highs[i])

        # Swing low: lowest in window
        window_lows = lows[i - lookback: i + lookback + 1]
        if lows[i] == np.min(window_lows):
            sl_idx.append(i)
            sl_val.append(lows[i])

    return (
        np.array(sh_idx, dtype=np.int64),
        np.array(sh_val, dtype=np.float64),
        np.array(sl_idx, dtype=np.int64),
        np.array(sl_val, dtype=np.float64),
    )


# ── Break of Structure & Change of Character ──────────

def detect_bos_choch(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    lookback: int = 5,
) -> dict[str, np.ndarray]:
    """
    Detect Break of Structure (BOS) and Change of Character (CHoCH).

    BOS: Price breaks the most recent swing high (bullish) or swing low (bearish),
         continuing the existing trend.

    CHoCH: First break in the OPPOSITE direction after a series of consistent
           breaks. Signals potential trend reversal.

    Returns dict of feature arrays (length n):
        bos_bullish:  1.0 on bars where bullish BOS occurs
        bos_bearish:  1.0 on bars where bearish BOS occurs
        choch_bullish: 1.0 on bars where bullish CHoCH occurs
        choch_bearish: 1.0 on bars where bearish CHoCH occurs
        structure_direction: running structure direction (+1=bullish, -1=bearish, 0=undefined)
        swing_high_dist: normalized distance from most recent swing high
        swing_low_dist: normalized distance from most recent swing low
    """
    n = len(highs)
    sh_idx, sh_val, sl_idx, sl_val = detect_swings(highs, lows, lookback)

    bos_bull = np.zeros(n)
    bos_bear = np.zeros(n)
    choch_bull = np.zeros(n)
    choch_bear = np.zeros(n)
    struct_dir = np.zeros(n)
    sh_dist = np.full(n, np.nan)
    sl_dist = np.full(n, np.nan)

    if len(sh_idx) < 2 or len(sl_idx) < 2:
        return {
            "bos_bullish": bos_bull,
            "bos_bearish": bos_bear,
            "choch_bullish": choch_bull,
            "choch_bearish": choch_bear,
            "structure_direction": struct_dir,
            "swing_high_dist": sh_dist,
            "swing_low_dist": sl_dist,
        }

    # Track the current trend based on structure breaks
    current_trend = 0  # 0=undefined, 1=bullish, -1=bearish
    last_sh_val = sh_val[0]
    last_sl_val = sl_val[0]
    prev_sh_val = sh_val[0]
    prev_sl_val = sl_val[0]

    # Merge swings into chronological order for processing
    all_swing_idx = np.concatenate([sh_idx, sl_idx])
    all_swing_type = np.concatenate([
        np.ones(len(sh_idx)),      # 1 = swing high
        -np.ones(len(sl_idx)),     # -1 = swing low
    ])
    all_swing_val = np.concatenate([sh_val, sl_val])
    sort_order = np.argsort(all_swing_idx)
    all_swing_idx = all_swing_idx[sort_order]
    all_swing_type = all_swing_type[sort_order]
    all_swing_val = all_swing_val[sort_order]

    # Process swings sequentially
    sh_ptr = 0  # pointer into swing high arrays
    sl_ptr = 0  # pointer into swing low arrays

    for bar in range(n):
        # Update nearest swing high/low pointers
        while sh_ptr < len(sh_idx) - 1 and sh_idx[sh_ptr + 1] <= bar:
            sh_ptr += 1
        while sl_ptr < len(sl_idx) - 1 and sl_idx[sl_ptr + 1] <= bar:
            sl_ptr += 1

        if sh_idx[sh_ptr] <= bar:
            last_sh_val = sh_val[sh_ptr]
            # Normalized distance from swing high
            if closes[bar] > 0:
                sh_dist[bar] = (closes[bar] - last_sh_val) / closes[bar]
        if sl_idx[sl_ptr] <= bar:
            last_sl_val = sl_val[sl_ptr]
            # Normalized distance from swing low
            if closes[bar] > 0:
                sl_dist[bar] = (closes[bar] - last_sl_val) / closes[bar]

        # Check for bullish break (close > last swing high)
        if closes[bar] > last_sh_val and last_sh_val > 0:
            if current_trend == -1:
                # Was bearish, now breaking high → CHoCH (reversal)
                choch_bull[bar] = 1.0
            else:
                # Continuing bullish or from undefined → BOS
                bos_bull[bar] = 1.0
            current_trend = 1
            prev_sh_val = last_sh_val

        # Check for bearish break (close < last swing low)
        if closes[bar] < last_sl_val and last_sl_val > 0:
            if current_trend == 1:
                # Was bullish, now breaking low → CHoCH (reversal)
                choch_bear[bar] = 1.0
            else:
                # Continuing bearish or from undefined → BOS
                bos_bear[bar] = 1.0
            current_trend = -1
            prev_sl_val = last_sl_val

        struct_dir[bar] = current_trend

    return {
        "bos_bullish": bos_bull,
        "bos_bearish": bos_bear,
        "choch_bullish": choch_bull,
        "choch_bearish": choch_bear,
        "structure_direction": struct_dir,
        "swing_high_dist": sh_dist,
        "swing_low_dist": sl_dist,
    }


# ── Order Blocks ──────────────────────────────────────

def detect_order_blocks(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    lookback: int = 5,
    max_ob_age: int = 50,
) -> dict[str, np.ndarray]:
    """
    Detect Order Blocks — the last opposing candle before a BOS.

    Bullish OB: Last bearish candle before a bullish BOS (demand zone).
    Bearish OB: Last bullish candle before a bearish BOS (supply zone).

    Returns:
        ob_bullish_proximity: how close price is to nearest unmitigated bullish OB (0-1)
        ob_bearish_proximity: how close price is to nearest unmitigated bearish OB (0-1)
        ob_bullish_touch: 1.0 when price touches/enters a bullish OB zone
        ob_bearish_touch: 1.0 when price touches/enters a bearish OB zone
    """
    n = len(closes)
    ob_bull_prox = np.zeros(n)
    ob_bear_prox = np.zeros(n)
    ob_bull_touch = np.zeros(n)
    ob_bear_touch = np.zeros(n)

    # Get BOS events
    bos_data = detect_bos_choch(highs, lows, closes, lookback)
    bos_bull = bos_data["bos_bullish"]
    bos_bear = bos_data["bos_bearish"]

    # Active order blocks: list of (low, high, bar_created)
    active_bull_obs: list[tuple[float, float, int]] = []
    active_bear_obs: list[tuple[float, float, int]] = []

    for bar in range(1, n):
        # On bullish BOS: find last bearish candle before it → bullish OB
        if bos_bull[bar] > 0:
            for j in range(bar - 1, max(bar - 10, 0), -1):
                if closes[j] < opens[j]:  # bearish candle
                    active_bull_obs.append((lows[j], highs[j], bar))
                    break

        # On bearish BOS: find last bullish candle before it → bearish OB
        if bos_bear[bar] > 0:
            for j in range(bar - 1, max(bar - 10, 0), -1):
                if closes[j] > opens[j]:  # bullish candle
                    active_bear_obs.append((lows[j], highs[j], bar))
                    break

        # Check proximity to active bullish OBs (demand zones below price)
        remaining_bull = []
        for ob_low, ob_high, ob_bar in active_bull_obs:
            age = bar - ob_bar
            if age > max_ob_age:
                continue  # expired

            # Check if price mitigated the OB (traded through it)
            if lows[bar] <= ob_low:
                continue  # mitigated, remove

            remaining_bull.append((ob_low, ob_high, ob_bar))

            # Proximity: how close is current low to OB high
            dist = (lows[bar] - ob_high) / closes[bar] if closes[bar] > 0 else 1.0
            proximity = max(0.0, 1.0 - abs(dist) * 20)  # 5% distance = 0 proximity
            ob_bull_prox[bar] = max(ob_bull_prox[bar], proximity)

            # Touch: price enters the OB zone
            if lows[bar] <= ob_high and highs[bar] >= ob_low:
                ob_bull_touch[bar] = 1.0

        active_bull_obs = remaining_bull

        # Check proximity to active bearish OBs (supply zones above price)
        remaining_bear = []
        for ob_low, ob_high, ob_bar in active_bear_obs:
            age = bar - ob_bar
            if age > max_ob_age:
                continue

            if highs[bar] >= ob_high:
                continue  # mitigated

            remaining_bear.append((ob_low, ob_high, ob_bar))

            dist = (ob_low - highs[bar]) / closes[bar] if closes[bar] > 0 else 1.0
            proximity = max(0.0, 1.0 - abs(dist) * 20)
            ob_bear_prox[bar] = max(ob_bear_prox[bar], proximity)

            if highs[bar] >= ob_low and lows[bar] <= ob_high:
                ob_bear_touch[bar] = 1.0

        active_bear_obs = remaining_bear

    return {
        "ob_bullish_proximity": ob_bull_prox,
        "ob_bearish_proximity": ob_bear_prox,
        "ob_bullish_touch": ob_bull_touch,
        "ob_bearish_touch": ob_bear_touch,
    }


# ── Fair Value Gaps ───────────────────────────────────

def detect_fair_value_gaps(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    max_fvg_age: int = 30,
) -> dict[str, np.ndarray]:
    """
    Detect Fair Value Gaps (FVGs) — 3-candle imbalance patterns.

    Bullish FVG: candle[i-2].high < candle[i].low (gap up, price may retrace to fill)
    Bearish FVG: candle[i-2].low > candle[i].high (gap down, price may retrace to fill)

    Returns:
        fvg_bullish_proximity: closeness to nearest unfilled bullish FVG (0-1)
        fvg_bearish_proximity: closeness to nearest unfilled bearish FVG (0-1)
        fvg_bullish_active: count of active bullish FVGs nearby
        fvg_bearish_active: count of active bearish FVGs nearby
    """
    n = len(highs)
    fvg_bull_prox = np.zeros(n)
    fvg_bear_prox = np.zeros(n)
    fvg_bull_count = np.zeros(n)
    fvg_bear_count = np.zeros(n)

    # Active FVGs: list of (gap_low, gap_high, bar_created)
    active_bull_fvgs: list[tuple[float, float, int]] = []
    active_bear_fvgs: list[tuple[float, float, int]] = []

    for bar in range(2, n):
        # Detect new bullish FVG: bar[i-2].high < bar[i].low
        if highs[bar - 2] < lows[bar]:
            gap_low = highs[bar - 2]
            gap_high = lows[bar]
            active_bull_fvgs.append((gap_low, gap_high, bar))

        # Detect new bearish FVG: bar[i-2].low > bar[i].high
        if lows[bar - 2] > highs[bar]:
            gap_low = highs[bar]
            gap_high = lows[bar - 2]
            active_bear_fvgs.append((gap_low, gap_high, bar))

        # Check bullish FVGs (below price — demand)
        remaining_bull = []
        for fvg_low, fvg_high, fvg_bar in active_bull_fvgs:
            age = bar - fvg_bar
            if age > max_fvg_age:
                continue

            # Filled if price traded through the gap
            if lows[bar] <= fvg_low:
                continue

            remaining_bull.append((fvg_low, fvg_high, fvg_bar))

            dist = (lows[bar] - fvg_high) / closes[bar] if closes[bar] > 0 else 1.0
            proximity = max(0.0, 1.0 - abs(dist) * 25)
            fvg_bull_prox[bar] = max(fvg_bull_prox[bar], proximity)

        active_bull_fvgs = remaining_bull
        fvg_bull_count[bar] = len(active_bull_fvgs)

        # Check bearish FVGs (above price — supply)
        remaining_bear = []
        for fvg_low, fvg_high, fvg_bar in active_bear_fvgs:
            age = bar - fvg_bar
            if age > max_fvg_age:
                continue

            if highs[bar] >= fvg_high:
                continue

            remaining_bear.append((fvg_low, fvg_high, fvg_bar))

            dist = (fvg_low - highs[bar]) / closes[bar] if closes[bar] > 0 else 1.0
            proximity = max(0.0, 1.0 - abs(dist) * 25)
            fvg_bear_prox[bar] = max(fvg_bear_prox[bar], proximity)

        active_bear_fvgs = remaining_bear
        fvg_bear_count[bar] = len(active_bear_fvgs)

    # Normalize counts
    max_count = max(np.max(fvg_bull_count), np.max(fvg_bear_count), 1.0)
    fvg_bull_count /= max_count
    fvg_bear_count /= max_count

    return {
        "fvg_bullish_proximity": fvg_bull_prox,
        "fvg_bearish_proximity": fvg_bear_prox,
        "fvg_bullish_active": fvg_bull_count,
        "fvg_bearish_active": fvg_bear_count,
    }


# ── Liquidity Sweeps ─────────────────────────────────

def detect_liquidity_sweeps(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    lookback: int = 5,
    sweep_threshold: float = 0.001,
) -> dict[str, np.ndarray]:
    """
    Detect Liquidity Sweeps — price takes out a swing level then reverses.

    Bullish sweep: price breaks below a swing low, then closes above it
                   (swept sell-side liquidity, likely to reverse up).

    Bearish sweep: price breaks above a swing high, then closes below it
                   (swept buy-side liquidity, likely to reverse down).

    Returns:
        liq_sweep_bullish: 1.0 on bars where bullish sweep is confirmed
        liq_sweep_bearish: 1.0 on bars where bearish sweep is confirmed
        liq_sweep_recency: bars since last sweep (normalized, decays to 0)
    """
    n = len(highs)
    sweep_bull = np.zeros(n)
    sweep_bear = np.zeros(n)
    sweep_recency = np.zeros(n)

    sh_idx, sh_val, sl_idx, sl_val = detect_swings(highs, lows, lookback)

    last_sweep_bar = -100

    for bar in range(lookback + 1, n):
        # Check bullish sweep: wick below recent swing low, close above it
        for j in range(len(sl_idx) - 1, -1, -1):
            if sl_idx[j] >= bar - 1:
                continue
            if sl_idx[j] < bar - 30:
                break
            sl = sl_val[j]
            # Low went below swing low (sweep) but close came back above
            if lows[bar] < sl * (1.0 - sweep_threshold) and closes[bar] > sl:
                sweep_bull[bar] = 1.0
                last_sweep_bar = bar
                break

        # Check bearish sweep: wick above recent swing high, close below it
        for j in range(len(sh_idx) - 1, -1, -1):
            if sh_idx[j] >= bar - 1:
                continue
            if sh_idx[j] < bar - 30:
                break
            sh = sh_val[j]
            if highs[bar] > sh * (1.0 + sweep_threshold) and closes[bar] < sh:
                sweep_bear[bar] = 1.0
                last_sweep_bar = bar
                break

        # Recency: decays over 20 bars
        if last_sweep_bar >= 0:
            age = bar - last_sweep_bar
            sweep_recency[bar] = max(0.0, 1.0 - age / 20.0)

    return {
        "liq_sweep_bullish": sweep_bull,
        "liq_sweep_bearish": sweep_bear,
        "liq_sweep_recency": sweep_recency,
    }


# ── Combined Feature Computation ──────────────────────

def compute_market_structure_features(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    swing_lookback: int = 5,
) -> dict[str, np.ndarray]:
    """
    Compute all market structure features in one call.

    Returns dict of ~22 feature arrays, all length n.
    """
    features = {}

    # 1. Structure breaks (BOS + CHoCH) — 7 features
    bos = detect_bos_choch(highs, lows, closes, swing_lookback)
    features.update(bos)

    # 2. Order blocks — 4 features
    ob = detect_order_blocks(opens, highs, lows, closes, swing_lookback)
    features.update(ob)

    # 3. Fair value gaps — 4 features
    fvg = detect_fair_value_gaps(highs, lows, closes)
    features.update(fvg)

    # 4. Liquidity sweeps — 3 features
    liq = detect_liquidity_sweeps(highs, lows, closes, swing_lookback)
    features.update(liq)

    # 5. Derived: combined signal strength
    n = len(closes)
    # Bullish confluence: BOS/CHoCH bull + OB touch + FVG proximity + liq sweep
    bull_confluence = (
        bos["bos_bullish"] * 0.3
        + bos["choch_bullish"] * 0.3
        + ob["ob_bullish_touch"] * 0.2
        + fvg["fvg_bullish_proximity"] * 0.1
        + liq["liq_sweep_bullish"] * 0.1
    )
    bear_confluence = (
        bos["bos_bearish"] * 0.3
        + bos["choch_bearish"] * 0.3
        + ob["ob_bearish_touch"] * 0.2
        + fvg["fvg_bearish_proximity"] * 0.1
        + liq["liq_sweep_bearish"] * 0.1
    )

    features["smc_bullish_confluence"] = bull_confluence
    features["smc_bearish_confluence"] = bear_confluence

    # Net structure bias: positive = bullish, negative = bearish
    features["smc_net_bias"] = bull_confluence - bear_confluence

    return features
