'use client';

/**
 * Backtest Page — V3 Complete Rewrite
 *
 * Thin orchestrator page that composes:
 *  - BacktestConfigDialog (modal to configure and launch backtests)
 *  - BacktestDashboard (full results dashboard with tabs)
 *  - RunHistorySidebar (past runs with compare)
 *  - StrategySettingsModal (edit strategy settings inline)
 *  - DeployAgentDialog (deploy winning strategy as agent)
 */

import { useState, useEffect, useCallback } from 'react';
import { api } from '@/lib/api';
import type {
  Strategy,
  DataSource,
  BacktestResponse,
  BacktestListItem,
} from '@/types';
import { Button } from '@/components/ui/button';
import { Play, History, Plus, Loader2, BarChart3, Settings, Rocket } from 'lucide-react';
import ErrorBoundary from '@/components/ErrorBoundary';
import { PageSkeleton } from '@/components/Skeletons';
import { useIsMobile } from '@/hooks/useIsMobile';
import BacktestConfigDialog from './components/BacktestConfigDialog';
import BacktestDashboard from './components/BacktestDashboard';
import RunHistorySidebar from './components/RunHistorySidebar';
import StrategySettingsModal from '@/components/StrategySettingsModal';
import DeployAgentDialog from './components/DeployAgentDialog';

export default function BacktestPage() {
  const isMobile = useIsMobile();
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [datasources, setDatasources] = useState<DataSource[]>([]);
  const [history, setHistory] = useState<BacktestListItem[]>([]);
  const [result, setResult] = useState<BacktestResponse | null>(null);
  const [compareResult, setCompareResult] = useState<BacktestResponse | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [loading, setLoading] = useState(false);
  const [configOpen, setConfigOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(!isMobile);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [deployOpen, setDeployOpen] = useState(false);
  // Track last run config so we can re-run after settings change
  const [lastRunConfig, setLastRunConfig] = useState<Record<string, unknown> | null>(null);

  // Load initial data
  useEffect(() => {
    Promise.all([
      api.get<{ items: Strategy[] }>('/api/strategies').catch(() => ({ items: [] })),
      api.get<{ items: DataSource[] }>('/api/data/sources').catch(() => ({ items: [] })),
      api.get<BacktestListItem[] | { items: BacktestListItem[] }>('/api/backtest').catch(() => []),
    ]).then(([strats, ds, hist]) => {
      setStrategies(Array.isArray(strats) ? strats : (strats as { items: Strategy[] }).items || []);
      setDatasources(Array.isArray(ds) ? ds : (ds as { items: DataSource[] }).items || []);
      const histItems = Array.isArray(hist) ? hist : (hist as { items: BacktestListItem[] }).items || [];
      setHistory(histItems);
    }).finally(() => setInitialLoading(false));
  }, []);

  const refreshHistory = useCallback(async () => {
    try {
      const hist = await api.get<BacktestListItem[] | { items: BacktestListItem[] }>('/api/backtest');
      const histItems = Array.isArray(hist) ? hist : (hist as { items: BacktestListItem[] }).items || [];
      setHistory(histItems);
    } catch { /* ignore */ }
  }, []);

  // Refresh strategies list (after settings update)
  const refreshStrategies = useCallback(async () => {
    try {
      const strats = await api.get<{ items: Strategy[] }>('/api/strategies');
      setStrategies(Array.isArray(strats) ? strats : (strats as { items: Strategy[] }).items || []);
    } catch { /* ignore */ }
  }, []);

  const handleRunBacktest = useCallback(async (config: {
    strategy_id: number;
    datasource_id: number;
    initial_balance: number;
    spread_points: number;
    commission_per_lot: number;
    point_value: number;
    tick_mode: string;
    slippage_pct: number;
    margin_rate: number;
    latency_ms: number;
    ml_model_id?: number;
    regime_model_id?: number;
    rl_model_id?: number;
    strategy_type?: string;
    ml_threshold?: number;
  }) => {
    setLoading(true);
    setConfigOpen(false);
    setCompareResult(null);
    setLastRunConfig(config);
    try {
      const res = await api.post<{ id: number; status: string }>('/api/backtest/run-v3', {
        ...config,
        engine_version: 'v3',
      });

      // Async backtest: poll until completed or failed
      if (res.status === 'running' && res.id) {
        const btId = res.id;
        const poll = async () => {
          for (let i = 0; i < 600; i++) {  // max ~30 min (3s intervals)
            await new Promise(r => setTimeout(r, 3000));
            try {
              const check = await api.get<{
                id: number; strategy_id: number; status: string;
                results: Record<string, unknown>;
              }>(`/api/backtest/${btId}`);
              if (check.status === 'completed') {
                const r = check.results || {};
                setResult({
                  id: check.id,
                  strategy_id: check.strategy_id,
                  datasource_id: (r.datasource_id as number) || config.datasource_id,
                  status: 'completed',
                  stats: (r.stats || r.v2_stats || {}) as BacktestResponse['stats'],
                  trades: (r.trades || []) as BacktestResponse['trades'],
                  equity_curve: (r.equity_curve || []) as number[],
                  engine_version: (r.engine_version as string) || 'v3',
                  v2_stats: r.v2_stats as Record<string, unknown>,
                  tearsheet: r.tearsheet as Record<string, unknown>,
                  elapsed_seconds: r.elapsed_seconds as number,
                });
                refreshHistory();
                setLoading(false);
                return;
              }
              if (check.status === 'failed') {
                const errMsg = (check.results as Record<string, unknown>)?.error;
                alert(`Backtest failed: ${errMsg || 'Unknown error'}`);
                setLoading(false);
                return;
              }
            } catch {
              // network blip — keep polling
            }
          }
          alert('Backtest timed out after 30 minutes');
          setLoading(false);
        };
        poll();
        return;  // don't setLoading(false) yet — poll() handles it
      }

      // Fallback: if backend returned completed synchronously
      setResult(res as unknown as BacktestResponse);
      refreshHistory();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Backtest failed';
      alert(msg);
    } finally {
      setLoading(false);
    }
  }, [refreshHistory]);

  const handleLoadRun = useCallback(async (id: number) => {
    try {
      const full = await api.get<{ results: Record<string, unknown>; id: number; strategy_id: number }>(`/api/backtest/${id}`);
      const r = full.results || {};
      setResult({
        id: full.id,
        strategy_id: full.strategy_id,
        datasource_id: 0,
        status: 'completed',
        stats: (r.stats || r.v2_stats || {}) as BacktestResponse['stats'],
        trades: (r.trades || []) as BacktestResponse['trades'],
        equity_curve: (r.equity_curve || []) as number[],
        engine_version: (r.engine_version as string) || 'v3',
        v2_stats: r.v2_stats as Record<string, unknown>,
        tearsheet: r.tearsheet as Record<string, unknown>,
        elapsed_seconds: r.elapsed_seconds as number,
      });
      setCompareResult(null);
    } catch { /* ignore */ }
  }, []);

  const handleCompare = useCallback(async (id: number) => {
    try {
      const full = await api.get<{ results: Record<string, unknown>; id: number; strategy_id: number }>(`/api/backtest/${id}`);
      const r = full.results || {};
      setCompareResult({
        id: full.id,
        strategy_id: full.strategy_id,
        datasource_id: 0,
        status: 'completed',
        stats: (r.stats || {}) as BacktestResponse['stats'],
        trades: (r.trades || []) as BacktestResponse['trades'],
        equity_curve: (r.equity_curve || []) as number[],
        engine_version: (r.engine_version as string) || 'v3',
      });
    } catch { /* ignore */ }
  }, []);

  const handleDeleteRun = useCallback(async (id: number) => {
    try {
      await api.delete(`/api/backtest/${id}`);
      refreshHistory();
      if (result?.id === id) setResult(null);
      if (compareResult?.id === id) setCompareResult(null);
    } catch { /* ignore */ }
  }, [refreshHistory, result, compareResult]);

  // Resolve the active strategy from current result
  const activeStrategy = result
    ? strategies.find(s => s.id === result.strategy_id) ?? null
    : null;

  // After saving settings, refresh strategies and optionally re-run
  const handleSettingsSaved = useCallback((updated: Strategy) => {
    setStrategies(prev => prev.map(s => s.id === updated.id ? updated : s));
    setSettingsOpen(false);
    // If we have a last run config matching this strategy, offer to re-run
    if (lastRunConfig && Number(lastRunConfig.strategy_id) === updated.id) {
      if (confirm('Settings saved. Re-run the backtest with updated settings?')) {
        handleRunBacktest(lastRunConfig as Parameters<typeof handleRunBacktest>[0]);
      }
    }
  }, [lastRunConfig, handleRunBacktest]);

  const hasSettings = activeStrategy && activeStrategy.settings_schema?.length > 0;
  const isProfitable = result && result.stats?.net_profit > 0;

  if (initialLoading) return <PageSkeleton />;

  return (
    <ErrorBoundary section="Backtesting">
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-card-border bg-card-bg/50">
        <div className="flex items-center gap-3">
          <BarChart3 className="w-5 h-5 text-accent" />
          <h1 className="text-lg font-semibold">Backtesting</h1>
          {result && (
            <span className="text-xs text-muted-foreground font-mono">
              {result.engine_version?.toUpperCase()} • {result.stats?.total_trades ?? 0} trades
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {/* Edit Strategy Settings */}
          {hasSettings && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setSettingsOpen(true)}
              className="gap-1.5"
              title="Edit strategy settings and re-run"
            >
              <Settings className="w-4 h-4" />
              {!isMobile && 'Edit Strategy'}
            </Button>
          )}
          {/* Deploy as Agent */}
          {isProfitable && activeStrategy && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setDeployOpen(true)}
              className="gap-1.5 border-green-500/40 text-green-400 hover:bg-green-500/10"
              title="Deploy this strategy as a trading agent"
            >
              <Rocket className="w-4 h-4" />
              {!isMobile && 'Deploy Agent'}
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() => setHistoryOpen(!historyOpen)}
            className="gap-1.5"
          >
            <History className="w-4 h-4" />
            {!isMobile && 'History'}
          </Button>
          <Button
            size="sm"
            onClick={() => setConfigOpen(true)}
            disabled={loading}
            className="gap-1.5"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            {!isMobile && (loading ? 'Running...' : 'New Backtest')}
          </Button>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 flex overflow-hidden">
        {/* Main Content */}
        <div className="flex-1 overflow-auto">
          {loading && (
            <div className="flex items-center justify-center h-full">
              <div className="text-center space-y-4">
                <Loader2 className="w-8 h-8 animate-spin mx-auto text-accent" />
                <p className="text-muted-foreground">Running backtest...</p>
              </div>
            </div>
          )}

          {!loading && !result && (
            <div className="flex items-center justify-center h-full">
              <div className="text-center space-y-4 max-w-md">
                <BarChart3 className="w-12 h-12 mx-auto text-muted-foreground/30" />
                <h2 className="text-xl font-semibold text-muted-foreground">No Results Yet</h2>
                <p className="text-sm text-muted-foreground/60">
                  Configure and run a backtest to see results, or select a previous run from history.
                </p>
                <Button onClick={() => setConfigOpen(true)} className="gap-2">
                  <Plus className="w-4 h-4" /> New Backtest
                </Button>
              </div>
            </div>
          )}

          {!loading && result && (
            <BacktestDashboard
              result={result}
              compareResult={compareResult}
              onClearCompare={() => setCompareResult(null)}
            />
          )}
        </div>

        {/* History Sidebar */}
        {historyOpen && (
          <RunHistorySidebar
            history={history}
            activeId={result?.id}
            onSelect={handleLoadRun}
            onCompare={handleCompare}
            onDelete={handleDeleteRun}
            onClose={() => setHistoryOpen(false)}
          />
        )}
      </div>

      {/* Config Dialog */}
      <BacktestConfigDialog
        open={configOpen}
        onOpenChange={setConfigOpen}
        strategies={strategies}
        datasources={datasources}
        onRun={handleRunBacktest}
      />

      {/* Strategy Settings Modal */}
      {settingsOpen && activeStrategy && (
        <StrategySettingsModal
          strategy={activeStrategy}
          onClose={() => setSettingsOpen(false)}
          onSaved={handleSettingsSaved}
        />
      )}

      {/* Deploy Agent Dialog */}
      {deployOpen && activeStrategy && result && (
        <DeployAgentDialog
          strategy={activeStrategy}
          symbol={result.stats ? (history.find(h => h.id === result.id)?.symbol || '') : ''}
          timeframe={history.find(h => h.id === result.id)?.timeframe || ''}
          stats={result.stats}
          onClose={() => setDeployOpen(false)}
        />
      )}
    </div>
    </ErrorBoundary>
  );
}
