"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { Strategy, IndicatorConfig, ConditionRow } from "@/types";

/* ── Indicator catalogue with sub-keys ────────────────────── */
interface IndDef {
  value: string;
  label: string;
  defaultParams: Record<string, number | string>;
  overlay?: boolean;
  /** Sub-components that should appear in condition dropdowns */
  subKeys?: { suffix: string; label: string }[];
}

const INDICATOR_TYPES: IndDef[] = [
  { value: "SMA", label: "SMA (Simple Moving Average)", defaultParams: { period: 20, source: "close" } },
  { value: "EMA", label: "EMA (Exponential Moving Average)", defaultParams: { period: 20, source: "close" } },
  { value: "RSI", label: "RSI (Relative Strength Index)", defaultParams: { period: 14, source: "close" }, overlay: false },
  {
    value: "MACD", label: "MACD", defaultParams: { fast: 12, slow: 26, signal: 9, source: "close" }, overlay: false,
    subKeys: [{ suffix: "_signal", label: "Signal" }, { suffix: "_hist", label: "Histogram" }],
  },
  {
    value: "Bollinger", label: "Bollinger Bands", defaultParams: { period: 20, std_dev: 2, source: "close" },
    subKeys: [{ suffix: "_upper", label: "Upper" }, { suffix: "_lower", label: "Lower" }],
  },
  { value: "ATR", label: "ATR (Average True Range)", defaultParams: { period: 14 }, overlay: false },
  {
    value: "Stochastic", label: "Stochastic", defaultParams: { k_period: 14, d_period: 3, smooth: 3 }, overlay: false,
    subKeys: [{ suffix: "_d", label: "%D" }],
  },
  { value: "ADX", label: "ADX (Avg Directional Index)", defaultParams: { period: 14 }, overlay: false },
  { value: "VWAP", label: "VWAP (Volume-Weighted Avg Price)", defaultParams: {} },
  { value: "ADR", label: "ADR (Average Daily Range)", defaultParams: { period: 10 }, overlay: false },
  {
    value: "Pivot", label: "Pivot Points (Daily)", defaultParams: { type: "standard" },
    subKeys: [
      { suffix: "_pp", label: "PP" },
      { suffix: "_r1", label: "R1" }, { suffix: "_r2", label: "R2" }, { suffix: "_r3", label: "R3" },
      { suffix: "_s1", label: "S1" }, { suffix: "_s2", label: "S2" }, { suffix: "_s3", label: "S3" },
    ],
  },
  { value: "PivotHigh", label: "Pivot High (Swing)", defaultParams: { lookback: 42 }, overlay: true },
  { value: "PivotLow", label: "Pivot Low (Swing)", defaultParams: { lookback: 42 }, overlay: true },
];

const OPERATORS = [
  { value: "crosses_above", label: "Crosses Above" },
  { value: "crosses_below", label: "Crosses Below" },
  { value: ">", label: "Greater Than" },
  { value: "<", label: "Less Than" },
  { value: ">=", label: "Greater or Equal" },
  { value: "<=", label: "Less or Equal" },
  { value: "==", label: "Equals" },
];

const PRICE_SOURCES = [
  { value: "price.open", label: "Price Open" },
  { value: "price.high", label: "Price High" },
  { value: "price.low", label: "Price Low" },
  { value: "price.close", label: "Price Close" },
];

const SL_TP_TYPES = [
  { value: "fixed_pips", label: "Fixed Pips" },
  { value: "atr_multiple", label: "ATR Multiple" },
  { value: "adr_pct", label: "ADR %" },
  { value: "percent", label: "Percentage" },
  { value: "rr_ratio", label: "Risk:Reward Ratio" },
  { value: "pivot_level", label: "Pivot Level" },
];

const DIRECTIONS = [
  { value: "both", label: "Both" },
  { value: "long", label: "Long Only" },
  { value: "short", label: "Short Only" },
];

/* ── Props ────────────────────────────────────────────────── */
interface Props {
  strategy: Strategy | null;
  onSave: () => void;
  onCancel: () => void;
}

export default function StrategyEditor({ strategy, onSave, onCancel }: Props) {
  const readOnly = Boolean(strategy?.is_system);
  const [name, setName] = useState(strategy?.name || "");
  const [description, setDescription] = useState(strategy?.description || "");
  const [indicators, setIndicators] = useState<IndicatorConfig[]>(strategy?.indicators || []);
  const [entryRules, setEntryRules] = useState<ConditionRow[]>(strategy?.entry_rules || []);
  const [exitRules, setExitRules] = useState<ConditionRow[]>(strategy?.exit_rules || []);
  const [riskParams, setRiskParams] = useState({
    position_size_type: "fixed_lot",
    position_size_value: 0.01,
    stop_loss_type: "fixed_pips",
    stop_loss_value: 50,
    take_profit_type: "fixed_pips",
    take_profit_value: 100,
    take_profit_2_type: "",
    take_profit_2_value: 0,
    lot_split: [] as number[],
    breakeven_on_tp1: false,
    trailing_stop: false,
    trailing_stop_type: "fixed_pips",
    trailing_stop_value: 0,
    max_positions: 1,
    max_drawdown_pct: 0,
    ...strategy?.risk_params,
  });
  const [filters, setFilters] = useState({
    time_start: "",
    time_end: "",
    days_of_week: [] as number[],
    min_volatility: 0,
    max_volatility: 0,
    min_adx: 0,
    max_adx: 0,
    ...strategy?.filters,
  });

  /* ── Detect dedicated strategy type (MSS / Gold BT / generic) ── */
  const strategyType: "mss" | "gold_bt" | "generic" =
    (filters as Record<string, unknown>).mss_config ? "mss"
    : (filters as Record<string, unknown>).gold_bt_config ? "gold_bt"
    : "generic";

  const mssConfig = (filters as Record<string, unknown>).mss_config as Record<string, unknown> | undefined;
  const goldConfig = (filters as Record<string, unknown>).gold_bt_config as Record<string, unknown> | undefined;

  const updateMssConfig = (key: string, val: unknown) => {
    setFilters({
      ...filters,
      mss_config: { ...(mssConfig || {}), [key]: val },
    } as typeof filters);
  };

  const updateGoldConfig = (key: string, val: unknown) => {
    setFilters({
      ...filters,
      gold_bt_config: { ...(goldConfig || {}), [key]: val },
    } as typeof filters);
  };
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<"indicators" | "entry" | "exit" | "risk" | "filters">("indicators");

  /* ── Indicator helpers ──────────────────────────────────── */
  const addIndicator = () => {
    const def = INDICATOR_TYPES[0];
    const count = indicators.filter((i) => i.type === def.value).length;
    setIndicators([
      ...indicators,
      {
        id: `${def.value.toLowerCase()}_${count + 1}`,
        type: def.value,
        params: { ...def.defaultParams },
        overlay: def.overlay !== false,
      },
    ]);
  };

  const updateIndicator = (idx: number, updates: Partial<IndicatorConfig>) => {
    setIndicators((prev) => prev.map((ind, i) => (i === idx ? { ...ind, ...updates } : ind)));
  };

  const changeIndicatorType = (idx: number, newType: string) => {
    const def = INDICATOR_TYPES.find((t) => t.value === newType);
    if (!def) return;
    const count = indicators.filter((i, j) => i.type === newType && j !== idx).length;
    updateIndicator(idx, {
      type: newType,
      id: `${newType.toLowerCase()}_${count + 1}`,
      params: { ...def.defaultParams },
      overlay: def.overlay !== false,
    });
  };

  const removeIndicator = (idx: number) => {
    setIndicators((prev) => prev.filter((_, i) => i !== idx));
  };

  /* ── Condition helpers ──────────────────────────────────── */
  const addCondition = (type: "entry" | "exit") => {
    const row: ConditionRow = { left: "price.close", operator: ">", right: "0", logic: "AND", direction: "both" };
    if (type === "entry") setEntryRules([...entryRules, row]);
    else setExitRules([...exitRules, row]);
  };

  const updateCondition = (type: "entry" | "exit", idx: number, updates: Partial<ConditionRow>) => {
    const setter = type === "entry" ? setEntryRules : setExitRules;
    setter((prev) => prev.map((r, i) => (i === idx ? { ...r, ...updates } : r)));
  };

  const removeCondition = (type: "entry" | "exit", idx: number) => {
    const setter = type === "entry" ? setEntryRules : setExitRules;
    setter((prev) => prev.filter((_, i) => i !== idx));
  };

  /* ── Source options with sub-keys ───────────────────────── */
  const sourceOptions = [
    ...PRICE_SOURCES,
    ...indicators.flatMap((ind) => {
      const def = INDICATOR_TYPES.find((t) => t.value === ind.type);
      const main = { value: ind.id, label: `${ind.type} (${ind.id})` };
      if (!def?.subKeys) return [main];
      return [
        main,
        ...def.subKeys.map((sk) => ({
          value: `${ind.id}${sk.suffix}`,
          label: `${ind.type} ${sk.label} (${ind.id}${sk.suffix})`,
        })),
      ];
    }),
  ];

  /* ── Save ───────────────────────────────────────────────── */
  const handleSave = async () => {
    if (!name.trim()) {
      setError("Strategy name is required");
      return;
    }
    setError("");
    setSaving(true);
    try {
      const payload = {
        name: name.trim(),
        description: description.trim(),
        indicators: indicators as unknown as Record<string, unknown>[],
        entry_rules: entryRules as unknown as Record<string, unknown>[],
        exit_rules: exitRules as unknown as Record<string, unknown>[],
        risk_params: riskParams,
        filters,
      };
      if (strategy) {
        await api.put(`/api/strategies/${strategy.id}`, payload);
      } else {
        await api.post("/api/strategies", payload);
      }
      onSave();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  /* ── Shared CSS classes ─────────────────────────────────── */
  const inputCls = "w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-accent";
  const selectCls = inputCls;
  const miniInputCls = "w-20 rounded border border-card-border bg-card-bg px-2 py-1 text-xs text-foreground outline-none focus:border-accent";
  const labelCls = "block text-xs font-medium text-foreground";
  const sectionTitle = "text-xs font-semibold text-accent uppercase tracking-wide";

  /* ── Tab config ─────────────────────────────────────────── */
  const tabs = [
    { key: "indicators" as const, label: "Indicators", count: indicators.length },
    { key: "entry" as const, label: "Entry Rules", count: entryRules.length },
    { key: "exit" as const, label: "Exit Rules", count: exitRules.length },
    { key: "risk" as const, label: "Risk Mgmt", count: null },
    { key: "filters" as const, label: "Filters", count: null },
  ];

  /* ── Render condition row ───────────────────────────────── */
  const renderConditionRow = (type: "entry" | "exit", rule: ConditionRow, idx: number) => (
    <div key={idx} className="rounded-lg border border-card-border bg-background p-3 space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        {idx > 0 ? (
          <select
            value={rule.logic}
            onChange={(e) => updateCondition(type, idx, { logic: e.target.value })}
            className="rounded border border-card-border bg-card-bg px-2 py-1 text-xs text-accent font-medium outline-none w-16"
          >
            <option value="AND">AND</option>
            <option value="OR">OR</option>
          </select>
        ) : (
          <span className="text-xs text-muted w-16">When</span>
        )}
        <select
          value={rule.left}
          onChange={(e) => updateCondition(type, idx, { left: e.target.value })}
          className="flex-1 min-w-[140px] rounded border border-card-border bg-card-bg px-2 py-1.5 text-sm text-foreground outline-none focus:border-accent"
        >
          {sourceOptions.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <select
          value={rule.operator}
          onChange={(e) => updateCondition(type, idx, { operator: e.target.value })}
          className="rounded border border-card-border bg-card-bg px-2 py-1.5 text-sm text-foreground outline-none focus:border-accent"
        >
          {OPERATORS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <select
          value={sourceOptions.some((o) => o.value === rule.right) ? rule.right : "__custom__"}
          onChange={(e) => {
            if (e.target.value !== "__custom__") updateCondition(type, idx, { right: e.target.value });
          }}
          className="flex-1 min-w-[140px] rounded border border-card-border bg-card-bg px-2 py-1.5 text-sm text-foreground outline-none focus:border-accent"
        >
          {sourceOptions.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
          <option value="__custom__">Custom Value</option>
        </select>
        {!sourceOptions.some((o) => o.value === rule.right) && (
          <input
            value={rule.right}
            onChange={(e) => updateCondition(type, idx, { right: e.target.value })}
            placeholder="value"
            className={miniInputCls}
          />
        )}
        <button onClick={() => removeCondition(type, idx)} className="text-xs text-muted hover:text-danger transition-colors px-1">
          ✕
        </button>
      </div>
      {/* Direction selector */}
      {type === "entry" && (
        <div className="flex items-center gap-2 pl-16">
          <span className="text-xs text-muted">Direction:</span>
          {DIRECTIONS.map((d) => (
            <button
              key={d.value}
              onClick={() => updateCondition(type, idx, { direction: d.value })}
              className={`rounded px-2 py-0.5 text-xs font-medium transition-colors ${
                (rule.direction || "both") === d.value
                  ? d.value === "long" ? "bg-success/20 text-success" : d.value === "short" ? "bg-danger/20 text-danger" : "bg-accent/20 text-accent"
                  : "text-muted hover:text-foreground"
              }`}
            >
              {d.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={onCancel} className="text-muted hover:text-foreground transition-colors text-sm">
            ← Back
          </button>
          <h2 className="text-xl font-semibold">
            {readOnly ? "View Strategy" : strategy ? "Edit Strategy" : "New Strategy"}
          </h2>
          {readOnly && (
            <span className="inline-flex items-center rounded-full bg-accent/15 text-accent px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ml-2">
              System &bull; Read Only
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={onCancel} className="rounded-lg border border-card-border px-4 py-2 text-sm text-muted hover:text-foreground transition-colors">
            {readOnly ? "Back" : "Cancel"}
          </button>
          {!readOnly && (
            <button
              onClick={handleSave}
              disabled={saving}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-black hover:bg-accent/90 transition-colors disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save Strategy"}
            </button>
          )}
        </div>
      </div>

      {error && <p className="text-sm text-danger">{error}</p>}

      {/* Name & Description */}
      <div className="rounded-xl border border-card-border bg-card-bg p-5 space-y-4">
        <div>
          <label className="block text-xs text-muted mb-1">Strategy Name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. VWAP + MACD Breakout Scalper"
            className={inputCls}
          />
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">Description</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Brief description of the strategy logic..."
            rows={2}
            className={`${inputCls} resize-none`}
          />
        </div>
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-1 rounded-xl border border-card-border bg-card-bg p-1">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`flex-1 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
              activeTab === tab.key ? "bg-accent text-black" : "text-muted hover:text-foreground"
            }`}
          >
            {tab.label}
            {tab.count !== null && (
              <span className={`ml-1.5 text-xs ${activeTab === tab.key ? "text-black/60" : "text-muted"}`}>
                ({tab.count})
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="rounded-xl border border-card-border bg-card-bg p-5">
        {/* ═══ INDICATORS TAB ═══ */}
        {activeTab === "indicators" && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted">Configure technical indicators used by entry/exit rules.</p>
              <button onClick={addIndicator} className="rounded-lg bg-accent/10 text-accent px-3 py-1.5 text-xs font-medium hover:bg-accent/20 transition-colors">
                + Add Indicator
              </button>
            </div>
            {indicators.length === 0 && (
              <p className="text-center text-sm text-muted py-8">No indicators added. Click &quot;Add Indicator&quot; to start.</p>
            )}
            {indicators.map((ind, idx) => {
              const def = INDICATOR_TYPES.find((t) => t.value === ind.type);
              return (
                <div key={idx} className="rounded-lg border border-card-border bg-background p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <select
                        value={ind.type}
                        onChange={(e) => changeIndicatorType(idx, e.target.value)}
                        className="rounded-lg border border-card-border bg-card-bg px-3 py-1.5 text-sm text-foreground outline-none focus:border-accent"
                      >
                        {INDICATOR_TYPES.map((t) => (
                          <option key={t.value} value={t.value}>{t.label}</option>
                        ))}
                      </select>
                      <span className="text-xs text-muted">ID: <code className="text-accent">{ind.id}</code></span>
                    </div>
                    <button onClick={() => removeIndicator(idx)} className="text-xs text-muted hover:text-danger transition-colors">
                      Remove
                    </button>
                  </div>
                  {/* Parameter fields */}
                  <div className="flex flex-wrap gap-3">
                    {Object.entries(ind.params).map(([key, val]) => (
                      <div key={key} className="flex items-center gap-2">
                        <label className="text-xs text-muted capitalize">{key}:</label>
                        <input
                          value={val}
                          onChange={(e) => {
                            const v = isNaN(Number(e.target.value)) ? e.target.value : Number(e.target.value);
                            updateIndicator(idx, { params: { ...ind.params, [key]: v } });
                          }}
                          className={miniInputCls}
                        />
                      </div>
                    ))}
                  </div>
                  {/* Show sub-keys info */}
                  {def?.subKeys && (
                    <div className="text-xs text-muted">
                      <span className="text-foreground/60">Available sub-keys: </span>
                      {def.subKeys.map((sk) => (
                        <code key={sk.suffix} className="text-accent/70 mr-2">{ind.id}{sk.suffix}</code>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* ═══ ENTRY RULES TAB ═══ */}
        {activeTab === "entry" && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted">Define conditions to open a trade. Each rule can target long, short, or both directions.</p>
              <button onClick={() => addCondition("entry")} className="rounded-lg bg-success/10 text-success px-3 py-1.5 text-xs font-medium hover:bg-success/20 transition-colors">
                + Add Entry Rule
              </button>
            </div>
            {entryRules.length === 0 && (
              <p className="text-center text-sm text-muted py-8">No entry rules. Add conditions that must be true to open a position.</p>
            )}
            {entryRules.map((rule, idx) => renderConditionRow("entry", rule, idx))}
          </div>
        )}

        {/* ═══ EXIT RULES TAB ═══ */}
        {activeTab === "exit" && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted">Define conditions to close a trade (EXIT signal). SL/TP are configured in Risk tab.</p>
              <button onClick={() => addCondition("exit")} className="rounded-lg bg-danger/10 text-danger px-3 py-1.5 text-xs font-medium hover:bg-danger/20 transition-colors">
                + Add Exit Rule
              </button>
            </div>
            {exitRules.length === 0 && (
              <p className="text-center text-sm text-muted py-8">No exit rules. Add conditions that trigger closing a position.</p>
            )}
            {exitRules.map((rule, idx) => renderConditionRow("exit", rule, idx))}
          </div>
        )}

        {/* ═══ RISK MANAGEMENT TAB ═══ */}
        {activeTab === "risk" && (
          <div className="space-y-6">
            {/* ── MSS Strategy Params ── */}
            {strategyType === "mss" && mssConfig && (
              <>
                <div className="rounded-lg border border-accent/30 bg-accent/5 px-4 py-2.5">
                  <p className="text-xs text-accent font-medium">MSS (Market Structure Shift) Strategy</p>
                  <p className="text-xs text-muted mt-0.5">These parameters directly control backtest behavior. Values are percentages of ADR10.</p>
                </div>

                {/* MSS Core Params */}
                <div>
                  <p className={sectionTitle}>Structure Detection</p>
                  <div className="grid grid-cols-2 gap-4 mt-3">
                    <div className="space-y-2">
                      <label className={labelCls}>Swing Lookback (bars)</label>
                      <input
                        type="number" min="5" max="200" step="1"
                        value={Number(mssConfig.swing_lb ?? 42)}
                        onChange={(e) => updateMssConfig("swing_lb", Number(e.target.value))}
                        className={inputCls}
                      />
                      <p className="text-xs text-muted">Bars to look back for swing high/low pivots</p>
                    </div>
                    <div className="space-y-2">
                      <label className={labelCls}>Confirmation Mode</label>
                      <select
                        value={String(mssConfig.confirm ?? "close")}
                        onChange={(e) => updateMssConfig("confirm", e.target.value)}
                        className={selectCls}
                      >
                        <option value="close">Close-based (conservative)</option>
                        <option value="wick">Wick-based (aggressive)</option>
                      </select>
                    </div>
                  </div>
                </div>

                {/* MSS SL/TP */}
                <div>
                  <p className={sectionTitle}>Stop Loss & Take Profit (% of ADR10)</p>
                  <div className="grid grid-cols-3 gap-4 mt-3">
                    <div className="space-y-2">
                      <label className={labelCls}>SL % of ADR</label>
                      <input
                        type="number" step="0.5" min="1" max="100"
                        value={Number(mssConfig.sl_pct ?? 25)}
                        onChange={(e) => updateMssConfig("sl_pct", Number(e.target.value))}
                        className={inputCls}
                      />
                    </div>
                    <div className="space-y-2">
                      <label className={labelCls}>TP1 % of ADR</label>
                      <input
                        type="number" step="0.5" min="1" max="100"
                        value={Number(mssConfig.tp1_pct ?? 15)}
                        onChange={(e) => updateMssConfig("tp1_pct", Number(e.target.value))}
                        className={inputCls}
                      />
                    </div>
                    <div className="space-y-2">
                      <label className={labelCls}>TP2 % of ADR</label>
                      <input
                        type="number" step="0.5" min="1" max="100"
                        value={Number(mssConfig.tp2_pct ?? 25)}
                        onChange={(e) => updateMssConfig("tp2_pct", Number(e.target.value))}
                        className={inputCls}
                      />
                    </div>
                  </div>
                </div>

                {/* MSS Pullback */}
                <div>
                  <p className={sectionTitle}>Pullback Entry</p>
                  <div className="mt-3 space-y-3">
                    <label className="flex items-center gap-2 text-xs font-medium text-foreground">
                      <input
                        type="checkbox"
                        checked={Boolean(mssConfig.use_pullback ?? true)}
                        onChange={(e) => updateMssConfig("use_pullback", e.target.checked)}
                        className="rounded accent-accent"
                      />
                      Wait for pullback before entry
                    </label>
                    {Boolean(mssConfig.use_pullback ?? true) && (
                      <div className="w-1/2 space-y-2">
                        <label className={labelCls}>Pullback Ratio (Fibonacci)</label>
                        <input
                          type="number" step="0.01" min="0.05" max="1.0"
                          value={Number(mssConfig.pb_pct ?? 0.382)}
                          onChange={(e) => updateMssConfig("pb_pct", Number(e.target.value))}
                          className={inputCls}
                        />
                        <p className="text-xs text-muted">0.382 = 38.2% retracement, 0.5 = 50%, 0.618 = 61.8%</p>
                      </div>
                    )}
                  </div>
                </div>
              </>
            )}

            {/* ── Gold BT Strategy Params ── */}
            {strategyType === "gold_bt" && goldConfig && (
              <>
                <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/5 px-4 py-2.5">
                  <p className="text-xs text-yellow-400 font-medium">Gold Breakout Trader Strategy</p>
                  <p className="text-xs text-muted mt-0.5">These parameters directly control backtest behavior.</p>
                </div>

                {/* Gold BT Box & Trigger */}
                <div>
                  <p className={sectionTitle}>Box Configuration</p>
                  <div className="grid grid-cols-2 gap-4 mt-3">
                    <div className="space-y-2">
                      <label className={labelCls}>Box Height ($)</label>
                      <input
                        type="number" step="0.5" min="1"
                        value={Number(goldConfig.box_height ?? 10)}
                        onChange={(e) => updateGoldConfig("box_height", Number(e.target.value))}
                        className={inputCls}
                      />
                    </div>
                    <div className="space-y-2">
                      <label className={labelCls}>Trigger Interval (hours)</label>
                      <input
                        type="number" step="0.5" min="0.5"
                        value={Number(goldConfig.trigger_interval_hours ?? 2)}
                        onChange={(e) => updateGoldConfig("trigger_interval_hours", Number(e.target.value))}
                        className={inputCls}
                      />
                    </div>
                  </div>
                </div>

                {/* Gold BT Risk */}
                <div>
                  <p className={sectionTitle}>Stop Loss & Take Profit</p>
                  <div className="grid grid-cols-2 gap-4 mt-3">
                    <div className="space-y-2">
                      <label className={labelCls}>SL Type</label>
                      <select
                        value={String(goldConfig.sl_type ?? "opposite_stop")}
                        onChange={(e) => updateGoldConfig("sl_type", e.target.value)}
                        className={selectCls}
                      >
                        <option value="opposite_stop">Opposite Stop Line</option>
                        <option value="fixed_usd">Fixed USD Amount</option>
                      </select>
                    </div>
                    <div className="space-y-2">
                      <label className={labelCls}>SL Fixed USD (if fixed)</label>
                      <input
                        type="number" step="0.5" min="1"
                        value={Number(goldConfig.sl_fixed_usd ?? 14)}
                        onChange={(e) => updateGoldConfig("sl_fixed_usd", Number(e.target.value))}
                        className={inputCls}
                      />
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-4 mt-4">
                    <div className="space-y-2">
                      <label className={labelCls}>Stop Line Buffer ($)</label>
                      <input
                        type="number" step="0.5" min="0"
                        value={Number(goldConfig.stop_line_buffer ?? 2)}
                        onChange={(e) => updateGoldConfig("stop_line_buffer", Number(e.target.value))}
                        className={inputCls}
                      />
                    </div>
                    <div className="space-y-2">
                      <label className={labelCls}>Stop-to-TP Gap ($)</label>
                      <input
                        type="number" step="0.5" min="0"
                        value={Number(goldConfig.stop_to_tp_gap ?? 2)}
                        onChange={(e) => updateGoldConfig("stop_to_tp_gap", Number(e.target.value))}
                        className={inputCls}
                      />
                    </div>
                  </div>
                </div>

                {/* Gold BT TP Zones */}
                <div>
                  <p className={sectionTitle}>Take Profit Zones</p>
                  <div className="grid grid-cols-3 gap-4 mt-3">
                    <div className="space-y-2">
                      <label className={labelCls}>TP Zone Gap ($)</label>
                      <input
                        type="number" step="0.5" min="0"
                        value={Number(goldConfig.tp_zone_gap ?? 1)}
                        onChange={(e) => updateGoldConfig("tp_zone_gap", Number(e.target.value))}
                        className={inputCls}
                      />
                    </div>
                    <div className="space-y-2">
                      <label className={labelCls}>TP1 Height ($)</label>
                      <input
                        type="number" step="0.5" min="0.5"
                        value={Number(goldConfig.tp1_height ?? 4)}
                        onChange={(e) => updateGoldConfig("tp1_height", Number(e.target.value))}
                        className={inputCls}
                      />
                    </div>
                    <div className="space-y-2">
                      <label className={labelCls}>TP2 Height ($)</label>
                      <input
                        type="number" step="0.5" min="0.5"
                        value={Number(goldConfig.tp2_height ?? 4)}
                        onChange={(e) => updateGoldConfig("tp2_height", Number(e.target.value))}
                        className={inputCls}
                      />
                    </div>
                  </div>
                </div>
              </>
            )}

            {/* ── Generic Strategy Risk Params ── */}
            {strategyType === "generic" && (
              <>
                {/* Position Sizing */}
                <div>
                  <p className={sectionTitle}>Position Sizing</p>
                  <div className="grid grid-cols-2 gap-4 mt-3">
                    <div className="space-y-2">
                      <label className={labelCls}>Size Type</label>
                      <select
                        value={riskParams.position_size_type}
                        onChange={(e) => setRiskParams({ ...riskParams, position_size_type: e.target.value })}
                        className={selectCls}
                      >
                        <option value="fixed_lot">Fixed Lot Size</option>
                        <option value="percent_risk">% Risk per Trade</option>
                        <option value="percent_equity">% of Equity</option>
                      </select>
                    </div>
                    <div className="space-y-2">
                      <label className={labelCls}>
                        {riskParams.position_size_type === "fixed_lot" ? "Lot Size" : riskParams.position_size_type === "percent_risk" ? "Risk %" : "Equity %"}
                      </label>
                      <input
                        type="number" step="0.01"
                        value={riskParams.position_size_value}
                        onChange={(e) => setRiskParams({ ...riskParams, position_size_value: Number(e.target.value) })}
                        className={inputCls}
                      />
                    </div>
                  </div>
                </div>

                {/* Stop Loss */}
                <div>
                  <p className={sectionTitle}>Stop Loss</p>
                  <div className="grid grid-cols-2 gap-4 mt-3">
                    <div className="space-y-2">
                      <label className={labelCls}>SL Type</label>
                      <select
                        value={riskParams.stop_loss_type}
                        onChange={(e) => setRiskParams({ ...riskParams, stop_loss_type: e.target.value })}
                        className={selectCls}
                      >
                        {SL_TP_TYPES.filter((t) => t.value !== "rr_ratio").map((t) => (
                          <option key={t.value} value={t.value}>{t.label}</option>
                        ))}
                        <option value="swing">Swing High/Low</option>
                      </select>
                    </div>
                    <div className="space-y-2">
                      <label className={labelCls}>SL Value</label>
                      <input
                        type="number" step="0.1"
                        value={riskParams.stop_loss_value}
                        onChange={(e) => setRiskParams({ ...riskParams, stop_loss_value: Number(e.target.value) })}
                        className={inputCls}
                      />
                    </div>
                  </div>
                </div>

                {/* Take Profit 1 */}
                <div>
                  <p className={sectionTitle}>Take Profit 1</p>
                  <div className="grid grid-cols-2 gap-4 mt-3">
                    <div className="space-y-2">
                      <label className={labelCls}>TP Type</label>
                      <select
                        value={riskParams.take_profit_type}
                        onChange={(e) => setRiskParams({ ...riskParams, take_profit_type: e.target.value })}
                        className={selectCls}
                      >
                        {SL_TP_TYPES.map((t) => (
                          <option key={t.value} value={t.value}>{t.label}</option>
                        ))}
                      </select>
                    </div>
                    <div className="space-y-2">
                      <label className={labelCls}>TP Value</label>
                      <input
                        type="number" step="0.1"
                        value={riskParams.take_profit_value}
                        onChange={(e) => setRiskParams({ ...riskParams, take_profit_value: Number(e.target.value) })}
                        className={inputCls}
                      />
                    </div>
                  </div>
                </div>

                {/* Take Profit 2 + Lot Split */}
                <div>
                  <p className={sectionTitle}>Take Profit 2 (Optional)</p>
                  <p className="text-xs text-muted mt-1 mb-3">Enable a second take-profit level with lot splitting.</p>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <label className={labelCls}>TP2 Type</label>
                      <select
                        value={riskParams.take_profit_2_type}
                        onChange={(e) => {
                          const tp2Type = e.target.value;
                          const updates: Record<string, unknown> = { take_profit_2_type: tp2Type };
                          if (tp2Type && (!riskParams.lot_split || riskParams.lot_split.length !== 2)) {
                            updates.lot_split = [0.6, 0.4];
                          }
                          if (!tp2Type) {
                            updates.lot_split = [];
                            updates.take_profit_2_value = 0;
                            updates.breakeven_on_tp1 = false;
                          }
                          setRiskParams({ ...riskParams, ...updates } as typeof riskParams);
                        }}
                        className={selectCls}
                      >
                        <option value="">Disabled</option>
                        {SL_TP_TYPES.map((t) => (
                          <option key={t.value} value={t.value}>{t.label}</option>
                        ))}
                      </select>
                    </div>
                    {riskParams.take_profit_2_type && (
                      <div className="space-y-2">
                        <label className={labelCls}>TP2 Value</label>
                        <input
                          type="number" step="0.1"
                          value={riskParams.take_profit_2_value}
                          onChange={(e) => setRiskParams({ ...riskParams, take_profit_2_value: Number(e.target.value) })}
                          className={inputCls}
                        />
                      </div>
                    )}
                  </div>
                  {riskParams.take_profit_2_type && (
                    <div className="mt-4 space-y-4">
                      {/* Lot Split */}
                      <div className="space-y-2">
                        <label className={labelCls}>
                          Lot Split (TP1: {Math.round((riskParams.lot_split?.[0] ?? 0.6) * 100)}% / TP2: {Math.round((riskParams.lot_split?.[1] ?? 0.4) * 100)}%)
                        </label>
                        <input
                          type="range" min="10" max="90" step="5"
                          value={Math.round((riskParams.lot_split?.[0] ?? 0.6) * 100)}
                          onChange={(e) => {
                            const pct = Number(e.target.value) / 100;
                            setRiskParams({ ...riskParams, lot_split: [pct, Math.round((1 - pct) * 100) / 100] });
                          }}
                          className="w-full accent-accent"
                        />
                        <div className="flex justify-between text-xs text-muted">
                          <span>10% TP1</span>
                          <span>90% TP1</span>
                        </div>
                      </div>
                      {/* Breakeven on TP1 */}
                      <label className="flex items-center gap-2 text-xs font-medium text-foreground">
                        <input
                          type="checkbox"
                          checked={riskParams.breakeven_on_tp1}
                          onChange={(e) => setRiskParams({ ...riskParams, breakeven_on_tp1: e.target.checked })}
                          className="rounded accent-accent"
                        />
                        Move SL to breakeven when TP1 is hit
                      </label>
                    </div>
                  )}
                </div>

                {/* Trailing Stop */}
                <div>
                  <p className={sectionTitle}>Trailing Stop</p>
                  <div className="mt-3 space-y-3">
                    <label className="flex items-center gap-2 text-xs font-medium text-foreground">
                      <input
                        type="checkbox"
                        checked={riskParams.trailing_stop}
                        onChange={(e) => setRiskParams({ ...riskParams, trailing_stop: e.target.checked })}
                        className="rounded accent-accent"
                      />
                      Enable Trailing Stop
                    </label>
                    {riskParams.trailing_stop && (
                      <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-2">
                          <label className={labelCls}>Trail Type</label>
                          <select
                            value={riskParams.trailing_stop_type}
                            onChange={(e) => setRiskParams({ ...riskParams, trailing_stop_type: e.target.value })}
                            className={selectCls}
                          >
                            <option value="fixed_pips">Fixed Pips</option>
                            <option value="atr_multiple">ATR Multiple</option>
                          </select>
                        </div>
                        <div className="space-y-2">
                          <label className={labelCls}>Trail Distance</label>
                          <input
                            type="number" step="0.1"
                            value={riskParams.trailing_stop_value}
                            onChange={(e) => setRiskParams({ ...riskParams, trailing_stop_value: Number(e.target.value) })}
                            className={inputCls}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </>
            )}

            {/* Risk Limits (shared across all strategy types) */}
            <div>
              <p className={sectionTitle}>Risk Limits</p>
              <div className="grid grid-cols-2 gap-4 mt-3">
                <div className="space-y-2">
                  <label className={labelCls}>Max Concurrent Positions</label>
                  <input
                    type="number" min="1"
                    value={riskParams.max_positions}
                    onChange={(e) => setRiskParams({ ...riskParams, max_positions: Number(e.target.value) })}
                    className={inputCls}
                  />
                </div>
                <div className="space-y-2">
                  <label className={labelCls}>Max Drawdown % (0 = off)</label>
                  <input
                    type="number" step="0.5" min="0"
                    value={riskParams.max_drawdown_pct}
                    onChange={(e) => setRiskParams({ ...riskParams, max_drawdown_pct: Number(e.target.value) })}
                    className={inputCls}
                  />
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ═══ FILTERS TAB ═══ */}
        {activeTab === "filters" && (
          <div className="space-y-6">
            {/* Time of Day */}
            <div>
              <p className={sectionTitle}>Trading Session</p>
              <div className="grid grid-cols-2 gap-4 mt-3">
                <div className="space-y-2">
                  <label className={labelCls}>Start Time (UTC)</label>
                  <input
                    type="time"
                    value={filters.time_start}
                    onChange={(e) => setFilters({ ...filters, time_start: e.target.value })}
                    className={inputCls}
                  />
                </div>
                <div className="space-y-2">
                  <label className={labelCls}>End Time (UTC)</label>
                  <input
                    type="time"
                    value={filters.time_end}
                    onChange={(e) => setFilters({ ...filters, time_end: e.target.value })}
                    className={inputCls}
                  />
                </div>
              </div>
            </div>

            {/* Trading Days */}
            <div>
              <p className={sectionTitle}>Trading Days</p>
              <div className="flex gap-2 mt-3">
                {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day, i) => (
                  <button
                    key={day}
                    onClick={() => {
                      const days = filters.days_of_week || [];
                      setFilters({
                        ...filters,
                        days_of_week: days.includes(i) ? days.filter((d: number) => d !== i) : [...days, i],
                      });
                    }}
                    className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                      (filters.days_of_week || []).includes(i)
                        ? "bg-accent text-black"
                        : "border border-card-border text-muted hover:text-foreground"
                    }`}
                  >
                    {day}
                  </button>
                ))}
              </div>
              <p className="text-xs text-muted mt-1">Leave empty to trade all days</p>
            </div>

            {/* ADX Trend Filter */}
            <div>
              <p className={sectionTitle}>ADX Trend Filter</p>
              <p className="text-xs text-muted mt-1 mb-3">Only take trades when ADX is within a range. Requires ADX indicator.</p>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className={labelCls}>Min ADX (0 = off)</label>
                  <input
                    type="number" step="1" min="0"
                    value={filters.min_adx}
                    onChange={(e) => setFilters({ ...filters, min_adx: Number(e.target.value) })}
                    placeholder="e.g. 20 (trending)"
                    className={inputCls}
                  />
                </div>
                <div className="space-y-2">
                  <label className={labelCls}>Max ADX (0 = off)</label>
                  <input
                    type="number" step="1" min="0"
                    value={filters.max_adx}
                    onChange={(e) => setFilters({ ...filters, max_adx: Number(e.target.value) })}
                    placeholder="e.g. 50 (not too strong)"
                    className={inputCls}
                  />
                </div>
              </div>
            </div>

            {/* Volatility Filter */}
            <div>
              <p className={sectionTitle}>Volatility Filter</p>
              <p className="text-xs text-muted mt-1 mb-3">Set min/max volatility thresholds. Requires ATR or ADR indicator.</p>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className={labelCls}>Min Volatility (0 = off)</label>
                  <input
                    type="number" step="0.1" min="0"
                    value={filters.min_volatility}
                    onChange={(e) => setFilters({ ...filters, min_volatility: Number(e.target.value) })}
                    className={inputCls}
                  />
                </div>
                <div className="space-y-2">
                  <label className={labelCls}>Max Volatility (0 = off)</label>
                  <input
                    type="number" step="0.1" min="0"
                    value={filters.max_volatility}
                    onChange={(e) => setFilters({ ...filters, max_volatility: Number(e.target.value) })}
                    className={inputCls}
                  />
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Strategy Summary */}
      <div className="rounded-xl border border-card-border bg-card-bg p-4">
        <h4 className="text-xs font-medium text-muted mb-2">Strategy Summary</h4>
        <div className="flex flex-wrap gap-4 text-sm">
          <span className="text-foreground">
            <span className="text-muted">Name:</span> {name || "\u2014"}
          </span>
          <span className="text-accent">
            {indicators.length} indicators
          </span>
          <span className="text-success">
            {entryRules.length} entry rules
          </span>
          <span className="text-danger">
            {exitRules.length} exit rules
          </span>
          <span className="text-foreground">
            <span className="text-muted">SL:</span> {riskParams.stop_loss_value} {riskParams.stop_loss_type}
          </span>
          <span className="text-foreground">
            <span className="text-muted">TP:</span> {riskParams.take_profit_value} {riskParams.take_profit_type}
          </span>
          {riskParams.take_profit_2_type && (
            <span className="text-foreground">
              <span className="text-muted">TP2:</span> {riskParams.take_profit_2_value} {riskParams.take_profit_2_type}
            </span>
          )}
          {riskParams.trailing_stop && (
            <span className="text-foreground">
              <span className="text-muted">Trail:</span> {riskParams.trailing_stop_value} {riskParams.trailing_stop_type}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
