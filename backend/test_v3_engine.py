"""
V3 Backtest Engine — Integration Test

Tests:
  1. Basic buy/sell with SL/TP bracket orders
  2. SL triggers correctly (proves original bug is fixed)
  3. TP triggers correctly
  4. Analytics computation
  5. Full adapter pipeline
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from app.services.backtest_engine.bar import Bar
from app.services.backtest_engine.engine import Engine, EngineConfig
from app.services.backtest_engine.data_feed import DataFeed
from app.services.backtest_engine.instrument import get_instrument
from app.services.backtest_engine.fill_engine import TickMode
from app.services.backtest_engine.position_sizer import SizingMethod
from app.services.backtest_engine.strategy import StrategyBase, StrategyContext, TradeRecord
from app.services.backtest_engine.analytics import compute_analytics
from app.services.backtest_engine.v3_adapter import run_v3_backtest, v3_result_to_api_response

# ─── Helper: generate synthetic bars ──────────────────────────────────

def make_bars(prices: list[tuple[float, float, float, float]], start_ts: int = 1000000) -> list[Bar]:
    """Create bars from (open, high, low, close) tuples."""
    bars = []
    for i, (o, h, l, c) in enumerate(prices):
        bars.append(Bar(
            timestamp=start_ts + i * 60,
            open=o, high=h, low=l, close=c, volume=100,
        ))
    return bars


# ─── Test 1: SL hits before TP ───────────────────────────────────────

class BuyOnBar1_SL_Strategy(StrategyBase):
    """Buy on bar 1 with SL=90 TP=120. Bar 3 dips to 88 → SL should trigger."""

    def on_bar(self, bar):
        if self.ctx.bar_index == 1:
            self.ctx.buy_bracket(stop_loss=90.0, take_profit=120.0)


def test_sl_triggers():
    """SL at 90 should fill when bar drops to 88. This was the original bug."""
    bars = make_bars([
        (100.0, 102.0, 99.0, 101.0),   # Bar 0: establish data
        (101.0, 103.0, 100.0, 102.0),   # Bar 1: BUY signal → entry at 102
        (102.0, 104.0, 101.0, 103.0),   # Bar 2: price goes up, no fill
        (103.0, 103.5, 88.0, 89.0),     # Bar 3: crash through SL at 90 → SL fills
        (89.0, 91.0, 88.0, 90.0),       # Bar 4: bounce
    ])

    feed = DataFeed()
    feed.add_symbol("TEST", bars)

    config = EngineConfig(
        initial_balance=10_000,
        spread_points=0,
        commission=0,
        point_value=1.0,
        slippage_pct=0,
        margin_rate=0.01,
        tick_mode=TickMode.OHLC_PESSIMISTIC,
        sizing_method=SizingMethod.FIXED_LOT,
        sizing_params={"fixed_lot": 1.0},
        close_at_end=False,
    )

    strategy = BuyOnBar1_SL_Strategy(name="SL_Test")
    instrument = get_instrument("TEST", point_value=1.0)
    engine = Engine(strategy=strategy, data_feed=feed, instrument=instrument, config=config)
    result = engine.run("TEST")

    trades = result.trades
    assert len(trades) >= 1, f"Expected at least 1 trade, got {len(trades)}"

    t = trades[0]
    assert t["direction"] == "long", f"Expected long, got {t['direction']}"
    assert t["exit_price"] is not None, "Trade should have been closed by SL"
    assert t["exit_reason"] == "stop_loss", f"Expected exit_reason='stop_loss', got '{t['exit_reason']}'"
    assert t["exit_price"] == 90.0, f"Expected SL fill at 90.0, got {t['exit_price']}"
    assert t["pnl"] < 0, f"SL trade should be a loss, got pnl={t['pnl']}"

    print("✓ Test 1 PASSED: SL triggers correctly at 90.0")
    return True


# ─── Test 2: TP hits before SL ───────────────────────────────────────

class BuyOnBar1_TP_Strategy(StrategyBase):
    """Buy on bar 1 with SL=95 TP=110. Bar 3 goes to 115 → TP should trigger."""

    def on_bar(self, bar):
        if self.ctx.bar_index == 1:
            self.ctx.buy_bracket(stop_loss=95.0, take_profit=110.0)


def test_tp_triggers():
    """TP at 110 should fill when bar goes to 115."""
    bars = make_bars([
        (100.0, 102.0, 99.0, 101.0),   # Bar 0
        (101.0, 103.0, 100.0, 102.0),   # Bar 1: BUY → entry at 102
        (102.0, 103.0, 101.0, 102.5),   # Bar 2: holds
        (102.5, 115.0, 102.0, 112.0),   # Bar 3: TP at 110 triggers
        (112.0, 113.0, 111.0, 112.0),   # Bar 4
    ])

    feed = DataFeed()
    feed.add_symbol("TEST", bars)

    config = EngineConfig(
        initial_balance=10_000,
        spread_points=0,
        commission=0,
        point_value=1.0,
        slippage_pct=0,
        margin_rate=0.01,
        tick_mode=TickMode.OHLC_PESSIMISTIC,
        sizing_method=SizingMethod.FIXED_LOT,
        sizing_params={"fixed_lot": 1.0},
        close_at_end=False,
    )

    strategy = BuyOnBar1_TP_Strategy(name="TP_Test")
    instrument = get_instrument("TEST", point_value=1.0)
    engine = Engine(strategy=strategy, data_feed=feed, instrument=instrument, config=config)
    result = engine.run("TEST")

    trades = result.trades
    assert len(trades) >= 1, f"Expected at least 1 trade, got {len(trades)}"

    t = trades[0]
    assert t["exit_reason"] == "take_profit", f"Expected exit_reason='take_profit', got '{t['exit_reason']}'"
    assert t["exit_price"] == 110.0, f"Expected TP fill at 110.0, got {t['exit_price']}"
    assert t["pnl"] > 0, f"TP trade should be a win, got pnl={t['pnl']}"

    print("✓ Test 2 PASSED: TP triggers correctly at 110.0")
    return True


# ─── Test 3: Short trade with SL above ───────────────────────────────

class SellOnBar1_Strategy(StrategyBase):
    """Sell on bar 1 with SL=105 TP=90."""

    def on_bar(self, bar):
        if self.ctx.bar_index == 1:
            self.ctx.sell_bracket(stop_loss=105.0, take_profit=90.0)


def test_short_sl():
    """Short: SL at 105 triggers when bar goes to 106."""
    bars = make_bars([
        (100.0, 102.0, 99.0, 100.0),   # Bar 0
        (100.0, 101.0, 99.0, 100.0),   # Bar 1: SELL → entry at 100
        (100.0, 100.5, 99.0, 99.5),    # Bar 2: holds
        (99.5, 106.0, 99.0, 105.0),    # Bar 3: spikes to 106 → SL at 105
        (105.0, 106.0, 104.0, 105.0),  # Bar 4
    ])

    feed = DataFeed()
    feed.add_symbol("TEST", bars)

    config = EngineConfig(
        initial_balance=10_000,
        spread_points=0,
        commission=0,
        point_value=1.0,
        slippage_pct=0,
        margin_rate=0.01,
        tick_mode=TickMode.OHLC_PESSIMISTIC,
        sizing_method=SizingMethod.FIXED_LOT,
        sizing_params={"fixed_lot": 1.0},
        close_at_end=False,
    )

    strategy = SellOnBar1_Strategy(name="Short_SL_Test")
    instrument = get_instrument("TEST", point_value=1.0)
    engine = Engine(strategy=strategy, data_feed=feed, instrument=instrument, config=config)
    result = engine.run("TEST")

    trades = result.trades
    assert len(trades) >= 1, f"Expected at least 1 trade, got {len(trades)}"

    t = trades[0]
    assert t["direction"] == "short", f"Expected short, got {t['direction']}"
    assert t["exit_reason"] == "stop_loss", f"Expected exit_reason='stop_loss', got '{t['exit_reason']}'"
    assert t["exit_price"] == 105.0, f"Expected SL fill at 105.0, got {t['exit_price']}"
    assert t["pnl"] < 0, f"Short SL should be loss, got pnl={t['pnl']}"

    print("✓ Test 3 PASSED: Short SL triggers correctly at 105.0")
    return True


# ─── Test 4: Analytics computation ────────────────────────────────────

def test_analytics():
    """Test analytics module computes reasonable values."""
    mock_trades = [
        TradeRecord(direction="long", entry_price=100, size=1, entry_time=1000000, entry_bar=0),
        TradeRecord(direction="long", entry_price=100, size=1, entry_time=1000120, entry_bar=2),
        TradeRecord(direction="short", entry_price=100, size=1, entry_time=1000240, entry_bar=4),
        TradeRecord(direction="long", entry_price=100, size=1, entry_time=1000360, entry_bar=6),
        TradeRecord(direction="short", entry_price=100, size=1, entry_time=1000480, entry_bar=8),
    ]
    # Manually set PnL values
    for t, pnl in zip(mock_trades, [100, -50, 200, -30, 80]):
        t.pnl = pnl
        t.pnl_pct = pnl / 100
        t.exit_time = t.entry_time + 60
        t.exit_bar = t.entry_bar + 1
        t.exit_price = 100 + pnl
        t.commission = 0
    equity_curve = [10000, 10100, 10050, 10250, 10220, 10300]

    stats = compute_analytics(mock_trades, equity_curve, 10000)

    assert stats["total_trades"] == 5
    assert stats["winning_trades"] == 3
    assert stats["losing_trades"] == 2
    assert abs(stats["win_rate"] - 60.0) < 1.0  # win_rate is percentage (60.0%)
    assert abs(stats["net_profit"] - 300) < 0.01
    assert stats["profit_factor"] > 1.0
    assert stats["max_drawdown"] >= 0

    print(f"✓ Test 4 PASSED: Analytics — WR={stats['win_rate']:.2%}, PF={stats['profit_factor']:.2f}, MaxDD={stats['max_drawdown']:.2f}")
    return True


# ─── Test 5: V3 adapter with builder strategy config ─────────────────

def test_v3_adapter():
    """Run full adapter pipeline with a simple crossover strategy config."""
    # 50 bars of trending data
    import math
    bars = []
    for i in range(100):
        base = 100 + 10 * math.sin(i / 10)  # oscillating
        noise = (i % 3 - 1) * 0.5
        o = base + noise
        h = base + abs(noise) + 1
        l = base - abs(noise) - 1
        c = base - noise
        bars.append({"time": 1000000 + i * 3600, "open": o, "high": h, "low": l, "close": c, "volume": 100})

    strategy_config = {
        "indicators": [
            {"name": "SMA", "params": {"period": 5, "source": "close"}, "id": "sma5"},
            {"name": "SMA", "params": {"period": 20, "source": "close"}, "id": "sma20"},
        ],
        "entry_rules": [
            {
                "left": "sma5",
                "operator": "crosses_above",
                "right": "sma20",
                "direction": "long",
            },
            {
                "left": "sma5",
                "operator": "crosses_below",
                "right": "sma20",
                "direction": "short",
                "logic": "OR",
            },
        ],
        "exit_rules": [],
        "risk_params": {
            "sizing_method": "fixed_lot",
            "lot_size": 0.1,
            "stop_loss_type": "fixed_pips",
            "stop_loss_value": 5,
            "take_profit_type": "fixed_pips",
            "take_profit_value": 10,
        },
        "filters": {},
    }

    result = run_v3_backtest(
        bars=bars,
        strategy_config=strategy_config,
        symbol="TESTPAIR",
        initial_balance=10_000,
        spread_points=0,
        commission_per_lot=0,
        point_value=1.0,
        tick_mode="ohlc_pessimistic",
    )

    assert result is not None, "Result should not be None"
    assert len(result.equity_curve) > 0, "Equity curve should have data"

    api_resp = v3_result_to_api_response(result, 10_000, len(bars))
    assert "stats" in api_resp, "API response should have stats"
    assert "trades" in api_resp, "API response should have trades"

    stats = api_resp["stats"]
    n_trades = stats.get("total_trades", 0)
    net_pnl = stats.get("net_profit", 0)

    print(f"✓ Test 5 PASSED: V3 Adapter — {n_trades} trades, Net P/L: ${net_pnl:.2f}")
    return True


# ─── Test 6: Pessimistic tick ordering for long (SL checked before TP) ───

class BuyWithTightBracket(StrategyBase):
    """Buy with both SL and TP where both could trigger in same bar.
    For a long: pessimistic = check SL first (O→L→H→C)."""

    def on_bar(self, bar):
        if self.ctx.bar_index == 1:
            self.ctx.buy_bracket(stop_loss=98.0, take_profit=106.0)


def test_pessimistic_long():
    """When both SL and TP could hit in same bar, pessimistic should fill SL first for long."""
    bars = make_bars([
        (100.0, 101.0, 99.0, 100.0),   # Bar 0
        (100.0, 101.0, 99.5, 100.0),   # Bar 1: BUY at 100
        (100.0, 107.0, 97.0, 103.0),   # Bar 2: low=97 (below SL=98), high=107 (above TP=106)
                                         #         Pessimistic for long: O→L→H→C → SL fills first
    ])

    feed = DataFeed()
    feed.add_symbol("TEST", bars)

    config = EngineConfig(
        initial_balance=10_000,
        spread_points=0,
        commission=0,
        point_value=1.0,
        slippage_pct=0,
        margin_rate=0.01,
        tick_mode=TickMode.OHLC_PESSIMISTIC,
        sizing_method=SizingMethod.FIXED_LOT,
        sizing_params={"fixed_lot": 1.0},
        close_at_end=True,
    )

    strategy = BuyWithTightBracket(name="Pessimistic_Test")
    instrument = get_instrument("TEST", point_value=1.0)
    engine = Engine(strategy=strategy, data_feed=feed, instrument=instrument, config=config)
    result = engine.run("TEST")

    trades = result.trades
    assert len(trades) >= 1, f"Expected at least 1 trade, got {len(trades)}"

    t = trades[0]
    # Pessimistic for long → SL fills first (worst case)
    assert t["exit_reason"] == "stop_loss", f"Pessimistic long: expected stop_loss first, got '{t['exit_reason']}'"
    assert t["exit_price"] == 98.0, f"Expected SL fill at 98.0, got {t['exit_price']}"

    print("✓ Test 6 PASSED: Pessimistic tick ordering correct for long (SL first)")
    return True


# ─── Main ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        ("SL triggers on long", test_sl_triggers),
        ("TP triggers on long", test_tp_triggers),
        ("SL triggers on short", test_short_sl),
        ("Analytics computation", test_analytics),
        ("V3 adapter pipeline", test_v3_adapter),
        ("Pessimistic tick ordering", test_pessimistic_long),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
        except Exception as e:
            print(f"✗ FAILED: {name} — {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")
    if failed == 0:
        print("All tests passed! ✓")
    else:
        print(f"FAILURES: {failed}")
        sys.exit(1)
