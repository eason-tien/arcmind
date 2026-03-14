# ── ArcMind Dockerfile ─────────────────────────────────────
# Multi-stage build for smaller image
FROM python:3.12-slim AS base

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install readpst for PST email processing (optional)
RUN apt-get update && apt-get install -y --no-install-recommends \
    pst-utils \
    && rm -rf /var/lib/apt/lists/* || true

WORKDIR /app

# Copy requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directories
RUN mkdir -p data logs outputs

# Expose port
EXPOSE 8100

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8100/health || exit 1

# Entry point
CMD ["python", "main.py"]
