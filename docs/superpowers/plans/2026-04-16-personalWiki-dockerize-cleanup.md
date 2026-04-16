# personalWiki Dockerization + Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Containerize the Python FastAPI app and remove foreign .NET artifacts from the project.

**Architecture:** Multi-stage Python 3.13-slim Dockerfile for the FastAPI app. docker-compose builds locally from the new Dockerfile. Foreign .NET artifacts deleted. The vault is mounted from the iCloud path and the app writes notes there.

**Tech Stack:** Python 3.13, FastAPI, uvicorn, Docker, Docker Compose

---

## File Map

| File | Action |
|------|--------|
| `Dockerfile` (old) | DELETE — .NET build, foreign |
| `docker-compose.yml` | REPLACE — .NET image → Python build |
| `Dockerfile` (new) | CREATE — Python multi-stage build |
| `src/Vke.*/` | DELETE — entire C# solution |
| `vke.sh`, `vke-quick.sh` | DELETE — .NET wrappers |
| `scripts/ingest.csx` | DELETE — C# script |
| `.github/workflows/vke-ingest.yml` | DELETE — .NET CI |
| `IHZwWFHWa-w.en.vtt` | DELETE — subtitle file |
| `default.profraw` | DELETE — profiling artifact |
| `__pycache__/` | DELETE — cache cleanup |
| `.gitignore` | NO CHANGE — already has `__pycache__/` |
| `scripts/migrate_notes_to_typed_templates.py` | KEEP — Python utility |
| `.github/workflows/ci.yml` | KEEP — Python CI |

---

## Pre-flight: Kill Any Existing personalwiki Containers

- [ ] **Step 1: Stop any running personalwiki containers**

```bash
docker stop personalwiki-vke-1 2>/dev/null; docker rm personalwiki-vke-1 2>/dev/null
docker stop aijurnalv2-vke-1 2>/dev/null; docker rm aijurnalv2-vke-1 2>/dev/null
echo "Containers cleared"
```

---

## Task 1: Create New Dockerfile (Python)

**Files:**
- Create: `Dockerfile`

- [ ] **Step 1: Create the new Python Dockerfile**

```dockerfile
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
```

- [ ] **Step 2: Verify file exists**

```bash
test -f Dockerfile && echo "Dockerfile created" || echo "ERROR: Dockerfile missing"
```

---

## Task 2: Replace docker-compose.yml

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Overwrite docker-compose.yml with the new content**

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
```

- [ ] **Step 2: Commit**

```bash
git add docker-compose.yml && git commit -m "fix: replace docker-compose with Python build from local Dockerfile

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 3: Delete .NET Artifacts

**Files:**
- Delete: `src/Vke.Cli/`, `src/Vke.Core/`, `src/Vke.Full/`, `src/Vke.Simple/`, `src/Vke.Web/`
- Delete: `Dockerfile` (old .NET one)
- Delete: `vke.sh`, `vke-quick.sh`
- Delete: `scripts/ingest.csx`
- Delete: `.github/workflows/vke-ingest.yml`

- [ ] **Step 1: Delete all .NET directories**

```bash
rm -rf src/Vke.Cli src/Vke.Core src/Vke.Full src/Vke.Simple src/Vke.Web
echo "Deleted src/Vke.*/"
```

- [ ] **Step 2: Delete old Dockerfile, scripts, and workflows**

```bash
rm -f Dockerfile vke.sh vke-quick.sh scripts/ingest.csx .github/workflows/vke-ingest.yml
echo "Deleted .NET artifacts"
```

- [ ] **Step 3: Verify src/ is empty or has only Python files**

```bash
ls src/
# Expected output: either empty or shows only Python dirs if any exist
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "chore: remove foreign .NET artifacts from project

Removed: src/Vke.*/, old Dockerfile, vke.sh, vke-quick.sh,
        scripts/ingest.csx, vke-ingest.yml

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Delete Junk Files

**Files:**
- Delete: `IHZwWFHWa-w.en.vtt`, `default.profraw`, `__pycache__/`

- [ ] **Step 1: Delete subtitle file and profiling artifact**

```bash
rm -f IHzwWFHWa-w.en.vtt default.profraw
echo "Deleted junk files"
```

- [ ] **Step 2: Delete all __pycache__ directories**

```bash
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; echo "Deleted __pycache__"
```

- [ ] **Step 3: Verify .gitignore has __pycache__ entries**

```bash
grep -E "__pycache__|\.pyc" .gitignore
# Expected: __pycache__/ and *.pyc already present
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "chore: remove junk files from project root

Deleted: IHzwWFHWa-w.en.vtt (subtitle), default.profraw (profiling),
        __pycache__/ (Python bytecode cache)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 5: Build and Verify

**Files:**
- Verify: `Dockerfile`, `docker-compose.yml`

- [ ] **Step 1: Build the Docker image**

```bash
docker compose build 2>&1
# Expected: build completes without error
```

- [ ] **Step 2: Start the container**

```bash
docker compose up -d 2>&1
# Expected: container starts
```

- [ ] **Step 3: Wait for startup and check HTTP response**

```bash
sleep 5 && curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/
# Expected: 200 or 302 (redirect to index)
```

- [ ] **Step 4: Check container logs for startup errors**

```bash
docker compose logs --tail 10
# Expected: "Application startup complete" or similar — no errors
```

- [ ] **Step 5: Verify git status shows only expected files**

```bash
git status --short
# Expected: only Dockerfile, docker-compose.yml, and modified docs/
```

- [ ] **Step 6: Commit final verification**

```bash
git add -A && git commit -m "chore: verify dockerization build and cleanup

- docker compose build succeeds
- container starts and responds on port 8000
- git status shows only expected files

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Expected Final State

```
personalWiki/
├── Dockerfile          # NEW: Python 3.13 multi-stage build
├── docker-compose.yml  # REPLACED: builds Python app, mounts vault
├── app.py              # (unchanged)
├── pipeline.py         # (unchanged)
├── config.py           # (unchanged)
├── core/               # (unchanged)
├── ingesters/          # (unchanged)
├── vault/              # (unchanged)
├── templates/          # (unchanged)
├── requirements.txt    # (unchanged)
├── .env                # (unchanged)
├── .gitignore          # (unchanged — already has __pycache__)
├── scripts/
│   └── migrate_notes_to_typed_templates.py  # (kept)
├── .github/workflows/
│   └── ci.yml          # (kept — Python CI)
└── tests/              # (unchanged)
```

**Deleted:**
- `src/Vke.*/` (C# solution)
- `vke.sh`, `vke-quick.sh`
- `scripts/ingest.csx`
- `.github/workflows/vke-ingest.yml`
- `IHZwWFHWa-w.en.vtt`
- `default.profraw`
- `__pycache__/`
