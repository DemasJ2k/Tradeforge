/**
 * Phase 5  —  Lightweight Charts indicator rendering helpers.
 *
 * Provides functions to add/remove overlay indicators and trade markers
 * on an IChartApi instance from lightweight-charts v5.
 */

import {
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type Time,
  type LineData,
  type SeriesMarker,
} from "lightweight-charts";

/* ─── Colour palette for overlay lines ──────────────────── */
const OVERLAY_COLORS = [
  "#06b6d4", // cyan    (accent)
  "#f59e0b", // amber
  "#a78bfa", // violet
  "#f472b6", // pink
  "#34d399", // emerald
  "#fb923c", // orange
  "#60a5fa", // blue
  "#e879f9", // fuchsia
];

/* ─── Types ─────────────────────────────────────────────── */

export interface OverlayLine {
  key: string;
  series: ISeriesApi<"Line">;
  isOscillator: boolean;
}

export interface TradeMarkerInput {
  time: number;
  type: "entry_long" | "entry_short" | "exit_long" | "exit_short";
  label?: string;
}

/* ─── Helpers ───────────────────────────────────────────── */

let _colIdx = 0;
function nextColor(): string {
  const c = OVERLAY_COLORS[_colIdx % OVERLAY_COLORS.length];
  _colIdx++;
  return c;
}

export function resetColorIndex() {
  _colIdx = 0;
}

/**
 * Add an overlay indicator line series to the main chart.
 * For oscillators supply `paneId` to put it in a separate price scale.
 */
export function addIndicatorLine(
  chart: IChartApi,
  key: string,
  data: { time: number; value: number | null }[],
  opts?: { color?: string; lineWidth?: number; paneId?: string; visible?: boolean },
): OverlayLine {
  const color = opts?.color ?? nextColor();
  const isOsc = !!opts?.paneId;

  const series = chart.addSeries(LineSeries, {
    color,
    lineWidth: (opts?.lineWidth ?? 1) as 1 | 2 | 3 | 4,
    priceLineVisible: false,
    lastValueVisible: false,
    crosshairMarkerVisible: false,
    visible: opts?.visible ?? true,
    ...(isOsc ? { priceScaleId: opts!.paneId } : {}),
  });

  if (isOsc) {
    chart.priceScale(opts!.paneId!).applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });
  }

  const lineData: LineData<Time>[] = data
    .filter((d) => d.value !== null && Number.isFinite(d.value!))
    .map((d) => ({ time: d.time as Time, value: d.value! }));

  series.setData(lineData);
  return { key, series, isOscillator: isOsc };
}

/**
 * Remove a set of overlay lines from the chart.
 */
export function removeOverlayLines(chart: IChartApi, lines: OverlayLine[]) {
  for (const l of lines) {
    try {
      chart.removeSeries(l.series);
    } catch {
      /* already removed */
    }
  }
}

/**
 * Build an array of Lightweight Charts markers from trade data.
 */
export function buildTradeMarkers(
  inputs: TradeMarkerInput[],
): SeriesMarker<Time>[] {
  return inputs
    .filter((m) => m.time > 0)
    .sort((a, b) => a.time - b.time)
    .map((m) => {
      const isEntry = m.type.startsWith("entry");
      const isLong = m.type.includes("long");

      return {
        time: m.time as Time,
        position: isEntry ? "belowBar" : "aboveBar",
        color: isLong ? "#22c55e" : "#ef4444",
        shape: isEntry ? "arrowUp" : "arrowDown",
        text: m.label ?? (isEntry ? (isLong ? "▲ L" : "▼ S") : "✕"),
      } as SeriesMarker<Time>;
    });
}

/**
 * Map indicator compute response to chart overlay lines.
 * Returns one overlay per indicator key.
 */
export function indicatorResultsToOverlays(
  chart: IChartApi,
  timestamps: number[],
  results: Record<string, (number | null)[]>,
  overlayIndicators: string[],
): OverlayLine[] {
  resetColorIndex();
  const lines: OverlayLine[] = [];

  for (const [key, values] of Object.entries(results)) {
    const isOverlay = overlayIndicators.includes(key.split(".")[0]);
    const data = timestamps.map((t, i) => ({ time: t, value: values[i] ?? null }));

    lines.push(
      addIndicatorLine(chart, key, data, {
        paneId: isOverlay ? undefined : `osc_${key}`,
      }),
    );
  }
  return lines;
}
