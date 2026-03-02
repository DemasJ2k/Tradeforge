'use client';

import { useState } from 'react';
import type { BacktestListItem } from '@/types';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
// ScrollArea not available — use native overflow
import {
  X,
  Search,
  Trash2,
  GitCompareArrows,
  ChevronRight,
  Clock,
} from 'lucide-react';

interface Props {
  history: BacktestListItem[];
  activeId?: number;
  onSelect: (id: number) => void;
  onCompare: (id: number) => void;
  onDelete: (id: number) => void;
  onClose: () => void;
}

export default function RunHistorySidebar({
  history,
  activeId,
  onSelect,
  onCompare,
  onDelete,
  onClose,
}: Props) {
  const [filter, setFilter] = useState('');

  const filtered = filter
    ? history.filter(h =>
        h.symbol?.toLowerCase().includes(filter.toLowerCase()) ||
        h.timeframe?.toLowerCase().includes(filter.toLowerCase()) ||
        `#${h.id}`.includes(filter)
      )
    : history;

  const formatDate = (iso: string) => {
    try {
      const d = new Date(iso);
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch { return iso; }
  };

  return (
    <div className="w-72 md:w-80 border-l border-card-border bg-card-bg flex flex-col shrink-0">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-card-border">
        <div className="flex items-center gap-2">
          <Clock className="w-4 h-4 text-muted-foreground" />
          <span className="text-sm font-medium">Run History</span>
          <span className="text-xs text-muted-foreground">({history.length})</span>
        </div>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose}>
          <X className="w-4 h-4" />
        </Button>
      </div>

      {/* Search */}
      <div className="px-3 py-2 border-b border-card-border">
        <div className="relative">
          <Search className="absolute left-2 top-2 w-3.5 h-3.5 text-muted-foreground" />
          <Input
            placeholder="Search runs..."
            value={filter}
            onChange={e => setFilter(e.target.value)}
            className="pl-8 h-7 text-xs"
          />
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-auto">
        {filtered.length === 0 && (
          <div className="px-3 py-8 text-center text-xs text-muted-foreground">
            {history.length === 0 ? 'No previous runs' : 'No matching runs'}
          </div>
        )}
        <div className="p-1.5 space-y-1">
          {filtered.map(item => {
            const isActive = item.id === activeId;
            const pnl = item.stats?.net_profit;
            const winRate = item.stats?.win_rate;
            return (
              <div
                key={item.id}
                className={`group rounded-md border transition-colors cursor-pointer ${
                  isActive
                    ? 'border-accent/60 bg-accent/10'
                    : 'border-transparent hover:border-card-border hover:bg-muted/30'
                }`}
                onClick={() => onSelect(item.id)}
              >
                <div className="px-2.5 py-2">
                  {/* Row 1: symbol + date */}
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold truncate">
                      {item.symbol || `Run #${item.id}`}
                      {item.timeframe && (
                        <span className="ml-1 text-muted-foreground font-normal">{item.timeframe}</span>
                      )}
                    </span>
                    <span className="text-[10px] text-muted-foreground whitespace-nowrap ml-2">
                      {formatDate(item.created_at)}
                    </span>
                  </div>

                  {/* Row 2: stats */}
                  <div className="flex items-center gap-3 mt-1">
                    {pnl !== undefined && (
                      <span className={`text-xs font-mono ${pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {pnl >= 0 ? '+' : ''}{typeof pnl === 'number' ? pnl.toFixed(2) : pnl}
                      </span>
                    )}
                    {winRate !== undefined && (
                      <span className="text-xs text-muted-foreground font-mono">
                        WR {typeof winRate === 'number' ? (winRate * 100).toFixed(0) : winRate}%
                      </span>
                    )}
                    {item.stats?.total_trades !== undefined && (
                      <span className="text-xs text-muted-foreground">{item.stats.total_trades} trades</span>
                    )}
                  </div>

                  {/* Row 3: actions (shown on hover / always for active) */}
                  <div className={`flex items-center gap-1 mt-1.5 ${isActive ? '' : 'opacity-0 group-hover:opacity-100'} transition-opacity`}>
                    {!isActive && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 px-2 text-xs gap-1"
                        onClick={e => { e.stopPropagation(); onSelect(item.id); }}
                      >
                        <ChevronRight className="w-3 h-3" /> Load
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 px-2 text-xs gap-1"
                      onClick={e => { e.stopPropagation(); onCompare(item.id); }}
                    >
                      <GitCompareArrows className="w-3 h-3" /> Compare
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 px-2 text-xs gap-1 text-destructive hover:text-destructive"
                      onClick={e => { e.stopPropagation(); onDelete(item.id); }}
                    >
                      <Trash2 className="w-3 h-3" />
                    </Button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
