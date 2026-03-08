"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import {
  Building2,
  Plus,
  TrendingUp,
  TrendingDown,
  Trophy,
  AlertTriangle,
  XCircle,
  Pause,
  Play,
  RotateCcw,
  ChevronLeft,
  Loader2,
  DollarSign,
  BarChart3,
  Target,
  Shield,
  Calendar,
  Percent,
  Activity,
  ArrowUpRight,
  ArrowDownRight,
  X,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// ── Types ──

interface AccountSummary {
  id: number;
  account_name: string;
  firm_name: string;
  phase: string;
  status: string;
  account_size: number;
  current_balance: number;
  total_pnl: number;
  today_pnl: number;
  max_drawdown_pct: number;
  profit_target_progress_pct: number;
  total_trades: number;
  trading_days: number;
  win_rate: number;
}

interface AccountDetail {
  id: number;
  account_name: string;
  firm_name: string;
  account_size: number;
  currency: string;
  phase: string;
  status: string;
  breach_reason: string | null;
  max_daily_loss_pct: number;
  max_total_loss_pct: number;
  profit_target_pct: number;
  min_trading_days: number;
  max_trading_days: number | null;
  no_news_trading: boolean;
  no_weekend_holding: boolean;
  max_lots_per_trade: number | null;
  max_open_positions: number | null;
  allowed_symbols: string[];
  restricted_hours: Record<string, unknown>;
  assigned_strategies: Record<string, unknown>[];
  current_balance: number;
  current_equity: number;
  total_pnl: number;
  today_pnl: number;
  max_drawdown_pct: number;
  peak_balance: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  trading_days: number;
  profit_target_reached: boolean;
  daily_loss_breached: boolean;
  total_loss_breached: boolean;
  profit_target_progress_pct: number;
  daily_loss_remaining_pct: number;
  total_loss_remaining_pct: number;
  win_rate: number;
  days_remaining: number | null;
  notes: string | null;
  broker_account_id: string | null;
  broker_name: string | null;
  created_at: string | null;
  updated_at: string | null;
}

interface Trade {
  id: number;
  account_id: number;
  symbol: string;
  direction: string;
  entry_price: number;
  exit_price: number | null;
  lot_size: number;
  stop_loss: number | null;
  take_profit: number | null;
  pnl: number;
  pnl_pct: number;
  commission: number;
  status: string;
  close_reason: string | null;
  strategy_id: number | null;
  balance_before: number | null;
  balance_after: number | null;
  opened_at: string | null;
  closed_at: string | null;
}

interface Dashboard {
  total_accounts: number;
  active_accounts: number;
  passed_accounts: number;
  breached_accounts: number;
  total_pnl: number;
  total_trades: number;
  accounts: AccountSummary[];
}

interface FirmPreset {
  firm_name: string;
  phase: string;
  max_daily_loss_pct: number;
  max_total_loss_pct: number;
  profit_target_pct: number;
  min_trading_days: number;
  max_trading_days: number | null;
  no_news_trading: boolean;
  no_weekend_holding: boolean;
}

interface EquityCurve {
  account_id: number;
  account_name: string;
  account_size: number;
  profit_target: number;
  loss_limit: number;
  history: { date: string; balance: number; equity: number; pnl: number; trade_id: number }[];
}

// ── Helpers ──

const fmt = (n: number) =>
  n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const pnlColor = (v: number) =>
  v > 0 ? "text-emerald-400" : v < 0 ? "text-red-400" : "text-muted-foreground";

const pnlBg = (v: number) =>
  v > 0 ? "bg-emerald-500/10" : v < 0 ? "bg-red-500/10" : "bg-muted/10";

const statusConfig: Record<string, { color: string; bg: string; icon: React.ElementType }> = {
  active: { color: "text-emerald-400", bg: "bg-emerald-500/15", icon: Activity },
  paused: { color: "text-yellow-400", bg: "bg-yellow-500/15", icon: Pause },
  breached: { color: "text-red-400", bg: "bg-red-500/15", icon: XCircle },
  passed: { color: "text-cyan-400", bg: "bg-cyan-500/15", icon: Trophy },
};

const phaseLabels: Record<string, string> = {
  challenge: "Challenge",
  verification: "Verification",
  funded: "Funded",
};

// ── Main Page ──

export default function PropFirmsPage() {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Detail view
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<AccountDetail | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [equityCurve, setEquityCurve] = useState<EquityCurve | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Create modal
  const [showCreate, setShowCreate] = useState(false);
  const [presets, setPresets] = useState<Record<string, FirmPreset>>({});
  const [creating, setCreating] = useState(false);

  // Create form state
  const [formName, setFormName] = useState("");
  const [formPreset, setFormPreset] = useState("");
  const [formSize, setFormSize] = useState("100000");
  const [formFirm, setFormFirm] = useState("");
  const [formPhase, setFormPhase] = useState("challenge");
  const [formDailyLoss, setFormDailyLoss] = useState("5");
  const [formTotalLoss, setFormTotalLoss] = useState("10");
  const [formProfitTarget, setFormProfitTarget] = useState("8");
  const [formMinDays, setFormMinDays] = useState("5");
  const [formMaxDays, setFormMaxDays] = useState("");

  // Delete confirm
  const [deleteId, setDeleteId] = useState<number | null>(null);

  const fetchDashboard = useCallback(async () => {
    try {
      setError(null);
      const data = await api.get<Dashboard>("/api/prop-firms/dashboard");
      setDashboard(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchPresets = useCallback(async () => {
    try {
      const data = await api.get<Record<string, FirmPreset>>("/api/prop-firms/presets");
      setPresets(data);
    } catch {
      // Presets are optional enhancement
    }
  }, []);

  useEffect(() => {
    fetchDashboard();
    fetchPresets();
  }, [fetchDashboard, fetchPresets]);

  const openDetail = useCallback(async (id: number) => {
    setSelectedId(id);
    setDetailLoading(true);
    try {
      const [acct, tradeList, curve] = await Promise.all([
        api.get<AccountDetail>(`/api/prop-firms/${id}`),
        api.get<Trade[] | { items: Trade[] }>(`/api/prop-firms/${id}/trades`).then(r => Array.isArray(r) ? r : (r as { items: Trade[] }).items || []),
        api.get<EquityCurve>(`/api/prop-firms/${id}/equity-curve`),
      ]);
      setDetail(acct);
      setTrades(tradeList);
      setEquityCurve(curve);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load account";
      toast.error(msg);
      setSelectedId(null);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const closeDetail = useCallback(() => {
    setSelectedId(null);
    setDetail(null);
    setTrades([]);
    setEquityCurve(null);
  }, []);

  // Apply preset to form
  const applyPreset = useCallback(
    (key: string) => {
      setFormPreset(key);
      const p = presets[key];
      if (!p) return;
      setFormFirm(p.firm_name);
      setFormPhase(p.phase);
      setFormDailyLoss(String(p.max_daily_loss_pct));
      setFormTotalLoss(String(p.max_total_loss_pct));
      setFormProfitTarget(String(p.profit_target_pct));
      setFormMinDays(String(p.min_trading_days));
      setFormMaxDays(p.max_trading_days ? String(p.max_trading_days) : "");
    },
    [presets]
  );

  const handleCreate = useCallback(async () => {
    if (!formName.trim() || !formFirm.trim()) {
      toast.error("Account name and firm name are required");
      return;
    }
    setCreating(true);
    try {
      await api.post("/api/prop-firms/", {
        account_name: formName.trim(),
        firm_name: formFirm.trim(),
        account_size: parseFloat(formSize) || 100000,
        phase: formPhase,
        max_daily_loss_pct: parseFloat(formDailyLoss) || 5,
        max_total_loss_pct: parseFloat(formTotalLoss) || 10,
        profit_target_pct: parseFloat(formProfitTarget) || 8,
        min_trading_days: parseInt(formMinDays) || 5,
        max_trading_days: formMaxDays ? parseInt(formMaxDays) : null,
      });
      toast.success(`Account "${formName}" created`);
      setShowCreate(false);
      resetForm();
      fetchDashboard();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to create account";
      toast.error(msg);
    } finally {
      setCreating(false);
    }
  }, [formName, formFirm, formSize, formPhase, formDailyLoss, formTotalLoss, formProfitTarget, formMinDays, formMaxDays, fetchDashboard]);

  const resetForm = () => {
    setFormName("");
    setFormPreset("");
    setFormSize("100000");
    setFormFirm("");
    setFormPhase("challenge");
    setFormDailyLoss("5");
    setFormTotalLoss("10");
    setFormProfitTarget("8");
    setFormMinDays("5");
    setFormMaxDays("");
  };

  const handleAction = useCallback(
    async (action: "pause" | "resume" | "reset", id: number, name: string) => {
      try {
        await api.post(`/api/prop-firms/${id}/${action}`);
        toast.success(`Account "${name}" ${action === "pause" ? "paused" : action === "resume" ? "resumed" : "reset"}`);
        fetchDashboard();
        if (selectedId === id) openDetail(id);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : `Failed to ${action}`;
        toast.error(msg);
      }
    },
    [fetchDashboard, selectedId, openDetail]
  );

  const handleDelete = useCallback(
    async (id: number) => {
      try {
        await api.delete(`/api/prop-firms/${id}`);
        toast.success("Account deleted");
        setDeleteId(null);
        if (selectedId === id) closeDetail();
        fetchDashboard();
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Failed to delete";
        toast.error(msg);
      }
    },
    [fetchDashboard, selectedId, closeDetail]
  );

  // ── Render: Loading ──
  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-accent" />
      </div>
    );
  }

  // ── Render: Error ──
  if (error) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <Card className="max-w-md bg-red-500/5 border-red-500/20">
          <CardContent className="p-6 text-center">
            <AlertTriangle className="h-10 w-10 text-red-400 mx-auto mb-3" />
            <p className="text-red-400 font-medium mb-2">Failed to load prop firm data</p>
            <p className="text-sm text-muted-foreground mb-4">{error}</p>
            <Button onClick={() => { setLoading(true); fetchDashboard(); }} variant="outline" size="sm">
              Retry
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ── Render: Detail View ──
  if (selectedId && detail) {
    return (
      <DetailView
        detail={detail}
        trades={trades}
        equityCurve={equityCurve}
        onBack={closeDetail}
        onAction={handleAction}
        onDelete={(id) => setDeleteId(id)}
        loading={detailLoading}
      />
    );
  }

  const accounts = dashboard?.accounts ?? [];

  // ── Render: Main List ──
  return (
    <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-foreground flex items-center gap-2">
            <Building2 className="h-5 w-5 text-accent" />
            Prop Firm Accounts
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Track and manage your prop firm challenges, verifications, and funded accounts
          </p>
        </div>
        <Button onClick={() => setShowCreate(true)} size="sm" className="bg-accent hover:bg-accent/80 text-white">
          <Plus className="h-4 w-4 mr-1" />
          New Account
        </Button>
      </div>

      {/* Dashboard Stats */}
      {dashboard && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard label="Active" value={dashboard.active_accounts} icon={Activity} color="text-emerald-400" />
          <StatCard label="Passed" value={dashboard.passed_accounts} icon={Trophy} color="text-cyan-400" />
          <StatCard label="Breached" value={dashboard.breached_accounts} icon={XCircle} color="text-red-400" />
          <StatCard
            label="Total P&L"
            value={`$${fmt(dashboard.total_pnl)}`}
            icon={DollarSign}
            color={dashboard.total_pnl >= 0 ? "text-emerald-400" : "text-red-400"}
          />
        </div>
      )}

      {/* Account Cards */}
      {accounts.length === 0 ? (
        <Card className="bg-card-bg border-card-border">
          <CardContent className="p-12 text-center">
            <Building2 className="h-12 w-12 text-muted-foreground/30 mx-auto mb-4" />
            <p className="text-muted-foreground font-medium mb-2">No prop firm accounts yet</p>
            <p className="text-sm text-muted-foreground/70 mb-4">
              Create your first account to start tracking your prop firm challenges
            </p>
            <Button onClick={() => setShowCreate(true)} size="sm" variant="outline">
              <Plus className="h-4 w-4 mr-1" />
              Create Account
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {accounts.map((a) => (
            <AccountCard
              key={a.id}
              account={a}
              onClick={() => openDetail(a.id)}
              onAction={handleAction}
              onDelete={(id) => setDeleteId(id)}
            />
          ))}
        </div>
      )}

      {/* Create Modal */}
      {showCreate && (
        <CreateModal
          presets={presets}
          formName={formName}
          setFormName={setFormName}
          formPreset={formPreset}
          applyPreset={applyPreset}
          formSize={formSize}
          setFormSize={setFormSize}
          formFirm={formFirm}
          setFormFirm={setFormFirm}
          formPhase={formPhase}
          setFormPhase={setFormPhase}
          formDailyLoss={formDailyLoss}
          setFormDailyLoss={setFormDailyLoss}
          formTotalLoss={formTotalLoss}
          setFormTotalLoss={setFormTotalLoss}
          formProfitTarget={formProfitTarget}
          setFormProfitTarget={setFormProfitTarget}
          formMinDays={formMinDays}
          setFormMinDays={setFormMinDays}
          formMaxDays={formMaxDays}
          setFormMaxDays={setFormMaxDays}
          creating={creating}
          onCreate={handleCreate}
          onClose={() => { setShowCreate(false); resetForm(); }}
        />
      )}

      {/* Delete Confirm Modal */}
      {deleteId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-2xl border border-card-border bg-card-bg p-6 shadow-2xl">
            <div className="flex items-center gap-3 mb-4">
              <div className="h-10 w-10 rounded-full bg-red-500/10 flex items-center justify-center">
                <Trash2 className="h-5 w-5 text-red-400" />
              </div>
              <div>
                <h3 className="font-semibold text-foreground">Delete Account</h3>
                <p className="text-sm text-muted-foreground">This action cannot be undone</p>
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => setDeleteId(null)}>
                Cancel
              </Button>
              <Button
                size="sm"
                className="bg-red-600 hover:bg-red-700 text-white"
                onClick={() => handleDelete(deleteId)}
              >
                Delete
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Stat Card ──

function StatCard({
  label,
  value,
  icon: Icon,
  color,
}: {
  label: string;
  value: string | number;
  icon: React.ElementType;
  color: string;
}) {
  return (
    <Card className="bg-card-bg border-card-border">
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground uppercase tracking-wide">{label}</span>
          <Icon className={`h-4 w-4 ${color}`} />
        </div>
        <p className={`text-xl font-bold mt-1 ${color}`}>{value}</p>
      </CardContent>
    </Card>
  );
}

// ── Account Card ──

function AccountCard({
  account: a,
  onClick,
  onAction,
  onDelete,
}: {
  account: AccountSummary;
  onClick: () => void;
  onAction: (action: "pause" | "resume" | "reset", id: number, name: string) => void;
  onDelete: (id: number) => void;
}) {
  const sc = statusConfig[a.status] || statusConfig.active;
  const StatusIcon = sc.icon;
  const pnlPct = a.account_size > 0 ? (a.total_pnl / a.account_size) * 100 : 0;

  return (
    <Card
      className="bg-card-bg border-card-border hover:border-accent/30 transition-colors cursor-pointer group"
      onClick={onClick}
    >
      <CardContent className="p-4 space-y-3">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0">
            <h3 className="font-semibold text-foreground truncate group-hover:text-accent transition-colors">
              {a.account_name}
            </h3>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-xs text-muted-foreground">{a.firm_name}</span>
              <Badge variant="outline" className="text-[10px] border-accent/30 text-accent">
                {phaseLabels[a.phase] || a.phase}
              </Badge>
            </div>
          </div>
          <Badge className={`${sc.bg} ${sc.color} border-0 text-[10px] flex items-center gap-1`}>
            <StatusIcon className="h-3 w-3" />
            {a.status.charAt(0).toUpperCase() + a.status.slice(1)}
          </Badge>
        </div>

        {/* Balance & PnL */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <span className="text-[10px] text-muted-foreground uppercase">Balance</span>
            <p className="text-sm font-semibold text-foreground">${fmt(a.current_balance)}</p>
          </div>
          <div>
            <span className="text-[10px] text-muted-foreground uppercase">P&L</span>
            <p className={`text-sm font-semibold ${pnlColor(a.total_pnl)}`}>
              {a.total_pnl >= 0 ? "+" : ""}${fmt(a.total_pnl)}
              <span className="text-[10px] ml-1">({pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(1)}%)</span>
            </p>
          </div>
        </div>

        {/* Progress Bar */}
        {a.status !== "funded" && (
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] text-muted-foreground">Profit Target</span>
              <span className="text-[10px] text-accent font-medium">{a.profit_target_progress_pct.toFixed(1)}%</span>
            </div>
            <div className="h-1.5 rounded-full bg-muted/20 overflow-hidden">
              <div
                className="h-full rounded-full bg-accent transition-all duration-500"
                style={{ width: `${Math.min(a.profit_target_progress_pct, 100)}%` }}
              />
            </div>
          </div>
        )}

        {/* Stats Row */}
        <div className="grid grid-cols-4 gap-1 pt-1 border-t border-card-border">
          <MiniStat label="Trades" value={a.total_trades} />
          <MiniStat label="Win Rate" value={`${a.win_rate.toFixed(0)}%`} />
          <MiniStat label="Max DD" value={`${a.max_drawdown_pct.toFixed(1)}%`} warn={a.max_drawdown_pct > 8} />
          <MiniStat label="Days" value={a.trading_days} />
        </div>

        {/* Quick Actions */}
        <div className="flex items-center gap-1 pt-1" onClick={(e) => e.stopPropagation()}>
          {a.status === "active" && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-[11px] text-yellow-400 hover:text-yellow-300 hover:bg-yellow-500/10"
              onClick={() => onAction("pause", a.id, a.account_name)}
            >
              <Pause className="h-3 w-3 mr-1" />
              Pause
            </Button>
          )}
          {a.status === "paused" && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-[11px] text-emerald-400 hover:text-emerald-300 hover:bg-emerald-500/10"
              onClick={() => onAction("resume", a.id, a.account_name)}
            >
              <Play className="h-3 w-3 mr-1" />
              Resume
            </Button>
          )}
          {(a.status === "breached" || a.status === "passed") && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-[11px] text-cyan-400 hover:text-cyan-300 hover:bg-cyan-500/10"
              onClick={() => onAction("reset", a.id, a.account_name)}
            >
              <RotateCcw className="h-3 w-3 mr-1" />
              Reset
            </Button>
          )}
          <div className="flex-1" />
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-[11px] text-red-400 hover:text-red-300 hover:bg-red-500/10"
            onClick={() => onDelete(a.id)}
          >
            <Trash2 className="h-3 w-3" />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function MiniStat({ label, value, warn }: { label: string; value: string | number; warn?: boolean }) {
  return (
    <div className="text-center">
      <p className={`text-xs font-medium ${warn ? "text-orange-400" : "text-foreground"}`}>{value}</p>
      <p className="text-[9px] text-muted-foreground">{label}</p>
    </div>
  );
}

// ── Detail View ──

function DetailView({
  detail: d,
  trades,
  equityCurve,
  onBack,
  onAction,
  onDelete,
  loading,
}: {
  detail: AccountDetail;
  trades: Trade[];
  equityCurve: EquityCurve | null;
  onBack: () => void;
  onAction: (action: "pause" | "resume" | "reset", id: number, name: string) => void;
  onDelete: (id: number) => void;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-accent" />
      </div>
    );
  }

  const sc = statusConfig[d.status] || statusConfig.active;
  const StatusIcon = sc.icon;
  const pnlPct = d.account_size > 0 ? (d.total_pnl / d.account_size) * 100 : 0;
  const targetAmount = d.account_size * (d.profit_target_pct / 100);
  const dailyLossLimit = d.account_size * (d.max_daily_loss_pct / 100);
  const totalLossLimit = d.account_size * (d.max_total_loss_pct / 100);

  return (
    <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6">
      {/* Back + Header */}
      <div>
        <button
          onClick={onBack}
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground mb-3 transition-colors"
        >
          <ChevronLeft className="h-4 w-4" />
          Back to accounts
        </button>
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-xl font-bold text-foreground flex items-center gap-2">
              {d.account_name}
              <Badge className={`${sc.bg} ${sc.color} border-0 text-xs flex items-center gap-1`}>
                <StatusIcon className="h-3 w-3" />
                {d.status.charAt(0).toUpperCase() + d.status.slice(1)}
              </Badge>
            </h1>
            <div className="flex items-center gap-3 mt-1 text-sm text-muted-foreground">
              <span>{d.firm_name}</span>
              <span className="text-accent">{phaseLabels[d.phase] || d.phase}</span>
              <span>${fmt(d.account_size)} {d.currency}</span>
              {d.created_at && (
                <span>Created {new Date(d.created_at).toLocaleDateString()}</span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {d.status === "active" && (
              <Button
                variant="outline"
                size="sm"
                className="text-yellow-400 border-yellow-400/30 hover:bg-yellow-500/10"
                onClick={() => onAction("pause", d.id, d.account_name)}
              >
                <Pause className="h-4 w-4 mr-1" />
                Pause
              </Button>
            )}
            {d.status === "paused" && (
              <Button
                variant="outline"
                size="sm"
                className="text-emerald-400 border-emerald-400/30 hover:bg-emerald-500/10"
                onClick={() => onAction("resume", d.id, d.account_name)}
              >
                <Play className="h-4 w-4 mr-1" />
                Resume
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              className="text-cyan-400 border-cyan-400/30 hover:bg-cyan-500/10"
              onClick={() => onAction("reset", d.id, d.account_name)}
            >
              <RotateCcw className="h-4 w-4 mr-1" />
              Reset
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="text-red-400 border-red-400/30 hover:bg-red-500/10"
              onClick={() => onDelete(d.id)}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Breach Warning */}
        {d.status === "breached" && d.breach_reason && (
          <div className="mt-3 p-3 rounded-lg bg-red-500/10 border border-red-500/30">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-red-400 shrink-0" />
              <p className="text-sm text-red-400 font-medium">Account Breached</p>
            </div>
            <p className="text-sm text-red-300/80 mt-1 ml-6">{d.breach_reason}</p>
          </div>
        )}
      </div>

      {/* Key Metrics Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard
          icon={DollarSign}
          label="Current Balance"
          value={`$${fmt(d.current_balance)}`}
          color="text-foreground"
        />
        <MetricCard
          icon={d.total_pnl >= 0 ? TrendingUp : TrendingDown}
          label="Total P&L"
          value={`${d.total_pnl >= 0 ? "+" : ""}$${fmt(d.total_pnl)} (${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(2)}%)`}
          color={pnlColor(d.total_pnl)}
        />
        <MetricCard
          icon={d.today_pnl >= 0 ? ArrowUpRight : ArrowDownRight}
          label="Today P&L"
          value={`${d.today_pnl >= 0 ? "+" : ""}$${fmt(d.today_pnl)}`}
          color={pnlColor(d.today_pnl)}
        />
        <MetricCard
          icon={Shield}
          label="Max Drawdown"
          value={`${d.max_drawdown_pct.toFixed(2)}%`}
          color={d.max_drawdown_pct > 8 ? "text-orange-400" : "text-foreground"}
        />
      </div>

      {/* Progress Bars */}
      <div className="grid md:grid-cols-3 gap-3">
        {/* Profit Target */}
        <Card className="bg-card-bg border-card-border">
          <CardContent className="p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-muted-foreground flex items-center gap-1">
                <Target className="h-3 w-3" />
                Profit Target ({d.profit_target_pct}%)
              </span>
              <span className="text-xs text-accent font-medium">
                ${fmt(d.current_balance - d.account_size)} / ${fmt(targetAmount)}
              </span>
            </div>
            <div className="h-2 rounded-full bg-muted/20 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  d.profit_target_reached ? "bg-emerald-500" : "bg-accent"
                }`}
                style={{ width: `${Math.min(d.profit_target_progress_pct, 100)}%` }}
              />
            </div>
            <p className="text-[10px] text-muted-foreground mt-1">
              {d.profit_target_progress_pct.toFixed(1)}% complete
              {d.profit_target_reached && " - Target Reached!"}
            </p>
          </CardContent>
        </Card>

        {/* Daily Loss */}
        <Card className="bg-card-bg border-card-border">
          <CardContent className="p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-muted-foreground flex items-center gap-1">
                <Percent className="h-3 w-3" />
                Daily Loss Remaining
              </span>
              <span className={`text-xs font-medium ${d.daily_loss_remaining_pct < 2 ? "text-red-400" : "text-emerald-400"}`}>
                {d.daily_loss_remaining_pct.toFixed(2)}%
              </span>
            </div>
            <div className="h-2 rounded-full bg-muted/20 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  d.daily_loss_remaining_pct < 2 ? "bg-red-500" : d.daily_loss_remaining_pct < 3 ? "bg-orange-500" : "bg-emerald-500"
                }`}
                style={{ width: `${Math.min((d.daily_loss_remaining_pct / d.max_daily_loss_pct) * 100, 100)}%` }}
              />
            </div>
            <p className="text-[10px] text-muted-foreground mt-1">
              ${fmt(d.daily_loss_remaining_pct / 100 * d.account_size)} of ${fmt(dailyLossLimit)} remaining today
            </p>
          </CardContent>
        </Card>

        {/* Total Loss */}
        <Card className="bg-card-bg border-card-border">
          <CardContent className="p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-muted-foreground flex items-center gap-1">
                <Shield className="h-3 w-3" />
                Total Loss Remaining
              </span>
              <span className={`text-xs font-medium ${d.total_loss_remaining_pct < 3 ? "text-red-400" : "text-emerald-400"}`}>
                {d.total_loss_remaining_pct.toFixed(2)}%
              </span>
            </div>
            <div className="h-2 rounded-full bg-muted/20 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  d.total_loss_remaining_pct < 3 ? "bg-red-500" : d.total_loss_remaining_pct < 5 ? "bg-orange-500" : "bg-emerald-500"
                }`}
                style={{ width: `${Math.min((d.total_loss_remaining_pct / d.max_total_loss_pct) * 100, 100)}%` }}
              />
            </div>
            <p className="text-[10px] text-muted-foreground mt-1">
              ${fmt(d.total_loss_remaining_pct / 100 * d.account_size)} of ${fmt(totalLossLimit)} remaining
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Stats + Rules Row */}
      <div className="grid md:grid-cols-2 gap-3">
        {/* Trading Stats */}
        <Card className="bg-card-bg border-card-border">
          <CardContent className="p-4">
            <h3 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
              <BarChart3 className="h-4 w-4 text-accent" />
              Trading Statistics
            </h3>
            <div className="grid grid-cols-2 gap-y-2.5">
              <StatRow label="Total Trades" value={d.total_trades} />
              <StatRow label="Win Rate" value={`${d.win_rate.toFixed(1)}%`} color={d.win_rate > 50 ? "text-emerald-400" : undefined} />
              <StatRow label="Winning" value={d.winning_trades} color="text-emerald-400" />
              <StatRow label="Losing" value={d.losing_trades} color="text-red-400" />
              <StatRow label="Trading Days" value={d.trading_days} />
              <StatRow label="Days Remaining" value={d.days_remaining ?? "Unlimited"} />
              <StatRow label="Peak Balance" value={`$${fmt(d.peak_balance)}`} />
              <StatRow label="Current Equity" value={`$${fmt(d.current_equity)}`} />
            </div>
          </CardContent>
        </Card>

        {/* Account Rules */}
        <Card className="bg-card-bg border-card-border">
          <CardContent className="p-4">
            <h3 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
              <Shield className="h-4 w-4 text-accent" />
              Account Rules
            </h3>
            <div className="grid grid-cols-2 gap-y-2.5">
              <StatRow label="Daily Loss Limit" value={`${d.max_daily_loss_pct}%`} />
              <StatRow label="Total Loss Limit" value={`${d.max_total_loss_pct}%`} />
              <StatRow label="Profit Target" value={d.profit_target_pct > 0 ? `${d.profit_target_pct}%` : "None"} />
              <StatRow label="Min Trading Days" value={d.min_trading_days} />
              <StatRow label="Max Trading Days" value={d.max_trading_days ?? "Unlimited"} />
              <StatRow label="No News Trading" value={d.no_news_trading ? "Yes" : "No"} />
              <StatRow label="No Weekend Hold" value={d.no_weekend_holding ? "Yes" : "No"} />
              <StatRow label="Max Lot Size" value={d.max_lots_per_trade ?? "No limit"} />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Equity Curve */}
      {equityCurve && equityCurve.history.length > 0 && (
        <Card className="bg-card-bg border-card-border">
          <CardContent className="p-4">
            <h3 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-accent" />
              Equity Curve
            </h3>
            <EquityChart curve={equityCurve} />
          </CardContent>
        </Card>
      )}

      {/* Trade History */}
      <Card className="bg-card-bg border-card-border">
        <CardContent className="p-4">
          <h3 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
            <Calendar className="h-4 w-4 text-accent" />
            Trade History
            <span className="text-[10px] text-muted-foreground ml-1">({trades.length} trades)</span>
          </h3>
          {trades.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-6">No trades recorded yet</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[10px] text-muted-foreground uppercase border-b border-card-border">
                    <th className="text-left py-2 pr-3">Symbol</th>
                    <th className="text-left py-2 pr-3">Direction</th>
                    <th className="text-right py-2 pr-3">Entry</th>
                    <th className="text-right py-2 pr-3">Exit</th>
                    <th className="text-right py-2 pr-3">Lots</th>
                    <th className="text-right py-2 pr-3">P&L</th>
                    <th className="text-left py-2 pr-3">Status</th>
                    <th className="text-left py-2">Date</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.map((t) => (
                    <tr key={t.id} className="border-b border-card-border/50 hover:bg-muted/5">
                      <td className="py-2 pr-3 font-medium text-foreground">{t.symbol}</td>
                      <td className="py-2 pr-3">
                        <Badge className={`border-0 text-[10px] ${
                          t.direction === "BUY"
                            ? "bg-emerald-500/15 text-emerald-400"
                            : "bg-red-500/15 text-red-400"
                        }`}>
                          {t.direction}
                        </Badge>
                      </td>
                      <td className="py-2 pr-3 text-right text-muted-foreground">{t.entry_price.toFixed(2)}</td>
                      <td className="py-2 pr-3 text-right text-muted-foreground">
                        {t.exit_price ? t.exit_price.toFixed(2) : "-"}
                      </td>
                      <td className="py-2 pr-3 text-right text-muted-foreground">{t.lot_size}</td>
                      <td className={`py-2 pr-3 text-right font-medium ${pnlColor(t.pnl)}`}>
                        {t.pnl >= 0 ? "+" : ""}${fmt(t.pnl)}
                      </td>
                      <td className="py-2 pr-3">
                        <Badge variant="outline" className="text-[10px]">
                          {t.status}
                        </Badge>
                      </td>
                      <td className="py-2 text-muted-foreground text-xs">
                        {t.opened_at ? new Date(t.opened_at).toLocaleDateString() : "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Notes */}
      {d.notes && (
        <Card className="bg-card-bg border-card-border">
          <CardContent className="p-4">
            <h3 className="text-sm font-semibold text-foreground mb-2">Notes</h3>
            <p className="text-sm text-muted-foreground whitespace-pre-wrap">{d.notes}</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function MetricCard({
  icon: Icon,
  label,
  value,
  color,
}: {
  icon: React.ElementType;
  label: string;
  value: string;
  color: string;
}) {
  return (
    <Card className="bg-card-bg border-card-border">
      <CardContent className="p-4">
        <div className="flex items-center gap-2 mb-1">
          <Icon className={`h-4 w-4 ${color}`} />
          <span className="text-[10px] text-muted-foreground uppercase tracking-wide">{label}</span>
        </div>
        <p className={`text-lg font-bold ${color}`}>{value}</p>
      </CardContent>
    </Card>
  );
}

function StatRow({
  label,
  value,
  color,
}: {
  label: string;
  value: string | number;
  color?: string;
}) {
  return (
    <div className="flex items-center justify-between pr-4">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className={`text-xs font-medium ${color || "text-foreground"}`}>{value}</span>
    </div>
  );
}

// ── Equity Chart (simple SVG) ──

function EquityChart({ curve }: { curve: EquityCurve }) {
  const history = curve.history;
  if (history.length < 2) {
    return <p className="text-sm text-muted-foreground text-center py-4">Not enough data for chart</p>;
  }

  const w = 800;
  const h = 200;
  const pad = { top: 20, right: 20, bottom: 30, left: 60 };
  const iw = w - pad.left - pad.right;
  const ih = h - pad.top - pad.bottom;

  const balances = history.map((p) => p.balance);
  const minB = Math.min(...balances, curve.loss_limit) * 0.998;
  const maxB = Math.max(...balances, curve.profit_target) * 1.002;
  const range = maxB - minB || 1;

  const toX = (i: number) => pad.left + (i / (history.length - 1)) * iw;
  const toY = (v: number) => pad.top + ih - ((v - minB) / range) * ih;

  const line = history.map((p, i) => `${i === 0 ? "M" : "L"}${toX(i).toFixed(1)},${toY(p.balance).toFixed(1)}`).join(" ");

  const targetY = toY(curve.profit_target);
  const limitY = toY(curve.loss_limit);
  const startY = toY(curve.account_size);

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full" preserveAspectRatio="xMidYMid meet">
      {/* Grid lines */}
      <line x1={pad.left} y1={pad.top} x2={pad.left} y2={h - pad.bottom} stroke="currentColor" strokeOpacity={0.1} />
      <line x1={pad.left} y1={h - pad.bottom} x2={w - pad.right} y2={h - pad.bottom} stroke="currentColor" strokeOpacity={0.1} />

      {/* Reference lines */}
      {curve.profit_target > 0 && (
        <>
          <line x1={pad.left} y1={targetY} x2={w - pad.right} y2={targetY} stroke="#22d3ee" strokeDasharray="4,4" strokeOpacity={0.5} />
          <text x={pad.left - 5} y={targetY + 4} textAnchor="end" className="fill-cyan-400 text-[10px]">
            Target
          </text>
        </>
      )}
      <line x1={pad.left} y1={limitY} x2={w - pad.right} y2={limitY} stroke="#ef4444" strokeDasharray="4,4" strokeOpacity={0.5} />
      <text x={pad.left - 5} y={limitY + 4} textAnchor="end" className="fill-red-400 text-[10px]">
        Limit
      </text>
      <line x1={pad.left} y1={startY} x2={w - pad.right} y2={startY} stroke="currentColor" strokeDasharray="2,4" strokeOpacity={0.2} />

      {/* Equity line */}
      <path d={line} fill="none" stroke="#a78bfa" strokeWidth={2} />

      {/* Current balance dot */}
      <circle cx={toX(history.length - 1)} cy={toY(history[history.length - 1].balance)} r={4} fill="#a78bfa" />

      {/* Labels */}
      <text x={pad.left - 5} y={startY + 4} textAnchor="end" className="fill-muted-foreground text-[10px]">
        ${(curve.account_size / 1000).toFixed(0)}k
      </text>
    </svg>
  );
}

// ── Create Modal ──

function CreateModal({
  presets,
  formName, setFormName,
  formPreset, applyPreset,
  formSize, setFormSize,
  formFirm, setFormFirm,
  formPhase, setFormPhase,
  formDailyLoss, setFormDailyLoss,
  formTotalLoss, setFormTotalLoss,
  formProfitTarget, setFormProfitTarget,
  formMinDays, setFormMinDays,
  formMaxDays, setFormMaxDays,
  creating,
  onCreate,
  onClose,
}: {
  presets: Record<string, FirmPreset>;
  formName: string; setFormName: (v: string) => void;
  formPreset: string; applyPreset: (k: string) => void;
  formSize: string; setFormSize: (v: string) => void;
  formFirm: string; setFormFirm: (v: string) => void;
  formPhase: string; setFormPhase: (v: string) => void;
  formDailyLoss: string; setFormDailyLoss: (v: string) => void;
  formTotalLoss: string; setFormTotalLoss: (v: string) => void;
  formProfitTarget: string; setFormProfitTarget: (v: string) => void;
  formMinDays: string; setFormMinDays: (v: string) => void;
  formMaxDays: string; setFormMaxDays: (v: string) => void;
  creating: boolean;
  onCreate: () => void;
  onClose: () => void;
}) {
  const presetLabels: Record<string, string> = {
    ftmo_challenge: "FTMO Challenge",
    ftmo_verification: "FTMO Verification",
    ftmo_funded: "FTMO Funded",
    funded_next_challenge: "Funded Next Challenge",
    funded_next_funded: "Funded Next Funded",
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-2xl border border-card-border bg-card-bg p-6 shadow-2xl max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-semibold text-foreground flex items-center gap-2">
            <Building2 className="h-5 w-5 text-accent" />
            New Prop Firm Account
          </h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-4">
          {/* Preset */}
          <div>
            <Label className="text-xs text-muted-foreground">Firm Preset</Label>
            <Select value={formPreset} onValueChange={applyPreset}>
              <SelectTrigger className="mt-1">
                <SelectValue placeholder="Select a preset (optional)" />
              </SelectTrigger>
              <SelectContent>
                {Object.keys(presets).map((k) => (
                  <SelectItem key={k} value={k}>
                    {presetLabels[k] || k}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Name + Size */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs text-muted-foreground">Account Name *</Label>
              <Input
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="e.g. FTMO 100k #1"
                className="mt-1"
              />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Account Size ($)</Label>
              <Input
                type="number"
                value={formSize}
                onChange={(e) => setFormSize(e.target.value)}
                placeholder="100000"
                className="mt-1"
              />
            </div>
          </div>

          {/* Firm + Phase */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs text-muted-foreground">Firm Name *</Label>
              <Input
                value={formFirm}
                onChange={(e) => setFormFirm(e.target.value)}
                placeholder="FTMO"
                className="mt-1"
              />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Phase</Label>
              <Select value={formPhase} onValueChange={setFormPhase}>
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="challenge">Challenge</SelectItem>
                  <SelectItem value="verification">Verification</SelectItem>
                  <SelectItem value="funded">Funded</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Rules */}
          <div className="pt-2 border-t border-card-border">
            <p className="text-xs text-muted-foreground mb-3 font-medium uppercase tracking-wide">Rules</p>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <Label className="text-[10px] text-muted-foreground">Daily Loss %</Label>
                <Input
                  type="number"
                  value={formDailyLoss}
                  onChange={(e) => setFormDailyLoss(e.target.value)}
                  className="mt-1"
                />
              </div>
              <div>
                <Label className="text-[10px] text-muted-foreground">Total Loss %</Label>
                <Input
                  type="number"
                  value={formTotalLoss}
                  onChange={(e) => setFormTotalLoss(e.target.value)}
                  className="mt-1"
                />
              </div>
              <div>
                <Label className="text-[10px] text-muted-foreground">Profit Target %</Label>
                <Input
                  type="number"
                  value={formProfitTarget}
                  onChange={(e) => setFormProfitTarget(e.target.value)}
                  className="mt-1"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3 mt-3">
              <div>
                <Label className="text-[10px] text-muted-foreground">Min Trading Days</Label>
                <Input
                  type="number"
                  value={formMinDays}
                  onChange={(e) => setFormMinDays(e.target.value)}
                  className="mt-1"
                />
              </div>
              <div>
                <Label className="text-[10px] text-muted-foreground">Max Trading Days</Label>
                <Input
                  type="number"
                  value={formMaxDays}
                  onChange={(e) => setFormMaxDays(e.target.value)}
                  placeholder="Unlimited"
                  className="mt-1"
                />
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button
              size="sm"
              className="bg-accent hover:bg-accent/80 text-white"
              onClick={onCreate}
              disabled={creating}
            >
              {creating ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Plus className="h-4 w-4 mr-1" />}
              Create Account
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
