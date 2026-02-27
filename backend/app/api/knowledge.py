"""
Knowledge Base API — articles, quizzes, progress tracking.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.api.auth import get_current_user
from app.models.user import User
from app.models.knowledge import KnowledgeArticle, QuizAttempt
from app.schemas.knowledge import (
    ArticleCreate,
    ArticleUpdate,
    ArticleResponse,
    ArticleListItem,
    QuizSubmitRequest,
    QuizResultResponse,
    QuizAttemptResponse,
    CategoryProgress,
    KnowledgeProgressResponse,
)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

VALID_CATEGORIES = ["basics", "ta", "fa", "risk", "psychology", "platform"]
VALID_DIFFICULTIES = ["beginner", "intermediate", "advanced"]


# ── helpers ────────────────────────────────────────────

def _article_to_response(a: KnowledgeArticle) -> ArticleResponse:
    questions = a.quiz_questions or []
    return ArticleResponse(
        id=a.id,
        title=a.title,
        content=a.content or "",
        category=a.category,
        difficulty=a.difficulty,
        quiz_questions=questions,
        author_id=a.author_id,
        source_type=a.source_type or "manual",
        external_url=a.external_url or "",
        order_index=a.order_index or 0,
        created_at=a.created_at.isoformat() if a.created_at else "",
        updated_at=a.updated_at.isoformat() if a.updated_at else "",
    )


def _article_to_list_item(a: KnowledgeArticle) -> ArticleListItem:
    questions = a.quiz_questions or []
    return ArticleListItem(
        id=a.id,
        title=a.title,
        category=a.category,
        difficulty=a.difficulty,
        source_type=a.source_type or "manual",
        has_quiz=len(questions) > 0,
        quiz_count=len(questions),
        order_index=a.order_index or 0,
        created_at=a.created_at.isoformat() if a.created_at else "",
    )


# ── Articles CRUD ──────────────────────────────────────

@router.get("/articles")
def list_articles(
    category: Optional[str] = Query(None),
    difficulty: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all articles with optional filters."""
    q = db.query(KnowledgeArticle)

    if category:
        q = q.filter(KnowledgeArticle.category == category)
    if difficulty:
        q = q.filter(KnowledgeArticle.difficulty == difficulty)
    if search:
        q = q.filter(
            KnowledgeArticle.title.ilike(f"%{search}%")
            | KnowledgeArticle.content.ilike(f"%{search}%")
        )

    articles = q.order_by(KnowledgeArticle.category, KnowledgeArticle.order_index, KnowledgeArticle.id).all()
    return [_article_to_list_item(a) for a in articles]


@router.get("/articles/{article_id}")
def get_article(
    article_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single article with full content."""
    article = db.query(KnowledgeArticle).filter(KnowledgeArticle.id == article_id).first()
    if not article:
        raise HTTPException(404, "Article not found")
    return _article_to_response(article)


@router.post("/articles")
def create_article(
    payload: ArticleCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new knowledge article."""
    article = KnowledgeArticle(
        title=payload.title,
        content=payload.content,
        category=payload.category,
        difficulty=payload.difficulty,
        quiz_questions=[q.model_dump() for q in payload.quiz_questions],
        author_id=user.id,
        source_type=payload.source_type,
        external_url=payload.external_url,
        order_index=payload.order_index,
    )
    db.add(article)
    db.commit()
    db.refresh(article)
    return _article_to_response(article)


@router.put("/articles/{article_id}")
def update_article(
    article_id: int,
    payload: ArticleUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update an existing article."""
    article = db.query(KnowledgeArticle).filter(KnowledgeArticle.id == article_id).first()
    if not article:
        raise HTTPException(404, "Article not found")

    if payload.title is not None:
        article.title = payload.title
    if payload.content is not None:
        article.content = payload.content
    if payload.category is not None:
        article.category = payload.category
    if payload.difficulty is not None:
        article.difficulty = payload.difficulty
    if payload.quiz_questions is not None:
        article.quiz_questions = [q.model_dump() for q in payload.quiz_questions]
    if payload.source_type is not None:
        article.source_type = payload.source_type
    if payload.external_url is not None:
        article.external_url = payload.external_url
    if payload.order_index is not None:
        article.order_index = payload.order_index

    db.commit()
    db.refresh(article)
    return _article_to_response(article)


@router.delete("/articles/{article_id}")
def delete_article(
    article_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete an article and associated quiz attempts."""
    article = db.query(KnowledgeArticle).filter(KnowledgeArticle.id == article_id).first()
    if not article:
        raise HTTPException(404, "Article not found")

    # Delete quiz attempts for this article
    db.query(QuizAttempt).filter(QuizAttempt.article_id == article_id).delete()
    db.delete(article)
    db.commit()
    return {"status": "deleted", "id": article_id}


# ── Categories ─────────────────────────────────────────

@router.get("/categories")
def list_categories(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get article counts per category."""
    results = (
        db.query(
            KnowledgeArticle.category,
            func.count(KnowledgeArticle.id).label("count"),
        )
        .group_by(KnowledgeArticle.category)
        .all()
    )
    categories = {cat: count for cat, count in results}
    return {
        "categories": VALID_CATEGORIES,
        "counts": {c: categories.get(c, 0) for c in VALID_CATEGORIES},
        "labels": {
            "basics": "Basics",
            "ta": "Technical Analysis",
            "fa": "Fundamental Analysis",
            "risk": "Risk Management",
            "psychology": "Psychology",
            "platform": "Platform Guide",
        },
    }


# ── Quizzes ────────────────────────────────────────────

@router.post("/quiz/submit")
def submit_quiz(
    payload: QuizSubmitRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit quiz answers and get results."""
    article = db.query(KnowledgeArticle).filter(KnowledgeArticle.id == payload.article_id).first()
    if not article:
        raise HTTPException(404, "Article not found")

    questions = article.quiz_questions or []
    if not questions:
        raise HTTPException(400, "This article has no quiz questions")

    if len(payload.answers) != len(questions):
        raise HTTPException(400, f"Expected {len(questions)} answers, got {len(payload.answers)}")

    # Grade
    details = []
    score = 0
    for i, (q, selected) in enumerate(zip(questions, payload.answers)):
        correct_idx = q.get("correct_index", 0)
        is_correct = selected == correct_idx
        if is_correct:
            score += 1
        details.append({
            "question": q.get("question", ""),
            "selected": selected,
            "correct": correct_idx,
            "is_correct": is_correct,
            "explanation": q.get("explanation", ""),
            "options": q.get("options", []),
        })

    # Save attempt
    attempt = QuizAttempt(
        user_id=user.id,
        article_id=payload.article_id,
        score=score,
        total_questions=len(questions),
        answers=payload.answers,
    )
    db.add(attempt)
    db.commit()

    return QuizResultResponse(
        article_id=payload.article_id,
        score=score,
        total_questions=len(questions),
        percentage=round((score / len(questions)) * 100, 1) if questions else 0,
        details=details,
    )


@router.get("/quiz/history")
def quiz_history(
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get user's quiz attempt history."""
    attempts = (
        db.query(QuizAttempt)
        .filter(QuizAttempt.user_id == user.id)
        .order_by(QuizAttempt.created_at.desc())
        .limit(limit)
        .all()
    )

    result = []
    for a in attempts:
        article = db.query(KnowledgeArticle).filter(KnowledgeArticle.id == a.article_id).first()
        title = article.title if article else "Deleted Article"
        total = a.total_questions or 1
        result.append(QuizAttemptResponse(
            id=a.id,
            article_id=a.article_id,
            article_title=title,
            score=a.score,
            total_questions=a.total_questions,
            percentage=round((a.score / total) * 100, 1),
            created_at=a.created_at.isoformat() if a.created_at else "",
        ))

    return result


# ── Progress ───────────────────────────────────────────

@router.get("/progress")
def get_progress(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get user's overall knowledge progress."""
    total_articles = db.query(KnowledgeArticle).count()

    # Quiz stats
    attempts = db.query(QuizAttempt).filter(QuizAttempt.user_id == user.id).all()
    total_quizzes = len(attempts)
    avg_score = 0.0
    if total_quizzes > 0:
        scores = [(a.score / max(a.total_questions, 1)) * 100 for a in attempts]
        avg_score = round(sum(scores) / len(scores), 1)

    # Per-category progress
    categories = []
    for cat in VALID_CATEGORIES:
        cat_articles = db.query(KnowledgeArticle).filter(KnowledgeArticle.category == cat).all()
        cat_article_ids = [a.id for a in cat_articles]
        cat_attempts = [a for a in attempts if a.article_id in cat_article_ids]

        articles_with_attempts = set(a.article_id for a in cat_attempts)
        cat_avg = 0.0
        if cat_attempts:
            cat_scores = [(a.score / max(a.total_questions, 1)) * 100 for a in cat_attempts]
            cat_avg = round(sum(cat_scores) / len(cat_scores), 1)

        categories.append(CategoryProgress(
            category=cat,
            total_articles=len(cat_articles),
            articles_read=len(articles_with_attempts),
            quizzes_taken=len(cat_attempts),
            avg_quiz_score=cat_avg,
        ))

    # Recent attempts
    recent = (
        db.query(QuizAttempt)
        .filter(QuizAttempt.user_id == user.id)
        .order_by(QuizAttempt.created_at.desc())
        .limit(5)
        .all()
    )
    recent_list = []
    for a in recent:
        article = db.query(KnowledgeArticle).filter(KnowledgeArticle.id == a.article_id).first()
        title = article.title if article else "Deleted Article"
        total = a.total_questions or 1
        recent_list.append(QuizAttemptResponse(
            id=a.id,
            article_id=a.article_id,
            article_title=title,
            score=a.score,
            total_questions=a.total_questions,
            percentage=round((a.score / total) * 100, 1),
            created_at=a.created_at.isoformat() if a.created_at else "",
        ))

    return KnowledgeProgressResponse(
        total_articles=total_articles,
        total_quizzes_taken=total_quizzes,
        avg_quiz_score=avg_score,
        categories=categories,
        recent_attempts=recent_list,
    )


# ── Seed Content ───────────────────────────────────────

@router.post("/seed")
def seed_starter_content(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Seed the knowledge base with starter articles. Idempotent."""
    existing = db.query(KnowledgeArticle).count()
    if existing > 0:
        return {"status": "skipped", "message": f"Knowledge base already has {existing} articles"}

    seed_articles = [
        {
            "title": "What is Forex Trading?",
            "category": "basics",
            "difficulty": "beginner",
            "content": """# What is Forex Trading?

Foreign exchange (Forex or FX) trading is the buying and selling of currencies on a decentralized global market. It is the largest financial market in the world, with a daily trading volume exceeding $7.5 trillion.

## Key Concepts

### Currency Pairs
Currencies are traded in pairs (e.g., EUR/USD). The first currency is the **base currency** and the second is the **quote currency**. When you buy EUR/USD, you are buying euros and selling US dollars.

### Bid and Ask
- **Bid**: The price at which you can sell the base currency
- **Ask**: The price at which you can buy the base currency
- **Spread**: The difference between bid and ask

### Pips
A pip is the smallest price move in a currency pair. For most pairs, 1 pip = 0.0001.

### Leverage
Forex brokers offer leverage, allowing you to control larger positions with less capital. While leverage amplifies profits, it also amplifies losses.

## Market Sessions
- **Sydney**: 10:00 PM - 7:00 AM UTC
- **Tokyo**: 12:00 AM - 9:00 AM UTC
- **London**: 8:00 AM - 5:00 PM UTC
- **New York**: 1:00 PM - 10:00 PM UTC

The highest volatility occurs during session overlaps, especially London-New York (1:00 PM - 5:00 PM UTC).
""",
            "quiz_questions": [
                {
                    "question": "What does the spread represent in forex trading?",
                    "options": ["The daily price range", "The difference between bid and ask", "The broker's commission rate", "The leverage ratio"],
                    "correct_index": 1,
                    "explanation": "The spread is the difference between the bid (sell) price and the ask (buy) price. It represents the cost of trading."
                },
                {
                    "question": "In EUR/USD, which is the base currency?",
                    "options": ["USD", "EUR", "Both equally", "Neither"],
                    "correct_index": 1,
                    "explanation": "The first currency in a pair is always the base currency. In EUR/USD, EUR is the base and USD is the quote currency."
                },
                {
                    "question": "When do the London and New York sessions overlap?",
                    "options": ["8:00 AM - 12:00 PM UTC", "1:00 PM - 5:00 PM UTC", "5:00 PM - 10:00 PM UTC", "12:00 AM - 7:00 AM UTC"],
                    "correct_index": 1,
                    "explanation": "The London-New York overlap occurs from 1:00 PM to 5:00 PM UTC and is typically the most volatile trading period."
                },
            ],
        },
        {
            "title": "Understanding Candlestick Charts",
            "category": "ta",
            "difficulty": "beginner",
            "content": """# Understanding Candlestick Charts

Candlestick charts are the most popular chart type for trading. Each candle represents price action over a specific time period.

## Anatomy of a Candle

A candlestick has four price points:
- **Open**: Where price started
- **Close**: Where price ended
- **High**: Highest price reached
- **Low**: Lowest price reached

### Body and Wicks
- **Body**: The filled area between open and close
- **Upper wick/shadow**: Line above the body (high)
- **Lower wick/shadow**: Line below the body (low)

### Bullish vs Bearish
- **Bullish (green/white)**: Close > Open (price went up)
- **Bearish (red/black)**: Close < Open (price went down)

## Common Patterns

### Single Candle Patterns
- **Doji**: Open and close are nearly the same. Signals indecision.
- **Hammer**: Small body at top, long lower wick. Bullish reversal signal.
- **Shooting Star**: Small body at bottom, long upper wick. Bearish reversal.
- **Marubozu**: Full body with no wicks. Strong directional conviction.

### Multi-Candle Patterns
- **Engulfing**: A larger candle completely engulfs the previous one
- **Morning Star**: Three-candle bullish reversal pattern
- **Evening Star**: Three-candle bearish reversal pattern
""",
            "quiz_questions": [
                {
                    "question": "What does a Doji candle indicate?",
                    "options": ["Strong buying pressure", "Strong selling pressure", "Market indecision", "Trend continuation"],
                    "correct_index": 2,
                    "explanation": "A Doji forms when the open and close are nearly equal, indicating indecision between buyers and sellers."
                },
                {
                    "question": "A bullish candle means:",
                    "options": ["The close is lower than the open", "The close is higher than the open", "The high equals the close", "Volume increased"],
                    "correct_index": 1,
                    "explanation": "A bullish candle closes higher than it opened, indicating buying pressure won during that period."
                },
            ],
        },
        {
            "title": "Risk Management Fundamentals",
            "category": "risk",
            "difficulty": "beginner",
            "content": """# Risk Management Fundamentals

Risk management is the most important aspect of trading. Without proper risk management, even the best strategy will eventually blow up your account.

## The 1-2% Rule

Never risk more than 1-2% of your account on a single trade. This ensures you can survive a losing streak.

**Example:**
- Account: $10,000
- Risk per trade: 1% = $100
- Stop loss: 50 pips on EUR/USD
- Position size: $100 / (50 pips x $0.10/pip per micro lot) = 2 micro lots

## Key Metrics

### Risk-Reward Ratio (R:R)
The ratio of potential loss to potential profit. A 1:2 R:R means you risk $1 to make $2.

**Minimum recommended R:R: 1:1.5**

### Maximum Drawdown
The largest peak-to-trough decline in account equity. Keep max drawdown below 20%.

### Position Sizing
Calculate your position size based on:
1. Account size
2. Risk percentage
3. Stop loss distance

**Formula:**
`Position Size = (Account x Risk%) / (Stop Loss in pips x Pip Value)`

## Rules to Live By
1. Always use a stop loss
2. Never move your stop loss further away
3. Don't over-leverage (stay under 5:1 effective leverage)
4. Diversify across uncorrelated pairs
5. Cut losses short, let winners run
""",
            "quiz_questions": [
                {
                    "question": "According to the 1-2% rule, how much should you risk on a $10,000 account?",
                    "options": ["$500-$1000", "$100-$200", "$1000-$2000", "$50-$100"],
                    "correct_index": 1,
                    "explanation": "The 1-2% rule means risking 1-2% of your account balance per trade. On a $10,000 account, that is $100-$200."
                },
                {
                    "question": "What does a 1:2 risk-reward ratio mean?",
                    "options": ["Risk $2 to make $1", "Risk $1 to make $2", "Win 2 out of 1 trades", "Use 2x leverage"],
                    "correct_index": 1,
                    "explanation": "A 1:2 R:R means for every $1 you risk, your target profit is $2. This means you can be profitable even with a win rate below 50%."
                },
                {
                    "question": "What is the recommended maximum drawdown?",
                    "options": ["5%", "10%", "20%", "50%"],
                    "correct_index": 2,
                    "explanation": "Keeping maximum drawdown below 20% helps preserve capital and reduces the psychological pressure of large losses."
                },
            ],
        },
        {
            "title": "Moving Averages Explained",
            "category": "ta",
            "difficulty": "intermediate",
            "content": """# Moving Averages Explained

Moving averages are the foundation of many trading strategies. They smooth out price data to identify trends and potential support/resistance levels.

## Types of Moving Averages

### Simple Moving Average (SMA)
The arithmetic mean of the last N periods.
`SMA = (P1 + P2 + ... + Pn) / N`

### Exponential Moving Average (EMA)
Gives more weight to recent prices, making it more responsive.
`EMA = Price x Multiplier + Previous EMA x (1 - Multiplier)`
Where Multiplier = 2 / (N + 1)

## Common Periods
- **20 EMA**: Short-term trend
- **50 SMA/EMA**: Medium-term trend
- **200 SMA**: Long-term trend (institutional favorite)

## Trading Strategies

### Crossover Strategy
- **Golden Cross**: 50 MA crosses above 200 MA (bullish)
- **Death Cross**: 50 MA crosses below 200 MA (bearish)

### Dynamic Support/Resistance
Price often bounces off key moving averages during trends:
- In uptrends, the 20 EMA acts as dynamic support
- In downtrends, the 20 EMA acts as dynamic resistance

### Multiple MA Ribbon
Using several MAs (e.g., 10, 20, 50, 100, 200) creates a "ribbon" that shows trend strength by the separation between lines.
""",
            "quiz_questions": [
                {
                    "question": "What does a Golden Cross signal?",
                    "options": ["Bearish reversal", "Bullish reversal", "Consolidation", "High volatility"],
                    "correct_index": 1,
                    "explanation": "A Golden Cross occurs when the 50 MA crosses above the 200 MA, signaling a potential bullish trend change."
                },
                {
                    "question": "Which moving average gives more weight to recent prices?",
                    "options": ["SMA", "EMA", "Both equally", "Neither"],
                    "correct_index": 1,
                    "explanation": "The Exponential Moving Average (EMA) uses a multiplier that gives exponentially more weight to recent prices, making it more responsive to current market conditions."
                },
            ],
        },
        {
            "title": "Trading Psychology: Emotions and Discipline",
            "category": "psychology",
            "difficulty": "intermediate",
            "content": """# Trading Psychology

Your biggest enemy in trading is not the market — it is yourself. Mastering psychology is what separates consistently profitable traders from the rest.

## Common Psychological Pitfalls

### Fear
- Fear of losing money leads to cutting winners too early
- Fear of missing out (FOMO) leads to entering bad trades
- Fear of being wrong prevents taking valid setups

### Greed
- Holding positions too long hoping for more profit
- Increasing position size after wins (euphoria)
- Not taking profits at planned levels

### Revenge Trading
After a loss, the urge to immediately "make it back" by taking impulsive trades. This almost always leads to larger losses.

## Building Discipline

### Create a Trading Plan
Write down your exact rules for:
1. Entry criteria
2. Exit criteria (both profit and loss)
3. Position sizing
4. Maximum daily/weekly loss limits

### Keep a Trading Journal
Record every trade with:
- Screenshot of the setup
- Reason for entry
- Emotional state during the trade
- What you would do differently

### The Process Over Results
Focus on executing your plan correctly rather than individual trade outcomes. A trade can be a "good trade" even if it loses money, as long as you followed your rules.

## Mental Models
- **Think in probabilities**: No single trade matters. Think in terms of 100+ trades.
- **The casino analogy**: You are the house. Individual hands don't matter; the edge plays out over time.
- **Detach from money**: Think in R-multiples (1R = your risk per trade), not dollar amounts.
""",
            "quiz_questions": [
                {
                    "question": "What is revenge trading?",
                    "options": ["Trading to recover losses quickly with impulsive trades", "A systematic strategy for reversals", "Trading against the prevailing trend", "Copying another trader's positions"],
                    "correct_index": 0,
                    "explanation": "Revenge trading is the emotional response of trying to quickly recover losses by taking impulsive, unplanned trades. It almost always leads to bigger losses."
                },
                {
                    "question": "Why should you think in probabilities?",
                    "options": ["To predict the next trade outcome", "Because no single trade matters — the edge plays out over many trades", "To calculate exact profit targets", "To avoid using stop losses"],
                    "correct_index": 1,
                    "explanation": "Thinking in probabilities means understanding that any individual trade is random, but over many trades, a strategy with a positive edge will be profitable."
                },
            ],
        },
        {
            "title": "TradeForge Platform Guide",
            "category": "platform",
            "difficulty": "beginner",
            "content": """# TradeForge Platform Guide

Welcome to TradeForge! This guide will walk you through the platform features.

## Navigation

### Dashboard
Your home screen showing account overview, recent activity, and quick stats.

### Data Management
Upload CSV files with historical price data. Supports OHLCV (bar) and tick data formats. The system auto-detects columns.

### Strategy Builder
Build trading strategies using a form-based interface:
1. Select indicators (SMA, EMA, RSI, MACD, Bollinger Bands, ATR)
2. Define entry conditions ("When RSI crosses above 30")
3. Define exit conditions (TP, SL, trailing stop)
4. Set risk management rules

### Backtesting
Test strategies against historical data:
- Select a strategy and data source
- Configure initial balance, spread, commission
- View equity curve, trade log, and statistics

### Optimization
Find the best parameter values for your strategy:
- Bayesian (Optuna): Efficient parameter search
- Genetic Algorithm: Broad exploration
- Hybrid: Best of both worlds
- Walk-Forward validation prevents overfitting

### Live Trading
Connect to brokers (Oanda) to trade live:
- View account balance and equity
- Monitor open positions and orders
- Place new orders with SL/TP
- Risk monitoring dashboard

### Chart
Interactive TradingView charts with indicators and trade markers.

### AI Assistant
Click the chat button (bottom-right) for AI-powered help:
- Strategy suggestions
- Backtest analysis
- Risk assessment
- Educational content
""",
            "quiz_questions": [
                {
                    "question": "Which optimization method combines Bayesian and Genetic approaches?",
                    "options": ["Bayesian", "Genetic", "Hybrid", "Random Search"],
                    "correct_index": 2,
                    "explanation": "The Hybrid method uses Bayesian optimization (Optuna) for efficient search and then refines with a Genetic Algorithm for the best results."
                },
                {
                    "question": "What does Walk-Forward validation help prevent?",
                    "options": ["Slow backtests", "Data loss", "Overfitting", "Broker disconnection"],
                    "correct_index": 2,
                    "explanation": "Walk-Forward validation splits data into in-sample (for optimization) and out-of-sample (for validation), which helps prevent overfitting to historical data."
                },
            ],
        },
    ]

    for article_data in seed_articles:
        article = KnowledgeArticle(
            title=article_data["title"],
            content=article_data["content"],
            category=article_data["category"],
            difficulty=article_data["difficulty"],
            quiz_questions=article_data["quiz_questions"],
            author_id=user.id,
            source_type="manual",
        )
        db.add(article)

    db.commit()
    return {"status": "seeded", "count": len(seed_articles)}
