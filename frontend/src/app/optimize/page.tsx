"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import ChatHelpers from "@/components/ChatHelpers";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Play, Square, CheckCircle2, AlertTriangle, Plus, X, ChevronDown, ChevronRight, Settings2, Trash2 } from "lucide-react";
import type {
  Strategy,
  StrategyList,
  DataSource,
  DataSourceList,
  ParamRange,
  OptimizationStatus,
  OptimizationResponse,
  OptimizationListItem,
} from "@/types";

// ── Inline types for new features ──────────────────────────────────────────────
interface RobustnessWindowResult {
  window_index: number; date_from: string; date_to: string; n_bars: number;
  total_trades: number; net_profit: number; sharpe_ratio: number;
  profit_factor: number; win_rate: number; max_drawdown_pct: number;
  sqn: number; passed: boolean;
}
interface RobustnessResult {
  opt_id: number; n_windows: number; windows_passed: number; pass_rate: number;
  windows: RobustnessWindowResult[]; criteria: Record<string, number | boolean>;
}
interface TradeLogEntry {
  entry_time: number; exit_time: number | null; direction: string;
  entry_price: number; exit_price: number | null; pnl: number; exit_reason: string;
}
interface TradeAnalysisGroup { trades: number; net_profit: number; win_rate: number; }
interface TradeLogResult {
  opt_id: number; trial_number: number; params: Record<string, number | string>;
  score: number; total_trades: number; trades: TradeLogEntry[];
  analysis: {
    by_hour: Record<string, TradeAnalysisGroup>;
    by_day: Record<string, TradeAnalysisGroup>;
    by_direction: Record<string, TradeAnalysisGroup>;
  };
}
interface PhaseData {
  id: number; chain_id: string; phase_number: number;
  strategy_id: number | null; datasource_id: number | null;
  objective: string; n_trials: number; method: string; min_trades: number;
  param_space: ParamRange[] | null; frozen_params: Record<string, number | string> | null;
  status: string; best_params: Record<string, number | string> | null;
  best_score: number | null; param_importance: Record<string, number> | null;
  history: unknown[] | null; created_at: string; completed_at: string | null;
}
interface ChainSummary {
  chain_id: string; n_phases: number; strategy_id: number | null;
  datasource_id: number | null; latest_phase: number;
  latest_status: string; latest_score: number | null; created_at: string;
}
// ──────────────────────────────────────────────────────────────────────────────

function extractOptimizableParams(strategy: Strategy): ParamRange[] {
  const params: ParamRange[] = [];

  // File-based strategies — extract from settings_schema
  if (strategy.strategy_type && strategy.strategy_type !== "builder" && strategy.settings_schema?.length > 0) {
    for (const entry of strategy.settings_schema) {
      if (entry.type === "int" || entry.type === "float") {
        const val = (strategy.settings_values?.[entry.key] ?? entry.default ?? 0) as number;
        params.push({
          param_path: `settings_values.${entry.key}`,
          param_type: entry.type,
          min_val: entry.min ?? Math.max(0, Math.round(val * 0.3)),
          max_val: entry.max ?? Math.round(val * 3),
          step: entry.step ?? (entry.type === "int" ? 1 : undefined),
          label: entry.label || entry.key,
        });
      }
    }
    return params;
  }

  const filters = (strategy.filters || {}) as Record<string, unknown>;
  const mssConfig = filters.mss_config as Record<string, unknown> | undefined;
  const goldConfig = filters.gold_bt_config as Record<string, unknown> | undefined;

  if (mssConfig) {
    /* ── MSS strategy params ── */
    const mssDefs: { key: string; label: string; type: "int" | "float"; min: number; max: number; step?: number }[] = [
      { key: "swing_lb", label: "MSS Swing Lookback", type: "int", min: 10, max: 100, step: 5 },
      { key: "sl_pct", label: "MSS SL % of ADR", type: "float", min: 5, max: 60 },
      { key: "tp1_pct", label: "MSS TP1 % of ADR", type: "float", min: 5, max: 60 },
      { key: "tp2_pct", label: "MSS TP2 % of ADR", type: "float", min: 5, max: 80 },
      { key: "pb_pct", label: "MSS Pullback Ratio", type: "float", min: 0.1, max: 0.9 },
    ];
    mssDefs.forEach(({ key, label, type, min, max, step }) => {
      const val = mssConfig[key];
      if (typeof val === "number") {
        params.push({
          param_path: `filters.mss_config.${key}`,
          param_type: type,
          min_val: min,
          max_val: max,
          step,
          label,
        });
      }
    });
  } else if (goldConfig) {
    /* ── Gold BT strategy params ── */
    const goldDefs: { key: string; label: string; type: "int" | "float"; min: number; max: number; step?: number }[] = [
      { key: "box_height", label: "Gold Box Height", type: "float", min: 2, max: 30 },
      { key: "trigger_interval_hours", label: "Gold Trigger Interval (h)", type: "int", min: 1, max: 8, step: 1 },
      { key: "stop_line_buffer", label: "Gold Stop Buffer", type: "float", min: 0.5, max: 10 },
      { key: "stop_to_tp_gap", label: "Gold Stop-to-TP Gap", type: "float", min: 0.5, max: 10 },
      { key: "tp_zone_gap", label: "Gold TP Zone Gap", type: "float", min: 0.5, max: 5 },
      { key: "tp1_height", label: "Gold TP1 Height", type: "float", min: 1, max: 15 },
      { key: "tp2_height", label: "Gold TP2 Height", type: "float", min: 1, max: 15 },
      { key: "sl_fixed_usd", label: "Gold Fixed SL ($)", type: "float", min: 5, max: 50 },
    ];
    goldDefs.forEach(({ key, label, type, min, max, step }) => {
      const val = goldConfig[key];
      if (typeof val === "number") {
        params.push({
          param_path: `filters.gold_bt_config.${key}`,
          param_type: type,
          min_val: min,
          max_val: max,
          step,
          label,
        });
      }
    });
  } else {
    /* ── Generic strategy params ── */
    (strategy.indicators || []).forEach((ind, idx) => {
      const p = ind.params || {};
      Object.entries(p).forEach(([key, val]) => {
        if (typeof val === "number") {
          const isInt = Number.isInteger(val);
          params.push({
            param_path: `indicators.${idx}.params.${key}`,
            param_type: isInt ? "int" : "float",
            min_val: Math.max(1, Math.round(val * 0.5)),
            max_val: Math.round(val * 2),
            step: isInt ? 1 : undefined,
            label: `${ind.type} ${key}`,
          });
        }
      });
    });
    const risk = strategy.risk_params || {};
    if (risk.stop_loss_value) {
      params.push({
        param_path: "risk_params.stop_loss_value",
        param_type: "float",
        min_val: Math.max(1, Math.round((risk.stop_loss_value as number) * 0.3)),
        max_val: Math.round((risk.stop_loss_value as number) * 3),
        label: "Stop Loss",
      });
    }
    if (risk.take_profit_value) {
      params.push({
        param_path: "risk_params.take_profit_value",
        param_type: "float",
        min_val: Math.max(1, Math.round((risk.take_profit_value as number) * 0.3)),
        max_val: Math.round((risk.take_profit_value as number) * 3),
        label: "Take Profit",
      });
    }
  }
  return params;
}

export default function OptimizePage() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [sources, setSources] = useState<DataSource[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState<number | null>(null);
  const [selectedSource, setSelectedSource] = useState<number | null>(null);

  // Param config
  const [paramSpace, setParamSpace] = useState<ParamRange[]>([]);
  const [objective, setObjective] = useState("sharpe_ratio");
  const [useSecondary, setUseSecondary] = useState(false);
  const [secondaryObjective, setSecondaryObjective] = useState("net_profit");
  const [secondaryOperator, setSecondaryOperator] = useState<'>=' | '<='>('>=');
  const [secondaryThreshold, setSecondaryThreshold] = useState(0);
  const [nTrials, setNTrials] = useState(50);
  const [minTrades, setMinTrades] = useState(30);
  const [method, setMethod] = useState("bayesian");

  // Robustness test state
  const [robustWindows, setRobustWindows] = useState(10);
  const [robustWindowPct, setRobustWindowPct] = useState(30);
  const [robustMinTrades, setRobustMinTrades] = useState(10);
  const [robustMinPF, setRobustMinPF] = useState(1.0);
  const [robustMinSharpe, setRobustMinSharpe] = useState(0.0);
  const [robustnessResult, setRobustnessResult] = useState<RobustnessResult | null>(null);
  const [robustnessLoading, setRobustnessLoading] = useState(false);

  // Trade log state
  const [tradeLog, setTradeLog] = useState<TradeLogResult | null>(null);
  const [tradeLogTopN, setTradeLogTopN] = useState(1);
  const [tradeLogLoading, setTradeLogLoading] = useState(false);

  // Phase optimizer state
  const [chains, setChains] = useState<ChainSummary[]>([]);
  const [expandedChain, setExpandedChain] = useState<string | null>(null);
  const [chainPhases, setChainPhases] = useState<Record<string, PhaseData[]>>({});
  const [showNewChain, setShowNewChain] = useState(false);
  const [phaseObjective, setPhaseObjective] = useState("sharpe_ratio");
  const [phaseNTrials, setPhaseNTrials] = useState(50);
  const [phaseMethod, setPhaseMethod] = useState("bayesian");
  const [phaseMinTrades, setPhaseMinTrades] = useState(30);
  const [phaseParamSpace, setPhaseParamSpace] = useState<ParamRange[]>([]);
  const [showNextPhase, setShowNextPhase] = useState<string | null>(null);
  const [nextObjective, setNextObjective] = useState("sharpe_ratio");
  const [nextNTrials, setNextNTrials] = useState(50);
  const [nextMethod, setNextMethod] = useState("bayesian");
  const [phaseError, setPhaseError] = useState("");
  const phasePollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [walkForward, setWalkForward] = useState(false);
  const [wfPct, setWfPct] = useState(70);

  // Trading defaults
  const [balance, setBalance] = useState(10000);
  const [spread, setSpread] = useState(0.3);
  const [commission, setCommission] = useState(7);
  const [pointValue, setPointValue] = useState(1);

  // Running state
  const [runningId, setRunningId] = useState<number | null>(null);
  const [status, setStatus] = useState<OptimizationStatus | null>(null);
  const [result, setResult] = useState<OptimizationResponse | null>(null);
  const [error, setError] = useState("");
  const [pastRuns, setPastRuns] = useState<OptimizationListItem[]>([]);
  const [pastRunsOpen, setPastRunsOpen] = useState(false);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load strategies + sources
  useEffect(() => {
    api.get<StrategyList>("/api/strategies").then((d) => setStrategies(d.items)).catch(() => {});
    api.get<DataSourceList>("/api/data/sources").then((d) => setSources(d.items)).catch(() => {});
    api.get<OptimizationListItem[]>("/api/optimize").then(setPastRuns).catch(() => {});
    api.get<ChainSummary[]>("/api/optimize/phase/chains").then(setChains).catch(() => {});
  }, []);

  // When strategy changes, auto-extract params
  const handleStrategyChange = useCallback((stratId: number | null) => {
    setSelectedStrategy(stratId);
    if (!stratId) { setParamSpace([]); return; }
    const s = strategies.find((x) => x.id === stratId);
    if (s) setParamSpace(extractOptimizableParams(s));
  }, [strategies]);

  // When datasource changes, auto-fill instrument profile defaults
  const handleSourceChange = useCallback((srcId: number | null) => {
    setSelectedSource(srcId);
    if (!srcId) return;
    const src = sources.find((x) => x.id === srcId);
    if (src) {
      setSpread(src.default_spread ?? 0.3);
      setCommission(src.default_commission ?? 7);
      setPointValue(src.point_value ?? 1);
    }
  }, [sources]);

  // Robustness test
  const runRobustness = useCallback(async (optId: number) => {
    setRobustnessLoading(true);
    setRobustnessResult(null);
    try {
      const r = await api.post<RobustnessResult>(`/api/optimize/${optId}/robustness`, {
        n_windows: robustWindows,
        window_pct: robustWindowPct,
        min_trades: robustMinTrades,
        min_profit_factor: robustMinPF,
        min_sharpe: robustMinSharpe,
        initial_balance: balance,
        spread_points: spread,
        commission_per_lot: commission,
        point_value: pointValue,
      });
      setRobustnessResult(r);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Robustness test failed");
    } finally {
      setRobustnessLoading(false);
    }
  }, [robustWindows, robustWindowPct, robustMinTrades, robustMinPF, robustMinSharpe, balance, spread, commission, pointValue]);

  // Trade log export
  const loadTradeLog = useCallback(async (optId: number) => {
    setTradeLogLoading(true);
    setTradeLog(null);
    try {
      const r = await api.get<TradeLogResult>(`/api/optimize/${optId}/trades?top_n=${tradeLogTopN}`);
      setTradeLog(r);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Trade log failed to load");
    } finally {
      setTradeLogLoading(false);
    }
  }, [tradeLogTopN]);

  // Phase optimizer callbacks
  const loadChains = useCallback(async () => {
    try {
      const data = await api.get<ChainSummary[]>("/api/optimize/phase/chains");
      setChains(data);
    } catch { /* ignore */ }
  }, []);

  const loadChainPhases = useCallback(async (chainId: string) => {
    try {
      const phases = await api.get<PhaseData[]>(`/api/optimize/phase/chain/${chainId}`);
      setChainPhases((prev) => ({ ...prev, [chainId]: phases }));
      return phases;
    } catch { return []; }
  }, []);

  const startPhasePoll = useCallback((chainId: string, phaseId: number) => {
    if (phasePollRef.current) clearInterval(phasePollRef.current);
    phasePollRef.current = setInterval(async () => {
      try {
        const s = await api.get<{ status: string }>(`/api/optimize/phase/chain/${chainId}/${phaseId}/status`);
        if (s.status === "completed" || s.status === "failed") {
          if (phasePollRef.current) clearInterval(phasePollRef.current);
          phasePollRef.current = null;
          await loadChainPhases(chainId);
          await loadChains();
        }
      } catch {
        if (phasePollRef.current) clearInterval(phasePollRef.current);
        phasePollRef.current = null;
      }
    }, 1500);
  }, [loadChainPhases, loadChains]);

  const startPhaseChain = useCallback(async () => {
    if (!selectedStrategy || !selectedSource || phaseParamSpace.length === 0) {
      setPhaseError("Select a strategy, data source and configure param space above first.");
      return;
    }
    setPhaseError("");
    try {
      const resp = await api.post<PhaseData>("/api/optimize/phase/run", {
        strategy_id: selectedStrategy,
        datasource_id: selectedSource,
        param_space: phaseParamSpace,
        objective: phaseObjective,
        n_trials: phaseNTrials,
        method: phaseMethod,
        min_trades: phaseMinTrades,
        initial_balance: balance,
        spread_points: spread,
        commission_per_lot: commission,
        point_value: pointValue,
      });
      setShowNewChain(false);
      await loadChains();
      setExpandedChain(resp.chain_id);
      setChainPhases((prev) => ({ ...prev, [resp.chain_id]: [resp] }));
      startPhasePoll(resp.chain_id, resp.id);
    } catch (e: unknown) {
      setPhaseError(e instanceof Error ? e.message : "Failed to start phase chain");
    }
  }, [selectedStrategy, selectedSource, phaseParamSpace, phaseObjective, phaseNTrials, phaseMethod, phaseMinTrades, balance, spread, commission, pointValue, loadChains, startPhasePoll]);

  const addNextPhase = useCallback(async (chainId: string) => {
    if (phaseParamSpace.length === 0) {
      setPhaseError("Configure the param space above, then click Add Next Phase.");
      return;
    }
    setPhaseError("");
    try {
      const resp = await api.post<PhaseData>(`/api/optimize/phase/chain/${chainId}/next`, {
        param_space: phaseParamSpace,
        objective: nextObjective,
        n_trials: nextNTrials,
        method: nextMethod,
        min_trades: phaseMinTrades,
      });
      setShowNextPhase(null);
      await loadChainPhases(chainId);
      await loadChains();
      startPhasePoll(chainId, resp.id);
    } catch (e: unknown) {
      setPhaseError(e instanceof Error ? e.message : "Failed to add next phase");
    }
  }, [phaseParamSpace, nextObjective, nextNTrials, nextMethod, phaseMinTrades, loadChainPhases, loadChains, startPhasePoll]);

  // Poll for progress
  const startPolling = useCallback((optId: number) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const s = await api.get<OptimizationStatus>(`/api/optimize/status/${optId}`);
        setStatus(s);
        if (s.status === "completed" || s.status === "failed") {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          if (s.status === "completed") {
            const r = await api.get<OptimizationResponse>(`/api/optimize/${optId}`);
            setResult(r);
          }
          setRunningId(null);
          api.get<OptimizationListItem[]>("/api/optimize").then(setPastRuns).catch(() => {});
        }
      } catch {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
      }
    }, 1000);
  }, []);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (phasePollRef.current) clearInterval(phasePollRef.current);
    };
  }, []);

  const runOptimization = async () => {
    if (!selectedStrategy || !selectedSource || paramSpace.length === 0) return;
    setError("");
    setResult(null);
    setStatus(null);
    try {
      const resp = await api.post<{ id: number }>("/api/optimize/run", {
        strategy_id: selectedStrategy,
        datasource_id: selectedSource,
        param_space: paramSpace,
        objective,
        n_trials: nTrials,
        min_trades: minTrades,
        method,
        initial_balance: balance,
        spread_points: spread,
        commission_per_lot: commission,
        point_value: pointValue,
        walk_forward: walkForward,
        wf_in_sample_pct: wfPct,
        ...(useSecondary && {
          secondary_objective: secondaryObjective,
          secondary_threshold: secondaryThreshold,
          secondary_operator: secondaryOperator,
        }),
      });
      setRunningId(resp.id);
      startPolling(resp.id);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to start optimization");
    }
  };

  const applyBestParams = async (optId: number) => {
    try {
      await api.post(`/api/optimize/${optId}/apply`, {});
      setError("");
      alert("Best parameters applied to strategy!");
    } catch {
      setError("Failed to apply params");
    }
  };

  const viewPastResult = async (optId: number) => {
    try {
      const r = await api.get<OptimizationResponse>(`/api/optimize/${optId}`);
      setResult(r);
      setStatus(null);
    } catch {
      setError("Failed to load result");
    }
  };

  const handleDeleteOptimization = async (optId: number) => {
    if (!confirm("Delete this optimization run?")) return;
    try {
      await api.delete(`/api/optimize/${optId}`);
      setPastRuns((prev) => prev.filter((r) => r.id !== optId));
    } catch {
      setError("Failed to delete optimization");
    }
  };

  const updateParam = (idx: number, field: keyof ParamRange, val: unknown) => {
    setParamSpace((prev) => prev.map((p, i) => (i === idx ? { ...p, [field]: val } : p)));
  };

  const removeParam = (idx: number) => {
    setParamSpace((prev) => prev.filter((_, i) => i !== idx));
  };

  const isRunning = runningId !== null;
  const canRun = !!selectedStrategy && !!selectedSource && paramSpace.length > 0 && !isRunning;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Optimization Engine</h1>
          <p className="text-sm text-muted-foreground mt-1">Bayesian + Genetic hybrid parameter optimization</p>
        </div>
      </div>

      {/* ── Configuration Panel ── */}
      <Card className="bg-card-bg border-card-border">
        <CardContent className="p-5 space-y-5">
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">Configuration</h2>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label className="text-xs text-muted-foreground mb-1">Strategy</Label>
            <select
              value={selectedStrategy ?? ""}
              onChange={(e) => handleStrategyChange(Number(e.target.value) || null)}
              className="w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm outline-none focus:border-accent"
            >
              <option value="">Select strategy...</option>
              {strategies.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </div>
          <div>
            <Label className="text-xs text-muted-foreground mb-1">Data Source</Label>
            <select
              value={selectedSource ?? ""}
              onChange={(e) => handleSourceChange(Number(e.target.value) || null)}
              className="w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm outline-none focus:border-accent"
            >
              <option value="">Select data source...</option>
              {sources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.symbol} {s.timeframe} ({s.row_count.toLocaleString()} bars)
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="grid grid-cols-5 gap-4">
          <div>
            <Label className="text-xs text-muted-foreground mb-1">Objective</Label>
            <select value={objective} onChange={(e) => setObjective(e.target.value)}
              className="w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm outline-none focus:border-accent">
              <option value="sharpe_ratio">Sharpe Ratio</option>
              <option value="sharpe_sqrt_trades">Sharpe × √Trades</option>
              <option value="sqn">SQN (Van Tharp)</option>
              <option value="pf_times_sharpe">PF × Sharpe</option>
              <option value="expectancy_score">Expectancy Score</option>
              <option value="net_profit">Net Profit</option>
              <option value="profit_factor">Profit Factor</option>
              <option value="win_rate">Win Rate</option>
            </select>
          </div>
          <div>
            <Label className="text-xs text-muted-foreground mb-1">Method</Label>
            <select value={method} onChange={(e) => setMethod(e.target.value)}
              className="w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm outline-none focus:border-accent">
              <option value="bayesian">Bayesian (Optuna)</option>
              <option value="genetic">Genetic Algorithm</option>
              <option value="hybrid">Hybrid (Bayesian + Genetic)</option>
            </select>
          </div>
          <div>
            <Label className="text-xs text-muted-foreground mb-1">Trials</Label>
            <input type="number" value={nTrials} min={10} max={1000} onChange={(e) => setNTrials(Number(e.target.value))}
              className="w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm outline-none focus:border-accent" />
          </div>
          <div>
            <Label className="text-xs text-muted-foreground mb-1">Min Trades</Label>
            <input type="number" value={minTrades} min={5} max={500} onChange={(e) => setMinTrades(Number(e.target.value))}
              className="w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm outline-none focus:border-accent"
              title="Minimum trades required — results with fewer trades are penalised" />
          </div>
          <div className="flex items-end gap-3">
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" checked={walkForward} onChange={(e) => setWalkForward(e.target.checked)}
                className="rounded accent-accent" />
              Walk-Forward
            </label>
            {walkForward && (
              <input type="number" value={wfPct} min={50} max={90} onChange={(e) => setWfPct(Number(e.target.value))}
                className="w-16 rounded-lg border border-card-border bg-input-bg px-2 py-1 text-xs outline-none" title="In-sample %" />
            )}
          </div>
        </div>

        {/* Secondary Objective Filter */}
        <div className="rounded-lg border border-card-border bg-background/40 p-3">
          <label className="flex items-center gap-2 cursor-pointer mb-0">
            <input
              type="checkbox"
              checked={useSecondary}
              onChange={e => setUseSecondary(e.target.checked)}
              className="rounded"
            />
            <span className="text-xs text-muted-foreground font-medium">Add secondary objective filter</span>
          </label>
          {useSecondary && (
            <div className="grid grid-cols-3 gap-3 mt-3">
              <div>
                <Label className="text-xs text-muted-foreground mb-1">Secondary Metric</Label>
                <select
                  value={secondaryObjective}
                  onChange={e => setSecondaryObjective(e.target.value)}
                  className="w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm outline-none focus:border-accent"
                >
                  {['sharpe_ratio','sharpe_sqrt_trades','sqn','pf_times_sharpe','expectancy_score','net_profit','profit_factor','win_rate']
                    .filter(o => o !== objective)
                    .map(o => (
                      <option key={o} value={o}>
                        {o === 'sharpe_ratio' ? 'Sharpe Ratio'
                          : o === 'sharpe_sqrt_trades' ? 'Sharpe × √Trades'
                          : o === 'sqn' ? 'SQN'
                          : o === 'pf_times_sharpe' ? 'PF × Sharpe'
                          : o === 'expectancy_score' ? 'Expectancy Score'
                          : o === 'net_profit' ? 'Net Profit'
                          : o === 'profit_factor' ? 'Profit Factor'
                          : 'Win Rate'}
                      </option>
                    ))}
                </select>
              </div>
              <div>
                <Label className="text-xs text-muted-foreground mb-1">Operator</Label>
                <select
                  value={secondaryOperator}
                  onChange={e => setSecondaryOperator(e.target.value as '>=' | '<=')}
                  className="w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm outline-none focus:border-accent"
                >
                  <option value=">=">≥ (at least)</option>
                  <option value="<=">≤ (at most)</option>
                </select>
              </div>
              <div>
                <Label className="text-xs text-muted-foreground mb-1">Threshold</Label>
                <input
                  type="number"
                  step="any"
                  value={secondaryThreshold}
                  onChange={e => setSecondaryThreshold(Number(e.target.value))}
                  className="w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm outline-none focus:border-accent"
                  placeholder="e.g. 500"
                />
              </div>
            </div>
          )}
        </div>

        <div className="grid grid-cols-4 gap-4">
          <div>
            <Label className="text-xs text-muted-foreground mb-1">Balance ($)</Label>
            <input type="number" value={balance} onChange={(e) => setBalance(Number(e.target.value))}
              className="w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm outline-none focus:border-accent" />
          </div>
          <div>
            <Label className="text-xs text-muted-foreground mb-1">Spread (pts)</Label>
            <input type="number" value={spread} step={0.1} onChange={(e) => setSpread(Number(e.target.value))}
              className="w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm outline-none focus:border-accent" />
          </div>
          <div>
            <Label className="text-xs text-muted-foreground mb-1">Commission ($)</Label>
            <input type="number" value={commission} onChange={(e) => setCommission(Number(e.target.value))}
              className={`w-full rounded-lg border px-3 py-2 text-sm outline-none focus:border-accent ${
                commission === 0 ? "border-yellow-500 bg-yellow-500/10" : "border-card-border bg-input-bg"
              }`} />
            {commission === 0 && (
              <p className="text-[10px] text-yellow-400 mt-1">⚠ Commission is 0 — results will be overstated</p>
            )}
          </div>
          <div>
            <Label className="text-xs text-muted-foreground mb-1">Point Value</Label>
            <input type="number" value={pointValue} step={0.01} onChange={(e) => setPointValue(Number(e.target.value))}
              className="w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm outline-none focus:border-accent" />
          </div>
        </div>
        </CardContent>
      </Card>

      {/* ── Parameter Space ── */}
      {paramSpace.length > 0 && (
        <Card className="bg-card-bg border-card-border">
          <CardContent className="p-5 space-y-4">
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">Parameter Space</h2>
          <div className="space-y-3">
            {paramSpace.map((p, i) => (
              <div key={i} className="flex items-center gap-3 rounded-lg border border-card-border bg-black/20 p-3">
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-medium text-accent">{p.label}</span>
                  <span className="text-xs text-muted-foreground ml-2">({p.param_type})</span>
                </div>
                <div className="flex items-center gap-2">
                  <Label className="text-xs text-muted-foreground">Min</Label>
                  <input type="number" value={p.min_val ?? 0}
                    onChange={(e) => updateParam(i, "min_val", Number(e.target.value))}
                    className="w-20 rounded border border-card-border bg-input-bg px-2 py-1 text-xs outline-none focus:border-accent" />
                  <Label className="text-xs text-muted-foreground">Max</Label>
                  <input type="number" value={p.max_val ?? 100}
                    onChange={(e) => updateParam(i, "max_val", Number(e.target.value))}
                    className="w-20 rounded border border-card-border bg-input-bg px-2 py-1 text-xs outline-none focus:border-accent" />
                  {p.param_type === "int" && (
                    <>
                      <Label className="text-xs text-muted-foreground">Step</Label>
                      <input type="number" value={p.step ?? 1}
                        onChange={(e) => updateParam(i, "step", Number(e.target.value))}
                        className="w-16 rounded border border-card-border bg-input-bg px-2 py-1 text-xs outline-none focus:border-accent" />
                    </>
                  )}
                  <Button variant="ghost" size="sm" onClick={() => removeParam(i)}
                    className="ml-2 h-auto p-1 text-muted-foreground hover:text-danger"><X className="w-3 h-3" /></Button>
                </div>
              </div>
            ))}
          </div>

          <div className="flex items-center gap-3 pt-2">
            <Button onClick={runOptimization} disabled={!canRun}>
              {isRunning ? "Running..." : <><Play className="w-4 h-4 mr-1.5" />Run Optimization ({nTrials} trials)</>}
            </Button>
            {isRunning && (
              <Button variant="outline" onClick={() => { setRunningId(null); if (pollRef.current) clearInterval(pollRef.current); }}
                className="border-danger/50 text-danger hover:bg-danger/10">
                <Square className="w-3.5 h-3.5 mr-1.5" />Cancel
              </Button>
            )}
          </div>
          </CardContent>
        </Card>
      )}

      {/* ── Live Progress ── */}
      {status && status.status === "running" && (
        <div className="rounded-xl border border-accent/30 bg-card-bg p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-accent">Optimization Running</h2>
            <span className="text-xs text-muted-foreground">{status.elapsed_seconds.toFixed(1)}s elapsed</span>
          </div>
          <div className="w-full bg-black/30 rounded-full h-3">
            <div className="bg-accent h-3 rounded-full transition-all duration-300"
              style={{ width: `${Math.min(status.progress, 100)}%` }} />
          </div>
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>Trial {status.current_trial} / {status.total_trials}</span>
            <span>{status.progress.toFixed(1)}%</span>
          </div>
          {status.best_score > -1e5 && (
            <div className="text-sm">
              Best score so far: <span className="text-accent font-semibold">{status.best_score.toFixed(4)}</span>
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="rounded-lg bg-red-500/10 border border-red-500/30 px-4 py-3 text-sm text-red-400">{error}</div>
      )}

      {/* ── Results ── */}
      {result && result.status === "completed" && (
        <div className="space-y-4">
          <div className="rounded-xl border border-success/30 bg-card-bg p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-success uppercase tracking-wide">Optimization Complete</h2>
              <Button variant="outline" size="sm" onClick={() => applyBestParams(result.id)}
                className="border-success/40 bg-success/20 text-success hover:bg-success/30">
                <CheckCircle2 className="w-3.5 h-3.5 mr-1.5" />Apply Best Params to Strategy
              </Button>
            </div>

            {/* Best params */}
            <div>
              <h3 className="text-xs text-muted-foreground mb-2">Best Parameters (Score: {result.best_score.toFixed(4)})</h3>
              <div className="flex flex-wrap gap-2">
                {Object.entries(result.best_params).map(([k, v]) => {
                  const label = paramSpace.find((p) => p.param_path === k)?.label || k;
                  return (
                    <span key={k} className="inline-flex items-center rounded-md bg-accent/10 text-accent px-2.5 py-1 text-xs font-medium">
                      {label}: {typeof v === "number" ? v.toFixed(v % 1 === 0 ? 0 : 2) : String(v)}
                    </span>
                  );
                })}
              </div>
            </div>

            {/* Param importance */}
            {Object.keys(result.param_importance).length > 0 && (
              <div>
                <h3 className="text-xs text-muted-foreground mb-2">Parameter Importance</h3>
                <div className="space-y-1.5">
                  {Object.entries(result.param_importance)
                    .sort(([, a], [, b]) => b - a)
                    .map(([k, v]) => {
                      const label = paramSpace.find((p) => p.param_path === k)?.label || k;
                      return (
                        <div key={k} className="flex items-center gap-3">
                          <span className="text-xs text-muted-foreground w-28 truncate">{label}</span>
                          <div className="flex-1 bg-black/30 rounded-full h-2">
                            <div className="bg-accent h-2 rounded-full" style={{ width: `${v * 100}%` }} />
                          </div>
                          <span className="text-xs text-muted-foreground w-12 text-right">{(v * 100).toFixed(1)}%</span>
                        </div>
                      );
                    })}
                </div>
              </div>
            )}
          </div>

          {/* Trial history table */}
          <Card className="bg-card-bg border-card-border">
            <CardContent className="p-5">
            <h3 className="text-xs text-muted-foreground mb-3 uppercase tracking-wide">Trial History ({result.history.length} trials)</h3>
            <div className="max-h-72 overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-card-bg">
                  <tr className="border-b border-card-border text-muted-foreground">
                    <th className="py-2 text-left px-2">#</th>
                    <th className="py-2 text-right px-2">Score</th>
                    <th className="py-2 text-right px-2">Trades</th>
                    <th className="py-2 text-right px-2">Win %</th>
                    <th className="py-2 text-right px-2">Net P&amp;L</th>
                    <th className="py-2 text-right px-2">Sharpe</th>
                    <th className="py-2 text-right px-2">SQN</th>
                    <th className="py-2 text-right px-2">PF</th>
                    <th className="py-2 text-right px-2">Neg Yrs</th>
                    <th className="py-2 text-left px-2">Params</th>
                  </tr>
                </thead>
                <tbody>
                  {[...result.history]
                    .sort((a, b) => b.score - a.score)
                    .slice(0, 50)
                    .map((t, i) => (
                      <tr key={i} className={`border-b border-card-border/50 ${i === 0 ? "text-accent font-medium" : ""}`}>
                        <td className="py-1.5 px-2">{t.trial_number + 1}</td>
                        <td className="py-1.5 px-2 text-right">{t.score.toFixed(4)}</td>
                        <td className="py-1.5 px-2 text-right">{t.stats.total_trades ?? "—"}</td>
                        <td className="py-1.5 px-2 text-right">{t.stats.win_rate?.toFixed(1) ?? "—"}%</td>
                        <td className={`py-1.5 px-2 text-right ${(t.stats.net_profit ?? 0) >= 0 ? "text-success" : "text-danger"}`}>
                          ${(t.stats.net_profit ?? 0).toFixed(0)}
                        </td>
                        <td className="py-1.5 px-2 text-right">{t.stats.sharpe_ratio?.toFixed(2) ?? "—"}</td>
                        <td className="py-1.5 px-2 text-right">{t.stats.sqn?.toFixed(2) ?? "—"}</td>
                        <td className="py-1.5 px-2 text-right">{t.stats.profit_factor?.toFixed(2) ?? "—"}</td>
                        <td className={`py-1.5 px-2 text-right ${(t.stats.negative_years ?? 0) > 0 ? "text-danger" : ""}`}>
                          {t.stats.negative_years ?? "—"}
                        </td>
                        <td className="py-1.5 px-2 text-muted-foreground truncate max-w-[200px]">
                          {Object.entries(t.params).map(([k, v]) => {
                            const lbl = paramSpace.find((p) => p.param_path === k)?.label || k.split(".").pop();
                            return `${lbl}=${typeof v === "number" ? (v % 1 === 0 ? v : v.toFixed(2)) : v}`;
                          }).join(", ")}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
            </CardContent>
          </Card>

          {/* Yearly PnL breakdown for best result */}
          {(() => {
            const best = [...result.history].sort((a, b) => b.score - a.score)[0];
            const yearly = best?.stats?.yearly_pnl as Record<string, number> | undefined;
            if (!yearly || Object.keys(yearly).length === 0) return null;
            const years = Object.keys(yearly).sort();
            const totalNeg = years.filter(y => yearly[y] < 0).length;
            return (
              <Card className="bg-card-bg border-card-border">
                <CardContent className="p-5">
                <h3 className="text-xs text-muted-foreground mb-3 uppercase tracking-wide">
                  Yearly P&amp;L — Best Trial
                  {totalNeg > 0 && (
                    <span className="ml-2 inline-flex rounded-full bg-danger/20 text-danger px-2 py-0.5 text-[10px] font-medium">
                      {totalNeg} negative {totalNeg === 1 ? "year" : "years"}
                    </span>
                  )}
                </h3>
                <div className="flex flex-wrap gap-2">
                  {years.map(y => (
                    <div key={y} className={`flex flex-col items-center rounded-lg px-3 py-2 border ${
                      yearly[y] >= 0
                        ? "border-success/30 bg-success/10 text-success"
                        : "border-danger/30 bg-danger/10 text-danger"
                    }`}>
                      <span className="text-[10px] font-medium mb-0.5">{y}</span>
                      <span className="text-sm font-bold">{yearly[y] >= 0 ? "+" : ""}{yearly[y].toFixed(0)}</span>
                    </div>
                  ))}
                </div>
                </CardContent>
              </Card>
            );
          })()}

          {/* ── Robustness Test ── */}
          <Card className="bg-card-bg border-card-border">
            <CardContent className="p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-xs text-muted-foreground uppercase tracking-wide font-semibold">
                Robustness Test
                {robustnessResult && (
                  <span className={`ml-2 inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium ${
                    robustnessResult.pass_rate >= 0.7 ? "bg-success/20 text-success"
                    : robustnessResult.pass_rate >= 0.5 ? "bg-yellow-500/20 text-yellow-400"
                    : "bg-danger/20 text-danger"
                  }`}>
                    {robustnessResult.windows_passed}/{robustnessResult.n_windows} windows passed ({(robustnessResult.pass_rate * 100).toFixed(0)}%)
                  </span>
                )}
              </h3>
              <Button variant="outline" size="sm"
                onClick={() => runRobustness(result.id)}
                disabled={robustnessLoading}
                className="border-accent/40 bg-accent/20 text-accent hover:bg-accent/30"
              >
                {robustnessLoading ? "Running…" : <><Play className="w-3.5 h-3.5 mr-1" />Run Robustness Test</>}
              </Button>
            </div>

            {/* Config row */}
            <div className="grid grid-cols-5 gap-3">
              <div>
                <Label className="text-xs text-muted-foreground mb-1">Windows</Label>
                <input type="number" value={robustWindows} min={3} max={30}
                  onChange={(e) => setRobustWindows(Number(e.target.value))}
                  className="w-full rounded-lg border border-card-border bg-input-bg px-2 py-1.5 text-xs outline-none focus:border-accent" />
              </div>
              <div>
                <Label className="text-xs text-muted-foreground mb-1">Window Size %</Label>
                <input type="number" value={robustWindowPct} min={10} max={80}
                  onChange={(e) => setRobustWindowPct(Number(e.target.value))}
                  className="w-full rounded-lg border border-card-border bg-input-bg px-2 py-1.5 text-xs outline-none focus:border-accent" />
              </div>
              <div>
                <Label className="text-xs text-muted-foreground mb-1">Min Trades</Label>
                <input type="number" value={robustMinTrades} min={1} max={200}
                  onChange={(e) => setRobustMinTrades(Number(e.target.value))}
                  className="w-full rounded-lg border border-card-border bg-input-bg px-2 py-1.5 text-xs outline-none focus:border-accent" />
              </div>
              <div>
                <Label className="text-xs text-muted-foreground mb-1">Min PF</Label>
                <input type="number" value={robustMinPF} min={0} max={5} step={0.1}
                  onChange={(e) => setRobustMinPF(Number(e.target.value))}
                  className="w-full rounded-lg border border-card-border bg-input-bg px-2 py-1.5 text-xs outline-none focus:border-accent" />
              </div>
              <div>
                <Label className="text-xs text-muted-foreground mb-1">Min Sharpe</Label>
                <input type="number" value={robustMinSharpe} min={-5} max={5} step={0.1}
                  onChange={(e) => setRobustMinSharpe(Number(e.target.value))}
                  className="w-full rounded-lg border border-card-border bg-input-bg px-2 py-1.5 text-xs outline-none focus:border-accent" />
              </div>
            </div>

            {/* Results table */}
            {robustnessResult && (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-card-border text-muted-foreground">
                      <th className="py-2 text-left px-2">#</th>
                      <th className="py-2 text-left px-2">From</th>
                      <th className="py-2 text-left px-2">To</th>
                      <th className="py-2 text-right px-2">Trades</th>
                      <th className="py-2 text-right px-2">Net P&amp;L</th>
                      <th className="py-2 text-right px-2">Sharpe</th>
                      <th className="py-2 text-right px-2">PF</th>
                      <th className="py-2 text-right px-2">SQN</th>
                      <th className="py-2 text-right px-2">DD%</th>
                      <th className="py-2 text-center px-2">Pass</th>
                    </tr>
                  </thead>
                  <tbody>
                    {robustnessResult.windows.map((w) => (
                      <tr key={w.window_index} className={`border-b border-card-border/50 ${w.passed ? "" : "opacity-60"}`}>
                        <td className="py-1.5 px-2 text-muted-foreground">{w.window_index + 1}</td>
                        <td className="py-1.5 px-2 text-muted-foreground">{w.date_from.slice(0, 10)}</td>
                        <td className="py-1.5 px-2 text-muted-foreground">{w.date_to.slice(0, 10)}</td>
                        <td className="py-1.5 px-2 text-right">{w.total_trades}</td>
                        <td className={`py-1.5 px-2 text-right ${w.net_profit >= 0 ? "text-success" : "text-danger"}`}>
                          {w.net_profit >= 0 ? "+" : ""}{w.net_profit.toFixed(0)}
                        </td>
                        <td className="py-1.5 px-2 text-right">{w.sharpe_ratio.toFixed(2)}</td>
                        <td className="py-1.5 px-2 text-right">{w.profit_factor.toFixed(2)}</td>
                        <td className="py-1.5 px-2 text-right">{w.sqn.toFixed(2)}</td>
                        <td className={`py-1.5 px-2 text-right ${w.max_drawdown_pct > 20 ? "text-danger" : ""}`}>
                          {w.max_drawdown_pct.toFixed(1)}%
                        </td>
                        <td className="py-1.5 px-2 text-center">
                          <span className={`inline-flex rounded-full w-5 h-5 items-center justify-center text-[10px] font-bold ${
                            w.passed ? "bg-success/20 text-success" : "bg-danger/20 text-danger"
                          }`}>{w.passed ? "✓" : "✗"}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            </CardContent>
          </Card>

          {/* ── Trade Log Analysis ── */}
          <Card className="bg-card-bg border-card-border">
            <CardContent className="p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-xs text-muted-foreground uppercase tracking-wide font-semibold">
                Trade Log Analysis
                {tradeLog && (
                  <span className="ml-2 text-muted-foreground font-normal font-sans normal-case tracking-normal">
                    — {tradeLog.total_trades} trades · trial #{tradeLog.trial_number + 1} · score {tradeLog.score.toFixed(4)}
                  </span>
                )}
              </h3>
              <div className="flex items-center gap-2">
                <Label className="text-xs text-muted-foreground">Top N trial:</Label>
                <input type="number" value={tradeLogTopN} min={1} max={20}
                  onChange={(e) => setTradeLogTopN(Number(e.target.value))}
                  className="w-14 rounded-lg border border-card-border bg-input-bg px-2 py-1 text-xs outline-none focus:border-accent" />
                <Button variant="outline" size="sm"
                  onClick={() => loadTradeLog(result.id)}
                  disabled={tradeLogLoading}
                  className="border-accent/40 bg-accent/20 text-accent hover:bg-accent/30"
                >
                  {tradeLogLoading ? "Loading…" : <><Play className="w-3.5 h-3.5 mr-1" />Load Trades</>}
                </Button>
              </div>
            </div>

            {tradeLog && (
              <div className="space-y-4">
                {/* By Direction */}
                <div className="grid grid-cols-3 gap-3">
                  {Object.entries(tradeLog.analysis.by_direction).map(([dir, g]) => (
                    <div key={dir} className="rounded-lg border border-card-border bg-black/20 p-3">
                      <div className="text-xs text-muted-foreground mb-1 capitalize font-medium">{dir}</div>
                      <div className="text-sm font-bold">{g.trades} trades</div>
                      <div className={`text-xs ${g.net_profit >= 0 ? "text-success" : "text-danger"}`}>
                        {g.net_profit >= 0 ? "+" : ""}{g.net_profit.toFixed(0)} | WR {g.win_rate.toFixed(1)}%
                      </div>
                    </div>
                  ))}
                </div>

                {/* By Hour */}
                <div>
                  <h4 className="text-xs text-muted-foreground mb-2 font-medium">Performance by Hour (UTC)</h4>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-card-border text-muted-foreground">
                          <th className="py-1.5 text-left px-2">Hour</th>
                          <th className="py-1.5 text-right px-2">Trades</th>
                          <th className="py-1.5 text-right px-2">Net P&amp;L</th>
                          <th className="py-1.5 text-right px-2">Win %</th>
                          <th className="py-1.5 text-left px-2" style={{ minWidth: 120 }}>P&amp;L Bar</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(() => {
                          const maxAbs = Math.max(
                            ...Object.values(tradeLog.analysis.by_hour).map((x) => Math.abs(x.net_profit)), 1
                          );
                          return Object.entries(tradeLog.analysis.by_hour)
                            .filter(([, g]) => g.trades > 0)
                            .sort(([a], [b]) => Number(a) - Number(b))
                            .map(([hour, g]) => (
                              <tr key={hour} className="border-b border-card-border/30">
                                <td className="py-1 px-2 font-mono">{String(Number(hour)).padStart(2, "0")}:00</td>
                                <td className="py-1 px-2 text-right">{g.trades}</td>
                                <td className={`py-1 px-2 text-right ${g.net_profit >= 0 ? "text-success" : "text-danger"}`}>
                                  {g.net_profit >= 0 ? "+" : ""}{g.net_profit.toFixed(0)}
                                </td>
                                <td className="py-1 px-2 text-right">{g.win_rate.toFixed(1)}%</td>
                                <td className="py-1 px-2">
                                  <div className="h-2 rounded-full overflow-hidden bg-black/20">
                                    <div
                                      className={`h-full rounded-full ${g.net_profit >= 0 ? "bg-success/60" : "bg-danger/60"}`}
                                      style={{ width: `${(Math.abs(g.net_profit) / maxAbs) * 100}%` }}
                                    />
                                  </div>
                                </td>
                              </tr>
                            ));
                        })()}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* By Day */}
                <div>
                  <h4 className="text-xs text-muted-foreground mb-2 font-medium">Performance by Day</h4>
                  <div className="grid grid-cols-7 gap-2">
                    {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day) => {
                      const g = tradeLog.analysis.by_day[day] ?? { trades: 0, net_profit: 0, win_rate: 0 };
                      return (
                        <div key={day} className={`rounded-lg border p-2 text-center ${
                          g.trades === 0
                            ? "border-card-border/30 opacity-30"
                            : g.net_profit >= 0
                            ? "border-success/30 bg-success/10"
                            : "border-danger/30 bg-danger/10"
                        }`}>
                          <div className="text-xs font-medium text-muted-foreground">{day}</div>
                          <div className="text-sm font-bold">{g.trades}</div>
                          <div className={`text-[10px] ${g.net_profit >= 0 ? "text-success" : "text-danger"}`}>
                            {g.net_profit >= 0 ? "+" : ""}{g.net_profit.toFixed(0)}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* ── Past Runs (Collapsible) ── */}
      {pastRuns.length > 0 && (() => {
        const [pastOpen, setPastOpen] = [pastRunsOpen, setPastRunsOpen];
        return (
        <Card className="bg-card-bg border-card-border">
          <CardContent className="p-0">
          <button
            onClick={() => setPastOpen(!pastOpen)}
            className="w-full flex items-center justify-between px-5 py-3 text-left hover:bg-muted/20 transition-colors"
          >
            <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide flex items-center gap-2">
              {pastOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
              Previous Optimizations
              <span className="text-muted-foreground/50 font-normal normal-case">({pastRuns.length})</span>
            </h2>
          </button>
          {pastOpen && (
          <div className="px-5 pb-4">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-card-border text-muted-foreground">
                <th className="py-2 text-left px-2">ID</th>
                <th className="py-2 text-left px-2">Strategy</th>
                <th className="py-2 text-left px-2">Objective</th>
                <th className="py-2 text-right px-2">Trials</th>
                <th className="py-2 text-left px-2">Status</th>
                <th className="py-2 text-right px-2">Best Score</th>
                <th className="py-2 text-left px-2">Date</th>
                <th className="py-2 text-right px-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {pastRuns.map((r) => (
                <tr key={r.id} className="border-b border-card-border/50">
                  <td className="py-1.5 px-2">#{r.id}</td>
                  <td className="py-1.5 px-2">{r.strategy_name}</td>
                  <td className="py-1.5 px-2 capitalize">{r.objective.replace("_", " ")}</td>
                  <td className="py-1.5 px-2 text-right">{r.n_trials}</td>
                  <td className="py-1.5 px-2">
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium ${
                      r.status === "completed" ? "bg-success/20 text-success" :
                      r.status === "running" ? "bg-accent/20 text-accent" :
                      "bg-danger/20 text-danger"
                    }`}>{r.status}</span>
                  </td>
                  <td className="py-1.5 px-2 text-right font-mono">{r.best_score.toFixed(4)}</td>
                  <td className="py-1.5 px-2 text-muted-foreground">{new Date(r.created_at).toLocaleDateString()}</td>
                  <td className="py-1.5 px-2 text-right flex items-center justify-end gap-1">
                    {r.status === "completed" && (
                      <Button variant="ghost" size="sm" onClick={() => viewPastResult(r.id)}
                        className="text-accent h-auto py-0.5 text-xs">View</Button>
                    )}
                    <Button variant="ghost" size="sm" onClick={() => handleDeleteOptimization(r.id)}
                      className="text-muted-foreground hover:text-danger h-auto py-0.5 text-xs"><Trash2 className="h-3 w-3" /></Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          )}
          </CardContent>
        </Card>
        );
      })()}

      {/* ── Phase Optimizer ── */}
      <Card className="bg-card-bg border-card-border">
        <CardContent className="p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">Phase Optimizer</h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              Multi-phase: lock entry params from Phase 1, optimize exits in Phase 2, etc.
            </p>
          </div>
          <Button variant="outline" size="sm"
            onClick={() => {
              setShowNewChain(!showNewChain);
              if (!showNewChain) {
                setPhaseParamSpace(paramSpace);
                setPhaseObjective(objective);
                setPhaseNTrials(nTrials);
                setPhaseMethod(method);
                setPhaseMinTrades(minTrades);
              }
            }}
            className="border-accent/40 bg-accent/20 text-accent hover:bg-accent/30"
          >
            {showNewChain ? "Cancel" : <><Plus className="w-3.5 h-3.5 mr-1" />New Chain</>}
          </Button>
        </div>

        {phaseError && (
          <div className="rounded-lg bg-red-500/10 border border-red-500/30 px-3 py-2 text-xs text-red-400">{phaseError}</div>
        )}

        {/* New Chain Form */}
        {showNewChain && (
          <div className="rounded-lg border border-accent/30 bg-accent/5 p-4 space-y-3">
            <h3 className="text-xs font-medium text-accent">New Phase Chain — Phase 1</h3>
            <p className="text-xs text-muted-foreground">
              Uses the current <strong>Strategy</strong> and <strong>Data Source</strong> selected above.
              Check which params to optimize in this first phase:
            </p>

            {paramSpace.length > 0 ? (
              <div className="space-y-1.5">
                {paramSpace.map((p, i) => (
                  <label key={i} className="flex items-center gap-2 text-xs cursor-pointer">
                    <input type="checkbox"
                      checked={phaseParamSpace.some((pp) => pp.param_path === p.param_path)}
                      onChange={(e) => {
                        setPhaseParamSpace((prev) =>
                          e.target.checked ? [...prev, p] : prev.filter((pp) => pp.param_path !== p.param_path)
                        );
                      }}
                      className="rounded accent-accent" />
                    <span className="text-accent font-medium">{p.label}</span>
                    <span className="text-muted-foreground">({p.min_val ?? 0} → {p.max_val ?? 100})</span>
                  </label>
                ))}
              </div>
            ) : (
              <p className="text-xs text-yellow-400">⚠ Configure a param space in the panel above first.</p>
            )}

            <div className="grid grid-cols-4 gap-3 pt-1">
              <div>
                <Label className="text-xs text-muted-foreground mb-1">Objective</Label>
                <select value={phaseObjective} onChange={(e) => setPhaseObjective(e.target.value)}
                  className="w-full rounded border border-card-border bg-input-bg px-2 py-1 text-xs outline-none">
                  {["sharpe_ratio","sharpe_sqrt_trades","sqn","pf_times_sharpe","expectancy_score","net_profit","profit_factor","win_rate"].map((o) => (
                    <option key={o} value={o}>{o.replace(/_/g, " ")}</option>
                  ))}
                </select>
              </div>
              <div>
                <Label className="text-xs text-muted-foreground mb-1">Method</Label>
                <select value={phaseMethod} onChange={(e) => setPhaseMethod(e.target.value)}
                  className="w-full rounded border border-card-border bg-input-bg px-2 py-1 text-xs outline-none">
                  <option value="bayesian">Bayesian</option>
                  <option value="genetic">Genetic</option>
                  <option value="hybrid">Hybrid</option>
                </select>
              </div>
              <div>
                <Label className="text-xs text-muted-foreground mb-1">Trials</Label>
                <input type="number" value={phaseNTrials} min={10}
                  onChange={(e) => setPhaseNTrials(Number(e.target.value))}
                  className="w-full rounded border border-card-border bg-input-bg px-2 py-1 text-xs outline-none" />
              </div>
              <div>
                <Label className="text-xs text-muted-foreground mb-1">Min Trades</Label>
                <input type="number" value={phaseMinTrades} min={5}
                  onChange={(e) => setPhaseMinTrades(Number(e.target.value))}
                  className="w-full rounded border border-card-border bg-input-bg px-2 py-1 text-xs outline-none" />
              </div>
            </div>

            <Button
              onClick={startPhaseChain}
              disabled={phaseParamSpace.length === 0 || !selectedStrategy || !selectedSource}
            >
              <Play className="w-4 h-4 mr-1.5" />Start Phase Chain
            </Button>
          </div>
        )}

        {/* Chains list */}
        {chains.length > 0 && (
          <div className="space-y-2">
            {chains.map((chain) => (
              <div key={chain.chain_id} className="rounded-lg border border-card-border overflow-hidden">
                {/* Chain header row */}
                <button
                  onClick={async () => {
                    if (expandedChain === chain.chain_id) {
                      setExpandedChain(null);
                    } else {
                      setExpandedChain(chain.chain_id);
                      if (!chainPhases[chain.chain_id]) await loadChainPhases(chain.chain_id);
                    }
                  }}
                  className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-black/10 transition"
                >
                  <div className="flex items-center gap-3">
                    <span className="text-xs font-mono text-muted-foreground">{chain.chain_id.slice(0, 8)}</span>
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium ${
                      chain.latest_status === "completed" ? "bg-success/20 text-success"
                      : chain.latest_status === "running" ? "bg-accent/20 text-accent"
                      : "bg-danger/20 text-danger"
                    }`}>{chain.latest_status}</span>
                    <span className="text-xs text-muted-foreground">{chain.n_phases} phase{chain.n_phases !== 1 ? "s" : ""}</span>
                    {chain.latest_score != null && (
                      <span className="text-xs">
                        score <span className="text-accent font-semibold">{chain.latest_score.toFixed(4)}</span>
                      </span>
                    )}
                  </div>
                  <span className="text-xs text-muted-foreground">{expandedChain === chain.chain_id ? "▲" : "▼"}</span>
                </button>

                {/* Expanded phase list */}
                {expandedChain === chain.chain_id && chainPhases[chain.chain_id] && (
                  <div className="border-t border-card-border bg-black/10 p-4 space-y-3">
                    {chainPhases[chain.chain_id].map((phase) => (
                      <div key={phase.id} className="rounded border border-card-border bg-card-bg p-3 space-y-2">
                        <div className="flex items-center gap-3 flex-wrap">
                          <span className="inline-flex rounded bg-accent/10 text-accent px-2 py-0.5 text-xs font-bold">
                            Phase {phase.phase_number}
                          </span>
                          <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium ${
                            phase.status === "completed" ? "bg-success/20 text-success"
                            : phase.status === "running" ? "bg-accent/20 text-accent"
                            : "bg-danger/20 text-danger"
                          }`}>{phase.status}</span>
                          <span className="text-xs text-muted-foreground">{phase.objective.replace(/_/g, " ")} · {phase.n_trials} trials · {phase.method}</span>
                          {phase.best_score != null && (
                            <span className="text-xs ml-auto">Score: <span className="text-success font-semibold">{phase.best_score.toFixed(4)}</span></span>
                          )}
                        </div>

                        {phase.best_params && Object.keys(phase.best_params).length > 0 && (
                          <div className="flex flex-wrap gap-1.5">
                            {Object.entries(phase.best_params).map(([k, v]) => (
                              <span key={k} className="inline-flex rounded bg-accent/10 text-accent px-2 py-0.5 text-[10px]">
                                {k.split(".").pop()}={typeof v === "number" ? (v % 1 === 0 ? v : (v as number).toFixed(2)) : String(v)}
                              </span>
                            ))}
                          </div>
                        )}

                        {phase.frozen_params && Object.keys(phase.frozen_params).length > 0 && (
                          <p className="text-[10px] text-muted-foreground">
                            🔒 Frozen: {Object.keys(phase.frozen_params).map((k) => k.split(".").pop()).join(", ")}
                          </p>
                        )}
                      </div>
                    ))}

                    {/* Add Next Phase */}
                    {chainPhases[chain.chain_id].at(-1)?.status === "completed" && (
                      <div>
                        {showNextPhase === chain.chain_id ? (
                          <div className="rounded border border-accent/30 bg-accent/5 p-3 space-y-3">
                            <h4 className="text-xs font-medium text-accent">
                              Phase {(chainPhases[chain.chain_id].at(-1)?.phase_number ?? 0) + 1} Config
                            </h4>
                            <p className="text-xs text-muted-foreground">Previous best params will be frozen. Select new params to optimize:</p>
                            {paramSpace.length > 0 ? (
                              <div className="space-y-1">
                                {paramSpace.map((p, i) => (
                                  <label key={i} className="flex items-center gap-2 text-xs cursor-pointer">
                                    <input type="checkbox"
                                      checked={phaseParamSpace.some((pp) => pp.param_path === p.param_path)}
                                      onChange={(e) => {
                                        setPhaseParamSpace((prev) =>
                                          e.target.checked ? [...prev, p] : prev.filter((pp) => pp.param_path !== p.param_path)
                                        );
                                      }}
                                      className="rounded accent-accent" />
                                    <span className="text-accent font-medium">{p.label}</span>
                                  </label>
                                ))}
                              </div>
                            ) : (
                              <p className="text-xs text-yellow-400">⚠ Configure param space above.</p>
                            )}
                            <div className="grid grid-cols-3 gap-2">
                              <div>
                                <Label className="text-[10px] text-muted-foreground mb-1">Objective</Label>
                                <select value={nextObjective} onChange={(e) => setNextObjective(e.target.value)}
                                  className="w-full rounded border border-card-border bg-input-bg px-2 py-1 text-xs outline-none">
                                  {["sharpe_ratio","sharpe_sqrt_trades","sqn","pf_times_sharpe","expectancy_score","net_profit","profit_factor","win_rate"].map((o) => (
                                    <option key={o} value={o}>{o.replace(/_/g, " ")}</option>
                                  ))}
                                </select>
                              </div>
                              <div>
                                <Label className="text-[10px] text-muted-foreground mb-1">Method</Label>
                                <select value={nextMethod} onChange={(e) => setNextMethod(e.target.value)}
                                  className="w-full rounded border border-card-border bg-input-bg px-2 py-1 text-xs outline-none">
                                  <option value="bayesian">Bayesian</option>
                                  <option value="genetic">Genetic</option>
                                  <option value="hybrid">Hybrid</option>
                                </select>
                              </div>
                              <div>
                                <Label className="text-[10px] text-muted-foreground mb-1">Trials</Label>
                                <input type="number" value={nextNTrials} min={10}
                                  onChange={(e) => setNextNTrials(Number(e.target.value))}
                                  className="w-full rounded border border-card-border bg-input-bg px-2 py-1 text-xs outline-none" />
                              </div>
                            </div>
                            <div className="flex gap-2">
                              <Button size="sm"
                                onClick={() => addNextPhase(chain.chain_id)}
                                disabled={phaseParamSpace.length === 0}
                              >
                                <Play className="w-3.5 h-3.5 mr-1" />Start Phase {(chainPhases[chain.chain_id].at(-1)?.phase_number ?? 0) + 1}
                              </Button>
                              <Button variant="outline" size="sm"
                                onClick={() => setShowNextPhase(null)}
                              >Cancel</Button>
                            </div>
                          </div>
                        ) : (
                          <Button variant="outline" size="sm"
                            onClick={() => {
                              setShowNextPhase(chain.chain_id);
                              setPhaseParamSpace(paramSpace);
                              setNextObjective(chainPhases[chain.chain_id].at(-1)?.objective ?? "sharpe_ratio");
                              setNextNTrials(nTrials);
                              setNextMethod(method);
                              setPhaseError("");
                            }}
                            className="border-accent/40 text-accent hover:bg-accent/10"
                          >
                            <Plus className="w-3.5 h-3.5 mr-1" />Add Phase {(chainPhases[chain.chain_id].at(-1)?.phase_number ?? 0) + 1}
                          </Button>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {chains.length === 0 && !showNewChain && (
          <div className="flex flex-col items-center justify-center py-10 text-center">
            <Settings2 className="h-8 w-8 text-muted-foreground/30 mb-3" />
            <p className="text-sm font-medium mb-1">No Phase Chains Yet</p>
            <p className="text-xs text-muted-foreground mb-4 max-w-sm">
              Create a multi-phase optimization chain to progressively refine your strategy parameters.
            </p>
            <Button size="sm" variant="outline" onClick={() => setShowNewChain(true)} className="gap-1.5">
              <Plus className="h-3.5 w-3.5" /> New Chain
            </Button>
          </div>
        )}
        </CardContent>
      </Card>

      <ChatHelpers />
    </div>
  );
}
