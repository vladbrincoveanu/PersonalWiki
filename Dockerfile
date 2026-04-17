# Stage 1: builder
FROM python:3.13-slim AS builder

WORKDIR /app

# Install build deps for yt-dlp, fastembed, docling, and native extensions (mmh3)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gcc \
    g++ \
    python3-dev \
    make \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: runtime
FROM python:3.13-slim

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

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
