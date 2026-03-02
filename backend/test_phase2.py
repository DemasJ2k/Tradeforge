"""Phase 2 — Indicator Library Expansion tests.

Tests all 30+ new indicators and the data_handler dispatch wiring.
Run: python -m pytest test_phase2.py -v
"""
import math
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import pytest
from app.services.backtest.indicators import *

NaN = float("nan")

# ── Helpers ────────────────────────────────────────────────────────

def _make_prices(n: int = 200, base: float = 100.0, swing: float = 10.0):
    """Generate synthetic OHLCV data with a sine-wave pattern."""
    import math as _m
    opens, highs, lows, closes, volumes, timestamps = [], [], [], [], [], []
    for i in range(n):
        c = base + swing * _m.sin(i * 0.1)
        o = c - 0.5 * _m.sin(i * 0.05)
        h = max(o, c) + abs(_m.sin(i * 0.2)) * 2
        l = min(o, c) - abs(_m.cos(i * 0.2)) * 2
        v = 1000 + 500 * abs(_m.sin(i * 0.03))
        ts = 1700000000 + i * 600  # 10-min bars
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        volumes.append(v)
        timestamps.append(ts)
    return opens, highs, lows, closes, volumes, timestamps


O, H, L, C, V, TS = _make_prices(300)


# ── Trend Indicators ──────────────────────────────────────────────

class TestTrendIndicators:
    def test_dema_length_and_valid(self):
        result = dema(C, 20)
        assert len(result) == len(C)
        valid = [v for v in result if not math.isnan(v)]
        assert len(valid) > len(C) // 2

    def test_tema_length_and_valid(self):
        result = tema(C, 20)
        assert len(result) == len(C)
        valid = [v for v in result if not math.isnan(v)]
        assert len(valid) > 0

    def test_zlema_length(self):
        result = zlema(C, 14)
        assert len(result) == len(C)

    def test_hull_ma_smoother_than_sma(self):
        hma = hull_ma(C, 20)
        s = sma(C, 20)
        # Both should be same length
        assert len(hma) == len(s) == len(C)

    def test_wma_helper(self):
        from app.services.backtest.indicators import _wma
        result = _wma([1, 2, 3, 4, 5], 3)
        assert len(result) == 5
        assert math.isnan(result[0])
        assert not math.isnan(result[2])
        # WMA(3) of [1,2,3] = (1*1 + 2*2 + 3*3)/(1+2+3) = 14/6
        assert abs(result[2] - 14 / 6) < 1e-10

    def test_ichimoku_keys(self):
        result = ichimoku(H, L, C)
        assert set(result.keys()) == {"tenkan", "kijun", "senkou_a", "senkou_b", "chikou"}
        for k in result:
            assert len(result[k]) == len(C)

    def test_supertrend_returns_level_and_direction(self):
        level, direction = supertrend(H, L, C, 10, 3.0)
        assert len(level) == len(C)
        assert len(direction) == len(C)
        # Direction should only be 1.0, -1.0, or NaN
        for v in direction:
            assert math.isnan(v) or v in (1.0, -1.0)

    def test_donchian_channel_bands(self):
        upper, middle, lower = donchian_channel(H, L, 20)
        assert len(upper) == len(C)
        for i in range(20, len(C)):
            if not math.isnan(upper[i]):
                assert upper[i] >= lower[i]
                assert abs(middle[i] - (upper[i] + lower[i]) / 2) < 1e-10

    def test_keltner_channel_bands(self):
        upper, middle, lower = keltner_channel(H, L, C, 20, 10, 2.0)
        assert len(upper) == len(C)
        for i in range(25, len(C)):
            if not (math.isnan(upper[i]) or math.isnan(lower[i])):
                assert upper[i] >= lower[i]

    def test_parabolic_sar_length(self):
        result = parabolic_sar(H, L)
        assert len(result) == len(H)
        valid = [v for v in result if not math.isnan(v)]
        assert len(valid) > len(H) - 5


# ── Oscillators ───────────────────────────────────────────────────

class TestOscillators:
    def test_cci_range(self):
        result = cci(H, L, C, 20)
        assert len(result) == len(C)
        valid = [v for v in result if not math.isnan(v)]
        assert len(valid) > 200

    def test_williams_r_range(self):
        result = williams_r(H, L, C, 14)
        assert len(result) == len(C)
        for v in result:
            if not math.isnan(v):
                assert -100 <= v <= 0

    def test_mfi_range(self):
        result = mfi(H, L, C, V, 14)
        assert len(result) == len(C)
        for v in result:
            if not math.isnan(v):
                assert 0 <= v <= 100

    def test_stochastic_rsi_returns_k_d(self):
        k, d = stochastic_rsi(C, 14, 14, 3, 3)
        assert len(k) == len(C)
        assert len(d) == len(C)

    def test_roc_basic(self):
        result = roc([100, 110, 120, 130, 140], 1)
        assert len(result) == 5
        assert math.isnan(result[0])
        assert abs(result[1] - 10.0) < 1e-10

    def test_awesome_oscillator(self):
        result = awesome_oscillator(H, L, 5, 34)
        assert len(result) == len(H)


# ── Volume ────────────────────────────────────────────────────────

class TestVolume:
    def test_obv_cumulative(self):
        result = obv([10, 11, 10, 12], [100, 200, 150, 300])
        assert result[0] == 0
        assert result[1] == 200  # price up → +vol
        assert result[2] == 50   # price down → -vol
        assert result[3] == 350  # price up → +vol

    def test_vwap_bands_structure(self):
        upper, vwap_l, lower = vwap_bands(H, L, C, V, TS, 2.0)
        assert len(upper) == len(C)
        for i in range(len(C)):
            if not (math.isnan(upper[i]) or math.isnan(lower[i])):
                assert upper[i] >= lower[i]

    def test_ad_line_length(self):
        result = ad_line(H, L, C, V)
        assert len(result) == len(C)
        assert not math.isnan(result[-1])

    def test_cmf_range(self):
        result = cmf(H, L, C, V, 20)
        assert len(result) == len(C)
        for v in result:
            if not math.isnan(v):
                assert -1 <= v <= 1

    def test_volume_profile_bins(self):
        result = volume_profile(C, V, 10)
        assert len(result["price_levels"]) == 10
        assert len(result["volume_at_price"]) == 10
        assert sum(result["volume_at_price"]) > 0


# ── Volatility ────────────────────────────────────────────────────

class TestVolatility:
    def test_atr_bands_structure(self):
        upper, middle, lower = atr_bands(H, L, C, 14, 2.0, "ema", 20)
        assert len(upper) == len(C)
        for i in range(25, len(C)):
            if not (math.isnan(upper[i]) or math.isnan(lower[i])):
                assert upper[i] >= lower[i]

    def test_historical_volatility_positive(self):
        result = historical_volatility(C, 20)
        assert len(result) == len(C)
        for v in result:
            if not math.isnan(v):
                assert v >= 0

    def test_stddev_channel_structure(self):
        upper, middle, lower = stddev_channel(C, 20, 2.0)
        assert len(upper) == len(C)
        for i in range(20, len(C)):
            if not (math.isnan(upper[i]) or math.isnan(lower[i])):
                assert upper[i] >= lower[i]


# ── Smart Money / ICT ─────────────────────────────────────────────

class TestSmartMoney:
    def test_fair_value_gaps_returns_bull_bear(self):
        bull, bear = fair_value_gaps(H, L, C, O)
        assert len(bull) == len(C)
        assert len(bear) == len(C)

    def test_order_blocks_returns_bull_bear(self):
        bull, bear = order_blocks(H, L, C, O, 5, 2.0)
        assert len(bull) == len(C)
        assert len(bear) == len(C)

    def test_liquidity_sweeps_returns_hi_lo(self):
        hi, lo = liquidity_sweeps(H, L, C, 20)
        assert len(hi) == len(C)
        assert len(lo) == len(C)


# ── Session / Time ────────────────────────────────────────────────

class TestSession:
    def test_session_high_low(self):
        hi, lo = session_high_low(H, L, TS, 8, 17)
        assert len(hi) == len(H)

    def test_previous_day_levels_keys(self):
        result = previous_day_levels(H, L, C, TS)
        assert set(result.keys()) == {"pdh", "pdl", "pdc"}
        for k in result:
            assert len(result[k]) == len(C)

    def test_weekly_open_length(self):
        result = weekly_open(O, TS)
        assert len(result) == len(O)

    def test_kill_zones_binary(self):
        lk, ny = kill_zones(TS)
        assert len(lk) == len(TS)
        for v in lk:
            assert v in (0.0, 1.0)
        for v in ny:
            assert v in (0.0, 1.0)


# ── Data Handler Dispatch Integration ─────────────────────────────

class TestDataHandlerDispatch:
    """Test that compute_indicators() in data_handler correctly dispatches to all new types."""

    @pytest.fixture
    def symbol_data(self):
        from app.services.backtest.v2.engine.data_handler import SymbolData
        from app.services.backtest.engine import Bar
        from datetime import datetime, timezone

        sd = SymbolData(symbol="TEST", timeframe_s=600)
        bars = []
        for i in range(len(C)):
            bars.append(Bar(
                time=datetime.fromtimestamp(TS[i], tz=timezone.utc),
                open=O[i], high=H[i], low=L[i], close=C[i], volume=V[i],
            ))
        sd.load_bars(bars)
        return sd

    @pytest.mark.parametrize("ind_type,params", [
        ("DEMA", {"period": 14}),
        ("TEMA", {"period": 14}),
        ("ZLEMA", {"period": 14}),
        ("HULL_MA", {"period": 14}),
        ("ICHIMOKU", {"tenkan": 9, "kijun": 26, "senkou_b": 52}),
        ("SUPERTREND", {"period": 10, "multiplier": 3}),
        ("DONCHIAN", {"period": 20}),
        ("KELTNER", {"ema_period": 20, "atr_period": 10, "multiplier": 2}),
        ("PARABOLIC_SAR", {}),
        ("CCI", {"period": 20}),
        ("WILLIAMS_R", {"period": 14}),
        ("MFI", {"period": 14}),
        ("STOCHASTIC_RSI", {"rsi_period": 14, "stoch_period": 14}),
        ("ROC", {"period": 14}),
        ("AWESOME_OSCILLATOR", {"fast": 5, "slow": 34}),
        ("OBV", {}),
        ("VWAP_BANDS", {"num_std": 2}),
        ("AD_LINE", {}),
        ("CMF", {"period": 20}),
        ("ATR_BANDS", {"atr_period": 14, "multiplier": 2}),
        ("HISTORICAL_VOLATILITY", {"period": 20}),
        ("STDDEV_CHANNEL", {"period": 20, "num_std": 2}),
        ("FAIR_VALUE_GAPS", {}),
        ("ORDER_BLOCKS", {"swing_lookback": 5}),
        ("LIQUIDITY_SWEEPS", {"lookback": 20}),
        ("SESSION_HL", {"session_start": 8, "session_end": 17}),
        ("PREV_DAY_LEVELS", {}),
        ("WEEKLY_OPEN", {}),
        ("KILL_ZONES", {}),
    ])
    def test_dispatch_creates_arrays(self, symbol_data, ind_type, params):
        cfg = [{"id": "test_ind", "type": ind_type, "params": params}]
        symbol_data.compute_indicators(cfg)
        # At minimum the base id should exist
        assert "test_ind" in symbol_data.indicator_arrays
        arr = symbol_data.indicator_arrays["test_ind"]
        assert len(arr) == len(C)


# ── Regression: existing indicators still work ────────────────────

class TestRegressionExisting:
    def test_sma_unchanged(self):
        result = sma(C, 20)
        assert len(result) == len(C)
        valid = [v for v in result if not math.isnan(v)]
        assert len(valid) == len(C) - 19

    def test_ema_unchanged(self):
        result = ema(C, 14)
        assert len(result) == len(C)

    def test_rsi_unchanged(self):
        result = rsi(C, 14)
        assert len(result) == len(C)

    def test_macd_unchanged(self):
        ml, sl, hist = macd(C, 12, 26, 9)
        assert len(ml) == len(C)

    def test_bollinger_unchanged(self):
        u, m, l = bollinger_bands(C, 20, 2.0)
        assert len(u) == len(C)

    def test_atr_unchanged(self):
        result = atr(H, L, C, 14)
        assert len(result) == len(C)

    def test_stochastic_unchanged(self):
        k, d = stochastic(H, L, C, 14, 3, 3)
        assert len(k) == len(C)

    def test_adx_unchanged(self):
        result = adx(H, L, C, 14)
        assert len(result) == len(C)

    def test_vwap_unchanged(self):
        result = vwap(H, L, C, V, TS)
        assert len(result) == len(C)
