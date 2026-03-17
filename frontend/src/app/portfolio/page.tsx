"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  PieChart, TrendingUp, TrendingDown, Shield, AlertTriangle,
  Pause, Play, Bot, Activity, DollarSign, BarChart3,
  ChevronDown, ChevronUp,
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

/* ─── Component ─────────────────────────────────────────── */
export default function PortfolioPage() {
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [equityCurve, setEquityCurve] = useState<EquityPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedAgent, setExpandedAgent] = useState<number | null>(null);

  const loadData = useCallback(async () => {
    try {
      const [sumData, eqData] = await Promise.all([
        api.get<PortfolioSummary>("/api/portfolio/summary"),
        api.get<{ snapshots: EquityPoint[] }>("/api/portfolio/equity-curve?days=30"),
      ]);
      setSummary(sumData);
      setEquityCurve(eqData.snapshots || []);
    } catch {
      // Portfolio not created yet — show empty state
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

  const handlePauseAll = async () => {
    try {
      await api.post("/api/portfolio/pause-all", {});
      loadData();
    } catch { /* */ }
  };

  const handleUnpause = async () => {
    try {
      await api.post("/api/portfolio/unpause", {});
      loadData();
    } catch { /* */ }
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

  return (
    <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-4 sm:space-y-6 pb-20 md:pb-6">
      {/* ── Portfolio Health Bar ── */}
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
          {isPaused ? (
            <Button size="sm" variant="outline" onClick={handleUnpause} className="gap-1.5">
              <Play className="h-3.5 w-3.5" /> Resume
            </Button>
          ) : (
            <Button size="sm" variant="destructive" onClick={handlePauseAll} className="gap-1.5">
              <Pause className="h-3.5 w-3.5" /> Pause All
            </Button>
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

      {/* ── Circuit Breaker Status ── */}
      {isPaused && (
        <Card className="bg-red-500/10 border-red-500/30">
          <CardContent className="p-4 flex items-center gap-3">
            <AlertTriangle className="h-5 w-5 text-red-400 shrink-0" />
            <div>
              <div className="text-sm font-medium text-red-400">Circuit Breaker Active</div>
              <div className="text-xs text-red-400/70">
                All agents paused. {s?.status === "breached" ? "Drawdown limit breached." : "Manually paused."}
                Click Resume when ready.
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Agent Performance Cards ── */}
      <div>
        <h2 className="text-base font-semibold text-foreground mb-3 flex items-center gap-2">
          <Bot className="h-4 w-4 text-accent" /> Active Agents
          <Badge className="bg-fa-card border-fa-card-border text-muted-foreground text-[10px]">
            {s?.open_positions ?? 0}/{s?.max_concurrent_positions ?? 6} positions
          </Badge>
        </h2>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {(s?.agents_detail || []).map((agent) => {
            const liveData = s?.agents?.[String(agent.id)];
            const isExpanded = expandedAgent === agent.id;
            const stats = agent.performance_stats || {};
            const totalPnl = liveData?.total_pnl ?? stats.total_pnl ?? 0;
            const dailyPnl = liveData?.daily_pnl ?? 0;
            const winRate = stats.win_rate ?? 0;
            const totalTrades = stats.total_trades ?? 0;

            return (
              <Card key={agent.id} className="bg-fa-card border-fa-card-border overflow-hidden">
                <CardContent className="p-0">
                  <button
                    onClick={() => setExpandedAgent(isExpanded ? null : agent.id)}
                    className="w-full p-3 sm:p-4 text-left hover:bg-fa-sidebar-hover/50 transition-colors"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <div className={`h-2 w-2 rounded-full ${
                          agent.status === "running" ? "bg-emerald-500 animate-pulse" :
                          agent.status === "paused" ? "bg-yellow-500" : "bg-zinc-600"
                        }`} />
                        <span className="text-sm font-medium text-foreground">{agent.name}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge className="bg-accent/10 text-accent border-0 text-[10px]">
                          {agent.symbol} {agent.timeframe}
                        </Badge>
                        {isExpanded ? <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" /> :
                                      <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />}
                      </div>
                    </div>

                    <div className="grid grid-cols-3 gap-2 text-xs">
                      <div>
                        <div className="text-muted-foreground">Daily</div>
                        <div className={`font-medium ${dailyPnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                          {dailyPnl >= 0 ? "+" : ""}${dailyPnl.toFixed(2)}
                        </div>
                      </div>
                      <div>
                        <div className="text-muted-foreground">Total</div>
                        <div className={`font-medium ${totalPnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                          {totalPnl >= 0 ? "+" : ""}${totalPnl.toFixed(2)}
                        </div>
                      </div>
                      <div>
                        <div className="text-muted-foreground">Win Rate</div>
                        <div className="font-medium text-foreground">
                          {winRate > 0 ? `${winRate.toFixed(1)}%` : "—"}
                        </div>
                      </div>
                    </div>

                    {liveData?.direction && (
                      <div className="mt-2 flex items-center gap-1.5">
                        {liveData.direction === "long" ? (
                          <TrendingUp className="h-3 w-3 text-emerald-400" />
                        ) : (
                          <TrendingDown className="h-3 w-3 text-red-400" />
                        )}
                        <span className={`text-xs font-medium ${
                          liveData.direction === "long" ? "text-emerald-400" : "text-red-400"
                        }`}>
                          {liveData.direction.toUpperCase()} open
                        </span>
                      </div>
                    )}
                  </button>

                  {/* Expanded details */}
                  {isExpanded && (
                    <div className="border-t border-fa-card-border p-3 sm:p-4 bg-fa-bg/50 space-y-2">
                      <div className="grid grid-cols-2 gap-2 text-xs">
                        <div>
                          <span className="text-muted-foreground">Mode:</span>{" "}
                          <span className="text-foreground capitalize">{agent.mode}</span>
                        </div>
                        <div>
                          <span className="text-muted-foreground">Status:</span>{" "}
                          <span className="text-foreground capitalize">{agent.status}</span>
                        </div>
                        <div>
                          <span className="text-muted-foreground">Trades Today:</span>{" "}
                          <span className="text-foreground">{liveData?.trades_today ?? 0}</span>
                        </div>
                        <div>
                          <span className="text-muted-foreground">Total Trades:</span>{" "}
                          <span className="text-foreground">{totalTrades}</span>
                        </div>
                      </div>
                      {stats.max_drawdown !== undefined && (
                        <div className="text-xs">
                          <span className="text-muted-foreground">Max Drawdown:</span>{" "}
                          <span className="text-foreground">{(stats.max_drawdown ?? 0).toFixed(2)}%</span>
                        </div>
                      )}
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })}

          {(!s?.agents_detail || s.agents_detail.length === 0) && (
            <Card className="bg-fa-card border-fa-card-border col-span-full">
              <CardContent className="p-8 text-center">
                <Bot className="h-10 w-10 text-muted-foreground mx-auto mb-3 opacity-50" />
                <div className="text-sm text-muted-foreground">No agents deployed yet</div>
                <div className="text-xs text-muted-foreground mt-1">
                  Go to Strategies to deploy agents with validated strategies
                </div>
              </CardContent>
            </Card>
          )}
        </div>
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
                const maxEq = Math.max(...equityCurve.map(p => p.equity), 1);
                const minEq = Math.min(...equityCurve.map(p => p.equity), 0);
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
                    {s?.agents_detail?.filter(a => a.status === "running").length ?? 0} running
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
