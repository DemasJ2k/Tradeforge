"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useAgents, subscribeToAgent } from "@/hooks/useAgents";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useBrokerAccounts } from "@/hooks/useBrokerAccounts";
import { api } from "@/lib/api";
import type {
  Agent,
  AgentCreateRequest,
  AgentMode,
  AgentLog,
  AgentTrade,
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
  v > 0 ? "text-green-400" : v < 0 ? "text-red-400" : "text-muted";

const SYMBOLS = ["XAUUSD", "XAGUSD", "US30", "NAS100"];
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
    selectedAgentId,
    selectAgent,
    logs,
    logsLoading,
    trades: agentTrades,
    tradesLoading,
    performance,
    pendingTrades,
    loadPendingTrades,
    confirmTrade,
    rejectTrade,
  } = useAgents();

  const wsStatus = useWebSocket((s) => s.status);

  // ── Local state ──
  const [showCreate, setShowCreate] = useState(false);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [tab, setTab] = useState<"agents" | "detail">("agents");
  const [actionError, setActionError] = useState("");
  const [actionLoading, setActionLoading] = useState<number | null>(null);

  // Connected broker accounts for broker selector (must be before other hooks)
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
  const [creating, setCreating] = useState(false);

  // Symbol combobox state for create form
  const AGENT_DEFAULT_SYMBOLS = ["XAUUSD", "XAGUSD", "US30", "NAS100", "EURUSD", "BTCUSD"];
  const [cSymbolInput, setCSymbolInput] = useState("XAUUSD");
  const [cSymbolOpen, setCSymbolOpen] = useState(false);
  const [cCustomSymbols, setCCustomSymbols] = useState<string[]>([]);

  const applyAgentSymbol = (sym: string) => {
    const upper = sym.trim().toUpperCase();
    if (!upper) return;
    if (!AGENT_DEFAULT_SYMBOLS.includes(upper) && !cCustomSymbols.includes(upper)) {
      setCCustomSymbols(prev => [...prev, upper]);
    }
    setCSymbol(upper);
    setCSymbolInput(upper);
    setCSymbolOpen(false);
  };
  const filteredAgentSymbols = [...AGENT_DEFAULT_SYMBOLS, ...cCustomSymbols].filter(s =>
    cSymbolInput === "" || s.includes(cSymbolInput.toUpperCase())
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
  const [editLotSize, setEditLotSize] = useState(0.01);
  const [editMaxPositions, setEditMaxPositions] = useState(3);
  const [editMaxDailyLoss, setEditMaxDailyLoss] = useState(5);
  const [editMaxDrawdown, setEditMaxDrawdown] = useState(10);
  const [editMsg, setEditMsg] = useState("");

  // ── Load agents & strategies on mount ──
  const didLoad = useRef(false);
  if (!didLoad.current) {
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
  }

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
        broker_name: cBroker || activeBroker || undefined,
        risk_config: {
          position_size_type: cSizeType,
          position_size_value: parseFloat(cSizeValue) || 0.01,
          max_exposure_per_symbol: parseFloat(cMaxExposure) || 1.0,
          max_open_positions: parseInt(cMaxOpenPositions) || 3,
          max_daily_loss_pct: parseFloat(cMaxDailyLoss) || 0,
          max_drawdown_pct: parseFloat(cMaxDrawdown) || 0,
        },
      };
      await createAgent(data);
      setShowCreate(false);
      setCName("");
      setCStrategyId(null);
      setCMlModelId(null);
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setCreating(false);
    }
  };

  const handleSelectAgent = (id: number) => {
    selectAgent(id);
    setTab("detail");
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

  const selectedAgent = agents.find((a) => a.id === selectedAgentId) || null;
  const strategyName = (id: number) =>
    strategies.find((s) => s.id === id)?.name || `Strategy #${id}`;

  /* ═══════════════ RENDER ═══════════════════════════ */
  return (
    <div className="rounded-xl border border-card-border bg-card-bg overflow-hidden">
      {/* ── Header ── */}
      <div className="flex items-center justify-between border-b border-card-border px-4 py-3">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold">Algo Agents</h3>

          {/* Tabs */}
          <div className="flex gap-1">
            <button
              onClick={() => setTab("agents")}
              className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
                tab === "agents"
                  ? "bg-accent/15 text-accent"
                  : "text-muted hover:text-foreground"
              }`}
            >
              Agents ({agents.length})
            </button>
            {selectedAgent && (
              <button
                onClick={() => setTab("detail")}
                className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
                  tab === "detail"
                    ? "bg-accent/15 text-accent"
                    : "text-muted hover:text-foreground"
                }`}
              >
                {selectedAgent.name}
              </button>
            )}
          </div>

          {/* Pending trade count badge */}
          {pendingTrades.length > 0 && (
            <span className="flex items-center gap-1 rounded-full bg-yellow-500/20 px-2 py-0.5 text-xs font-medium text-yellow-400 animate-pulse">
              {pendingTrades.length} pending
            </span>
          )}
        </div>

        <button
          onClick={() => setShowCreate(true)}
          className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-black hover:bg-accent/90 transition-colors"
        >
          + New Agent
        </button>
      </div>

      {actionError && (
        <div className="mx-4 mt-2 rounded-lg border border-red-500/30 bg-red-500/10 p-2 text-xs text-red-400">
          {actionError}
        </div>
      )}

      {/* ── Pending Trade Confirmations Banner ── */}
      {pendingTrades.length > 0 && tab === "agents" && (
        <div className="border-b border-yellow-500/20 bg-yellow-500/5 px-4 py-3">
          <div className="text-xs font-semibold text-yellow-400 mb-2">
            ⚡ Trades Awaiting Confirmation
          </div>
          <div className="space-y-2">
            {pendingTrades.map((t) => (
              <div
                key={t.id}
                className="flex items-center justify-between rounded-lg border border-yellow-500/20 bg-card-bg p-3"
              >
                <div className="flex items-center gap-3">
                  <span
                    className={`rounded px-2 py-0.5 text-xs font-bold ${
                      t.direction === "BUY"
                        ? "bg-green-500/20 text-green-400"
                        : "bg-red-500/20 text-red-400"
                    }`}
                  >
                    {t.direction}
                  </span>
                  <div>
                    <div className="text-sm font-medium">{t.symbol}</div>
                    <div className="text-xs text-muted">
                      {t.lot_size} lots • SL: {t.stop_loss ?? "—"} • TP: {t.take_profit_1 ?? "—"}
                      {t.signal_reason && ` • ${t.signal_reason}`}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {t.signal_confidence > 0 && (
                    <span className="text-xs text-muted">
                      {(t.signal_confidence * 100).toFixed(0)}% conf
                    </span>
                  )}
                  <button
                    onClick={() => handleConfirm(t)}
                    className="rounded-lg bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-700 transition-colors"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => handleReject(t)}
                    className="rounded-lg border border-red-500/40 px-3 py-1 text-xs text-red-400 hover:bg-red-500/10 transition-colors"
                  >
                    Reject
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Agents List ── */}
      {tab === "agents" && (
        <div className="p-4">
          {loading ? (
            <div className="flex h-24 items-center justify-center text-sm text-muted">
              Loading agents...
            </div>
          ) : agents.length === 0 ? (
            <div className="flex h-24 flex-col items-center justify-center text-sm text-muted gap-2">
              <span>No agents yet. Create one to start algo trading.</span>
            </div>
          ) : (
            <div className="grid gap-3">
              {agents.map((agent) => (
                <div
                  key={agent.id}
                  className="flex items-center justify-between rounded-lg border border-card-border bg-background/50 p-3 hover:border-accent/30 transition-colors cursor-pointer"
                  onClick={() => handleSelectAgent(agent.id)}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <span
                      className={`inline-block h-2.5 w-2.5 rounded-full shrink-0 ${statusDot[agent.status] || "bg-zinc-500"}`}
                    />
                    <div className="min-w-0">
                      <div className="text-sm font-medium truncate">
                        {agent.name}
                      </div>
                      <div className="text-xs text-muted truncate">
                        {strategyName(agent.strategy_id)} • {agent.symbol} • {agent.timeframe}
                        {agent.broker_name && (
                          <span className="ml-1 capitalize text-accent/70">• {agent.broker_name}</span>
                        )}
                        {agent.ml_model_id && (
                          <span className="ml-1 text-cyan-400/70">
                            • ML #{agent.ml_model_id}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0 ml-3">
                    {/* Mode badge */}
                    <span
                      className={`rounded px-2 py-0.5 text-[10px] font-medium uppercase ${
                        agent.mode === "paper"
                          ? "bg-blue-500/15 text-blue-400"
                          : agent.mode === "auto"
                            ? "bg-orange-500/15 text-orange-400"
                            : "bg-purple-500/15 text-purple-400"
                      }`}
                    >
                      {agent.mode === "auto" ? "autonomous" : agent.mode}
                    </span>

                    {/* Status badge */}
                    <span
                      className={`rounded px-2 py-0.5 text-[10px] font-medium uppercase ${
                        statusColor[agent.status] || "bg-zinc-500/20 text-zinc-400"
                      }`}
                    >
                      {agent.status}
                    </span>

                    {/* P&L */}
                    {agent.performance_stats?.total_pnl != null && (
                      <span
                        className={`text-xs font-mono font-medium ${pnlColor(agent.performance_stats.total_pnl)}`}
                      >
                        {agent.performance_stats.total_pnl >= 0 ? "+" : ""}
                        {agent.performance_stats.total_pnl.toFixed(2)}
                      </span>
                    )}

                    {/* Action buttons */}
                    <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                      {agent.status === "stopped" && (
                        <button
                          onClick={() => handleAction("start", agent)}
                          disabled={actionLoading === agent.id}
                          className="rounded border border-green-500/40 px-2 py-0.5 text-xs text-green-400 hover:bg-green-500/10 transition-colors disabled:opacity-50"
                          title="Start agent"
                        >
                          ▶
                        </button>
                      )}
                      {agent.status === "running" && (
                        <>
                          <button
                            onClick={() => handleAction("pause", agent)}
                            disabled={actionLoading === agent.id}
                            className="rounded border border-yellow-500/40 px-2 py-0.5 text-xs text-yellow-400 hover:bg-yellow-500/10 transition-colors disabled:opacity-50"
                            title="Pause agent"
                          >
                            ⏸
                          </button>
                          <button
                            onClick={() => handleAction("stop", agent)}
                            disabled={actionLoading === agent.id}
                            className="rounded border border-red-500/40 px-2 py-0.5 text-xs text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-50"
                            title="Stop agent"
                          >
                            ⏹
                          </button>
                        </>
                      )}
                      {agent.status === "paused" && (
                        <>
                          <button
                            onClick={() => handleAction("start", agent)}
                            disabled={actionLoading === agent.id}
                            className="rounded border border-green-500/40 px-2 py-0.5 text-xs text-green-400 hover:bg-green-500/10 transition-colors disabled:opacity-50"
                            title="Resume agent"
                          >
                            ▶
                          </button>
                          <button
                            onClick={() => handleAction("stop", agent)}
                            disabled={actionLoading === agent.id}
                            className="rounded border border-red-500/40 px-2 py-0.5 text-xs text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-50"
                            title="Stop agent"
                          >
                            ⏹
                          </button>
                        </>
                      )}
                      <button
                        onClick={() => {
                          setEditAgent(agent);
                          setEditName(agent.name);
                          setEditMode(agent.mode);
                          setEditMlModelId(agent.ml_model_id ?? null);
                          setEditLotSize(agent.risk_config?.lot_size ?? 0.01);
                          setEditMaxPositions(agent.risk_config?.max_open_positions ?? 3);
                          setEditMaxDailyLoss(agent.risk_config?.max_daily_loss_pct ?? 5);
                          setEditMaxDrawdown(agent.risk_config?.max_drawdown_pct ?? 10);
                          setEditMsg("");
                        }}
                        title="Edit agent"
                        className="rounded p-1 text-muted hover:text-accent transition-colors text-sm"
                      >✏️</button>
                      <button
                        onClick={() => handleAction("delete", agent)}
                        disabled={actionLoading === agent.id}
                        className="rounded border border-card-border px-2 py-0.5 text-xs text-muted hover:text-red-400 hover:border-red-500/40 transition-colors disabled:opacity-50"
                        title="Delete agent"
                      >
                        ✕
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Agent Detail ── */}
      {tab === "detail" && selectedAgent && (
        <AgentDetail
          agent={selectedAgent}
          strategyName={strategyName(selectedAgent.strategy_id)}
          logs={logs}
          logsLoading={logsLoading}
          trades={agentTrades}
          tradesLoading={tradesLoading}
          performance={performance}
          onBack={() => { selectAgent(null); setTab("agents"); }}
          onConfirm={handleConfirm}
          onReject={handleReject}
        />
      )}

      {/* ── Create Agent Modal ── */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="w-full max-w-md rounded-xl border border-card-border bg-[#1a1a2e] p-6 space-y-4">
            <h3 className="text-lg font-semibold">Create Trading Agent</h3>

            <div>
              <label className="block text-xs text-muted mb-1">Agent Name</label>
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
                <label className="block text-xs text-muted mb-1">Broker Account</label>
                <div className="flex gap-2 flex-wrap">
                  {brokerAccounts.map((acct) => (
                    <button
                      key={acct.broker}
                      onClick={() => setCBroker(acct.broker)}
                      className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                        cBroker === acct.broker
                          ? "border-accent/60 bg-accent/10 text-accent"
                          : "border-card-border text-muted hover:border-accent/40 hover:text-foreground"
                      }`}
                    >
                      <div className="h-1.5 w-1.5 rounded-full bg-green-400" />
                      <span className="capitalize">{acct.broker}</span>
                      <span className="text-muted/70">
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
              <label className="block text-xs text-muted mb-1">Strategy</label>
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
                <label className="block text-xs text-muted mb-1">Symbol</label>
                <div className="relative">
                  <input
                    value={cSymbolInput}
                    onChange={e => { setCSymbolInput(e.target.value.toUpperCase()); setCSymbolOpen(true); }}
                    onFocus={() => setCSymbolOpen(true)}
                    onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); applyAgentSymbol(cSymbolInput); } if (e.key === "Escape") setCSymbolOpen(false); }}
                    onBlur={() => setTimeout(() => setCSymbolOpen(false), 150)}
                    className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm outline-none focus:border-accent"
                    placeholder="Symbol (e.g. XAUUSD)"
                  />
                  {cSymbolOpen && (
                    <div className="absolute z-50 top-full left-0 right-0 mt-1 rounded-lg border border-card-border bg-card-bg shadow-lg max-h-40 overflow-y-auto">
                      {filteredAgentSymbols.map(s => (
                        <button key={s} onMouseDown={() => applyAgentSymbol(s)}
                          className={`w-full text-left px-3 py-1.5 text-sm hover:bg-card-border transition-colors ${s === cSymbol ? "text-accent" : "text-foreground"}`}>
                          {s}
                        </button>
                      ))}
                      {cSymbolInput && !filteredAgentSymbols.includes(cSymbolInput) && (
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
                <label className="block text-xs text-muted mb-1">Timeframe</label>
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
              <label className="block text-xs text-muted mb-1">Mode</label>
              <div className="flex gap-2">
                <button
                  onClick={() => setCMode("paper")}
                  className={`flex-1 rounded-lg py-2 text-sm font-medium transition-colors ${
                    cMode === "paper"
                      ? "bg-blue-500/20 text-blue-400 border border-blue-500/40"
                      : "border border-card-border text-muted hover:text-foreground"
                  }`}
                >
                  📝 Paper
                </button>
                <button
                  onClick={() => setCMode("confirmation")}
                  className={`flex-1 rounded-lg py-2 text-sm font-medium transition-colors ${
                    cMode === "confirmation"
                      ? "bg-purple-500/20 text-purple-400 border border-purple-500/40"
                      : "border border-card-border text-muted hover:text-foreground"
                  }`}
                >
                  ✅ Confirm
                </button>
                <button
                  onClick={() => setCMode("auto")}
                  className={`flex-1 rounded-lg py-2 text-sm font-medium transition-colors ${
                    cMode === "auto"
                      ? "bg-orange-500/20 text-orange-400 border border-orange-500/40"
                      : "border border-card-border text-muted hover:text-foreground"
                  }`}
                >
                  ⚡ Autonomous
                </button>
              </div>
              <p className="text-xs text-muted mt-1">
                {cMode === "paper"
                  ? "Simulates trades without connecting to broker. Tracks virtual P&L."
                  : cMode === "confirmation"
                    ? "Shows trade signals and requires your approval before execution."
                    : "Fully autonomous — executes trades directly on broker without confirmation."}
              </p>
              {cMode === "auto" && (
                <div className="mt-2 rounded-lg bg-orange-500/10 border border-orange-500/30 px-3 py-2 text-xs text-orange-400">
                  ⚠️ Autonomous mode will place real trades on your connected broker. Ensure risk settings are configured.
                </div>
              )}
            </div>

            {/* ML Model (optional) */}
            <div>
              <label className="block text-xs text-muted mb-1">
                ML Model <span className="text-zinc-500">(optional — filters/enhances signals)</span>
              </label>
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

            {/* ── Risk Configuration ── */}
            <div className="border-t border-card-border pt-3">
              <label className="block text-xs font-semibold text-foreground mb-2">Risk Configuration</label>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[10px] text-muted mb-1">Position Sizing</label>
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
                  <label className="block text-[10px] text-muted mb-1">
                    {cSizeType === "fixed_lot" ? "Lot Size" : "Risk %"}
                  </label>
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
                  <label className="block text-[10px] text-muted mb-1">Max Exposure</label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    value={cMaxExposure}
                    onChange={(e) => setCMaxExposure(e.target.value)}
                    className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
                    placeholder="1.0 lots"
                  />
                </div>
                <div>
                  <label className="block text-[10px] text-muted mb-1">Max Positions</label>
                  <input
                    type="number"
                    step="1"
                    min="1"
                    value={cMaxOpenPositions}
                    onChange={(e) => setCMaxOpenPositions(e.target.value)}
                    className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
                    placeholder="3"
                  />
                </div>
                <div>
                  <label className="block text-[10px] text-muted mb-1">Max Daily Loss %</label>
                  <input
                    type="number"
                    step="0.5"
                    min="0"
                    value={cMaxDailyLoss}
                    onChange={(e) => setCMaxDailyLoss(e.target.value)}
                    className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
                    placeholder="5%"
                  />
                </div>
              </div>

              <div className="mt-2">
                <label className="block text-[10px] text-muted mb-1">Max Drawdown % <span className="text-zinc-500">(0 = disabled)</span></label>
                <input
                  type="number"
                  step="1"
                  min="0"
                  value={cMaxDrawdown}
                  onChange={(e) => setCMaxDrawdown(e.target.value)}
                  className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
                  placeholder="10%"
                />
              </div>
            </div>

            <div className="flex justify-end gap-3 pt-2">
              <button
                onClick={() => setShowCreate(false)}
                className="rounded-lg border border-card-border px-4 py-2 text-sm text-muted hover:text-foreground"
              >
                Cancel
              </button>
              <button
                onClick={handleCreate}
                disabled={creating || !cName || !cStrategyId}
                className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-black hover:bg-accent/90 disabled:opacity-40 transition-colors"
              >
                {creating ? "Creating..." : "Create Agent"}
              </button>
            </div>
          </div>
        </div>
      )}

      {editAgent && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={e => { if (e.target === e.currentTarget) setEditAgent(null); }}>
          <div className="w-full max-w-md rounded-xl border border-card-border bg-card-bg p-6 space-y-4 max-h-[90vh] overflow-y-auto">
            <h3 className="font-semibold text-foreground">Edit Agent</h3>
            <div className="grid grid-cols-3 gap-2 text-xs">
              <div className="rounded bg-background p-2"><div className="text-muted mb-0.5">Symbol</div><div className="text-foreground font-mono">{editAgent.symbol}</div></div>
              <div className="rounded bg-background p-2"><div className="text-muted mb-0.5">Timeframe</div><div className="text-foreground">{editAgent.timeframe}</div></div>
              <div className="rounded bg-background p-2"><div className="text-muted mb-0.5">Broker</div><div className="text-foreground capitalize">{editAgent.broker_name}</div></div>
            </div>
            <div>
              <label className="block text-xs text-muted mb-1.5">Agent Name</label>
              <input value={editName} onChange={e => setEditName(e.target.value)}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm outline-none focus:border-accent" />
            </div>
            <div>
              <label className="block text-xs text-muted mb-1.5">Mode</label>
              <select value={editMode} onChange={e => setEditMode(e.target.value)}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm outline-none focus:border-accent">
                <option value="paper">Paper Trading (simulated)</option>
                <option value="confirm">Confirm Each Trade</option>
                <option value="autonomous">Fully Autonomous</option>
              </select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-muted mb-1.5">Lot Size</label>
                <input type="number" step="0.01" min="0.01" value={editLotSize} onChange={e => setEditLotSize(parseFloat(e.target.value) || 0.01)}
                  className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm outline-none focus:border-accent" />
              </div>
              <div>
                <label className="block text-xs text-muted mb-1.5">Max Open Positions</label>
                <input type="number" min="1" max="50" value={editMaxPositions} onChange={e => setEditMaxPositions(parseInt(e.target.value) || 1)}
                  className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm outline-none focus:border-accent" />
              </div>
              <div>
                <label className="block text-xs text-muted mb-1.5">Max Daily Loss %</label>
                <input type="number" step="0.5" min="0" value={editMaxDailyLoss} onChange={e => setEditMaxDailyLoss(parseFloat(e.target.value) || 0)}
                  className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm outline-none focus:border-accent" />
              </div>
              <div>
                <label className="block text-xs text-muted mb-1.5">Max Drawdown %</label>
                <input type="number" step="0.5" min="0" value={editMaxDrawdown} onChange={e => setEditMaxDrawdown(parseFloat(e.target.value) || 0)}
                  className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm outline-none focus:border-accent" />
              </div>
            </div>
            {editMsg && <p className={`text-xs ${editMsg.startsWith('✓') ? 'text-accent' : 'text-danger'}`}>{editMsg}</p>}
            <div className="flex gap-2 pt-1">
              <button onClick={async () => {
                try {
                  await api.put(`/api/agents/${editAgent.id}`, {
                    name: editName, mode: editMode, ml_model_id: editMlModelId,
                    risk_config: { ...editAgent.risk_config, lot_size: editLotSize, max_open_positions: editMaxPositions, max_daily_loss_pct: editMaxDailyLoss, max_drawdown_pct: editMaxDrawdown },
                  });
                  setEditMsg("✓ Agent updated successfully");
                  setTimeout(() => setEditAgent(null), 1200);
                } catch (err: unknown) { setEditMsg(err instanceof Error ? err.message : "Save failed"); }
              }} className="flex-1 rounded-lg bg-accent py-2 text-sm font-medium text-black hover:bg-accent-hover transition-colors">Save Changes</button>
              <button onClick={() => setEditAgent(null)} className="flex-1 rounded-lg border border-card-border py-2 text-sm text-muted hover:text-foreground transition-colors">Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════
   Agent Detail Sub-Component
   ═══════════════════════════════════════════════════════ */

function AgentDetail({
  agent,
  strategyName,
  logs,
  logsLoading,
  trades,
  tradesLoading,
  performance,
  onBack,
  onConfirm,
  onReject,
}: {
  agent: Agent;
  strategyName: string;
  logs: AgentLog[];
  logsLoading: boolean;
  trades: AgentTrade[];
  tradesLoading: boolean;
  performance: ReturnType<typeof useAgents.getState>["performance"];
  onBack: () => void;
  onConfirm: (trade: AgentTrade) => void;
  onReject: (trade: AgentTrade) => void;
}) {
  const [detailTab, setDetailTab] = useState<"trades" | "logs" | "performance">("trades");

  return (
    <div className="p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="rounded border border-card-border px-2 py-1 text-xs text-muted hover:text-foreground transition-colors"
          >
            ← Back
          </button>
          <div>
            <h4 className="text-sm font-semibold">{agent.name}</h4>
            <div className="text-xs text-muted">
              {strategyName} • {agent.symbol} • {agent.timeframe} •{" "}
              <span className="uppercase">{agent.mode}</span>
              {agent.ml_model_id && (
                <span className="text-cyan-400/70 ml-1">
                  • ML Model #{agent.ml_model_id}
                </span>
              )}
            </div>
          </div>
        </div>
        <span
          className={`rounded px-2 py-0.5 text-xs font-medium uppercase ${
            statusColor[agent.status] || "bg-zinc-500/20 text-zinc-400"
          }`}
        >
          {agent.status}
        </span>
      </div>

      {/* Performance summary cards */}
      {performance && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <div className="rounded-lg border border-card-border bg-background/50 p-3">
            <div className="text-[10px] text-muted uppercase">Total P&L</div>
            <div className={`text-sm font-semibold ${pnlColor(performance.total_pnl)}`}>
              {performance.total_pnl >= 0 ? "+" : ""}
              {performance.total_pnl.toFixed(2)}
            </div>
          </div>
          <div className="rounded-lg border border-card-border bg-background/50 p-3">
            <div className="text-[10px] text-muted uppercase">Win Rate</div>
            <div className="text-sm font-semibold">{performance.win_rate.toFixed(1)}%</div>
          </div>
          <div className="rounded-lg border border-card-border bg-background/50 p-3">
            <div className="text-[10px] text-muted uppercase">Total Trades</div>
            <div className="text-sm font-semibold">{performance.total_trades}</div>
          </div>
          <div className="rounded-lg border border-card-border bg-background/50 p-3">
            <div className="text-[10px] text-muted uppercase">Wins</div>
            <div className="text-sm font-semibold text-green-400">{performance.wins}</div>
          </div>
          <div className="rounded-lg border border-card-border bg-background/50 p-3">
            <div className="text-[10px] text-muted uppercase">Losses</div>
            <div className="text-sm font-semibold text-red-400">{performance.losses}</div>
          </div>
        </div>
      )}

      {/* Detail tabs */}
      <div className="flex gap-1 border-b border-card-border pb-0">
        {(["trades", "logs", "performance"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setDetailTab(t)}
            className={`rounded-t px-3 py-1.5 text-xs font-medium transition-colors ${
              detailTab === t
                ? "bg-card-bg text-accent border-b-2 border-accent"
                : "text-muted hover:text-foreground"
            }`}
          >
            {t === "trades" ? `Trades (${trades.length})` : t === "logs" ? `Logs (${logs.length})` : "Equity Curve"}
          </button>
        ))}
      </div>

      {/* ── Trades Tab ── */}
      {detailTab === "trades" && (
        <div>
          {tradesLoading ? (
            <div className="flex h-24 items-center justify-center text-sm text-muted">
              Loading trades...
            </div>
          ) : trades.length === 0 ? (
            <div className="flex h-24 items-center justify-center text-sm text-muted">
              No trades yet
            </div>
          ) : (
            <div className="max-h-[300px] overflow-y-auto space-y-2">
              {trades.map((t) => (
                <div
                  key={t.id}
                  className={`flex items-center justify-between rounded-lg border p-3 ${
                    t.status === "pending_confirmation"
                      ? "border-yellow-500/30 bg-yellow-500/5"
                      : "border-card-border bg-background/50"
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-bold ${
                        t.direction === "BUY"
                          ? "bg-green-500/20 text-green-400"
                          : "bg-red-500/20 text-red-400"
                      }`}
                    >
                      {t.direction}
                    </span>
                    <div>
                      <div className="text-sm font-medium">
                        {t.symbol} • {t.lot_size} lots
                      </div>
                      <div className="text-xs text-muted">
                        Entry: {t.entry_price?.toFixed(2) ?? "—"} •
                        SL: {t.stop_loss?.toFixed(2) ?? "—"} •
                        TP: {t.take_profit_1?.toFixed(2) ?? "—"}
                        {t.signal_reason && <span className="ml-1 italic">({t.signal_reason})</span>}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="text-right">
                      <div className={`text-sm font-medium ${pnlColor(t.pnl)}`}>
                        {t.pnl !== 0
                          ? `${t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(2)}`
                          : "—"}
                      </div>
                      <span
                        className={`text-[10px] font-medium uppercase rounded px-1.5 py-0.5 ${
                          t.status === "pending_confirmation"
                            ? "bg-yellow-500/20 text-yellow-400"
                            : t.status === "executed" || t.status === "paper"
                              ? "bg-green-500/15 text-green-400"
                              : t.status === "rejected"
                                ? "bg-red-500/15 text-red-400"
                                : "bg-zinc-500/15 text-zinc-400"
                        }`}
                      >
                        {t.status}
                      </span>
                    </div>
                    {t.status === "pending_confirmation" && (
                      <div className="flex gap-1">
                        <button
                          onClick={() => onConfirm(t)}
                          className="rounded bg-green-600 px-2 py-1 text-xs font-medium text-white hover:bg-green-700"
                        >
                          ✓
                        </button>
                        <button
                          onClick={() => onReject(t)}
                          className="rounded border border-red-500/40 px-2 py-1 text-xs text-red-400 hover:bg-red-500/10"
                        >
                          ✕
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Logs Tab ── */}
      {detailTab === "logs" && (
        <div>
          {logsLoading ? (
            <div className="flex h-24 items-center justify-center text-sm text-muted">
              Loading logs...
            </div>
          ) : logs.length === 0 ? (
            <div className="flex h-24 items-center justify-center text-sm text-muted">
              No logs yet
            </div>
          ) : (
            <div className="max-h-[300px] overflow-y-auto font-mono text-xs space-y-0.5">
              {logs.map((log) => (
                <div
                  key={log.id}
                  className={`flex gap-2 rounded px-2 py-1 ${
                    log.level === "error"
                      ? "bg-red-500/5 text-red-400"
                      : log.level === "warn"
                        ? "bg-yellow-500/5 text-yellow-400"
                        : log.level === "trade"
                          ? "bg-green-500/5 text-green-400"
                          : "text-muted"
                  }`}
                >
                  <span className="shrink-0 text-zinc-600">
                    {new Date(log.created_at).toLocaleTimeString()}
                  </span>
                  <span
                    className={`shrink-0 w-12 text-right uppercase font-semibold ${
                      log.level === "error"
                        ? "text-red-400"
                        : log.level === "warn"
                          ? "text-yellow-400"
                          : log.level === "trade"
                            ? "text-green-400"
                            : "text-zinc-500"
                    }`}
                  >
                    {log.level}
                  </span>
                  <span className="break-all">{log.message}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Equity Curve Tab ── */}
      {detailTab === "performance" && (
        <div>
          {!performance || performance.equity_curve.length === 0 ? (
            <div className="flex h-24 items-center justify-center text-sm text-muted">
              No performance data yet
            </div>
          ) : (
            <div className="space-y-3">
              {/* Simple text-based equity display — can be replaced with chart later */}
              <div className="max-h-[250px] overflow-y-auto font-mono text-xs">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-card-border text-muted">
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
                            <td className="py-1 text-muted">
                              {pt.time ? new Date(pt.time).toLocaleDateString() : `Trade #${i + 1}`}
                            </td>
                            <td className={`py-1 text-right ${pnlColor(pt.pnl)}`}>
                              {pt.pnl >= 0 ? "+" : ""}
                              {pt.pnl.toFixed(2)}
                            </td>
                            <td className={`py-1 text-right font-medium ${pnlColor(cumulative)}`}>
                              {cumulative >= 0 ? "+" : ""}
                              {cumulative.toFixed(2)}
                            </td>
                          </tr>
                        );
                      });
                    })()}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
