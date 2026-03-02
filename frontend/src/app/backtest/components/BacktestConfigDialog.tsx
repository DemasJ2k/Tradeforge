'use client';

import { useState } from 'react';
import type { Strategy, DataSource } from '@/types';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Play, Settings } from 'lucide-react';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  strategies: Strategy[];
  datasources: DataSource[];
  onRun: (config: {
    strategy_id: number;
    datasource_id: number;
    initial_balance: number;
    spread_points: number;
    commission_per_lot: number;
    point_value: number;
    tick_mode: string;
    slippage_pct: number;
    margin_rate: number;
  }) => void;
}

export default function BacktestConfigDialog({
  open,
  onOpenChange,
  strategies,
  datasources,
  onRun,
}: Props) {
  const [strategyId, setStrategyId] = useState<string>('');
  const [datasourceId, setDatasourceId] = useState<string>('');
  const [balance, setBalance] = useState(10000);
  const [spread, setSpread] = useState(0);
  const [commission, setCommission] = useState(7);
  const [pointValue, setPointValue] = useState(1);
  const [tickMode, setTickMode] = useState('ohlc_pessimistic');
  const [slippage, setSlippage] = useState(0);
  const [marginRate, setMarginRate] = useState(0.01);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Auto-fill point value from datasource
  const selectedDs = datasources.find(d => d.id === Number(datasourceId));
  const autoPointValue = selectedDs?.point_value || pointValue;

  const canRun = strategyId && datasourceId;

  const handleRun = () => {
    if (!canRun) return;
    onRun({
      strategy_id: Number(strategyId),
      datasource_id: Number(datasourceId),
      initial_balance: balance,
      spread_points: spread,
      commission_per_lot: commission,
      point_value: autoPointValue,
      tick_mode: tickMode,
      slippage_pct: slippage,
      margin_rate: marginRate,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg bg-card-bg border-card-border">
        <DialogHeader>
          <DialogTitle>Configure Backtest</DialogTitle>
          <DialogDescription>
            Select a strategy and data source to run a backtest with the V3 engine.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 mt-2">
          {/* Strategy */}
          <div className="space-y-1.5">
            <Label>Strategy</Label>
            <Select value={strategyId} onValueChange={setStrategyId}>
              <SelectTrigger>
                <SelectValue placeholder="Select strategy..." />
              </SelectTrigger>
              <SelectContent>
                {strategies.map(s => (
                  <SelectItem key={s.id} value={String(s.id)}>
                    {s.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Data Source */}
          <div className="space-y-1.5">
            <Label>Data Source</Label>
            <Select value={datasourceId} onValueChange={setDatasourceId}>
              <SelectTrigger>
                <SelectValue placeholder="Select data source..." />
              </SelectTrigger>
              <SelectContent>
                {datasources.map(d => (
                  <SelectItem key={d.id} value={String(d.id)}>
                    {d.symbol} — {d.timeframe} ({d.row_count?.toLocaleString()} bars)
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Balance + Spread (side by side) */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Initial Balance</Label>
              <Input
                type="number"
                value={balance}
                onChange={e => setBalance(Number(e.target.value))}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Spread (points)</Label>
              <Input
                type="number"
                value={spread}
                onChange={e => setSpread(Number(e.target.value))}
              />
            </div>
          </div>

          {/* Commission + Point Value */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Commission/lot</Label>
              <Input
                type="number"
                value={commission}
                onChange={e => setCommission(Number(e.target.value))}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Point Value</Label>
              <Input
                type="number"
                value={autoPointValue}
                onChange={e => setPointValue(Number(e.target.value))}
              />
            </div>
          </div>

          {/* Advanced Toggle */}
          <button
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="text-xs text-accent hover:underline flex items-center gap-1"
          >
            <Settings className="w-3 h-3" />
            {showAdvanced ? 'Hide' : 'Show'} Advanced Settings
          </button>

          {showAdvanced && (
            <div className="space-y-3 pl-2 border-l-2 border-accent/20">
              <div className="space-y-1.5">
                <Label>Tick Mode</Label>
                <Select value={tickMode} onValueChange={setTickMode}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ohlc_pessimistic">OHLC Pessimistic (Recommended)</SelectItem>
                    <SelectItem value="ohlc_four">OHLC 4-Point</SelectItem>
                    <SelectItem value="brownian">Brownian Bridge</SelectItem>
                    <SelectItem value="close_only">Close Only</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label>Slippage %</Label>
                  <Input
                    type="number"
                    step="0.001"
                    value={slippage}
                    onChange={e => setSlippage(Number(e.target.value))}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>Margin Rate</Label>
                  <Input
                    type="number"
                    step="0.001"
                    value={marginRate}
                    onChange={e => setMarginRate(Number(e.target.value))}
                  />
                </div>
              </div>
            </div>
          )}

          {/* Run Button */}
          <Button
            onClick={handleRun}
            disabled={!canRun}
            className="w-full gap-2"
            size="lg"
          >
            <Play className="w-4 h-4" />
            Run Backtest
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
