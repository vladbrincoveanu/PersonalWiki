import json
import logging
import requests
from config import MINIMAX_API_KEY, MINIMAX_MODEL, MINIMAX_API_URL

_logger = logging.getLogger(__name__)

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
  "cross_links": ["existing-note-slug-1", "existing-note-slug-2"],
  "entities": [
    {{"name": "Display Name", "slug": "display-name", "type": "concept|person|institution|dataset|method"}}
  ],
  "figure_captions": ["one-line caption for figure 1 inferred from surrounding text", "caption for figure 2"],
  "why_saved_hint": "one sentence about why this source is worth keeping",
  "chapters": [{{"time": "MM:SS", "title": "Chapter title"}}, ...],
  "key_quotes": [{{"text": "quoted text", "speaker": "Speaker name"}}, ...],
  "topics_covered": ["topic1", "topic2", "topic3"]
}}

Rules:
- entities: extract recurring concepts, people, institutions, datasets, and methods that deserve their own notes. slug must be lowercase with hyphens (e.g. "MIMIC-IV" → "mimic-iv"). Only include entities that appear meaningfully in the content.
- figure_captions: the raw content contains <!-- image --> placeholders where figures appear. Generate one caption per placeholder IN ORDER based on the surrounding text. Return an empty list if there are no <!-- image --> placeholders.
- cross_links: use slugs of existing notes listed below only if genuinely relevant.
- why_saved_hint: one sentence starter for a personal note about relevance — be specific, not generic.
- video type: extract chapters (timestamp + title from transcript markers), key quotes (exact quoted text + speaker attribution), topics covered (list of specific topics)

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
    if not MINIMAX_API_KEY:
        _logger.warning("MINIMAX_API_KEY is not set — returning fallback for source=%s", source)
        return {
            "title": "Untitled",
            "type": "article",
            "tags": [],
            "summary": "",
            "key_facts": [],
            "cross_links": [],
            "entities": [],
            "figure_captions": [],
            "why_saved_hint": "",
            "chapters": [],
            "key_quotes": [],
            "topics_covered": [],
            "raw_text": raw_text,
            "error": True,
        }
    prompt = _build_prompt(raw_text, similar_titles, source)
    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
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
        data = resp.json()
        base_resp = data.get("base_resp", {})
        if base_resp.get("status_code") and base_resp["status_code"] != 0:
            raise ValueError(f"Minimax API error {base_resp['status_code']}: {base_resp.get('status_msg')}")
        if "choices" not in data:
            _logger.error("Minimax unexpected response for source=%s: %s", source, data)
            raise ValueError(f"No 'choices' in Minimax response: {data}")
        content = data["choices"][0]["message"]["content"]
        content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(content)
        data.setdefault("entities", [])
        data.setdefault("figure_captions", [])
        data.setdefault("why_saved_hint", "")
        data.setdefault("chapters", [])
        data.setdefault("key_quotes", [])
        data.setdefault("topics_covered", [])
        data.setdefault("raw_text", raw_text)
        data.setdefault("error", False)
        return data
    except Exception as e:
        _logger.warning("Minimax enrich failed for source=%s: %s", source, e)
        return {
            "title": "Untitled",
            "type": "article",
            "tags": [],
            "summary": "",
            "key_facts": [],
            "cross_links": [],
            "entities": [],
            "figure_captions": [],
            "why_saved_hint": "",
            "chapters": [],
            "key_quotes": [],
            "topics_covered": [],
            "raw_text": raw_text,
            "error": True,
        }
