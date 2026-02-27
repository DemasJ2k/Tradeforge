"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import ChatHelpers from "@/components/ChatHelpers";
import type {
  ArticleListItem,
  KnowledgeArticle,
  QuizResult,
  KnowledgeProgress,
  CategoryInfo,
} from "@/types";

/* ── constants ───────────────────────────────────── */

const CAT_COLORS: Record<string, string> = {
  basics: "bg-blue-500",
  ta: "bg-purple-500",
  fa: "bg-green-500",
  risk: "bg-amber-500",
  psychology: "bg-rose-500",
  platform: "bg-cyan-500",
};

const DIFF_COLORS: Record<string, string> = {
  beginner: "bg-green-500/20 text-green-400",
  intermediate: "bg-amber-500/20 text-amber-400",
  advanced: "bg-red-500/20 text-red-400",
};

/* ═══════════════════════════════════════════════════ */

export default function KnowledgePage() {
  /* ── state ────────────────────────────────────── */
  const [view, setView] = useState<"list" | "article" | "quiz" | "result">("list");
  const [articles, setArticles] = useState<ArticleListItem[]>([]);
  const [categoryInfo, setCategoryInfo] = useState<CategoryInfo | null>(null);
  const [progress, setProgress] = useState<KnowledgeProgress | null>(null);
  const [selectedCat, setSelectedCat] = useState<string | null>(null);

  // Article view
  const [activeArticle, setActiveArticle] = useState<KnowledgeArticle | null>(null);

  // Quiz state
  const [quizAnswers, setQuizAnswers] = useState<(number | null)[]>([]);
  const [quizResult, setQuizResult] = useState<QuizResult | null>(null);
  const [submittingQuiz, setSubmittingQuiz] = useState(false);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [seeding, setSeeding] = useState(false);

  /* ── load data ────────────────────────────────── */
  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [arts, cats, prog] = await Promise.all([
        api.get<ArticleListItem[]>("/api/knowledge/articles"),
        api.get<CategoryInfo>("/api/knowledge/categories"),
        api.get<KnowledgeProgress>("/api/knowledge/progress"),
      ]);
      setArticles(arts);
      setCategoryInfo(cats);
      setProgress(prog);
      setError("");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  };

  /* ── seed ──────────────────────────────────────── */
  const seedContent = async () => {
    setSeeding(true);
    try {
      await api.post("/api/knowledge/seed", {});
      await loadData();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Seed failed");
    } finally {
      setSeeding(false);
    }
  };

  /* ── open article ──────────────────────────────── */
  const openArticle = async (id: number) => {
    try {
      const article = await api.get<KnowledgeArticle>(`/api/knowledge/articles/${id}`);
      setActiveArticle(article);
      setView("article");
      setQuizResult(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load article");
    }
  };

  /* ── start quiz ────────────────────────────────── */
  const startQuiz = () => {
    if (!activeArticle?.quiz_questions?.length) return;
    setQuizAnswers(new Array(activeArticle.quiz_questions.length).fill(null));
    setQuizResult(null);
    setView("quiz");
  };

  /* ── submit quiz ───────────────────────────────── */
  const submitQuiz = async () => {
    if (!activeArticle || quizAnswers.some((a) => a === null)) return;
    setSubmittingQuiz(true);
    try {
      const result = await api.post<QuizResult>("/api/knowledge/quiz/submit", {
        article_id: activeArticle.id,
        answers: quizAnswers,
      });
      setQuizResult(result);
      setView("result");
      // Refresh progress
      const prog = await api.get<KnowledgeProgress>("/api/knowledge/progress");
      setProgress(prog);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Submit failed");
    } finally {
      setSubmittingQuiz(false);
    }
  };

  /* ── filtered articles ─────────────────────────── */
  const filtered = selectedCat
    ? articles.filter((a) => a.category === selectedCat)
    : articles;

  /* ═══════════════ RENDER ═══════════════════════ */

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-muted">
        Loading knowledge base...
      </div>
    );
  }

  /* ── Quiz Result View ──────────────────────────── */
  if (view === "result" && quizResult && activeArticle) {
    return (
      <div className="space-y-4 max-w-3xl">
        <button
          onClick={() => { setView("article"); }}
          className="text-sm text-accent hover:underline"
        >
          &larr; Back to Article
        </button>

        <div className="rounded-xl border border-card-border bg-card-bg p-6 text-center">
          <div className="text-5xl mb-3">
            {quizResult.percentage >= 80 ? "🎉" : quizResult.percentage >= 50 ? "👍" : "📖"}
          </div>
          <h2 className="text-2xl font-bold mb-1">
            {quizResult.score} / {quizResult.total_questions}
          </h2>
          <p className="text-muted">
            {quizResult.percentage}% —{" "}
            {quizResult.percentage >= 80
              ? "Excellent!"
              : quizResult.percentage >= 50
                ? "Good effort!"
                : "Keep studying!"}
          </p>
        </div>

        <div className="space-y-3">
          {quizResult.details.map((d, i) => (
            <div
              key={i}
              className={`rounded-xl border p-4 ${
                d.is_correct
                  ? "border-green-500/30 bg-green-500/5"
                  : "border-red-500/30 bg-red-500/5"
              }`}
            >
              <div className="flex items-start gap-2 mb-2">
                <span className="text-lg">{d.is_correct ? "✅" : "❌"}</span>
                <p className="text-sm font-medium">{d.question}</p>
              </div>
              <div className="ml-7 space-y-1">
                {d.options.map((opt: string, oi: number) => (
                  <div
                    key={oi}
                    className={`text-xs px-2 py-1 rounded ${
                      oi === d.correct
                        ? "text-green-400 font-medium"
                        : oi === d.selected && !d.is_correct
                          ? "text-red-400 line-through"
                          : "text-muted"
                    }`}
                  >
                    {oi === d.correct && "✓ "}
                    {oi === d.selected && !d.is_correct && "✗ "}
                    {opt}
                  </div>
                ))}
                {d.explanation && (
                  <p className="text-xs text-muted mt-2 italic">
                    {d.explanation}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>

        <div className="flex gap-3">
          <button
            onClick={() => startQuiz()}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/80"
          >
            Retry Quiz
          </button>
          <button
            onClick={() => { setView("list"); setActiveArticle(null); }}
            className="rounded-lg border border-card-border px-4 py-2 text-sm text-muted hover:text-foreground"
          >
            Back to Articles
          </button>
        </div>
      </div>
    );
  }

  /* ── Quiz View ─────────────────────────────────── */
  if (view === "quiz" && activeArticle) {
    const questions = activeArticle.quiz_questions || [];
    const allAnswered = quizAnswers.every((a) => a !== null);

    return (
      <div className="space-y-4 max-w-3xl">
        <button
          onClick={() => setView("article")}
          className="text-sm text-accent hover:underline"
        >
          &larr; Back to Article
        </button>

        <h2 className="text-xl font-semibold">Quiz: {activeArticle.title}</h2>
        <p className="text-sm text-muted">
          {questions.length} questions — Select an answer for each
        </p>

        <div className="space-y-4">
          {questions.map((q, qi) => (
            <div
              key={qi}
              className="rounded-xl border border-card-border bg-card-bg p-5"
            >
              <p className="text-sm font-medium mb-3">
                {qi + 1}. {q.question}
              </p>
              <div className="space-y-2">
                {q.options.map((opt, oi) => (
                  <button
                    key={oi}
                    onClick={() => {
                      const next = [...quizAnswers];
                      next[qi] = oi;
                      setQuizAnswers(next);
                    }}
                    className={`w-full text-left rounded-lg border px-4 py-2.5 text-sm transition-colors ${
                      quizAnswers[qi] === oi
                        ? "border-accent bg-accent/10 text-foreground"
                        : "border-card-border hover:border-accent/50 text-muted hover:text-foreground"
                    }`}
                  >
                    <span className="text-xs text-muted mr-2">
                      {String.fromCharCode(65 + oi)}.
                    </span>
                    {opt}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>

        <button
          onClick={submitQuiz}
          disabled={!allAnswered || submittingQuiz}
          className="rounded-lg bg-accent px-6 py-2.5 text-sm font-medium text-white hover:bg-accent/80 disabled:opacity-40"
        >
          {submittingQuiz ? "Submitting..." : "Submit Answers"}
        </button>
      </div>
    );
  }

  /* ── Article View ──────────────────────────────── */
  if (view === "article" && activeArticle) {
    return (
      <div className="space-y-4 max-w-3xl">
        <button
          onClick={() => { setView("list"); setActiveArticle(null); }}
          className="text-sm text-accent hover:underline"
        >
          &larr; Back to Articles
        </button>

        <div className="rounded-xl border border-card-border bg-card-bg p-6">
          <div className="flex items-center gap-3 mb-4">
            <span className={`rounded px-2 py-0.5 text-xs ${DIFF_COLORS[activeArticle.difficulty] || ""}`}>
              {activeArticle.difficulty}
            </span>
            <span className="text-xs text-muted">
              {categoryInfo?.labels[activeArticle.category] || activeArticle.category}
            </span>
          </div>

          <h2 className="text-xl font-bold mb-4">{activeArticle.title}</h2>

          {/* Render markdown-ish content */}
          <div className="prose prose-invert prose-sm max-w-none text-foreground/90">
            {activeArticle.content.split("\n").map((line, i) => {
              if (line.startsWith("### ")) return <h4 key={i} className="text-sm font-semibold mt-4 mb-1 text-foreground">{line.slice(4)}</h4>;
              if (line.startsWith("## ")) return <h3 key={i} className="text-base font-semibold mt-5 mb-2 text-foreground">{line.slice(3)}</h3>;
              if (line.startsWith("# ")) return <h2 key={i} className="text-lg font-bold mt-6 mb-2 text-foreground">{line.slice(2)}</h2>;
              if (line.startsWith("- **")) {
                const match = line.match(/^- \*\*(.+?)\*\*:?\s*(.*)/);
                if (match) return <p key={i} className="text-sm ml-4 mb-1"><strong className="text-foreground">{match[1]}</strong>{match[2] ? `: ${match[2]}` : ""}</p>;
              }
              if (line.startsWith("- ")) return <p key={i} className="text-sm ml-4 mb-1">• {line.slice(2)}</p>;
              if (/^\d+\.\s/.test(line)) return <p key={i} className="text-sm ml-4 mb-1">{line}</p>;
              if (line.startsWith("`") && line.endsWith("`")) return <code key={i} className="block bg-background rounded px-3 py-2 text-xs text-accent mb-2">{line.slice(1, -1)}</code>;
              if (line.startsWith("**") && line.endsWith("**")) return <p key={i} className="text-sm font-semibold mb-1">{line.slice(2, -2)}</p>;
              if (line.trim() === "") return <div key={i} className="h-2" />;
              return <p key={i} className="text-sm mb-1 text-foreground/80">{line}</p>;
            })}
          </div>
        </div>

        {activeArticle.quiz_questions.length > 0 && (
          <button
            onClick={startQuiz}
            className="rounded-lg bg-accent px-6 py-2.5 text-sm font-medium text-white hover:bg-accent/80"
          >
            Take Quiz ({activeArticle.quiz_questions.length} questions)
          </button>
        )}

        <ChatHelpers />
      </div>
    );
  }

  /* ── List View (default) ───────────────────────── */
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Knowledge Base</h2>
        {articles.length === 0 && (
          <button
            onClick={seedContent}
            disabled={seeding}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/80 disabled:opacity-40"
          >
            {seeding ? "Seeding..." : "Load Starter Content"}
          </button>
        )}
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Progress Overview */}
      {progress && progress.total_articles > 0 && (
        <div className="grid grid-cols-3 gap-4">
          <div className="rounded-xl border border-card-border bg-card-bg p-4">
            <div className="text-xs text-muted mb-1">Articles</div>
            <div className="text-lg font-semibold">{progress.total_articles}</div>
          </div>
          <div className="rounded-xl border border-card-border bg-card-bg p-4">
            <div className="text-xs text-muted mb-1">Quizzes Taken</div>
            <div className="text-lg font-semibold">{progress.total_quizzes_taken}</div>
          </div>
          <div className="rounded-xl border border-card-border bg-card-bg p-4">
            <div className="text-xs text-muted mb-1">Avg Score</div>
            <div className="text-lg font-semibold">
              {progress.total_quizzes_taken > 0 ? `${progress.avg_quiz_score}%` : "—"}
            </div>
          </div>
        </div>
      )}

      {/* Category Cards */}
      {categoryInfo && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
          <button
            onClick={() => setSelectedCat(null)}
            className={`rounded-xl border p-4 text-left transition-colors ${
              selectedCat === null
                ? "border-accent bg-accent/10"
                : "border-card-border bg-card-bg hover:border-accent/50"
            }`}
          >
            <div className="text-sm font-medium">All</div>
            <div className="text-xs text-muted">{articles.length} articles</div>
          </button>
          {categoryInfo.categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setSelectedCat(cat === selectedCat ? null : cat)}
              className={`rounded-xl border p-4 text-left transition-colors ${
                selectedCat === cat
                  ? "border-accent bg-accent/10"
                  : "border-card-border bg-card-bg hover:border-accent/50"
              }`}
            >
              <div className="flex items-center gap-2">
                <div className={`h-2.5 w-2.5 rounded-full ${CAT_COLORS[cat] || "bg-gray-500"}`} />
                <div className="text-sm font-medium">{categoryInfo.labels[cat]}</div>
              </div>
              <div className="text-xs text-muted mt-1">
                {categoryInfo.counts[cat]} articles
              </div>
            </button>
          ))}
        </div>
      )}

      {/* Article List */}
      {articles.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-card-border bg-card-bg p-16 text-center">
          <div className="text-4xl mb-4">📚</div>
          <h3 className="text-lg font-medium mb-2">No Articles Yet</h3>
          <p className="text-sm text-muted mb-6 max-w-md">
            Get started by loading the starter content, or create your own articles.
          </p>
          <button
            onClick={seedContent}
            disabled={seeding}
            className="rounded-lg bg-accent px-6 py-2.5 text-sm font-medium text-white hover:bg-accent/80 disabled:opacity-40"
          >
            {seeding ? "Loading..." : "Load Starter Content"}
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((a) => (
            <button
              key={a.id}
              onClick={() => openArticle(a.id)}
              className="w-full text-left rounded-xl border border-card-border bg-card-bg p-4 hover:border-accent/50 transition-colors"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className={`h-2.5 w-2.5 rounded-full ${CAT_COLORS[a.category] || "bg-gray-500"}`} />
                  <div>
                    <div className="text-sm font-medium">{a.title}</div>
                    <div className="flex items-center gap-2 mt-1">
                      <span className={`rounded px-1.5 py-0.5 text-[10px] ${DIFF_COLORS[a.difficulty] || ""}`}>
                        {a.difficulty}
                      </span>
                      {a.has_quiz && (
                        <span className="text-[10px] text-accent">
                          {a.quiz_count} quiz questions
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <svg className="h-4 w-4 text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </div>
            </button>
          ))}
        </div>
      )}

      {/* Recent Quiz Attempts */}
      {progress && progress.recent_attempts.length > 0 && (
        <div className="rounded-xl border border-card-border bg-card-bg p-5">
          <h3 className="text-sm font-medium text-muted mb-3">Recent Quiz Attempts</h3>
          <div className="space-y-2">
            {progress.recent_attempts.map((a) => (
              <div
                key={a.id}
                className="flex items-center justify-between rounded-lg border border-card-border bg-background/50 p-3"
              >
                <div>
                  <div className="text-sm">{a.article_title}</div>
                  <div className="text-xs text-muted">
                    {new Date(a.created_at).toLocaleDateString()}
                  </div>
                </div>
                <div className={`text-sm font-medium ${
                  a.percentage >= 80 ? "text-green-400" : a.percentage >= 50 ? "text-amber-400" : "text-red-400"
                }`}>
                  {a.score}/{a.total_questions} ({a.percentage}%)
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <ChatHelpers />
    </div>
  );
}
