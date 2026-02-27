"use client";

import { useCallback, useEffect, useState } from "react";
import { useDropzone } from "react-dropzone";
import { api } from "@/lib/api";
import type { DataSource, DataSourceList } from "@/types";
import ChatHelpers from "@/components/ChatHelpers";

const BROKERS = [
  { id: "mt5", label: "MetaTrader 5" },
  { id: "oanda", label: "Oanda" },
  { id: "coinbase", label: "Coinbase" },
  { id: "tradovate", label: "Tradovate" },
];

const TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];

const inputCls =
  "w-full bg-[#1a1f2e] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-blue-500 focus:outline-none";
const btnPrimary =
  "px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors disabled:opacity-40";
const btnSecondary =
  "px-4 py-2 rounded-lg bg-gray-700 hover:bg-gray-600 text-gray-200 text-sm font-medium transition-colors";

export default function DataPage() {
  const [sources, setSources] = useState<DataSource[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

  // Fetch from broker modal state
  const [showFetchModal, setShowFetchModal] = useState(false);
  const [fetchBroker, setFetchBroker] = useState("mt5");
  const [fetchSymbol, setFetchSymbol] = useState("XAUUSD");
  const [fetchTimeframe, setFetchTimeframe] = useState("H1");
  const [fetchBars, setFetchBars] = useState("5000");
  const [fetching, setFetching] = useState(false);
  const [fetchMsg, setFetchMsg] = useState("");

  const loadSources = useCallback(async () => {
    try {
      const data = await api.get<DataSourceList>("/api/data/sources");
      setSources(data.items);
    } catch {
      // ignore on first load
    }
  }, []);

  useEffect(() => {
    loadSources();
  }, [loadSources]);

  const onDrop = useCallback(
    async (files: File[]) => {
      setError("");
      setUploading(true);
      try {
        for (const file of files) {
          await api.upload<DataSource>("/api/data/upload", file);
        }
        await loadSources();
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "Upload failed");
      } finally {
        setUploading(false);
      }
    },
    [loadSources]
  );

  const deleteSource = async (id: number) => {
    try {
      await api.delete(`/api/data/sources/${id}`);
      setSources((prev) => prev.filter((s) => s.id !== id));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  const fetchFromBroker = async () => {
    setFetching(true);
    setFetchMsg("");
    try {
      await api.post<DataSource>("/api/data/fetch-broker", {
        broker: fetchBroker,
        symbol: fetchSymbol.toUpperCase(),
        timeframe: fetchTimeframe,
        bars: parseInt(fetchBars) || 5000,
      });
      setFetchMsg("Data fetched successfully!");
      await loadSources();
      setTimeout(() => {
        setShowFetchModal(false);
        setFetchMsg("");
      }, 1500);
    } catch (err: unknown) {
      setFetchMsg(err instanceof Error ? err.message : "Fetch failed");
    } finally {
      setFetching(false);
    }
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "text/csv": [".csv"] },
    multiple: true,
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Data Sources</h2>
        <button onClick={() => setShowFetchModal(true)} className={btnPrimary}>
          Fetch from Broker
        </button>
      </div>

      {/* Fetch from Broker modal */}
      {showFetchModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="w-full max-w-md bg-[#151923] rounded-xl border border-gray-800 p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-white">Fetch from Broker</h3>
              <button onClick={() => { setShowFetchModal(false); setFetchMsg(""); }}
                className="text-gray-400 hover:text-white text-xl leading-none">&times;</button>
            </div>
            <p className="text-sm text-gray-400">Download historical candle data from your connected broker.</p>

            <div>
              <label className="block text-xs text-gray-400 mb-1">Broker</label>
              <select value={fetchBroker} onChange={e => setFetchBroker(e.target.value)} className={inputCls}>
                {BROKERS.map(b => (
                  <option key={b.id} value={b.id}>{b.label}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">Symbol</label>
              <input type="text" value={fetchSymbol} onChange={e => setFetchSymbol(e.target.value)}
                placeholder="e.g. XAUUSD, EURUSD, NAS100" className={inputCls} />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-gray-400 mb-1">Timeframe</label>
                <select value={fetchTimeframe} onChange={e => setFetchTimeframe(e.target.value)} className={inputCls}>
                  {TIMEFRAMES.map(tf => (
                    <option key={tf} value={tf}>{tf}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">Bars</label>
                <input type="number" value={fetchBars} onChange={e => setFetchBars(e.target.value)}
                  min="100" max="100000" className={inputCls} />
              </div>
            </div>

            <div className="flex gap-3 pt-2">
              <button onClick={fetchFromBroker} disabled={fetching || !fetchSymbol} className={btnPrimary}>
                {fetching ? "Fetching..." : "Fetch Data"}
              </button>
              <button onClick={() => { setShowFetchModal(false); setFetchMsg(""); }} className={btnSecondary}>
                Cancel
              </button>
            </div>

            {fetchMsg && (
              <p className={`text-sm ${fetchMsg.includes("success") ? "text-green-400" : "text-red-400"}`}>
                {fetchMsg}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Upload zone */}
      <div
        {...getRootProps()}
        className={`rounded-xl border-2 border-dashed p-10 text-center cursor-pointer transition-colors ${
          isDragActive
            ? "border-accent bg-accent/5"
            : "border-card-border hover:border-muted"
        }`}
      >
        <input {...getInputProps()} />
        {uploading ? (
          <p className="text-sm text-accent">Uploading...</p>
        ) : isDragActive ? (
          <p className="text-sm text-accent">Drop CSV files here</p>
        ) : (
          <div>
            <p className="text-sm text-foreground mb-1">
              Drag & drop CSV files here, or click to browse
            </p>
            <p className="text-xs text-muted">
              Supports MT5 export, generic OHLCV, and tick data formats
            </p>
          </div>
        )}
      </div>

      {error && (
        <p className="text-sm text-danger">{error}</p>
      )}

      {/* Data sources table */}
      {sources.length > 0 ? (
        <div className="rounded-xl border border-card-border bg-card-bg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-card-border text-left text-xs text-muted">
                <th className="px-4 py-3 font-medium">Symbol</th>
                <th className="px-4 py-3 font-medium">Timeframe</th>
                <th className="px-4 py-3 font-medium">Rows</th>
                <th className="px-4 py-3 font-medium">Date Range</th>
                <th className="px-4 py-3 font-medium">Source</th>
                <th className="px-4 py-3 font-medium">Size</th>
                <th className="px-4 py-3 font-medium">File</th>
                <th className="px-4 py-3 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {sources.map((s) => (
                <tr
                  key={s.id}
                  className="border-b border-card-border/50 hover:bg-sidebar-hover transition-colors"
                >
                  <td className="px-4 py-3 font-medium text-accent">
                    {s.symbol || "—"}
                  </td>
                  <td className="px-4 py-3">{s.timeframe || "—"}</td>
                  <td className="px-4 py-3 text-muted">
                    {s.row_count.toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-muted text-xs">
                    {s.date_from} — {s.date_to}
                  </td>
                  <td className="px-4 py-3">
                    {s.source_type === "broker" ? (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-blue-900/30 text-blue-400">
                        {s.broker_name?.toUpperCase() || "Broker"}
                      </span>
                    ) : (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-gray-700/50 text-gray-400">
                        Upload
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-muted">{s.file_size_mb}MB</td>
                  <td className="px-4 py-3 text-muted text-xs truncate max-w-48">
                    {s.filename}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => deleteSource(s.id)}
                      className="text-xs text-muted hover:text-danger transition-colors"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="rounded-xl border border-card-border bg-card-bg p-8 text-center">
          <p className="text-sm text-muted">
            No data sources yet. Upload a CSV file or fetch from a broker to get started.
          </p>
        </div>
      )}

      <ChatHelpers />
    </div>
  );
}
