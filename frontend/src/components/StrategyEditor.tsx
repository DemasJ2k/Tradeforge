"use client";

import { useState, lazy, Suspense } from "react";
import { api } from "@/lib/api";
import type { Strategy, IndicatorConfig, ConditionRow } from "@/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Accordion, AccordionItem, AccordionTrigger, AccordionContent } from "@/components/ui/accordion";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { cn } from "@/lib/utils";
import { ArrowLeft, Plus, X, Loader2, Lock, Activity, LogIn, LogOut, Shield, Filter, Search, ChevronsUpDown, Check, TrendingUp, BarChart3, Crosshair, Zap, Calendar, SlidersHorizontal, LayoutGrid, FileText } from "lucide-react";

/* ── Lazy-load visual editor (heavy dep: React Flow) ────── */
const VisualEditor = lazy(() => import("@/components/visual-editor/VisualEditor"));

/* ── Indicator catalogue with sub-keys ────────────────────── */
interface IndDef {
  value: string;
  label: string;
  defaultParams: Record<string, number | string>;
  overlay?: boolean;
  /** Sub-components that should appear in condition dropdowns */
  subKeys?: { suffix: string; label: string }[];
  /** Category for grouped display */
  category?: string;
}

const INDICATOR_TYPES: IndDef[] = [
  // ── Trend ──────────────────────────────────────────────────
  { value: "SMA", label: "SMA (Simple Moving Average)", defaultParams: { period: 20, source: "close" }, category: "Trend" },
  { value: "EMA", label: "EMA (Exponential Moving Average)", defaultParams: { period: 20, source: "close" }, category: "Trend" },
  { value: "DEMA", label: "DEMA (Double EMA)", defaultParams: { period: 20, source: "close" }, category: "Trend" },
  { value: "TEMA", label: "TEMA (Triple EMA)", defaultParams: { period: 20, source: "close" }, category: "Trend" },
  { value: "ZLEMA", label: "ZLEMA (Zero-Lag EMA)", defaultParams: { period: 20, source: "close" }, category: "Trend" },
  { value: "HULL_MA", label: "Hull Moving Average", defaultParams: { period: 20, source: "close" }, category: "Trend" },
  {
    value: "ICHIMOKU", label: "Ichimoku Cloud", defaultParams: { tenkan: 9, kijun: 26, senkou_b: 52, displacement: 26 }, category: "Trend",
    subKeys: [
      { suffix: "_kijun", label: "Kijun" },
      { suffix: "_senkou_a", label: "Senkou A" },
      { suffix: "_senkou_b", label: "Senkou B" },
      { suffix: "_chikou", label: "Chikou" },
    ],
  },
  {
    value: "SUPERTREND", label: "Supertrend", defaultParams: { period: 10, multiplier: 3.0 }, category: "Trend",
    subKeys: [{ suffix: "_dir", label: "Direction" }],
  },
  {
    value: "DONCHIAN", label: "Donchian Channel", defaultParams: { period: 20 }, category: "Trend",
    subKeys: [{ suffix: "_upper", label: "Upper" }, { suffix: "_lower", label: "Lower" }],
  },
  {
    value: "KELTNER", label: "Keltner Channel", defaultParams: { ema_period: 20, atr_period: 10, multiplier: 2 }, category: "Trend",
    subKeys: [{ suffix: "_upper", label: "Upper" }, { suffix: "_lower", label: "Lower" }],
  },
  { value: "PARABOLIC_SAR", label: "Parabolic SAR", defaultParams: { af_start: 0.02, af_step: 0.02, af_max: 0.2 }, overlay: true, category: "Trend" },
  {
    value: "Bollinger", label: "Bollinger Bands", defaultParams: { period: 20, std_dev: 2, source: "close" }, category: "Trend",
    subKeys: [{ suffix: "_upper", label: "Upper" }, { suffix: "_lower", label: "Lower" }],
  },

  // ── Oscillators ────────────────────────────────────────────
  { value: "RSI", label: "RSI (Relative Strength Index)", defaultParams: { period: 14, source: "close" }, overlay: false, category: "Oscillators" },
  {
    value: "MACD", label: "MACD", defaultParams: { fast: 12, slow: 26, signal: 9, source: "close" }, overlay: false, category: "Oscillators",
    subKeys: [{ suffix: "_signal", label: "Signal" }, { suffix: "_hist", label: "Histogram" }],
  },
  {
    value: "Stochastic", label: "Stochastic", defaultParams: { k_period: 14, d_period: 3, smooth: 3 }, overlay: false, category: "Oscillators",
    subKeys: [{ suffix: "_d", label: "%D" }],
  },
  {
    value: "STOCHASTIC_RSI", label: "Stochastic RSI", defaultParams: { rsi_period: 14, stoch_period: 14, k_smooth: 3, d_smooth: 3, source: "close" }, overlay: false, category: "Oscillators",
    subKeys: [{ suffix: "_d", label: "%D" }],
  },
  { value: "ADX", label: "ADX (Avg Directional Index)", defaultParams: { period: 14 }, overlay: false, category: "Oscillators" },
  { value: "CCI", label: "CCI (Commodity Channel Index)", defaultParams: { period: 20 }, overlay: false, category: "Oscillators" },
  { value: "WILLIAMS_R", label: "Williams %R", defaultParams: { period: 14 }, overlay: false, category: "Oscillators" },
  { value: "MFI", label: "MFI (Money Flow Index)", defaultParams: { period: 14 }, overlay: false, category: "Oscillators" },
  { value: "ROC", label: "ROC (Rate of Change)", defaultParams: { period: 14, source: "close" }, overlay: false, category: "Oscillators" },
  { value: "AWESOME_OSCILLATOR", label: "Awesome Oscillator", defaultParams: { fast: 5, slow: 34 }, overlay: false, category: "Oscillators" },

  // ── Volume ─────────────────────────────────────────────────
  { value: "VWAP", label: "VWAP (Volume-Weighted Avg Price)", defaultParams: {}, category: "Volume" },
  {
    value: "VWAP_BANDS", label: "VWAP Bands", defaultParams: { num_std: 2 }, category: "Volume",
    subKeys: [{ suffix: "_upper", label: "Upper" }, { suffix: "_lower", label: "Lower" }],
  },
  { value: "OBV", label: "OBV (On-Balance Volume)", defaultParams: {}, overlay: false, category: "Volume" },
  { value: "AD_LINE", label: "A/D Line (Accumulation/Distribution)", defaultParams: {}, overlay: false, category: "Volume" },
  { value: "CMF", label: "CMF (Chaikin Money Flow)", defaultParams: { period: 20 }, overlay: false, category: "Volume" },

  // ── Volatility ─────────────────────────────────────────────
  { value: "ATR", label: "ATR (Average True Range)", defaultParams: { period: 14 }, overlay: false, category: "Volatility" },
  {
    value: "ATR_BANDS", label: "ATR Bands", defaultParams: { atr_period: 14, multiplier: 2, basis: "ema", basis_period: 20 }, category: "Volatility",
    subKeys: [{ suffix: "_upper", label: "Upper" }, { suffix: "_lower", label: "Lower" }],
  },
  { value: "HISTORICAL_VOLATILITY", label: "Historical Volatility", defaultParams: { period: 20 }, overlay: false, category: "Volatility" },
  {
    value: "STDDEV_CHANNEL", label: "Std Dev Channel", defaultParams: { period: 20, num_std: 2 }, category: "Volatility",
    subKeys: [{ suffix: "_upper", label: "Upper" }, { suffix: "_lower", label: "Lower" }],
  },
  { value: "ADR", label: "ADR (Average Daily Range)", defaultParams: { period: 10 }, overlay: false, category: "Volatility" },

  // ── Levels / Structure ─────────────────────────────────────
  {
    value: "Pivot", label: "Pivot Points (Daily)", defaultParams: { type: "standard" }, category: "Levels",
    subKeys: [
      { suffix: "_pp", label: "PP" },
      { suffix: "_r1", label: "R1" }, { suffix: "_r2", label: "R2" }, { suffix: "_r3", label: "R3" },
      { suffix: "_s1", label: "S1" }, { suffix: "_s2", label: "S2" }, { suffix: "_s3", label: "S3" },
    ],
  },
  { value: "PivotHigh", label: "Pivot High (Swing)", defaultParams: { lookback: 42 }, overlay: true, category: "Levels" },
  { value: "PivotLow", label: "Pivot Low (Swing)", defaultParams: { lookback: 42 }, overlay: true, category: "Levels" },

  // ── Smart Money / ICT ──────────────────────────────────────
  {
    value: "FAIR_VALUE_GAPS", label: "Fair Value Gaps", defaultParams: {}, overlay: true, category: "Smart Money",
    subKeys: [{ suffix: "_bull", label: "Bullish FVG" }, { suffix: "_bear", label: "Bearish FVG" }],
  },
  {
    value: "ORDER_BLOCKS", label: "Order Blocks", defaultParams: { swing_lookback: 5, impulse_mult: 2 }, overlay: true, category: "Smart Money",
    subKeys: [{ suffix: "_bull", label: "Bullish OB" }, { suffix: "_bear", label: "Bearish OB" }],
  },
  {
    value: "LIQUIDITY_SWEEPS", label: "Liquidity Sweeps", defaultParams: { lookback: 20 }, overlay: true, category: "Smart Money",
    subKeys: [{ suffix: "_high", label: "Sweep High" }, { suffix: "_low", label: "Sweep Low" }],
  },

  // ── Session / Time ─────────────────────────────────────────
  {
    value: "SESSION_HL", label: "Session High/Low", defaultParams: { session_start: 8, session_end: 17 }, overlay: true, category: "Session",
    subKeys: [{ suffix: "_high", label: "Session High" }, { suffix: "_low", label: "Session Low" }],
  },
  {
    value: "PREV_DAY_LEVELS", label: "Previous Day H/L/C", defaultParams: {}, overlay: true, category: "Session",
    subKeys: [{ suffix: "_pdh", label: "Prev High" }, { suffix: "_pdl", label: "Prev Low" }, { suffix: "_pdc", label: "Prev Close" }],
  },
  { value: "WEEKLY_OPEN", label: "Weekly Open", defaultParams: {}, overlay: true, category: "Session" },
  {
    value: "KILL_ZONES", label: "Kill Zones", defaultParams: { london_start: 2, london_end: 5, ny_start: 7, ny_end: 10 }, overlay: false, category: "Session",
    subKeys: [{ suffix: "_london", label: "London KZ" }, { suffix: "_ny", label: "NY KZ" }],
  },

  // ── Candlestick Patterns ─────────────────────────────────────
  { value: "CANDLE_PATTERN", label: "Engulfing", defaultParams: { pattern: "engulfing" }, overlay: false, category: "Candlestick" },
  { value: "CANDLE_PATTERN", label: "Pin Bar", defaultParams: { pattern: "pin_bar", body_ratio: 0.33, wick_ratio: 2.0 }, overlay: false, category: "Candlestick" },
  { value: "CANDLE_PATTERN", label: "Doji", defaultParams: { pattern: "doji", threshold: 0.05 }, overlay: false, category: "Candlestick" },
  { value: "CANDLE_PATTERN", label: "Hammer", defaultParams: { pattern: "hammer" }, overlay: false, category: "Candlestick" },
  { value: "CANDLE_PATTERN", label: "Inverted Hammer", defaultParams: { pattern: "inverted_hammer" }, overlay: false, category: "Candlestick" },
  { value: "CANDLE_PATTERN", label: "Shooting Star", defaultParams: { pattern: "shooting_star" }, overlay: false, category: "Candlestick" },
  { value: "CANDLE_PATTERN", label: "Morning Star", defaultParams: { pattern: "morning_star" }, overlay: false, category: "Candlestick" },
  { value: "CANDLE_PATTERN", label: "Evening Star", defaultParams: { pattern: "evening_star" }, overlay: false, category: "Candlestick" },
  { value: "CANDLE_PATTERN", label: "Inside Bar", defaultParams: { pattern: "inside_bar" }, overlay: false, category: "Candlestick" },
  { value: "CANDLE_PATTERN", label: "Outside Bar", defaultParams: { pattern: "outside_bar" }, overlay: false, category: "Candlestick" },
  { value: "CANDLE_PATTERN", label: "Three White Soldiers", defaultParams: { pattern: "three_white_soldiers" }, overlay: false, category: "Candlestick" },
  { value: "CANDLE_PATTERN", label: "Three Black Crows", defaultParams: { pattern: "three_black_crows" }, overlay: false, category: "Candlestick" },
  { value: "CANDLE_PATTERN", label: "Harami", defaultParams: { pattern: "harami" }, overlay: false, category: "Candlestick" },
  { value: "CANDLE_PATTERN", label: "Tweezer Top", defaultParams: { pattern: "tweezer_top", tolerance: 0.001 }, overlay: false, category: "Candlestick" },
  { value: "CANDLE_PATTERN", label: "Tweezer Bottom", defaultParams: { pattern: "tweezer_bottom", tolerance: 0.001 }, overlay: false, category: "Candlestick" },
  { value: "CANDLE_PATTERN", label: "Spinning Top", defaultParams: { pattern: "spinning_top", body_threshold: 0.3 }, overlay: false, category: "Candlestick" },
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
  { value: "structure", label: "Structure (Swing)" },
];

const DIRECTIONS = [
  { value: "both", label: "Both" },
  { value: "long", label: "Long Only" },
  { value: "short", label: "Short Only" },
];

/* ── Entry Templates ──────────────────────────────────────── */
interface EntryTemplate {
  id: string;
  label: string;
  description: string;
  icon: string;
  /** Indicators that should be auto-added if missing */
  requiredIndicators: { type: string; params: Record<string, number | string> }[];
  /** Condition rows to insert */
  conditions: ConditionRow[];
}

const ENTRY_TEMPLATES: EntryTemplate[] = [
  {
    id: "crossover",
    label: "MA Crossover",
    description: "Fast EMA crosses above/below slow EMA",
    icon: "↗",
    requiredIndicators: [
      { type: "EMA", params: { period: 9, source: "close" } },
      { type: "EMA", params: { period: 21, source: "close" } },
    ],
    conditions: [
      { left: "ema_1", operator: "crosses_above", right: "ema_2", logic: "AND", direction: "long" },
      { left: "ema_1", operator: "crosses_below", right: "ema_2", logic: "AND", direction: "short" },
    ],
  },
  {
    id: "breakout",
    label: "Bollinger Breakout",
    description: "Price breaks above upper or below lower BB",
    icon: "⚡",
    requiredIndicators: [
      { type: "BB", params: { period: 20, std_dev: 2, source: "close" } },
    ],
    conditions: [
      { left: "price.close", operator: ">", right: "bb_1.upper", logic: "AND", direction: "long" },
      { left: "price.close", operator: "<", right: "bb_1.lower", logic: "AND", direction: "short" },
    ],
  },
  {
    id: "bounce",
    label: "RSI Bounce",
    description: "RSI crosses above oversold / below overbought",
    icon: "↩",
    requiredIndicators: [
      { type: "RSI", params: { period: 14, source: "close" } },
    ],
    conditions: [
      { left: "rsi_1", operator: "crosses_above", right: "30", logic: "AND", direction: "long" },
      { left: "rsi_1", operator: "crosses_below", right: "70", logic: "AND", direction: "short" },
    ],
  },
  {
    id: "pullback",
    label: "EMA Pullback",
    description: "Price touches EMA then bounces (trend continuation)",
    icon: "↪",
    requiredIndicators: [
      { type: "EMA", params: { period: 50, source: "close" } },
      { type: "RSI", params: { period: 14, source: "close" } },
    ],
    conditions: [
      { left: "price.low", operator: "<=", right: "ema_1", logic: "AND", direction: "long" },
      { left: "rsi_1", operator: ">", right: "40", logic: "AND", direction: "long" },
      { left: "price.high", operator: ">=", right: "ema_1", logic: "AND", direction: "short" },
      { left: "rsi_1", operator: "<", right: "60", logic: "AND", direction: "short" },
    ],
  },
  {
    id: "candlestick",
    label: "Engulfing + Trend",
    description: "Engulfing pattern confirmed by EMA trend direction",
    icon: "🕯",
    requiredIndicators: [
      { type: "EMA", params: { period: 50, source: "close" } },
      { type: "CANDLE_PATTERN", params: { pattern: "engulfing" } },
    ],
    conditions: [
      { left: "candle_pattern_1", operator: ">", right: "0", logic: "AND", direction: "long" },
      { left: "price.close", operator: ">", right: "ema_1", logic: "AND", direction: "long" },
      { left: "candle_pattern_1", operator: "<", right: "0", logic: "AND", direction: "short" },
      { left: "price.close", operator: "<", right: "ema_1", logic: "AND", direction: "short" },
    ],
  },
  {
    id: "time_momentum",
    label: "Session Momentum",
    description: "MACD crossover during active trading hours",
    icon: "⏰",
    requiredIndicators: [
      { type: "MACD", params: { fast_period: 12, slow_period: 26, signal_period: 9, source: "close" } },
    ],
    conditions: [
      { left: "macd_1.macd", operator: "crosses_above", right: "macd_1.signal", logic: "AND", direction: "long" },
      { left: "macd_1.macd", operator: "crosses_below", right: "macd_1.signal", logic: "AND", direction: "short" },
    ],
  },
];

/* ── Searchable Indicator Combobox (grouped by category) ───── */
const INDICATOR_CATEGORIES = [...new Set(INDICATOR_TYPES.map((t) => t.category || "Other"))];

function IndicatorCombobox({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(false);
  const selected = INDICATOR_TYPES.find((t) => t.value === value);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" role="combobox" aria-expanded={open} className="w-[260px] justify-between bg-card-bg border-card-border text-sm h-8">
          {selected?.label || "Select indicator…"}
          <ChevronsUpDown className="ml-2 h-3.5 w-3.5 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[300px] p-0 bg-card-bg border-card-border max-h-[360px]">
        <Command className="bg-transparent">
          <CommandInput placeholder="Search indicators…" className="h-8 text-sm" />
          <CommandList className="max-h-[310px]">
            <CommandEmpty>No indicator found.</CommandEmpty>
            {INDICATOR_CATEGORIES.map((cat) => (
              <CommandGroup key={cat} heading={cat}>
                {INDICATOR_TYPES.filter((t) => (t.category || "Other") === cat).map((t) => (
                  <CommandItem
                    key={t.value}
                    value={t.label}
                    onSelect={() => { onChange(t.value); setOpen(false); }}
                    className="text-sm"
                  >
                    <Check className={cn("mr-2 h-3.5 w-3.5", value === t.value ? "opacity-100" : "opacity-0")} />
                    {t.label}
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

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
    stop_loss_buffer_pips: 0,
    take_profit_type: "fixed_pips",
    take_profit_value: 100,
    take_profit_2_type: "",
    take_profit_2_value: 0,
    take_profit_3_type: "",
    take_profit_3_value: 0,
    lot_split: [] as number[],
    breakeven_on_tp1: false,
    move_sl_to_tp1_on_tp2: false,
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
    session_preset: "",
    kill_zone_preset: "",
    trend_filter_indicator: "",
    trend_filter_period: 0,
    max_spread_pips: 0,
    max_trades_per_day: 0,
    consecutive_loss_limit: 0,
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
  const [viewMode, setViewMode] = useState<"form" | "visual">("form");

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

  /* ── Apply entry template ──────────────────────────────── */
  const applyTemplate = (tmpl: EntryTemplate) => {
    // Auto-add required indicators that are missing
    let updatedIndicators = [...indicators];
    const indicatorIdMap: Record<string, string> = {};

    for (const req of tmpl.requiredIndicators) {
      // Check if an indicator of this type already exists
      const existing = updatedIndicators.find((ind) =>
        ind.type === req.type &&
        Object.entries(req.params).every(([k, v]) => ind.params[k] === v)
      );

      if (existing) {
        indicatorIdMap[req.type] = existing.id;
      } else {
        const def = INDICATOR_TYPES.find((t) => t.value === req.type);
        const count = updatedIndicators.filter((i) => i.type === req.type).length;
        const newId = `${req.type.toLowerCase()}_${count + 1}`;
        updatedIndicators.push({
          id: newId,
          type: req.type,
          params: { ...def?.defaultParams, ...req.params },
          overlay: def?.overlay !== false,
        });
        indicatorIdMap[req.type] = newId;
      }
    }
    setIndicators(updatedIndicators);

    // Remap template condition IDs to actual indicator IDs
    const remapped = tmpl.conditions.map((c) => {
      let left = c.left;
      let right = c.right;
      // For each required indicator, remap placeholder ids (e.g., "ema_1" → actual id)
      for (const req of tmpl.requiredIndicators) {
        const placeholder = `${req.type.toLowerCase()}_${tmpl.requiredIndicators.filter((r, ri) => r.type === req.type && ri <= tmpl.requiredIndicators.indexOf(req)).length}`;
        const actual = indicatorIdMap[req.type] || placeholder;
        if (left === placeholder || left.startsWith(placeholder + ".")) {
          left = left.replace(placeholder, actual);
        }
        if (right === placeholder || right.startsWith(placeholder + ".")) {
          right = right.replace(placeholder, actual);
        }
      }
      return { ...c, left, right };
    });

    setEntryRules([...entryRules, ...remapped]);
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
      if (strategy && strategy.id) {
        await api.put(`/api/strategies/${strategy.id}`, payload);
      } else {
        await api.post("/api/strategies", payload);
      }
      onSave();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : typeof err === "string" ? err : "Save failed";
      setError(msg);
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

  /* ── Render condition row ───────────────────────────────── */
  const renderConditionRow = (type: "entry" | "exit", rule: ConditionRow, idx: number) => {
    const accentColor = type === "entry" ? "success" : "danger";
    return (
    <div key={idx} className="relative">
      {/* Visual connector line between conditions */}
      {idx > 0 && (
        <div className="flex items-center justify-center -mt-1 mb-1">
          <div className={`h-4 w-px bg-${accentColor}/30`} />
        </div>
      )}
      <div className={`rounded-lg border border-card-border bg-background p-3 space-y-2 transition-all hover:border-${accentColor}/30`}>
        {/* Logic connector badge */}
        <div className="flex items-center gap-2 flex-wrap">
          {idx > 0 ? (
            <Badge
              variant="outline"
              className={`cursor-pointer select-none border-${accentColor}/30 text-${accentColor} hover:bg-${accentColor}/10 px-2 py-0.5 text-[10px] font-bold w-14 justify-center`}
              onClick={() => updateCondition(type, idx, { logic: rule.logic === "AND" ? "OR" : "AND" })}
            >
              {rule.logic}
            </Badge>
          ) : (
            <Badge variant="secondary" className="px-2 py-0.5 text-[10px] font-medium w-14 justify-center">IF</Badge>
          )}
          <select
            value={rule.left}
            onChange={(e) => updateCondition(type, idx, { left: e.target.value })}
            className="flex-1 min-w-[140px] rounded-md border border-card-border bg-card-bg px-2 py-1.5 text-sm text-foreground outline-none focus:border-accent focus:ring-1 focus:ring-accent/30"
          >
            {sourceOptions.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <select
            value={rule.operator}
            onChange={(e) => updateCondition(type, idx, { operator: e.target.value })}
            className="rounded-md border border-card-border bg-card-bg px-2 py-1.5 text-sm font-medium text-accent outline-none focus:border-accent focus:ring-1 focus:ring-accent/30"
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
            className="flex-1 min-w-[140px] rounded-md border border-card-border bg-card-bg px-2 py-1.5 text-sm text-foreground outline-none focus:border-accent focus:ring-1 focus:ring-accent/30"
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
          <Button variant="ghost" size="sm" onClick={() => removeCondition(type, idx)} className="h-7 w-7 p-0 text-muted-foreground hover:text-danger">
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
        {/* Direction selector */}
        {type === "entry" && (
          <div className="flex items-center gap-1.5 pl-16">
            <span className="text-[10px] text-muted-foreground uppercase tracking-wide mr-1">Direction</span>
            {DIRECTIONS.map((d) => (
              <Button
                key={d.value}
                variant="ghost"
                size="sm"
                onClick={() => updateCondition(type, idx, { direction: d.value })}
                className={cn(
                  "h-6 px-2 text-[10px] font-semibold",
                  (rule.direction || "both") === d.value
                    ? d.value === "long" ? "bg-success/20 text-success hover:bg-success/30" : d.value === "short" ? "bg-danger/20 text-danger hover:bg-danger/30" : "bg-accent/20 text-accent hover:bg-accent/30"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                {d.label}
              </Button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={onCancel} className="gap-1 text-muted-foreground hover:text-foreground">
            <ArrowLeft className="h-4 w-4" /> Back
          </Button>
          <h2 className="text-xl font-semibold">
            {readOnly ? "View Strategy" : strategy ? "Edit Strategy" : "New Strategy"}
          </h2>
          {readOnly && (
            <Badge variant="outline" className="text-accent border-accent/30 ml-2">
              <Lock className="h-3 w-3 mr-1" /> System &bull; Read Only
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={onCancel}>
            {readOnly ? "Back" : "Cancel"}
          </Button>
          {!readOnly && (
            <Button
              onClick={handleSave}
              disabled={saving}
              className="bg-accent text-black hover:bg-accent/90 gap-2"
            >
              {saving ? <><Loader2 className="h-4 w-4 animate-spin" /> Saving...</> : "Save Strategy"}
            </Button>
          )}
        </div>
      </div>

      {error && <p className="text-sm text-danger">{typeof error === "string" ? error : String(error)}</p>}

      {/* Name & Description */}
      <Card className="bg-card-bg border-card-border">
        <CardContent className="p-5 space-y-4">
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Strategy Name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. TTM Squeeze Momentum, EMA Ribbon Trend..."
            className={inputCls}
          />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Description</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Brief description of the strategy logic..."
            rows={2}
            className={`${inputCls} resize-none`}
          />
        </div>
        </CardContent>
      </Card>

      {/* View mode toggle */}
      <div className="flex items-center gap-2">
        <div className="inline-flex rounded-lg border border-card-border bg-card-bg p-0.5">
          <button
            onClick={() => setViewMode("form")}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              viewMode === "form" ? "bg-accent text-black shadow" : "text-muted-foreground hover:text-foreground"
            )}
          >
            <FileText className="h-3.5 w-3.5" /> Form
          </button>
          <button
            onClick={() => setViewMode("visual")}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              viewMode === "visual" ? "bg-accent text-black shadow" : "text-muted-foreground hover:text-foreground"
            )}
          >
            <LayoutGrid className="h-3.5 w-3.5" /> Visual
          </button>
        </div>
        {viewMode === "visual" && (
          <span className="text-[10px] text-muted-foreground">Drag-and-drop node editor &bull; Click &ldquo;Sync → Form&rdquo; to apply changes</span>
        )}
      </div>

      {/* ═══ VISUAL EDITOR VIEW ═══ */}
      {viewMode === "visual" && (
        <Suspense fallback={
          <div className="w-full h-[620px] rounded-lg border border-card-border bg-slate-950 flex items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent" />
          </div>
        }>
          <VisualEditor
            indicators={indicators}
            entryRules={entryRules}
            exitRules={exitRules}
            onSync={(inds, entry, exit) => {
              setIndicators(inds);
              setEntryRules(entry);
              setExitRules(exit);
            }}
            readOnly={readOnly}
          />
        </Suspense>
      )}

      {/* ═══ FORM VIEW ═══ */}
      {viewMode === "form" && (
      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as typeof activeTab)}>
        <TabsList className="w-full bg-card-bg border border-card-border rounded-xl p-1 h-auto">
          <TabsTrigger value="indicators" className="flex-1 gap-1.5 rounded-lg py-2 data-[state=active]:bg-accent data-[state=active]:text-black data-[state=active]:shadow-none">
            <Activity className="h-3.5 w-3.5" /> Indicators
            {indicators.length > 0 && <Badge variant="secondary" className="ml-0.5 h-5 px-1.5 text-[10px] font-semibold">{indicators.length}</Badge>}
          </TabsTrigger>
          <TabsTrigger value="entry" className="flex-1 gap-1.5 rounded-lg py-2 data-[state=active]:bg-success data-[state=active]:text-black data-[state=active]:shadow-none">
            <LogIn className="h-3.5 w-3.5" /> Entry
            {entryRules.length > 0 && <Badge variant="secondary" className="ml-0.5 h-5 px-1.5 text-[10px] font-semibold">{entryRules.length}</Badge>}
          </TabsTrigger>
          <TabsTrigger value="exit" className="flex-1 gap-1.5 rounded-lg py-2 data-[state=active]:bg-danger data-[state=active]:text-black data-[state=active]:shadow-none">
            <LogOut className="h-3.5 w-3.5" /> Exit
            {exitRules.length > 0 && <Badge variant="secondary" className="ml-0.5 h-5 px-1.5 text-[10px] font-semibold">{exitRules.length}</Badge>}
          </TabsTrigger>
          <TabsTrigger value="risk" className="flex-1 gap-1.5 rounded-lg py-2 data-[state=active]:bg-accent data-[state=active]:text-black data-[state=active]:shadow-none">
            <Shield className="h-3.5 w-3.5" /> Risk
          </TabsTrigger>
          <TabsTrigger value="filters" className="flex-1 gap-1.5 rounded-lg py-2 data-[state=active]:bg-accent data-[state=active]:text-black data-[state=active]:shadow-none">
            <Filter className="h-3.5 w-3.5" /> Filters
          </TabsTrigger>
        </TabsList>

        {/* ═══ INDICATORS TAB ═══ */}
        <TabsContent value="indicators">
        <Card className="bg-card-bg border-card-border">
        <CardContent className="p-5">
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted-foreground">Configure technical indicators used by entry/exit rules.</p>
              <Button variant="ghost" size="sm" onClick={addIndicator} className="text-accent hover:bg-accent/10 gap-1">
                <Plus className="h-3.5 w-3.5" /> Add Indicator
              </Button>
            </div>
            {indicators.length === 0 && (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <div className="rounded-full bg-accent/10 p-4 mb-4">
                  <Activity className="h-8 w-8 text-accent" />
                </div>
                <p className="text-sm font-medium text-foreground mb-1">No indicators added</p>
                <p className="text-xs text-muted-foreground mb-4 max-w-[280px]">Indicators provide the data signals your entry and exit rules will evaluate.</p>
                <Button variant="outline" size="sm" onClick={addIndicator} className="gap-1.5">
                  <Plus className="h-3.5 w-3.5" /> Add Your First Indicator
                </Button>
              </div>
            )}
            {indicators.map((ind, idx) => {
              const def = INDICATOR_TYPES.find((t) => t.value === ind.type);
              return (
                <div key={idx} className="rounded-lg border border-card-border bg-background p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <IndicatorCombobox
                        value={ind.type}
                        onChange={(newType) => changeIndicatorType(idx, newType)}
                      />
                      <Badge variant="outline" className="text-accent border-accent/30 font-mono text-[10px]">{ind.id}</Badge>
                    </div>
                    <Button variant="ghost" size="sm" onClick={() => removeIndicator(idx)} className="text-muted-foreground hover:text-danger h-7 px-2 gap-1">
                      <X className="h-3.5 w-3.5" /> Remove
                    </Button>
                  </div>
                  {/* Parameter fields */}
                  <div className="flex flex-wrap gap-3">
                    {Object.entries(ind.params).map(([key, val]) => (
                      <div key={key} className="flex items-center gap-2">
                        <label className="text-xs text-muted-foreground capitalize">{key}:</label>
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
                    <div className="text-xs text-muted-foreground">
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
        </CardContent>
        </Card>
        </TabsContent>

        {/* ═══ ENTRY RULES TAB ═══ */}
        <TabsContent value="entry">
        <Card className="bg-card-bg border-card-border">
        <CardContent className="p-5">
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted-foreground">Define conditions to open a trade. Each rule can target long, short, or both directions.</p>
              <Button variant="ghost" size="sm" onClick={() => addCondition("entry")} className="text-success hover:bg-success/10 gap-1">
                <Plus className="h-3.5 w-3.5" /> Add Entry Rule
              </Button>
            </div>

            {/* ── Quick Templates ── */}
            <Accordion type="single" collapsible className="border border-card-border rounded-lg">
              <AccordionItem value="templates" className="border-0">
                <AccordionTrigger className="px-4 py-2.5 text-sm hover:no-underline">
                  <div className="flex items-center gap-2">
                    <Zap className="h-3.5 w-3.5 text-accent" />
                    <span className="font-medium">Quick Templates</span>
                    <Badge variant="outline" className="text-[10px] ml-1">{ENTRY_TEMPLATES.length}</Badge>
                  </div>
                </AccordionTrigger>
                <AccordionContent className="px-4 pb-4">
                  <p className="text-xs text-muted-foreground mb-3">Click a template to auto-add its indicators and entry conditions. You can edit everything afterwards.</p>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                    {ENTRY_TEMPLATES.map((tmpl) => (
                      <button
                        key={tmpl.id}
                        onClick={() => applyTemplate(tmpl)}
                        disabled={readOnly}
                        className="flex flex-col items-start gap-1 rounded-lg border border-card-border bg-background p-3 text-left transition-colors hover:border-accent/50 hover:bg-accent/5 disabled:opacity-50 disabled:pointer-events-none"
                      >
                        <div className="flex items-center gap-1.5">
                          <span className="text-base leading-none">{tmpl.icon}</span>
                          <span className="text-xs font-medium text-foreground">{tmpl.label}</span>
                        </div>
                        <span className="text-[10px] text-muted-foreground leading-tight">{tmpl.description}</span>
                        <div className="flex gap-1 mt-1">
                          <Badge variant="outline" className="text-[9px] px-1 py-0">{tmpl.conditions.length} rules</Badge>
                          <Badge variant="outline" className="text-[9px] px-1 py-0">{tmpl.requiredIndicators.length} ind.</Badge>
                        </div>
                      </button>
                    ))}
                  </div>
                </AccordionContent>
              </AccordionItem>
            </Accordion>

            {entryRules.length === 0 && (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <div className="rounded-full bg-success/10 p-4 mb-4">
                  <LogIn className="h-8 w-8 text-success" />
                </div>
                <p className="text-sm font-medium text-foreground mb-1">No entry rules defined</p>
                <p className="text-xs text-muted-foreground mb-4 max-w-[280px]">Entry rules determine when to open a position based on your indicator signals.</p>
                <Button variant="outline" size="sm" onClick={() => addCondition("entry")} className="gap-1.5">
                  <Plus className="h-3.5 w-3.5" /> Add Entry Rule
                </Button>
              </div>
            )}
            {entryRules.map((rule, idx) => renderConditionRow("entry", rule, idx))}
          </div>
        </CardContent>
        </Card>
        </TabsContent>

        {/* ═══ EXIT RULES TAB ═══ */}
        <TabsContent value="exit">
        <Card className="bg-card-bg border-card-border">
        <CardContent className="p-5">
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted-foreground">Define conditions to close a trade (EXIT signal). SL/TP are configured in Risk tab.</p>
              <Button variant="ghost" size="sm" onClick={() => addCondition("exit")} className="text-danger hover:bg-danger/10 gap-1">
                <Plus className="h-3.5 w-3.5" /> Add Exit Rule
              </Button>
            </div>
            {exitRules.length === 0 && (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <div className="rounded-full bg-danger/10 p-4 mb-4">
                  <LogOut className="h-8 w-8 text-danger" />
                </div>
                <p className="text-sm font-medium text-foreground mb-1">No exit rules defined</p>
                <p className="text-xs text-muted-foreground mb-4 max-w-[280px]">Exit rules trigger position closing based on signal conditions. SL/TP are set in the Risk tab.</p>
                <Button variant="outline" size="sm" onClick={() => addCondition("exit")} className="gap-1.5">
                  <Plus className="h-3.5 w-3.5" /> Add Exit Rule
                </Button>
              </div>
            )}
            {exitRules.map((rule, idx) => renderConditionRow("exit", rule, idx))}
          </div>
        </CardContent>
        </Card>
        </TabsContent>

        {/* ═══ RISK MANAGEMENT TAB ═══ */}
        <TabsContent value="risk">
        <Card className="bg-card-bg border-card-border">
        <CardContent className="p-5">
          <div className="space-y-6">
            {/* ── MSS Strategy Params ── */}
            {strategyType === "mss" && mssConfig && (
              <>
                <div className="rounded-lg border border-accent/30 bg-accent/5 px-4 py-2.5">
                  <p className="text-xs text-accent font-medium">MSS (Market Structure Shift) Strategy</p>
                  <p className="text-xs text-muted-foreground mt-0.5">These parameters directly control backtest behavior. Values are percentages of ADR10.</p>
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
                      <p className="text-xs text-muted-foreground">Bars to look back for swing high/low pivots</p>
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
                        <p className="text-xs text-muted-foreground">0.382 = 38.2% retracement, 0.5 = 50%, 0.618 = 61.8%</p>
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
                  <p className="text-xs text-muted-foreground mt-0.5">These parameters directly control backtest behavior.</p>
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
              <Accordion type="multiple" defaultValue={["position-sizing", "stop-loss", "take-profit"]} className="space-y-2">
                {/* Position Sizing */}
                <AccordionItem value="position-sizing" className="rounded-lg border border-card-border bg-background px-4">
                  <AccordionTrigger className="py-3 hover:no-underline">
                    <div className="flex items-center gap-2">
                      <SlidersHorizontal className="h-4 w-4 text-accent" />
                      <span className="text-sm font-medium">Position Sizing</span>
                    </div>
                  </AccordionTrigger>
                  <AccordionContent>
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
                  </AccordionContent>
                </AccordionItem>

                {/* Stop Loss */}
                <AccordionItem value="stop-loss" className="rounded-lg border border-card-border bg-background px-4">
                  <AccordionTrigger className="py-3 hover:no-underline">
                    <div className="flex items-center gap-2">
                      <Shield className="h-4 w-4 text-danger" />
                      <span className="text-sm font-medium">Stop Loss</span>
                      <Badge variant="outline" className="text-[10px] h-5 border-danger/30 text-danger">{riskParams.stop_loss_value} {riskParams.stop_loss_type}</Badge>
                    </div>
                  </AccordionTrigger>
                  <AccordionContent>
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
                  {(riskParams.stop_loss_type === "structure" || riskParams.stop_loss_type === "swing") && (
                    <div className="mt-3 w-1/2 space-y-2">
                      <label className={labelCls}>SL Buffer (pips beyond structure level)</label>
                      <input
                        type="number" step="0.5" min="0"
                        value={riskParams.stop_loss_buffer_pips ?? 0}
                        onChange={(e) => setRiskParams({ ...riskParams, stop_loss_buffer_pips: Number(e.target.value) })}
                        className={inputCls}
                      />
                    </div>
                  )}
                  </AccordionContent>
                </AccordionItem>

                {/* Take Profit 1 */}
                <AccordionItem value="take-profit" className="rounded-lg border border-card-border bg-background px-4">
                  <AccordionTrigger className="py-3 hover:no-underline">
                    <div className="flex items-center gap-2">
                      <TrendingUp className="h-4 w-4 text-success" />
                      <span className="text-sm font-medium">Take Profit</span>
                      <Badge variant="outline" className="text-[10px] h-5 border-success/30 text-success">{riskParams.take_profit_value} {riskParams.take_profit_type}</Badge>
                    </div>
                  </AccordionTrigger>
                  <AccordionContent>
                  <div className="space-y-6">
                  <div>
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
                  <p className="text-xs font-semibold text-success/70 uppercase tracking-wide mt-2">Take Profit 2 (Optional)</p>
                  <p className="text-xs text-muted-foreground mt-1 mb-3">Enable a second take-profit level with lot splitting.</p>
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
                        {!riskParams.take_profit_3_type ? (
                          <>
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
                            <div className="flex justify-between text-xs text-muted-foreground">
                              <span>10% TP1</span>
                              <span>90% TP1</span>
                            </div>
                          </>
                        ) : (
                          <>
                            <label className={labelCls}>
                              Lot Split (TP1: {Math.round((riskParams.lot_split?.[0] ?? 0.5) * 100)}% / TP2: {Math.round((riskParams.lot_split?.[1] ?? 0.3) * 100)}% / TP3: {Math.round((riskParams.lot_split?.[2] ?? 0.2) * 100)}%)
                            </label>
                            <div className="grid grid-cols-3 gap-3">
                              <div className="space-y-1">
                                <span className="text-xs text-muted-foreground">TP1 %</span>
                                <input type="number" min="5" max="90" step="5"
                                  value={Math.round((riskParams.lot_split?.[0] ?? 0.5) * 100)}
                                  onChange={(e) => {
                                    const tp1 = Number(e.target.value) / 100;
                                    const tp2 = riskParams.lot_split?.[1] ?? 0.3;
                                    const tp3 = Math.max(0, Math.round((1 - tp1 - tp2) * 100) / 100);
                                    setRiskParams({ ...riskParams, lot_split: [tp1, tp2, tp3] });
                                  }}
                                  className={inputCls}
                                />
                              </div>
                              <div className="space-y-1">
                                <span className="text-xs text-muted-foreground">TP2 %</span>
                                <input type="number" min="5" max="90" step="5"
                                  value={Math.round((riskParams.lot_split?.[1] ?? 0.3) * 100)}
                                  onChange={(e) => {
                                    const tp1 = riskParams.lot_split?.[0] ?? 0.5;
                                    const tp2 = Number(e.target.value) / 100;
                                    const tp3 = Math.max(0, Math.round((1 - tp1 - tp2) * 100) / 100);
                                    setRiskParams({ ...riskParams, lot_split: [tp1, tp2, tp3] });
                                  }}
                                  className={inputCls}
                                />
                              </div>
                              <div className="space-y-1">
                                <span className="text-xs text-muted-foreground">TP3 % (auto)</span>
                                <input type="number" disabled
                                  value={Math.round((riskParams.lot_split?.[2] ?? 0.2) * 100)}
                                  className={inputCls + " opacity-60"}
                                />
                              </div>
                            </div>
                          </>
                        )}
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
                      {/* Move SL to TP1 on TP2 */}
                      <label className="flex items-center gap-2 text-xs font-medium text-foreground">
                        <input
                          type="checkbox"
                          checked={riskParams.move_sl_to_tp1_on_tp2 ?? false}
                          onChange={(e) => setRiskParams({ ...riskParams, move_sl_to_tp1_on_tp2: e.target.checked })}
                          className="rounded accent-accent"
                        />
                        Move SL to TP1 level when TP2 is hit
                      </label>
                    </div>
                  )}

                  {/* Take Profit 3 (only when TP2 is active) */}
                  {riskParams.take_profit_2_type && (
                    <div className="mt-4">
                      <p className="text-xs font-semibold text-success/70 uppercase tracking-wide mt-2">Take Profit 3 (Optional)</p>
                      <p className="text-xs text-muted-foreground mt-1 mb-3">Enable a third take-profit level with 3-way lot splitting.</p>
                      <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-2">
                          <label className={labelCls}>TP3 Type</label>
                          <select
                            value={riskParams.take_profit_3_type ?? ""}
                            onChange={(e) => {
                              const tp3Type = e.target.value;
                              const updates: Record<string, unknown> = { take_profit_3_type: tp3Type };
                              if (tp3Type && (!riskParams.lot_split || riskParams.lot_split.length !== 3)) {
                                updates.lot_split = [0.5, 0.3, 0.2];
                              }
                              if (!tp3Type) {
                                updates.take_profit_3_value = 0;
                                if (riskParams.lot_split && riskParams.lot_split.length === 3) {
                                  updates.lot_split = [0.6, 0.4];
                                }
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
                        {riskParams.take_profit_3_type && (
                          <div className="space-y-2">
                            <label className={labelCls}>TP3 Value</label>
                            <input
                              type="number" step="0.1"
                              value={riskParams.take_profit_3_value ?? 0}
                              onChange={(e) => setRiskParams({ ...riskParams, take_profit_3_value: Number(e.target.value) })}
                              className={inputCls}
                            />
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
                </div>
                  </AccordionContent>
                </AccordionItem>

                {/* Trailing Stop */}
                <AccordionItem value="trailing-stop" className="rounded-lg border border-card-border bg-background px-4">
                  <AccordionTrigger className="py-3 hover:no-underline">
                    <div className="flex items-center gap-2">
                      <Zap className="h-4 w-4 text-accent" />
                      <span className="text-sm font-medium">Trailing Stop</span>
                      {riskParams.trailing_stop && <Badge variant="outline" className="text-[10px] h-5 border-accent/30 text-accent">Active</Badge>}
                    </div>
                  </AccordionTrigger>
                  <AccordionContent>
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
                  </AccordionContent>
                </AccordionItem>
              </Accordion>
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
        </CardContent>
        </Card>
        </TabsContent>

        {/* ═══ FILTERS TAB ═══ */}
        <TabsContent value="filters">
        <Card className="bg-card-bg border-card-border">
        <CardContent className="p-5">
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
                        : "border border-card-border text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {day}
                  </button>
                ))}
              </div>
              <p className="text-xs text-muted-foreground mt-1">Leave empty to trade all days</p>
            </div>

            {/* ADX Trend Filter */}
            <div>
              <p className={sectionTitle}>ADX Trend Filter</p>
              <p className="text-xs text-muted-foreground mt-1 mb-3">Only take trades when ADX is within a range. Requires ADX indicator.</p>
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
              <p className="text-xs text-muted-foreground mt-1 mb-3">Set min/max volatility thresholds. Requires ATR or ADR indicator.</p>
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

            {/* Session Preset */}
            <div>
              <p className={sectionTitle}>Session Preset</p>
              <p className="text-xs text-muted-foreground mt-1 mb-3">Quick-fill time range for common trading sessions.</p>
              <div className="flex gap-2 flex-wrap">
                {[
                  { value: "london", label: "London (08:00–17:00)", start: "08:00", end: "17:00" },
                  { value: "new_york", label: "New York (13:00–22:00)", start: "13:00", end: "22:00" },
                  { value: "asia", label: "Asia (00:00–09:00)", start: "00:00", end: "09:00" },
                  { value: "london_ny_overlap", label: "LDN/NY Overlap (13:00–17:00)", start: "13:00", end: "17:00" },
                ].map((s) => (
                  <button
                    key={s.value}
                    onClick={() =>
                      setFilters({ ...filters, session_preset: s.value, time_start: s.start, time_end: s.end })
                    }
                    className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                      filters.session_preset === s.value
                        ? "bg-accent text-black"
                        : "border border-card-border text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Kill Zone Preset */}
            <div>
              <p className={sectionTitle}>Kill Zone Preset</p>
              <p className="text-xs text-muted-foreground mt-1 mb-3">Only trade during high-liquidity kill zone windows.</p>
              <select
                value={filters.kill_zone_preset ?? ""}
                onChange={(e) => setFilters({ ...filters, kill_zone_preset: e.target.value })}
                className={selectCls}
              >
                <option value="">Disabled</option>
                <option value="london_open">London Open (02:00–05:00 UTC)</option>
                <option value="ny_open">NY Open (07:00–10:00 UTC)</option>
                <option value="london_close">London Close (10:00–12:00 UTC)</option>
              </select>
            </div>

            {/* Trend Direction Filter */}
            <div>
              <p className={sectionTitle}>Trend Direction Filter</p>
              <p className="text-xs text-muted-foreground mt-1 mb-3">Only trade in the direction of a longer-term moving average.</p>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className={labelCls}>Trend Indicator</label>
                  <select
                    value={filters.trend_filter_indicator ?? ""}
                    onChange={(e) => setFilters({ ...filters, trend_filter_indicator: e.target.value })}
                    className={selectCls}
                  >
                    <option value="">Disabled</option>
                    <option value="SMA">SMA</option>
                    <option value="EMA">EMA</option>
                  </select>
                </div>
                {filters.trend_filter_indicator && (
                  <div className="space-y-2">
                    <label className={labelCls}>Period</label>
                    <input
                      type="number" step="1" min="5" max="500"
                      value={filters.trend_filter_period || 200}
                      onChange={(e) => setFilters({ ...filters, trend_filter_period: Number(e.target.value) })}
                      className={inputCls}
                    />
                  </div>
                )}
              </div>
            </div>

            {/* Trade Limits & Spread */}
            <div>
              <p className={sectionTitle}>Trade Limits</p>
              <div className="grid grid-cols-3 gap-4 mt-3">
                <div className="space-y-2">
                  <label className={labelCls}>Max Spread (pips, 0 = off)</label>
                  <input
                    type="number" step="0.1" min="0"
                    value={filters.max_spread_pips ?? 0}
                    onChange={(e) => setFilters({ ...filters, max_spread_pips: Number(e.target.value) })}
                    className={inputCls}
                  />
                </div>
                <div className="space-y-2">
                  <label className={labelCls}>Max Trades / Day (0 = ∞)</label>
                  <input
                    type="number" min="0" step="1"
                    value={filters.max_trades_per_day ?? 0}
                    onChange={(e) => setFilters({ ...filters, max_trades_per_day: Number(e.target.value) })}
                    className={inputCls}
                  />
                </div>
                <div className="space-y-2">
                  <label className={labelCls}>Consec. Loss Pause (0 = off)</label>
                  <input
                    type="number" min="0" step="1"
                    value={filters.consecutive_loss_limit ?? 0}
                    onChange={(e) => setFilters({ ...filters, consecutive_loss_limit: Number(e.target.value) })}
                    className={inputCls}
                  />
                  <p className="text-xs text-muted-foreground">Pause trading after N consecutive losses</p>
                </div>
              </div>
            </div>
          </div>
        </CardContent>
        </Card>
        </TabsContent>
      </Tabs>
      )}

      {/* Strategy Summary */}
      <Card className="bg-card-bg border-card-border">
        <CardContent className="p-4">
        <div className="flex items-center justify-between mb-3">
          <h4 className="text-xs font-medium text-muted-foreground">Strategy Summary</h4>
          <span className="text-xs text-muted-foreground">{name || "Untitled"}</span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-2">
          <div className="rounded-md bg-accent/10 border border-accent/20 px-3 py-2 text-center">
            <p className="text-lg font-bold text-accent">{indicators.length}</p>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide">Indicators</p>
          </div>
          <div className="rounded-md bg-success/10 border border-success/20 px-3 py-2 text-center">
            <p className="text-lg font-bold text-success">{entryRules.length}</p>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide">Entry Rules</p>
          </div>
          <div className="rounded-md bg-danger/10 border border-danger/20 px-3 py-2 text-center">
            <p className="text-lg font-bold text-danger">{exitRules.length}</p>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide">Exit Rules</p>
          </div>
          <div className="rounded-md bg-card-bg border border-card-border px-3 py-2 text-center">
            <p className="text-sm font-bold text-foreground">{riskParams.stop_loss_value}</p>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide">SL ({riskParams.stop_loss_type.replace("_", " ")})</p>
          </div>
          <div className="rounded-md bg-card-bg border border-card-border px-3 py-2 text-center">
            <p className="text-sm font-bold text-foreground">{riskParams.take_profit_value}</p>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide">TP ({riskParams.take_profit_type.replace("_", " ")})</p>
          </div>
          {(riskParams.take_profit_2_type || riskParams.trailing_stop) && (
            <div className="rounded-md bg-card-bg border border-card-border px-3 py-2 text-center">
              {riskParams.take_profit_2_type ? (
                <>
                  <p className="text-sm font-bold text-foreground">{riskParams.take_profit_2_value}</p>
                  <p className="text-[10px] text-muted-foreground uppercase tracking-wide">TP2</p>
                </>
              ) : (
                <>
                  <p className="text-sm font-bold text-accent">{riskParams.trailing_stop_value}</p>
                  <p className="text-[10px] text-muted-foreground uppercase tracking-wide">Trail</p>
                </>
              )}
            </div>
          )}
        </div>
        </CardContent>
      </Card>
    </div>
  );
}
