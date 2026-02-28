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
}

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
  indicators?: IndicatorConfig;
}

// ─── Indicator calculation helpers ───────────────────────────────────────────

function calcSMA(closes: number[], len: number): (number | null)[] {
  return closes.map((_, i) => {
    if (i < len - 1) return null;
    const slice = closes.slice(i - len + 1, i + 1);
    return slice.reduce((a, b) => a + b, 0) / len;
  });
}

function calcEMA(closes: number[], len: number): (number | null)[] {
  const k = 2 / (len + 1);
  const result: (number | null)[] = [];
  let ema: number | null = null;
  for (let i = 0; i < closes.length; i++) {
    if (i < len - 1) { result.push(null); continue; }
    if (ema === null) {
      ema = closes.slice(0, len).reduce((a, b) => a + b, 0) / len;
    } else {
      ema = closes[i] * k + ema * (1 - k);
    }
    result.push(ema);
  }
  return result;
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
    indicators,
  },
  ref
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const maSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const emaSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const colors = useMemo(() => ({ upColor, downColor, volumeColor }), [upColor, downColor, volumeColor]);
  const colorsRef = useRef(colors);

  // Keep colors ref in sync (inside an effect to avoid ref access during render)
  useEffect(() => {
    colorsRef.current = colors;
  }, [colors]);

  // Track whether initial data has been set (to avoid .update() on empty series)
  const dataLoadedRef = useRef(false);

  // Expose imperative handle for live updates
  const updateBar = useCallback((bar: CandleInput) => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current) return;
    if (!dataLoadedRef.current) return; // Don't update before setData

    // Validate time is a proper finite number (Unix timestamp in seconds)
    const t = typeof bar.time === "number" ? bar.time : Number(bar.time);
    if (!Number.isFinite(t) || t <= 0) return;

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

    // .update() will append if new time, or update if same time
    try {
      candleSeriesRef.current.update(candle);
      volumeSeriesRef.current.update(volume);
    } catch (e) {
      // Ignore lightweight-charts ordering errors (e.g., stale data)
      console.warn("[CandlestickChart] update error:", e);
    }
  }, []);

  useImperativeHandle(ref, () => ({
    updateBar,
    getChart: () => chartRef.current,
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

    // MA series (always created, hidden until enabled)
    const maSeries = chart.addSeries(LineSeries, {
      color: "#f59e0b",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
      visible: false,
    });

    // EMA series
    const emaSeries = chart.addSeries(LineSeries, {
      color: "#a78bfa",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
      visible: false,
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    maSeriesRef.current = maSeries;
    emaSeriesRef.current = emaSeries;

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
      maSeriesRef.current = null;
      emaSeriesRef.current = null;
      dataLoadedRef.current = false;
    };
  }, [height, upColor, downColor, showGrid, showCrosshair]);

  // Set initial data
  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current || data.length === 0) {
      dataLoadedRef.current = false;
      return;
    }

    // Ensure all time values are valid numbers (Unix timestamps in seconds)
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

    if (candles.length > 100) {
      const from = candles[candles.length - 100].time;
      const to = candles[candles.length - 1].time;
      chartRef.current?.timeScale().setVisibleRange({ from, to });
    }
  }, [data, upColor, downColor, volumeColor]);

  // Update MA/EMA indicators when data or indicator config changes
  useEffect(() => {
    if (!maSeriesRef.current || !emaSeriesRef.current || data.length === 0) return;

    const validData = data.filter(
      (d) => typeof d.time === "number" && Number.isFinite(d.time) && d.time > 0
    );
    const closes = validData.map((d) => d.close);
    const times = validData.map((d) => d.time as Time);

    // MA
    const showMA = indicators?.ma ?? false;
    const maLen = indicators?.maLen ?? 20;
    if (showMA && closes.length >= maLen) {
      const maValues = calcSMA(closes, maLen);
      const maData: LineData<Time>[] = maValues
        .map((v, i) => ({ time: times[i], value: v! }))
        .filter((d) => d.value !== null);
      maSeriesRef.current.setData(maData);
      maSeriesRef.current.applyOptions({ visible: true });
    } else {
      maSeriesRef.current.applyOptions({ visible: false });
    }

    // EMA
    const showEMA = indicators?.ema ?? false;
    const emaLen = indicators?.emaLen ?? 50;
    if (showEMA && closes.length >= emaLen) {
      const emaValues = calcEMA(closes, emaLen);
      const emaData: LineData<Time>[] = emaValues
        .map((v, i) => ({ time: times[i], value: v! }))
        .filter((d) => d.value !== null);
      emaSeriesRef.current.setData(emaData);
      emaSeriesRef.current.applyOptions({ visible: true });
    } else {
      emaSeriesRef.current.applyOptions({ visible: false });
    }
  }, [data, indicators]);

  return (
    <div
      ref={containerRef}
      className="w-full rounded-lg overflow-hidden"
      style={{ height }}
    />
  );
});

export default CandlestickChart;
