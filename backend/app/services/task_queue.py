"""Lightweight async task queue for long-running copilot operations.

Runs tasks as asyncio background tasks. When complete, sends notification
via Telegram/email. Stores result for web UI retrieval.

Sufficient for ~40 users — no Redis/Celery dependency needed.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger(__name__)

# ── Task result ──────────────────────────────────────────────────────

class TaskResult:
    __slots__ = (
        "task_id", "user_id", "task_type", "status",
        "result", "error", "started_at", "completed_at",
    )

    def __init__(self, task_id: str, user_id: int, task_type: str):
        self.task_id = task_id
        self.user_id = user_id
        self.task_type = task_type
        self.status = "running"  # running | completed | failed
        self.result: Optional[dict] = None
        self.error: Optional[str] = None
        self.started_at = datetime.now(timezone.utc)
        self.completed_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "task_type": self.task_type,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


# ── In-memory store ──────────────────────────────────────────────────

_tasks: dict[str, TaskResult] = {}


async def enqueue_task(
    user_id: int,
    task_type: str,
    coro: Coroutine,
    notify_message_fn: Optional[Callable[[dict], str]] = None,
) -> str:
    """Enqueue an async task. Returns task_id immediately."""
    task_id = str(uuid.uuid4())[:8]
    task_result = TaskResult(task_id, user_id, task_type)
    _tasks[task_id] = task_result

    async def _run():
        try:
            result = await coro
            task_result.result = result
            task_result.status = "completed"
            task_result.completed_at = datetime.now(timezone.utc)

            # Send notification to user
            try:
                from app.core.database import SessionLocal
                from app.services.notification import notify
                db = SessionLocal()
                try:
                    msg = notify_message_fn(result) if notify_message_fn else f"Task '{task_type}' completed."
                    await notify(db, user_id, f"Task Complete: {task_type}", msg)
                finally:
                    db.close()
            except Exception as e:
                logger.warning("Task notification failed: %s", e)

        except Exception as e:
            task_result.error = str(e)
            task_result.status = "failed"
            task_result.completed_at = datetime.now(timezone.utc)
            logger.exception("Background task %s failed", task_id)

    asyncio.create_task(_run())
    return task_id


def get_task_status(task_id: str) -> Optional[dict]:
    """Get task status and result by ID."""
    t = _tasks.get(task_id)
    if not t:
        return None
    return t.to_dict()


def get_user_tasks(user_id: int, limit: int = 10) -> list[dict]:
    """Get recent tasks for a user."""
    user_tasks = [t for t in _tasks.values() if t.user_id == user_id]
    user_tasks.sort(key=lambda t: t.started_at, reverse=True)
    return [t.to_dict() for t in user_tasks[:limit]]


def cleanup_old_tasks(max_age_hours: int = 24) -> int:
    """Remove completed tasks older than max_age_hours. Returns count removed."""
    now = datetime.now(timezone.utc)
    to_remove = []
    for tid, t in _tasks.items():
        if t.completed_at and (now - t.completed_at).total_seconds() > max_age_hours * 3600:
            to_remove.append(tid)
    for tid in to_remove:
        del _tasks[tid]
    return len(to_remove)
