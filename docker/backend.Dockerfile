FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    gcc \
    g++ \
    python3-dev \
    curl \
    ca-certificates \
    libfontconfig1 \
    libgraphite2-3 \
    libicu-dev \
    libssl3 \
    && curl --proto '=https' --tlsv1.2 -fsSL https://drop-sh.fullyjustified.net | sh \
    && mv tectonic /usr/local/bin/ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --default-timeout=100 -r requirements.txt

# Create a non-root user
RUN groupadd -r docaligner && useradd -r -g docaligner docaligner
RUN chown -R docaligner:docaligner /app
USER docaligner

ENV PYTHONPATH=/app
COPY . /app/backend

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
