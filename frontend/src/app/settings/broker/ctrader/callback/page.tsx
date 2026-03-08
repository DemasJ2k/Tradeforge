'use client';

import { useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense } from 'react';

function CallbackHandler() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const code = searchParams.get('code');
    if (code) {
      // Redirect to settings page with the code as a query param
      router.replace(`/settings?ctrader_code=${encodeURIComponent(code)}`);
    } else {
      // No code — just go back to settings
      router.replace('/settings');
    }
  }, [searchParams, router]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="text-center space-y-3">
        <div className="w-8 h-8 border-2 border-fa-accent border-t-transparent rounded-full animate-spin mx-auto" />
        <p className="text-sm text-muted-foreground">Completing cTrader authorization...</p>
      </div>
    </div>
  );
}

export default function CTraderCallbackPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="w-8 h-8 border-2 border-fa-accent border-t-transparent rounded-full animate-spin" />
      </div>
    }>
      <CallbackHandler />
    </Suspense>
  );
}
