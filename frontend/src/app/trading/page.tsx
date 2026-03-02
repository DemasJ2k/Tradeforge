"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { api } from "@/lib/api";
import ChatHelpers from "@/components/ChatHelpers";
import AgentPanel from "@/components/AgentPanel";
import CandlestickChart, { type ChartHandle, type CandleInput } from "@/components/CandlestickChart";
import StrategyOverlayPanel from "@/components/StrategyOverlayPanel";
import { useWebSocket } from "@/hooks/useWebSocket";
import { ChevronDown, Radio, RefreshCw } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { useMarketData } from "@/hooks/useMarketData";
import { useSettings } from "@/hooks/useSettings";
import { useBrokerAccounts } from "@/hooks/useBrokerAccounts";
import type { Time, LogicalRange } from "lightweight-charts";
import type {
  AccountInfo,
  LivePosition,
  LiveOrder,
  PlaceOrderRequest,
  BrokerListResponse,
  TradeHistory,
  DataSource,
} from "@/types";

/* ── tiny helpers ─────────────────────────────────── */

const pnlColor = (v: number) =>
  v > 0 ? "text-green-400" : v < 0 ? "text-red-400" : "text-muted-foreground";

const fmt = (n: number, d = 2) => n.toFixed(d);
const fmtK = (n: number) =>
  Math.abs(n) >= 1000 ? `${(n / 1000).toFixed(1)}k` : fmt(n, 2);

/**
 * Derive appropriate decimal places from bid/ask spread.
 * Works for all asset classes: forex (5dp), crypto (2dp), gold (2dp), indices (2dp).
 *   e.g. spread 0.00020 → 5dp,  spread 2.00 → 2dp,  spread 0.30 → 2dp
 */
function tickDecimals(spread: number): number {
  if (!spread || spread <= 0) return 5; // Default forex precision
  const raw = Math.ceil(-Math.log10(spread)) + 1;
  return Math.max(2, Math.min(raw, 8));
}

/** Format a price value with smart decimal places derived from spread. */
function fmtTick(price: number, spread: number): string {
  if (!Number.isFinite(price)) return "—";
  return price.toFixed(tickDecimals(spread));
}

/** Relative time label: "just now", "2s ago", "5m ago" */
function relativeMs(ms: number): string {
  const diff = Date.now() - ms;
  if (diff < 2000) return "live";
  if (diff < 60_000) return `${Math.floor(diff / 1000)}s ago`;
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  return "stale";
}

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
  const [orderBroker, setOrderBroker] = useState("");
  const { accounts: brokerAccounts, activeBroker } = useBrokerAccounts();

  // polling
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Chart state ──
  const DEFAULT_SYMBOLS = ["XAUUSD", "XAGUSD", "US30", "NAS100", "EURUSD", "BTCUSD"];
  const TIMEFRAMES = ["M1", "M5", "M10", "M15", "M30", "H1", "H4", "D1"];
  const [chartSymbol, setChartSymbol] = useState(() =>
    (typeof window !== "undefined" ? localStorage.getItem("tf_chart_symbol") : null) ?? "XAUUSD"
  );
  const [symbolInput, setSymbolInput] = useState("XAUUSD");
  const [symbolDropdownOpen, setSymbolDropdownOpen] = useState(false);
  const [customSymbols, setCustomSymbols] = useState<string[]>([]);
  const symbolInputRef = useRef<HTMLInputElement>(null);
  const [recentSymbols, setRecentSymbols] = useState<string[]>(() => {
    try {
      if (typeof window === "undefined") return [];
      return JSON.parse(localStorage.getItem("tf_recent_symbols") ?? "[]");
    } catch { return []; }
  });

  const applySymbol = (sym: string) => {
    const upper = sym.trim().toUpperCase();
    if (!upper) return;
    if (!DEFAULT_SYMBOLS.includes(upper) && !customSymbols.includes(upper)) {
      setCustomSymbols((prev) => [...prev, upper]);
    }
    setChartSymbol(upper);
    setSymbolInput(upper);
    setSymbolDropdownOpen(false);
    setRecentSymbols(prev => {
      const next = [upper, ...prev.filter(s => s !== upper)].slice(0, 5);
      if (typeof window !== "undefined") localStorage.setItem("tf_recent_symbols", JSON.stringify(next));
      return next;
    });
  };

  const allSymbols = [...new Set([...DEFAULT_SYMBOLS, ...customSymbols])];
  const filteredSymbols = symbolInput
    ? allSymbols.filter((s) => s.includes(symbolInput.toUpperCase()))
    : allSymbols;
  const [chartTimeframe, setChartTimeframe] = useState(() =>
    (typeof window !== "undefined" ? localStorage.getItem("tf_chart_timeframe") : null) ?? "H1"
  );
  const [chartBroker, setChartBroker] = useState<string>(() =>
    (typeof window !== "undefined" ? localStorage.getItem("tf_chart_broker") : null) ?? "mt5"
  ); // "mt5" | "oanda" | "coinbase" | "tradovate" | "static"
  const chartMode = chartBroker === "static" ? "static" : "live";
  useEffect(() => { if (typeof window !== "undefined") localStorage.setItem("tf_chart_symbol", chartSymbol); }, [chartSymbol]);
  useEffect(() => { if (typeof window !== "undefined") localStorage.setItem("tf_chart_timeframe", chartTimeframe); }, [chartTimeframe]);
  useEffect(() => { if (typeof window !== "undefined") localStorage.setItem("tf_chart_broker", chartBroker); }, [chartBroker]);
  const [chartBars, setChartBars] = useState<CandleInput[]>([]);
  const [chartLoading, setChartLoading] = useState(false);
  const chartRef = useRef<ChartHandle>(null);

  // ── Strategy Overlay datasource state (Phase 5A) ──
  const [overlayDatasourceId, setOverlayDatasourceId] = useState<number | null>(null);
  const [overlayDatasources, setOverlayDatasources] = useState<DataSource[]>([]);
  useEffect(() => {
    api.get<DataSource[] | { items: DataSource[] }>("/api/data/sources")
      .then((data) => {
        const arr = Array.isArray(data) ? data : (data as { items: DataSource[] }).items ?? [];
        setOverlayDatasources(arr);
        if (arr.length > 0) setOverlayDatasourceId(arr[0].id);
      })
      .catch(() => {});
  }, []);

  // ── Indicator state ──
  const [indMA, setIndMA] = useState(false);
  const [indMALen, setIndMALen] = useState(20);
  const [indEMA, setIndEMA] = useState(false);
  const [indEMALen, setIndEMALen] = useState(50);
  const [indMACD, setIndMACD] = useState(false);
  const macdContainerRef = useRef<HTMLDivElement>(null);
  const macdChartRef = useRef<import("lightweight-charts").IChartApi | null>(null);
  const wsStatus = useWebSocket((s) => s.status);
  const { ticks, lastTickMs, bars, currentBar, subscribeBars, subscribeTicks } = useMarketData();
  const { settings } = useSettings();

  // Ref tracking current bar state for direct tick→chart updates
  const liveBarStateRef = useRef<{ time: number; open: number; high: number; low: number; close: number; volume: number } | null>(null);
  // Track whether we've already scrolled to realtime after first live bar
  const scrolledToRealtimeRef = useRef<boolean>(false);
  // Track last tick update time for freshness display (re-render every second)
  const [tickAge, setTickAge] = useState<string>("—");
  const tickAgeTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Ref so the interval callback can read latest lastTickMs without being a dep
  const lastTickMsRef = useRef<Record<string, number>>({});

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
      if (chartBroker === "mt5") {
        // MT5: try MT5-specific endpoint first, fall back to generic
        try {
          const res = await api.get<{ bars: CandleInput[] }>(
            `/api/market/mt5/bars/${sym}?timeframe=${tf}&count=500`
          );
          if (res.bars && res.bars.length > 0) {
            setChartBars(res.bars);
            return;
          }
        } catch { /* fall through */ }
        try {
          const res = await api.get<{ candles: CandleInput[] }>(
            `/api/market/candles/${sym}?timeframe=${tf}&count=500`
          );
          setChartBars(res.candles || []);
        } catch {
          setChartBars([]);
        }
      } else if (chartBroker === "static") {
        // Static / CSV mode
        try {
          const res = await api.get<{ candles: CandleInput[] }>(
            `/api/market/candles/${sym}?timeframe=${tf}&count=500`
          );
          setChartBars(res.candles || []);
        } catch {
          setChartBars([]);
        }
      } else {
        // Oanda / Coinbase / Tradovate — use broker candles endpoint (requires active connection)
        try {
          const res = await api.get<CandleInput[]>(
            `/api/broker/candles/${sym}?timeframe=${tf}&count=500&broker=${chartBroker}`
          );
          setChartBars(Array.isArray(res) ? res : []);
        } catch {
          // Broker not connected — fall back to generic
          try {
            const res = await api.get<{ candles: CandleInput[] }>(
              `/api/market/candles/${sym}?timeframe=${tf}&count=500`
            );
            setChartBars(res.candles || []);
          } catch {
            setChartBars([]);
          }
        }
      }
    } catch {
      setChartBars([]);
    } finally {
      setChartLoading(false);
    }
  }, [chartBroker]);

  // ── Reload bars when symbol/timeframe/broker changes ──
  useEffect(() => {
    // Reset live bar state so stale data from previous symbol doesn't bleed through
    liveBarStateRef.current = null;
    scrolledToRealtimeRef.current = false; // will re-scroll when first live bar arrives
    loadChartBars(chartSymbol, chartTimeframe);
  }, [chartSymbol, chartTimeframe, chartBroker, loadChartBars]);

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
      // Keep liveBarStateRef in sync with bar_update data
      liveBarStateRef.current = { ...liveCurrentBar };
      chartRef.current.updateBar(liveCurrentBar);
      // On first live bar, scroll chart to realtime so the live candle is visible.
      // This handles the case where live data is ahead of the historical data range
      // (e.g. historical ends Friday, live bar is Monday — gap hidden to the right).
      if (!scrolledToRealtimeRef.current) {
        scrolledToRealtimeRef.current = true;
        chartRef.current.getChart()?.timeScale().scrollToRealTime();
      }
    }
  }, [liveCurrentBar, chartMode, chartBars.length]);

  const currentTick = ticks[chartSymbol];

  // ── Direct tick → chart update (fills gaps between bar_update events) ──
  // For MT5: bar_update already fires on every tick, so this adds no latency.
  // For non-MT5 (broker_stream.py REST polling): same path, ~1-2s intervals.
  useEffect(() => {
    if (!currentTick || !chartRef.current || chartMode !== "live") return;
    if (chartBars.length === 0) return;

    const midPrice = (currentTick.bid + currentTick.ask) / 2;
    const last = liveBarStateRef.current;

    if (last && typeof last.time === "number" && last.time > 0) {
      const updated = {
        ...last,
        high: Math.max(last.high, midPrice),
        low: Math.min(last.low, midPrice),
        close: midPrice,
      };
      liveBarStateRef.current = updated;
      chartRef.current.updateBar(updated);
    }
  }, [currentTick, chartMode, chartBars.length]);

  // Keep ref in sync so the interval reads latest values without being a dep
  useEffect(() => {
    lastTickMsRef.current = lastTickMs;
  }, [lastTickMs]);

  // ── Tick age timer (update display every second) ──
  // NOTE: lastTickMs intentionally excluded from deps — reads via ref so the
  // 1-second interval isn't torn down and restarted on every 150ms MT5 tick.
  useEffect(() => {
    if (tickAgeTimerRef.current) clearInterval(tickAgeTimerRef.current);
    if (chartMode !== "live" || wsStatus !== "connected") {
      setTickAge("—");
      return;
    }
    tickAgeTimerRef.current = setInterval(() => {
      const ms = lastTickMsRef.current[chartSymbol];
      setTickAge(ms ? relativeMs(ms) : "waiting…");
    }, 1000);
    return () => {
      if (tickAgeTimerRef.current) clearInterval(tickAgeTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chartMode, wsStatus, chartSymbol]); // lastTickMs read via ref — intentional

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

  // ── MACD chart ──
  useEffect(() => {
    let cancelled = false;
    // Stores the main-chart time-scale unsubscribe fn so we can remove it on cleanup
    let unsubTimeSync: (() => void) | null = null;

    const destroy = () => {
      unsubTimeSync?.();
      unsubTimeSync = null;
      if (macdChartRef.current) {
        try { macdChartRef.current.remove(); } catch { /* already removed */ }
        macdChartRef.current = null;
      }
    };

    if (!indMACD || !macdContainerRef.current || chartBars.length < 26) {
      destroy();
      return () => { cancelled = true; };
    }
    destroy(); // ensure clean slate before creating

    // Dynamic import to avoid SSR issues
    import("lightweight-charts").then(({ createChart, LineSeries, HistogramSeries }) => {
      if (cancelled || !macdContainerRef.current) return;
      const macdChart = createChart(macdContainerRef.current, {
        height: 120,
        layout: { background: { color: "transparent" }, textColor: "#9ca3af" },
        grid: { vertLines: { color: "#1f2937" }, horzLines: { color: "#1f2937" } },
        rightPriceScale: { borderColor: "#374151" },
        timeScale: {
          borderColor: "#374151",
          timeVisible: true,
          secondsVisible: false,
          // Hide the MACD time axis to save space — main chart's axis is enough
          visible: false,
        },
        crosshair: { mode: 1 },
        handleScroll: false,
        handleScale: false,
      });
      macdChartRef.current = macdChart;

      // MACD calculation helpers
      function ema(vals: number[], len: number): (number | null)[] {
        const k = 2 / (len + 1);
        const out: (number | null)[] = [];
        let e: number | null = null;
        for (let i = 0; i < vals.length; i++) {
          if (i < len - 1) { out.push(null); continue; }
          if (e === null) {
            e = vals.slice(0, len).reduce((a, b) => a + b, 0) / len;
          } else {
            e = vals[i] * k + e * (1 - k);
          }
          out.push(e);
        }
        return out;
      }

      const closes = chartBars.map(b => b.close);
      const times = chartBars.map(b => b.time as number);
      const ema12 = ema(closes, 12);
      const ema26 = ema(closes, 26);
      const macdLine = ema12.map((v, i) => (v !== null && ema26[i] !== null ? v - ema26[i]! : null));
      const macdClean = macdLine.filter(v => v !== null) as number[];
      const macdStartIdx = macdLine.findIndex(v => v !== null);
      const signalRaw = ema(macdClean, 9);
      const signalLine = [...Array(macdStartIdx).fill(null), ...signalRaw] as (number | null)[];
      const histogram = macdLine.map((v, i) => (v !== null && signalLine[i] !== null ? v - signalLine[i]! : null));

      const toSeries = (vals: (number | null)[]) =>
        vals.map((v, i) => v !== null ? { time: times[i] as Time, value: v } : null)
            .filter((d): d is { time: Time; value: number } => d !== null);

      const histSeries = macdChart.addSeries(HistogramSeries, { color: "#22c55e", priceLineVisible: false });
      histSeries.setData(toSeries(histogram).map(p => ({
        time: p.time,
        value: p.value,
        color: p.value >= 0 ? "#22c55e66" : "#ef444466",
      })));

      const macdSeries = macdChart.addSeries(LineSeries, { color: "#3b82f6", lineWidth: 1, priceLineVisible: false });
      macdSeries.setData(toSeries(macdLine));

      const signalSeries = macdChart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 1, priceLineVisible: false });
      signalSeries.setData(toSeries(signalLine));

      // ── Sync time scale with main chart ──────────────────────────────────
      // The MACD chart has scroll/scale disabled — all navigation is driven
      // by the main chart. We subscribe to the main chart's visible-range
      // changes and mirror them onto the MACD chart.
      const mainChart = chartRef.current?.getChart();
      if (mainChart) {
        // Apply the main chart's current visible range immediately
        try {
          const range: LogicalRange | null = mainChart.timeScale().getVisibleLogicalRange();
          if (range) macdChart.timeScale().setVisibleLogicalRange(range);
        } catch { /* ignore */ }

        // Keep MACD in sync whenever the user scrolls/zooms the main chart
        const syncHandler = (range: LogicalRange | null) => {
          if (!range) return;
          try { macdChart.timeScale().setVisibleLogicalRange(range); } catch { /* ignore */ }
        };
        mainChart.timeScale().subscribeVisibleLogicalRangeChange(syncHandler);
        unsubTimeSync = () => {
          try { mainChart.timeScale().unsubscribeVisibleLogicalRangeChange(syncHandler); } catch { /* ignore */ }
        };
      } else {
        // Fallback: show all data if main chart isn't ready
        macdChart.timeScale().fitContent();
      }
    });

    return () => {
      cancelled = true;
      destroy();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [indMACD, chartBars]);

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
      const brokerParam = brokerName ? `?broker=${brokerName}` : "";
      await api.post(`/api/broker/positions/close${brokerParam}`, { position_id: posId });
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

      await api.post("/api/broker/orders", { ...req, broker: orderBroker });
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
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <h2 className="text-lg sm:text-xl font-semibold">Live Trading</h2>
        <div className="flex items-center gap-2 sm:gap-3">
          {connected && (
            <>
              <span className="flex items-center gap-1.5 text-sm text-green-400">
                <span className="inline-block h-2 w-2 rounded-full bg-green-400 animate-pulse" />
                {brokerName}
              </span>
              <Button
                onClick={() => { setShowOrder(true); setOrderBroker(activeBroker ?? brokerAccounts.find(b => b.connected)?.broker ?? ""); }}
              >
                New Order
              </Button>
              <Button
                variant="outline"
                onClick={handleDisconnect}
                className="border-red-500/40 text-red-400 hover:bg-red-500/10"
              >
                Disconnect
              </Button>
            </>
          )}
          {!connected && (
            <Button
              onClick={() => setShowConnect(true)}
            >
              Connect Broker
            </Button>
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
        <div className="flex flex-wrap items-center justify-between border-b border-card-border px-2 sm:px-4 py-2 gap-2">
          <div className="flex items-center gap-2 sm:gap-3 flex-wrap">
            {/* Symbol combobox — type any symbol or pick from list */}
            <div className="relative">
              <div className="flex items-center rounded-lg border border-card-border bg-background focus-within:border-accent">
                <input
                  ref={symbolInputRef}
                  value={symbolInput}
                  onChange={(e) => {
                    setSymbolInput(e.target.value.toUpperCase());
                    setSymbolDropdownOpen(true);
                  }}
                  onFocus={() => setSymbolDropdownOpen(true)}
                  onBlur={() => setTimeout(() => setSymbolDropdownOpen(false), 150)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") applySymbol(symbolInput);
                    if (e.key === "Escape") { setSymbolDropdownOpen(false); symbolInputRef.current?.blur(); }
                  }}
                  className="w-24 bg-transparent px-2 py-1.5 text-sm font-medium uppercase outline-none"
                  placeholder="Symbol"
                />
                <button
                  onMouseDown={(e) => { e.preventDefault(); setSymbolDropdownOpen((o) => !o); symbolInputRef.current?.focus(); }}
                  className="pr-2 text-muted-foreground hover:text-foreground"
                >
                  <ChevronDown className="h-3 w-3" />
                </button>
              </div>
              {symbolDropdownOpen && (
                <div className="absolute left-0 top-full z-50 mt-1 min-w-[140px] rounded-lg border border-card-border bg-card-bg shadow-xl">
                  {recentSymbols.length > 0 && symbolInput === "" && (
                    <>
                      <div className="px-3 py-1 text-xs text-muted-foreground font-medium border-b border-card-border">Recent</div>
                      {recentSymbols.map(s => (
                        <button key={`recent-${s}`} onMouseDown={() => applySymbol(s)}
                          className="w-full text-left px-3 py-1.5 text-sm hover:bg-card-border transition-colors text-accent">
                          🕐 {s}
                        </button>
                      ))}
                      <div className="px-3 py-1 text-xs text-muted-foreground font-medium border-b border-card-border">All Symbols</div>
                    </>
                  )}
                  {filteredSymbols.map((s) => (
                    <button
                      key={s}
                      onMouseDown={() => applySymbol(s)}
                      className={`block w-full px-3 py-1.5 text-left text-sm hover:bg-sidebar-hover transition-colors ${s === chartSymbol ? "text-accent font-medium" : "text-foreground"}`}
                    >
                      {s}
                    </button>
                  ))}
                  {symbolInput && !filteredSymbols.includes(symbolInput.toUpperCase()) && (
                    <button
                      onMouseDown={() => applySymbol(symbolInput)}
                      className="block w-full border-t border-card-border px-3 py-1.5 text-left text-sm text-accent hover:bg-sidebar-hover transition-colors"
                    >
                      + Use &quot;{symbolInput.toUpperCase()}&quot;
                    </button>
                  )}
                </div>
              )}
            </div>

            {/* Timeframe selector */}
            <div className="flex gap-1">
              {TIMEFRAMES.map((tf) => (
                <button
                  key={tf}
                  onClick={() => setChartTimeframe(tf)}
                  className={`rounded px-2 py-1 text-xs font-medium transition-colors ${
                    chartTimeframe === tf
                      ? "bg-accent text-black"
                      : "text-muted-foreground hover:text-foreground hover:bg-card-border/50"
                  }`}
                >
                  {tf}
                </button>
              ))}
            </div>

            {/* Data source dropdown */}
            <select
              value={chartBroker}
              onChange={e => setChartBroker(e.target.value)}
              className="ml-2 rounded px-2 py-1 text-xs font-medium bg-input-bg border border-card-border text-foreground/90 focus:outline-none focus:border-blue-500"
            >
              <option value="mt5">MT5 Live</option>
              <option value="oanda">Oanda</option>
              <option value="coinbase">Coinbase</option>
              <option value="tradovate">Tradovate</option>
              <option value="static">Chart Data</option>
            </select>
          </div>

          <div className="flex items-center gap-2 sm:gap-3 flex-wrap">
            {/* Live tick display — smart decimal formatting based on spread */}
            {currentTick && chartMode === "live" && (
              <div className="flex items-center gap-2 text-xs font-mono">
                {/* Symbol badge */}
                <span className="text-muted-foreground font-sans mr-0.5">{currentTick.symbol}</span>

                {/* Bid */}
                <span className="text-muted-foreground font-sans">B</span>
                <span className="text-green-400">{fmtTick(currentTick.bid, currentTick.spread)}</span>

                {/* Ask */}
                <span className="text-muted-foreground font-sans">A</span>
                <span className="text-red-400">{fmtTick(currentTick.ask, currentTick.spread)}</span>

                {/* Spread */}
                <span className="text-zinc-500 font-sans">Sprd</span>
                <span className="text-zinc-400">{fmtTick(currentTick.spread, currentTick.spread)}</span>

                {/* Freshness */}
                <span className={`font-sans ml-0.5 px-1.5 py-0.5 rounded text-[10px] ${
                  tickAge === "live"
                    ? "bg-green-500/15 text-green-400"
                    : tickAge === "waiting…"
                      ? "bg-zinc-700/50 text-zinc-400"
                      : "bg-amber-500/15 text-amber-400"
                }`}>
                  {tickAge}
                </span>
              </div>
            )}

            {/* No tick yet — show waiting state */}
            {!currentTick && chartMode === "live" && wsStatus === "connected" && (
              <div className="flex items-center gap-1.5 text-xs text-zinc-500">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-zinc-500 animate-pulse" />
                Waiting for ticks…
              </div>
            )}

            {/* Connection status dot */}
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
                : chartBroker === "static" ? "Chart Data" : "Static"}
            </span>
          </div>
        </div>

        {/* Indicator toggle bar */}
        <div className="flex items-center gap-2 px-3 py-1.5 border-b border-card-border bg-background/50">
          <span className="text-xs text-muted-foreground mr-1">Indicators:</span>
          {/* MA toggle */}
          <button
            onClick={() => setIndMA(v => !v)}
            className={`flex items-center gap-1 px-2 py-0.5 text-xs rounded border transition-colors ${
              indMA ? "bg-amber-500/15 border-amber-500/40 text-amber-400" : "border-card-border text-muted-foreground hover:text-foreground"
            }`}
          >
            MA
          </button>
          {indMA && (
            <input
              type="number" value={indMALen} min={2} max={500}
              onChange={e => setIndMALen(Math.max(2, Number(e.target.value)))}
              className="w-14 rounded border border-amber-500/40 bg-background px-1.5 py-0.5 text-xs text-amber-400 focus:outline-none"
              title="MA period"
            />
          )}
          {/* EMA toggle */}
          <button
            onClick={() => setIndEMA(v => !v)}
            className={`flex items-center gap-1 px-2 py-0.5 text-xs rounded border transition-colors ${
              indEMA ? "bg-purple-500/15 border-purple-500/40 text-purple-400" : "border-card-border text-muted-foreground hover:text-foreground"
            }`}
          >
            EMA
          </button>
          {indEMA && (
            <input
              type="number" value={indEMALen} min={2} max={500}
              onChange={e => setIndEMALen(Math.max(2, Number(e.target.value)))}
              className="w-14 rounded border border-purple-500/40 bg-background px-1.5 py-0.5 text-xs text-purple-400 focus:outline-none"
              title="EMA period"
            />
          )}
          {/* MACD toggle */}
          <button
            onClick={() => setIndMACD(v => !v)}
            className={`flex items-center gap-1 px-2 py-0.5 text-xs rounded border transition-colors ${
              indMACD ? "bg-blue-500/15 border-blue-500/40 text-fa-accent" : "border-card-border text-muted-foreground hover:text-foreground"
            }`}
          >
            MACD
          </button>
        </div>

        {/* Chart */}
        <div className="relative">
        {chartLoading ? (
          <div className="flex h-[400px] items-center justify-center text-sm text-muted-foreground">
            Loading chart data...
          </div>
        ) : chartBars.length === 0 ? (
          <div className="flex h-[400px] flex-col items-center justify-center text-sm text-muted-foreground gap-2">
            <span>
              {chartBroker === "mt5" && !connected
                ? "Connect MT5 broker to view live chart data"
                : chartBroker !== "static" && chartBroker !== "mt5" && !connected
                  ? `Connect ${chartBroker.charAt(0).toUpperCase() + chartBroker.slice(1)} in Settings → Brokers, then use Connect Broker`
                  : chartMode === "live" && wsStatus !== "connected"
                    ? "WebSocket connecting... waiting for live data"
                    : "No chart data available — try switching to a different symbol or data source"}
            </span>
            {chartBroker === "mt5" && !connected && (
              <Button variant="outline" size="sm"
                onClick={() => setShowConnect(true)}
                className="border-accent/30 bg-accent/20 text-accent hover:bg-accent/30"
              >
                Connect Broker
              </Button>
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
            indicators={{ ma: indMA, maLen: indMALen, ema: indEMA, emaLen: indEMALen }}
          />
        )}
        {/* Strategy Overlay Panel (Phase 5A) */}
        <StrategyOverlayPanel
          chart={chartRef.current?.getChart() ?? null}
          datasourceId={overlayDatasourceId}
        />
        </div>

        {/* MACD pane */}
        {indMACD && chartBars.length >= 26 && (
          <div className="border-t border-card-border">
            <div className="px-3 py-1 text-xs text-muted-foreground flex items-center gap-2">
              <span className="text-fa-accent font-medium">MACD</span>
              <span className="text-zinc-600">(12, 26, 9)</span>
              <span className="inline-block h-2 w-2 rounded-sm bg-blue-500/60" /> MACD
              <span className="inline-block h-2 w-2 rounded-sm bg-amber-500/60" /> Signal
              <span className="inline-block h-2 w-2 rounded-sm bg-green-500/40" /> Hist
            </div>
            <div ref={macdContainerRef} className="w-full" style={{ height: 120 }} />
          </div>
        )}
      </div>

      {/* ── Connect Modal ──────────────────────── */}
      <Dialog open={showConnect} onOpenChange={setShowConnect}>
        <DialogContent className="max-w-md max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Connect Broker</DialogTitle>
            <DialogDescription>Enter your broker credentials to connect.</DialogDescription>
          </DialogHeader>

            <div>
              <Label className="text-xs text-muted-foreground mb-1">Broker</Label>
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
                  <Label className="text-xs text-muted-foreground mb-1">API Key (Token)</Label>
                  <input type="password" value={cApiKey} onChange={(e) => setCApiKey(e.target.value)}
                    placeholder="Your Oanda API token" className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground mb-1">Account ID</Label>
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
                  <Label className="text-xs text-muted-foreground mb-1">API Key</Label>
                  <input type="password" value={cApiKey} onChange={(e) => setCApiKey(e.target.value)}
                    placeholder="Coinbase API key" className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground mb-1">API Secret</Label>
                  <input type="password" value={cExtra.api_secret || ""} onChange={(e) => setCExtra({ ...cExtra, api_secret: e.target.value })}
                    placeholder="Coinbase API secret" className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
                </div>
                <p className="text-xs text-muted-foreground">Create API keys in Coinbase → Settings → API</p>
              </>
            )}

            {/* ── MT5 fields ── */}
            {cBroker === "mt5" && (
              <>
                <div>
                  <Label className="text-xs text-muted-foreground mb-1">Server</Label>
                  <input value={cExtra.server || ""} onChange={(e) => setCExtra({ ...cExtra, server: e.target.value })}
                    placeholder="e.g. MetaQuotes-Demo" className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground mb-1">Login (Account Number)</Label>
                  <input value={cExtra.login || ""} onChange={(e) => setCExtra({ ...cExtra, login: e.target.value })}
                    placeholder="e.g. 12345678" className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground mb-1">Password</Label>
                  <input type="password" value={cApiKey} onChange={(e) => setCApiKey(e.target.value)}
                    placeholder="MT5 account password" className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
                </div>
                <p className="text-xs text-muted-foreground">MetaTrader 5 terminal must be installed and running on this machine.</p>
              </>
            )}

            {/* ── Tradovate fields ── */}
            {cBroker === "tradovate" && (
              <>
                <div>
                  <Label className="text-xs text-muted-foreground mb-1">Username</Label>
                  <input value={cExtra.username || ""} onChange={(e) => setCExtra({ ...cExtra, username: e.target.value })}
                    placeholder="Tradovate username" className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground mb-1">Password</Label>
                  <input type="password" value={cApiKey} onChange={(e) => setCApiKey(e.target.value)}
                    placeholder="Tradovate password" className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label className="text-xs text-muted-foreground mb-1">App ID</Label>
                    <input value={cExtra.app_id || ""} onChange={(e) => setCExtra({ ...cExtra, app_id: e.target.value })}
                      placeholder="App ID" className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
                  </div>
                  <div>
                    <Label className="text-xs text-muted-foreground mb-1">Client ID</Label>
                    <input value={cExtra.cid || ""} onChange={(e) => setCExtra({ ...cExtra, cid: e.target.value })}
                      placeholder="Client ID" className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
                  </div>
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground mb-1">Client Secret</Label>
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
              <Button variant="outline"
                onClick={() => setShowConnect(false)}
              >
                Cancel
              </Button>
              <Button
                onClick={handleConnect}
                disabled={connecting || !cApiKey}
              >
                {connecting ? "Connecting..." : "Connect"}
              </Button>
            </div>
        </DialogContent>
      </Dialog>

      {/* ── Order Modal ────────────────────────── */}
      <Dialog open={showOrder} onOpenChange={setShowOrder}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Place Order</DialogTitle>
            <DialogDescription>Configure and submit a new order.</DialogDescription>
          </DialogHeader>

            <div>
              <Label className="text-xs text-muted-foreground mb-1">Broker</Label>
              <select value={orderBroker} onChange={e => setOrderBroker(e.target.value)}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm outline-none focus:border-accent">
                {brokerAccounts.filter(b => b.connected).map(b => (
                  <option key={b.broker} value={b.broker}>{b.broker.charAt(0).toUpperCase() + b.broker.slice(1)} ({b.currency})</option>
                ))}
              </select>
            </div>

            <div>
              <Label className="text-xs text-muted-foreground mb-1">Symbol</Label>
              <input
                value={oSymbol}
                onChange={(e) => setOSymbol(e.target.value)}
                placeholder="EUR_USD"
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-xs text-muted-foreground mb-1">Side</Label>
                <div className="flex gap-2">
                  <button
                    onClick={() => setOSide("BUY")}
                    className={`flex-1 rounded-lg py-2 text-sm font-medium transition-colors ${
                      oSide === "BUY"
                        ? "bg-green-500/20 text-green-400 border border-green-500/40"
                        : "border border-card-border text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    BUY
                  </button>
                  <button
                    onClick={() => setOSide("SELL")}
                    className={`flex-1 rounded-lg py-2 text-sm font-medium transition-colors ${
                      oSide === "SELL"
                        ? "bg-red-500/20 text-red-400 border border-red-500/40"
                        : "border border-card-border text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    SELL
                  </button>
                </div>
              </div>
              <div>
                <Label className="text-xs text-muted-foreground mb-1">Size (units)</Label>
                <input
                  type="number"
                  value={oSize}
                  onChange={(e) => setOSize(e.target.value)}
                  className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
                />
              </div>
            </div>

            <div>
              <Label className="text-xs text-muted-foreground mb-1">Order Type</Label>
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
                <Label className="text-xs text-muted-foreground mb-1">Price</Label>
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
                <Label className="text-xs text-muted-foreground mb-1">Stop Loss</Label>
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
                <Label className="text-xs text-muted-foreground mb-1">Take Profit</Label>
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
              <Button variant="outline"
                onClick={() => setShowOrder(false)}
              >
                Cancel
              </Button>
              <Button
                onClick={placeOrder}
                disabled={placing || !oSymbol || !oSize}
                className={`${
                  oSide === "BUY"
                    ? "bg-green-600 hover:bg-green-700"
                    : "bg-red-600 hover:bg-red-700"
                }`}
              >
                {placing ? "Placing..." : `${oSide} ${oSymbol}`}
              </Button>
            </div>
        </DialogContent>
      </Dialog>

      {/* ── Algo Agents Panel ────────────────── */}
      <AgentPanel />

      {/* ── Not Connected State ────────────────── */}
      {!connected && (
        <Card className="border-card-border bg-card-bg p-16 text-center">
          <CardContent className="flex flex-col items-center justify-center p-0">
          <Radio className="w-10 h-10 text-muted-foreground mb-4" />
          <h3 className="text-lg font-medium mb-2">No Broker Connected</h3>
          <p className="text-sm text-muted-foreground mb-6 max-w-md">
            Connect to a broker to see live positions, place orders, and monitor your
            account in real time.
          </p>
          <Button
            onClick={() => setShowConnect(true)}
          >
            Connect Broker
          </Button>
          </CardContent>
        </Card>
      )}

      {/* ── Connected Dashboard ────────────────── */}
      {connected && account && (
        <>
          {/* Account Summary Cards */}
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <Card className="border-card-border bg-card-bg">
              <CardContent className="p-4">
              <div className="text-xs text-muted-foreground mb-1">Balance</div>
              <div className="text-lg font-semibold">
                {account.currency} {fmtK(account.balance)}
              </div>
              </CardContent>
            </Card>
            <Card className="border-card-border bg-card-bg">
              <CardContent className="p-4">
              <div className="text-xs text-muted-foreground mb-1">Equity</div>
              <div className="text-lg font-semibold">
                {account.currency} {fmtK(account.equity)}
              </div>
              </CardContent>
            </Card>
            <Card className="border-card-border bg-card-bg">
              <CardContent className="p-4">
              <div className="text-xs text-muted-foreground mb-1">Unrealized P&L</div>
              <div className={`text-lg font-semibold ${pnlColor(account.unrealized_pnl)}`}>
                {account.unrealized_pnl >= 0 ? "+" : ""}
                {fmt(account.unrealized_pnl)}
              </div>
              </CardContent>
            </Card>
            <Card className="border-card-border bg-card-bg">
              <CardContent className="p-4">
              <div className="text-xs text-muted-foreground mb-1">Margin Used / Free</div>
              <div className="text-lg font-semibold">
                {fmtK(account.margin_used)}{" "}
                <span className="text-xs text-muted-foreground font-normal">
                  / {fmtK(account.margin_available)}
                </span>
              </div>
              </CardContent>
            </Card>
          </div>

          {/* Positions & Orders */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {/* Open Positions */}
            <Card className="border-card-border bg-card-bg">
              <CardContent className="p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-medium text-muted-foreground">
                  Open Positions ({positions.length})
                </h3>
                <Button variant="ghost" size="sm" onClick={refreshData}
                  className="text-xs text-muted-foreground hover:text-accent h-auto py-1">
                  <RefreshCw className="w-3 h-3 mr-1" />Refresh
                </Button>
              </div>

              {positions.length === 0 ? (
                <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
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
                        <Badge variant="secondary"
                          className={`${p.side === "LONG" ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"}`}
                        >
                          {p.side}
                        </Badge>
                        <div>
                          <div className="text-sm font-medium">{p.symbol}</div>
                          <div className="text-xs text-muted-foreground">
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
                          <div className="text-xs text-muted-foreground">
                            {fmt(p.current_price, 5)}
                          </div>
                        </div>
                        <Button variant="outline" size="sm"
                          onClick={() => closePosition(p.position_id)}
                          className="border-red-500/40 text-red-400 hover:bg-red-500/10 h-auto py-1 px-2"
                          title="Close position"
                        >
                          Close
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              </CardContent>
            </Card>

            {/* Pending Orders */}
            <Card className="border-card-border bg-card-bg">
              <CardContent className="p-5">
              <h3 className="text-sm font-medium text-muted-foreground mb-4">
                Pending Orders ({orders.length})
              </h3>

              {orders.length === 0 ? (
                <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
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
                        <Badge variant="secondary"
                          className={`${o.side === "BUY" ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"}`}
                        >
                          {o.side}
                        </Badge>
                        <div>
                          <div className="text-sm font-medium">{o.symbol}</div>
                          <div className="text-xs text-muted-foreground">
                            {o.order_type} — {o.size} units
                            {o.price ? ` @ ${fmt(o.price, 5)}` : ""}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <div className="text-right text-xs text-muted-foreground">
                          {o.stop_loss && <div>SL: {fmt(o.stop_loss, 5)}</div>}
                          {o.take_profit && <div>TP: {fmt(o.take_profit, 5)}</div>}
                        </div>
                        <Button variant="outline" size="sm"
                          onClick={() => cancelOrder(o.order_id)}
                          className="border-red-500/40 text-red-400 hover:bg-red-500/10 h-auto py-1 px-2"
                        >
                          Cancel
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              </CardContent>
            </Card>
          </div>

          {/* Risk Monitor */}
          <Card className="border-card-border bg-card-bg">
            <CardContent className="p-5">
            <h3 className="text-sm font-medium text-muted-foreground mb-4">Risk Monitor</h3>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
              <div>
                <div className="text-xs text-muted-foreground mb-1">Total Exposure</div>
                <div className="text-sm font-medium">
                  {positions.reduce((s, p) => s + p.size * p.current_price, 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground mb-1">Positions</div>
                <div className="text-sm font-medium">{positions.length}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground mb-1">Margin Level</div>
                <div className="text-sm font-medium">
                  {account.margin_used > 0
                    ? `${((account.equity / account.margin_used) * 100).toFixed(0)}%`
                    : "—"}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground mb-1">Unrealized P&L %</div>
                <div className={`text-sm font-medium ${pnlColor(account.unrealized_pnl)}`}>
                  {account.balance > 0
                    ? `${((account.unrealized_pnl / account.balance) * 100).toFixed(2)}%`
                    : "0.00%"}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground mb-1">Free Margin %</div>
                <div className="text-sm font-medium">
                  {account.equity > 0
                    ? `${((account.margin_available / account.equity) * 100).toFixed(0)}%`
                    : "—"}
                </div>
              </div>
            </div>
            </CardContent>
          </Card>

          {/* Trade History */}
          <Card className="border-card-border bg-card-bg">
            <CardContent className="p-5">
            <h3 className="text-sm font-medium text-muted-foreground mb-4">
              Recent Trade History
            </h3>

            {trades.length === 0 ? (
              <div className="flex h-24 items-center justify-center text-sm text-muted-foreground">
                No trades recorded yet
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-card-border text-xs text-muted-foreground">
                      <th className="pb-2 text-left font-medium">Symbol</th>
                      <th className="pb-2 text-left font-medium">Broker</th>
                      <th className="pb-2 text-left font-medium">Side</th>
                      <th className="pb-2 text-right font-medium">Size</th>
                      <th className="pb-2 text-right font-medium">SL</th>
                      <th className="pb-2 text-right font-medium">TP</th>
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
                        <td className="py-2 text-xs text-muted-foreground">{(t as any).broker ?? "—"}</td>
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
                        <td className="py-2 text-right text-xs text-muted-foreground">{(t as any).stop_loss ?? "—"}</td>
                        <td className="py-2 text-right text-xs text-muted-foreground">{(t as any).take_profit ?? "—"}</td>
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
                          <Badge variant="secondary"
                            className={`${
                              t.status === "open"
                                ? "bg-blue-500/20 text-fa-accent"
                                : "bg-zinc-500/20 text-zinc-400"
                            }`}
                          >
                            {t.status}
                          </Badge>
                        </td>
                        <td className="py-2 text-xs text-muted-foreground">
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
            </CardContent>
          </Card>
        </>
      )}

      <ChatHelpers />
    </div>
  );
}
