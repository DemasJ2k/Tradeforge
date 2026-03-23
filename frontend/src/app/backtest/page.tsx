"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Redirect /backtest → /ml?view=backtest
 * Backtest functionality is now part of the ML Lab page.
 */
export default function BacktestRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/ml?view=backtest");
  }, [router]);
  return null;
}
