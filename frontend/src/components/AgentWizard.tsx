"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { useBrokerAccounts } from "@/hooks/useBrokerAccounts";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import {
  Zap, Brain, ChevronLeft, ChevronRight, Rocket, AlertTriangle, Lock,
} from "lucide-react";
import type { AgentCreateRequest, AgentMode } from "@/types";

/* ── Types ─────────────────────────────────────────────── */

interface AgentAvailability {
  scalping: { available: boolean; grade?: string; sharpe?: number; symbols: string[] };
  expert: { available: boolean; grade?: string; sharpe?: number; symbols: string[] };
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => void;
}

/* ── Constants ─────────────────────────────────────────── */

const FALLBACK_SYMBOLS = ["XAUUSD", "XAGUSD", "US30", "NAS100", "EURUSD", "BTCUSD"];
const POPULAR_SYMBOLS = ["XAUUSD", "US30", "BTCUSD", "NAS100", "EURUSD"];

// Hardcoded model availability until backend endpoint exists
const DEFAULT_AVAILABILITY: AgentAvailability = {
  scalping: { available: true, grade: undefined, sharpe: undefined, symbols: ["XAUUSD", "US30"] },
  expert: { available: true, grade: undefined, sharpe: undefined, symbols: ["XAUUSD", "US30", "BTCUSD"] },
};

/* ═══════════════════════════════════════════════════════ */

export default function AgentWizard({ open, onOpenChange, onCreated }: Props) {
  /* ── Step state ── */
  const [step, setStep] = useState(0);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  /* ── Step 1: Symbol ── */
  const [symbol, setSymbol] = useState("XAUUSD");
  const [symbolInput, setSymbolInput] = useState("XAUUSD");
  const [symbolDropdownOpen, setSymbolDropdownOpen] = useState(false);
  const [brokerSymbols, setBrokerSymbols] = useState<string[]>([]);
  const [customSymbols, setCustomSymbols] = useState<string[]>([]);
  const [recentSymbols] = useState<string[]>(() => {
    try {
      if (typeof window === "undefined") return [];
      return JSON.parse(localStorage.getItem("tf_recent_symbols") ?? "[]");
    } catch { return []; }
  });

  /* ── Step 2: Agent Type ── */
  const [agentType, setAgentType] = useState<"scalping" | "expert">("scalping");
  const [availability, setAvailability] = useState<AgentAvailability>(DEFAULT_AVAILABILITY);
  const [timeframe, setTimeframe] = useState("M5");

  /* ── Step 3: Risk Config ── */
  const [sizeType, setSizeType] = useState("percent_risk");
  const [riskPerTrade, setRiskPerTrade] = useState("0.5");
  const [maxDailyLoss, setMaxDailyLoss] = useState("4");
  const [maxDrawdown, setMaxDrawdown] = useState("8");
  const [maxPositions, setMaxPositions] = useState("3");
  const [propFirmId, setPropFirmId] = useState<number | null>(null);
  const [propFirmAccounts, setPropFirmAccounts] = useState<{ id: number; account_name: string; firm_name: string; status: string }[]>([]);

  // Agent-specific settings
  const [minConfidence, setMinConfidence] = useState("0.55");
  const [sessionFilter, setSessionFilter] = useState(true);
  const [newsFilter, setNewsFilter] = useState(true);
  const [regimeFilter, setRegimeFilter] = useState(true);
  const [minAgreement, setMinAgreement] = useState("2");

  /* ── Step 4: Mode & Deploy ── */
  const [agentName, setAgentName] = useState("");
  const [mode, setMode] = useState<AgentMode>("paper");
  const [broker, setBroker] = useState("");

  const { accounts: brokerAccounts, activeBroker } = useBrokerAccounts();

  /* ── Effects ── */

  // Reset wizard on open
  useEffect(() => {
    if (open) {
      setStep(0);
      setError("");
      setCreating(false);
    }
  }, [open]);

  // Auto-set broker from active
  useEffect(() => {
    if (activeBroker && !broker) setBroker(activeBroker);
  }, [activeBroker, broker]);

  // Fetch broker symbols
  useEffect(() => {
    if (!broker) return;
    api
      .get<{ symbol: string; display_name: string; asset_class: string; tradeable: boolean }[]>(
        `/api/broker/symbols?broker=${encodeURIComponent(broker)}`
      )
      .then((syms) => {
        setBrokerSymbols(
          (Array.isArray(syms) ? syms : [])
            .filter((s) => s.tradeable !== false)
            .map((s) => s.symbol)
        );
      })
      .catch(() => setBrokerSymbols([]));
  }, [broker]);

  // Fetch prop firm accounts
  useEffect(() => {
    api
      .get<{ id: number; account_name: string; firm_name: string; status: string }[]>("/api/prop-firm/")
      .then((accts) => setPropFirmAccounts(Array.isArray(accts) ? accts : []))
      .catch(() => setPropFirmAccounts([]));
  }, []);

  // Try to fetch available agents from backend
  useEffect(() => {
    api
      .get<AgentAvailability>(`/api/ml/available-agents?symbol=${symbol}`)
      .then(setAvailability)
      .catch(() => {
        // Fallback: determine availability from known supported symbols
        setAvailability({
          scalping: {
            ...DEFAULT_AVAILABILITY.scalping,
            available: DEFAULT_AVAILABILITY.scalping.symbols.includes(symbol),
          },
          expert: {
            ...DEFAULT_AVAILABILITY.expert,
            available: DEFAULT_AVAILABILITY.expert.symbols.includes(symbol),
          },
        });
      });
  }, [symbol]);

  // Auto-generate agent name when symbol or type changes
  useEffect(() => {
    const typeLabel = agentType === "scalping" ? "Scalping" : "Expert";
    setAgentName(`${symbol} ${typeLabel} Agent`);
  }, [symbol, agentType]);

  /* ── Helpers ── */

  const allSymbols = [...new Set([...FALLBACK_SYMBOLS, ...brokerSymbols, ...customSymbols])];
  const filteredSymbols = symbolInput
    ? allSymbols.filter((s) => s.toUpperCase().includes(symbolInput.toUpperCase()))
    : allSymbols;

  const applySymbol = (sym: string) => {
    const upper = sym.trim().toUpperCase();
    if (!upper) return;
    if (!allSymbols.includes(upper)) {
      setCustomSymbols((prev) => [...prev, upper]);
    }
    setSymbol(upper);
    setSymbolInput(upper);
    setSymbolDropdownOpen(false);
  };

  const isAgentAvailable = (type: "scalping" | "expert") => availability[type].available;

  const canProceedStep = () => {
    switch (step) {
      case 0: return !!symbol;
      case 1: return isAgentAvailable(agentType);
      case 2: return true;
      case 3: return !!agentName && (mode === "paper" || !!broker);
      default: return false;
    }
  };

  /* ── Deploy ── */

  const handleDeploy = async () => {
    setCreating(true);
    setError("");
    try {
      const riskConfig: Record<string, unknown> = agentType === "scalping"
        ? {
            agent_type: "scalping",
            risk_per_trade: parseFloat(riskPerTrade) / 100 || 0.005,
            position_size_type: sizeType,
            position_size_value: parseFloat(riskPerTrade) || 0.5,
            max_daily_loss_pct: parseFloat(maxDailyLoss) || 4,
            max_drawdown_pct: parseFloat(maxDrawdown) || 8,
            max_open_positions: parseInt(maxPositions) || 2,
            min_confidence: parseFloat(minConfidence) || 0.55,
            session_filter: sessionFilter,
            min_bars_between_trades: 3,
          }
        : {
            agent_type: "expert",
            risk_per_trade: parseFloat(riskPerTrade) / 100 || 0.005,
            position_size_type: sizeType,
            position_size_value: parseFloat(riskPerTrade) || 0.5,
            max_daily_loss_pct: parseFloat(maxDailyLoss) || 4,
            max_drawdown_pct: parseFloat(maxDrawdown) || 8,
            max_open_positions: parseInt(maxPositions) || 2,
            news_filter_enabled: newsFilter,
            news_window_minutes: 15,
            ensemble_min_agreement: parseInt(minAgreement) || 2,
            ensemble_min_confidence: parseFloat(minConfidence) || 0.55,
            session_filter: sessionFilter,
            regime_filter: regimeFilter,
          };

      const data: AgentCreateRequest = {
        name: agentName,
        strategy_id: null,
        symbol,
        timeframe,
        mode,
        broker_name: broker || activeBroker || "",
        risk_config: riskConfig,
        prop_firm_account_id: propFirmId,
      };

      await api.post("/api/agents", data);
      onCreated();
      onOpenChange(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCreating(false);
    }
  };

  /* ── Step Headers ── */
  const stepTitles = [
    "Select Symbol",
    "Choose Agent Type",
    "Configure Risk",
    "Review & Deploy",
  ];

  /* ═══════════ RENDER ═══════════════════════════════════ */
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>New Agent — {stepTitles[step]}</DialogTitle>
          <DialogDescription>Step {step + 1} of 4</DialogDescription>
        </DialogHeader>

        {/* Step indicator */}
        <div className="flex items-center gap-1.5 mb-4">
          {stepTitles.map((_, i) => (
            <div
              key={i}
              className={`h-1.5 rounded-full transition-all ${
                i === step ? "w-10 bg-accent" : i < step ? "w-6 bg-accent/40" : "w-6 bg-card-border"
              }`}
            />
          ))}
        </div>

        {error && (
          <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-2 text-xs text-red-400 mb-3">
            {error}
          </div>
        )}

        {/* ═══ STEP 0: Symbol Selection ═══ */}
        {step === 0 && (
          <div className="space-y-4">
            <div>
              <Label className="text-xs text-muted-foreground mb-1.5">Search or select a symbol</Label>
              <div className="relative">
                <input
                  value={symbolInput}
                  onChange={(e) => { setSymbolInput(e.target.value.toUpperCase()); setSymbolDropdownOpen(true); }}
                  onFocus={() => setSymbolDropdownOpen(true)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") { e.preventDefault(); applySymbol(symbolInput); }
                    if (e.key === "Escape") setSymbolDropdownOpen(false);
                  }}
                  onBlur={() => setTimeout(() => setSymbolDropdownOpen(false), 150)}
                  className="w-full rounded-lg border border-card-border bg-background px-3 py-2.5 text-sm outline-none focus:border-accent"
                  placeholder="e.g. XAUUSD"
                />
                {symbolDropdownOpen && filteredSymbols.length > 0 && (
                  <div className="absolute z-50 top-full left-0 right-0 mt-1 rounded-lg border border-card-border bg-card-bg shadow-lg max-h-40 overflow-y-auto">
                    {filteredSymbols.map((s) => (
                      <button
                        key={s}
                        onMouseDown={() => applySymbol(s)}
                        className={`w-full text-left px-3 py-1.5 text-sm hover:bg-card-border transition-colors ${
                          s === symbol ? "text-accent" : "text-foreground"
                        }`}
                      >
                        {s}
                      </button>
                    ))}
                    {symbolInput && !filteredSymbols.includes(symbolInput.toUpperCase()) && (
                      <button
                        onMouseDown={() => applySymbol(symbolInput)}
                        className="w-full text-left px-3 py-1.5 text-sm text-accent hover:bg-card-border transition-colors"
                      >
                        + Use &quot;{symbolInput}&quot;
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>

            <div>
              <Label className="text-xs text-muted-foreground mb-1.5">Popular</Label>
              <div className="flex flex-wrap gap-2">
                {POPULAR_SYMBOLS.map((s) => (
                  <button
                    key={s}
                    onClick={() => applySymbol(s)}
                    className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                      symbol === s
                        ? "border-accent bg-accent/10 text-accent"
                        : "border-card-border text-muted-foreground hover:border-accent/40 hover:text-foreground"
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>

            {recentSymbols.length > 0 && (
              <div>
                <Label className="text-xs text-muted-foreground mb-1.5">Recent</Label>
                <div className="flex flex-wrap gap-2">
                  {recentSymbols.filter((s) => !POPULAR_SYMBOLS.includes(s)).map((s) => (
                    <button
                      key={s}
                      onClick={() => applySymbol(s)}
                      className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                        symbol === s
                          ? "border-accent bg-accent/10 text-accent"
                          : "border-card-border text-muted-foreground hover:border-accent/40"
                      }`}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ═══ STEP 1: Agent Type Selection ═══ */}
        {step === 1 && (
          <div className="space-y-3">
            {/* Scalping Agent Card */}
            <button
              onClick={() => isAgentAvailable("scalping") && setAgentType("scalping")}
              disabled={!isAgentAvailable("scalping")}
              className={`w-full text-left rounded-xl border p-4 transition-all ${
                !isAgentAvailable("scalping")
                  ? "opacity-50 border-card-border cursor-not-allowed"
                  : agentType === "scalping"
                    ? "border-amber-500 bg-amber-500/10 shadow-lg shadow-amber-500/5"
                    : "border-card-border hover:border-amber-500/40 cursor-pointer"
              }`}
            >
              <div className="flex items-start justify-between mb-2">
                <div className="flex items-center gap-2">
                  <Zap className="h-5 w-5 text-amber-400" />
                  <span className="font-semibold text-sm">Scalping Agent</span>
                </div>
                {isAgentAvailable("scalping") ? (
                  <div className="flex items-center gap-1.5">
                    {availability.scalping.grade && (
                      <Badge className="bg-green-500/20 text-green-400 text-[10px]">
                        {availability.scalping.grade}
                      </Badge>
                    )}
                    {availability.scalping.sharpe && (
                      <Badge className="bg-accent/20 text-accent text-[10px]">
                        Sharpe {availability.scalping.sharpe}
                      </Badge>
                    )}
                  </div>
                ) : (
                  <Badge className="bg-orange-500/20 text-orange-400 text-[10px] gap-1">
                    <Lock className="h-2.5 w-2.5" /> Training Required
                  </Badge>
                )}
              </div>
              <p className="text-xs text-muted-foreground mb-2">
                XGBoost + LightGBM ensemble. Both models must agree. M5 timeframe with session filtering and ATR-based dynamic SL/TP.
              </p>
              <div className="flex items-center gap-2 text-[10px] text-muted-foreground/70">
                <span>Symbols: {availability.scalping.symbols.join(", ")}</span>
              </div>
            </button>

            {/* Expert Agent Card */}
            <button
              onClick={() => isAgentAvailable("expert") && setAgentType("expert")}
              disabled={!isAgentAvailable("expert")}
              className={`w-full text-left rounded-xl border p-4 transition-all ${
                !isAgentAvailable("expert")
                  ? "opacity-50 border-card-border cursor-not-allowed"
                  : agentType === "expert"
                    ? "border-emerald-500 bg-emerald-500/10 shadow-lg shadow-emerald-500/5"
                    : "border-card-border hover:border-emerald-500/40 cursor-pointer"
              }`}
            >
              <div className="flex items-start justify-between mb-2">
                <div className="flex items-center gap-2">
                  <Brain className="h-5 w-5 text-emerald-400" />
                  <span className="font-semibold text-sm">Expert Agent</span>
                </div>
                {isAgentAvailable("expert") ? (
                  <div className="flex items-center gap-1.5">
                    {availability.expert.grade && (
                      <Badge className="bg-green-500/20 text-green-400 text-[10px]">
                        {availability.expert.grade}
                      </Badge>
                    )}
                    {availability.expert.sharpe && (
                      <Badge className="bg-accent/20 text-accent text-[10px]">
                        Sharpe {availability.expert.sharpe}
                      </Badge>
                    )}
                  </div>
                ) : (
                  <Badge className="bg-orange-500/20 text-orange-400 text-[10px] gap-1">
                    <Lock className="h-2.5 w-2.5" /> Training Required
                  </Badge>
                )}
              </div>
              <p className="text-xs text-muted-foreground mb-2">
                XGBoost + LightGBM + LSTM + Meta-labeler ensemble. Multi-timeframe analysis (M5+H1+H4+D1), news-aware, regime-filtered.
              </p>
              <div className="flex items-center gap-2 text-[10px] text-muted-foreground/70">
                <span>Symbols: {availability.expert.symbols.join(", ")}</span>
              </div>
            </button>

            {/* Timeframe Selection */}
            <div>
              <Label className="block text-xs font-semibold text-foreground mb-2">Timeframe</Label>
              <div className="flex flex-wrap gap-2">
                {["M1", "M5", "M15", "M30", "H1", "H4", "D1"].map((tf) => (
                  <button
                    key={tf}
                    onClick={() => setTimeframe(tf)}
                    className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                      timeframe === tf
                        ? "border-accent bg-accent/10 text-accent"
                        : "border-card-border text-muted-foreground hover:border-accent/40 hover:text-foreground"
                    }`}
                  >
                    {tf}
                  </button>
                ))}
              </div>
              <p className="text-[10px] text-muted-foreground mt-1">
                {agentType === "scalping"
                  ? "M5 recommended for scalping. Shorter timeframes increase trade frequency."
                  : "M5 primary with multi-timeframe analysis (H1, H4, D1)."}
              </p>
            </div>

            {!isAgentAvailable(agentType) && (
              <div className="flex items-center gap-2 rounded-lg bg-orange-500/10 border border-orange-500/20 px-3 py-2 text-xs text-orange-400">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                <span>No trained models for {symbol}. <a href="/ml?view=retrain" className="underline text-accent hover:text-accent/80">Go to ML Lab →</a></span>
              </div>
            )}
          </div>
        )}

        {/* ═══ STEP 2: Risk Configuration ═══ */}
        {step === 2 && (
          <div className="space-y-4">
            {/* Position Sizing */}
            <div>
              <Label className="block text-xs font-semibold text-foreground mb-2">Position Sizing</Label>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="block text-[10px] text-muted-foreground mb-1">Type</Label>
                  <select
                    value={sizeType}
                    onChange={(e) => setSizeType(e.target.value)}
                    className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
                  >
                    <option value="percent_risk">% of Balance</option>
                    <option value="fixed_lot">Fixed Lot</option>
                  </select>
                </div>
                <div>
                  <Label className="block text-[10px] text-muted-foreground mb-1">
                    {sizeType === "percent_risk" ? "Risk per Trade (%)" : "Lot Size"}
                  </Label>
                  <input
                    type="number"
                    step={sizeType === "percent_risk" ? "0.1" : "0.01"}
                    min="0.01"
                    value={riskPerTrade}
                    onChange={(e) => setRiskPerTrade(e.target.value)}
                    className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
                  />
                </div>
              </div>
            </div>

            {/* Risk Limits */}
            <div>
              <Label className="block text-xs font-semibold text-foreground mb-2">Risk Limits</Label>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <Label className="block text-[10px] text-muted-foreground mb-1">Max Daily Loss %</Label>
                  <input
                    type="number" step="0.5" min="0" value={maxDailyLoss}
                    onChange={(e) => setMaxDailyLoss(e.target.value)}
                    className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <Label className="block text-[10px] text-muted-foreground mb-1">Max Drawdown %</Label>
                  <input
                    type="number" step="1" min="0" value={maxDrawdown}
                    onChange={(e) => setMaxDrawdown(e.target.value)}
                    className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <Label className="block text-[10px] text-muted-foreground mb-1">Max Positions</Label>
                  <input
                    type="number" step="1" min="1" value={maxPositions}
                    onChange={(e) => setMaxPositions(e.target.value)}
                    className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
                  />
                </div>
              </div>
            </div>

            {/* Prop Firm Account (optional) */}
            {propFirmAccounts.filter((a) => a.status === "active").length > 0 && (
              <div>
                <Label className="text-xs text-muted-foreground mb-1">
                  Prop Firm Account <span className="text-zinc-500">(optional)</span>
                </Label>
                <select
                  value={propFirmId ?? ""}
                  onChange={(e) => setPropFirmId(e.target.value ? Number(e.target.value) : null)}
                  className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm"
                >
                  <option value="">No prop firm</option>
                  {propFirmAccounts
                    .filter((a) => a.status === "active")
                    .map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.firm_name} — {a.account_name}
                      </option>
                    ))}
                </select>
              </div>
            )}

            {/* Agent-Specific Settings */}
            <div className={`rounded-lg border p-3 space-y-3 ${
              agentType === "scalping"
                ? "border-amber-500/20 bg-amber-500/5"
                : "border-emerald-500/20 bg-emerald-500/5"
            }`}>
              <Label className={`block text-xs font-semibold ${
                agentType === "scalping" ? "text-amber-400" : "text-emerald-400"
              }`}>
                {agentType === "scalping" ? "Scalping" : "Expert"} Agent Settings
              </Label>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="block text-[10px] text-muted-foreground mb-1">Min Confidence</Label>
                  <input
                    type="number" step="0.05" min="0.3" max="0.95" value={minConfidence}
                    onChange={(e) => setMinConfidence(e.target.value)}
                    className="w-full rounded-lg border border-card-border bg-background px-3 py-1.5 text-sm"
                  />
                </div>
                <div className="flex flex-col items-center gap-1.5 rounded-lg border border-card-border p-2">
                  <Label className="text-[10px] text-muted-foreground">Session Filter</Label>
                  <ToggleSwitch checked={sessionFilter} onChange={setSessionFilter} color={agentType === "scalping" ? "amber" : "emerald"} />
                </div>
              </div>

              {agentType === "expert" && (
                <>
                  <div className="grid grid-cols-3 gap-2">
                    <div className="flex flex-col items-center gap-1.5 rounded-lg border border-card-border p-2">
                      <Label className="text-[10px] text-muted-foreground">News Filter</Label>
                      <ToggleSwitch checked={newsFilter} onChange={setNewsFilter} color="emerald" />
                    </div>
                    <div className="flex flex-col items-center gap-1.5 rounded-lg border border-card-border p-2">
                      <Label className="text-[10px] text-muted-foreground">Regime Filter</Label>
                      <ToggleSwitch checked={regimeFilter} onChange={setRegimeFilter} color="emerald" />
                    </div>
                    <div>
                      <Label className="block text-[10px] text-muted-foreground mb-1">Min Agreement</Label>
                      <select
                        value={minAgreement}
                        onChange={(e) => setMinAgreement(e.target.value)}
                        className="w-full rounded-lg border border-card-border bg-background px-3 py-1.5 text-sm"
                      >
                        <option value="2">2 of 3</option>
                        <option value="3">3 of 3 (strict)</option>
                      </select>
                    </div>
                  </div>
                </>
              )}

              <div className={`text-[10px] flex items-center gap-1.5 ${
                agentType === "scalping" ? "text-amber-400/70" : "text-emerald-400/70"
              }`}>
                <span className={`inline-block h-1.5 w-1.5 rounded-full ${
                  agentType === "scalping" ? "bg-amber-400" : "bg-emerald-400"
                }`} />
                {agentType === "scalping"
                  ? `Timeframe: ${timeframe} · Ensemble: XGBoost + LightGBM`
                  : `Timeframe: ${timeframe} · Ensemble: XGBoost + LightGBM + LSTM`}
              </div>
            </div>
          </div>
        )}

        {/* ═══ STEP 3: Review & Deploy ═══ */}
        {step === 3 && (
          <div className="space-y-4">
            <div>
              <Label className="text-xs text-muted-foreground mb-1.5">Agent Name</Label>
              <input
                value={agentName}
                onChange={(e) => setAgentName(e.target.value)}
                className="w-full rounded-lg border border-card-border bg-background px-3 py-2.5 text-sm outline-none focus:border-accent"
                placeholder="e.g. XAUUSD Scalping Agent"
              />
            </div>

            {/* Mode Selection */}
            <div>
              <Label className="text-xs text-muted-foreground mb-1.5">Trading Mode</Label>
              <div className="flex gap-2">
                {(["paper", "confirmation", "auto"] as const).map((m) => (
                  <button
                    key={m}
                    onClick={() => setMode(m)}
                    className={`flex-1 rounded-lg py-2.5 text-sm font-medium transition-colors ${
                      mode === m
                        ? m === "paper" ? "bg-blue-500/20 text-fa-accent border border-blue-500/40"
                          : m === "confirmation" ? "bg-purple-500/20 text-purple-400 border border-purple-500/40"
                            : "bg-orange-500/20 text-orange-400 border border-orange-500/40"
                        : "border border-card-border text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {m === "paper" ? "Paper" : m === "confirmation" ? "Confirm" : "Auto"}
                  </button>
                ))}
              </div>
              <p className="text-[10px] text-muted-foreground mt-1">
                {mode === "paper"
                  ? "Simulates trades without connecting to broker. Tracks virtual P&L."
                  : mode === "confirmation"
                    ? "Shows trade signals — requires your approval before execution."
                    : "Fully autonomous — executes trades directly on broker."}
              </p>
              {mode === "auto" && (
                <div className="mt-2 rounded-lg bg-orange-500/10 border border-orange-500/30 px-3 py-2 text-xs text-orange-400 flex items-center gap-2">
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                  Auto mode will place real trades. Ensure risk settings are correct.
                </div>
              )}
            </div>

            {/* Broker */}
            {brokerAccounts.length > 0 && (
              <div>
                <Label className="text-xs text-muted-foreground mb-1.5">Broker Account</Label>
                <div className="flex gap-2 flex-wrap">
                  {brokerAccounts.map((acct) => (
                    <button
                      key={acct.broker}
                      onClick={() => setBroker(acct.broker)}
                      className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                        broker === acct.broker
                          ? "border-accent/60 bg-accent/10 text-accent"
                          : "border-card-border text-muted-foreground hover:border-accent/40"
                      }`}
                    >
                      <div className="h-1.5 w-1.5 rounded-full bg-green-400" />
                      <span className="capitalize">{acct.broker}</span>
                      <span className="text-muted-foreground/70">
                        {acct.currency} {acct.balance >= 1000
                          ? `${(acct.balance / 1000).toFixed(1)}k`
                          : acct.balance.toFixed(0)}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Summary */}
            <div className="rounded-lg border border-card-border bg-background/50 p-3">
              <Label className="block text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider">Summary</Label>
              <div className="grid grid-cols-2 gap-y-1.5 text-xs">
                <span className="text-muted-foreground">Symbol</span>
                <span className="font-medium text-foreground">{symbol}</span>
                <span className="text-muted-foreground">Agent Type</span>
                <span className="font-medium text-foreground flex items-center gap-1">
                  {agentType === "scalping" ? (
                    <><Zap className="h-3 w-3 text-amber-400" /> Scalping</>
                  ) : (
                    <><Brain className="h-3 w-3 text-emerald-400" /> Expert</>
                  )}
                </span>
                <span className="text-muted-foreground">Timeframe</span>
                <span className="font-medium text-foreground">{timeframe}</span>
                <span className="text-muted-foreground">Risk / Trade</span>
                <span className="font-medium text-foreground">
                  {sizeType === "percent_risk" ? `${riskPerTrade}%` : `${riskPerTrade} lots`}
                </span>
                <span className="text-muted-foreground">Max Daily Loss</span>
                <span className="font-medium text-foreground">{maxDailyLoss}%</span>
                <span className="text-muted-foreground">Max Drawdown</span>
                <span className="font-medium text-foreground">{maxDrawdown}%</span>
                <span className="text-muted-foreground">Mode</span>
                <span className="font-medium text-foreground capitalize">{mode === "auto" ? "Autonomous" : mode}</span>
              </div>
            </div>
          </div>
        )}

        {/* ═══ Navigation Buttons ═══ */}
        <div className="flex items-center justify-between pt-2 border-t border-card-border mt-2">
          <div>
            {step > 0 && (
              <Button variant="outline" size="sm" onClick={() => setStep(step - 1)} className="gap-1">
                <ChevronLeft className="h-3.5 w-3.5" /> Back
              </Button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            {step < 3 ? (
              <Button
                size="sm"
                onClick={() => setStep(step + 1)}
                disabled={!canProceedStep()}
                className="gap-1"
              >
                Next <ChevronRight className="h-3.5 w-3.5" />
              </Button>
            ) : (
              <Button
                size="sm"
                onClick={handleDeploy}
                disabled={creating || !agentName}
                className="gap-1.5 bg-accent hover:bg-accent/90 text-black"
              >
                {creating ? "Deploying..." : <><Rocket className="h-3.5 w-3.5" /> Deploy Agent</>}
              </Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/* ── Toggle Switch Sub-Component ── */
function ToggleSwitch({ checked, onChange, color = "accent" }: { checked: boolean; onChange: (v: boolean) => void; color?: string }) {
  const colorOn = color === "amber" ? "bg-amber-600" : color === "emerald" ? "bg-emerald-600" : "bg-accent";
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-4 w-8 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
        checked ? colorOn : "bg-zinc-600"
      }`}
    >
      <span
        className={`pointer-events-none inline-block h-3 w-3 transform rounded-full bg-white shadow-sm transition-transform ${
          checked ? "translate-x-4" : "translate-x-0"
        }`}
      />
    </button>
  );
}
