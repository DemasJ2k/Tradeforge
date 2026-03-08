'use client';

/**
 * TearsheetPanel — Full quantstats-style tearsheet with:
 *   - Grouped metric sections (performance, risk, risk-adjusted, trading)
 *   - Drawdown chart (canvas)
 *   - Trade P/L distribution histogram (canvas)
 *   - Exit reason breakdown
 */

import { useRef, useEffect, useMemo, useState, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
import type { BacktestStats, TradeResult } from '@/types';

interface MonteCarloResult {
  n_simulations: number;
  final_equity: { p5: number; p25: number; p50: number; p75: number; p95: number };
  max_drawdown: { p5: number; p25: number; p50: number; p75: number; p95: number };
  max_drawdown_pct: { p5: number; p25: number; p50: number; p75: number; p95: number };
  prob_ruin: number;
  equity_paths: number[][];
}

interface Props {
  stats: BacktestStats;
  v2Stats: Record<string, unknown>;
  trades: TradeResult[];
  equityCurve: number[];
  backtestId?: number;
}

/* ──────────────────────────────────────────────────────────────────── */
/*  Helpers                                                            */
/* ──────────────────────────────────────────────────────────────────── */

function fmt(v: unknown, dp = 2, suffix = ''): string {
  if (v === null || v === undefined) return '—';
  const n = Number(v);
  if (isNaN(n)) return '—';
  return `${n.toFixed(dp)}${suffix}`;
}

function pct(v: unknown, dp = 2): string {
  return fmt(v, dp, '%');
}

function usd(v: unknown, dp = 2): string {
  if (v === null || v === undefined) return '—';
  const n = Number(v);
  if (isNaN(n)) return '—';
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;
}

/* ──────────────────────────────────────────────────────────────────── */
/*  Metric helpers — derived from what we have                         */
/* ──────────────────────────────────────────────────────────────────── */

function computeDerived(stats: BacktestStats, v2: Record<string, unknown>, trades: TradeResult[], eq: number[]) {
  const initial = (Number(v2.initial_balance) || eq[0] || 10000);
  const final = (Number(v2.final_balance) || eq[eq.length - 1] || initial);
  const totalReturn = ((final - initial) / initial) * 100;

  // Drawdown series from equity curve
  const drawdowns: number[] = [];
  let peak = eq[0] || initial;
  for (const val of eq) {
    if (val > peak) peak = val;
    drawdowns.push(((val - peak) / peak) * 100);
  }

  // Trade P/L array
  const pnls = trades.map(t => t.pnl).filter(v => typeof v === 'number' && !isNaN(v));

  // Win / loss streaks (from v2 or compute)
  let maxWinStreak = Number(v2.max_consecutive_wins) || 0;
  let maxLossStreak = Number(v2.max_consecutive_losses) || 0;
  if (!maxWinStreak && trades.length) {
    let ws = 0, ls = 0;
    for (const t of trades) {
      if (t.pnl > 0) { ws++; ls = 0; maxWinStreak = Math.max(maxWinStreak, ws); }
      else { ls++; ws = 0; maxLossStreak = Math.max(maxLossStreak, ls); }
    }
  }

  // Exit reason breakdown
  const exitReasons: Record<string, number> = {};
  for (const t of trades) {
    const reason = t.exit_reason || 'unknown';
    exitReasons[reason] = (exitReasons[reason] || 0) + 1;
  }

  // Long / short split
  const longTrades = trades.filter(t => t.direction === 'long');
  const shortTrades = trades.filter(t => t.direction === 'short');
  const longWins = longTrades.filter(t => t.pnl > 0).length;
  const shortWins = shortTrades.filter(t => t.pnl > 0).length;

  return {
    initial, final, totalReturn,
    drawdowns, pnls,
    maxWinStreak, maxLossStreak,
    exitReasons,
    longTrades: longTrades.length,
    shortTrades: shortTrades.length,
    longWinRate: longTrades.length ? (longWins / longTrades.length * 100) : 0,
    shortWinRate: shortTrades.length ? (shortWins / shortTrades.length * 100) : 0,
  };
}

/* ──────────────────────────────────────────────────────────────────── */
/*  Mini canvas charts                                                 */
/* ──────────────────────────────────────────────────────────────────── */

function DrawdownChart({ drawdowns }: { drawdowns: number[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || drawdowns.length < 2) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);

    const minDD = Math.min(...drawdowns);
    const range = Math.abs(minDD) || 1;

    // Background
    ctx.fillStyle = '#0f1219';
    ctx.fillRect(0, 0, w, h);

    // Grid lines
    ctx.strokeStyle = '#1e293b';
    ctx.lineWidth = 0.5;
    ctx.font = '9px monospace';
    ctx.fillStyle = '#6b7280';
    for (let i = 0; i <= 4; i++) {
      const y = (i / 4) * h;
      ctx.beginPath();
      ctx.moveTo(40, y);
      ctx.lineTo(w, y);
      ctx.stroke();
      const label = (-(i / 4) * range).toFixed(1) + '%';
      ctx.fillText(label, 2, y + 3);
    }

    // Drawdown area fill
    ctx.beginPath();
    ctx.moveTo(40, 0);
    for (let i = 0; i < drawdowns.length; i++) {
      const x = 40 + (i / (drawdowns.length - 1)) * (w - 40);
      const y = (Math.abs(drawdowns[i]) / range) * h;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.lineTo(w, 0);
    ctx.closePath();
    ctx.fillStyle = 'rgba(239, 68, 68, 0.15)';
    ctx.fill();

    // Drawdown line
    ctx.beginPath();
    for (let i = 0; i < drawdowns.length; i++) {
      const x = 40 + (i / (drawdowns.length - 1)) * (w - 40);
      const y = (Math.abs(drawdowns[i]) / range) * h;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.strokeStyle = '#ef4444';
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }, [drawdowns]);

  return (
    <canvas
      ref={canvasRef}
      className="w-full rounded-lg border border-card-border"
      style={{ height: 160 }}
    />
  );
}

function PnlHistogram({ pnls }: { pnls: number[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || pnls.length < 2) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);

    ctx.fillStyle = '#0f1219';
    ctx.fillRect(0, 0, w, h);

    // Bin the PnLs
    const sorted = [...pnls].sort((a, b) => a - b);
    const min = sorted[0];
    const max = sorted[sorted.length - 1];
    const binCount = Math.min(30, Math.max(8, Math.ceil(Math.sqrt(pnls.length))));
    const binWidth = (max - min) / binCount || 1;
    const bins: number[] = new Array(binCount).fill(0);

    for (const v of pnls) {
      let idx = Math.floor((v - min) / binWidth);
      if (idx >= binCount) idx = binCount - 1;
      if (idx < 0) idx = 0;
      bins[idx]++;
    }

    const maxBin = Math.max(...bins, 1);
    const barW = (w - 50) / binCount;
    const chartH = h - 20;

    // Zero line
    const zeroIdx = min >= 0 ? -1 : Math.floor((0 - min) / binWidth);
    if (zeroIdx >= 0 && zeroIdx < binCount) {
      const zeroX = 45 + zeroIdx * barW;
      ctx.strokeStyle = '#6b7280';
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(zeroX, 0);
      ctx.lineTo(zeroX, chartH);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Bars
    for (let i = 0; i < binCount; i++) {
      const barH = (bins[i] / maxBin) * chartH;
      const x = 45 + i * barW;
      const y = chartH - barH;
      const binMid = min + (i + 0.5) * binWidth;
      ctx.fillStyle = binMid >= 0 ? 'rgba(34, 197, 94, 0.7)' : 'rgba(239, 68, 68, 0.7)';
      ctx.fillRect(x + 1, y, barW - 2, barH);
    }

    // X-axis labels
    ctx.font = '9px monospace';
    ctx.fillStyle = '#6b7280';
    ctx.textAlign = 'center';
    for (let i = 0; i <= 4; i++) {
      const idx = Math.floor((i / 4) * (binCount - 1));
      const val = min + (idx + 0.5) * binWidth;
      const x = 45 + idx * barW + barW / 2;
      ctx.fillText(`$${val.toFixed(0)}`, x, h - 4);
    }
  }, [pnls]);

  return (
    <canvas
      ref={canvasRef}
      className="w-full rounded-lg border border-card-border"
      style={{ height: 160 }}
    />
  );
}

/* ──────────────────────────────────────────────────────────────────── */
/*  Exit Reason Bar                                                    */
/* ──────────────────────────────────────────────────────────────────── */

const REASON_COLORS: Record<string, string> = {
  stop_loss: '#ef4444',
  take_profit: '#22c55e',
  signal: '#3b82f6',
  end_of_data: '#6b7280',
  opposite_signal: '#eab308',
  manual: '#8b5cf6',
  trailing_stop: '#f97316',
  unknown: '#4b5563',
};

function ExitReasonBar({ exitReasons, total }: { exitReasons: Record<string, number>; total: number }) {
  if (!total) return null;
  const entries = Object.entries(exitReasons).sort((a, b) => b[1] - a[1]);

  return (
    <div className="space-y-2">
      {/* Stacked bar */}
      <div className="flex h-5 rounded-full overflow-hidden bg-card-border">
        {entries.map(([reason, count]) => (
          <div
            key={reason}
            style={{
              width: `${(count / total) * 100}%`,
              backgroundColor: REASON_COLORS[reason] || REASON_COLORS.unknown,
            }}
            title={`${reason}: ${count} (${((count / total) * 100).toFixed(1)}%)`}
          />
        ))}
      </div>
      {/* Legend */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {entries.map(([reason, count]) => (
          <span key={reason} className="flex items-center gap-1.5">
            <span
              className="w-2.5 h-2.5 rounded-full inline-block"
              style={{ backgroundColor: REASON_COLORS[reason] || REASON_COLORS.unknown }}
            />
            <span className="text-muted-foreground capitalize">
              {reason.replace(/_/g, ' ')}: {count} ({((count / total) * 100).toFixed(0)}%)
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────── */
/*  Metric row                                                         */
/* ──────────────────────────────────────────────────────────────────── */

function MetricRow({ label, value, highlight }: { label: string; value: string; highlight?: 'green' | 'red' | 'neutral' }) {
  const color = highlight === 'green' ? 'text-green-400' : highlight === 'red' ? 'text-red-400' : 'text-foreground';
  return (
    <div className="flex justify-between items-center py-1.5 border-b border-card-border/50 last:border-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className={`text-sm font-mono font-medium ${color}`}>{value}</span>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────── */
/*  Monte Carlo Equity Paths Chart                                     */
/* ──────────────────────────────────────────────────────────────────── */

function MonteCarloChart({ paths, initial }: { paths: number[][]; initial: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || paths.length === 0) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);

    ctx.fillStyle = '#0f1219';
    ctx.fillRect(0, 0, w, h);

    // Find global min/max
    let gMin = initial, gMax = initial;
    for (const path of paths) {
      for (const v of path) {
        if (v < gMin) gMin = v;
        if (v > gMax) gMax = v;
      }
    }
    const range = gMax - gMin || 1;
    const maxLen = Math.max(...paths.map(p => p.length));

    // Grid
    ctx.strokeStyle = '#1e293b';
    ctx.lineWidth = 0.5;
    ctx.font = '9px monospace';
    ctx.fillStyle = '#6b7280';
    for (let i = 0; i <= 4; i++) {
      const y = h - (i / 4) * h;
      ctx.beginPath();
      ctx.moveTo(50, y);
      ctx.lineTo(w, y);
      ctx.stroke();
      const val = gMin + (i / 4) * range;
      ctx.fillText(`$${val.toFixed(0)}`, 2, y + 3);
    }

    // Draw paths
    const colors = ['rgba(59,130,246,0.3)', 'rgba(34,197,94,0.25)', 'rgba(168,85,247,0.25)', 'rgba(249,115,22,0.25)', 'rgba(236,72,153,0.25)'];
    for (let p = 0; p < paths.length; p++) {
      const path = paths[p];
      ctx.beginPath();
      for (let i = 0; i < path.length; i++) {
        const x = 50 + (i / (maxLen - 1)) * (w - 50);
        const y = h - ((path[i] - gMin) / range) * h;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = colors[p % colors.length];
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    // Initial balance line
    const initY = h - ((initial - gMin) / range) * h;
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = '#6b7280';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(50, initY);
    ctx.lineTo(w, initY);
    ctx.stroke();
    ctx.setLineDash([]);
  }, [paths, initial]);

  return (
    <canvas
      ref={canvasRef}
      className="w-full rounded-lg border border-card-border"
      style={{ height: 200 }}
    />
  );
}

/* ──────────────────────────────────────────────────────────────────── */
/*  Main Component                                                     */
/* ──────────────────────────────────────────────────────────────────── */

export default function TearsheetPanel({ stats, v2Stats, trades, equityCurve, backtestId }: Props) {
  const derived = useMemo(
    () => computeDerived(stats, v2Stats, trades, equityCurve),
    [stats, v2Stats, trades, equityCurve],
  );

  const v2 = v2Stats;

  // Monte Carlo state
  const [mcResult, setMcResult] = useState<MonteCarloResult | null>(null);
  const [mcLoading, setMcLoading] = useState(false);
  const [mcError, setMcError] = useState('');

  const runMonteCarlo = useCallback(async () => {
    if (!backtestId) return;
    setMcLoading(true);
    setMcError('');
    try {
      const result = await api.post<MonteCarloResult>('/api/backtest/monte-carlo', {
        backtest_id: backtestId,
        n_simulations: 1000,
      });
      setMcResult(result);
    } catch (e) {
      setMcError(e instanceof Error ? e.message : 'Monte Carlo failed');
    } finally {
      setMcLoading(false);
    }
  }, [backtestId]);

  return (
    <div className="space-y-4">
      {/* ── Row 1: Performance + Risk ────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Performance */}
        <Card className="bg-card-bg border-card-border">
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Performance</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <MetricRow label="Total Return" value={pct(derived.totalReturn)} highlight={derived.totalReturn >= 0 ? 'green' : 'red'} />
            <MetricRow label="Net P/L" value={usd(stats.net_profit)} highlight={stats.net_profit >= 0 ? 'green' : 'red'} />
            <MetricRow label="Gross Profit" value={usd(stats.gross_profit)} highlight="green" />
            <MetricRow label="Gross Loss" value={usd(stats.gross_loss)} highlight="red" />
            <MetricRow label="Initial Balance" value={usd(derived.initial)} />
            <MetricRow label="Final Balance" value={usd(derived.final)} />
          </CardContent>
        </Card>

        {/* Risk */}
        <Card className="bg-card-bg border-card-border">
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Risk</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <MetricRow label="Max Drawdown" value={usd(stats.max_drawdown)} highlight="red" />
            <MetricRow label="Max Drawdown %" value={pct(stats.max_drawdown_pct)} highlight="red" />
            <MetricRow label="Recovery Factor" value={fmt(v2.recovery_factor, 2)} />
            <MetricRow label="Largest Win" value={usd(stats.largest_win)} highlight="green" />
            <MetricRow label="Largest Loss" value={usd(stats.largest_loss)} highlight="red" />
            <MetricRow label="Negative Years" value={String(stats.negative_years ?? '—')} />
          </CardContent>
        </Card>

        {/* Risk-Adjusted Returns */}
        <Card className="bg-card-bg border-card-border">
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Risk-Adjusted</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <MetricRow label="Sharpe Ratio" value={fmt(stats.sharpe_ratio, 4)} />
            <MetricRow label="Sortino Ratio" value={fmt(v2.sortino_ratio, 4)} />
            <MetricRow label="Calmar Ratio" value={fmt(v2.calmar_ratio, 4)} />
            <MetricRow label="SQN" value={fmt(stats.sqn, 2)} />
            <MetricRow label="Profit Factor" value={fmt(stats.profit_factor, 2)} />
            <MetricRow label="Expectancy" value={usd(stats.expectancy)} />
          </CardContent>
        </Card>

        {/* Trading Statistics */}
        <Card className="bg-card-bg border-card-border">
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Trading</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <MetricRow label="Total Trades" value={String(stats.total_trades)} />
            <MetricRow label="Win Rate" value={pct(stats.win_rate)} />
            <MetricRow label="Avg Win" value={usd(stats.avg_win)} highlight="green" />
            <MetricRow label="Avg Loss" value={usd(stats.avg_loss)} highlight="red" />
            <MetricRow label="Avg Trade" value={usd(stats.avg_trade)} />
            <MetricRow label="Payoff Ratio" value={fmt(v2.payoff_ratio, 2)} />
          </CardContent>
        </Card>
      </div>

      {/* ── Row 2: Direction split + Streaks ─────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Direction Breakdown */}
        <Card className="bg-card-bg border-card-border">
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Direction Split</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <MetricRow label="Long Trades" value={String(derived.longTrades)} />
            <MetricRow label="Long Win Rate" value={pct(derived.longWinRate)} />
            <MetricRow label="Short Trades" value={String(derived.shortTrades)} />
            <MetricRow label="Short Win Rate" value={pct(derived.shortWinRate)} />
          </CardContent>
        </Card>

        {/* Streaks & Duration */}
        <Card className="bg-card-bg border-card-border">
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Streaks & Duration</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <MetricRow label="Max Consec Wins" value={String(derived.maxWinStreak)} highlight="green" />
            <MetricRow label="Max Consec Losses" value={String(derived.maxLossStreak)} highlight="red" />
            <MetricRow label="Avg Bars Held" value={fmt(v2.avg_bars_held, 1)} />
            <MetricRow label="Total Bars" value={String(stats.total_bars ?? '—')} />
          </CardContent>
        </Card>

        {/* Exit Reasons */}
        <Card className="bg-card-bg border-card-border">
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Exit Reasons</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <ExitReasonBar exitReasons={derived.exitReasons} total={stats.total_trades} />
          </CardContent>
        </Card>
      </div>

      {/* ── Row 3: Charts ────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card className="bg-card-bg border-card-border">
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Drawdown</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <DrawdownChart drawdowns={derived.drawdowns} />
          </CardContent>
        </Card>

        <Card className="bg-card-bg border-card-border">
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Trade P/L Distribution</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <PnlHistogram pnls={derived.pnls} />
          </CardContent>
        </Card>
      </div>

      {/* ── Row 4: Yearly breakdown ──────────────────────────── */}
      {stats.yearly_pnl && Object.keys(stats.yearly_pnl).length > 0 && (
        <Card className="bg-card-bg border-card-border">
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Yearly P/L</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2">
              {Object.entries(stats.yearly_pnl)
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([year, pnl]) => (
                  <div key={year} className="p-2 rounded-lg bg-background/50 border border-card-border/30 text-center">
                    <div className="text-xs text-muted-foreground">{year}</div>
                    <div className={`text-sm font-mono font-bold ${pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {usd(pnl)}
                    </div>
                  </div>
                ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Row 5: Monte Carlo Simulation ────────────────────── */}
      {backtestId && (
        <Card className="bg-card-bg border-card-border">
          <CardHeader className="pb-2 pt-3 px-4 flex flex-row items-center justify-between">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Monte Carlo Simulation</CardTitle>
            <Button
              size="sm"
              variant="outline"
              onClick={runMonteCarlo}
              disabled={mcLoading}
              className="h-7 text-xs"
            >
              {mcLoading ? 'Running...' : mcResult ? 'Re-run (1,000 sims)' : 'Run Monte Carlo'}
            </Button>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            {mcError && <p className="text-xs text-red-400 mb-2">{mcError}</p>}
            {!mcResult && !mcLoading && (
              <p className="text-xs text-muted-foreground">
                Shuffles trade order 1,000 times to estimate the range of possible outcomes (drawdown, final equity, ruin probability).
              </p>
            )}
            {mcResult && (
              <div className="space-y-4">
                {/* Equity paths chart */}
                {mcResult.equity_paths?.length > 0 && (
                  <MonteCarloChart
                    paths={mcResult.equity_paths}
                    initial={Number(v2.initial_balance) || equityCurve[0] || 10000}
                  />
                )}

                {/* Percentile tables */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  {/* Final Equity */}
                  <div className="space-y-1">
                    <h4 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Final Equity</h4>
                    {(['p5', 'p25', 'p50', 'p75', 'p95'] as const).map(k => (
                      <MetricRow
                        key={k}
                        label={k.toUpperCase()}
                        value={usd(mcResult.final_equity[k])}
                        highlight={mcResult.final_equity[k] >= (Number(v2.initial_balance) || 10000) ? 'green' : 'red'}
                      />
                    ))}
                  </div>

                  {/* Max Drawdown % */}
                  <div className="space-y-1">
                    <h4 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Max Drawdown %</h4>
                    {(['p5', 'p25', 'p50', 'p75', 'p95'] as const).map(k => (
                      <MetricRow
                        key={k}
                        label={k.toUpperCase()}
                        value={pct(mcResult.max_drawdown_pct[k])}
                        highlight="red"
                      />
                    ))}
                  </div>

                  {/* Max Drawdown $ */}
                  <div className="space-y-1">
                    <h4 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Max Drawdown $</h4>
                    {(['p5', 'p25', 'p50', 'p75', 'p95'] as const).map(k => (
                      <MetricRow
                        key={k}
                        label={k.toUpperCase()}
                        value={usd(mcResult.max_drawdown[k])}
                        highlight="red"
                      />
                    ))}
                  </div>
                </div>

                {/* Probability of Ruin */}
                <MetricRow
                  label="Probability of Ruin (50% drawdown)"
                  value={pct(mcResult.prob_ruin * 100)}
                  highlight={mcResult.prob_ruin > 0.05 ? 'red' : 'green'}
                />
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
