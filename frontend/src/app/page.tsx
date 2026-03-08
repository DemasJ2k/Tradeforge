"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import Link from "next/link";
import ChatHelpers from "@/components/ChatHelpers";
import { useBrokerAccounts } from "@/hooks/useBrokerAccounts";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Activity, TrendingUp, Wallet, Bot, Plus, ArrowRight, BarChart3, Database, Zap } from "lucide-react";
import WelcomeWizard, { useOnboarding } from "@/components/Onboarding/WelcomeWizard";

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
  n > 0 ? "text-success" : n < 0 ? "text-danger" : "text-muted-foreground";

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
  const { showOnboarding, dismissOnboarding } = useOnboarding();

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

  // Show onboarding for new users (no user strategies and no data sources)
  const isNewUser = s.user === 0 && data.data_sources === 0;

  return (
    <div className="space-y-6">
      {/* Onboarding wizard for first-time users */}
      {showOnboarding && isNewUser && (
        <WelcomeWizard onDismiss={dismissOnboarding} />
      )}
      {/* ── Header Row ─────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2">
        <h2 className="text-xl font-semibold">Dashboard</h2>
        <div className="flex items-center gap-3 text-xs flex-wrap">
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
            <Card
              key={acct.broker}
              className={`cursor-pointer transition-all hover:border-accent/60 ${
                acct.broker === activeBroker
                  ? "border-accent/60 bg-accent/5"
                  : "bg-card-bg border-card-border"
              }`}
              onClick={() => setActiveBroker(acct.broker)}
            >
              <CardContent className="p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <div className="h-2 w-2 rounded-full bg-green-400" />
                  <span className="text-sm font-semibold capitalize text-foreground">
                    {acct.broker}
                  </span>
                </div>
                {acct.broker === activeBroker && (
                  <Badge variant="secondary" className="text-[10px] text-accent bg-accent/20">active</Badge>
                )}
              </div>
              <div className="space-y-1.5">
                <div className="flex justify-between text-xs">
                  <span className="text-muted-foreground">Balance</span>
                  <span className="font-medium text-foreground">
                    {acct.currency} {acct.balance >= 1000
                      ? `${(acct.balance / 1000).toFixed(1)}k`
                      : acct.balance.toFixed(2)}
                  </span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-muted-foreground">Equity</span>
                  <span className="font-medium text-foreground">
                    {acct.currency} {acct.equity >= 1000
                      ? `${(acct.equity / 1000).toFixed(1)}k`
                      : acct.equity.toFixed(2)}
                  </span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-muted-foreground">Open P&L</span>
                  <span className={`font-medium ${acct.unrealizedPnl > 0 ? "text-green-400" : acct.unrealizedPnl < 0 ? "text-red-400" : "text-muted-foreground"}`}>
                    {acct.unrealizedPnl >= 0 ? "+" : ""}
                    {acct.unrealizedPnl.toFixed(2)}
                  </span>
                </div>
              </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* ── Stats Cards ────────────────────────────────── */}
      <div className="grid grid-cols-1 xs:grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
        <StatCard
          icon={<Wallet className="h-4 w-4" />}
          label="Account Balance"
          value={a.broker_connected ? `$${fmt(a.balance)}` : "—"}
          sub={a.broker_connected ? `Equity: $${fmt(a.equity)}` : "Connect broker"}
          color="text-accent"
        />
        <StatCard
          icon={<TrendingUp className="h-4 w-4" />}
          label="Today's PnL"
          value={t.trades > 0 ? `$${fmt(t.pnl)}` : "$0.00"}
          sub={t.trades > 0 ? `${t.trades} trades · ${t.win_rate}% WR` : "No trades today"}
          color={pnlColor(t.pnl)}
        />
        <StatCard
          icon={<Activity className="h-4 w-4" />}
          label="Open Positions"
          value={String(a.broker_connected ? a.open_positions : pos.length || 0)}
          sub={a.unrealized_pnl !== 0 ? `Unrealized: $${fmt(a.unrealized_pnl)}` : "No open P&L"}
          color={a.open_positions > 0 ? "text-success" : "text-muted-foreground"}
        />
        <StatCard
          icon={<Bot className="h-4 w-4" />}
          label="Running Agents"
          value={`${ag.running}`}
          sub={`${ag.total} total · ${ag.paused} paused`}
          color={ag.running > 0 ? "text-success" : "text-muted-foreground"}
        />
      </div>

      {/* ── Middle Row: Positions + Quick Stats ─────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 sm:gap-4">

        {/* Positions / Portfolio */}
        <Card className="lg:col-span-2 bg-card-bg border-card-border">
          <CardContent className="p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Open Positions</h3>
            {a.broker_connected && (
              <Button variant="ghost" size="sm" asChild className="text-accent h-7 gap-1">
                <Link href="/trading">Go to Trading <ArrowRight className="h-3 w-3" /></Link>
              </Button>
            )}
          </div>
          {pos.length > 0 ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="border-card-border">
                    <TableHead className="text-xs">Symbol</TableHead>
                    <TableHead className="text-xs">Side</TableHead>
                    <TableHead className="text-xs text-right">Size</TableHead>
                    <TableHead className="text-xs text-right">Entry</TableHead>
                    <TableHead className="text-xs text-right">Current</TableHead>
                    <TableHead className="text-xs text-right">P&L</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pos.map((p) => (
                    <TableRow key={p.position_id} className="border-card-border/40">
                      <TableCell className="font-medium text-xs py-2">{p.symbol}</TableCell>
                      <TableCell className={`text-xs py-2 ${p.side === "BUY" ? "text-success" : "text-danger"}`}>
                        {p.side}
                      </TableCell>
                      <TableCell className="text-xs py-2 text-right">{p.size}</TableCell>
                      <TableCell className="text-xs py-2 text-right">{fmt(p.entry_price, 5)}</TableCell>
                      <TableCell className="text-xs py-2 text-right">{fmt(p.current_price, 5)}</TableCell>
                      <TableCell className={`text-xs py-2 text-right font-medium ${pnlColor(p.unrealized_pnl)}`}>
                        ${fmt(p.unrealized_pnl)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <div className="flex flex-col h-32 items-center justify-center text-center">
              <Activity className="h-6 w-6 text-muted-foreground/40 mb-2" />
              <p className="text-sm text-muted-foreground">
                {a.broker_connected ? "No open positions" : "Connect a broker to see positions"}
              </p>
            </div>
          )}
          </CardContent>
        </Card>

        {/* Quick Stats */}
        <Card className="bg-card-bg border-card-border">
          <CardContent className="p-5 space-y-4">
          <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Platform Stats</h3>
          <div className="space-y-3 text-sm">
            <StatRow icon={<Zap className="h-3.5 w-3.5 text-accent" />} label="Strategies" value={`${s.user} user · ${s.system} system`} />
            <StatRow icon={<Database className="h-3.5 w-3.5 text-accent" />} label="Data Sources" value={`${data.data_sources} files`} />
            <StatRow icon={<BarChart3 className="h-3.5 w-3.5 text-accent" />} label="Backtests Run" value={`${data.backtests.total}`} />
            <StatRow
              label="Last Backtest"
              value={data.backtests.last_run
                ? new Date(data.backtests.last_run).toLocaleDateString()
                : "—"
              }
            />
            <StatRow icon={<Bot className="h-3.5 w-3.5 text-accent" />} label="Agents (Paper)" value={`${ag.paper}`} />
          </div>
          <div className="pt-2 border-t border-card-border space-y-1.5">
            <Button variant="ghost" size="sm" asChild className="text-accent h-7 gap-1 w-full justify-start">
              <Link href="/strategies"><Plus className="h-3 w-3" /> New Strategy</Link>
            </Button>
            <Button variant="ghost" size="sm" asChild className="text-accent h-7 gap-1 w-full justify-start">
              <Link href="/backtest"><BarChart3 className="h-3 w-3" /> Run Backtest</Link>
            </Button>
            <Button variant="ghost" size="sm" asChild className="text-accent h-7 gap-1 w-full justify-start">
              <Link href="/trading"><ArrowRight className="h-3 w-3" /> Go to Trading</Link>
            </Button>
          </div>
          </CardContent>
        </Card>
      </div>

      {/* ── Bottom Row: Trades + Agents ────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 sm:gap-4">

        {/* Recent Trades */}
        <Card className="bg-card-bg border-card-border">
          <CardContent className="p-5">
          <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wider mb-4">Recent Trades</h3>
          {trades.length > 0 ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="border-card-border">
                    <TableHead className="text-xs">Symbol</TableHead>
                    <TableHead className="text-xs">Dir</TableHead>
                    <TableHead className="text-xs text-right">Size</TableHead>
                    <TableHead className="text-xs text-right">P&L</TableHead>
                    <TableHead className="text-xs">Source</TableHead>
                    <TableHead className="text-xs">Time</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {trades.map((tr) => (
                    <TableRow key={`${tr.source}-${tr.id}`} className="border-card-border/40">
                      <TableCell className="font-medium text-xs py-1.5">{tr.symbol}</TableCell>
                      <TableCell className={`text-xs py-1.5 ${tr.direction === "BUY" ? "text-success" : "text-danger"}`}>
                        {tr.direction}
                      </TableCell>
                      <TableCell className="text-xs py-1.5 text-right">{tr.lot_size}</TableCell>
                      <TableCell className={`text-xs py-1.5 text-right font-medium ${pnlColor(tr.pnl)}`}>
                        ${fmt(tr.pnl)}
                      </TableCell>
                      <TableCell className="text-xs py-1.5">
                        <Badge variant="secondary" className={`text-[10px] ${
                          tr.source === "agent" ? "bg-accent/20 text-accent" : "bg-success/20 text-success"
                        }`}>
                          {tr.source}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs py-1.5 text-muted-foreground">
                        {tr.time ? new Date(tr.time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <div className="flex flex-col h-32 items-center justify-center text-center">
              <TrendingUp className="h-6 w-6 text-muted-foreground/40 mb-2" />
              <p className="text-sm text-muted-foreground">No trades yet</p>
            </div>
          )}
          </CardContent>
        </Card>

        {/* Active Agents */}
        <Card className="bg-card-bg border-card-border">
          <CardContent className="p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Trading Agents</h3>
            <Button variant="ghost" size="sm" asChild className="text-accent h-7 gap-1">
              <Link href="/trading">Manage <ArrowRight className="h-3 w-3" /></Link>
            </Button>
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
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span>{agent.symbol}</span>
                    <span>{agent.timeframe}</span>
                    <Badge variant="secondary" className={`text-[10px] ${
                      agent.mode === "paper" ? "bg-yellow-500/20 text-yellow-400" : "bg-accent/20 text-accent"
                    }`}>
                      {agent.mode}
                    </Badge>
                    <Badge variant="outline" className={`text-[10px] ${
                      agent.status === "running" ? "text-success border-success/30" : agent.status === "error" ? "text-danger border-danger/30" : "text-muted-foreground"
                    }`}>
                      {agent.status}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex flex-col h-32 items-center justify-center text-center">
              <Bot className="h-6 w-6 text-muted-foreground/40 mb-2" />
              <p className="text-sm text-muted-foreground">No agents created yet</p>
              <Button variant="ghost" size="sm" asChild className="text-accent mt-1 gap-1">
                <Link href="/trading"><Plus className="h-3 w-3" /> Create your first agent</Link>
              </Button>
            </div>
          )}
          </CardContent>
        </Card>
      </div>

      <ChatHelpers />
    </div>
  );
}

/* ─── Sub-components ───────────────────────────────────── */
function StatCard({ label, value, sub, color, icon }: { label: string; value: string; sub: string; color: string; icon?: React.ReactNode }) {
  return (
    <Card className="bg-card-bg border-card-border">
      <CardContent className="p-5">
        <div className="flex items-center justify-between mb-1">
          <p className="text-xs text-muted-foreground">{label}</p>
          {icon && <span className="text-muted-foreground/50">{icon}</span>}
        </div>
        <p className={`text-2xl font-semibold ${color}`}>{value}</p>
        <p className="text-xs text-muted-foreground mt-1">{sub}</p>
      </CardContent>
    </Card>
  );
}

function StatRow({ label, value, icon }: { label: string; value: string; icon?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <span className="flex items-center gap-1.5 text-muted-foreground">
        {icon && <span className="text-muted-foreground/60">{icon}</span>}
        {label}
      </span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

function DashSkeleton() {
  return (
    <div className="space-y-6 animate-pulse">
      <div className="h-7 w-32 rounded bg-card-border/30" />
      <div className="grid grid-cols-1 xs:grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
        {[...Array(4)].map((_, i) => (
          <Card key={i} className="bg-card-bg border-card-border">
            <CardContent className="p-5 space-y-2">
              <div className="h-3 w-20 rounded bg-card-border/30" />
              <div className="h-7 w-24 rounded bg-card-border/30" />
              <div className="h-3 w-28 rounded bg-card-border/30" />
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 sm:gap-4">
        <Card className="lg:col-span-2 bg-card-bg border-card-border">
          <CardContent className="p-5 h-48" />
        </Card>
        <Card className="bg-card-bg border-card-border">
          <CardContent className="p-5 h-48" />
        </Card>
      </div>
    </div>
  );
}
