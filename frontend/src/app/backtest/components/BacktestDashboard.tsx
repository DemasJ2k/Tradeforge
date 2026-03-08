'use client';

/**
 * BacktestDashboard — Full results dashboard with tab navigation.
 *
 * Tabs:
 *  1. Overview     — Stats cards + equity curve
 *  2. Trades       — Full trade log table
 *  3. Charts       — Equity + trade markers, P/L waterfall
 *  4. Monthly      — Monthly/yearly returns heatmap
 *  5. Analysis     — Extended tearsheet metrics + Monte Carlo
 *  6. Walk-Forward — Out-of-sample validation
 */

import type { BacktestResponse } from '@/types';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { X, TrendingUp, TrendingDown, GitCompare } from 'lucide-react';
import StatsCards from './StatsCards';
import EquityCurveChart from './EquityCurveChart';
import TradeLogTable from './TradeLogTable';
import MonthlyHeatmap from './MonthlyHeatmap';
import TearsheetPanel from './TearsheetPanel';
import TradeChartOverlay from './TradeChartOverlay';
import WalkForwardPanel from './WalkForwardPanel';

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
          <TabsTrigger value="charts">Charts</TabsTrigger>
          <TabsTrigger value="monthly">Monthly</TabsTrigger>
          <TabsTrigger value="analysis">Analysis</TabsTrigger>
          <TabsTrigger value="walkforward">Walk-Forward</TabsTrigger>
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

        {/* Charts Tab */}
        <TabsContent value="charts" className="mt-4">
          <TradeChartOverlay trades={result.trades} equityCurve={result.equity_curve} />
        </TabsContent>

        {/* Monthly Tab */}
        <TabsContent value="monthly" className="mt-4">
          <MonthlyHeatmap
            monthlyReturns={(v2.monthly_returns as Record<string, number>) || (result.tearsheet as Record<string, unknown>)?.monthly_returns as Record<string, number> || {}}
          />
        </TabsContent>

        {/* Analysis Tab */}
        <TabsContent value="analysis" className="mt-4">
          <TearsheetPanel
            stats={stats}
            v2Stats={v2}
            trades={result.trades}
            equityCurve={result.equity_curve}
            backtestId={result.id}
          />
        </TabsContent>

        {/* Walk-Forward Tab */}
        <TabsContent value="walkforward" className="mt-4">
          <WalkForwardPanel
            strategyId={result.strategy_id}
            datasourceId={result.datasource_id}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}

