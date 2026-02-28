"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import Link from "next/link";
import ChatHelpers from "@/components/ChatHelpers";
import { useBrokerAccounts } from "@/hooks/useBrokerAccounts";

/* ─── Types ─────────────────────────────────────────────── */
interface DashboardData {
  account: {
    balance: number;
    equity: number;
    unrealized_pnl: number;
    currency: string;
    open_positions: number;
    open_orders: number;
    margin_used: number;
    broker_connected: boolean;
    broker_name: string | null;
  };
  positions: {
    position_id: string;
    symbol: string;
    side: string;
    size: number;
    entry_price: number;
    current_price: number;
    unrealized_pnl: number;
  }[];
  strategies: { total: number; system: number; user: number };
  agents: {
    total: number;
    running: number;
    paused: number;
    paper: number;
    items: {
      id: number;
      name: string;
      symbol: string;
      timeframe: string;
      mode: string;
      status: string;
      strategy_id: number;
    }[];
  };
  today: {
    pnl: number;
    trades: number;
    wins: number;
    losses: number;
    win_rate: number;
  };
  recent_trades: {
    id: number;
    source: string;
    symbol: string;
    direction: string;
    entry_price: number | null;
    exit_price: number | null;
    lot_size: number;
    pnl: number;
    status: string;
    time: string;
  }[];
  backtests: { total: number; last_run: string | null; last_status: string | null };
  data_sources: number;
  pending_confirmations: number;
  ws_clients: number;
}

/* ─── Helpers ───────────────────────────────────────────── */
const fmt = (n: number, decimals = 2) =>
  n.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });

const pnlColor = (n: number) =>
  n > 0 ? "text-success" : n < 0 ? "text-danger" : "text-muted";

const statusDot = (status: string) => {
  const colors: Record<string, string> = {
    running: "bg-success",
    paused: "bg-yellow-500",
    stopped: "bg-muted",
    error: "bg-danger",
  };
  return colors[status] || "bg-muted";
};

/* ─── Component ─────────────────────────────────────────── */
export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const { accounts: brokerAccounts, activeBroker, setActiveBroker } = useBrokerAccounts();

  const load = useCallback(async () => {
    try {
      const d = await api.get<DashboardData>("/api/dashboard/summary");
      setData(d);
      setError("");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const iv = setInterval(load, 15000);          // refresh every 15s
    return () => clearInterval(iv);
  }, [load]);

  if (loading) return <DashSkeleton />;
  if (error) return <div className="p-6 text-danger">{error}</div>;
  if (!data) return null;

  const { account: a, today: t, strategies: s, agents: ag, recent_trades: trades, positions: pos } = data;

  return (
    <div className="space-y-6">
      {/* ── Header Row ─────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Dashboard</h2>
        <div className="flex items-center gap-3 text-xs">
          <span className="flex items-center gap-1.5">
            <span className={`inline-block h-2 w-2 rounded-full ${a.broker_connected ? "bg-success" : "bg-danger"}`} />
            {a.broker_connected ? `${a.broker_name} connected` : "No broker"}
          </span>
          <span className="flex items-center gap-1.5">
            <span className={`inline-block h-2 w-2 rounded-full ${data.ws_clients > 0 ? "bg-success" : "bg-muted"}`} />
            WS {data.ws_clients > 0 ? "live" : "off"}
          </span>
          {data.pending_confirmations > 0 && (
            <Link href="/trading" className="rounded bg-accent/20 px-2 py-0.5 text-accent hover:bg-accent/30 transition">
              {data.pending_confirmations} pending confirmation{data.pending_confirmations > 1 ? "s" : ""}
            </Link>
          )}
        </div>
      </div>

      {/* ── Broker Account Cards ───────────────────────── */}
      {brokerAccounts.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {brokerAccounts.map((acct) => (
            <button
              key={acct.broker}
              onClick={() => setActiveBroker(acct.broker)}
              className={`rounded-xl border p-4 text-left transition-all hover:border-accent/60 ${
                acct.broker === activeBroker
                  ? "border-accent/60 bg-accent/5"
                  : "border-card-border bg-card-bg"
              }`}
            >
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <div className="h-2 w-2 rounded-full bg-green-400" />
                  <span className="text-sm font-semibold capitalize text-foreground">
                    {acct.broker}
                  </span>
                </div>
                {acct.broker === activeBroker && (
                  <span className="rounded-full bg-accent/20 px-1.5 py-0.5 text-[10px] text-accent">
                    active
                  </span>
                )}
              </div>
              <div className="space-y-1.5">
                <div className="flex justify-between text-xs">
                  <span className="text-muted">Balance</span>
                  <span className="font-medium text-foreground">
                    {acct.currency} {acct.balance >= 1000
                      ? `${(acct.balance / 1000).toFixed(1)}k`
                      : acct.balance.toFixed(2)}
                  </span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-muted">Equity</span>
                  <span className="font-medium text-foreground">
                    {acct.currency} {acct.equity >= 1000
                      ? `${(acct.equity / 1000).toFixed(1)}k`
                      : acct.equity.toFixed(2)}
                  </span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-muted">Open P&L</span>
                  <span className={`font-medium ${acct.unrealizedPnl > 0 ? "text-green-400" : acct.unrealizedPnl < 0 ? "text-red-400" : "text-muted"}`}>
                    {acct.unrealizedPnl >= 0 ? "+" : ""}
                    {acct.unrealizedPnl.toFixed(2)}
                  </span>
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

      {/* ── Stats Cards ────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          label="Account Balance"
          value={a.broker_connected ? `$${fmt(a.balance)}` : "—"}
          sub={a.broker_connected ? `Equity: $${fmt(a.equity)}` : "Connect broker"}
          color="text-accent"
        />
        <StatCard
          label="Today's PnL"
          value={t.trades > 0 ? `$${fmt(t.pnl)}` : "$0.00"}
          sub={t.trades > 0 ? `${t.trades} trades · ${t.win_rate}% WR` : "No trades today"}
          color={pnlColor(t.pnl)}
        />
        <StatCard
          label="Open Positions"
          value={String(a.broker_connected ? a.open_positions : pos.length || 0)}
          sub={a.unrealized_pnl !== 0 ? `Unrealized: $${fmt(a.unrealized_pnl)}` : "No open P&L"}
          color={a.open_positions > 0 ? "text-success" : "text-muted"}
        />
        <StatCard
          label="Running Agents"
          value={`${ag.running}`}
          sub={`${ag.total} total · ${ag.paused} paused`}
          color={ag.running > 0 ? "text-success" : "text-muted"}
        />
      </div>

      {/* ── Middle Row: Positions + Quick Stats ─────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* Positions / Portfolio */}
        <div className="lg:col-span-2 rounded-xl border border-card-border bg-card-bg p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-medium text-muted uppercase tracking-wider">Open Positions</h3>
            {a.broker_connected && (
              <Link href="/trading" className="text-xs text-accent hover:underline">Go to Trading →</Link>
            )}
          </div>
          {pos.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-muted border-b border-card-border">
                    <th className="text-left py-2 pr-3">Symbol</th>
                    <th className="text-left py-2 pr-3">Side</th>
                    <th className="text-right py-2 pr-3">Size</th>
                    <th className="text-right py-2 pr-3">Entry</th>
                    <th className="text-right py-2 pr-3">Current</th>
                    <th className="text-right py-2">P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {pos.map((p) => (
                    <tr key={p.position_id} className="border-b border-card-border/40">
                      <td className="py-2 pr-3 font-medium">{p.symbol}</td>
                      <td className={`py-2 pr-3 ${p.side === "BUY" ? "text-success" : "text-danger"}`}>
                        {p.side}
                      </td>
                      <td className="py-2 pr-3 text-right">{p.size}</td>
                      <td className="py-2 pr-3 text-right">{fmt(p.entry_price, 5)}</td>
                      <td className="py-2 pr-3 text-right">{fmt(p.current_price, 5)}</td>
                      <td className={`py-2 text-right font-medium ${pnlColor(p.unrealized_pnl)}`}>
                        ${fmt(p.unrealized_pnl)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="flex h-32 items-center justify-center text-sm text-muted">
              {a.broker_connected ? "No open positions" : "Connect a broker to see positions"}
            </div>
          )}
        </div>

        {/* Quick Stats */}
        <div className="rounded-xl border border-card-border bg-card-bg p-5 space-y-4">
          <h3 className="text-sm font-medium text-muted uppercase tracking-wider">Platform Stats</h3>
          <div className="space-y-3 text-sm">
            <StatRow label="Strategies" value={`${s.user} user · ${s.system} system`} />
            <StatRow label="Data Sources" value={`${data.data_sources} files`} />
            <StatRow label="Backtests Run" value={`${data.backtests.total}`} />
            <StatRow
              label="Last Backtest"
              value={data.backtests.last_run
                ? new Date(data.backtests.last_run).toLocaleDateString()
                : "—"
              }
            />
            <StatRow label="Agents (Paper)" value={`${ag.paper}`} />
          </div>
          <div className="pt-2 border-t border-card-border space-y-2">
            <Link href="/strategies" className="block text-xs text-accent hover:underline">+ New Strategy</Link>
            <Link href="/backtest" className="block text-xs text-accent hover:underline">+ Run Backtest</Link>
            <Link href="/trading" className="block text-xs text-accent hover:underline">→ Go to Trading</Link>
          </div>
        </div>
      </div>

      {/* ── Bottom Row: Trades + Agents ────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

        {/* Recent Trades */}
        <div className="rounded-xl border border-card-border bg-card-bg p-5">
          <h3 className="text-sm font-medium text-muted uppercase tracking-wider mb-4">Recent Trades</h3>
          {trades.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-muted border-b border-card-border">
                    <th className="text-left py-2 pr-2">Symbol</th>
                    <th className="text-left py-2 pr-2">Dir</th>
                    <th className="text-right py-2 pr-2">Size</th>
                    <th className="text-right py-2 pr-2">P&L</th>
                    <th className="text-left py-2 pr-2">Source</th>
                    <th className="text-left py-2">Time</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.map((tr) => (
                    <tr key={`${tr.source}-${tr.id}`} className="border-b border-card-border/40">
                      <td className="py-1.5 pr-2 font-medium">{tr.symbol}</td>
                      <td className={`py-1.5 pr-2 ${tr.direction === "BUY" ? "text-success" : "text-danger"}`}>
                        {tr.direction}
                      </td>
                      <td className="py-1.5 pr-2 text-right">{tr.lot_size}</td>
                      <td className={`py-1.5 pr-2 text-right font-medium ${pnlColor(tr.pnl)}`}>
                        ${fmt(tr.pnl)}
                      </td>
                      <td className="py-1.5 pr-2">
                        <span className={`inline-block rounded px-1.5 py-0.5 text-[10px] ${
                          tr.source === "agent" ? "bg-accent/20 text-accent" : "bg-success/20 text-success"
                        }`}>
                          {tr.source}
                        </span>
                      </td>
                      <td className="py-1.5 text-muted">
                        {tr.time ? new Date(tr.time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="flex h-32 items-center justify-center text-sm text-muted">
              No trades yet
            </div>
          )}
        </div>

        {/* Active Agents */}
        <div className="rounded-xl border border-card-border bg-card-bg p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-medium text-muted uppercase tracking-wider">Trading Agents</h3>
            <Link href="/trading" className="text-xs text-accent hover:underline">Manage →</Link>
          </div>
          {ag.items.length > 0 ? (
            <div className="space-y-2">
              {ag.items.map((agent) => (
                <div
                  key={agent.id}
                  className="flex items-center justify-between rounded-lg border border-card-border/60 px-3 py-2"
                >
                  <div className="flex items-center gap-2">
                    <span className={`inline-block h-2 w-2 rounded-full ${statusDot(agent.status)}`} />
                    <span className="text-sm font-medium">{agent.name}</span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-muted">
                    <span>{agent.symbol}</span>
                    <span>{agent.timeframe}</span>
                    <span className={`rounded px-1.5 py-0.5 ${
                      agent.mode === "paper" ? "bg-yellow-500/20 text-yellow-400" : "bg-accent/20 text-accent"
                    }`}>
                      {agent.mode}
                    </span>
                    <span className={`font-medium ${
                      agent.status === "running" ? "text-success" : agent.status === "error" ? "text-danger" : "text-muted"
                    }`}>
                      {agent.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex h-32 items-center justify-center text-sm text-muted">
              <div className="text-center">
                <p>No agents created yet</p>
                <Link href="/trading" className="text-accent hover:underline mt-1 inline-block">
                  Create your first agent →
                </Link>
              </div>
            </div>
          )}
        </div>
      </div>

      <ChatHelpers />
    </div>
  );
}

/* ─── Sub-components ───────────────────────────────────── */
function StatCard({ label, value, sub, color }: { label: string; value: string; sub: string; color: string }) {
  return (
    <div className="rounded-xl border border-card-border bg-card-bg p-5">
      <p className="text-xs text-muted mb-1">{label}</p>
      <p className={`text-2xl font-semibold ${color}`}>{value}</p>
      <p className="text-xs text-muted mt-1">{sub}</p>
    </div>
  );
}

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-muted">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

function DashSkeleton() {
  return (
    <div className="space-y-6 animate-pulse">
      <div className="h-7 w-32 rounded bg-card-border/30" />
      <div className="grid grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="rounded-xl border border-card-border bg-card-bg p-5 space-y-2">
            <div className="h-3 w-20 rounded bg-card-border/30" />
            <div className="h-7 w-24 rounded bg-card-border/30" />
            <div className="h-3 w-28 rounded bg-card-border/30" />
          </div>
        ))}
      </div>
      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2 rounded-xl border border-card-border bg-card-bg p-5 h-48" />
        <div className="rounded-xl border border-card-border bg-card-bg p-5 h-48" />
      </div>
    </div>
  );
}
