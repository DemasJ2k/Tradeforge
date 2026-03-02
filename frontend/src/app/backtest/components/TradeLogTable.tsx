'use client';

import { useState, useMemo } from 'react';
import type { TradeResult } from '@/types';
import { Card, CardContent } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ArrowUpDown, Search, ChevronLeft, ChevronRight } from 'lucide-react';

interface Props {
  trades: TradeResult[];
}

type SortKey = 'entry_time' | 'pnl' | 'pnl_pct' | 'size' | 'duration_bars';

export default function TradeLogTable({ trades }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('entry_time');
  const [sortAsc, setSortAsc] = useState(true);
  const [filter, setFilter] = useState('');
  const [page, setPage] = useState(0);
  const perPage = 50;

  const filtered = useMemo(() => {
    let list = [...trades];
    if (filter) {
      const f = filter.toLowerCase();
      list = list.filter(t =>
        t.direction.includes(f) ||
        t.exit_reason?.toLowerCase().includes(f) ||
        t.pnl.toFixed(2).includes(f)
      );
    }
    list.sort((a, b) => {
      const av = (a as unknown as Record<string, unknown>)[sortKey] as number || 0;
      const bv = (b as unknown as Record<string, unknown>)[sortKey] as number || 0;
      return sortAsc ? av - bv : bv - av;
    });
    return list;
  }, [trades, sortKey, sortAsc, filter]);

  const pageCount = Math.ceil(filtered.length / perPage);
  const visible = filtered.slice(page * perPage, (page + 1) * perPage);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(true); }
  };

  const formatTime = (ts: number | null | undefined) => {
    if (!ts) return '—';
    return new Date(ts * 1000).toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  };

  return (
    <Card className="bg-card-bg border-card-border">
      <CardContent className="p-0">
        {/* Search + Count */}
        <div className="flex items-center justify-between p-3 border-b border-card-border">
          <div className="relative">
            <Search className="absolute left-2 top-2.5 w-3.5 h-3.5 text-muted-foreground" />
            <Input
              placeholder="Filter trades..."
              value={filter}
              onChange={e => { setFilter(e.target.value); setPage(0); }}
              className="pl-8 h-8 w-48 text-sm"
            />
          </div>
          <span className="text-xs text-muted-foreground">
            {filtered.length} trade{filtered.length !== 1 ? 's' : ''}
          </span>
        </div>

        {/* Table */}
        <div className="overflow-auto max-h-[60vh]">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-10">#</TableHead>
                <TableHead>Direction</TableHead>
                <TableHead className="cursor-pointer" onClick={() => toggleSort('entry_time')}>
                  Entry <ArrowUpDown className="inline w-3 h-3 ml-1" />
                </TableHead>
                <TableHead>Entry Price</TableHead>
                <TableHead>SL</TableHead>
                <TableHead>TP</TableHead>
                <TableHead>Exit</TableHead>
                <TableHead>Exit Price</TableHead>
                <TableHead>Reason</TableHead>
                <TableHead className="cursor-pointer text-right" onClick={() => toggleSort('pnl')}>
                  P/L <ArrowUpDown className="inline w-3 h-3 ml-1" />
                </TableHead>
                <TableHead className="text-right">P/L %</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((t, i) => (
                <TableRow key={i} className="text-xs font-mono">
                  <TableCell className="text-muted-foreground">{page * perPage + i + 1}</TableCell>
                  <TableCell>
                    <span className={t.direction === 'long' ? 'text-green-400' : 'text-red-400'}>
                      {t.direction === 'long' ? '▲ LONG' : '▼ SHORT'}
                    </span>
                  </TableCell>
                  <TableCell>{formatTime(t.entry_time)}</TableCell>
                  <TableCell>{t.entry_price?.toFixed(5)}</TableCell>
                  <TableCell className="text-red-400/70">{t.stop_loss ? t.stop_loss.toFixed(5) : '—'}</TableCell>
                  <TableCell className="text-green-400/70">{t.take_profit ? t.take_profit.toFixed(5) : '—'}</TableCell>
                  <TableCell>{formatTime(t.exit_time)}</TableCell>
                  <TableCell>{t.exit_price ? t.exit_price.toFixed(5) : '—'}</TableCell>
                  <TableCell className="text-muted-foreground">{t.exit_reason || '—'}</TableCell>
                  <TableCell className={`text-right font-semibold ${t.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {t.pnl >= 0 ? '+' : ''}{t.pnl?.toFixed(2)}
                  </TableCell>
                  <TableCell className={`text-right ${t.pnl_pct >= 0 ? 'text-green-400/70' : 'text-red-400/70'}`}>
                    {t.pnl_pct >= 0 ? '+' : ''}{t.pnl_pct?.toFixed(2)}%
                  </TableCell>
                </TableRow>
              ))}
              {visible.length === 0 && (
                <TableRow>
                  <TableCell colSpan={11} className="text-center text-muted-foreground py-8">
                    No trades found
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>

        {/* Pagination */}
        {pageCount > 1 && (
          <div className="flex items-center justify-between p-3 border-t border-card-border">
            <Button
              variant="ghost"
              size="sm"
              disabled={page === 0}
              onClick={() => setPage(p => p - 1)}
            >
              <ChevronLeft className="w-4 h-4" /> Prev
            </Button>
            <span className="text-xs text-muted-foreground">
              Page {page + 1} of {pageCount}
            </span>
            <Button
              variant="ghost"
              size="sm"
              disabled={page >= pageCount - 1}
              onClick={() => setPage(p => p + 1)}
            >
              Next <ChevronRight className="w-4 h-4" />
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
