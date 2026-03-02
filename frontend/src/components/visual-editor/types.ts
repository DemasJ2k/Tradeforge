/**
 * Phase 4 — Visual Node Editor types
 *
 * These types define the node data shapes used by React Flow nodes.
 * They bridge the visual graph representation ↔ JSON strategy schema.
 */

// ── Node data payloads ─────────────────────────────────────

export interface IndicatorNodeData {
  indicatorType: string;   // e.g. "EMA", "RSI", "BB"
  indicatorId: string;     // e.g. "ema_1"
  params: Record<string, number | string>;
  label: string;
}

export interface PriceNodeData {
  source: string;  // "open" | "high" | "low" | "close" | "volume"
  label: string;
}

export interface ConditionNodeData {
  operator: string; // "crosses_above" | ">" | "<" | ">=" | "<=" | "==" | "crosses_below"
  /** Static right-hand value (used when right input is not connected) */
  staticValue?: string;
  label: string;
}

export interface LogicGateNodeData {
  gateType: "AND" | "OR" | "NOT";
  label: string;
}

export interface IfThenElseNodeData {
  label: string;
}

export interface PatternNodeData {
  pattern: string; // e.g. "engulfing", "pin_bar"
  label: string;
}

export interface FilterNodeData {
  filterType: string; // "time" | "session" | "day_of_week" | "trend" | "adx" | "spread"
  config: Record<string, unknown>;
  label: string;
}

export interface SignalNodeData {
  signalType: "entry" | "exit";
  direction: "long" | "short" | "both";
  label: string;
}

export interface ConstantNodeData {
  value: string;
  label: string;
}

// ── Union of all node data types ───────────────────────────

export type StrategyNodeData =
  | IndicatorNodeData
  | PriceNodeData
  | ConditionNodeData
  | LogicGateNodeData
  | IfThenElseNodeData
  | PatternNodeData
  | FilterNodeData
  | SignalNodeData
  | ConstantNodeData;

// ── Node type identifiers (used in nodeTypes registry) ─────

export const NODE_TYPE_IDS = {
  INDICATOR: "indicatorNode",
  PRICE: "priceNode",
  CONDITION: "conditionNode",
  LOGIC_GATE: "logicGateNode",
  IF_THEN_ELSE: "ifThenElseNode",
  PATTERN: "patternNode",
  FILTER: "filterNode",
  SIGNAL: "signalNode",
  CONSTANT: "constantNode",
} as const;

export type NodeTypeId = (typeof NODE_TYPE_IDS)[keyof typeof NODE_TYPE_IDS];

// ── Handle IDs ─────────────────────────────────────────────
// Standardised handle names used by nodes for connections

export const HANDLE = {
  // Inputs
  IN: "in",
  LEFT: "left",
  RIGHT: "right",
  CONDITION: "condition",
  THEN: "then",
  ELSE: "else",
  GATE_IN: "gate-in",
  FILTER_IN: "filter-in",
  // Outputs
  OUT: "out",
  TRUE_OUT: "true",
  FALSE_OUT: "false",
  SIGNAL_OUT: "signal",
} as const;
