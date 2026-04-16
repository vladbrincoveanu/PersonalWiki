import json
import logging
import re
import requests
from dataclasses import dataclass
from typing import List
from config import MINIMAX_API_KEY, MINIMAX_MODEL, MINIMAX_API_URL

_logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    text: str
    start_index: int
    end_index: int
    chunk_number: int


_TIMESTAMP_PATTERN_RE = re.compile(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->.+$", re.MULTILINE)
_CHAPTER_MARKER_RE = re.compile(
    r"^\s*(?:\[Chapter|Chapter\s*\d+|#{1,3}\s*|##?)\s*[:.\-]?\s*",
    re.IGNORECASE | re.MULTILINE,
)
_PARAGRAPH_BREAK_RE = re.compile(r"\n\n+")

_MIN_CHUNK_SIZE = 60_000


def _make_fallback_note(raw_text: str, error: bool = True) -> dict:
    """Return a fallback note dict used when API calls fail or are skipped."""
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
        "error": error,
    }


def semantic_chunk(text: str) -> List[Chunk]:
    """Split transcript at natural boundaries with 60k char minimum per chunk (except final chunk)."""
    if len(text) <= _MIN_CHUNK_SIZE:
        return [
            Chunk(
                text=text,
                start_index=0,
                end_index=len(text),
                chunk_number=1,
            )
        ]

    # Try to split at chapter/section markers first
    splits = _find_chapter_splits(text)
    if len(splits) > 1:
        chunks = _build_chunks(text, splits)
        if all(len(c.text) >= _MIN_CHUNK_SIZE or c is chunks[-1] for c in chunks):
            return chunks

    # Try to split at large timestamp gaps (>10s)
    splits = _find_timestamp_gap_splits(text)
    if len(splits) > 1:
        chunks = _build_chunks(text, splits)
        if all(len(c.text) >= _MIN_CHUNK_SIZE or c is chunks[-1] for c in chunks):
            return chunks

    # Try paragraph breaks
    splits = _find_paragraph_splits(text)
    if len(splits) > 1:
        chunks = _build_chunks(text, splits)
        if all(len(c.text) >= _MIN_CHUNK_SIZE or c is chunks[-1] for c in chunks):
            return chunks

    # Fallback: fixed-size with overlap
    return _fixed_chunk(text)


def _find_chapter_splits(text: str) -> List[int]:
    """Find split points at chapter/section markers."""
    matches = list(_CHAPTER_MARKER_RE.finditer(text))
    return [m.start() for m in matches]


def _find_timestamp_gap_splits(text: str) -> List[int]:
    """Find split points at large timestamp gaps (>10s)."""
    timestamps = list(_TIMESTAMP_PATTERN_RE.finditer(text))
    splits = []
    for i in range(1, len(timestamps)):
        prev_end = timestamps[i - 1].end()
        next_start = timestamps[i].start()
        prev_ts = timestamps[i - 1].group()
        next_ts = timestamps[i].group()
        gap = _timestamp_gap(prev_ts, next_ts)
        if gap is not None and gap > 10.0:
            splits.append(next_start)
    return splits


def _timestamp_gap(ts1: str, ts2: str) -> float | None:
    """Parse timestamps and return gap in seconds. Returns None on parse failure."""
    try:
        t1 = _parse_timestamp(ts1)
        t2 = _parse_timestamp(ts2)
        return t2 - t1
    except (ValueError, IndexError):
        return None


def _parse_timestamp(ts: str) -> float:
    """Parse HH:MM:SS,mmm or HH:MM:SS.mmm to seconds."""
    ts = ts.strip().split()[0]
    parts = ts.replace(",", ".").split(":")
    h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
    return h * 3600 + m * 60 + s


def _find_paragraph_splits(text: str) -> List[int]:
    """Find split points at paragraph breaks (\\n\\n)."""
    splits = []
    pos = 0
    while pos < len(text):
        idx = text.find("\n\n", pos)
        if idx == -1:
            break
        splits.append(idx + 2)
        pos = idx + 2
    return splits


def _build_chunks(text: str, splits: List[int]) -> List[Chunk]:
    """Build chunks from a list of split indices."""
    # Deduplicate consecutive boundaries (fixes empty chunk when split==0)
    boundaries = [0] + sorted(set(splits)) + [len(text)]
    deduped: list[int] = []
    for b in boundaries:
        if not deduped or b != deduped[-1]:
            deduped.append(b)
    chunks = []
    for i in range(len(deduped) - 1):
        start = deduped[i]
        end = deduped[i + 1]
        chunk_text = text[start:end]
        chunks.append(
            Chunk(
                text=chunk_text,
                start_index=start,
                end_index=end,
                chunk_number=i + 1,
            )
        )
    return chunks


def _fixed_chunk(text: str) -> List[Chunk]:
    """Fixed-size fallback — sequential 60k chunks, no overlap."""
    chunks = []
    pos = 0
    n = 1
    while pos < len(text):
        end = min(pos + _MIN_CHUNK_SIZE, len(text))
        if pos + _MIN_CHUNK_SIZE < len(text):
            # back up to last newline to avoid cutting mid-word
            nl = text.rfind("\n", pos, end)
            if nl > pos:
                end = nl
        chunk_text = text[pos:end]
        chunks.append(
            Chunk(
                text=chunk_text,
                start_index=pos,
                end_index=end,
                chunk_number=n,
            )
        )
        if end >= len(text):
            break
        pos = end
        n += 1
    return chunks


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
        raw_text=raw_text,
    )


def enrich(raw_text: str, similar_titles: list[str], source: str) -> dict:
    if not MINIMAX_API_KEY:
        _logger.warning("MINIMAX_API_KEY is not set — returning fallback for source=%s", source)
        return _make_fallback_note(raw_text)
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
        # Check for API-level errors
        base_resp = data.get("base_resp", {})
        if base_resp.get("status_code") and base_resp["status_code"] != 0:
            _logger.warning("MiniMax API error %s: %s", base_resp["status_code"], base_resp.get("status_msg"))
            return _make_fallback_note(raw_text)
        if "choices" not in data or not data["choices"]:
            _logger.error("Minimax response missing choices for source=%s", source)
            return _make_fallback_note(raw_text)
        content = data["choices"][0]["message"]["content"]
    except Exception as e:
        _logger.warning("Minimax enrich failed for source=%s: %s", source, e)
        return _make_fallback_note(raw_text)

    try:
        content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(content)
    except (json.JSONDecodeError, AttributeError) as e:
        _logger.warning("Minimax returned invalid JSON for source=%s: %s", source, e)
        return _make_fallback_note(raw_text)

    # Add defaults
    data.setdefault("entities", [])
    data.setdefault("figure_captions", [])
    data.setdefault("why_saved_hint", "")
    data.setdefault("chapters", [])
    data.setdefault("key_quotes", [])
    data.setdefault("topics_covered", [])
    data.setdefault("raw_text", raw_text)
    data.setdefault("error", False)
    return data


_SYNTHESIS_SYSTEM = """You are a knowledge synthesizer. Given analyses of multiple sections of one video, produce one unified research note.
Always respond with valid JSON only — no markdown fences, no explanation."""

_SYNTHESIS_TEMPLATE = """Multiple sections of one video have been analyzed separately.
Your task is to produce ONE unified research note — not a list of section summaries.

The final note must:
- Read as a coherent narrative essay about the video's core ideas
- Weave insights together across sections; don't repeat identical facts verbatim
- Preserve key quotes with speaker attribution
- Structure as: opening thesis → key concepts (with examples) → conclusion / "so what"
- Include chapters extracted across all sections, ordered by timestamp
- Preserve entities, key_facts, and tags from all chunks; deduplicate where overlapping
- summary: 2-3 sentence unified synthesis — NOT a list of chunk summaries

Respond with JSON matching this exact structure:
{{
  "title": "concise descriptive title",
  "type": "video",
  "tags": ["tag1", "tag2"],
  "summary": "2-3 sentence unified synthesis",
  "key_facts": ["fact 1", "fact 2"],
  "cross_links": ["existing-note-slug"],
  "entities": [
    {{"name": "Entity Name", "slug": "entity-name", "type": "concept|person|institution|dataset|method"}}
  ],
  "chapters": [{{"time": "MM:SS", "title": "Chapter title"}}, ...],
  "key_quotes": [{{"text": "quoted text", "speaker": "Speaker name"}}, ...],
  "topics_covered": ["topic1", "topic2"],
  "why_saved_hint": "one sentence about why this is worth keeping"
}}

Section analyses to synthesize:
{section_summaries}

Source: {source}
Existing related notes: {related}
"""


def enrich_video_synthesis(chunk_results: List[dict], source: str, similar_titles: List[str]) -> dict:
    """
    Run synthesis pass: take per-chunk enrichment results, produce one unified narrative note.
    Used for video content where the transcript was split into semantic chunks.
    """
    if not chunk_results:
        return {
            "title": "Untitled", "type": "video", "tags": [], "summary": "",
            "key_facts": [], "cross_links": [], "entities": [], "chapters": [],
            "key_quotes": [], "topics_covered": [], "why_saved_hint": "", "error": True,
        }

    if len(chunk_results) == 1:
        # Single chunk — no synthesis needed, just enrich normally
        r = chunk_results[0].copy()
        r.setdefault("type", "video")
        r.setdefault("error", False)
        # Preserve raw_text from the chunk
        r.setdefault("raw_text", chunk_results[0].get("raw_text", ""))
        return r

    # Build section summaries text
    section_summaries = []
    for i, cr in enumerate(chunk_results, 1):
        summary_text = cr.get("summary", "")
        chapters = cr.get("chapters", [])
        key_quotes = cr.get("key_quotes", [])
        section_summaries.append(
            f"--- Section {i} ---\n"
            f"Title: {cr.get('title', 'Untitled')}\n"
            f"Summary: {summary_text}\n"
            f"Chapters: {chapters}\n"
            f"Key Quotes: {key_quotes}\n"
            f"Entities: {cr.get('entities', [])}\n"
            f"Topics: {cr.get('topics_covered', [])}\n"
        )
    sections_text = "\n".join(section_summaries)
    similar_str = "\n".join(f"- {t}" for t in similar_titles) if similar_titles else "(none yet)"
    prompt = _SYNTHESIS_TEMPLATE.format(
        section_summaries=sections_text,
        source=source,
        related=similar_str,
    )

    if not MINIMAX_API_KEY:
        return {**chunk_results[0], "error": True}

    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MINIMAX_MODEL,
        "messages": [
            {"role": "system", "content": _SYNTHESIS_SYSTEM},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        resp = requests.post(MINIMAX_API_URL, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        base_resp = data.get("base_resp", {})
        if base_resp.get("status_code") and base_resp["status_code"] != 0:
            raise ValueError(f"MiniMax API error {base_resp['status_code']}: {base_resp.get('status_msg')}")
        content = data["choices"][0]["message"]["content"]
        content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(content)
        result.setdefault("entities", [])
        result.setdefault("chapters", [])
        result.setdefault("key_quotes", [])
        result.setdefault("topics_covered", [])
        result.setdefault("key_facts", [])
        result.setdefault("cross_links", [])
        result.setdefault("why_saved_hint", "")
        result.setdefault("error", False)
        # Preserve raw_text from first chunk
        result.setdefault("raw_text", chunk_results[0].get("raw_text", ""))
        return result
    except Exception as e:
        _logger.warning("Synthesis pass failed for source=%s: %s", source, e)
        # Fallback: return first chunk result, don't lose data
        fallback = chunk_results[0].copy()
        fallback["error"] = True
        return fallback
