# YouTube Transcript Summarization Design

## Problem

The current `minimax_client.enrich()` hard-truncates raw_text to 6000 chars before sending to MiniMax. For long-form intellectual videos (20–90 min), this discards 70–90% of the content, causing summaries to miss key points. MiniMax supports 200k total context (prompt + content).

## Solution

Semantic chunking with a 60k char minimum per chunk, per-chunk enrichment, then a synthesis pass to produce one unified narrative note.

```
raw_transcript (full)
       │
       ▼
[ Semantic Chunker ]  ← splits at chapter markers / topic shifts / speaker changes
       │
       ▼
┌──────────────┐
│ Chunk 1 ≥60k │ ──► MiniMax.enrich() ──► chunk_1_result
├──────────────┤
│ Chunk 2 ≥60k │ ──► MiniMax.enrich() ──► chunk_2_result
├──────────────┤
│ Chunk 3 ...  │ ──► MiniMax.enrich() ──► ...
└──────────────┘
       │
       ▼
[ Synthesis Pass ]  ← second LLM call, unified narrative prompt
       │
       ▼
final_note  (one coherent piece)
```

## Chunking Strategy

- **Minimum chunk size:** 60,000 characters. If remaining transcript is smaller than 60k, it becomes the final chunk (no forced padding).
- **Split at natural boundaries** (in priority order):
  1. Explicit chapter/title card markers in transcript (e.g., `[Chapter:]`, `##`, or timestamped section headers)
  2. Long pauses (gaps > 3 seconds in timestamps, indicating topic shift)
  3. Keyword/topic density shift (detect when the dominant n-gram topic changes substantially)
  4. Fallback: split by character count with 10% overlap (so ideas don't get cut mid-sentence)
- **Overlap text** is prepended to the next chunk so context carries across splits.
- Each chunk is passed to `enrich()` with the **existing prompt template** (no changes to `minimax_client.py` internals — the enrichment prompt already handles video type correctly).

## Enrichment

- Each chunk calls `core.minimax_client.enrich(raw_text=chunk, similar_titles=similar_titles, source=source)` as-is.
- Chunk results accumulate: `List[dict]` of per-chunk enriched dicts.

## Synthesis Pass

New function `enrich_video_synthesis(chunk_results: List[dict], source: str, similar_titles: list[str]) -> dict`:

**Prompt:**

```
You are a knowledge synthesizer. Multiple sections of one video have been analyzed separately.
Your task is to produce ONE unified research note — not a list of section summaries.

The final note must:
- Read as a coherent narrative essay about the video's core ideas
- Weave insights together across sections; don't repeat identical facts verbatim
- Preserve key quotes with speaker attribution
- Structure as: opening thesis → key concepts (with examples) → conclusion / "so what"
- Include chapters extracted across all sections, ordered by timestamp
- Preserve entities, key_facts, and tags from all chunks; deduplicate where overlapping

Respond with JSON matching this structure:
{
  "title": "...",
  "type": "video",
  "tags": [...],
  "summary": "2-3 sentence unified synthesis — NOT a list of chunk summaries",
  "key_facts": [...],
  "cross_links": [...],
  "entities": [...],
  "chapters": [{"time": "MM:SS", "title": "..."}],
  "key_quotes": [{"text": "...", "speaker": "..."}],
  "topics_covered": [...],
  "why_saved_hint": "..."
}

Section analyses:
{section_summaries}

Source: {source}
Existing related notes: {similar_titles}
```

## Data Flow

```
extract_youtube(url)
       │
       ▼
Document(raw_text=full_transcript)
       │
       ▼
semantic_chunk(full_transcript)  → List[Chunk]
       │
       ▼
for each chunk:
  enrich(chunk.text, similar, source)  → List[ChunkResult]
       │
       ▼
enrich_video_synthesis(all_chunk_results, source, similar)  → final_note
       │
       ▼
write_vault_note(final_note)
```

## Error Handling

- **Chunk enrichment failure:** if any single chunk fails, fall back to using only the successful chunks (log warning).
- **All chunks fail:** return the existing fallback dict (title="Untitled", error=True).
- **Synthesis failure:** if synthesis pass fails, return the first successful chunk result with a warning (don't lose data).
- **Empty transcript:** pass through `Document(raw_text="", content_type="video")` → quality gate handles.

## Chunk Metadata

Each chunk carries metadata for traceability:

```python
@dataclass
class Chunk:
    text: str
    start_index: int      # position in full transcript
    end_index: int
    chunk_number: int     # 1-indexed
    size_chars: int
```

Chunk results are stored with the chunk metadata so synthesis can order chapters by transcript position.

## Testing

- Unit test `test_semantic_chunking` with known transcript strings (short, medium, oversize) verifying 60k min and boundary logic.
- Unit test `test_synthesis_unified_narrative` verifying merged output is one narrative, not a list of chunk summaries.
- Integration test: ingest a known long video, verify final note has chapters from multiple chunks and summary reads as unified prose.

## File Changes

- `core/minimax_client.py`: add `enrich_video_synthesis()` and `semantic_chunk()` — no changes to existing `enrich()` signature
- `ingesters/youtube.py`: pipe `Document` through new chunk → enrich → synthesis flow
- `tests/test_video_synthesis.py`: new test file
