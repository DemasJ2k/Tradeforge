"use client";

/**
 * Phase 5A — Strategy Overlay Panel
 *
 * Collapsible sidebar panel that lets the user pick a strategy,
 * compute its indicators via `/api/backtest/indicators/compute`,
 * and draw the results on the main chart.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import { ChevronRight, ChevronLeft, Eye, EyeOff, Layers, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { IChartApi, ISeriesApi, Time, LineData } from "lightweight-charts";
import type { Strategy } from "@/types";

/* ─── Vibrant colour palette ─────────────────────── */
const LINE_COLORS = [
  "#22d3ee", // cyan-400
  "#fbbf24", // amber-400
  "#a78bfa", // violet-400
  "#f472b6", // pink-400
  "#4ade80", // green-400
  "#fb923c", // orange-400
  "#60a5fa", // blue-400
  "#e879f9", // fuchsia-400
  "#2dd4bf", // teal-400
  "#facc15", // yellow-400
];

/* ─── Band indicator types (use dashed + area fill) ─ */
const BAND_TYPES = new Set(["BB", "KELTNER", "DONCHIAN", "ENVELOPE"]);

/* ─── Types ───────────────────────────────────────── */
interface OverlayLine {
  key: string;
  series: ISeriesApi<"Line"> | ISeriesApi<"Area">;
  visible: boolean;
  color: string;
}

interface ComputeResponse {
  timestamps: number[];
  results: Record<string, (number | null)[]>;
}

interface Props {
  chart: IChartApi | null;
  datasourceId: number | null;
}

/* ─── Indicator overlay classification ────────────── */
const OVERLAY_TYPES = new Set([
  "SMA", "EMA", "WMA", "DEMA", "TEMA", "HMA", "KAMA",
  "BB",   // bollinger bands overlay
  "ICHIMOKU",
  "VWAP", "PIVOT",
  "SUPERTREND",
  "CANDLE_PATTERN",
  "KELTNER", "DONCHIAN", "ENVELOPE",
]);

function isOverlayIndicator(type: string): boolean {
  return OVERLAY_TYPES.has(type.toUpperCase());
}

function isBandIndicator(type: string): boolean {
  return BAND_TYPES.has(type.toUpperCase());
}

/* ─── Component ───────────────────────────────────── */

export default function StrategyOverlayPanel({ chart, datasourceId }: Props) {
  const [open, setOpen] = useState(false);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [selectedId, setSelectedId] = useState<number | "">("");
  const [computing, setComputing] = useState(false);
  const [error, setError] = useState("");
  const [lines, setLines] = useState<OverlayLine[]>([]);
  const colorIdx = useRef(0);

  // Load strategies on mount
  useEffect(() => {
    api.get<Strategy[]>("/api/strategies")
      .then((data) => {
        // handle both bare array and { items: [] } envelope
        const arr = Array.isArray(data) ? data : (data as unknown as { items: Strategy[] }).items ?? [];
        setStrategies(arr);
      })
      .catch(() => {});
  }, []);

  // Cleanup overlay lines when component unmounts or chart changes
  useEffect(() => {
    return () => {
      clearOverlays();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chart]);

  const clearOverlays = useCallback(() => {
    if (!chart) return;
    for (const l of lines) {
      try { chart.removeSeries(l.series); } catch { /* */ }
    }
    setLines([]);
  }, [chart, lines]);

  const nextColor = () => {
    const c = LINE_COLORS[colorIdx.current % LINE_COLORS.length];
    colorIdx.current++;
    return c;
  };

  /**
   * Snap indicator timestamps to the nearest candle timestamp on the chart.
   * This fixes alignment issues where backend returns slightly different timestamps.
   */
  const alignTimestamps = (indTimestamps: number[], chartData: { time: number }[]): Map<number, number> => {
    const map = new Map<number, number>();
    if (chartData.length === 0) return map;

    // Build a set of candle timestamps for O(1) lookup
    const candleTimes = new Set(chartData.map((c) => c.time));
    
    for (const t of indTimestamps) {
      if (candleTimes.has(t)) {
        map.set(t, t);
      } else {
        // Find nearest candle timestamp
        let best = chartData[0].time;
        let bestDiff = Math.abs(t - best);
        for (const c of chartData) {
          const diff = Math.abs(t - c.time);
          if (diff < bestDiff) {
            bestDiff = diff;
            best = c.time;
          }
          if (diff === 0) break;
        }
        // Only snap if within 2x the typical bar interval
        if (chartData.length > 1) {
          const avgInterval = (chartData[chartData.length - 1].time - chartData[0].time) / (chartData.length - 1);
          if (bestDiff <= avgInterval * 2) {
            map.set(t, best);
          }
        } else {
          map.set(t, best);
        }
      }
    }
    return map;
  };

  const computeAndDraw = useCallback(async () => {
    if (!chart || !selectedId || !datasourceId) return;

    const strat = strategies.find((s) => s.id === selectedId);
    if (!strat) return;

    setComputing(true);
    setError("");
    clearOverlays();
    colorIdx.current = 0;

    try {
      const indicators = strat.indicators ?? [];
      if (indicators.length === 0) {
        setError("Strategy has no indicators configured");
        return;
      }

      const resp = await api.post<ComputeResponse>("/api/backtest/indicators/compute", {
        datasource_id: datasourceId,
        indicators,
      });

      if (!resp.timestamps || !resp.results) {
        setError("No indicator data returned");
        return;
      }

      // Dynamic import to avoid SSR issues
      const { LineSeries, AreaSeries } = await import("lightweight-charts");

      const newLines: OverlayLine[] = [];

      for (const [key, values] of Object.entries(resp.results)) {
        const indId = key.split(".")[0];
        const ind = indicators.find((i) => i.id === indId);
        const indType = ind?.type?.toUpperCase() || "";
        const isOverlay = ind ? isOverlayIndicator(ind.type) : true;
        const isBand = isBandIndicator(indType);
        // Use area series for band upper/lower (not middle)
        const isBandEdge = isBand && (key.includes("upper") || key.includes("lower"));

        const color = nextColor();

        if (isBandEdge) {
          // Area series for band edges with semi-transparent fill
          const series = chart.addSeries(AreaSeries, {
            lineColor: color,
            topColor: color + "18",
            bottomColor: color + "05",
            lineWidth: 2 as 1 | 2 | 3 | 4,
            lineStyle: 2, // dashed
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
            visible: true,
          });

          const lineData = resp.timestamps
            .map((t, i) => ({ time: t as Time, value: values[i] }))
            .filter((d): d is { time: Time; value: number } => d.value !== null && Number.isFinite(d.value!));

          series.setData(lineData);
          newLines.push({ key, series, visible: true, color });
        } else {
          // Line series — thicker, vibrant
          const series = chart.addSeries(LineSeries, {
            color,
            lineWidth: 2 as 1 | 2 | 3 | 4,
            lineStyle: isBand ? 2 : 0, // dashed for band middle, solid otherwise
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
            visible: true,
            ...(isOverlay ? {} : { priceScaleId: `osc_${indId}` }),
          });

          if (!isOverlay) {
            chart.priceScale(`osc_${indId}`).applyOptions({
              scaleMargins: { top: 0.80, bottom: 0.02 },
              borderVisible: true,
              borderColor: "#27272a",
            });
          }

          const lineData = resp.timestamps
            .map((t, i) => ({ time: t as Time, value: values[i] }))
            .filter((d): d is { time: Time; value: number } => d.value !== null && Number.isFinite(d.value!));

          series.setData(lineData);
          newLines.push({ key, series, visible: true, color });
        }
      }

      setLines(newLines);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to compute indicators");
    } finally {
      setComputing(false);
    }
  }, [chart, selectedId, datasourceId, strategies, clearOverlays]);

  const toggleLine = (idx: number) => {
    setLines((prev) =>
      prev.map((l, i) =>
        i === idx
          ? (() => {
              const next = !l.visible;
              l.series.applyOptions({ visible: next });
              return { ...l, visible: next };
            })()
          : l,
      ),
    );
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="absolute top-2 right-2 z-10 flex items-center gap-1 rounded-lg bg-card-bg/90 border border-card-border px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:border-fa-accent/40 transition-colors backdrop-blur-sm"
        title="Strategy Overlay"
      >
        <Layers className="h-3.5 w-3.5" />
        <ChevronLeft className="h-3 w-3" />
      </button>
    );
  }

  return (
    <div className="absolute top-0 right-0 z-10 h-full w-64 bg-card-bg/95 border-l border-card-border backdrop-blur-sm flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-card-border">
        <span className="text-xs font-semibold text-foreground/80 flex items-center gap-1.5">
          <Layers className="h-3.5 w-3.5 text-fa-accent" />
          Strategy Overlay
        </span>
        <button onClick={() => setOpen(false)} className="text-muted-foreground hover:text-foreground">
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>

      {/* Strategy selector */}
      <div className="px-3 py-2 space-y-2 border-b border-card-border">
        <select
          value={selectedId}
          onChange={(e) => setSelectedId(e.target.value ? Number(e.target.value) : "")}
          className="w-full rounded border border-card-border bg-background px-2 py-1.5 text-xs focus:outline-none focus:border-fa-accent/50"
        >
          <option value="">Select strategy…</option>
          {strategies.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>

        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={computeAndDraw}
            disabled={!selectedId || computing || !datasourceId}
            className="flex-1 text-xs h-7 border-fa-accent/30 text-fa-accent hover:bg-fa-accent/10"
          >
            {computing ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
            {computing ? "Computing…" : "Apply"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={clearOverlays}
            disabled={lines.length === 0}
            className="text-xs h-7 text-muted-foreground"
          >
            Clear
          </Button>
        </div>

        {error && <p className="text-xs text-red-400">{error}</p>}
      </div>

      {/* Active indicator lines */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1">
        {lines.length === 0 && (
          <p className="text-xs text-muted-foreground/60 text-center mt-4">
            No overlays active
          </p>
        )}
        {lines.map((l, idx) => (
          <div
            key={l.key}
            className="flex items-center justify-between py-1 px-1.5 rounded hover:bg-muted/30 text-xs"
          >
            <div className="flex items-center gap-2 min-w-0">
              <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ backgroundColor: l.color }} />
              <span className="truncate text-foreground/80">{l.key}</span>
            </div>
            <button onClick={() => toggleLine(idx)} className="text-muted-foreground hover:text-foreground shrink-0">
              {l.visible ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
