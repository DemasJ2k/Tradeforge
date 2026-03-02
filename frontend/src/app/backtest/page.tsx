'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import type {
  Strategy,
  DataSource,
  BacktestResponse,
  BacktestListItem,
  TradeResult,
} from '@/types';
import ChatHelpers from '@/components/ChatHelpers';
import { useBrokerAccounts } from '@/hooks/useBrokerAccounts';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Play, RefreshCw, Plus, Loader2, ChevronLeft, ChevronRight,
  ArrowUpDown, TrendingUp, TrendingDown, Rocket, BarChart3, Settings, Trash2, Eye,
} from 'lucide-react';
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable';
import BacktestTradeChart from '@/components/BacktestTradeChart';
import StrategySettingsModal from '@/components/StrategySettingsModal';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function getToken() {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('token');
}

function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

// ─── Stat Card ───
function StatCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <Card className="bg-card-bg border-card-border">
      <CardContent className="p-4">
        <div className="text-xs text-muted-foreground uppercase tracking-wider mb-1">{label}</div>
        <div className={`text-xl font-bold font-mono ${color || 'text-foreground'}`}>{value}</div>
        {sub && <div className="text-xs text-muted-foreground/60 mt-1">{sub}</div>}
      </CardContent>
    </Card>
  );
}

// ─── Equity Curve (canvas) ───
function EquityCurve({ data, height = 300 }: { data: number[]; height?: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || data.length < 2) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Read theme colors from CSS custom properties
    const style = getComputedStyle(document.documentElement);
    const bgColor = style.getPropertyValue('--fa-card-bg').trim() || '#0f1219';
    const gridColor = style.getPropertyValue('--fa-card-border').trim() || '#1e293b';
    const labelColor = style.getPropertyValue('--color-muted-foreground')?.trim() || '#6b7280';
    const successColor = '#22c55e';
    const dangerColor = '#ef4444';

    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);

    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min || 1;
    const pad = 60;

    // Background
    ctx.fillStyle = bgColor;
    ctx.fillRect(0, 0, w, h);

    // Grid lines
    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = pad / 2 + ((h - pad) * i) / 4;
      ctx.beginPath();
      ctx.moveTo(pad, y);
      ctx.lineTo(w - 10, y);
      ctx.stroke();

      // Y-axis labels
      const val = max - (range * i) / 4;
      ctx.fillStyle = labelColor;
      ctx.font = '11px "JetBrains Mono", monospace';
      ctx.textAlign = 'right';
      ctx.fillText(`$${val.toFixed(0)}`, pad - 5, y + 4);
    }

    // Initial balance line
    const initialY = pad / 2 + ((max - data[0]) / range) * (h - pad);
    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(pad, initialY);
    ctx.lineTo(w - 10, initialY);
    ctx.stroke();
    ctx.setLineDash([]);

    // Equity line
    const finalVal = data[data.length - 1];
    const isProfit = finalVal >= data[0];
    ctx.strokeStyle = isProfit ? successColor : dangerColor;
    ctx.lineWidth = 2;
    ctx.beginPath();

    for (let i = 0; i < data.length; i++) {
      const x = pad + ((w - pad - 10) * i) / (data.length - 1);
      const y = pad / 2 + ((max - data[i]) / range) * (h - pad);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Fill under curve
    const lastX = pad + (w - pad - 10);
    ctx.lineTo(lastX, h - pad / 2);
    ctx.lineTo(pad, h - pad / 2);
    ctx.closePath();
    const gradient = ctx.createLinearGradient(0, 0, 0, h);
    gradient.addColorStop(0, isProfit ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)');
    gradient.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = gradient;
    ctx.fill();
  }, [data, height]);

  return (
    <canvas
      ref={canvasRef}
      className="w-full rounded-lg"
      style={{ height: `${height}px` }}
    />
  );
}

// ─── Trade Log Table ───
function TradeLog({ trades }: { trades: TradeResult[] }) {
  const [sortBy, setSortBy] = useState<'entry_time' | 'pnl'>('entry_time');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const [page, setPage] = useState(0);
  const perPage = 20;

  const sorted = [...trades].sort((a, b) => {
    const m = sortDir === 'asc' ? 1 : -1;
    if (sortBy === 'pnl') return (a.pnl - b.pnl) * m;
    return (a.entry_time - b.entry_time) * m;
  });

  const paged = sorted.slice(page * perPage, (page + 1) * perPage);
  const totalPages = Math.ceil(trades.length / perPage);

  const toggleSort = (col: 'entry_time' | 'pnl') => {
    if (sortBy === col) setSortDir(d => (d === 'asc' ? 'desc' : 'asc'));
    else { setSortBy(col); setSortDir('asc'); }
  };

  const fmtTime = (ts: number | null) => {
    if (!ts) return '-';
    return new Date(ts * 1000).toISOString().replace('T', ' ').slice(0, 19);
  };

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted-foreground border-b border-card-border">
              <th className="text-left p-2">#</th>
              <th className="text-left p-2 cursor-pointer hover:text-white" onClick={() => toggleSort('entry_time')}>
                Entry Time {sortBy === 'entry_time' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
              </th>
              <th className="text-left p-2">Dir</th>
              <th className="text-right p-2">Entry</th>
              <th className="text-right p-2">SL</th>
              <th className="text-right p-2">TP</th>
              <th className="text-right p-2">Exit</th>
              <th className="text-left p-2">Reason</th>
              <th className="text-right p-2 cursor-pointer hover:text-white" onClick={() => toggleSort('pnl')}>
                PnL {sortBy === 'pnl' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
              </th>
            </tr>
          </thead>
          <tbody>
            {paged.map((t, idx) => (
              <tr key={idx} className="border-b border-card-border/50 hover:bg-muted/30">
                <td className="p-2 text-muted-foreground/60">{page * perPage + idx + 1}</td>
                <td className="p-2 text-foreground/80 font-mono text-xs">{fmtTime(t.entry_time)}</td>
                <td className="p-2">
                  <span className={`px-2 py-0.5 rounded text-xs font-bold ${t.direction === 'long' ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'}`}>
                    {t.direction.toUpperCase()}
                  </span>
                </td>
                <td className="p-2 text-right font-mono text-foreground/80">{t.entry_price.toFixed(2)}</td>
                <td className="p-2 text-right font-mono text-muted-foreground/60">{t.stop_loss.toFixed(2)}</td>
                <td className="p-2 text-right font-mono text-muted-foreground/60">{t.take_profit.toFixed(2)}</td>
                <td className="p-2 text-right font-mono text-foreground/80">{t.exit_price?.toFixed(2) || '-'}</td>
                <td className="p-2">
                  <span className={`text-xs ${t.exit_reason === 'take_profit' ? 'text-green-400' : t.exit_reason === 'stop_loss' ? 'text-red-400' : 'text-muted-foreground'}`}>
                    {t.exit_reason.replace('_', ' ')}
                  </span>
                </td>
                <td className={`p-2 text-right font-mono font-bold ${t.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {t.pnl >= 0 ? '+' : ''}{t.pnl.toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-3 px-2">
          <span className="text-sm text-muted-foreground">
            Showing {page * perPage + 1}-{Math.min((page + 1) * perPage, trades.length)} of {trades.length}
          </span>
          <div className="flex gap-2">
            <button onClick={() => setPage(Math.max(0, page - 1))} disabled={page === 0}
              className="px-3 py-1 rounded bg-muted text-foreground/80 disabled:opacity-30 hover:bg-muted text-sm">
              Prev
            </button>
            <button onClick={() => setPage(Math.min(totalPages - 1, page + 1))} disabled={page >= totalPages - 1}
              className="px-3 py-1 rounded bg-muted text-foreground/80 disabled:opacity-30 hover:bg-muted text-sm">
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Monthly Returns Heatmap ───
function MonthlyReturns({ trades }: { trades: TradeResult[] }) {
  const monthly: Record<string, number> = {};
  for (const t of trades) {
    if (!t.exit_time) continue;
    const d = new Date(t.exit_time * 1000);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    monthly[key] = (monthly[key] || 0) + t.pnl;
  }

  const keys = Object.keys(monthly).sort();
  if (keys.length === 0) return null;

  const maxAbs = Math.max(...Object.values(monthly).map(Math.abs), 1);
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const years = [...new Set(keys.map(k => k.split('-')[0]))];

  return (
    <div className="overflow-x-auto">
      <table className="text-xs">
        <thead>
          <tr>
            <th className="p-1 text-muted-foreground"></th>
            {months.map(m => <th key={m} className="p-1 text-muted-foreground min-w-[50px]">{m}</th>)}
            <th className="p-1 text-muted-foreground min-w-[60px]">Total</th>
          </tr>
        </thead>
        <tbody>
          {years.map(yr => {
            let yearTotal = 0;
            return (
              <tr key={yr}>
                <td className="p-1 text-muted-foreground font-bold">{yr}</td>
                {months.map((_, mi) => {
                  const key = `${yr}-${String(mi + 1).padStart(2, '0')}`;
                  const val = monthly[key];
                  if (val !== undefined) yearTotal += val;
                  if (val === undefined) return <td key={mi} className="p-1 text-center text-muted-foreground/30">-</td>;
                  const intensity = Math.min(Math.abs(val) / maxAbs, 1);
                  const bg = val >= 0
                    ? `rgba(34,197,94,${0.15 + intensity * 0.6})`
                    : `rgba(239,68,68,${0.15 + intensity * 0.6})`;
                  return (
                    <td key={mi} className="p-1 text-center font-mono rounded" style={{ backgroundColor: bg }}>
                      <span className={val >= 0 ? 'text-green-300' : 'text-red-300'}>
                        {val >= 0 ? '+' : ''}{val.toFixed(0)}
                      </span>
                    </td>
                  );
                })}
                <td className={`p-1 text-center font-mono font-bold ${yearTotal >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {yearTotal >= 0 ? '+' : ''}{yearTotal.toFixed(0)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Main Page ───
export default function BacktestPage() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [datasources, setDatasources] = useState<DataSource[]>([]);
  const [history, setHistory] = useState<BacktestListItem[]>([]);

  const [strategyId, setStrategyId] = useState<number | ''>('');
  const [datasourceId, setDatasourceId] = useState<number | ''>('');
  const [datasourceIds, setDatasourceIds] = useState<number[]>([]);
  const [settingsStrategy, setSettingsStrategy] = useState<Strategy | null>(null);
  const [initialBalance, setInitialBalance] = useState(10000);
  const [spreadPoints, setSpreadPoints] = useState(0.3);
  const [commission, setCommission] = useState(7.0);
  const [pointValue, setPointValue] = useState(1.0);
  const engineVersion = 'v2' as const;
  // V2 engine options
  const [slippagePct, setSlippagePct] = useState(0.0);
  const [commissionPct, setCommissionPct] = useState(0.0);
  const [marginRate, setMarginRate] = useState(0.01);
  const [useFastCore, setUseFastCore] = useState(false);
  const [barsPerDay, setBarsPerDay] = useState(1.0);

  const [running, setRunning] = useState(false);
  const [runningWF, setRunningWF] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<BacktestResponse | null>(null);
  const [chartBars, setChartBars] = useState<{time:number;open:number;high:number;low:number;close:number;volume?:number}[]>([]);
  const [chartIndicators, setChartIndicators] = useState<Record<string, {time:number;value:number|null}[]>>({});
  const [wfResult, setWfResult] = useState<any>(null);
  const [activeTab, setActiveTab] = useState<'equity' | 'trades' | 'monthly' | 'tearsheet' | 'portfolio' | 'chart'>('equity');
  const [showCreateAgent, setShowCreateAgent] = useState(false);
  const { accounts, activeBroker } = useBrokerAccounts();

  useEffect(() => {
    const h = authHeaders();
    fetch(`${API}/api/strategies`, { headers: h })
      .then(r => r.json())
      .then(d => setStrategies(d.items || []))
      .catch(() => {});

    fetch(`${API}/api/data/sources`, { headers: h })
      .then(r => r.json())
      .then(d => setDatasources(d.items || []))
      .catch(() => {});

    fetch(`${API}/api/backtest`, { headers: h })
      .then(r => r.json())
      .then(d => setHistory(Array.isArray(d) ? d : []))
      .catch(() => {});
  }, []);

  const runBacktest = useCallback(async () => {
    if (!strategyId || !datasourceId) {
      setError('Select a strategy and data source');
      return;
    }
    setRunning(true);
    setError('');
    setResult(null);

    const isPortfolio = datasourceIds.length > 1;

    try {
      const r = await fetch(`${API}/api/backtest/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          strategy_id: strategyId,
          datasource_id: datasourceId,
          initial_balance: initialBalance,
          spread_points: spreadPoints,
          commission_per_lot: commission,
          point_value: pointValue,
          engine_version: 'v2',
          ...(isPortfolio ? { datasource_ids: datasourceIds } : {}),
          slippage_pct: slippagePct,
          commission_pct: commissionPct,
          margin_rate: marginRate,
          use_fast_core: useFastCore,
          bars_per_day: barsPerDay,
        }),
      });

      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(err.detail || `Error ${r.status}`);
      }

      const data: BacktestResponse = await r.json();
      setResult(data);

      // Fetch chart data for trade chart overlay (Phase 5B)
      if (data.id) {
        fetch(`${API}/api/backtest/${data.id}/chart-data`, { headers: authHeaders() })
          .then(r2 => r2.ok ? r2.json() : null)
          .then(cd => {
            if (cd && cd.bars) {
              setChartBars(cd.bars);
              // Convert indicator arrays to {time,value}[] format
              if (cd.indicators && cd.timestamps) {
                const overlays: Record<string, {time:number;value:number|null}[]> = {};
                for (const [key, vals] of Object.entries(cd.indicators)) {
                  overlays[key] = (cd.timestamps as number[]).map((t: number, i: number) => ({
                    time: t,
                    value: (vals as (number|null)[])[i] ?? null,
                  }));
                }
                setChartIndicators(overlays);
              }
            }
          })
          .catch(() => {});
      }

      fetch(`${API}/api/backtest`, { headers: authHeaders() })
        .then(r => r.json())
        .then(d => setHistory(Array.isArray(d) ? d : []))
        .catch(() => {});
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Backtest failed');
    } finally {
      setRunning(false);
    }
  }, [strategyId, datasourceId, datasourceIds, initialBalance, spreadPoints, commission, pointValue, slippagePct, commissionPct, marginRate, useFastCore, barsPerDay]);

  const runWalkForward = useCallback(async () => {
    if (!strategyId || !datasourceId) {
      setError('Select a strategy and data source');
      return;
    }
    setRunningWF(true);
    setError('');
    setWfResult(null);

    try {
      const r = await fetch(`${API}/api/backtest/walk-forward`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          strategy_id: strategyId,
          datasource_id: datasourceId,
          n_folds: 5,
          train_pct: 70,
          mode: 'anchored',
          initial_balance: initialBalance,
          spread_points: spreadPoints,
          commission_per_lot: commission,
          point_value: pointValue,
        }),
      });

      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(err.detail || `Error ${r.status}`);
      }

      const data = await r.json();
      setWfResult(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Walk-forward failed');
    } finally {
      setRunningWF(false);
    }
  }, [strategyId, datasourceId, initialBalance, spreadPoints, commission, pointValue]);

  const [mlModels, setMlModels] = useState<{id: number; name: string; val_accuracy: number | null}[]>([]);

  useEffect(() => {
    fetch(`${API}/api/ml/models?status=ready`, { headers: authHeaders() })
      .then(r => r.json())
      .then(d => setMlModels(Array.isArray(d) ? d : d.items || []))
      .catch(() => {});
  }, []);

  const deployAsAgent = useCallback(async (
    name: string, mode: string, timeframe: string,
    mlModelId: number | null, brokerName: string, lotSize: number,
  ) => {
    if (!strategyId) return;
    const ds = datasources.find(d => d.id === datasourceId);
    const symbol = ds?.symbol || 'XAUUSD';
    try {
      const body: Record<string, unknown> = {
        name,
        strategy_id: strategyId,
        symbol,
        timeframe,
        mode,
        broker_name: brokerName,
        risk_config: { lot_size: lotSize },
      };
      if (mlModelId) body.ml_model_id = mlModelId;
      const r = await fetch(`${API}/api/agents`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error('Failed to create agent');
      setShowCreateAgent(false);
      setError('');
      alert(`Agent "${name}" created successfully! Go to Trading page to manage it.`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to create agent');
    }
  }, [strategyId, datasourceId, datasources]);

  const stats = result?.stats;

  const handleViewPastResult = async (btId: number) => {
    try {
      const r = await fetch(`${API}/api/backtest/${btId}`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      if (!r.ok) throw new Error('fetch failed');
      const data = await r.json();
      if (data.results && data.results.stats) {
        setResult(data.results as unknown as BacktestResponse);
        setError('');
      } else {
        setError('No results stored for this backtest');
      }
    } catch {
      setError('Failed to load past backtest');
    }
  };

  const handleDeleteBacktest = async (btId: number) => {
    if (!confirm('Delete this backtest run?')) return;
    try {
      const r = await fetch(`${API}/api/backtest/${btId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      if (!r.ok) throw new Error('delete failed');
      setHistory((prev) => prev.filter((h) => h.id !== btId));
    } catch {
      setError('Failed to delete backtest');
    }
  };

  return (
    <div className="space-y-4 h-full">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Backtesting</h1>
          <p className="text-muted-foreground text-sm mt-1">Test strategies against historical data</p>
        </div>
      </div>

      <ResizablePanelGroup orientation="horizontal" className="min-h-[calc(100vh-200px)] rounded-xl border border-card-border">
        {/* ─── LEFT: Config Panel ─── */}
        <ResizablePanel defaultSize={35} minSize={5}>
          <div className="h-full overflow-y-auto p-5 bg-card-bg">
            <h2 className="text-sm font-semibold text-foreground uppercase tracking-wider mb-4">Configuration</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Strategy</label>
                <div className="flex items-center gap-1.5">
                <select
                  value={strategyId}
                  onChange={e => setStrategyId(e.target.value ? Number(e.target.value) : '')}
                  className="flex-1 bg-input-bg border border-input-border rounded-lg px-3 py-2 text-foreground text-sm focus:border-fa-accent focus:outline-none"
                >
                  <option value="">Select strategy...</option>
                  {strategies.map(s => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
                {strategyId && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      const s = strategies.find(x => x.id === strategyId);
                      if (s) setSettingsStrategy(s);
                    }}
                    className="h-9 w-9 p-0 text-muted-foreground hover:text-accent shrink-0"
                    title="Strategy settings"
                  >
                    <Settings className="h-4 w-4" />
                  </Button>
                )}
                </div>
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Data Source</label>
                <select
                  value={datasourceId}
                  onChange={e => {
                    const id = e.target.value ? Number(e.target.value) : '';
                    setDatasourceId(id);
                    if (id && !datasourceIds.includes(id as number)) {
                      setDatasourceIds(prev => [...prev, id as number]);
                    }
                  }}
                  className="w-full bg-input-bg border border-input-border rounded-lg px-3 py-2 text-foreground text-sm focus:border-fa-accent focus:outline-none"
                >
                  <option value="">Select data source...</option>
                  {datasources.map(d => (
                    <option key={d.id} value={d.id}>
                      {d.symbol} {d.timeframe} ({d.row_count?.toLocaleString()} bars)
                    </option>
                  ))}
                </select>
                {/* Multi-symbol portfolio chips */}
                {datasourceIds.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1.5">
                    {datasourceIds.map(id => {
                      const ds = datasources.find(d => d.id === id);
                      return (
                        <Badge key={id} variant="outline" className="gap-1 border-fa-accent/30 text-fa-accent/80">
                          {ds?.symbol || `#${id}`}
                          <button
                            onClick={() => {
                              setDatasourceIds(prev => prev.filter(x => x !== id));
                              if (id === datasourceId) {
                                const remaining = datasourceIds.filter(x => x !== id);
                                setDatasourceId(remaining[0] || '');
                              }
                            }}
                            className="hover:text-red-400 ml-0.5"
                          >&times;</button>
                        </Badge>
                      );
                    })}
                    {datasourceIds.length > 1 && (
                      <Badge variant="outline" className="border-emerald-500/30 text-emerald-400 text-[10px]">Portfolio Mode</Badge>
                    )}
                  </div>
                )}
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Balance ($)</label>
                  <input type="number" value={initialBalance}
                    onChange={e => setInitialBalance(Number(e.target.value))}
                    className="w-full bg-input-bg border border-input-border rounded-lg px-3 py-2 text-foreground text-sm focus:border-fa-accent focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Spread (pts)</label>
                  <input type="number" step="0.1" value={spreadPoints}
                    onChange={e => setSpreadPoints(Number(e.target.value))}
                    className="w-full bg-input-bg border border-input-border rounded-lg px-3 py-2 text-foreground text-sm focus:border-fa-accent focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Commission ($)</label>
                  <input type="number" step="0.5" value={commission}
                    onChange={e => setCommission(Number(e.target.value))}
                    className="w-full bg-input-bg border border-input-border rounded-lg px-3 py-2 text-foreground text-sm focus:border-fa-accent focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Point Value</label>
                  <input type="number" step="0.01" value={pointValue}
                    onChange={e => setPointValue(Number(e.target.value))}
                    className="w-full bg-input-bg border border-input-border rounded-lg px-3 py-2 text-foreground text-sm focus:border-fa-accent focus:outline-none"
                  />
                </div>
              </div>

              <div className="flex gap-2">
                <Button
                  onClick={runBacktest}
                  disabled={running || runningWF || !strategyId || !datasourceId}
                  className="flex-1 bg-fa-accent hover:bg-fa-accent/80 text-white font-semibold"
            >
              {running ? (
                <><Loader2 className="h-4 w-4 animate-spin" /> Running...</>
              ) : (
                <><Play className="h-4 w-4" /> Backtest</>
              )}
            </Button>
            <Button
              onClick={runWalkForward}
              disabled={running || runningWF || !strategyId || !datasourceId}
              variant="outline"
              className="flex-1 border-purple-600 text-purple-400 hover:bg-purple-600/20"
            >
              {runningWF ? (
                <><Loader2 className="h-4 w-4 animate-spin" /> Validating...</>
              ) : (
                <><RefreshCw className="h-4 w-4" /> Walk-Forward</>
              )}
            </Button>
          </div>

          {/* Advanced Engine Options */}
            <div className="border-t border-card-border pt-4">
              <h3 className="text-xs font-semibold text-fa-accent uppercase tracking-wider mb-3">Advanced Options</h3>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Slippage (%)</label>
                  <input type="number" step="0.001" value={slippagePct}
                    onChange={e => setSlippagePct(Number(e.target.value))}
                    className="w-full bg-input-bg border border-input-border rounded-lg px-3 py-2 text-white text-sm focus:border-fa-accent focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Comm. (%)</label>
                  <input type="number" step="0.001" value={commissionPct}
                    onChange={e => setCommissionPct(Number(e.target.value))}
                    className="w-full bg-input-bg border border-input-border rounded-lg px-3 py-2 text-white text-sm focus:border-fa-accent focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Margin Rate</label>
                  <input type="number" step="0.001" value={marginRate}
                    onChange={e => setMarginRate(Number(e.target.value))}
                    className="w-full bg-input-bg border border-input-border rounded-lg px-3 py-2 text-white text-sm focus:border-fa-accent focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Bars/Day</label>
                  <input type="number" step="1" value={barsPerDay}
                    onChange={e => setBarsPerDay(Number(e.target.value))}
                    className="w-full bg-input-bg border border-input-border rounded-lg px-3 py-2 text-white text-sm focus:border-fa-accent focus:outline-none"
                  />
                </div>
              </div>
              <label className="flex items-center gap-2 cursor-pointer mt-3">
                <input type="checkbox" checked={useFastCore}
                  onChange={e => setUseFastCore(e.target.checked)}
                  className="w-4 h-4 rounded border-input-border bg-input-bg text-fa-accent focus:ring-fa-accent focus:ring-offset-0"
                />
                <span className="text-sm text-foreground/80">Fast Core</span>
              </label>
            </div>

          {error && <div className="text-red-400 text-sm bg-red-900/20 rounded-lg px-3 py-2">{error}</div>}

          {/* History */}
          {history.length > 0 && (
            <div className="border-t border-card-border pt-4">
              <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Recent Runs</h3>
              <div className="space-y-1.5 max-h-60 overflow-y-auto">
                {history.slice(0, 15).map(bt => (
                  <div key={bt.id} className="flex items-center justify-between text-xs py-1.5 px-2 rounded hover:bg-muted/30 group">
                    <button onClick={() => handleViewPastResult(bt.id)} className="flex items-center gap-2 min-w-0 flex-1 text-left">
                      <Eye className="h-3 w-3 text-muted-foreground/40 group-hover:text-accent shrink-0" />
                      <span className="font-semibold text-foreground">{bt.symbol}</span>
                      <span className="text-muted-foreground">{bt.timeframe}</span>
                    </button>
                    <div className="flex items-center gap-2">
                      <span className={`font-mono font-bold ${(bt.stats.net_profit || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        ${(bt.stats.net_profit || 0).toFixed(0)}
                      </span>
                      <span className="text-muted-foreground/60">{bt.stats.total_trades || 0}t</span>
                      <button onClick={() => handleDeleteBacktest(bt.id)} className="text-muted-foreground/30 hover:text-danger transition-colors" title="Delete">
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
            </div>
          </div>
        </ResizablePanel>

        <ResizableHandle withHandle />

        {/* ─── RIGHT: Results Panel ─── */}
        <ResizablePanel defaultSize={65} minSize={5}>
          <div className="h-full overflow-y-auto p-5 bg-background">
      {/* Results */}
      {stats && result ? (
        <div className="space-y-5">
          {/* Action bar */}
          {stats.profit_factor > 1.2 && stats.total_trades >= 10 && (
            <div className="flex items-center justify-between bg-green-900/20 border border-green-800/40 rounded-lg px-4 py-2">
              <span className="text-sm text-green-300">
                Profitable strategy detected (PF {stats.profit_factor.toFixed(1)}, {stats.win_rate.toFixed(0)}% WR).
              </span>
              <Button
                onClick={() => setShowCreateAgent(true)}
                size="sm"
                className="bg-green-600 hover:bg-green-500 text-white"
              >
                <Rocket className="h-3.5 w-3.5" /> Deploy as Agent
              </Button>
            </div>
          )}

          {/* Stats Grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3">
            <StatCard label="Total Trades" value={String(stats.total_trades)} />
            <StatCard
              label="Win Rate"
              value={`${stats.win_rate.toFixed(1)}%`}
              color={stats.win_rate >= 50 ? 'text-green-400' : 'text-yellow-400'}
            />
            <StatCard
              label="Net Profit"
              value={`$${stats.net_profit.toFixed(2)}`}
              color={stats.net_profit >= 0 ? 'text-green-400' : 'text-red-400'}
            />
            <StatCard
              label="Profit Factor"
              value={stats.profit_factor.toFixed(2)}
              color={stats.profit_factor >= 1.5 ? 'text-green-400' : stats.profit_factor >= 1 ? 'text-yellow-400' : 'text-red-400'}
            />
            <StatCard
              label="Sharpe Ratio"
              value={stats.sharpe_ratio.toFixed(2)}
              color={stats.sharpe_ratio >= 1 ? 'text-green-400' : 'text-yellow-400'}
            />
            <StatCard
              label="Max Drawdown"
              value={`$${stats.max_drawdown.toFixed(2)}`}
              sub={`${stats.max_drawdown_pct.toFixed(1)}%`}
              color="text-red-400"
            />
            <StatCard
              label="Avg Win / Loss"
              value={`$${stats.avg_win.toFixed(2)}`}
              sub={`/ $${stats.avg_loss.toFixed(2)}`}
            />
            <StatCard
              label="Expectancy"
              value={`$${stats.expectancy.toFixed(2)}`}
              color={stats.expectancy >= 0 ? 'text-green-400' : 'text-red-400'}
            />
          </div>

          {/* V2 Engine Badge & Elapsed Time */}
          {result.engine_version === 'v2' && (
            <div className="flex items-center gap-3 text-sm">
              <Badge variant="outline" className="border-fa-accent/30 text-fa-accent font-mono">V2 Engine</Badge>
              {result.symbols && result.symbols.length > 1 && (
                <Badge variant="outline" className="border-emerald-500/30 text-emerald-400 font-mono">
                  Portfolio ({result.symbols.length} symbols: {result.symbols.join(', ')})
                </Badge>
              )}
              {result.elapsed_seconds != null && (
                <span className="text-muted-foreground/60 font-mono text-xs">{result.elapsed_seconds.toFixed(3)}s</span>
              )}
            </div>
          )}

          {/* Tabs */}
          <div className="bg-card-bg rounded-xl border border-card-border">
            <div className="flex border-b border-card-border">
              {(['equity', 'chart', 'trades', 'monthly',
                ...(result.engine_version === 'v2' ? ['tearsheet'] : []),
                ...(result.portfolio_analytics ? ['portfolio'] : []),
              ] as const).map(tab => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab as typeof activeTab)}
                  className={`px-6 py-3 text-sm font-medium transition-colors ${activeTab === tab ? 'text-fa-accent border-b-2 border-fa-accent' : 'text-muted-foreground hover:text-foreground/90'}`}
                >
                  {tab === 'equity' ? 'Equity Curve' : tab === 'chart' ? 'Trade Chart' : tab === 'trades' ? 'Trade Log' : tab === 'monthly' ? 'Monthly Returns' : tab === 'tearsheet' ? 'Tearsheet' : 'Portfolio'}
                </button>
              ))}
            </div>

            <div className="p-4">
              {activeTab === 'equity' && result.equity_curve.length > 0 && (
                <EquityCurve data={result.equity_curve} height={350} />
              )}
              {activeTab === 'chart' && chartBars.length > 0 && (
                <BacktestTradeChart
                  bars={chartBars}
                  trades={result.trades}
                  equityCurve={result.equity_curve}
                  indicatorOverlays={Object.keys(chartIndicators).length > 0 ? chartIndicators : undefined}
                  height={450}
                />
              )}
              {activeTab === 'chart' && chartBars.length === 0 && (
                <div className="flex h-[350px] items-center justify-center text-sm text-muted-foreground">
                  No chart data available for this backtest
                </div>
              )}
              {activeTab === 'trades' && (
                <TradeLog trades={result.trades} />
              )}
              {activeTab === 'monthly' && (
                <MonthlyReturns trades={result.trades} />
              )}
              {activeTab === 'tearsheet' && result.v2_stats && (
                <div className="space-y-4">
                  <h3 className="text-sm font-semibold text-foreground/80">Full V2 Metrics (55+)</h3>
                  <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                    {Object.entries(result.v2_stats)
                      .filter(([, v]) => typeof v === 'number')
                      .map(([key, val]) => (
                        <div key={key} className="bg-input-bg rounded px-3 py-2 border border-card-border">
                          <div className="text-[10px] text-muted-foreground/60 uppercase tracking-wider truncate" title={key}>
                            {key.replace(/_/g, ' ')}
                          </div>
                          <div className="text-sm font-mono text-white">
                            {typeof val === 'number' ? (Number.isInteger(val) ? val : (val as number).toFixed(4)) : String(val)}
                          </div>
                        </div>
                      ))}
                  </div>
                  {!!result.tearsheet?.monte_carlo && (
                    <div>
                      <h3 className="text-sm font-semibold text-foreground/80 mt-4 mb-2">Monte Carlo Simulation</h3>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        {Object.entries(result.tearsheet.monte_carlo as Record<string, unknown>)
                          .filter(([, v]) => typeof v === 'number')
                          .slice(0, 8)
                          .map(([key, val]) => (
                            <div key={key} className="bg-input-bg rounded px-3 py-2 border border-card-border">
                              <div className="text-[10px] text-muted-foreground/60 uppercase tracking-wider truncate" title={key}>{key.replace(/_/g, ' ')}</div>
                              <div className="text-sm font-mono text-white">{(val as number).toFixed(2)}</div>
                            </div>
                          ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Portfolio Analytics Tab (Phase 4) */}
              {activeTab === 'portfolio' && result.portfolio_analytics && (() => {
                const pa = result.portfolio_analytics;
                return (
                  <div className="space-y-6">
                    {/* Portfolio Summary */}
                    <div className="flex items-center gap-4">
                      <span className="px-3 py-1 rounded-full bg-emerald-900/40 text-emerald-400 text-xs font-bold">
                        {pa.num_symbols} Symbols
                      </span>
                      <span className="text-sm text-foreground/80">
                        Diversification Ratio: <span className="font-mono font-bold text-white">{pa.diversification_ratio.toFixed(2)}</span>
                        {pa.diversification_ratio > 1 && <span className="text-emerald-400 ml-1">(risk reduction active)</span>}
                      </span>
                      <span className="text-sm text-foreground/80">
                        Avg Correlation: <span className="font-mono font-bold text-white">{pa.correlation.avg_correlation.toFixed(3)}</span>
                      </span>
                    </div>

                    {/* Per-Symbol Breakdown */}
                    <div>
                      <h3 className="text-sm font-semibold text-foreground/80 mb-2">Per-Symbol Breakdown</h3>
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="text-muted-foreground border-b border-card-border">
                              <th className="text-left p-2">Symbol</th>
                              <th className="text-right p-2">Trades</th>
                              <th className="text-right p-2">Win %</th>
                              <th className="text-right p-2">Net P&L</th>
                              <th className="text-right p-2">PF</th>
                              <th className="text-right p-2">Avg Win</th>
                              <th className="text-right p-2">Avg Loss</th>
                              <th className="text-right p-2">Sharpe</th>
                            </tr>
                          </thead>
                          <tbody>
                            {Object.entries(pa.per_symbol).map(([sym, st]) => (
                              <tr key={sym} className="border-b border-card-border/50 hover:bg-muted/30">
                                <td className="p-2 text-white font-semibold">{sym}</td>
                                <td className="p-2 text-right text-foreground/80">{st.total_trades}</td>
                                <td className="p-2 text-right text-foreground/80">{st.win_rate}%</td>
                                <td className={`p-2 text-right font-mono font-bold ${st.net_profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                  ${st.net_profit.toFixed(2)}
                                </td>
                                <td className="p-2 text-right text-foreground/80">{st.profit_factor}</td>
                                <td className="p-2 text-right text-green-400 font-mono">${st.avg_win.toFixed(2)}</td>
                                <td className="p-2 text-right text-red-400 font-mono">${st.avg_loss.toFixed(2)}</td>
                                <td className="p-2 text-right text-foreground/80 font-mono">{st.sharpe_per_trade.toFixed(2)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>

                    {/* Correlation Matrix */}
                    {pa.correlation.symbols.length > 1 && (
                      <div>
                        <h3 className="text-sm font-semibold text-foreground/80 mb-2">Correlation Matrix</h3>
                        <div className="overflow-x-auto">
                          <table className="text-xs">
                            <thead>
                              <tr>
                                <th className="p-2 text-muted-foreground"></th>
                                {pa.correlation.symbols.map(s => (
                                  <th key={s} className="p-2 text-muted-foreground min-w-[70px]">{s}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {pa.correlation.symbols.map((sym, i) => (
                                <tr key={sym}>
                                  <td className="p-2 text-muted-foreground font-bold">{sym}</td>
                                  {pa.correlation.matrix[i].map((val, j) => {
                                    const isOnDiag = i === j;
                                    const absVal = Math.abs(val);
                                    const color = isOnDiag
                                      ? 'rgba(59,130,246,0.3)'
                                      : val >= 0
                                        ? `rgba(239,68,68,${0.1 + absVal * 0.6})`
                                        : `rgba(34,197,94,${0.1 + absVal * 0.6})`;
                                    return (
                                      <td key={j} className="p-2 text-center font-mono rounded" style={{ backgroundColor: color }}>
                                        <span className={isOnDiag ? 'text-fa-accent/80' : val >= 0.5 ? 'text-red-300' : val <= -0.3 ? 'text-green-300' : 'text-foreground/80'}>
                                          {val.toFixed(2)}
                                        </span>
                                      </td>
                                    );
                                  })}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          <p className="text-[10px] text-muted-foreground/40 mt-1">
                            Red = positive correlation (less diversification) | Green = negative correlation (more diversification)
                          </p>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          </div>

      {/* Walk-Forward Results */}
      {wfResult && (
        <div className="bg-card-bg rounded-xl border border-purple-800/50 p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-purple-300">Walk-Forward Validation (Out-of-Sample)</h2>
              <p className="text-xs text-muted-foreground mt-1">{wfResult.n_folds} folds, {wfResult.mode} window</p>
            </div>
            <div className="flex items-center gap-3">
              <span className={`text-sm font-bold px-3 py-1 rounded-full ${wfResult.consistency_score === 100 ? 'bg-green-900/40 text-green-400' : wfResult.consistency_score >= 60 ? 'bg-yellow-900/40 text-yellow-400' : 'bg-red-900/40 text-red-400'}`}>
                {wfResult.consistency_score}% Consistent
              </span>
              {wfResult.oos_profit_factor > 1.2 && wfResult.consistency_score >= 80 && (
                <button
                  onClick={() => setShowCreateAgent(true)}
                  className="px-4 py-1.5 rounded-lg bg-green-600 hover:bg-green-500 text-white text-sm font-semibold transition-colors"
                >
                  + Deploy as Agent
                </button>
              )}
            </div>
          </div>

          {/* OOS Stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3">
            <StatCard label="OOS Trades" value={String(wfResult.oos_total_trades)} />
            <StatCard label="OOS Win Rate" value={`${wfResult.oos_win_rate}%`}
              color={wfResult.oos_win_rate >= 50 ? 'text-green-400' : 'text-yellow-400'} />
            <StatCard label="OOS Net Profit" value={`$${wfResult.oos_net_profit.toFixed(2)}`}
              color={wfResult.oos_net_profit >= 0 ? 'text-green-400' : 'text-red-400'} />
            <StatCard label="OOS Profit Factor" value={wfResult.oos_profit_factor.toFixed(2)}
              color={wfResult.oos_profit_factor >= 1.5 ? 'text-green-400' : wfResult.oos_profit_factor >= 1 ? 'text-yellow-400' : 'text-red-400'} />
            <StatCard label="OOS Sharpe" value={wfResult.oos_sharpe_ratio.toFixed(2)}
              color={wfResult.oos_sharpe_ratio >= 1 ? 'text-green-400' : 'text-yellow-400'} />
            <StatCard label="OOS Max DD" value={`$${wfResult.oos_max_drawdown.toFixed(2)}`}
              sub={`${wfResult.oos_max_drawdown_pct.toFixed(1)}%`} color="text-red-400" />
            <StatCard label="OOS Avg Win/Loss" value={`$${wfResult.oos_avg_win.toFixed(2)}`}
              sub={`/ $${wfResult.oos_avg_loss.toFixed(2)}`} />
            <StatCard label="OOS Expectancy" value={`$${wfResult.oos_expectancy.toFixed(2)}`}
              color={wfResult.oos_expectancy >= 0 ? 'text-green-400' : 'text-red-400'} />
          </div>

          {/* Per-Fold Breakdown */}
          <div>
            <h3 className="text-sm font-semibold text-foreground/80 mb-2">Per-Fold OOS Performance</h3>
            <div className="grid grid-cols-5 gap-2">
              {wfResult.windows?.map((w: any) => (
                <div key={w.fold} className={`rounded-lg p-3 border text-center ${w.test_stats.net_profit >= 0 ? 'border-green-800/50 bg-green-900/10' : 'border-red-800/50 bg-red-900/10'}`}>
                  <div className="text-xs text-muted-foreground">Fold {w.fold}</div>
                  <div className="text-sm font-bold text-white mt-1">{w.test_stats.win_rate}% WR</div>
                  <div className={`text-xs font-mono ${w.test_stats.net_profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    ${w.test_stats.net_profit?.toFixed(0)}
                  </div>
                  <div className="text-xs text-muted-foreground/60">PF {w.test_stats.profit_factor?.toFixed(1)}</div>
                  <div className="text-xs text-muted-foreground/40">{w.test_stats.total_trades} trades</div>
                </div>
              ))}
            </div>
          </div>

          {/* OOS Equity Curve */}
          {wfResult.oos_equity_curve?.length > 2 && (
            <div>
              <h3 className="text-sm font-semibold text-foreground/80 mb-2">OOS Equity Curve (all folds concatenated)</h3>
              <EquityCurve data={wfResult.oos_equity_curve} height={250} />
            </div>
          )}
        </div>
      )}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center h-full text-center text-muted-foreground p-8">
          <BarChart3 className="h-16 w-16 mb-4 opacity-20" />
          <p className="text-lg font-medium text-foreground/60">No Results Yet</p>
          <p className="text-sm mt-1">Configure and run a backtest to see results here</p>
        </div>
      )}
          </div>
        </ResizablePanel>
      </ResizablePanelGroup>

      {/* Deploy as Agent Modal */}
      {showCreateAgent && (() => {
        const ds = datasources.find(d => d.id === datasourceId);
        const deploySymbol = ds?.symbol || 'Unknown';
        const connectedBrokers = accounts.filter(a => a.connected);
        return (
          <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center" onClick={() => setShowCreateAgent(false)}>
            <div className="bg-input-bg rounded-xl border border-input-border p-6 w-full max-w-md" onClick={e => e.stopPropagation()}>
              <h3 className="text-lg font-bold text-white mb-4">Deploy Strategy as Agent</h3>
              <form onSubmit={e => {
                e.preventDefault();
                const fd = new FormData(e.currentTarget);
                const mlVal = fd.get('ml_model_id') as string;
                deployAsAgent(
                  fd.get('name') as string,
                  fd.get('mode') as string,
                  fd.get('timeframe') as string,
                  mlVal ? Number(mlVal) : null,
                  fd.get('broker_name') as string,
                  Number(fd.get('lot_size')) || 0.01,
                );
              }} className="space-y-3">
                {/* Symbol (read-only from datasource) */}
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Symbol</label>
                  <div className="w-full bg-card-bg border border-input-border rounded-lg px-3 py-2 text-accent text-sm font-mono">
                    {deploySymbol}
                  </div>
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Agent Name</label>
                  <input name="name" required defaultValue={`WF-Agent-${Date.now().toString(36)}`}
                    className="w-full bg-card-bg border border-input-border rounded-lg px-3 py-2 text-white text-sm" />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-muted-foreground mb-1">Broker</label>
                    <select name="broker_name" defaultValue={activeBroker || ''} className="w-full bg-card-bg border border-input-border rounded-lg px-3 py-2 text-white text-sm">
                      {connectedBrokers.length > 0
                        ? connectedBrokers.map(a => (
                          <option key={a.broker} value={a.broker}>{a.broker}</option>
                        ))
                        : <option value="">No brokers connected</option>
                      }
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-muted-foreground mb-1">Lot Size</label>
                    <input name="lot_size" type="number" step="0.01" min="0.01" defaultValue="0.01" required
                      className="w-full bg-card-bg border border-input-border rounded-lg px-3 py-2 text-white text-sm" />
                  </div>
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Mode</label>
                  <select name="mode" defaultValue="paper" className="w-full bg-card-bg border border-input-border rounded-lg px-3 py-2 text-white text-sm">
                    <option value="paper">Paper Trading (simulated, no real trades)</option>
                    <option value="confirmation">Confirm Trade (approve each trade before execution)</option>
                    <option value="auto">Fully Autonomous (executes trades automatically)</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Timeframe</label>
                  <select name="timeframe" defaultValue="M10" className="w-full bg-card-bg border border-input-border rounded-lg px-3 py-2 text-white text-sm">
                    <option value="M1">M1</option>
                    <option value="M5">M5</option>
                    <option value="M10">M10</option>
                    <option value="M15">M15</option>
                    <option value="M30">M30</option>
                    <option value="H1">H1</option>
                    <option value="H4">H4</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">ML Model (optional)</label>
                  <select name="ml_model_id" defaultValue="" className="w-full bg-card-bg border border-input-border rounded-lg px-3 py-2 text-white text-sm">
                    <option value="">None — pure strategy signals</option>
                    {mlModels.map(m => (
                      <option key={m.id} value={m.id}>
                        {m.name} {m.val_accuracy ? `(${(m.val_accuracy * 100).toFixed(1)}% acc)` : ''}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="flex gap-2 pt-2">
                  <button type="button" onClick={() => setShowCreateAgent(false)}
                    className="flex-1 px-4 py-2 rounded-lg border border-input-border text-foreground/80 hover:bg-muted text-sm">
                    Cancel
                  </button>
                  <button type="submit"
                    className="flex-1 px-4 py-2 rounded-lg bg-green-600 hover:bg-green-500 text-white font-semibold text-sm">
                    Create Agent
                  </button>
                </div>
              </form>
            </div>
          </div>
        );
      })()}

      {settingsStrategy && (
        <StrategySettingsModal
          strategy={settingsStrategy}
          onClose={() => setSettingsStrategy(null)}
          onSaved={(updated) => {
            setStrategies(prev => prev.map(s => s.id === updated.id ? updated : s));
            setSettingsStrategy(null);
          }}
        />
      )}

      <ChatHelpers />
    </div>
  );
}
