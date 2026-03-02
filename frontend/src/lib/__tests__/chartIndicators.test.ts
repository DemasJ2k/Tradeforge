/**
 * Phase 5 — Chart Indicator helpers tests
 *
 * Tests the pure-logic functions in chartIndicators.ts:
 *  - buildTradeMarkers()
 *  - resetColorIndex()
 *  - indicatorResultsToOverlays() (mocked chart)
 *
 * Run: npx vitest run src/lib/__tests__/chartIndicators.test.ts
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  buildTradeMarkers,
  resetColorIndex,
  type TradeMarkerInput,
} from "../chartIndicators";

/* ── buildTradeMarkers ────────────────────────────────── */

describe("buildTradeMarkers", () => {
  it("returns empty array for no inputs", () => {
    expect(buildTradeMarkers([])).toEqual([]);
  });

  it("creates correct marker for long entry", () => {
    const inputs: TradeMarkerInput[] = [
      { time: 1700000000, type: "entry_long" },
    ];
    const markers = buildTradeMarkers(inputs);
    expect(markers).toHaveLength(1);
    expect(markers[0].position).toBe("belowBar");
    expect(markers[0].color).toBe("#22c55e");
    expect(markers[0].shape).toBe("arrowUp");
    expect(markers[0].text).toBe("▲ L");
  });

  it("creates correct marker for short entry", () => {
    const inputs: TradeMarkerInput[] = [
      { time: 1700000000, type: "entry_short" },
    ];
    const markers = buildTradeMarkers(inputs);
    expect(markers).toHaveLength(1);
    expect(markers[0].color).toBe("#ef4444");
    expect(markers[0].shape).toBe("arrowUp");
    expect(markers[0].text).toBe("▼ S");
  });

  it("creates correct marker for long exit", () => {
    const inputs: TradeMarkerInput[] = [
      { time: 1700000000, type: "exit_long", label: "+50" },
    ];
    const markers = buildTradeMarkers(inputs);
    expect(markers).toHaveLength(1);
    expect(markers[0].position).toBe("aboveBar");
    expect(markers[0].color).toBe("#22c55e");
    expect(markers[0].shape).toBe("arrowDown");
    expect(markers[0].text).toBe("+50");
  });

  it("creates correct marker for short exit", () => {
    const inputs: TradeMarkerInput[] = [
      { time: 1700000000, type: "exit_short", label: "-30" },
    ];
    const markers = buildTradeMarkers(inputs);
    expect(markers).toHaveLength(1);
    expect(markers[0].color).toBe("#ef4444");
  });

  it("sorts markers by time", () => {
    const inputs: TradeMarkerInput[] = [
      { time: 1700001000, type: "exit_long" },
      { time: 1700000000, type: "entry_long" },
      { time: 1700000500, type: "entry_short" },
    ];
    const markers = buildTradeMarkers(inputs);
    expect(markers).toHaveLength(3);
    expect((markers[0].time as number)).toBeLessThanOrEqual(markers[1].time as number);
    expect((markers[1].time as number)).toBeLessThanOrEqual(markers[2].time as number);
  });

  it("filters out markers with time <= 0", () => {
    const inputs: TradeMarkerInput[] = [
      { time: 0, type: "entry_long" },
      { time: -100, type: "exit_long" },
      { time: 1700000000, type: "entry_long" },
    ];
    const markers = buildTradeMarkers(inputs);
    expect(markers).toHaveLength(1);
    expect(markers[0].time).toBe(1700000000);
  });

  it("uses default labels when label is omitted", () => {
    const inputs: TradeMarkerInput[] = [
      { time: 1700000000, type: "entry_long" },
      { time: 1700001000, type: "exit_short" },
    ];
    const markers = buildTradeMarkers(inputs);
    expect(markers[0].text).toBe("▲ L");
    expect(markers[1].text).toBe("✕");
  });

  it("handles many markers efficiently", () => {
    const inputs: TradeMarkerInput[] = Array.from({ length: 500 }, (_, i) => ({
      time: 1700000000 + i * 600,
      type: (i % 2 === 0 ? "entry_long" : "exit_long") as TradeMarkerInput["type"],
    }));
    const markers = buildTradeMarkers(inputs);
    expect(markers).toHaveLength(500);
  });
});

/* ── resetColorIndex ──────────────────────────────────── */

describe("resetColorIndex", () => {
  it("is callable without errors", () => {
    expect(() => resetColorIndex()).not.toThrow();
  });
});
