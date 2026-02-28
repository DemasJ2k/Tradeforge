"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import ChatHelpers from "@/components/ChatHelpers";
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

function extractOptimizableParams(strategy: Strategy): ParamRange[] {
  const params: ParamRange[] = [];
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
  const [method, setMethod] = useState("bayesian");
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

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load strategies + sources
  useEffect(() => {
    api.get<StrategyList>("/api/strategies").then((d) => setStrategies(d.items)).catch(() => {});
    api.get<DataSourceList>("/api/data/sources").then((d) => setSources(d.items)).catch(() => {});
    api.get<OptimizationListItem[]>("/api/optimize").then(setPastRuns).catch(() => {});
  }, []);

  // When strategy changes, auto-extract params
  const handleStrategyChange = useCallback((stratId: number | null) => {
    setSelectedStrategy(stratId);
    if (!stratId) { setParamSpace([]); return; }
    const s = strategies.find((x) => x.id === stratId);
    if (s) setParamSpace(extractOptimizableParams(s));
  }, [strategies]);

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

  useEffect(() => { return () => { if (pollRef.current) clearInterval(pollRef.current); }; }, []);

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
          <p className="text-sm text-muted mt-1">Bayesian + Genetic hybrid parameter optimization</p>
        </div>
      </div>

      {/* ── Configuration Panel ── */}
      <div className="rounded-xl border border-card-border bg-card-bg p-5 space-y-5">
        <h2 className="text-sm font-semibold text-muted uppercase tracking-wide">Configuration</h2>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-muted mb-1">Strategy</label>
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
            <label className="block text-xs text-muted mb-1">Data Source</label>
            <select
              value={selectedSource ?? ""}
              onChange={(e) => setSelectedSource(Number(e.target.value) || null)}
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

        <div className="grid grid-cols-4 gap-4">
          <div>
            <label className="block text-xs text-muted mb-1">Objective</label>
            <select value={objective} onChange={(e) => setObjective(e.target.value)}
              className="w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm outline-none focus:border-accent">
              <option value="sharpe_ratio">Sharpe Ratio</option>
              <option value="net_profit">Net Profit</option>
              <option value="profit_factor">Profit Factor</option>
              <option value="win_rate">Win Rate</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">Method</label>
            <select value={method} onChange={(e) => setMethod(e.target.value)}
              className="w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm outline-none focus:border-accent">
              <option value="bayesian">Bayesian (Optuna)</option>
              <option value="genetic">Genetic Algorithm</option>
              <option value="hybrid">Hybrid (Bayesian + Genetic)</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">Trials</label>
            <input type="number" value={nTrials} min={10} max={1000} onChange={(e) => setNTrials(Number(e.target.value))}
              className="w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm outline-none focus:border-accent" />
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
            <span className="text-xs text-muted font-medium">Add secondary objective filter</span>
          </label>
          {useSecondary && (
            <div className="grid grid-cols-3 gap-3 mt-3">
              <div>
                <label className="block text-xs text-muted mb-1">Secondary Metric</label>
                <select
                  value={secondaryObjective}
                  onChange={e => setSecondaryObjective(e.target.value)}
                  className="w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm outline-none focus:border-accent"
                >
                  {['sharpe_ratio','net_profit','profit_factor','win_rate']
                    .filter(o => o !== objective)
                    .map(o => (
                      <option key={o} value={o}>
                        {o === 'sharpe_ratio' ? 'Sharpe Ratio'
                          : o === 'net_profit' ? 'Net Profit'
                          : o === 'profit_factor' ? 'Profit Factor'
                          : 'Win Rate'}
                      </option>
                    ))}
                </select>
              </div>
              <div>
                <label className="block text-xs text-muted mb-1">Operator</label>
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
                <label className="block text-xs text-muted mb-1">Threshold</label>
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
            <label className="block text-xs text-muted mb-1">Balance ($)</label>
            <input type="number" value={balance} onChange={(e) => setBalance(Number(e.target.value))}
              className="w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm outline-none focus:border-accent" />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">Spread (pts)</label>
            <input type="number" value={spread} step={0.1} onChange={(e) => setSpread(Number(e.target.value))}
              className="w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm outline-none focus:border-accent" />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">Commission ($)</label>
            <input type="number" value={commission} onChange={(e) => setCommission(Number(e.target.value))}
              className="w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm outline-none focus:border-accent" />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">Point Value</label>
            <input type="number" value={pointValue} step={0.01} onChange={(e) => setPointValue(Number(e.target.value))}
              className="w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm outline-none focus:border-accent" />
          </div>
        </div>
      </div>

      {/* ── Parameter Space ── */}
      {paramSpace.length > 0 && (
        <div className="rounded-xl border border-card-border bg-card-bg p-5 space-y-4">
          <h2 className="text-sm font-semibold text-muted uppercase tracking-wide">Parameter Space</h2>
          <div className="space-y-3">
            {paramSpace.map((p, i) => (
              <div key={i} className="flex items-center gap-3 rounded-lg border border-card-border bg-black/20 p-3">
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-medium text-accent">{p.label}</span>
                  <span className="text-xs text-muted ml-2">({p.param_type})</span>
                </div>
                <div className="flex items-center gap-2">
                  <label className="text-xs text-muted">Min</label>
                  <input type="number" value={p.min_val ?? 0}
                    onChange={(e) => updateParam(i, "min_val", Number(e.target.value))}
                    className="w-20 rounded border border-card-border bg-input-bg px-2 py-1 text-xs outline-none focus:border-accent" />
                  <label className="text-xs text-muted">Max</label>
                  <input type="number" value={p.max_val ?? 100}
                    onChange={(e) => updateParam(i, "max_val", Number(e.target.value))}
                    className="w-20 rounded border border-card-border bg-input-bg px-2 py-1 text-xs outline-none focus:border-accent" />
                  {p.param_type === "int" && (
                    <>
                      <label className="text-xs text-muted">Step</label>
                      <input type="number" value={p.step ?? 1}
                        onChange={(e) => updateParam(i, "step", Number(e.target.value))}
                        className="w-16 rounded border border-card-border bg-input-bg px-2 py-1 text-xs outline-none focus:border-accent" />
                    </>
                  )}
                  <button onClick={() => removeParam(i)}
                    className="ml-2 text-xs text-muted hover:text-danger transition-colors">✕</button>
                </div>
              </div>
            ))}
          </div>

          <div className="flex items-center gap-3 pt-2">
            <button onClick={runOptimization} disabled={!canRun}
              className="rounded-lg bg-accent px-5 py-2 text-sm font-medium text-black disabled:opacity-40 hover:brightness-110 transition">
              {isRunning ? "Running..." : `▶ Run Optimization (${nTrials} trials)`}
            </button>
            {isRunning && (
              <button onClick={() => { setRunningId(null); if (pollRef.current) clearInterval(pollRef.current); }}
                className="rounded-lg border border-danger/50 px-4 py-2 text-sm text-danger hover:bg-danger/10 transition">
                Cancel
              </button>
            )}
          </div>
        </div>
      )}

      {/* ── Live Progress ── */}
      {status && status.status === "running" && (
        <div className="rounded-xl border border-accent/30 bg-card-bg p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-accent">Optimization Running</h2>
            <span className="text-xs text-muted">{status.elapsed_seconds.toFixed(1)}s elapsed</span>
          </div>
          <div className="w-full bg-black/30 rounded-full h-3">
            <div className="bg-accent h-3 rounded-full transition-all duration-300"
              style={{ width: `${Math.min(status.progress, 100)}%` }} />
          </div>
          <div className="flex items-center justify-between text-xs text-muted">
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
              <button onClick={() => applyBestParams(result.id)}
                className="rounded-lg bg-success/20 border border-success/40 px-4 py-1.5 text-xs text-success hover:bg-success/30 transition">
                Apply Best Params to Strategy
              </button>
            </div>

            {/* Best params */}
            <div>
              <h3 className="text-xs text-muted mb-2">Best Parameters (Score: {result.best_score.toFixed(4)})</h3>
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
                <h3 className="text-xs text-muted mb-2">Parameter Importance</h3>
                <div className="space-y-1.5">
                  {Object.entries(result.param_importance)
                    .sort(([, a], [, b]) => b - a)
                    .map(([k, v]) => {
                      const label = paramSpace.find((p) => p.param_path === k)?.label || k;
                      return (
                        <div key={k} className="flex items-center gap-3">
                          <span className="text-xs text-muted w-28 truncate">{label}</span>
                          <div className="flex-1 bg-black/30 rounded-full h-2">
                            <div className="bg-accent h-2 rounded-full" style={{ width: `${v * 100}%` }} />
                          </div>
                          <span className="text-xs text-muted w-12 text-right">{(v * 100).toFixed(1)}%</span>
                        </div>
                      );
                    })}
                </div>
              </div>
            )}
          </div>

          {/* Trial history table */}
          <div className="rounded-xl border border-card-border bg-card-bg p-5">
            <h3 className="text-xs text-muted mb-3 uppercase tracking-wide">Trial History ({result.history.length} trials)</h3>
            <div className="max-h-72 overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-card-bg">
                  <tr className="border-b border-card-border text-muted">
                    <th className="py-2 text-left px-2">#</th>
                    <th className="py-2 text-right px-2">Score</th>
                    <th className="py-2 text-right px-2">Trades</th>
                    <th className="py-2 text-right px-2">Win %</th>
                    <th className="py-2 text-right px-2">Net P&L</th>
                    <th className="py-2 text-right px-2">Sharpe</th>
                    <th className="py-2 text-right px-2">PF</th>
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
                        <td className="py-1.5 px-2 text-right">{t.stats.profit_factor?.toFixed(2) ?? "—"}</td>
                        <td className="py-1.5 px-2 text-muted truncate max-w-[200px]">
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
          </div>
        </div>
      )}

      {/* ── Past Runs ── */}
      {pastRuns.length > 0 && (
        <div className="rounded-xl border border-card-border bg-card-bg p-5">
          <h2 className="text-sm font-semibold text-muted uppercase tracking-wide mb-3">Previous Optimizations</h2>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-card-border text-muted">
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
                  <td className="py-1.5 px-2 text-muted">{new Date(r.created_at).toLocaleDateString()}</td>
                  <td className="py-1.5 px-2 text-right">
                    {r.status === "completed" && (
                      <button onClick={() => viewPastResult(r.id)}
                        className="text-accent hover:underline text-xs">View</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ChatHelpers />
    </div>
  );
}
