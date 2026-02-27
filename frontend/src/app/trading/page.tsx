"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { api } from "@/lib/api";
import ChatHelpers from "@/components/ChatHelpers";
import AgentPanel from "@/components/AgentPanel";
import CandlestickChart, { type ChartHandle, type CandleInput } from "@/components/CandlestickChart";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useMarketData } from "@/hooks/useMarketData";
import { useSettings } from "@/hooks/useSettings";
import type {
  AccountInfo,
  LivePosition,
  LiveOrder,
  PlaceOrderRequest,
  BrokerListResponse,
  TradeHistory,
} from "@/types";

/* ── tiny helpers ─────────────────────────────────── */

const pnlColor = (v: number) =>
  v > 0 ? "text-green-400" : v < 0 ? "text-red-400" : "text-muted";

const fmt = (n: number, d = 2) => n.toFixed(d);
const fmtK = (n: number) =>
  Math.abs(n) >= 1000 ? `${(n / 1000).toFixed(1)}k` : fmt(n, 2);

/* ═══════════════════════════════════════════════════ */

export default function TradingPage() {
  /* ── state ────────────────────────────────────── */
  const [connected, setConnected] = useState(false);
  const [brokerName, setBrokerName] = useState<string | null>(null);
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [positions, setPositions] = useState<LivePosition[]>([]);
  const [orders, setOrders] = useState<LiveOrder[]>([]);
  const [trades, setTrades] = useState<TradeHistory[]>([]);
  const [error, setError] = useState("");

  // connect modal
  const [showConnect, setShowConnect] = useState(false);
  const [cBroker, setCBroker] = useState("oanda");
  const [cApiKey, setCApiKey] = useState("");
  const [cAccountId, setCAccountId] = useState("");
  const [cPractice, setCPractice] = useState(true);
  const [cExtra, setCExtra] = useState<Record<string, string>>({});
  const [connecting, setConnecting] = useState(false);

  // order panel
  const [showOrder, setShowOrder] = useState(false);
  const [oSymbol, setOSymbol] = useState("EUR_USD");
  const [oSide, setOSide] = useState<"BUY" | "SELL">("BUY");
  const [oSize, setOSize] = useState("1000");
  const [oType, setOType] = useState("MARKET");
  const [oPrice, setOPrice] = useState("");
  const [oSL, setOSL] = useState("");
  const [oTP, setOTP] = useState("");
  const [placing, setPlacing] = useState(false);

  // polling
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Chart state ──
  const SYMBOLS = ["XAUUSD", "XAGUSD", "US30", "NAS100"];
  const TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];
  const [chartSymbol, setChartSymbol] = useState("XAUUSD");
  const [chartTimeframe, setChartTimeframe] = useState("H1");
  const [chartMode, setChartMode] = useState<"live" | "static">("live"); // MT5 Live vs Static
  const [chartBars, setChartBars] = useState<CandleInput[]>([]);
  const [chartLoading, setChartLoading] = useState(false);
  const chartRef = useRef<ChartHandle>(null);
  const wsStatus = useWebSocket((s) => s.status);
  const { ticks, bars, currentBar, subscribeBars, subscribeTicks } = useMarketData();
  const { settings } = useSettings();

  // ── Connect WebSocket on mount ──
  useEffect(() => {
    const { connect, status } = useWebSocket.getState();
    if (status === "disconnected") {
      connect();
    }
  }, []);

  // ── Load initial chart bars ──
  const loadChartBars = useCallback(async (sym: string, tf: string) => {
    setChartLoading(true);
    try {
      if (chartMode === "live") {
        // Try MT5 bars first (works when MT5 broker is connected)
        try {
          const res = await api.get<{ bars: CandleInput[] }>(
            `/api/market/mt5/bars/${sym}?timeframe=${tf}&count=500`
          );
          if (res.bars && res.bars.length > 0) {
            setChartBars(res.bars);
            return;
          }
        } catch {
          // MT5 not connected — fall through to generic provider
        }
        // Fallback: try generic market data endpoint
        try {
          const res = await api.get<{ candles: CandleInput[] }>(
            `/api/market/candles/${sym}?timeframe=${tf}&count=500`
          );
          setChartBars(res.candles || []);
        } catch {
          setChartBars([]);
        }
      } else {
        // Static mode — try generic market data endpoint
        try {
          const res = await api.get<{ candles: CandleInput[] }>(
            `/api/market/candles/${sym}?timeframe=${tf}&count=500`
          );
          setChartBars(res.candles || []);
        } catch {
          setChartBars([]);
        }
      }
    } catch {
      setChartBars([]);
    } finally {
      setChartLoading(false);
    }
  }, [chartMode]);

  // ── Reload bars when symbol/timeframe/mode changes ──
  useEffect(() => {
    loadChartBars(chartSymbol, chartTimeframe);
  }, [chartSymbol, chartTimeframe, chartMode, loadChartBars]);

  // ── Subscribe to live bars when in live mode ──
  useEffect(() => {
    if (chartMode !== "live" || wsStatus !== "connected") return;

    const unsubBars = subscribeBars(chartSymbol, chartTimeframe);
    const unsubTicks = subscribeTicks(chartSymbol);

    return () => {
      unsubBars();
      unsubTicks();
    };
  }, [chartMode, chartSymbol, chartTimeframe, wsStatus, subscribeBars, subscribeTicks]);

  // ── Stream live bar updates to chart ──
  const barKey = `${chartSymbol}:${chartTimeframe}`;
  const liveBarArray = bars[barKey];
  const liveBarCount = liveBarArray?.length ?? 0;
  const liveCurrentBar = currentBar[barKey];

  useEffect(() => {
    if (!chartRef.current || chartMode !== "live") return;
    // Don't push live bars before chart has initial data
    if (chartBars.length === 0) return;
    const liveBars = liveBarArray || [];
    if (liveBars.length > 0) {
      const lastBar = liveBars[liveBars.length - 1];
      if (lastBar && typeof lastBar.time === "number" && lastBar.time > 0) {
        chartRef.current.updateBar(lastBar);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveBarCount, chartMode, chartBars.length]);

  useEffect(() => {
    if (!chartRef.current || chartMode !== "live" || !liveCurrentBar) return;
    // Don't push live bars before chart has initial data
    if (chartBars.length === 0) return;
    if (typeof liveCurrentBar.time === "number" && liveCurrentBar.time > 0) {
      chartRef.current.updateBar(liveCurrentBar);
    }
  }, [liveCurrentBar, chartMode, chartBars.length]);

  const currentTick = ticks[chartSymbol];

  // ── Chart auto-refresh polling fallback ──
  // When WebSocket bar updates aren't arriving (e.g. on deployed server without MT5),
  // poll the REST endpoint every 8 seconds to keep chart fresh.
  const lastBarUpdateRef = useRef<number>(Date.now());
  useEffect(() => {
    // Track when we last got a WS bar update
    lastBarUpdateRef.current = Date.now();
  }, [liveBarCount, liveCurrentBar]);

  useEffect(() => {
    if (chartMode !== "live" || chartBars.length === 0) return;

    const pollInterval = setInterval(async () => {
      const timeSinceUpdate = Date.now() - lastBarUpdateRef.current;
      // Only poll if no WS update in the last 10 seconds
      if (timeSinceUpdate < 10_000) return;

      try {
        // Fetch the latest few bars and merge with existing chart
        const res = await api.get<{ candles: CandleInput[] }>(
          `/api/market/candles/${chartSymbol}?timeframe=${chartTimeframe}&count=5`
        );
        const freshBars = res.candles || [];
        if (freshBars.length > 0 && chartRef.current) {
          for (const bar of freshBars) {
            if (typeof bar.time === "number" && bar.time > 0) {
              chartRef.current.updateBar(bar);
            }
          }
        }
      } catch {
        // Silent fail — polling is best-effort
      }
    }, 8_000);

    return () => clearInterval(pollInterval);
  }, [chartMode, chartSymbol, chartTimeframe, chartBars.length]);

  /* ── check broker on mount ────────────────────── */
  useEffect(() => {
    checkBrokerStatus();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const checkBrokerStatus = async () => {
    try {
      const res = await api.get<BrokerListResponse>("/api/broker/status");
      const names = Object.keys(res.brokers);
      if (names.length > 0 && res.brokers[names[0]].connected) {
        setConnected(true);
        setBrokerName(res.default_broker || names[0]);
        startPolling();
      }
    } catch {
      // no broker connected — that's fine
    }
  };

  /* ── polling loop ─────────────────────────────── */
  const refreshData = useCallback(async () => {
    try {
      const [acc, pos, ord, hist] = await Promise.all([
        api.get<AccountInfo>("/api/broker/account"),
        api.get<LivePosition[]>("/api/broker/positions"),
        api.get<LiveOrder[]>("/api/broker/orders"),
        api.get<TradeHistory[]>("/api/broker/trades?limit=20"),
      ]);
      setAccount(acc);
      setPositions(pos);
      setOrders(ord);
      setTrades(hist);
      setError("");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
    }
  }, []);

  const startPolling = useCallback(() => {
    refreshData();
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(refreshData, 3000);
  }, [refreshData]);

  /* ── connect ──────────────────────────────────── */
  const handleConnect = async () => {
    if (!cApiKey) return;
    setConnecting(true);
    setError("");
    try {
      await api.post("/api/broker/connect", {
        broker: cBroker,
        api_key: cApiKey,
        account_id: cAccountId,
        practice: cPractice,
        extra: cExtra,
      });
      setConnected(true);
      setBrokerName(cBroker);
      setShowConnect(false);
      startPolling();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Connection failed");
    } finally {
      setConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    if (!brokerName) return;
    try {
      await api.post(`/api/broker/disconnect/${brokerName}`, {});
      setConnected(false);
      setBrokerName(null);
      setAccount(null);
      setPositions([]);
      setOrders([]);
      if (pollRef.current) clearInterval(pollRef.current);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Disconnect failed");
    }
  };

  /* ── close position ───────────────────────────── */
  const closePosition = async (posId: string) => {
    try {
      await api.post("/api/broker/positions/close", { position_id: posId });
      refreshData();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Close failed");
    }
  };

  /* ── cancel order ─────────────────────────────── */
  const cancelOrder = async (orderId: string) => {
    try {
      await api.delete(`/api/broker/orders/${orderId}`);
      refreshData();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Cancel failed");
    }
  };

  /* ── place order ──────────────────────────────── */
  const placeOrder = async () => {
    if (!oSymbol || !oSize) return;
    setPlacing(true);
    setError("");
    try {
      const req: PlaceOrderRequest = {
        symbol: oSymbol,
        side: oSide,
        size: parseFloat(oSize),
        order_type: oType,
      };
      if (oType !== "MARKET" && oPrice) req.price = parseFloat(oPrice);
      if (oSL) req.stop_loss = parseFloat(oSL);
      if (oTP) req.take_profit = parseFloat(oTP);

      await api.post("/api/broker/orders", req);
      setShowOrder(false);
      refreshData();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Order failed");
    } finally {
      setPlacing(false);
    }
  };

  /* ═══════════════ RENDER ═══════════════════════ */
  return (
    <div className="space-y-4">
      {/* ── Header ─────────────────────────────── */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Live Trading</h2>
        <div className="flex items-center gap-3">
          {connected && (
            <>
              <span className="flex items-center gap-1.5 text-sm text-green-400">
                <span className="inline-block h-2 w-2 rounded-full bg-green-400 animate-pulse" />
                {brokerName}
              </span>
              <button
                onClick={() => setShowOrder(true)}
                className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/80 transition-colors"
              >
                New Order
              </button>
              <button
                onClick={handleDisconnect}
                className="rounded-lg border border-red-500/40 px-3 py-2 text-sm text-red-400 hover:bg-red-500/10 transition-colors"
              >
                Disconnect
              </button>
            </>
          )}
          {!connected && (
            <button
              onClick={() => setShowConnect(true)}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/80 transition-colors"
            >
              Connect Broker
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* ── Chart Panel ────────────────────────── */}
      <div className="rounded-xl border border-card-border bg-card-bg overflow-hidden">
        {/* Chart toolbar */}
        <div className="flex items-center justify-between border-b border-card-border px-4 py-2">
          <div className="flex items-center gap-3">
            {/* Symbol selector */}
            <select
              value={chartSymbol}
              onChange={(e) => setChartSymbol(e.target.value)}
              className="rounded-lg border border-card-border bg-background px-2 py-1.5 text-sm"
            >
              {SYMBOLS.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>

            {/* Timeframe selector */}
            <div className="flex gap-1">
              {TIMEFRAMES.map((tf) => (
                <button
                  key={tf}
                  onClick={() => setChartTimeframe(tf)}
                  className={`rounded px-2 py-1 text-xs font-medium transition-colors ${
                    chartTimeframe === tf
                      ? "bg-accent text-black"
                      : "text-muted hover:text-foreground hover:bg-card-border/50"
                  }`}
                >
                  {tf}
                </button>
              ))}
            </div>

            {/* Data source toggle */}
            <div className="flex items-center gap-2 ml-2">
              <button
                onClick={() => setChartMode("live")}
                className={`rounded px-2 py-1 text-xs font-medium transition-colors ${
                  chartMode === "live"
                    ? "bg-green-500/20 text-green-400 border border-green-500/40"
                    : "text-muted hover:text-foreground border border-transparent"
                }`}
              >
                MT5 Live
              </button>
              <button
                onClick={() => setChartMode("static")}
                className={`rounded px-2 py-1 text-xs font-medium transition-colors ${
                  chartMode === "static"
                    ? "bg-blue-500/20 text-blue-400 border border-blue-500/40"
                    : "text-muted hover:text-foreground border border-transparent"
                }`}
              >
                Chart Data
              </button>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Live tick display */}
            {currentTick && chartMode === "live" && (
              <div className="flex items-center gap-2 text-xs">
                <span className="text-muted">Bid:</span>
                <span className="font-mono">{currentTick.bid.toFixed(currentTick.bid < 10 ? 5 : 2)}</span>
                <span className="text-muted">Ask:</span>
                <span className="font-mono">{currentTick.ask.toFixed(currentTick.ask < 10 ? 5 : 2)}</span>
                <span className="text-muted">Spread:</span>
                <span className="font-mono">{currentTick.spread.toFixed(currentTick.spread < 1 ? 5 : 2)}</span>
              </div>
            )}

            {/* Connection status */}
            <span className={`flex items-center gap-1.5 text-xs ${
              chartMode === "live" && wsStatus === "connected"
                ? "text-green-400"
                : chartMode === "live" && wsStatus === "reconnecting"
                  ? "text-yellow-400"
                  : "text-zinc-500"
            }`}>
              <span className={`inline-block h-1.5 w-1.5 rounded-full ${
                chartMode === "live" && wsStatus === "connected"
                  ? "bg-green-400 animate-pulse"
                  : chartMode === "live" && wsStatus === "reconnecting"
                    ? "bg-yellow-400 animate-pulse"
                    : "bg-zinc-500"
              }`} />
              {chartMode === "live"
                ? wsStatus === "connected" ? "Live" : wsStatus === "reconnecting" ? "Reconnecting" : "Offline"
                : "Static"}
            </span>
          </div>
        </div>

        {/* Chart */}
        {chartLoading ? (
          <div className="flex h-[400px] items-center justify-center text-sm text-muted">
            Loading chart data...
          </div>
        ) : chartBars.length === 0 ? (
          <div className="flex h-[400px] flex-col items-center justify-center text-sm text-muted gap-2">
            <span>
              {chartMode === "live" && !connected
                ? "Connect MT5 broker to view live chart data"
                : chartMode === "live" && wsStatus !== "connected"
                  ? "WebSocket connecting... waiting for live data"
                  : "No chart data available — try switching to a different symbol or data source"}
            </span>
            {chartMode === "live" && !connected && (
              <button
                onClick={() => setShowConnect(true)}
                className="rounded-lg bg-accent/20 border border-accent/30 px-4 py-1.5 text-xs text-accent hover:bg-accent/30 transition-colors"
              >
                Connect Broker
              </button>
            )}
          </div>
        ) : (
          <CandlestickChart
            ref={chartRef}
            data={chartBars}
            height={400}
            upColor={settings?.chart_up_color || "#22c55e"}
            downColor={settings?.chart_down_color || "#ef4444"}
            showGrid={settings?.chart_grid !== false}
            showCrosshair={settings?.chart_crosshair !== false}
          />
        )}
      </div>

      {/* ── Connect Modal ──────────────────────── */}
      {showConnect && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="w-full max-w-md rounded-xl border border-card-border bg-[#1a1a2e] p-6 space-y-4 max-h-[90vh] overflow-y-auto">
            <h3 className="text-lg font-semibold">Connect Broker</h3>

            <div>
              <label className="block text-xs text-muted mb-1">Broker</label>
              <select
                value={cBroker}
                onChange={(e) => { setCBroker(e.target.value); setCApiKey(""); setCAccountId(""); setCExtra({}); }}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
              >
                <option value="oanda">Oanda (Forex/CFDs)</option>
                <option value="coinbase">Coinbase (Crypto)</option>
                <option value="mt5">MetaTrader 5</option>
                <option value="tradovate">Tradovate (Futures)</option>
              </select>
            </div>

            {/* ── Oanda fields ── */}
            {cBroker === "oanda" && (
              <>
                <div>
                  <label className="block text-xs text-muted mb-1">API Key (Token)</label>
                  <input type="password" value={cApiKey} onChange={(e) => setCApiKey(e.target.value)}
                    placeholder="Your Oanda API token" className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
                </div>
                <div>
                  <label className="block text-xs text-muted mb-1">Account ID</label>
                  <input value={cAccountId} onChange={(e) => setCAccountId(e.target.value)}
                    placeholder="e.g. 101-011-12345678-001" className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
                </div>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={cPractice} onChange={(e) => setCPractice(e.target.checked)} className="accent-accent" />
                  Practice / Demo Account
                </label>
              </>
            )}

            {/* ── Coinbase fields ── */}
            {cBroker === "coinbase" && (
              <>
                <div>
                  <label className="block text-xs text-muted mb-1">API Key</label>
                  <input type="password" value={cApiKey} onChange={(e) => setCApiKey(e.target.value)}
                    placeholder="Coinbase API key" className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
                </div>
                <div>
                  <label className="block text-xs text-muted mb-1">API Secret</label>
                  <input type="password" value={cExtra.api_secret || ""} onChange={(e) => setCExtra({ ...cExtra, api_secret: e.target.value })}
                    placeholder="Coinbase API secret" className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
                </div>
                <p className="text-xs text-muted">Create API keys in Coinbase → Settings → API</p>
              </>
            )}

            {/* ── MT5 fields ── */}
            {cBroker === "mt5" && (
              <>
                <div>
                  <label className="block text-xs text-muted mb-1">Server</label>
                  <input value={cExtra.server || ""} onChange={(e) => setCExtra({ ...cExtra, server: e.target.value })}
                    placeholder="e.g. MetaQuotes-Demo" className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
                </div>
                <div>
                  <label className="block text-xs text-muted mb-1">Login (Account Number)</label>
                  <input value={cExtra.login || ""} onChange={(e) => setCExtra({ ...cExtra, login: e.target.value })}
                    placeholder="e.g. 12345678" className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
                </div>
                <div>
                  <label className="block text-xs text-muted mb-1">Password</label>
                  <input type="password" value={cApiKey} onChange={(e) => setCApiKey(e.target.value)}
                    placeholder="MT5 account password" className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
                </div>
                <p className="text-xs text-muted">MetaTrader 5 terminal must be installed and running on this machine.</p>
              </>
            )}

            {/* ── Tradovate fields ── */}
            {cBroker === "tradovate" && (
              <>
                <div>
                  <label className="block text-xs text-muted mb-1">Username</label>
                  <input value={cExtra.username || ""} onChange={(e) => setCExtra({ ...cExtra, username: e.target.value })}
                    placeholder="Tradovate username" className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
                </div>
                <div>
                  <label className="block text-xs text-muted mb-1">Password</label>
                  <input type="password" value={cApiKey} onChange={(e) => setCApiKey(e.target.value)}
                    placeholder="Tradovate password" className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-muted mb-1">App ID</label>
                    <input value={cExtra.app_id || ""} onChange={(e) => setCExtra({ ...cExtra, app_id: e.target.value })}
                      placeholder="App ID" className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
                  </div>
                  <div>
                    <label className="block text-xs text-muted mb-1">Client ID</label>
                    <input value={cExtra.cid || ""} onChange={(e) => setCExtra({ ...cExtra, cid: e.target.value })}
                      placeholder="Client ID" className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
                  </div>
                </div>
                <div>
                  <label className="block text-xs text-muted mb-1">Client Secret</label>
                  <input type="password" value={cAccountId} onChange={(e) => setCAccountId(e.target.value)}
                    placeholder="Client secret" className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
                </div>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={cPractice} onChange={(e) => setCPractice(e.target.checked)} className="accent-accent" />
                  Demo / Simulated Account
                </label>
              </>
            )}

            <div className="flex justify-end gap-3 pt-2">
              <button
                onClick={() => setShowConnect(false)}
                className="rounded-lg border border-card-border px-4 py-2 text-sm text-muted hover:text-foreground"
              >
                Cancel
              </button>
              <button
                onClick={handleConnect}
                disabled={connecting || !cApiKey}
                className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/80 disabled:opacity-40"
              >
                {connecting ? "Connecting..." : "Connect"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Order Modal ────────────────────────── */}
      {showOrder && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="w-full max-w-md rounded-xl border border-card-border bg-[#1a1a2e] p-6 space-y-4">
            <h3 className="text-lg font-semibold">Place Order</h3>

            <div>
              <label className="block text-xs text-muted mb-1">Symbol</label>
              <input
                value={oSymbol}
                onChange={(e) => setOSymbol(e.target.value)}
                placeholder="EUR_USD"
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-muted mb-1">Side</label>
                <div className="flex gap-2">
                  <button
                    onClick={() => setOSide("BUY")}
                    className={`flex-1 rounded-lg py-2 text-sm font-medium transition-colors ${
                      oSide === "BUY"
                        ? "bg-green-500/20 text-green-400 border border-green-500/40"
                        : "border border-card-border text-muted hover:text-foreground"
                    }`}
                  >
                    BUY
                  </button>
                  <button
                    onClick={() => setOSide("SELL")}
                    className={`flex-1 rounded-lg py-2 text-sm font-medium transition-colors ${
                      oSide === "SELL"
                        ? "bg-red-500/20 text-red-400 border border-red-500/40"
                        : "border border-card-border text-muted hover:text-foreground"
                    }`}
                  >
                    SELL
                  </button>
                </div>
              </div>
              <div>
                <label className="block text-xs text-muted mb-1">Size (units)</label>
                <input
                  type="number"
                  value={oSize}
                  onChange={(e) => setOSize(e.target.value)}
                  className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs text-muted mb-1">Order Type</label>
              <select
                value={oType}
                onChange={(e) => setOType(e.target.value)}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
              >
                <option value="MARKET">Market</option>
                <option value="LIMIT">Limit</option>
                <option value="STOP">Stop</option>
              </select>
            </div>

            {oType !== "MARKET" && (
              <div>
                <label className="block text-xs text-muted mb-1">Price</label>
                <input
                  type="number"
                  step="any"
                  value={oPrice}
                  onChange={(e) => setOPrice(e.target.value)}
                  className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
                />
              </div>
            )}

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-muted mb-1">Stop Loss</label>
                <input
                  type="number"
                  step="any"
                  value={oSL}
                  onChange={(e) => setOSL(e.target.value)}
                  placeholder="Optional"
                  className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="block text-xs text-muted mb-1">Take Profit</label>
                <input
                  type="number"
                  step="any"
                  value={oTP}
                  onChange={(e) => setOTP(e.target.value)}
                  placeholder="Optional"
                  className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
                />
              </div>
            </div>

            <div className="flex justify-end gap-3 pt-2">
              <button
                onClick={() => setShowOrder(false)}
                className="rounded-lg border border-card-border px-4 py-2 text-sm text-muted hover:text-foreground"
              >
                Cancel
              </button>
              <button
                onClick={placeOrder}
                disabled={placing || !oSymbol || !oSize}
                className={`rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-40 transition-colors ${
                  oSide === "BUY"
                    ? "bg-green-600 hover:bg-green-700"
                    : "bg-red-600 hover:bg-red-700"
                }`}
              >
                {placing ? "Placing..." : `${oSide} ${oSymbol}`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Algo Agents Panel ────────────────── */}
      <AgentPanel />

      {/* ── Not Connected State ────────────────── */}
      {!connected && (
        <div className="flex flex-col items-center justify-center rounded-xl border border-card-border bg-card-bg p-16 text-center">
          <div className="text-4xl mb-4">📡</div>
          <h3 className="text-lg font-medium mb-2">No Broker Connected</h3>
          <p className="text-sm text-muted mb-6 max-w-md">
            Connect to a broker to see live positions, place orders, and monitor your
            account in real time.
          </p>
          <button
            onClick={() => setShowConnect(true)}
            className="rounded-lg bg-accent px-6 py-2.5 text-sm font-medium text-white hover:bg-accent/80 transition-colors"
          >
            Connect Broker
          </button>
        </div>
      )}

      {/* ── Connected Dashboard ────────────────── */}
      {connected && account && (
        <>
          {/* Account Summary Cards */}
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <div className="rounded-xl border border-card-border bg-card-bg p-4">
              <div className="text-xs text-muted mb-1">Balance</div>
              <div className="text-lg font-semibold">
                {account.currency} {fmtK(account.balance)}
              </div>
            </div>
            <div className="rounded-xl border border-card-border bg-card-bg p-4">
              <div className="text-xs text-muted mb-1">Equity</div>
              <div className="text-lg font-semibold">
                {account.currency} {fmtK(account.equity)}
              </div>
            </div>
            <div className="rounded-xl border border-card-border bg-card-bg p-4">
              <div className="text-xs text-muted mb-1">Unrealized P&L</div>
              <div className={`text-lg font-semibold ${pnlColor(account.unrealized_pnl)}`}>
                {account.unrealized_pnl >= 0 ? "+" : ""}
                {fmt(account.unrealized_pnl)}
              </div>
            </div>
            <div className="rounded-xl border border-card-border bg-card-bg p-4">
              <div className="text-xs text-muted mb-1">Margin Used / Free</div>
              <div className="text-lg font-semibold">
                {fmtK(account.margin_used)}{" "}
                <span className="text-xs text-muted font-normal">
                  / {fmtK(account.margin_available)}
                </span>
              </div>
            </div>
          </div>

          {/* Positions & Orders */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {/* Open Positions */}
            <div className="rounded-xl border border-card-border bg-card-bg p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-medium text-muted">
                  Open Positions ({positions.length})
                </h3>
                <button
                  onClick={refreshData}
                  className="text-xs text-muted hover:text-accent transition-colors"
                >
                  Refresh
                </button>
              </div>

              {positions.length === 0 ? (
                <div className="flex h-32 items-center justify-center text-sm text-muted">
                  No open positions
                </div>
              ) : (
                <div className="space-y-2">
                  {positions.map((p) => (
                    <div
                      key={p.position_id}
                      className="flex items-center justify-between rounded-lg border border-card-border bg-background/50 p-3"
                    >
                      <div className="flex items-center gap-3">
                        <span
                          className={`rounded px-2 py-0.5 text-xs font-medium ${
                            p.side === "LONG"
                              ? "bg-green-500/20 text-green-400"
                              : "bg-red-500/20 text-red-400"
                          }`}
                        >
                          {p.side}
                        </span>
                        <div>
                          <div className="text-sm font-medium">{p.symbol}</div>
                          <div className="text-xs text-muted">
                            {p.size} units @ {fmt(p.entry_price, 5)}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-4">
                        <div className="text-right">
                          <div className={`text-sm font-medium ${pnlColor(p.unrealized_pnl)}`}>
                            {p.unrealized_pnl >= 0 ? "+" : ""}
                            {fmt(p.unrealized_pnl)}
                          </div>
                          <div className="text-xs text-muted">
                            {fmt(p.current_price, 5)}
                          </div>
                        </div>
                        <button
                          onClick={() => closePosition(p.position_id)}
                          className="rounded border border-red-500/40 px-2 py-1 text-xs text-red-400 hover:bg-red-500/10 transition-colors"
                          title="Close position"
                        >
                          Close
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Pending Orders */}
            <div className="rounded-xl border border-card-border bg-card-bg p-5">
              <h3 className="text-sm font-medium text-muted mb-4">
                Pending Orders ({orders.length})
              </h3>

              {orders.length === 0 ? (
                <div className="flex h-32 items-center justify-center text-sm text-muted">
                  No pending orders
                </div>
              ) : (
                <div className="space-y-2">
                  {orders.map((o) => (
                    <div
                      key={o.order_id}
                      className="flex items-center justify-between rounded-lg border border-card-border bg-background/50 p-3"
                    >
                      <div className="flex items-center gap-3">
                        <span
                          className={`rounded px-2 py-0.5 text-xs font-medium ${
                            o.side === "BUY"
                              ? "bg-green-500/20 text-green-400"
                              : "bg-red-500/20 text-red-400"
                          }`}
                        >
                          {o.side}
                        </span>
                        <div>
                          <div className="text-sm font-medium">{o.symbol}</div>
                          <div className="text-xs text-muted">
                            {o.order_type} — {o.size} units
                            {o.price ? ` @ ${fmt(o.price, 5)}` : ""}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <div className="text-right text-xs text-muted">
                          {o.stop_loss && <div>SL: {fmt(o.stop_loss, 5)}</div>}
                          {o.take_profit && <div>TP: {fmt(o.take_profit, 5)}</div>}
                        </div>
                        <button
                          onClick={() => cancelOrder(o.order_id)}
                          className="rounded border border-red-500/40 px-2 py-1 text-xs text-red-400 hover:bg-red-500/10 transition-colors"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Risk Monitor */}
          <div className="rounded-xl border border-card-border bg-card-bg p-5">
            <h3 className="text-sm font-medium text-muted mb-4">Risk Monitor</h3>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
              <div>
                <div className="text-xs text-muted mb-1">Total Exposure</div>
                <div className="text-sm font-medium">
                  {positions.reduce((s, p) => s + p.size * p.current_price, 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted mb-1">Positions</div>
                <div className="text-sm font-medium">{positions.length}</div>
              </div>
              <div>
                <div className="text-xs text-muted mb-1">Margin Level</div>
                <div className="text-sm font-medium">
                  {account.margin_used > 0
                    ? `${((account.equity / account.margin_used) * 100).toFixed(0)}%`
                    : "—"}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted mb-1">Unrealized P&L %</div>
                <div className={`text-sm font-medium ${pnlColor(account.unrealized_pnl)}`}>
                  {account.balance > 0
                    ? `${((account.unrealized_pnl / account.balance) * 100).toFixed(2)}%`
                    : "0.00%"}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted mb-1">Free Margin %</div>
                <div className="text-sm font-medium">
                  {account.equity > 0
                    ? `${((account.margin_available / account.equity) * 100).toFixed(0)}%`
                    : "—"}
                </div>
              </div>
            </div>
          </div>

          {/* Trade History */}
          <div className="rounded-xl border border-card-border bg-card-bg p-5">
            <h3 className="text-sm font-medium text-muted mb-4">
              Recent Trade History
            </h3>

            {trades.length === 0 ? (
              <div className="flex h-24 items-center justify-center text-sm text-muted">
                No trades recorded yet
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-card-border text-xs text-muted">
                      <th className="pb-2 text-left font-medium">Symbol</th>
                      <th className="pb-2 text-left font-medium">Side</th>
                      <th className="pb-2 text-right font-medium">Size</th>
                      <th className="pb-2 text-right font-medium">Entry</th>
                      <th className="pb-2 text-right font-medium">Exit</th>
                      <th className="pb-2 text-right font-medium">P&L</th>
                      <th className="pb-2 text-left font-medium">Status</th>
                      <th className="pb-2 text-left font-medium">Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((t) => (
                      <tr
                        key={t.id}
                        className="border-b border-card-border/50 last:border-0"
                      >
                        <td className="py-2">{t.symbol}</td>
                        <td className="py-2">
                          <span
                            className={
                              t.direction === "BUY"
                                ? "text-green-400"
                                : "text-red-400"
                            }
                          >
                            {t.direction}
                          </span>
                        </td>
                        <td className="py-2 text-right">{t.lot_size}</td>
                        <td className="py-2 text-right">
                          {t.entry_price ? fmt(t.entry_price, 5) : "—"}
                        </td>
                        <td className="py-2 text-right">
                          {t.exit_price ? fmt(t.exit_price, 5) : "—"}
                        </td>
                        <td className={`py-2 text-right ${pnlColor(t.pnl ?? 0)}`}>
                          {t.pnl != null ? fmt(t.pnl) : "—"}
                        </td>
                        <td className="py-2">
                          <span
                            className={`rounded px-1.5 py-0.5 text-xs ${
                              t.status === "open"
                                ? "bg-blue-500/20 text-blue-400"
                                : "bg-zinc-500/20 text-zinc-400"
                            }`}
                          >
                            {t.status}
                          </span>
                        </td>
                        <td className="py-2 text-xs text-muted">
                          {t.entry_time
                            ? new Date(t.entry_time).toLocaleString()
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}

      <ChatHelpers />
    </div>
  );
}
