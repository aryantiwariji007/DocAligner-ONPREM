from celery import Celery
from kombu import Queue
import os

# Env vars
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "worker",
    broker=REDIS_URL,
    backend=REDIS_URL
)

# Include tasks module so tasks are registered on worker startup
celery_app.conf.include = ["backend.app.tasks"]

celery_app.conf.task_default_queue = "celery"

# Tune for batching
celery_app.conf.worker_prefetch_multiplier = 3  # Allow more messages for batching window
celery_app.conf.task_routes = {
    "backend.app.tasks.validate_document_task_stage1": {"queue": "stage1-fast"},
    "backend.app.tasks.validate_document_task_stage2": {"queue": "stage2-slow"},
    "backend.app.tasks.revalidate_folder_task": {"queue": "stage2-slow"}, # Full sweeps can go to slow
    "backend.app.tasks.validate_document_task": {"queue": "stage2-slow"}, # Legacy fallback
}

celery_app.conf.task_queues = [
    Queue("celery"),
    Queue("stage1-fast"),
    Queue("stage2-slow"),
]
