# Agents

## Environment Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in LLM_API_KEY
```

The LLM is any OpenAI-compatible chat-completions endpoint, configured entirely
through `.env`:

| Variable | Default |
|---|---|
| `LLM_API_KEY` | *(required)* |
| `LLM_BASE_URL` | `https://api.deepinfra.com/v1/openai` |
| `LLM_MODEL` | `deepseek-ai/DeepSeek-V4-Flash-0731` |
| `LLM_VISION_MODEL` | `Qwen/Qwen3-VL-235B-A22B-Instruct` |

Never commit `.env` — it is gitignored.

## Commands

```bash
python app.py                        # web UI on http://localhost:8000
python -m pytest tests/ -v           # test suite
python -m vault.scanner              # reindex the vault into LanceDB
docker compose up --build            # containerised run (always --build)
```

## Tech Stack

- Python 3.13, FastAPI + HTMX
- LanceDB (vectors) + FastEmbed `BAAI/bge-small-en-v1.5`
- Docling (PDF), Crawl4AI (web), yt-dlp (video)
- pytest
