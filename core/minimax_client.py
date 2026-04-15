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
    size_chars: int


_TIMESTAMP_PATTERN_RE = re.compile(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->.+$", re.MULTILINE)
_CHAPTER_MARKER_RE = re.compile(
    r"^\s*(?:\[Chapter|Chapter\s*\d+|#{1,3}\s*|##?)\s*[:.\-]?\s*",
    re.IGNORECASE | re.MULTILINE,
)
_PARAGRAPH_BREAK_RE = re.compile(r"\n\n+")

_MIN_CHUNK_SIZE = 60_000
_OVERLAP_SIZE = 5_000  # 10% overlap for 60k target


def semantic_chunk(text: str) -> List[Chunk]:
    """
    Split transcript into semantic chunks with 60k char minimum.

    Split priority:
      1. Explicit chapter / section markers (e.g., [Chapter:], ## Title, ---)
      2. Large timestamp gaps (> 10s between consecutive cues)
      3. Paragraph breaks (\n\n) in regions large enough to form a chunk
      4. Fixed-size fallback with 5k char overlap

    Returns list of Chunk objects sorted by position in transcript.
    """
    if len(text) <= _MIN_CHUNK_SIZE:
        return [
            Chunk(
                text=text,
                start_index=0,
                end_index=len(text),
                chunk_number=1,
                size_chars=len(text),
            )
        ]

    # Try to split at chapter markers first
    boundaries = _find_chapter_boundaries(text)
    if len(boundaries) >= 2:
        chunks = _make_chunks(text, boundaries)
        if all(c.size_chars >= _MIN_CHUNK_SIZE for c in chunks[:-1]):
            return chunks

    # Try timestamp-gap splitting
    boundaries = _find_timestamp_gap_boundaries(text)
    if len(boundaries) >= 2:
        chunks = _make_chunks(text, boundaries)
        if all(c.size_chars >= _MIN_CHUNK_SIZE for c in chunks[:-1]):
            return chunks

    # Fallback: fixed-size splits with overlap
    return _fixed_size_chunk(text)


def _find_chapter_boundaries(text: str) -> List[int]:
    """Return start indices of sections preceded by chapter markers."""
    boundaries = [0]
    lines = text.splitlines()
    current_pos = 0
    for i, line in enumerate(lines):
        if _CHAPTER_MARKER_RE.match(line.strip()):
            boundaries.append(current_pos)
        current_pos += len(line) + 1
    # Deduplicate and sort
    boundaries = sorted(set(boundaries))
    # Ensure last boundary is not too close to end
    if boundaries[-1] > len(text) - _MIN_CHUNK_SIZE:
        boundaries = boundaries[:-1]
    return boundaries


def _find_timestamp_gap_boundaries(text: str) -> List[int]:
    """Return start indices where a large timestamp gap (>10s) occurs."""
    timestamps = [
        m.start() for m in _TIMESTAMP_PATTERN_RE.finditer(text)
    ]
    boundaries = [0]
    for i in range(1, len(timestamps)):
        gap = timestamps[i] - timestamps[i - 1]
        if gap > 10_000:  # 10 seconds of transcript gap → topic shift
            boundaries.append(timestamps[i])
    return sorted(set(boundaries))


def _make_chunks(text: str, boundaries: List[int]) -> List[Chunk]:
    """Build Chunk list from a sorted list of start indices."""
    chunks = []
    for i, start in enumerate(boundaries):
        if i < len(boundaries) - 1:
            end = boundaries[i + 1]
        else:
            end = len(text)
        chunk_text = text[start:end]
        chunks.append(
            Chunk(
                text=chunk_text,
                start_index=start,
                end_index=end,
                chunk_number=i + 1,
                size_chars=len(chunk_text),
            )
        )
    return chunks


def _fixed_size_chunk(text: str) -> List[Chunk]:
    """Fallback: split into ~60k char chunks at natural boundaries."""
    chunks = []
    pos = 0
    chunk_num = 1
    while pos < len(text):
        end = min(pos + _MIN_CHUNK_SIZE, len(text))
        is_last = pos + _MIN_CHUNK_SIZE >= len(text)
        if is_last:
            # Last chunk — take all remaining (even if < 60k)
            chunk_text = text[pos:]
        else:
            # Try to split at a paragraph break to avoid cutting mid-sentence
            chunk_text = text[pos:end]
            last_break = chunk_text.rfind("\n\n")
            if last_break > _MIN_CHUNK_SIZE // 2:
                end = pos + last_break + 2
                chunk_text = text[pos:end]
            else:
                # No good break found — use fixed boundary
                chunk_text = text[pos:end]
        chunks.append(
            Chunk(
                text=chunk_text,
                start_index=pos,
                end_index=end,
                chunk_number=chunk_num,
                size_chars=len(chunk_text),
            )
        )
        chunk_num += 1
        pos = end
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
        r = chunk_results[0]
        r.setdefault("type", "video")
        r.setdefault("error", False)
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
        return result
    except Exception as e:
        _logger.warning("Synthesis pass failed for source=%s: %s", source, e)
        # Fallback: return first chunk result, don't lose data
        fallback = chunk_results[0].copy()
        fallback["error"] = True
        return fallback
