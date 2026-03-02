'use client';

import { Card, CardContent } from '@/components/ui/card';
import type { BacktestStats } from '@/types';

interface Props {
  stats: BacktestStats;
  v2Stats?: Record<string, unknown>;
  compareStats?: Partial<BacktestStats> | null;
}

function fmt(val: number | undefined | null, decimals = 2): string {
  if (val == null || isNaN(val)) return '—';
  return val.toFixed(decimals);
}

function fmtPct(val: number | undefined | null): string {
  if (val == null || isNaN(val)) return '—';
  return val.toFixed(1) + '%';
}

function diffColor(a: number | undefined, b: number | undefined, higherIsBetter = true): string {
  if (a == null || b == null) return 'text-foreground';
  const diff = a - b;
  if (Math.abs(diff) < 0.01) return 'text-foreground';
  const better = higherIsBetter ? diff > 0 : diff < 0;
  return better ? 'text-green-400' : 'text-red-400';
}

const cards = [
  { key: 'net_profit', label: 'Net Profit', format: (v: number) => `$${fmt(v)}`, higher: true },
  { key: 'win_rate', label: 'Win Rate', format: (v: number) => fmtPct(v), higher: true },
  { key: 'profit_factor', label: 'Profit Factor', format: (v: number) => fmt(v, 4), higher: true },
  { key: 'max_drawdown_pct', label: 'Max DD %', format: (v: number) => fmtPct(v), higher: false },
  { key: 'total_trades', label: 'Total Trades', format: (v: number) => String(v), higher: true },
  { key: 'sharpe_ratio', label: 'Sharpe', format: (v: number) => fmt(v, 4), higher: true },
  { key: 'avg_win', label: 'Avg Win', format: (v: number) => `$${fmt(v)}`, higher: true },
  { key: 'avg_loss', label: 'Avg Loss', format: (v: number) => `$${fmt(v)}`, higher: false },
  { key: 'largest_win', label: 'Largest Win', format: (v: number) => `$${fmt(v)}`, higher: true },
  { key: 'largest_loss', label: 'Largest Loss', format: (v: number) => `$${fmt(v)}`, higher: false },
  { key: 'expectancy', label: 'Expectancy', format: (v: number) => `$${fmt(v)}`, higher: true },
  { key: 'gross_profit', label: 'Gross Profit', format: (v: number) => `$${fmt(v)}`, higher: true },
] as const;

export default function StatsCards({ stats, compareStats }: Props) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
      {cards.map(({ key, label, format, higher }) => {
        const val = (stats as unknown as Record<string, number>)[key];
        const cmp = compareStats ? (compareStats as Record<string, number>)[key] : undefined;
        const color = val != null && val >= 0 ? (key.includes('loss') || key.includes('drawdown') ? 'text-red-400' : 'text-green-400') : 'text-red-400';

        return (
          <Card key={key} className="bg-card-bg border-card-border">
            <CardContent className="p-3">
              <div className="text-xs text-muted-foreground uppercase tracking-wider mb-1">{label}</div>
              <div className={`text-lg font-bold font-mono ${compareStats ? diffColor(val, cmp, higher) : color}`}>
                {format(val)}
              </div>
              {compareStats && cmp != null && (
                <div className="text-xs text-muted-foreground/60 mt-0.5 font-mono">
                  vs {format(cmp)}
                </div>
              )}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
