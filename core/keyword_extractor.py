# core/keyword_extractor.py
"""
Extract candidate keywords from a newly written note.
Uses MiniMax to analyze note content and suggest 3-5 new search keywords.
"""
import logging
import requests
from config import MINIMAX_API_KEY, MINIMAX_MODEL, MINIMAX_API_URL

_logger = logging.getLogger(__name__)

_KEYWORD_PROMPT = """Given this note, extract 3-5 specific search keywords that would find similar, related content.

Title: {title}
Content preview: {content}

Rules:
- Keywords should be specific, searchable topics (not generic: avoid "article", "post", "video")
- Prioritize technical terms, proper nouns, and specific methodologies
- Return as a JSON array of strings: ["keyword1", "keyword2", "keyword3"]

Return ONLY the JSON array, nothing else."""


def extract_keywords_from_note(title: str, raw_text: str) -> list[str]:
    if not MINIMAX_API_KEY:
        _logger.debug("No MINIMAX_API_KEY — skipping keyword extraction")
        return []

    if not raw_text or len(raw_text.strip()) < 100:
        return []

    prompt = _KEYWORD_PROMPT.format(title=title, content=raw_text[:3000])
    try:
        resp = requests.post(
            MINIMAX_API_URL,
            headers={"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": MINIMAX_MODEL,
                "messages": [
                    {"role": "system", "content": "You are a keyword extraction assistant. Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=20,
        )
        resp.raise_for_status()
        content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        import json
        keywords = json.loads(content)
        return [k for k in keywords if isinstance(k, str) and len(k) > 2][:5]
    except Exception as e:
        _logger.debug("Keyword extraction failed: %s", e)
        return []
