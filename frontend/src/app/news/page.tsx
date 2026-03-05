"use client";

import { useCallback, useEffect, useState, useMemo } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import ChatHelpers from "@/components/ChatHelpers";
import {
  Newspaper,
  Calendar,
  TrendingUp,
  TrendingDown,
  Minus,
  RefreshCw,
  ExternalLink,
  Clock,
  Globe,
  Search,
  Loader2,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  BarChart3,
  Zap,
  Filter,
  X,
  Bot,
  Sparkles,
  Target,
  ShieldAlert,
  ArrowUpRight,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface EconomicEvent {
  event: string;
  country: string;
  currency: string;
  impact: "high" | "medium" | "low";
  event_time: string;
  actual: number | null;
  estimate: number | null;
  prev: number | null;
  unit: string;
  source: string;
}

interface NewsArticle {
  id?: number;
  external_id: string;
  headline: string;
  summary: string;
  source: string;
  url: string;
  image_url: string;
  category: string;
  published_at: string;
  related_symbols: string;
  sentiment_score: number | null;
  sentiment_label: string | null;
}

interface ArticleDetail extends NewsArticle {
  id: number;
  ai_analysis: AIAnalysis | null;
  fetched_at: string | null;
}

interface AIAnalysis {
  key_points: string[];
  impact_assessment: string;
  affected_symbols: string[];
  recommendation: string;
  confidence: number;
  reasoning: string;
}

interface SentimentData {
  score: number;
  label: string;
  articles: number;
  symbol: string;
  bullish_pct?: number;
  bearish_pct?: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function timeAgo(isoStr: string): string {
  const diff = Date.now() - new Date(isoStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function timeUntil(isoStr: string): string {
  const diff = new Date(isoStr).getTime() - Date.now();
  if (diff < 0) return "released";
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `in ${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `in ${hrs}h ${mins % 60}m`;
  const days = Math.floor(hrs / 24);
  return `in ${days}d`;
}

function formatEventDate(isoStr: string): string {
  try {
    const d = new Date(isoStr);
    return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  } catch { return ""; }
}

function formatEventTime(isoStr: string): string {
  try {
    const d = new Date(isoStr);
    return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: true });
  } catch { return ""; }
}

const IMPACT_COLORS = {
  high: "bg-red-500/15 text-red-400 border-red-500/30",
  medium: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  low: "bg-blue-500/10 text-blue-400 border-blue-500/30",
};

const IMPACT_DOT = {
  high: "bg-red-500",
  medium: "bg-amber-500",
  low: "bg-blue-500",
};

// ---------------------------------------------------------------------------
// Component: Economic Calendar
// ---------------------------------------------------------------------------

function EconomicCalendar({
  events,
  loading,
}: {
  events: EconomicEvent[];
  loading: boolean;
}) {
  const [impactFilter, setImpactFilter] = useState<string>("all");
  const [currencyFilter, setCurrencyFilter] = useState<string>("");
  const [expandedDates, setExpandedDates] = useState<Set<string>>(new Set());

  // Group events by date
  const grouped = useMemo(() => {
    let filtered = events;
    if (impactFilter !== "all") {
      filtered = filtered.filter((e) => e.impact === impactFilter);
    }
    if (currencyFilter) {
      filtered = filtered.filter((e) =>
        e.currency.toUpperCase().includes(currencyFilter.toUpperCase())
      );
    }

    const groups = new Map<string, EconomicEvent[]>();
    for (const e of filtered) {
      const dateKey = formatEventDate(e.event_time);
      if (!groups.has(dateKey)) groups.set(dateKey, []);
      groups.get(dateKey)!.push(e);
    }
    return groups;
  }, [events, impactFilter, currencyFilter]);

  // Auto-expand today and tomorrow
  useEffect(() => {
    const today = formatEventDate(new Date().toISOString());
    const tomorrow = formatEventDate(new Date(Date.now() + 86400000).toISOString());
    setExpandedDates(new Set([today, tomorrow]));
  }, []);

  const toggleDate = (d: string) => {
    setExpandedDates((prev) => {
      const next = new Set(prev);
      if (next.has(d)) next.delete(d);
      else next.add(d);
      return next;
    });
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-accent" />
        <span className="ml-2 text-sm text-muted-foreground">Loading calendar...</span>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <Filter className="h-3.5 w-3.5 text-muted-foreground" />
        <div className="flex gap-1">
          {["all", "high", "medium", "low"].map((level) => (
            <Button
              key={level}
              variant={impactFilter === level ? "default" : "outline"}
              size="sm"
              onClick={() => setImpactFilter(level)}
              className={`h-7 text-[11px] ${
                impactFilter === level ? "bg-accent text-black" : ""
              }`}
            >
              {level === "all" ? "All" : (
                <span className="flex items-center gap-1">
                  <span className={`w-2 h-2 rounded-full ${IMPACT_DOT[level as keyof typeof IMPACT_DOT]}`} />
                  {level.charAt(0).toUpperCase() + level.slice(1)}
                </span>
              )}
            </Button>
          ))}
        </div>
        <Input
          value={currencyFilter}
          onChange={(e) => setCurrencyFilter(e.target.value)}
          placeholder="Currency (USD, EUR...)"
          className="h-7 w-32 text-xs bg-card-bg border-card-border"
        />
      </div>

      {/* Grouped by date */}
      {grouped.size === 0 ? (
        <div className="text-center py-8 text-sm text-muted-foreground">
          No events match your filters.
        </div>
      ) : (
        Array.from(grouped.entries()).map(([dateKey, dateEvents]) => {
          const isExpanded = expandedDates.has(dateKey);
          const highCount = dateEvents.filter((e) => e.impact === "high").length;

          return (
            <div key={dateKey}>
              <button
                onClick={() => toggleDate(dateKey)}
                className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5 hover:text-foreground transition-colors w-full text-left"
              >
                {isExpanded ? (
                  <ChevronDown className="h-3.5 w-3.5" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5" />
                )}
                <Calendar className="h-3 w-3" />
                {dateKey}
                <span className="text-muted-foreground/50 font-normal normal-case">
                  ({dateEvents.length} events)
                </span>
                {highCount > 0 && (
                  <Badge className="bg-red-500/15 text-red-400 border-0 text-[10px]">
                    {highCount} high impact
                  </Badge>
                )}
              </button>

              {isExpanded && (
                <div className="space-y-1 ml-5 mb-3">
                  {dateEvents.map((e, i) => (
                    <div
                      key={`${e.event}-${e.event_time}-${i}`}
                      className={`flex items-center gap-3 px-3 py-2 rounded-lg border transition-colors ${
                        e.impact === "high"
                          ? "border-red-500/20 bg-red-500/5"
                          : e.impact === "medium"
                          ? "border-amber-500/15 bg-amber-500/5"
                          : "border-card-border bg-card-bg/50"
                      }`}
                    >
                      {/* Impact dot */}
                      <span
                        className={`w-2.5 h-2.5 rounded-full shrink-0 ${
                          IMPACT_DOT[e.impact]
                        }`}
                      />
                      {/* Time */}
                      <span className="text-[11px] text-muted-foreground w-16 shrink-0 font-mono">
                        {formatEventTime(e.event_time)}
                      </span>
                      {/* Currency badge */}
                      <Badge
                        className={`text-[10px] border shrink-0 ${
                          IMPACT_COLORS[e.impact]
                        }`}
                      >
                        {e.currency}
                      </Badge>
                      {/* Event name */}
                      <span className="text-sm text-foreground flex-1 truncate">
                        {e.event}
                      </span>
                      {/* Forecast / Previous / Actual */}
                      <div className="flex items-center gap-3 text-[11px] shrink-0">
                        {e.estimate != null && (
                          <span className="text-muted-foreground">
                            Est: <span className="text-foreground">{e.estimate}{e.unit}</span>
                          </span>
                        )}
                        {e.prev != null && (
                          <span className="text-muted-foreground">
                            Prev: <span className="text-foreground">{e.prev}{e.unit}</span>
                          </span>
                        )}
                        {e.actual != null ? (
                          <Badge className="bg-emerald-500/15 text-emerald-400 border-0 text-[10px]">
                            Actual: {e.actual}{e.unit}
                          </Badge>
                        ) : (
                          <span className="text-muted-foreground/50 text-[10px]">
                            {timeUntil(e.event_time)}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component: News Feed
// ---------------------------------------------------------------------------

function NewsFeed({
  articles,
  loading,
  onArticleClick,
}: {
  articles: NewsArticle[];
  loading: boolean;
  onArticleClick: (article: NewsArticle) => void;
}) {
  const [searchFilter, setSearchFilter] = useState("");

  const filtered = useMemo(() => {
    if (!searchFilter) return articles;
    const q = searchFilter.toLowerCase();
    return articles.filter(
      (a) =>
        a.headline.toLowerCase().includes(q) ||
        a.summary.toLowerCase().includes(q) ||
        (a.related_symbols || "").toLowerCase().includes(q)
    );
  }, [articles, searchFilter]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-accent" />
        <span className="ml-2 text-sm text-muted-foreground">Loading news...</span>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
        <Input
          value={searchFilter}
          onChange={(e) => setSearchFilter(e.target.value)}
          placeholder="Search headlines, symbols..."
          className="pl-9 h-8 text-xs bg-card-bg border-card-border"
        />
      </div>

      {filtered.length === 0 ? (
        <div className="text-center py-8 text-sm text-muted-foreground">
          No news articles found.
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((a, i) => (
            <div
              key={a.external_id || i}
              onClick={() => onArticleClick(a)}
              className="block cursor-pointer"
            >
              <Card className="bg-card-bg border-card-border hover:border-accent/30 transition-colors cursor-pointer">
                <CardContent className="p-3">
                  <div className="flex gap-3">
                    {/* Image thumbnail */}
                    {a.image_url && (
                      <div className="w-20 h-14 rounded-md overflow-hidden shrink-0 bg-muted/20">
                        <img
                          src={a.image_url}
                          alt=""
                          className="w-full h-full object-cover"
                          onError={(e) => {
                            (e.target as HTMLImageElement).style.display = "none";
                          }}
                        />
                      </div>
                    )}
                    <div className="flex-1 min-w-0">
                      <h4 className="text-sm font-medium text-foreground line-clamp-2 leading-tight">
                        {a.headline}
                      </h4>
                      <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                        <span className="text-[10px] text-muted-foreground flex items-center gap-1">
                          <Globe className="h-3 w-3" />
                          {a.source}
                        </span>
                        <span className="text-[10px] text-muted-foreground flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {timeAgo(a.published_at)}
                        </span>
                        {a.related_symbols && (
                          <Badge className="bg-purple-500/10 text-purple-400 border-0 text-[9px]">
                            {a.related_symbols.slice(0, 30)}
                          </Badge>
                        )}
                        {a.sentiment_label && (
                          <Badge
                            className={`border-0 text-[9px] ${
                              a.sentiment_label === "Bullish"
                                ? "bg-emerald-500/15 text-emerald-400"
                                : a.sentiment_label === "Bearish"
                                ? "bg-red-500/15 text-red-400"
                                : "bg-gray-500/10 text-gray-400"
                            }`}
                          >
                            {a.sentiment_label}
                          </Badge>
                        )}
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component: Article Detail Modal
// ---------------------------------------------------------------------------

function ArticleDetailModal({
  article,
  onClose,
}: {
  article: NewsArticle;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<ArticleDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState("");

  // Fetch full article detail if we have an ID
  useEffect(() => {
    if (!article.id) {
      // No DB id — show what we have from the feed
      setDetail({
        ...article,
        id: 0,
        ai_analysis: null,
        fetched_at: null,
      });
      setLoading(false);
      return;
    }
    (async () => {
      try {
        const data = await api.get<ArticleDetail>(`/api/news/articles/${article.id}`);
        setDetail(data);
      } catch {
        setDetail({ ...article, id: article.id!, ai_analysis: null, fetched_at: null });
      } finally {
        setLoading(false);
      }
    })();
  }, [article]);

  const runAnalysis = async () => {
    if (!detail?.id) return;
    setAnalyzing(true);
    setAnalysisError("");
    try {
      const data = await api.post<{ article_id: number; analysis: AIAnalysis }>(
        `/api/news/articles/${detail.id}/analyze`
      );
      setDetail((prev) => prev ? { ...prev, ai_analysis: data.analysis } : prev);
    } catch (e: unknown) {
      setAnalysisError(e instanceof Error ? e.message : "Analysis failed — check LLM settings.");
    } finally {
      setAnalyzing(false);
    }
  };

  // Close on Escape
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose]);

  const sentimentColor =
    article.sentiment_label === "Bullish" ? "text-emerald-400" :
    article.sentiment_label === "Bearish" ? "text-red-400" : "text-gray-400";

  const sentimentBg =
    article.sentiment_label === "Bullish" ? "bg-emerald-500/10 border-emerald-500/30" :
    article.sentiment_label === "Bearish" ? "bg-red-500/10 border-red-500/30" : "bg-gray-500/10 border-gray-500/30";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />

      {/* Modal */}
      <div
        className="relative bg-card-bg border border-card-border rounded-xl shadow-2xl w-full max-w-2xl max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close button */}
        <button onClick={onClose} className="absolute top-3 right-3 p-1 rounded-lg hover:bg-input-bg transition-colors z-10">
          <X className="h-5 w-5 text-muted-foreground" />
        </button>

        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="h-6 w-6 animate-spin text-accent" />
          </div>
        ) : (
          <div className="p-6 space-y-5">
            {/* Image */}
            {article.image_url && (
              <div className="w-full h-48 rounded-lg overflow-hidden bg-muted/20 -mt-1">
                <img
                  src={article.image_url}
                  alt=""
                  className="w-full h-full object-cover"
                  onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                />
              </div>
            )}

            {/* Headline */}
            <h2 className="text-lg font-semibold text-foreground leading-tight pr-8">
              {article.headline}
            </h2>

            {/* Meta row */}
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-xs text-muted-foreground flex items-center gap-1">
                <Globe className="h-3 w-3" /> {article.source}
              </span>
              <span className="text-xs text-muted-foreground flex items-center gap-1">
                <Clock className="h-3 w-3" /> {timeAgo(article.published_at)}
              </span>
              <Badge className="text-[10px] bg-blue-500/10 text-blue-400 border-0">
                {article.category}
              </Badge>
              {article.related_symbols && (
                <Badge className="bg-purple-500/10 text-purple-400 border-0 text-[10px]">
                  {article.related_symbols}
                </Badge>
              )}
              {article.url && (
                <a href={article.url} target="_blank" rel="noopener noreferrer"
                  className="text-xs text-accent flex items-center gap-1 hover:underline ml-auto">
                  <ExternalLink className="h-3 w-3" /> Source
                </a>
              )}
            </div>

            {/* Sentiment bar */}
            {article.sentiment_label && (
              <div className={`rounded-lg border px-4 py-2.5 flex items-center gap-3 ${sentimentBg}`}>
                {article.sentiment_label === "Bullish" ? <TrendingUp className={`h-4 w-4 ${sentimentColor}`} /> :
                 article.sentiment_label === "Bearish" ? <TrendingDown className={`h-4 w-4 ${sentimentColor}`} /> :
                 <Minus className={`h-4 w-4 ${sentimentColor}`} />}
                <span className={`text-sm font-medium ${sentimentColor}`}>{article.sentiment_label}</span>
                {article.sentiment_score != null && (
                  <span className="text-xs text-muted-foreground">
                    Score: {article.sentiment_score.toFixed(3)}
                  </span>
                )}
              </div>
            )}

            {/* Summary */}
            {article.summary && (
              <div>
                <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Summary</h3>
                <p className="text-sm text-foreground/80 leading-relaxed">{article.summary}</p>
              </div>
            )}

            {/* AI Analysis section */}
            <div className="border-t border-card-border pt-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-accent" />
                  AI Trading Analysis
                </h3>
                {detail?.id && detail.id > 0 && !detail.ai_analysis && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={runAnalysis}
                    disabled={analyzing}
                    className="gap-1.5 text-xs"
                  >
                    {analyzing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Bot className="h-3.5 w-3.5" />}
                    {analyzing ? "Analyzing..." : "Run AI Analysis"}
                  </Button>
                )}
              </div>

              {analysisError && (
                <div className="rounded-lg bg-red-500/10 border border-red-500/30 px-3 py-2 text-xs text-red-400 mb-3">
                  {analysisError}
                </div>
              )}

              {!detail?.ai_analysis && !analyzing && !analysisError && (
                <div className="text-center py-6 text-sm text-muted-foreground">
                  {detail?.id && detail.id > 0
                    ? 'Click "Run AI Analysis" to get trading insights for this article.'
                    : "AI analysis requires the article to be stored in the database."}
                </div>
              )}

              {detail?.ai_analysis && (
                <div className="space-y-4">
                  {/* Key Points */}
                  {detail.ai_analysis.key_points?.length > 0 && (
                    <div>
                      <h4 className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-1">
                        <Target className="h-3 w-3" /> Key Points
                      </h4>
                      <ul className="space-y-1">
                        {detail.ai_analysis.key_points.map((p, i) => (
                          <li key={i} className="text-sm text-foreground/80 flex items-start gap-2">
                            <span className="text-accent mt-0.5">&#8226;</span>
                            <span>{p}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Impact Assessment */}
                  {detail.ai_analysis.impact_assessment && (
                    <div>
                      <h4 className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-1">
                        <ShieldAlert className="h-3 w-3" /> Impact Assessment
                      </h4>
                      <p className="text-sm text-foreground/80">{detail.ai_analysis.impact_assessment}</p>
                    </div>
                  )}

                  {/* Affected Symbols */}
                  {detail.ai_analysis.affected_symbols?.length > 0 && (
                    <div>
                      <h4 className="text-xs font-medium text-muted-foreground mb-1.5">Affected Symbols</h4>
                      <div className="flex flex-wrap gap-1.5">
                        {detail.ai_analysis.affected_symbols.map((s) => (
                          <Badge key={s} className="bg-purple-500/10 text-purple-400 border-0 text-[11px]">{s}</Badge>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Recommendation */}
                  {detail.ai_analysis.recommendation && (
                    <div className="rounded-lg bg-accent/5 border border-accent/20 px-4 py-3">
                      <h4 className="text-xs font-medium text-accent mb-1 flex items-center gap-1">
                        <ArrowUpRight className="h-3 w-3" /> Recommendation
                      </h4>
                      <p className="text-sm text-foreground/90">{detail.ai_analysis.recommendation}</p>
                      {detail.ai_analysis.confidence != null && (
                        <div className="mt-2 flex items-center gap-2">
                          <span className="text-[10px] text-muted-foreground">Confidence:</span>
                          <div className="flex-1 h-1.5 bg-card-border rounded-full max-w-[120px]">
                            <div className="h-full bg-accent rounded-full" style={{ width: `${Math.round(detail.ai_analysis.confidence * 100)}%` }} />
                          </div>
                          <span className="text-[10px] text-foreground/70">{Math.round(detail.ai_analysis.confidence * 100)}%</span>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Reasoning */}
                  {detail.ai_analysis.reasoning && (
                    <div>
                      <h4 className="text-xs font-medium text-muted-foreground mb-1.5">Reasoning</h4>
                      <p className="text-xs text-foreground/60 leading-relaxed">{detail.ai_analysis.reasoning}</p>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component: Sentiment Panel
// ---------------------------------------------------------------------------

function SentimentPanel({
  sentiment,
  loading,
}: {
  sentiment: Record<string, SentimentData>;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-6">
        <Loader2 className="h-5 w-5 animate-spin text-accent" />
      </div>
    );
  }

  const symbols = Object.keys(sentiment);
  if (symbols.length === 0) {
    return (
      <div className="text-center py-4 text-xs text-muted-foreground">
        Set ALPHAVANTAGE_API_KEY for sentiment data.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
      {symbols.map((sym) => {
        const s = sentiment[sym];
        const Icon =
          s.label === "Bullish"
            ? TrendingUp
            : s.label === "Bearish"
            ? TrendingDown
            : Minus;
        const color =
          s.label === "Bullish"
            ? "text-emerald-400"
            : s.label === "Bearish"
            ? "text-red-400"
            : "text-gray-400";
        const bg =
          s.label === "Bullish"
            ? "bg-emerald-500/10 border-emerald-500/20"
            : s.label === "Bearish"
            ? "bg-red-500/10 border-red-500/20"
            : "bg-card-bg border-card-border";

        return (
          <Card key={sym} className={`${bg} transition-colors`}>
            <CardContent className="p-3 text-center">
              <div className="text-xs font-semibold text-muted-foreground mb-1">
                {sym}
              </div>
              <Icon className={`h-5 w-5 mx-auto ${color}`} />
              <div className={`text-sm font-bold mt-1 ${color}`}>
                {s.label}
              </div>
              <div className="text-[10px] text-muted-foreground mt-0.5">
                Score: {s.score?.toFixed(3) ?? "N/A"} ({s.articles} articles)
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component: Upcoming High-Impact Strip
// ---------------------------------------------------------------------------

function UpcomingEventsStrip({ events }: { events: EconomicEvent[] }) {
  const upcoming = events
    .filter((e) => e.impact === "high" && e.actual == null)
    .slice(0, 5);

  if (upcoming.length === 0) return null;

  return (
    <Card className="bg-red-500/5 border-red-500/20">
      <CardContent className="p-3">
        <div className="flex items-center gap-2 mb-2">
          <AlertTriangle className="h-4 w-4 text-red-400" />
          <span className="text-xs font-semibold text-red-400 uppercase tracking-wider">
            Upcoming High-Impact Events
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          {upcoming.map((e, i) => (
            <Badge
              key={`${e.event}-${i}`}
              className="bg-red-500/15 text-red-300 border-red-500/30 text-[11px] py-1 px-2"
            >
              <Zap className="h-3 w-3 mr-1" />
              {e.currency} — {e.event} — {timeUntil(e.event_time)}
            </Badge>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

type Tab = "calendar" | "news" | "sentiment";

export default function NewsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("calendar");
  const [calendarEvents, setCalendarEvents] = useState<EconomicEvent[]>([]);
  const [newsArticles, setNewsArticles] = useState<NewsArticle[]>([]);
  const [sentiment, setSentiment] = useState<Record<string, SentimentData>>({});
  const [newsCategory, setNewsCategory] = useState<string>("general");
  const [loadingCal, setLoadingCal] = useState(true);
  const [loadingNews, setLoadingNews] = useState(true);
  const [loadingSentiment, setLoadingSentiment] = useState(true);
  const [error, setError] = useState<string>("");
  const [selectedArticle, setSelectedArticle] = useState<NewsArticle | null>(null);

  const loadCalendar = useCallback(async () => {
    setLoadingCal(true);
    try {
      const data = await api.get<{ items: EconomicEvent[] }>("/api/news/calendar");
      setCalendarEvents(data.items || []);
    } catch (e) {
      setError("Failed to load calendar. Ensure FINNHUB_API_KEY is configured.");
    } finally {
      setLoadingCal(false);
    }
  }, []);

  const loadNews = useCallback(async (cat: string) => {
    setLoadingNews(true);
    try {
      const data = await api.get<{ items: NewsArticle[] }>(
        `/api/news/feed?category=${cat}&limit=100`
      );
      setNewsArticles(data.items || []);
    } catch {
      // Silently fail — news may not be configured
    } finally {
      setLoadingNews(false);
    }
  }, []);

  const loadSentiment = useCallback(async () => {
    setLoadingSentiment(true);
    try {
      const data = await api.get<{ sentiment: Record<string, SentimentData> }>(
        "/api/news/overview"
      );
      setSentiment(data.sentiment || {});
    } catch {
      // Silently fail
    } finally {
      setLoadingSentiment(false);
    }
  }, []);

  useEffect(() => {
    loadCalendar();
    loadNews(newsCategory);
    loadSentiment();
  }, [loadCalendar, loadNews, loadSentiment, newsCategory]);

  // Auto-refresh every 5 minutes
  useEffect(() => {
    const iv = setInterval(() => {
      loadCalendar();
      loadNews(newsCategory);
    }, 300000);
    return () => clearInterval(iv);
  }, [loadCalendar, loadNews, newsCategory]);

  const handleRefresh = () => {
    loadCalendar();
    loadNews(newsCategory);
    loadSentiment();
  };

  const tabs: { key: Tab; label: string; icon: typeof Newspaper }[] = [
    { key: "calendar", label: "Economic Calendar", icon: Calendar },
    { key: "news", label: "Market News", icon: Newspaper },
    { key: "sentiment", label: "Sentiment", icon: BarChart3 },
  ];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <h2 className="text-lg sm:text-xl font-semibold flex items-center gap-2">
          <Newspaper className="h-5 w-5 text-accent" />
          News & Events
        </h2>
        <Button
          variant="outline"
          size="sm"
          onClick={handleRefresh}
          className="gap-1.5 text-xs"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </Button>
      </div>

      {/* Error banner */}
      {error && (
        <div className="rounded-lg bg-amber-500/10 border border-amber-500/30 px-4 py-2 text-sm text-amber-400 flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {/* Upcoming high-impact strip */}
      <UpcomingEventsStrip events={calendarEvents} />

      {/* Sentiment row */}
      <SentimentPanel sentiment={sentiment} loading={loadingSentiment} />

      {/* Tab navigation */}
      <div className="flex items-center gap-1 border-b border-card-border pb-0">
        {tabs.map((t) => {
          const Icon = t.icon;
          const isActive = activeTab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => setActiveTab(t.key)}
              className={`flex items-center gap-1.5 px-4 py-2 text-xs font-medium transition-colors border-b-2 -mb-[1px] ${
                isActive
                  ? "border-accent text-accent"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              {t.label}
            </button>
          );
        })}

        {/* News category filter (only on news tab) */}
        {activeTab === "news" && (
          <div className="ml-auto flex items-center gap-1">
            {["general", "forex", "crypto"].map((cat) => (
              <Button
                key={cat}
                variant={newsCategory === cat ? "default" : "ghost"}
                size="sm"
                onClick={() => {
                  setNewsCategory(cat);
                  loadNews(cat);
                }}
                className={`h-6 text-[10px] ${
                  newsCategory === cat ? "bg-accent text-black" : ""
                }`}
              >
                {cat.charAt(0).toUpperCase() + cat.slice(1)}
              </Button>
            ))}
          </div>
        )}
      </div>

      {/* Tab content */}
      <div className="min-h-[400px]">
        {activeTab === "calendar" && (
          <EconomicCalendar events={calendarEvents} loading={loadingCal} />
        )}
        {activeTab === "news" && (
          <NewsFeed articles={newsArticles} loading={loadingNews} onArticleClick={setSelectedArticle} />
        )}
        {activeTab === "sentiment" && (
          <div className="space-y-4">
            <SentimentPanel sentiment={sentiment} loading={loadingSentiment} />
            <div className="text-xs text-muted-foreground text-center">
              Sentiment data powered by Alpha Vantage. Updates every 60 minutes.
              <br />
              Configure <code className="text-accent">ALPHAVANTAGE_API_KEY</code> in your environment for live data.
            </div>
          </div>
        )}
      </div>

      {/* Article detail modal */}
      {selectedArticle && (
        <ArticleDetailModal
          article={selectedArticle}
          onClose={() => setSelectedArticle(null)}
        />
      )}

      <ChatHelpers />
    </div>
  );
}
