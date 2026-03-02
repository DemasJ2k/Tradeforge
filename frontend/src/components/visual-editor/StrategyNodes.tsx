"use client";

/**
 * Phase 4B — Custom React Flow node components
 *
 * Each node renders a styled card with typed input/output handles.
 * Nodes are purposely compact so many fit on screen.
 */

import { memo, useCallback } from "react";
import { Handle, Position, useReactFlow, type NodeProps } from "@xyflow/react";
import type {
  IndicatorNodeData,
  PriceNodeData,
  ConditionNodeData,
  LogicGateNodeData,
  IfThenElseNodeData,
  PatternNodeData,
  FilterNodeData,
  SignalNodeData,
  ConstantNodeData,
} from "./types";
import { HANDLE } from "./types";

/* ── Shared styling ──────────────────────────────────────── */
const baseCard =
  "rounded-lg border shadow-md text-xs min-w-[140px] select-none";
const headerCls =
  "px-2.5 py-1.5 font-semibold text-[10px] uppercase tracking-wider rounded-t-lg flex items-center gap-1.5";
const bodyCls = "px-2.5 py-2 space-y-1.5";
const handleStyle = { width: 8, height: 8 };
const inputCls =
  "w-full bg-black/20 border border-white/10 rounded px-1.5 py-0.5 text-[11px] text-white focus:border-cyan-400 focus:outline-none";
const selectCls = inputCls;

/* ── Helper: tiny labelled handle ────────────────────────── */
function LabelledHandle({
  type,
  position,
  id,
  label,
  className,
}: {
  type: "source" | "target";
  position: Position;
  id: string;
  label?: string;
  className?: string;
}) {
  return (
    <div className={`relative flex items-center ${position === Position.Left ? "justify-start" : "justify-end"} ${className || ""}`}>
      <Handle type={type} position={position} id={id} style={handleStyle} className="!bg-cyan-400 !border-cyan-600" />
      {label && (
        <span className={`text-[9px] text-white/50 ${position === Position.Left ? "ml-3" : "mr-3"}`}>
          {label}
        </span>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════
   INDICATOR NODE
   ═══════════════════════════════════════════════════════════ */
export const IndicatorNode = memo(function IndicatorNode({ id, data }: NodeProps & { data: IndicatorNodeData }) {
  const { updateNodeData } = useReactFlow();
  const onChange = useCallback(
    (key: string, val: string | number) => {
      updateNodeData(id, { params: { ...data.params, [key]: val } });
    },
    [id, data.params, updateNodeData],
  );

  return (
    <div className={`${baseCard} border-cyan-700/60 bg-slate-900`}>
      <div className={`${headerCls} bg-cyan-900/60 text-cyan-300`}>
        <span>📊</span> {data.indicatorType}
      </div>
      <div className={bodyCls}>
        <div className="text-[10px] text-white/40 font-mono">{data.indicatorId}</div>
        {Object.entries(data.params).map(([k, v]) => (
          <div key={k} className="flex items-center gap-1">
            <label className="text-[9px] text-white/50 w-12 shrink-0 capitalize">{k}</label>
            <input
              className={inputCls}
              value={v}
              onChange={(e) => {
                const n = Number(e.target.value);
                onChange(k, isNaN(n) ? e.target.value : n);
              }}
            />
          </div>
        ))}
      </div>
      <LabelledHandle type="source" position={Position.Right} id={HANDLE.OUT} label="out" />
    </div>
  );
});

/* ═══════════════════════════════════════════════════════════
   PRICE NODE
   ═══════════════════════════════════════════════════════════ */
export const PriceNode = memo(function PriceNode({ id, data }: NodeProps & { data: PriceNodeData }) {
  const { updateNodeData } = useReactFlow();
  return (
    <div className={`${baseCard} border-emerald-700/60 bg-slate-900`}>
      <div className={`${headerCls} bg-emerald-900/60 text-emerald-300`}>
        <span>💲</span> Price
      </div>
      <div className={bodyCls}>
        <select className={selectCls} value={data.source} onChange={(e) => updateNodeData(id, { source: e.target.value, label: `price.${e.target.value}` })}>
          {["open", "high", "low", "close", "volume"].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>
      <LabelledHandle type="source" position={Position.Right} id={HANDLE.OUT} label="out" />
    </div>
  );
});

/* ═══════════════════════════════════════════════════════════
   CONSTANT NODE
   ═══════════════════════════════════════════════════════════ */
export const ConstantNode = memo(function ConstantNode({ id, data }: NodeProps & { data: ConstantNodeData }) {
  const { updateNodeData } = useReactFlow();
  return (
    <div className={`${baseCard} border-gray-600/60 bg-slate-900 min-w-[100px]`}>
      <div className={`${headerCls} bg-gray-800/60 text-gray-300`}>
        <span>#</span> Value
      </div>
      <div className={bodyCls}>
        <input
          className={inputCls}
          value={data.value}
          onChange={(e) => updateNodeData(id, { value: e.target.value, label: e.target.value })}
        />
      </div>
      <LabelledHandle type="source" position={Position.Right} id={HANDLE.OUT} label="out" />
    </div>
  );
});

/* ═══════════════════════════════════════════════════════════
   CONDITION NODE
   ═══════════════════════════════════════════════════════════ */
const OPERATOR_OPTIONS = [
  { value: "crosses_above", label: "Crosses ↑" },
  { value: "crosses_below", label: "Crosses ↓" },
  { value: ">", label: ">" },
  { value: "<", label: "<" },
  { value: ">=", label: ">=" },
  { value: "<=", label: "<=" },
  { value: "==", label: "==" },
];

export const ConditionNode = memo(function ConditionNode({ id, data }: NodeProps & { data: ConditionNodeData }) {
  const { updateNodeData } = useReactFlow();
  return (
    <div className={`${baseCard} border-amber-700/60 bg-slate-900`}>
      <div className={`${headerCls} bg-amber-900/60 text-amber-300`}>
        <span>⚖️</span> Condition
      </div>
      <div className="relative">
        <LabelledHandle type="target" position={Position.Left} id={HANDLE.LEFT} label="left" className="py-1" />
        <div className={bodyCls}>
          <select className={selectCls} value={data.operator} onChange={(e) => updateNodeData(id, { operator: e.target.value })}>
            {OPERATOR_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
        <LabelledHandle type="target" position={Position.Left} id={HANDLE.RIGHT} label="right" className="py-1" />
      </div>
      <LabelledHandle type="source" position={Position.Right} id={HANDLE.OUT} label="bool" />
    </div>
  );
});

/* ═══════════════════════════════════════════════════════════
   LOGIC GATE NODE
   ═══════════════════════════════════════════════════════════ */
export const LogicGateNode = memo(function LogicGateNode({ id, data }: NodeProps & { data: LogicGateNodeData }) {
  const { updateNodeData } = useReactFlow();
  return (
    <div className={`${baseCard} border-violet-700/60 bg-slate-900 min-w-[100px]`}>
      <div className={`${headerCls} bg-violet-900/60 text-violet-300`}>
        <span>🔗</span> Gate
      </div>
      <div className="relative">
        <LabelledHandle type="target" position={Position.Left} id={`${HANDLE.GATE_IN}-0`} label="A" className="py-1" />
        <div className={bodyCls}>
          <select className={selectCls} value={data.gateType} onChange={(e) => updateNodeData(id, { gateType: e.target.value, label: e.target.value })}>
            {(["AND", "OR", "NOT"] as const).map((g) => (
              <option key={g} value={g}>{g}</option>
            ))}
          </select>
        </div>
        <LabelledHandle type="target" position={Position.Left} id={`${HANDLE.GATE_IN}-1`} label="B" className="py-1" />
      </div>
      <LabelledHandle type="source" position={Position.Right} id={HANDLE.OUT} label="out" />
    </div>
  );
});

/* ═══════════════════════════════════════════════════════════
   IF / THEN / ELSE NODE
   ═══════════════════════════════════════════════════════════ */
export const IfThenElseNode = memo(function IfThenElseNode({ data }: NodeProps & { data: IfThenElseNodeData }) {
  return (
    <div className={`${baseCard} border-pink-700/60 bg-slate-900 min-w-[130px]`}>
      <div className={`${headerCls} bg-pink-900/60 text-pink-300`}>
        <span>🔀</span> IF / THEN / ELSE
      </div>
      <div className="relative space-y-1 py-2">
        <LabelledHandle type="target" position={Position.Left} id={HANDLE.CONDITION} label="if" className="py-1" />
        <LabelledHandle type="target" position={Position.Left} id={HANDLE.THEN} label="then" className="py-1" />
        <LabelledHandle type="target" position={Position.Left} id={HANDLE.ELSE} label="else" className="py-1" />
      </div>
      <LabelledHandle type="source" position={Position.Right} id={HANDLE.OUT} label="out" />
    </div>
  );
});

/* ═══════════════════════════════════════════════════════════
   PATTERN NODE
   ═══════════════════════════════════════════════════════════ */
const PATTERN_OPTIONS = [
  "engulfing", "pin_bar", "doji", "hammer", "inverted_hammer",
  "shooting_star", "morning_star", "evening_star", "inside_bar",
  "outside_bar", "three_white_soldiers", "three_black_crows",
  "harami", "tweezer_top", "tweezer_bottom", "spinning_top",
];

export const PatternNode = memo(function PatternNode({ id, data }: NodeProps & { data: PatternNodeData }) {
  const { updateNodeData } = useReactFlow();
  return (
    <div className={`${baseCard} border-orange-700/60 bg-slate-900`}>
      <div className={`${headerCls} bg-orange-900/60 text-orange-300`}>
        <span>🕯️</span> Pattern
      </div>
      <div className={bodyCls}>
        <select className={selectCls} value={data.pattern} onChange={(e) => updateNodeData(id, { pattern: e.target.value, label: e.target.value })}>
          {PATTERN_OPTIONS.map((p) => (
            <option key={p} value={p}>{p.replace(/_/g, " ")}</option>
          ))}
        </select>
      </div>
      <LabelledHandle type="source" position={Position.Right} id={HANDLE.OUT} label="signal" />
    </div>
  );
});

/* ═══════════════════════════════════════════════════════════
   FILTER NODE
   ═══════════════════════════════════════════════════════════ */
const FILTER_OPTIONS = [
  { value: "time", label: "Time Window" },
  { value: "session", label: "Session Preset" },
  { value: "day_of_week", label: "Day of Week" },
  { value: "trend", label: "Trend Direction" },
  { value: "adx", label: "ADX Filter" },
  { value: "spread", label: "Max Spread" },
];

export const FilterNode = memo(function FilterNode({ id, data }: NodeProps & { data: FilterNodeData }) {
  const { updateNodeData } = useReactFlow();
  return (
    <div className={`${baseCard} border-sky-700/60 bg-slate-900`}>
      <div className={`${headerCls} bg-sky-900/60 text-sky-300`}>
        <span>🔒</span> Filter
      </div>
      <div className="relative">
        <LabelledHandle type="target" position={Position.Left} id={HANDLE.FILTER_IN} label="in" className="py-1" />
        <div className={bodyCls}>
          <select className={selectCls} value={data.filterType} onChange={(e) => updateNodeData(id, { filterType: e.target.value, label: e.target.value })}>
            {FILTER_OPTIONS.map((f) => (
              <option key={f.value} value={f.value}>{f.label}</option>
            ))}
          </select>
        </div>
      </div>
      <LabelledHandle type="source" position={Position.Right} id={HANDLE.OUT} label="pass" />
    </div>
  );
});

/* ═══════════════════════════════════════════════════════════
   SIGNAL NODE (Entry / Exit)
   ═══════════════════════════════════════════════════════════ */
export const SignalNode = memo(function SignalNode({ id, data }: NodeProps & { data: SignalNodeData }) {
  const { updateNodeData } = useReactFlow();
  const isEntry = data.signalType === "entry";
  const borderColor = isEntry ? "border-green-600/60" : "border-red-600/60";
  const bgColor = isEntry ? "bg-green-900/60" : "bg-red-900/60";
  const textColor = isEntry ? "text-green-300" : "text-red-300";
  const icon = isEntry ? "🟢" : "🔴";

  return (
    <div className={`${baseCard} ${borderColor} bg-slate-900 min-w-[120px]`}>
      <div className={`${headerCls} ${bgColor} ${textColor}`}>
        <span>{icon}</span> {isEntry ? "Entry" : "Exit"} Signal
      </div>
      <div className="relative">
        <LabelledHandle type="target" position={Position.Left} id={HANDLE.IN} label="trigger" className="py-1" />
        <div className={bodyCls}>
          <select className={selectCls} value={data.direction} onChange={(e) => updateNodeData(id, { direction: e.target.value })}>
            <option value="both">Both</option>
            <option value="long">Long</option>
            <option value="short">Short</option>
          </select>
        </div>
      </div>
    </div>
  );
});
