"use client";

import { useState, useEffect, useCallback } from "react";
import { api, API_BASE } from "@/lib/api";
import ChatHelpers from "@/components/ChatHelpers";
import { Sparkles, Loader2, ArrowLeft, Brain, Trash2, Play, BarChart3, GitCompare, RefreshCw, Download, Upload, Activity, TrendingUp } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type {
  MLModelListItem,
  MLModelDetail,
  MLPredictionResult,
  MLActionPlan,
  FeatureList,
  DataSource,
} from "@/types";

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
  /* ── state ──────────────────────────────────── */
  const [view, setView] = useState<"list" | "detail" | "train" | "predict" | "compare" | "regime" | "forecast">("list");
  const [models, setModels] = useState<MLModelListItem[]>([]);
  const [selected, setSelected] = useState<MLModelDetail | null>(null);
  const [predictions, setPredictions] = useState<MLPredictionResult | null>(null);
  const [features, setFeatures] = useState<FeatureList | null>(null);
  const [dataSources, setDataSources] = useState<DataSource[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Compare state
  const [compareIds, setCompareIds] = useState<number[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [compareData, setCompareData] = useState<any>(null);

  // Walk-forward retrain
  const [retraining, setRetraining] = useState(false);

  // Train form state
  const [tName, setTName] = useState("");
  const [tLevel, setTLevel] = useState(2);
  const [tModelType, setTModelType] = useState("lightgbm");
  const [tDsId, setTDsId] = useState<number>(0);
  const [tSymbol, setTSymbol] = useState("");
  const [tTimeframe, setTTimeframe] = useState("H1");
  const [tTarget, setTTarget] = useState("direction");
  const [tHorizon, setTHorizon] = useState(1);
  const [tNEst, setTNEst] = useState(100);
  const [tMaxDepth, setTMaxDepth] = useState(10);
  const [tLR, setTLR] = useState(0.1);
  const [tFeatures, setTFeatures] = useState<string[]>([]);
  const [tNormalize, setTNormalize] = useState("none");
  const [tZscoreWindow, setTZscoreWindow] = useState(50);
  // Triple barrier params
  const [tSlAtrMult, setTSlAtrMult] = useState(1.5);
  const [tTpAtrMult, setTTpAtrMult] = useState(2.0);
  const [tMaxHoldBars, setTMaxHoldBars] = useState(10);

  // Level 3 config
  const [l3SubType, setL3SubType] = useState('ensemble');
  const [l3SeqLen, setL3SeqLen] = useState(20);
  const [l3Units, setL3Units] = useState(64);

  // Predict form
  const [pDsId, setPDsId] = useState<number>(0);
  const [pBars, setPBars] = useState(50);

  // Optuna config
  const [tUseOptuna, setTUseOptuna] = useState(false);
  const [tOptunaNTrials, setTOptunaNTrials] = useState(50);
  const [tOptunaTimeout, setTOptunaTimeout] = useState(600);
  const [tOptunaFolds, setTOptunaFolds] = useState(3);

  // Regime detection
  const [regimeDsId, setRegimeDsId] = useState<number>(0);
  const [regimeModelId, setRegimeModelId] = useState(0);
  const [regimeTraining, setRegimeTraining] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [regimeResult, setRegimeResult] = useState<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [regimeHistory, setRegimeHistory] = useState<any[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [regimeCurrent, setRegimeCurrent] = useState<any>(null);

  // LSTM forecast
  const [lstmDsId, setLstmDsId] = useState<number>(0);
  const [lstmModelId, setLstmModelId] = useState(0);
  const [lstmCell, setLstmCell] = useState("lstm");
  const [lstmSeqLen, setLstmSeqLen] = useState(60);
  const [lstmHorizon, setLstmHorizon] = useState(10);
  const [lstmHidden, setLstmHidden] = useState(128);
  const [lstmEpochs, setLstmEpochs] = useState(50);
  const [lstmTraining, setLstmTraining] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [lstmResult, setLstmResult] = useState<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [lstmForecast, setLstmForecast] = useState<any>(null);

  // Meta-labeling
  const [metaTraining, setMetaTraining] = useState(false);

  // AI assist state
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiPlan, setAiPlan] = useState<MLActionPlan | null>(null);
  const [aiError, setAiError] = useState("");

  /* ── loaders ────────────────────────────────── */
  const loadModels = useCallback(async () => {
    try {
      const data = await api.get<MLModelListItem[]>("/api/ml/models");
      setModels(data);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    loadModels();
    api.get<FeatureList>("/api/ml/features").then(setFeatures).catch(() => {});
    api.get<{ items: DataSource[] }>("/api/data/sources").then(r => setDataSources(r.items || [])).catch(() => {});
  }, [loadModels]);

  const openDetail = async (id: number) => {
    try {
      const m = await api.get<MLModelDetail>(`/api/ml/models/${id}`);
      setSelected(m);
      setView("detail");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Load failed");
    }
  };

  /* ── AI interpret ────────────────────────────── */
  const handleAiInterpret = async () => {
    if (!aiPrompt.trim()) return;
    setAiLoading(true);
    setAiError("");
    setAiPlan(null);
    try {
      const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
      const res = await fetch(`${API_BASE}/api/llm/ml-action`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ prompt: aiPrompt }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      const plan: MLActionPlan = await res.json();
      if (plan.action === "clarify") {
        setAiError(plan.explanation || "Please provide more details.");
      } else {
        setAiPlan(plan);
      }
    } catch (e) {
      setAiError(e instanceof Error ? e.message : "AI interpretation failed");
    } finally {
      setAiLoading(false);
    }
  };

  const applyAiPlan = () => {
    if (!aiPlan) return;
    setTName(aiPlan.name);
    setTLevel(aiPlan.level);
    setTModelType(aiPlan.model_type);
    setTDsId(aiPlan.datasource_id);
    setTSymbol(aiPlan.symbol);
    setTTimeframe(aiPlan.timeframe);
    setTTarget(aiPlan.target_type);
    setTHorizon(aiPlan.target_horizon);
    setTNEst(aiPlan.n_estimators);
    setTMaxDepth(aiPlan.max_depth);
    setTLR(aiPlan.learning_rate);
    setTFeatures(aiPlan.features || []);
    setAiPlan(null);
    setAiPrompt("");
    setView("train");
  };

  const trainFromPlan = async () => {
    if (!aiPlan) return;
    setLoading(true);
    setError("");
    try {
      const result = await api.post<MLModelDetail>("/api/ml/train", {
        name: aiPlan.name,
        level: aiPlan.level,
        model_type: aiPlan.model_type,
        datasource_id: aiPlan.datasource_id,
        symbol: aiPlan.symbol,
        timeframe: aiPlan.timeframe,
        target_type: aiPlan.target_type,
        target_horizon: aiPlan.target_horizon,
        features: aiPlan.features.length > 0 ? aiPlan.features : undefined,
        n_estimators: aiPlan.n_estimators,
        max_depth: aiPlan.max_depth,
        learning_rate: aiPlan.learning_rate,
      });
      setSelected(result);
      setView("detail");
      setAiPlan(null);
      setAiPrompt("");
      loadModels();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Training failed");
    } finally {
      setLoading(false);
    }
  };

  /* ── train model ────────────────────────────── */
  const handleTrain = async () => {
    if (!tName || !tDsId) return;
    setLoading(true);
    setError("");
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const result = await api.post<any>("/api/ml/train", {
        name: tName,
        level: tLevel,
        model_type: tModelType,
        datasource_id: tDsId,
        symbol: tSymbol,
        timeframe: tTimeframe,
        target_type: tTarget,
        target_horizon: tHorizon,
        features: tFeatures.length > 0 ? tFeatures : undefined,
        normalize: tNormalize,
        zscore_window: tZscoreWindow,
        n_estimators: tNEst,
        max_depth: tMaxDepth,
        learning_rate: tLR,
        ...(tTarget === "triple_barrier" && { sl_atr_mult: tSlAtrMult, tp_atr_mult: tTpAtrMult, max_holding_bars: tMaxHoldBars }),
        ...(tLevel === 3 && { sub_type: l3SubType, seq_len: l3SeqLen, hidden_units: l3Units }),
        ...(tUseOptuna && { use_optuna: true, optuna_n_trials: tOptunaNTrials, optuna_timeout: tOptunaTimeout, optuna_n_folds: tOptunaFolds }),
      });

      // Background training: poll for completion
      if (result.status === "training" && result.id) {
        setView("list");
        loadModels();
        const pollId = result.id;
        const poll = setInterval(async () => {
          try {
            const m = await api.get<MLModelDetail>(`/api/ml/models/${pollId}`);
            if (m.status === "ready" || m.status === "failed") {
              clearInterval(poll);
              setSelected(m);
              setView("detail");
              loadModels();
              setLoading(false);
            }
          } catch {
            clearInterval(poll);
            setLoading(false);
          }
        }, 3000);
        // Safety: stop polling after 10 minutes
        setTimeout(() => { clearInterval(poll); setLoading(false); }, 600000);
      } else {
        // Synchronous response (legacy fallback)
        setSelected(result);
        setView("detail");
        loadModels();
        setLoading(false);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Training failed");
      setLoading(false);
    }
  };

  /* ── predict ────────────────────────────────── */
  const handlePredict = async () => {
    if (!selected || !pDsId) return;
    setLoading(true);
    setError("");
    try {
      const result = await api.post<MLPredictionResult>("/api/ml/predict", {
        model_id: selected.id,
        datasource_id: pDsId,
        last_n_bars: pBars,
      });
      setPredictions(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Prediction failed");
    } finally {
      setLoading(false);
    }
  };

  /* ── delete model ───────────────────────────── */
  const handleDelete = async (id: number) => {
    try {
      await api.delete(`/api/ml/models/${id}`);
      loadModels();
      if (selected?.id === id) {
        setSelected(null);
        setView("list");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
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
        setTimeout(() => { clearInterval(poll); setMetaTraining(false); }, 600000);
      } else {
        setMetaTraining(false);
        loadModels();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Meta-labeling training failed");
      setMetaTraining(false);
    }
  };

  /* ── Regime handlers ─────────────────────── */
  const handleRegimeTrain = async () => {
    if (!regimeDsId) { setError("Select a datasource"); return; }
    setRegimeTraining(true);
    setError("");
    setRegimeResult(null);
    try {
      const result = await api.post(`/api/ml/regime/train?datasource_id=${regimeDsId}&model_id=${regimeModelId}`, {});
      setRegimeResult(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Regime training failed");
    } finally {
      setRegimeTraining(false);
    }
  };

  const handleRegimePredict = async () => {
    if (!regimeDsId) { setError("Select a datasource"); return; }
    setError("");
    try {
      // Find datasource name for symbol extraction
      const ds = dataSources.find(d => d.id === regimeDsId);
      const symbol = ds ? ds.filename.split("_")[0] : "UNKNOWN";
      const result = await api.get(`/api/ml/regime/current/${symbol}?datasource_id=${regimeDsId}&model_id=${regimeModelId}`);
      setRegimeCurrent(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Regime prediction failed");
    }
  };

  const handleRegimeHistory = async () => {
    if (!regimeDsId) { setError("Select a datasource"); return; }
    setError("");
    try {
      const ds = dataSources.find(d => d.id === regimeDsId);
      const parts = ds ? ds.filename.split("_") : [];
      const symbol = parts[0] || "UNKNOWN";
      const timeframe = parts[1] || "H1";
      const data = await api.get<Record<string, unknown>[]>(
        `/api/ml/regime/history?symbol=${symbol}&timeframe=${timeframe}&model_id=${regimeModelId}`
      );
      setRegimeHistory(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load regime history");
    }
  };

  const regimeColor = (r: string) => {
    if (r === "trending_up") return "bg-green-500/20 text-green-400 border-green-500/30";
    if (r === "trending_down") return "bg-red-500/20 text-red-400 border-red-500/30";
    if (r === "ranging") return "bg-blue-500/20 text-blue-400 border-blue-500/30";
    if (r === "volatile") return "bg-orange-500/20 text-orange-400 border-orange-500/30";
    return "bg-zinc-500/20 text-zinc-400 border-zinc-500/30";
  };

  /* ── LSTM handlers ───────────────────────── */
  const handleLstmTrain = async () => {
    if (!lstmDsId) { setError("Select a datasource"); return; }
    setLstmTraining(true);
    setError("");
    setLstmResult(null);
    try {
      const params = new URLSearchParams({
        datasource_id: String(lstmDsId),
        model_id: String(lstmModelId),
        cell_type: lstmCell,
        seq_len: String(lstmSeqLen),
        horizon: String(lstmHorizon),
        hidden_size: String(lstmHidden),
        epochs: String(lstmEpochs),
      });
      const result = await api.post(`/api/ml/lstm/train?${params}`, {});
      setLstmResult(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "LSTM training failed");
    } finally {
      setLstmTraining(false);
    }
  };

  const handleLstmPredict = async () => {
    if (!lstmDsId) { setError("Select a datasource"); return; }
    setError("");
    try {
      const ds = dataSources.find(d => d.id === lstmDsId);
      const symbol = ds ? ds.filename.split("_")[0] : "UNKNOWN";
      const result = await api.get(
        `/api/ml/lstm/predict/${symbol}?datasource_id=${lstmDsId}&model_id=${lstmModelId}`
      );
      setLstmForecast(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "LSTM prediction failed");
    }
  };

  /* ═══════════════ RENDER ═══════════════════════ */
  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-xl font-semibold">ML Lab</h2>
          {view !== "list" && (
            <Button variant="ghost" size="sm" onClick={() => { setView("list"); setPredictions(null); }} className="gap-1 text-muted-foreground">
              <ArrowLeft className="h-3 w-3" /> Back to Models
            </Button>
          )}
        </div>
        <div className="flex gap-2">
          <Button variant="outline" className="gap-1.5" onClick={() => {
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
          <Button variant="outline" onClick={() => setView("regime")} className="gap-1.5">
            <Activity className="h-4 w-4" /> Regime
          </Button>
          <Button variant="outline" onClick={() => setView("forecast")} className="gap-1.5">
            <TrendingUp className="h-4 w-4" /> Forecast
          </Button>
          <Button onClick={() => setView("train")} className="gap-1.5">
            <Brain className="h-4 w-4" /> Train New Model
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>
      )}

      {/* ── AI TRAINING ASSISTANT ─────────────── */}
      {view === "list" && (
        <Card className="border-accent/30 bg-accent/5">
          <CardContent className="p-5">
          <div className="flex items-center gap-2 mb-3">
            <Sparkles className="h-5 w-5 text-accent" />
            <h3 className="text-sm font-semibold text-accent">AI Training Assistant</h3>
          </div>
          <p className="text-xs text-muted-foreground mb-3">
            Describe what you want to train in natural language. The AI will configure the model parameters for you.
          </p>

          <div className="flex gap-2">
            <textarea
              value={aiPrompt}
              onChange={e => setAiPrompt(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleAiInterpret(); } }}
              placeholder='e.g. "Train an XGBoost model on XAUUSD H1 data to predict next-bar direction using RSI, MACD, and Bollinger Bands"'
              rows={2}
              className="flex-1 rounded-lg border border-card-border bg-background px-3 py-2 text-sm resize-none focus:outline-none focus:border-accent placeholder:text-muted-foreground/60"
            />
            <Button
              onClick={handleAiInterpret}
              disabled={aiLoading || !aiPrompt.trim()}
              className="self-end whitespace-nowrap"
            >
              {aiLoading ? (
                <span className="flex items-center gap-2">
                  <Loader2 className="animate-spin h-4 w-4" />
                  Interpreting...
                </span>
              ) : "Configure with AI"}
            </Button>
          </div>

          {/* Example prompts */}
          <div className="flex flex-wrap gap-2 mt-2">
            {[
              "Train XGBoost to predict XAUUSD direction",
              "Build a volatility predictor for gold on 5-min bars",
              "Random Forest on NAS100 H4 with trend features",
            ].map(ex => (
              <button key={ex} onClick={() => setAiPrompt(ex)}
                className="rounded-full border border-card-border px-3 py-1 text-[11px] text-muted-foreground hover:text-accent hover:border-accent/50 transition-colors">
                {ex}
              </button>
            ))}
          </div>

          {aiError && (
            <div className="mt-3 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{aiError}</div>
          )}

          {/* AI Plan Review */}
          {aiPlan && (
            <div className="mt-4 rounded-xl border border-accent/40 bg-card-bg p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-semibold text-accent">AI Configuration Plan</h4>
                <span className="text-[10px] text-muted-foreground">
                  {aiPlan.tokens_used?.input ?? 0} / {aiPlan.tokens_used?.output ?? 0} tokens
                </span>
              </div>

              {aiPlan.explanation && (
                <p className="text-xs text-muted-foreground italic bg-background/50 rounded-lg px-3 py-2">
                  {aiPlan.explanation}
                </p>
              )}

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div>
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wide">Model</div>
                  <div className="text-sm font-medium">{aiPlan.name}</div>
                </div>
                <div>
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wide">Type</div>
                  <div className="text-sm font-medium">{aiPlan.model_type}</div>
                </div>
                <div>
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wide">Level</div>
                  <div className="text-sm font-medium">{levelLabel(aiPlan.level)}</div>
                </div>
                <div>
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wide">Target</div>
                  <div className="text-sm font-medium">{aiPlan.target_type} ({aiPlan.target_horizon} bar)</div>
                </div>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div>
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wide">Dataset</div>
                  <div className="text-sm">{aiPlan.datasource_name || `ID ${aiPlan.datasource_id}`}</div>
                  {aiPlan.datasource_info && (
                    <div className="text-[10px] text-muted-foreground">{aiPlan.datasource_info}</div>
                  )}
                </div>
                <div>
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wide">Symbol / TF</div>
                  <div className="text-sm font-medium">{aiPlan.symbol} {aiPlan.timeframe}</div>
                </div>
                <div>
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wide">Estimators</div>
                  <div className="text-sm font-medium">{aiPlan.n_estimators}</div>
                </div>
                <div>
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wide">Depth / LR</div>
                  <div className="text-sm font-medium">{aiPlan.max_depth} / {aiPlan.learning_rate}</div>
                </div>
              </div>

              {aiPlan.features.length > 0 && (
                <div>
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1">Features ({aiPlan.features.length})</div>
                  <div className="flex flex-wrap gap-1">
                    {aiPlan.features.map(f => (
                      <Badge key={f} variant="secondary" className="bg-accent/10 border-accent/20 text-accent text-[10px]">
                        {f}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              <div className="flex gap-2 pt-1">
                <Button onClick={trainFromPlan} disabled={loading} variant="default" className="bg-green-600 hover:bg-green-500">
                  {loading ? "Training..." : "Train Now"}
                </Button>
                <Button variant="outline" onClick={applyAiPlan} className="text-accent border-accent/40 hover:bg-accent/10">
                  Edit First
                </Button>
                <Button variant="outline" onClick={() => setAiPlan(null)}>
                  Dismiss
                </Button>
              </div>
            </div>
          )}
          </CardContent>
        </Card>
      )}

      {/* Level Overview Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {[1, 2, 3].map(level => {
          const levelModels = models.filter(m => m.level === level);
          const ready = levelModels.filter(m => m.status === "ready");
          return (
            <Card key={level} className="bg-card-bg border-card-border">
              <CardContent className="p-4">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-sm font-medium text-accent">
                    {level === 1 ? "Level 1: Adaptive Params" : level === 2 ? "Level 2: Signal Prediction" : "Level 3: Advanced ML"}
                  </h3>
                  <Badge variant="secondary" className="text-[10px]">{ready.length} ready</Badge>
                </div>
                <p className="text-xs text-muted-foreground">
                  {level === 1 && "ML predicts best strategy params for current market regime."}
                  {level === 2 && "Predict next-bar direction/movement using trained classifiers."}
                  {level === 3 && "Stacked ensemble classifiers (RF + XGB + Logistic Regression meta-learner)."}
                </p>
                {ready.length > 0 && (
                  <div className="mt-2 text-xs">
                    Best val acc: <span className="text-green-400 font-medium">
                      {pct(Math.max(...ready.map(m => m.val_accuracy || 0)))}
                    </span>
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

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
                Train your first ML model by uploading price data,
                or describe what you want to train using the AI assistant above.
              </p>
              <Button onClick={() => setView("train")} className="gap-1.5">
                <Sparkles className="h-4 w-4" /> Train New Model
              </Button>
            </div>
          ) : (
            <div className="space-y-2">
              {models.map(m => (
                <div key={m.id}
                  className="flex items-center justify-between rounded-lg border border-card-border bg-background/50 p-3 hover:bg-background/80 cursor-pointer transition-colors"
                  onClick={() => openDetail(m.id)}>
                  <div className="flex items-center gap-3">
                    <input
                      type="checkbox"
                      checked={compareIds.includes(m.id)}
                      onChange={(e) => { e.stopPropagation(); toggleCompare(m.id); }}
                      onClick={(e) => e.stopPropagation()}
                      className="accent-accent h-3.5 w-3.5"
                    />
                    <Badge variant="secondary" className={`text-xs font-medium ${statusColor(m.status)}`}>{m.status}</Badge>
                    <div>
                      <div className="text-sm font-medium">{m.name}</div>
                      <div className="text-xs text-muted-foreground">
                        {levelLabel(m.level)} · {m.model_type} · {m.symbol || "—"} · {m.timeframe}
                        {m.level === 3 && (m as { architecture?: string }).architecture && (
                          <span className="ml-1 text-accent/70">· {(m as { architecture?: string }).architecture}</span>
                        )}
                        {m.name.startsWith("Meta:") && (
                          <Badge variant="secondary" className="ml-1 text-[9px] bg-purple-500/20 text-purple-400 px-1 py-0">META</Badge>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-6">
                    <div className="text-right">
                      <div className="text-xs text-muted-foreground">Train / Val Accuracy</div>
                      <div className="text-sm font-medium">
                        <span className="text-fa-accent">{pct(m.train_accuracy)}</span>
                        {" / "}
                        <span className="text-green-400">{pct(m.val_accuracy)}</span>
                      </div>
                    </div>
                    <div className="text-right text-xs text-muted-foreground">
                      {m.n_features} features
                    </div>
                    <Button variant="outline" size="sm" onClick={(e) => { e.stopPropagation(); handleDelete(m.id); }}
                      className="text-red-400 border-red-500/40 hover:bg-red-500/10 h-7 gap-1">
                      <Trash2 className="h-3 w-3" /> Delete
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
          </CardContent>
        </Card>
      )}

      {/* ── TRAIN NEW MODEL ─────────────────────── */}
      {view === "train" && (
        <Card className="bg-card-bg border-card-border">
          <CardContent className="p-6 space-y-5">
          <h3 className="text-lg font-semibold">Train New Model</h3>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label className="text-xs text-muted-foreground mb-1">Model Name</Label>
              <Input value={tName} onChange={e => setTName(e.target.value)} placeholder="e.g. EURUSD Direction Predictor" />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground mb-1">Level</Label>
              <select value={tLevel} onChange={e => setTLevel(Number(e.target.value))}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm">
                <option value={1}>Level 1: Adaptive Params</option>
                <option value={2}>Level 2: Signal Prediction</option>
                <option value={3}>Level 3: Advanced ML: Stacked Ensemble</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <Label className="text-xs text-muted-foreground mb-1">Model Type</Label>
              <select value={tModelType} onChange={e => setTModelType(e.target.value)}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm">
                <option value="lightgbm">LightGBM (recommended)</option>
                <option value="catboost">CatBoost</option>
                <option value="xgboost">XGBoost</option>
                <option value="random_forest">Random Forest</option>
                <option value="gradient_boosting">Gradient Boosting</option>
              </select>
            </div>
            <div>
              <Label className="text-xs text-muted-foreground mb-1">Data Source</Label>
              <select value={tDsId} onChange={e => setTDsId(Number(e.target.value))}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm">
                <option value={0}>Select dataset...</option>
                {dataSources.map(ds => (
                  <option key={ds.id} value={ds.id}>{ds.filename} ({ds.symbol} {ds.timeframe}, {ds.row_count} bars)</option>
                ))}
              </select>
            </div>
            <div>
              <Label className="text-xs text-muted-foreground mb-1">Prediction Target</Label>
              <select value={tTarget} onChange={e => setTTarget(e.target.value)}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm">
                <option value="direction">Direction (Up/Down)</option>
                <option value="return">Return Magnitude</option>
                <option value="volatility">Volatility</option>
                <option value="triple_barrier">Triple Barrier (SL/TP)</option>
              </select>
            </div>
          </div>

          {/* Triple barrier params */}
          {tTarget === "triple_barrier" && (
            <div className="grid grid-cols-3 gap-4 p-3 rounded-lg border border-orange-500/30 bg-orange-500/5">
              <div>
                <Label className="text-xs text-muted-foreground mb-1">SL (ATR ×)</Label>
                <Input type="number" step={0.1} value={tSlAtrMult} onChange={e => setTSlAtrMult(Number(e.target.value))} min={0.5} max={5} />
              </div>
              <div>
                <Label className="text-xs text-muted-foreground mb-1">TP (ATR ×)</Label>
                <Input type="number" step={0.1} value={tTpAtrMult} onChange={e => setTTpAtrMult(Number(e.target.value))} min={0.5} max={10} />
              </div>
              <div>
                <Label className="text-xs text-muted-foreground mb-1">Max Hold (bars)</Label>
                <Input type="number" value={tMaxHoldBars} onChange={e => setTMaxHoldBars(Number(e.target.value))} min={1} max={50} />
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div>
              <Label className="text-xs text-muted-foreground mb-1">Symbol</Label>
              <Input value={tSymbol} onChange={e => setTSymbol(e.target.value)} placeholder="Auto from dataset" />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground mb-1">Timeframe</Label>
              <select value={tTimeframe} onChange={e => setTTimeframe(e.target.value)}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm">
                {["M1","M5","M15","M30","H1","H4","D1"].map(tf => <option key={tf} value={tf}>{tf}</option>)}
              </select>
            </div>
            <div>
              <Label className="text-xs text-muted-foreground mb-1">Horizon (bars)</Label>
              <Input type="number" value={tHorizon} onChange={e => setTHorizon(Number(e.target.value))} min={1} max={20} />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground mb-1">Normalization</Label>
              <select value={tNormalize} onChange={e => setTNormalize(e.target.value)}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm">
                <option value="none">None</option>
                <option value="zscore">Rolling Z-Score</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div>
              <Label className="text-xs text-muted-foreground mb-1">Estimators</Label>
              <Input type="number" value={tNEst} onChange={e => setTNEst(Number(e.target.value))} min={10} max={1000} />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground mb-1">Max Depth</Label>
              <Input type="number" value={tMaxDepth} onChange={e => setTMaxDepth(Number(e.target.value))} min={2} max={30} />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground mb-1">Learning Rate</Label>
              <Input type="number" step={0.01} value={tLR} onChange={e => setTLR(Number(e.target.value))} min={0.001} max={1} />
            </div>
            {tNormalize === "zscore" && (
              <div>
                <Label className="text-xs text-muted-foreground mb-1">Z-Score Window</Label>
                <Input type="number" value={tZscoreWindow} onChange={e => setTZscoreWindow(Number(e.target.value))} min={10} max={200} />
              </div>
            )}
          </div>

          {/* Optuna auto-tuning */}
          {tLevel !== 3 && (
            <div className="space-y-3 p-3 rounded-lg border border-card-border bg-background/40">
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={tUseOptuna} onChange={e => setTUseOptuna(e.target.checked)} className="accent-accent" />
                <span className="text-sm font-medium">Optuna Auto-Tuning</span>
                <span className="text-xs text-muted-foreground">— automatically finds optimal hyperparameters</span>
              </label>
              {tUseOptuna && (
                <div className="grid grid-cols-3 gap-4 mt-2">
                  <div>
                    <Label className="text-xs text-muted-foreground mb-1">Trials</Label>
                    <Input type="number" value={tOptunaNTrials} onChange={e => setTOptunaNTrials(Number(e.target.value))} min={10} max={500} />
                  </div>
                  <div>
                    <Label className="text-xs text-muted-foreground mb-1">Timeout (sec)</Label>
                    <Input type="number" value={tOptunaTimeout} onChange={e => setTOptunaTimeout(Number(e.target.value))} min={60} max={3600} />
                  </div>
                  <div>
                    <Label className="text-xs text-muted-foreground mb-1">CV Folds</Label>
                    <Input type="number" value={tOptunaFolds} onChange={e => setTOptunaFolds(Number(e.target.value))} min={2} max={10} />
                  </div>
                </div>
              )}
              {tUseOptuna && (
                <p className="text-xs text-muted-foreground">
                  When enabled, the hyperparameter fields above are ignored — Optuna searches for optimal values automatically.
                  More trials = better results but longer training time.
                </p>
              )}
            </div>
          )}

          {/* Level 3 Advanced ML config */}
          {tLevel === 3 && (
            <div className="space-y-3 p-3 rounded-lg border border-card-border bg-background/40">
              <p className="text-xs text-muted-foreground">
                Level 3 trains a Stacked Ensemble: Random Forest + XGBoost as base models with Logistic Regression as the meta-learner.
                Features are auto-scaled. This combines the strengths of multiple models for better generalization.
              </p>
            </div>
          )}

          {/* Feature selection */}
          {features && (
            <div>
              <label className="block text-xs text-muted-foreground mb-2">Features (leave empty for all)</label>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                {features.available_features.map(f => (
                  <label key={f} className="flex items-center gap-2 text-xs cursor-pointer">
                    <input type="checkbox" checked={tFeatures.includes(f)}
                      onChange={e => {
                        if (e.target.checked) setTFeatures([...tFeatures, f]);
                        else setTFeatures(tFeatures.filter(x => x !== f));
                      }}
                      className="accent-accent" />
                    <span>{f}</span>
                    <span className="text-muted-foreground ml-1">— {features.descriptions[f] || ""}</span>
                  </label>
                ))}
              </div>
            </div>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <Button variant="outline" onClick={() => setView("list")}>
              Cancel
            </Button>
            <Button onClick={handleTrain} disabled={loading || !tName || !tDsId}>
              {loading ? "Training..." : "Train Model"}
            </Button>
          </div>
          </CardContent>
        </Card>
      )}

      {/* ── MODEL DETAIL ────────────────────────── */}
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
                  <Button onClick={() => { setPDsId(0); setPredictions(null); setView("predict"); }} className="gap-1.5">
                    <Play className="h-3.5 w-3.5" /> Run Predictions
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

          {/* Feature Importance */}
          {selected.feature_importance && Object.keys(selected.feature_importance).length > 0 && (
            <Card className="bg-card-bg border-card-border">
              <CardContent className="p-5">
              <h4 className="text-sm font-medium text-muted-foreground mb-3">Feature Importance (top 15)</h4>
              <div className="space-y-1.5">
                {Object.entries(selected.feature_importance)
                  .slice(0, 15)
                  .map(([name, imp]) => {
                    const maxImp = Math.max(...Object.values(selected.feature_importance));
                    const widthPct = maxImp > 0 ? (imp / maxImp) * 100 : 0;
                    return (
                      <div key={name} className="flex items-center gap-3">
                        <span className="text-xs text-muted-foreground w-40 truncate">{name}</span>
                        <div className="flex-1 h-4 rounded bg-background/50 overflow-hidden">
                          <div className="h-full rounded bg-accent/60" style={{ width: `${widthPct}%` }} />
                        </div>
                        <span className="text-xs font-mono w-16 text-right">{(imp * 100).toFixed(2)}%</span>
                      </div>
                    );
                  })}
              </div>
              </CardContent>
            </Card>
          )}

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

      {/* ── PREDICTIONS VIEW ────────────────────── */}
      {view === "predict" && (
        <div className="space-y-4">
          {/* Predict form */}
          {!predictions && selected && (
            <Card className="bg-card-bg border-card-border">
              <CardContent className="p-6 space-y-4">
              <h3 className="text-lg font-semibold">Run Predictions — {selected.name}</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label className="text-xs text-muted-foreground mb-1">Data Source</Label>
                  <select value={pDsId} onChange={e => setPDsId(Number(e.target.value))}
                    className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm">
                    <option value={0}>Select dataset...</option>
                    {dataSources.map(ds => (
                      <option key={ds.id} value={ds.id}>{ds.filename} ({ds.row_count} bars)</option>
                    ))}
                  </select>
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground mb-1">Last N Bars</Label>
                  <Input type="number" value={pBars} onChange={e => setPBars(Number(e.target.value))} min={10} max={500} />
                </div>
              </div>
              <div className="flex justify-end gap-3">
                <Button variant="outline" onClick={() => { setView("detail"); setPredictions(null); }}>
                  Cancel
                </Button>
                <Button onClick={handlePredict} disabled={loading || !pDsId}>
                  {loading ? "Predicting..." : "Predict"}
                </Button>
              </div>
              </CardContent>
            </Card>
          )}

          {/* Prediction results */}
          {predictions && (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <Card className="bg-card-bg border-card-border">
                  <CardContent className="p-4">
                    <div className="text-xs text-muted-foreground mb-1">Total Predictions</div>
                    <div className="text-lg font-semibold">{predictions.total_predictions}</div>
                  </CardContent>
                </Card>
                <Card className="bg-card-bg border-card-border">
                  <CardContent className="p-4">
                    <div className="text-xs text-muted-foreground mb-1">Avg Confidence</div>
                    <div className="text-lg font-semibold">{pct(predictions.avg_confidence)}</div>
                  </CardContent>
                </Card>
                <Card className="bg-card-bg border-card-border">
                  <CardContent className="p-4">
                    <div className="text-xs text-muted-foreground mb-1">Bull / Bear Split</div>
                    <div className="text-lg font-semibold">
                      <span className="text-green-400">
                        {predictions.predictions.filter(p => p.prediction >= 0.5).length}
                      </span>
                      {" / "}
                      <span className="text-red-400">
                        {predictions.predictions.filter(p => p.prediction < 0.5).length}
                      </span>
                    </div>
                  </CardContent>
                </Card>
              </div>

              {/* Signal bar chart */}
              <Card className="bg-card-bg border-card-border">
                <CardContent className="p-5">
                <h4 className="text-sm font-medium text-muted-foreground mb-3">Prediction Signal (last {Math.min(80, predictions.predictions.length)} bars)</h4>
                <div className="flex items-end gap-px h-32">
                  {predictions.predictions.slice(-80).map((p, i) => {
                    const isBull = p.prediction >= 0.5;
                    const height = Math.max(10, p.confidence * 100);
                    return (
                      <div key={i} className="flex-1 min-w-[2px] relative group">
                        <div
                          className={`absolute bottom-0 w-full rounded-t-sm ${isBull ? "bg-green-500/70" : "bg-red-500/70"}`}
                          style={{ height: `${height}%` }}
                        />
                        <div className="absolute -top-8 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 bg-card-bg border border-card-border rounded px-2 py-1 text-xs whitespace-nowrap z-10 pointer-events-none">
                          {isBull ? "↑ Bull" : "↓ Bear"} {(p.confidence * 100).toFixed(0)}%
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div className="flex justify-between text-xs text-muted-foreground mt-2">
                  <span>Oldest</span>
                  <span className="flex items-center gap-4">
                    <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm bg-green-500/70" /> Bull</span>
                    <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm bg-red-500/70" /> Bear</span>
                  </span>
                  <span>Newest</span>
                </div>
                </CardContent>
              </Card>

              {/* Predictions table */}
              <Card className="bg-card-bg border-card-border">
                <CardContent className="p-5">
                <h4 className="text-sm font-medium text-muted-foreground mb-3">Detailed Predictions (last 20)</h4>
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow className="border-card-border">
                        <TableHead>Bar #</TableHead>
                        <TableHead>Signal</TableHead>
                        <TableHead className="text-right">Confidence</TableHead>
                        <TableHead className="text-right">Top Features</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {predictions.predictions.slice(-20).reverse().map((p, i) => (
                        <TableRow key={i} className="border-card-border/50">
                          <TableCell>{p.bar_index}</TableCell>
                          <TableCell>
                            <Badge variant="secondary" className={`text-xs font-medium ${
                              p.prediction >= 0.5 ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"
                            }`}>
                              {p.prediction >= 0.5 ? "↑ BULL" : "↓ BEAR"}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-right">{(p.confidence * 100).toFixed(1)}%</TableCell>
                          <TableCell className="text-right text-xs text-muted-foreground">
                            {Object.entries(p.features || {}).slice(0, 3).map(([k, v]) =>
                              `${k}: ${typeof v === "number" ? v.toFixed(4) : v}`
                            ).join(", ")}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
                </CardContent>
              </Card>
            </>
          )}
        </div>
      )}

      {/* ── COMPARE VIEW ─────────────────────────── */}
      {view === "compare" && compareData && (
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

      {/* ── REGIME DETECTION VIEW ──────────── */}
      {view === "regime" && (
        <div className="space-y-4">
          <Card className="bg-card-bg border-card-border">
            <CardContent className="p-5 space-y-4">
              <h3 className="text-sm font-semibold text-accent flex items-center gap-2">
                <Activity className="h-4 w-4" /> HMM Regime Detection
              </h3>
              <p className="text-xs text-muted-foreground">
                Train a Hidden Markov Model to classify market regime into 4 states:
                <Badge className="ml-1 bg-green-500/20 text-green-400 text-[10px]">trending up</Badge>
                <Badge className="ml-1 bg-red-500/20 text-red-400 text-[10px]">trending down</Badge>
                <Badge className="ml-1 bg-blue-500/20 text-blue-400 text-[10px]">ranging</Badge>
                <Badge className="ml-1 bg-orange-500/20 text-orange-400 text-[10px]">volatile</Badge>
              </p>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <Label className="text-xs">Datasource</Label>
                  <select
                    className="w-full mt-1 rounded-md bg-zinc-900 border border-zinc-700 text-sm p-2"
                    value={regimeDsId}
                    onChange={e => setRegimeDsId(Number(e.target.value))}
                  >
                    <option value={0}>Select datasource...</option>
                    {dataSources.map(ds => (
                      <option key={ds.id} value={ds.id}>{ds.filename}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <Label className="text-xs">Model ID</Label>
                  <Input
                    type="number"
                    className="mt-1"
                    value={regimeModelId}
                    onChange={e => setRegimeModelId(Number(e.target.value))}
                  />
                </div>
                <div className="flex items-end gap-2">
                  <Button onClick={handleRegimeTrain} disabled={regimeTraining || !regimeDsId} className="gap-1.5">
                    {regimeTraining ? <Loader2 className="h-4 w-4 animate-spin" /> : <Brain className="h-4 w-4" />}
                    Train HMM
                  </Button>
                  <Button variant="outline" onClick={handleRegimePredict} disabled={!regimeDsId}>
                    <Play className="h-4 w-4 mr-1" /> Current
                  </Button>
                  <Button variant="outline" onClick={handleRegimeHistory} disabled={!regimeDsId}>
                    <BarChart3 className="h-4 w-4 mr-1" /> History
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Training Result */}
          {regimeResult && (
            <Card className="bg-card-bg border-card-border">
              <CardContent className="p-5 space-y-3">
                <h4 className="text-sm font-semibold text-green-400">Training Complete</h4>
                <div className="grid grid-cols-3 gap-3 text-sm">
                  <div><span className="text-muted-foreground">Bars:</span> {regimeResult.n_bars}</div>
                  <div><span className="text-muted-foreground">States:</span> {regimeResult.n_states}</div>
                  <div><span className="text-muted-foreground">Log-Likelihood:</span> {regimeResult.log_likelihood?.toFixed(2)}</div>
                </div>
                {regimeResult.regime_stats && (
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2">
                    {Object.entries(regimeResult.regime_stats).map(([name, stats]: [string, unknown]) => {
                      const s = stats as Record<string, number>;
                      return (
                        <div key={name} className={`rounded-lg border p-3 ${regimeColor(name)}`}>
                          <div className="text-xs font-semibold capitalize">{name.replace(/_/g, " ")}</div>
                          <div className="text-lg font-bold">{s.pct}%</div>
                          <div className="text-[10px] mt-1">
                            Avg return: {(s.return_mean * 100).toFixed(3)}% | Vol: {(s.vol_mean * 100).toFixed(3)}%
                          </div>
                          <div className="text-[10px]">{s.count} bars</div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Current Regime */}
          {regimeCurrent && (
            <Card className="bg-card-bg border-card-border">
              <CardContent className="p-5 space-y-3">
                <h4 className="text-sm font-semibold">Current Market Regime</h4>
                <div className="flex items-center gap-4">
                  <Badge className={`text-base px-4 py-2 ${regimeColor(regimeCurrent.regime)}`}>
                    {regimeCurrent.regime?.replace(/_/g, " ")}
                  </Badge>
                  <span className="text-sm text-muted-foreground">
                    Confidence: {(regimeCurrent.confidence * 100).toFixed(1)}%
                  </span>
                </div>
                {regimeCurrent.probabilities && (
                  <div className="space-y-1 mt-2">
                    {Object.entries(regimeCurrent.probabilities).map(([name, prob]: [string, unknown]) => (
                      <div key={name} className="flex items-center gap-2 text-xs">
                        <span className="w-28 text-muted-foreground capitalize">{name.replace(/_/g, " ")}</span>
                        <div className="flex-1 h-2 bg-zinc-800 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${
                              name === "trending_up" ? "bg-green-500" :
                              name === "trending_down" ? "bg-red-500" :
                              name === "ranging" ? "bg-blue-500" : "bg-orange-500"
                            }`}
                            style={{ width: `${(prob as number) * 100}%` }}
                          />
                        </div>
                        <span className="w-12 text-right">{((prob as number) * 100).toFixed(1)}%</span>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Regime History */}
          {regimeHistory.length > 0 && (
            <Card className="bg-card-bg border-card-border">
              <CardContent className="p-5">
                <h4 className="text-sm font-semibold mb-3">Regime History ({regimeHistory.length} bars)</h4>
                <div className="flex h-8 rounded overflow-hidden">
                  {regimeHistory.map((r, i) => (
                    <div
                      key={i}
                      className={`flex-1 ${
                        r.regime === "trending_up" ? "bg-green-500" :
                        r.regime === "trending_down" ? "bg-red-500" :
                        r.regime === "ranging" ? "bg-blue-500" : "bg-orange-500"
                      }`}
                      title={`${r.datetime || i}: ${r.regime}`}
                    />
                  ))}
                </div>
                <div className="flex justify-between mt-2 text-[10px] text-muted-foreground">
                  <span>{regimeHistory[0]?.datetime?.split("T")[0] || "start"}</span>
                  <span>{regimeHistory[regimeHistory.length - 1]?.datetime?.split("T")[0] || "end"}</span>
                </div>
                {/* Legend */}
                <div className="flex gap-4 mt-2 text-[10px]">
                  <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-green-500"/> Trending Up</span>
                  <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-red-500"/> Trending Down</span>
                  <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-blue-500"/> Ranging</span>
                  <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-orange-500"/> Volatile</span>
                </div>
                {/* Breakdown */}
                <div className="grid grid-cols-4 gap-2 mt-3 text-xs">
                  {["trending_up", "trending_down", "ranging", "volatile"].map(r => {
                    const count = regimeHistory.filter(h => h.regime === r).length;
                    return (
                      <div key={r} className={`rounded p-2 text-center ${regimeColor(r)}`}>
                        <div className="capitalize text-[10px]">{r.replace(/_/g, " ")}</div>
                        <div className="font-bold">{((count / regimeHistory.length) * 100).toFixed(1)}%</div>
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* ── LSTM FORECAST VIEW ──────────── */}
      {view === "forecast" && (
        <div className="space-y-4">
          <Card className="bg-card-bg border-card-border">
            <CardContent className="p-5 space-y-4">
              <h3 className="text-sm font-semibold text-accent flex items-center gap-2">
                <TrendingUp className="h-4 w-4" /> LSTM/GRU Price Range Forecaster
              </h3>
              <p className="text-xs text-muted-foreground">
                Train a deep learning model to predict future price distribution (mean, std, p20, p80) for dynamic SL/TP placement.
                Requires PyTorch for training (local only). Inference uses ONNX Runtime.
              </p>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div>
                  <Label className="text-xs">Datasource</Label>
                  <select
                    className="w-full mt-1 rounded-md bg-zinc-900 border border-zinc-700 text-sm p-2"
                    value={lstmDsId}
                    onChange={e => setLstmDsId(Number(e.target.value))}
                  >
                    <option value={0}>Select datasource...</option>
                    {dataSources.map(ds => (
                      <option key={ds.id} value={ds.id}>{ds.filename}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <Label className="text-xs">Cell Type</Label>
                  <select
                    className="w-full mt-1 rounded-md bg-zinc-900 border border-zinc-700 text-sm p-2"
                    value={lstmCell}
                    onChange={e => setLstmCell(e.target.value)}
                  >
                    <option value="lstm">LSTM</option>
                    <option value="gru">GRU</option>
                  </select>
                </div>
                <div>
                  <Label className="text-xs">Model ID</Label>
                  <Input type="number" className="mt-1" value={lstmModelId} onChange={e => setLstmModelId(Number(e.target.value))} />
                </div>
                <div>
                  <Label className="text-xs">Hidden Size</Label>
                  <Input type="number" className="mt-1" value={lstmHidden} onChange={e => setLstmHidden(Number(e.target.value))} />
                </div>
                <div>
                  <Label className="text-xs">Seq Length</Label>
                  <Input type="number" className="mt-1" value={lstmSeqLen} onChange={e => setLstmSeqLen(Number(e.target.value))} />
                </div>
                <div>
                  <Label className="text-xs">Horizon (bars)</Label>
                  <Input type="number" className="mt-1" value={lstmHorizon} onChange={e => setLstmHorizon(Number(e.target.value))} />
                </div>
                <div>
                  <Label className="text-xs">Epochs</Label>
                  <Input type="number" className="mt-1" value={lstmEpochs} onChange={e => setLstmEpochs(Number(e.target.value))} />
                </div>
                <div className="flex items-end gap-2">
                  <Button onClick={handleLstmTrain} disabled={lstmTraining || !lstmDsId} className="gap-1.5">
                    {lstmTraining ? <Loader2 className="h-4 w-4 animate-spin" /> : <Brain className="h-4 w-4" />}
                    Train
                  </Button>
                  <Button variant="outline" onClick={handleLstmPredict} disabled={!lstmDsId}>
                    <Play className="h-4 w-4 mr-1" /> Predict
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* LSTM Training Result */}
          {lstmResult && (
            <Card className="bg-card-bg border-card-border">
              <CardContent className="p-5 space-y-3">
                <h4 className="text-sm font-semibold text-green-400">Training Complete</h4>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                  <div><span className="text-muted-foreground">Cell:</span> {lstmResult.cell_type?.toUpperCase()}</div>
                  <div><span className="text-muted-foreground">Features:</span> {lstmResult.n_features}</div>
                  <div><span className="text-muted-foreground">Train:</span> {lstmResult.n_train} samples</div>
                  <div><span className="text-muted-foreground">Val:</span> {lstmResult.n_val} samples</div>
                  <div><span className="text-muted-foreground">Best Val Loss:</span> {lstmResult.best_val_loss?.toFixed(6)}</div>
                  <div><span className="text-muted-foreground">Direction Acc:</span> <span className="text-green-400">{(lstmResult.direction_accuracy * 100).toFixed(1)}%</span></div>
                  <div><span className="text-muted-foreground">Model Size:</span> {lstmResult.model_size_kb} KB</div>
                  <div><span className="text-muted-foreground">Horizon:</span> {lstmResult.horizon} bars</div>
                </div>
                {/* Loss curve (simplified) */}
                {lstmResult.val_losses && (
                  <div className="mt-2">
                    <span className="text-xs text-muted-foreground">Val loss (last 10 epochs):</span>
                    <div className="flex items-end gap-1 h-12 mt-1">
                      {lstmResult.val_losses.map((l: number, i: number) => {
                        const max = Math.max(...lstmResult.val_losses);
                        const h = max > 0 ? (l / max) * 100 : 0;
                        return (
                          <div key={i} className="flex-1 bg-accent/30 rounded-t" style={{ height: `${h}%` }} title={l.toFixed(6)} />
                        );
                      })}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* LSTM Forecast */}
          {lstmForecast && (
            <Card className="bg-card-bg border-card-border">
              <CardContent className="p-5 space-y-3">
                <h4 className="text-sm font-semibold">Price Forecast ({lstmForecast.horizon} bars ahead)</h4>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                  <div className="rounded-lg border border-zinc-700 p-3 text-center">
                    <div className="text-[10px] text-muted-foreground">Current Price</div>
                    <div className="text-lg font-bold">{lstmForecast.current_price?.toFixed(2)}</div>
                  </div>
                  <div className="rounded-lg border border-zinc-700 p-3 text-center">
                    <div className="text-[10px] text-muted-foreground">Mean Return</div>
                    <div className={`text-lg font-bold ${lstmForecast.predicted_mean_return > 0 ? "text-green-400" : "text-red-400"}`}>
                      {(lstmForecast.predicted_mean_return * 100).toFixed(3)}%
                    </div>
                  </div>
                  <div className="rounded-lg border border-zinc-700 p-3 text-center">
                    <div className="text-[10px] text-muted-foreground">Volatility (std)</div>
                    <div className="text-lg font-bold text-orange-400">{(lstmForecast.predicted_std * 100).toFixed(3)}%</div>
                  </div>
                  <div className="rounded-lg border border-zinc-700 p-3 text-center">
                    <div className="text-[10px] text-muted-foreground">Range (P20-P80)</div>
                    <div className="text-sm font-bold">
                      <span className="text-red-400">{(lstmForecast.predicted_p20 * 100).toFixed(3)}%</span>
                      {" → "}
                      <span className="text-green-400">{(lstmForecast.predicted_p80 * 100).toFixed(3)}%</span>
                    </div>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3 mt-2 text-sm">
                  <div className="rounded-lg border border-green-500/30 bg-green-500/5 p-3">
                    <div className="text-[10px] text-green-400">Long Setup</div>
                    <div>TP: <span className="font-bold">{lstmForecast.tp_price_long?.toFixed(2)}</span></div>
                    <div>SL: <span className="font-bold">{lstmForecast.sl_price_long?.toFixed(2)}</span></div>
                  </div>
                  <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3">
                    <div className="text-[10px] text-red-400">Short Setup</div>
                    <div>TP: <span className="font-bold">{lstmForecast.tp_price_short?.toFixed(2)}</span></div>
                    <div>SL: <span className="font-bold">{lstmForecast.sl_price_short?.toFixed(2)}</span></div>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      <ChatHelpers />
    </div>
  );
}
