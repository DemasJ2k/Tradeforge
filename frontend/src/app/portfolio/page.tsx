"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";
import {
  TrendingDown, Shield, AlertTriangle,
  Pause, Play, Square, Bot, Activity, DollarSign, BarChart3,
  ChevronDown, ChevronUp, Loader2,
} from "lucide-react";

/* ─── Types ─────────────────────────────────────────────── */
interface PortfolioSummary {
  portfolio_id: number;
  mode: string;
  status: string;
  current_equity: number;
  peak_equity: number;
  daily_pnl: number;
  total_pnl: number;
  drawdown_pct: number;
  daily_loss_pct: number;
  max_daily_loss_pct: number;
  max_total_drawdown_pct: number;
  open_positions: number;
  max_concurrent_positions: number;
  agents: Record<string, {
    symbol: string;
    direction: string | null;
    daily_pnl: number;
    total_pnl: number;
    trades_today: number;
  }>;
  agents_detail: {
    id: number;
    name: string;
    symbol: string;
    timeframe: string;
    status: string;
    mode: string;
    strategy_id: number;
    performance_stats: Record<string, number>;
    portfolio_id: number | null;
  }[];
}

interface EquityPoint {
  timestamp: string;
  equity: number;
  pnl: number;
  daily_pnl: number;
  drawdown_pct: number;
}

interface BrokerAgent {
  id: number;
  name: string;
  symbol: string;
  timeframe: string;
  status: string;
  mode: string;
  total_pnl: number;
  win_rate: number;
  total_trades: number;
  daily_pnl: number;
}

interface BrokerPortfolio {
  broker: string;
  currency: string;
  balance: number;
  equity: number;
  balance_usd: number;
  equity_usd: number;
  daily_pnl: number;
  drawdown_pct: number;
  agents: BrokerAgent[];
}

interface BrokerPortfoliosResponse {
  brokers: BrokerPortfolio[];
  combined: {
    total_balance_usd: number;
    total_equity_usd: number;
    total_daily_pnl: number;
  };
}

/* ─── Component ─────────────────────────────────────────── */
export default function PortfolioPage() {
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [brokerData, setBrokerData] = useState<BrokerPortfoliosResponse | null>(null);
  const [equityCurve, setEquityCurve] = useState<EquityPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedBrokers, setExpandedBrokers] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState(false);

  const loadData = useCallback(async () => {
    try {
      setError(null);
      const [sumData, brokerRes, eqData] = await Promise.all([
        api.get<PortfolioSummary>("/api/portfolio/summary"),
        api.get<BrokerPortfoliosResponse>("/api/portfolio/broker-portfolios"),
        api.get<{ snapshots: EquityPoint[] }>("/api/portfolio/equity-curve?days=30"),
      ]);
      setSummary(sumData);
      setBrokerData(brokerRes);
      setEquityCurve(eqData.snapshots || []);
      // Auto-expand all brokers on first load
      if (brokerRes.brokers.length > 0) {
        setExpandedBrokers((prev) =>
          prev.size === 0
            ? new Set(brokerRes.brokers.map((b) => b.broker))
            : prev
        );
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load portfolio";
      if (!msg.includes("401") && !msg.includes("Unauthorized")) {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  // Auto-refresh every 30s
  useEffect(() => {
    const interval = setInterval(loadData, 30000);
    return () => clearInterval(interval);
  }, [loadData]);

  /* ─── Global Actions ─── */
  const handlePauseAll = async () => {
    setActing(true);
    try {
      await api.post("/api/portfolio/pause-all", {});
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to pause agents");
    } finally {
      setActing(false);
    }
  };

  const handleUnpause = async () => {
    setActing(true);
    try {
      await api.post("/api/portfolio/unpause", {});
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to resume portfolio");
    } finally {
      setActing(false);
    }
  };

  /* ─── Per-Agent Actions ─── */
  const handleAgentAction = async (agentId: number, action: "start" | "pause" | "stop") => {
    try {
      const endpoint =
        action === "start" ? `/api/agents/${agentId}/start` :
        action === "pause" ? `/api/agents/${agentId}/pause` :
        `/api/agents/${agentId}/stop`;
      await api.post(endpoint, {});
      loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to ${action} agent`);
    }
  };

  /* ─── Broker section toggle ─── */
  const toggleBroker = (broker: string) => {
    setExpandedBrokers((prev) => {
      const next = new Set(prev);
      if (next.has(broker)) next.delete(broker);
      else next.add(broker);
      return next;
    });
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="animate-spin h-8 w-8 border-2 border-accent border-t-transparent rounded-full" />
      </div>
    );
  }

  const s = summary;
  const ddUsed = s?.drawdown_pct ?? 0;
  const ddMax = s?.max_total_drawdown_pct ?? 10;
  const dailyUsed = s?.daily_loss_pct ?? 0;
  const dailyMax = s?.max_daily_loss_pct ?? 5;
  const isPaused = s?.status === "paused" || s?.status === "breached";
  const hasRunningAgents = brokerData?.brokers.some((b) =>
    b.agents.some((a) => a.status === "running")
  ) ?? false;
  const hasAnyAgents = (s?.agents_detail?.length ?? 0) > 0 ||
    (brokerData?.brokers.some((b) => b.agents.length > 0) ?? false);

  return (
    <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-4 sm:space-y-6 pb-20 md:pb-6">
      {/* ── Portfolio Header ── */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-foreground">Portfolio</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Multi-agent portfolio management & risk monitoring
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge className={`${
            s?.mode === "aggressive" ? "bg-red-500/15 text-red-400" :
            s?.mode === "conservative" ? "bg-blue-500/15 text-blue-400" :
            "bg-emerald-500/15 text-emerald-400"
          } border-0 text-xs`}>
            {s?.mode || "balanced"}
          </Badge>
          {hasAnyAgents && (
            isPaused ? (
              <Button size="sm" variant="outline" onClick={handleUnpause} disabled={acting} className="gap-1.5">
                {acting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />} Play All
              </Button>
            ) : hasRunningAgents ? (
              <Button size="sm" variant="destructive" onClick={handlePauseAll} disabled={acting} className="gap-1.5">
                {acting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Pause className="h-3.5 w-3.5" />} Pause All
              </Button>
            ) : (
              <Button size="sm" variant="outline" onClick={handleUnpause} disabled={acting} className="gap-1.5">
                {acting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />} Play All
              </Button>
            )
          )}
        </div>
      </div>

      {/* ── Key Metrics Strip ── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Card className="bg-fa-card border-fa-card-border">
          <CardContent className="p-3 sm:p-4">
            <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
              <DollarSign className="h-3.5 w-3.5" /> Equity
            </div>
            <div className="text-lg sm:text-xl font-bold text-foreground">
              ${(s?.current_equity ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </div>
          </CardContent>
        </Card>

        <Card className="bg-fa-card border-fa-card-border">
          <CardContent className="p-3 sm:p-4">
            <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
              <Activity className="h-3.5 w-3.5" /> Daily P&L
            </div>
            <div className={`text-lg sm:text-xl font-bold ${
              (s?.daily_pnl ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"
            }`}>
              {(s?.daily_pnl ?? 0) >= 0 ? "+" : ""}${(s?.daily_pnl ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </div>
          </CardContent>
        </Card>

        <Card className="bg-fa-card border-fa-card-border">
          <CardContent className="p-3 sm:p-4">
            <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
              <TrendingDown className="h-3.5 w-3.5" /> Drawdown
            </div>
            <div className="text-lg sm:text-xl font-bold text-foreground">
              {ddUsed.toFixed(1)}%
            </div>
            <div className="mt-1.5 h-1.5 bg-fa-card-border rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${
                  ddUsed > ddMax * 0.8 ? "bg-red-500" :
                  ddUsed > ddMax * 0.5 ? "bg-yellow-500" : "bg-emerald-500"
                }`}
                style={{ width: `${Math.min((ddUsed / ddMax) * 100, 100)}%` }}
              />
            </div>
            <div className="text-[10px] text-muted-foreground mt-0.5">
              Limit: {ddMax}%
            </div>
          </CardContent>
        </Card>

        <Card className="bg-fa-card border-fa-card-border">
          <CardContent className="p-3 sm:p-4">
            <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
              <Shield className="h-3.5 w-3.5" /> Daily Loss
            </div>
            <div className="text-lg sm:text-xl font-bold text-foreground">
              {dailyUsed.toFixed(1)}%
            </div>
            <div className="mt-1.5 h-1.5 bg-fa-card-border rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${
                  dailyUsed > dailyMax * 0.8 ? "bg-red-500" :
                  dailyUsed > dailyMax * 0.5 ? "bg-yellow-500" : "bg-emerald-500"
                }`}
                style={{ width: `${Math.min((dailyUsed / dailyMax) * 100, 100)}%` }}
              />
            </div>
            <div className="text-[10px] text-muted-foreground mt-0.5">
              Limit: {dailyMax}%
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ── Error Banner ── */}
      {error && (
        <Card className="bg-red-500/10 border-red-500/30">
          <CardContent className="p-3 flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm text-red-400">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              {error}
            </div>
            <Button size="sm" variant="outline" onClick={loadData} className="text-xs">
              Retry
            </Button>
          </CardContent>
        </Card>
      )}

      {/* ── Circuit Breaker Status ── */}
      {isPaused && (
        <Card className="bg-red-500/10 border-red-500/30">
          <CardContent className="p-4 flex items-center gap-3">
            <AlertTriangle className="h-5 w-5 text-red-400 shrink-0" />
            <div>
              <div className="text-sm font-medium text-red-400">Circuit Breaker Active</div>
              <div className="text-xs text-red-400/70">
                All agents paused. {s?.status === "breached" ? "Drawdown limit breached." : "Manually paused."}
                {" "}Click Resume All when ready.
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Broker-Separated Sections ── */}
      <div className="space-y-4">
        <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
          <Bot className="h-4 w-4 text-accent" /> Broker Portfolios
        </h2>

        {brokerData && brokerData.brokers.length > 0 ? (
          brokerData.brokers.map((broker) => {
            const isOpen = expandedBrokers.has(broker.broker);
            return (
              <Collapsible
                key={broker.broker}
                open={isOpen}
                onOpenChange={() => toggleBroker(broker.broker)}
              >
                <Card className="bg-fa-card border-fa-card-border overflow-hidden">
                  <CollapsibleTrigger className="w-full">
                    <div className="flex items-center justify-between p-4 hover:bg-fa-sidebar-hover/50 transition-colors cursor-pointer">
                      <div className="flex items-center gap-3">
                        <div className="h-9 w-9 rounded-lg bg-accent/10 flex items-center justify-center">
                          <DollarSign className="h-4.5 w-4.5 text-accent" />
                        </div>
                        <div className="text-left">
                          <div className="text-sm font-semibold text-foreground">
                            {broker.broker.charAt(0).toUpperCase() + broker.broker.slice(1)}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {broker.agents.length} agent{broker.agents.length !== 1 ? "s" : ""}
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-4">
                        <div className="text-right hidden sm:block">
                          <div className="text-sm font-semibold text-foreground">
                            {broker.currency} {broker.balance.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            USD ${broker.balance_usd.toLocaleString(undefined, { minimumFractionDigits: 0 })}
                          </div>
                        </div>
                        <div className="text-right sm:hidden">
                          <div className="text-sm font-semibold text-foreground">
                            ${broker.balance_usd.toLocaleString(undefined, { minimumFractionDigits: 0 })}
                          </div>
                        </div>
                        <div className={`text-right ${broker.daily_pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                          <div className="text-xs font-medium">
                            {broker.daily_pnl >= 0 ? "+" : ""}${broker.daily_pnl.toFixed(2)}
                          </div>
                          <div className="text-[10px] text-muted-foreground">daily</div>
                        </div>
                        {isOpen
                          ? <ChevronUp className="h-4 w-4 text-muted-foreground" />
                          : <ChevronDown className="h-4 w-4 text-muted-foreground" />
                        }
                      </div>
                    </div>
                  </CollapsibleTrigger>

                  <CollapsibleContent>
                    <div className="border-t border-fa-card-border p-3 sm:p-4">
                      {broker.agents.length > 0 ? (
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          {broker.agents.map((agent) => (
                            <AgentCard
                              key={agent.id}
                              agent={agent}
                              onAction={handleAgentAction}
                            />
                          ))}
                        </div>
                      ) : (
                        <div className="text-center py-6">
                          <Bot className="h-8 w-8 text-muted-foreground mx-auto mb-2 opacity-50" />
                          <div className="text-sm text-muted-foreground">No agents on this broker</div>
                        </div>
                      )}
                    </div>
                  </CollapsibleContent>
                </Card>
              </Collapsible>
            );
          })
        ) : (
          <Card className="bg-fa-card border-fa-card-border">
            <CardContent className="p-8 text-center">
              <Bot className="h-10 w-10 text-muted-foreground mx-auto mb-3 opacity-50" />
              <div className="text-sm text-muted-foreground">No agents deployed yet</div>
              <div className="text-xs text-muted-foreground mt-1">
                Go to Trading to deploy ML-powered agents
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      {/* ── Equity Curve ── */}
      <Card className="bg-fa-card border-fa-card-border">
        <CardContent className="p-4">
          <h3 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-accent" /> Portfolio Equity Curve
          </h3>
          {equityCurve.length > 0 ? (
            <div className="h-48 sm:h-64 lg:h-80 flex items-end gap-[1px]">
              {(() => {
                const eqValues = equityCurve.map(p => p.equity);
                const maxEq = Math.max(...eqValues, 1);
                const minEq = Math.min(...eqValues);
                const range = maxEq - minEq || 1;
                return equityCurve.map((p, i) => (
                  <div
                    key={i}
                    className={`flex-1 rounded-t-sm min-w-[2px] ${
                      p.pnl >= 0 ? "bg-emerald-500/70" : "bg-red-500/70"
                    }`}
                    style={{ height: `${Math.max(((p.equity - minEq) / range) * 100, 2)}%` }}
                    title={`${new Date(p.timestamp).toLocaleDateString()} — $${p.equity.toFixed(2)}`}
                  />
                ));
              })()}
            </div>
          ) : (
            <div className="h-48 sm:h-64 lg:h-80 flex items-center justify-center">
              <div className="text-sm text-muted-foreground">
                Equity data will appear once agents start trading
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Risk Dashboard ── */}
      <Card className="bg-fa-card border-fa-card-border">
        <CardContent className="p-4">
          <h3 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
            <Shield className="h-4 w-4 text-accent" /> Risk Dashboard
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {/* Drawdown Meter */}
            <div className="text-center">
              <div className="text-xs text-muted-foreground mb-2">Total Drawdown</div>
              <div className="relative w-24 h-24 mx-auto">
                <svg className="w-full h-full -rotate-90" viewBox="0 0 36 36">
                  <path d="M18 2.5a15.5 15.5 0 1 1 0 31 15.5 15.5 0 0 1 0-31"
                    fill="none" stroke="currentColor" strokeWidth="3"
                    className="text-fa-card-border" />
                  <path d="M18 2.5a15.5 15.5 0 1 1 0 31 15.5 15.5 0 0 1 0-31"
                    fill="none" strokeWidth="3" strokeDasharray={`${(ddUsed / ddMax) * 97.4} 97.4`}
                    strokeLinecap="round"
                    className={ddUsed > ddMax * 0.8 ? "stroke-red-500" :
                              ddUsed > ddMax * 0.5 ? "stroke-yellow-500" : "stroke-emerald-500"} />
                </svg>
                <div className="absolute inset-0 flex items-center justify-center">
                  <span className="text-sm font-bold text-foreground">{ddUsed.toFixed(1)}%</span>
                </div>
              </div>
              <div className="text-[10px] text-muted-foreground mt-1">of {ddMax}% limit</div>
            </div>

            {/* Daily Loss Meter */}
            <div className="text-center">
              <div className="text-xs text-muted-foreground mb-2">Daily Loss</div>
              <div className="relative w-24 h-24 mx-auto">
                <svg className="w-full h-full -rotate-90" viewBox="0 0 36 36">
                  <path d="M18 2.5a15.5 15.5 0 1 1 0 31 15.5 15.5 0 0 1 0-31"
                    fill="none" stroke="currentColor" strokeWidth="3"
                    className="text-fa-card-border" />
                  <path d="M18 2.5a15.5 15.5 0 1 1 0 31 15.5 15.5 0 0 1 0-31"
                    fill="none" strokeWidth="3" strokeDasharray={`${(dailyUsed / dailyMax) * 97.4} 97.4`}
                    strokeLinecap="round"
                    className={dailyUsed > dailyMax * 0.8 ? "stroke-red-500" :
                              dailyUsed > dailyMax * 0.5 ? "stroke-yellow-500" : "stroke-emerald-500"} />
                </svg>
                <div className="absolute inset-0 flex items-center justify-center">
                  <span className="text-sm font-bold text-foreground">{dailyUsed.toFixed(1)}%</span>
                </div>
              </div>
              <div className="text-[10px] text-muted-foreground mt-1">of {dailyMax}% limit</div>
            </div>

            {/* Position Summary */}
            <div>
              <div className="text-xs text-muted-foreground mb-2 text-center">Positions</div>
              <div className="space-y-2">
                <div className="flex justify-between text-xs">
                  <span className="text-muted-foreground">Open</span>
                  <span className="text-foreground font-medium">
                    {s?.open_positions ?? 0} / {s?.max_concurrent_positions ?? 6}
                  </span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-muted-foreground">Agents</span>
                  <span className="text-foreground font-medium">
                    {brokerData?.brokers.reduce((sum, b) =>
                      sum + b.agents.filter(a => a.status === "running").length, 0) ?? 0} running
                  </span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-muted-foreground">Total P&L</span>
                  <span className={`font-medium ${(s?.total_pnl ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {(s?.total_pnl ?? 0) >= 0 ? "+" : ""}${(s?.total_pnl ?? 0).toFixed(2)}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/* ─── Agent Card Sub-Component ─────────────────────────── */
function AgentCard({
  agent,
  onAction,
}: {
  agent: BrokerAgent;
  onAction: (id: number, action: "start" | "pause" | "stop") => void;
}) {
  const statusColor =
    agent.status === "running" ? "bg-emerald-500" :
    agent.status === "paused"  ? "bg-yellow-500"  : "bg-zinc-600";
  const statusPulse = agent.status === "running" ? "animate-pulse" : "";

  return (
    <Card className="bg-fa-bg/60 border-fa-card-border">
      <CardContent className="p-3 sm:p-4">
        {/* Top row: status dot, name, badge */}
        <div className="flex items-center justify-between mb-2.5">
          <div className="flex items-center gap-2 min-w-0">
            <div className={`h-2 w-2 rounded-full shrink-0 ${statusColor} ${statusPulse}`} />
            <span className="text-sm font-medium text-foreground truncate">{agent.name}</span>
          </div>
          <Badge className="bg-accent/10 text-accent border-0 text-[10px] shrink-0 ml-2">
            {agent.symbol} {agent.timeframe}
          </Badge>
        </div>

        {/* Stats grid */}
        <div className="grid grid-cols-4 gap-2 text-xs mb-3">
          <div>
            <div className="text-muted-foreground">Daily</div>
            <div className={`font-medium ${(agent.daily_pnl ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
              {(agent.daily_pnl ?? 0) >= 0 ? "+" : ""}${(agent.daily_pnl ?? 0).toFixed(2)}
            </div>
          </div>
          <div>
            <div className="text-muted-foreground">Total</div>
            <div className={`font-medium ${(agent.total_pnl ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
              {(agent.total_pnl ?? 0) >= 0 ? "+" : ""}${(agent.total_pnl ?? 0).toFixed(2)}
            </div>
          </div>
          <div>
            <div className="text-muted-foreground">Win Rate</div>
            <div className="font-medium text-foreground">
              {(agent.win_rate ?? 0) > 0 ? `${agent.win_rate.toFixed(1)}%` : "\u2014"}
            </div>
          </div>
          <div>
            <div className="text-muted-foreground">Trades</div>
            <div className="font-medium text-foreground">{agent.total_trades ?? 0}</div>
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex items-center justify-between">
          <Badge className={`border-0 text-[10px] capitalize ${
            agent.status === "running" ? "bg-emerald-500/15 text-emerald-400" :
            agent.status === "paused"  ? "bg-yellow-500/15 text-yellow-400"  :
            "bg-zinc-500/15 text-zinc-400"
          }`}>
            {agent.status}
          </Badge>
          <div className="flex items-center gap-1">
            {agent.status === "running" ? (
              <Button
                size="sm"
                variant="outline"
                className="h-7 px-2 text-xs gap-1 text-yellow-400 border-yellow-500/30 hover:bg-yellow-500/10"
                onClick={() => onAction(agent.id, "pause")}
              >
                <Pause className="h-3 w-3" /> Pause
              </Button>
            ) : (
              <Button
                size="sm"
                variant="outline"
                className="h-7 px-2 text-xs gap-1 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/10"
                onClick={() => onAction(agent.id, "start")}
              >
                <Play className="h-3 w-3" /> Play
              </Button>
            )}
            {agent.status !== "stopped" && (
              <Button
                size="sm"
                variant="outline"
                className="h-7 px-2 text-xs gap-1 text-red-400 border-red-500/30 hover:bg-red-500/10"
                onClick={() => onAction(agent.id, "stop")}
              >
                <Square className="h-3 w-3" /> Stop
              </Button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
