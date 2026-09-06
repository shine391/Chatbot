"""Health check endpoint."""

from typing import Any

from fastapi import APIRouter

from app.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "healthy",
        "app_name": settings.app_name,
        "environment": settings.app_env.value,
    }
