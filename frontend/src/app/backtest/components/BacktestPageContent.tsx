'use client';

/**
 * BacktestPageContent — Reusable backtest orchestrator component.
 *
 * Extracted from the original BacktestPage so it can be embedded
 * in the combined Strategies page (tab) while keeping /backtest as a redirect.
 *
 * Composes:
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
import { Play, History, Plus, Loader2, BarChart3, Settings, Rocket, Database, FlaskConical } from 'lucide-react';
import ErrorBoundary from '@/components/ErrorBoundary';
import { PageSkeleton } from '@/components/Skeletons';
import { useIsMobile } from '@/hooks/useIsMobile';
import BacktestConfigDialog from './BacktestConfigDialog';
import BacktestDashboard from './BacktestDashboard';
import RunHistorySidebar from './RunHistorySidebar';
import StrategySettingsModal from '@/components/StrategySettingsModal';
import DeployAgentDialog from './DeployAgentDialog';
import DataSourcesPanel from './DataSourcesPanel';
import WalkForwardPanel from './WalkForwardPanel';

interface BacktestPageContentProps {
  defaultStrategyId?: number;
}

export default function BacktestPageContent({ defaultStrategyId }: BacktestPageContentProps = {}) {
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
  const [lastRunConfig, setLastRunConfig] = useState<Record<string, unknown> | null>(null);
  const [activeTab, setActiveTab] = useState<'backtest' | 'datasources' | 'walkforward'>('backtest');

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

  // Auto-open config dialog when defaultStrategyId is passed
  useEffect(() => {
    if (defaultStrategyId && !initialLoading && strategies.length > 0) {
      setConfigOpen(true);
    }
  }, [defaultStrategyId, initialLoading, strategies.length]);

  const refreshHistory = useCallback(async () => {
    try {
      const hist = await api.get<BacktestListItem[] | { items: BacktestListItem[] }>('/api/backtest');
      const histItems = Array.isArray(hist) ? hist : (hist as { items: BacktestListItem[] }).items || [];
      setHistory(histItems);
    } catch { /* ignore */ }
  }, []);

  const refreshDatasources = useCallback(async () => {
    try {
      const ds = await api.get<{ items: DataSource[] }>('/api/data/sources');
      setDatasources(Array.isArray(ds) ? ds : (ds as { items: DataSource[] }).items || []);
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

      if (res.status === 'running' && res.id) {
        const btId = res.id;
        const poll = async () => {
          for (let i = 0; i < 600; i++) {
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
        return;
      }

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

  const activeStrategy = result
    ? strategies.find(s => s.id === result.strategy_id) ?? null
    : null;

  const handleSettingsSaved = useCallback((updated: Strategy) => {
    setStrategies(prev => prev.map(s => s.id === updated.id ? updated : s));
    setSettingsOpen(false);
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
          <div className="flex items-center rounded-lg border border-card-border bg-card-bg/80 p-0.5">
            <button
              onClick={() => setActiveTab('backtest')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                activeTab === 'backtest'
                  ? 'bg-accent text-white'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              <BarChart3 className="w-4 h-4" />
              {!isMobile && 'Backtest'}
            </button>
            <button
              onClick={() => setActiveTab('datasources')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                activeTab === 'datasources'
                  ? 'bg-accent text-white'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              <Database className="w-4 h-4" />
              {!isMobile && 'Data Sources'}
              {datasources.length > 0 && (
                <span className={`text-xs px-1.5 py-0.5 rounded-full ${
                  activeTab === 'datasources'
                    ? 'bg-white/20'
                    : 'bg-muted-foreground/20'
                }`}>
                  {datasources.length}
                </span>
              )}
            </button>
            <button
              onClick={() => setActiveTab('walkforward')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                activeTab === 'walkforward'
                  ? 'bg-accent text-white'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              <FlaskConical className="w-4 h-4" />
              {!isMobile && 'Walk-Forward'}
            </button>
          </div>
          {activeTab === 'backtest' && result && (
            <span className="text-xs text-muted-foreground font-mono">
              {result.engine_version?.toUpperCase()} • {result.stats?.total_trades ?? 0} trades
            </span>
          )}
        </div>
        {activeTab === 'backtest' && (
          <div className="flex items-center gap-2">
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
        )}
      </div>

      {/* Body */}
      <div className="flex-1 flex overflow-hidden">
        {activeTab === 'datasources' ? (
          <div className="flex-1 overflow-auto">
            <DataSourcesPanel
              datasources={datasources}
              onRefresh={refreshDatasources}
            />
          </div>
        ) : activeTab === 'walkforward' ? (
          <div className="flex-1 overflow-auto p-4">
            {result ? (
              <WalkForwardPanel
                strategyId={result.strategy_id}
                datasourceId={result.datasource_id || 0}
              />
            ) : (
              <div className="flex items-center justify-center h-full">
                <div className="text-center space-y-4 max-w-md">
                  <FlaskConical className="w-12 h-12 mx-auto text-muted-foreground/30" />
                  <h2 className="text-xl font-semibold text-muted-foreground">Run a Backtest First</h2>
                  <p className="text-sm text-muted-foreground/60">
                    Run a backtest on the Backtest tab, then come here to validate it with walk-forward analysis.
                  </p>
                  <Button onClick={() => setActiveTab('backtest')} className="gap-2">
                    <BarChart3 className="w-4 h-4" /> Go to Backtest
                  </Button>
                </div>
              </div>
            )}
          </div>
        ) : (
          <>
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
          </>
        )}
      </div>

      {/* Config Dialog */}
      <BacktestConfigDialog
        open={configOpen}
        onOpenChange={setConfigOpen}
        strategies={strategies}
        datasources={datasources}
        defaultStrategyId={defaultStrategyId}
        onRun={handleRunBacktest}
      />

      {settingsOpen && activeStrategy && (
        <StrategySettingsModal
          strategy={activeStrategy}
          onClose={() => setSettingsOpen(false)}
          onSaved={handleSettingsSaved}
        />
      )}

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
