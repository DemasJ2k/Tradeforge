"""
Data validation and cleaning for the V2 backtesting engine.

Phase 1E — Data Layer Hardening

Provides:
  - Timestamp parsing with timezone-aware handling (any offset → UTC)
  - OHLCV relationship validation (H >= L, O/C within H-L)
  - Duplicate bar removal (same timestamp)
  - Gap detection (intra-session vs expected weekend/holiday gaps)
  - Monotonic timestamp enforcement
  - Comprehensive validation report

Usage:
    from app.services.backtest.v2.engine.data_validation import (
        validate_and_clean, parse_timestamp, ValidationReport,
    )

    report = validate_and_clean(bars)      # mutates list in place
    ts     = parse_timestamp("2024-01-01 12:00:00+03:00")
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Sequence

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────
# Timestamp Parsing (Phase 1E-a)
# ────────────────────────────────────────────────────────────────────

# Formats WITHOUT embedded timezone (assumed UTC)
_NAIVE_FORMATS: list[str] = [
    "%Y.%m.%d %H:%M:%S",
    "%Y.%m.%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%Y%m%d %H%M%S",
    "%Y%m%d",
]

# Regex to detect trailing timezone offset: +HH:MM, -HH:MM, +HHMM, -HHMM, Z
_TZ_OFFSET_RE = re.compile(
    r"([+-])(\d{2}):?(\d{2})$"
)
_TRAILING_Z_RE = re.compile(r"Z$", re.IGNORECASE)


def parse_timestamp(val: str) -> float:
    """Parse a datetime string → UTC Unix timestamp (float seconds).

    Handles:
      - Numeric (already Unix timestamp)
      - ISO 8601 with offset (``2024-01-01T12:00:00+03:00`` → UTC)
      - ``Z`` suffix (UTC)
      - 11 naive formats (assumed UTC)

    Returns NaN if unparseable.
    """
    val = val.strip()

    # ── fast path: already a number ─────────────────────────────
    try:
        return float(val)
    except ValueError:
        pass

    # ── Python 3.11+ fromisoformat (handles offsets natively) ───
    try:
        dt = datetime.fromisoformat(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        pass

    # ── Remove trailing 'Z' (Zulu / UTC marker) ────────────────
    cleaned = _TRAILING_Z_RE.sub("", val)
    if cleaned != val:
        # Retry fromisoformat without trailing Z
        try:
            dt = datetime.fromisoformat(cleaned)
            dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except (ValueError, TypeError):
            pass

    # ── Strip explicit offset, parse naive, then apply offset ───
    m = _TZ_OFFSET_RE.search(cleaned)
    if m:
        sign_str, hh, mm = m.group(1), int(m.group(2)), int(m.group(3))
        offset_secs = (hh * 3600 + mm * 60) * (1 if sign_str == "+" else -1)
        raw = cleaned[: m.start()].rstrip()
        for fmt in _NAIVE_FORMATS:
            try:
                dt = datetime.strptime(raw, fmt)
                tz = timezone(timedelta(seconds=offset_secs))
                dt = dt.replace(tzinfo=tz)
                return dt.timestamp()  # converts to UTC
            except ValueError:
                continue

    # ── Naive formats (assumed UTC) ─────────────────────────────
    for fmt in _NAIVE_FORMATS:
        try:
            dt = datetime.strptime(cleaned, fmt).replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue

    return float("nan")


# ────────────────────────────────────────────────────────────────────
# Validation Report
# ────────────────────────────────────────────────────────────────────

@dataclass
class GapInfo:
    """A detected gap between two successive bars."""
    index: int              # bar index of the SECOND bar (after the gap)
    timestamp_before: float
    timestamp_after: float
    gap_seconds: float
    expected_seconds: float
    is_weekend: bool = False


@dataclass
class ValidationReport:
    """Result of validate_and_clean()."""
    original_count: int = 0
    final_count: int = 0

    # Counts of issues found & fixed
    duplicates_removed: int = 0
    unsorted_fixed: bool = False
    ohlc_violations: int = 0        # bars where H<L or O/C out of range
    nan_bars_removed: int = 0       # bars with NaN price values
    unparseable_timestamps: int = 0 # timestamps that couldn't be parsed

    # Gap analysis
    gaps: list[GapInfo] = field(default_factory=list)
    median_bar_interval_s: float = 0.0  # detected bar interval in seconds

    @property
    def is_clean(self) -> bool:
        """True if no issues were found."""
        return (
            self.duplicates_removed == 0
            and not self.unsorted_fixed
            and self.ohlc_violations == 0
            and self.nan_bars_removed == 0
            and self.unparseable_timestamps == 0
        )

    def summary(self) -> str:
        lines = [f"Bars: {self.original_count} → {self.final_count}"]
        if self.duplicates_removed:
            lines.append(f"  Duplicates removed: {self.duplicates_removed}")
        if self.unsorted_fixed:
            lines.append("  Unsorted timestamps: re-sorted")
        if self.ohlc_violations:
            lines.append(f"  OHLC violations repaired: {self.ohlc_violations}")
        if self.nan_bars_removed:
            lines.append(f"  NaN bars removed: {self.nan_bars_removed}")
        if self.unparseable_timestamps:
            lines.append(f"  Unparseable timestamps dropped: {self.unparseable_timestamps}")
        if self.gaps:
            non_weekend = [g for g in self.gaps if not g.is_weekend]
            lines.append(f"  Gaps detected: {len(self.gaps)} total, {len(non_weekend)} non-weekend")
        if self.median_bar_interval_s:
            lines.append(f"  Median bar interval: {self.median_bar_interval_s:.0f}s")
        return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────
# Validation & Cleaning Functions
# ────────────────────────────────────────────────────────────────────

def _is_weekend(ts: float) -> bool:
    """Check if a Unix timestamp falls on Saturday or Sunday."""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.weekday() >= 5  # 5 = Saturday, 6 = Sunday


def _median(values: list[float]) -> float:
    """Simple median for a sorted list."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def validate_and_clean(
    bars: list,
    *,
    gap_threshold_mult: float = 3.0,
    repair_ohlc: bool = True,
    remove_nan_bars: bool = True,
) -> ValidationReport:
    """Validate and clean a list of bar objects IN PLACE.

    Accepts V1 Bar objects (with ``.time``, ``.open``, etc.) or dicts
    with ``"time"``/``"open"``/etc. keys.

    Operations (in order):
      1. Remove bars with NaN/None timestamps or prices
      2. Remove duplicate timestamps (keep first)
      3. Sort by timestamp if not already sorted
      4. Repair OHLC violations (clamp O/C to [L, H])
      5. Detect gaps (mark weekend gaps separately)

    Parameters
    ----------
    bars : list
        Mutable list of bar objects or dicts. Modified in place.
    gap_threshold_mult : float
        A gap is flagged if interval > median_interval × this multiplier.
    repair_ohlc : bool
        If True, clamp O/C within [L, H] range.
    remove_nan_bars : bool
        If True, remove bars where any OHLCV value is NaN.

    Returns
    -------
    ValidationReport with details of all fixes applied.
    """
    report = ValidationReport(original_count=len(bars))

    if not bars:
        return report

    # Helpers to read/write bar fields regardless of type (Bar object or dict)
    def _get(bar, key: str, default=None):
        if isinstance(bar, dict):
            return bar.get(key, default)
        return getattr(bar, key, default)

    def _set(bar, key: str, val):
        if isinstance(bar, dict):
            bar[key] = val
        else:
            setattr(bar, key, val)

    # ── 1. Remove bars with bad timestamps or NaN prices ────────
    good = []
    for b in bars:
        ts = _get(b, "time")
        if ts is None or (isinstance(ts, float) and math.isnan(ts)):
            report.nan_bars_removed += 1
            continue

        if remove_nan_bars:
            o, h, l, c = _get(b, "open"), _get(b, "high"), _get(b, "low"), _get(b, "close")
            if any(
                v is None or (isinstance(v, float) and math.isnan(v))
                for v in (o, h, l, c)
            ):
                report.nan_bars_removed += 1
                continue

        good.append(b)

    # ── 2. Sort by timestamp ────────────────────────────────────
    timestamps = [_get(b, "time") for b in good]
    is_sorted = all(timestamps[i] <= timestamps[i + 1] for i in range(len(timestamps) - 1)) if len(timestamps) > 1 else True
    if not is_sorted:
        good.sort(key=lambda b: _get(b, "time"))
        report.unsorted_fixed = True

    # ── 3. Remove duplicates (same timestamp) ──────────────────
    if len(good) > 1:
        deduped = [good[0]]
        for i in range(1, len(good)):
            if _get(good[i], "time") != _get(good[i - 1], "time"):
                deduped.append(good[i])
            else:
                report.duplicates_removed += 1
        good = deduped

    # ── 4. Repair OHLC violations ──────────────────────────────
    if repair_ohlc:
        for b in good:
            o, h, l, c = _get(b, "open"), _get(b, "high"), _get(b, "low"), _get(b, "close")
            fixed = False

            # Ensure H >= L
            if h < l:
                _set(b, "high", l)
                _set(b, "low", h)
                h, l = l, h
                fixed = True

            # Clamp O to [L, H]
            if o < l:
                _set(b, "open", l)
                fixed = True
            elif o > h:
                _set(b, "open", h)
                fixed = True

            # Clamp C to [L, H]
            if c < l:
                _set(b, "close", l)
                fixed = True
            elif c > h:
                _set(b, "close", h)
                fixed = True

            if fixed:
                report.ohlc_violations += 1

    # ── 5. Gap detection ───────────────────────────────────────
    if len(good) >= 2:
        intervals = []
        for i in range(1, len(good)):
            diff = _get(good[i], "time") - _get(good[i - 1], "time")
            if diff > 0:
                intervals.append(diff)

        median_interval = _median(intervals) if intervals else 0.0
        report.median_bar_interval_s = median_interval

        if median_interval > 0:
            threshold = median_interval * gap_threshold_mult
            for i in range(1, len(good)):
                ts_before = _get(good[i - 1], "time")
                ts_after = _get(good[i], "time")
                diff = ts_after - ts_before
                if diff > threshold:
                    # Check if gap spans a weekend
                    is_wknd = _is_weekend(ts_before) or _is_weekend(ts_after)
                    report.gaps.append(GapInfo(
                        index=i,
                        timestamp_before=ts_before,
                        timestamp_after=ts_after,
                        gap_seconds=diff,
                        expected_seconds=median_interval,
                        is_weekend=is_wknd,
                    ))

    # ── Write back (bars is a mutable list) ─────────────────────
    bars.clear()
    bars.extend(good)
    report.final_count = len(bars)

    if not report.is_clean:
        logger.info("Data validation: %s", report.summary())

    return report


def validate_timestamps_only(
    timestamps: Sequence[float],
) -> tuple[bool, list[int]]:
    """Quick check that timestamps are monotonically increasing.

    Returns (is_monotonic, list_of_bad_indices).
    """
    bad = []
    for i in range(1, len(timestamps)):
        if timestamps[i] <= timestamps[i - 1]:
            bad.append(i)
    return len(bad) == 0, bad
