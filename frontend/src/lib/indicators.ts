/**
 * FlowrexAlgo — Indicator Calculation Library
 *
 * Pure-function implementations for 18 technical indicators.
 * Each function accepts arrays of numbers and returns arrays of (number | null).
 * null entries represent periods where insufficient data exists.
 */

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Simple Moving Average */
export function calcSMA(values: number[], len: number): (number | null)[] {
  const out: (number | null)[] = [];
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= len) sum -= values[i - len];
    out.push(i >= len - 1 ? sum / len : null);
  }
  return out;
}

/** Exponential Moving Average */
export function calcEMA(values: number[], len: number): (number | null)[] {
  const k = 2 / (len + 1);
  const out: (number | null)[] = [];
  let ema: number | null = null;
  for (let i = 0; i < values.length; i++) {
    if (i < len - 1) { out.push(null); continue; }
    if (ema === null) {
      ema = values.slice(0, len).reduce((a, b) => a + b, 0) / len;
    } else {
      ema = values[i] * k + ema * (1 - k);
    }
    out.push(ema);
  }
  return out;
}

/** Wilder-style smoothed moving average (used in RSI, ATR, ADX) */
function wilderSmooth(values: number[], len: number): (number | null)[] {
  const out: (number | null)[] = [];
  let avg: number | null = null;
  for (let i = 0; i < values.length; i++) {
    if (i < len - 1) { out.push(null); continue; }
    if (avg === null) {
      avg = values.slice(0, len).reduce((a, b) => a + b, 0) / len;
    } else {
      avg = (avg * (len - 1) + values[i]) / len;
    }
    out.push(avg);
  }
  return out;
}

/** True Range */
function trueRange(highs: number[], lows: number[], closes: number[]): number[] {
  const tr: number[] = [highs[0] - lows[0]];
  for (let i = 1; i < highs.length; i++) {
    tr.push(Math.max(
      highs[i] - lows[i],
      Math.abs(highs[i] - closes[i - 1]),
      Math.abs(lows[i] - closes[i - 1])
    ));
  }
  return tr;
}

// ─── Overlay Indicators ───────────────────────────────────────────────────────

/** Bollinger Bands: { upper, middle, lower } */
export function calcBollingerBands(
  closes: number[], len = 20, mult = 2
): { upper: (number | null)[]; middle: (number | null)[]; lower: (number | null)[] } {
  const middle = calcSMA(closes, len);
  const upper: (number | null)[] = [];
  const lower: (number | null)[] = [];
  for (let i = 0; i < closes.length; i++) {
    if (middle[i] === null) { upper.push(null); lower.push(null); continue; }
    const slice = closes.slice(i - len + 1, i + 1);
    const mean = middle[i]!;
    const std = Math.sqrt(slice.reduce((s, v) => s + (v - mean) ** 2, 0) / len);
    upper.push(mean + mult * std);
    lower.push(mean - mult * std);
  }
  return { upper, middle, lower };
}

/** VWAP (Volume Weighted Average Price) — resets each day */
export function calcVWAP(
  highs: number[], lows: number[], closes: number[], volumes: number[], times: number[]
): (number | null)[] {
  const out: (number | null)[] = [];
  let cumVol = 0;
  let cumTP = 0;
  let lastDay = -1;
  for (let i = 0; i < closes.length; i++) {
    const day = Math.floor(times[i] / 86400);
    if (day !== lastDay) {
      cumVol = 0;
      cumTP = 0;
      lastDay = day;
    }
    const tp = (highs[i] + lows[i] + closes[i]) / 3;
    cumVol += volumes[i] || 1;
    cumTP += tp * (volumes[i] || 1);
    out.push(cumVol > 0 ? cumTP / cumVol : null);
  }
  return out;
}

/** Parabolic SAR */
export function calcParabolicSAR(
  highs: number[], lows: number[], afStart = 0.02, afStep = 0.02, afMax = 0.2
): (number | null)[] {
  const n = highs.length;
  if (n < 2) return new Array(n).fill(null);
  const out: (number | null)[] = [null];
  let bull = true;
  let sar = lows[0];
  let ep = highs[0];
  let af = afStart;

  for (let i = 1; i < n; i++) {
    const prevSar = sar;
    sar = prevSar + af * (ep - prevSar);

    if (bull) {
      sar = Math.min(sar, lows[i - 1], i >= 2 ? lows[i - 2] : lows[i - 1]);
      if (lows[i] < sar) {
        bull = false;
        sar = ep;
        ep = lows[i];
        af = afStart;
      } else {
        if (highs[i] > ep) {
          ep = highs[i];
          af = Math.min(af + afStep, afMax);
        }
      }
    } else {
      sar = Math.max(sar, highs[i - 1], i >= 2 ? highs[i - 2] : highs[i - 1]);
      if (highs[i] > sar) {
        bull = true;
        sar = ep;
        ep = highs[i];
        af = afStart;
      } else {
        if (lows[i] < ep) {
          ep = lows[i];
          af = Math.min(af + afStep, afMax);
        }
      }
    }
    out.push(sar);
  }
  return out;
}

/** SuperTrend */
export function calcSuperTrend(
  highs: number[], lows: number[], closes: number[], len = 10, mult = 3
): { supertrend: (number | null)[]; direction: (number | null)[] } {
  const n = closes.length;
  const atr = calcATR(highs, lows, closes, len);
  const st: (number | null)[] = new Array(n).fill(null);
  const dir: (number | null)[] = new Array(n).fill(null);

  let upperBand = 0, lowerBand = 0;
  let prevUpper = 0, prevLower = 0;
  let prevDir = 1;

  for (let i = 0; i < n; i++) {
    if (atr[i] === null) continue;
    const mid = (highs[i] + lows[i]) / 2;
    let ub = mid + mult * atr[i]!;
    let lb = mid - mult * atr[i]!;

    if (prevLower !== 0) lb = closes[i - 1] > prevLower ? Math.max(lb, prevLower) : lb;
    if (prevUpper !== 0) ub = closes[i - 1] < prevUpper ? Math.min(ub, prevUpper) : ub;

    let d: number;
    if (prevDir === 1 && closes[i] < lb) d = -1;
    else if (prevDir === -1 && closes[i] > ub) d = 1;
    else d = prevDir;

    st[i] = d === 1 ? lb : ub;
    dir[i] = d;

    prevUpper = ub;
    prevLower = lb;
    prevDir = d;
    upperBand = ub;
    lowerBand = lb;
  }
  // Suppress unused variable warnings
  void upperBand;
  void lowerBand;
  return { supertrend: st, direction: dir };
}

/** Ichimoku Cloud: tenkan, kijun, senkouA, senkouB, chikou */
export function calcIchimoku(
  highs: number[], lows: number[], closes: number[],
  tenkanLen = 9, kijunLen = 26, senkouBLen = 52, displacement = 26
): {
  tenkan: (number | null)[];
  kijun: (number | null)[];
  senkouA: (number | null)[];
  senkouB: (number | null)[];
  chikou: (number | null)[];
} {
  const n = closes.length;
  const midHL = (h: number[], l: number[], start: number, len: number) => {
    let hi = -Infinity, lo = Infinity;
    for (let j = start; j < start + len && j < h.length; j++) {
      hi = Math.max(hi, h[j]);
      lo = Math.min(lo, l[j]);
    }
    return (hi + lo) / 2;
  };

  const tenkan: (number | null)[] = [];
  const kijun: (number | null)[] = [];
  const senkouA: (number | null)[] = new Array(n + displacement).fill(null);
  const senkouB: (number | null)[] = new Array(n + displacement).fill(null);
  const chikou: (number | null)[] = new Array(n).fill(null);

  for (let i = 0; i < n; i++) {
    tenkan.push(i >= tenkanLen - 1 ? midHL(highs, lows, i - tenkanLen + 1, tenkanLen) : null);
    kijun.push(i >= kijunLen - 1 ? midHL(highs, lows, i - kijunLen + 1, kijunLen) : null);

    if (tenkan[i] !== null && kijun[i] !== null) {
      senkouA[i + displacement] = (tenkan[i]! + kijun[i]!) / 2;
    }
    if (i >= senkouBLen - 1) {
      senkouB[i + displacement] = midHL(highs, lows, i - senkouBLen + 1, senkouBLen);
    }
    if (i >= displacement) {
      chikou[i - displacement] = closes[i];
    }
  }

  // Trim senkouA/B to n length (future projection beyond data is discarded)
  return {
    tenkan,
    kijun,
    senkouA: senkouA.slice(0, n),
    senkouB: senkouB.slice(0, n),
    chikou,
  };
}

/** Keltner Channels: upper, middle (EMA), lower */
export function calcKeltnerChannels(
  highs: number[], lows: number[], closes: number[], emaLen = 20, atrLen = 10, mult = 1.5
): { upper: (number | null)[]; middle: (number | null)[]; lower: (number | null)[] } {
  const middle = calcEMA(closes, emaLen);
  const atr = calcATR(highs, lows, closes, atrLen);
  const upper: (number | null)[] = [];
  const lower: (number | null)[] = [];
  for (let i = 0; i < closes.length; i++) {
    if (middle[i] === null || atr[i] === null) { upper.push(null); lower.push(null); continue; }
    upper.push(middle[i]! + mult * atr[i]!);
    lower.push(middle[i]! - mult * atr[i]!);
  }
  return { upper, middle, lower };
}

/** Donchian Channels: upper (highest high), lower (lowest low), middle */
export function calcDonchianChannels(
  highs: number[], lows: number[], len = 20
): { upper: (number | null)[]; middle: (number | null)[]; lower: (number | null)[] } {
  const upper: (number | null)[] = [];
  const lower: (number | null)[] = [];
  const middle: (number | null)[] = [];
  for (let i = 0; i < highs.length; i++) {
    if (i < len - 1) { upper.push(null); lower.push(null); middle.push(null); continue; }
    let hi = -Infinity, lo = Infinity;
    for (let j = i - len + 1; j <= i; j++) {
      hi = Math.max(hi, highs[j]);
      lo = Math.min(lo, lows[j]);
    }
    upper.push(hi);
    lower.push(lo);
    middle.push((hi + lo) / 2);
  }
  return { upper, middle, lower };
}

// ─── Oscillator Indicators ────────────────────────────────────────────────────

/** MACD: { macd, signal, histogram } */
export function calcMACD(
  closes: number[], fast = 12, slow = 26, signal = 9
): { macd: (number | null)[]; signal: (number | null)[]; histogram: (number | null)[] } {
  const emaFast = calcEMA(closes, fast);
  const emaSlow = calcEMA(closes, slow);
  const macdLine: (number | null)[] = emaFast.map((v, i) =>
    v !== null && emaSlow[i] !== null ? v - emaSlow[i]! : null
  );
  const macdClean = macdLine.filter(v => v !== null) as number[];
  const startIdx = macdLine.findIndex(v => v !== null);
  const sigRaw = calcEMA(macdClean, signal);
  const sigLine: (number | null)[] = [...Array(startIdx < 0 ? 0 : startIdx).fill(null), ...sigRaw];
  // Pad to same length
  while (sigLine.length < closes.length) sigLine.push(null);

  const hist: (number | null)[] = macdLine.map((v, i) =>
    v !== null && sigLine[i] !== null ? v - sigLine[i]! : null
  );
  return { macd: macdLine, signal: sigLine, histogram: hist };
}

/** RSI (Wilder smoothing) */
export function calcRSI(closes: number[], len = 14): (number | null)[] {
  if (closes.length < len + 1) return new Array(closes.length).fill(null);
  const gains: number[] = [0];
  const losses: number[] = [0];
  for (let i = 1; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1];
    gains.push(diff > 0 ? diff : 0);
    losses.push(diff < 0 ? -diff : 0);
  }
  const avgGain = wilderSmooth(gains, len);
  const avgLoss = wilderSmooth(losses, len);
  return avgGain.map((g, i) => {
    if (g === null || avgLoss[i] === null) return null;
    const l = avgLoss[i]!;
    if (l === 0) return 100;
    const rs = g / l;
    return 100 - 100 / (1 + rs);
  });
}

/** ATR (Average True Range) */
export function calcATR(
  highs: number[], lows: number[], closes: number[], len = 14
): (number | null)[] {
  const tr = trueRange(highs, lows, closes);
  return wilderSmooth(tr, len);
}

/** Stochastic Oscillator: { k, d } */
export function calcStochastic(
  highs: number[], lows: number[], closes: number[], kLen = 14, dLen = 3
): { k: (number | null)[]; d: (number | null)[] } {
  const kLine: (number | null)[] = [];
  for (let i = 0; i < closes.length; i++) {
    if (i < kLen - 1) { kLine.push(null); continue; }
    let hi = -Infinity, lo = Infinity;
    for (let j = i - kLen + 1; j <= i; j++) {
      hi = Math.max(hi, highs[j]);
      lo = Math.min(lo, lows[j]);
    }
    kLine.push(hi === lo ? 50 : ((closes[i] - lo) / (hi - lo)) * 100);
  }
  const kClean = kLine.filter(v => v !== null) as number[];
  const dRaw = calcSMA(kClean, dLen);
  const startIdx = kLine.findIndex(v => v !== null);
  const dLine: (number | null)[] = [...Array(startIdx < 0 ? 0 : startIdx).fill(null), ...dRaw];
  while (dLine.length < closes.length) dLine.push(null);
  return { k: kLine, d: dLine };
}

/** ADX (Average Directional Index): { adx, plusDI, minusDI } */
export function calcADX(
  highs: number[], lows: number[], closes: number[], len = 14
): { adx: (number | null)[]; plusDI: (number | null)[]; minusDI: (number | null)[] } {
  const n = closes.length;
  const plusDM: number[] = [0];
  const minusDM: number[] = [0];
  for (let i = 1; i < n; i++) {
    const upMove = highs[i] - highs[i - 1];
    const downMove = lows[i - 1] - lows[i];
    plusDM.push(upMove > downMove && upMove > 0 ? upMove : 0);
    minusDM.push(downMove > upMove && downMove > 0 ? downMove : 0);
  }
  const atr = calcATR(highs, lows, closes, len);
  const smoothPlusDM = wilderSmooth(plusDM, len);
  const smoothMinusDM = wilderSmooth(minusDM, len);

  const plusDI: (number | null)[] = [];
  const minusDI: (number | null)[] = [];
  const dx: (number | null)[] = [];

  for (let i = 0; i < n; i++) {
    if (atr[i] === null || smoothPlusDM[i] === null || smoothMinusDM[i] === null || atr[i] === 0) {
      plusDI.push(null); minusDI.push(null); dx.push(null); continue;
    }
    const pdi = (smoothPlusDM[i]! / atr[i]!) * 100;
    const mdi = (smoothMinusDM[i]! / atr[i]!) * 100;
    plusDI.push(pdi);
    minusDI.push(mdi);
    const sum = pdi + mdi;
    dx.push(sum === 0 ? 0 : (Math.abs(pdi - mdi) / sum) * 100);
  }

  const dxClean = dx.filter(v => v !== null) as number[];
  const adxRaw = wilderSmooth(dxClean, len);
  const startIdx = dx.findIndex(v => v !== null);
  const adx: (number | null)[] = [...Array(startIdx < 0 ? 0 : startIdx).fill(null), ...adxRaw];
  while (adx.length < n) adx.push(null);

  return { adx, plusDI, minusDI };
}

/** CCI (Commodity Channel Index) */
export function calcCCI(
  highs: number[], lows: number[], closes: number[], len = 20
): (number | null)[] {
  const tp: number[] = [];
  for (let i = 0; i < closes.length; i++) {
    tp.push((highs[i] + lows[i] + closes[i]) / 3);
  }
  const sma = calcSMA(tp, len);
  return sma.map((mean, i) => {
    if (mean === null) return null;
    const slice = tp.slice(i - len + 1, i + 1);
    const mad = slice.reduce((s, v) => s + Math.abs(v - mean), 0) / len;
    return mad === 0 ? 0 : (tp[i] - mean) / (0.015 * mad);
  });
}

/** Williams %R */
export function calcWilliamsR(
  highs: number[], lows: number[], closes: number[], len = 14
): (number | null)[] {
  const out: (number | null)[] = [];
  for (let i = 0; i < closes.length; i++) {
    if (i < len - 1) { out.push(null); continue; }
    let hi = -Infinity, lo = Infinity;
    for (let j = i - len + 1; j <= i; j++) {
      hi = Math.max(hi, highs[j]);
      lo = Math.min(lo, lows[j]);
    }
    out.push(hi === lo ? -50 : ((hi - closes[i]) / (hi - lo)) * -100);
  }
  return out;
}

/** OBV (On Balance Volume) */
export function calcOBV(closes: number[], volumes: number[]): (number | null)[] {
  const out: (number | null)[] = [volumes[0] || 0];
  for (let i = 1; i < closes.length; i++) {
    const prev = (out[i - 1] as number) || 0;
    if (closes[i] > closes[i - 1]) out.push(prev + (volumes[i] || 0));
    else if (closes[i] < closes[i - 1]) out.push(prev - (volumes[i] || 0));
    else out.push(prev);
  }
  return out;
}

/** MFI (Money Flow Index) */
export function calcMFI(
  highs: number[], lows: number[], closes: number[], volumes: number[], len = 14
): (number | null)[] {
  const tp: number[] = [];
  for (let i = 0; i < closes.length; i++) {
    tp.push((highs[i] + lows[i] + closes[i]) / 3);
  }
  const out: (number | null)[] = [];
  for (let i = 0; i < closes.length; i++) {
    if (i < len) { out.push(null); continue; }
    let posFlow = 0, negFlow = 0;
    for (let j = i - len + 1; j <= i; j++) {
      const mf = tp[j] * (volumes[j] || 1);
      if (tp[j] > tp[j - 1]) posFlow += mf;
      else if (tp[j] < tp[j - 1]) negFlow += mf;
    }
    out.push(negFlow === 0 ? 100 : 100 - 100 / (1 + posFlow / negFlow));
  }
  return out;
}
