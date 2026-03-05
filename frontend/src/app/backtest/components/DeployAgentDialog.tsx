'use client';

import { useState } from 'react';
import { api } from '@/lib/api';
import type { Strategy, BacktestStats } from '@/types';
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
import { Rocket, CheckCircle, TrendingUp, Loader2 } from 'lucide-react';

interface Props {
  strategy: Strategy;
  symbol: string;
  timeframe: string;
  stats: BacktestStats;
  onClose: () => void;
}

export default function DeployAgentDialog({ strategy, symbol, timeframe, stats, onClose }: Props) {
  const [name, setName] = useState(`${strategy.name} — ${symbol} ${timeframe}`);
  const [mode, setMode] = useState<string>('paper');
  const [lotSize, setLotSize] = useState(0.01);
  const [maxDailyLossPct, setMaxDailyLossPct] = useState(5);
  const [deploying, setDeploying] = useState(false);
  const [deployed, setDeployed] = useState(false);
  const [error, setError] = useState('');

  const handleDeploy = async () => {
    setDeploying(true);
    setError('');
    try {
      await api.post('/api/agents', {
        name,
        strategy_id: strategy.id,
        symbol,
        timeframe,
        mode,
        risk_config: {
          lot_size: lotSize,
          max_daily_loss_pct: maxDailyLossPct,
        },
      });
      setDeployed(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to create agent');
    } finally {
      setDeploying(false);
    }
  };

  if (deployed) {
    return (
      <Dialog open onOpenChange={() => onClose()}>
        <DialogContent className="max-w-md bg-card-bg border-card-border">
          <div className="text-center py-6 space-y-4">
            <CheckCircle className="w-12 h-12 text-green-400 mx-auto" />
            <h3 className="text-lg font-semibold">Agent Deployed</h3>
            <p className="text-sm text-muted-foreground">
              Your agent &ldquo;{name}&rdquo; has been created in <span className="font-medium text-accent">{mode}</span> mode.
              Go to the Agents page to start it.
            </p>
            <Button onClick={onClose}>Close</Button>
          </div>
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <Dialog open onOpenChange={() => onClose()}>
      <DialogContent className="max-w-md bg-card-bg border-card-border">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Rocket className="w-5 h-5 text-green-400" />
            Deploy as Agent
          </DialogTitle>
          <DialogDescription>
            Create a trading agent from this profitable backtest result.
          </DialogDescription>
        </DialogHeader>

        {/* Backtest summary */}
        <div className="rounded-lg border border-green-500/20 bg-green-500/5 p-3 space-y-1">
          <div className="flex items-center gap-2 text-sm font-medium text-green-400">
            <TrendingUp className="w-4 h-4" />
            Backtest Performance
          </div>
          <div className="grid grid-cols-3 gap-2 text-xs text-muted-foreground">
            <div>P/L: <span className="text-green-400 font-mono">${stats.net_profit?.toFixed(2)}</span></div>
            <div>WR: <span className="text-foreground font-mono">{stats.win_rate?.toFixed(1)}%</span></div>
            <div>PF: <span className="text-foreground font-mono">{stats.profit_factor?.toFixed(2)}</span></div>
          </div>
        </div>

        <div className="space-y-4 mt-2">
          {/* Agent Name */}
          <div className="space-y-1.5">
            <Label>Agent Name</Label>
            <Input value={name} onChange={e => setName(e.target.value)} />
          </div>

          {/* Mode */}
          <div className="space-y-1.5">
            <Label>Mode</Label>
            <Select value={mode} onValueChange={setMode}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="paper">Paper Trading (Recommended)</SelectItem>
                <SelectItem value="confirmation">Confirmation (Approve each trade)</SelectItem>
                <SelectItem value="auto">Auto Trading (Fully automated)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Risk params */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Lot Size</Label>
              <Input
                type="number"
                step="0.01"
                value={lotSize}
                onChange={e => setLotSize(Number(e.target.value))}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Max Daily Loss %</Label>
              <Input
                type="number"
                step="0.5"
                value={maxDailyLossPct}
                onChange={e => setMaxDailyLossPct(Number(e.target.value))}
              />
            </div>
          </div>

          {error && <p className="text-xs text-red-400">{error}</p>}

          <Button
            onClick={handleDeploy}
            disabled={deploying || !name}
            className="w-full gap-2 bg-green-600 hover:bg-green-500 text-white"
            size="lg"
          >
            {deploying ? <Loader2 className="w-4 h-4 animate-spin" /> : <Rocket className="w-4 h-4" />}
            {deploying ? 'Deploying...' : 'Deploy Agent'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
