// tradeforge_core/src/indicators.rs
// ─────────────────────────────────────────────────────────────
// Rolling-window indicator calculations in Rust.
//
// SMA, EMA, ATR, Bollinger Bands — the core indicators that
// strategies use on every bar.  In Python these are computed
// via numpy or plain loops; Rust gets them for free in the
// hot loop without crossing the FFI boundary.
//
// These are also exposed to Python via PyO3 for standalone use
// (e.g. parameter sweeps, feature engineering).
// ─────────────────────────────────────────────────────────────

use pyo3::prelude::*;

// ── SMA ───────────────────────────────────────────────────────

/// Incremental Simple Moving Average.
///
/// Maintains a circular buffer for O(1) updates.
#[pyclass]
#[derive(Clone, Debug)]
pub struct SMA {
    period: usize,
    buf: Vec<f64>,
    pos: usize,       // next write position in circular buffer
    sum: f64,
    count: usize,     // how many values have been pushed
}

#[pymethods]
impl SMA {
    #[new]
    pub fn new(period: usize) -> Self {
        Self {
            period,
            buf: vec![0.0; period],
            pos: 0,
            sum: 0.0,
            count: 0,
        }
    }

    /// Push a new value and return the current SMA (NaN if not enough data).
    pub fn push(&mut self, value: f64) -> f64 {
        if self.count >= self.period {
            self.sum -= self.buf[self.pos];
        }
        self.buf[self.pos] = value;
        self.sum += value;
        self.pos = (self.pos + 1) % self.period;
        self.count += 1;

        if self.count >= self.period {
            self.sum / self.period as f64
        } else {
            f64::NAN
        }
    }

    /// Current value without pushing.
    #[getter]
    pub fn value(&self) -> f64 {
        if self.count >= self.period {
            self.sum / self.period as f64
        } else {
            f64::NAN
        }
    }

    /// Whether the indicator is ready (has enough data).
    #[getter]
    pub fn ready(&self) -> bool {
        self.count >= self.period
    }

    /// Reset the indicator.
    pub fn reset(&mut self) {
        self.buf.fill(0.0);
        self.pos = 0;
        self.sum = 0.0;
        self.count = 0;
    }
}

// Rust-only fast path
impl SMA {
    #[inline(always)]
    pub(crate) fn push_fast(&mut self, value: f64) -> f64 {
        if self.count >= self.period {
            self.sum -= self.buf[self.pos];
        }
        self.buf[self.pos] = value;
        self.sum += value;
        self.pos = (self.pos + 1) % self.period;
        self.count += 1;
        if self.count >= self.period {
            self.sum / self.period as f64
        } else {
            f64::NAN
        }
    }
}

// ── EMA ───────────────────────────────────────────────────────

/// Exponential Moving Average with configurable smoothing.
#[pyclass]
#[derive(Clone, Debug)]
pub struct EMA {
    period: usize,
    alpha: f64,
    value_inner: f64,
    count: usize,
    // Use SMA for the seed period
    seed_sum: f64,
}

#[pymethods]
impl EMA {
    #[new]
    #[pyo3(signature = (period, smoothing = 2.0))]
    pub fn new(period: usize, smoothing: f64) -> Self {
        let alpha = smoothing / (period as f64 + 1.0);
        Self {
            period,
            alpha,
            value_inner: f64::NAN,
            count: 0,
            seed_sum: 0.0,
        }
    }

    /// Push a value and return the current EMA.
    pub fn push(&mut self, value: f64) -> f64 {
        self.push_fast(value)
    }

    #[getter]
    pub fn value(&self) -> f64 {
        self.value_inner
    }

    #[getter]
    pub fn ready(&self) -> bool {
        self.count >= self.period
    }

    pub fn reset(&mut self) {
        self.value_inner = f64::NAN;
        self.count = 0;
        self.seed_sum = 0.0;
    }
}

impl EMA {
    #[inline(always)]
    pub(crate) fn push_fast(&mut self, value: f64) -> f64 {
        self.count += 1;
        if self.count < self.period {
            self.seed_sum += value;
            self.value_inner = f64::NAN;
            return f64::NAN;
        }
        if self.count == self.period {
            self.seed_sum += value;
            self.value_inner = self.seed_sum / self.period as f64;
            return self.value_inner;
        }
        // Incremental EMA
        self.value_inner = self.alpha * value + (1.0 - self.alpha) * self.value_inner;
        self.value_inner
    }
}

// ── ATR (Average True Range) ──────────────────────────────────

/// Wilder's ATR: smoothed average of True Range.
#[pyclass]
#[derive(Clone, Debug)]
pub struct ATR {
    period: usize,
    value_inner: f64,
    count: usize,
    prev_close: f64,
    seed_sum: f64,
}

#[pymethods]
impl ATR {
    #[new]
    pub fn new(period: usize) -> Self {
        Self {
            period,
            value_inner: f64::NAN,
            count: 0,
            prev_close: f64::NAN,
            seed_sum: 0.0,
        }
    }

    /// Push a new bar (high, low, close) and return the current ATR.
    #[pyo3(signature = (high, low, close))]
    pub fn push(&mut self, high: f64, low: f64, close: f64) -> f64 {
        self.push_fast(high, low, close)
    }

    #[getter]
    pub fn value(&self) -> f64 {
        self.value_inner
    }

    #[getter]
    pub fn ready(&self) -> bool {
        self.count >= self.period
    }

    pub fn reset(&mut self) {
        self.value_inner = f64::NAN;
        self.count = 0;
        self.prev_close = f64::NAN;
        self.seed_sum = 0.0;
    }
}

impl ATR {
    #[inline(always)]
    pub(crate) fn push_fast(&mut self, high: f64, low: f64, close: f64) -> f64 {
        let tr = if self.prev_close.is_nan() {
            high - low
        } else {
            let hl = high - low;
            let hpc = (high - self.prev_close).abs();
            let lpc = (low - self.prev_close).abs();
            hl.max(hpc).max(lpc)
        };
        self.prev_close = close;
        self.count += 1;

        if self.count < self.period {
            self.seed_sum += tr;
            self.value_inner = f64::NAN;
            return f64::NAN;
        }
        if self.count == self.period {
            self.seed_sum += tr;
            self.value_inner = self.seed_sum / self.period as f64;
            return self.value_inner;
        }
        // Wilder smoothing
        self.value_inner = (self.value_inner * (self.period as f64 - 1.0) + tr) / self.period as f64;
        self.value_inner
    }
}

// ── Bollinger Bands ───────────────────────────────────────────

/// Bollinger Bands (SMA ± k × StdDev).
#[pyclass]
#[derive(Clone, Debug)]
pub struct BollingerBands {
    period: usize,
    k: f64,
    buf: Vec<f64>,
    pos: usize,
    sum: f64,
    sum_sq: f64,
    count: usize,
    upper: f64,
    middle: f64,
    lower: f64,
}

#[pymethods]
impl BollingerBands {
    #[new]
    #[pyo3(signature = (period, k = 2.0))]
    pub fn new(period: usize, k: f64) -> Self {
        Self {
            period,
            k,
            buf: vec![0.0; period],
            pos: 0,
            sum: 0.0,
            sum_sq: 0.0,
            count: 0,
            upper: f64::NAN,
            middle: f64::NAN,
            lower: f64::NAN,
        }
    }

    /// Push a new value and return (upper, middle, lower).
    pub fn push(&mut self, value: f64) -> (f64, f64, f64) {
        self.push_fast(value)
    }

    #[getter]
    pub fn upper(&self) -> f64 { self.upper }
    #[getter]
    pub fn middle(&self) -> f64 { self.middle }
    #[getter]
    pub fn lower(&self) -> f64 { self.lower }
    #[getter]
    pub fn ready(&self) -> bool { self.count >= self.period }

    pub fn reset(&mut self) {
        self.buf.fill(0.0);
        self.pos = 0;
        self.sum = 0.0;
        self.sum_sq = 0.0;
        self.count = 0;
        self.upper = f64::NAN;
        self.middle = f64::NAN;
        self.lower = f64::NAN;
    }
}

impl BollingerBands {
    #[inline(always)]
    pub(crate) fn push_fast(&mut self, value: f64) -> (f64, f64, f64) {
        if self.count >= self.period {
            let old = self.buf[self.pos];
            self.sum -= old;
            self.sum_sq -= old * old;
        }
        self.buf[self.pos] = value;
        self.sum += value;
        self.sum_sq += value * value;
        self.pos = (self.pos + 1) % self.period;
        self.count += 1;

        if self.count < self.period {
            self.upper = f64::NAN;
            self.middle = f64::NAN;
            self.lower = f64::NAN;
            return (f64::NAN, f64::NAN, f64::NAN);
        }

        let n = self.period as f64;
        let mean = self.sum / n;
        let variance = (self.sum_sq / n) - (mean * mean);
        let std = if variance > 0.0 { variance.sqrt() } else { 0.0 };
        self.middle = mean;
        self.upper = mean + self.k * std;
        self.lower = mean - self.k * std;
        (self.upper, self.middle, self.lower)
    }
}

// ── Batch compute (vectorised) ────────────────────────────────

/// Compute SMA over an entire price array at once.
/// Returns a Vec of the same length (NaN for warm-up period).
#[pyfunction]
pub fn sma_array(values: Vec<f64>, period: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; values.len()];
    if period == 0 || values.is_empty() {
        return out;
    }
    let mut ind = SMA::new(period);
    for (i, &v) in values.iter().enumerate() {
        out[i] = ind.push_fast(v);
    }
    out
}

/// Compute EMA over an entire price array at once.
#[pyfunction]
#[pyo3(signature = (values, period, smoothing = 2.0))]
pub fn ema_array(values: Vec<f64>, period: usize, smoothing: f64) -> Vec<f64> {
    let mut out = vec![f64::NAN; values.len()];
    if period == 0 || values.is_empty() {
        return out;
    }
    let mut ind = EMA::new(period, smoothing);
    for (i, &v) in values.iter().enumerate() {
        out[i] = ind.push_fast(v);
    }
    out
}

/// Compute ATR over OHLC arrays at once.
/// high, low, close must have equal length.
#[pyfunction]
pub fn atr_array(high: Vec<f64>, low: Vec<f64>, close: Vec<f64>, period: usize) -> Vec<f64> {
    let n = high.len().min(low.len()).min(close.len());
    let mut out = vec![f64::NAN; n];
    if period == 0 || n == 0 {
        return out;
    }
    let mut ind = ATR::new(period);
    for i in 0..n {
        out[i] = ind.push_fast(high[i], low[i], close[i]);
    }
    out
}

// ── IndicatorSet ──────────────────────────────────────────────

/// A set of pre-configured indicators for one symbol.
///
/// Used by the FastRunner to maintain rolling indicator state
/// across bars without repeated allocation.
#[derive(Clone)]
pub(crate) struct IndicatorSet {
    pub sma_fast: Option<SMA>,
    pub sma_slow: Option<SMA>,
    pub ema_fast: Option<EMA>,
    pub ema_slow: Option<EMA>,
    pub atr: Option<ATR>,
    pub bb: Option<BollingerBands>,
}

impl IndicatorSet {
    pub fn empty() -> Self {
        Self {
            sma_fast: None,
            sma_slow: None,
            ema_fast: None,
            ema_slow: None,
            atr: None,
            bb: None,
        }
    }

    /// Push a bar's data through all configured indicators.
    /// Returns a small struct with computed values.
    #[inline]
    pub fn update(&mut self, open: f64, high: f64, low: f64, close: f64) -> IndicatorValues {
        let sma_f = self.sma_fast.as_mut().map(|s| s.push_fast(close));
        let sma_s = self.sma_slow.as_mut().map(|s| s.push_fast(close));
        let ema_f = self.ema_fast.as_mut().map(|e| e.push_fast(close));
        let ema_s = self.ema_slow.as_mut().map(|e| e.push_fast(close));
        let atr_v = self.atr.as_mut().map(|a| a.push_fast(high, low, close));
        let bb_v =  self.bb.as_mut().map(|b| b.push_fast(close));

        IndicatorValues {
            sma_fast: sma_f.unwrap_or(f64::NAN),
            sma_slow: sma_s.unwrap_or(f64::NAN),
            ema_fast: ema_f.unwrap_or(f64::NAN),
            ema_slow: ema_s.unwrap_or(f64::NAN),
            atr: atr_v.unwrap_or(f64::NAN),
            bb_upper: bb_v.map_or(f64::NAN, |v| v.0),
            bb_middle: bb_v.map_or(f64::NAN, |v| v.1),
            bb_lower: bb_v.map_or(f64::NAN, |v| v.2),
        }
    }
}

/// Computed indicator values for one bar.
#[pyclass]
#[derive(Clone, Copy, Debug)]
pub struct IndicatorValues {
    #[pyo3(get)]
    pub sma_fast: f64,
    #[pyo3(get)]
    pub sma_slow: f64,
    #[pyo3(get)]
    pub ema_fast: f64,
    #[pyo3(get)]
    pub ema_slow: f64,
    #[pyo3(get)]
    pub atr: f64,
    #[pyo3(get)]
    pub bb_upper: f64,
    #[pyo3(get)]
    pub bb_middle: f64,
    #[pyo3(get)]
    pub bb_lower: f64,
}

// ── Tests ─────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sma_basic() {
        let mut s = SMA::new(3);
        assert!(s.push(1.0).is_nan());
        assert!(s.push(2.0).is_nan());
        let v = s.push(3.0);
        assert!((v - 2.0).abs() < 1e-10); // (1+2+3)/3
        let v = s.push(4.0);
        assert!((v - 3.0).abs() < 1e-10); // (2+3+4)/3
    }

    #[test]
    fn test_ema_basic() {
        let mut e = EMA::new(3, 2.0);
        assert!(e.push(1.0).is_nan());
        assert!(e.push(2.0).is_nan());
        let v = e.push(3.0); // seed = (1+2+3)/3 = 2.0
        assert!((v - 2.0).abs() < 1e-10);
        let v = e.push(4.0); // alpha=0.5, 0.5*4+0.5*2 = 3.0
        assert!((v - 3.0).abs() < 1e-10);
    }

    #[test]
    fn test_atr_basic() {
        let mut a = ATR::new(2);
        let _ = a.push(10.0, 8.0, 9.0);   // TR=2, not ready
        let v = a.push(11.0, 7.0, 10.0);   // TR=max(4, |11-9|, |7-9|) = 4
        // ATR = (2+4)/2 = 3.0
        assert!((v - 3.0).abs() < 1e-10);
    }

    #[test]
    fn test_bollinger_basic() {
        let mut bb = BollingerBands::new(3, 2.0);
        bb.push(10.0);
        bb.push(10.0);
        let (u, m, l) = bb.push(10.0);
        assert!((m - 10.0).abs() < 1e-10);
        assert!((u - 10.0).abs() < 1e-10); // zero std
        assert!((l - 10.0).abs() < 1e-10);
    }

    #[test]
    fn test_sma_array() {
        let data = vec![1.0, 2.0, 3.0, 4.0, 5.0];
        let result = sma_array(data, 3);
        assert!(result[0].is_nan());
        assert!(result[1].is_nan());
        assert!((result[2] - 2.0).abs() < 1e-10);
        assert!((result[3] - 3.0).abs() < 1e-10);
        assert!((result[4] - 4.0).abs() < 1e-10);
    }
}
