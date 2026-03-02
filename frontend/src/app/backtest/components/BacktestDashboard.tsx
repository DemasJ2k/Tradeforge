'use client';

/**
 * BacktestDashboard — Full results dashboard with tab navigation.
 *
 * Tabs:
 *  1. Overview  — Stats cards + equity curve
 *  2. Trades    — Full trade log table
 *  3. Monthly   — Monthly/yearly returns heatmap
 *  4. Analysis  — Extended tearsheet metrics
 */

import type { BacktestResponse } from '@/types';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { X, TrendingUp, TrendingDown, GitCompare } from 'lucide-react';
import StatsCards from './StatsCards';
import EquityCurveChart from './EquityCurveChart';
import TradeLogTable from './TradeLogTable';
import MonthlyHeatmap from './MonthlyHeatmap';

interface Props {
  result: BacktestResponse;
  compareResult?: BacktestResponse | null;
  onClearCompare?: () => void;
}

export default function BacktestDashboard({ result, compareResult, onClearCompare }: Props) {
  const stats = result.stats;
  const v2 = (result.v2_stats || {}) as Record<string, unknown>;

  return (
    <div className="p-4 space-y-4">
      {/* Compare banner */}
      {compareResult && (
        <div className="flex items-center gap-2 p-2 rounded-lg bg-accent/10 border border-accent/20">
          <GitCompare className="w-4 h-4 text-accent" />
          <span className="text-sm">Comparing with run #{compareResult.id}</span>
          <Button variant="ghost" size="sm" onClick={onClearCompare} className="ml-auto h-6 w-6 p-0">
            <X className="w-3 h-3" />
          </Button>
        </div>
      )}

      {/* Quick Summary Banner */}
      <div className="flex items-center gap-4 flex-wrap">
        <Badge variant={stats.net_profit >= 0 ? 'default' : 'destructive'} className="text-sm px-3 py-1">
          {stats.net_profit >= 0 ? <TrendingUp className="w-3.5 h-3.5 mr-1" /> : <TrendingDown className="w-3.5 h-3.5 mr-1" />}
          Net P/L: ${stats.net_profit?.toFixed(2)}
        </Badge>
        <span className="text-sm text-muted-foreground">
          {stats.total_trades} trades • {stats.win_rate?.toFixed(1)}% WR • PF {stats.profit_factor?.toFixed(2)} • DD {stats.max_drawdown_pct?.toFixed(1)}%
        </span>
        {result.elapsed_seconds != null && (
          <span className="text-xs text-muted-foreground/50 ml-auto">
            {result.elapsed_seconds.toFixed(2)}s
          </span>
        )}
      </div>

      {/* Tabbed Dashboard */}
      <Tabs defaultValue="overview" className="w-full">
        <TabsList className="bg-card-bg border border-card-border">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="trades">Trades</TabsTrigger>
          <TabsTrigger value="monthly">Monthly</TabsTrigger>
          <TabsTrigger value="analysis">Analysis</TabsTrigger>
        </TabsList>

        {/* Overview Tab */}
        <TabsContent value="overview" className="space-y-4 mt-4">
          <StatsCards stats={stats} v2Stats={v2} compareStats={compareResult?.stats} />
          <EquityCurveChart
            data={result.equity_curve}
            compareData={compareResult?.equity_curve}
          />
        </TabsContent>

        {/* Trades Tab */}
        <TabsContent value="trades" className="mt-4">
          <TradeLogTable trades={result.trades} />
        </TabsContent>

        {/* Monthly Tab */}
        <TabsContent value="monthly" className="mt-4">
          <MonthlyHeatmap
            monthlyReturns={(v2.monthly_returns as Record<string, number>) || (result.tearsheet as Record<string, unknown>)?.monthly_returns as Record<string, number> || {}}
          />
        </TabsContent>

        {/* Analysis Tab */}
        <TabsContent value="analysis" className="mt-4">
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            <MetricCard label="Sharpe Ratio" value={stats.sharpe_ratio?.toFixed(4)} />
            <MetricCard label="Sortino Ratio" value={(v2.sortino_ratio as number)?.toFixed(4) || '—'} />
            <MetricCard label="Calmar Ratio" value={(v2.calmar_ratio as number)?.toFixed(4) || '—'} />
            <MetricCard label="SQN" value={stats.sqn?.toFixed(2)} />
            <MetricCard label="Recovery Factor" value={(v2.recovery_factor as number)?.toFixed(2) || '—'} />
            <MetricCard label="Payoff Ratio" value={(v2.payoff_ratio as number)?.toFixed(2) || '—'} />
            <MetricCard label="Max Consec Wins" value={String((v2.max_consecutive_wins as number) ?? '—')} />
            <MetricCard label="Max Consec Losses" value={String((v2.max_consecutive_losses as number) ?? '—')} />
            <MetricCard label="Avg Bars Held" value={(v2.avg_bars_held as number)?.toFixed(1) || '—'} />
            <MetricCard label="Expectancy" value={`$${stats.expectancy?.toFixed(2)}`} />
            <MetricCard label="Initial Balance" value={`$${(v2.initial_balance as number)?.toLocaleString() || '—'}`} />
            <MetricCard label="Final Balance" value={`$${(v2.final_balance as number)?.toLocaleString() || '—'}`} />
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value?: string }) {
  return (
    <Card className="bg-card-bg border-card-border">
      <CardContent className="p-3">
        <div className="text-xs text-muted-foreground uppercase tracking-wider mb-1">{label}</div>
        <div className="text-base font-bold font-mono">{value || '—'}</div>
      </CardContent>
    </Card>
  );
}
