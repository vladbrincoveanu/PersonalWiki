# personalWiki Dockerization + Cleanup Design

## Status
Draft

## Goal
Containerize the Python FastAPI app and remove foreign .NET artifacts from the project.

---

## Context

`personalWiki` is a Python-based automated knowledge capture pipeline. It ingests URLs, PDFs, YouTube videos, tweets, and news articles — enriching them with MiniMax LLM and writing structured Obsidian markdown notes to a vault.

The project was contaminated with .NET artifacts from the `aiJurnalV2` project (a separate Verified Knowledge Engine). The `docker-compose.yml` currently pulls `aijurnalv2/vke:latest` — a pre-built .NET Docker image that has **nothing to do** with the Python app.

The Obsidian vault lives on iCloud and must remain untouched.

---

## What to Delete

All .NET / foreign artifacts completely unrelated to the Python project:

| Path | Reason |
|------|--------|
| `src/Vke.*/` | C# .NET solution — foreign architecture |
| `Dockerfile` | .NET multi-stage build targeting `Vke.Web.dll` |
| `vke.sh` | Calls `dotnet Vke.Full.dll` |
| `vke-quick.sh` | Calls `dotnet Vke.Simple.dll` |
| `scripts/ingest.csx` | C# scripting file |
| `.github/workflows/vke-ingest.yml` | .NET/CI workflow for VKE CLI |
| `IHZwWFHWa-w.en.vtt` | 29KB YouTube subtitle file at root level |
| `default.profraw` | LLVM profiling artifact |
| `__pycache__/` | Python bytecode cache (wrong-Python runs) |

**Keep:**
- `scripts/migrate_notes_to_typed_templates.py` — Python utility for re-enriching notes
- `.github/workflows/ci.yml` — Python CI workflow

---

## New Dockerfile

Multi-stage build for the Python FastAPI app.

### Module: Dockerfile
- **Responsibility:** Containerize the Python FastAPI app with all dependencies
- **Interface:** Builds image,Exposes port 8000, reads env vars and vault path
- **Dependencies:** Python 3.13, system packages (yt-dlp, ffmpeg)
- **Size target:** ~50 lines

```dockerfile
# Stage 1: builder
FROM python:3.13-slim AS builder

WORKDIR /app

# Install build deps
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
```

---

## Fixed docker-compose.yml

### Module: docker-compose.yml
- **Responsibility:** Run the Python app in Docker with vault access and env vars
- **Interface:** Port 8000 exposed, vault mounted, env vars injected
- **Dependencies:** .env file for secrets
- **Size target:** ~25 lines

```yaml
services:
  personalwiki:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ${VAULT_PATH:-/Users/vladbrincoveanu/Library/Mobile Documents/iCloud~md~obsidian/Documents/PersonalWiki}:/vault
    env_file:
      - .env
    environment:
      - VAULT_PATH=/vault/notes
      - INDEX_PATH=/app/.vke_index
    restart: unless-stopped
    # Vault is read-write — app writes notes here, Obsidian reads from same vault
```

Changes from current:
- Removed `version: "3.8"` (obsolete)
- Changed `image: aijurnalv2/vke:latest` → `build: .`
- Mount vault as **read-write** (app writes notes, Obsidian reads)
- Dropped `mem_limit` and `cpus` (can be re-added if needed)

---

## Cleanup of __pycache__

```bash
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -name "*.pyc" -delete 2>/dev/null
```

Also add to `.gitignore` if not already present.

---

## Verification

After cleanup and dockerization:
1. `docker compose build` completes without error
2. `docker compose up -d` starts the container
3. `curl http://localhost:8000/` returns HTTP 200
4. Ingest a test URL and verify note lands in vault
5. `git status` shows only relevant Python files

---

## Out of Scope

- Any changes to the Python app source code (UI fixes, etc.)
- Changes to the Obsidian vault
- Migration of any .NET functionality
- Changing the vault path or iCloud setup
