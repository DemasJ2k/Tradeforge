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
import { Play, Settings, Brain, Activity, Bot } from 'lucide-react';
import { api } from '@/lib/api';
import { useEffect } from 'react';

interface MLModel {
  id: number;
  name: string;
  model_type: string;
  status: string;
}

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
    latency_ms: number;
    ml_model_id?: number;
    regime_model_id?: number;
    rl_model_id?: number;
    strategy_type?: string;
    ml_threshold?: number;
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
  const [latencyMs, setLatencyMs] = useState(0);
  const [showAdvanced, setShowAdvanced] = useState(false);
  // ML-enhanced backtest options
  const [mlModels, setMlModels] = useState<MLModel[]>([]);
  const [mlModelId, setMlModelId] = useState<string>('');
  const [regimeModelId, setRegimeModelId] = useState<string>('');
  const [rlModelId, setRlModelId] = useState<string>('');
  const [mlThreshold, setMlThreshold] = useState(0.5);
  const [showMl, setShowMl] = useState(false);
  const isRlMode = !!rlModelId;

  // Load ML models
  useEffect(() => {
    if (open) {
      api.get<{ items: MLModel[] } | MLModel[]>('/api/ml/models')
        .then(res => {
          const items = Array.isArray(res) ? res : (res as { items: MLModel[] }).items || [];
          setMlModels(items.filter(m => m.status === 'ready'));
        })
        .catch(() => setMlModels([]));
    }
  }, [open]);

  // Auto-fill point value from datasource
  const selectedDs = datasources.find(d => d.id === Number(datasourceId));
  const autoPointValue = selectedDs?.point_value || pointValue;

  const canRun = (strategyId || isRlMode) && datasourceId;

  const handleRun = () => {
    if (!canRun) return;
    if (balance <= 0) { alert("Initial balance must be greater than 0"); return; }
    if (spread < 0) { alert("Spread cannot be negative"); return; }
    if (commission < 0) { alert("Commission cannot be negative"); return; }
    if (slippage < 0 || slippage > 10) { alert("Slippage must be between 0% and 10%"); return; }
    if (marginRate < 0 || marginRate > 1) { alert("Margin rate must be between 0 and 1"); return; }
    onRun({
      strategy_id: Number(strategyId) || 0,
      datasource_id: Number(datasourceId),
      initial_balance: balance,
      spread_points: spread,
      commission_per_lot: commission,
      point_value: autoPointValue,
      tick_mode: tickMode,
      slippage_pct: slippage,
      margin_rate: marginRate,
      latency_ms: latencyMs,
      ...(mlModelId ? { ml_model_id: Number(mlModelId) } : {}),
      ...(regimeModelId ? { regime_model_id: Number(regimeModelId) } : {}),
      ...(rlModelId ? { rl_model_id: Number(rlModelId), strategy_type: 'rl' } : {}),
      ...(mlModelId ? { ml_threshold: mlThreshold } : {}),
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
                    <SelectItem value="synthetic">Synthetic (20-tick Bridge)</SelectItem>
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
              <div className="space-y-1.5">
                <Label>Latency (ms)</Label>
                <Input
                  type="number"
                  step="10"
                  min="0"
                  max="1000"
                  value={latencyMs}
                  onChange={e => setLatencyMs(Number(e.target.value))}
                />
                <p className="text-[10px] text-muted-foreground">Simulates execution delay. 0 = instant fills, 100-200ms = realistic.</p>
              </div>
            </div>
          )}

          {/* ML Enhancement Toggle */}
          <button
            onClick={() => setShowMl(!showMl)}
            className="text-xs text-accent hover:underline flex items-center gap-1"
          >
            <Brain className="w-3 h-3" />
            {showMl ? 'Hide' : 'Show'} ML Enhancement
          </button>

          {showMl && (
            <div className="space-y-3 pl-2 border-l-2 border-purple-500/30">
              {/* RL Agent Mode */}
              <div className="space-y-1.5">
                <Label className="flex items-center gap-1">
                  <Bot className="w-3 h-3" /> RL Agent (replaces strategy)
                </Label>
                <Select value={rlModelId} onValueChange={v => { setRlModelId(v === '_none' ? '' : v); }}>
                  <SelectTrigger>
                    <SelectValue placeholder="None — use strategy" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="_none">None</SelectItem>
                    {mlModels.filter(m => m.model_type === 'rl_ppo').map(m => (
                      <SelectItem key={m.id} value={String(m.id)}>
                        {m.name} (RL)
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-[10px] text-muted-foreground">
                  RL agent trades autonomously — strategy is ignored.
                </p>
              </div>

              {!isRlMode && (
                <>
                  {/* ML Signal Filter */}
                  <div className="space-y-1.5">
                    <Label className="flex items-center gap-1">
                      <Brain className="w-3 h-3" /> ML Signal Filter
                    </Label>
                    <Select value={mlModelId} onValueChange={v => setMlModelId(v === '_none' ? '' : v)}>
                      <SelectTrigger>
                        <SelectValue placeholder="None — no ML filter" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="_none">None</SelectItem>
                        {mlModels.filter(m => !['rl_ppo', 'hmm_regime', 'lstm', 'gru'].includes(m.model_type)).map(m => (
                          <SelectItem key={m.id} value={String(m.id)}>
                            {m.name} ({m.model_type})
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  {mlModelId && (
                    <div className="space-y-1.5">
                      <Label>ML Threshold</Label>
                      <Input
                        type="number"
                        step="0.05"
                        min="0"
                        max="1"
                        value={mlThreshold}
                        onChange={e => setMlThreshold(Number(e.target.value))}
                      />
                      <p className="text-[10px] text-muted-foreground">
                        Signals below this confidence are filtered out.
                      </p>
                    </div>
                  )}

                  {/* Regime Model */}
                  <div className="space-y-1.5">
                    <Label className="flex items-center gap-1">
                      <Activity className="w-3 h-3" /> Regime Model
                    </Label>
                    <Select value={regimeModelId} onValueChange={v => setRegimeModelId(v === '_none' ? '' : v)}>
                      <SelectTrigger>
                        <SelectValue placeholder="None — no regime filter" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="_none">None</SelectItem>
                        {mlModels.filter(m => m.model_type === 'hmm_regime').map(m => (
                          <SelectItem key={m.id} value={String(m.id)}>
                            {m.name} (HMM)
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <p className="text-[10px] text-muted-foreground">
                      Filters counter-trend signals and adjusts confidence by regime.
                    </p>
                  </div>
                </>
              )}
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
            {isRlMode ? 'Backtest RL Agent' : 'Run Backtest'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
