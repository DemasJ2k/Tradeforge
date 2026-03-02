'use client';

import { useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface Props {
  monthlyReturns: Record<string, number>; // "2024-01" → 3.41 (% or $)
  mode?: 'pct' | 'usd';
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function cellColor(val: number): string {
  if (val === 0 || isNaN(val)) return 'bg-transparent text-muted-foreground';
  if (val > 10) return 'bg-green-500/30 text-green-300';
  if (val > 5) return 'bg-green-500/20 text-green-400';
  if (val > 0) return 'bg-green-500/10 text-green-400/80';
  if (val > -5) return 'bg-red-500/10 text-red-400/80';
  if (val > -10) return 'bg-red-500/20 text-red-400';
  return 'bg-red-500/30 text-red-300';
}

export default function MonthlyHeatmap({ monthlyReturns, mode = 'pct' }: Props) {
  const { years, grid, yearTotals } = useMemo(() => {
    const yearSet = new Set<number>();
    const map = new Map<string, number>();

    Object.entries(monthlyReturns).forEach(([key, val]) => {
      const [y] = key.split('-');
      const yearNum = Number(y);
      if (isNaN(yearNum) || yearNum < 1900 || yearNum > 2100) return;
      if (typeof val !== 'number' || isNaN(val)) return;
      yearSet.add(yearNum);
      map.set(key, val);
    });

    const sortedYears = Array.from(yearSet).sort();
    const g: Record<number, (number | null)[]> = {};
    const yt: Record<number, number> = {};

    sortedYears.forEach(year => {
      g[year] = [];
      yt[year] = 0;
      for (let m = 0; m < 12; m++) {
        const key = `${year}-${String(m + 1).padStart(2, '0')}`;
        const val = map.get(key) ?? null;
        g[year].push(val);
        if (val !== null) yt[year] += val;
      }
    });

    return { years: sortedYears, grid: g, yearTotals: yt };
  }, [monthlyReturns]);

  const monthTotals = useMemo(() => {
    return MONTHS.map((_, idx) => {
      let total = 0;
      years.forEach(y => { total += grid[y][idx] ?? 0; });
      return total;
    });
  }, [years, grid]);

  const fmt = (v: number | null) => {
    if (v === null || v === undefined || isNaN(v)) return '';
    return mode === 'pct' ? `${v >= 0 ? '+' : ''}${v.toFixed(1)}%` : `${v >= 0 ? '+' : ''}$${v.toFixed(0)}`;
  };

  if (years.length === 0) {
    return (
      <Card className="bg-card-bg border-card-border">
        <CardContent className="py-12 text-center text-muted-foreground">
          No monthly data available
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="bg-card-bg border-card-border">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">Monthly Returns Heatmap</CardTitle>
      </CardHeader>
      <CardContent className="overflow-auto">
        <table className="w-full text-xs font-mono border-collapse">
          <thead>
            <tr>
              <th className="p-1.5 text-left text-muted-foreground font-medium">Year</th>
              {MONTHS.map(m => (
                <th key={m} className="p-1.5 text-center text-muted-foreground font-medium">{m}</th>
              ))}
              <th className="p-1.5 text-center text-muted-foreground font-medium border-l border-card-border">YTD</th>
            </tr>
          </thead>
          <tbody>
            {years.map(year => (
              <tr key={year}>
                <td className="p-1.5 font-semibold text-foreground">{year}</td>
                {grid[year].map((val, idx) => (
                  <td
                    key={idx}
                    className={`p-1.5 text-center rounded-sm ${val !== null ? cellColor(val) : ''}`}
                  >
                    {fmt(val)}
                  </td>
                ))}
                <td
                  className={`p-1.5 text-center font-semibold border-l border-card-border ${cellColor(yearTotals[year])}`}
                >
                  {fmt(yearTotals[year])}
                </td>
              </tr>
            ))}
            {/* Bottom totals row */}
            <tr className="border-t border-card-border">
              <td className="p-1.5 font-semibold text-muted-foreground">Avg</td>
              {monthTotals.map((val, idx) => {
                const avg = years.length > 0 ? val / years.length : 0;
                return (
                  <td key={idx} className={`p-1.5 text-center ${cellColor(avg)}`}>
                    {fmt(avg)}
                  </td>
                );
              })}
              <td className="p-1.5 border-l border-card-border" />
            </tr>
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
