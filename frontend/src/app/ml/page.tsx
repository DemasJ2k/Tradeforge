"use client";

import { useState, useEffect, useCallback } from "react";
import { api, API_BASE } from "@/lib/api";
import ChatHelpers from "@/components/ChatHelpers";
import { Sparkles, Loader2, ArrowLeft, Brain, Trash2, Play, BarChart3, GitCompare, RefreshCw } from "lucide-react";
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
  const [view, setView] = useState<"list" | "detail" | "train" | "predict" | "compare">("list");
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
        normalize: tNormalize,
        zscore_window: tZscoreWindow,
        n_estimators: tNEst,
        max_depth: tMaxDepth,
        learning_rate: tLR,
        ...(tTarget === "triple_barrier" && { sl_atr_mult: tSlAtrMult, tp_atr_mult: tTpAtrMult, max_holding_bars: tMaxHoldBars }),
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
        <Button onClick={() => setView("train")} className="gap-1.5">
          <Brain className="h-4 w-4" /> Train New Model
        </Button>
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
                </div>
              </div>
              <div className="flex items-center gap-3">
                <Badge variant="secondary" className={`text-xs font-medium ${statusColor(selected.status)}`}>{selected.status}</Badge>
                {selected.status === "ready" && (
                  <>
                  <Button onClick={handleRetrain} disabled={retraining} variant="outline" className="gap-1.5 border-accent/40 text-accent hover:bg-accent/10">
                    {retraining ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Retraining...</> : <><RefreshCw className="h-3.5 w-3.5" /> Walk-Forward Retrain</>}
                  </Button>
                  <Button onClick={() => { setPDsId(0); setPredictions(null); setView("predict"); }} className="gap-1.5">
                    <Play className="h-3.5 w-3.5" /> Run Predictions
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
                  {Object.entries(selected.val_metrics).map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between">
                      <span className="text-xs text-muted-foreground capitalize">{k.replace(/_/g, " ")}</span>
                      <span className="text-sm font-medium">{typeof v === "number" ? (v < 1 ? pct(v) : v.toFixed(4)) : String(v)}</span>
                    </div>
                  ))}
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

      <ChatHelpers />
    </div>
  );
}
