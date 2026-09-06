"""Celery application and scheduled task definitions."""

import asyncio
import os
from typing import Any

from celery import Celery  # type: ignore[import-not-found]

from app.config import get_settings

settings = get_settings()
redis_url = os.environ.get("REDIS_URL", settings.redis_url)

celery_app = Celery(
    "chatbot_tasks",
    broker=redis_url,
    backend=redis_url,
)
app = celery_app
celery = celery_app

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "followup-care-every-30-minutes": {
            "task": "app.tasks.celery_app.run_followup_scheduler_task",
            "schedule": 1800.0,  # Every 30 minutes
        },
    },
)


@celery_app.task(name="app.tasks.celery_app.run_followup_scheduler_task")  # type: ignore[untyped-decorator]
def run_followup_scheduler_task() -> dict[str, Any]:
    """Celery task wrapper around async execute_followup_jobs."""
    from app.services.followup_scheduler import execute_followup_jobs

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(execute_followup_jobs())
        return result
    finally:
        loop.close()
