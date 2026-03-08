'use client';

/**
 * WelcomeWizard — shown to first-time users on the dashboard.
 * 3-step wizard: Welcome → Data Setup → First Strategy.
 * Dismissable with a skip button; state persisted in localStorage.
 */

import { useState, useCallback } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import {
  Sparkles, BarChart3, ChevronRight, ChevronLeft, X,
  Database, Layers, Rocket, TrendingUp,
} from 'lucide-react';
import { useRouter } from 'next/navigation';

const ONBOARDING_KEY = 'flowrex_onboarding_completed';

interface Props {
  onDismiss: () => void;
}

export function useOnboarding() {
  const [dismissed, setDismissed] = useState(() => {
    if (typeof window === 'undefined') return true;
    return localStorage.getItem(ONBOARDING_KEY) === 'true';
  });

  const dismiss = useCallback(() => {
    localStorage.setItem(ONBOARDING_KEY, 'true');
    setDismissed(true);
  }, []);

  return { showOnboarding: !dismissed, dismissOnboarding: dismiss };
}

export default function WelcomeWizard({ onDismiss }: Props) {
  const [step, setStep] = useState(0);
  const router = useRouter();

  const steps = [
    {
      title: 'Welcome to FlowrexAlgo',
      icon: <Sparkles className="w-10 h-10 text-accent" />,
      description: 'Your AI-powered algorithmic trading platform. Build strategies, backtest them on historical data, and deploy live trading agents.',
      highlights: [
        { icon: <Layers className="w-4 h-4" />, text: 'Build strategies with visual editor or AI import' },
        { icon: <BarChart3 className="w-4 h-4" />, text: 'Backtest with V3 engine + walk-forward validation' },
        { icon: <Rocket className="w-4 h-4" />, text: 'Deploy agents for paper or live trading' },
        { icon: <TrendingUp className="w-4 h-4" />, text: 'Track prop firm challenges with rule validation' },
      ],
    },
    {
      title: 'Upload Market Data',
      icon: <Database className="w-10 h-10 text-accent" />,
      description: 'To run backtests, you need historical market data. Upload a CSV file with OHLCV bars, or connect a broker for live data.',
      action: { label: 'Upload Data', onClick: () => { onDismiss(); router.push('/data'); } },
      secondaryAction: { label: 'Connect Broker', onClick: () => { onDismiss(); router.push('/trading'); } },
      tip: 'Supported: MT5 CSV, TradingView export, or any OHLCV CSV with datetime, open, high, low, close, volume columns.',
    },
    {
      title: 'Create Your First Strategy',
      icon: <Layers className="w-10 h-10 text-accent" />,
      description: 'Build a strategy using the visual editor, import from PineScript, or start with one of our pre-built templates.',
      action: { label: 'Use a Template', onClick: () => { onDismiss(); router.push('/strategies'); } },
      secondaryAction: { label: 'AI Import', onClick: () => { onDismiss(); router.push('/strategies'); } },
      tip: '5 templates available: SMA Crossover, RSI Mean Reversion, Bollinger Breakout, MACD+RSI, and ATR Trailing Momentum.',
    },
  ];

  const current = steps[step];
  const isLast = step === steps.length - 1;

  return (
    <Card className="bg-card-bg border-accent/20 shadow-lg shadow-accent/5 relative overflow-hidden">
      <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-accent via-accent/60 to-transparent" />
      <CardContent className="p-6 sm:p-8">
        <button onClick={onDismiss} className="absolute top-3 right-3 text-muted-foreground hover:text-foreground" title="Skip">
          <X className="w-4 h-4" />
        </button>

        {/* Step indicator */}
        <div className="flex items-center gap-2 mb-6">
          {steps.map((_, i) => (
            <div key={i} className={`h-1.5 rounded-full transition-all ${i === step ? 'w-8 bg-accent' : i < step ? 'w-4 bg-accent/40' : 'w-4 bg-card-border'}`} />
          ))}
          <span className="ml-auto text-xs text-muted-foreground">Step {step + 1} of {steps.length}</span>
        </div>

        <div className="flex flex-col sm:flex-row gap-6 items-start">
          <div className="shrink-0 w-16 h-16 rounded-2xl bg-accent/10 flex items-center justify-center">{current.icon}</div>
          <div className="flex-1 min-w-0">
            <h2 className="text-lg font-semibold mb-2">{current.title}</h2>
            <p className="text-sm text-muted-foreground mb-4">{current.description}</p>

            {'highlights' in current && current.highlights && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-4">
                {current.highlights.map((h, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span className="text-accent">{h.icon}</span>{h.text}
                  </div>
                ))}
              </div>
            )}

            {'tip' in current && current.tip && (
              <div className="text-xs text-muted-foreground/70 bg-muted/10 rounded-lg px-3 py-2 mb-4">{current.tip}</div>
            )}

            <div className="flex items-center gap-3 flex-wrap">
              {step > 0 && (
                <Button variant="outline" size="sm" onClick={() => setStep(s => s - 1)} className="gap-1">
                  <ChevronLeft className="w-3.5 h-3.5" /> Back
                </Button>
              )}
              {'action' in current && current.action && (
                <Button size="sm" onClick={current.action.onClick} className="gap-1.5 bg-accent text-black hover:bg-accent/90">
                  {current.action.label} <ChevronRight className="w-3.5 h-3.5" />
                </Button>
              )}
              {'secondaryAction' in current && current.secondaryAction && (
                <Button variant="outline" size="sm" onClick={current.secondaryAction.onClick} className="gap-1.5 border-accent/30 text-accent hover:bg-accent/10">
                  {current.secondaryAction.label}
                </Button>
              )}
              {!isLast && (
                <Button variant="ghost" size="sm" onClick={() => setStep(s => s + 1)} className="gap-1 text-muted-foreground hover:text-foreground ml-auto">
                  {step === 0 ? 'Get Started' : 'Next'} <ChevronRight className="w-3.5 h-3.5" />
                </Button>
              )}
              {isLast && (
                <Button variant="ghost" size="sm" onClick={onDismiss} className="gap-1 text-muted-foreground hover:text-foreground ml-auto">
                  Done
                </Button>
              )}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
