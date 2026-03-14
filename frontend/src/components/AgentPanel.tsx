"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useAgents, subscribeToAgent } from "@/hooks/useAgents";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useBrokerAccounts } from "@/hooks/useBrokerAccounts";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Play, Pause, Square, Pencil, Trash2, Plus, Check, X, Bot, ChevronDown } from "lucide-react";
import type {
  Agent,
  AgentCreateRequest,
  AgentMode,
  AgentLog,
  AgentTrade,
  AgentPerformance,
  Strategy,
  StrategyList,
} from "@/types";

/* ── tiny helpers ─────────────────────────────────────── */

const statusColor: Record<string, string> = {
  stopped: "bg-zinc-500/20 text-zinc-400",
  running: "bg-green-500/20 text-green-400",
  paused: "bg-yellow-500/20 text-yellow-400",
  error: "bg-red-500/20 text-red-400",
};

const statusDot: Record<string, string> = {
  stopped: "bg-zinc-500",
  running: "bg-green-400 animate-pulse",
  paused: "bg-yellow-400",
  error: "bg-red-400",
};

const pnlColor = (v: number) =>
  v > 0 ? "text-green-400" : v < 0 ? "text-red-400" : "text-muted-foreground";

const TIMEFRAMES = ["M1", "M5", "M10", "M15", "M30", "H1", "H4", "D1"];

/* ═══════════════════════════════════════════════════════ */

export default function AgentPanel() {
  const {
    agents,
    loading,
    loadAgents,
    createAgent,
    deleteAgent,
    startAgent,
    stopAgent,
    pauseAgent,
    expandedAgentIds,
    toggleAgentExpand,
    agentDetails,
    pendingTrades,
    loadPendingTrades,
    confirmTrade,
    rejectTrade,
  } = useAgents();

  const wsStatus = useWebSocket((s) => s.status);

  // ── Local state ──
  const [showCreate, setShowCreate] = useState(false);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [actionError, setActionError] = useState("");
  const [actionLoading, setActionLoading] = useState<number | null>(null);

  // Connected broker accounts for broker selector
  const { accounts: brokerAccounts, activeBroker } = useBrokerAccounts();

  // Create form state
  const [cName, setCName] = useState("");
  const [cStrategyId, setCStrategyId] = useState<number | null>(null);
  const [cSymbol, setCSymbol] = useState("XAUUSD");
  const [cTimeframe, setCTimeframe] = useState("H1");
  const [cMode, setCMode] = useState<AgentMode>("paper");
  const [cMlModelId, setCMlModelId] = useState<number | null>(null);
  const [cBroker, setCBroker] = useState<string>("");
  const [mlModels, setMlModels] = useState<{ id: number; name: string; val_accuracy: number | null; strategy_id: number | null }[]>([]);
  const [rlModels, setRlModels] = useState<{ id: number; name: string; symbol: string; train_metrics?: Record<string, number> }[]>([]);
  const [cRlEnhanced, setCRlEnhanced] = useState(false);
  const [cRlModelId, setCRlModelId] = useState<number | null>(null);
  const [cRlMode, setCRlMode] = useState<"filter" | "autonomous">("filter");
  const [propFirmAccounts, setPropFirmAccounts] = useState<{ id: number; account_name: string; firm_name: string; status: string }[]>([]);
  const [cPropFirmId, setCPropFirmId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);

  // Symbol combobox state for create form
  const FALLBACK_SYMBOLS = ["XAUUSD", "XAGUSD", "US30", "NAS100", "EURUSD", "BTCUSD"];
  const [brokerSymbols, setBrokerSymbols] = useState<string[]>([]);
  const [brokerSymbolsLoading, setBrokerSymbolsLoading] = useState(false);
  const [cSymbolInput, setCSymbolInput] = useState("XAUUSD");
  const [cSymbolOpen, setCSymbolOpen] = useState(false);
  const [cCustomSymbols, setCCustomSymbols] = useState<string[]>([]);

  // Fetch available symbols when broker selection changes
  useEffect(() => {
    if (!cBroker) return;
    setBrokerSymbolsLoading(true);
    api
      .get<{ symbol: string; display_name: string; asset_class: string; tradeable: boolean }[]>(
        `/api/broker/symbols?broker=${encodeURIComponent(cBroker)}`
      )
      .then((symbols) => {
        const names = (Array.isArray(symbols) ? symbols : [])
          .filter((s) => s.tradeable !== false)
          .map((s) => s.symbol);
        setBrokerSymbols(names);
      })
      .catch(() => setBrokerSymbols([]))
      .finally(() => setBrokerSymbolsLoading(false));
  }, [cBroker]);

  const availableSymbols = brokerSymbols.length > 0 ? brokerSymbols : FALLBACK_SYMBOLS;

  const applyAgentSymbol = (sym: string) => {
    const upper = sym.trim().toUpperCase();
    if (!upper) return;
    if (!availableSymbols.includes(upper) && !cCustomSymbols.includes(upper)) {
      setCCustomSymbols(prev => [...prev, upper]);
    }
    setCSymbol(upper);
    setCSymbolInput(upper);
    setCSymbolOpen(false);
  };
  const filteredAgentSymbols = [...availableSymbols, ...cCustomSymbols].filter(s =>
    cSymbolInput === "" || s.toUpperCase().includes(cSymbolInput.toUpperCase())
  );

  // Risk config form state
  const [cSizeType, setCSizeType] = useState("fixed_lot");
  const [cSizeValue, setCSizeValue] = useState("0.01");
  const [cMaxExposure, setCMaxExposure] = useState("1.0");
  const [cMaxOpenPositions, setCMaxOpenPositions] = useState("3");
  const [cMaxDailyLoss, setCMaxDailyLoss] = useState("5");
  const [cMaxDrawdown, setCMaxDrawdown] = useState("10");

  // Edit agent modal state
  const [editAgent, setEditAgent] = useState<Agent | null>(null);
  const [editName, setEditName] = useState("");
  const [editMode, setEditMode] = useState("paper");
  const [editMlModelId, setEditMlModelId] = useState<number | null>(null);
  const [editSizeType, setEditSizeType] = useState("fixed_lot");
  const [editSizeValue, setEditSizeValue] = useState(0.01);
  const [editMaxPositions, setEditMaxPositions] = useState(3);
  const [editMaxDailyLoss, setEditMaxDailyLoss] = useState(5);
  const [editMaxDrawdown, setEditMaxDrawdown] = useState(10);
  const [editRlEnhanced, setEditRlEnhanced] = useState(false);
  const [editRlModelId, setEditRlModelId] = useState<number | null>(null);
  const [editRlMode, setEditRlMode] = useState<"filter" | "autonomous">("filter");
  const [editMsg, setEditMsg] = useState("");

  // ── Load agents & strategies on mount ──
  const didLoad = useRef(false);
  useEffect(() => {
    if (didLoad.current) return;
    didLoad.current = true;
    loadAgents();
    api
      .get<StrategyList>("/api/strategies")
      .then((res) => setStrategies(res.items))
      .catch(() => {});
    api
      .get<{ id: number; name: string; val_accuracy: number | null; strategy_id: number | null }[]>("/api/ml/models?status=ready")
      .then((models) => setMlModels(Array.isArray(models) ? models : []))
      .catch(() => {});
    api
      .get<{ id: number; name: string; symbol: string; train_metrics?: Record<string, number> }[]>("/api/ml/models?status=ready&model_type=rl_ppo")
      .then((models) => setRlModels(Array.isArray(models) ? models : []))
      .catch(() => {});
    api
      .get<{ id: number; account_name: string; firm_name: string; status: string }[]>("/api/prop-firms/")
      .then((accts) => setPropFirmAccounts(Array.isArray(accts) ? accts : []))
      .catch(() => {});
  }, []);

  // ── Default cBroker to activeBroker when it first becomes available ──
  useEffect(() => {
    if (activeBroker && !cBroker) setCBroker(activeBroker);
  }, [activeBroker, cBroker]);

  // ── Subscribe to agent WebSocket channels ──
  useEffect(() => {
    if (wsStatus !== "connected" || agents.length === 0) return;

    const unsubs: (() => void)[] = [];
    for (const agent of agents) {
      if (agent.status === "running" || agent.status === "paused") {
        unsubs.push(subscribeToAgent(agent.id));
      }
    }
    return () => unsubs.forEach((u) => u());
  }, [wsStatus, agents]);

  // ── Load pending trades periodically ──
  useEffect(() => {
    if (agents.some((a) => a.status === "running" && a.mode === "confirmation")) {
      loadPendingTrades();
      const iv = setInterval(loadPendingTrades, 10000);
      return () => clearInterval(iv);
    }
  }, [agents, loadPendingTrades]);

  // ── Actions ──
  const handleAction = useCallback(
    async (action: "start" | "stop" | "pause" | "delete", agent: Agent) => {
      setActionError("");
      setActionLoading(agent.id);
      try {
        if (action === "start") await startAgent(agent.id);
        else if (action === "stop") await stopAgent(agent.id);
        else if (action === "pause") await pauseAgent(agent.id);
        else if (action === "delete") {
          if (!confirm(`Delete agent "${agent.name}"?`)) return;
          await deleteAgent(agent.id);
        }
      } catch (e) {
        setActionError((e as Error).message);
      } finally {
        setActionLoading(null);
      }
    },
    [startAgent, stopAgent, pauseAgent, deleteAgent]
  );

  const handleCreate = async () => {
    if (!cName || !cStrategyId) return;
    setCreating(true);
    setActionError("");
    try {
      const data: AgentCreateRequest = {
        name: cName,
        strategy_id: cStrategyId,
        symbol: cSymbol,
        timeframe: cTimeframe,
        mode: cMode,
        ml_model_id: cMlModelId,
        prop_firm_account_id: cPropFirmId,
        broker_name: cBroker || activeBroker || "",
        risk_config: {
          position_size_type: cSizeType,
          position_size_value: parseFloat(cSizeValue) || 0.01,
          max_exposure_per_symbol: parseFloat(cMaxExposure) || 1.0,
          max_open_positions: parseInt(cMaxOpenPositions) || 3,
          max_daily_loss_pct: parseFloat(cMaxDailyLoss) || 0,
          max_drawdown_pct: parseFloat(cMaxDrawdown) || 0,
          ...(cRlEnhanced && cRlModelId ? {
            rl_enhanced: true,
            rl_model_id: cRlModelId,
            rl_mode: cRlMode,
          } : {}),
        },
      };
      await createAgent(data);
      setShowCreate(false);
      setCName("");
      setCStrategyId(null);
      setCMlModelId(null);
      setCPropFirmId(null);
      setCRlEnhanced(false);
      setCRlModelId(null);
      setCRlMode("filter");
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setCreating(false);
    }
  };

  const handleConfirm = async (trade: AgentTrade) => {
    try {
      await confirmTrade(trade.agent_id, trade.id);
    } catch (e) {
      setActionError((e as Error).message);
    }
  };

  const handleReject = async (trade: AgentTrade) => {
    try {
      await rejectTrade(trade.agent_id, trade.id);
    } catch (e) {
      setActionError((e as Error).message);
    }
  };

  const strategyName = (id: number) =>
    strategies.find((s) => s.id === id)?.name || `Strategy #${id}`;

  /* ═══════════════ RENDER ═══════════════════════════ */
  return (
    <div>
      {/* ── Header ── */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold">Algo Agents ({agents.length})</h3>
          {pendingTrades.length > 0 && (
            <Badge variant="secondary" className="bg-yellow-500/20 text-yellow-400 animate-pulse">
              {pendingTrades.length} pending
            </Badge>
          )}
        </div>
        <Button size="sm" onClick={() => setShowCreate(true)}>
          <Plus className="w-3.5 h-3.5 mr-1" />New Agent
        </Button>
      </div>

      {actionError && (
        <div className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 p-2 text-xs text-red-400">
          {actionError}
        </div>
      )}

      {/* ── Pending Trade Confirmations Banner ── */}
      {pendingTrades.length > 0 && (
        <div className="mb-3 rounded-lg border border-yellow-500/20 bg-yellow-500/5 px-4 py-3">
          <div className="text-xs font-semibold text-yellow-400 mb-2">
            Trades Awaiting Confirmation
          </div>
          <div className="space-y-2">
            {pendingTrades.map((t) => (
              <div
                key={t.id}
                className="flex items-center justify-between rounded-lg border border-yellow-500/20 bg-card-bg p-3"
              >
                <div className="flex items-center gap-3">
                  <Badge
                    variant="secondary"
                    className={`text-xs font-bold ${
                      t.direction === "BUY"
                        ? "bg-green-500/20 text-green-400"
                        : "bg-red-500/20 text-red-400"
                    }`}
                  >
                    {t.direction}
                  </Badge>
                  <div>
                    <div className="text-sm font-medium">{t.symbol}</div>
                    <div className="text-xs text-muted-foreground">
                      {t.lot_size} lots{" "}
                      {t.signal_reason && `- ${t.signal_reason}`}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {t.signal_confidence > 0 && (
                    <span className="text-xs text-muted-foreground">
                      {(t.signal_confidence * 100).toFixed(0)}% conf
                    </span>
                  )}
                  <Button size="sm"
                    onClick={() => handleConfirm(t)}
                    className="bg-green-600 hover:bg-green-700 h-auto py-1 px-3"
                  >
                    <Check className="w-3 h-3 mr-1" />Approve
                  </Button>
                  <Button variant="outline" size="sm"
                    onClick={() => handleReject(t)}
                    className="border-red-500/40 text-red-400 hover:bg-red-500/10 h-auto py-1 px-3"
                  >
                    <X className="w-3 h-3 mr-1" />Reject
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Agents List with Inline Expand ── */}
      {loading ? (
        <div className="flex h-24 items-center justify-center text-sm text-muted-foreground">
          Loading agents...
        </div>
      ) : agents.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-10 text-center">
          <Bot className="h-8 w-8 text-muted-foreground/30 mb-3" />
          <p className="text-sm font-medium mb-1">No Agents Yet</p>
          <p className="text-xs text-muted-foreground mb-4 max-w-xs">
            Create your first trading agent to start automated algo trading with your strategies.
          </p>
          <Button size="sm" onClick={() => setShowCreate(true)} className="gap-1.5">
            <Plus className="h-3.5 w-3.5" /> Create Agent
          </Button>
        </div>
      ) : (
        <div className="space-y-2">
          {agents.map((agent) => {
            const isExpanded = expandedAgentIds.includes(agent.id);
            const detail = agentDetails[agent.id];

            return (
              <Collapsible
                key={agent.id}
                open={isExpanded}
                onOpenChange={() => toggleAgentExpand(agent.id)}
              >
                {/* Agent Row (trigger) */}
                <div className="rounded-lg border border-card-border bg-background/50 hover:border-accent/30 transition-colors overflow-hidden">
                  <CollapsibleTrigger asChild>
                    <div className="flex items-center justify-between p-3 cursor-pointer">
                      <div className="flex items-center gap-3 min-w-0">
                        <span
                          className={`inline-block h-2.5 w-2.5 rounded-full shrink-0 ${statusDot[agent.status] || "bg-zinc-500"}`}
                        />
                        <div className="min-w-0">
                          <div className="text-sm font-medium truncate">
                            {agent.name}
                          </div>
                          <div className="text-xs text-muted-foreground truncate">
                            {strategyName(agent.strategy_id)} - {agent.symbol} - {agent.timeframe}
                            {agent.broker_name && (
                              <span className="ml-1 capitalize text-accent/70">- {agent.broker_name}</span>
                            )}
                            {agent.risk_config?.rl_enhanced && (
                              <Badge className="ml-1.5 bg-purple-500/20 text-purple-400 text-[9px] py-0">RL</Badge>
                            )}
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-2 shrink-0 ml-3">
                        {/* Mode badge */}
                        <Badge
                          variant="secondary"
                          className={`text-[10px] font-medium uppercase hidden sm:inline-flex ${
                            agent.mode === "paper"
                              ? "bg-blue-500/15 text-fa-accent"
                              : agent.mode === "auto"
                                ? "bg-orange-500/15 text-orange-400"
                                : "bg-purple-500/15 text-purple-400"
                          }`}
                        >
                          {agent.mode === "auto" ? "autonomous" : agent.mode}
                        </Badge>

                        {/* Status badge */}
                        <Badge
                          variant="secondary"
                          className={`text-[10px] font-medium uppercase ${
                            statusColor[agent.status] || "bg-zinc-500/20 text-zinc-400"
                          }`}
                        >
                          {agent.status}
                        </Badge>

                        {/* P&L */}
                        {agent.performance_stats?.total_pnl != null && (
                          <span
                            className={`text-xs font-mono font-medium ${pnlColor(agent.performance_stats.total_pnl)}`}
                          >
                            {agent.performance_stats.total_pnl >= 0 ? "+" : ""}
                            ${agent.performance_stats.total_pnl.toFixed(2)}
                          </span>
                        )}

                        {/* Action buttons */}
                        <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                          {agent.status === "stopped" && (
                            <Button variant="outline" size="sm"
                              onClick={() => handleAction("start", agent)}
                              disabled={actionLoading === agent.id}
                              className="border-green-500/40 text-green-400 hover:bg-green-500/10 h-auto py-0.5 px-2"
                              title="Start agent"
                            >
                              <Play className="w-3 h-3" />
                            </Button>
                          )}
                          {agent.status === "running" && (
                            <>
                              <Button variant="outline" size="sm"
                                onClick={() => handleAction("pause", agent)}
                                disabled={actionLoading === agent.id}
                                className="border-yellow-500/40 text-yellow-400 hover:bg-yellow-500/10 h-auto py-0.5 px-2"
                                title="Pause agent"
                              >
                                <Pause className="w-3 h-3" />
                              </Button>
                              <Button variant="outline" size="sm"
                                onClick={() => handleAction("stop", agent)}
                                disabled={actionLoading === agent.id}
                                className="border-red-500/40 text-red-400 hover:bg-red-500/10 h-auto py-0.5 px-2"
                                title="Stop agent"
                              >
                                <Square className="w-3 h-3" />
                              </Button>
                            </>
                          )}
                          {agent.status === "paused" && (
                            <>
                              <Button variant="outline" size="sm"
                                onClick={() => handleAction("start", agent)}
                                disabled={actionLoading === agent.id}
                                className="border-green-500/40 text-green-400 hover:bg-green-500/10 h-auto py-0.5 px-2"
                                title="Resume agent"
                              >
                                <Play className="w-3 h-3" />
                              </Button>
                              <Button variant="outline" size="sm"
                                onClick={() => handleAction("stop", agent)}
                                disabled={actionLoading === agent.id}
                                className="border-red-500/40 text-red-400 hover:bg-red-500/10 h-auto py-0.5 px-2"
                                title="Stop agent"
                              >
                                <Square className="w-3 h-3" />
                              </Button>
                            </>
                          )}
                          <Button variant="ghost" size="sm"
                            onClick={() => {
                              setEditAgent(agent);
                              setEditName(agent.name);
                              setEditMode(agent.mode);
                              setEditMlModelId(agent.ml_model_id ?? null);
                              setEditSizeType(agent.risk_config?.position_size_type ?? "fixed_lot");
                              setEditSizeValue(agent.risk_config?.position_size_value ?? agent.risk_config?.lot_size ?? 0.01);
                              setEditMaxPositions(agent.risk_config?.max_open_positions ?? 3);
                              setEditMaxDailyLoss(agent.risk_config?.max_daily_loss_pct ?? 5);
                              setEditMaxDrawdown(agent.risk_config?.max_drawdown_pct ?? 10);
                              setEditRlEnhanced(agent.risk_config?.rl_enhanced ?? false);
                              setEditRlModelId(agent.risk_config?.rl_model_id ?? null);
                              setEditRlMode(agent.risk_config?.rl_mode ?? "filter");
                              setEditMsg("");
                            }}
                            title="Edit agent"
                            className="h-auto p-1 text-muted-foreground hover:text-accent"
                          ><Pencil className="w-3.5 h-3.5" /></Button>
                          <Button variant="outline" size="sm"
                            onClick={() => handleAction("delete", agent)}
                            disabled={actionLoading === agent.id}
                            className="border-card-border text-muted-foreground hover:text-red-400 hover:border-red-500/40 h-auto py-0.5 px-2"
                            title="Delete agent"
                          >
                            <Trash2 className="w-3 h-3" />
                          </Button>
                        </div>

                        {/* Expand chevron */}
                        <ChevronDown className={`w-4 h-4 text-muted-foreground transition-transform ${isExpanded ? "rotate-180" : ""}`} />
                      </div>
                    </div>
                  </CollapsibleTrigger>

                  {/* Expanded Detail (inline) */}
                  <CollapsibleContent>
                    <AgentInlineDetail
                      agent={agent}
                      detail={detail}
                      strategyName={strategyName(agent.strategy_id)}
                      onConfirm={handleConfirm}
                      onReject={handleReject}
                    />
                  </CollapsibleContent>
                </div>
              </Collapsible>
            );
          })}
        </div>
      )}

      {/* ── Create Agent Modal ── */}
      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent className="max-w-md max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Create Trading Agent</DialogTitle>
            <DialogDescription>Configure a new automated trading agent.</DialogDescription>
          </DialogHeader>

            <div>
              <Label className="text-xs text-muted-foreground mb-1">Agent Name</Label>
              <input
                value={cName}
                onChange={(e) => setCName(e.target.value)}
                placeholder="e.g. XAUUSD MSS H1"
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
              />
            </div>

            {/* Broker account selector */}
            {brokerAccounts.length > 0 && (
              <div>
                <Label className="text-xs text-muted-foreground mb-1">Broker Account</Label>
                <div className="flex gap-2 flex-wrap">
                  {brokerAccounts.map((acct) => (
                    <button
                      key={acct.broker}
                      onClick={() => setCBroker(acct.broker)}
                      className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                        cBroker === acct.broker
                          ? "border-accent/60 bg-accent/10 text-accent"
                          : "border-card-border text-muted-foreground hover:border-accent/40 hover:text-foreground"
                      }`}
                    >
                      <div className="h-1.5 w-1.5 rounded-full bg-green-400" />
                      <span className="capitalize">{acct.broker}</span>
                      <span className="text-muted-foreground/70">
                        {acct.currency} {acct.balance >= 1000
                          ? `${(acct.balance / 1000).toFixed(1)}k`
                          : acct.balance.toFixed(0)}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div>
              <Label className="text-xs text-muted-foreground mb-1">Strategy</Label>
              <select
                value={cStrategyId ?? ""}
                onChange={(e) => setCStrategyId(Number(e.target.value) || null)}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
              >
                <option value="">Select a strategy...</option>
                {strategies.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} {s.is_system ? "(System)" : ""}
                  </option>
                ))}
              </select>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-xs text-muted-foreground mb-1">
                  Symbol {brokerSymbolsLoading && <span className="text-muted-foreground/50 ml-1">(loading...)</span>}
                  {brokerSymbols.length > 0 && <span className="text-green-400/70 ml-1">({brokerSymbols.length} from broker)</span>}
                </Label>
                <div className="relative">
                  <input
                    value={cSymbolInput}
                    onChange={e => { setCSymbolInput(e.target.value.toUpperCase()); setCSymbolOpen(true); }}
                    onFocus={() => setCSymbolOpen(true)}
                    onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); applyAgentSymbol(cSymbolInput); } if (e.key === "Escape") setCSymbolOpen(false); }}
                    onBlur={() => setTimeout(() => setCSymbolOpen(false), 150)}
                    className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm outline-none focus:border-accent"
                    placeholder={brokerSymbols.length > 0 ? "Search broker symbols..." : "Symbol (e.g. XAUUSD)"}
                  />
                  {cSymbolOpen && (
                    <div className="absolute z-50 top-full left-0 right-0 mt-1 rounded-lg border border-card-border bg-card-bg shadow-lg max-h-40 overflow-y-auto">
                      {filteredAgentSymbols.map(s => (
                        <button key={s} onMouseDown={() => applyAgentSymbol(s)}
                          className={`w-full text-left px-3 py-1.5 text-sm hover:bg-card-border transition-colors ${s === cSymbol ? "text-accent" : "text-foreground"}`}>
                          {s}
                        </button>
                      ))}
                      {cSymbolInput && !filteredAgentSymbols.includes(cSymbolInput.toUpperCase()) && (
                        <button onMouseDown={() => applyAgentSymbol(cSymbolInput)}
                          className="w-full text-left px-3 py-1.5 text-sm text-accent hover:bg-card-border transition-colors">
                          + Use &quot;{cSymbolInput}&quot;
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </div>
              <div>
                <Label className="text-xs text-muted-foreground mb-1">Timeframe</Label>
                <select
                  value={cTimeframe}
                  onChange={(e) => setCTimeframe(e.target.value)}
                  className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
                >
                  {TIMEFRAMES.map((tf) => (
                    <option key={tf} value={tf}>{tf}</option>
                  ))}
                </select>
              </div>
            </div>

            <div>
              <Label className="text-xs text-muted-foreground mb-1">Mode</Label>
              <div className="flex gap-2">
                {(["paper", "confirmation", "auto"] as const).map((m) => (
                  <button
                    key={m}
                    onClick={() => setCMode(m)}
                    className={`flex-1 rounded-lg py-2 text-sm font-medium transition-colors ${
                      cMode === m
                        ? m === "paper" ? "bg-blue-500/20 text-fa-accent border border-blue-500/40"
                          : m === "confirmation" ? "bg-purple-500/20 text-purple-400 border border-purple-500/40"
                            : "bg-orange-500/20 text-orange-400 border border-orange-500/40"
                        : "border border-card-border text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {m === "paper" ? "Paper" : m === "confirmation" ? "Confirm" : "Autonomous"}
                  </button>
                ))}
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                {cMode === "paper"
                  ? "Simulates trades without connecting to broker. Tracks virtual P&L."
                  : cMode === "confirmation"
                    ? "Shows trade signals and requires your approval before execution."
                    : "Fully autonomous — executes trades directly on broker without confirmation."}
              </p>
              {cMode === "auto" && (
                <div className="mt-2 rounded-lg bg-orange-500/10 border border-orange-500/30 px-3 py-2 text-xs text-orange-400">
                  Autonomous mode will place real trades on your connected broker. Ensure risk settings are configured.
                </div>
              )}
            </div>

            {/* ML Model (optional) */}
            <div>
              <Label className="text-xs text-muted-foreground mb-1">
                ML Model <span className="text-zinc-500">(optional)</span>
              </Label>
              <select
                value={cMlModelId ?? ""}
                onChange={(e) => setCMlModelId(e.target.value ? Number(e.target.value) : null)}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
              >
                <option value="">No ML filter</option>
                {mlModels
                  .filter((m) => !cStrategyId || m.strategy_id === cStrategyId || !m.strategy_id)
                  .map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                      {m.val_accuracy != null ? ` (${(m.val_accuracy * 100).toFixed(1)}% acc)` : ""}
                    </option>
                  ))}
              </select>
            </div>

            {/* RL-Enhanced Toggle */}
            <div className="border-t border-card-border pt-3">
              <div className="flex items-center gap-3 mb-2">
                <button
                  type="button"
                  role="switch"
                  aria-checked={cRlEnhanced}
                  onClick={() => setCRlEnhanced(!cRlEnhanced)}
                  className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${cRlEnhanced ? "bg-purple-600" : "bg-zinc-600"}`}
                >
                  <span className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow-sm transition-transform ${cRlEnhanced ? "translate-x-4" : "translate-x-0"}`} />
                </button>
                <Label className="text-xs font-semibold text-foreground">
                  RL-Enhanced
                  {cRlEnhanced && <Badge className="ml-2 bg-purple-500/20 text-purple-400 text-[10px]">AI</Badge>}
                </Label>
              </div>
              {cRlEnhanced && (
                <div className="space-y-2 pl-1">
                  <div>
                    <Label className="block text-[10px] text-muted-foreground mb-1">RL Model</Label>
                    <select
                      value={cRlModelId ?? ""}
                      onChange={(e) => setCRlModelId(e.target.value ? Number(e.target.value) : null)}
                      className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
                    >
                      <option value="">Select RL model...</option>
                      {rlModels.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name} {m.symbol ? `(${m.symbol})` : ""}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <Label className="block text-[10px] text-muted-foreground mb-1">RL Mode</Label>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => setCRlMode("filter")}
                        className={`flex-1 rounded-lg border px-3 py-1.5 text-xs transition-colors ${cRlMode === "filter" ? "border-purple-500 bg-purple-500/10 text-purple-400" : "border-card-border text-muted-foreground hover:border-zinc-500"}`}
                      >
                        Filter
                      </button>
                      <button
                        type="button"
                        onClick={() => setCRlMode("autonomous")}
                        className={`flex-1 rounded-lg border px-3 py-1.5 text-xs transition-colors ${cRlMode === "autonomous" ? "border-purple-500 bg-purple-500/10 text-purple-400" : "border-card-border text-muted-foreground hover:border-zinc-500"}`}
                      >
                        Autonomous
                      </button>
                    </div>
                    <p className="text-[10px] text-zinc-500 mt-1">
                      {cRlMode === "filter" ? "RL gates strategy signals (safer)" : "RL trades independently (advanced)"}
                    </p>
                  </div>
                  {cRlModelId && rlModels.find(m => m.id === cRlModelId)?.train_metrics && (
                    <div className="flex gap-2 text-[10px]">
                      {(() => {
                        const metrics = rlModels.find(m => m.id === cRlModelId)?.train_metrics;
                        if (!metrics) return null;
                        return (
                          <>
                            {metrics.eval_avg_wr != null && <Badge className="bg-green-500/10 text-green-400">WR {metrics.eval_avg_wr}%</Badge>}
                            {metrics.eval_avg_pnl != null && <Badge className={`${metrics.eval_avg_pnl >= 0 ? "bg-green-500/10 text-green-400" : "bg-red-500/10 text-red-400"}`}>PnL ${metrics.eval_avg_pnl}</Badge>}
                            {metrics.eval_avg_dd != null && <Badge className="bg-yellow-500/10 text-yellow-400">DD {metrics.eval_avg_dd}%</Badge>}
                          </>
                        );
                      })()}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Prop Firm Account (optional) */}
            {propFirmAccounts.length > 0 && (
              <div>
                <Label className="text-xs text-muted-foreground mb-1">
                  Prop Firm Account <span className="text-zinc-500">(optional)</span>
                </Label>
                <select
                  value={cPropFirmId ?? ""}
                  onChange={(e) => setCPropFirmId(e.target.value ? Number(e.target.value) : null)}
                  className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
                >
                  <option value="">No prop firm</option>
                  {propFirmAccounts
                    .filter((a) => a.status === "active")
                    .map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.firm_name} — {a.account_name}
                      </option>
                    ))}
                </select>
              </div>
            )}

            {/* ── Risk Configuration ── */}
            <div className="border-t border-card-border pt-3">
              <Label className="block text-xs font-semibold text-foreground mb-2">Risk Configuration</Label>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="block text-[10px] text-muted-foreground mb-1">Position Sizing</Label>
                  <select
                    value={cSizeType}
                    onChange={(e) => setCSizeType(e.target.value)}
                    className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
                  >
                    <option value="fixed_lot">Fixed Lot</option>
                    <option value="percent_risk">% of Balance</option>
                  </select>
                </div>
                <div>
                  <Label className="block text-[10px] text-muted-foreground mb-1">
                    {cSizeType === "fixed_lot" ? "Lot Size" : "Risk %"}
                  </Label>
                  <input
                    type="number"
                    step={cSizeType === "fixed_lot" ? "0.01" : "0.5"}
                    min="0"
                    value={cSizeValue}
                    onChange={(e) => setCSizeValue(e.target.value)}
                    className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
                    placeholder={cSizeType === "fixed_lot" ? "0.01" : "2"}
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3 mt-2">
                <div>
                  <Label className="block text-[10px] text-muted-foreground mb-1">Max Exposure</Label>
                  <input type="number" step="0.1" min="0" value={cMaxExposure} onChange={(e) => setCMaxExposure(e.target.value)}
                    className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" placeholder="1.0 lots" />
                </div>
                <div>
                  <Label className="block text-[10px] text-muted-foreground mb-1">Max Positions</Label>
                  <input type="number" step="1" min="1" value={cMaxOpenPositions} onChange={(e) => setCMaxOpenPositions(e.target.value)}
                    className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" placeholder="3" />
                </div>
                <div>
                  <Label className="block text-[10px] text-muted-foreground mb-1">Max Daily Loss %</Label>
                  <input type="number" step="0.5" min="0" value={cMaxDailyLoss} onChange={(e) => setCMaxDailyLoss(e.target.value)}
                    className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" placeholder="5%" />
                </div>
              </div>

              <div className="mt-2">
                <Label className="block text-[10px] text-muted-foreground mb-1">Max Drawdown % <span className="text-zinc-500">(0 = disabled)</span></Label>
                <input type="number" step="1" min="0" value={cMaxDrawdown} onChange={(e) => setCMaxDrawdown(e.target.value)}
                  className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm" placeholder="10%" />
              </div>
            </div>

            <div className="flex justify-end gap-3 pt-2">
              <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
              <Button onClick={handleCreate} disabled={creating || !cName || !cStrategyId}>
                {creating ? "Creating..." : "Create Agent"}
              </Button>
            </div>
        </DialogContent>
      </Dialog>

      {/* ── Edit Agent Modal ── */}
      <Dialog open={!!editAgent} onOpenChange={(open) => { if (!open) setEditAgent(null); }}>
        <DialogContent className="max-w-md max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Edit Agent</DialogTitle>
            <DialogDescription>Modify agent settings and risk configuration.</DialogDescription>
          </DialogHeader>
          {editAgent && (
            <>
            <div className="grid grid-cols-3 gap-2 text-xs">
              <div className="rounded bg-background p-2"><div className="text-muted-foreground mb-0.5">Symbol</div><div className="text-foreground font-mono">{editAgent.symbol}</div></div>
              <div className="rounded bg-background p-2"><div className="text-muted-foreground mb-0.5">Timeframe</div><div className="text-foreground">{editAgent.timeframe}</div></div>
              <div className="rounded bg-background p-2"><div className="text-muted-foreground mb-0.5">Broker</div><div className="text-foreground capitalize">{editAgent.broker_name}</div></div>
            </div>
            <div>
              <Label className="block text-xs text-muted-foreground mb-1.5">Agent Name</Label>
              <input value={editName} onChange={e => setEditName(e.target.value)}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm outline-none focus:border-accent" />
            </div>
            <div>
              <Label className="block text-xs text-muted-foreground mb-1.5">Mode</Label>
              <select value={editMode} onChange={e => setEditMode(e.target.value)}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm outline-none focus:border-accent">
                <option value="paper">Paper Trading (simulated)</option>
                <option value="confirmation">Confirm Each Trade</option>
                <option value="auto">Fully Autonomous</option>
              </select>
            </div>
            <div>
              <Label className="block text-xs text-muted-foreground mb-1.5">ML Model <span className="text-zinc-500">(optional)</span></Label>
              <select value={editMlModelId ?? ""} onChange={e => setEditMlModelId(e.target.value ? Number(e.target.value) : null)}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm outline-none focus:border-accent">
                <option value="">No ML filter</option>
                {mlModels.map(m => (
                  <option key={m.id} value={m.id}>
                    {m.name}{m.val_accuracy != null ? ` (${(m.val_accuracy * 100).toFixed(1)}% acc)` : ""}
                  </option>
                ))}
              </select>
            </div>
            {/* RL-Enhanced Toggle (Edit) */}
            <div className="border-t border-card-border pt-3">
              <div className="flex items-center gap-3 mb-2">
                <button type="button" role="switch" aria-checked={editRlEnhanced}
                  onClick={() => setEditRlEnhanced(!editRlEnhanced)}
                  className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${editRlEnhanced ? "bg-purple-600" : "bg-zinc-600"}`}>
                  <span className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow-sm transition-transform ${editRlEnhanced ? "translate-x-4" : "translate-x-0"}`} />
                </button>
                <Label className="text-xs font-semibold text-foreground">
                  RL-Enhanced
                  {editRlEnhanced && <Badge className="ml-2 bg-purple-500/20 text-purple-400 text-[10px]">AI</Badge>}
                </Label>
              </div>
              {editRlEnhanced && (
                <div className="space-y-2 pl-1">
                  <div>
                    <Label className="block text-[10px] text-muted-foreground mb-1">RL Model</Label>
                    <select value={editRlModelId ?? ""} onChange={e => setEditRlModelId(e.target.value ? Number(e.target.value) : null)}
                      className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm outline-none focus:border-accent">
                      <option value="">Select RL model...</option>
                      {rlModels.map(m => (
                        <option key={m.id} value={m.id}>{m.name} {m.symbol ? `(${m.symbol})` : ""}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <Label className="block text-[10px] text-muted-foreground mb-1">RL Mode</Label>
                    <div className="flex gap-2">
                      <button type="button" onClick={() => setEditRlMode("filter")}
                        className={`flex-1 rounded-lg border px-3 py-1.5 text-xs transition-colors ${editRlMode === "filter" ? "border-purple-500 bg-purple-500/10 text-purple-400" : "border-card-border text-muted-foreground hover:border-zinc-500"}`}>
                        Filter
                      </button>
                      <button type="button" onClick={() => setEditRlMode("autonomous")}
                        className={`flex-1 rounded-lg border px-3 py-1.5 text-xs transition-colors ${editRlMode === "autonomous" ? "border-purple-500 bg-purple-500/10 text-purple-400" : "border-card-border text-muted-foreground hover:border-zinc-500"}`}>
                        Autonomous
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
            <div>
              <Label className="block text-xs text-muted-foreground mb-1.5">Position Sizing</Label>
              <div className="flex rounded-lg border border-card-border overflow-hidden mb-2">
                <button type="button" onClick={() => { setEditSizeType("fixed_lot"); setEditSizeValue(0.01); }}
                  className={`flex-1 px-3 py-1.5 text-xs font-medium transition-colors ${editSizeType === "fixed_lot" ? "bg-accent text-white" : "bg-background text-muted-foreground hover:text-foreground"}`}>
                  Fixed Lot
                </button>
                <button type="button" onClick={() => { setEditSizeType("percent_risk"); setEditSizeValue(1.0); }}
                  className={`flex-1 px-3 py-1.5 text-xs font-medium transition-colors ${editSizeType === "percent_risk" ? "bg-accent text-white" : "bg-background text-muted-foreground hover:text-foreground"}`}>
                  % Risk
                </button>
              </div>
              <input type="number" step={editSizeType === "fixed_lot" ? "0.01" : "0.1"} min="0.01"
                value={editSizeValue} onChange={e => setEditSizeValue(parseFloat(e.target.value) || 0.01)}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm outline-none focus:border-accent" />
              <p className="text-[10px] text-muted-foreground mt-1">
                {editSizeType === "fixed_lot" ? "Lot size per trade (e.g. 0.01)" : "Risk % per trade based on balance & SL distance"}
              </p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="block text-xs text-muted-foreground mb-1.5">Max Open Positions</Label>
                <input type="number" min="1" max="50" value={editMaxPositions} onChange={e => setEditMaxPositions(parseInt(e.target.value) || 1)}
                  className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm outline-none focus:border-accent" />
              </div>
              <div>
                <Label className="block text-xs text-muted-foreground mb-1.5">Max Daily Loss %</Label>
                <input type="number" step="0.5" min="0" value={editMaxDailyLoss} onChange={e => setEditMaxDailyLoss(parseFloat(e.target.value) || 0)}
                  className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm outline-none focus:border-accent" />
              </div>
              <div>
                <Label className="block text-xs text-muted-foreground mb-1.5">Max Drawdown %</Label>
                <input type="number" step="0.5" min="0" value={editMaxDrawdown} onChange={e => setEditMaxDrawdown(parseFloat(e.target.value) || 0)}
                  className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm outline-none focus:border-accent" />
              </div>
            </div>
            {editMsg && <p className={`text-xs ${editMsg.startsWith('\u2713') ? 'text-accent' : 'text-danger'}`}>{editMsg}</p>}
            <div className="flex gap-2 pt-1">
              <Button onClick={async () => {
                try {
                  await api.put(`/api/agents/${editAgent.id}`, {
                    name: editName, mode: editMode, ml_model_id: editMlModelId,
                    risk_config: {
                      ...editAgent.risk_config,
                      position_size_type: editSizeType,
                      position_size_value: editSizeValue,
                      max_open_positions: editMaxPositions,
                      max_daily_loss_pct: editMaxDailyLoss,
                      max_drawdown_pct: editMaxDrawdown,
                      rl_enhanced: editRlEnhanced,
                      rl_model_id: editRlEnhanced ? editRlModelId : undefined,
                      rl_mode: editRlEnhanced ? editRlMode : undefined,
                    },
                  });
                  setEditMsg("\u2713 Agent updated successfully");
                  setTimeout(() => setEditAgent(null), 1200);
                } catch (err: unknown) { setEditMsg(err instanceof Error ? err.message : "Save failed"); }
              }} className="flex-1">Save Changes</Button>
              <Button variant="outline" onClick={() => setEditAgent(null)} className="flex-1">Cancel</Button>
            </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════
   Agent Inline Detail Sub-Component
   ═══════════════════════════════════════════════════════ */

function AgentInlineDetail({
  agent,
  detail,
  strategyName,
  onConfirm,
  onReject,
}: {
  agent: Agent;
  detail?: { logs: AgentLog[]; trades: AgentTrade[]; performance: AgentPerformance | null; loading: boolean };
  strategyName: string;
  onConfirm: (trade: AgentTrade) => void;
  onReject: (trade: AgentTrade) => void;
}) {
  if (!detail || detail.loading) {
    return (
      <div className="flex h-24 items-center justify-center border-t border-card-border text-sm text-muted-foreground">
        Loading agent details...
      </div>
    );
  }

  const { logs, trades, performance } = detail;

  return (
    <div className="border-t border-card-border p-4 space-y-3">
      {/* Mini performance cards */}
      {performance && (
        <div className="grid grid-cols-5 gap-2">
          <div className="rounded-lg bg-background/80 p-2">
            <div className="text-[10px] text-muted-foreground uppercase">P&L</div>
            <div className={`text-sm font-semibold ${pnlColor(performance.total_pnl)}`}>
              {performance.total_pnl >= 0 ? "+" : ""}${performance.total_pnl.toFixed(2)}
            </div>
          </div>
          <div className="rounded-lg bg-background/80 p-2">
            <div className="text-[10px] text-muted-foreground uppercase">Win Rate</div>
            <div className="text-sm font-semibold">{performance.win_rate.toFixed(1)}%</div>
          </div>
          <div className="rounded-lg bg-background/80 p-2">
            <div className="text-[10px] text-muted-foreground uppercase">Trades</div>
            <div className="text-sm font-semibold">{performance.total_trades}</div>
          </div>
          <div className="rounded-lg bg-background/80 p-2">
            <div className="text-[10px] text-muted-foreground uppercase">Wins</div>
            <div className="text-sm font-semibold text-green-400">{performance.wins}</div>
          </div>
          <div className="rounded-lg bg-background/80 p-2">
            <div className="text-[10px] text-muted-foreground uppercase">Losses</div>
            <div className="text-sm font-semibold text-red-400">{performance.losses}</div>
          </div>
        </div>
      )}

      {/* Sub-tabs: Trades | Logs | Equity */}
      <Tabs defaultValue="trades" className="w-full">
        <TabsList variant="line" className="w-full justify-start">
          <TabsTrigger value="trades" className="text-xs">Trades ({trades.length})</TabsTrigger>
          <TabsTrigger value="logs" className="text-xs">Logs ({logs.length})</TabsTrigger>
          <TabsTrigger value="equity" className="text-xs">Equity</TabsTrigger>
        </TabsList>

        {/* ── Trades ── */}
        <TabsContent value="trades">
          {trades.length === 0 ? (
            <div className="flex h-20 items-center justify-center text-xs text-muted-foreground">No trades yet</div>
          ) : (
            <div className="max-h-[250px] overflow-y-auto space-y-1.5">
              {trades.map((t) => (
                <div
                  key={t.id}
                  className={`flex items-center justify-between rounded-lg border p-2.5 ${
                    t.status === "pending_confirmation"
                      ? "border-yellow-500/30 bg-yellow-500/5"
                      : "border-card-border bg-background/30"
                  }`}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <Badge
                      variant="secondary"
                      className={`text-[10px] font-bold shrink-0 ${
                        t.direction === "BUY" ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"
                      }`}
                    >
                      {t.direction}
                    </Badge>
                    <div className="min-w-0">
                      <div className="text-xs font-medium">
                        {t.symbol} - {t.lot_size} lots
                        {t.broker_name && <span className="text-[10px] text-muted-foreground ml-1">({t.broker_name})</span>}
                      </div>
                      <div className="text-[10px] text-muted-foreground">
                        {t.filled_price ? (
                          <>Fill: {t.filled_price.toFixed(2)}</>
                        ) : (
                          <>Entry: {t.entry_price?.toFixed(2) ?? "—"}</>
                        )}
                        {" "}SL: {t.stop_loss?.toFixed(2) ?? "—"} TP: {t.take_profit_1?.toFixed(2) ?? "—"}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <div className="text-right">
                      <div className={`text-xs font-medium ${pnlColor(t.pnl)}`}>
                        {t.pnl !== 0 ? `$${t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(2)}` : "—"}
                      </div>
                      <div className="flex gap-1 justify-end">
                        {t.exit_reason && (
                          <Badge variant="secondary" className={`text-[9px] font-medium uppercase ${
                            t.exit_reason === "SL" ? "bg-red-500/15 text-red-400"
                            : t.exit_reason.startsWith("TP") ? "bg-green-500/15 text-green-400"
                            : "bg-cyan-500/15 text-cyan-400"
                          }`}>{t.exit_reason}</Badge>
                        )}
                        <Badge variant="secondary" className={`text-[9px] font-medium uppercase ${
                          t.status === "pending_confirmation" ? "bg-yellow-500/20 text-yellow-400"
                          : t.status === "executed" || t.status === "paper" ? "bg-green-500/15 text-green-400"
                          : t.status === "rejected" ? "bg-red-500/15 text-red-400"
                          : "bg-zinc-500/15 text-zinc-400"
                        }`}>{t.status}</Badge>
                      </div>
                    </div>
                    {t.status === "pending_confirmation" && (
                      <div className="flex gap-1">
                        <button onClick={() => onConfirm(t)}
                          className="rounded bg-green-600 px-2 py-0.5 text-[10px] font-medium text-foreground hover:bg-green-700">
                          Approve
                        </button>
                        <button onClick={() => onReject(t)}
                          className="rounded border border-red-500/40 px-2 py-0.5 text-[10px] text-red-400 hover:bg-red-500/10">
                          Reject
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </TabsContent>

        {/* ── Logs ── */}
        <TabsContent value="logs">
          {logs.length === 0 ? (
            <div className="flex h-20 items-center justify-center text-xs text-muted-foreground">No logs yet</div>
          ) : (
            <div className="max-h-[250px] overflow-y-auto font-mono text-[11px] space-y-0.5">
              {logs.map((log) => (
                <div
                  key={log.id}
                  className={`flex gap-2 rounded px-2 py-0.5 ${
                    log.level === "error" ? "bg-red-500/5 text-red-400"
                    : log.level === "warn" ? "bg-yellow-500/5 text-yellow-400"
                    : log.level === "trade" ? "bg-green-500/5 text-green-400"
                    : log.level === "rl_filter" ? "bg-purple-500/5 text-purple-400"
                    : "text-muted-foreground"
                  }`}
                >
                  <span className="shrink-0 text-zinc-600">
                    {new Date(log.created_at).toLocaleTimeString()}
                  </span>
                  <span className={`shrink-0 w-10 text-right uppercase font-semibold ${
                    log.level === "error" ? "text-red-400"
                    : log.level === "warn" ? "text-yellow-400"
                    : log.level === "trade" ? "text-green-400"
                    : log.level === "rl_filter" ? "text-purple-400"
                    : "text-zinc-500"
                  }`}>
                    {log.level === "rl_filter" ? "RL" : log.level}
                  </span>
                  <span className="break-all">{log.message}</span>
                </div>
              ))}
            </div>
          )}
        </TabsContent>

        {/* ── Equity Curve ── */}
        <TabsContent value="equity">
          {!performance || performance.equity_curve.length === 0 ? (
            <div className="flex h-20 items-center justify-center text-xs text-muted-foreground">
              No performance data yet
            </div>
          ) : (
            <div className="max-h-[250px] overflow-y-auto font-mono text-[11px]">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-card-border text-muted-foreground">
                    <th className="pb-1 text-left font-medium">Time</th>
                    <th className="pb-1 text-right font-medium">P&L</th>
                    <th className="pb-1 text-right font-medium">Cumulative</th>
                  </tr>
                </thead>
                <tbody>
                  {(() => {
                    let cumulative = 0;
                    return performance.equity_curve.map((pt, i) => {
                      cumulative += pt.pnl;
                      return (
                        <tr key={i} className="border-b border-card-border/30">
                          <td className="py-0.5 text-muted-foreground">
                            {pt.time ? new Date(pt.time).toLocaleDateString() : `#${i + 1}`}
                          </td>
                          <td className={`py-0.5 text-right ${pnlColor(pt.pnl)}`}>
                            {pt.pnl >= 0 ? "+" : ""}{pt.pnl.toFixed(2)}
                          </td>
                          <td className={`py-0.5 text-right font-medium ${pnlColor(cumulative)}`}>
                            {cumulative >= 0 ? "+" : ""}{cumulative.toFixed(2)}
                          </td>
                        </tr>
                      );
                    });
                  })()}
                </tbody>
              </table>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
