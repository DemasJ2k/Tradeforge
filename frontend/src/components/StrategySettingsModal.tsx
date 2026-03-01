"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import type { Strategy, SettingsSchemaEntry } from "@/types";

interface Props {
  strategy: Strategy;
  onClose: () => void;
  onSaved: (updated: Strategy) => void;
}

export default function StrategySettingsModal({ strategy, onClose, onSaved }: Props) {
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    // Initialize with current values, falling back to schema defaults
    const init: Record<string, unknown> = {};
    for (const entry of strategy.settings_schema || []) {
      init[entry.key] = strategy.settings_values?.[entry.key] ?? entry.default ?? "";
    }
    setValues(init);
  }, [strategy]);

  const updateValue = (key: string, val: unknown) => {
    setValues((prev) => ({ ...prev, [key]: val }));
  };

  const handleSave = async () => {
    setSaving(true);
    setError("");
    try {
      const resp = await api.put<Strategy>(`/api/strategies/${strategy.id}/settings`, {
        settings_values: values,
      });
      onSaved(resp);
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    const defaults: Record<string, unknown> = {};
    for (const entry of strategy.settings_schema || []) {
      defaults[entry.key] = entry.default ?? "";
    }
    setValues(defaults);
  };

  const schema = strategy.settings_schema || [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-xl border border-card-border bg-card-bg shadow-2xl max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-card-border px-5 py-3">
          <div>
            <h2 className="text-sm font-semibold">{strategy.name}</h2>
            <span className="text-xs text-muted">
              {strategy.strategy_type === "python" ? "Python" :
               strategy.strategy_type === "json" ? "JSON" :
               strategy.strategy_type === "pinescript" ? "Pine Script" : "Strategy"} Settings
            </span>
          </div>
          <button onClick={onClose} className="text-muted hover:text-foreground transition-colors text-lg leading-none">&times;</button>
        </div>

        {/* Body — scrollable */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {schema.length === 0 ? (
            <p className="text-sm text-muted">No configurable settings detected for this strategy.</p>
          ) : (
            schema.map((entry) => (
              <SettingsField
                key={entry.key}
                entry={entry}
                value={values[entry.key]}
                onChange={(val) => updateValue(entry.key, val)}
              />
            ))
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-card-border px-5 py-3 flex items-center justify-between">
          <button
            onClick={handleReset}
            className="text-xs text-muted hover:text-foreground transition-colors"
          >
            Reset to Defaults
          </button>
          <div className="flex items-center gap-2">
            {error && <span className="text-xs text-danger mr-2">{error}</span>}
            <button
              onClick={onClose}
              className="rounded-lg border border-card-border px-4 py-1.5 text-sm text-muted hover:text-foreground transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="rounded-lg bg-accent px-4 py-1.5 text-sm font-medium text-black hover:brightness-110 transition disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}


function SettingsField({
  entry,
  value,
  onChange,
}: {
  entry: SettingsSchemaEntry;
  value: unknown;
  onChange: (val: unknown) => void;
}) {
  const inputClass =
    "w-full rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm outline-none focus:border-accent transition-colors";

  if (entry.type === "bool") {
    return (
      <label className="flex items-center justify-between cursor-pointer group">
        <div>
          <span className="text-sm">{entry.label}</span>
          {entry.key && <span className="text-xs text-muted ml-2 opacity-0 group-hover:opacity-100 transition-opacity">{entry.key}</span>}
        </div>
        <div
          className={`relative w-10 h-5 rounded-full transition-colors ${value ? "bg-accent" : "bg-card-border"}`}
          onClick={() => onChange(!value)}
        >
          <div
            className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${value ? "translate-x-5" : "translate-x-0.5"}`}
          />
        </div>
      </label>
    );
  }

  if (entry.type === "select" && entry.options) {
    return (
      <div>
        <label className="block text-xs text-muted mb-1">{entry.label}</label>
        <select
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
          className={inputClass}
        >
          {entry.options.map((opt) => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
      </div>
    );
  }

  if (entry.type === "int" || entry.type === "float") {
    const numValue = typeof value === "number" ? value : Number(value) || 0;
    const hasRange = entry.min !== undefined && entry.max !== undefined;

    return (
      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="text-xs text-muted">{entry.label}</label>
          <span className="text-xs font-mono text-accent">
            {entry.type === "int" ? Math.round(numValue) : numValue.toFixed(2)}
          </span>
        </div>
        {hasRange ? (
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted w-8 text-right">{entry.min}</span>
            <input
              type="range"
              min={entry.min}
              max={entry.max}
              step={entry.step ?? (entry.type === "int" ? 1 : 0.01)}
              value={numValue}
              onChange={(e) => {
                const v = Number(e.target.value);
                onChange(entry.type === "int" ? Math.round(v) : v);
              }}
              className="flex-1 accent-accent h-1.5"
            />
            <span className="text-xs text-muted w-8">{entry.max}</span>
          </div>
        ) : (
          <input
            type="number"
            value={numValue}
            step={entry.step ?? (entry.type === "int" ? 1 : 0.01)}
            onChange={(e) => {
              const v = Number(e.target.value);
              onChange(entry.type === "int" ? Math.round(v) : v);
            }}
            className={inputClass}
          />
        )}
      </div>
    );
  }

  // String fallback
  return (
    <div>
      <label className="block text-xs text-muted mb-1">{entry.label}</label>
      <input
        type="text"
        value={String(value ?? "")}
        onChange={(e) => onChange(e.target.value)}
        className={inputClass}
      />
    </div>
  );
}
