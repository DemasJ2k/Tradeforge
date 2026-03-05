"use client";

import { useEffect, useRef, useImperativeHandle, forwardRef, useCallback, useMemo } from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type HistogramData,
  type LineData,
  type Time,
  ColorType,
  CrosshairMode,
} from "lightweight-charts";

export interface CandleInput {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface ChartHandle {
  /** Update or append a single bar (for live streaming). */
  updateBar: (bar: CandleInput) => void;
  /** Get the underlying chart API. */
  getChart: () => IChartApi | null;
  /** Get the candle series for markers / overlays. */
  getCandleSeries: () => ISeriesApi<"Candlestick"> | null;
}

/** A single line to render on the main (price) chart. */
export interface OverlayLine {
  key: string;
  color: string;
  lineWidth?: number;
  data: { time: number; value: number }[];
}

// Keep legacy IndicatorConfig for backward compat (used nowhere now but exported)
export interface IndicatorConfig {
  ma?: boolean;
  maLen?: number;
  ema?: boolean;
  emaLen?: number;
}

interface Props {
  data: CandleInput[];
  height?: number;
  upColor?: string;
  downColor?: string;
  volumeColor?: string;
  showGrid?: boolean;
  showCrosshair?: boolean;
  /** Generic overlay lines rendered on the price chart */
  overlayLines?: OverlayLine[];
  /** @deprecated Use overlayLines instead */
  indicators?: IndicatorConfig;
}

// ─── Component ───────────────────────────────────────────────────────────────

const CandlestickChart = forwardRef<ChartHandle, Props>(function CandlestickChart(
  {
    data,
    height = 500,
    upColor = "#22c55e",
    downColor = "#ef4444",
    volumeColor,
    showGrid = true,
    showCrosshair = true,
    overlayLines,
  },
  ref
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  /** Dynamic overlay line series — keyed by overlay key string */
  const overlaySeriesRef = useRef<Map<string, ISeriesApi<"Line">>>(new Map());
  const colors = useMemo(() => ({ upColor, downColor, volumeColor }), [upColor, downColor, volumeColor]);
  const colorsRef = useRef(colors);

  // Keep colors ref in sync (inside an effect to avoid ref access during render)
  useEffect(() => {
    colorsRef.current = colors;
  }, [colors]);

  // Track whether initial data has been set (to avoid .update() on empty series)
  const dataLoadedRef = useRef(false);
  const lastSeriesTimeRef = useRef<number>(0);

  // Expose imperative handle for live updates
  const updateBar = useCallback((bar: CandleInput) => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current) return;
    if (!dataLoadedRef.current) return;

    const t = typeof bar.time === "number" ? bar.time : Number(bar.time);
    if (!Number.isFinite(t) || t <= 0) return;
    if (t < lastSeriesTimeRef.current) return;

    const candle: CandlestickData<Time> = {
      time: t as Time,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    };

    const { upColor: up, downColor: down, volumeColor: vc } = colorsRef.current;
    const volColor = bar.close >= bar.open
      ? (vc ? vc + "4D" : up + "4D")
      : (vc ? vc + "4D" : down + "4D");

    const volume: HistogramData<Time> = {
      time: t as Time,
      value: bar.volume || 0,
      color: volColor,
    };

    try {
      candleSeriesRef.current.update(candle);
      volumeSeriesRef.current.update(volume);
      if (t > lastSeriesTimeRef.current) lastSeriesTimeRef.current = t;
    } catch (e) {
      const msg = e instanceof Error ? e.message : (typeof e === "object" && e !== null ? JSON.stringify(e) : String(e));
      console.warn("[CandlestickChart] update error:", msg, "| bar.time=", bar.time);
    }
  }, []);

  useImperativeHandle(ref, () => ({
    updateBar,
    getChart: () => chartRef.current,
    getCandleSeries: () => candleSeriesRef.current,
  }), [updateBar]);

  // Create chart
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#18181b" },
        textColor: "#71717a",
        fontSize: 12,
      },
      grid: {
        vertLines: { color: "#27272a", visible: showGrid },
        horzLines: { color: "#27272a", visible: showGrid },
      },
      crosshair: {
        mode: showCrosshair ? CrosshairMode.Normal : CrosshairMode.Hidden,
        vertLine: { color: "#71717a", width: 1, style: 2 },
        horzLine: { color: "#71717a", width: 1, style: 2 },
      },
      rightPriceScale: {
        borderColor: "#27272a",
      },
      timeScale: {
        borderColor: "#27272a",
        timeVisible: true,
        secondsVisible: false,
      },
      width: containerRef.current.clientWidth,
      height,
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor,
      downColor,
      borderUpColor: upColor,
      borderDownColor: downColor,
      wickUpColor: upColor,
      wickDownColor: downColor,
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });

    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    overlaySeriesRef.current = new Map();

    // Handle resize
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        chart.applyOptions({ width: entry.contentRect.width });
      }
    });
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      overlaySeriesRef.current = new Map();
      dataLoadedRef.current = false;
      lastSeriesTimeRef.current = 0;
    };
  }, [height, upColor, downColor, showGrid, showCrosshair]);

  // Set initial data
  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current || data.length === 0) {
      dataLoadedRef.current = false;
      return;
    }

    const candles: CandlestickData<Time>[] = data
      .filter((d) => typeof d.time === "number" && Number.isFinite(d.time) && d.time > 0)
      .map((d) => ({
        time: d.time as Time,
        open: d.open,
        high: d.high,
        low: d.low,
        close: d.close,
      }));

    if (candles.length === 0) {
      dataLoadedRef.current = false;
      return;
    }

    const volUp = volumeColor ? volumeColor + "4D" : upColor + "4D";
    const volDown = volumeColor ? volumeColor + "4D" : downColor + "4D";
    const volumes: HistogramData<Time>[] = data
      .filter((d) => typeof d.time === "number" && Number.isFinite(d.time) && d.time > 0)
      .map((d) => ({
        time: d.time as Time,
        value: d.volume || 0,
        color: d.close >= d.open ? volUp : volDown,
      }));

    candleSeriesRef.current.setData(candles);
    volumeSeriesRef.current.setData(volumes);
    dataLoadedRef.current = true;

    if (candles.length > 0) {
      lastSeriesTimeRef.current = candles[candles.length - 1].time as number;
    }

    if (candles.length > 100) {
      const from = candles[candles.length - 100].time;
      const to = candles[candles.length - 1].time;
      chartRef.current?.timeScale().setVisibleRange({ from, to });
    }
  }, [data, upColor, downColor, volumeColor]);

  // ── Overlay lines (generic — handles any number of lines) ──
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    const currentMap = overlaySeriesRef.current;
    const wantedKeys = new Set((overlayLines || []).map((l) => l.key));

    // Remove series that are no longer needed
    for (const [key, series] of currentMap) {
      if (!wantedKeys.has(key)) {
        try { chart.removeSeries(series); } catch { /* ignore */ }
        currentMap.delete(key);
      }
    }

    // Add / update series
    for (const line of overlayLines || []) {
      let series = currentMap.get(line.key);
      if (!series) {
        series = chart.addSeries(LineSeries, {
          color: line.color,
          lineWidth: (line.lineWidth ?? 1) as 1 | 2 | 3 | 4,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        currentMap.set(line.key, series);
      } else {
        series.applyOptions({ color: line.color, lineWidth: (line.lineWidth ?? 1) as 1 | 2 | 3 | 4 });
      }
      const lineData: LineData<Time>[] = line.data.map((d) => ({
        time: d.time as Time,
        value: d.value,
      }));
      series.setData(lineData);
    }
  }, [overlayLines]);

  return (
    <div
      ref={containerRef}
      className="w-full rounded-lg overflow-hidden"
      style={{ height }}
    />
  );
});

export default CandlestickChart;
