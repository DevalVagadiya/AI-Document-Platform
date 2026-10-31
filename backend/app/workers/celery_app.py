"""
Celery application factory.

Design decisions:
- Using Redis as both broker and result backend.
- Task serializer is JSON (never pickle — security risk).
- ``task_always_eager`` is enabled in test environments via override.
- Separate queues for ingestion (CPU-heavy) vs. default (light tasks).
"""

from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "doc_platform",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.workers.document_tasks"],
)

celery_app.conf.update(
    # Serialization (JSON only — no pickle!)
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Retry / reliability
    task_acks_late=True,  # Acknowledge AFTER execution (not before)
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # One task at a time per worker process
    # Result expiry
    result_expires=3600,  # 1 hour
    # Routing — separate queues for heavy vs. light work
    task_default_queue="default",
    task_routes={
        "app.workers.document_tasks.ingest_document": {"queue": "ingestion"},
    },
    # Beat schedule (cron-style tasks)
    beat_schedule={},
)
