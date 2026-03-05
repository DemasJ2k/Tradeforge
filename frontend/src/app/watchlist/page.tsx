"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import ChatHelpers from "@/components/ChatHelpers";
import {
  Eye, Plus, Trash2, X, Star, Bell, BellRing, ChevronDown, ChevronRight, Edit2, Check,
} from "lucide-react";

// ── Types ────────────────────────────────────────────────────────────

interface Watchlist {
  id: number;
  name: string;
  symbols: string[];
  created_at: string;
}

interface WatchlistAlert {
  id: number;
  symbol: string;
  condition: "price_above" | "price_below" | "pct_change";
  threshold: number;
  triggered: boolean;
  active: boolean;
  created_at: string;
}

// ── Helpers ──────────────────────────────────────────────────────────

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
function getToken() {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("token");
}
function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

const conditionLabels: Record<string, string> = {
  price_above: "Price Above",
  price_below: "Price Below",
  pct_change: "% Change",
};

// ── Page Component ───────────────────────────────────────────────────

export default function WatchlistPage() {
  const [watchlists, setWatchlists] = useState<Watchlist[]>([]);
  const [alerts, setAlerts] = useState<WatchlistAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  // Create watchlist form
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newSymbols, setNewSymbols] = useState("");

  // Add symbol form
  const [addSymbolWl, setAddSymbolWl] = useState<number | null>(null);
  const [addSymbolVal, setAddSymbolVal] = useState("");

  // Alert form
  const [showAlertForm, setShowAlertForm] = useState(false);
  const [alertSymbol, setAlertSymbol] = useState("");
  const [alertCondition, setAlertCondition] = useState("price_above");
  const [alertThreshold, setAlertThreshold] = useState("");

  // Edit name
  const [editId, setEditId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");

  const loadData = useCallback(async () => {
    try {
      const [wlRes, alertRes] = await Promise.all([
        fetch(`${API}/api/watchlists`, { headers: authHeaders() }).then(r => r.json()),
        fetch(`${API}/api/watchlists/alerts`, { headers: authHeaders() }).then(r => r.json()),
      ]);
      setWatchlists(wlRes.watchlists || []);
      setAlerts(alertRes.alerts || []);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const createWatchlist = async () => {
    if (!newName.trim()) return;
    const symbols = newSymbols.split(",").map(s => s.trim().toUpperCase()).filter(Boolean);
    try {
      await fetch(`${API}/api/watchlists`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ name: newName, symbols }),
      });
      setNewName(""); setNewSymbols(""); setShowCreate(false);
      await loadData();
    } catch { /* ignore */ }
  };

  const deleteWatchlist = async (id: number) => {
    if (!confirm("Delete this watchlist?")) return;
    await fetch(`${API}/api/watchlists/${id}`, { method: "DELETE", headers: authHeaders() });
    await loadData();
  };

  const addSymbol = async (wlId: number) => {
    const sym = addSymbolVal.trim().toUpperCase();
    if (!sym) return;
    await fetch(`${API}/api/watchlists/${wlId}/symbols`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ symbol: sym }),
    });
    setAddSymbolVal(""); setAddSymbolWl(null);
    await loadData();
  };

  const removeSymbol = async (wlId: number, symbol: string) => {
    await fetch(`${API}/api/watchlists/${wlId}/symbols/${symbol}`, {
      method: "DELETE", headers: authHeaders(),
    });
    await loadData();
  };

  const renameWatchlist = async (id: number) => {
    if (!editName.trim()) return;
    await fetch(`${API}/api/watchlists/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ name: editName }),
    });
    setEditId(null);
    await loadData();
  };

  const createAlert = async () => {
    if (!alertSymbol || !alertThreshold) return;
    await fetch(`${API}/api/watchlists/alerts`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({
        symbol: alertSymbol.toUpperCase(),
        condition: alertCondition,
        threshold: parseFloat(alertThreshold),
      }),
    });
    setShowAlertForm(false);
    setAlertSymbol(""); setAlertThreshold("");
    await loadData();
  };

  const deleteAlert = async (id: number) => {
    await fetch(`${API}/api/watchlists/alerts/${id}`, { method: "DELETE", headers: authHeaders() });
    await loadData();
  };

  const toggleAlert = async (alert: WatchlistAlert) => {
    await fetch(`${API}/api/watchlists/alerts/${alert.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ active: !alert.active }),
    });
    await loadData();
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-muted-foreground">Loading watchlists...</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-foreground">Watchlists</h1>
          <p className="text-muted-foreground text-sm mt-1">Track symbols and set price alerts</p>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => setShowAlertForm(true)} variant="outline" className="gap-1.5">
            <Bell className="h-4 w-4" /> New Alert
          </Button>
          <Button onClick={() => setShowCreate(true)} className="gap-1.5">
            <Plus className="h-4 w-4" /> New Watchlist
          </Button>
        </div>
      </div>

      {/* Create watchlist form */}
      {showCreate && (
        <Card className="border-card-border bg-card-bg">
          <CardContent className="p-4 space-y-3">
            <h3 className="text-sm font-semibold text-foreground">Create Watchlist</h3>
            <Input
              value={newName} onChange={e => setNewName(e.target.value)}
              placeholder="Watchlist name (e.g. Gold & Silver)"
              className="bg-input-bg"
            />
            <Input
              value={newSymbols} onChange={e => setNewSymbols(e.target.value)}
              placeholder="Symbols (comma-separated): XAUUSD, XAGUSD, EURUSD"
              className="bg-input-bg"
            />
            <div className="flex gap-2">
              <Button onClick={createWatchlist} disabled={!newName.trim()}>Create</Button>
              <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Alert form */}
      {showAlertForm && (
        <Card className="border-card-border bg-card-bg">
          <CardContent className="p-4 space-y-3">
            <h3 className="text-sm font-semibold text-foreground">Create Price Alert</h3>
            <div className="grid grid-cols-3 gap-3">
              <Input
                value={alertSymbol} onChange={e => setAlertSymbol(e.target.value.toUpperCase())}
                placeholder="Symbol" className="bg-input-bg"
              />
              <select
                value={alertCondition} onChange={e => setAlertCondition(e.target.value)}
                className="rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm text-foreground"
              >
                <option value="price_above">Price Above</option>
                <option value="price_below">Price Below</option>
                <option value="pct_change">% Change</option>
              </select>
              <Input
                type="number" step="any" value={alertThreshold}
                onChange={e => setAlertThreshold(e.target.value)}
                placeholder="Threshold" className="bg-input-bg"
              />
            </div>
            <div className="flex gap-2">
              <Button onClick={createAlert} disabled={!alertSymbol || !alertThreshold}>Create Alert</Button>
              <Button variant="outline" onClick={() => setShowAlertForm(false)}>Cancel</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Watchlists */}
      {watchlists.length === 0 && !showCreate ? (
        <Card className="border-card-border bg-card-bg p-12 text-center">
          <CardContent className="flex flex-col items-center p-0">
            <Eye className="h-10 w-10 text-muted-foreground mb-4 opacity-40" />
            <h3 className="text-lg font-medium mb-2">No Watchlists Yet</h3>
            <p className="text-sm text-muted-foreground mb-6 max-w-md">
              Create a watchlist to track your favorite trading symbols and set price alerts.
            </p>
            <Button onClick={() => setShowCreate(true)}>
              <Plus className="h-4 w-4 mr-1.5" /> Create Watchlist
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {watchlists.map(wl => {
            const isExpanded = expandedId === wl.id;
            return (
              <Card key={wl.id} className="border-card-border bg-card-bg overflow-hidden">
                <CardContent className="p-0">
                  {/* Watchlist header */}
                  <div
                    className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-sidebar-hover/30 transition-colors"
                    onClick={() => setExpandedId(isExpanded ? null : wl.id)}
                  >
                    <div className="flex items-center gap-2">
                      {isExpanded ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
                      {editId === wl.id ? (
                        <div className="flex items-center gap-1" onClick={e => e.stopPropagation()}>
                          <Input
                            value={editName} onChange={e => setEditName(e.target.value)}
                            className="h-7 w-40 text-sm bg-input-bg"
                            onKeyDown={e => { if (e.key === "Enter") renameWatchlist(wl.id); if (e.key === "Escape") setEditId(null); }}
                            autoFocus
                          />
                          <button onClick={() => renameWatchlist(wl.id)} className="p-1 text-green-400 hover:text-green-300">
                            <Check className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      ) : (
                        <span className="text-sm font-medium text-foreground">{wl.name}</span>
                      )}
                      <Badge variant="secondary" className="text-[10px]">{wl.symbols.length} symbols</Badge>
                    </div>
                    <div className="flex items-center gap-1" onClick={e => e.stopPropagation()}>
                      <button
                        onClick={() => { setEditId(wl.id); setEditName(wl.name); }}
                        className="p-1.5 rounded text-muted-foreground hover:text-foreground hover:bg-sidebar-hover"
                        title="Rename"
                      >
                        <Edit2 className="h-3.5 w-3.5" />
                      </button>
                      <button
                        onClick={() => deleteWatchlist(wl.id)}
                        className="p-1.5 rounded text-muted-foreground hover:text-red-400 hover:bg-red-400/10"
                        title="Delete watchlist"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>

                  {/* Symbol chips + add symbol */}
                  {isExpanded && (
                    <div className="px-4 pb-3 border-t border-card-border/50">
                      <div className="flex flex-wrap gap-2 mt-3">
                        {wl.symbols.map(sym => (
                          <div
                            key={sym}
                            className="flex items-center gap-1.5 rounded-lg bg-background border border-card-border px-3 py-1.5 text-sm group"
                          >
                            <Star className="h-3 w-3 text-accent" />
                            <span className="font-medium">{sym}</span>
                            <button
                              onClick={() => removeSymbol(wl.id, sym)}
                              className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-red-400 transition-opacity ml-1"
                            >
                              <X className="h-3 w-3" />
                            </button>
                          </div>
                        ))}
                        {/* Add symbol inline */}
                        {addSymbolWl === wl.id ? (
                          <div className="flex items-center gap-1">
                            <Input
                              value={addSymbolVal}
                              onChange={e => setAddSymbolVal(e.target.value.toUpperCase())}
                              placeholder="SYMBOL"
                              className="h-8 w-24 text-xs bg-input-bg uppercase"
                              onKeyDown={e => {
                                if (e.key === "Enter") addSymbol(wl.id);
                                if (e.key === "Escape") setAddSymbolWl(null);
                              }}
                              autoFocus
                            />
                            <button onClick={() => addSymbol(wl.id)} className="p-1 text-green-400 hover:text-green-300">
                              <Check className="h-3.5 w-3.5" />
                            </button>
                            <button onClick={() => setAddSymbolWl(null)} className="p-1 text-muted-foreground hover:text-foreground">
                              <X className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        ) : (
                          <button
                            onClick={() => setAddSymbolWl(wl.id)}
                            className="flex items-center gap-1 rounded-lg border border-dashed border-card-border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors"
                          >
                            <Plus className="h-3 w-3" /> Add Symbol
                          </button>
                        )}
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {/* Price Alerts Section */}
      <div className="mt-8">
        <div className="flex items-center gap-2 mb-4">
          <BellRing className="h-5 w-5 text-accent" />
          <h2 className="text-lg font-semibold text-foreground">Price Alerts</h2>
          <Badge variant="secondary">{alerts.length}</Badge>
        </div>

        {alerts.length === 0 ? (
          <Card className="border-card-border bg-card-bg">
            <CardContent className="p-6 text-center">
              <Bell className="h-8 w-8 text-muted-foreground mx-auto mb-2 opacity-30" />
              <p className="text-sm text-muted-foreground">No alerts configured. Create one to get notified when a price target is hit.</p>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-2">
            {alerts.map(alert => (
              <Card key={alert.id} className="border-card-border bg-card-bg">
                <CardContent className="p-3 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={`h-2 w-2 rounded-full ${alert.triggered ? "bg-amber-400" : alert.active ? "bg-green-400 animate-pulse" : "bg-zinc-500"}`} />
                    <div>
                      <span className="text-sm font-medium text-foreground">{alert.symbol}</span>
                      <span className="text-xs text-muted-foreground ml-2">
                        {conditionLabels[alert.condition] || alert.condition} {alert.threshold}
                      </span>
                    </div>
                    {alert.triggered && <Badge className="bg-amber-500/20 text-amber-400 text-[10px]">Triggered</Badge>}
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => toggleAlert(alert)}
                      className={`text-xs px-2 py-1 rounded transition-colors ${
                        alert.active ? "bg-green-500/15 text-green-400 hover:bg-green-500/25" : "bg-zinc-500/15 text-zinc-400 hover:bg-zinc-500/25"
                      }`}
                    >
                      {alert.active ? "Active" : "Paused"}
                    </button>
                    <button
                      onClick={() => deleteAlert(alert.id)}
                      className="p-1 rounded text-muted-foreground hover:text-red-400 hover:bg-red-400/10"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>

      <ChatHelpers />
    </div>
  );
}
