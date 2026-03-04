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
}: {
  articles: NewsArticle[];
  loading: boolean;
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
            <a
              key={a.external_id || i}
              href={a.url}
              target="_blank"
              rel="noopener noreferrer"
              className="block"
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
                      <div className="flex items-center gap-2 mt-1.5">
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
                        <ExternalLink className="h-3 w-3 text-muted-foreground/50 ml-auto shrink-0" />
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </a>
          ))}
        </div>
      )}
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
          <NewsFeed articles={newsArticles} loading={loadingNews} />
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

      <ChatHelpers />
    </div>
  );
}
