"""
Phase 1E — Data Layer Hardening Tests

Tests:
  1. parse_timestamp: naive / ISO 8601 + offset / Z suffix / numeric
  2. validate_and_clean: dedup, sort, OHLC repair, gap detection
  3. Multi-timeframe: resample M5 → H1, index mapping, no look-ahead
  4. HTF value access via StrategyContext
  5. Tick data: load, feed into queue
  6. DataHandler.add_htf shortcut
  7. CSV loader: data validation is applied
  8. detect_timeframe from timestamps
"""

import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import pytest
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

# ── Imports under test ──────────────────────────────────────────────

from app.services.backtest.v2.engine.data_validation import (
    parse_timestamp,
    validate_and_clean,
    validate_timestamps_only,
    ValidationReport,
)
from app.services.backtest.v2.engine.data_handler import (
    DataHandler,
    SymbolData,
    BarData,
    TickStore,
    TickData,
    parse_timeframe,
    detect_timeframe,
    TIMEFRAME_SECONDS,
)
from app.services.backtest.v2.engine.strategy_base import StrategyBase, StrategyContext
from app.services.backtest.v2.engine.events import BarEvent, TickEvent, EventType
from app.services.backtest.v2.engine.event_queue import EventQueue


# ── Helper: simple Bar dataclass (mimics V1 Bar) ───────────────────

@dataclass
class Bar:
    time: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0


def make_bars(n: int, interval_s: int = 300, start_ts: float = 1_700_000_000.0) -> list[Bar]:
    """Generate n bars with given interval (default M5 = 300s)."""
    bars = []
    for i in range(n):
        ts = start_ts + i * interval_s
        price = 2000.0 + i * 0.5
        bars.append(Bar(
            time=ts,
            open=price,
            high=price + 1.0,
            low=price - 0.5,
            close=price + 0.3,
            volume=100.0 + i,
        ))
    return bars


# ════════════════════════════════════════════════════════════════════
#  Test 1: parse_timestamp
# ════════════════════════════════════════════════════════════════════

class TestParseTimestamp:

    def test_numeric(self):
        assert parse_timestamp("1700000000.5") == 1700000000.5

    def test_naive_utc(self):
        """Naive datetime → treated as UTC."""
        ts = parse_timestamp("2024-01-15 12:30:00")
        dt = datetime(2024, 1, 15, 12, 30, 0, tzinfo=timezone.utc)
        assert abs(ts - dt.timestamp()) < 1.0

    def test_iso_with_offset(self):
        """ISO 8601 with timezone offset → converted to UTC."""
        ts = parse_timestamp("2024-01-15T12:30:00+03:00")
        # 12:30 + 03:00 = 09:30 UTC
        dt_utc = datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc)
        assert abs(ts - dt_utc.timestamp()) < 1.0

    def test_z_suffix(self):
        """Z suffix (Zulu time) → UTC."""
        ts = parse_timestamp("2024-01-15T12:30:00Z")
        dt = datetime(2024, 1, 15, 12, 30, 0, tzinfo=timezone.utc)
        assert abs(ts - dt.timestamp()) < 1.0

    def test_dot_format(self):
        """MT5-style format: YYYY.MM.DD HH:MM:SS"""
        ts = parse_timestamp("2024.01.15 12:30:00")
        dt = datetime(2024, 1, 15, 12, 30, 0, tzinfo=timezone.utc)
        assert abs(ts - dt.timestamp()) < 1.0

    def test_negative_offset(self):
        ts = parse_timestamp("2024-06-01T10:00:00-05:00")
        # 10:00 - 05:00 = 15:00 UTC
        dt_utc = datetime(2024, 6, 1, 15, 0, 0, tzinfo=timezone.utc)
        assert abs(ts - dt_utc.timestamp()) < 1.0

    def test_unparseable_returns_nan(self):
        ts = parse_timestamp("not-a-date")
        assert math.isnan(ts)


# ════════════════════════════════════════════════════════════════════
#  Test 2: validate_and_clean
# ════════════════════════════════════════════════════════════════════

class TestValidateAndClean:

    def test_removes_duplicates(self):
        bars = [
            Bar(time=100, open=1, high=2, low=0.5, close=1.5),
            Bar(time=100, open=1.1, high=2.1, low=0.6, close=1.6),
            Bar(time=200, open=2, high=3, low=1, close=2.5),
        ]
        report = validate_and_clean(bars)
        assert report.duplicates_removed == 1
        assert len(bars) == 2
        assert bars[0].time == 100
        assert bars[1].time == 200

    def test_sorts_unsorted(self):
        bars = [
            Bar(time=300, open=3, high=4, low=2, close=3.5),
            Bar(time=100, open=1, high=2, low=0.5, close=1.5),
            Bar(time=200, open=2, high=3, low=1, close=2.5),
        ]
        report = validate_and_clean(bars)
        assert report.unsorted_fixed is True
        assert [b.time for b in bars] == [100, 200, 300]

    def test_repairs_ohlc_high_low_swap(self):
        """High < Low → should swap."""
        bars = [Bar(time=100, open=2.0, high=1.0, low=3.0, close=2.5)]
        report = validate_and_clean(bars)
        assert report.ohlc_violations == 1
        assert bars[0].high == 3.0
        assert bars[0].low == 1.0

    def test_clamps_open_close(self):
        """Open/Close outside [L, H] → clamped."""
        bars = [Bar(time=100, open=5.0, high=3.0, low=1.0, close=-1.0)]
        report = validate_and_clean(bars)
        assert report.ohlc_violations == 1
        assert bars[0].open == 3.0
        assert bars[0].close == 1.0

    def test_removes_nan_bars(self):
        bars = [
            Bar(time=100, open=1, high=2, low=0.5, close=1.5),
            Bar(time=200, open=float("nan"), high=2, low=0.5, close=1.5),
            Bar(time=300, open=3, high=4, low=2, close=3.5),
        ]
        report = validate_and_clean(bars)
        assert report.nan_bars_removed == 1
        assert len(bars) == 2

    def test_gap_detection(self):
        """Large gap between bars should be flagged."""
        bars = [
            Bar(time=1000, open=1, high=2, low=0.5, close=1.5),
            Bar(time=1300, open=2, high=3, low=1, close=2.5),  # 300s gap
            Bar(time=1600, open=3, high=4, low=2, close=3.5),  # 300s gap
            Bar(time=3000, open=4, high=5, low=3, close=4.5),  # 1400s gap = >3x
        ]
        report = validate_and_clean(bars)
        assert len(report.gaps) >= 1
        big_gap = [g for g in report.gaps if g.gap_seconds > 1000]
        assert len(big_gap) == 1

    def test_clean_report(self):
        """Clean data produces is_clean=True."""
        bars = make_bars(10)
        report = validate_and_clean(bars)
        assert report.is_clean is True
        assert report.final_count == 10

    def test_dict_bars(self):
        """Works with dict-style bars too."""
        bars = [
            {"time": 100, "open": 1, "high": 2, "low": 0.5, "close": 1.5},
            {"time": 100, "open": 1.1, "high": 2.1, "low": 0.6, "close": 1.6},
        ]
        report = validate_and_clean(bars)
        assert report.duplicates_removed == 1
        assert len(bars) == 1


# ════════════════════════════════════════════════════════════════════
#  Test 3: Multi-Timeframe Resampling
# ════════════════════════════════════════════════════════════════════

class TestMultiTimeframe:

    def test_resample_m5_to_h1(self):
        """12 M5 bars (1 hour) should produce 1 or 2 H1 bars."""
        bars = make_bars(24, interval_s=300)  # 24 × 5min = 2 hours
        sd = SymbolData(symbol="TEST", timeframe_s=300)
        sd.load_bars(bars)

        htf_sd = sd.resample_to_htf("H1")
        # 2 hours of M5 data → at least 1 completed H1 bar
        assert htf_sd.bar_count >= 1
        assert htf_sd.timeframe_s == 3600

    def test_htf_ohlcv_correctness(self):
        """Check OHLC aggregation: high = max(highs), low = min(lows)."""
        # 12 M5 bars = 1 hour, all in same H1 bucket
        start = 1_700_000_000.0  # Aligned to hour boundary
        # Make start a round hour
        start = (start // 3600) * 3600
        bars = []
        for i in range(12):
            bar = Bar(
                time=start + i * 300,
                open=100 + i,
                high=110 + i,
                low=90 + i,
                close=105 + i,
                volume=50.0,
            )
            bars.append(bar)

        sd = SymbolData(symbol="TEST", timeframe_s=300)
        sd.load_bars(bars)
        htf_sd = sd.resample_to_htf("H1")

        assert htf_sd.bar_count >= 1
        # First H1 bar should aggregate all 12 M5 bars
        assert htf_sd.opens[0] == 100  # first M5 open
        assert htf_sd.highs[0] == max(110 + i for i in range(12))  # max high
        assert htf_sd.lows[0] == min(90 + i for i in range(12))   # min low
        assert htf_sd.closes[0] == 105 + 11  # last M5 close
        assert htf_sd.volumes[0] == 50.0 * 12  # sum of volumes

    def test_index_map_no_lookahead(self):
        """HTF index map should NOT allow look-ahead bias."""
        # 24 M5 bars = 2 hours → 2 H1 bars
        start = 1_700_000_000.0
        start = (start // 3600) * 3600
        bars = make_bars(24, interval_s=300, start_ts=start)
        sd = SymbolData(symbol="TEST", timeframe_s=300)
        sd.load_bars(bars)
        sd.resample_to_htf("H1")

        # During the first H1 bucket (bars 0-11), htf_bar_index_for
        # should return -1 (first bucket not yet completed)
        for i in range(11):
            idx = sd.htf_bar_index_for(i, "H1")
            assert idx == -1, f"bar {i} should not see any completed HTF bar"

        # At bar 12 (first bar of second H1 bucket), the first H1 bar
        # is now completed
        # Actually at bar 11 (last bar of first bucket), the bucket
        # is still forming or just closed, depending on implementation
        # At bar 12 (first of second bucket), first H1 is definitely done
        idx_12 = sd.htf_bar_index_for(12, "H1")
        assert idx_12 >= 0, "bar 12 should see at least one completed HTF bar"


# ════════════════════════════════════════════════════════════════════
#  Test 4: StrategyContext HTF Access
# ════════════════════════════════════════════════════════════════════

def test_ctx_htf_value():
    """StrategyContext.get_htf_value returns HTF close, no look-ahead."""
    start = (1_700_000_000 // 3600) * 3600
    bars = make_bars(36, interval_s=300, start_ts=start)  # 3 hours

    dh = DataHandler()
    dh.add_symbol("TEST", bars, point_value=1.0)
    dh.add_htf("TEST", "H1")

    ctx = StrategyContext()
    ctx._data_handler = dh

    # At bar 24 (start of 3rd hour) → 2 completed H1 bars
    ctx._bar_index = 24
    val = ctx.get_htf_value("TEST", "H1", "price.close")
    assert val is not None
    # Should be the close of the 2nd completed H1 bar
    sd = dh.get_symbol_data("TEST")
    htf_sd = sd.htf_data["H1"]
    htf_idx = sd.htf_bar_index_for(24, "H1")
    assert htf_idx >= 0
    expected = htf_sd.closes[htf_idx]
    assert val == expected

    # bars_ago=1 should give previous H1 bar
    val_prev = ctx.get_htf_value("TEST", "H1", "price.close", bars_ago=1)
    if htf_idx > 0:
        assert val_prev == htf_sd.closes[htf_idx - 1]


# ════════════════════════════════════════════════════════════════════
#  Test 5: Tick Data
# ════════════════════════════════════════════════════════════════════

class TestTickData:

    def test_load_ticks_from_dicts(self):
        ticks = [
            {"timestamp": 100.0, "bid": 2000.0, "ask": 2000.5, "last": 2000.2, "volume": 10},
            {"timestamp": 100.1, "bid": 2000.1, "ask": 2000.6, "last": 2000.3, "volume": 5},
        ]
        store = TickStore(symbol="XAUUSD")
        store.load_ticks(ticks)
        assert store.tick_count == 2
        assert store.bids[0] == 2000.0
        assert store.asks[1] == 2000.6

    def test_load_ticks_from_tuples(self):
        ticks = [
            (100.0, 2000.0, 2000.5, 2000.2, 10),
            (100.1, 2000.1, 2000.6),  # short tuple — last/volume default 0
        ]
        store = TickStore(symbol="XAUUSD")
        store.load_ticks(ticks)
        assert store.tick_count == 2
        assert store.lasts[1] == 0.0

    def test_feed_ticks_to_queue(self):
        ticks = [
            {"timestamp": 100.0, "bid": 2000.0, "ask": 2000.5},
            {"timestamp": 100.1, "bid": 2000.1, "ask": 2000.6},
        ]
        dh = DataHandler()
        dh.add_ticks("XAUUSD", ticks)
        queue = EventQueue()
        count = dh.feed_ticks(queue)
        assert count == 2
        event = queue.pop()
        assert event.event_type == EventType.TICK
        assert event.symbol == "XAUUSD"
        assert event.bid == 2000.0

    def test_tick_data_dataclass(self):
        td = TickData(timestamp=100.0, bid=1.0, ask=1.1, last=1.05, volume=100)
        store = TickStore("SYM")
        store.load_ticks([td])
        assert store.tick_count == 1
        assert store.bids[0] == 1.0


# ════════════════════════════════════════════════════════════════════
#  Test 6: DataHandler.add_htf + detect_timeframe
# ════════════════════════════════════════════════════════════════════

def test_datahandler_add_htf():
    """DataHandler.add_htf creates HTF data accessible via get_htf_value."""
    bars = make_bars(48, interval_s=300)  # 4 hours
    dh = DataHandler()
    dh.add_symbol("TEST", bars)
    htf_sd = dh.add_htf("TEST", "H1")
    assert htf_sd.bar_count >= 2

    # get_htf_value should work
    val = dh.get_htf_value("TEST", "H1", "price.close", base_bar_index=24)
    assert val is not None


def test_detect_timeframe():
    """Auto-detect bar interval from timestamps."""
    bars = make_bars(50, interval_s=600)  # M10
    sd = SymbolData(symbol="TEST")
    sd.load_bars(bars)
    tf = detect_timeframe(sd.timestamps)
    assert tf == 600


def test_parse_timeframe_labels():
    assert parse_timeframe("M5") == 300
    assert parse_timeframe("H1") == 3600
    assert parse_timeframe("D1") == 86400
    assert parse_timeframe("600") == 600


# ════════════════════════════════════════════════════════════════════
#  Test 7: validate_timestamps_only
# ════════════════════════════════════════════════════════════════════

def test_validate_timestamps_only():
    ok, bad = validate_timestamps_only([100, 200, 300, 400])
    assert ok is True
    assert bad == []

    ok2, bad2 = validate_timestamps_only([100, 300, 200, 400])
    assert ok2 is False
    assert bad2 == [2]


# ════════════════════════════════════════════════════════════════════
#  Test 8: HTF with indicators
# ════════════════════════════════════════════════════════════════════

def test_htf_with_indicators():
    """Resample to H1 and compute SMA on HTF data."""
    bars = make_bars(144, interval_s=300)  # 12 hours of M5 data
    dh = DataHandler()
    dh.add_symbol("TEST", bars)
    htf_sd = dh.add_htf(
        "TEST", "H1",
        indicator_configs=[{"id": "sma_3", "type": "SMA", "params": {"period": 3}}],
    )
    assert htf_sd.bar_count >= 6
    assert "sma_3" in htf_sd.indicator_arrays
    # SMA should have values after warmup
    sma_vals = htf_sd.indicator_arrays["sma_3"]
    non_nan = [v for v in sma_vals if not math.isnan(v)]
    assert len(non_nan) >= 3


# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
