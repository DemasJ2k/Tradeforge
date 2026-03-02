"use client";

/**
 * Phase 4D — Visual Node Editor component
 *
 * Drag-and-drop strategy builder using React Flow.
 * Renders as an alternative view inside StrategyEditor.
 */

import { useCallback, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  Controls,
  MiniMap,
  Background,
  BackgroundVariant,
  addEdge,
  useNodesState,
  useEdgesState,
  type OnConnect,
  type Node,
  type Edge,
  type NodeTypes,
  ReactFlowProvider,
  Panel,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { IndicatorConfig, ConditionRow } from "@/types";
import { NODE_TYPE_IDS } from "./types";
import {
  IndicatorNode,
  PriceNode,
  ConstantNode,
  ConditionNode,
  LogicGateNode,
  IfThenElseNode,
  PatternNode,
  FilterNode,
  SignalNode,
} from "./StrategyNodes";
import { strategyToGraph, graphToStrategy } from "./serialization";

/* ── Node types registry ─────────────────────────────────── */

const nodeTypes: NodeTypes = {
  [NODE_TYPE_IDS.INDICATOR]: IndicatorNode as unknown as NodeTypes[string],
  [NODE_TYPE_IDS.PRICE]: PriceNode as unknown as NodeTypes[string],
  [NODE_TYPE_IDS.CONSTANT]: ConstantNode as unknown as NodeTypes[string],
  [NODE_TYPE_IDS.CONDITION]: ConditionNode as unknown as NodeTypes[string],
  [NODE_TYPE_IDS.LOGIC_GATE]: LogicGateNode as unknown as NodeTypes[string],
  [NODE_TYPE_IDS.IF_THEN_ELSE]: IfThenElseNode as unknown as NodeTypes[string],
  [NODE_TYPE_IDS.PATTERN]: PatternNode as unknown as NodeTypes[string],
  [NODE_TYPE_IDS.FILTER]: FilterNode as unknown as NodeTypes[string],
  [NODE_TYPE_IDS.SIGNAL]: SignalNode as unknown as NodeTypes[string],
};

/* ── Node palette items ──────────────────────────────────── */

interface PaletteItem {
  type: string;
  label: string;
  icon: string;
  defaultData: Record<string, unknown>;
}

const PALETTE: PaletteItem[] = [
  {
    type: NODE_TYPE_IDS.INDICATOR,
    label: "Indicator",
    icon: "📊",
    defaultData: { indicatorType: "EMA", indicatorId: "ema_new", params: { period: 20, source: "close" }, label: "EMA" },
  },
  {
    type: NODE_TYPE_IDS.PRICE,
    label: "Price",
    icon: "💲",
    defaultData: { source: "close", label: "price.close" },
  },
  {
    type: NODE_TYPE_IDS.CONSTANT,
    label: "Value",
    icon: "#",
    defaultData: { value: "50", label: "50" },
  },
  {
    type: NODE_TYPE_IDS.CONDITION,
    label: "Condition",
    icon: "⚖️",
    defaultData: { operator: ">", label: "Condition" },
  },
  {
    type: NODE_TYPE_IDS.LOGIC_GATE,
    label: "Logic Gate",
    icon: "🔗",
    defaultData: { gateType: "AND", label: "AND" },
  },
  {
    type: NODE_TYPE_IDS.IF_THEN_ELSE,
    label: "IF/THEN/ELSE",
    icon: "🔀",
    defaultData: { label: "IF/THEN/ELSE" },
  },
  {
    type: NODE_TYPE_IDS.PATTERN,
    label: "Pattern",
    icon: "🕯️",
    defaultData: { pattern: "engulfing", label: "engulfing" },
  },
  {
    type: NODE_TYPE_IDS.FILTER,
    label: "Filter",
    icon: "🔒",
    defaultData: { filterType: "time", config: {}, label: "time" },
  },
  {
    type: NODE_TYPE_IDS.SIGNAL,
    label: "Entry Signal",
    icon: "🟢",
    defaultData: { signalType: "entry", direction: "both", label: "entry" },
  },
  {
    type: NODE_TYPE_IDS.SIGNAL,
    label: "Exit Signal",
    icon: "🔴",
    defaultData: { signalType: "exit", direction: "both", label: "exit" },
  },
];

/* ── Props ────────────────────────────────────────────────── */

interface VisualEditorProps {
  indicators: IndicatorConfig[];
  entryRules: ConditionRow[];
  exitRules: ConditionRow[];
  onSync: (indicators: IndicatorConfig[], entryRules: ConditionRow[], exitRules: ConditionRow[]) => void;
  readOnly?: boolean;
}

/* ── Inner component (must be inside ReactFlowProvider) ──── */

function VisualEditorInner({
  indicators,
  entryRules,
  exitRules,
  onSync,
  readOnly,
}: VisualEditorProps) {
  const initial = useMemo(
    () => strategyToGraph(indicators, entryRules, exitRules),
    // Only compute on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initial.edges);
  const [dirty, setDirty] = useState(false);
  const idCounter = useRef(Date.now());

  const onConnect: OnConnect = useCallback(
    (connection) => {
      setEdges((eds) => addEdge({ ...connection, animated: true }, eds));
      setDirty(true);
    },
    [setEdges],
  );

  const handleNodesChange: typeof onNodesChange = useCallback(
    (changes) => {
      onNodesChange(changes);
      // Mark dirty on meaningful changes (not just selection)
      if (changes.some((c) => c.type === "remove" || c.type === "add")) {
        setDirty(true);
      }
    },
    [onNodesChange],
  );

  const handleEdgesChange: typeof onEdgesChange = useCallback(
    (changes) => {
      onEdgesChange(changes);
      if (changes.some((c) => c.type === "remove" || c.type === "add")) {
        setDirty(true);
      }
    },
    [onEdgesChange],
  );

  /* ── Add node from palette ──────────────────────────────── */
  const addNode = useCallback(
    (item: PaletteItem) => {
      idCounter.current += 1;
      const newNode: Node = {
        id: `visual_${idCounter.current}`,
        type: item.type,
        position: { x: 300 + Math.random() * 100, y: 200 + Math.random() * 100 },
        data: { ...item.defaultData },
      };
      setNodes((nds) => [...nds, newNode]);
      setDirty(true);
    },
    [setNodes],
  );

  /* ── Sync back to form ──────────────────────────────────── */
  const syncToForm = useCallback(() => {
    const result = graphToStrategy(nodes, edges);
    onSync(result.indicators, result.entryRules, result.exitRules);
    setDirty(false);
  }, [nodes, edges, onSync]);

  /* ── Reload from form ───────────────────────────────────── */
  const reloadFromForm = useCallback(() => {
    const g = strategyToGraph(indicators, entryRules, exitRules);
    setNodes(g.nodes);
    setEdges(g.edges);
    setDirty(false);
  }, [indicators, entryRules, exitRules, setNodes, setEdges]);

  return (
    <div className="w-full h-[620px] rounded-lg border border-card-border overflow-hidden bg-slate-950 relative">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={readOnly ? undefined : handleNodesChange}
        onEdgesChange={readOnly ? undefined : handleEdgesChange}
        onConnect={readOnly ? undefined : onConnect}
        nodeTypes={nodeTypes}
        fitView
        snapToGrid
        snapGrid={[15, 15]}
        minZoom={0.3}
        maxZoom={2}
        deleteKeyCode={readOnly ? null : "Delete"}
        className="bg-slate-950"
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={15} size={1} color="#1e293b" />
        <Controls className="!bg-slate-800 !border-slate-700 !shadow-xl [&_button]:!bg-slate-700 [&_button]:!border-slate-600 [&_button]:!text-slate-300 [&_button:hover]:!bg-slate-600" />
        <MiniMap
          nodeStrokeColor="#06b6d4"
          nodeColor="#0f172a"
          maskColor="rgb(15, 23, 42, 0.7)"
          className="!bg-slate-900 !border-slate-700"
        />

        {/* Top panel: sync buttons */}
        <Panel position="top-right" className="flex gap-2">
          {dirty && (
            <span className="text-[10px] text-amber-400 bg-amber-900/30 px-2 py-1 rounded self-center">
              Unsaved graph changes
            </span>
          )}
          <button
            onClick={syncToForm}
            className="px-3 py-1.5 text-xs font-medium rounded bg-cyan-600 hover:bg-cyan-500 text-white shadow"
          >
            Sync → Form
          </button>
          <button
            onClick={reloadFromForm}
            className="px-3 py-1.5 text-xs font-medium rounded bg-slate-700 hover:bg-slate-600 text-slate-200 shadow"
          >
            ↻ Reload
          </button>
        </Panel>
      </ReactFlow>

      {/* Left sidebar: node palette */}
      {!readOnly && (
        <div className="absolute top-2 left-2 z-10 bg-slate-900/95 border border-slate-700 rounded-lg p-2 space-y-1 w-[130px] shadow-xl backdrop-blur">
          <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider px-1 mb-1">
            Add Node
          </div>
          {PALETTE.map((item, i) => (
            <button
              key={`${item.type}-${i}`}
              onClick={() => addNode(item)}
              className="flex items-center gap-1.5 w-full px-2 py-1.5 rounded text-left text-[11px] text-slate-300 hover:bg-slate-700/60 transition-colors"
            >
              <span className="text-sm">{item.icon}</span>
              <span>{item.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Exported wrapper with ReactFlowProvider ─────────────── */

export default function VisualEditor(props: VisualEditorProps) {
  return (
    <ReactFlowProvider>
      <VisualEditorInner {...props} />
    </ReactFlowProvider>
  );
}
