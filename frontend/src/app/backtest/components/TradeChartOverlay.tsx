'use client';

/**
 * TradeChartOverlay — Equity curve with trade entry/exit markers + P/L waterfall.
 *
 * Two views:
 *  1. Equity + Trades — Equity line with triangular entry/exit markers
 *  2. P/L Waterfall   — Sequential trade P/L bar chart
 */

import { useRef, useEffect, useState, useCallback, useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import type { TradeResult } from '@/types';

interface Props {
  trades: TradeResult[];
  equityCurve: number[];
}

/* ──────────────────────────────────────────────────────────────────── */
/*  Constants                                                          */
/* ──────────────────────────────────────────────────────────────────── */

const GREEN = '#22c55e';
const RED = '#ef4444';
const BLUE = '#3b82f6';
const AMBER = '#f59e0b';
const GRID_COLOR = '#1e293b';
const LABEL_COLOR = '#6b7280';
const BG = '#0f1219';

/* ──────────────────────────────────────────────────────────────────── */
/*  Equity + Trade Markers                                             */
/* ──────────────────────────────────────────────────────────────────── */

function EquityTradeChart({ equityCurve, trades }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || equityCurve.length < 2) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);

    const pad = { top: 10, right: 10, bottom: 25, left: 55 };
    const cw = w - pad.left - pad.right;
    const ch = h - pad.top - pad.bottom;

    const allVals = equityCurve;
    const min = Math.min(...allVals);
    const max = Math.max(...allVals);
    const range = max - min || 1;

    const xScale = (idx: number) => pad.left + (idx / (allVals.length - 1)) * cw;
    const yScale = (val: number) => pad.top + (1 - (val - min + range * 0.05) / (range * 1.1)) * ch;

    // BG
    ctx.fillStyle = BG;
    ctx.fillRect(0, 0, w, h);

    // Grid
    ctx.strokeStyle = GRID_COLOR;
    ctx.lineWidth = 0.5;
    ctx.font = '9px monospace';
    ctx.fillStyle = LABEL_COLOR;
    for (let i = 0; i <= 5; i++) {
      const val = min + (i / 5) * range;
      const y = yScale(val);
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(w - pad.right, y);
      ctx.stroke();
      ctx.fillText(`$${val.toFixed(0)}`, 2, y + 3);
    }

    // Equity line
    ctx.beginPath();
    for (let i = 0; i < allVals.length; i++) {
      const x = xScale(i);
      const y = yScale(allVals[i]);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.strokeStyle = '#60a5fa';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Gradient fill under equity
    const grad = ctx.createLinearGradient(0, pad.top, 0, h - pad.bottom);
    grad.addColorStop(0, 'rgba(96, 165, 250, 0.15)');
    grad.addColorStop(1, 'rgba(96, 165, 250, 0)');
    ctx.lineTo(xScale(allVals.length - 1), h - pad.bottom);
    ctx.lineTo(xScale(0), h - pad.bottom);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // Trade markers
    const maxBar = allVals.length - 1;
    for (const t of trades) {
      const entryIdx = Math.min(t.entry_bar, maxBar);
      const exitIdx = t.exit_bar != null ? Math.min(t.exit_bar, maxBar) : null;
      const isWin = t.pnl > 0;
      const isLong = t.direction === 'long';

      // Entry marker — triangle
      const ex = xScale(entryIdx);
      const ey = yScale(allVals[entryIdx] ?? min);
      ctx.fillStyle = isLong ? GREEN : RED;
      ctx.beginPath();
      if (isLong) {
        // Up triangle
        ctx.moveTo(ex, ey - 8);
        ctx.lineTo(ex - 5, ey + 2);
        ctx.lineTo(ex + 5, ey + 2);
      } else {
        // Down triangle
        ctx.moveTo(ex, ey + 8);
        ctx.lineTo(ex - 5, ey - 2);
        ctx.lineTo(ex + 5, ey - 2);
      }
      ctx.closePath();
      ctx.fill();

      // Exit marker — diamond
      if (exitIdx != null) {
        const xx = xScale(exitIdx);
        const xy = yScale(allVals[exitIdx] ?? min);
        ctx.fillStyle = isWin ? GREEN : RED;
        ctx.beginPath();
        ctx.moveTo(xx, xy - 5);
        ctx.lineTo(xx + 4, xy);
        ctx.lineTo(xx, xy + 5);
        ctx.lineTo(xx - 4, xy);
        ctx.closePath();
        ctx.fill();

        // Connecting line (entry → exit)
        ctx.strokeStyle = isWin ? 'rgba(34,197,94,0.25)' : 'rgba(239,68,68,0.25)';
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(ex, ey);
        ctx.lineTo(xx, xy);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    // Legend
    ctx.font = '10px monospace';
    const legendY = h - 6;
    ctx.fillStyle = GREEN;
    ctx.beginPath();
    ctx.moveTo(pad.left, legendY - 4);
    ctx.lineTo(pad.left - 3, legendY + 1);
    ctx.lineTo(pad.left + 3, legendY + 1);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = LABEL_COLOR;
    ctx.fillText('Long entry', pad.left + 6, legendY + 1);

    ctx.fillStyle = RED;
    ctx.beginPath();
    ctx.moveTo(pad.left + 80, legendY + 4);
    ctx.lineTo(pad.left + 77, legendY - 1);
    ctx.lineTo(pad.left + 83, legendY - 1);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = LABEL_COLOR;
    ctx.fillText('Short entry', pad.left + 86, legendY + 1);

    // Diamond legend
    ctx.fillStyle = AMBER;
    ctx.beginPath();
    ctx.moveTo(pad.left + 168, legendY - 3);
    ctx.lineTo(pad.left + 172, legendY);
    ctx.lineTo(pad.left + 168, legendY + 3);
    ctx.lineTo(pad.left + 164, legendY);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = LABEL_COLOR;
    ctx.fillText('Exit', pad.left + 176, legendY + 1);
  }, [equityCurve, trades]);

  useEffect(() => { draw(); }, [draw]);

  return (
    <canvas
      ref={canvasRef}
      className="w-full rounded-lg"
      style={{ height: 300 }}
    />
  );
}

/* ──────────────────────────────────────────────────────────────────── */
/*  P/L Waterfall                                                      */
/* ──────────────────────────────────────────────────────────────────── */

function WaterfallChart({ trades }: { trades: TradeResult[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || trades.length < 1) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);

    const pad = { top: 10, right: 10, bottom: 25, left: 55 };
    const cw = w - pad.left - pad.right;
    const ch = h - pad.top - pad.bottom;

    const pnls = trades.map(t => t.pnl);
    const cumPnl: number[] = [];
    let running = 0;
    for (const p of pnls) { running += p; cumPnl.push(running); }

    const allVals = [0, ...cumPnl];
    const min = Math.min(...allVals);
    const max = Math.max(...allVals);
    const range = max - min || 1;

    const yScale = (val: number) => pad.top + (1 - (val - min + range * 0.05) / (range * 1.1)) * ch;

    // BG
    ctx.fillStyle = BG;
    ctx.fillRect(0, 0, w, h);

    // Grid + zero line
    ctx.strokeStyle = GRID_COLOR;
    ctx.lineWidth = 0.5;
    ctx.font = '9px monospace';
    ctx.fillStyle = LABEL_COLOR;
    for (let i = 0; i <= 5; i++) {
      const val = min + (i / 5) * range;
      const y = yScale(val);
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(w - pad.right, y);
      ctx.stroke();
      ctx.fillText(`$${val.toFixed(0)}`, 2, y + 3);
    }

    // Zero line
    if (min < 0 && max > 0) {
      const zy = yScale(0);
      ctx.strokeStyle = LABEL_COLOR;
      ctx.lineWidth = 0.8;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(pad.left, zy);
      ctx.lineTo(w - pad.right, zy);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Waterfall bars
    const barW = Math.max(2, Math.min(20, cw / trades.length - 1));
    const gap = (cw - barW * trades.length) / (trades.length + 1);

    let prevY = yScale(0);
    for (let i = 0; i < trades.length; i++) {
      const pnl = pnls[i];
      const cumTop = cumPnl[i];
      const cumBot = i === 0 ? 0 : cumPnl[i - 1];

      const x = pad.left + gap + i * (barW + gap);
      const y1 = yScale(cumBot);
      const y2 = yScale(cumTop);
      const barTop = Math.min(y1, y2);
      const barH = Math.max(1, Math.abs(y2 - y1));

      ctx.fillStyle = pnl >= 0 ? GREEN : RED;
      ctx.fillRect(x, barTop, barW, barH);

      prevY = y2;
    }

    // Cumulative line
    ctx.beginPath();
    ctx.moveTo(pad.left, yScale(0));
    for (let i = 0; i < cumPnl.length; i++) {
      const x = pad.left + gap + i * (barW + gap) + barW / 2;
      ctx.lineTo(x, yScale(cumPnl[i]));
    }
    ctx.strokeStyle = BLUE;
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // X-axis labels (trade #)
    ctx.font = '9px monospace';
    ctx.fillStyle = LABEL_COLOR;
    ctx.textAlign = 'center';
    const step = Math.max(1, Math.floor(trades.length / 10));
    for (let i = 0; i < trades.length; i += step) {
      const x = pad.left + gap + i * (barW + gap) + barW / 2;
      ctx.fillText(`#${i + 1}`, x, h - 6);
    }
  }, [trades]);

  useEffect(() => { draw(); }, [draw]);

  return (
    <canvas
      ref={canvasRef}
      className="w-full rounded-lg"
      style={{ height: 300 }}
    />
  );
}

/* ──────────────────────────────────────────────────────────────────── */
/*  Trade Stats Summary                                                */
/* ──────────────────────────────────────────────────────────────────── */

function TradeStatsSummary({ trades }: { trades: TradeResult[] }) {
  const stats = useMemo(() => {
    if (!trades.length) return null;
    const wins = trades.filter(t => t.pnl > 0);
    const losses = trades.filter(t => t.pnl <= 0);
    const avgWinDuration = wins.reduce((s, t) => s + (t.duration_bars || 0), 0) / (wins.length || 1);
    const avgLossDuration = losses.reduce((s, t) => s + (t.duration_bars || 0), 0) / (losses.length || 1);
    const bestTrade = trades.reduce((a, b) => a.pnl > b.pnl ? a : b);
    const worstTrade = trades.reduce((a, b) => a.pnl < b.pnl ? a : b);
    return { wins: wins.length, losses: losses.length, avgWinDuration, avgLossDuration, bestTrade, worstTrade };
  }, [trades]);

  if (!stats) return null;

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-xs">
      <div className="bg-background/50 rounded-lg p-2 border border-card-border/30">
        <div className="text-muted-foreground mb-1">Best Trade</div>
        <div className="font-mono font-bold text-green-400">
          ${stats.bestTrade.pnl.toFixed(2)}
        </div>
        <div className="text-muted-foreground/60 mt-0.5">
          {stats.bestTrade.direction} #{stats.bestTrade.entry_bar}
        </div>
      </div>
      <div className="bg-background/50 rounded-lg p-2 border border-card-border/30">
        <div className="text-muted-foreground mb-1">Worst Trade</div>
        <div className="font-mono font-bold text-red-400">
          ${stats.worstTrade.pnl.toFixed(2)}
        </div>
        <div className="text-muted-foreground/60 mt-0.5">
          {stats.worstTrade.direction} #{stats.worstTrade.entry_bar}
        </div>
      </div>
      <div className="bg-background/50 rounded-lg p-2 border border-card-border/30">
        <div className="text-muted-foreground mb-1">Avg Duration</div>
        <div className="font-mono">
          <span className="text-green-400">{stats.avgWinDuration.toFixed(1)}</span>
          <span className="text-muted-foreground mx-1">/</span>
          <span className="text-red-400">{stats.avgLossDuration.toFixed(1)}</span>
          <span className="text-muted-foreground ml-1">bars (W/L)</span>
        </div>
      </div>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────── */
/*  Main Component                                                     */
/* ──────────────────────────────────────────────────────────────────── */

export default function TradeChartOverlay({ trades, equityCurve }: Props) {
  const [view, setView] = useState<'equity' | 'waterfall'>('equity');

  if (!trades.length) {
    return (
      <Card className="bg-card-bg border-card-border">
        <CardContent className="flex items-center justify-center h-40 text-muted-foreground text-sm">
          No trades to visualize
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      {/* View toggle */}
      <div className="flex gap-2">
        <Button
          variant={view === 'equity' ? 'default' : 'outline'}
          size="sm"
          onClick={() => setView('equity')}
          className="text-xs"
        >
          Equity + Trades
        </Button>
        <Button
          variant={view === 'waterfall' ? 'default' : 'outline'}
          size="sm"
          onClick={() => setView('waterfall')}
          className="text-xs"
        >
          P/L Waterfall
        </Button>
      </div>

      {/* Chart */}
      <Card className="bg-card-bg border-card-border">
        <CardContent className="p-3">
          {view === 'equity' ? (
            <EquityTradeChart equityCurve={equityCurve} trades={trades} />
          ) : (
            <WaterfallChart trades={trades} />
          )}
        </CardContent>
      </Card>

      {/* Quick stats */}
      <TradeStatsSummary trades={trades} />
    </div>
  );
}
