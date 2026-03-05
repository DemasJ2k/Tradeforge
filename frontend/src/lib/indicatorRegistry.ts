/**
 * TradeForge — Indicator Registry
 *
 * Metadata for every indicator: id, display name, type (overlay / oscillator),
 * configurable parameters, output keys, and default colours.
 */

export interface IndicatorParam {
  key: string;
  label: string;
  default: number;
  min: number;
  max: number;
  step?: number;
}

export interface IndicatorOutputLine {
  key: string;
  label: string;
  color: string;
  /** "line" | "histogram" | "area" (between two keys) */
  style: "line" | "histogram" | "area";
}

export interface IndicatorDef {
  id: string;
  name: string;
  shortName: string;
  /** "overlay" renders on the price chart; "oscillator" renders in a separate pane */
  type: "overlay" | "oscillator";
  params: IndicatorParam[];
  outputs: IndicatorOutputLine[];
  /** Optional fixed scale boundaries for the oscillator pane */
  scaleMin?: number;
  scaleMax?: number;
}

// ─── Overlay Indicators (9) ──────────────────────────────────────────────────

const SMA: IndicatorDef = {
  id: "sma", name: "Simple Moving Average", shortName: "SMA", type: "overlay",
  params: [{ key: "length", label: "Period", default: 20, min: 2, max: 500 }],
  outputs: [{ key: "sma", label: "SMA", color: "#fbbf24", style: "line" }],
};

const EMA: IndicatorDef = {
  id: "ema", name: "Exponential Moving Average", shortName: "EMA", type: "overlay",
  params: [{ key: "length", label: "Period", default: 50, min: 2, max: 500 }],
  outputs: [{ key: "ema", label: "EMA", color: "#a78bfa", style: "line" }],
};

const BB: IndicatorDef = {
  id: "bb", name: "Bollinger Bands", shortName: "BB", type: "overlay",
  params: [
    { key: "length", label: "Period", default: 20, min: 2, max: 200 },
    { key: "mult", label: "Std Dev", default: 2, min: 0.5, max: 5, step: 0.5 },
  ],
  outputs: [
    { key: "upper", label: "Upper", color: "#60a5fa", style: "line" },
    { key: "middle", label: "Middle", color: "#60a5fa", style: "line" },
    { key: "lower", label: "Lower", color: "#60a5fa", style: "line" },
  ],
};

const VWAP: IndicatorDef = {
  id: "vwap", name: "VWAP", shortName: "VWAP", type: "overlay",
  params: [],
  outputs: [{ key: "vwap", label: "VWAP", color: "#f472b6", style: "line" }],
};

const PSAR: IndicatorDef = {
  id: "psar", name: "Parabolic SAR", shortName: "PSAR", type: "overlay",
  params: [
    { key: "afStart", label: "AF Start", default: 0.02, min: 0.005, max: 0.1, step: 0.005 },
    { key: "afStep", label: "AF Step", default: 0.02, min: 0.005, max: 0.1, step: 0.005 },
    { key: "afMax", label: "AF Max", default: 0.2, min: 0.05, max: 0.5, step: 0.05 },
  ],
  outputs: [{ key: "psar", label: "SAR", color: "#f59e0b", style: "line" }],
};

const SUPERTREND: IndicatorDef = {
  id: "supertrend", name: "SuperTrend", shortName: "ST", type: "overlay",
  params: [
    { key: "length", label: "ATR Period", default: 10, min: 2, max: 100 },
    { key: "mult", label: "Multiplier", default: 3, min: 0.5, max: 10, step: 0.5 },
  ],
  outputs: [{ key: "supertrend", label: "SuperTrend", color: "#22d3ee", style: "line" }],
};

const ICHIMOKU: IndicatorDef = {
  id: "ichimoku", name: "Ichimoku Cloud", shortName: "Ichi", type: "overlay",
  params: [
    { key: "tenkanLen", label: "Tenkan", default: 9, min: 2, max: 60 },
    { key: "kijunLen", label: "Kijun", default: 26, min: 2, max: 120 },
    { key: "senkouBLen", label: "Senkou B", default: 52, min: 2, max: 240 },
  ],
  outputs: [
    { key: "tenkan", label: "Tenkan", color: "#22d3ee", style: "line" },
    { key: "kijun", label: "Kijun", color: "#f472b6", style: "line" },
    { key: "senkouA", label: "Senkou A", color: "#4ade80", style: "line" },
    { key: "senkouB", label: "Senkou B", color: "#ef4444", style: "line" },
  ],
};

const KELTNER: IndicatorDef = {
  id: "keltner", name: "Keltner Channels", shortName: "KC", type: "overlay",
  params: [
    { key: "emaLen", label: "EMA Period", default: 20, min: 2, max: 200 },
    { key: "atrLen", label: "ATR Period", default: 10, min: 2, max: 100 },
    { key: "mult", label: "Multiplier", default: 1.5, min: 0.5, max: 5, step: 0.5 },
  ],
  outputs: [
    { key: "upper", label: "Upper", color: "#c084fc", style: "line" },
    { key: "middle", label: "Middle", color: "#c084fc", style: "line" },
    { key: "lower", label: "Lower", color: "#c084fc", style: "line" },
  ],
};

const DONCHIAN: IndicatorDef = {
  id: "donchian", name: "Donchian Channels", shortName: "DC", type: "overlay",
  params: [{ key: "length", label: "Period", default: 20, min: 2, max: 200 }],
  outputs: [
    { key: "upper", label: "Upper", color: "#fb923c", style: "line" },
    { key: "middle", label: "Middle", color: "#fb923c", style: "line" },
    { key: "lower", label: "Lower", color: "#fb923c", style: "line" },
  ],
};

// ─── Oscillator Indicators (9) ───────────────────────────────────────────────

const MACD: IndicatorDef = {
  id: "macd", name: "MACD", shortName: "MACD", type: "oscillator",
  params: [
    { key: "fast", label: "Fast", default: 12, min: 2, max: 100 },
    { key: "slow", label: "Slow", default: 26, min: 2, max: 200 },
    { key: "signal", label: "Signal", default: 9, min: 2, max: 50 },
  ],
  outputs: [
    { key: "macd", label: "MACD", color: "#3b82f6", style: "line" },
    { key: "signal", label: "Signal", color: "#f59e0b", style: "line" },
    { key: "histogram", label: "Histogram", color: "#22c55e", style: "histogram" },
  ],
};

const RSI: IndicatorDef = {
  id: "rsi", name: "Relative Strength Index", shortName: "RSI", type: "oscillator",
  params: [{ key: "length", label: "Period", default: 14, min: 2, max: 100 }],
  outputs: [{ key: "rsi", label: "RSI", color: "#a78bfa", style: "line" }],
  scaleMin: 0, scaleMax: 100,
};

const ATR: IndicatorDef = {
  id: "atr", name: "Average True Range", shortName: "ATR", type: "oscillator",
  params: [{ key: "length", label: "Period", default: 14, min: 2, max: 100 }],
  outputs: [{ key: "atr", label: "ATR", color: "#f472b6", style: "line" }],
};

const STOCHASTIC: IndicatorDef = {
  id: "stochastic", name: "Stochastic Oscillator", shortName: "Stoch", type: "oscillator",
  params: [
    { key: "kLen", label: "%K Period", default: 14, min: 2, max: 100 },
    { key: "dLen", label: "%D Smooth", default: 3, min: 2, max: 20 },
  ],
  outputs: [
    { key: "k", label: "%K", color: "#3b82f6", style: "line" },
    { key: "d", label: "%D", color: "#f59e0b", style: "line" },
  ],
  scaleMin: 0, scaleMax: 100,
};

const ADX: IndicatorDef = {
  id: "adx", name: "Average Directional Index", shortName: "ADX", type: "oscillator",
  params: [{ key: "length", label: "Period", default: 14, min: 2, max: 100 }],
  outputs: [
    { key: "adx", label: "ADX", color: "#fbbf24", style: "line" },
    { key: "plusDI", label: "+DI", color: "#22c55e", style: "line" },
    { key: "minusDI", label: "−DI", color: "#ef4444", style: "line" },
  ],
  scaleMin: 0, scaleMax: 100,
};

const CCI: IndicatorDef = {
  id: "cci", name: "Commodity Channel Index", shortName: "CCI", type: "oscillator",
  params: [{ key: "length", label: "Period", default: 20, min: 2, max: 200 }],
  outputs: [{ key: "cci", label: "CCI", color: "#60a5fa", style: "line" }],
};

const WILLIAMSR: IndicatorDef = {
  id: "williamsr", name: "Williams %R", shortName: "%R", type: "oscillator",
  params: [{ key: "length", label: "Period", default: 14, min: 2, max: 100 }],
  outputs: [{ key: "williamsr", label: "%R", color: "#f472b6", style: "line" }],
  scaleMin: -100, scaleMax: 0,
};

const OBV: IndicatorDef = {
  id: "obv", name: "On Balance Volume", shortName: "OBV", type: "oscillator",
  params: [],
  outputs: [{ key: "obv", label: "OBV", color: "#22d3ee", style: "line" }],
};

const MFI: IndicatorDef = {
  id: "mfi", name: "Money Flow Index", shortName: "MFI", type: "oscillator",
  params: [{ key: "length", label: "Period", default: 14, min: 2, max: 100 }],
  outputs: [{ key: "mfi", label: "MFI", color: "#4ade80", style: "line" }],
  scaleMin: 0, scaleMax: 100,
};

// ─── Exports ─────────────────────────────────────────────────────────────────

export const OVERLAYS: IndicatorDef[] = [SMA, EMA, BB, VWAP, PSAR, SUPERTREND, ICHIMOKU, KELTNER, DONCHIAN];
export const OSCILLATORS: IndicatorDef[] = [MACD, RSI, ATR, STOCHASTIC, ADX, CCI, WILLIAMSR, OBV, MFI];
export const ALL_INDICATORS: IndicatorDef[] = [...OVERLAYS, ...OSCILLATORS];

export function getIndicatorById(id: string): IndicatorDef | undefined {
  return ALL_INDICATORS.find(ind => ind.id === id);
}
