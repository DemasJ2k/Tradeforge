"use client";

import { useCallback, useState, useRef } from "react";
import { api } from "@/lib/api";
import type { Strategy, StrategyList } from "@/types";
import StrategyEditor from "@/components/StrategyEditor";
import ChatHelpers from "@/components/ChatHelpers";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function StrategiesPage() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [editing, setEditing] = useState<Strategy | null>(null);
  const [creating, setCreating] = useState(false);
  const [loaded, setLoaded] = useState(false);

  // AI Import state
  const [showAiModal, setShowAiModal] = useState(false);
  const [aiFile, setAiFile] = useState<File | null>(null);
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState("");
  const [aiResult, setAiResult] = useState<Partial<Strategy> | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.get<StrategyList>("/api/strategies");
      setStrategies(data.items);
    } catch {
      /* ignore */
    }
  }, []);

  if (!loaded) {
    setLoaded(true);
    load();
  }

  const [deleteError, setDeleteError] = useState("");

  const handleDelete = async (id: number) => {
    const strat = strategies.find((s) => s.id === id);
    const msg = strat
      ? `Delete "${strat.name}"? This will also remove all associated backtests, agents, ML models, and optimizations.`
      : "Delete this strategy?";
    if (!confirm(msg)) return;
    setDeleteError("");
    try {
      await api.delete(`/api/strategies/${id}`);
      setStrategies((prev) => prev.filter((s) => s.id !== id));
    } catch (e: unknown) {
      const msg2 = e instanceof Error ? e.message : "Failed to delete strategy";
      setDeleteError(msg2);
    }
  };

  const handleDuplicate = async (id: number) => {
    try {
      await api.post<Strategy>(`/api/strategies/${id}/duplicate`, {});
      await load();
    } catch { /* ignore */ }
  };

  const handleSaved = () => {
    setEditing(null);
    setCreating(false);
    setAiResult(null);
    load();
  };

  /* ── AI Import ──────────────────────────────────────── */
  const handleAiGenerate = async () => {
    if (!aiFile) return;
    setAiLoading(true);
    setAiError("");
    try {
      const token = localStorage.getItem("token");
      const form = new FormData();
      form.append("file", aiFile);
      if (aiPrompt.trim()) form.append("prompt", aiPrompt.trim());

      const res = await fetch(`${API}/api/strategies/ai-generate`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setAiResult(data as Partial<Strategy>);
      setShowAiModal(false);
    } catch (e: unknown) {
      setAiError(e instanceof Error ? e.message : "AI generation failed");
    } finally {
      setAiLoading(false);
    }
  };

  const closeAiModal = () => {
    setShowAiModal(false);
    setAiFile(null);
    setAiPrompt("");
    setAiError("");
  };

  // If AI result is ready, open StrategyEditor with pre-filled data
  if (aiResult) {
    return (
      <StrategyEditor
        strategy={aiResult as Strategy}
        onSave={handleSaved}
        onCancel={() => { setAiResult(null); }}
      />
    );
  }

  if (editing || creating) {
    return (
      <StrategyEditor
        strategy={editing}
        onSave={handleSaved}
        onCancel={() => { setEditing(null); setCreating(false); }}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Strategies</h2>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowAiModal(true)}
            className="rounded-lg border border-accent/40 bg-accent/10 px-4 py-2 text-sm font-medium text-accent hover:bg-accent/20 transition-colors flex items-center gap-1.5"
          >
            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M12 2L2 7l10 5 10-5-10-5z" /><path d="M2 17l10 5 10-5" /><path d="M2 12l10 5 10-5" />
            </svg>
            AI Import
          </button>
          <button
            onClick={() => setCreating(true)}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-black hover:bg-accent/90 transition-colors"
          >
            + New Strategy
          </button>
        </div>
      </div>

      {deleteError && (
        <div className="rounded-lg bg-danger/10 border border-danger/30 px-4 py-3 text-sm text-danger flex items-center justify-between">
          <span>{deleteError}</span>
          <button onClick={() => setDeleteError("")} className="text-danger/60 hover:text-danger ml-4">✕</button>
        </div>
      )}

      {strategies.length === 0 ? (
        <div className="rounded-xl border border-card-border bg-card-bg p-12 text-center">
          <div className="text-4xl mb-3">📊</div>
          <p className="text-sm text-muted mb-4">
            No strategies yet. Create your first trading strategy or import one with AI.
          </p>
          <div className="flex items-center justify-center gap-3">
            <button
              onClick={() => setShowAiModal(true)}
              className="rounded-lg border border-accent/40 bg-accent/10 px-4 py-2 text-sm font-medium text-accent hover:bg-accent/20"
            >
              AI Import
            </button>
            <button
              onClick={() => setCreating(true)}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-black hover:bg-accent/90"
            >
              Create Strategy
            </button>
          </div>
        </div>
      ) : (
        <div className="grid gap-4">
          {strategies.map((s) => (
            <div
              key={s.id}
              className="rounded-xl border border-card-border bg-card-bg p-5 hover:border-accent/30 transition-colors"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <h3 className="font-semibold text-foreground truncate flex items-center gap-2">
                    {s.is_system && (
                      <svg className="h-4 w-4 text-accent shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                        <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                        <path d="M7 11V7a5 5 0 0110 0v4" />
                      </svg>
                    )}
                    {s.name}
                    {s.is_system && (
                      <span className="inline-flex items-center rounded-full bg-accent/15 text-accent px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider">
                        System
                      </span>
                    )}
                  </h3>
                  {s.description && (
                    <p className="text-sm text-muted mt-1 line-clamp-2">{s.description}</p>
                  )}
                  <div className="flex flex-wrap gap-2 mt-3">
                    <span className="inline-flex items-center rounded-md bg-accent/10 text-accent px-2 py-0.5 text-xs font-medium">
                      {s.indicators?.length || 0} indicators
                    </span>
                    <span className="inline-flex items-center rounded-md bg-success/10 text-success px-2 py-0.5 text-xs font-medium">
                      {s.entry_rules?.length || 0} entry rules
                    </span>
                    <span className="inline-flex items-center rounded-md bg-danger/10 text-danger px-2 py-0.5 text-xs font-medium">
                      {s.exit_rules?.length || 0} exit rules
                    </span>
                    {s.risk_params?.stop_loss_type && (
                      <span className="inline-flex items-center rounded-md bg-blue-500/10 text-blue-400 px-2 py-0.5 text-xs font-medium">
                        SL: {s.risk_params.stop_loss_value} {s.risk_params.stop_loss_type}
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2 ml-4">
                  <button
                    onClick={() => setEditing(s)}
                    className="rounded-lg border border-card-border px-3 py-1.5 text-xs text-muted hover:text-foreground hover:border-accent/50 transition-colors"
                  >
                    {s.is_system ? "View" : "Edit"}
                  </button>
                  <button
                    onClick={() => handleDuplicate(s.id)}
                    className="rounded-lg border border-card-border px-3 py-1.5 text-xs text-muted hover:text-foreground hover:border-accent/50 transition-colors"
                  >
                    Duplicate
                  </button>
                  {!s.is_system && (
                    <button
                      onClick={() => handleDelete(s.id)}
                      className="rounded-lg border border-card-border px-3 py-1.5 text-xs text-muted hover:text-danger hover:border-danger/50 transition-colors"
                    >
                      Delete
                    </button>
                  )}
                </div>
              </div>
              <div className="mt-3 text-xs text-muted">
                Updated {new Date(s.updated_at).toLocaleDateString()}
              </div>
            </div>
          ))}
        </div>
      )}

      <ChatHelpers />

      {/* ── AI Import Modal ─────────────────────────────── */}
      {showAiModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl border border-card-border bg-[#0e0e10] p-6 shadow-2xl">
            <div className="flex items-center justify-between mb-5">
              <h3 className="text-lg font-semibold flex items-center gap-2">
                <svg className="h-5 w-5 text-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                  <path d="M12 2L2 7l10 5 10-5-10-5z" /><path d="M2 17l10 5 10-5" /><path d="M2 12l10 5 10-5" />
                </svg>
                AI Strategy Import
              </h3>
              <button onClick={closeAiModal} className="text-muted hover:text-foreground">
                <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                  <path d="M18 6L6 18M6 6l12 12" />
                </svg>
              </button>
            </div>

            <p className="text-sm text-muted mb-4">
              Upload a strategy document (.txt, .pine, .md, .pdf) and the AI will
              convert it into a TradeForge strategy you can review and edit.
            </p>

            {/* File Drop Zone */}
            <div
              onClick={() => fileRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
              onDrop={(e) => {
                e.preventDefault();
                e.stopPropagation();
                const f = e.dataTransfer.files?.[0];
                if (f) setAiFile(f);
              }}
              className={`relative cursor-pointer rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
                aiFile
                  ? "border-accent/50 bg-accent/5"
                  : "border-card-border hover:border-accent/30 hover:bg-card-bg"
              }`}
            >
              <input
                ref={fileRef}
                type="file"
                accept=".txt,.pine,.pinescript,.md,.pdf,.text"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) setAiFile(f);
                }}
              />
              {aiFile ? (
                <div>
                  <div className="text-2xl mb-2">📄</div>
                  <p className="text-sm font-medium">{aiFile.name}</p>
                  <p className="text-xs text-muted mt-1">
                    {(aiFile.size / 1024).toFixed(1)} KB — Click to change
                  </p>
                </div>
              ) : (
                <div>
                  <div className="text-2xl mb-2">📁</div>
                  <p className="text-sm text-muted">
                    Drag & drop a file here, or click to browse
                  </p>
                  <p className="text-xs text-muted mt-1">
                    .txt, .pine, .md, .pdf — max 2 MB
                  </p>
                </div>
              )}
            </div>

            {/* Optional prompt */}
            <div className="mt-4">
              <label className="block text-xs text-muted mb-1">
                Additional instructions (optional)
              </label>
              <textarea
                value={aiPrompt}
                onChange={(e) => setAiPrompt(e.target.value)}
                placeholder='e.g. "Focus on the scalping strategy", "Use ATR for stops"...'
                className="w-full rounded-lg border border-card-border bg-card-bg px-3 py-2 text-sm text-foreground placeholder-muted/50 focus:border-accent focus:outline-none resize-none"
                rows={2}
              />
            </div>

            {aiError && (
              <div className="mt-3 rounded-lg bg-danger/10 border border-danger/30 px-3 py-2 text-sm text-danger">
                {aiError}
              </div>
            )}

            <div className="mt-5 flex items-center justify-end gap-3">
              <button
                onClick={closeAiModal}
                className="rounded-lg border border-card-border px-4 py-2 text-sm text-muted hover:text-foreground transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleAiGenerate}
                disabled={!aiFile || aiLoading}
                className="rounded-lg bg-accent px-5 py-2 text-sm font-medium text-black hover:bg-accent/90 transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {aiLoading ? (
                  <>
                    <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Generating...
                  </>
                ) : (
                  "Generate Strategy"
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
