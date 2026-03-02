"use client";

/**
 * Phase 5B — BacktestTradeChart
 *
 * Shows backtest results on a Lightweight Charts candlestick chart with:
 *  - Entry markers (green ▲ for long, red ▼ for short)
 *  - Exit markers (with P&L label)
 *  - Drawdown shading on equity pane
 *  - Click-to-scroll from trade list
 */

import { useEffect, useRef, useCallback, forwardRef, useImperativeHandle } from "react";
import type { IChartApi, Time, SeriesMarker } from "lightweight-charts";
import type { TradeResult } from "@/types";

/* Helper type for the markers plugin returned by createSeriesMarkers */
interface MarkersPlugin { setMarkers(m: SeriesMarker<Time>[]): void; detach(): void; }

export interface BacktestChartHandle {
  scrollToTime: (unixSeconds: number) => void;
}

interface Props {
  /** OHLCV bars (unix-second timestamps) */
  bars: { time: number; open: number; high: number; low: number; close: number; volume?: number }[];
  /** Trade results from backtest */
  trades: TradeResult[];
  /** Equity curve values (one per bar) */
  equityCurve: number[];
  /** Indicator overlay data: key → time-value pairs */
  indicatorOverlays?: Record<string, { time: number; value: number | null }[]>;
  height?: number;
}

const OVERLAY_COLORS = [
  "#06b6d4", "#f59e0b", "#a78bfa", "#f472b6",
  "#34d399", "#fb923c", "#60a5fa", "#e879f9",
];

const BacktestTradeChart = forwardRef<BacktestChartHandle, Props>(function BacktestTradeChart(
  { bars, trades, equityCurve, indicatorOverlays, height = 400 },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useImperativeHandle(ref, () => ({
    scrollToTime: (ts: number) => {
      chartRef.current?.timeScale().scrollToPosition(
        bars.findIndex((b) => b.time >= ts) - bars.length + 20,
        false,
      );
    },
  }));

  useEffect(() => {
    if (!containerRef.current || bars.length === 0) return;

    let destroyed = false;

    import("lightweight-charts").then(
      ({ createChart, CandlestickSeries, HistogramSeries, LineSeries, ColorType, CrosshairMode, createSeriesMarkers }) => {
        if (destroyed || !containerRef.current) return;

        const chart = createChart(containerRef.current, {
          layout: {
            background: { type: ColorType.Solid, color: "#18181b" },
            textColor: "#71717a",
            fontSize: 12,
          },
          grid: {
            vertLines: { color: "#27272a" },
            horzLines: { color: "#27272a" },
          },
          crosshair: { mode: CrosshairMode.Normal },
          rightPriceScale: { borderColor: "#27272a" },
          timeScale: { borderColor: "#27272a", timeVisible: true, secondsVisible: false },
          width: containerRef.current.clientWidth,
          height,
        });
        chartRef.current = chart;

        // --- Candle series ---
        const candleSeries = chart.addSeries(CandlestickSeries, {
          upColor: "#22c55e",
          downColor: "#ef4444",
          borderUpColor: "#22c55e",
          borderDownColor: "#ef4444",
          wickUpColor: "#22c55e",
          wickDownColor: "#ef4444",
        });

        candleSeries.setData(
          bars.map((b) => ({
            time: b.time as Time,
            open: b.open,
            high: b.high,
            low: b.low,
            close: b.close,
          })),
        );

        // --- Volume pane ---
        const volSeries = chart.addSeries(HistogramSeries, {
          priceFormat: { type: "volume" },
          priceScaleId: "volume",
        });
        chart.priceScale("volume").applyOptions({
          scaleMargins: { top: 0.85, bottom: 0 },
        });
        volSeries.setData(
          bars.map((b) => ({
            time: b.time as Time,
            value: b.volume ?? 0,
            color: b.close >= b.open ? "#22c55e4D" : "#ef44444D",
          })),
        );

        // --- Equity curve overlay (on separate price scale) ---
        if (equityCurve.length > 0 && equityCurve.length <= bars.length) {
          const eqSeries = chart.addSeries(LineSeries, {
            color: "#06b6d4",
            lineWidth: 2 as 1 | 2 | 3 | 4,
            priceLineVisible: false,
            lastValueVisible: true,
            crosshairMarkerVisible: false,
            priceScaleId: "equity",
          });
          chart.priceScale("equity").applyOptions({
            scaleMargins: { top: 0.0, bottom: 0.55 },
          });

          // Map equity values to bar timestamps
          // Equity curve might be per-bar or per-trade; use min(length)
          const eqLen = Math.min(equityCurve.length, bars.length);
          const eqData = [];
          for (let i = 0; i < eqLen; i++) {
            eqData.push({ time: bars[i].time as Time, value: equityCurve[i] });
          }
          eqSeries.setData(eqData);
        }

        // --- Trade markers ---
        const markers: SeriesMarker<Time>[] = [];

        for (const t of trades) {
          if (t.entry_time && t.entry_time > 0) {
            const isLong = t.direction === "long";
            markers.push({
              time: t.entry_time as Time,
              position: "belowBar",
              color: isLong ? "#22c55e" : "#ef4444",
              shape: "arrowUp",
              text: isLong ? "▲ L" : "▼ S",
            } as SeriesMarker<Time>);
          }
          if (t.exit_time && t.exit_time > 0) {
            const pnlLabel = t.pnl >= 0 ? `+${t.pnl.toFixed(0)}` : t.pnl.toFixed(0);
            markers.push({
              time: t.exit_time as Time,
              position: "aboveBar",
              color: t.pnl >= 0 ? "#22c55e" : "#ef4444",
              shape: "arrowDown",
              text: `✕ ${pnlLabel}`,
            } as SeriesMarker<Time>);
          }
        }

        markers.sort((a, b) => (a.time as number) - (b.time as number));
        (createSeriesMarkers as any)(candleSeries, markers);

        // --- Indicator overlays ---
        if (indicatorOverlays) {
          let cIdx = 0;
          for (const [key, data] of Object.entries(indicatorOverlays)) {
            const color = OVERLAY_COLORS[cIdx % OVERLAY_COLORS.length];
            cIdx++;

            const series = chart.addSeries(LineSeries, {
              color,
              lineWidth: 1 as 1 | 2 | 3 | 4,
              priceLineVisible: false,
              lastValueVisible: false,
              crosshairMarkerVisible: false,
            });

            series.setData(
              data
                .filter((d) => d.value !== null && Number.isFinite(d.value!))
                .map((d) => ({ time: d.time as Time, value: d.value! })),
            );
          }
        }

        // Resize observer
        const obs = new ResizeObserver((entries) => {
          for (const e of entries) chart.applyOptions({ width: e.contentRect.width });
        });
        obs.observe(containerRef.current!);

        // Show range with trades
        if (bars.length > 100) {
          const from = bars[Math.max(0, bars.length - 200)].time as Time;
          const to = bars[bars.length - 1].time as Time;
          chart.timeScale().setVisibleRange({ from, to });
        }

        return () => {
          obs.disconnect();
          chart.remove();
        };
      },
    );

    return () => {
      destroyed = true;
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [bars, trades, equityCurve, indicatorOverlays, height]);

  return (
    <div
      ref={containerRef}
      className="w-full rounded-lg overflow-hidden"
      style={{ height }}
    />
  );
});

export default BacktestTradeChart;
