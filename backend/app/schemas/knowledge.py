"""Pydantic schemas for Knowledge Base endpoints."""

from typing import Optional
from pydantic import BaseModel


# ── Quiz structures ────────────────────────────────────

class QuizQuestion(BaseModel):
    question: str
    options: list[str]
    correct_index: int
    explanation: str = ""


# ── Articles ───────────────────────────────────────────

class ArticleCreate(BaseModel):
    title: str
    content: str = ""
    category: str = "basics"          # basics, ta, fa, risk, psychology, platform
    difficulty: str = "beginner"      # beginner, intermediate, advanced
    quiz_questions: list[QuizQuestion] = []
    source_type: str = "manual"       # manual, ai_generated, external, community
    external_url: str = ""
    order_index: int = 0


class ArticleUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    difficulty: Optional[str] = None
    quiz_questions: Optional[list[QuizQuestion]] = None
    source_type: Optional[str] = None
    external_url: Optional[str] = None
    order_index: Optional[int] = None


class ArticleResponse(BaseModel):
    id: int
    title: str
    content: str
    category: str
    difficulty: str
    quiz_questions: list[QuizQuestion]
    author_id: int | None
    source_type: str
    external_url: str
    order_index: int
    created_at: str
    updated_at: str


class ArticleListItem(BaseModel):
    id: int
    title: str
    category: str
    difficulty: str
    source_type: str
    has_quiz: bool
    quiz_count: int
    order_index: int
    created_at: str


# ── Quizzes ────────────────────────────────────────────

class QuizSubmitRequest(BaseModel):
    article_id: int
    answers: list[int]                 # list of selected option indices


class QuizResultResponse(BaseModel):
    article_id: int
    score: int
    total_questions: int
    percentage: float
    details: list[dict]                # [{question, selected, correct, is_correct, explanation}]


class QuizAttemptResponse(BaseModel):
    id: int
    article_id: int
    article_title: str
    score: int
    total_questions: int
    percentage: float
    created_at: str


# ── Progress ───────────────────────────────────────────

class CategoryProgress(BaseModel):
    category: str
    total_articles: int
    articles_read: int
    quizzes_taken: int
    avg_quiz_score: float


class KnowledgeProgressResponse(BaseModel):
    total_articles: int
    total_quizzes_taken: int
    avg_quiz_score: float
    categories: list[CategoryProgress]
    recent_attempts: list[QuizAttemptResponse]
