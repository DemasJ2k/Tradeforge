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
    <div className="bg-[#1a1f2e] rounded-lg p-4 border border-gray-800">
      <div className="text-xs text-gray-400 uppercase tracking-wider mb-1">{label}</div>
      <div className={`text-xl font-bold ${color || 'text-white'}`}>{value}</div>
      {sub && <div className="text-xs text-gray-500 mt-1">{sub}</div>}
    </div>
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
    ctx.fillStyle = '#0f1219';
    ctx.fillRect(0, 0, w, h);

    // Grid lines
    ctx.strokeStyle = '#1a1f2e';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = pad / 2 + ((h - pad) * i) / 4;
      ctx.beginPath();
      ctx.moveTo(pad, y);
      ctx.lineTo(w - 10, y);
      ctx.stroke();

      // Y-axis labels
      const val = max - (range * i) / 4;
      ctx.fillStyle = '#6b7280';
      ctx.font = '11px monospace';
      ctx.textAlign = 'right';
      ctx.fillText(`$${val.toFixed(0)}`, pad - 5, y + 4);
    }

    // Initial balance line
    const initialY = pad / 2 + ((max - data[0]) / range) * (h - pad);
    ctx.strokeStyle = '#374151';
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
    ctx.strokeStyle = isProfit ? '#22c55e' : '#ef4444';
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
            <tr className="text-gray-400 border-b border-gray-800">
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
              <tr key={idx} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                <td className="p-2 text-gray-500">{page * perPage + idx + 1}</td>
                <td className="p-2 text-gray-300 font-mono text-xs">{fmtTime(t.entry_time)}</td>
                <td className="p-2">
                  <span className={`px-2 py-0.5 rounded text-xs font-bold ${t.direction === 'long' ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'}`}>
                    {t.direction.toUpperCase()}
                  </span>
                </td>
                <td className="p-2 text-right font-mono text-gray-300">{t.entry_price.toFixed(2)}</td>
                <td className="p-2 text-right font-mono text-gray-500">{t.stop_loss.toFixed(2)}</td>
                <td className="p-2 text-right font-mono text-gray-500">{t.take_profit.toFixed(2)}</td>
                <td className="p-2 text-right font-mono text-gray-300">{t.exit_price?.toFixed(2) || '-'}</td>
                <td className="p-2">
                  <span className={`text-xs ${t.exit_reason === 'take_profit' ? 'text-green-400' : t.exit_reason === 'stop_loss' ? 'text-red-400' : 'text-gray-400'}`}>
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
          <span className="text-sm text-gray-400">
            Showing {page * perPage + 1}-{Math.min((page + 1) * perPage, trades.length)} of {trades.length}
          </span>
          <div className="flex gap-2">
            <button onClick={() => setPage(Math.max(0, page - 1))} disabled={page === 0}
              className="px-3 py-1 rounded bg-gray-800 text-gray-300 disabled:opacity-30 hover:bg-gray-700 text-sm">
              Prev
            </button>
            <button onClick={() => setPage(Math.min(totalPages - 1, page + 1))} disabled={page >= totalPages - 1}
              className="px-3 py-1 rounded bg-gray-800 text-gray-300 disabled:opacity-30 hover:bg-gray-700 text-sm">
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
            <th className="p-1 text-gray-400"></th>
            {months.map(m => <th key={m} className="p-1 text-gray-400 min-w-[50px]">{m}</th>)}
            <th className="p-1 text-gray-400 min-w-[60px]">Total</th>
          </tr>
        </thead>
        <tbody>
          {years.map(yr => {
            let yearTotal = 0;
            return (
              <tr key={yr}>
                <td className="p-1 text-gray-400 font-bold">{yr}</td>
                {months.map((_, mi) => {
                  const key = `${yr}-${String(mi + 1).padStart(2, '0')}`;
                  const val = monthly[key];
                  if (val !== undefined) yearTotal += val;
                  if (val === undefined) return <td key={mi} className="p-1 text-center text-gray-700">-</td>;
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
  const [initialBalance, setInitialBalance] = useState(10000);
  const [spreadPoints, setSpreadPoints] = useState(0.3);
  const [commission, setCommission] = useState(7.0);
  const [pointValue, setPointValue] = useState(1.0);

  const [running, setRunning] = useState(false);
  const [runningWF, setRunningWF] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<BacktestResponse | null>(null);
  const [wfResult, setWfResult] = useState<any>(null);
  const [activeTab, setActiveTab] = useState<'equity' | 'trades' | 'monthly'>('equity');
  const [showCreateAgent, setShowCreateAgent] = useState(false);

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
        }),
      });

      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(err.detail || `Error ${r.status}`);
      }

      const data: BacktestResponse = await r.json();
      setResult(data);

      fetch(`${API}/api/backtest`, { headers: authHeaders() })
        .then(r => r.json())
        .then(d => setHistory(Array.isArray(d) ? d : []))
        .catch(() => {});
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Backtest failed');
    } finally {
      setRunning(false);
    }
  }, [strategyId, datasourceId, initialBalance, spreadPoints, commission, pointValue]);

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

  const deployAsAgent = useCallback(async (name: string, mode: string, timeframe: string, mlModelId: number | null) => {
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

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Backtesting</h1>
          <p className="text-gray-400 text-sm mt-1">Test strategies against historical data</p>
        </div>
      </div>

      {/* Config Form */}
      <div className="bg-[#151923] rounded-xl border border-gray-800 p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Configuration</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          <div className="col-span-2 lg:col-span-2">
            <label className="block text-xs text-gray-400 mb-1">Strategy</label>
            <select
              value={strategyId}
              onChange={e => setStrategyId(e.target.value ? Number(e.target.value) : '')}
              className="w-full bg-[#1a1f2e] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-blue-500 focus:outline-none"
            >
              <option value="">Select strategy...</option>
              {strategies.map(s => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </div>
          <div className="col-span-2 lg:col-span-2">
            <label className="block text-xs text-gray-400 mb-1">Data Source</label>
            <select
              value={datasourceId}
              onChange={e => setDatasourceId(e.target.value ? Number(e.target.value) : '')}
              className="w-full bg-[#1a1f2e] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-blue-500 focus:outline-none"
            >
              <option value="">Select data source...</option>
              {datasources.map(d => (
                <option key={d.id} value={d.id}>
                  {d.symbol} {d.timeframe} ({d.row_count?.toLocaleString()} bars)
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Balance ($)</label>
            <input type="number" value={initialBalance}
              onChange={e => setInitialBalance(Number(e.target.value))}
              className="w-full bg-[#1a1f2e] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Spread (pts)</label>
            <input type="number" step="0.1" value={spreadPoints}
              onChange={e => setSpreadPoints(Number(e.target.value))}
              className="w-full bg-[#1a1f2e] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Commission ($)</label>
            <input type="number" step="0.5" value={commission}
              onChange={e => setCommission(Number(e.target.value))}
              className="w-full bg-[#1a1f2e] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Point Value</label>
            <input type="number" step="0.01" value={pointValue}
              onChange={e => setPointValue(Number(e.target.value))}
              className="w-full bg-[#1a1f2e] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
          <div className="flex items-end col-span-2 lg:col-span-2 gap-2">
            <button
              onClick={runBacktest}
              disabled={running || runningWF || !strategyId || !datasourceId}
              className="flex-1 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white font-semibold text-sm transition-colors"
            >
              {running ? (
                <span className="flex items-center justify-center gap-2">
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Running...
                </span>
              ) : '▶ Backtest'}
            </button>
            <button
              onClick={runWalkForward}
              disabled={running || runningWF || !strategyId || !datasourceId}
              className="flex-1 px-4 py-2 rounded-lg bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 disabled:text-gray-500 text-white font-semibold text-sm transition-colors"
            >
              {runningWF ? (
                <span className="flex items-center justify-center gap-2">
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Validating...
                </span>
              ) : '⟳ Walk-Forward'}
            </button>
          </div>
        </div>
        {error && <div className="mt-3 text-red-400 text-sm bg-red-900/20 rounded-lg px-4 py-2">{error}</div>}
      </div>

      {/* Results */}
      {stats && result && (
        <>
          {/* Action bar */}
          {stats.profit_factor > 1.2 && stats.total_trades >= 10 && (
            <div className="flex items-center justify-between bg-green-900/20 border border-green-800/40 rounded-lg px-4 py-2">
              <span className="text-sm text-green-300">
                Profitable strategy detected (PF {stats.profit_factor.toFixed(1)}, {stats.win_rate.toFixed(0)}% WR). Run Walk-Forward validation for realistic OOS estimates, then deploy.
              </span>
              <button
                onClick={() => setShowCreateAgent(true)}
                className="px-4 py-1.5 rounded-lg bg-green-600 hover:bg-green-500 text-white text-sm font-semibold transition-colors whitespace-nowrap ml-3"
              >
                + Deploy as Agent
              </button>
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

          {/* Tabs */}
          <div className="bg-[#151923] rounded-xl border border-gray-800">
            <div className="flex border-b border-gray-800">
              {(['equity', 'trades', 'monthly'] as const).map(tab => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={`px-6 py-3 text-sm font-medium transition-colors ${activeTab === tab ? 'text-blue-400 border-b-2 border-blue-400' : 'text-gray-400 hover:text-gray-200'}`}
                >
                  {tab === 'equity' ? 'Equity Curve' : tab === 'trades' ? 'Trade Log' : 'Monthly Returns'}
                </button>
              ))}
            </div>

            <div className="p-4">
              {activeTab === 'equity' && result.equity_curve.length > 0 && (
                <EquityCurve data={result.equity_curve} height={350} />
              )}
              {activeTab === 'trades' && (
                <TradeLog trades={result.trades} />
              )}
              {activeTab === 'monthly' && (
                <MonthlyReturns trades={result.trades} />
              )}
            </div>
          </div>
        </>
      )}

      {/* Walk-Forward Results */}
      {wfResult && (
        <div className="bg-[#151923] rounded-xl border border-purple-800/50 p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-purple-300">Walk-Forward Validation (Out-of-Sample)</h2>
              <p className="text-xs text-gray-400 mt-1">{wfResult.n_folds} folds, {wfResult.mode} window</p>
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
            <h3 className="text-sm font-semibold text-gray-300 mb-2">Per-Fold OOS Performance</h3>
            <div className="grid grid-cols-5 gap-2">
              {wfResult.windows?.map((w: any) => (
                <div key={w.fold} className={`rounded-lg p-3 border text-center ${w.test_stats.net_profit >= 0 ? 'border-green-800/50 bg-green-900/10' : 'border-red-800/50 bg-red-900/10'}`}>
                  <div className="text-xs text-gray-400">Fold {w.fold}</div>
                  <div className="text-sm font-bold text-white mt-1">{w.test_stats.win_rate}% WR</div>
                  <div className={`text-xs font-mono ${w.test_stats.net_profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    ${w.test_stats.net_profit?.toFixed(0)}
                  </div>
                  <div className="text-xs text-gray-500">PF {w.test_stats.profit_factor?.toFixed(1)}</div>
                  <div className="text-xs text-gray-600">{w.test_stats.total_trades} trades</div>
                </div>
              ))}
            </div>
          </div>

          {/* OOS Equity Curve */}
          {wfResult.oos_equity_curve?.length > 2 && (
            <div>
              <h3 className="text-sm font-semibold text-gray-300 mb-2">OOS Equity Curve (all folds concatenated)</h3>
              <EquityCurve data={wfResult.oos_equity_curve} height={250} />
            </div>
          )}
        </div>
      )}

      {/* Deploy as Agent Modal */}
      {showCreateAgent && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center" onClick={() => setShowCreateAgent(false)}>
          <div className="bg-[#1a1f2e] rounded-xl border border-gray-700 p-6 w-full max-w-md" onClick={e => e.stopPropagation()}>
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
              );
            }} className="space-y-3">
              <div>
                <label className="block text-xs text-gray-400 mb-1">Agent Name</label>
                <input name="name" required defaultValue={`WF-Agent-${Date.now().toString(36)}`}
                  className="w-full bg-[#0f1219] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm" />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">Mode</label>
                <select name="mode" defaultValue="paper" className="w-full bg-[#0f1219] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm">
                  <option value="paper">Paper Trading (simulated, no real trades)</option>
                  <option value="confirmation">Confirm Trade (approve each trade before execution)</option>
                  <option value="auto">Fully Autonomous (executes trades automatically)</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">Timeframe</label>
                <select name="timeframe" defaultValue="M10" className="w-full bg-[#0f1219] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm">
                  <option value="M1">M1</option>
                  <option value="M5">M5</option>
                  <option value="M10">M10</option>
                  <option value="M15">M15</option>
                  <option value="H1">H1</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">ML Model (optional)</label>
                <select name="ml_model_id" defaultValue="" className="w-full bg-[#0f1219] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm">
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
                  className="flex-1 px-4 py-2 rounded-lg border border-gray-600 text-gray-300 hover:bg-gray-800 text-sm">
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
      )}

      {/* History */}
      {history.length > 0 && (
        <div className="bg-[#151923] rounded-xl border border-gray-800 p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Previous Backtests</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-400 border-b border-gray-800">
                  <th className="text-left p-2">ID</th>
                  <th className="text-left p-2">Symbol</th>
                  <th className="text-left p-2">TF</th>
                  <th className="text-right p-2">Trades</th>
                  <th className="text-right p-2">Win %</th>
                  <th className="text-right p-2">Net P&L</th>
                  <th className="text-right p-2">PF</th>
                  <th className="text-left p-2">Date</th>
                </tr>
              </thead>
              <tbody>
                {history.map(bt => (
                  <tr key={bt.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                    <td className="p-2 text-gray-500">#{bt.id}</td>
                    <td className="p-2 text-white font-semibold">{bt.symbol}</td>
                    <td className="p-2 text-gray-300">{bt.timeframe}</td>
                    <td className="p-2 text-right text-gray-300">{bt.stats.total_trades || 0}</td>
                    <td className="p-2 text-right text-gray-300">{(bt.stats.win_rate || 0).toFixed(1)}%</td>
                    <td className={`p-2 text-right font-mono font-bold ${(bt.stats.net_profit || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      ${(bt.stats.net_profit || 0).toFixed(2)}
                    </td>
                    <td className="p-2 text-right text-gray-300">{(bt.stats.profit_factor || 0).toFixed(2)}</td>
                    <td className="p-2 text-gray-500 text-xs">{bt.created_at?.slice(0, 19).replace('T', ' ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <ChatHelpers />
    </div>
  );
}
