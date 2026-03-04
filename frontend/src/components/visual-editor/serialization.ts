/**
 * Phase 4C — Serialization: visual graph ↔ JSON strategy
 *
 * Two main functions:
 *  1. strategyToGraph()  — convert a JSON strategy into React Flow nodes/edges
 *  2. graphToStrategy()  — convert React Flow nodes/edges into JSON strategy
 */

import type { Node, Edge } from "@xyflow/react";
import type { IndicatorConfig, ConditionRow } from "@/types";
import { NODE_TYPE_IDS, HANDLE } from "./types";
import type {
  IndicatorNodeData,
  PriceNodeData,
  ConditionNodeData,
  LogicGateNodeData,
  SignalNodeData,
  PatternNodeData,
  ConstantNodeData,
} from "./types";

// ── Helpers ────────────────────────────────────────────────

/** Safe cast for React Flow node.data (which is Record<string, unknown>) */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function nd<T>(node: Node): T { return node.data as any as T; }

let _nextId = 1;
function uid() {
  return `node_${Date.now()}_${_nextId++}`;
}

const X_START = 60;
const Y_GAP = 120;
const X_GAP = 250;

// ── Strategy → Graph ───────────────────────────────────────

export function strategyToGraph(
  indicators: IndicatorConfig[],
  entryRules: ConditionRow[],
  exitRules: ConditionRow[],
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const indicatorNodeIds: Record<string, string> = {};

  let yOff = 40;

  // 1) Create indicator / price nodes (column 0)
  for (const ind of indicators) {
    const nId = uid();
    indicatorNodeIds[ind.id] = nId;

    if (ind.type === "CANDLE_PATTERN") {
      nodes.push({
        id: nId,
        type: NODE_TYPE_IDS.PATTERN,
        position: { x: X_START, y: yOff },
        data: {
          pattern: String(ind.params.pattern || "engulfing"),
          label: String(ind.params.pattern || "engulfing"),
        } satisfies PatternNodeData,
      });
    } else {
      nodes.push({
        id: nId,
        type: NODE_TYPE_IDS.INDICATOR,
        position: { x: X_START, y: yOff },
        data: {
          indicatorType: ind.type,
          indicatorId: ind.id,
          params: { ...ind.params },
          label: `${ind.type} (${ind.id})`,
        } satisfies IndicatorNodeData,
      });
    }
    yOff += Y_GAP;
  }

  // Helper to resolve a source ref (like "price.close", "ema_1", "70") to a node+handle
  function resolveSource(ref: string): { nodeId: string; handle: string } | null {
    // Price source
    if (ref.startsWith("price.")) {
      const src = ref.replace("price.", "");
      const existing = nodes.find(
        (n) => n.type === NODE_TYPE_IDS.PRICE && nd<PriceNodeData>(n).source === src,
      );
      if (existing) return { nodeId: existing.id, handle: HANDLE.OUT };

      const pId = uid();
      nodes.push({
        id: pId,
        type: NODE_TYPE_IDS.PRICE,
        position: { x: X_START, y: yOff },
        data: { source: src, label: ref } satisfies PriceNodeData,
      });
      yOff += Y_GAP * 0.7;
      return { nodeId: pId, handle: HANDLE.OUT };
    }

    // Indicator ref — supports dot notation ("bb_1.upper") and underscore notation ("bb_1_upper")
    const baseName = ref.split(".")[0];
    if (indicatorNodeIds[baseName]) {
      return { nodeId: indicatorNodeIds[baseName], handle: HANDLE.OUT };
    }
    // Try underscore-separated: "bb_1_upper" → check if "bb_1" exists
    for (const indId of Object.keys(indicatorNodeIds)) {
      if (ref.startsWith(indId + "_") && ref.length > indId.length + 1) {
        return { nodeId: indicatorNodeIds[indId], handle: HANDLE.OUT };
      }
    }

    // Numeric constant
    if (!isNaN(Number(ref))) {
      const cId = uid();
      nodes.push({
        id: cId,
        type: NODE_TYPE_IDS.CONSTANT,
        position: { x: X_START, y: yOff },
        data: { value: ref, label: ref } satisfies ConstantNodeData,
      });
      yOff += Y_GAP * 0.6;
      return { nodeId: cId, handle: HANDLE.OUT };
    }

    return null;
  }

  // 2) Create condition + signal nodes for rules
  function processRules(rules: ConditionRow[], signalType: "entry" | "exit", xBase: number) {
    let ry = 40;
    // Group by direction
    const condNodeIds: string[] = [];

    for (const rule of rules) {
      // Condition node
      const condId = uid();
      nodes.push({
        id: condId,
        type: NODE_TYPE_IDS.CONDITION,
        position: { x: xBase, y: ry },
        data: {
          operator: rule.operator,
          label: `${rule.left} ${rule.operator} ${rule.right}`,
        } satisfies ConditionNodeData,
      });
      condNodeIds.push(condId);

      // Wire left
      const leftSrc = resolveSource(rule.left);
      if (leftSrc) {
        edges.push({
          id: `e-${leftSrc.nodeId}-${condId}-L`,
          source: leftSrc.nodeId,
          sourceHandle: leftSrc.handle,
          target: condId,
          targetHandle: HANDLE.LEFT,
          animated: true,
        });
      }

      // Wire right
      const rightSrc = resolveSource(rule.right);
      if (rightSrc) {
        edges.push({
          id: `e-${rightSrc.nodeId}-${condId}-R`,
          source: rightSrc.nodeId,
          sourceHandle: rightSrc.handle,
          target: condId,
          targetHandle: HANDLE.RIGHT,
          animated: true,
        });
      }

      ry += Y_GAP;
    }

    if (condNodeIds.length === 0) return;

    // Logic gate to combine (if >1 condition with same logic)
    let finalBoolNode = condNodeIds[0];
    if (condNodeIds.length > 1) {
      const gateId = uid();
      const logic = rules[0]?.logic || "AND";
      nodes.push({
        id: gateId,
        type: NODE_TYPE_IDS.LOGIC_GATE,
        position: { x: xBase + X_GAP, y: 40 + (ry - 40) / 2 - Y_GAP / 2 },
        data: { gateType: logic as "AND" | "OR", label: logic } satisfies LogicGateNodeData,
      });

      condNodeIds.forEach((cid, i) => {
        edges.push({
          id: `e-${cid}-${gateId}`,
          source: cid,
          sourceHandle: HANDLE.OUT,
          target: gateId,
          targetHandle: `${HANDLE.GATE_IN}-${Math.min(i, 1)}`,
          animated: true,
        });
      });
      finalBoolNode = gateId;
    }

    // Signal node
    const sigId = uid();
    const direction = rules.length > 0 ? rules[0].direction || "both" : "both";
    nodes.push({
      id: sigId,
      type: NODE_TYPE_IDS.SIGNAL,
      position: {
        x: condNodeIds.length > 1 ? xBase + X_GAP * 2 : xBase + X_GAP,
        y: 40 + (ry - 40) / 2 - Y_GAP / 2,
      },
      data: {
        signalType,
        direction: direction as "long" | "short" | "both",
        label: `${signalType} ${direction}`,
      } satisfies SignalNodeData,
    });

    edges.push({
      id: `e-${finalBoolNode}-${sigId}`,
      source: finalBoolNode,
      sourceHandle: HANDLE.OUT,
      target: sigId,
      targetHandle: HANDLE.IN,
      animated: true,
    });
  }

  processRules(entryRules, "entry", X_START + X_GAP);
  processRules(exitRules, "exit", X_START + X_GAP);

  return { nodes, edges };
}

// ── Graph → Strategy ───────────────────────────────────────

export function graphToStrategy(
  nodes: Node[],
  edges: Edge[],
): {
  indicators: IndicatorConfig[];
  entryRules: ConditionRow[];
  exitRules: ConditionRow[];
} {
  const indicators: IndicatorConfig[] = [];
  const entryRules: ConditionRow[] = [];
  const exitRules: ConditionRow[] = [];

  // Build lookup maps
  const nodeMap = new Map(nodes.map((n) => [n.id, n]));

  // Collect indicators
  for (const node of nodes) {
    if (node.type === NODE_TYPE_IDS.INDICATOR) {
      const d = nd<IndicatorNodeData>(node);
      indicators.push({
        id: d.indicatorId,
        type: d.indicatorType,
        params: { ...d.params },
        overlay: !["RSI", "MACD", "STOCH", "ADX", "CCI", "MFI", "WILLR", "OBV", "VWAP_BANDS", "ATR"].includes(d.indicatorType),
      });
    }
    if (node.type === NODE_TYPE_IDS.PATTERN) {
      const d = nd<PatternNodeData>(node);
      const count = indicators.filter((i) => i.type === "CANDLE_PATTERN").length;
      indicators.push({
        id: `candle_pattern_${count + 1}`,
        type: "CANDLE_PATTERN",
        params: { pattern: d.pattern },
        overlay: false,
      });
    }
  }

  // Resolve what a handle outputs as a source reference string
  function resolveRef(nodeId: string): string {
    const node = nodeMap.get(nodeId);
    if (!node) return "0";

    switch (node.type) {
      case NODE_TYPE_IDS.PRICE:
        return `price.${nd<PriceNodeData>(node).source}`;
      case NODE_TYPE_IDS.INDICATOR:
        return nd<IndicatorNodeData>(node).indicatorId;
      case NODE_TYPE_IDS.PATTERN: {
        const d = nd<PatternNodeData>(node);
        const idx = indicators.findIndex(
          (i) => i.type === "CANDLE_PATTERN" && i.params.pattern === d.pattern,
        );
        return idx >= 0 ? indicators[idx].id : "candle_pattern_1";
      }
      case NODE_TYPE_IDS.CONSTANT:
        return nd<ConstantNodeData>(node).value;
      default:
        return "0";
    }
  }

  // Find signal nodes and trace back to condition nodes
  const signalNodes = nodes.filter((n) => n.type === NODE_TYPE_IDS.SIGNAL);

  for (const sigNode of signalNodes) {
    const sigData = nd<SignalNodeData>(sigNode);
    const rules: ConditionRow[] = [];

    // Find edges coming into this signal's "in" handle
    const inEdges = edges.filter(
      (e) => e.target === sigNode.id && e.targetHandle === HANDLE.IN,
    );

    for (const inEdge of inEdges) {
      const srcNode = nodeMap.get(inEdge.source);
      if (!srcNode) continue;

      if (srcNode.type === NODE_TYPE_IDS.CONDITION) {
        // Direct condition → signal
        rules.push(conditionNodeToRow(srcNode, edges, sigData.direction, "AND"));
      } else if (srcNode.type === NODE_TYPE_IDS.LOGIC_GATE) {
        // Logic gate → unroll
        const gateData = nd<LogicGateNodeData>(srcNode);
        const gateInEdges = edges.filter(
          (e) => e.target === srcNode.id && e.targetHandle?.startsWith(HANDLE.GATE_IN),
        );
        for (const ge of gateInEdges) {
          const condNode = nodeMap.get(ge.source);
          if (condNode?.type === NODE_TYPE_IDS.CONDITION) {
            rules.push(conditionNodeToRow(condNode, edges, sigData.direction, gateData.gateType));
          }
        }
      }
    }

    if (sigData.signalType === "entry") {
      entryRules.push(...rules);
    } else {
      exitRules.push(...rules);
    }
  }

  function conditionNodeToRow(
    condNode: Node,
    allEdges: Edge[],
    direction: string,
    logic: string,
  ): ConditionRow {
    const condData = nd<ConditionNodeData>(condNode);

    // Find left input
    const leftEdge = allEdges.find(
      (e) => e.target === condNode.id && e.targetHandle === HANDLE.LEFT,
    );
    const left = leftEdge ? resolveRef(leftEdge.source) : "price.close";

    // Find right input
    const rightEdge = allEdges.find(
      (e) => e.target === condNode.id && e.targetHandle === HANDLE.RIGHT,
    );
    const right = rightEdge ? resolveRef(rightEdge.source) : condData.staticValue || "0";

    return {
      left,
      operator: condData.operator,
      right,
      logic,
      direction,
    };
  }

  return { indicators, entryRules, exitRules };
}
