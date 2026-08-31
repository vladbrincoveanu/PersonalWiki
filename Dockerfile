# Stage 1: builder
# Base pinned by digest (index of python:3.13-slim, Debian trixie), observed 2026-08-31.
FROM python:3.13-slim@sha256:7ce4b6dfe35e55397b7cda544f8a13f191b7ae28dc5aad71fe664dbc9bc2623f AS builder

WORKDIR /app

# Install build deps for yt-dlp, fastembed, docling, and native extensions (mmh3)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gcc \
    g++ \
    python3-dev \
    make \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps from the committed transitive lock.
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt

# Stage 2: runtime
# Same pinned base as the builder stage, observed 2026-08-31.
FROM python:3.13-slim@sha256:7ce4b6dfe35e55397b7cda544f8a13f191b7ae28dc5aad71fe664dbc9bc2623f

WORKDIR /app

# Install runtime deps only (including browser deps for playwright/crawl4ai)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libatspi2.0-0 \
    libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright browser (required by crawl4ai)
RUN pip install playwright && python -m playwright install chromium

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY app.py pipeline.py config.py ./
COPY core/ ./core/
COPY ingesters/ ./ingesters/
COPY vault/ ./vault/
COPY templates/ ./templates/

EXPOSE 8000

# Vault is mounted read-write at container runtime via docker-compose
ENV VAULT_PATH=/vault
ENV INDEX_PATH=/app/.vke_index

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=12 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=3)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
