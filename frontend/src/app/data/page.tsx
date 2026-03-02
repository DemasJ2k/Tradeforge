"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { useDropzone } from "react-dropzone";
import { api } from "@/lib/api";
import type { DataSource, DataSourceList } from "@/types";
import ChatHelpers from "@/components/ChatHelpers";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Upload, Database, Download, Trash2, ChevronDown, ChevronUp, Info } from "lucide-react";

const BROKERS = [
  { id: "mt5", label: "MetaTrader 5" },
  { id: "oanda", label: "Oanda" },
  { id: "coinbase", label: "Coinbase" },
  { id: "tradovate", label: "Tradovate" },
];

const TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];

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
  const [expandedId, setExpandedId] = useState<number | null>(null);

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
        <Button onClick={() => setShowFetchModal(true)} className="gap-1.5">
          <Download className="h-4 w-4" /> Fetch from Broker
        </Button>
      </div>

      {/* Fetch from Broker modal */}
      <Dialog open={showFetchModal} onOpenChange={(open) => { if (!open) { setShowFetchModal(false); setFetchMsg(""); } }}>
        <DialogContent className="bg-card-bg border-card-border">
          <DialogHeader>
            <DialogTitle>Fetch from Broker</DialogTitle>
            <DialogDescription>Download historical candle data from a broker. Save API credentials in Settings → Brokers first.</DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div>
              <Label className="text-xs text-muted-foreground mb-1">Broker</Label>
              <select value={fetchBroker} onChange={e => setFetchBroker(e.target.value)}
                className="w-full bg-input-bg border border-card-border rounded-lg px-3 py-2 text-foreground text-sm focus:border-accent focus:outline-none">
                {BROKERS.map(b => (
                  <option key={b.id} value={b.id}>{b.label}</option>
                ))}
              </select>
            </div>

            <div>
              <Label className="text-xs text-muted-foreground mb-1">Symbol</Label>
              <Input type="text" value={fetchSymbol} onChange={e => setFetchSymbol(e.target.value)}
                placeholder="e.g. XAUUSD, EURUSD, NAS100" />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-xs text-muted-foreground mb-1">Timeframe</Label>
                <select value={fetchTimeframe} onChange={e => setFetchTimeframe(e.target.value)}
                  className="w-full bg-input-bg border border-card-border rounded-lg px-3 py-2 text-foreground text-sm focus:border-accent focus:outline-none">
                  {TIMEFRAMES.map(tf => (
                    <option key={tf} value={tf}>{tf}</option>
                  ))}
                </select>
              </div>
              <div>
                <Label className="text-xs text-muted-foreground mb-1">Bars</Label>
                <Input type="number" value={fetchBars} onChange={e => setFetchBars(e.target.value)}
                  min={100} max={100000} />
              </div>
            </div>

            <div className="flex gap-3 pt-2">
              <Button onClick={fetchFromBroker} disabled={fetching || !fetchSymbol}>
                {fetching ? "Fetching..." : "Fetch Data"}
              </Button>
              <Button variant="outline" onClick={() => { setShowFetchModal(false); setFetchMsg(""); }}>
                Cancel
              </Button>
            </div>

            {fetchMsg && (
              <p className={`text-sm ${fetchMsg.includes("success") ? "text-green-400" : "text-red-400"}`}>
                {fetchMsg}
              </p>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Upload zone */}
      <Card className="bg-card-bg border-card-border border-dashed border-2 hover:border-accent/40 transition-colors cursor-pointer"
        {...getRootProps()}>
        <CardContent className="p-10 text-center">
          <input {...getInputProps()} />
          {uploading ? (
            <p className="text-sm text-accent">Uploading...</p>
          ) : isDragActive ? (
            <p className="text-sm text-accent">Drop CSV files here</p>
          ) : (
            <div>
              <Upload className="h-8 w-8 text-muted-foreground/30 mx-auto mb-3" />
              <p className="text-sm text-foreground mb-1">
                Drag & drop CSV files here, or click to browse
              </p>
              <p className="text-xs text-muted-foreground">
                Supports MT5 export, generic OHLCV, and tick data formats
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {error && (
        <p className="text-sm text-danger">{error}</p>
      )}

      {/* Data sources table */}
      {sources.length > 0 ? (
        <Card className="bg-card-bg border-card-border overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="border-card-border">
                <TableHead>Symbol</TableHead>
                <TableHead>Timeframe</TableHead>
                <TableHead>Rows</TableHead>
                <TableHead>Date Range</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Size</TableHead>
                <TableHead>File</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sources.map((s) => (
                <Fragment key={s.id}>
                <TableRow
                  className="border-card-border/50 hover:bg-sidebar-hover cursor-pointer"
                  onClick={() => setExpandedId(expandedId === s.id ? null : s.id)}
                >
                  <TableCell className="font-medium text-accent">
                    <div className="flex items-center gap-1.5">
                      {expandedId === s.id ? <ChevronUp className="h-3 w-3 text-muted-foreground" /> : <ChevronDown className="h-3 w-3 text-muted-foreground" />}
                      {s.symbol || "—"}
                    </div>
                  </TableCell>
                  <TableCell>{s.timeframe || "—"}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {s.row_count.toLocaleString()}
                  </TableCell>
                  <TableCell className="text-muted-foreground text-xs">
                    {s.date_from} — {s.date_to}
                  </TableCell>
                  <TableCell>
                    {s.source_type === "broker" ? (
                      <Badge variant="secondary" className="bg-blue-900/30 text-fa-accent">
                        {s.broker_name?.toUpperCase() || "Broker"}
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="text-muted-foreground">
                        Upload
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">{s.file_size_mb}MB</TableCell>
                  <TableCell className="text-muted-foreground text-xs truncate max-w-48">
                    {s.filename}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={(e) => { e.stopPropagation(); deleteSource(s.id); }}
                      className="text-muted-foreground hover:text-danger h-7 gap-1"
                    >
                      <Trash2 className="h-3.5 w-3.5" /> Delete
                    </Button>
                  </TableCell>
                </TableRow>
                {expandedId === s.id && (
                  <TableRow key={`${s.id}-profile`} className="border-card-border/30 bg-card-bg/50">
                    <TableCell colSpan={8} className="py-3 px-6">
                      <div className="flex items-center gap-2 mb-2">
                        <Info className="h-3.5 w-3.5 text-accent" />
                        <span className="text-xs font-medium text-accent uppercase tracking-wide">Instrument Profile</span>
                      </div>
                      <div className="grid grid-cols-3 sm:grid-cols-6 gap-4">
                        <div>
                          <div className="text-[10px] text-muted-foreground uppercase tracking-wide">Pip Value</div>
                          <div className="text-sm font-medium">{s.pip_value ?? "—"}</div>
                        </div>
                        <div>
                          <div className="text-[10px] text-muted-foreground uppercase tracking-wide">Point Value</div>
                          <div className="text-sm font-medium">{s.point_value ?? "—"}</div>
                        </div>
                        <div>
                          <div className="text-[10px] text-muted-foreground uppercase tracking-wide">Lot Size</div>
                          <div className="text-sm font-medium">{s.lot_size ?? "—"}</div>
                        </div>
                        <div>
                          <div className="text-[10px] text-muted-foreground uppercase tracking-wide">Spread</div>
                          <div className="text-sm font-medium">{s.default_spread ?? "—"}</div>
                        </div>
                        <div>
                          <div className="text-[10px] text-muted-foreground uppercase tracking-wide">Commission</div>
                          <div className="text-sm font-medium">{s.default_commission ?? "—"} <span className="text-muted-foreground text-[10px]">{s.commission_model || ""}</span></div>
                        </div>
                        <div>
                          <div className="text-[10px] text-muted-foreground uppercase tracking-wide">JPY Pair</div>
                          <div className="text-sm font-medium">{s.is_jpy_pair ? "Yes" : "No"}</div>
                        </div>
                      </div>
                    </TableCell>
                  </TableRow>
                )}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        </Card>
      ) : (
        <Card className="bg-card-bg border-card-border">
          <CardContent className="flex flex-col items-center justify-center p-16 text-center">
            <Database className="h-10 w-10 text-muted-foreground/30 mb-4" />
            <h3 className="text-lg font-medium mb-2">No Data Sources Yet</h3>
            <p className="text-sm text-muted-foreground mb-6 max-w-md">
              Upload a CSV file above or fetch from a broker to get started with backtesting and ML.
            </p>
            <div className="flex items-center gap-3">
              <Button variant="outline" onClick={() => setShowFetchModal(true)} className="gap-1.5">
                <Download className="h-4 w-4" /> Fetch from Broker
              </Button>
              <Button onClick={() => document.querySelector<HTMLInputElement>('input[type=file]')?.click()} className="gap-1.5">
                <Upload className="h-4 w-4" /> Upload CSV
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <ChatHelpers />
    </div>
  );
}
