from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Text

from app.core.database import Base


class KnowledgeArticle(Base):
    __tablename__ = "knowledge_articles"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, default="")                # Markdown
    category = Column(String(50), nullable=False)     # basics, ta, fa, risk, psychology, platform
    difficulty = Column(String(20), default="beginner")  # beginner, intermediate, advanced
    quiz_questions = Column(JSON, default=list)       # [{question, options, correct_index, explanation}]
    author_id = Column(Integer, ForeignKey("users.id"))
    source_type = Column(String(20), default="manual")  # manual, ai_generated, external, community
    external_url = Column(String(500), default="")
    order_index = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    article_id = Column(Integer, ForeignKey("knowledge_articles.id"), nullable=False)
    score = Column(Integer, default=0)
    total_questions = Column(Integer, default=0)
    answers = Column(JSON, default=list)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
