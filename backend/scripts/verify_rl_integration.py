"""
Final comprehensive verification of Track A: RL Integration.
Tests all components end-to-end.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def test_rl_signal_filter():
    """Test RLSignalFilter loads and runs inference."""
    from app.services.agent.rl_signal_filter import RLSignalFilter
    import numpy as np

    onnx_path = os.path.join(os.path.dirname(__file__), "..", "data", "ml_models", "rl_lw_us30.onnx")
    if not os.path.exists(onnx_path):
        print("[SKIP] US30 ONNX model not found")
        return False

    filt = RLSignalFilter(onnx_path=onnx_path)
    assert filt.load(), "Failed to load RLSignalFilter"
    print("[OK] RLSignalFilter loaded successfully")

    # Generate fake bars (need 30+ for indicators)
    np.random.seed(42)
    bars = []
    price = 42000.0
    for i in range(50):
        o = price + np.random.randn() * 50
        h = o + abs(np.random.randn() * 30)
        l = o - abs(np.random.randn() * 30)
        c = o + np.random.randn() * 20
        bars.append({
            "open": o, "high": h, "low": l, "close": c,
            "volume": 1000 + np.random.randint(0, 500),
            "time": f"2024-01-{(i+1):02d}T10:00:00",
        })
        price = c

    # Test evaluate_signal
    result = filt.evaluate_signal(
        strategy_direction=1,
        strategy_confidence=0.75,
        bars=bars,
        position_dir=0,
    )
    assert "approved" in result, "Missing 'approved' in result"
    assert "rl_action" in result, "Missing 'rl_action' in result"
    assert "rl_confidence" in result, "Missing 'rl_confidence' in result"
    assert "reason" in result, "Missing 'reason' in result"
    assert result["rl_action"] in ("skip", "take", "close"), f"Invalid action: {result['rl_action']}"
    print(f"[OK] evaluate_signal returned: action={result['rl_action']}, "
          f"approved={result['approved']}, confidence={result['rl_confidence']:.3f}")

    # Test with position (should potentially trigger close)
    result2 = filt.evaluate_signal(
        strategy_direction=-1,
        strategy_confidence=0.8,
        bars=bars,
        position_dir=1,
        position_pnl=-0.02,
    )
    print(f"[OK] With position: action={result2['rl_action']}, "
          f"approved={result2['approved']}, close_position={result2.get('close_position', False)}")

    return True


def test_performance_monitor():
    """Test RLPerformanceMonitor tracking."""
    from app.services.agent.rl_performance_monitor import RLPerformanceMonitor

    monitor = RLPerformanceMonitor()
    model_id = 999

    # Record some winning trades
    for _ in range(5):
        monitor.record_trade(model_id, 50.0)

    # Record some losing trades
    for _ in range(3):
        monitor.record_trade(model_id, -30.0)

    metrics = monitor.get_metrics(model_id)
    assert metrics["total_trades"] == 8, f"Expected 8 trades, got {metrics['total_trades']}"
    assert metrics["winning_trades"] == 5, f"Expected 5 wins, got {metrics['winning_trades']}"
    assert abs(metrics["win_rate"] - 62.5) < 0.1, f"Expected 62.5% WR, got {metrics['win_rate']}"
    assert metrics["gross_profit"] == 250.0, f"Expected $250 profit, got {metrics['gross_profit']}"
    assert metrics["gross_loss"] == 90.0, f"Expected $90 loss, got {metrics['gross_loss']}"

    pf = metrics["profit_factor"]
    expected_pf = 250.0 / 90.0
    assert abs(pf - expected_pf) < 0.01, f"Expected PF {expected_pf:.3f}, got {pf}"

    print(f"[OK] Performance monitor: {metrics['total_trades']} trades, "
          f"WR={metrics['win_rate']}%, PF={pf:.3f}")

    # Test losing streak alert
    monitor2 = RLPerformanceMonitor()
    model_id2 = 998
    for i in range(10):
        alert = monitor2.record_trade(model_id2, -20.0)

    assert alert is not None, "Expected alert after 10 consecutive losses"
    assert alert["level"] == "warning", f"Expected warning, got {alert['level']}"
    assert alert["type"] == "losing_streak", f"Expected losing_streak, got {alert['type']}"
    print(f"[OK] Losing streak alert: {alert['message']}")

    # Test should_disable (need 100+ trades with bad PF)
    monitor3 = RLPerformanceMonitor()
    model_id3 = 997
    # 40 wins at $10, 61 losses at $10 => PF = 400/610 = 0.656
    for _ in range(40):
        monitor3.record_trade(model_id3, 10.0)
    for _ in range(61):
        monitor3.record_trade(model_id3, -10.0)

    assert monitor3.should_disable(model_id3), "Expected should_disable=True for PF=0.656"
    print(f"[OK] Auto-disable check works (PF < 0.9 after 100+ trades)")

    return True


def test_schema():
    """Test RLModelRegisterRequest schema."""
    from app.schemas.ml import RLModelRegisterRequest

    req = RLModelRegisterRequest(
        name="RL LW US30 PPO",
        symbol="US30",
        timeframe="M5",
        onnx_filename="rl_lw_us30.onnx",
        eval_avg_pnl=640.44,
        eval_avg_wr=55.1,
        eval_avg_trades=563.7,
        eval_avg_dd=4.9,
        timesteps=500000,
        feature_space="lw_25",
    )
    assert req.name == "RL LW US30 PPO"
    assert req.symbol == "US30"
    assert req.eval_avg_pnl == 640.44
    print(f"[OK] RLModelRegisterRequest schema validated: {req.name}")
    return True


def test_onnx_files():
    """Verify ONNX model files exist and have correct shapes."""
    try:
        import onnxruntime as ort
    except ImportError:
        print("[SKIP] onnxruntime not installed")
        return True

    import numpy as np
    model_dir = os.path.join(os.path.dirname(__file__), "..", "data", "ml_models")

    for symbol in ["us30", "xauusd"]:
        onnx_path = os.path.join(model_dir, f"rl_lw_{symbol}.onnx")
        stats_path = os.path.join(model_dir, f"rl_lw_{symbol}_stats.npz")

        if not os.path.exists(onnx_path):
            print(f"[SKIP] {symbol} ONNX not found")
            continue

        # Check ONNX
        sess = ort.InferenceSession(onnx_path)
        inp = sess.get_inputs()[0]
        out = sess.get_outputs()[0]
        assert inp.shape[1] == 32, f"Expected input dim 32, got {inp.shape}"
        assert out.shape[1] == 3, f"Expected output dim 3, got {out.shape}"

        # Test inference
        test_obs = np.random.randn(1, 32).astype(np.float32)
        result = sess.run(None, {"obs": test_obs})[0]
        assert result.shape == (1, 3), f"Expected output (1, 3), got {result.shape}"
        print(f"[OK] {symbol.upper()} ONNX: input={inp.shape}, output={out.shape}")

        # Check stats
        if os.path.exists(stats_path):
            stats = np.load(stats_path)
            assert stats["obs_mean"].shape == (32,), f"Bad obs_mean shape: {stats['obs_mean'].shape}"
            assert stats["obs_var"].shape == (32,), f"Bad obs_var shape: {stats['obs_var'].shape}"
            print(f"[OK] {symbol.upper()} stats: mean={stats['obs_mean'].shape}, var={stats['obs_var'].shape}")

    return True


def test_imports():
    """Test all critical imports work."""
    from app.services.agent.rl_signal_filter import RLSignalFilter
    print("[OK] Import: RLSignalFilter")

    from app.services.agent.rl_performance_monitor import rl_performance_monitor
    print("[OK] Import: rl_performance_monitor")

    from app.schemas.ml import RLModelRegisterRequest
    print("[OK] Import: RLModelRegisterRequest")

    # Verify trade_monitor has RL recording method
    from app.services.agent.trade_monitor import trade_monitor
    assert hasattr(trade_monitor, '_record_rl_performance'), "Missing _record_rl_performance method"
    print("[OK] Import: trade_monitor._record_rl_performance exists")

    return True


if __name__ == "__main__":
    print("=" * 60)
    print("  Track A: RL Integration — Final Verification")
    print("=" * 60)

    tests = [
        ("Imports", test_imports),
        ("ONNX Files", test_onnx_files),
        ("RLSignalFilter", test_rl_signal_filter),
        ("Performance Monitor", test_performance_monitor),
        ("Schema", test_schema),
    ]

    passed = 0
    failed = 0
    for name, test_fn in tests:
        print(f"\n--- {name} ---")
        try:
            if test_fn():
                passed += 1
            else:
                failed += 1
                print(f"[FAIL] {name}")
        except Exception as e:
            failed += 1
            print(f"[FAIL] {name}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'=' * 60}")
    print(f"  Results: {passed}/{passed + failed} passed")
    if failed == 0:
        print("  ALL TESTS PASSED!")
    else:
        print(f"  {failed} FAILED")
    print(f"{'=' * 60}")
