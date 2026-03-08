'use client';

/**
 * Reusable skeleton loading components for various page sections.
 * Uses animate-pulse matching the existing DashSkeleton pattern.
 */

import { Card, CardContent, CardHeader } from '@/components/ui/card';

/** Single pulsing bar */
function Bar({ className = '' }: { className?: string }) {
  return <div className={`rounded bg-card-border/30 ${className}`} />;
}

/** Skeleton for a stats card grid (backtest stats, dashboard cards) */
export function CardGridSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 animate-pulse">
      {[...Array(count)].map((_, i) => (
        <Card key={i} className="bg-card-bg border-card-border">
          <CardContent className="p-4 space-y-2">
            <Bar className="h-3 w-16" />
            <Bar className="h-6 w-20" />
            <Bar className="h-2.5 w-24" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

/** Skeleton for a table (trade log, backtest history, etc.) */
export function TableSkeleton({ rows = 5, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <Card className="bg-card-bg border-card-border animate-pulse">
      <CardHeader className="pb-2 pt-3 px-4">
        <Bar className="h-4 w-32" />
      </CardHeader>
      <CardContent className="px-4 pb-3 space-y-2">
        {/* Header row */}
        <div className="flex gap-3 pb-2 border-b border-card-border">
          {[...Array(cols)].map((_, i) => (
            <Bar key={i} className="h-3 flex-1" />
          ))}
        </div>
        {/* Data rows */}
        {[...Array(rows)].map((_, i) => (
          <div key={i} className="flex gap-3 py-1.5">
            {[...Array(cols)].map((_, j) => (
              <Bar key={j} className="h-3.5 flex-1" />
            ))}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

/** Skeleton for a list of items (strategy list, agent list) */
export function ListSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="space-y-2 animate-pulse">
      {[...Array(count)].map((_, i) => (
        <Card key={i} className="bg-card-bg border-card-border">
          <CardContent className="p-3 flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-card-border/30 shrink-0" />
            <div className="flex-1 space-y-1.5">
              <Bar className="h-3.5 w-32" />
              <Bar className="h-2.5 w-48" />
            </div>
            <Bar className="h-6 w-16 rounded-md" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

/** Skeleton for a chart area */
export function ChartSkeleton({ height = 'h-64' }: { height?: string }) {
  return (
    <Card className="bg-card-bg border-card-border animate-pulse">
      <CardContent className={`p-4 ${height} flex flex-col justify-end gap-1`}>
        <div className="flex-1" />
        <div className="flex items-end gap-1 h-3/4">
          {[...Array(20)].map((_, i) => (
            <div
              key={i}
              className="flex-1 bg-card-border/20 rounded-t"
              style={{ height: `${20 + Math.random() * 80}%` }}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

/** Full page skeleton (combines header + cards + table) */
export function PageSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <Bar className="h-7 w-40" />
      <CardGridSkeleton count={4} />
      <TableSkeleton rows={5} cols={4} />
    </div>
  );
}
