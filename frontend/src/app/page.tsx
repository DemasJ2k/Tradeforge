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
import { Activity, TrendingUp, Wallet, Bot, Plus, ArrowRight, BarChart3, Database, Zap, Radio, Clock, Building2, AlertTriangle } from "lucide-react";
import WelcomeWizard, { useOnboarding } from "@/components/Onboarding/WelcomeWizard";
import { useWebSocket } from "@/hooks/useWebSocket";
import { showToast } from "@/lib/toast";

/* ─── Types ─────────────────────────────────────────────── */
interface ActivityItem {
  id: number;
  agent_id: number;
  agent_name: string;
  level: string;
  message: string;
  created_at: string;
}

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
  equity_curve: { date: string; pnl: number }[];
  backtests: { total: number; last_run: string | null; last_status: string | null };
  data_sources: number;
  pending_confirmations: number;
  ws_clients: number;
  prop_firm_accounts: {
    id: number;
    name: string;
    firm: string;
    phase: string;
    account_size: number;
    balance: number;
    daily_loss_used: number;
    daily_loss_limit: number;
    daily_loss_pct: number;
    drawdown_used: number;
    drawdown_limit: number;
    drawdown_pct: number;
    profit_target: number;
    profit_made: number;
    profit_pct: number;
    open_trades: number;
    days_left: number | null;
  }[];
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
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const { accounts: brokerAccounts, activeBroker, setActiveBroker } = useBrokerAccounts();
  const { showOnboarding, dismissOnboarding } = useOnboarding();

  const load = useCallback(async () => {
    try {
      const [d, act] = await Promise.all([
        api.get<DashboardData>("/api/dashboard/summary"),
        api.get<{ items: ActivityItem[] }>("/api/dashboard/activity").catch(() => ({ items: [] })),
      ]);
      setData(d);
      setActivity(act.items || []);
      setLastRefresh(new Date());
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

  // ── WebSocket: subscribe to running agents for prop firm block alerts ──
  const { connect: wsConnect, subscribe: wsSubscribe } = useWebSocket();
  useEffect(() => {
    wsConnect();
  }, [wsConnect]);

  useEffect(() => {
    if (!data?.agents?.items) return;
    const runningAgents = data.agents.items.filter((a) => a.status === "running");
    if (runningAgents.length === 0) return;

    const unsubs = runningAgents.map((agent) =>
      wsSubscribe(`agent_${agent.id}`, (msg) => {
        if (msg.type === "prop_firm_block") {
          showToast.warning(
            `Trade blocked: ${agent.name}`,
            `${msg.reason} (${msg.symbol} ${msg.direction})`,
          );
          // Refresh dashboard data to reflect updated state
          load();
        }
      })
    );
    return () => unsubs.forEach((u) => u());
  }, [data?.agents?.items, wsSubscribe, load]);

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

      {/* ── Live P&L Ticker Bar ──────────────────────────── */}
      {(a.broker_connected || t.trades > 0) && (
        <div className="flex items-center gap-4 rounded-lg border border-card-border bg-card-bg/50 px-4 py-2 text-xs overflow-x-auto">
          <div className="flex items-center gap-1.5 shrink-0">
            <Radio className="h-3 w-3 text-success animate-pulse" />
            <span className="text-muted-foreground font-medium">LIVE</span>
          </div>
          <div className="h-4 w-px bg-card-border" />
          <div className="flex items-center gap-1.5 shrink-0">
            <span className="text-muted-foreground">Balance</span>
            <span className="font-semibold text-foreground">${fmt(a.balance)}</span>
          </div>
          <div className="h-4 w-px bg-card-border" />
          <div className="flex items-center gap-1.5 shrink-0">
            <span className="text-muted-foreground">Today</span>
            <span className={`font-semibold ${pnlColor(t.pnl)}`}>
              {t.pnl >= 0 ? "+" : ""}${fmt(t.pnl)}
            </span>
            {t.trades > 0 && (
              <span className="text-muted-foreground/60">({t.trades} trades)</span>
            )}
          </div>
          {a.unrealized_pnl !== 0 && (
            <>
              <div className="h-4 w-px bg-card-border" />
              <div className="flex items-center gap-1.5 shrink-0">
                <span className="text-muted-foreground">Open P&L</span>
                <span className={`font-semibold ${pnlColor(a.unrealized_pnl)}`}>
                  {a.unrealized_pnl >= 0 ? "+" : ""}${fmt(a.unrealized_pnl)}
                </span>
              </div>
            </>
          )}
          <div className="ml-auto flex items-center gap-1.5 shrink-0 text-muted-foreground/50">
            <Clock className="h-3 w-3" />
            <span>
              {lastRefresh.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
            </span>
          </div>
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

      {/* ── Equity Curve (30-day P&L) ─────────────────── */}
      {data.equity_curve && data.equity_curve.length > 1 && (
        <Card className="bg-card-bg border-card-border">
          <CardContent className="p-5">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
                30-Day Equity Curve
              </h3>
              <span className={`text-sm font-semibold ${pnlColor(data.equity_curve[data.equity_curve.length - 1].pnl)}`}>
                {data.equity_curve[data.equity_curve.length - 1].pnl >= 0 ? "+" : ""}
                ${fmt(data.equity_curve[data.equity_curve.length - 1].pnl)}
              </span>
            </div>
            <MiniEquityChart points={data.equity_curve} />
          </CardContent>
        </Card>
      )}

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

      {/* ── Agent Activity Feed ───────────────────────── */}
      {activity.length > 0 && (
        <Card className="bg-card-bg border-card-border">
          <CardContent className="p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wider flex items-center gap-2">
                <Radio className="h-3 w-3 text-accent" />
                Agent Activity
              </h3>
              <span className="text-[10px] text-muted-foreground/50">
                Auto-refreshes every 15s
              </span>
            </div>
            <div className="space-y-1.5 max-h-48 overflow-y-auto">
              {activity.slice(0, 10).map((item) => (
                <div
                  key={item.id}
                  className="flex items-start gap-2 rounded-md px-2 py-1.5 text-xs hover:bg-muted/10 transition-colors"
                >
                  <span className={`mt-0.5 inline-block h-1.5 w-1.5 rounded-full shrink-0 ${
                    item.level === "error" ? "bg-danger" :
                    item.level === "warning" ? "bg-yellow-500" :
                    item.level === "trade" ? "bg-success" :
                    "bg-accent/50"
                  }`} />
                  <div className="flex-1 min-w-0">
                    <span className="font-medium text-foreground">{item.agent_name}</span>
                    <span className="text-muted-foreground ml-1.5">{item.message}</span>
                  </div>
                  <span className="text-muted-foreground/50 text-[10px] shrink-0">
                    {item.created_at ? new Date(item.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : ""}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Prop Firm Status Cards ──────────────────────── */}
      {data.prop_firm_accounts && data.prop_firm_accounts.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wider flex items-center gap-2">
              <Building2 className="h-3.5 w-3.5 text-accent" />
              Prop Firm Accounts
            </h3>
            <Button variant="ghost" size="sm" asChild className="text-accent h-7 gap-1">
              <Link href="/prop-firms">Manage <ArrowRight className="h-3 w-3" /></Link>
            </Button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {data.prop_firm_accounts.map((pf) => (
              <Card key={pf.id} className="bg-card-bg border-card-border">
                <CardContent className="p-4 space-y-3">
                  {/* Header */}
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium">{pf.name}</p>
                      <p className="text-[10px] text-muted-foreground">{pf.firm} · {pf.phase}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-semibold">${fmt(pf.balance)}</p>
                      <p className="text-[10px] text-muted-foreground">${fmt(pf.account_size)} size</p>
                    </div>
                  </div>

                  {/* Profit Target */}
                  {pf.profit_target > 0 && (
                    <div>
                      <div className="flex justify-between text-[10px] mb-1">
                        <span className="text-muted-foreground">Profit Target</span>
                        <span className="text-success">${fmt(pf.profit_made)} / ${fmt(pf.profit_target)} ({pf.profit_pct}%)</span>
                      </div>
                      <div className="h-1.5 rounded-full bg-card-border overflow-hidden">
                        <div className="h-full rounded-full bg-success transition-all" style={{ width: `${Math.min(pf.profit_pct, 100)}%` }} />
                      </div>
                    </div>
                  )}

                  {/* Daily Loss */}
                  {pf.daily_loss_limit > 0 && (
                    <div>
                      <div className="flex justify-between text-[10px] mb-1">
                        <span className="text-muted-foreground">Daily Loss</span>
                        <span className={pf.daily_loss_pct > 80 ? "text-danger" : pf.daily_loss_pct > 50 ? "text-yellow-400" : "text-muted-foreground"}>
                          ${fmt(pf.daily_loss_used)} / ${fmt(pf.daily_loss_limit)} ({pf.daily_loss_pct}%)
                        </span>
                      </div>
                      <div className="h-1.5 rounded-full bg-card-border overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${pf.daily_loss_pct > 80 ? "bg-danger" : pf.daily_loss_pct > 50 ? "bg-yellow-500" : "bg-accent/60"}`}
                          style={{ width: `${Math.min(pf.daily_loss_pct, 100)}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {/* Max Drawdown */}
                  {pf.drawdown_limit > 0 && (
                    <div>
                      <div className="flex justify-between text-[10px] mb-1">
                        <span className="text-muted-foreground">Max Drawdown</span>
                        <span className={pf.drawdown_pct > 80 ? "text-danger" : pf.drawdown_pct > 50 ? "text-yellow-400" : "text-muted-foreground"}>
                          ${fmt(pf.drawdown_used)} / ${fmt(pf.drawdown_limit)} ({pf.drawdown_pct}%)
                        </span>
                      </div>
                      <div className="h-1.5 rounded-full bg-card-border overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${pf.drawdown_pct > 80 ? "bg-danger" : pf.drawdown_pct > 50 ? "bg-yellow-500" : "bg-accent/60"}`}
                          style={{ width: `${Math.min(pf.drawdown_pct, 100)}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {/* Alert badge */}
                  {(pf.daily_loss_pct > 80 || pf.drawdown_pct > 80) && (
                    <div className="flex items-center gap-1.5 text-[10px] text-danger">
                      <AlertTriangle className="h-3 w-3" />
                      Approaching {pf.daily_loss_pct > 80 ? "daily loss" : "drawdown"} limit
                    </div>
                  )}

                  {/* Footer stats */}
                  <div className="flex items-center gap-3 text-[10px] text-muted-foreground pt-1 border-t border-card-border">
                    <span>{pf.open_trades} open trades</span>
                    {pf.days_left !== null && <span>{pf.days_left} days left</span>}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

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

function MiniEquityChart({ points }: { points: { date: string; pnl: number }[] }) {
  if (points.length < 2) return null;
  const W = 800;
  const H = 120;
  const PAD = 4;
  const vals = points.map((p) => p.pnl);
  const minV = Math.min(0, ...vals);
  const maxV = Math.max(0, ...vals);
  const range = maxV - minV || 1;

  const toX = (i: number) => PAD + (i / (points.length - 1)) * (W - PAD * 2);
  const toY = (v: number) => H - PAD - ((v - minV) / range) * (H - PAD * 2);

  const pathD = points.map((p, i) => `${i === 0 ? "M" : "L"}${toX(i).toFixed(1)},${toY(p.pnl).toFixed(1)}`).join(" ");
  const lastPnl = points[points.length - 1].pnl;
  const color = lastPnl >= 0 ? "#22c55e" : "#ef4444";
  const zeroY = toY(0);

  // Area fill
  const areaD = `${pathD} L${toX(points.length - 1).toFixed(1)},${zeroY.toFixed(1)} L${toX(0).toFixed(1)},${zeroY.toFixed(1)} Z`;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-24" preserveAspectRatio="none">
      {/* Zero line */}
      <line x1={PAD} y1={zeroY} x2={W - PAD} y2={zeroY} stroke="currentColor" strokeOpacity={0.15} strokeDasharray="4 4" />
      {/* Area fill */}
      <path d={areaD} fill={color} fillOpacity={0.1} />
      {/* Line */}
      <path d={pathD} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" />
      {/* End dot */}
      <circle cx={toX(points.length - 1)} cy={toY(lastPnl)} r={3} fill={color} />
    </svg>
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
