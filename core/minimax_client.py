import json
import requests
from config import MINIMAX_API_KEY, MINIMAX_GROUP_ID, MINIMAX_MODEL, MINIMAX_API_URL

_SYSTEM_PROMPT = """You are a knowledge curator. Given raw text from a source, extract and structure it into a research note.
Always respond with valid JSON only — no markdown fences, no explanation."""

_NOTE_TEMPLATE = """
Analyze this content and respond with JSON in exactly this structure:
{{
  "title": "concise descriptive title",
  "type": "paper|article|video|personal",
  "tags": ["tag1", "tag2", "tag3"],
  "summary": "2-3 sentence synthesis of the main insight",
  "key_facts": ["fact 1", "fact 2", "fact 3"],
  "cross_links": ["existing-note-slug-1", "existing-note-slug-2"]
}}

Source: {source}

Existing notes in my vault that may be related (use their slugs for cross_links only if genuinely relevant):
{similar}

Raw content to analyze:
{raw_text}
"""


def _build_prompt(raw_text: str, similar_titles: list[str], source: str) -> str:
    similar_str = "\n".join(f"- {t}" for t in similar_titles) if similar_titles else "(none yet)"
    return _NOTE_TEMPLATE.format(
        source=source,
        similar=similar_str,
        raw_text=raw_text[:6000],
    )


def enrich(raw_text: str, similar_titles: list[str], source: str) -> dict:
    prompt = _build_prompt(raw_text, similar_titles, source)
    headers = {
        "Authorization": f"Bearer {MINIMAX_GROUP_ID}:{MINIMAX_API_KEY}" if MINIMAX_GROUP_ID else f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MINIMAX_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        resp = requests.post(MINIMAX_API_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        # Strip markdown fences if model wraps anyway
        content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(content)
        data.setdefault("raw_text", raw_text)
        data.setdefault("error", False)
        return data
    except Exception:
        return {
            "title": "Untitled",
            "type": "article",
            "tags": [],
            "summary": "",
            "key_facts": [],
            "cross_links": [],
            "raw_text": raw_text,
            "error": True,
        }
