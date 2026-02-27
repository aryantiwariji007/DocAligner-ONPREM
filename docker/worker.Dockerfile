FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install only essential system dependencies (Postgres client)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONPATH=/app
# Copy code (though volumes will override in dev)
COPY . /app/backend

# Run Celery worker
CMD ["celery", "-A", "backend.app.worker.celery_app", "worker", "--loglevel=info"]
