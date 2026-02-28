"use client";

import { create } from "zustand";
import { api } from "@/lib/api";

export interface BrokerAccount {
  broker: string;
  connected: boolean;
  currency: string;
  balance: number;
  equity: number;
  unrealizedPnl: number;
  todayPnl: number;
}

interface BrokerAccountsStore {
  accounts: BrokerAccount[];
  activeBroker: string | null;
  loading: boolean;
  setActiveBroker: (broker: string) => void;
  refreshAccounts: () => Promise<void>;
}

export const useBrokerAccounts = create<BrokerAccountsStore>((set, get) => ({
  accounts: [],
  activeBroker: null,
  loading: false,

  setActiveBroker: (broker) => set({ activeBroker: broker }),

  refreshAccounts: async () => {
    set({ loading: true });
    try {
      // Get list of all connected brokers
      const status = await api.get<{
        brokers: Record<string, { connected: boolean; broker_name?: string }>;
        default_broker: string | null;
      }>("/api/broker/status");

      const connectedBrokers = Object.entries(status.brokers)
        .filter(([, info]) => info.connected)
        .map(([name]) => name);

      if (connectedBrokers.length === 0) {
        set({ accounts: [], activeBroker: null, loading: false });
        return;
      }

      // Fetch account info for each connected broker in parallel
      const accountResults = await Promise.allSettled(
        connectedBrokers.map((broker) =>
          api
            .get<{
              account_id: string;
              broker: string;
              currency: string;
              balance: number;
              equity: number;
              unrealized_pnl: number;
              margin_used: number;
              margin_available: number;
            }>(`/api/broker/account?broker=${broker}`)
            .then((info) => ({
              broker,
              connected: true,
              currency: info.currency ?? "USD",
              balance: info.balance ?? 0,
              equity: info.equity ?? 0,
              unrealizedPnl: info.unrealized_pnl ?? 0,
              todayPnl: 0, // TODO: calculate from trade history
            }))
        )
      );

      const accounts: BrokerAccount[] = accountResults
        .filter((r): r is PromiseFulfilledResult<BrokerAccount> => r.status === "fulfilled")
        .map((r) => r.value);

      const { activeBroker } = get();
      const newActive =
        activeBroker && accounts.some((a) => a.broker === activeBroker)
          ? activeBroker
          : (status.default_broker ?? accounts[0]?.broker ?? null);

      set({ accounts, activeBroker: newActive, loading: false });
    } catch {
      set({ loading: false });
    }
  },
}));
