"""Quick smoke test for Phase 1A: fill pipeline with real ATR + volume."""

from app.services.backtest.v2.engine.runner import Runner, RunConfig, SlippageMode
from app.services.backtest.v2.engine.data_handler import DataHandler
from app.services.backtest.v2.engine.strategy_base import StrategyBase
from app.services.backtest.v2.engine.events import BarEvent


class BuyAndSell(StrategyBase):
    """Buy on bar 20, sell on bar 30."""
    def __init__(self):
        super().__init__()
        self._bought = False

    def on_bar(self, bar: BarEvent):
        if bar.bar_index == 20 and not self._bought:
            self.ctx.buy_market(bar.symbol, 0.01, "entry")
            self._bought = True
        elif bar.bar_index == 30 and self._bought:
            self.ctx.sell_market(bar.symbol, 0.01, "exit")
            self._bought = False


def make_bars(n=100):
    import random
    random.seed(42)
    bars = []
    price = 2000.0
    for i in range(n):
        o = price
        h = o + random.uniform(1, 10)
        l = o - random.uniform(1, 10)
        c = o + random.uniform(-5, 5)
        bars.append({
            "time": 1700000000 + i * 600,
            "open": o, "high": h, "low": l, "close": c,
            "volume": random.uniform(100, 1000),
        })
        price = c
    return bars


def test_atr_and_volume():
    """Verify pre-computed ATR + avg_volume are non-zero."""
    bars = make_bars()
    dh = DataHandler()
    dh.add_symbol("XAUUSD", bars, indicator_configs=[
        {"id": "atr_1", "type": "ATR", "params": {"period": 14}},
    ])
    cfg = RunConfig(
        initial_cash=10000, spread=0.5,
        slippage_mode=SlippageMode.REALISTIC,
        bars_per_day=144,
    )
    runner = Runner(data_handler=dh, strategy=BuyAndSell(), config=cfg)

    atr_50 = runner._get_atr("XAUUSD", 50)
    avgv_50 = runner._get_avg_volume("XAUUSD", 50)
    atr_5 = runner._get_atr("XAUUSD", 5)
    print(f"  ATR@50: {atr_50:.4f}")
    print(f"  AvgVol@50: {avgv_50:.2f}")
    print(f"  ATR@5 (warmup): {atr_5:.4f}")
    assert atr_50 > 0, "ATR should be non-zero after warm-up"
    assert avgv_50 > 0, "AvgVol should be non-zero after warm-up"
    assert atr_5 == 0.0, "ATR should be 0 during warm-up"
    print("  PASS: ATR + volume are correct")


def test_slippage_modes():
    """Verify REALISTIC slippage produces more slippage than NONE."""
    bars = make_bars()

    # REALISTIC
    dh1 = DataHandler()
    dh1.add_symbol("XAUUSD", bars, indicator_configs=[])
    r1 = Runner(
        data_handler=dh1, strategy=BuyAndSell(),
        config=RunConfig(
            initial_cash=10000, spread=0.5,
            slippage_mode=SlippageMode.REALISTIC,
            bars_per_day=144,
        ),
    )
    res1 = r1.run()

    # NONE
    dh2 = DataHandler()
    dh2.add_symbol("XAUUSD", bars, indicator_configs=[])
    r2 = Runner(
        data_handler=dh2, strategy=BuyAndSell(),
        config=RunConfig(
            initial_cash=10000, spread=0.5,
            slippage_mode=SlippageMode.NONE,
            bars_per_day=144,
        ),
    )
    res2 = r2.run()

    t1 = res1.closed_trades[0] if res1.closed_trades else {}
    t2 = res2.closed_trades[0] if res2.closed_trades else {}

    slip1 = t1.get("slippage", 0)
    slip2 = t2.get("slippage", 0)

    print(f"  REALISTIC: entry={t1.get('entry_price', 0):.5f}  "
          f"exit={t1.get('exit_price', 0):.5f}  "
          f"slippage={slip1:.5f}  pnl={t1.get('pnl', 0):.4f}")
    print(f"  NONE:      entry={t2.get('entry_price', 0):.5f}  "
          f"exit={t2.get('exit_price', 0):.5f}  "
          f"slippage={slip2:.5f}  pnl={t2.get('pnl', 0):.4f}")

    assert slip1 > slip2, (
        f"REALISTIC slippage ({slip1:.5f}) should exceed NONE ({slip2:.5f})"
    )
    print(f"  PASS: REALISTIC slippage ({slip1:.5f}) > NONE ({slip2:.5f})")


def test_system_atr_auto_compute():
    """Verify system ATR is auto-computed even without explicit ATR indicator."""
    bars = make_bars()
    dh = DataHandler()
    dh.add_symbol("XAUUSD", bars, indicator_configs=[])  # No indicators!
    cfg = RunConfig(initial_cash=10000, spread=0.5, bars_per_day=144)
    runner = Runner(data_handler=dh, strategy=BuyAndSell(), config=cfg)

    atr_50 = runner._get_atr("XAUUSD", 50)
    print(f"  System ATR@50 (auto-computed): {atr_50:.4f}")
    assert atr_50 > 0, "System ATR should auto-compute even without indicator config"
    print("  PASS: System ATR auto-computed")


def test_pessimistic_sl_tp():
    """Verify pessimistic_sl_tp config exists and defaults to True."""
    cfg = RunConfig()
    assert cfg.pessimistic_sl_tp is True, "pessimistic_sl_tp should default to True"
    print("  PASS: pessimistic_sl_tp defaults to True")


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")

    print("Test 1: ATR & Volume pre-computation")
    test_atr_and_volume()

    print("\nTest 2: Slippage modes (REALISTIC vs NONE)")
    test_slippage_modes()

    print("\nTest 3: System ATR auto-compute without indicator config")
    test_system_atr_auto_compute()

    print("\nTest 4: Pessimistic SL/TP config")
    test_pessimistic_sl_tp()

    print("\n=== ALL PHASE 1A TESTS PASSED ===")
