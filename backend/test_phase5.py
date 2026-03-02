"""Phase 5 — Chart Overlay Tests.

Covers:
  5A/5B: Frontend-only components (tested via vitest in frontend/)
  5C: Backend chart-data API endpoint
       – _ChartBar / _TradeMark / _ChartDataResponse models
       – get_backtest_chart_data() logic (unit-style, no HTTP server)
"""

import math
import sys
import os
import json

sys.path.insert(0, os.path.dirname(__file__))

import pytest

# ── 5C.1: Chart data Pydantic models ────────────────────────────────

from pydantic import BaseModel


def _import_chart_models():
    """Import the private Pydantic models from the backtest router module."""
    from app.api.backtest import _ChartBar, _TradeMark, _ChartDataResponse
    return _ChartBar, _TradeMark, _ChartDataResponse


class TestChartBarModel:
    def test_fields_present(self):
        CB, _, _ = _import_chart_models()
        bar = CB(time=1700000000.0, open=100.0, high=105.0, low=95.0, close=102.0, volume=500.0)
        assert bar.time == 1700000000.0
        assert bar.open == 100.0
        assert bar.high == 105.0
        assert bar.low == 95.0
        assert bar.close == 102.0
        assert bar.volume == 500.0

    def test_roundtrip_json(self):
        CB, _, _ = _import_chart_models()
        bar = CB(time=1700000000.0, open=1.0, high=2.0, low=0.5, close=1.5, volume=100.0)
        d = bar.model_dump()
        bar2 = CB(**d)
        assert bar2.time == bar.time
        assert bar2.close == bar.close


class TestTradeMarkModel:
    def test_entry_mark(self):
        _, TM, _ = _import_chart_models()
        m = TM(time=1700000000.0, type="entry_long", price=2000.0)
        assert m.pnl is None
        assert m.label is None
        assert m.type == "entry_long"

    def test_exit_mark_with_pnl(self):
        _, TM, _ = _import_chart_models()
        m = TM(time=1700001000.0, type="exit_long", price=2050.0, pnl=50.0, label="+50")
        assert m.pnl == 50.0
        assert m.label == "+50"

    def test_all_valid_types(self):
        _, TM, _ = _import_chart_models()
        for t in ("entry_long", "entry_short", "exit_long", "exit_short"):
            m = TM(time=1.0, type=t, price=100.0)
            assert m.type == t


class TestChartDataResponseModel:
    def test_complete_response(self):
        CB, TM, CDR = _import_chart_models()
        bars = [CB(time=float(i), open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0) for i in range(5)]
        marks = [TM(time=1.0, type="entry_long", price=100.0)]
        resp = CDR(
            bars=bars,
            indicators={"sma_20": [None, None, 1.0, 1.1, 1.2]},
            timestamps=[0.0, 1.0, 2.0, 3.0, 4.0],
            trade_marks=marks,
            equity_curve=[10000.0, 10010.0, 10020.0, 10005.0, 10050.0],
        )
        assert len(resp.bars) == 5
        assert resp.indicators["sma_20"][0] is None
        assert resp.indicators["sma_20"][2] == 1.0
        assert len(resp.trade_marks) == 1
        assert len(resp.equity_curve) == 5

    def test_empty_response(self):
        _, _, CDR = _import_chart_models()
        resp = CDR(bars=[], indicators={}, timestamps=[], trade_marks=[], equity_curve=[])
        assert resp.bars == []
        assert resp.indicators == {}


# ── 5C.2: CSV→ChartBar pipeline ────────────────────────────────────

from app.services.backtest.engine import Bar  # The Bar dataclass
from app.api.backtest import _load_bars_from_csv
import tempfile, csv


def _write_temp_csv(bars_dicts: list[dict], header=True) -> str:
    """Write bar dicts to a temp CSV file and return the path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="")
    writer = csv.DictWriter(f, fieldnames=["time", "open", "high", "low", "close", "volume"])
    if header:
        writer.writeheader()
    for b in bars_dicts:
        writer.writerow(b)
    f.close()
    return f.name


def _make_bar_dicts(n: int = 100, base: float = 2000.0):
    """Generate synthetic OHLCV bar dicts."""
    import random
    random.seed(99)
    bars = []
    price = base
    for i in range(n):
        o = price
        h = o + random.uniform(1, 8)
        l = o - random.uniform(1, 8)
        c = o + random.uniform(-4, 4)
        bars.append({
            "time": str(1700000000 + i * 600),
            "open": f"{o:.2f}",
            "high": f"{h:.2f}",
            "low": f"{l:.2f}",
            "close": f"{c:.2f}",
            "volume": f"{random.uniform(100, 1000):.0f}",
        })
        price = c
    return bars


class TestLoadBarsFromCSV:
    def test_basic_load(self):
        dicts = _make_bar_dicts(50)
        path = _write_temp_csv(dicts)
        bars = _load_bars_from_csv(path, validate=False)
        assert len(bars) == 50
        assert isinstance(bars[0], Bar)
        assert bars[0].time == 1700000000
        os.unlink(path)

    def test_timestamps_monotonic(self):
        dicts = _make_bar_dicts(100)
        path = _write_temp_csv(dicts)
        bars = _load_bars_from_csv(path, validate=False)
        times = [b.time for b in bars]
        assert times == sorted(times), "Bar timestamps should be monotonically increasing"
        os.unlink(path)

    def test_empty_file(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
        f.write("time,open,high,low,close,volume\n")
        f.close()
        bars = _load_bars_from_csv(f.name, validate=False)
        assert bars == [] or len(bars) == 0
        os.unlink(f.name)


# ── 5C.3: Indicator computation from strategy configs ───────────────

from app.services.backtest.v2.engine.data_handler import SymbolData


class TestIndicatorOverlayComputation:
    """Ensure SymbolData.compute_indicators works for overlay purposes."""

    def _make_symbol_data(self, n=200):
        import random
        random.seed(42)
        bars = []
        price = 2000.0
        for i in range(n):
            o = price
            h = o + random.uniform(1, 10)
            l = o - random.uniform(1, 10)
            c = o + random.uniform(-5, 5)
            bars.append(Bar(
                time=1700000000 + i * 600,
                open=o, high=h, low=l, close=c,
                volume=random.uniform(100, 1000),
            ))
            price = c
        sd = SymbolData(symbol="TEST", timeframe_s=600)
        sd.load_bars(bars)
        return sd, bars

    def test_sma_overlay(self):
        sd, bars = self._make_symbol_data()
        sd.compute_indicators([{"id": "sma_1", "type": "SMA", "params": {"period": 20, "source": "close"}}])
        assert "sma_1" in sd.indicator_arrays
        arr = sd.indicator_arrays["sma_1"]
        assert len(arr) == len(bars)
        # First 19 should be NaN (period=20)
        assert math.isnan(arr[0])
        # After warm-up, values should be valid
        valid = [v for v in arr[20:] if not math.isnan(v)]
        assert len(valid) > 100

    def test_rsi_overlay(self):
        sd, bars = self._make_symbol_data()
        sd.compute_indicators([{"id": "rsi_1", "type": "RSI", "params": {"period": 14, "source": "close"}}])
        assert "rsi_1" in sd.indicator_arrays
        arr = sd.indicator_arrays["rsi_1"]
        valid = [v for v in arr if not math.isnan(v)]
        assert len(valid) > 100
        # RSI should be bounded [0, 100]
        for v in valid:
            assert 0 <= v <= 100

    def test_multiple_indicators(self):
        sd, bars = self._make_symbol_data()
        configs = [
            {"id": "ema_1", "type": "EMA", "params": {"period": 12, "source": "close"}},
            {"id": "ema_2", "type": "EMA", "params": {"period": 26, "source": "close"}},
            {"id": "atr_1", "type": "ATR", "params": {"period": 14}},
        ]
        sd.compute_indicators(configs)
        assert "ema_1" in sd.indicator_arrays
        assert "ema_2" in sd.indicator_arrays
        assert "atr_1" in sd.indicator_arrays

    def test_none_replacement_for_nan(self):
        """The chart-data endpoint replaces NaN with None for JSON serialization."""
        sd, _ = self._make_symbol_data()
        sd.compute_indicators([{"id": "sma_1", "type": "SMA", "params": {"period": 20, "source": "close"}}])
        arr = sd.indicator_arrays["sma_1"]
        # Simulate the endpoint's NaN → None replacement
        cleaned = [None if (v != v) else v for v in arr]
        assert None in cleaned  # Warm-up period produces NaN → None
        non_none = [v for v in cleaned if v is not None]
        assert len(non_none) > 0
        # Ensure cleaned list is JSON-serialisable (no NaN which isn't valid JSON)
        j = json.dumps(cleaned)
        assert "NaN" not in j


# ── 5C.4: Trade mark extraction logic ──────────────────────────────

class TestTradeMarkExtraction:
    """Test the trade mark building logic used in the chart-data endpoint."""

    def _extract_marks(self, stored_trades):
        """Replicate the endpoint's trade mark extraction."""
        from app.api.backtest import _TradeMark
        marks = []
        for t in stored_trades:
            entry_time = t.get("entry_time", 0)
            exit_time = t.get("exit_time", 0)
            direction = t.get("direction", "long")
            pnl = t.get("pnl", 0)

            if entry_time:
                marks.append(_TradeMark(
                    time=entry_time,
                    type=f"entry_{direction}",
                    price=t.get("entry_price", 0),
                ))
            if exit_time:
                marks.append(_TradeMark(
                    time=exit_time,
                    type=f"exit_{direction}",
                    price=t.get("exit_price", 0),
                    pnl=pnl,
                    label=f"{'+' if pnl >= 0 else ''}{pnl:.0f}",
                ))
        return marks

    def test_long_trade(self):
        trades = [{
            "entry_time": 1700000000, "exit_time": 1700001000,
            "entry_price": 2000.0, "exit_price": 2050.0,
            "direction": "long", "pnl": 50.0,
        }]
        marks = self._extract_marks(trades)
        assert len(marks) == 2
        assert marks[0].type == "entry_long"
        assert marks[0].price == 2000.0
        assert marks[1].type == "exit_long"
        assert marks[1].pnl == 50.0
        assert marks[1].label == "+50"

    def test_short_trade(self):
        trades = [{
            "entry_time": 1700000000, "exit_time": 1700001000,
            "entry_price": 2050.0, "exit_price": 2000.0,
            "direction": "short", "pnl": 50.0,
        }]
        marks = self._extract_marks(trades)
        assert marks[0].type == "entry_short"
        assert marks[1].type == "exit_short"

    def test_negative_pnl_label(self):
        trades = [{
            "entry_time": 1700000000, "exit_time": 1700001000,
            "entry_price": 2050.0, "exit_price": 2100.0,
            "direction": "short", "pnl": -50.0,
        }]
        marks = self._extract_marks(trades)
        assert marks[1].label == "-50"

    def test_multiple_trades(self):
        trades = [
            {"entry_time": 1700000000, "exit_time": 1700001000, "entry_price": 100, "exit_price": 110, "direction": "long", "pnl": 10},
            {"entry_time": 1700002000, "exit_time": 1700003000, "entry_price": 120, "exit_price": 115, "direction": "short", "pnl": 5},
        ]
        marks = self._extract_marks(trades)
        assert len(marks) == 4  # 2 entries + 2 exits
        types = [m.type for m in marks]
        assert "entry_long" in types
        assert "exit_long" in types
        assert "entry_short" in types
        assert "exit_short" in types

    def test_empty_trades(self):
        marks = self._extract_marks([])
        assert marks == []

    def test_trade_missing_exit(self):
        """Open trade with entry but no exit yet."""
        trades = [{"entry_time": 1700000000, "entry_price": 2000, "direction": "long", "pnl": 0}]
        marks = self._extract_marks(trades)
        assert len(marks) == 1
        assert marks[0].type == "entry_long"


# ── 5C.5: ChartBar from Bar conversion ─────────────────────────────

class TestBarToChartBarConversion:
    """Test the Bar → _ChartBar mapping used in the endpoint."""

    def test_conversion(self):
        from app.api.backtest import _ChartBar
        raw_bars = [
            Bar(time=1700000000, open=100.0, high=105.0, low=95.0, close=102.0, volume=500.0),
            Bar(time=1700000600, open=102.0, high=108.0, low=100.0, close=106.0, volume=600.0),
        ]
        chart_bars = [
            _ChartBar(
                time=b.time, open=b.open, high=b.high,
                low=b.low, close=b.close, volume=b.volume,
            )
            for b in raw_bars
        ]
        assert len(chart_bars) == 2
        assert chart_bars[0].time == 1700000000
        assert chart_bars[0].open == 100.0
        assert chart_bars[1].volume == 600.0


# ── 5C.6: Equity curve serialisation ───────────────────────────────

class TestEquityCurveSerialization:
    def test_equity_curve_json_safe(self):
        """Equity curve from backtest should be JSON-serialisable."""
        curve = [10000.0, 10050.5, 9980.2, 10100.0, 10200.75]
        j = json.dumps(curve)
        parsed = json.loads(j)
        assert parsed == curve

    def test_empty_equity_curve(self):
        _, _, CDR = _import_chart_models()
        resp = CDR(bars=[], indicators={}, timestamps=[], trade_marks=[], equity_curve=[])
        assert resp.equity_curve == []


# ── Run standalone ──────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
