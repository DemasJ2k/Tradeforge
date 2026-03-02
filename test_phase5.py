"""
Smoke test for Phase 5: Rust / Python fallback fast core.

Validates:
  1. Fallback module imports correctly
  2. SMA / EMA / ATR indicators produce correct values
  3. FastEventQueue ordering is correct
  4. FastPortfolio tracks positions and equity
  5. FastRunner runs a simple SMA crossover strategy
  6. Runner integration via use_fast_core=True flag

Run:
    cd backend
    python -m pytest ../test_phase5.py -v
"""

from __future__ import annotations

import sys
import os
import math
import time

# Ensure backend is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))


# ── Test 1: Import ──────────────────────────────────────────────────

def test_import_core():
    """The core package should import without error (Rust or fallback)."""
    from app.services.backtest.v2.core import USING_RUST
    from app.services.backtest.v2.core.python_bindings import (
        Bar, EngineConfig, SymbolConfig,
        FastRunner, FastPortfolio, BacktestResult,
        SMA, EMA, ATR, BollingerBands,
    )
    print(f"  Engine: {'Rust' if USING_RUST else 'Python fallback'}")
    assert Bar is not None
    assert FastRunner is not None


# ── Test 2: SMA indicator ──────────────────────────────────────────

def test_sma():
    from app.services.backtest.v2.core.python_bindings import SMA, sma_array
    s = SMA(period=3)
    s.push(10.0)
    assert not s.ready
    s.push(20.0)
    s.push(30.0)
    assert s.ready
    assert abs(s.value - 20.0) < 1e-9

    s.push(40.0)
    assert abs(s.value - 30.0) < 1e-9  # (20+30+40)/3

    # Vectorised
    arr = sma_array([10.0, 20.0, 30.0, 40.0, 50.0], 3)
    assert len(arr) == 5
    assert math.isnan(arr[0])
    assert math.isnan(arr[1])
    assert abs(arr[2] - 20.0) < 1e-9
    assert abs(arr[3] - 30.0) < 1e-9
    assert abs(arr[4] - 40.0) < 1e-9


# ── Test 3: EMA indicator ──────────────────────────────────────────

def test_ema():
    from app.services.backtest.v2.core.python_bindings import EMA
    e = EMA(period=3)
    # Seed: first 3 values -> SMA = 20
    e.push(10.0)
    e.push(20.0)
    e.push(30.0)
    assert e.ready
    assert abs(e.value - 20.0) < 1e-9  # SMA seed

    # Next: EMA(3) alpha = 2/(3+1) = 0.5
    e.push(40.0)
    expected = 20.0 + 0.5 * (40.0 - 20.0)  # = 30.0
    assert abs(e.value - expected) < 1e-9


# ── Test 4: ATR indicator ──────────────────────────────────────────

def test_atr():
    from app.services.backtest.v2.core.python_bindings import ATR
    a = ATR(period=3)
    # ATR.push(high, low, close) - tracks prev_close internally
    # Bar 0: no prev close -> TR = H-L
    a.push(10.5, 9.5, 10.0)   # TR = 10.5-9.5 = 1.0
    a.push(10.5, 9.8, 10.3)   # prev_close=10.0: TR = max(0.7, 0.5, 0.2) = 0.7
    a.push(11.0, 10.0, 10.8)  # prev_close=10.3: TR = max(1.0, 0.7, 0.3) = 1.0
    assert a.ready
    # SMA seed over first 3 TR values: (1.0 + 0.7 + 1.0) / 3 = 0.9
    assert abs(a.value - 0.9) < 1e-9


# ── Test 5: Bollinger Bands ─────────────────────────────────────────

def test_bollinger():
    from app.services.backtest.v2.core.python_bindings import BollingerBands
    bb = BollingerBands(period=5, k=2.0)
    values = [20.0, 21.0, 22.0, 21.5, 20.5]
    for v in values:
        bb.push(v)
    assert bb.ready
    mid = bb.middle
    assert abs(mid - 21.0) < 1e-9  # Mean of 5 values
    assert bb.upper > mid
    assert bb.lower < mid
    # Width = 2 * k * std = 4 * std
    half_width = (bb.upper - mid)
    variance = sum((v - 21.0)**2 for v in values) / 5
    expected_std = math.sqrt(variance)
    assert abs(half_width - 2.0 * expected_std) < 1e-9


# ── Test 6: FastEventQueue ──────────────────────────────────────────

def test_event_queue():
    from app.services.backtest.v2.core.python_bindings import FastEventQueue
    q = FastEventQueue()
    # push_bar(timestamp_ns, bar_index, symbol_idx)
    q.push_bar(2_000, 1, 0)
    q.push_bar(1_000, 0, 0)
    assert q.len() == 2
    first = q.pop()
    assert first is not None
    assert first[0] == 1_000  # Earlier timestamp comes first


# ── Test 7: FastPortfolio ───────────────────────────────────────────

def test_portfolio():
    from app.services.backtest.v2.core.python_bindings import (
        EngineConfig, SymbolConfig, FastPortfolio, RustFill, OrderSide,
    )
    cfg = EngineConfig(
        initial_cash=10_000.0,
        commission_per_lot=2.0,
        commission_pct=0.0,
        spread=0.0,
        slippage_pct=0.0,
        default_margin_rate=0.01,
        max_drawdown_pct=0.0,
        max_positions=0,
        exclusive_orders=False,
        warm_up_bars=0,
        bars_per_day=1.0,
    )
    syms = [SymbolConfig(symbol_idx=0, name="TEST", point_value=1.0, margin_rate=0.01, spread=0.0)]
    p = FastPortfolio(config=cfg, symbols=syms)

    # Buy 1 lot at 100
    fill_buy = RustFill(
        order_idx=0, symbol_idx=0, side=OrderSide.Buy,
        quantity=1.0, price=100.0,
        commission=2.0, slippage=0.0,
        timestamp_ns=1000, bar_index=0, is_gap_fill=False,
    )
    p.apply_fill(fill_buy)
    assert p.cash < 10_000.0  # Cash decreased by commission

    # Update price to 110 and snapshot
    p.update_price(0, 110.0)
    p.snapshot_equity()

    assert len(p.equity_curve) >= 2  # Initial + 1 snapshot
    # Equity should be > initial because price went up
    assert p.equity_curve[-1] > 10_000.0

    # Sell to close
    fill_sell = RustFill(
        order_idx=1, symbol_idx=0, side=OrderSide.Sell,
        quantity=1.0, price=110.0,
        commission=2.0, slippage=0.0,
        timestamp_ns=2000, bar_index=1, is_gap_fill=False,
    )
    p.apply_fill(fill_sell)
    assert p.is_flat(0)

    # PnL: (110-100)*1*pv - exit_commission = 10 - 2 = 8
    trades = p.get_trades()
    assert len(trades) == 1
    t = trades[0]
    assert abs(t["pnl"] - 8.0) < 1e-6
    # Cash = 10000 - 2 (buy comm) + 8 (close PnL incl exit comm) = 10006
    assert abs(p.cash - 10006.0) < 1e-6


# ── Test 8: FastRunner with SMA crossover ──────────────────────────

def test_fast_runner_sma_crossover():
    from app.services.backtest.v2.core.python_bindings import (
        Bar, EngineConfig, SymbolConfig, FastRunner, USING_RUST,
    )

    # Generate synthetic bars: uptrend then downtrend
    bars = []
    prices = (
        [100 + i * 0.5 for i in range(50)]    # Uptrend
        + [125 - i * 0.5 for i in range(50)]  # Downtrend
    )
    for i, p in enumerate(prices):
        bars.append(Bar(
            timestamp_ns=i * 1_000_000_000,
            symbol_idx=0,
            bar_index=i,
            open=p - 0.25,
            high=p + 1.0,
            low=p - 1.0,
            close=p,
            volume=1000.0,
        ))

    cfg = EngineConfig(
        initial_cash=10_000.0,
        commission_per_lot=1.0,
        commission_pct=0.0,
        spread=0.1,
        slippage_pct=0.0,
        default_margin_rate=1.0,  # No margin
        max_drawdown_pct=0.0,
        max_positions=0,
        exclusive_orders=True,
        warm_up_bars=20,
        bars_per_day=1.0,
    )
    syms = [SymbolConfig(symbol_idx=0, name="TEST", point_value=1.0, margin_rate=1.0, spread=0.1)]

    # SMA crossover strategy via callback
    sma_fast_period = 5
    sma_slow_period = 20
    fast_buf = []
    slow_buf = []
    position = [0]  # 0=flat, 1=long, -1=short

    def strategy_cb(bar_dict, indicator_vals):
        price = bar_dict["close"]
        fast_buf.append(price)
        slow_buf.append(price)
        if len(fast_buf) > sma_fast_period:
            fast_buf.pop(0)
        if len(slow_buf) > sma_slow_period:
            slow_buf.pop(0)

        if len(slow_buf) < sma_slow_period:
            return []

        sma_f = sum(fast_buf) / len(fast_buf)
        sma_s = sum(slow_buf) / len(slow_buf)

        orders = []
        if sma_f > sma_s and position[0] <= 0:
            if position[0] < 0:
                orders.append({"symbol_idx": 0, "side": 1, "order_type": 1, "quantity": 1.0})
            orders.append({"symbol_idx": 0, "side": 1, "order_type": 1, "quantity": 1.0})
            position[0] = 1
        elif sma_f < sma_s and position[0] >= 0:
            if position[0] > 0:
                orders.append({"symbol_idx": 0, "side": 2, "order_type": 1, "quantity": 1.0})
            orders.append({"symbol_idx": 0, "side": 2, "order_type": 1, "quantity": 1.0})
            position[0] = -1
        return orders

    runner = FastRunner(config=cfg, symbols=syms, bars_flat=bars)
    result, portfolio = runner.run(strategy_cb)

    print(f"  Engine: {'Rust' if USING_RUST else 'fallback'}")
    print(f"  Bars processed: {result.bars_processed}")
    print(f"  Trades: {result.n_trades}")
    print(f"  Fills: {result.n_fills}")
    print(f"  Elapsed: {result.elapsed_ms:.1f} ms")
    print(f"  Equity curve length: {len(portfolio.equity_curve)}")

    assert result.bars_processed > 0
    assert len(portfolio.equity_curve) > 0


# ── Test 9: Integration with V2 Runner ──────────────────────────────

def test_runner_fast_core_flag():
    """Test that Runner.run() with use_fast_core=True works end-to-end."""
    from app.services.backtest.v2.engine.runner import Runner, RunConfig
    from app.services.backtest.v2.engine.data_handler import DataHandler
    from app.services.backtest.v2.engine.strategy_base import StrategyBase
    from app.services.backtest.v2.engine.events import BarEvent

    class SimpleBuyHold(StrategyBase):
        def __init__(self):
            super().__init__(params={})
            self._bought = False

        def on_bar(self, bar: BarEvent):
            if not self._bought and self.ctx.bar_index >= 5:
                self.ctx.buy_market(bar.symbol, 1.0)
                self._bought = True

    # Build data
    data = DataHandler()
    n_bars = 50
    bars = []
    for i in range(n_bars):
        bars.append({
            "time": 1700000000 + i * 60,
            "open": 100.0 + i * 0.1,
            "high": 100.5 + i * 0.1,
            "low": 99.5 + i * 0.1,
            "close": 100.2 + i * 0.1,
            "volume": 1000.0,
        })

    data.add_symbol("TEST", bars, indicator_configs=[])

    config = RunConfig(
        initial_cash=10_000.0,
        commission_per_lot=1.0,
        spread=0.1,
        point_values={"TEST": 1.0},
        margin_rates={"TEST": 1.0},
        bars_per_day=1.0,
        use_fast_core=True,
        warm_up_bars=0,
    )

    strategy = SimpleBuyHold()
    runner = Runner(data_handler=data, strategy=strategy, config=config)
    result = runner.run()

    print(f"  Bars processed: {result.bars_processed}")
    print(f"  Trades: {len(result.closed_trades)}")
    print(f"  Elapsed: {result.elapsed_seconds:.3f}s")
    print(f"  Equity curve: {len(result.equity_curve)} points")

    # Should have processed some bars and generated the equity curve
    assert result.bars_processed > 0
    assert len(result.equity_curve) > 0


# ── Benchmark ───────────────────────────────────────────────────────

def test_benchmark():
    """Timing benchmark: run 1000-bar backtest and report speed."""
    from app.services.backtest.v2.core.python_bindings import (
        Bar, EngineConfig, SymbolConfig, FastRunner, USING_RUST,
    )

    n_bars = 1_000
    bars = []
    base = 100.0
    for i in range(n_bars):
        noise = 0.5 * ((-1) ** i)
        p = base + i * 0.01 + noise
        bars.append(Bar(
            timestamp_ns=i * 1_000_000_000,
            symbol_idx=0,
            bar_index=i,
            open=p - 0.1,
            high=p + 0.5,
            low=p - 0.5,
            close=p,
            volume=1000.0,
        ))

    cfg = EngineConfig(
        initial_cash=100_000.0,
        commission_per_lot=1.0,
        commission_pct=0.0,
        spread=0.1,
        slippage_pct=0.0,
        default_margin_rate=1.0,
        max_drawdown_pct=0.0,
        max_positions=0,
        exclusive_orders=True,
        warm_up_bars=50,
        bars_per_day=1.0,
    )
    syms = [SymbolConfig(symbol_idx=0, name="BENCH", point_value=1.0, margin_rate=1.0, spread=0.1)]

    pos = [0]

    def simple_strategy(bar_dict, _ind):
        """Alternate buy/sell every 10 bars."""
        orders = []
        bi = bar_dict["bar_index"]
        if bi % 10 == 0:
            if pos[0] == 0:
                orders.append({"symbol_idx": 0, "side": 1, "order_type": 1, "quantity": 1.0})
                pos[0] = 1
            elif pos[0] == 1:
                orders.append({"symbol_idx": 0, "side": 2, "order_type": 1, "quantity": 1.0})
                orders.append({"symbol_idx": 0, "side": 2, "order_type": 1, "quantity": 1.0})
                pos[0] = -1
            else:
                orders.append({"symbol_idx": 0, "side": 1, "order_type": 1, "quantity": 1.0})
                orders.append({"symbol_idx": 0, "side": 1, "order_type": 1, "quantity": 1.0})
                pos[0] = 1
        return orders

    # Warm up
    runner = FastRunner(config=cfg, symbols=syms, bars_flat=bars)
    runner.run(simple_strategy)

    # Timed run
    pos[0] = 0
    t0 = time.perf_counter()
    n_runs = 10
    for _ in range(n_runs):
        pos[0] = 0
        r = FastRunner(config=cfg, symbols=syms, bars_flat=bars)
        res, pf = r.run(simple_strategy)
    elapsed = time.perf_counter() - t0

    engine = "Rust" if USING_RUST else "Python fallback"
    print(f"\n  Benchmark: {engine}")
    print(f"  {n_runs} x {n_bars} bars = {n_runs * n_bars:,} total bars")
    print(f"  Total: {elapsed:.3f}s")
    print(f"  Per run: {elapsed/n_runs*1000:.1f} ms")
    print(f"  Bars/sec: {n_runs * n_bars / elapsed:,.0f}")
    print(f"  Trades per run: {res.n_trades}")
    assert elapsed > 0


# ── Main ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        ("Import core", test_import_core),
        ("SMA indicator", test_sma),
        ("EMA indicator", test_ema),
        ("ATR indicator", test_atr),
        ("Bollinger Bands", test_bollinger),
        ("Event queue ordering", test_event_queue),
        ("Portfolio position tracking", test_portfolio),
        ("FastRunner SMA crossover", test_fast_runner_sma_crossover),
        ("Runner integration (fast_core)", test_runner_fast_core_flag),
        ("Benchmark (1000 bars x 10)", test_benchmark),
    ]

    passed = 0
    failed = 0
    for name, func in tests:
        print(f"\n{'='*60}")
        print(f"TEST: {name}")
        print(f"{'='*60}")
        try:
            func()
            print(f"  PASSED")
            passed += 1
        except Exception as e:
            print(f"  FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed, {passed+failed} total")
    print(f"{'='*60}")
