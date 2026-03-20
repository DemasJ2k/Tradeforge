"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Redirect /backtest → /strategies?tab=backtest
 * The backtest functionality is now embedded in the combined Strategies page.
 */
export default function BacktestRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/strategies?tab=backtest");
  }, [router]);
  return null;
}
