/**
 * Phase 4 — Visual Editor serialization tests
 *
 * Tests the strategy ↔ graph roundtrip (serialization.ts).
 * Run: npx jest --config jest.config.ts src/components/visual-editor/__tests__/serialization.test.ts
 *
 * If Jest isn't configured, these can be verified manually or via a simple Node script.
 */

import type { IndicatorConfig, ConditionRow } from "@/types";
import { strategyToGraph, graphToStrategy } from "../serialization";
import { NODE_TYPE_IDS } from "../types";

/* ── Helper ──────────────────────────────────────────────── */
function roundtrip(
  indicators: IndicatorConfig[],
  entryRules: ConditionRow[],
  exitRules: ConditionRow[],
) {
  const { nodes, edges } = strategyToGraph(indicators, entryRules, exitRules);
  return graphToStrategy(nodes, edges);
}

/* ── Tests ────────────────────────────────────────────────── */

describe("strategyToGraph", () => {
  it("creates indicator nodes for each indicator", () => {
    const indicators: IndicatorConfig[] = [
      { id: "ema_1", type: "EMA", params: { period: 20, source: "close" }, overlay: true },
      { id: "rsi_1", type: "RSI", params: { period: 14, source: "close" }, overlay: false },
    ];
    const { nodes } = strategyToGraph(indicators, [], []);
    const indNodes = nodes.filter((n) => n.type === NODE_TYPE_IDS.INDICATOR);
    expect(indNodes).toHaveLength(2);
  });

  it("creates pattern nodes for CANDLE_PATTERN indicators", () => {
    const indicators: IndicatorConfig[] = [
      { id: "candle_pattern_1", type: "CANDLE_PATTERN", params: { pattern: "engulfing" }, overlay: false },
    ];
    const { nodes } = strategyToGraph(indicators, [], []);
    const patNodes = nodes.filter((n) => n.type === NODE_TYPE_IDS.PATTERN);
    expect(patNodes).toHaveLength(1);
  });

  it("creates condition, signal, and price nodes for entry rules", () => {
    const indicators: IndicatorConfig[] = [
      { id: "ema_1", type: "EMA", params: { period: 20, source: "close" }, overlay: true },
    ];
    const entryRules: ConditionRow[] = [
      { left: "price.close", operator: ">", right: "ema_1", logic: "AND", direction: "long" },
    ];
    const { nodes, edges } = strategyToGraph(indicators, entryRules, []);

    const condNodes = nodes.filter((n) => n.type === NODE_TYPE_IDS.CONDITION);
    const sigNodes = nodes.filter((n) => n.type === NODE_TYPE_IDS.SIGNAL);
    const priceNodes = nodes.filter((n) => n.type === NODE_TYPE_IDS.PRICE);

    expect(condNodes.length).toBeGreaterThanOrEqual(1);
    expect(sigNodes.length).toBeGreaterThanOrEqual(1);
    expect(priceNodes.length).toBeGreaterThanOrEqual(1);
    expect(edges.length).toBeGreaterThanOrEqual(3); // left + right + cond→signal
  });

  it("creates constant nodes for numeric right values", () => {
    const indicators: IndicatorConfig[] = [
      { id: "rsi_1", type: "RSI", params: { period: 14, source: "close" }, overlay: false },
    ];
    const entryRules: ConditionRow[] = [
      { left: "rsi_1", operator: "crosses_above", right: "30", logic: "AND", direction: "long" },
    ];
    const { nodes } = strategyToGraph(indicators, entryRules, []);
    const constNodes = nodes.filter((n) => n.type === NODE_TYPE_IDS.CONSTANT);
    expect(constNodes.length).toBeGreaterThanOrEqual(1);
  });

  it("creates logic gate for multiple conditions", () => {
    const indicators: IndicatorConfig[] = [
      { id: "ema_1", type: "EMA", params: { period: 9, source: "close" }, overlay: true },
      { id: "ema_2", type: "EMA", params: { period: 21, source: "close" }, overlay: true },
    ];
    const entryRules: ConditionRow[] = [
      { left: "ema_1", operator: "crosses_above", right: "ema_2", logic: "AND", direction: "long" },
      { left: "price.close", operator: ">", right: "ema_2", logic: "AND", direction: "long" },
    ];
    const { nodes } = strategyToGraph(indicators, entryRules, []);
    const gateNodes = nodes.filter((n) => n.type === NODE_TYPE_IDS.LOGIC_GATE);
    expect(gateNodes).toHaveLength(1);
  });
});

describe("graphToStrategy", () => {
  it("extracts indicators from indicator nodes", () => {
    const indicators: IndicatorConfig[] = [
      { id: "ema_1", type: "EMA", params: { period: 20, source: "close" }, overlay: true },
    ];
    const { nodes, edges } = strategyToGraph(indicators, [], []);
    const result = graphToStrategy(nodes, edges);
    expect(result.indicators).toHaveLength(1);
    expect(result.indicators[0].type).toBe("EMA");
    expect(result.indicators[0].id).toBe("ema_1");
  });

  it("extracts pattern indicators from pattern nodes", () => {
    const indicators: IndicatorConfig[] = [
      { id: "candle_pattern_1", type: "CANDLE_PATTERN", params: { pattern: "pin_bar" }, overlay: false },
    ];
    const { nodes, edges } = strategyToGraph(indicators, [], []);
    const result = graphToStrategy(nodes, edges);
    expect(result.indicators).toHaveLength(1);
    expect(result.indicators[0].type).toBe("CANDLE_PATTERN");
    expect(result.indicators[0].params.pattern).toBe("pin_bar");
  });
});

describe("roundtrip", () => {
  it("preserves indicator configs through roundtrip", () => {
    const indicators: IndicatorConfig[] = [
      { id: "ema_1", type: "EMA", params: { period: 20, source: "close" }, overlay: true },
      { id: "rsi_1", type: "RSI", params: { period: 14, source: "close" }, overlay: false },
    ];
    const result = roundtrip(indicators, [], []);
    expect(result.indicators).toHaveLength(2);
    expect(result.indicators[0].type).toBe("EMA");
    expect(result.indicators[1].type).toBe("RSI");
  });

  it("preserves simple entry rule through roundtrip", () => {
    const indicators: IndicatorConfig[] = [
      { id: "ema_1", type: "EMA", params: { period: 20, source: "close" }, overlay: true },
    ];
    const entry: ConditionRow[] = [
      { left: "price.close", operator: ">", right: "ema_1", logic: "AND", direction: "long" },
    ];
    const result = roundtrip(indicators, entry, []);
    expect(result.entryRules).toHaveLength(1);
    expect(result.entryRules[0].left).toBe("price.close");
    expect(result.entryRules[0].operator).toBe(">");
    expect(result.entryRules[0].right).toBe("ema_1");
    expect(result.entryRules[0].direction).toBe("long");
  });

  it("preserves exit rules separately from entry rules", () => {
    const indicators: IndicatorConfig[] = [
      { id: "rsi_1", type: "RSI", params: { period: 14, source: "close" }, overlay: false },
    ];
    const entry: ConditionRow[] = [
      { left: "rsi_1", operator: "crosses_above", right: "30", logic: "AND", direction: "long" },
    ];
    const exit: ConditionRow[] = [
      { left: "rsi_1", operator: "crosses_below", right: "70", logic: "AND", direction: "short" },
    ];
    const result = roundtrip(indicators, entry, exit);
    expect(result.entryRules.length).toBeGreaterThanOrEqual(1);
    expect(result.exitRules.length).toBeGreaterThanOrEqual(1);
  });

  it("handles empty strategy", () => {
    const result = roundtrip([], [], []);
    expect(result.indicators).toHaveLength(0);
    expect(result.entryRules).toHaveLength(0);
    expect(result.exitRules).toHaveLength(0);
  });
});
