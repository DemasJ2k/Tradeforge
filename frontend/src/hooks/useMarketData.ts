"use client";

import { create } from "zustand";
import { useWebSocket } from "./useWebSocket";

export interface TickData {
  symbol: string;
  bid: number;
  ask: number;
  spread: number;
  timestamp: number;
}

export interface BarData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface MarketDataState {
  /** Latest tick per symbol */
  ticks: Record<string, TickData>;
  /** Live bars per "symbol:timeframe" key */
  bars: Record<string, BarData[]>;
  /** Current (incomplete) bar per "symbol:timeframe" */
  currentBar: Record<string, BarData>;
  /** Subscribe to ticks for a symbol. Returns unsubscribe. */
  subscribeTicks: (symbol: string) => () => void;
  /** Subscribe to bars for a symbol+timeframe. Returns unsubscribe. */
  subscribeBars: (symbol: string, timeframe: string) => () => void;
  /** Set initial bars (from historical load). */
  setInitialBars: (symbol: string, timeframe: string, bars: BarData[]) => void;
  /** Clear all data. */
  clear: () => void;
}

export const useMarketData = create<MarketDataState>((set) => ({
  ticks: {},
  bars: {},
  currentBar: {},

  subscribeTicks: (symbol: string) => {
    const channel = `ticks:${symbol}`;
    const unsub = useWebSocket.getState().subscribe(channel, (msg) => {
      const data = msg.data as Record<string, unknown>;
      const tick: TickData = {
        symbol: (data.symbol as string) || symbol,
        bid: Number(data.bid) || 0,
        ask: Number(data.ask) || 0,
        spread: Number(data.spread) || 0,
        timestamp: Number(data.timestamp) || Date.now() / 1000,
      };
      set((state) => ({
        ticks: { ...state.ticks, [symbol]: tick },
      }));
    });
    return unsub;
  },

  subscribeBars: (symbol: string, timeframe: string) => {
    const key = `${symbol}:${timeframe}`;
    const barChannel = `bars:${symbol}:${timeframe}`;

    // Handle closed bars (append to history)
    const unsubBar = useWebSocket.getState().subscribe(barChannel, (msg) => {
      const type = msg.type as string;
      const data = msg.data as Record<string, unknown>;

      // Ensure time is a valid finite number (Unix timestamp in seconds)
      const rawTime = Number(data.time);
      if (!Number.isFinite(rawTime) || rawTime <= 0) return;

      const bar: BarData = {
        time: rawTime,
        open: Number(data.open) || 0,
        high: Number(data.high) || 0,
        low: Number(data.low) || 0,
        close: Number(data.close) || 0,
        volume: Number(data.volume) || 0,
      };

      if (type === "bar") {
        // Closed bar — append to history
        set((state) => {
          const existing = state.bars[key] || [];
          // Avoid duplicates
          const last = existing[existing.length - 1];
          if (last && last.time === bar.time) return state;
          return {
            bars: { ...state.bars, [key]: [...existing, bar] },
            currentBar: { ...state.currentBar, [key]: undefined as unknown as BarData },
          };
        });
      } else if (type === "bar_update") {
        // Live updating bar (current incomplete bar)
        set((state) => ({
          currentBar: { ...state.currentBar, [key]: bar },
        }));
      }
    });

    return () => {
      unsubBar();
    };
  },

  setInitialBars: (symbol: string, timeframe: string, bars: BarData[]) => {
    const key = `${symbol}:${timeframe}`;
    set((state) => ({
      bars: { ...state.bars, [key]: bars },
    }));
  },

  clear: () => {
    set({ ticks: {}, bars: {}, currentBar: {} });
  },
}));
