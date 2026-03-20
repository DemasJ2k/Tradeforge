'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import { api } from '@/lib/api';
import type { DataSource } from '@/types';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Upload,
  Trash2,
  FileSpreadsheet,
  HardDrive,
  RefreshCw,
  Loader2,
  AlertCircle,
  CheckCircle2,
  Calendar,
  Database,
} from 'lucide-react';
import { useIsMobile } from '@/hooks/useIsMobile';

interface DataSourcesPanelProps {
  datasources: DataSource[];
  onRefresh: () => void;
}

export default function DataSourcesPanel({ datasources, onRefresh }: DataSourcesPanelProps) {
  const isMobile = useIsMobile();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadSuccess, setUploadSuccess] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  // Auto-clear messages
  useEffect(() => {
    if (uploadSuccess) {
      const t = setTimeout(() => setUploadSuccess(null), 4000);
      return () => clearTimeout(t);
    }
  }, [uploadSuccess]);

  useEffect(() => {
    if (uploadError) {
      const t = setTimeout(() => setUploadError(null), 6000);
      return () => clearTimeout(t);
    }
  }, [uploadError]);

  const handleUpload = useCallback(async (file: File) => {
    if (!file.name.endsWith('.csv')) {
      setUploadError('Only CSV files are supported.');
      return;
    }
    setUploading(true);
    setUploadError(null);
    setUploadSuccess(null);
    try {
      await api.upload<DataSource>('/api/data/upload', file);
      setUploadSuccess(`Uploaded "${file.name}" successfully.`);
      onRefresh();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Upload failed';
      setUploadError(msg);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }, [onRefresh]);

  const handleDelete = useCallback(async (id: number) => {
    if (!confirm('Delete this data source? This cannot be undone.')) return;
    setDeleting(id);
    try {
      await api.delete(`/api/data/sources/${id}`);
      onRefresh();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Delete failed';
      setUploadError(msg);
    } finally {
      setDeleting(null);
    }
  }, [onRefresh]);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    onRefresh();
    setTimeout(() => setRefreshing(false), 600);
  }, [onRefresh]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleUpload(file);
  }, [handleUpload]);

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleUpload(file);
  }, [handleUpload]);

  // Compute totals
  const totalSize = datasources.reduce((acc, ds) => acc + (ds.file_size_mb || 0), 0);
  const totalRows = datasources.reduce((acc, ds) => acc + (ds.row_count || 0), 0);

  const formatDate = (d: string | null | undefined) => {
    if (!d) return '--';
    try {
      return new Date(d).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
    } catch {
      return d;
    }
  };

  const formatSize = (mb: number) => {
    if (mb < 0.01) return '<0.01 MB';
    if (mb < 1) return `${mb.toFixed(2)} MB`;
    return `${mb.toFixed(1)} MB`;
  };

  return (
    <div className="flex flex-col h-full overflow-auto p-4 md:p-6 space-y-6">
      {/* Upload Area */}
      <div
        className={`
          relative border-2 border-dashed rounded-xl p-8 text-center transition-colors cursor-pointer
          ${dragOver
            ? 'border-accent bg-accent/10'
            : 'border-card-border hover:border-muted-foreground/40 bg-card-bg/30'
          }
          ${uploading ? 'pointer-events-none opacity-60' : ''}
        `}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => !uploading && fileInputRef.current?.click()}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv"
          className="hidden"
          onChange={handleFileChange}
        />
        {uploading ? (
          <div className="flex flex-col items-center gap-3">
            <Loader2 className="w-10 h-10 animate-spin text-accent" />
            <p className="text-sm text-muted-foreground">Uploading and parsing CSV...</p>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3">
            <Upload className="w-10 h-10 text-muted-foreground/50" />
            <div>
              <p className="text-sm font-medium text-foreground">
                Drop a CSV file here, or click to browse
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                OHLCV format with datetime column. Supports MT5, TradingView, and standard CSV exports.
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Status Messages */}
      {uploadSuccess && (
        <div className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-green-500/10 border border-green-500/30 text-green-400 text-sm">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          {uploadSuccess}
        </div>
      )}
      {uploadError && (
        <div className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {uploadError}
        </div>
      )}

      {/* Summary Bar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Database className="w-4 h-4" />
            <span className="font-medium text-foreground">{datasources.length}</span> source{datasources.length !== 1 ? 's' : ''}
          </div>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <HardDrive className="w-4 h-4" />
            {formatSize(totalSize)}
          </div>
          <div className="hidden sm:flex items-center gap-2 text-sm text-muted-foreground">
            <FileSpreadsheet className="w-4 h-4" />
            {totalRows.toLocaleString()} rows
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleRefresh}
          disabled={refreshing}
          className="gap-1.5"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          {!isMobile && 'Refresh'}
        </Button>
      </div>

      {/* Data Sources List */}
      {datasources.length === 0 ? (
        <div className="flex-1 flex items-center justify-center py-16">
          <div className="text-center space-y-3">
            <FileSpreadsheet className="w-12 h-12 mx-auto text-muted-foreground/30" />
            <h3 className="text-lg font-medium text-muted-foreground">No Data Sources</h3>
            <p className="text-sm text-muted-foreground/60 max-w-sm">
              Upload a CSV file above to get started. Your data will be parsed and available for backtesting.
            </p>
          </div>
        </div>
      ) : isMobile ? (
        /* Mobile: Card layout */
        <div className="space-y-3">
          {datasources.map((ds) => (
            <div
              key={ds.id}
              className="rounded-lg border border-card-border bg-card-bg p-4 space-y-3"
            >
              <div className="flex items-start justify-between">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-foreground">{ds.symbol || '--'}</span>
                    <Badge variant="outline" className="text-xs">{ds.timeframe || '--'}</Badge>
                    <Badge variant="secondary" className="text-xs capitalize">{ds.source_type || 'csv'}</Badge>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1 truncate">{ds.filename}</p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleDelete(ds.id)}
                  disabled={deleting === ds.id}
                  className="shrink-0 text-red-400 hover:text-red-300 hover:bg-red-500/10 border-red-500/30"
                >
                  {deleting === ds.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                </Button>
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                <div className="flex items-center gap-1.5">
                  <FileSpreadsheet className="w-3.5 h-3.5" />
                  {(ds.row_count || 0).toLocaleString()} rows
                </div>
                <div className="flex items-center gap-1.5">
                  <HardDrive className="w-3.5 h-3.5" />
                  {formatSize(ds.file_size_mb || 0)}
                </div>
                <div className="flex items-center gap-1.5 col-span-2">
                  <Calendar className="w-3.5 h-3.5" />
                  {formatDate(ds.date_from)} &mdash; {formatDate(ds.date_to)}
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        /* Desktop: Table layout */
        <div className="rounded-lg border border-card-border overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-card-bg/80 border-b border-card-border text-muted-foreground">
                <th className="text-left px-4 py-3 font-medium">Symbol</th>
                <th className="text-left px-4 py-3 font-medium">Timeframe</th>
                <th className="text-left px-4 py-3 font-medium">Source</th>
                <th className="text-right px-4 py-3 font-medium">Rows</th>
                <th className="text-left px-4 py-3 font-medium">Date Range</th>
                <th className="text-right px-4 py-3 font-medium">Size</th>
                <th className="text-left px-4 py-3 font-medium">Filename</th>
                <th className="text-right px-4 py-3 font-medium w-20"></th>
              </tr>
            </thead>
            <tbody>
              {datasources.map((ds) => (
                <tr
                  key={ds.id}
                  className="border-b border-card-border/50 hover:bg-card-bg/40 transition-colors"
                >
                  <td className="px-4 py-3 font-semibold text-foreground">{ds.symbol || '--'}</td>
                  <td className="px-4 py-3">
                    <Badge variant="outline" className="text-xs">{ds.timeframe || '--'}</Badge>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant="secondary" className="text-xs capitalize">{ds.source_type || 'csv'}</Badge>
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-muted-foreground">
                    {(ds.row_count || 0).toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground text-xs">
                    {formatDate(ds.date_from)} &mdash; {formatDate(ds.date_to)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-muted-foreground">
                    {formatSize(ds.file_size_mb || 0)}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground truncate max-w-[200px]" title={ds.filename}>
                    {ds.filename}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleDelete(ds.id)}
                      disabled={deleting === ds.id}
                      className="h-8 w-8 p-0 text-red-400 hover:text-red-300 hover:bg-red-500/10 border-red-500/30"
                    >
                      {deleting === ds.id
                        ? <Loader2 className="w-4 h-4 animate-spin" />
                        : <Trash2 className="w-4 h-4" />
                      }
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
