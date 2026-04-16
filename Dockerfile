# Stage 1: builder
FROM python:3.13-slim AS builder

WORKDIR /app

# Install build deps for yt-dlp, fastembed, docling
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: runtime
FROM python:3.13-slim

WORKDIR /app

# Install runtime deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

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
ENV VAULT_PATH=/vault/notes
ENV INDEX_PATH=/app/.vke_index

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
