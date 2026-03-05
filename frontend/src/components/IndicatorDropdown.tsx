"use client";

import { useState, useRef, useEffect } from "react";
import { ChevronDown, X, Settings2 } from "lucide-react";
import {
  OVERLAYS,
  OSCILLATORS,
  type IndicatorDef,
  type IndicatorParam,
} from "@/lib/indicatorRegistry";

export interface ActiveIndicator {
  id: string;
  params: Record<string, number>;
}

interface Props {
  /** Slot label, e.g. "Indicator 1" */
  label: string;
  /** Currently selected indicator (null = none) */
  value: ActiveIndicator | null;
  /** Called when user picks or clears an indicator */
  onChange: (value: ActiveIndicator | null) => void;
}

export default function IndicatorDropdown({ label, value, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const [showParams, setShowParams] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
        setShowParams(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const allIndicators = [...OVERLAYS, ...OSCILLATORS];
  const selected = value ? allIndicators.find((i) => i.id === value.id) : null;

  const handleSelect = (def: IndicatorDef) => {
    const params: Record<string, number> = {};
    for (const p of def.params) params[p.key] = p.default;
    onChange({ id: def.id, params });
    setOpen(false);
  };

  const handleClear = (e: React.MouseEvent) => {
    e.stopPropagation();
    onChange(null);
    setShowParams(false);
  };

  const handleParamChange = (key: string, val: number) => {
    if (!value) return;
    onChange({ ...value, params: { ...value.params, [key]: val } });
  };

  const toggleParams = (e: React.MouseEvent) => {
    e.stopPropagation();
    setShowParams((v) => !v);
  };

  return (
    <div ref={wrapperRef} className="relative inline-flex items-center gap-1">
      {/* Main button */}
      <button
        onClick={() => { setOpen((v) => !v); setShowParams(false); }}
        className={`flex items-center gap-1 px-2 py-0.5 text-xs rounded border transition-colors ${
          selected
            ? "bg-accent/15 border-accent/40 text-accent"
            : "border-card-border text-muted-foreground hover:text-foreground"
        }`}
      >
        <span className="max-w-[90px] truncate">
          {selected ? selected.shortName : label}
        </span>
        {selected ? (
          <X className="h-3 w-3 opacity-60 hover:opacity-100" onClick={handleClear} />
        ) : (
          <ChevronDown className="h-3 w-3 opacity-60" />
        )}
      </button>

      {/* Params gear (when indicator is selected and has params) */}
      {selected && selected.params.length > 0 && (
        <button
          onClick={toggleParams}
          className={`p-0.5 rounded transition-colors ${
            showParams ? "text-accent" : "text-muted-foreground hover:text-foreground"
          }`}
          title="Settings"
        >
          <Settings2 className="h-3 w-3" />
        </button>
      )}

      {/* Dropdown menu */}
      {open && (
        <div className="absolute left-0 top-full mt-1 z-50 w-52 rounded-lg border border-card-border bg-card-bg shadow-xl overflow-hidden">
          <div className="max-h-64 overflow-y-auto py-1">
            {/* None option */}
            <button
              onClick={() => { onChange(null); setOpen(false); }}
              className="w-full text-left px-3 py-1.5 text-xs text-muted-foreground hover:bg-background/60 transition-colors"
            >
              None
            </button>

            {/* Overlays */}
            <div className="px-3 pt-2 pb-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">
              Overlays
            </div>
            {OVERLAYS.map((ind) => (
              <button
                key={ind.id}
                onClick={() => handleSelect(ind)}
                className={`w-full text-left px-3 py-1.5 text-xs transition-colors flex items-center gap-2 ${
                  value?.id === ind.id
                    ? "bg-accent/10 text-accent"
                    : "text-foreground hover:bg-background/60"
                }`}
              >
                <span
                  className="inline-block h-2 w-2 rounded-sm flex-shrink-0"
                  style={{ backgroundColor: ind.outputs[0].color }}
                />
                {ind.name}
              </button>
            ))}

            {/* Oscillators */}
            <div className="px-3 pt-2 pb-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">
              Oscillators
            </div>
            {OSCILLATORS.map((ind) => (
              <button
                key={ind.id}
                onClick={() => handleSelect(ind)}
                className={`w-full text-left px-3 py-1.5 text-xs transition-colors flex items-center gap-2 ${
                  value?.id === ind.id
                    ? "bg-accent/10 text-accent"
                    : "text-foreground hover:bg-background/60"
                }`}
              >
                <span
                  className="inline-block h-2 w-2 rounded-sm flex-shrink-0"
                  style={{ backgroundColor: ind.outputs[0].color }}
                />
                {ind.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Params panel (floating below) */}
      {showParams && selected && selected.params.length > 0 && (
        <div className="absolute left-0 top-full mt-1 z-50 w-52 rounded-lg border border-card-border bg-card-bg shadow-xl p-3 space-y-2">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60 mb-1">
            {selected.shortName} Settings
          </div>
          {selected.params.map((p: IndicatorParam) => (
            <div key={p.key} className="flex items-center gap-2">
              <label className="text-xs text-muted-foreground min-w-[60px]">{p.label}</label>
              <input
                type="number"
                value={value?.params[p.key] ?? p.default}
                min={p.min}
                max={p.max}
                step={p.step ?? 1}
                onChange={(e) => handleParamChange(p.key, Number(e.target.value))}
                className="w-20 rounded border border-card-border bg-background px-1.5 py-0.5 text-xs text-foreground focus:outline-none focus:border-accent"
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
