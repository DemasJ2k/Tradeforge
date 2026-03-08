'use client';

/**
 * WalkForwardPanel — Run walk-forward validation from a completed backtest.
 * Shows OOS (out-of-sample) aggregate metrics + per-fold breakdown table.
 */

import { useState, useCallback, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { api } from '@/lib/api';
import { Play, Database } from 'lucide-react';

interface DataSourceOption {
  id: number;
  filename: string;
  symbol: string;
  timeframe: string;
  row_count: number;
}

interface WFWindowStats {
  fold: number;
  train_bars: number;
  test_bars: number;
  train_stats: Record<string, number>;
  test_stats: Record<string, number>;
}

interface WalkForwardResult {
  oos_total_trades: number;
  oos_win_rate: number;
  oos_net_profit: number;
  oos_profit_factor: number;
  oos_max_drawdown: number;
  oos_max_drawdown_pct: number;
  oos_sharpe_ratio: number;
  oos_expectancy: number;
  oos_avg_win: number;
  oos_avg_loss: number;
  windows: WFWindowStats[];
  fold_win_rates: number[];
  fold_profit_factors: number[];
  fold_net_profits: number[];
  consistency_score: number;
  oos_equity_curve: number[];
}

interface Props {
  strategyId: number;
  datasourceId: number;
}

export default function WalkForwardPanel({ strategyId, datasourceId }: Props) {
  const [result, setResult] = useState<WalkForwardResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Config
  const [nFolds, setNFolds] = useState(5);
  const [trainPct, setTrainPct] = useState(70);
  const [mode, setMode] = useState<'anchored' | 'rolling'>('anchored');

  // Datasource selector
  const [datasources, setDatasources] = useState<DataSourceOption[]>([]);
  const [selectedDsId, setSelectedDsId] = useState<number>(datasourceId);
  const [dsLoading, setDsLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await api.get<{ items: DataSourceOption[] }>('/api/data/sources');
        setDatasources(res.items || []);
        // If the backtest's datasource doesn't exist in the list, default to first available
        const ids = (res.items || []).map((d: DataSourceOption) => d.id);
        if (!ids.includes(datasourceId) && ids.length > 0) {
          setSelectedDsId(ids[0]);
        }
      } catch {
        // ignore — user just won't see options
      } finally {
        setDsLoading(false);
      }
    })();
  }, [datasourceId]);

  const runWalkForward = useCallback(async () => {
    if (!selectedDsId) {
      setError('Please select a data source');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const res = await api.post<WalkForwardResult>('/api/backtest/walk-forward', {
        strategy_id: strategyId,
        datasource_id: selectedDsId,
        n_folds: nFolds,
        train_pct: trainPct,
        mode,
        initial_balance: 10000,
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Walk-forward failed');
    } finally {
      setLoading(false);
    }
  }, [strategyId, selectedDsId, nFolds, trainPct, mode]);

  const fmt = (v: number, dp = 2) => v?.toFixed(dp) ?? '—';
  const usd = (v: number) => `$${v?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) ?? '—'}`;

  return (
    <div className="space-y-4">
      {/* Config + Run */}
      <Card className="bg-card-bg border-card-border">
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs text-muted-foreground uppercase tracking-wide font-semibold">
              Walk-Forward Validation
              {result && (
                <span className={`ml-2 inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium ${
                  result.consistency_score >= 70 ? 'bg-green-500/20 text-green-400'
                  : result.consistency_score >= 50 ? 'bg-yellow-500/20 text-yellow-400'
                  : 'bg-red-500/20 text-red-400'
                }`}>
                  Consistency: {result.consistency_score.toFixed(0)}%
                </span>
              )}
            </h3>
            <Button
              variant="outline"
              size="sm"
              onClick={runWalkForward}
              disabled={loading}
              className="border-accent/40 bg-accent/20 text-accent hover:bg-accent/30"
            >
              {loading ? 'Running...' : <><Play className="w-3.5 h-3.5 mr-1" />Run Walk-Forward</>}
            </Button>
          </div>

          {/* Data Source Selector */}
          <div className="mb-3">
            <Label className="text-xs text-muted-foreground mb-1 flex items-center gap-1">
              <Database className="h-3 w-3" /> Data Source
            </Label>
            {dsLoading ? (
              <div className="w-full rounded-lg border border-card-border bg-background px-2 py-1.5 text-xs text-muted-foreground">
                Loading data sources...
              </div>
            ) : datasources.length > 0 ? (
              <select
                value={selectedDsId}
                onChange={(e) => setSelectedDsId(Number(e.target.value))}
                className="w-full rounded-lg border border-card-border bg-background px-2 py-1.5 text-xs outline-none focus:border-accent"
              >
                {datasources.map((ds) => (
                  <option key={ds.id} value={ds.id}>
                    {ds.symbol} {ds.timeframe} — {ds.filename} ({ds.row_count.toLocaleString()} bars)
                  </option>
                ))}
              </select>
            ) : (
              <p className="text-xs text-red-400">No data sources available. Upload data first.</p>
            )}
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label className="text-xs text-muted-foreground mb-1">Folds</Label>
              <input type="number" value={nFolds} min={3} max={20}
                onChange={(e) => setNFolds(Number(e.target.value))}
                className="w-full rounded-lg border border-card-border bg-background px-2 py-1.5 text-xs outline-none focus:border-accent" />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground mb-1">Train %</Label>
              <input type="number" value={trainPct} min={50} max={90}
                onChange={(e) => setTrainPct(Number(e.target.value))}
                className="w-full rounded-lg border border-card-border bg-background px-2 py-1.5 text-xs outline-none focus:border-accent" />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground mb-1">Mode</Label>
              <select value={mode} onChange={(e) => setMode(e.target.value as 'anchored' | 'rolling')}
                className="w-full rounded-lg border border-card-border bg-background px-2 py-1.5 text-xs outline-none focus:border-accent">
                <option value="anchored">Anchored</option>
                <option value="rolling">Rolling</option>
              </select>
            </div>
          </div>

          {error && <p className="text-xs text-red-400 mt-2">{error}</p>}
        </CardContent>
      </Card>

      {/* OOS Summary */}
      {result && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-5 gap-3">
            {[
              { label: 'OOS Net P/L', value: usd(result.oos_net_profit), color: result.oos_net_profit >= 0 ? 'text-green-400' : 'text-red-400' },
              { label: 'OOS Trades', value: String(result.oos_total_trades), color: 'text-foreground' },
              { label: 'OOS Win Rate', value: `${fmt(result.oos_win_rate)}%`, color: 'text-foreground' },
              { label: 'OOS Profit Factor', value: fmt(result.oos_profit_factor), color: result.oos_profit_factor >= 1 ? 'text-green-400' : 'text-red-400' },
              { label: 'OOS Max DD%', value: `${fmt(result.oos_max_drawdown_pct)}%`, color: 'text-red-400' },
              { label: 'OOS Sharpe', value: fmt(result.oos_sharpe_ratio, 4), color: 'text-foreground' },
              { label: 'OOS Expectancy', value: usd(result.oos_expectancy), color: result.oos_expectancy >= 0 ? 'text-green-400' : 'text-red-400' },
              { label: 'OOS Avg Win', value: usd(result.oos_avg_win), color: 'text-green-400' },
              { label: 'OOS Avg Loss', value: usd(result.oos_avg_loss), color: 'text-red-400' },
              { label: 'Consistency', value: `${result.consistency_score.toFixed(0)}%`, color: result.consistency_score >= 70 ? 'text-green-400' : 'text-yellow-400' },
            ].map(({ label, value, color }) => (
              <Card key={label} className="bg-card-bg border-card-border">
                <CardContent className="p-3 text-center">
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wider">{label}</div>
                  <div className={`text-sm font-mono font-bold mt-1 ${color}`}>{value}</div>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* Per-fold table */}
          {result.windows.length > 0 && (
            <Card className="bg-card-bg border-card-border">
              <CardHeader className="pb-2 pt-3 px-4">
                <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Per-Fold Breakdown</CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-3">
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-card-border text-muted-foreground">
                        <th className="py-2 text-left px-2">Fold</th>
                        <th className="py-2 text-right px-2">Train Bars</th>
                        <th className="py-2 text-right px-2">Test Bars</th>
                        <th className="py-2 text-right px-2">OOS Trades</th>
                        <th className="py-2 text-right px-2">OOS Net P&L</th>
                        <th className="py-2 text-right px-2">OOS WR%</th>
                        <th className="py-2 text-right px-2">OOS PF</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.windows.map((w, i) => {
                        const ts = w.test_stats || {};
                        return (
                          <tr key={w.fold} className="border-b border-card-border/50">
                            <td className="py-1.5 px-2 text-muted-foreground">{w.fold}</td>
                            <td className="py-1.5 px-2 text-right">{w.train_bars}</td>
                            <td className="py-1.5 px-2 text-right">{w.test_bars}</td>
                            <td className="py-1.5 px-2 text-right">{ts.total_trades ?? result.fold_net_profits?.length ?? '—'}</td>
                            <td className={`py-1.5 px-2 text-right ${(result.fold_net_profits?.[i] ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                              {usd(result.fold_net_profits?.[i] ?? 0)}
                            </td>
                            <td className="py-1.5 px-2 text-right">{fmt(result.fold_win_rates?.[i] ?? 0)}%</td>
                            <td className="py-1.5 px-2 text-right">{fmt(result.fold_profit_factors?.[i] ?? 0)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
