'use client';

/**
 * Client-side wrapper for ErrorBoundary — used in server component layouts.
 * Wraps page content to catch rendering crashes per-page.
 */

import ErrorBoundary from './ErrorBoundary';
import type { ReactNode } from 'react';

export default function PageErrorBoundary({ children }: { children: ReactNode }) {
  return <ErrorBoundary section="Page">{children}</ErrorBoundary>;
}
