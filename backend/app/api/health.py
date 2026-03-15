from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["health"])

_DEPLOY_TAG = "2026-03-15-fix-symbol-names"


@router.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "deploy": _DEPLOY_TAG,
    }
