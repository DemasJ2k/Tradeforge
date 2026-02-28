"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import ChatHelpers from "@/components/ChatHelpers";
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
  if (s === "training") return "bg-blue-500/20 text-blue-400 animate-pulse";
  if (s === "failed") return "bg-red-500/20 text-red-400";
  return "bg-zinc-500/20 text-zinc-400";
};
const levelLabel = (l: number) =>
  l === 1 ? "L1: Adaptive Params" : l === 2 ? "L2: Signal Prediction" : "L3: Advanced ML";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/* ═══════════════════════════════════════════════════ */

export default function MLPage() {
  /* ── state ──────────────────────────────────── */
  const [view, setView] = useState<"list" | "detail" | "train" | "predict">("list");
  const [models, setModels] = useState<MLModelListItem[]>([]);
  const [selected, setSelected] = useState<MLModelDetail | null>(null);
  const [predictions, setPredictions] = useState<MLPredictionResult | null>(null);
  const [features, setFeatures] = useState<FeatureList | null>(null);
  const [dataSources, setDataSources] = useState<DataSource[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Train form state
  const [tName, setTName] = useState("");
  const [tLevel, setTLevel] = useState(2);
  const [tModelType, setTModelType] = useState("random_forest");
  const [tDsId, setTDsId] = useState<number>(0);
  const [tSymbol, setTSymbol] = useState("");
  const [tTimeframe, setTTimeframe] = useState("H1");
  const [tTarget, setTTarget] = useState("direction");
  const [tHorizon, setTHorizon] = useState(1);
  const [tNEst, setTNEst] = useState(100);
  const [tMaxDepth, setTMaxDepth] = useState(10);
  const [tLR, setTLR] = useState(0.1);
  const [tFeatures, setTFeatures] = useState<string[]>([]);

  // Level 3 config
  const [l3SubType, setL3SubType] = useState('lstm');
  const [l3SeqLen, setL3SeqLen] = useState(20);
  const [l3Units, setL3Units] = useState(64);

  // Predict form
  const [pDsId, setPDsId] = useState<number>(0);
  const [pBars, setPBars] = useState(50);

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
      const result = await api.post<MLModelDetail>("/api/ml/train", {
        name: tName,
        level: tLevel,
        model_type: tModelType,
        datasource_id: tDsId,
        symbol: tSymbol,
        timeframe: tTimeframe,
        target_type: tTarget,
        target_horizon: tHorizon,
        features: tFeatures.length > 0 ? tFeatures : undefined,
        n_estimators: tNEst,
        max_depth: tMaxDepth,
        learning_rate: tLR,
        ...(tLevel === 3 && { sub_type: l3SubType, seq_len: l3SeqLen, hidden_units: l3Units }),
      });
      setSelected(result);
      setView("detail");
      loadModels();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Training failed");
    } finally {
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

  /* ═══════════════ RENDER ═══════════════════════ */
  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-xl font-semibold">ML Lab</h2>
          {view !== "list" && (
            <button onClick={() => { setView("list"); setPredictions(null); }}
              className="text-sm text-muted hover:text-accent transition-colors">
              ← Back to Models
            </button>
          )}
        </div>
        <button onClick={() => setView("train")}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/80 transition-colors">
          Train New Model
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>
      )}

      {/* ── AI TRAINING ASSISTANT ─────────────── */}
      {view === "list" && (
        <div className="rounded-xl border border-accent/30 bg-accent/5 p-5">
          <div className="flex items-center gap-2 mb-3">
            <svg className="h-5 w-5 text-accent" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z" />
            </svg>
            <h3 className="text-sm font-semibold text-accent">AI Training Assistant</h3>
          </div>
          <p className="text-xs text-muted mb-3">
            Describe what you want to train in natural language. The AI will configure the model parameters for you.
          </p>

          <div className="flex gap-2">
            <textarea
              value={aiPrompt}
              onChange={e => setAiPrompt(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleAiInterpret(); } }}
              placeholder='e.g. "Train an XGBoost model on XAUUSD H1 data to predict next-bar direction using RSI, MACD, and Bollinger Bands"'
              rows={2}
              className="flex-1 rounded-lg border border-card-border bg-background px-3 py-2 text-sm resize-none focus:outline-none focus:border-accent placeholder:text-muted/60"
            />
            <button
              onClick={handleAiInterpret}
              disabled={aiLoading || !aiPrompt.trim()}
              className="self-end rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/80 disabled:opacity-40 transition-colors whitespace-nowrap"
            >
              {aiLoading ? (
                <span className="flex items-center gap-2">
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  Interpreting...
                </span>
              ) : "Configure with AI"}
            </button>
          </div>

          {/* Example prompts */}
          <div className="flex flex-wrap gap-2 mt-2">
            {[
              "Train XGBoost to predict XAUUSD direction",
              "Build a volatility predictor for gold on 5-min bars",
              "Random Forest on NAS100 H4 with trend features",
            ].map(ex => (
              <button key={ex} onClick={() => setAiPrompt(ex)}
                className="rounded-full border border-card-border px-3 py-1 text-[11px] text-muted hover:text-accent hover:border-accent/50 transition-colors">
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
                <span className="text-[10px] text-muted">
                  {aiPlan.tokens_used?.input ?? 0} / {aiPlan.tokens_used?.output ?? 0} tokens
                </span>
              </div>

              {aiPlan.explanation && (
                <p className="text-xs text-muted italic bg-background/50 rounded-lg px-3 py-2">
                  {aiPlan.explanation}
                </p>
              )}

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div>
                  <div className="text-[10px] text-muted uppercase tracking-wide">Model</div>
                  <div className="text-sm font-medium">{aiPlan.name}</div>
                </div>
                <div>
                  <div className="text-[10px] text-muted uppercase tracking-wide">Type</div>
                  <div className="text-sm font-medium">{aiPlan.model_type}</div>
                </div>
                <div>
                  <div className="text-[10px] text-muted uppercase tracking-wide">Level</div>
                  <div className="text-sm font-medium">{levelLabel(aiPlan.level)}</div>
                </div>
                <div>
                  <div className="text-[10px] text-muted uppercase tracking-wide">Target</div>
                  <div className="text-sm font-medium">{aiPlan.target_type} ({aiPlan.target_horizon} bar)</div>
                </div>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div>
                  <div className="text-[10px] text-muted uppercase tracking-wide">Dataset</div>
                  <div className="text-sm">{aiPlan.datasource_name || `ID ${aiPlan.datasource_id}`}</div>
                  {aiPlan.datasource_info && (
                    <div className="text-[10px] text-muted">{aiPlan.datasource_info}</div>
                  )}
                </div>
                <div>
                  <div className="text-[10px] text-muted uppercase tracking-wide">Symbol / TF</div>
                  <div className="text-sm font-medium">{aiPlan.symbol} {aiPlan.timeframe}</div>
                </div>
                <div>
                  <div className="text-[10px] text-muted uppercase tracking-wide">Estimators</div>
                  <div className="text-sm font-medium">{aiPlan.n_estimators}</div>
                </div>
                <div>
                  <div className="text-[10px] text-muted uppercase tracking-wide">Depth / LR</div>
                  <div className="text-sm font-medium">{aiPlan.max_depth} / {aiPlan.learning_rate}</div>
                </div>
              </div>

              {aiPlan.features.length > 0 && (
                <div>
                  <div className="text-[10px] text-muted uppercase tracking-wide mb-1">Features ({aiPlan.features.length})</div>
                  <div className="flex flex-wrap gap-1">
                    {aiPlan.features.map(f => (
                      <span key={f} className="rounded-full bg-accent/10 border border-accent/20 px-2 py-0.5 text-[10px] text-accent">
                        {f}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div className="flex gap-2 pt-1">
                <button onClick={trainFromPlan} disabled={loading}
                  className="rounded-lg bg-green-600 px-5 py-2 text-sm font-medium text-white hover:bg-green-500 disabled:opacity-40 transition-colors">
                  {loading ? "Training..." : "Train Now"}
                </button>
                <button onClick={applyAiPlan}
                  className="rounded-lg border border-accent/40 px-4 py-2 text-sm text-accent hover:bg-accent/10 transition-colors">
                  Edit First
                </button>
                <button onClick={() => setAiPlan(null)}
                  className="rounded-lg border border-card-border px-4 py-2 text-sm text-muted hover:text-foreground transition-colors">
                  Dismiss
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Level Overview Cards */}
      <div className="grid grid-cols-3 gap-4">
        {[1, 2, 3].map(level => {
          const levelModels = models.filter(m => m.level === level);
          const ready = levelModels.filter(m => m.status === "ready");
          return (
            <div key={level} className="rounded-xl border border-card-border bg-card-bg p-4">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-medium text-accent">
                  {level === 1 ? "Level 1: Adaptive Params" : level === 2 ? "Level 2: Signal Prediction" : "Level 3: Advanced ML"}
                </h3>
                <span className="text-xs text-muted">{ready.length} ready</span>
              </div>
              <p className="text-xs text-muted">
                {level === 1 && "ML predicts best strategy params for current market regime."}
                {level === 2 && "Predict next-bar direction/movement using trained classifiers."}
                {level === 3 && "LSTM time-series models and stacked ensemble classifiers (RF + XGB + LR)."}
              </p>
              {ready.length > 0 && (
                <div className="mt-2 text-xs">
                  Best val acc: <span className="text-green-400 font-medium">
                    {pct(Math.max(...ready.map(m => m.val_accuracy || 0)))}
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* ── MODEL LIST ──────────────────────────── */}
      {view === "list" && (
        <div className="rounded-xl border border-card-border bg-card-bg p-5">
          <h3 className="text-sm font-medium text-muted mb-4">Trained Models ({models.length})</h3>
          {models.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <div className="text-4xl mb-4">🧠</div>
              <h3 className="text-lg font-medium mb-2">No Models Yet</h3>
              <p className="text-sm text-muted mb-4 max-w-md">
                Train your first ML model by uploading price data and clicking &quot;Train New Model&quot;,
                or describe what you want to train using the AI assistant above.
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {models.map(m => (
                <div key={m.id}
                  className="flex items-center justify-between rounded-lg border border-card-border bg-background/50 p-3 hover:bg-background/80 cursor-pointer transition-colors"
                  onClick={() => openDetail(m.id)}>
                  <div className="flex items-center gap-3">
                    <span className={`rounded px-2 py-0.5 text-xs font-medium ${statusColor(m.status)}`}>{m.status}</span>
                    <div>
                      <div className="text-sm font-medium">{m.name}</div>
                      <div className="text-xs text-muted">
                        {levelLabel(m.level)} · {m.model_type} · {m.symbol || "—"} · {m.timeframe}
                        {m.level === 3 && (m as { architecture?: string }).architecture && (
                          <span className="ml-1 text-accent/70">· {(m as { architecture?: string }).architecture}</span>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-6">
                    <div className="text-right">
                      <div className="text-xs text-muted">Train / Val Accuracy</div>
                      <div className="text-sm font-medium">
                        <span className="text-blue-400">{pct(m.train_accuracy)}</span>
                        {" / "}
                        <span className="text-green-400">{pct(m.val_accuracy)}</span>
                      </div>
                    </div>
                    <div className="text-right text-xs text-muted">
                      {m.n_features} features
                    </div>
                    <button onClick={(e) => { e.stopPropagation(); handleDelete(m.id); }}
                      className="rounded border border-red-500/40 px-2 py-1 text-xs text-red-400 hover:bg-red-500/10 transition-colors">
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── TRAIN NEW MODEL ─────────────────────── */}
      {view === "train" && (
        <div className="rounded-xl border border-card-border bg-card-bg p-6 space-y-5">
          <h3 className="text-lg font-semibold">Train New Model</h3>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-muted mb-1">Model Name</label>
              <input value={tName} onChange={e => setTName(e.target.value)} placeholder="e.g. EURUSD Direction Predictor"
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-xs text-muted mb-1">Level</label>
              <select value={tLevel} onChange={e => setTLevel(Number(e.target.value))}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm">
                <option value={1}>Level 1: Adaptive Params</option>
                <option value={2}>Level 2: Signal Prediction</option>
                <option value={3}>Level 3: Advanced ML: LSTM &amp; Stacked Ensemble</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-xs text-muted mb-1">Model Type</label>
              <select value={tModelType} onChange={e => setTModelType(e.target.value)}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm">
                <option value="random_forest">Random Forest</option>
                <option value="xgboost">XGBoost</option>
                <option value="gradient_boosting">Gradient Boosting</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-muted mb-1">Data Source</label>
              <select value={tDsId} onChange={e => setTDsId(Number(e.target.value))}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm">
                <option value={0}>Select dataset...</option>
                {dataSources.map(ds => (
                  <option key={ds.id} value={ds.id}>{ds.filename} ({ds.symbol} {ds.timeframe}, {ds.row_count} bars)</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-muted mb-1">Prediction Target</label>
              <select value={tTarget} onChange={e => setTTarget(e.target.value)}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm">
                <option value="direction">Direction (Up/Down)</option>
                <option value="return">Return Magnitude</option>
                <option value="volatility">Volatility</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-4 gap-4">
            <div>
              <label className="block text-xs text-muted mb-1">Symbol</label>
              <input value={tSymbol} onChange={e => setTSymbol(e.target.value)} placeholder="Auto from dataset"
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-xs text-muted mb-1">Timeframe</label>
              <select value={tTimeframe} onChange={e => setTTimeframe(e.target.value)}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm">
                {["M1","M5","M15","M30","H1","H4","D1"].map(tf => <option key={tf} value={tf}>{tf}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs text-muted mb-1">Horizon (bars)</label>
              <input type="number" value={tHorizon} onChange={e => setTHorizon(Number(e.target.value))} min={1} max={20}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-xs text-muted mb-1">Estimators</label>
              <input type="number" value={tNEst} onChange={e => setTNEst(Number(e.target.value))} min={10} max={1000}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-muted mb-1">Max Depth</label>
              <input type="number" value={tMaxDepth} onChange={e => setTMaxDepth(Number(e.target.value))} min={2} max={30}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-xs text-muted mb-1">Learning Rate</label>
              <input type="number" step="0.01" value={tLR} onChange={e => setTLR(Number(e.target.value))} min={0.001} max={1}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
            </div>
          </div>

          {/* Level 3 Advanced ML config */}
          {tLevel === 3 && (
            <div className="space-y-3 p-3 rounded-lg border border-card-border bg-background/40">
              <div>
                <label className="block text-xs text-muted mb-1">Model Architecture</label>
                <select value={l3SubType} onChange={e => setL3SubType(e.target.value)}
                  className="w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm">
                  <option value="lstm">LSTM (time-series sequence model)</option>
                  <option value="ensemble">Stacked Ensemble (RF + XGB + Logistic)</option>
                </select>
              </div>
              {l3SubType === 'lstm' && (
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-muted mb-1">Sequence Length</label>
                    <input type="number" min="5" max="100" value={l3SeqLen}
                      onChange={e => setL3SeqLen(Number(e.target.value))}
                      className="w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm" />
                  </div>
                  <div>
                    <label className="block text-xs text-muted mb-1">Hidden Units</label>
                    <input type="number" min="16" max="256" step="16" value={l3Units}
                      onChange={e => setL3Units(Number(e.target.value))}
                      className="w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm" />
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Feature selection */}
          {features && (
            <div>
              <label className="block text-xs text-muted mb-2">Features (leave empty for all)</label>
              <div className="grid grid-cols-3 gap-2">
                {features.available_features.map(f => (
                  <label key={f} className="flex items-center gap-2 text-xs cursor-pointer">
                    <input type="checkbox" checked={tFeatures.includes(f)}
                      onChange={e => {
                        if (e.target.checked) setTFeatures([...tFeatures, f]);
                        else setTFeatures(tFeatures.filter(x => x !== f));
                      }}
                      className="accent-accent" />
                    <span>{f}</span>
                    <span className="text-muted ml-1">— {features.descriptions[f] || ""}</span>
                  </label>
                ))}
              </div>
            </div>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <button onClick={() => setView("list")}
              className="rounded-lg border border-card-border px-4 py-2 text-sm text-muted hover:text-foreground">
              Cancel
            </button>
            <button onClick={handleTrain} disabled={loading || !tName || !tDsId}
              className="rounded-lg bg-accent px-6 py-2 text-sm font-medium text-white hover:bg-accent/80 disabled:opacity-40">
              {loading ? "Training..." : "Train Model"}
            </button>
          </div>
        </div>
      )}

      {/* ── MODEL DETAIL ────────────────────────── */}
      {view === "detail" && selected && (
        <div className="space-y-4">
          {/* Model header */}
          <div className="rounded-xl border border-card-border bg-card-bg p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-lg font-semibold">{selected.name}</h3>
                <div className="text-sm text-muted mt-1">
                  {levelLabel(selected.level)} · {selected.model_type} · {selected.symbol} {selected.timeframe}
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className={`rounded px-2.5 py-1 text-xs font-medium ${statusColor(selected.status)}`}>{selected.status}</span>
                {selected.status === "ready" && (
                  <button onClick={() => { setPDsId(0); setPredictions(null); setView("predict"); }}
                    className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/80">
                    Run Predictions
                  </button>
                )}
              </div>
            </div>
            {selected.error_message && (
              <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
                {selected.error_message}
              </div>
            )}
          </div>

          {/* Metrics */}
          {selected.status === "ready" && (
            <div className="grid grid-cols-2 gap-4">
              <div className="rounded-xl border border-card-border bg-card-bg p-5">
                <h4 className="text-sm font-medium text-blue-400 mb-3">Training Metrics</h4>
                <div className="space-y-2">
                  {Object.entries(selected.train_metrics).map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between">
                      <span className="text-xs text-muted capitalize">{k.replace(/_/g, " ")}</span>
                      <span className="text-sm font-medium">{typeof v === "number" ? (v < 1 ? pct(v) : v.toFixed(4)) : String(v)}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="rounded-xl border border-card-border bg-card-bg p-5">
                <h4 className="text-sm font-medium text-green-400 mb-3">Validation Metrics</h4>
                <div className="space-y-2">
                  {Object.entries(selected.val_metrics).map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between">
                      <span className="text-xs text-muted capitalize">{k.replace(/_/g, " ")}</span>
                      <span className="text-sm font-medium">{typeof v === "number" ? (v < 1 ? pct(v) : v.toFixed(4)) : String(v)}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Feature Importance */}
          {selected.feature_importance && Object.keys(selected.feature_importance).length > 0 && (
            <div className="rounded-xl border border-card-border bg-card-bg p-5">
              <h4 className="text-sm font-medium text-muted mb-3">Feature Importance (top 15)</h4>
              <div className="space-y-1.5">
                {Object.entries(selected.feature_importance)
                  .slice(0, 15)
                  .map(([name, imp]) => {
                    const maxImp = Math.max(...Object.values(selected.feature_importance));
                    const widthPct = maxImp > 0 ? (imp / maxImp) * 100 : 0;
                    return (
                      <div key={name} className="flex items-center gap-3">
                        <span className="text-xs text-muted w-40 truncate">{name}</span>
                        <div className="flex-1 h-4 rounded bg-background/50 overflow-hidden">
                          <div className="h-full rounded bg-accent/60" style={{ width: `${widthPct}%` }} />
                        </div>
                        <span className="text-xs font-mono w-16 text-right">{(imp * 100).toFixed(2)}%</span>
                      </div>
                    );
                  })}
              </div>
            </div>
          )}

          {/* Config details */}
          <div className="grid grid-cols-3 gap-4">
            <div className="rounded-xl border border-card-border bg-card-bg p-4">
              <h4 className="text-xs font-medium text-muted mb-2">Target</h4>
              <div className="text-sm">
                {String((selected.target_config as Record<string,unknown>).type || "direction")} — {String((selected.target_config as Record<string,unknown>).horizon || 1)} bar(s)
              </div>
            </div>
            <div className="rounded-xl border border-card-border bg-card-bg p-4">
              <h4 className="text-xs font-medium text-muted mb-2">Hyperparameters</h4>
              <div className="text-xs space-y-1">
                {Object.entries(selected.hyperparams).map(([k, v]) => (
                  <div key={k}><span className="text-muted">{k}:</span> {String(v)}</div>
                ))}
              </div>
            </div>
            <div className="rounded-xl border border-card-border bg-card-bg p-4">
              <h4 className="text-xs font-medium text-muted mb-2">Timeline</h4>
              <div className="text-xs space-y-1">
                <div><span className="text-muted">Created:</span> {new Date(selected.created_at).toLocaleString()}</div>
                {selected.trained_at && <div><span className="text-muted">Trained:</span> {new Date(selected.trained_at).toLocaleString()}</div>}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── PREDICTIONS VIEW ────────────────────── */}
      {view === "predict" && (
        <div className="space-y-4">
          {/* Predict form */}
          {!predictions && selected && (
            <div className="rounded-xl border border-card-border bg-card-bg p-6 space-y-4">
              <h3 className="text-lg font-semibold">Run Predictions — {selected.name}</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-muted mb-1">Data Source</label>
                  <select value={pDsId} onChange={e => setPDsId(Number(e.target.value))}
                    className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm">
                    <option value={0}>Select dataset...</option>
                    {dataSources.map(ds => (
                      <option key={ds.id} value={ds.id}>{ds.filename} ({ds.row_count} bars)</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-muted mb-1">Last N Bars</label>
                  <input type="number" value={pBars} onChange={e => setPBars(Number(e.target.value))} min={10} max={500}
                    className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" />
                </div>
              </div>
              <div className="flex justify-end gap-3">
                <button onClick={() => { setView("detail"); setPredictions(null); }}
                  className="rounded-lg border border-card-border px-4 py-2 text-sm text-muted hover:text-foreground">
                  Cancel
                </button>
                <button onClick={handlePredict} disabled={loading || !pDsId}
                  className="rounded-lg bg-accent px-6 py-2 text-sm font-medium text-white hover:bg-accent/80 disabled:opacity-40">
                  {loading ? "Predicting..." : "Predict"}
                </button>
              </div>
            </div>
          )}

          {/* Prediction results */}
          {predictions && (
            <>
              <div className="grid grid-cols-3 gap-4">
                <div className="rounded-xl border border-card-border bg-card-bg p-4">
                  <div className="text-xs text-muted mb-1">Total Predictions</div>
                  <div className="text-lg font-semibold">{predictions.total_predictions}</div>
                </div>
                <div className="rounded-xl border border-card-border bg-card-bg p-4">
                  <div className="text-xs text-muted mb-1">Avg Confidence</div>
                  <div className="text-lg font-semibold">{pct(predictions.avg_confidence)}</div>
                </div>
                <div className="rounded-xl border border-card-border bg-card-bg p-4">
                  <div className="text-xs text-muted mb-1">Bull / Bear Split</div>
                  <div className="text-lg font-semibold">
                    <span className="text-green-400">
                      {predictions.predictions.filter(p => p.prediction >= 0.5).length}
                    </span>
                    {" / "}
                    <span className="text-red-400">
                      {predictions.predictions.filter(p => p.prediction < 0.5).length}
                    </span>
                  </div>
                </div>
              </div>

              {/* Signal bar chart */}
              <div className="rounded-xl border border-card-border bg-card-bg p-5">
                <h4 className="text-sm font-medium text-muted mb-3">Prediction Signal (last {Math.min(80, predictions.predictions.length)} bars)</h4>
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
                        <div className="absolute -top-8 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 bg-[#1a1a2e] border border-card-border rounded px-2 py-1 text-xs whitespace-nowrap z-10 pointer-events-none">
                          {isBull ? "↑ Bull" : "↓ Bear"} {(p.confidence * 100).toFixed(0)}%
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div className="flex justify-between text-xs text-muted mt-2">
                  <span>Oldest</span>
                  <span className="flex items-center gap-4">
                    <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm bg-green-500/70" /> Bull</span>
                    <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm bg-red-500/70" /> Bear</span>
                  </span>
                  <span>Newest</span>
                </div>
              </div>

              {/* Predictions table */}
              <div className="rounded-xl border border-card-border bg-card-bg p-5">
                <h4 className="text-sm font-medium text-muted mb-3">Detailed Predictions (last 20)</h4>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-card-border text-xs text-muted">
                        <th className="pb-2 text-left font-medium">Bar #</th>
                        <th className="pb-2 text-left font-medium">Signal</th>
                        <th className="pb-2 text-right font-medium">Confidence</th>
                        <th className="pb-2 text-right font-medium">Top Features</th>
                      </tr>
                    </thead>
                    <tbody>
                      {predictions.predictions.slice(-20).reverse().map((p, i) => (
                        <tr key={i} className="border-b border-card-border/50 last:border-0">
                          <td className="py-2">{p.bar_index}</td>
                          <td className="py-2">
                            <span className={`rounded px-2 py-0.5 text-xs font-medium ${
                              p.prediction >= 0.5 ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"
                            }`}>
                              {p.prediction >= 0.5 ? "↑ BULL" : "↓ BEAR"}
                            </span>
                          </td>
                          <td className="py-2 text-right">{(p.confidence * 100).toFixed(1)}%</td>
                          <td className="py-2 text-right text-xs text-muted">
                            {Object.entries(p.features || {}).slice(0, 3).map(([k, v]) =>
                              `${k}: ${typeof v === "number" ? v.toFixed(4) : v}`
                            ).join(", ")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      <ChatHelpers />
    </div>
  );
}
