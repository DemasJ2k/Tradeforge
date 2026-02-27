"use client";

import { create } from "zustand";
import { api } from "@/lib/api";
import { useWebSocket } from "@/hooks/useWebSocket";
import type {
  Agent,
  AgentList,
  AgentCreateRequest,
  AgentUpdateRequest,
  AgentLog,
  AgentLogList,
  AgentTrade,
  AgentTradeList,
  AgentPerformance,
} from "@/types";

// ── Store state ─────────────────────────────────────

interface AgentsState {
  agents: Agent[];
  loading: boolean;
  error: string | null;

  /** Currently selected agent id (for detail panel) */
  selectedAgentId: number | null;

  /** Logs for the selected agent */
  logs: AgentLog[];
  logsLoading: boolean;

  /** Trades for the selected agent */
  trades: AgentTrade[];
  tradesLoading: boolean;

  /** Pending confirmation trades (across all agents) */
  pendingTrades: AgentTrade[];

  /** Performance stats for selected agent */
  performance: AgentPerformance | null;

  // ── Actions ──

  /** Fetch all agents for current user */
  loadAgents: () => Promise<void>;

  /** Create a new agent */
  createAgent: (data: AgentCreateRequest) => Promise<Agent>;

  /** Update an existing agent */
  updateAgent: (id: number, data: AgentUpdateRequest) => Promise<Agent>;

  /** Delete an agent */
  deleteAgent: (id: number) => Promise<void>;

  /** Start an agent */
  startAgent: (id: number) => Promise<void>;

  /** Stop an agent */
  stopAgent: (id: number) => Promise<void>;

  /** Pause an agent */
  pauseAgent: (id: number) => Promise<void>;

  /** Select an agent and load its details */
  selectAgent: (id: number | null) => void;

  /** Load logs for the selected agent */
  loadLogs: (agentId: number, limit?: number) => Promise<void>;

  /** Load trades for the selected agent */
  loadTrades: (agentId: number, limit?: number) => Promise<void>;

  /** Load all pending trades across all agents */
  loadPendingTrades: () => Promise<void>;

  /** Load performance stats for an agent */
  loadPerformance: (agentId: number) => Promise<void>;

  /** Confirm a pending trade */
  confirmTrade: (agentId: number, tradeId: number) => Promise<void>;

  /** Reject a pending trade */
  rejectTrade: (agentId: number, tradeId: number) => Promise<void>;

  /** Handle real-time agent event from WebSocket */
  handleAgentEvent: (data: Record<string, unknown>) => void;

  /** Reset store */
  reset: () => void;
}

// ── Initial state ───────────────────────────────────

const initialState = {
  agents: [] as Agent[],
  loading: false,
  error: null as string | null,
  selectedAgentId: null as number | null,
  logs: [] as AgentLog[],
  logsLoading: false,
  trades: [] as AgentTrade[],
  tradesLoading: false,
  pendingTrades: [] as AgentTrade[],
  performance: null as AgentPerformance | null,
};

// ── Store ───────────────────────────────────────────

export const useAgents = create<AgentsState>((set, get) => ({
  ...initialState,

  loadAgents: async () => {
    set({ loading: true, error: null });
    try {
      const data = await api.get<AgentList>("/api/agents");
      set({ agents: data.items, loading: false });
    } catch (e) {
      set({ error: (e as Error).message, loading: false });
    }
  },

  createAgent: async (data: AgentCreateRequest) => {
    const agent = await api.post<Agent>("/api/agents", data);
    set((s) => ({ agents: [agent, ...s.agents] }));
    return agent;
  },

  updateAgent: async (id: number, data: AgentUpdateRequest) => {
    const agent = await api.put<Agent>(`/api/agents/${id}`, data);
    set((s) => ({
      agents: s.agents.map((a) => (a.id === id ? agent : a)),
    }));
    return agent;
  },

  deleteAgent: async (id: number) => {
    await api.delete(`/api/agents/${id}`);
    set((s) => ({
      agents: s.agents.filter((a) => a.id !== id),
      selectedAgentId: s.selectedAgentId === id ? null : s.selectedAgentId,
    }));
  },

  startAgent: async (id: number) => {
    const agent = await api.post<Agent>(`/api/agents/${id}/start`, {});
    set((s) => ({
      agents: s.agents.map((a) => (a.id === id ? agent : a)),
    }));
  },

  stopAgent: async (id: number) => {
    const agent = await api.post<Agent>(`/api/agents/${id}/stop`, {});
    set((s) => ({
      agents: s.agents.map((a) => (a.id === id ? agent : a)),
    }));
  },

  pauseAgent: async (id: number) => {
    const agent = await api.post<Agent>(`/api/agents/${id}/pause`, {});
    set((s) => ({
      agents: s.agents.map((a) => (a.id === id ? agent : a)),
    }));
  },

  selectAgent: (id: number | null) => {
    set({ selectedAgentId: id, logs: [], trades: [], performance: null });
    if (id !== null) {
      get().loadLogs(id);
      get().loadTrades(id);
      get().loadPerformance(id);
    }
  },

  loadLogs: async (agentId: number, limit = 50) => {
    set({ logsLoading: true });
    try {
      const data = await api.get<AgentLogList>(
        `/api/agents/${agentId}/logs?limit=${limit}`
      );
      set({ logs: data.items, logsLoading: false });
    } catch {
      set({ logsLoading: false });
    }
  },

  loadTrades: async (agentId: number, limit = 50) => {
    set({ tradesLoading: true });
    try {
      const data = await api.get<AgentTradeList>(
        `/api/agents/${agentId}/trades?limit=${limit}`
      );
      set({ trades: data.items, tradesLoading: false });
    } catch {
      set({ tradesLoading: false });
    }
  },

  loadPendingTrades: async () => {
    // Collect pending trades across all agents
    const { agents } = get();
    const pending: AgentTrade[] = [];
    for (const agent of agents) {
      if (agent.status !== "running") continue;
      try {
        const data = await api.get<AgentTradeList>(
          `/api/agents/${agent.id}/trades?status=pending_confirmation&limit=20`
        );
        pending.push(...data.items);
      } catch {
        // skip
      }
    }
    set({ pendingTrades: pending });
  },

  loadPerformance: async (agentId: number) => {
    try {
      const data = await api.get<AgentPerformance>(
        `/api/agents/${agentId}/performance`
      );
      set({ performance: data });
    } catch {
      set({ performance: null });
    }
  },

  confirmTrade: async (agentId: number, tradeId: number) => {
    await api.post(`/api/agents/${agentId}/trades/${tradeId}/confirm`, {});
    // Refresh trades and pending
    set((s) => ({
      pendingTrades: s.pendingTrades.filter((t) => t.id !== tradeId),
      trades: s.trades.map((t) =>
        t.id === tradeId ? { ...t, status: "confirmed" as const } : t
      ),
    }));
  },

  rejectTrade: async (agentId: number, tradeId: number) => {
    await api.post(`/api/agents/${agentId}/trades/${tradeId}/reject`, {});
    set((s) => ({
      pendingTrades: s.pendingTrades.filter((t) => t.id !== tradeId),
      trades: s.trades.map((t) =>
        t.id === tradeId ? { ...t, status: "rejected" as const } : t
      ),
    }));
  },

  handleAgentEvent: (data: Record<string, unknown>) => {
    const eventType = data.event as string | undefined;
    const agentId = data.agent_id as number | undefined;

    if (!eventType || !agentId) return;

    switch (eventType) {
      case "status_change": {
        const newStatus = data.status as string;
        set((s) => ({
          agents: s.agents.map((a) =>
            a.id === agentId
              ? { ...a, status: newStatus as Agent["status"] }
              : a
          ),
        }));
        break;
      }

      case "new_trade": {
        const trade = data.trade as AgentTrade | undefined;
        if (!trade) break;

        // Add to pending if it needs confirmation
        if (trade.status === "pending_confirmation") {
          set((s) => ({
            pendingTrades: [trade, ...s.pendingTrades],
          }));
        }

        // Add to trades list if viewing this agent
        if (get().selectedAgentId === agentId) {
          set((s) => ({ trades: [trade, ...s.trades] }));
        }
        break;
      }

      case "trade_update": {
        const trade = data.trade as AgentTrade | undefined;
        if (!trade) break;

        set((s) => ({
          trades: s.trades.map((t) => (t.id === trade.id ? trade : t)),
          pendingTrades: s.pendingTrades.filter((t) => t.id !== trade.id),
        }));
        break;
      }

      case "log": {
        const log = data.log as AgentLog | undefined;
        if (!log) break;

        // Prepend to logs if viewing this agent
        if (get().selectedAgentId === agentId) {
          set((s) => ({ logs: [log, ...s.logs].slice(0, 200) }));
        }
        break;
      }

      case "performance_update": {
        const perf = data.performance as AgentPerformance | undefined;
        if (!perf) break;

        if (get().selectedAgentId === agentId) {
          set({ performance: perf });
        }

        // Update agent performance_stats
        set((s) => ({
          agents: s.agents.map((a) =>
            a.id === agentId
              ? {
                  ...a,
                  performance_stats: {
                    total_pnl: perf.total_pnl,
                    win_rate: perf.win_rate,
                    total_trades: perf.total_trades,
                  },
                }
              : a
          ),
        }));
        break;
      }
    }
  },

  reset: () => set(initialState),
}));

// ── WebSocket subscription helper ───────────────────

/**
 * Subscribe to real-time updates for a specific agent.
 * Call this from a useEffect with the agent id.
 * Returns the unsubscribe function.
 */
export function subscribeToAgent(agentId: number): () => void {
  const ws = useWebSocket.getState();
  const { handleAgentEvent } = useAgents.getState();

  return ws.subscribe(`agent:${agentId}`, handleAgentEvent);
}

/**
 * Subscribe to real-time updates for all running agents.
 * Returns a cleanup function that unsubscribes all.
 */
export function subscribeToAllAgents(): () => void {
  const { agents } = useAgents.getState();
  const unsubs: (() => void)[] = [];

  for (const agent of agents) {
    if (agent.status === "running" || agent.status === "paused") {
      unsubs.push(subscribeToAgent(agent.id));
    }
  }

  return () => {
    for (const unsub of unsubs) {
      unsub();
    }
  };
}
