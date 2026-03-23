"use client";

import { useState, useEffect, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { api, API_BASE } from "@/lib/api";
import ChatHelpers from "@/components/ChatHelpers";
import { Loader2, ArrowLeft, Brain, Trash2, Play, BarChart3, GitCompare, RefreshCw, Download, Upload, Database, Zap, Target, ChevronRight, Signal } from "lucide-react";
import { toast } from "sonner";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type {
  MLModelListItem,
  MLModelDetail,
  DataSource,
} from "@/types";

/* ── types ────────────────────────────────────────── */
interface DabentoDataset {
  filename: string;
  symbol: string;
  timeframe: string;
  row_count: number;
  size_mb: number;
  path: string;
}

interface ModelPerformance {
  id: number;
  name: string;
  model_type: string;
  symbol: string;
  timeframe: string;
  level: number;
  train_accuracy: number | null;
  val_accuracy: number | null;
  val_f1: number | null;
  val_sharpe: number | null;
  n_features: number;
  trained_at: string | null;
}

/* ── tiny helpers ─────────────────────────────────── */
const pct = (v: number | null) => (v != null ? `${(v * 100).toFixed(1)}%` : "—");
const statusColor = (s: string) => {
  if (s === "ready") return "bg-green-500/20 text-green-400";
  if (s === "training") return "bg-blue-500/20 text-fa-accent animate-pulse";
  if (s === "failed") return "bg-red-500/20 text-red-400";
  return "bg-zinc-500/20 text-zinc-400";
};
const levelLabel = (l: number) =>
  l === 1 ? "L1: Adaptive Params" : l === 2 ? "L2: Signal Prediction" : "L3: Advanced ML";

/* ═══════════════════════════════════════════════════ */

export default function MLPage() {
  const searchParams = useSearchParams();

  /* ── state ──────────────────────────────────── */
  const [view, setView] = useState<"list" | "detail" | "compare" | "retrain" | "backtest" | "data">(() => {
    const v = searchParams.get("view");
    if (v === "backtest" || v === "retrain" || v === "data") return v;
    return "list";
  });
  const [models, setModels] = useState<MLModelListItem[]>([]);
  const [selected, setSelected] = useState<MLModelDetail | null>(null);
  const [dataSources, setDataSources] = useState<DataSource[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Compare state
  const [compareIds, setCompareIds] = useState<number[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [compareData, setCompareData] = useState<any>(null);

  // Walk-forward retrain
  const [retraining, setRetraining] = useState(false);

  // Meta-labeling
  const [metaTraining, setMetaTraining] = useState(false);

  // Databento datasets
  const [dabentoDatasets, setDabentoDatasets] = useState<DabentoDataset[]>([]);
  // Performance summary for charts
  const [perfSummary, setPerfSummary] = useState<ModelPerformance[]>([]);

  // Pipeline retrain state
  const [retrainRunning, setRetrainRunning] = useState<string | null>(null);
  const [retrainLog, setRetrainLog] = useState<string[]>([]);

  // Heatmap filter
  const [heatFilter, setHeatFilter] = useState("lightgbm");

  // Pipeline retrain handler
  const handlePipelineRetrain = async (pipeline: "scalping" | "expert", symbol: string) => {
    const key = `${pipeline}_${symbol}`;
    setRetrainRunning(key);
    setRetrainLog([`Starting ${pipeline} pipeline retrain for ${symbol}...`]);
    try {
      const result = await api.post<{ task_id?: string; status: string; message?: string }>(
        `/api/ml/retrain/${pipeline}`,
        { symbol }
      );
      if (result.task_id) {
        setRetrainLog(prev => [...prev, `Task started: ${result.task_id}`]);
        // Poll for completion
        const poll = setInterval(async () => {
          try {
            const m = await api.get<{ status: string; log?: string[] }>(`/api/ml/retrain/status/${result.task_id}`);
            if (m.log) setRetrainLog(m.log);
            if (m.status === "completed" || m.status === "failed") {
              clearInterval(poll);
              setRetrainRunning(null);
              toast[m.status === "completed" ? "success" : "error"](`${pipeline} retrain ${m.status}`);
              loadModels();
              loadPerfSummary();
            }
          } catch {
            clearInterval(poll);
            setRetrainRunning(null);
          }
        }, 3000);
        setTimeout(() => {
          clearInterval(poll);
          setRetrainRunning(null);
          toast.error("Training timed out after 10 minutes. Check ML Lab for status.");
          setRetrainLog(prev => [...prev, "Polling stopped — 10 minute timeout reached. Training may still be running on server."]);
        }, 600000);
      } else {
        toast.success(result.message || `${pipeline} retrain complete`);
        setRetrainRunning(null);
        loadModels();
        loadPerfSummary();
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Retrain failed");
      setRetrainLog(prev => [...prev, `Error: ${e instanceof Error ? e.message : "Unknown error"}`]);
      setRetrainRunning(null);
    }
  };

  /* ── loaders ────────────────────────────────── */
  const loadModels = useCallback(async () => {
    try {
      const data = await api.get<MLModelListItem[]>("/api/ml/models");
      setModels(data);
    } catch { /* ignore */ }
  }, []);

  const loadDabentoDatasets = useCallback(async () => {
    try {
      const data = await api.get<{ datasets: DabentoDataset[] }>("/api/ml/databento/datasets");
      setDabentoDatasets(data.datasets || []);
    } catch { /* ignore */ }
  }, []);

  const loadPerfSummary = useCallback(async () => {
    try {
      const data = await api.get<{ models: ModelPerformance[] }>("/api/ml/performance-summary");
      setPerfSummary(data.models || []);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    loadModels();
    loadDabentoDatasets();
    loadPerfSummary();
    api.get<{ items: DataSource[] }>("/api/data/sources").then(r => setDataSources(r.items || [])).catch(console.error);
  }, [loadModels, loadDabentoDatasets, loadPerfSummary]);

  const openDetail = async (id: number) => {
    try {
      const m = await api.get<MLModelDetail>(`/api/ml/models/${id}`);
      setSelected(m);
      setView("detail");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Load failed");
    }
  };

  /* ── delete model ───────────────────────────── */
  const handleDelete = async (id: number) => {
    try {
      await api.delete(`/api/ml/models/${id}`);
      toast.success("Model deleted");
      loadModels();
      loadPerfSummary();
      if (selected?.id === id) {
        setSelected(null);
        setView("list");
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Delete failed";
      toast.error("Delete failed", { description: msg });
      setError(msg);
    }
  };

  /* ── compare models ────────────────────────── */
  const toggleCompare = (id: number) => {
    setCompareIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const handleCompare = async () => {
    if (compareIds.length < 2) {
      setError("Select at least 2 models to compare");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const data = await api.get(`/api/ml/compare?model_ids=${compareIds.join(",")}`);
      setCompareData(data);
      setView("compare");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Compare failed");
    } finally {
      setLoading(false);
    }
  };

  /* ── walk-forward retrain ──────────────────── */
  const handleRetrain = async () => {
    if (!selected) return;
    setRetraining(true);
    setError("");
    try {
      const result = await api.post<MLModelDetail>(
        `/api/ml/retrain-wf/${selected.id}?n_folds=5`,
        {}
      );
      setSelected(result);
      loadModels();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Walk-forward retrain failed");
    } finally {
      setRetraining(false);
    }
  };

  /* ── purged k-fold retrain ──────────────────── */
  const handlePurgedRetrain = async () => {
    if (!selected) return;
    setRetraining(true);
    setError("");
    try {
      const result = await api.post<MLModelDetail>(
        `/api/ml/retrain-purged/${selected.id}?n_folds=5&embargo_pct=0.02`,
        {}
      );
      setSelected(result);
      loadModels();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Purged k-fold retrain failed");
    } finally {
      setRetraining(false);
    }
  };

  /* ── meta-labeling train ──────────────────────── */
  const handleMetaTrain = async () => {
    if (!selected) return;
    setMetaTraining(true);
    setError("");
    try {
      // Find the datasource for this model
      const ds = dataSources.find(d => d.symbol === selected.symbol && d.timeframe === selected.timeframe)
        || dataSources[0];
      if (!ds) {
        setError("No data source found. Upload data first.");
        setMetaTraining(false);
        return;
      }
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const result = await api.post<any>("/api/ml/train-meta", {
        name: `Meta: ${selected.name}`,
        model_type: selected.model_type === "ensemble" ? "lightgbm" : selected.model_type,
        datasource_id: ds.id,
        symbol: selected.symbol,
        timeframe: selected.timeframe,
        target_type: selected.target_config?.type || "direction",
        target_horizon: selected.target_config?.horizon || 1,
        features: [],
        n_estimators: 200,
        max_depth: 6,
        learning_rate: 0.05,
        primary_model_id: selected.id,
      });
      if (result.status === "training" && result.id) {
        // Poll for completion
        const pollId = result.id;
        const poll = setInterval(async () => {
          try {
            const m = await api.get<MLModelDetail>(`/api/ml/models/${pollId}`);
            if (m.status === "ready" || m.status === "failed") {
              clearInterval(poll);
              setSelected(m);
              loadModels();
              setMetaTraining(false);
            }
          } catch {
            clearInterval(poll);
            setMetaTraining(false);
          }
        }, 3000);
        setTimeout(() => {
          clearInterval(poll);
          setMetaTraining(false);
          toast.error("Meta-training timed out after 10 minutes. Check ML Lab for status.");
        }, 600000);
      } else {
        setMetaTraining(false);
        loadModels();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Meta-labeling training failed");
      setMetaTraining(false);
    }
  };

  /* ═══════════════ RENDER ═══════════════════════ */
  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <h2 className="text-lg sm:text-xl font-semibold">ML Lab</h2>
          {view !== "list" && (
            <Button variant="ghost" size="sm" onClick={() => { setView("list"); setCompareData(null); }} className="gap-1 text-muted-foreground">
              <ArrowLeft className="h-3 w-3" /> Back to Models
            </Button>
          )}
        </div>
        <div className="flex gap-2 flex-wrap">
          <Button variant="outline" size="sm" className="gap-1.5" onClick={() => {
            const input = document.createElement("input");
            input.type = "file";
            input.accept = ".onnx,.joblib";
            input.onchange = async (e) => {
              const file = (e.target as HTMLInputElement).files?.[0];
              if (!file) return;
              const name = prompt("Model name:", file.name.replace(/\.(onnx|joblib)$/i, ""));
              if (!name) return;
              const formData = new FormData();
              formData.append("file", file);
              try {
                setLoading(true);
                const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
                const res = await fetch(`${API_BASE}/api/ml/upload-model?name=${encodeURIComponent(name)}`, {
                  method: "POST",
                  headers: token ? { Authorization: `Bearer ${token}` } : {},
                  body: formData,
                });
                if (!res.ok) throw new Error(await res.text());
                loadModels();
              } catch (err) {
                setError(err instanceof Error ? err.message : "Upload failed");
              } finally {
                setLoading(false);
              }
            };
            input.click();
          }}>
            <Upload className="h-4 w-4" /> Upload Model
          </Button>
          <Button variant="outline" size="sm" onClick={() => { setView("data"); loadDabentoDatasets(); }} className="gap-1.5">
            <Database className="h-4 w-4" /> Data Sources
          </Button>
          <Button variant="outline" size="sm" onClick={() => setView("backtest")} className="gap-1.5">
            <BarChart3 className="h-4 w-4" /> Backtest
          </Button>
          <Button size="sm" onClick={() => setView("retrain")} className="gap-1.5">
            <RefreshCw className="h-4 w-4" /> Retrain Pipelines
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>
      )}

      {view === "list" && (
      <>
      {/* Agent Pipeline Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {([
          { key: "scalping", icon: <Zap className="h-5 w-5" />, title: "Scalping Agent", desc: "XGBoost + LightGBM ensemble · M5 timeframe · Session-filtered", symbols: ["XAUUSD", "US30"], color: "text-amber-400", borderColor: "border-amber-500/20 hover:border-amber-500/40" },
          { key: "expert", icon: <Brain className="h-5 w-5" />, title: "Expert Agent", desc: "XGB + LGB + LSTM + Meta-labeler + Regime · Multi-TF · News-aware", symbols: ["XAUUSD", "US30", "BTCUSD"], color: "text-cyan-400", borderColor: "border-cyan-500/20 hover:border-cyan-500/40" },
        ]).map(({ key, icon, title, desc, symbols, color, borderColor }) => {
          const ready = models.filter(m => m.status === "ready").length;
          return (
            <Card key={key} className={`bg-card-bg ${borderColor} transition-colors cursor-pointer`} onClick={() => setView("retrain")}>
              <CardContent className="p-5">
                <div className="flex items-center gap-3 mb-3">
                  <div className={`h-10 w-10 rounded-xl bg-background/80 flex items-center justify-center ${color}`}>{icon}</div>
                  <div>
                    <h3 className={`text-sm font-semibold ${color}`}>{title}</h3>
                    <p className="text-xs text-muted-foreground mt-0.5">{desc}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                  {symbols.map(s => (
                    <Badge key={s} variant="secondary" className="text-[10px] bg-background/80">{s}</Badge>
                  ))}
                  <span className="ml-auto text-xs text-muted-foreground">{ready} models ready</span>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Performance Comparison Bar Chart */}
      {perfSummary.length > 0 && (
        <Card className="bg-card-bg border-card-border">
          <CardContent className="p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold flex items-center gap-2">
                <BarChart3 className="h-4 w-4 text-accent" /> Model Performance Comparison
              </h3>
              <span className="text-[10px] text-muted-foreground">{perfSummary.length} models</span>
            </div>
            <div className="space-y-2 max-h-[300px] overflow-y-auto">
              {perfSummary
                .sort((a, b) => (b.val_accuracy || 0) - (a.val_accuracy || 0))
                .slice(0, 20)
                .map(m => {
                  const valAcc = m.val_accuracy || 0;
                  const trainAcc = m.train_accuracy || 0;
                  const barWidth = Math.max(valAcc * 100, 2);
                  const isOverfit = trainAcc - valAcc > 0.15;
                  return (
                    <div key={m.id} className="flex items-center gap-3 group cursor-pointer hover:bg-background/50 rounded-lg px-2 py-1.5 transition-colors"
                      onClick={() => openDetail(m.id)}>
                      <div className="w-40 min-w-[160px] truncate">
                        <div className="text-xs font-medium truncate">{m.name}</div>
                        <div className="text-[10px] text-muted-foreground">{m.symbol} {m.timeframe} · {m.model_type}</div>
                      </div>
                      <div className="flex-1 flex items-center gap-2">
                        <div className="flex-1 h-5 bg-background/50 rounded-full overflow-hidden relative">
                          <div className="h-full rounded-full bg-gradient-to-r from-accent/80 to-accent transition-all"
                            style={{ width: `${barWidth}%` }} />
                          <div className="absolute inset-0 flex items-center justify-center text-[10px] font-semibold text-white mix-blend-difference">
                            {pct(valAcc)}
                          </div>
                        </div>
                        {isOverfit && (
                          <Badge variant="secondary" className="text-[9px] bg-orange-500/20 text-orange-400 px-1 py-0 shrink-0">overfit</Badge>
                        )}
                      </div>
                      <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/30 group-hover:text-accent transition-colors shrink-0" />
                    </div>
                  );
                })}
            </div>
          </CardContent>
        </Card>
      )}
      {/* Symbol × Timeframe Accuracy Heatmap */}
      {perfSummary.length > 0 && (() => {
        const heatSymbols = [...new Set(perfSummary.map(m => m.symbol))].sort();
        const heatTfs = ["M1", "M5", "M15", "H1", "H4"].filter(tf => perfSummary.some(m => m.timeframe === tf));
        const heatTypes = [...new Set(perfSummary.map(m => m.model_type))].sort();
        const filteredPerf = heatFilter ? perfSummary.filter(m => m.model_type === heatFilter) : perfSummary;
        const cellColor = (acc: number | null) => {
          if (acc === null) return "bg-zinc-800/50 text-muted-foreground/40";
          if (acc > 0.60) return "bg-green-500/40 text-green-300 font-semibold";
          if (acc > 0.55) return "bg-green-500/20 text-green-400";
          if (acc > 0.52) return "bg-emerald-500/10 text-emerald-400";
          if (acc > 0.50) return "bg-yellow-500/15 text-yellow-400";
          return "bg-red-500/15 text-red-400";
        };
        return (
          <Card className="bg-card-bg border-card-border">
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold flex items-center gap-2">
                  <Signal className="h-4 w-4 text-purple-400" /> Accuracy Heatmap
                </h3>
                <div className="flex gap-1">
                  {heatTypes.map(t => (
                    <button key={t} onClick={() => setHeatFilter(t)}
                      className={`px-2 py-0.5 rounded text-[10px] transition-colors ${heatFilter === t ? "bg-accent/20 text-accent border border-accent/40" : "text-muted-foreground hover:text-foreground border border-transparent"}`}>
                      {t}
                    </button>
                  ))}
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr>
                      <th className="text-left text-muted-foreground font-normal pb-2 pr-3">Symbol</th>
                      {heatTfs.map(tf => (
                        <th key={tf} className="text-center text-muted-foreground font-normal pb-2 px-2 min-w-[56px]">{tf}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {heatSymbols.map(sym => (
                      <tr key={sym}>
                        <td className="font-medium text-foreground py-1 pr-3">{sym}</td>
                        {heatTfs.map(tf => {
                          const best = filteredPerf
                            .filter(m => m.symbol === sym && m.timeframe === tf)
                            .sort((a, b) => (b.val_accuracy ?? 0) - (a.val_accuracy ?? 0))[0];
                          const acc = best?.val_accuracy ?? null;
                          return (
                            <td key={tf} className={`text-center py-1 px-2 rounded cursor-pointer hover:ring-1 hover:ring-accent/40 transition-all ${cellColor(acc)}`}
                              onClick={() => best && openDetail(best.id)}>
                              {acc !== null ? `${(acc * 100).toFixed(1)}%` : "—"}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        );
      })()}
      </>
      )}

      {/* ── MODEL LIST ──────────────────────────── */}
      {view === "list" && (
        <Card className="bg-card-bg border-card-border">
          <CardContent className="p-5">
          <h3 className="text-sm font-medium text-muted-foreground mb-4">Trained Models ({models.length})</h3>
          {/* Compare controls */}
          {models.length >= 2 && (
            <div className="flex items-center gap-3 mb-4">
              <Button
                variant="outline"
                size="sm"
                onClick={handleCompare}
                disabled={compareIds.length < 2 || loading}
                className="gap-1.5 border-accent/40 text-accent hover:bg-accent/10"
              >
                <GitCompare className="h-3.5 w-3.5" />
                Compare {compareIds.length > 0 ? `(${compareIds.length})` : ""}
              </Button>
              {compareIds.length > 0 && (
                <button onClick={() => setCompareIds([])} className="text-xs text-muted-foreground hover:text-foreground">
                  Clear selection
                </button>
              )}
            </div>
          )}
          {models.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Brain className="h-10 w-10 text-muted-foreground/30 mb-4" />
              <h3 className="text-lg font-medium mb-2">No Models Yet</h3>
              <p className="text-sm text-muted-foreground mb-6 max-w-md">
                Use the Retrain Pipelines to train Scalping Agent and Expert Agent models,
                or upload pre-trained models.
              </p>
              <Button onClick={() => setView("retrain")} className="gap-1.5">
                <RefreshCw className="h-4 w-4" /> Retrain Pipelines
              </Button>
            </div>
          ) : loading ? (
            /* Loading skeleton */
            <div className="space-y-2">
              {[1, 2, 3, 4].map(i => (
                <div key={i} className="rounded-lg border border-card-border bg-background/50 p-4 animate-pulse">
                  <div className="flex items-center gap-3">
                    <div className="h-4 w-4 rounded bg-card-border" />
                    <div className="h-5 w-16 rounded bg-card-border" />
                    <div className="flex-1 space-y-1.5">
                      <div className="h-4 w-48 rounded bg-card-border" />
                      <div className="h-3 w-32 rounded bg-card-border/60" />
                    </div>
                    <div className="h-8 w-24 rounded bg-card-border hidden sm:block" />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="space-y-2">
              {models.map(m => {
                const modelTypeIcon = m.model_type === "rl_ppo" ? "RL" : m.model_type === "lstm" ? "LS" : m.model_type === "hmm_regime" ? "HM" : m.model_type.charAt(0).toUpperCase() + m.model_type.charAt(1);
                const isRegime = m.model_type === "hmm_regime";
                const isRL = m.model_type === "rl_ppo";
                return (
                <div key={m.id}
                  className="flex items-center justify-between gap-3 rounded-xl border border-card-border bg-background/50 p-3.5 hover:bg-background/80 hover:border-accent/20 cursor-pointer transition-all group"
                  onClick={() => openDetail(m.id)}>
                  <div className="flex items-center gap-3 min-w-0">
                    <input
                      type="checkbox"
                      checked={compareIds.includes(m.id)}
                      onChange={(e) => { e.stopPropagation(); toggleCompare(m.id); }}
                      onClick={(e) => e.stopPropagation()}
                      className="accent-accent h-3.5 w-3.5"
                    />
                    {/* Model type avatar */}
                    <div className={`h-8 w-8 rounded-lg flex items-center justify-center text-[10px] font-bold shrink-0 ${
                      isRegime ? "bg-amber-500/20 text-amber-400" :
                      isRL ? "bg-purple-500/20 text-purple-400" :
                      "bg-accent/15 text-accent"
                    }`}>
                      {modelTypeIcon}
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium truncate">{m.name}</span>
                        <Badge variant="secondary" className={`text-[10px] font-medium ${statusColor(m.status)}`}>{m.status}</Badge>
                        {isRegime && (
                          <Badge variant="secondary" className="text-[9px] bg-amber-500/15 text-amber-400 border-amber-500/20 px-1.5 py-0">
                            <Signal className="h-2.5 w-2.5 mr-0.5" />REGIME
                          </Badge>
                        )}
                        {m.name.startsWith("Meta:") && (
                          <Badge variant="secondary" className="text-[9px] bg-purple-500/20 text-purple-400 px-1 py-0">META</Badge>
                        )}
                      </div>
                      <div className="text-xs text-muted-foreground truncate mt-0.5">
                        {m.model_type} · {m.symbol || "—"} · {m.timeframe} · {m.n_features} features
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-3 sm:gap-5 shrink-0">
                    {/* Accuracy mini-bars */}
                    <div className="hidden sm:flex items-center gap-3">
                      <div className="text-right">
                        <div className="text-[10px] text-muted-foreground mb-0.5">Train</div>
                        <div className="flex items-center gap-1.5">
                          <div className="w-16 h-1.5 bg-background rounded-full overflow-hidden">
                            <div className="h-full bg-accent/60 rounded-full" style={{ width: `${(m.train_accuracy || 0) * 100}%` }} />
                          </div>
                          <span className="text-xs font-medium text-accent w-10 text-right">{pct(m.train_accuracy)}</span>
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-[10px] text-muted-foreground mb-0.5">Val</div>
                        <div className="flex items-center gap-1.5">
                          <div className="w-16 h-1.5 bg-background rounded-full overflow-hidden">
                            <div className="h-full bg-green-500/60 rounded-full" style={{ width: `${(m.val_accuracy || 0) * 100}%` }} />
                          </div>
                          <span className="text-xs font-medium text-green-400 w-10 text-right">{pct(m.val_accuracy)}</span>
                        </div>
                      </div>
                    </div>
                    <Button variant="outline" size="sm" onClick={(e) => { e.stopPropagation(); handleDelete(m.id); }}
                      className="text-red-400 border-red-500/30 hover:bg-red-500/10 h-7 gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <Trash2 className="h-3 w-3" />
                    </Button>
                    <ChevronRight className="h-4 w-4 text-muted-foreground/30 group-hover:text-accent transition-colors" />
                  </div>
                </div>
                );
              })}
            </div>
          )}
          </CardContent>
        </Card>
      )}

      {view === "detail" && selected && (
        <div className="space-y-4">
          {/* Model header */}
          <Card className="bg-card-bg border-card-border">
            <CardContent className="p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-lg font-semibold">{selected.name}</h3>
                <div className="text-sm text-muted-foreground mt-1">
                  {levelLabel(selected.level)} · {selected.model_type} · {selected.symbol} {selected.timeframe}
                  {!!(selected.features_config as Record<string, unknown>)?.is_meta_model && (
                    <Badge variant="secondary" className="ml-2 text-[10px] bg-purple-500/20 text-purple-400">META-LABEL</Badge>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-3">
                <Badge variant="secondary" className={`text-xs font-medium ${statusColor(selected.status)}`}>{selected.status}</Badge>
                {selected.status === "ready" && (
                  <>
                  <Button onClick={handleRetrain} disabled={retraining} variant="outline" className="gap-1.5 border-accent/40 text-accent hover:bg-accent/10">
                    {retraining ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Retraining...</> : <><RefreshCw className="h-3.5 w-3.5" /> Walk-Forward</>}
                  </Button>
                  <Button onClick={handlePurgedRetrain} disabled={retraining} variant="outline" className="gap-1.5 border-blue-500/40 text-blue-400 hover:bg-blue-500/10">
                    {retraining ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Retraining...</> : <><RefreshCw className="h-3.5 w-3.5" /> Purged K-Fold</>}
                  </Button>
                  <Button onClick={handleMetaTrain} disabled={metaTraining || retraining} variant="outline" className="gap-1.5 border-purple-500/40 text-purple-400 hover:bg-purple-500/10">
                    {metaTraining ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Training Meta...</> : <><Brain className="h-3.5 w-3.5" /> Meta-Label</>}
                  </Button>
                  <Button onClick={() => {
                    const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
                    const url = `${API_BASE}/api/ml/export/${selected.id}?format=joblib`;
                    window.open(url + (token ? `&token=${token}` : ""), "_blank");
                  }} variant="outline" className="gap-1.5 border-card-border">
                    <Download className="h-3.5 w-3.5" /> Export
                  </Button>
                  </>
                )}
              </div>
            </div>
            {selected.error_message && (
              <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
                {selected.error_message}
              </div>
            )}
            </CardContent>
          </Card>

          {/* Metrics */}
          {selected.status === "ready" && (
            <div className="grid grid-cols-2 gap-4">
              <Card className="bg-card-bg border-card-border">
                <CardContent className="p-5">
                <h4 className="text-sm font-medium text-fa-accent mb-3">Training Metrics</h4>
                <div className="space-y-2">
                  {Object.entries(selected.train_metrics).map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between">
                      <span className="text-xs text-muted-foreground capitalize">{k.replace(/_/g, " ")}</span>
                      <span className="text-sm font-medium">{typeof v === "number" ? (v < 1 ? pct(v) : v.toFixed(4)) : String(v)}</span>
                    </div>
                  ))}
                </div>
                </CardContent>
              </Card>
              <Card className="bg-card-bg border-card-border">
                <CardContent className="p-5">
                <h4 className="text-sm font-medium text-green-400 mb-3">Validation Metrics</h4>
                <div className="space-y-2">
                  {Object.entries(selected.val_metrics)
                    .filter(([, v]) => typeof v === "number" || typeof v === "string")
                    .map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between">
                      <span className="text-xs text-muted-foreground capitalize">{k.replace(/_/g, " ")}</span>
                      <span className="text-sm font-medium">{typeof v === "number" ? (Math.abs(v) < 1 ? pct(v) : v.toFixed(4)) : String(v)}</span>
                    </div>
                  ))}
                  {/* CV summary (walk-forward or purged k-fold) */}
                  {selected.val_metrics.walk_forward && (
                    <div className="pt-2 border-t border-card-border">
                      <span className="text-xs text-blue-400 font-medium">Walk-Forward CV</span>
                      <div className="flex justify-between text-xs mt-1">
                        <span className="text-muted-foreground">Avg Accuracy</span>
                        <span>{pct((selected.val_metrics.walk_forward as unknown as {avg_accuracy: number}).avg_accuracy)}</span>
                      </div>
                      <div className="flex justify-between text-xs">
                        <span className="text-muted-foreground">Std</span>
                        <span>{((selected.val_metrics.walk_forward as unknown as {std_accuracy: number}).std_accuracy * 100).toFixed(2)}%</span>
                      </div>
                    </div>
                  )}
                  {selected.val_metrics.purged_kfold && (
                    <div className="pt-2 border-t border-card-border">
                      <span className="text-xs text-purple-400 font-medium">Purged K-Fold CV</span>
                      <div className="flex justify-between text-xs mt-1">
                        <span className="text-muted-foreground">Avg Accuracy</span>
                        <span>{pct((selected.val_metrics.purged_kfold as unknown as {avg_accuracy: number}).avg_accuracy)}</span>
                      </div>
                      <div className="flex justify-between text-xs">
                        <span className="text-muted-foreground">Std</span>
                        <span>{((selected.val_metrics.purged_kfold as unknown as {std_accuracy: number}).std_accuracy * 100).toFixed(2)}%</span>
                      </div>
                    </div>
                  )}
                  {/* Meta-labeling stats */}
                  {!!(selected.features_config as Record<string, unknown>)?.is_meta_model && selected.val_metrics.meta_trades_taken != null && (
                    <div className="pt-2 border-t border-card-border">
                      <span className="text-xs text-purple-400 font-medium">Meta-Label Filter</span>
                      <div className="flex justify-between text-xs mt-1">
                        <span className="text-muted-foreground">Trades Taken</span>
                        <span>{selected.val_metrics.meta_trades_taken} / {selected.val_metrics.meta_trades_total}</span>
                      </div>
                      <div className="flex justify-between text-xs">
                        <span className="text-muted-foreground">Filter Rate</span>
                        <span>{pct(selected.val_metrics.meta_filter_rate as number)}</span>
                      </div>
                      <div className="flex justify-between text-xs">
                        <span className="text-muted-foreground">Filtered Accuracy</span>
                        <span className="text-green-400 font-medium">{pct(selected.val_metrics.meta_filtered_accuracy as number)}</span>
                      </div>
                    </div>
                  )}
                  {/* Optuna results */}
                  {selected.val_metrics.optuna && (
                    <div className="pt-2 border-t border-card-border">
                      <span className="text-xs text-amber-400 font-medium">Optuna Auto-Tuning</span>
                      <div className="flex justify-between text-xs mt-1">
                        <span className="text-muted-foreground">Best CV Score</span>
                        <span className="text-amber-400 font-medium">
                          {pct((selected.val_metrics.optuna as unknown as {best_value: number}).best_value)}
                        </span>
                      </div>
                      <div className="flex justify-between text-xs">
                        <span className="text-muted-foreground">Trials</span>
                        <span>{(selected.val_metrics.optuna as unknown as {n_trials: number}).n_trials}</span>
                      </div>
                      {(selected.val_metrics.optuna as unknown as {best_params: Record<string, number>}).best_params && (
                        <div className="mt-2 space-y-0.5">
                          <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Best Parameters</span>
                          {Object.entries((selected.val_metrics.optuna as unknown as {best_params: Record<string, number>}).best_params).map(([k, v]) => (
                            <div key={k} className="flex justify-between text-xs">
                              <span className="text-muted-foreground">{k}</span>
                              <span>{typeof v === "number" ? (v < 0.01 ? v.toExponential(2) : v.toFixed(4)) : String(v)}</span>
                            </div>
                          ))}
                        </div>
                      )}
                      {(selected.val_metrics.optuna as unknown as {param_importances: Record<string, number>}).param_importances &&
                        Object.keys((selected.val_metrics.optuna as unknown as {param_importances: Record<string, number>}).param_importances).length > 0 && (
                        <div className="mt-2 space-y-0.5">
                          <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Parameter Importance</span>
                          {Object.entries((selected.val_metrics.optuna as unknown as {param_importances: Record<string, number>}).param_importances).map(([k, v]) => (
                            <div key={k} className="flex items-center gap-2 text-xs">
                              <span className="text-muted-foreground w-28 truncate">{k}</span>
                              <div className="flex-1 h-1.5 bg-card-border rounded-full">
                                <div className="h-full bg-amber-400 rounded-full" style={{ width: `${(v as number) * 100}%` }} />
                              </div>
                              <span className="w-10 text-right">{pct(v as number)}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
                </CardContent>
              </Card>
            </div>
          )}

          {/* Feature Importance — Recharts bar chart */}
          {selected.feature_importance && Object.keys(selected.feature_importance).length > 0 && (() => {
            const fiData = Object.entries(selected.feature_importance)
              .slice(0, 15)
              .map(([name, imp]) => ({ name, importance: +(imp * 100).toFixed(2) }))
              .reverse(); // bottom-to-top for horizontal bar
            const barColors = ["#6366f1", "#818cf8", "#a5b4fc", "#8b5cf6", "#a78bfa", "#c084fc"];
            return (
              <Card className="bg-card-bg border-card-border">
                <CardContent className="p-5">
                  <h4 className="text-sm font-medium text-muted-foreground mb-3">Feature Importance (top 15)</h4>
                  <ResponsiveContainer width="100%" height={Math.max(fiData.length * 28, 200)}>
                    <BarChart data={fiData} layout="vertical" margin={{ left: 100, right: 20, top: 5, bottom: 5 }}>
                      <XAxis type="number" tick={{ fontSize: 11, fill: "#9ca3af" }} tickFormatter={v => `${v}%`} />
                      <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: "#9ca3af" }} width={95} />
                      <Tooltip
                        contentStyle={{ background: "#1f2937", border: "1px solid #374151", borderRadius: 8, fontSize: 12 }}
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        formatter={((value: number) => [`${value}%`, "Importance"]) as any}
                      />
                      <Bar dataKey="importance" radius={[0, 4, 4, 0]} barSize={18}>
                        {fiData.map((_, i) => (
                          <Cell key={i} fill={barColors[i % barColors.length]} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            );
          })()}

          {/* Config details */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Card className="bg-card-bg border-card-border">
              <CardContent className="p-4">
              <h4 className="text-xs font-medium text-muted-foreground mb-2">Target</h4>
              <div className="text-sm">
                {String((selected.target_config as Record<string,unknown>).type || "direction")} — {String((selected.target_config as Record<string,unknown>).horizon || 1)} bar(s)
              </div>
              </CardContent>
            </Card>
            <Card className="bg-card-bg border-card-border">
              <CardContent className="p-4">
              <h4 className="text-xs font-medium text-muted-foreground mb-2">Hyperparameters</h4>
              <div className="text-xs space-y-1">
                {Object.entries(selected.hyperparams).map(([k, v]) => (
                  <div key={k}><span className="text-muted-foreground">{k}:</span> {String(v)}</div>
                ))}
              </div>
              </CardContent>
            </Card>
            <Card className="bg-card-bg border-card-border">
              <CardContent className="p-4">
              <h4 className="text-xs font-medium text-muted-foreground mb-2">Timeline</h4>
              <div className="text-xs space-y-1">
                <div><span className="text-muted-foreground">Created:</span> {new Date(selected.created_at).toLocaleString()}</div>
                {selected.trained_at && <div><span className="text-muted-foreground">Trained:</span> {new Date(selected.trained_at).toLocaleString()}</div>}
              </div>
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {view === "compare" && compareData && compareData.models?.length > 0 && (
        <Card className="bg-card-bg border-card-border">
          <CardContent className="p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-accent flex items-center gap-2">
              <GitCompare className="h-4 w-4" /> Model Comparison
            </h3>
            <Button variant="ghost" size="sm" onClick={() => { setView("list"); setCompareData(null); setCompareIds([]); }}>
              Done
            </Button>
          </div>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="border-card-border">
                  <TableHead>Metric</TableHead>
                  {compareData.models.map((m: { id: number; name: string }) => (
                    <TableHead key={m.id} className="text-center">{m.name}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {/* Basic info rows */}
                {["model_type", "level"].map((key) => (
                  <TableRow key={key} className="border-card-border/50">
                    <TableCell className="text-xs text-muted-foreground capitalize">{key.replace(/_/g, " ")}</TableCell>
                    {compareData.models.map((m: Record<string, unknown>) => (
                      <TableCell key={String(m.id)} className="text-center text-sm">
                        {key === "level" ? levelLabel(m[key] as number) : String(m[key] ?? "—")}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
                {/* Train metrics */}
                {(() => {
                  const allKeys = new Set<string>();
                  compareData.models.forEach((m: { train_metrics: Record<string, unknown> }) =>
                    Object.keys(m.train_metrics || {}).forEach((k) => allKeys.add(k))
                  );
                  return Array.from(allKeys).map((k) => (
                    <TableRow key={`train-${k}`} className="border-card-border/50">
                      <TableCell className="text-xs text-muted-foreground">Train: {k.replace(/_/g, " ")}</TableCell>
                      {compareData.models.map((m: { id: number; train_metrics: Record<string, number> }) => {
                        const v = m.train_metrics?.[k];
                        return (
                          <TableCell key={m.id} className="text-center text-sm font-medium">
                            {typeof v === "number" ? (v < 1 ? pct(v) : v.toFixed(4)) : "—"}
                          </TableCell>
                        );
                      })}
                    </TableRow>
                  ));
                })()}
                {/* Val metrics */}
                {(() => {
                  const allKeys = new Set<string>();
                  compareData.models.forEach((m: { val_metrics: Record<string, unknown> }) =>
                    Object.keys(m.val_metrics || {}).forEach((k) => {
                      if (k !== "walk_forward") allKeys.add(k);
                    })
                  );
                  return Array.from(allKeys).map((k) => (
                    <TableRow key={`val-${k}`} className="border-card-border/50">
                      <TableCell className="text-xs text-muted-foreground">Val: {k.replace(/_/g, " ")}</TableCell>
                      {compareData.models.map((m: { id: number; val_metrics: Record<string, number> }) => {
                        const v = m.val_metrics?.[k];
                        return (
                          <TableCell key={m.id} className="text-center text-sm font-medium text-green-400">
                            {typeof v === "number" ? (v < 1 ? pct(v) : v.toFixed(4)) : "—"}
                          </TableCell>
                        );
                      })}
                    </TableRow>
                  ));
                })()}
              </TableBody>
            </Table>
          </div>
          </CardContent>
        </Card>
      )}

      {/* ── RETRAIN PIPELINES VIEW ────────────── */}
      {view === "retrain" && (
        <div className="space-y-4">
          {/* Scalping Pipeline */}
          <Card className="bg-card-bg border-amber-500/20">
            <CardContent className="p-5">
              <div className="flex items-center gap-3 mb-4">
                <div className="h-10 w-10 rounded-xl bg-amber-500/10 flex items-center justify-center">
                  <Zap className="h-5 w-5 text-amber-400" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-amber-400">Scalping Pipeline</h3>
                  <p className="text-xs text-muted-foreground">XGBoost + LightGBM ensemble for M5 timeframe</p>
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
                {["XAUUSD", "US30"].map(symbol => (
                  <div key={symbol} className="flex items-center justify-between rounded-lg border border-card-border bg-background/50 p-3">
                    <div>
                      <div className="text-sm font-medium">{symbol}</div>
                      <div className="text-xs text-muted-foreground">M5 · Session-filtered · ATR SL/TP</div>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      className="gap-1.5 border-amber-500/30 text-amber-400 hover:bg-amber-500/10"
                      disabled={retrainRunning !== null}
                      onClick={() => handlePipelineRetrain("scalping", symbol)}
                    >
                      {retrainRunning === `scalping_${symbol}` ? (
                        <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Training...</>
                      ) : (
                        <><RefreshCw className="h-3.5 w-3.5" /> Retrain</>
                      )}
                    </Button>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Expert Pipeline */}
          <Card className="bg-card-bg border-cyan-500/20">
            <CardContent className="p-5">
              <div className="flex items-center gap-3 mb-4">
                <div className="h-10 w-10 rounded-xl bg-cyan-500/10 flex items-center justify-center">
                  <Brain className="h-5 w-5 text-cyan-400" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-cyan-400">Expert Pipeline</h3>
                  <p className="text-xs text-muted-foreground">XGB + LGB + LSTM + Meta-labeler + Regime detection</p>
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
                {["XAUUSD", "US30", "BTCUSD"].map(symbol => (
                  <div key={symbol} className="flex items-center justify-between rounded-lg border border-card-border bg-background/50 p-3">
                    <div>
                      <div className="text-sm font-medium">{symbol}</div>
                      <div className="text-xs text-muted-foreground">Multi-TF · News · Regime</div>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      className="gap-1.5 border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/10"
                      disabled={retrainRunning !== null}
                      onClick={() => handlePipelineRetrain("expert", symbol)}
                    >
                      {retrainRunning === `expert_${symbol}` ? (
                        <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Training...</>
                      ) : (
                        <><RefreshCw className="h-3.5 w-3.5" /> Retrain</>
                      )}
                    </Button>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Training Log */}
          {retrainLog.length > 0 && (
            <Card className="bg-card-bg border-card-border">
              <CardContent className="p-5">
                <h4 className="text-sm font-medium text-muted-foreground mb-3">Training Log</h4>
                <div className="bg-background/80 rounded-lg p-3 max-h-[300px] overflow-y-auto font-mono text-xs space-y-1">
                  {retrainLog.map((line, i) => (
                    <div key={i} className="text-muted-foreground">{line}</div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* ── BACKTEST VIEW ───────────────────────── */}
      {view === "backtest" && (
        <div className="space-y-4">
          <Card className="bg-card-bg border-card-border">
            <CardContent className="p-5">
              <div className="flex items-center gap-3 mb-4">
                <BarChart3 className="h-5 w-5 text-accent" />
                <div>
                  <h3 className="text-sm font-semibold">Model Backtesting</h3>
                  <p className="text-xs text-muted-foreground">Run backtests on trained ML models to validate performance before deploying agents.</p>
                </div>
              </div>
              {models.filter(m => m.status === "ready").length === 0 ? (
                <div className="text-center py-8">
                  <Brain className="h-8 w-8 text-muted-foreground/30 mx-auto mb-3" />
                  <p className="text-sm text-muted-foreground">No trained models available for backtesting.</p>
                  <Button variant="outline" size="sm" className="mt-3" onClick={() => setView("retrain")}>
                    Train Models First
                  </Button>
                </div>
              ) : (
                <div className="space-y-2">
                  {models.filter(m => m.status === "ready").map(m => (
                    <div key={m.id} className="flex items-center justify-between rounded-lg border border-card-border bg-background/50 p-3 hover:border-accent/20 transition-colors">
                      <div className="flex items-center gap-3">
                        <div className="h-8 w-8 rounded-lg bg-accent/15 flex items-center justify-center text-[10px] font-bold text-accent">
                          {m.model_type.charAt(0).toUpperCase()}{m.model_type.charAt(1)}
                        </div>
                        <div>
                          <div className="text-sm font-medium">{m.name}</div>
                          <div className="text-xs text-muted-foreground">{m.model_type} · {m.symbol} · {m.timeframe} · Val: {pct(m.val_accuracy)}</div>
                        </div>
                      </div>
                      <Button size="sm" variant="outline" className="gap-1.5" onClick={() => openDetail(m.id)}>
                        <Play className="h-3.5 w-3.5" /> View Details
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {view === "data" && (
        <div className="space-y-4">
          <Card className="bg-card-bg border-card-border">
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold flex items-center gap-2">
                  <Database className="h-5 w-5 text-accent" /> Databento Datasets
                </h3>
                <Button variant="outline" size="sm" onClick={loadDabentoDatasets} className="gap-1.5">
                  <RefreshCw className="h-3.5 w-3.5" /> Refresh
                </Button>
              </div>

              {dabentoDatasets.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <Database className="h-10 w-10 text-muted-foreground/30 mb-4" />
                  <h3 className="text-base font-medium mb-2">No Datasets Downloaded</h3>
                  <p className="text-sm text-muted-foreground mb-4 max-w-md">
                    Run the Databento download pipeline to fetch CME futures data for ML training.
                  </p>
                  <code className="text-xs bg-background/80 border border-card-border rounded-lg px-4 py-2 text-muted-foreground font-mono">
                    python scripts/download_databento.py --symbols GC ES NQ YM BTC
                  </code>
                </div>
              ) : (
                <>
                  {/* Summary stats */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
                    <div className="rounded-lg bg-background/50 border border-card-border p-3">
                      <div className="text-[10px] text-muted-foreground uppercase tracking-wide">Datasets</div>
                      <div className="text-xl font-bold text-accent">{dabentoDatasets.length}</div>
                    </div>
                    <div className="rounded-lg bg-background/50 border border-card-border p-3">
                      <div className="text-[10px] text-muted-foreground uppercase tracking-wide">Symbols</div>
                      <div className="text-xl font-bold">{new Set(dabentoDatasets.map(d => d.symbol)).size}</div>
                    </div>
                    <div className="rounded-lg bg-background/50 border border-card-border p-3">
                      <div className="text-[10px] text-muted-foreground uppercase tracking-wide">Total Bars</div>
                      <div className="text-xl font-bold">{(dabentoDatasets.reduce((s, d) => s + d.row_count, 0) / 1000000).toFixed(1)}M</div>
                    </div>
                    <div className="rounded-lg bg-background/50 border border-card-border p-3">
                      <div className="text-[10px] text-muted-foreground uppercase tracking-wide">Total Size</div>
                      <div className="text-xl font-bold">{dabentoDatasets.reduce((s, d) => s + d.size_mb, 0).toFixed(0)} MB</div>
                    </div>
                  </div>

                  {/* Group by symbol */}
                  {Array.from(new Set(dabentoDatasets.map(d => d.symbol))).sort().map(symbol => {
                    const symbolDatasets = dabentoDatasets.filter(d => d.symbol === symbol);
                    return (
                      <div key={symbol} className="mb-3">
                        <div className="flex items-center gap-2 mb-2">
                          <h4 className="text-sm font-semibold text-accent">{symbol}</h4>
                          <span className="text-xs text-muted-foreground">{symbolDatasets.length} timeframes</span>
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-5 gap-2">
                          {symbolDatasets
                            .sort((a, b) => {
                              const tfOrder: Record<string, number> = { M1: 1, M5: 2, M10: 3, M15: 4, M30: 5, H1: 6, H4: 7, D1: 8 };
                              return (tfOrder[a.timeframe] || 99) - (tfOrder[b.timeframe] || 99);
                            })
                            .map(ds => (
                            <div key={ds.filename} className="rounded-lg border border-card-border bg-background/50 p-3 hover:border-accent/30 transition-colors group">
                              <div className="flex items-center justify-between mb-1">
                                <Badge variant="secondary" className="text-[10px] bg-accent/10 text-accent">{ds.timeframe}</Badge>
                                <span className="text-[10px] text-muted-foreground">{ds.size_mb} MB</span>
                              </div>
                              <div className="text-lg font-bold">{ds.row_count >= 1000000 ? `${(ds.row_count / 1000000).toFixed(1)}M` : ds.row_count >= 1000 ? `${(ds.row_count / 1000).toFixed(1)}K` : ds.row_count}</div>
                              <div className="text-[10px] text-muted-foreground mt-1">bars</div>
                            </div>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      <ChatHelpers />
    </div>
  );
}
