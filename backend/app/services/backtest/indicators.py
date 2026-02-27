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
