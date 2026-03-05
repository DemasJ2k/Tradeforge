'use client';

import { useState, useEffect, useCallback } from 'react';
import type { UserSettings, StorageInfo, Invitation, BrokerCredentialMasked } from '@/types';
import ChatHelpers from '@/components/ChatHelpers';
import { useSettings } from '@/hooks/useSettings';
import { useAuth } from '@/hooks/useAuth';
import { User, Palette, Bot, TrendingUp, Link, HardDrive, Cog, ChevronDown, Bell, Zap, type LucideIcon } from 'lucide-react';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function getToken() {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('token');
}
function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

// ─── Reusable form components ───
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs text-muted-foreground mb-1">{label}</label>
      {children}
    </div>
  );
}

const inputCls = "w-full bg-input-bg border border-card-border rounded-lg px-3 py-2 text-foreground text-sm focus:border-blue-500 focus:outline-none";
const selectCls = inputCls;
const btnPrimary = "px-4 py-2 rounded-lg bg-fa-accent hover:bg-fa-accent/80 text-foreground text-sm font-medium transition-colors disabled:opacity-40";
const btnDanger = "px-4 py-2 rounded-lg bg-red-600/80 hover:bg-red-500 text-foreground text-sm font-medium transition-colors";
const btnSecondary = "px-4 py-2 rounded-lg bg-input-bg hover:bg-input-bg text-foreground/90 text-sm font-medium transition-colors";

// ─── Entity type display config ───
const ENTITY_LABELS: Record<string, { label: string; icon: string }> = {
  strategy: { label: 'Strategy', icon: '📋' },
  datasource: { label: 'Data Source', icon: '📁' },
  backtest: { label: 'Backtest', icon: '📊' },
  agent: { label: 'Agent', icon: '🤖' },
  ml_model: { label: 'ML Model', icon: '🧠' },
  knowledge: { label: 'Article', icon: '📚' },
  conversation: { label: 'Conversation', icon: '💬' },
};

function RecycleBinSection() {
  const [items, setItems] = useState<{id: number; name: string; entity_type: string; deleted_at: string}[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const loadBin = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/recycle-bin`, { headers: authHeaders() });
      if (res.ok) {
        const data = await res.json();
        setItems(data.items || []);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { loadBin(); }, [loadBin]);

  const handleRestore = async (type: string, id: number) => {
    const key = `restore-${type}-${id}`;
    setActionLoading(key);
    try {
      await fetch(`${API}/api/recycle-bin/${type}/${id}/restore`, { method: 'POST', headers: authHeaders() });
      await loadBin();
    } catch { /* ignore */ }
    finally { setActionLoading(null); }
  };

  const handlePermanentDelete = async (type: string, id: number, name: string) => {
    if (!confirm(`Permanently delete "${name}"? This cannot be undone.`)) return;
    const key = `delete-${type}-${id}`;
    setActionLoading(key);
    try {
      await fetch(`${API}/api/recycle-bin/${type}/${id}`, { method: 'DELETE', headers: authHeaders() });
      await loadBin();
    } catch { /* ignore */ }
    finally { setActionLoading(null); }
  };

  const handleClearAll = async () => {
    if (!confirm('Permanently delete ALL items in the recycle bin? This cannot be undone.')) return;
    setActionLoading('clear-all');
    try {
      await fetch(`${API}/api/recycle-bin/clear`, { method: 'DELETE', headers: authHeaders() });
      await loadBin();
    } catch { /* ignore */ }
    finally { setActionLoading(null); }
  };

  const formatDate = (iso: string) => {
    if (!iso) return '';
    const d = new Date(iso);
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    if (days < 7) return `${days}d ago`;
    return d.toLocaleDateString();
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-md font-semibold text-foreground">Recently Deleted</h3>
        {items.length > 0 && (
          <button
            onClick={handleClearAll}
            disabled={actionLoading === 'clear-all'}
            className="text-xs text-red-400 hover:text-red-300 transition-colors disabled:opacity-40"
          >
            {actionLoading === 'clear-all' ? 'Clearing...' : `Clear All (${items.length})`}
          </button>
        )}
      </div>
      {loading ? (
        <p className="text-sm text-muted-foreground">Loading...</p>
      ) : items.length === 0 ? (
        <div className="bg-input-bg rounded-lg p-4 border border-card-border text-center">
          <p className="text-sm text-muted-foreground">Recycle bin is empty</p>
        </div>
      ) : (
        <div className="space-y-2 max-h-[400px] overflow-y-auto">
          {items.map((item) => {
            const cfg = ENTITY_LABELS[item.entity_type] || { label: item.entity_type, icon: '📄' };
            const restoreKey = `restore-${item.entity_type}-${item.id}`;
            const deleteKey = `delete-${item.entity_type}-${item.id}`;
            return (
              <div
                key={`${item.entity_type}-${item.id}`}
                className="flex items-center justify-between bg-input-bg rounded-lg px-3 py-2 border border-card-border group hover:border-card-border/80"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-sm">{cfg.icon}</span>
                  <div className="min-w-0">
                    <span className="text-sm text-foreground truncate block">{item.name || 'Untitled'}</span>
                    <span className="text-[10px] text-muted-foreground">{cfg.label} &bull; {formatDate(item.deleted_at)}</span>
                  </div>
                </div>
                <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button
                    onClick={() => handleRestore(item.entity_type, item.id)}
                    disabled={actionLoading === restoreKey}
                    className="px-2 py-1 text-[11px] rounded bg-fa-accent/20 text-fa-accent hover:bg-fa-accent/30 transition-colors disabled:opacity-40"
                  >
                    {actionLoading === restoreKey ? '...' : 'Restore'}
                  </button>
                  <button
                    onClick={() => handlePermanentDelete(item.entity_type, item.id, item.name)}
                    disabled={actionLoading === deleteKey}
                    className="px-2 py-1 text-[11px] rounded bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors disabled:opacity-40"
                  >
                    {actionLoading === deleteKey ? '...' : 'Delete'}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// Theme presets with preview colors
const THEME_PRESETS = [
  { id: 'midnight-teal', label: 'Midnight Teal', accent: '#06b6d4', bg: '#0c1425', desc: 'Default dark theme' },
  { id: 'ocean-blue', label: 'Ocean Blue', accent: '#3b82f6', bg: '#0a1628', desc: 'Deep blue tones' },
  { id: 'emerald-trader', label: 'Emerald Trader', accent: '#10b981', bg: '#0a1a14', desc: 'Green finance feel' },
  { id: 'sunset-gold', label: 'Sunset Gold', accent: '#f59e0b', bg: '#1a1408', desc: 'Warm amber tones' },
  { id: 'neon-purple', label: 'Neon Purple', accent: '#a855f7', bg: '#14081e', desc: 'Vibrant purple' },
  { id: 'classic-dark', label: 'Classic Dark', accent: '#6b7280', bg: '#111111', desc: 'Neutral & minimal' },
  { id: 'warm-stone', label: 'Warm Stone', accent: '#a8a29e', bg: '#1c1917', desc: 'Earthy warm tones' },
  { id: 'arctic-light', label: 'Arctic Light', accent: '#0ea5e9', bg: '#0c1a2a', desc: 'Cool & crisp' },
] as const;

// Preset card component
function PresetCard({ preset, active, onSelect }: {
  preset: typeof THEME_PRESETS[number];
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button onClick={onSelect}
      className={`relative rounded-xl p-3 text-left transition-all border-2 ${
        active
          ? 'border-fa-accent ring-2 ring-fa-accent/30 scale-[1.02]'
          : 'border-card-border hover:border-fa-accent/40 hover:scale-[1.01]'
      }`}
      style={{ backgroundColor: preset.bg }}
    >
      <div className="flex items-center gap-2 mb-2">
        <div className="w-4 h-4 rounded-full" style={{ backgroundColor: preset.accent }} />
        <span className="text-xs font-semibold text-foreground">{preset.label}</span>
      </div>
      {/* Mini preview bars */}
      <div className="flex gap-1 mb-1.5">
        <div className="h-1.5 w-8 rounded-full" style={{ backgroundColor: preset.accent, opacity: 0.8 }} />
        <div className="h-1.5 w-5 rounded-full bg-white/10" />
        <div className="h-1.5 w-6 rounded-full bg-white/10" />
      </div>
      <p className="text-[10px] text-muted-foreground">{preset.desc}</p>
      {active && (
        <div className="absolute top-2 right-2 w-2 h-2 rounded-full bg-fa-accent" />
      )}
    </button>
  );
}

// Color swatch button (kept for chart colors)
function ColorPick({ value, onChange, colors }: { value: string; onChange: (v: string) => void; colors: string[] }) {
  return (
    <div className="flex gap-2 flex-wrap">
      {colors.map(c => (
        <button key={c} onClick={() => onChange(c)}
          className={`w-7 h-7 rounded-full border-2 transition-all ${value === c ? 'border-white scale-110' : 'border-transparent opacity-60 hover:opacity-100'}`}
          style={{ backgroundColor: c }}
        />
      ))}
    </div>
  );
}

// Toggle
function Toggle({ value, onChange, label }: { value: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button onClick={() => onChange(!value)} className="flex items-center gap-3 group">
      <div className={`relative w-10 h-5 rounded-full transition-colors ${value ? 'bg-fa-accent' : 'bg-input-bg'}`}>
        <div className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform ${value ? 'translate-x-5' : ''}`} />
      </div>
      <span className="text-sm text-foreground/80 group-hover:text-foreground">{label}</span>
    </button>
  );
}

// ─── LLM Models by provider ───
const LLM_MODELS: Record<string, { value: string; label: string }[]> = {
  claude: [
    { value: 'claude-sonnet-4-20250514', label: 'Claude Sonnet 4' },
    { value: 'claude-opus-4-20250514', label: 'Claude Opus 4' },
    { value: 'claude-3-5-haiku-20241022', label: 'Claude 3.5 Haiku' },
  ],
  openai: [
    { value: 'gpt-4o', label: 'GPT-4o' },
    { value: 'gpt-4o-mini', label: 'GPT-4o Mini' },
    { value: 'o3-mini', label: 'o3-mini' },
  ],
  gemini: [
    { value: 'gemini-2.5-pro-preview-05-06', label: 'Gemini 2.5 Pro' },
    { value: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash' },
  ],
};

// ─── Webhook Settings Section ───
const WEBHOOK_EVENTS = [
  { value: 'trade_opened', label: 'Trade Opened' },
  { value: 'trade_closed', label: 'Trade Closed' },
  { value: 'signal_generated', label: 'Signal Generated' },
  { value: 'agent_started', label: 'Agent Started' },
  { value: 'agent_stopped', label: 'Agent Stopped' },
  { value: 'agent_error', label: 'Agent Error' },
  { value: 'backtest_complete', label: 'Backtest Complete' },
  { value: 'optimization_complete', label: 'Optimization Complete' },
  { value: 'alert_triggered', label: 'Alert Triggered' },
  { value: 'price_alert', label: 'Price Alert' },
];

interface WebhookEndpoint {
  id: number;
  name: string;
  url: string;
  events: string[];
  enabled: boolean;
  has_secret: boolean;
  last_triggered_at: string | null;
  last_status_code: number | null;
  failure_count: number;
  created_at: string;
}

interface WebhookLogEntry {
  id: number;
  event_type: string;
  payload: Record<string, unknown>;
  status_code: number;
  success: boolean;
  delivered_at: string;
}

function WebhookSettingsSection() {
  const [webhooks, setWebhooks] = useState<WebhookEndpoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [logsFor, setLogsFor] = useState<number | null>(null);
  const [logs, setLogs] = useState<WebhookLogEntry[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [testResult, setTestResult] = useState<{ id: number; msg: string; ok: boolean } | null>(null);
  const [saving, setSaving] = useState(false);

  // Form state
  const [form, setForm] = useState({ name: '', url: '', secret: '', events: [] as string[], enabled: true });

  const loadWebhooks = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/webhooks`, { headers: authHeaders() });
      if (res.ok) {
        const data = await res.json();
        setWebhooks(data.webhooks || []);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { loadWebhooks(); }, [loadWebhooks]);

  const resetForm = () => { setForm({ name: '', url: '', secret: '', events: [], enabled: true }); setShowCreate(false); setEditId(null); };

  const handleSave = async () => {
    if (!form.name || !form.url) return;
    setSaving(true);
    try {
      const method = editId ? 'PUT' : 'POST';
      const url = editId ? `${API}/api/webhooks/${editId}` : `${API}/api/webhooks`;
      const body: Record<string, unknown> = { name: form.name, url: form.url, events: form.events, enabled: form.enabled };
      if (form.secret) body.secret = form.secret;
      await fetch(url, { method, headers: { ...authHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      await loadWebhooks();
      resetForm();
    } catch { /* ignore */ }
    finally { setSaving(false); }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('Delete this webhook endpoint?')) return;
    await fetch(`${API}/api/webhooks/${id}`, { method: 'DELETE', headers: authHeaders() });
    await loadWebhooks();
  };

  const handleTest = async (id: number) => {
    setTestResult(null);
    try {
      const res = await fetch(`${API}/api/webhooks/${id}/test`, { method: 'POST', headers: authHeaders() });
      const data = await res.json();
      setTestResult({ id, msg: data.message || (data.success ? 'OK' : 'Failed'), ok: data.success });
    } catch {
      setTestResult({ id, msg: 'Network error', ok: false });
    }
  };

  const handleViewLogs = async (id: number) => {
    if (logsFor === id) { setLogsFor(null); return; }
    setLogsFor(id);
    setLogsLoading(true);
    try {
      const res = await fetch(`${API}/api/webhooks/${id}/logs?limit=20`, { headers: authHeaders() });
      if (res.ok) { const data = await res.json(); setLogs(data.logs || []); }
    } catch { setLogs([]); }
    finally { setLogsLoading(false); }
  };

  const startEdit = (wh: WebhookEndpoint) => {
    setForm({ name: wh.name, url: wh.url, secret: '', events: wh.events || [], enabled: wh.enabled });
    setEditId(wh.id);
    setShowCreate(true);
  };

  const toggleEvent = (ev: string) => {
    setForm(f => ({ ...f, events: f.events.includes(ev) ? f.events.filter(e => e !== ev) : [...f.events, ev] }));
  };

  if (loading) return <div className="text-sm text-muted-foreground py-4">Loading webhooks...</div>;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-md font-semibold text-foreground">Webhook Endpoints</h3>
        {!showCreate && (
          <button onClick={() => { resetForm(); setShowCreate(true); }} className={btnPrimary + ' text-xs !py-1.5 !px-3'}>
            + Add Webhook
          </button>
        )}
      </div>
      <p className="text-xs text-muted-foreground -mt-2">
        Receive HTTP POST notifications when events occur. Supports HMAC-SHA256 signing.
      </p>

      {/* Create / Edit form */}
      {showCreate && (
        <div className="bg-input-bg rounded-lg border border-card-border p-4 space-y-3">
          <h4 className="text-sm font-medium text-foreground">{editId ? 'Edit Webhook' : 'New Webhook'}</h4>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label="Name">
              <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                placeholder="My Webhook" className={inputCls} />
            </Field>
            <Field label="URL">
              <input value={form.url} onChange={e => setForm(f => ({ ...f, url: e.target.value }))}
                placeholder="https://example.com/webhook" className={inputCls} />
            </Field>
          </div>
          <Field label="Secret (optional — for HMAC-SHA256 signing)">
            <input value={form.secret} onChange={e => setForm(f => ({ ...f, secret: e.target.value }))}
              placeholder={editId ? '(leave blank to keep existing)' : 'my-secret-key'} className={inputCls} />
          </Field>
          <Field label="Events (empty = subscribe to all)">
            <div className="flex flex-wrap gap-1.5 mt-1">
              {WEBHOOK_EVENTS.map(ev => (
                <button key={ev.value} onClick={() => toggleEvent(ev.value)}
                  className={`text-[11px] px-2 py-1 rounded-md border transition-colors ${
                    form.events.includes(ev.value)
                      ? 'bg-fa-accent/20 border-fa-accent text-fa-accent'
                      : 'bg-input-bg border-card-border text-muted-foreground hover:text-foreground'
                  }`}>
                  {ev.label}
                </button>
              ))}
            </div>
          </Field>
          <Toggle value={form.enabled} onChange={v => setForm(f => ({ ...f, enabled: v }))} label="Enabled" />
          <div className="flex gap-2 pt-1">
            <button onClick={handleSave} disabled={saving || !form.name || !form.url} className={btnPrimary + ' text-xs'}>
              {saving ? 'Saving...' : editId ? 'Update' : 'Create'}
            </button>
            <button onClick={resetForm} className={btnSecondary + ' text-xs'}>Cancel</button>
          </div>
        </div>
      )}

      {/* Webhook list */}
      {webhooks.length === 0 && !showCreate ? (
        <div className="text-center py-6 text-sm text-muted-foreground">
          No webhook endpoints configured yet. Click &ldquo;Add Webhook&rdquo; to get started.
        </div>
      ) : (
        <div className="space-y-2">
          {webhooks.map(wh => (
            <div key={wh.id} className="bg-input-bg rounded-lg border border-card-border p-3">
              <div className="flex items-center gap-3">
                {/* Status dot */}
                <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${
                  !wh.enabled ? 'bg-gray-500' :
                  wh.failure_count > 5 ? 'bg-red-500' :
                  wh.failure_count > 0 ? 'bg-amber-500' : 'bg-emerald-500'
                }`} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-foreground truncate">{wh.name}</span>
                    {!wh.enabled && <span className="text-[10px] bg-gray-500/20 text-gray-400 px-1.5 py-0.5 rounded">Disabled</span>}
                    {wh.failure_count > 5 && <span className="text-[10px] bg-red-500/20 text-red-400 px-1.5 py-0.5 rounded">Failing</span>}
                  </div>
                  <div className="text-[11px] text-muted-foreground truncate mt-0.5">{wh.url}</div>
                  <div className="flex items-center gap-2 mt-1 flex-wrap">
                    {(wh.events || []).length === 0 ? (
                      <span className="text-[10px] text-muted-foreground/60">All events</span>
                    ) : (
                      (wh.events || []).map(ev => (
                        <span key={ev} className="text-[10px] bg-fa-accent/10 text-fa-accent px-1.5 py-0.5 rounded">{ev.replace(/_/g, ' ')}</span>
                      ))
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button onClick={() => handleTest(wh.id)} className="text-[11px] px-2 py-1 rounded bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 transition-colors">
                    Test
                  </button>
                  <button onClick={() => handleViewLogs(wh.id)} className="text-[11px] px-2 py-1 rounded bg-input-bg text-muted-foreground hover:text-foreground transition-colors border border-card-border">
                    Logs
                  </button>
                  <button onClick={() => startEdit(wh)} className="text-[11px] px-2 py-1 rounded bg-input-bg text-muted-foreground hover:text-foreground transition-colors border border-card-border">
                    Edit
                  </button>
                  <button onClick={() => handleDelete(wh.id)} className="text-[11px] px-2 py-1 rounded bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors">
                    Delete
                  </button>
                </div>
              </div>

              {/* Test result */}
              {testResult?.id === wh.id && (
                <div className={`mt-2 text-xs px-3 py-1.5 rounded ${testResult.ok ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
                  {testResult.ok ? '✓' : '✗'} {testResult.msg}
                </div>
              )}

              {/* Logs */}
              {logsFor === wh.id && (
                <div className="mt-2 border-t border-card-border pt-2">
                  {logsLoading ? (
                    <div className="text-xs text-muted-foreground py-2">Loading logs...</div>
                  ) : logs.length === 0 ? (
                    <div className="text-xs text-muted-foreground py-2">No delivery logs yet.</div>
                  ) : (
                    <div className="space-y-1 max-h-48 overflow-y-auto">
                      {logs.map(log => (
                        <div key={log.id} className="flex items-center gap-2 text-[11px] px-2 py-1 rounded bg-card-bg/50">
                          <span className={`w-1.5 h-1.5 rounded-full ${log.success ? 'bg-emerald-500' : 'bg-red-500'}`} />
                          <span className="text-muted-foreground font-mono w-8">{log.status_code}</span>
                          <span className="text-foreground/70">{log.event_type.replace(/_/g, ' ')}</span>
                          <span className="text-muted-foreground/50 ml-auto">
                            {new Date(log.delivered_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const TABS: { id: string; label: string; icon: LucideIcon }[] = [
  { id: 'profile',       label: 'Profile',           icon: User },
  { id: 'appearance',    label: 'Appearance',         icon: Palette },
  { id: 'llm',           label: 'AI / LLM',           icon: Bot },
  { id: 'copilot',       label: 'AI Copilot',          icon: Zap },
  { id: 'trading',       label: 'Trading Defaults',   icon: TrendingUp },
  { id: 'brokers',       label: 'Brokers',            icon: Link },
  { id: 'data',          label: 'Data Management',    icon: HardDrive },
  { id: 'notifications', label: 'Notifications',      icon: Bell },
  { id: 'platform',      label: 'Platform',           icon: Cog },
];
type TabId = typeof TABS[number]['id'];

export default function SettingsPage() {
  const { updateSettings: applySettingsToDOM } = useSettings();
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<TabId>('profile');
  const [storage, setStorage] = useState<StorageInfo | null>(null);

  // Password change state
  const [currentPw, setCurrentPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [pwMsg, setPwMsg] = useState('');

  // LLM test state
  const [llmApiKey, setLlmApiKey] = useState('');
  const [llmTesting, setLlmTesting] = useState(false);
  const [llmTestResult, setLlmTestResult] = useState('');

  // Profile / 2FA state
  const { user, refreshUser } = useAuth();
  const [profileEmail, setProfileEmail] = useState('');
  const [profilePhone, setProfilePhone] = useState('');
  const [profileMsg, setProfileMsg] = useState('');
  const [totpSetup, setTotpSetup] = useState<{ secret: string; qr_base64: string } | null>(null);
  const [totpCode, setTotpCode] = useState('');
  const [totpMsg, setTotpMsg] = useState('');
  const [disableCode, setDisableCode] = useState('');

  // Admin invitation state
  const [invEmail, setInvEmail] = useState('');
  const [invUsername, setInvUsername] = useState('');
  const [invPassword, setInvPassword] = useState('');
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [invMsg, setInvMsg] = useState('');

  // Admin password reset requests
  const [resetRequests, setResetRequests] = useState<Array<{
    id: number; user_id: number; username: string; email: string;
    created_at: string; expires_at: string; used: boolean;
  }>>([]);
  const [manualResetUserId, setManualResetUserId] = useState<number | null>(null);
  const [manualResetPw, setManualResetPw] = useState('');
  const [manualResetMsg, setManualResetMsg] = useState('');

  // Admin: registered users
  const [registeredUsers, setRegisteredUsers] = useState<Array<{
    id: number; username: string; email: string;
    is_admin: boolean; must_change_password: boolean; created_at: string;
  }>>([]);
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null);
  const [deleteMsg, setDeleteMsg] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(true);

  // Broker credentials state
  const [brokerCreds, setBrokerCreds] = useState<BrokerCredentialMasked[]>([]);
  const [brokerForms, setBrokerForms] = useState<Record<string, Record<string, string>>>({});
  const [brokerAutoConnect, setBrokerAutoConnect] = useState<Record<string, boolean>>({});
  const [brokerBusy, setBrokerBusy] = useState<Record<string, boolean>>({});
  const [brokerMsg, setBrokerMsg] = useState<Record<string, string>>({});
  const [expandedBroker, setExpandedBroker] = useState<string | null>(null);

  // Notification channel state
  const [notifSmtpPass, setNotifSmtpPass] = useState('');
  const [notifTelegramToken, setNotifTelegramToken] = useState('');
  const [notifTesting, setNotifTesting] = useState<string | null>(null); // 'email' | 'telegram' | null
  const [notifTestResult, setNotifTestResult] = useState<Record<string, string>>({});

  // Load profile data when user loads
  useEffect(() => {
    if (user) {
      setProfileEmail(user.email || '');
      setProfilePhone(user.phone || '');
    }
  }, [user]);

  // Load invitations + reset requests + registered users if admin
  useEffect(() => {
    if (user?.is_admin && tab === 'profile') {
      fetch(`${API}/api/auth/invitations`, { headers: authHeaders() })
        .then(r => r.json())
        .then(d => { if (Array.isArray(d)) setInvitations(d); })
        .catch(() => {});
      fetch(`${API}/api/auth/admin/reset-requests`, { headers: authHeaders() })
        .then(r => r.json())
        .then(d => { if (Array.isArray(d)) setResetRequests(d); })
        .catch(() => {});
      fetch(`${API}/api/auth/admin/users`, { headers: authHeaders() })
        .then(r => r.json())
        .then(d => { if (Array.isArray(d)) setRegisteredUsers(d); })
        .catch(() => {});
    }
  }, [user, tab]);

  // Load settings
  useEffect(() => {
    fetch(`${API}/api/settings`, { headers: authHeaders() })
      .then(r => r.json())
      .then(d => { setSettings(d); setLoading(false); })
      .catch(() => setLoading(false));

    fetch(`${API}/api/settings/storage`, { headers: authHeaders() })
      .then(r => r.json())
      .then(d => setStorage(d))
      .catch(() => {});
  }, []);

  // Load broker credentials
  const loadBrokerCreds = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/settings/broker-credentials`, { headers: authHeaders() });
      if (r.ok) {
        const d = await r.json();
        setBrokerCreds(d.brokers || []);
        const ac: Record<string, boolean> = {};
        for (const b of d.brokers || []) ac[b.broker] = b.auto_connect;
        setBrokerAutoConnect(ac);
      }
    } catch {}
  }, []);

  useEffect(() => { loadBrokerCreds(); }, [loadBrokerCreds]);

  // Broker form field setter
  const setBrokerField = (broker: string, field: string, value: string) => {
    setBrokerForms(prev => ({ ...prev, [broker]: { ...(prev[broker] || {}), [field]: value } }));
  };

  // Save broker credentials
  const saveBrokerCreds = async (broker: string) => {
    setBrokerBusy(p => ({ ...p, [broker]: true }));
    setBrokerMsg(p => ({ ...p, [broker]: '' }));
    try {
      const form = brokerForms[broker] || {};
      const r = await fetch(`${API}/api/settings/broker-credentials`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ credentials: { broker, ...form, auto_connect: brokerAutoConnect[broker] ?? false } }),
      });
      if (!r.ok) throw new Error((await r.json()).detail || 'Save failed');
      setBrokerMsg(p => ({ ...p, [broker]: 'Credentials saved' }));
      setBrokerForms(p => ({ ...p, [broker]: {} })); // Clear form
      await loadBrokerCreds();
    } catch (e: unknown) {
      setBrokerMsg(p => ({ ...p, [broker]: e instanceof Error ? e.message : 'Save failed' }));
    } finally {
      setBrokerBusy(p => ({ ...p, [broker]: false }));
    }
  };

  // Connect to broker
  const connectBroker = async (broker: string) => {
    setBrokerBusy(p => ({ ...p, [broker]: true }));
    setBrokerMsg(p => ({ ...p, [broker]: '' }));
    try {
      const r = await fetch(`${API}/api/settings/broker-credentials/${broker}/connect`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (!r.ok) throw new Error((await r.json()).detail || 'Connection failed');
      setBrokerMsg(p => ({ ...p, [broker]: 'Connected!' }));
      await loadBrokerCreds();
    } catch (e: unknown) {
      setBrokerMsg(p => ({ ...p, [broker]: e instanceof Error ? e.message : 'Connection failed' }));
    } finally {
      setBrokerBusy(p => ({ ...p, [broker]: false }));
    }
  };

  // Delete broker credentials
  const deleteBrokerCreds = async (broker: string) => {
    if (!confirm(`Remove saved credentials for ${broker.toUpperCase()}?`)) return;
    setBrokerBusy(p => ({ ...p, [broker]: true }));
    try {
      await fetch(`${API}/api/settings/broker-credentials/${broker}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      setBrokerMsg(p => ({ ...p, [broker]: 'Credentials removed' }));
      await loadBrokerCreds();
    } catch {
      setBrokerMsg(p => ({ ...p, [broker]: 'Failed to remove' }));
    } finally {
      setBrokerBusy(p => ({ ...p, [broker]: false }));
    }
  };

  // Save settings
  const save = useCallback(async (patch: Record<string, unknown>) => {
    setSaving(true);
    setError('');
    setSaved(false);
    try {
      const body = { ...patch };
      // Include llm_api_key if user typed one
      if (llmApiKey) body.llm_api_key = llmApiKey;

      const r = await fetch(`${API}/api/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error((await r.json()).detail || 'Save failed');
      const d = await r.json();
      setSettings(d);
      applySettingsToDOM(d); // Apply theme/accent/font to DOM immediately
      setSaved(true);
      setLlmApiKey(''); // Clear after save
      setTimeout(() => setSaved(false), 2000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  }, [llmApiKey, applySettingsToDOM]);

  // Update local state field (functional update to avoid stale state when called multiple times)
  const set = (key: keyof UserSettings, val: unknown) => {
    setSettings(prev => prev ? { ...prev, [key]: val } : prev);
  };

  // Change password
  const changePassword = async () => {
    setPwMsg('');
    try {
      const r = await fetch(`${API}/api/settings/change-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ current_password: currentPw, new_password: newPw }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Failed');
      setPwMsg('Password changed successfully');
      setCurrentPw('');
      setNewPw('');
    } catch (e: unknown) {
      setPwMsg(e instanceof Error ? e.message : 'Failed');
    }
  };

  // Test LLM
  const testLlm = async () => {
    if (!settings) return;
    setLlmTesting(true);
    setLlmTestResult('');
    try {
      const r = await fetch(`${API}/api/settings/test-llm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          provider: settings.llm_provider,
          api_key: llmApiKey || 'stored',
          model: settings.llm_model,
        }),
      });
      const d = await r.json();
      setLlmTestResult(d.success ? `✓ ${d.message} (${d.model_used})` : `✗ ${d.message}`);
    } catch {
      setLlmTestResult('✗ Connection failed');
    } finally {
      setLlmTesting(false);
    }
  };

  if (loading || !settings) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-muted-foreground">Loading settings...</div>
      </div>
    );
  }

  const s = settings;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl sm:text-2xl font-bold text-foreground">Settings</h1>
        <p className="text-muted-foreground text-sm mt-1">Configure your FlowrexAlgo experience</p>
      </div>

      <div className="flex flex-col md:flex-row gap-4">
        {/* Tab navigation — horizontal scroll on mobile, vertical sidebar on desktop */}
        <div className={`shrink-0 transition-all duration-200 md:block ${sidebarOpen ? 'md:w-48' : 'md:w-12'}`}>
          {/* Toggle button — desktop only */}
          <button
            onClick={() => setSidebarOpen(o => !o)}
            className="mb-2 hidden md:flex h-9 w-full items-center justify-center rounded-lg border border-card-border text-muted-foreground hover:bg-card-bg hover:text-foreground transition-colors text-sm"
            title={sidebarOpen ? 'Collapse menu' : 'Expand menu'}
          >
            {sidebarOpen ? '◀' : '▶'}
          </button>
          {/* Mobile: horizontal scroll tabs */}
          <div className="flex md:hidden overflow-x-auto gap-1 pb-1 -mx-1 px-1">
            {TABS.map(t => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`flex items-center gap-1.5 rounded-lg text-xs font-medium transition-colors whitespace-nowrap px-3 py-2
                  ${tab === t.id ? 'bg-fa-accent/20 text-fa-accent' : 'text-muted-foreground hover:bg-card-bg hover:text-foreground'}`}
              >
                <t.icon className="w-3.5 h-3.5 shrink-0" />
                <span>{t.label}</span>
              </button>
            ))}
          </div>
          {/* Desktop: vertical sidebar */}
          <div className="hidden md:block space-y-1">
            {TABS.map(t => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                title={!sidebarOpen ? t.label : undefined}
                className={`w-full flex items-center gap-2.5 rounded-lg text-sm font-medium transition-colors overflow-hidden
                  ${sidebarOpen ? 'px-3 py-2.5 text-left' : 'px-0 py-2.5 justify-center'}
                  ${tab === t.id ? 'bg-fa-accent/20 text-fa-accent' : 'text-muted-foreground hover:bg-card-bg hover:text-foreground'}`}
              >
                <t.icon className="w-4 h-4 shrink-0" />
                {sidebarOpen && <span className="truncate">{t.label}</span>}
              </button>
            ))}
          </div>
        </div>

        {/* Tab content */}
        <div className="flex-1 bg-card-bg rounded-xl border border-card-border p-4 sm:p-6 min-h-[400px] md:min-h-[500px] max-h-[calc(100vh-180px)] overflow-y-auto">
          {/* ─── Profile ─── */}
          {tab === 'profile' && (
            <div className="space-y-6 max-w-lg">
              <h2 className="text-lg font-semibold text-foreground">Profile & Account</h2>
              <Field label="Display Name">
                <input type="text" value={s.display_name} onChange={e => set('display_name', e.target.value)} className={inputCls} placeholder="Your name" />
              </Field>
              <div className="pt-2">
                <button onClick={() => save({ display_name: s.display_name })} disabled={saving} className={btnPrimary}>
                  {saving ? 'Saving...' : 'Save Profile'}
                </button>
              </div>

              <hr className="border-card-border" />
              <h3 className="text-md font-semibold text-foreground">Contact Information</h3>
              <Field label="Email">
                <input type="email" value={profileEmail} onChange={e => setProfileEmail(e.target.value)} className={inputCls} placeholder="you@example.com" />
              </Field>
              <Field label="Phone">
                <input type="tel" value={profilePhone} onChange={e => setProfilePhone(e.target.value)} className={inputCls} placeholder="+1 (555) 123-4567" />
              </Field>
              <button onClick={async () => {
                setProfileMsg('');
                try {
                  await fetch(`${API}/api/auth/profile`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json', ...authHeaders() },
                    body: JSON.stringify({ email: profileEmail, phone: profilePhone }),
                  });
                  await refreshUser();
                  setProfileMsg('Contact info saved');
                } catch { setProfileMsg('Failed to save'); }
              }} className={btnPrimary}>Save Contact Info</button>
              {profileMsg && <p className={`text-sm ${profileMsg.includes('saved') ? 'text-green-400' : 'text-red-400'}`}>{profileMsg}</p>}

              <hr className="border-card-border" />
              <h3 className="text-md font-semibold text-foreground">Two-Factor Authentication (2FA)</h3>
              {user?.totp_enabled ? (
                <div className="space-y-3">
                  <p className="text-sm text-green-400">2FA is enabled</p>
                  <Field label="Enter 2FA code to disable">
                    <div className="flex gap-2">
                      <input type="text" inputMode="numeric" maxLength={6} value={disableCode}
                        onChange={e => setDisableCode(e.target.value.replace(/\D/g, ''))} className={inputCls} placeholder="000000" />
                      <button onClick={async () => {
                        setTotpMsg('');
                        try {
                          const r = await fetch(`${API}/api/auth/disable-totp`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json', ...authHeaders() },
                            body: JSON.stringify({ code: disableCode }),
                          });
                          const d = await r.json();
                          if (r.ok) { await refreshUser(); setTotpMsg('2FA disabled'); setDisableCode(''); }
                          else setTotpMsg(d.detail || 'Failed');
                        } catch { setTotpMsg('Failed'); }
                      }} disabled={disableCode.length !== 6} className={btnDanger}>Disable 2FA</button>
                    </div>
                  </Field>
                  {totpMsg && <p className={`text-sm ${totpMsg.includes('disabled') ? 'text-green-400' : 'text-red-400'}`}>{totpMsg}</p>}
                </div>
              ) : totpSetup ? (
                <div className="space-y-3">
                  <p className="text-sm text-muted-foreground">Scan this QR code with your authenticator app (Google Authenticator, Authy, etc.):</p>
                  <div className="flex justify-center">
                    {/* eslint-disable-next-line @next/next/no-img-element -- base64 data URIs can't use next/image */}
                    <img src={`data:image/png;base64,${totpSetup.qr_base64}`} alt="TOTP QR" className="w-48 h-48 rounded-lg" />
                  </div>
                  <p className="text-xs text-muted-foreground/60 text-center break-all">Manual key: {totpSetup.secret}</p>
                  <Field label="Enter the 6-digit code to confirm">
                    <div className="flex gap-2">
                      <input type="text" inputMode="numeric" maxLength={6} value={totpCode}
                        onChange={e => setTotpCode(e.target.value.replace(/\D/g, ''))} className={inputCls} placeholder="000000" />
                      <button onClick={async () => {
                        setTotpMsg('');
                        try {
                          const r = await fetch(`${API}/api/auth/confirm-totp`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json', ...authHeaders() },
                            body: JSON.stringify({ code: totpCode }),
                          });
                          const d = await r.json();
                          if (d.valid) { await refreshUser(); setTotpSetup(null); setTotpCode(''); setTotpMsg('2FA enabled!'); }
                          else setTotpMsg('Invalid code. Try again.');
                        } catch { setTotpMsg('Verification failed'); }
                      }} disabled={totpCode.length !== 6} className={btnPrimary}>Confirm</button>
                    </div>
                  </Field>
                  {totpMsg && <p className={`text-sm ${totpMsg.includes('enabled') ? 'text-green-400' : 'text-red-400'}`}>{totpMsg}</p>}
                </div>
              ) : (
                <div className="space-y-3">
                  <p className="text-sm text-muted-foreground">Add an extra layer of security to your account.</p>
                  <button onClick={async () => {
                    setTotpMsg('');
                    try {
                      const r = await fetch(`${API}/api/auth/setup-totp`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', ...authHeaders() },
                      });
                      const d = await r.json();
                      if (r.ok) setTotpSetup(d);
                      else setTotpMsg(d.detail || 'Setup failed');
                    } catch { setTotpMsg('Setup failed'); }
                  }} className={btnPrimary}>Enable 2FA</button>
                  {totpMsg && <p className="text-sm text-red-400">{totpMsg}</p>}
                </div>
              )}

              <hr className="border-card-border" />
              <h3 className="text-md font-semibold text-foreground">Change Password</h3>
              <Field label="Current Password">
                <input type="password" value={currentPw} onChange={e => setCurrentPw(e.target.value)} className={inputCls} />
              </Field>
              <Field label="New Password">
                <input type="password" value={newPw} onChange={e => setNewPw(e.target.value)} className={inputCls} />
              </Field>
              <button onClick={changePassword} disabled={!currentPw || !newPw} className={btnPrimary}>Change Password</button>
              {pwMsg && <p className={`text-sm ${pwMsg.includes('success') ? 'text-green-400' : 'text-red-400'}`}>{pwMsg}</p>}

              {/* ─── Admin: Invitations ─── */}
              {user?.is_admin && (
                <>
                  <hr className="border-card-border" />
                  <h3 className="text-md font-semibold text-foreground">Invite Users (Admin)</h3>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                    <Field label="Email">
                      <input type="email" value={invEmail} onChange={e => setInvEmail(e.target.value)} className={inputCls} placeholder="user@email.com" />
                    </Field>
                    <Field label="Username">
                      <input type="text" value={invUsername} onChange={e => setInvUsername(e.target.value)} className={inputCls} placeholder="username" />
                    </Field>
                    <Field label="Temp Password">
                      <input type="text" value={invPassword} onChange={e => setInvPassword(e.target.value)} className={inputCls} placeholder="temp123" />
                    </Field>
                  </div>
                  <button onClick={async () => {
                    setInvMsg('');
                    try {
                      const r = await fetch(`${API}/api/auth/invite`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', ...authHeaders() },
                        body: JSON.stringify({ email: invEmail, username: invUsername, temp_password: invPassword }),
                      });
                      const d = await r.json();
                      if (r.ok) {
                        setInvMsg(`Invitation created for ${invUsername}`);
                        setInvEmail(''); setInvUsername(''); setInvPassword('');
                        // Refresh invitations list
                        const lr = await fetch(`${API}/api/auth/invitations`, { headers: authHeaders() });
                        const ld = await lr.json();
                        if (Array.isArray(ld)) setInvitations(ld);
                      } else {
                        setInvMsg(d.detail || 'Failed to create invitation');
                      }
                    } catch { setInvMsg('Failed to create invitation'); }
                  }} disabled={!invEmail || !invUsername || !invPassword} className={btnPrimary}>Send Invitation</button>
                  {invMsg && <p className={`text-sm ${invMsg.includes('created') ? 'text-green-400' : 'text-red-400'}`}>{invMsg}</p>}

                  {invitations.length > 0 && (
                    <div className="bg-input-bg rounded-lg border border-card-border overflow-hidden">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-card-border text-muted-foreground text-xs">
                            <th className="text-left px-3 py-2">Username</th>
                            <th className="text-left px-3 py-2">Email</th>
                            <th className="text-left px-3 py-2">Status</th>
                            <th className="px-3 py-2"></th>
                          </tr>
                        </thead>
                        <tbody>
                          {invitations.map(inv => (
                            <tr key={inv.id} className="border-b border-card-border">
                              <td className="px-3 py-2 text-foreground">{inv.username}</td>
                              <td className="px-3 py-2 text-muted-foreground">{inv.email}</td>
                              <td className="px-3 py-2">
                                <span className={`text-xs px-2 py-0.5 rounded-full ${
                                  inv.status === 'accepted' ? 'bg-green-900/30 text-green-400' :
                                  inv.status === 'revoked' ? 'bg-red-900/30 text-red-400' :
                                  'bg-yellow-900/30 text-yellow-400'
                                }`}>{inv.status}</span>
                              </td>
                              <td className="px-3 py-2 text-right flex gap-2 justify-end">
                                {inv.status === 'pending' && (
                                  <button onClick={async () => {
                                    await fetch(`${API}/api/auth/invitations/${inv.id}`, { method: 'DELETE', headers: authHeaders() });
                                    setInvitations(prev => prev.map(i => i.id === inv.id ? { ...i, status: 'revoked' } : i));
                                  }} className="text-xs text-red-400 hover:text-red-300">Revoke</button>
                                )}
                                {inv.status === 'revoked' && (
                                  <button onClick={async () => {
                                    const r = await fetch(`${API}/api/auth/invitations/${inv.id}`, { method: 'DELETE', headers: authHeaders() });
                                    if (r.ok) setInvitations(prev => prev.filter(i => i.id !== inv.id));
                                  }} className="text-xs text-muted-foreground/60 hover:text-red-400">Delete</button>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  {/* ─── Admin: Password Reset Requests ─── */}
                  <hr className="border-card-border" />
                  <h3 className="text-md font-semibold text-foreground">Password Reset Requests (Admin)</h3>
                  {resetRequests.length === 0 ? (
                    <p className="text-xs text-muted-foreground/60">No password reset requests yet.</p>
                  ) : (
                    <div className="bg-input-bg rounded-lg border border-card-border overflow-hidden">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-card-border text-muted-foreground text-xs">
                            <th className="text-left px-3 py-2">Username</th>
                            <th className="text-left px-3 py-2">Email</th>
                            <th className="text-left px-3 py-2">Requested</th>
                            <th className="text-left px-3 py-2">Status</th>
                            <th className="px-3 py-2"></th>
                          </tr>
                        </thead>
                        <tbody>
                          {resetRequests.map(req => (
                            <tr key={req.id} className="border-b border-card-border">
                              <td className="px-3 py-2 text-foreground">{req.username}</td>
                              <td className="px-3 py-2 text-muted-foreground">{req.email}</td>
                              <td className="px-3 py-2 text-muted-foreground text-xs">{req.created_at}</td>
                              <td className="px-3 py-2">
                                <span className={`text-xs px-2 py-0.5 rounded-full ${
                                  req.used ? 'bg-green-900/30 text-green-400' : 'bg-yellow-900/30 text-yellow-400'
                                }`}>{req.used ? 'used' : 'pending'}</span>
                              </td>
                              <td className="px-3 py-2 text-right">
                                {!req.used && (
                                  <button
                                    onClick={() => { setManualResetUserId(req.user_id); setManualResetPw(''); setManualResetMsg(''); }}
                                    className="text-xs text-fa-accent hover:text-blue-300"
                                  >
                                    Manual Reset
                                  </button>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* ─── Admin: Registered Users ─── */}
                  <hr className="border-card-border" />
                  <h3 className="text-md font-semibold text-foreground">Registered Users (Admin)</h3>
                  {deleteMsg && (
                    <p className={`text-xs ${deleteMsg.includes('deleted') ? 'text-green-400' : 'text-red-400'}`}>{deleteMsg}</p>
                  )}
                  {registeredUsers.length === 0 ? (
                    <p className="text-xs text-muted-foreground/60">No registered users yet.</p>
                  ) : (
                    <div className="bg-input-bg rounded-lg border border-card-border overflow-hidden">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-card-border text-muted-foreground text-xs">
                            <th className="text-left px-3 py-2">Username</th>
                            <th className="text-left px-3 py-2">Email</th>
                            <th className="text-left px-3 py-2">Joined</th>
                            <th className="text-left px-3 py-2">Status</th>
                            <th className="px-3 py-2"></th>
                          </tr>
                        </thead>
                        <tbody>
                          {registeredUsers.map(u => (
                            <tr key={u.id} className="border-b border-card-border">
                              <td className="px-3 py-2 text-foreground font-medium">{u.username}</td>
                              <td className="px-3 py-2 text-muted-foreground text-xs">{u.email || '—'}</td>
                              <td className="px-3 py-2 text-muted-foreground text-xs">{u.created_at}</td>
                              <td className="px-3 py-2">
                                {u.is_admin ? (
                                  <span className="text-xs px-2 py-0.5 rounded-full bg-blue-900/30 text-fa-accent">admin</span>
                                ) : u.must_change_password ? (
                                  <span className="text-xs px-2 py-0.5 rounded-full bg-yellow-900/30 text-yellow-400">must change pw</span>
                                ) : (
                                  <span className="text-xs px-2 py-0.5 rounded-full bg-green-900/30 text-green-400">active</span>
                                )}
                              </td>
                              <td className="px-3 py-2 text-right">
                                {!u.is_admin && u.id !== user?.id && (
                                  <button
                                    onClick={() => { setDeleteConfirmId(u.id); setDeleteMsg(''); }}
                                    className="text-xs text-red-400 hover:text-red-300"
                                  >
                                    Delete
                                  </button>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* Delete User Confirmation Modal */}
                  {deleteConfirmId !== null && (() => {
                    const target = registeredUsers.find(u => u.id === deleteConfirmId);
                    return (
                      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
                        <div className="w-full max-w-sm rounded-xl border border-card-border bg-card-bg p-6 space-y-4">
                          <h3 className="font-semibold text-foreground">Delete User Account</h3>
                          <p className="text-sm text-foreground/80">
                            Are you sure you want to permanently delete{' '}
                            <strong className="text-foreground">{target?.username}</strong>{target?.email ? ` (${target.email})` : ''}?
                          </p>
                          <p className="text-xs text-red-400">
                            This removes their account, settings, LLM data, and access. This cannot be undone.
                          </p>
                          <div className="flex gap-2">
                            <button
                              onClick={async () => {
                                try {
                                  const r = await fetch(`${API}/api/auth/admin/users/${deleteConfirmId}`, {
                                    method: 'DELETE',
                                    headers: authHeaders(),
                                  });
                                  const d = await r.json();
                                  if (r.ok) {
                                    setRegisteredUsers(prev => prev.filter(u => u.id !== deleteConfirmId));
                                    setDeleteMsg(d.message || 'User deleted.');
                                  } else {
                                    setDeleteMsg(d.detail || 'Failed to delete user.');
                                  }
                                } catch { setDeleteMsg('Request failed.'); }
                                setDeleteConfirmId(null);
                              }}
                              className="flex-1 rounded-lg bg-red-600 py-2 text-sm font-medium text-foreground hover:bg-red-700 transition-colors"
                            >
                              Yes, Delete
                            </button>
                            <button
                              onClick={() => setDeleteConfirmId(null)}
                              className="flex-1 rounded-lg border border-card-border py-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  })()}

                  {/* Manual Reset Modal */}
                  {manualResetUserId !== null && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
                      <div className="w-full max-w-sm rounded-xl border border-card-border bg-card-bg p-6 space-y-4">
                        <h3 className="font-semibold text-foreground">Manual Password Reset</h3>
                        <p className="text-xs text-muted-foreground">
                          Set a temporary password for this user. They will be required to change it on next login.
                        </p>
                        <input
                          type="text"
                          value={manualResetPw}
                          onChange={e => setManualResetPw(e.target.value)}
                          className={inputCls}
                          placeholder="Temporary password (min 6 chars)"
                        />
                        {manualResetMsg && <p className={`text-xs ${manualResetMsg.includes('success') || manualResetMsg.includes('Reset') ? 'text-green-400' : 'text-red-400'}`}>{manualResetMsg}</p>}
                        <div className="flex gap-2">
                          <button
                            onClick={async () => {
                              if (manualResetPw.length < 6) { setManualResetMsg('Password must be at least 6 characters'); return; }
                              try {
                                const r = await fetch(`${API}/api/auth/admin/manual-reset`, {
                                  method: 'POST',
                                  headers: { 'Content-Type': 'application/json', ...authHeaders() },
                                  body: JSON.stringify({ user_id: manualResetUserId, temp_password: manualResetPw }),
                                });
                                const d = await r.json();
                                if (r.ok) {
                                  setManualResetMsg('Reset successful — user must change password on next login.');
                                  // Refresh reset requests
                                  const lr = await fetch(`${API}/api/auth/admin/reset-requests`, { headers: authHeaders() });
                                  const ld = await lr.json();
                                  if (Array.isArray(ld)) setResetRequests(ld);
                                  setTimeout(() => { setManualResetUserId(null); setManualResetPw(''); setManualResetMsg(''); }, 1800);
                                } else { setManualResetMsg(d.detail || 'Failed'); }
                              } catch { setManualResetMsg('Request failed'); }
                            }}
                            disabled={!manualResetPw}
                            className={btnPrimary}
                          >
                            Set Password
                          </button>
                          <button
                            onClick={() => { setManualResetUserId(null); setManualResetPw(''); setManualResetMsg(''); }}
                            className="flex-1 rounded-lg border border-card-border py-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* ─── Appearance ─── */}
          {tab === 'appearance' && (
            <div className="space-y-8 max-w-2xl">
              <h2 className="text-lg font-semibold text-foreground">Appearance</h2>

              {/* Mode toggle */}
              <div>
                <label className="block text-xs text-muted-foreground mb-2 font-medium uppercase tracking-wider">Mode</label>
                <div className="flex gap-2">
                  {(['dark', 'light', 'system'] as const).map(mode => (
                    <button key={mode} onClick={() => set('theme', mode)}
                      className={`px-4 py-2 rounded-lg text-sm font-medium transition-all capitalize ${
                        s.theme === mode
                          ? 'bg-fa-accent text-foreground'
                          : 'bg-card-bg border border-card-border text-muted-foreground hover:text-foreground hover:border-fa-accent/40'
                      }`}
                    >
                      {mode}
                    </button>
                  ))}
                </div>
              </div>

              {/* Theme presets */}
              <div>
                <label className="block text-xs text-muted-foreground mb-3 font-medium uppercase tracking-wider">Theme Preset</label>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {THEME_PRESETS.map(preset => (
                    <PresetCard
                      key={preset.id}
                      preset={preset}
                      active={s.accent_color === `preset:${preset.id}` || (preset.id === 'midnight-teal' && !s.accent_color?.startsWith('preset:') && !s.accent_color?.startsWith('#'))}
                      onSelect={() => set('accent_color', `preset:${preset.id}`)}
                    />
                  ))}
                </div>
              </div>

              {/* Custom accent color */}
              <div>
                <label className="block text-xs text-muted-foreground mb-2 font-medium uppercase tracking-wider">Custom Accent</label>
                <div className="flex items-center gap-3">
                  <input
                    type="color"
                    value={s.accent_color?.startsWith('#') ? s.accent_color : '#06b6d4'}
                    onChange={e => set('accent_color', e.target.value)}
                    className="w-10 h-10 rounded-lg border border-card-border bg-transparent cursor-pointer"
                  />
                  <input
                    type="text"
                    value={s.accent_color?.startsWith('#') ? s.accent_color : ''}
                    onChange={e => { if (/^#[0-9a-f]{0,6}$/i.test(e.target.value)) set('accent_color', e.target.value); }}
                    placeholder="#06b6d4"
                    className={inputCls + ' w-32 font-mono'}
                  />
                  <span className="text-xs text-muted-foreground">or pick a preset above</span>
                </div>
              </div>

              {/* Font size */}
              <div>
                <label className="block text-xs text-muted-foreground mb-2 font-medium uppercase tracking-wider">Font Size</label>
                <div className="flex gap-2">
                  {(['small', 'normal', 'large'] as const).map(sz => (
                    <button key={sz} onClick={() => set('font_size', sz)}
                      className={`px-4 py-2 rounded-lg text-sm font-medium transition-all capitalize ${
                        s.font_size === sz
                          ? 'bg-fa-accent text-foreground'
                          : 'bg-card-bg border border-card-border text-muted-foreground hover:text-foreground hover:border-fa-accent/40'
                      }`}
                    >
                      {sz}
                    </button>
                  ))}
                </div>
              </div>

              <Toggle value={s.compact_mode} onChange={v => set('compact_mode', v)} label="Compact Mode" />

              <hr className="border-card-border" />
              <h3 className="text-md font-semibold text-foreground">Chart Colors</h3>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <Field label="Bullish Candle">
                  <input type="color" value={s.chart_up_color} onChange={e => set('chart_up_color', e.target.value)} className="w-full h-9 rounded bg-transparent cursor-pointer" />
                </Field>
                <Field label="Bearish Candle">
                  <input type="color" value={s.chart_down_color} onChange={e => set('chart_down_color', e.target.value)} className="w-full h-9 rounded bg-transparent cursor-pointer" />
                </Field>
                <Field label="Volume">
                  <input type="color" value={s.chart_volume_color} onChange={e => set('chart_volume_color', e.target.value)} className="w-full h-9 rounded bg-transparent cursor-pointer" />
                </Field>
              </div>
              <div className="flex gap-6">
                <Toggle value={s.chart_grid} onChange={v => set('chart_grid', v)} label="Show Grid" />
                <Toggle value={s.chart_crosshair} onChange={v => set('chart_crosshair', v)} label="Crosshair" />
              </div>
              <div className="pt-2">
                <button onClick={() => save({
                  theme: s.theme, accent_color: s.accent_color, font_size: s.font_size,
                  compact_mode: s.compact_mode, chart_up_color: s.chart_up_color,
                  chart_down_color: s.chart_down_color, chart_volume_color: s.chart_volume_color,
                  chart_grid: s.chart_grid, chart_crosshair: s.chart_crosshair,
                })} disabled={saving} className={btnPrimary}>
                  {saving ? 'Saving...' : 'Save Appearance'}
                </button>
              </div>
            </div>
          )}

          {/* ─── AI / LLM ─── */}
          {tab === 'llm' && (
            <div className="space-y-6 max-w-xl">
              <h2 className="text-lg font-semibold text-foreground">AI Assistant Configuration</h2>
              <p className="text-sm text-muted-foreground">Connect your preferred LLM provider to enable the AI trading assistant across all pages.</p>

              <Field label="Provider">
                <select value={s.llm_provider} onChange={e => { set('llm_provider', e.target.value); set('llm_model', ''); }} className={selectCls}>
                  <option value="">Select provider...</option>
                  <option value="claude">Anthropic (Claude)</option>
                  <option value="openai">OpenAI (GPT)</option>
                  <option value="gemini">Google (Gemini)</option>
                </select>
              </Field>

              <Field label="API Key">
                <div className="relative">
                  <input type="password" value={llmApiKey}
                    onChange={e => setLlmApiKey(e.target.value)}
                    placeholder={s.llm_api_key_set ? '••••••••••• (key stored)' : 'Enter API key...'}
                    className={inputCls} />
                  {s.llm_api_key_set && !llmApiKey && (
                    <span className="absolute right-3 top-2 text-xs text-green-400">✓ Saved</span>
                  )}
                </div>
              </Field>

              {s.llm_provider && LLM_MODELS[s.llm_provider] && (
                <Field label="Model">
                  <select value={s.llm_model} onChange={e => set('llm_model', e.target.value)} className={selectCls}>
                    <option value="">Select model...</option>
                    {LLM_MODELS[s.llm_provider].map(m => (
                      <option key={m.value} value={m.value}>{m.label}</option>
                    ))}
                  </select>
                </Field>
              )}

              <div className="grid grid-cols-2 gap-4">
                <Field label="Temperature">
                  <input type="number" step="0.1" min="0" max="2" value={s.llm_temperature}
                    onChange={e => set('llm_temperature', e.target.value)} className={inputCls} />
                </Field>
                <Field label="Max Tokens">
                  <input type="number" step="512" min="256" max="200000" value={s.llm_max_tokens}
                    onChange={e => set('llm_max_tokens', e.target.value)} className={inputCls} />
                </Field>
              </div>

              <Field label="Custom System Prompt (optional)">
                <textarea value={s.llm_system_prompt} onChange={e => set('llm_system_prompt', e.target.value)}
                  rows={3} placeholder="Additional instructions for the AI assistant..."
                  className={inputCls + ' resize-y'} />
                <p className="text-xs text-muted-foreground/60 mt-1">
                  The system prompt is prepended to every AI conversation. Use it to set the assistant&apos;s personality,
                  focus on specific trading strategies, or add constraints (e.g. &quot;Always explain risk before suggesting trades&quot;).
                  Leave blank for the default trading-focused prompt.
                </p>
              </Field>

              <div className="flex gap-3 items-center">
                <button onClick={() => save({
                  llm_provider: s.llm_provider, llm_model: s.llm_model,
                  llm_temperature: s.llm_temperature, llm_max_tokens: s.llm_max_tokens,
                  llm_system_prompt: s.llm_system_prompt,
                })} disabled={saving} className={btnPrimary}>
                  {saving ? 'Saving...' : 'Save LLM Settings'}
                </button>
                <button onClick={testLlm} disabled={llmTesting || (!llmApiKey && !s.llm_api_key_set)}
                  className={btnSecondary}>
                  {llmTesting ? 'Testing...' : 'Test Connection'}
                </button>
              </div>
              {llmTestResult && (
                <p className={`text-sm ${llmTestResult.startsWith('✓') ? 'text-green-400' : 'text-red-400'}`}>{llmTestResult}</p>
              )}
            </div>
          )}

          {/* ─── AI Copilot ─── */}
          {tab === 'copilot' && (
            <div className="space-y-6 max-w-xl">
              <h2 className="text-lg font-semibold text-foreground">AI Copilot Settings</h2>
              <p className="text-sm text-muted-foreground">
                Control how the AI copilot interacts with your account — toggle it on or off, set the autonomy level,
                and override permissions for individual tools.
              </p>

              <Toggle
                value={!!s.copilot_enabled}
                onChange={v => set('copilot_enabled', v ? 1 : 0)}
                label="Enable AI Copilot"
              />

              <Field label="Autonomy Level">
                <select
                  value={s.copilot_autonomy ?? 'assisted'}
                  onChange={e => set('copilot_autonomy', e.target.value)}
                  className={selectCls}
                >
                  <option value="analysis_only">Analysis Only — read-only tools, no side effects</option>
                  <option value="assisted">Assisted — actions require confirmation</option>
                  <option value="full_auto">Full Auto — all permitted tools run automatically</option>
                </select>
              </Field>

              <hr className="border-card-border" />
              <h3 className="text-md font-semibold text-foreground">Tool Permissions</h3>
              <p className="text-xs text-muted-foreground">
                Override the default permission for each tool. &quot;Default&quot; inherits from the autonomy level above.
              </p>

              <div className="bg-input-bg rounded-lg border border-card-border overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-card-border text-muted-foreground text-xs">
                      <th className="text-left px-3 py-2">Tool</th>
                      <th className="text-left px-3 py-2">Default</th>
                      <th className="text-left px-3 py-2">Permission</th>
                    </tr>
                  </thead>
                  <tbody>
                    {([
                      { tool: 'list_strategies',  defaultPerm: 'auto' },
                      { tool: 'list_data_sources', defaultPerm: 'auto' },
                      { tool: 'list_backtests',   defaultPerm: 'auto' },
                      { tool: 'get_positions',    defaultPerm: 'auto' },
                      { tool: 'get_orders',       defaultPerm: 'auto' },
                      { tool: 'run_backtest',     defaultPerm: 'confirm' },
                      { tool: 'start_agent',      defaultPerm: 'confirm' },
                      { tool: 'stop_agent',       defaultPerm: 'confirm' },
                      { tool: 'place_order',      defaultPerm: 'confirm' },
                      { tool: 'close_position',   defaultPerm: 'confirm' },
                    ] as const).map(({ tool, defaultPerm }) => {
                      const perms = (s.copilot_permissions ?? {}) as Record<string, string>;
                      return (
                        <tr key={tool} className="border-b border-card-border last:border-b-0">
                          <td className="px-3 py-2 text-foreground font-mono text-xs">{tool}</td>
                          <td className="px-3 py-2 text-muted-foreground text-xs">{defaultPerm}</td>
                          <td className="px-3 py-2">
                            <select
                              value={perms[tool] ?? 'default'}
                              onChange={e => {
                                const updated = { ...perms, [tool]: e.target.value };
                                set('copilot_permissions', updated);
                              }}
                              className={selectCls + ' text-xs py-1'}
                            >
                              <option value="default">Default</option>
                              <option value="auto">Auto</option>
                              <option value="confirm">Confirm</option>
                              <option value="blocked">Blocked</option>
                            </select>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="pt-2">
                <button onClick={() => save({
                  copilot_enabled: s.copilot_enabled,
                  copilot_autonomy: s.copilot_autonomy,
                  copilot_permissions: s.copilot_permissions,
                })} disabled={saving} className={btnPrimary}>
                  {saving ? 'Saving...' : 'Save Copilot Settings'}
                </button>
              </div>
            </div>
          )}

          {/* ─── Trading Defaults ─── */}
          {tab === 'trading' && (
            <div className="space-y-6 max-w-lg">
              <h2 className="text-lg font-semibold text-foreground">Default Trading Parameters</h2>
              <p className="text-sm text-muted-foreground">These defaults are pre-filled when creating new backtests or strategies.</p>

              <div className="grid grid-cols-2 gap-4">
                <Field label="Initial Balance ($)">
                  <input type="text" value={s.default_balance} onChange={e => set('default_balance', e.target.value)} className={inputCls} />
                </Field>
                <Field label="Risk Per Trade (%)">
                  <input type="text" value={s.default_risk_pct} onChange={e => set('default_risk_pct', e.target.value)} className={inputCls} />
                </Field>
                <Field label="Spread (points)">
                  <input type="text" value={s.default_spread} onChange={e => set('default_spread', e.target.value)} className={inputCls} />
                </Field>
                <Field label="Commission ($/lot)">
                  <input type="text" value={s.default_commission} onChange={e => set('default_commission', e.target.value)} className={inputCls} />
                </Field>
                <Field label="Point Value">
                  <input type="text" value={s.default_point_value} onChange={e => set('default_point_value', e.target.value)} className={inputCls} />
                </Field>
              </div>

              <Field label="Preferred Instruments (comma-separated)">
                <input type="text" value={s.preferred_instruments} onChange={e => set('preferred_instruments', e.target.value)}
                  placeholder="XAUUSD, EURUSD, BTCUSD" className={inputCls} />
              </Field>
              <Field label="Preferred Timeframes (comma-separated)">
                <input type="text" value={s.preferred_timeframes} onChange={e => set('preferred_timeframes', e.target.value)}
                  placeholder="M10, H1, H4, D1" className={inputCls} />
              </Field>

              <hr className="border-card-border" />
              <h3 className="text-md font-semibold text-foreground">Broker Defaults</h3>
              <Field label="Default Broker">
                <select value={s.default_broker} onChange={e => set('default_broker', e.target.value)} className={selectCls}>
                  <option value="">None selected</option>
                  <option value="oanda">Oanda</option>
                  <option value="coinbase">Coinbase</option>
                  <option value="mt5">MetaTrader 5</option>
                  <option value="tradovate">Tradovate</option>
                </select>
              </Field>

              <div className="pt-2">
                <button onClick={() => save({
                  default_balance: s.default_balance, default_spread: s.default_spread,
                  default_commission: s.default_commission, default_point_value: s.default_point_value,
                  default_risk_pct: s.default_risk_pct, preferred_instruments: s.preferred_instruments,
                  preferred_timeframes: s.preferred_timeframes, default_broker: s.default_broker,
                })} disabled={saving} className={btnPrimary}>
                  {saving ? 'Saving...' : 'Save Trading Defaults'}
                </button>
              </div>

              {/* ─── Broker Connections ─── */}
              <hr className="border-card-border" />
              <h3 className="text-md font-semibold text-foreground">Broker Connections</h3>
              <p className="text-sm text-muted-foreground">Store broker credentials securely. Connect with one click.</p>

              <div className="space-y-3">
                {[
                  { id: 'mt5', label: 'MetaTrader 5', fields: [
                    { key: 'server', label: 'Server', placeholder: 'e.g. MetaQuotes-Demo' },
                    { key: 'login', label: 'Login', placeholder: 'Account number' },
                    { key: 'password', label: 'Password', placeholder: 'Password', type: 'password' },
                  ]},
                  { id: 'oanda', label: 'Oanda', fields: [
                    { key: 'api_key', label: 'API Key', placeholder: 'Your Oanda API token', type: 'password' },
                    { key: 'account_id', label: 'Account ID', placeholder: 'e.g. 101-001-12345678-001' },
                  ]},
                  { id: 'coinbase', label: 'Coinbase', fields: [
                    { key: 'api_key', label: 'CDP API Key', placeholder: 'organizations/{org_id}/apiKeys/{key_id}', type: 'password' },
                    { key: 'api_secret', label: 'CDP Private Key', placeholder: '-----BEGIN EC PRIVATE KEY-----...', type: 'password', multiline: true },
                  ]},
                  { id: 'tradovate', label: 'Tradovate', fields: [
                    { key: 'username', label: 'Username', placeholder: 'Tradovate username' },
                    { key: 'password', label: 'Password', placeholder: 'Password', type: 'password' },
                    { key: 'app_id', label: 'App ID', placeholder: 'Application ID' },
                    { key: 'cid', label: 'CID', placeholder: 'Client ID' },
                    { key: 'sec', label: 'Secret', placeholder: 'Client secret', type: 'password' },
                  ]},
                ].map(broker => {
                  const cred = brokerCreds.find(c => c.broker === broker.id);
                  const isExpanded = expandedBroker === broker.id;
                  const busy = brokerBusy[broker.id];
                  const msg = brokerMsg[broker.id];

                  return (
                    <div key={broker.id} className="bg-input-bg rounded-lg border border-card-border overflow-hidden">
                      {/* Header row */}
                      <button onClick={() => setExpandedBroker(isExpanded ? null : broker.id)}
                        className="w-full flex items-center justify-between px-4 py-3 hover:bg-card-bg transition-colors">
                        <div className="flex items-center gap-3">
                          <span className="text-sm font-medium text-foreground">{broker.label}</span>
                          {cred?.connected && (
                            <span className="flex items-center gap-1 text-xs text-green-400">
                              <span className="w-2 h-2 rounded-full bg-green-400 inline-block" /> Connected
                            </span>
                          )}
                          {cred?.configured && !cred.connected && (
                            <span className="text-xs text-yellow-400">Configured</span>
                          )}
                          {!cred?.configured && (
                            <span className="text-xs text-muted-foreground/60">Not configured</span>
                          )}
                        </div>
                        <ChevronDown className={`w-4 h-4 text-muted-foreground transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
                      </button>

                      {/* Expanded form */}
                      {isExpanded && (
                        <div className="px-4 pb-4 space-y-3 border-t border-card-border pt-3">
                          {/* Show which fields are already stored */}
                          {cred?.configured && (
                            <p className="text-xs text-muted-foreground/60">
                              Stored fields: {cred.fields_set.join(', ')}
                              {' '}— fill in fields below to update
                            </p>
                          )}

                          {/* Credential fields */}
                          <div className="grid grid-cols-2 gap-3">
                            {broker.fields.map((f: { key: string; label: string; placeholder?: string; type?: string; multiline?: boolean }) => (
                              <Field key={f.key} label={f.label}>
                                {f.multiline ? (
                                  <textarea
                                    value={brokerForms[broker.id]?.[f.key] || ''}
                                    onChange={e => setBrokerField(broker.id, f.key, e.target.value)}
                                    placeholder={cred?.fields_set.includes(f.key) ? '••••• (stored)' : f.placeholder}
                                    className={inputCls + ' h-20 resize-y font-mono text-xs'}
                                    rows={3}
                                  />
                                ) : (
                                  <input
                                    type={f.type || 'text'}
                                    value={brokerForms[broker.id]?.[f.key] || ''}
                                    onChange={e => setBrokerField(broker.id, f.key, e.target.value)}
                                    placeholder={cred?.fields_set.includes(f.key) ? '••••• (stored)' : f.placeholder}
                                    className={inputCls}
                                  />
                                )}
                              </Field>
                            ))}
                          </div>

                          {/* Oanda practice toggle */}
                          {broker.id === 'oanda' && (
                            <Toggle
                              value={brokerForms[broker.id]?.practice !== 'false'}
                              onChange={v => setBrokerField(broker.id, 'practice', v ? 'true' : 'false')}
                              label="Practice Account (demo)"
                            />
                          )}

                          {/* Auto-connect toggle */}
                          <Toggle
                            value={brokerAutoConnect[broker.id] ?? false}
                            onChange={v => setBrokerAutoConnect(p => ({ ...p, [broker.id]: v }))}
                            label="Auto-connect on app startup"
                          />

                          {/* Action buttons */}
                          <div className="flex gap-2 flex-wrap pt-1">
                            <button
                              onClick={() => saveBrokerCreds(broker.id)}
                              disabled={busy}
                              className={btnPrimary}
                            >
                              {busy ? 'Saving...' : 'Save Credentials'}
                            </button>
                            {cred?.configured && !cred.connected && (
                              <button onClick={() => connectBroker(broker.id)} disabled={busy} className={btnSecondary}>
                                {busy ? 'Connecting...' : 'Connect'}
                              </button>
                            )}
                            {cred?.connected && (
                              <span className="px-3 py-2 text-sm text-green-400 font-medium">Connected</span>
                            )}
                            {cred?.configured && (
                              <button onClick={() => deleteBrokerCreds(broker.id)} disabled={busy} className={btnDanger}>
                                Remove
                              </button>
                            )}
                          </div>

                          {/* Status message */}
                          {msg && (
                            <p className={`text-xs ${msg.includes('saved') || msg.includes('Connected') || msg.includes('removed') ? 'text-green-400' : 'text-red-400'}`}>
                              {msg}
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ─── Data Management ─── */}
          {tab === 'data' && (
            <div className="space-y-6 max-w-lg">
              <h2 className="text-lg font-semibold text-foreground">Data Management</h2>

              {storage && (
                <div className="bg-input-bg rounded-lg p-4 border border-card-border">
                  <h3 className="text-sm font-medium text-foreground/80 mb-3">Storage Overview</h3>
                  <div className="grid grid-cols-2 gap-3 text-sm">
                    <div><span className="text-muted-foreground">CSV Files:</span> <span className="text-foreground font-medium">{storage.total_csvs}</span></div>
                    <div><span className="text-muted-foreground">Total Size:</span> <span className="text-foreground font-medium">{storage.total_size_mb} MB</span></div>
                    <div className="col-span-2"><span className="text-muted-foreground">Newest:</span> <span className="text-foreground/80 text-xs ml-1">{storage.newest_file || 'None'}</span></div>
                  </div>
                </div>
              )}

              <Field label="CSV Retention (days, 0 = keep forever)">
                <input type="number" min="0" value={s.csv_retention_days}
                  onChange={e => set('csv_retention_days', parseInt(e.target.value) || 0)} className={inputCls} />
              </Field>
              <Field label="Max Storage (MB, 0 = unlimited)">
                <input type="number" min="0" value={s.max_storage_mb}
                  onChange={e => set('max_storage_mb', parseInt(e.target.value) || 0)} className={inputCls} />
              </Field>
              <Field label="Export Format">
                <select value={s.export_format} onChange={e => set('export_format', e.target.value)} className={selectCls}>
                  <option value="csv">CSV</option>
                  <option value="json">JSON</option>
                </select>
              </Field>

              <div className="pt-2">
                <button onClick={() => save({
                  csv_retention_days: s.csv_retention_days, max_storage_mb: s.max_storage_mb,
                  export_format: s.export_format,
                })} disabled={saving} className={btnPrimary}>
                  {saving ? 'Saving...' : 'Save Data Settings'}
                </button>
              </div>

              <hr className="border-card-border" />
              <h3 className="text-md font-semibold text-foreground">Database</h3>
              <div className="flex gap-3">
                <button
                  onClick={async () => {
                    try {
                      const token = getToken();
                      const res = await fetch(`${API}/api/settings/backup`, {
                        headers: token ? { Authorization: `Bearer ${token}` } : {},
                      });
                      if (!res.ok) throw new Error('Backup failed');
                      const blob = await res.blob();
                      const url = URL.createObjectURL(blob);
                      const a = document.createElement('a');
                      a.href = url;
                      a.download = `tradeforge-backup-${new Date().toISOString().slice(0, 10)}.db`;
                      a.click();
                      URL.revokeObjectURL(url);
                    } catch {
                      alert('Failed to download backup');
                    }
                  }}
                  className={btnSecondary}
                >
                  Download Backup
                </button>
              </div>

              <hr className="border-card-border" />
              <RecycleBinSection />

              <hr className="border-card-border" />
              <h3 className="text-md font-semibold text-red-400">Danger Zone</h3>
              <p className="text-sm text-muted-foreground">Clear all uploaded CSV data and data source records. This cannot be undone.</p>
              <button onClick={async () => {
                if (!confirm('Delete ALL uploaded CSV data? This cannot be undone.')) return;
                await fetch(`${API}/api/settings/clear-data`, { method: 'DELETE', headers: authHeaders() });
                // Refresh storage
                const r = await fetch(`${API}/api/settings/storage`, { headers: authHeaders() });
                if (r.ok) setStorage(await r.json());
              }} className={btnDanger}>
                Clear All Data
              </button>
            </div>
          )}

          {/* ─── Brokers ─── */}
          {tab === 'brokers' && (
            <div className="space-y-6 max-w-2xl">
              <div>
                <h2 className="text-lg font-semibold text-foreground">Broker Connections</h2>
                <p className="text-sm text-muted-foreground mt-1">
                  Save API credentials for each broker. Credentials are encrypted at rest.
                  Once saved, you can connect and fetch historical data from the Data page.
                </p>
              </div>

              {/* Oanda */}
              {(() => {
                const bc = brokerCreds.find(b => b.broker === 'oanda');
                const busy = brokerBusy['oanda'];
                const msg = brokerMsg['oanda'];
                const form = brokerForms['oanda'] || {};
                const expanded = expandedBroker === 'oanda';
                return (
                  <div className="bg-input-bg rounded-xl border border-card-border p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <span className="font-semibold text-foreground">Oanda</span>
                        {bc?.connected && <span className="text-xs text-green-400 bg-green-900/30 px-2 py-0.5 rounded-full">Connected</span>}
                        {bc?.configured && !bc.connected && <span className="text-xs text-yellow-400 bg-yellow-900/30 px-2 py-0.5 rounded-full">Saved</span>}
                        {bc?.fields_set?.length ? <span className="text-xs text-muted-foreground/60">{bc.fields_set.join(', ')} set</span> : null}
                      </div>
                      <button onClick={() => setExpandedBroker(expanded ? null : 'oanda')}
                        className="text-xs text-muted-foreground hover:text-foreground px-3 py-1 rounded bg-input-bg hover:bg-input-bg">
                        {expanded ? 'Collapse' : bc?.configured ? 'Edit' : 'Configure'}
                      </button>
                    </div>
                    {expanded && (
                      <div className="space-y-3 pt-2 border-t border-card-border">
                        <Field label="API Key (Personal Access Token)">
                          <input type="password" value={form.api_key || ''} onChange={e => setBrokerField('oanda', 'api_key', e.target.value)}
                            placeholder="••••••••" className={inputCls} />
                        </Field>
                        <Field label="Account ID">
                          <input type="text" value={form.account_id || ''} onChange={e => setBrokerField('oanda', 'account_id', e.target.value)}
                            placeholder="101-011-12345678-001" className={inputCls} />
                        </Field>
                        <Toggle value={form.practice !== 'false'}
                          onChange={v => setBrokerField('oanda', 'practice', v.toString())}
                          label="Practice account (paper trading)" />
                        <Toggle value={brokerAutoConnect['oanda'] ?? false}
                          onChange={v => setBrokerAutoConnect(p => ({ ...p, oanda: v }))}
                          label="Auto-connect on startup" />
                        <div className="flex gap-2 pt-1 flex-wrap">
                          <button onClick={() => saveBrokerCreds('oanda')} disabled={busy} className={btnPrimary}>
                            {busy ? 'Saving...' : 'Save Credentials'}
                          </button>
                          {bc?.configured && (
                            <button onClick={() => connectBroker('oanda')} disabled={busy} className={btnSecondary}>
                              {busy ? 'Connecting...' : 'Test Connection'}
                            </button>
                          )}
                          {bc?.configured && (
                            <button onClick={() => deleteBrokerCreds('oanda')} disabled={busy} className={btnDanger}>
                              Remove
                            </button>
                          )}
                        </div>
                        {msg && <p className={`text-xs ${msg.includes('saved') || msg.includes('Connected') ? 'text-green-400' : 'text-red-400'}`}>{msg}</p>}
                      </div>
                    )}
                  </div>
                );
              })()}

              {/* Coinbase */}
              {(() => {
                const bc = brokerCreds.find(b => b.broker === 'coinbase');
                const busy = brokerBusy['coinbase'];
                const msg = brokerMsg['coinbase'];
                const form = brokerForms['coinbase'] || {};
                const expanded = expandedBroker === 'coinbase';
                return (
                  <div className="bg-input-bg rounded-xl border border-card-border p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <span className="font-semibold text-foreground">Coinbase Advanced</span>
                        {bc?.connected && <span className="text-xs text-green-400 bg-green-900/30 px-2 py-0.5 rounded-full">Connected</span>}
                        {bc?.configured && !bc.connected && <span className="text-xs text-yellow-400 bg-yellow-900/30 px-2 py-0.5 rounded-full">Saved</span>}
                      </div>
                      <button onClick={() => setExpandedBroker(expanded ? null : 'coinbase')}
                        className="text-xs text-muted-foreground hover:text-foreground px-3 py-1 rounded bg-input-bg hover:bg-input-bg">
                        {expanded ? 'Collapse' : bc?.configured ? 'Edit' : 'Configure'}
                      </button>
                    </div>
                    {expanded && (
                      <div className="space-y-3 pt-2 border-t border-card-border">
                        <p className="text-xs text-muted-foreground">Use CDP (Cloud Developer Platform) API keys. Format: organizations/…/apiKeys/…</p>
                        <Field label="CDP API Key Name">
                          <input type="text" value={form.api_key || ''} onChange={e => setBrokerField('coinbase', 'api_key', e.target.value)}
                            placeholder="organizations/.../apiKeys/..." className={inputCls} />
                        </Field>
                        <Field label="CDP API Secret (EC Private Key PEM)">
                          <textarea value={form.api_secret || ''} onChange={e => setBrokerField('coinbase', 'api_secret', e.target.value)}
                            placeholder="-----BEGIN EC PRIVATE KEY-----&#10;...&#10;-----END EC PRIVATE KEY-----"
                            rows={4} className={`${inputCls} font-mono text-xs`} />
                        </Field>
                        <div className="flex gap-2 pt-1 flex-wrap">
                          <button onClick={() => saveBrokerCreds('coinbase')} disabled={busy} className={btnPrimary}>
                            {busy ? 'Saving...' : 'Save Credentials'}
                          </button>
                          {bc?.configured && (
                            <button onClick={() => connectBroker('coinbase')} disabled={busy} className={btnSecondary}>
                              {busy ? 'Connecting...' : 'Test Connection'}
                            </button>
                          )}
                          {bc?.configured && (
                            <button onClick={() => deleteBrokerCreds('coinbase')} disabled={busy} className={btnDanger}>
                              Remove
                            </button>
                          )}
                        </div>
                        {msg && <p className={`text-xs ${msg.includes('saved') || msg.includes('Connected') ? 'text-green-400' : 'text-red-400'}`}>{msg}</p>}
                      </div>
                    )}
                  </div>
                );
              })()}

              {/* Tradovate */}
              {(() => {
                const bc = brokerCreds.find(b => b.broker === 'tradovate');
                const busy = brokerBusy['tradovate'];
                const msg = brokerMsg['tradovate'];
                const form = brokerForms['tradovate'] || {};
                const expanded = expandedBroker === 'tradovate';
                return (
                  <div className="bg-input-bg rounded-xl border border-card-border p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <span className="font-semibold text-foreground">Tradovate</span>
                        {bc?.connected && <span className="text-xs text-green-400 bg-green-900/30 px-2 py-0.5 rounded-full">Connected</span>}
                        {bc?.configured && !bc.connected && <span className="text-xs text-yellow-400 bg-yellow-900/30 px-2 py-0.5 rounded-full">Saved</span>}
                      </div>
                      <button onClick={() => setExpandedBroker(expanded ? null : 'tradovate')}
                        className="text-xs text-muted-foreground hover:text-foreground px-3 py-1 rounded bg-input-bg hover:bg-input-bg">
                        {expanded ? 'Collapse' : bc?.configured ? 'Edit' : 'Configure'}
                      </button>
                    </div>
                    {expanded && (
                      <div className="space-y-3 pt-2 border-t border-card-border">
                        <Field label="Username">
                          <input type="text" value={form.username || ''} onChange={e => setBrokerField('tradovate', 'username', e.target.value)}
                            placeholder="your@email.com" className={inputCls} />
                        </Field>
                        <Field label="Password">
                          <input type="password" value={form.password || ''} onChange={e => setBrokerField('tradovate', 'password', e.target.value)}
                            placeholder="••••••••" className={inputCls} />
                        </Field>
                        <Field label="App ID">
                          <input type="text" value={form.app_id || ''} onChange={e => setBrokerField('tradovate', 'app_id', e.target.value)}
                            placeholder="MyApp" className={inputCls} />
                        </Field>
                        <div className="grid grid-cols-2 gap-3">
                          <Field label="CID">
                            <input type="text" value={form.cid || ''} onChange={e => setBrokerField('tradovate', 'cid', e.target.value)}
                              placeholder="12345" className={inputCls} />
                          </Field>
                          <Field label="SEC">
                            <input type="password" value={form.sec || ''} onChange={e => setBrokerField('tradovate', 'sec', e.target.value)}
                              placeholder="••••••••" className={inputCls} />
                          </Field>
                        </div>
                        <Toggle value={form.practice !== 'false'}
                          onChange={v => setBrokerField('tradovate', 'practice', v.toString())}
                          label="Demo account" />
                        <div className="flex gap-2 pt-1 flex-wrap">
                          <button onClick={() => saveBrokerCreds('tradovate')} disabled={busy} className={btnPrimary}>
                            {busy ? 'Saving...' : 'Save Credentials'}
                          </button>
                          {bc?.configured && (
                            <button onClick={() => connectBroker('tradovate')} disabled={busy} className={btnSecondary}>
                              {busy ? 'Connecting...' : 'Test Connection'}
                            </button>
                          )}
                          {bc?.configured && (
                            <button onClick={() => deleteBrokerCreds('tradovate')} disabled={busy} className={btnDanger}>
                              Remove
                            </button>
                          )}
                        </div>
                        {msg && <p className={`text-xs ${msg.includes('saved') || msg.includes('Connected') ? 'text-green-400' : 'text-red-400'}`}>{msg}</p>}
                      </div>
                    )}
                  </div>
                );
              })()}

              {/* MT5 */}
              {(() => {
                const bc = brokerCreds.find(b => b.broker === 'mt5');
                const busy = brokerBusy['mt5'];
                const msg = brokerMsg['mt5'];
                const form = brokerForms['mt5'] || {};
                const expanded = expandedBroker === 'mt5';
                return (
                  <div className="bg-input-bg rounded-xl border border-card-border p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <span className="font-semibold text-foreground">MetaTrader 5</span>
                        {bc?.connected && <span className="text-xs text-green-400 bg-green-900/30 px-2 py-0.5 rounded-full">Connected</span>}
                        {bc?.configured && !bc.connected && <span className="text-xs text-yellow-400 bg-yellow-900/30 px-2 py-0.5 rounded-full">Saved</span>}
                        <span className="text-xs text-muted-foreground/40">(Windows-only)</span>
                      </div>
                      <button onClick={() => setExpandedBroker(expanded ? null : 'mt5')}
                        className="text-xs text-muted-foreground hover:text-foreground px-3 py-1 rounded bg-input-bg hover:bg-input-bg">
                        {expanded ? 'Collapse' : bc?.configured ? 'Edit' : 'Configure'}
                      </button>
                    </div>
                    {expanded && (
                      <div className="space-y-3 pt-2 border-t border-card-border">
                        <Field label="Server">
                          <input type="text" value={form.server || ''} onChange={e => setBrokerField('mt5', 'server', e.target.value)}
                            placeholder="ICMarkets-Demo01" className={inputCls} />
                        </Field>
                        <Field label="Login">
                          <input type="text" value={form.login || ''} onChange={e => setBrokerField('mt5', 'login', e.target.value)}
                            placeholder="12345678" className={inputCls} />
                        </Field>
                        <Field label="Password">
                          <input type="password" value={form.password || ''} onChange={e => setBrokerField('mt5', 'password', e.target.value)}
                            placeholder="••••••••" className={inputCls} />
                        </Field>
                        <div className="flex gap-2 pt-1 flex-wrap">
                          <button onClick={() => saveBrokerCreds('mt5')} disabled={busy} className={btnPrimary}>
                            {busy ? 'Saving...' : 'Save Credentials'}
                          </button>
                          {bc?.configured && (
                            <button onClick={() => connectBroker('mt5')} disabled={busy} className={btnSecondary}>
                              {busy ? 'Connecting...' : 'Test Connection'}
                            </button>
                          )}
                          {bc?.configured && (
                            <button onClick={() => deleteBrokerCreds('mt5')} disabled={busy} className={btnDanger}>
                              Remove
                            </button>
                          )}
                        </div>
                        {msg && <p className={`text-xs ${msg.includes('saved') || msg.includes('Connected') ? 'text-green-400' : 'text-red-400'}`}>{msg}</p>}
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          )}

          {/* ─── Notifications ─── */}
          {tab === 'notifications' && (
            <div className="space-y-6 max-w-lg">
              <h2 className="text-lg font-semibold text-foreground">Notification Channels</h2>
              <p className="text-sm text-muted-foreground">
                Configure email and/or Telegram to receive alerts for trade executions, backtest completions, and optimization results.
              </p>

              {/* ── In-app toggles ── */}
              <h3 className="text-md font-semibold text-foreground pt-2">Event Toggles</h3>
              <div className="space-y-3">
                <Toggle value={s.notifications?.backtest ?? true}
                  onChange={v => set('notifications', { ...s.notifications, backtest: v })}
                  label="Backtest completed" />
                <Toggle value={s.notifications?.optimize ?? true}
                  onChange={v => set('notifications', { ...s.notifications, optimize: v })}
                  label="Optimization completed" />
                <Toggle value={s.notifications?.trade ?? true}
                  onChange={v => set('notifications', { ...s.notifications, trade: v })}
                  label="Trade executed" />
              </div>

              {/* ── Email / SMTP ── */}
              <hr className="border-card-border" />
              <h3 className="text-md font-semibold text-foreground">Email (SMTP)</h3>
              <div className="space-y-3">
                <Field label="Recipient Email">
                  <input type="email" value={s.notification_email ?? ''}
                    onChange={e => set('notification_email', e.target.value)}
                    placeholder="you@example.com" className={inputCls} />
                </Field>
                <Field label="SMTP Host">
                  <input value={s.notification_smtp_host ?? ''}
                    onChange={e => set('notification_smtp_host', e.target.value)}
                    placeholder="smtp.gmail.com" className={inputCls} />
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="SMTP Port">
                    <input type="number" value={s.notification_smtp_port ?? 587}
                      onChange={e => set('notification_smtp_port', parseInt(e.target.value) || 587)}
                      className={inputCls} />
                  </Field>
                  <Field label="Use TLS">
                    <select value={s.notification_smtp_use_tls ? 'yes' : 'no'}
                      onChange={e => set('notification_smtp_use_tls', e.target.value === 'yes')}
                      className={selectCls}>
                      <option value="yes">Yes</option>
                      <option value="no">No</option>
                    </select>
                  </Field>
                </div>
                <Field label="SMTP Username">
                  <input value={s.notification_smtp_user ?? ''}
                    onChange={e => set('notification_smtp_user', e.target.value)}
                    placeholder="you@gmail.com" className={inputCls} />
                </Field>
                <Field label="SMTP Password">
                  <input type="password" value={notifSmtpPass}
                    onChange={e => setNotifSmtpPass(e.target.value)}
                    placeholder={s.notification_smtp_pass_set ? '••••••••  (saved)' : 'App password'}
                    className={inputCls} />
                </Field>
                <div className="flex gap-2 items-center">
                  <button disabled={notifTesting === 'email'} onClick={async () => {
                    setNotifTesting('email');
                    setNotifTestResult({});
                    try {
                      const resp = await fetch(`${API}/api/settings/test-notification`, {
                        method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() },
                        body: JSON.stringify({
                          channel: 'email',
                          email: s.notification_email,
                          smtp_host: s.notification_smtp_host,
                          smtp_port: s.notification_smtp_port,
                          smtp_user: s.notification_smtp_user,
                          smtp_pass: notifSmtpPass || undefined,
                          smtp_use_tls: s.notification_smtp_use_tls,
                        }),
                      });
                      const data = await resp.json();
                      setNotifTestResult({ email: data.email ? 'Test email sent!' : (data.email_error || 'Failed to send') });
                    } catch { setNotifTestResult({ email: 'Network error' }); }
                    setNotifTesting(null);
                  }} className={btnSecondary}>
                    {notifTesting === 'email' ? 'Sending...' : 'Send Test Email'}
                  </button>
                  {notifTestResult.email && (
                    <span className={`text-xs ${notifTestResult.email.includes('sent') ? 'text-green-400' : 'text-red-400'}`}>
                      {notifTestResult.email}
                    </span>
                  )}
                </div>
              </div>

              {/* ── Telegram ── */}
              <hr className="border-card-border" />
              <h3 className="text-md font-semibold text-foreground">Telegram</h3>
              <p className="text-xs text-muted-foreground mb-2">
                1. Message <a href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer" className="text-fa-accent hover:underline">@BotFather</a> to create a bot and get a token.
                2. Start a chat with your bot, then use <a href="https://t.me/userinfobot" target="_blank" rel="noopener noreferrer" className="text-fa-accent hover:underline">@userinfobot</a> to get your Chat ID.
              </p>
              <div className="space-y-3">
                <Field label="Bot Token">
                  <input type="password" value={notifTelegramToken}
                    onChange={e => setNotifTelegramToken(e.target.value)}
                    placeholder={s.notification_telegram_bot_token_set ? '••••••••  (saved)' : '123456:ABC-DEF...'}
                    className={inputCls} />
                </Field>
                <Field label="Chat ID">
                  <input value={s.notification_telegram_chat_id ?? ''}
                    onChange={e => set('notification_telegram_chat_id', e.target.value)}
                    placeholder="123456789" className={inputCls} />
                </Field>
                <div className="flex gap-2 items-center">
                  <button disabled={notifTesting === 'telegram'} onClick={async () => {
                    setNotifTesting('telegram');
                    setNotifTestResult({});
                    try {
                      const resp = await fetch(`${API}/api/settings/test-notification`, {
                        method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() },
                        body: JSON.stringify({
                          channel: 'telegram',
                          bot_token: notifTelegramToken || undefined,
                          chat_id: s.notification_telegram_chat_id,
                        }),
                      });
                      const data = await resp.json();
                      setNotifTestResult({ telegram: data.telegram ? 'Test message sent!' : (data.telegram_error || 'Failed to send') });
                    } catch { setNotifTestResult({ telegram: 'Network error' }); }
                    setNotifTesting(null);
                  }} className={btnSecondary}>
                    {notifTesting === 'telegram' ? 'Sending...' : 'Send Test Message'}
                  </button>
                  {notifTestResult.telegram && (
                    <span className={`text-xs ${notifTestResult.telegram.includes('sent') ? 'text-green-400' : 'text-red-400'}`}>
                      {notifTestResult.telegram}
                    </span>
                  )}
                </div>
              </div>

              {/* ── Save ── */}
              <div className="pt-4">
                <button onClick={() => {
                  const payload: Record<string, unknown> = {
                    notifications: s.notifications,
                    notification_email: s.notification_email,
                    notification_smtp_host: s.notification_smtp_host,
                    notification_smtp_port: s.notification_smtp_port,
                    notification_smtp_user: s.notification_smtp_user,
                    notification_smtp_use_tls: s.notification_smtp_use_tls,
                    notification_telegram_chat_id: s.notification_telegram_chat_id,
                  };
                  if (notifSmtpPass) payload.notification_smtp_pass = notifSmtpPass;
                  if (notifTelegramToken) payload.notification_telegram_bot_token = notifTelegramToken;
                  save(payload);
                  setNotifSmtpPass('');
                  setNotifTelegramToken('');
                }} disabled={saving} className={btnPrimary}>
                  {saving ? 'Saving...' : 'Save Notification Settings'}
                </button>
              </div>

              {/* ── Webhooks ── */}
              <hr className="border-card-border" />
              <WebhookSettingsSection />
            </div>
          )}

          {/* ─── Platform ─── */}
          {tab === 'platform' && (
            <div className="space-y-6 max-w-lg">
              <h2 className="text-lg font-semibold text-foreground">Platform Configuration</h2>

              <Field label="Session Timeout (minutes, 0 = no timeout)">
                <input type="number" min="0" value={s.session_timeout_minutes}
                  onChange={e => set('session_timeout_minutes', parseInt(e.target.value) || 0)} className={inputCls} />
              </Field>

              <div className="pt-2">
                <button onClick={() => save({
                  session_timeout_minutes: s.session_timeout_minutes,
                })} disabled={saving} className={btnPrimary}>
                  {saving ? 'Saving...' : 'Save Platform Settings'}
                </button>
              </div>

              <hr className="border-card-border" />
              <h3 className="text-md font-semibold text-foreground">Keyboard Shortcuts</h3>
              <div className="bg-input-bg rounded-lg p-4 border border-card-border text-sm space-y-2">
                {[
                  ['Ctrl + K', 'Open AI Assistant'],
                  ['Ctrl + B', 'Toggle Sidebar'],
                  ['Ctrl + Enter', 'Run Backtest'],
                  ['Ctrl + S', 'Save Current Page'],
                  ['Ctrl + /', 'Keyboard Shortcuts'],
                ].map(([key, desc]) => (
                  <div key={key} className="flex justify-between">
                    <span className="text-muted-foreground">{desc}</span>
                    <kbd className="px-2 py-0.5 rounded bg-input-bg text-foreground/80 text-xs font-mono">{key}</kbd>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Status bar */}
          {(saved || error) && (
            <div className={`mt-6 px-4 py-2 rounded-lg text-sm ${saved ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'}`}>
              {saved ? '✓ Settings saved successfully' : error}
            </div>
          )}
        </div>
      </div>

      <ChatHelpers />
    </div>
  );
}
