"use client";

import { useCallback, useEffect, useState, useRef, useMemo } from "react";
import { api } from "@/lib/api";
import type { Strategy, StrategyList } from "@/types";
import StrategyEditor from "@/components/StrategyEditor";
import StrategySettingsModal from "@/components/StrategySettingsModal";
import ChatHelpers from "@/components/ChatHelpers";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Plus, Upload, Layers, Settings, Copy, Trash2, Pencil, Eye, Lock, Loader2, X, Sparkles, BarChart3, Search, FolderPlus, FolderOpen, ChevronDown, ChevronRight, FolderIcon, ShieldCheck, TrendingUp } from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/* Strategies to auto-delete on first load */
const STALE_STRATEGY_NAMES = [
  "200-EMA + VWAP Trend Scalper",
  "Pivot Point Breakout/Reversal",
  "RSI + Bollinger Band Reversal",
  "VWAP + MACD Breakout Scalper",
];

export default function StrategiesPage() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [editing, setEditing] = useState<Strategy | null>(null);
  const [creating, setCreating] = useState(false);

  // AI Import state
  const [showAiModal, setShowAiModal] = useState(false);
  const [aiFile, setAiFile] = useState<File | null>(null);
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState("");
  const [aiResult, setAiResult] = useState<Partial<Strategy> | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // File upload state
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadName, setUploadName] = useState("");
  const [uploadLoading, setUploadLoading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const uploadRef = useRef<HTMLInputElement>(null);

  // Settings modal state
  const [settingsStrategy, setSettingsStrategy] = useState<Strategy | null>(null);

  // Search filter
  const [search, setSearch] = useState("");

  // Folder state
  const [collapsedFolders, setCollapsedFolders] = useState<Set<string>>(new Set());
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [movingStrategy, setMovingStrategy] = useState<Strategy | null>(null);

  const filtered = useMemo(
    () =>
      strategies.filter(
        (s) =>
          !search ||
          s.name.toLowerCase().includes(search.toLowerCase()) ||
          (s.description || "").toLowerCase().includes(search.toLowerCase()) ||
          (s.strategy_type || "").toLowerCase().includes(search.toLowerCase())
      ),
    [strategies, search]
  );

  // Group strategies by folder
  const grouped = useMemo(() => {
    const systemStrats = filtered.filter((s) => s.is_system);
    const userStrats = filtered.filter((s) => !s.is_system);

    const folders = new Map<string, Strategy[]>();
    const root: Strategy[] = [];

    for (const s of userStrats) {
      const f = s.folder;
      if (f) {
        if (!folders.has(f)) folders.set(f, []);
        folders.get(f)!.push(s);
      } else {
        root.push(s);
      }
    }

    // All unique folder names (including empty ones from collapsed)
    const allFolders = Array.from(folders.keys()).sort();

    return { systemStrats, root, folders, allFolders };
  }, [filtered]);

  const load = useCallback(async () => {
    try {
      const data = await api.get<StrategyList>("/api/strategies");
      setStrategies(data.items);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Auto-delete stale strategies on first load
  const staleCleanedRef = useRef(false);
  useEffect(() => {
    if (staleCleanedRef.current || strategies.length === 0) return;
    staleCleanedRef.current = true;
    const toDelete = strategies.filter((s) => STALE_STRATEGY_NAMES.includes(s.name) && !s.is_system);
    if (toDelete.length === 0) return;
    Promise.all(toDelete.map((s) => api.delete(`/api/strategies/${s.id}`).catch(() => {}))).then(() => {
      setStrategies((prev) => prev.filter((s) => !STALE_STRATEGY_NAMES.includes(s.name) || s.is_system));
    });
  }, [strategies]);

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

  const toggleFolder = (name: string) => {
    setCollapsedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const createFolder = () => {
    const name = newFolderName.trim();
    if (!name) return;
    // Just toggle it open; folders are implicit from strategies
    setCollapsedFolders((prev) => { const n = new Set(prev); n.delete(name); return n; });
    setShowNewFolder(false);
    setNewFolderName("");
  };

  const moveToFolder = async (strat: Strategy, folder: string | null) => {
    try {
      await api.put(`/api/strategies/${strat.id}`, { folder: folder || null });
      setStrategies((prev) =>
        prev.map((s) => (s.id === strat.id ? { ...s, folder: folder || undefined } : s))
      );
    } catch { /* ignore */ }
    setMovingStrategy(null);
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

  /* ── File Upload ──────────────────────────────────── */
  const handleFileUpload = async () => {
    if (!uploadFile) return;
    setUploadLoading(true);
    setUploadError("");
    try {
      const token = localStorage.getItem("token");
      const form = new FormData();
      form.append("file", uploadFile);
      if (uploadName.trim()) form.append("name", uploadName.trim());

      const res = await fetch(`${API}/api/strategies/upload`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      setShowUploadModal(false);
      setUploadFile(null);
      setUploadName("");
      await load();
    } catch (e: unknown) {
      setUploadError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploadLoading(false);
    }
  };

  const closeUploadModal = () => {
    setShowUploadModal(false);
    setUploadFile(null);
    setUploadName("");
    setUploadError("");
  };

  const handleSettingsSaved = (updated: Strategy) => {
    setStrategies((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
    setSettingsStrategy(null);
  };

  // Get all existing folder names for move-to menu
  const allFolderNames = useMemo(() => {
    const names = new Set<string>();
    for (const s of strategies) {
      if (s.folder) names.add(s.folder);
    }
    return Array.from(names).sort();
  }, [strategies]);

  // ── Strategy Card ──
  const StrategyCard = ({ s }: { s: Strategy }) => (
    <Card
      key={s.id}
      className="bg-card-bg border-card-border hover:border-accent/30 transition-colors"
    >
      <CardContent className="p-4">
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-foreground truncate flex items-center gap-2 text-sm">
            {s.is_system && <Lock className="h-3.5 w-3.5 text-accent shrink-0" />}
            {s.strategy_type === "python" && <span title="Python strategy" className="shrink-0">🐍</span>}
            {s.strategy_type === "json" && <span title="JSON strategy" className="shrink-0">📋</span>}
            {s.strategy_type === "pinescript" && <span title="Pine Script strategy" className="shrink-0">🌲</span>}
            {s.name}
            {s.is_system && (
              <Badge variant="outline" className="text-accent border-accent/30 text-[10px]">System</Badge>
            )}
          </h3>
          {s.description && (
            <p className="text-xs text-muted-foreground mt-1 line-clamp-1">{s.description}</p>
          )}
          {/* Verified performance badges */}
          {s.verified_performance && (
            <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
              <Badge className="bg-emerald-500/15 text-emerald-400 border-0 text-[10px] flex items-center gap-1">
                <ShieldCheck className="h-3 w-3" />
                {s.verified_performance.robustness === "GOOD" ? "Verified" : s.verified_performance.robustness}
              </Badge>
              <Badge className="bg-blue-500/10 text-blue-400 border-0 text-[10px]">
                PF {s.verified_performance.profit_factor.toFixed(2)}
              </Badge>
              <Badge className="bg-green-500/10 text-green-400 border-0 text-[10px]">
                WR {s.verified_performance.win_rate.toFixed(0)}%
              </Badge>
              <Badge className="bg-amber-500/10 text-amber-400 border-0 text-[10px]">
                DD {s.verified_performance.max_dd_pct.toFixed(1)}%
              </Badge>
              <Badge className="bg-purple-500/10 text-purple-300 border-0 text-[10px]">
                {s.verified_performance.symbol} {s.verified_performance.tf}
              </Badge>
              <Badge className="bg-cyan-500/10 text-cyan-400 border-0 text-[10px]">
                WF {s.verified_performance.wf_score}%
              </Badge>
            </div>
          )}
          <div className="flex flex-wrap gap-1.5 mt-1.5">
            {s.strategy_type && s.strategy_type !== "builder" && (
              <Badge className="bg-purple-500/10 text-purple-400 border-0 text-[10px]">
                {s.strategy_type === "python" ? "🐍 Python" : s.strategy_type === "json" ? "📋 JSON" : s.strategy_type === "pinescript" ? "🌲 Pine Script" : s.strategy_type}
              </Badge>
            )}
            {(!s.strategy_type || s.strategy_type === "builder") && (
              <>
                <Badge className="bg-accent/10 text-accent border-0 text-[10px]">{s.indicators?.length || 0} ind</Badge>
                <Badge className="bg-success/10 text-success border-0 text-[10px]">{s.entry_rules?.length || 0} entry</Badge>
                <Badge className="bg-danger/10 text-danger border-0 text-[10px]">{s.exit_rules?.length || 0} exit</Badge>
              </>
            )}
            {s.settings_schema?.length > 0 && (
              <Badge className="bg-fa-accent/10 text-fa-accent border-0 text-[10px]">{s.settings_schema.length} settings</Badge>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1 ml-3 shrink-0">
          {s.strategy_type && s.strategy_type !== "builder" && s.settings_schema?.length > 0 && (
            <Button variant="ghost" size="icon" onClick={() => setSettingsStrategy(s)} title="Strategy Settings" className="h-7 w-7 text-muted-foreground hover:text-accent">
              <Settings className="h-3.5 w-3.5" />
            </Button>
          )}
          {(!s.strategy_type || s.strategy_type === "builder") && (
            <Button variant="ghost" size="icon" onClick={() => setEditing(s)} title={s.is_system ? "View" : "Edit"} className="h-7 w-7 text-muted-foreground hover:text-accent">
              {s.is_system ? <Eye className="h-3.5 w-3.5" /> : <Pencil className="h-3.5 w-3.5" />}
            </Button>
          )}
          <Button variant="ghost" size="icon" onClick={() => handleDuplicate(s.id)} title="Duplicate" className="h-7 w-7 text-muted-foreground hover:text-foreground">
            <Copy className="h-3.5 w-3.5" />
          </Button>
          {!s.is_system && (
            <Button variant="ghost" size="icon" onClick={() => setMovingStrategy(s)} title="Move to folder" className="h-7 w-7 text-muted-foreground hover:text-foreground">
              <FolderOpen className="h-3.5 w-3.5" />
            </Button>
          )}
          <Button variant="ghost" size="icon" onClick={() => handleDelete(s.id)} title="Delete" className="h-7 w-7 text-muted-foreground hover:text-danger">
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
      </CardContent>
    </Card>
  );

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
    <div className="space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <h2 className="text-lg sm:text-xl font-semibold">Strategies</h2>
        <div className="flex items-center gap-2 flex-wrap">
          <Button variant="outline" size="sm" onClick={() => setShowNewFolder(true)} className="gap-1.5 text-xs">
            <FolderPlus className="h-3.5 w-3.5" />
            New Folder
          </Button>
          <Button variant="outline" size="sm" onClick={() => setShowUploadModal(true)} className="gap-1.5 text-xs">
            <Upload className="h-3.5 w-3.5" />
            Upload
          </Button>
          <Button variant="outline" size="sm" onClick={() => setShowAiModal(true)} className="gap-1.5 text-xs border-accent/40 text-accent hover:bg-accent/10">
            <Sparkles className="h-3.5 w-3.5" />
            AI Import
          </Button>
          <Button size="sm" onClick={() => setCreating(true)} className="gap-1.5 text-xs bg-accent text-black hover:bg-accent/90">
            <Plus className="h-3.5 w-3.5" />
            New Strategy
          </Button>
        </div>
      </div>

      {/* Search / filter */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search strategies by name, description, or type..."
          className="pl-9 bg-card-bg border-card-border"
        />
      </div>

      {/* New Folder inline form */}
      {showNewFolder && (
        <div className="flex items-center gap-2">
          <FolderIcon className="h-4 w-4 text-accent" />
          <Input
            value={newFolderName}
            onChange={(e) => setNewFolderName(e.target.value)}
            placeholder="Folder name..."
            className="bg-card-bg border-card-border max-w-xs h-8 text-sm"
            autoFocus
            onKeyDown={(e) => { if (e.key === "Enter") createFolder(); if (e.key === "Escape") setShowNewFolder(false); }}
          />
          <Button size="sm" onClick={createFolder} disabled={!newFolderName.trim()} className="h-8 text-xs bg-accent text-black hover:bg-accent/90">
            Create
          </Button>
          <Button size="sm" variant="ghost" onClick={() => { setShowNewFolder(false); setNewFolderName(""); }} className="h-8 text-xs">
            Cancel
          </Button>
        </div>
      )}

      {deleteError && (
        <div className="rounded-lg bg-danger/10 border border-danger/30 px-4 py-3 text-sm text-danger flex items-center justify-between">
          <span>{deleteError}</span>
          <button onClick={() => setDeleteError("")} className="text-danger/60 hover:text-danger ml-4">✕</button>
        </div>
      )}

      {filtered.length === 0 ? (
        <Card className="bg-card-bg border-card-border">
          <CardContent className="p-12 text-center">
            <BarChart3 className="h-10 w-10 mx-auto mb-3 text-muted-foreground/40" />
            <p className="text-sm text-muted-foreground mb-4">
              No strategies yet. Create your first trading strategy or import one with AI.
            </p>
            <div className="flex items-center justify-center gap-3">
              <Button variant="outline" onClick={() => setShowAiModal(true)} className="border-accent/40 text-accent hover:bg-accent/10">
                AI Import
              </Button>
              <Button onClick={() => setCreating(true)} className="bg-accent text-black hover:bg-accent/90">
                Create Strategy
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {/* ── System strategies (collapsible) ── */}
          {grouped.systemStrats.length > 0 && (
            <div>
              <button
                onClick={() => toggleFolder("__system__")}
                className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 hover:text-foreground transition-colors w-full text-left"
              >
                {collapsedFolders.has("__system__") ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                <Lock className="h-3 w-3" />
                System Strategies
                <span className="text-muted-foreground/50 font-normal normal-case">({grouped.systemStrats.length})</span>
              </button>
              {!collapsedFolders.has("__system__") && (
                <div className="grid gap-2 ml-5">
                  {grouped.systemStrats.map((s) => <StrategyCard key={s.id} s={s} />)}
                </div>
              )}
            </div>
          )}

          {/* ── User folders ── */}
          {grouped.allFolders.map((folderName) => {
            const folderStrats = grouped.folders.get(folderName) || [];
            if (folderStrats.length === 0) return null;
            const isCollapsed = collapsedFolders.has(folderName);
            return (
              <div key={folderName}>
                <button
                  onClick={() => toggleFolder(folderName)}
                  className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 hover:text-foreground transition-colors w-full text-left"
                >
                  {isCollapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                  <FolderOpen className="h-3 w-3 text-accent" />
                  {folderName}
                  <span className="text-muted-foreground/50 font-normal normal-case">({folderStrats.length})</span>
                </button>
                {!isCollapsed && (
                  <div className="grid gap-2 ml-5">
                    {folderStrats.map((s) => <StrategyCard key={s.id} s={s} />)}
                  </div>
                )}
              </div>
            );
          })}

          {/* ── Root strategies (no folder) ── */}
          {grouped.root.length > 0 && (
            <div>
              {(grouped.allFolders.length > 0 || grouped.systemStrats.length > 0) && (
                <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-2">
                  <Layers className="h-3 w-3" />
                  My Strategies
                  <span className="text-muted-foreground/50 font-normal normal-case">({grouped.root.length})</span>
                </div>
              )}
              <div className="grid gap-2">
                {grouped.root.map((s) => <StrategyCard key={s.id} s={s} />)}
              </div>
            </div>
          )}
        </div>
      )}

      <ChatHelpers />

      {/* ── Move to Folder Modal ── */}
      {movingStrategy && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-2xl border border-card-border bg-card-bg p-5 shadow-2xl">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold flex items-center gap-2">
                <FolderOpen className="h-4 w-4 text-accent" />
                Move &quot;{movingStrategy.name}&quot;
              </h3>
              <button onClick={() => setMovingStrategy(null)} className="text-muted-foreground hover:text-foreground">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-1">
              <button
                onClick={() => moveToFolder(movingStrategy, null)}
                className={`w-full text-left text-sm px-3 py-2 rounded-lg hover:bg-muted/30 transition-colors flex items-center gap-2 ${
                  !movingStrategy.folder ? "bg-accent/10 text-accent" : "text-foreground"
                }`}
              >
                <Layers className="h-3.5 w-3.5" />
                No Folder (root)
              </button>
              {allFolderNames.map((f) => (
                <button
                  key={f}
                  onClick={() => moveToFolder(movingStrategy, f)}
                  className={`w-full text-left text-sm px-3 py-2 rounded-lg hover:bg-muted/30 transition-colors flex items-center gap-2 ${
                    movingStrategy.folder === f ? "bg-accent/10 text-accent" : "text-foreground"
                  }`}
                >
                  <FolderOpen className="h-3.5 w-3.5" />
                  {f}
                </button>
              ))}
            </div>
            {/* Create new folder inline */}
            <div className="mt-3 pt-3 border-t border-card-border">
              <div className="flex items-center gap-2">
                <Input
                  placeholder="New folder..."
                  className="bg-card-bg border-card-border h-8 text-sm flex-1"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.target as HTMLInputElement).value.trim()) {
                      moveToFolder(movingStrategy, (e.target as HTMLInputElement).value.trim());
                    }
                  }}
                />
                <span className="text-[10px] text-muted-foreground">Enter to move</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Settings Modal ─────────────────────────────── */}
      {settingsStrategy && (
        <StrategySettingsModal
          strategy={settingsStrategy}
          onClose={() => setSettingsStrategy(null)}
          onSaved={handleSettingsSaved}
        />
      )}

      {/* ── File Upload Modal ──────────────────────────── */}
      {showUploadModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl border border-card-border bg-card-bg p-6 shadow-2xl">
            <div className="flex items-center justify-between mb-5">
              <h3 className="text-lg font-semibold flex items-center gap-2">
                <Upload className="h-5 w-5 text-accent" />
                Upload Strategy File
              </h3>
              <button onClick={closeUploadModal} className="text-muted-foreground hover:text-foreground">
                <X className="h-5 w-5" />
              </button>
            </div>

            <p className="text-sm text-muted-foreground mb-4">
              Upload a strategy file (.py, .json, .pine). Parameters will be auto-detected
              and exposed as editable settings.
            </p>

            <div
              onClick={() => uploadRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
              onDrop={(e) => {
                e.preventDefault();
                e.stopPropagation();
                const f = e.dataTransfer.files?.[0];
                if (f) setUploadFile(f);
              }}
              className={`relative cursor-pointer rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
                uploadFile
                  ? "border-accent/50 bg-accent/5"
                  : "border-card-border hover:border-accent/30 hover:bg-card-bg"
              }`}
            >
              <input
                ref={uploadRef}
                type="file"
                accept=".py,.json,.pine,.pinescript"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) setUploadFile(f);
                }}
              />
              {uploadFile ? (
                <div>
                  <div className="text-2xl mb-2">📄</div>
                  <p className="text-sm font-medium">{uploadFile.name}</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    {(uploadFile.size / 1024).toFixed(1)} KB — Click to change
                  </p>
                </div>
              ) : (
                <div>
                  <div className="text-2xl mb-2">📁</div>
                  <p className="text-sm text-muted-foreground">Drag & drop a file here, or click to browse</p>
                  <p className="text-xs text-muted-foreground mt-1">.py, .json, .pine — max 5 MB</p>
                </div>
              )}
            </div>

            <div className="mt-4">
              <label className="block text-xs text-muted-foreground mb-1">Strategy Name (optional)</label>
              <input
                type="text"
                value={uploadName}
                onChange={(e) => setUploadName(e.target.value)}
                placeholder="Auto-detected from file if empty"
                className="w-full rounded-lg border border-card-border bg-card-bg px-3 py-2 text-sm text-foreground placeholder-muted/50 focus:border-accent focus:outline-none"
              />
            </div>

            {uploadError && (
              <div className="mt-3 rounded-lg bg-danger/10 border border-danger/30 px-3 py-2 text-sm text-danger">
                {uploadError}
              </div>
            )}

            <div className="mt-5 flex items-center justify-end gap-3">
              <Button variant="outline" onClick={closeUploadModal}>Cancel</Button>
              <Button
                onClick={handleFileUpload}
                disabled={!uploadFile || uploadLoading}
                className="bg-accent text-black hover:bg-accent/90 gap-2"
              >
                {uploadLoading ? <><Loader2 className="h-4 w-4 animate-spin" /> Uploading...</> : "Upload Strategy"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ── AI Import Modal ─────────────────────────────── */}
      {showAiModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl border border-card-border bg-card-bg p-6 shadow-2xl">
            <div className="flex items-center justify-between mb-5">
              <h3 className="text-lg font-semibold flex items-center gap-2">
                <Sparkles className="h-5 w-5 text-accent" />
                AI Strategy Import
              </h3>
              <button onClick={closeAiModal} className="text-muted-foreground hover:text-foreground">
                <X className="h-5 w-5" />
              </button>
            </div>

            <p className="text-sm text-muted-foreground mb-4">
              Upload a strategy document (.txt, .pine, .md, .pdf) and the AI will
              convert it into a FlowrexAlgo strategy you can review and edit.
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
                  <p className="text-xs text-muted-foreground mt-1">
                    {(aiFile.size / 1024).toFixed(1)} KB — Click to change
                  </p>
                </div>
              ) : (
                <div>
                  <div className="text-2xl mb-2">📁</div>
                  <p className="text-sm text-muted-foreground">
                    Drag & drop a file here, or click to browse
                  </p>
                  <p className="text-xs text-muted-foreground mt-1">
                    .txt, .pine, .md, .pdf — max 2 MB
                  </p>
                </div>
              )}
            </div>

            {/* Optional prompt */}
            <div className="mt-4">
              <label className="block text-xs text-muted-foreground mb-1">
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
              <Button variant="outline" onClick={closeAiModal}>Cancel</Button>
              <Button
                onClick={handleAiGenerate}
                disabled={!aiFile || aiLoading}
                className="bg-accent text-black hover:bg-accent/90 gap-2"
              >
                {aiLoading ? <><Loader2 className="h-4 w-4 animate-spin" /> Generating...</> : "Generate Strategy"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
