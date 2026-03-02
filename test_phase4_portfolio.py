"""
Phase 4 Smoke Test — Multi-Symbol Portfolio Backtesting
Run with:  python test_phase4_portfolio.py
"""
import sys, os, time, random, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

import numpy as np

from app.services.backtest.v2.engine.events import BarEvent, EventType
from app.services.backtest.v2.engine.data_handler import DataHandler
from app.services.backtest.v2.engine.strategy_base import StrategyBase
from app.services.backtest.v2.engine.runner import Runner, RunConfig, RunResult
from app.services.backtest.v2.engine.risk_manager import RiskConfig

from app.services.backtest.v2.analytics.portfolio_analytics import (
    per_symbol_stats,
    correlation_matrix,
    compute_symbol_returns,
    diversification_ratio,
    compute_allocation_over_time,
    build_portfolio_analytics,
)
from app.services.backtest.v2_adapter import (
    MultiSymbolBuilderStrategy,
    run_v2_portfolio_backtest,
    v2_portfolio_result_to_api_response,
)
from app.schemas.backtest import BacktestRequest, BacktestResponse


# ────────────────────────────────────────────────────────────────────
# Helpers — synthetic bar data generation
# ────────────────────────────────────────────────────────────────────

def make_bars(n=500, start_price=2000.0, seed=42, volatility=5.0, trend=0.0):
    """Generate synthetic bar data with controllable properties."""
    rng = random.Random(seed)
    bars = []
    price = start_price
    for i in range(n):
        o = price
        c = o + rng.gauss(trend, volatility)
        h = max(o, c) + abs(rng.gauss(0, volatility * 0.4))
        l = min(o, c) - abs(rng.gauss(0, volatility * 0.4))
        ts = 1700000000 + i * 600  # 10-minute bars
        bars.append({
            "time": ts, "open": round(o, 2), "high": round(h, 2),
            "low": round(l, 2), "close": round(c, 2),
            "volume": rng.randint(100, 1000),
        })
        price = c
    return bars


def make_correlated_bars(n=500, seed1=42, seed2=99, corr=0.5):
    """Generate two symbol datasets with approximate correlation.
    
    Uses a common-factor model: price_B = alpha * common + (1-alpha) * idio.
    """
    rng1 = random.Random(seed1)
    rng2 = random.Random(seed2)
    
    bars_a = []
    bars_b = []
    price_a = 2000.0
    price_b = 30.0  # e.g. silver-like
    
    for i in range(n):
        # Common shock factor
        common = rng1.gauss(0, 5)
        idio_a = rng1.gauss(0, 3)
        idio_b = rng2.gauss(0, 2)
        
        move_a = common + idio_a
        move_b = corr * common * 0.4 + (1 - corr) * idio_b  # Scale down for different price level
        
        o_a = price_a
        c_a = o_a + move_a
        h_a = max(o_a, c_a) + abs(rng1.gauss(0, 2))
        l_a = min(o_a, c_a) - abs(rng1.gauss(0, 2))
        
        o_b = price_b
        c_b = o_b + move_b
        h_b = max(o_b, c_b) + abs(rng2.gauss(0, 0.5))
        l_b = min(o_b, c_b) - abs(rng2.gauss(0, 0.5))
        
        ts = 1700000000 + i * 600
        bars_a.append({
            "time": ts, "open": round(o_a, 2), "high": round(h_a, 2),
            "low": round(l_a, 2), "close": round(c_a, 2),
            "volume": rng1.randint(100, 1000),
        })
        bars_b.append({
            "time": ts, "open": round(o_b, 2), "high": round(h_b, 2),
            "low": round(l_b, 2), "close": round(c_b, 2),
            "volume": rng2.randint(50, 500),
        })
        price_a = c_a
        price_b = c_b
    
    return bars_a, bars_b


# A simple SMA crossover strategy config (no custom indicators needed)
SIMPLE_STRATEGY_CONFIG = {
    "indicators": [
        {"id": "sma_10", "type": "sma", "params": {"period": 10, "source": "close"}},
        {"id": "sma_30", "type": "sma", "params": {"period": 30, "source": "close"}},
    ],
    "entry_rules": [
        {
            "left": "sma_10",
            "operator": "crosses_above",
            "right": "sma_30",
            "direction": "long",
        },
        {
            "left": "sma_10",
            "operator": "crosses_below",
            "right": "sma_30",
            "direction": "short",
            "logic": "OR",
        },
    ],
    "exit_rules": [],
    "risk_params": {
        "position_size_value": 0.1,
        "stop_loss_type": "fixed_pips",
        "stop_loss_value": 50,
        "take_profit_type": "fixed_pips",
        "take_profit_value": 100,
        "max_positions": 3,
    },
    "filters": {},
}

OK = 0
FAIL = 0

def check(test_name: str, passed: bool, detail: str = ""):
    global OK, FAIL
    status = "PASS" if passed else "FAIL"
    if passed:
        OK += 1
    else:
        FAIL += 1
    msg = f"  [{status}] {test_name}"
    if detail:
        msg += f"  ({detail})"
    print(msg)
    return passed


# ════════════════════════════════════════════════════════════════════
# TEST 1: Portfolio Analytics — per_symbol_stats
# ════════════════════════════════════════════════════════════════════

def test_per_symbol_stats():
    print()
    print("=" * 60)
    print("TEST 1: per_symbol_stats")
    print("=" * 60)
    
    trades = [
        {"symbol": "XAUUSD", "pnl": 100, "commission": 5},
        {"symbol": "XAUUSD", "pnl": -40, "commission": 5},
        {"symbol": "XAUUSD", "pnl": 60, "commission": 5},
        {"symbol": "XAGUSD", "pnl": -20, "commission": 3},
        {"symbol": "XAGUSD", "pnl": 30, "commission": 3},
    ]
    
    stats = per_symbol_stats(trades)
    
    check("Two symbols returned", len(stats) == 2)
    check("XAUUSD has 3 trades", stats["XAUUSD"]["total_trades"] == 3)
    check("XAGUSD has 2 trades", stats["XAGUSD"]["total_trades"] == 2)
    check("XAUUSD win_rate ~66.67%", abs(stats["XAUUSD"]["win_rate"] - 66.67) < 0.1,
          f"got={stats['XAUUSD']['win_rate']}")
    check("XAGUSD win_rate == 50%", abs(stats["XAGUSD"]["win_rate"] - 50.0) < 0.1,
          f"got={stats['XAGUSD']['win_rate']}")
    check("XAUUSD net_profit > 0", stats["XAUUSD"]["net_profit"] > 0,
          f"got={stats['XAUUSD']['net_profit']}")
    check("XAUUSD total_commission == 15", abs(stats["XAUUSD"]["total_commission"] - 15) < 0.01)
    check("XAGUSD total_commission == 6", abs(stats["XAGUSD"]["total_commission"] - 6) < 0.01)


# ════════════════════════════════════════════════════════════════════
# TEST 2: Portfolio Analytics — correlation_matrix
# ════════════════════════════════════════════════════════════════════

def test_correlation_matrix():
    print()
    print("=" * 60)
    print("TEST 2: correlation_matrix")
    print("=" * 60)
    
    np.random.seed(42)
    
    # Perfectly correlated returns
    rets_a = np.random.randn(100)
    rets_b = rets_a.copy()  # Perfect correlation
    
    corr = correlation_matrix({"SYM_A": rets_a, "SYM_B": rets_b})
    
    check("Two symbols in matrix", len(corr["symbols"]) == 2)
    check("Matrix is 2x2", len(corr["matrix"]) == 2 and len(corr["matrix"][0]) == 2)
    check("Diagonal == 1.0", abs(corr["matrix"][0][0] - 1.0) < 0.001)
    check("Perfect correlation ~1.0", abs(corr["avg_correlation"] - 1.0) < 0.001,
          f"got={corr['avg_correlation']}")
    
    # Uncorrelated returns
    rets_c = np.random.randn(100)
    rets_d = np.random.randn(100)
    
    corr2 = correlation_matrix({"SYM_C": rets_c, "SYM_D": rets_d})
    check("Uncorrelated avg_correlation near 0", abs(corr2["avg_correlation"]) < 0.3,
          f"got={corr2['avg_correlation']}")
    
    # Single symbol (edge case)
    corr3 = correlation_matrix({"SOLO": np.random.randn(100)})
    check("Single symbol matrix is [[1.0]]",
          corr3["matrix"] == [[1.0]] and corr3["avg_correlation"] == 0.0)
    
    # Empty (0 symbols)
    corr4 = correlation_matrix({})
    check("Empty returns => empty matrix", corr4["matrix"] == [] and corr4["avg_correlation"] == 0.0)


# ════════════════════════════════════════════════════════════════════
# TEST 3: Portfolio Analytics — compute_symbol_returns
# ════════════════════════════════════════════════════════════════════

def test_compute_symbol_returns():
    print()
    print("=" * 60)
    print("TEST 3: compute_symbol_returns")
    print("=" * 60)
    
    closes = {
        "A": [100.0, 110.0, 121.0],
        "B": [50.0, 50.0, 50.0],
    }
    
    rets = compute_symbol_returns(closes)
    
    check("Two symbols in returns", len(rets) == 2)
    check("A has 2 returns (N-1)", len(rets["A"]) == 2)
    # log(110/100) ≈ 0.0953
    check("A first return ≈ 0.0953", abs(rets["A"][0] - math.log(110.0/100.0)) < 0.001,
          f"got={rets['A'][0]:.4f}")
    # B flat => returns ≈ 0
    check("B returns ≈ 0 (flat)", all(abs(r) < 1e-10 for r in rets["B"]),
          f"got={rets['B']}")
    
    # Edge case: single close
    rets2 = compute_symbol_returns({"X": [100.0]})
    check("Single close => [0.0]", len(rets2["X"]) == 1 and rets2["X"][0] == 0.0)


# ════════════════════════════════════════════════════════════════════
# TEST 4: Portfolio Analytics — diversification_ratio
# ════════════════════════════════════════════════════════════════════

def test_diversification_ratio():
    print()
    print("=" * 60)
    print("TEST 4: diversification_ratio")
    print("=" * 60)
    
    np.random.seed(42)
    
    # Identical returns => DR == 1 (no diversification)
    rets_same = np.random.randn(200)
    dr_same = diversification_ratio({"A": rets_same, "B": rets_same.copy()})
    check("Identical returns => DR ≈ 1.0", abs(dr_same - 1.0) < 0.05,
          f"got={dr_same}")
    
    # Independent returns => DR > 1 (diversification benefit)
    rets_x = np.random.randn(200)
    rets_y = np.random.randn(200)
    dr_indep = diversification_ratio({"X": rets_x, "Y": rets_y})
    check("Independent returns => DR > 1.0", dr_indep > 1.0,
          f"got={dr_indep}")
    
    # Single symbol => DR == 1
    dr_single = diversification_ratio({"SOLO": np.random.randn(200)})
    check("Single symbol => DR == 1.0", dr_single == 1.0)
    
    # Very few data points => DR == 1
    dr_short = diversification_ratio({"A": np.array([1.0, 2.0]), "B": np.array([3.0, 4.0])})
    check("Short series (<5) => DR == 1.0", dr_short == 1.0)


# ════════════════════════════════════════════════════════════════════
# TEST 5: Portfolio Analytics — build_portfolio_analytics master
# ════════════════════════════════════════════════════════════════════

def test_build_portfolio_analytics():
    print()
    print("=" * 60)
    print("TEST 5: build_portfolio_analytics (master function)"
    )
    print("=" * 60)
    
    symbols = ["XAUUSD", "XAGUSD"]
    closed_trades = [
        {"symbol": "XAUUSD", "pnl": 100, "commission": 5, "entry_bar": 10, "exit_bar": 50, "quantity": 0.1, "entry_price": 2000},
        {"symbol": "XAUUSD", "pnl": -30, "commission": 5, "entry_bar": 60, "exit_bar": 80, "quantity": 0.1, "entry_price": 2050},
        {"symbol": "XAGUSD", "pnl": 50, "commission": 3, "entry_bar": 20, "exit_bar": 70, "quantity": 0.1, "entry_price": 30},
    ]
    equity_curve = [
        {"bar_index": i, "equity": 10000 + i * 0.5, "cash": 9000, "timestamp": 1700000000 + i * 600}
        for i in range(200)
    ]
    symbol_closes = {
        "XAUUSD": [2000 + i * 0.1 for i in range(200)],
        "XAGUSD": [30 + i * 0.01 for i in range(200)],
    }
    
    analytics = build_portfolio_analytics(closed_trades, equity_curve, symbol_closes, symbols)
    
    check("per_symbol present", "per_symbol" in analytics)
    check("correlation present", "correlation" in analytics)
    check("diversification_ratio present", "diversification_ratio" in analytics)
    check("allocation_over_time present", "allocation_over_time" in analytics)
    check("num_symbols == 2", analytics["num_symbols"] == 2)
    check("symbols list", analytics["symbols"] == ["XAUUSD", "XAGUSD"])
    check("per_symbol has XAUUSD", "XAUUSD" in analytics["per_symbol"])
    check("per_symbol has XAGUSD", "XAGUSD" in analytics["per_symbol"])
    check("correlation.symbols sorted", analytics["correlation"]["symbols"] == ["XAGUSD", "XAUUSD"])


# ════════════════════════════════════════════════════════════════════
# TEST 6: MultiSymbolBuilderStrategy — creation & basic properties
# ════════════════════════════════════════════════════════════════════

def test_multi_symbol_strategy_creation():
    print()
    print("=" * 60)
    print("TEST 6: MultiSymbolBuilderStrategy creation")
    print("=" * 60)
    
    strategy = MultiSymbolBuilderStrategy(
        strategy_config=SIMPLE_STRATEGY_CONFIG,
        symbols=["XAUUSD", "XAGUSD"],
        point_values={"XAUUSD": 1.0, "XAGUSD": 5.0},
    )
    
    check("Strategy name", strategy.name == "MultiSymbolBuilder")
    check("Symbols list", strategy.symbols == ["XAUUSD", "XAGUSD"])
    check("Point values", strategy.point_values == {"XAUUSD": 1.0, "XAGUSD": 5.0})
    check("Config stored", strategy.config == SIMPLE_STRATEGY_CONFIG)


# ════════════════════════════════════════════════════════════════════
# TEST 7: run_v2_portfolio_backtest — 2-symbol execution
# ════════════════════════════════════════════════════════════════════

def test_run_v2_portfolio_backtest():
    print()
    print("=" * 60)
    print("TEST 7: run_v2_portfolio_backtest (2 symbols)")
    print("=" * 60)
    
    bars_gold = make_bars(n=500, start_price=2000.0, seed=42, volatility=5.0, trend=0.02)
    bars_silver = make_bars(n=500, start_price=30.0, seed=99, volatility=0.5, trend=0.01)
    
    symbols_data = [
        {"symbol": "XAUUSD", "bars": bars_gold, "point_value": 1.0},
        {"symbol": "XAGUSD", "bars": bars_silver, "point_value": 5.0},
    ]
    
    t0 = time.perf_counter()
    result, analytics = run_v2_portfolio_backtest(
        symbols_data=symbols_data,
        strategy_config=SIMPLE_STRATEGY_CONFIG,
        initial_balance=10_000.0,
        spread_points=0.5,
        commission_per_lot=3.0,
        margin_rate=0.01,
        bars_per_day=144.0,
    )
    elapsed = time.perf_counter() - t0
    
    check("Returns RunResult", isinstance(result, RunResult))
    check("Returns portfolio analytics dict", isinstance(analytics, dict))
    check("Has equity_curve", len(result.equity_curve) > 0,
          f"len={len(result.equity_curve)}")
    check("Has closed_trades", isinstance(result.closed_trades, list))
    
    # Check that trades have symbol field
    if result.closed_trades:
        syms_in_trades = set(t.get("symbol", "") for t in result.closed_trades)
        check("Trades have symbol field", all(s != "" for s in syms_in_trades),
              f"symbols_in_trades={syms_in_trades}")
    
    # Analytics structure
    check("analytics.per_symbol present", "per_symbol" in analytics)
    check("analytics.correlation present", "correlation" in analytics)
    check("analytics.diversification_ratio present", "diversification_ratio" in analytics)
    check("analytics.num_symbols == 2", analytics.get("num_symbols") == 2)
    
    # Performance
    check(f"Completed in < 10s", elapsed < 10.0, f"elapsed={elapsed:.3f}s")
    
    print(f"\n  Total closed trades: {len(result.closed_trades)}")
    print(f"  Elapsed: {elapsed:.3f}s")
    if "per_symbol" in analytics:
        for sym, st in analytics["per_symbol"].items():
            print(f"  {sym}: {st['total_trades']} trades, "
                  f"win_rate={st['win_rate']:.1f}%, net={st['net_profit']:.2f}")
    if "correlation" in analytics:
        print(f"  Avg correlation: {analytics['correlation'].get('avg_correlation', 'N/A')}")
        print(f"  Diversification ratio: {analytics.get('diversification_ratio', 'N/A')}")


# ════════════════════════════════════════════════════════════════════
# TEST 8: v2_portfolio_result_to_api_response — response shape
# ════════════════════════════════════════════════════════════════════

def test_v2_portfolio_result_to_api_response():
    print()
    print("=" * 60)
    print("TEST 8: v2_portfolio_result_to_api_response")
    print("=" * 60)
    
    bars_a = make_bars(n=300, start_price=1000.0, seed=10)
    bars_b = make_bars(n=300, start_price=50.0, seed=20)
    
    symbols_data = [
        {"symbol": "SYM_A", "bars": bars_a, "point_value": 1.0},
        {"symbol": "SYM_B", "bars": bars_b, "point_value": 2.0},
    ]
    
    result, analytics = run_v2_portfolio_backtest(
        symbols_data=symbols_data,
        strategy_config=SIMPLE_STRATEGY_CONFIG,
        initial_balance=10_000.0,
    )
    
    response = v2_portfolio_result_to_api_response(
        run_result=result,
        portfolio_analytics=analytics,
        initial_balance=10_000.0,
        total_bars=300,
    )
    
    check("Response is dict", isinstance(response, dict))
    check("Response has portfolio_analytics", "portfolio_analytics" in response)
    check("Response has trades", "trades" in response)
    check("Response has equity_curve", "equity_curve" in response)
    check("Response has stats", "stats" in response)
    check("portfolio_analytics matches input", response["portfolio_analytics"] == analytics)


# ════════════════════════════════════════════════════════════════════
# TEST 9: Single-symbol still works (backward compatibility)
# ════════════════════════════════════════════════════════════════════

def test_single_symbol_backtest():
    print()
    print("=" * 60)
    print("TEST 9: Single-symbol backward compatibility")
    print("=" * 60)
    
    from app.services.backtest.v2_adapter import run_v2_backtest
    
    bars = make_bars(n=300, start_price=2000.0, seed=42)
    
    result = run_v2_backtest(
        bars=bars,
        strategy_config=SIMPLE_STRATEGY_CONFIG,
        symbol="XAUUSD",
        point_value=1.0,
        initial_balance=10_000.0,
        spread_points=0.5,
        commission_per_lot=3.0,
    )
    
    check("Single-symbol returns RunResult", isinstance(result, RunResult))
    check("Has equity_curve", len(result.equity_curve) > 0)
    check("Has stats", isinstance(result.stats, dict))
    
    # Single-symbol result should not have portfolio_analytics
    # (it's a RunResult, not an API response)
    check("RunResult doesn't have portfolio_analytics attr",
          not hasattr(result, "portfolio_analytics"))


# ════════════════════════════════════════════════════════════════════
# TEST 10: Schema backward compatibility
# ════════════════════════════════════════════════════════════════════

def test_schema_backward_compat():
    print()
    print("=" * 60)
    print("TEST 10: Schema backward compatibility")
    print("=" * 60)
    
    # V1-style request (no datasource_ids) should work
    req1 = BacktestRequest(strategy_id=1, datasource_id=1)
    check("Default datasource_ids is None", req1.datasource_ids is None)
    check("Default engine_version is v1", req1.engine_version == "v1")
    
    # V2 request with datasource_ids
    req2 = BacktestRequest(
        strategy_id=1,
        datasource_id=1,
        engine_version="v2",
        datasource_ids=[1, 2, 3],
    )
    check("datasource_ids set", req2.datasource_ids == [1, 2, 3])
    check("engine_version is v2", req2.engine_version == "v2")
    
    # Response schema: portfolio_analytics is optional
    # Just validate the model accepts None
    stats = {
        "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
        "win_rate": 0, "gross_profit": 0, "gross_loss": 0,
        "net_profit": 0, "profit_factor": 0, "max_drawdown": 0,
        "max_drawdown_pct": 0, "avg_win": 0, "avg_loss": 0,
        "largest_win": 0, "largest_loss": 0, "avg_trade": 0,
        "sharpe_ratio": 0, "expectancy": 0, "total_bars": 0,
    }
    resp = BacktestResponse(
        id=1, strategy_id=1, datasource_id=1,
        status="completed", stats=stats, trades=[], equity_curve=[],
    )
    check("portfolio_analytics defaults to None", resp.portfolio_analytics is None)
    check("symbols defaults to None", resp.symbols is None)
    
    # With portfolio data
    resp2 = BacktestResponse(
        id=2, strategy_id=1, datasource_id=1,
        status="completed", stats=stats, trades=[], equity_curve=[],
        portfolio_analytics={"per_symbol": {}, "num_symbols": 2},
        symbols=["XAUUSD", "XAGUSD"],
    )
    check("portfolio_analytics set", resp2.portfolio_analytics is not None)
    check("symbols set", resp2.symbols == ["XAUUSD", "XAGUSD"])


# ════════════════════════════════════════════════════════════════════
# TEST 11: Portfolio with 3 symbols
# ════════════════════════════════════════════════════════════════════

def test_three_symbol_portfolio():
    print()
    print("=" * 60)
    print("TEST 11: Three-symbol portfolio backtest")
    print("=" * 60)
    
    bars_1 = make_bars(n=400, start_price=2000.0, seed=42, volatility=5.0)
    bars_2 = make_bars(n=400, start_price=30.0, seed=99, volatility=0.5)
    bars_3 = make_bars(n=400, start_price=35000.0, seed=77, volatility=200.0)
    
    symbols_data = [
        {"symbol": "XAUUSD", "bars": bars_1, "point_value": 1.0},
        {"symbol": "XAGUSD", "bars": bars_2, "point_value": 5.0},
        {"symbol": "US30", "bars": bars_3, "point_value": 1.0},
    ]
    
    # Allow 3 positions total
    config = dict(SIMPLE_STRATEGY_CONFIG)
    config["risk_params"] = dict(config["risk_params"])
    config["risk_params"]["max_positions"] = 3
    
    result, analytics = run_v2_portfolio_backtest(
        symbols_data=symbols_data,
        strategy_config=config,
        initial_balance=50_000.0,
        spread_points=0.5,
    )
    
    check("3-symbol: Returns RunResult", isinstance(result, RunResult))
    check("3-symbol: analytics.num_symbols == 3", analytics.get("num_symbols") == 3)
    check("3-symbol: correlation matrix 3x3",
          len(analytics["correlation"]["matrix"]) == 3 and
          len(analytics["correlation"]["matrix"][0]) == 3)
    check("3-symbol: diversification_ratio present",
          isinstance(analytics.get("diversification_ratio"), (int, float)))
    
    n_trades = len(result.closed_trades)
    print(f"\n  Total trades across 3 symbols: {n_trades}")
    if "per_symbol" in analytics:
        for sym, st in analytics["per_symbol"].items():
            print(f"  {sym}: {st['total_trades']} trades, WR={st['win_rate']:.1f}%")


# ════════════════════════════════════════════════════════════════════
# TEST 12: Edge case — portfolio with 1 symbol (graceful fallback)
# ════════════════════════════════════════════════════════════════════

def test_single_symbol_in_portfolio_mode():
    print()
    print("=" * 60)
    print("TEST 12: Single symbol in portfolio mode (edge case)")
    print("=" * 60)
    
    bars = make_bars(n=300, start_price=2000.0, seed=42)
    
    symbols_data = [
        {"symbol": "XAUUSD", "bars": bars, "point_value": 1.0},
    ]
    
    result, analytics = run_v2_portfolio_backtest(
        symbols_data=symbols_data,
        strategy_config=SIMPLE_STRATEGY_CONFIG,
        initial_balance=10_000.0,
    )
    
    check("1-symbol portfolio: Returns RunResult", isinstance(result, RunResult))
    check("1-symbol portfolio: num_symbols == 1", analytics.get("num_symbols") == 1)
    check("1-symbol portfolio: diversification_ratio == 1",
          analytics.get("diversification_ratio") == 1.0)
    check("1-symbol portfolio: correlation matrix [[1.0]]",
          analytics["correlation"]["matrix"] == [[1.0]])


# ════════════════════════════════════════════════════════════════════
# TEST 13: Edge case — all trades are winners or losers
# ════════════════════════════════════════════════════════════════════

def test_edge_case_all_winners_losers():
    print()
    print("=" * 60)
    print("TEST 13: Edge cases — all winners / all losers / no trades")
    print("=" * 60)
    
    # All winners
    all_wins = [
        {"symbol": "A", "pnl": 10, "commission": 1},
        {"symbol": "A", "pnl": 20, "commission": 1},
    ]
    stats_w = per_symbol_stats(all_wins)
    check("All winners: win_rate == 100%", stats_w["A"]["win_rate"] == 100.0)
    check("All winners: profit_factor max", stats_w["A"]["profit_factor"] == 999.99)
    
    # All losers
    all_losses = [
        {"symbol": "B", "pnl": -10, "commission": 1},
        {"symbol": "B", "pnl": -5, "commission": 1},
    ]
    stats_l = per_symbol_stats(all_losses)
    check("All losers: win_rate == 0%", stats_l["B"]["win_rate"] == 0.0)
    check("All losers: profit_factor == 0", stats_l["B"]["profit_factor"] == 0.0)
    
    # No trades
    stats_empty = per_symbol_stats([])
    check("No trades: empty dict", stats_empty == {})


# ════════════════════════════════════════════════════════════════════
# TEST 14: Correlated vs uncorrelated symbols have different DR
# ════════════════════════════════════════════════════════════════════

def test_correlation_vs_diversification():
    print()
    print("=" * 60)
    print("TEST 14: Correlated vs uncorrelated diversification")
    print("=" * 60)
    
    bars_a_corr, bars_b_corr = make_correlated_bars(n=500, seed1=42, seed2=99, corr=0.9)
    bars_a_uncorr, bars_b_uncorr = make_correlated_bars(n=500, seed1=42, seed2=99, corr=0.1)
    
    # Compute returns from close prices
    closes_corr = {
        "A": [b["close"] for b in bars_a_corr],
        "B": [b["close"] for b in bars_b_corr],
    }
    closes_uncorr = {
        "A": [b["close"] for b in bars_a_uncorr],
        "B": [b["close"] for b in bars_b_uncorr],
    }
    
    rets_corr = compute_symbol_returns(closes_corr)
    rets_uncorr = compute_symbol_returns(closes_uncorr)
    
    dr_corr = diversification_ratio(rets_corr)
    dr_uncorr = diversification_ratio(rets_uncorr)
    
    check("Higher correlation => lower DR",
          dr_corr < dr_uncorr,
          f"dr_corr={dr_corr}, dr_uncorr={dr_uncorr}")
    
    corr_high = correlation_matrix(rets_corr)
    corr_low = correlation_matrix(rets_uncorr)
    
    check("High corr pair has higher avg_corr",
          corr_high["avg_correlation"] > corr_low["avg_correlation"],
          f"high={corr_high['avg_correlation']}, low={corr_low['avg_correlation']}")


# ════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("╔" + "═" * 58 + "╗")
    print("║  Phase 4 — Multi-Symbol Portfolio Smoke Tests           ║")
    print("╚" + "═" * 58 + "╝")
    
    t_start = time.perf_counter()
    
    test_per_symbol_stats()         # Test 1
    test_correlation_matrix()       # Test 2
    test_compute_symbol_returns()   # Test 3
    test_diversification_ratio()    # Test 4
    test_build_portfolio_analytics()  # Test 5
    test_multi_symbol_strategy_creation()  # Test 6
    test_run_v2_portfolio_backtest()  # Test 7
    test_v2_portfolio_result_to_api_response()  # Test 8
    test_single_symbol_backtest()   # Test 9
    test_schema_backward_compat()   # Test 10
    test_three_symbol_portfolio()   # Test 11
    test_single_symbol_in_portfolio_mode()  # Test 12
    test_edge_case_all_winners_losers()  # Test 13
    test_correlation_vs_diversification()  # Test 14
    
    elapsed = time.perf_counter() - t_start
    
    print()
    print("═" * 60)
    total = OK + FAIL
    print(f"  Phase 4 Results: {OK}/{total} passed, {FAIL} failed  ({elapsed:.2f}s)")
    print("═" * 60)
    
    if FAIL > 0:
        print("\n  *** SOME TESTS FAILED ***")
        sys.exit(1)
    else:
        print("\n  All Phase 4 portfolio tests passed!")
        sys.exit(0)
