'use client';

/**
 * ErrorBoundary — catches React rendering errors and shows a fallback UI
 * instead of a white screen. Wrap around page sections or whole pages.
 */

import React, { Component, type ReactNode } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface Props {
  children: ReactNode;
  /** Optional section label (e.g. "Strategy Editor", "Trade Chart") */
  section?: string;
  /** Optional compact mode for smaller inline sections */
  compact?: boolean;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error(`[ErrorBoundary${this.props.section ? ` - ${this.props.section}` : ''}]`, error, info.componentStack);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      const { section, compact } = this.props;
      const msg = this.state.error?.message || 'Something went wrong';

      if (compact) {
        return (
          <div className="flex items-center gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
            <span className="truncate">{section ? `${section}: ` : ''}{msg}</span>
            <button onClick={this.handleReset} className="ml-auto shrink-0 hover:text-red-300">
              <RefreshCw className="w-3 h-3" />
            </button>
          </div>
        );
      }

      return (
        <Card className="bg-card-bg border-red-500/30">
          <CardContent className="p-6 flex flex-col items-center justify-center text-center gap-3">
            <div className="w-10 h-10 rounded-full bg-red-500/10 flex items-center justify-center">
              <AlertTriangle className="w-5 h-5 text-red-400" />
            </div>
            <div>
              <p className="text-sm font-medium text-foreground">
                {section ? `${section} crashed` : 'Something went wrong'}
              </p>
              <p className="text-xs text-muted-foreground mt-1 max-w-sm">{msg}</p>
            </div>
            <button
              onClick={this.handleReset}
              className="mt-1 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-accent/20 text-accent hover:bg-accent/30 transition-colors"
            >
              <RefreshCw className="w-3 h-3" /> Try Again
            </button>
          </CardContent>
        </Card>
      );
    }

    return this.props.children;
  }
}
