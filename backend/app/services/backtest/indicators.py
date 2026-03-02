"""
Pure-Python technical indicator calculations.
All functions take lists of floats and return lists of floats (with NaN padding).
"""
import math

NaN = float("nan")


def sma(data: list[float], period: int) -> list[float]:
    """Simple Moving Average."""
    result = [NaN] * len(data)
    if period > len(data):
        return result
    window_sum = sum(data[:period])
    result[period - 1] = window_sum / period
    for i in range(period, len(data)):
        window_sum += data[i] - data[i - period]
        result[i] = window_sum / period
    return result


def ema(data: list[float], period: int) -> list[float]:
    """Exponential Moving Average."""
    result = [NaN] * len(data)
    if period > len(data):
        return result
    k = 2.0 / (period + 1)
    # Seed with SMA
    result[period - 1] = sum(data[:period]) / period
    for i in range(period, len(data)):
        result[i] = data[i] * k + result[i - 1] * (1 - k)
    return result


def rsi(data: list[float], period: int = 14) -> list[float]:
    """Relative Strength Index."""
    result = [NaN] * len(data)
    if period + 1 > len(data):
        return result

    gains = []
    losses = []
    for i in range(1, period + 1):
        diff = data[i] - data[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(period + 1, len(data)):
        diff = data[i] - data[i - 1]
        gain = max(diff, 0)
        loss = max(-diff, 0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            result[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i] = 100.0 - (100.0 / (1.0 + rs))

    return result


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    """Average True Range."""
    n = len(highs)
    result = [NaN] * n
    if period + 1 > n:
        return result

    trs = []
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)

    # First ATR is simple average
    if len(trs) < period:
        return result
    result[period] = sum(trs[:period]) / period

    for i in range(period + 1, n):
        result[i] = (result[i - 1] * (period - 1) + trs[i - 1]) / period

    return result


def macd(data: list[float], fast: int = 12, slow: int = 26, signal_period: int = 9):
    """MACD. Returns (macd_line, signal_line, histogram)."""
    fast_ema = ema(data, fast)
    slow_ema = ema(data, slow)
    n = len(data)

    macd_line = [NaN] * n
    for i in range(n):
        if not (math.isnan(fast_ema[i]) or math.isnan(slow_ema[i])):
            macd_line[i] = fast_ema[i] - slow_ema[i]

    # Signal line = EMA of MACD line
    valid_macd = [v for v in macd_line if not math.isnan(v)]
    signal_line_vals = ema(valid_macd, signal_period) if len(valid_macd) >= signal_period else [NaN] * len(valid_macd)

    signal_line = [NaN] * n
    histogram = [NaN] * n
    j = 0
    for i in range(n):
        if not math.isnan(macd_line[i]):
            if j < len(signal_line_vals):
                signal_line[i] = signal_line_vals[j]
                if not math.isnan(signal_line_vals[j]):
                    histogram[i] = macd_line[i] - signal_line_vals[j]
            j += 1

    return macd_line, signal_line, histogram


def bollinger_bands(data: list[float], period: int = 20, std_dev: float = 2.0):
    """Bollinger Bands. Returns (upper, middle, lower)."""
    middle = sma(data, period)
    n = len(data)
    upper = [NaN] * n
    lower = [NaN] * n

    for i in range(period - 1, n):
        if math.isnan(middle[i]):
            continue
        window = data[i - period + 1 : i + 1]
        mean = middle[i]
        variance = sum((x - mean) ** 2 for x in window) / period
        std = math.sqrt(variance)
        upper[i] = mean + std_dev * std
        lower[i] = mean - std_dev * std

    return upper, middle, lower


def stochastic(highs: list[float], lows: list[float], closes: list[float],
               k_period: int = 14, d_period: int = 3, smooth: int = 3):
    """Stochastic oscillator. Returns (%K, %D)."""
    n = len(closes)
    raw_k = [NaN] * n

    for i in range(k_period - 1, n):
        h = max(highs[i - k_period + 1 : i + 1])
        l = min(lows[i - k_period + 1 : i + 1])
        if h != l:
            raw_k[i] = ((closes[i] - l) / (h - l)) * 100
        else:
            raw_k[i] = 50.0

    # Smooth %K
    valid_k = [v for v in raw_k if not math.isnan(v)]
    smoothed = sma(valid_k, smooth) if smooth > 1 and len(valid_k) >= smooth else valid_k

    k_line = [NaN] * n
    j = 0
    for i in range(n):
        if not math.isnan(raw_k[i]):
            if j < len(smoothed):
                k_line[i] = smoothed[j]
            j += 1

    # %D = SMA of %K
    valid_k2 = [v for v in k_line if not math.isnan(v)]
    d_vals = sma(valid_k2, d_period) if len(valid_k2) >= d_period else [NaN] * len(valid_k2)

    d_line = [NaN] * n
    j = 0
    for i in range(n):
        if not math.isnan(k_line[i]):
            if j < len(d_vals):
                d_line[i] = d_vals[j]
            j += 1

    return k_line, d_line


def pivot_high(highs: list[float], lookback: int = 42) -> list[float]:
    """Pivot High — tracks the most recent confirmed swing high level.
    A swing high is a bar whose high is the highest in a window of
    `lookback` bars before and `lookback//4` bars after (confirmation).
    Once a swing high is confirmed, it persists until a new swing high forms."""
    n = len(highs)
    result = [NaN] * n
    confirm = max(lookback // 4, 2)  # confirmation bars after the pivot
    current_level = NaN

    for i in range(lookback + confirm, n):
        # Check if bar at (i - confirm) is a swing high
        candidate_idx = i - confirm
        candidate_high = highs[candidate_idx]
        # Must be highest in window [candidate_idx - lookback, candidate_idx + confirm]
        window_start = max(0, candidate_idx - lookback)
        window_end = min(n, candidate_idx + confirm + 1)
        window_max = max(highs[window_start:window_end])
        if candidate_high >= window_max:
            current_level = candidate_high

        if not math.isnan(current_level):
            result[i] = current_level

    return result


def pivot_low(lows: list[float], lookback: int = 42) -> list[float]:
    """Pivot Low — tracks the most recent confirmed swing low level.
    A swing low is a bar whose low is the lowest in a window of
    `lookback` bars before and `lookback//4` bars after (confirmation).
    Once a swing low is confirmed, it persists until a new swing low forms."""
    n = len(lows)
    result = [NaN] * n
    confirm = max(lookback // 4, 2)  # confirmation bars after the pivot
    current_level = NaN

    for i in range(lookback + confirm, n):
        # Check if bar at (i - confirm) is a swing low
        candidate_idx = i - confirm
        candidate_low = lows[candidate_idx]
        # Must be lowest in window [candidate_idx - lookback, candidate_idx + confirm]
        window_start = max(0, candidate_idx - lookback)
        window_end = min(n, candidate_idx + confirm + 1)
        window_min = min(lows[window_start:window_end])
        if candidate_low <= window_min:
            current_level = candidate_low

        if not math.isnan(current_level):
            result[i] = current_level

    return result


def adr(highs: list[float], lows: list[float], period: int = 10,
        timestamps: list[float] | None = None) -> list[float]:
    """Average Daily Range — average of true daily (high-low) ranges.

    When *timestamps* are provided the function groups bars by calendar date
    (UTC) and computes max(high) - min(low) for each full trading day.  The
    last ``period`` completed daily ranges are then averaged.  This produces
    the correct ADR even on intraday data (M1, M5, M10, H1, …).

    When timestamps are ``None`` (or the data is already daily) the function
    falls back to a simple SMA of per-bar ranges, which is the legacy
    behaviour.
    """
    import datetime as _dt

    n = len(highs)
    result = [NaN] * n
    if n == 0:
        return result

    # ------------------------------------------------------------------
    # Fast path: no timestamps → assume bars ARE daily
    # ------------------------------------------------------------------
    if timestamps is None or len(timestamps) != n:
        if period > n:
            return result
        ranges = [highs[i] - lows[i] for i in range(n)]
        window_sum = sum(ranges[:period])
        result[period - 1] = window_sum / period
        for i in range(period, n):
            window_sum += ranges[i] - ranges[i - period]
            result[i] = window_sum / period
        return result

    # ------------------------------------------------------------------
    # Intraday path: group bars by calendar date and compute true daily range
    # ------------------------------------------------------------------
    # Build per-day high/low running values
    # day_ranges is a list of (date_ordinal, daily_range) completed so far
    day_ranges: list[float] = []          # completed daily ranges
    last_day_bar: list[int] = []          # bar index where each day ended

    prev_date_ord: int = -1
    day_high = -math.inf
    day_low = math.inf

    # Map each bar to which day index (in day_ranges) it has completed
    # bar_completed_days[i] = how many full daily ranges are available AT bar i
    bar_completed_days = [0] * n

    for i in range(n):
        dt = _dt.datetime.fromtimestamp(timestamps[i], tz=_dt.timezone.utc)
        date_ord = dt.toordinal()

        if prev_date_ord == -1:
            # First bar
            prev_date_ord = date_ord
            day_high = highs[i]
            day_low = lows[i]
        elif date_ord != prev_date_ord:
            # New day → close previous day
            daily_range = day_high - day_low
            if daily_range > 0:
                day_ranges.append(daily_range)
                last_day_bar.append(i - 1)
            # Start new day
            prev_date_ord = date_ord
            day_high = highs[i]
            day_low = lows[i]
        else:
            # Same day — update running high/low
            if highs[i] > day_high:
                day_high = highs[i]
            if lows[i] < day_low:
                day_low = lows[i]

        bar_completed_days[i] = len(day_ranges)

    # Now fill result: for each bar, average the last `period` completed daily ranges
    for i in range(n):
        num_days = bar_completed_days[i]
        if num_days < period:
            continue
        # Average the last `period` daily ranges
        recent = day_ranges[num_days - period : num_days]
        result[i] = sum(recent) / period

    return result


def adx(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    """Average Directional Index."""
    n = len(highs)
    result = [NaN] * n
    if n < period * 2:
        return result

    plus_dm = []
    minus_dm = []
    tr_list = []

    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)
        tr_list.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))

    # Smooth using Wilder's method
    atr_val = sum(tr_list[:period])
    plus_di_smooth = sum(plus_dm[:period])
    minus_di_smooth = sum(minus_dm[:period])

    dx_values = []
    for i in range(period, len(tr_list)):
        atr_val = atr_val - (atr_val / period) + tr_list[i]
        plus_di_smooth = plus_di_smooth - (plus_di_smooth / period) + plus_dm[i]
        minus_di_smooth = minus_di_smooth - (minus_di_smooth / period) + minus_dm[i]

        if atr_val > 0:
            pdi = 100 * plus_di_smooth / atr_val
            mdi = 100 * minus_di_smooth / atr_val
            if pdi + mdi > 0:
                dx_values.append(100 * abs(pdi - mdi) / (pdi + mdi))
            else:
                dx_values.append(0)
        else:
            dx_values.append(0)

    # ADX = smoothed DX
    if len(dx_values) >= period:
        adx_val = sum(dx_values[:period]) / period
        idx = 2 * period
        if idx < n:
            result[idx] = adx_val
        for j in range(period, len(dx_values)):
            adx_val = (adx_val * (period - 1) + dx_values[j]) / period
            idx = j + period + 1
            if idx < n:
                result[idx] = adx_val

    return result


# ── VWAP ──────────────────────────────────────────────────────────

def vwap(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
    timestamps: list[float] | None = None,
) -> list[float]:
    """Volume-Weighted Average Price — resets each calendar day (UTC).

    Typical price = (H + L + C) / 3.  VWAP = cumsum(TP*Vol) / cumsum(Vol)
    within each trading day.  When *timestamps* are not provided the VWAP
    runs cumulatively over the entire dataset (no daily reset).
    """
    import datetime as _dt

    n = len(closes)
    result = [NaN] * n
    if n == 0:
        return result

    cum_tp_vol = 0.0
    cum_vol = 0.0
    prev_date_ord = -1

    for i in range(n):
        tp = (highs[i] + lows[i] + closes[i]) / 3.0
        vol = volumes[i] if volumes[i] > 0 else 1.0  # fallback for zero-volume bars

        # Reset on new calendar day
        if timestamps is not None and len(timestamps) == n:
            dt = _dt.datetime.fromtimestamp(timestamps[i], tz=_dt.timezone.utc)
            date_ord = dt.toordinal()
            if prev_date_ord != -1 and date_ord != prev_date_ord:
                cum_tp_vol = 0.0
                cum_vol = 0.0
            prev_date_ord = date_ord

        cum_tp_vol += tp * vol
        cum_vol += vol
        result[i] = cum_tp_vol / cum_vol if cum_vol > 0 else tp

    return result


# ── Daily Pivot Points ────────────────────────────────────────────

def daily_pivot_points(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    timestamps: list[float],
) -> dict[str, list[float]]:
    """Standard (Floor) Pivot Points from prior day's High, Low, Close.

    Returns a dict with keys: pp, r1, r2, r3, s1, s2, s3.
    Each value is a list[float] of length n.  On the first day of data all
    values are NaN because there is no prior day.
    """
    import datetime as _dt

    n = len(closes)
    keys = ("pp", "r1", "r2", "r3", "s1", "s2", "s3")
    out: dict[str, list[float]] = {k: [NaN] * n for k in keys}
    if n == 0 or timestamps is None or len(timestamps) != n:
        return out

    # Pass 1: collect daily high/low/close
    day_high = highs[0]
    day_low = lows[0]
    day_close = closes[0]
    prev_date_ord = _dt.datetime.fromtimestamp(timestamps[0], tz=_dt.timezone.utc).toordinal()
    have_prev_day = False
    p_pp = p_r1 = p_r2 = p_r3 = p_s1 = p_s2 = p_s3 = NaN

    for i in range(n):
        dt = _dt.datetime.fromtimestamp(timestamps[i], tz=_dt.timezone.utc)
        date_ord = dt.toordinal()

        if date_ord != prev_date_ord:
            # Compute pivots from COMPLETED day
            pp = (day_high + day_low + day_close) / 3.0
            p_r1 = 2.0 * pp - day_low
            p_s1 = 2.0 * pp - day_high
            p_r2 = pp + (day_high - day_low)
            p_s2 = pp - (day_high - day_low)
            p_r3 = day_high + 2.0 * (pp - day_low)
            p_s3 = day_low - 2.0 * (day_high - pp)
            p_pp = pp
            have_prev_day = True
            # Reset for new day
            day_high = highs[i]
            day_low = lows[i]
            day_close = closes[i]
            prev_date_ord = date_ord
        else:
            if highs[i] > day_high:
                day_high = highs[i]
            if lows[i] < day_low:
                day_low = lows[i]
            day_close = closes[i]

        if have_prev_day:
            out["pp"][i] = p_pp
            out["r1"][i] = p_r1
            out["r2"][i] = p_r2
            out["r3"][i] = p_r3
            out["s1"][i] = p_s1
            out["s2"][i] = p_s2
            out["s3"][i] = p_s3

    return out


# ════════════════════════════════════════════════════════════════════
#  Phase 2A — New Indicators (30+)
# ════════════════════════════════════════════════════════════════════

# ── Trend Indicators ────────────────────────────────────────────────

def dema(data: list[float], period: int) -> list[float]:
    """Double Exponential Moving Average: 2*EMA - EMA(EMA)."""
    e1 = ema(data, period)
    e2 = ema([v if not math.isnan(v) else 0.0 for v in e1], period)
    n = len(data)
    result = [NaN] * n
    for i in range(n):
        if not (math.isnan(e1[i]) or math.isnan(e2[i])):
            result[i] = 2.0 * e1[i] - e2[i]
    return result


def tema(data: list[float], period: int) -> list[float]:
    """Triple Exponential Moving Average: 3*EMA - 3*EMA(EMA) + EMA(EMA(EMA))."""
    e1 = ema(data, period)
    e1_clean = [v if not math.isnan(v) else 0.0 for v in e1]
    e2 = ema(e1_clean, period)
    e2_clean = [v if not math.isnan(v) else 0.0 for v in e2]
    e3 = ema(e2_clean, period)
    n = len(data)
    result = [NaN] * n
    for i in range(n):
        if not (math.isnan(e1[i]) or math.isnan(e2[i]) or math.isnan(e3[i])):
            result[i] = 3.0 * e1[i] - 3.0 * e2[i] + e3[i]
    return result


def zlema(data: list[float], period: int) -> list[float]:
    """Zero-Lag EMA: EMA of (2×close − close[lag]) where lag = (period-1)//2."""
    n = len(data)
    lag = (period - 1) // 2
    adjusted = [NaN] * n
    for i in range(lag, n):
        adjusted[i] = 2.0 * data[i] - data[i - lag]
    # Replace NaN with 0 for EMA seed
    adj_clean = [v if not math.isnan(v) else data[i] for i, v in enumerate(adjusted)]
    return ema(adj_clean, period)


def hull_ma(data: list[float], period: int) -> list[float]:
    """Hull Moving Average: WMA(2×WMA(n/2) − WMA(n), sqrt(n))."""
    half_p = max(period // 2, 1)
    sqrt_p = max(int(math.sqrt(period)), 1)
    wma_half = _wma(data, half_p)
    wma_full = _wma(data, period)
    n = len(data)
    diff = [NaN] * n
    for i in range(n):
        if not (math.isnan(wma_half[i]) or math.isnan(wma_full[i])):
            diff[i] = 2.0 * wma_half[i] - wma_full[i]
    diff_clean = [v if not math.isnan(v) else 0.0 for v in diff]
    return _wma(diff_clean, sqrt_p)


def _wma(data: list[float], period: int) -> list[float]:
    """Weighted Moving Average (helper)."""
    n = len(data)
    result = [NaN] * n
    if period > n:
        return result
    weights = list(range(1, period + 1))
    w_sum = sum(weights)
    for i in range(period - 1, n):
        s = sum(data[i - period + 1 + j] * weights[j] for j in range(period))
        result[i] = s / w_sum
    return result


def ichimoku(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    tenkan_period: int = 9,
    kijun_period: int = 26,
    senkou_b_period: int = 52,
    displacement: int = 26,
) -> dict[str, list[float]]:
    """Ichimoku Cloud — returns dict with tenkan, kijun, senkou_a, senkou_b, chikou."""
    n = len(closes)

    def _mid(arr, p, i):
        s = max(0, i - p + 1)
        return (max(arr[s:i+1]) + min(arr[s:i+1])) / 2.0

    tenkan = [NaN] * n
    kijun = [NaN] * n
    senkou_a = [NaN] * (n + displacement)
    senkou_b = [NaN] * (n + displacement)
    chikou = [NaN] * n

    for i in range(n):
        if i >= tenkan_period - 1:
            tenkan[i] = _mid(highs, tenkan_period, i)
        if i >= kijun_period - 1:
            kijun[i] = _mid(highs, kijun_period, i)
            # Kijun uses highs and lows
            kijun[i] = (_mid(highs, kijun_period, i) + _mid(lows, kijun_period, i)) / 2.0 if i >= kijun_period - 1 else NaN
        # Fix tenkan to also use both
        if i >= tenkan_period - 1:
            tenkan[i] = (_mid(highs, tenkan_period, i) + _mid(lows, tenkan_period, i)) / 2.0

        # Senkou A = (tenkan + kijun) / 2, displaced forward
        if not (math.isnan(tenkan[i]) or math.isnan(kijun[i])):
            fwd = i + displacement
            if fwd < len(senkou_a):
                senkou_a[fwd] = (tenkan[i] + kijun[i]) / 2.0

        # Senkou B = mid(high, low, senkou_b_period), displaced forward
        if i >= senkou_b_period - 1:
            mid_b = (_mid(highs, senkou_b_period, i) + _mid(lows, senkou_b_period, i)) / 2.0
            fwd = i + displacement
            if fwd < len(senkou_b):
                senkou_b[fwd] = mid_b

        # Chikou = close displaced backward
        bk = i - displacement
        if bk >= 0:
            chikou[bk] = closes[i]

    # Trim senkou to n length
    senkou_a = senkou_a[:n]
    senkou_b = senkou_b[:n]

    return {
        "tenkan": tenkan,
        "kijun": kijun,
        "senkou_a": senkou_a,
        "senkou_b": senkou_b,
        "chikou": chikou,
    }


def supertrend(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 10,
    multiplier: float = 3.0,
) -> tuple[list[float], list[float]]:
    """Supertrend — returns (level, direction).

    direction[i] = 1.0 (uptrend/bullish) or -1.0 (downtrend/bearish).
    """
    n = len(closes)
    atr_vals = atr(highs, lows, closes, period)
    level = [NaN] * n
    direction = [NaN] * n

    upper_band = [NaN] * n
    lower_band = [NaN] * n

    for i in range(period, n):
        if math.isnan(atr_vals[i]):
            continue
        hl2 = (highs[i] + lows[i]) / 2.0
        upper_band[i] = hl2 + multiplier * atr_vals[i]
        lower_band[i] = hl2 - multiplier * atr_vals[i]

        # Adjust bands
        if i > period and not math.isnan(upper_band[i - 1]):
            if closes[i - 1] <= upper_band[i - 1]:
                upper_band[i] = min(upper_band[i], upper_band[i - 1])
        if i > period and not math.isnan(lower_band[i - 1]):
            if closes[i - 1] >= lower_band[i - 1]:
                lower_band[i] = max(lower_band[i], lower_band[i - 1])

        # Direction
        if i == period:
            direction[i] = 1.0 if closes[i] > upper_band[i] else -1.0
        elif not math.isnan(direction[i - 1]):
            prev_dir = direction[i - 1]
            if prev_dir == 1.0:
                direction[i] = 1.0 if closes[i] >= lower_band[i] else -1.0
            else:
                direction[i] = -1.0 if closes[i] <= upper_band[i] else 1.0
        else:
            direction[i] = 1.0

        level[i] = lower_band[i] if direction[i] == 1.0 else upper_band[i]

    return level, direction


def donchian_channel(
    highs: list[float],
    lows: list[float],
    period: int = 20,
) -> tuple[list[float], list[float], list[float]]:
    """Donchian Channel — returns (upper, middle, lower)."""
    n = len(highs)
    upper = [NaN] * n
    lower = [NaN] * n
    middle = [NaN] * n
    for i in range(period - 1, n):
        h = max(highs[i - period + 1: i + 1])
        l = min(lows[i - period + 1: i + 1])
        upper[i] = h
        lower[i] = l
        middle[i] = (h + l) / 2.0
    return upper, middle, lower


def keltner_channel(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    ema_period: int = 20,
    atr_period: int = 10,
    multiplier: float = 2.0,
) -> tuple[list[float], list[float], list[float]]:
    """Keltner Channel — returns (upper, middle, lower)."""
    n = len(closes)
    mid = ema(closes, ema_period)
    atr_vals = atr(highs, lows, closes, atr_period)
    upper = [NaN] * n
    lower = [NaN] * n
    for i in range(n):
        if not (math.isnan(mid[i]) or math.isnan(atr_vals[i])):
            upper[i] = mid[i] + multiplier * atr_vals[i]
            lower[i] = mid[i] - multiplier * atr_vals[i]
    return upper, mid, lower


def parabolic_sar(
    highs: list[float],
    lows: list[float],
    af_start: float = 0.02,
    af_step: float = 0.02,
    af_max: float = 0.20,
) -> list[float]:
    """Parabolic SAR."""
    n = len(highs)
    if n < 2:
        return [NaN] * n
    result = [NaN] * n
    is_long = highs[1] > highs[0]
    af = af_start
    ep = highs[0] if is_long else lows[0]
    sar = lows[0] if is_long else highs[0]

    for i in range(1, n):
        prev_sar = sar
        sar = prev_sar + af * (ep - prev_sar)

        if is_long:
            sar = min(sar, lows[i - 1])
            if i >= 2:
                sar = min(sar, lows[i - 2])
            if lows[i] < sar:
                is_long = False
                sar = ep
                ep = lows[i]
                af = af_start
            else:
                if highs[i] > ep:
                    ep = highs[i]
                    af = min(af + af_step, af_max)
        else:
            sar = max(sar, highs[i - 1])
            if i >= 2:
                sar = max(sar, highs[i - 2])
            if highs[i] > sar:
                is_long = True
                sar = ep
                ep = highs[i]
                af = af_start
            else:
                if lows[i] < ep:
                    ep = lows[i]
                    af = min(af + af_step, af_max)

        result[i] = sar
    return result


# ── Oscillators ─────────────────────────────────────────────────────

def cci(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 20,
) -> list[float]:
    """Commodity Channel Index."""
    n = len(closes)
    result = [NaN] * n
    tp = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(n)]
    for i in range(period - 1, n):
        window = tp[i - period + 1: i + 1]
        mean = sum(window) / period
        md = sum(abs(v - mean) for v in window) / period
        if md != 0:
            result[i] = (tp[i] - mean) / (0.015 * md)
        else:
            result[i] = 0.0
    return result


def williams_r(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> list[float]:
    """Williams %R."""
    n = len(closes)
    result = [NaN] * n
    for i in range(period - 1, n):
        hh = max(highs[i - period + 1: i + 1])
        ll = min(lows[i - period + 1: i + 1])
        if hh != ll:
            result[i] = -100.0 * (hh - closes[i]) / (hh - ll)
        else:
            result[i] = -50.0
    return result


def mfi(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
    period: int = 14,
) -> list[float]:
    """Money Flow Index."""
    n = len(closes)
    result = [NaN] * n
    if n < period + 1:
        return result
    tp = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(n)]
    mf = [tp[i] * volumes[i] for i in range(n)]

    for i in range(period, n):
        pos = neg = 0.0
        for j in range(i - period + 1, i + 1):
            if j > 0 and tp[j] > tp[j - 1]:
                pos += mf[j]
            elif j > 0:
                neg += mf[j]
        if neg == 0:
            result[i] = 100.0
        else:
            result[i] = 100.0 - 100.0 / (1.0 + pos / neg)
    return result


def stochastic_rsi(
    data: list[float],
    rsi_period: int = 14,
    stoch_period: int = 14,
    k_smooth: int = 3,
    d_smooth: int = 3,
) -> tuple[list[float], list[float]]:
    """Stochastic RSI — returns (%K, %D)."""
    rsi_vals = rsi(data, rsi_period)
    n = len(data)
    raw_k = [NaN] * n

    for i in range(n):
        if i < rsi_period + stoch_period:
            continue
        window = []
        for j in range(i - stoch_period + 1, i + 1):
            if not math.isnan(rsi_vals[j]):
                window.append(rsi_vals[j])
        if len(window) < stoch_period:
            continue
        hh = max(window)
        ll = min(window)
        if hh != ll and not math.isnan(rsi_vals[i]):
            raw_k[i] = (rsi_vals[i] - ll) / (hh - ll) * 100.0
        else:
            raw_k[i] = 50.0

    # Smooth K
    valid_k = [v for v in raw_k if not math.isnan(v)]
    sk = sma(valid_k, k_smooth) if len(valid_k) >= k_smooth else valid_k
    k_line = [NaN] * n
    j = 0
    for i in range(n):
        if not math.isnan(raw_k[i]):
            k_line[i] = sk[j] if j < len(sk) else NaN
            j += 1

    # D line
    valid_k2 = [v for v in k_line if not math.isnan(v)]
    sd = sma(valid_k2, d_smooth) if len(valid_k2) >= d_smooth else valid_k2
    d_line = [NaN] * n
    j = 0
    for i in range(n):
        if not math.isnan(k_line[i]):
            d_line[i] = sd[j] if j < len(sd) else NaN
            j += 1

    return k_line, d_line


def roc(data: list[float], period: int = 14) -> list[float]:
    """Rate of Change."""
    n = len(data)
    result = [NaN] * n
    for i in range(period, n):
        if data[i - period] != 0:
            result[i] = ((data[i] - data[i - period]) / data[i - period]) * 100.0
        else:
            result[i] = 0.0
    return result


def awesome_oscillator(
    highs: list[float],
    lows: list[float],
    fast: int = 5,
    slow: int = 34,
) -> list[float]:
    """Awesome Oscillator = SMA(midprice, 5) − SMA(midprice, 34)."""
    n = len(highs)
    mid = [(highs[i] + lows[i]) / 2.0 for i in range(n)]
    sma_fast = sma(mid, fast)
    sma_slow = sma(mid, slow)
    result = [NaN] * n
    for i in range(n):
        if not (math.isnan(sma_fast[i]) or math.isnan(sma_slow[i])):
            result[i] = sma_fast[i] - sma_slow[i]
    return result


# ── Volume ──────────────────────────────────────────────────────────

def obv(closes: list[float], volumes: list[float]) -> list[float]:
    """On-Balance Volume."""
    n = len(closes)
    result = [NaN] * n
    if n == 0:
        return result
    result[0] = 0.0
    for i in range(1, n):
        if closes[i] > closes[i - 1]:
            result[i] = result[i - 1] + volumes[i]
        elif closes[i] < closes[i - 1]:
            result[i] = result[i - 1] - volumes[i]
        else:
            result[i] = result[i - 1]
    return result


def vwap_bands(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
    timestamps: list[float] | None = None,
    num_std: float = 2.0,
) -> tuple[list[float], list[float], list[float]]:
    """VWAP ± N standard deviations — returns (upper, vwap_line, lower)."""
    import datetime as _dt

    n = len(closes)
    vwap_line = [NaN] * n
    upper = [NaN] * n
    lower = [NaN] * n

    cum_tp_vol = 0.0
    cum_vol = 0.0
    cum_tp2_vol = 0.0
    prev_date_ord = -1

    for i in range(n):
        tp = (highs[i] + lows[i] + closes[i]) / 3.0
        vol = volumes[i] if volumes[i] > 0 else 1.0

        if timestamps and len(timestamps) == n:
            dt = _dt.datetime.fromtimestamp(timestamps[i], tz=_dt.timezone.utc)
            d_ord = dt.toordinal()
            if prev_date_ord != -1 and d_ord != prev_date_ord:
                cum_tp_vol = cum_vol = cum_tp2_vol = 0.0
            prev_date_ord = d_ord

        cum_tp_vol += tp * vol
        cum_vol += vol
        cum_tp2_vol += tp * tp * vol

        if cum_vol > 0:
            v = cum_tp_vol / cum_vol
            vwap_line[i] = v
            var = cum_tp2_vol / cum_vol - v * v
            std = math.sqrt(max(var, 0))
            upper[i] = v + num_std * std
            lower[i] = v - num_std * std

    return upper, vwap_line, lower


def ad_line(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
) -> list[float]:
    """Accumulation/Distribution Line."""
    n = len(closes)
    result = [NaN] * n
    if n == 0:
        return result
    cum = 0.0
    for i in range(n):
        hl = highs[i] - lows[i]
        if hl > 0:
            mfm = ((closes[i] - lows[i]) - (highs[i] - closes[i])) / hl
        else:
            mfm = 0.0
        cum += mfm * volumes[i]
        result[i] = cum
    return result


def cmf(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
    period: int = 20,
) -> list[float]:
    """Chaikin Money Flow."""
    n = len(closes)
    result = [NaN] * n
    mfv = [0.0] * n
    for i in range(n):
        hl = highs[i] - lows[i]
        if hl > 0:
            mfm = ((closes[i] - lows[i]) - (highs[i] - closes[i])) / hl
        else:
            mfm = 0.0
        mfv[i] = mfm * volumes[i]

    for i in range(period - 1, n):
        sv = sum(volumes[i - period + 1: i + 1])
        if sv > 0:
            result[i] = sum(mfv[i - period + 1: i + 1]) / sv
        else:
            result[i] = 0.0
    return result


def volume_profile(
    closes: list[float],
    volumes: list[float],
    num_bins: int = 24,
) -> dict[str, list[float]]:
    """Simplified volume profile — returns {price_levels, volume_at_price}.

    Not bar-indexed; returns aggregated histogram.
    """
    if not closes:
        return {"price_levels": [], "volume_at_price": []}
    mn = min(closes)
    mx = max(closes)
    if mn == mx:
        return {"price_levels": [mn], "volume_at_price": [sum(volumes)]}
    bin_size = (mx - mn) / num_bins
    levels = [mn + (i + 0.5) * bin_size for i in range(num_bins)]
    vol_at = [0.0] * num_bins
    for c, v in zip(closes, volumes):
        idx = min(int((c - mn) / bin_size), num_bins - 1)
        vol_at[idx] += v
    return {"price_levels": levels, "volume_at_price": vol_at}


# ── Volatility ──────────────────────────────────────────────────────

def atr_bands(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    atr_period: int = 14,
    multiplier: float = 2.0,
    basis: str = "ema",
    basis_period: int = 20,
) -> tuple[list[float], list[float], list[float]]:
    """ATR Bands: middle ± ATR×multiplier — returns (upper, middle, lower)."""
    n = len(closes)
    mid = ema(closes, basis_period) if basis == "ema" else sma(closes, basis_period)
    atr_vals = atr(highs, lows, closes, atr_period)
    upper = [NaN] * n
    lower = [NaN] * n
    for i in range(n):
        if not (math.isnan(mid[i]) or math.isnan(atr_vals[i])):
            upper[i] = mid[i] + multiplier * atr_vals[i]
            lower[i] = mid[i] - multiplier * atr_vals[i]
    return upper, mid, lower


def historical_volatility(
    closes: list[float],
    period: int = 20,
    annualize: float = 252.0,
) -> list[float]:
    """Rolling historical volatility (annualized std dev of log returns)."""
    n = len(closes)
    result = [NaN] * n
    if n < period + 1:
        return result
    log_ret = [NaN] * n
    for i in range(1, n):
        if closes[i] > 0 and closes[i - 1] > 0:
            log_ret[i] = math.log(closes[i] / closes[i - 1])
    for i in range(period, n):
        window = [log_ret[j] for j in range(i - period + 1, i + 1) if not math.isnan(log_ret[j])]
        if len(window) >= period // 2:
            mean = sum(window) / len(window)
            var = sum((x - mean) ** 2 for x in window) / len(window)
            result[i] = math.sqrt(var * annualize)
    return result


def stddev_channel(
    closes: list[float],
    period: int = 20,
    num_std: float = 2.0,
) -> tuple[list[float], list[float], list[float]]:
    """Standard Deviation Channel: linear regression ± N×σ.

    Returns (upper, regression_line, lower).
    """
    n = len(closes)
    upper = [NaN] * n
    middle = [NaN] * n
    lower = [NaN] * n

    for i in range(period - 1, n):
        window = closes[i - period + 1: i + 1]
        # Linear regression
        x_mean = (period - 1) / 2.0
        y_mean = sum(window) / period
        num = sum((j - x_mean) * (window[j] - y_mean) for j in range(period))
        den = sum((j - x_mean) ** 2 for j in range(period))
        slope = num / den if den != 0 else 0.0
        intercept = y_mean - slope * x_mean
        reg_val = intercept + slope * (period - 1)

        # Standard deviation of residuals
        residuals = [window[j] - (intercept + slope * j) for j in range(period)]
        var = sum(r ** 2 for r in residuals) / period
        std = math.sqrt(var)

        middle[i] = reg_val
        upper[i] = reg_val + num_std * std
        lower[i] = reg_val - num_std * std

    return upper, middle, lower


# ── Smart Money / ICT Concepts ──────────────────────────────────────

def fair_value_gaps(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    opens: list[float],
) -> tuple[list[float], list[float]]:
    """Fair Value Gap detection (bullish upper, bearish lower).

    A bullish FVG:  bar[i-2].high < bar[i].low  (gap UP between bar i-2 high and bar i low)
    A bearish FVG:  bar[i-2].low > bar[i].high  (gap DOWN between bar i-2 low and bar i high)

    Returns (bullish_fvg_level, bearish_fvg_level) — persists until filled.
    """
    n = len(highs)
    bull = [NaN] * n
    bear = [NaN] * n
    current_bull = NaN
    current_bear = NaN

    for i in range(2, n):
        # Bullish FVG: gap between bar i-2 high and bar i low
        if lows[i] > highs[i - 2]:
            current_bull = (lows[i] + highs[i - 2]) / 2.0
        # Bearish FVG
        if highs[i] < lows[i - 2]:
            current_bear = (highs[i] + lows[i - 2]) / 2.0

        # Check if filled
        if not math.isnan(current_bull) and lows[i] <= current_bull:
            current_bull = NaN
        if not math.isnan(current_bear) and highs[i] >= current_bear:
            current_bear = NaN

        bull[i] = current_bull
        bear[i] = current_bear

    return bull, bear


def order_blocks(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    opens: list[float],
    swing_lookback: int = 5,
    impulse_mult: float = 2.0,
) -> tuple[list[float], list[float]]:
    """Order Block detection — returns (bullish_ob_level, bearish_ob_level).

    Bullish OB: last bearish candle before a strong bullish impulse move.
    Bearish OB: last bullish candle before a strong bearish impulse move.
    """
    n = len(closes)
    bull_ob = [NaN] * n
    bear_ob = [NaN] * n
    current_bull = NaN
    current_bear = NaN

    if n < swing_lookback + 2:
        return bull_ob, bear_ob

    # Average candle body for impulse detection
    avg_body = 0.0
    for i in range(1, min(50, n)):
        avg_body += abs(closes[i] - opens[i])
    avg_body /= min(49, n - 1)

    for i in range(swing_lookback, n):
        body = abs(closes[i] - opens[i])
        is_bullish_candle = closes[i] > opens[i]
        is_impulse = body > avg_body * impulse_mult

        if is_impulse and is_bullish_candle:
            # Look back for last bearish candle
            for j in range(i - 1, max(i - swing_lookback - 1, 0), -1):
                if closes[j] < opens[j]:
                    current_bull = (highs[j] + lows[j]) / 2.0
                    break

        if is_impulse and not is_bullish_candle:
            for j in range(i - 1, max(i - swing_lookback - 1, 0), -1):
                if closes[j] > opens[j]:
                    current_bear = (highs[j] + lows[j]) / 2.0
                    break

        # Update running average
        avg_body = avg_body * 0.99 + abs(closes[i] - opens[i]) * 0.01

        bull_ob[i] = current_bull
        bear_ob[i] = current_bear

    return bull_ob, bear_ob


def liquidity_sweeps(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    lookback: int = 20,
) -> tuple[list[float], list[float]]:
    """Liquidity sweep detection — returns (sweep_high, sweep_low).

    A sweep high occurs when price pierces above a recent swing high
    then closes back below it.  A sweep low is the inverse.
    """
    n = len(closes)
    sweep_hi = [NaN] * n
    sweep_lo = [NaN] * n

    for i in range(lookback + 1, n):
        recent_high = max(highs[i - lookback: i])
        recent_low = min(lows[i - lookback: i])

        # Sweep high: wick above recent high, close below
        if highs[i] > recent_high and closes[i] < recent_high:
            sweep_hi[i] = recent_high

        # Sweep low: wick below recent low, close above
        if lows[i] < recent_low and closes[i] > recent_low:
            sweep_lo[i] = recent_low

    return sweep_hi, sweep_lo


# ── Session / Time ──────────────────────────────────────────────────

def session_high_low(
    highs: list[float],
    lows: list[float],
    timestamps: list[float],
    session_start_utc: int = 8,
    session_end_utc: int = 17,
) -> tuple[list[float], list[float]]:
    """Session High/Low — returns (session_high, session_low).

    Configurable UTC hours for session boundaries.
    Default: 08:00-17:00 UTC (London + NY overlap).
    """
    import datetime as _dt

    n = len(highs)
    s_high = [NaN] * n
    s_low = [NaN] * n

    current_high = -math.inf
    current_low = math.inf
    in_session = False

    for i in range(n):
        dt = _dt.datetime.fromtimestamp(timestamps[i], tz=_dt.timezone.utc)
        hour = dt.hour

        if session_start_utc <= hour < session_end_utc:
            if not in_session:
                current_high = highs[i]
                current_low = lows[i]
                in_session = True
            else:
                current_high = max(current_high, highs[i])
                current_low = min(current_low, lows[i])
            s_high[i] = current_high
            s_low[i] = current_low
        else:
            in_session = False
            if not math.isinf(current_high):
                s_high[i] = current_high
                s_low[i] = current_low

    return s_high, s_low


def previous_day_levels(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    timestamps: list[float],
) -> dict[str, list[float]]:
    """Previous Day High/Low/Close — returns {pdh, pdl, pdc}.

    Each value persists throughout the current day until the next day starts.
    """
    import datetime as _dt

    n = len(closes)
    out = {"pdh": [NaN] * n, "pdl": [NaN] * n, "pdc": [NaN] * n}
    if n == 0:
        return out

    prev_h = prev_l = prev_c = NaN
    day_h = highs[0]
    day_l = lows[0]
    day_c = closes[0]
    prev_date = _dt.datetime.fromtimestamp(timestamps[0], tz=_dt.timezone.utc).toordinal()

    for i in range(n):
        dt = _dt.datetime.fromtimestamp(timestamps[i], tz=_dt.timezone.utc)
        d_ord = dt.toordinal()
        if d_ord != prev_date:
            prev_h = day_h
            prev_l = day_l
            prev_c = day_c
            day_h = highs[i]
            day_l = lows[i]
            day_c = closes[i]
            prev_date = d_ord
        else:
            day_h = max(day_h, highs[i])
            day_l = min(day_l, lows[i])
            day_c = closes[i]

        out["pdh"][i] = prev_h
        out["pdl"][i] = prev_l
        out["pdc"][i] = prev_c

    return out


def weekly_open(
    opens: list[float],
    timestamps: list[float],
) -> list[float]:
    """Weekly Open — the opening price of the current trading week (Monday)."""
    import datetime as _dt

    n = len(opens)
    result = [NaN] * n
    current_wo = NaN
    prev_week = -1

    for i in range(n):
        dt = _dt.datetime.fromtimestamp(timestamps[i], tz=_dt.timezone.utc)
        iso_week = dt.isocalendar()[1]  # ISO week number
        iso_year = dt.isocalendar()[0]
        week_key = iso_year * 100 + iso_week
        if week_key != prev_week:
            current_wo = opens[i]
            prev_week = week_key
        result[i] = current_wo
    return result


def kill_zones(
    timestamps: list[float],
    london_start: int = 2,
    london_end: int = 5,
    ny_start: int = 7,
    ny_end: int = 10,
) -> tuple[list[float], list[float]]:
    """Kill Zone markers — returns (london_kz, ny_kz).

    Value is 1.0 inside kill zone, 0.0 outside.
    Default: London 02:00-05:00 UTC, NY 07:00-10:00 UTC.
    """
    import datetime as _dt

    n = len(timestamps)
    london = [0.0] * n
    ny = [0.0] * n

    for i in range(n):
        dt = _dt.datetime.fromtimestamp(timestamps[i], tz=_dt.timezone.utc)
        h = dt.hour
        if london_start <= h < london_end:
            london[i] = 1.0
        if ny_start <= h < ny_end:
            ny[i] = 1.0

    return london, ny
