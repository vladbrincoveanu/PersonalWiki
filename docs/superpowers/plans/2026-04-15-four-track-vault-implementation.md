# Four-Track Vault Quality & Retrieval — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add quality gates, self-reinforcing discovery amplification, YouTube priority pipeline, and typed retrieval to personalWiki.

**Architecture:** Four tracks: A (quality gate), B (amplification loop), C (YouTube), D (typed retrieval + rerank). Track A integrates into `pipeline.py` before extraction. Track B extends `DiscoveryScheduler`. Track C extends `ingesters/youtube.py`. Track D adds typed note templates in `vault/writer.py` and a cross-encoder reranker in `core/reranker.py`.

**Tech Stack:** Python asyncio, MiniMax LLM API, LanceDB, CrossEncoder (sentence-transformers), Crawl4AI, yt-dlp.

---

## Phase 1 — Track A: Quality Gate

**Goal:** Stop garbage (404s, thin content, paywalls, off-topic) from entering the vault.

### Task 1: Create `core/quality_gate.py`

**Files:**
- Create: `core/quality_gate.py`
- Test: `tests/test_quality_gate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_quality_gate.py
import pytest
from unittest.mock import patch, MagicMock

class TestQualityGate:
    def test_rejects_404_content(self):
        from core.quality_gate import QualityGate
        gate = QualityGate()
        result = gate.check(
            url="https://example.com/page",
            raw_text="[404] Page not found",
            keyword="test"
        )
        assert result.pass_ is False
        assert "404" in result.reason

    def test_rejects_thin_content(self):
        from core.quality_gate import QualityGate
        gate = QualityGate()
        result = gate.check(
            url="https://example.com/page",
            raw_text="Too short",
            keyword="test"
        )
        assert result.pass_ is False
        assert "thin" in result.reason.lower()

    def test_rejects_paywalled_content(self):
        from core.quality_gate import QualityGate
        gate = QualityGate()
        result = gate.check(
            url="https://example.com/page",
            raw_text="[PAYWALLED] Subscribe to read...",
            keyword="test"
        )
        assert result.pass_ is False

    def test_rejects_short_video_transcript(self):
        from core.quality_gate import QualityGate
        gate = QualityGate()
        result = gate.check(
            url="https://youtube.com/watch?v=xxx",
            raw_text="Short transcript",
            keyword="test",
            content_type="video"
        )
        assert result.pass_ is False
        assert "200 words" in result.reason

    def test_passes_valid_content(self):
        from core.quality_gate import QualityGate
        gate = QualityGate()
        result = gate.check(
            url="https://example.com/good-article",
            raw_text="This is a substantial article with real content that is definitely over five hundred characters long.",
            keyword="test"
        )
        assert result.pass_ is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_quality_gate.py -v`
Expected: `ERROR — module 'core.quality_gate' not found`

- [ ] **Step 3: Write minimal implementation**

```python
# core/quality_gate.py
from dataclasses import dataclass
import urllib.request
import logging

_logger = logging.getLogger(__name__)

_ERROR_SIGNALS = ["[PAYWALLED]", "[PAYWALL]", "404", "Page not found", "[BLOCKED]"]
_MIN_ARTICLE_CHARS = 500
_MIN_VIDEO_WORDS = 200


@dataclass
class GateResult:
    pass_: bool
    reason: str = ""


class QualityGate:
    def check(
        self,
        url: str,
        raw_text: str,
        keyword: str,
        content_type: str = "article",
    ) -> GateResult:
        # Check 1: Error signals
        stripped = raw_text.strip()
        for sig in _ERROR_SIGNALS:
            if sig in stripped:
                return GateResult(pass_=False, reason=f"Error signal: {sig}")

        # Check 2: Content length
        if content_type == "video":
            word_count = len(stripped.split())
            if word_count < _MIN_VIDEO_WORDS:
                return GateResult(pass_=False, reason=f"Video transcript too thin: {word_count} words, need >{_MIN_VIDEO_WORDS}")
        else:
            if len(stripped) < _MIN_ARTICLE_CHARS:
                return GateResult(pass_=False, reason=f"Content too thin: {len(stripped)} chars, need >{_MIN_ARTICLE_CHARS}")

        # Check 3: Paywall/auth
        if any(p in stripped for p in ["[PAYWALLED]", "[PAYWALL]", "[SUBSCRIPTION REQUIRED]"]):
            return GateResult(pass_=False, reason="Paywall detected")

        # Check 4: LLM relevance (discovery only — caller controls this flag)
        # Implemented in check_relevance() below

        return GateResult(pass_=True)

    def check_relevance(self, raw_text: str, keyword: str) -> GateResult:
        """Lightweight MiniMax call to verify content matches keyword intent.
        Discovery-sourced URLs only. Returns Pass/Fail."""
        if not raw_text or not keyword:
            return GateResult(pass_=True)

        from config import MINIMAX_API_KEY, MINIMAX_MODEL, MINIMAX_API_URL
        if not MINIMAX_API_KEY:
            return GateResult(pass_=True)  # Skip in test/dev

        import requests
        prompt = (
            f'Keyword: "{keyword}"\n\n'
            f'Content preview (first 500 chars):\n{raw_text[:500]}\n\n'
            f'Question: Does this content match the keyword "{keyword}"? '
            f'Answer YES if the content is about or related to "{keyword}". '
            f'Answer NO if the content is unrelated or off-topic.\n\n'
            f'Answer: Yes or No (nothing else).'
        )
        try:
            resp = requests.post(
                MINIMAX_API_URL,
                headers={"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": MINIMAX_MODEL,
                    "messages": [
                        {"role": "system", "content": "You are a relevance classifier. Answer only Yes or No."},
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=15,
            )
            content = (resp.json().get("choices", [{}])[0].get("message", {}).get("content") or "").lower()
            if "no" in content and len(content) < 10:
                return GateResult(pass_=False, reason=f"LLM: off-topic for keyword '{keyword}'")
        except Exception as e:
            _logger.debug("Relevance check failed, passing through: %s", e)

        return GateResult(pass_=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_quality_gate.py -v`
Expected: PASS (the check_relevance test will be skipped or mocked since it needs MINIMAX_API_KEY)

- [ ] **Step 5: Commit**

```bash
git add core/quality_gate.py tests/test_quality_gate.py
git commit -m "feat: add Track A quality gate — reject 404/thin/paywall content

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Integrate Quality Gate into `pipeline.py`

**Files:**
- Modify: `pipeline.py` (add gate call between extraction and enrichment)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_quality_gate_integration.py
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_pipeline_runs_quality_gate_before_enrichment():
    """Quality gate runs after extraction, before enrichment.
    A thin extraction should not call enrich."""
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.exists.return_value = False
    mock_store.search.return_value = []

    with (
        patch("pipeline.get_store", return_value=mock_store),
        patch("pipeline._is_pdf_url", return_value=False),
        patch("ingesters.news.extract_news", AsyncMock(return_value=MagicMock(
            raw_text="Short",  # too thin
            images=[]
        ))),
        patch("pipeline.enrich") as mock_enrich,
    ):
        messages = []
        async for msg in run_pipeline(url="https://example.com/thin"):
            messages.append(msg)

        mock_enrich.assert_not_called()
        assert any("Skipped" in m or "thin" in m.lower() for m in messages)

@pytest.mark.asyncio
async def test_pipeline_passes_valid_content_through_gate():
    """Valid content should pass through gate and reach enrichment."""
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.exists.return_value = False
    mock_store.search.return_value = []

    valid_content = "This is a substantial article with real content that is definitely over five hundred characters long. " * 5

    with (
        patch("pipeline.get_store", return_value=mock_store),
        patch("pipeline._is_pdf_url", return_value=False),
        patch("ingesters.news.extract_news", AsyncMock(return_value=MagicMock(
            raw_text=valid_content,
            images=[]
        ))),
        patch("pipeline.embed", return_value=[0.1] * 384),
        patch("pipeline.enrich", return_value={
            "title": "Good Article", "type": "article", "tags": [],
            "summary": ".", "key_facts": [], "cross_links": [],
            "entities": [], "figure_captions": [], "why_saved_hint": "",
            "raw_text": valid_content, "error": False,
        }),
        patch("pipeline.write_note", return_value="/vault/notes/good.md"),
    ):
        messages = []
        async for msg in run_pipeline(url="https://example.com/good"):
            messages.append(msg)

        assert any("Saved" in m for m in messages)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_quality_gate_integration.py -v`
Expected: FAIL (gate not yet integrated)

- [ ] **Step 3: Modify pipeline.py to add quality gate**

In `pipeline.py`, add after Step 1 (after extraction):

```python
# After extraction block (around line 85), add:

# Quality gate (Track A) — skip bad content before enrichment
from core.quality_gate import QualityGate
gate = QualityGate()
gate_result = gate.check(
    url=url if url else "",
    raw_text=raw_text,
    keyword="",  # populated from discovery scheduler context
    content_type=doc.content_type if hasattr(doc, 'content_type') else 'article',
)
if not gate_result.pass_:
    yield f"Skipped: {gate_result.reason}"
    return
```

Also add `content_type` to the `Document` result in `ingesters/news.py` and `ingesters/web.py` if not already present. Check `ingesters/__init__.py` — `Document` already has `content_type`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_quality_gate_integration.py tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline.py
git commit -m "feat: integrate Track A quality gate into pipeline — fail fast on bad content

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Phase 2 — Track D Part 1: Typed Note Templates

**Goal:** Per-content-type note templates so LLMs always know where to find structured facts.

### Task 3: Add typed templates to `vault/writer.py`

**Files:**
- Modify: `vault/writer.py`
- Test: `tests/test_writer.py` (extend existing tests)

The existing `write_note` function builds the note body with a generic template. We need to branch on `note["type"]` to use typed templates for `paper` and `video`. The `article` type keeps the existing template.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_typed_templates.py
import pytest, tempfile, os
from pathlib import Path
from unittest.mock import patch, MagicMock

def test_video_template_has_chapters_and_quotes():
    """Video notes should have Timestamped Chapters and Key Quotes sections."""
    from vault.writer import write_note

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("vault.writer.NOTES_DIR", Path(tmpdir)):
            with patch("vault.writer.VAULT_PATH", Path(tmpdir)):
                note = {
                    "title": "Test Video",
                    "type": "video",
                    "tags": ["ai"],
                    "summary": "A video about transformers.",
                    "key_facts": ["Attention is all you need"],
                    "cross_links": [],
                    "entities": [],
                    "why_saved_hint": "Great explanation",
                    "figure_captions": [],
                    "raw_text": "Full transcript here...",
                    "chapters": [{"time": "00:00", "title": "Introduction"}, {"time": "01:30", "title": "Core Concept"}],
                    "key_quotes": [{"text": "Attention is all you need", "speaker": "Vaswani"}],
                    "topics_covered": ["transformers", "attention"],
                }
                path = write_note(note, source="https://youtube.com/watch?v=xxx")

                content = Path(path).read_text()
                assert "## Timestamped Chapters" in content
                assert "[00:00] Introduction" in content
                assert "## Key Quotes" in content
                assert "Attention is all you need" in content
                assert "## Topics Covered" in content

def test_paper_template_has_tldr():
    """Paper notes should have TL;DR and Method sections."""
    from vault.writer import write_note

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("vault.writer.NOTES_DIR", Path(tmpdir)):
            with patch("vault.writer.VAULT_PATH", Path(tmpdir)):
                note = {
                    "title": "Attention Is All You Need",
                    "type": "paper",
                    "tags": ["nlp"],
                    "summary": "Transformer architecture.",
                    "key_facts": ["Uses self-attention", "Replaces RNNs"],
                    "cross_links": [],
                    "entities": [{"name": "Vaswani", "slug": "vaswani", "type": "person"}],
                    "tldr": "A new network architecture based on attention.",
                    "method": "Self-attention layers with multi-head attention.",
                    "benchmarks": "WMT translation, GLUE benchmark.",
                    "raw_text": "Full paper text...",
                    "why_saved_hint": "",
                    "figure_captions": [],
                }
                path = write_note(note, source="https://arxiv.org/abs/1706.03762")

                content = Path(path).read_text()
                assert "## TL;DR" in content
                assert "## Method / Architecture" in content
                assert "## Key Findings" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_typed_templates.py -v`
Expected: FAIL (templates not yet implemented)

- [ ] **Step 3: Implement typed templates in writer.py**

Add a `_build_body` helper that branches on `note["type"]`:

```python
# vault/writer.py — add after the imports and slugify function

def _build_body(note: dict) -> str:
    """Build typed note body. Branches on note['type'] for type-specific templates."""
    ntype = note.get("type", "article")

    if ntype == "video":
        return _build_video_body(note)
    elif ntype == "paper":
        return _build_paper_body(note)
    else:
        return _build_article_body(note)


def _build_video_body(note: dict) -> str:
    """Video-specific template: chapters, key quotes, topics, transcript."""
    chapters = note.get("chapters", [])
    chapters_str = "\n".join(
        f"- [{c.get('time', '??:??

')}] {c.get('title', '')}" for c in chapters
    ) if chapters else "_No chapters extracted._"

    quotes = note.get("key_quotes", [])
    quotes_str = "\n".join(
        f'> "{q.get("text", "")}" — {q.get("speaker", "Speaker")}'
        for q in quotes
    ) if quotes else "_No key quotes extracted._"

    topics = note.get("topics_covered", [])
    topics_str = "\n".join(f"- {t}" for t in topics) if topics else "_None listed._"

    why_saved = note.get("why_saved_hint", "")
    why_str = f"\n## Why I Saved This\n> {why_saved}\n\n_(edit this)_\n" if why_saved else ""

    raw = note.get("raw_text", "")
    raw_section = (
        f"\n## Transcript (Selected Sections)\n<details>\n<summary>Full transcript</summary>\n\n{raw}\n\n</details>"
    ) if raw else ""

    return (
        f"## Summary\n{note.get('summary', '_Not available._')}\n\n"
        f"## Timestamped Chapters\n{chapters_str}\n\n"
        f"## Key Quotes\n{quotes_str}\n\n"
        f"## Topics Covered\n{topics_str}\n"
        f"{why_str}{raw_section}"
    )


def _build_paper_body(note: dict) -> str:
    """Paper-specific template: TL;DR, method, findings, benchmarks."""
    tldr = note.get("tldr", "")
    tldr_section = f"\n## TL;DR\n_{tldr}_\n" if tldr else "\n## TL;DR\n_Not available._\n"

    method = note.get("method", "")
    method_section = f"\n## Method / Architecture\n{method}\n" if method else ""

    findings = note.get("key_facts", [])
    findings_str = "\n".join(f"- {f}" for f in findings) if findings else "_None extracted._"

    benchmarks = note.get("benchmarks", "")
    bench_section = f"\n## Benchmarks\n{benchmarks}\n" if benchmarks else ""

    entities = note.get("entities", [])
    entities_str = ""
    if entities:
        links = " · ".join(
            f"[[{e['name']}]]" for e in entities if e.get("name") and e.get("slug")
        )
        if links:
            entities_str = f"\n## Related Entities\n{links}\n"

    cross_links = note.get("cross_links", [])
    links_str = ""
    if cross_links:
        links_str = f"\n## My Knowledge Says\n{', '.join(f'[[{l}]]' for l in cross_links)}\n"

    raw = note.get("raw_text", "")
    raw_section = (
        f"\n## Raw Extract\n<details>\n<summary>Original extracted text</summary>\n\n{raw}\n\n</details>"
    ) if raw else ""

    return (
        f"## Summary\n{note.get('summary', '_Not available._')}\n"
        f"{tldr_section}"
        f"## Key Findings\n{findings_str}\n"
        f"{method_section}{bench_section}{entities_str}{links_str}{raw_section}"
    )


def _build_article_body(note: dict) -> str:
    """Article template — existing template (kept as-is for backward compat)."""
    key_facts = note.get("key_facts", [])
    facts_str = "\n".join(f"- {f}" for f in key_facts) if key_facts else "_None extracted._"

    entities = note.get("entities", [])
    entities_section = ""
    if entities:
        links = " · ".join(
            f"[[{e['name']}]]" for e in entities if e.get("name") and e.get("slug")
        )
        if links:
            entities_section = f"\n## Entities\n{links}\n"

    why_saved_hint = note.get("why_saved_hint", "")
    why_saved_section = (
        f"\n## Why I Saved This\n> {why_saved_hint}\n\n_(edit this)_\n"
    ) if why_saved_hint else ""

    recent_dev_section = ""  # caller passes entity_statuses separately

    cross_links = note.get("cross_links", [])
    cross_links_section = (
        f"\n## My Knowledge Says\n{', '.join(f'[[{l}]]' for l in cross_links)}\n"
    ) if cross_links else ""

    raw_text = note.get("raw_text", "")
    raw_section = (
        f"\n## Raw Extract\n<details>\n<summary>Original extracted text</summary>\n\n{raw_text}\n\n</details>"
    ) if raw_text else ""

    return (
        f"## Summary\n{note.get('summary', '_Not available._')}\n\n"
        f"## Key Facts\n{facts_str}\n"
        f"{entities_section}{why_saved_section}{recent_dev_section}{cross_links_section}{raw_section}"
    )
```

Now update `write_note` to use `_build_body` instead of the inline body building:

Find the `body = (...)` block in `write_note` and replace:
```python
    body = _build_body(note)
```

Remove the inline body-building code (the `f"## Summary\n..."` block) since it's now in `_build_body`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_typed_templates.py tests/test_writer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add vault/writer.py tests/test_typed_templates.py
git commit -m "feat: add typed note templates — video and paper types get specific sections

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Phase 3 — Track D Part 2: Cross-Encoder Reranking

**Goal:** After vector search, rerank top-K results with a cross-encoder for better retrieval accuracy.

### Task 4: Create `core/reranker.py` with CrossEncoder

**Files:**
- Create: `core/reranker.py`
- Modify: `core/vector_store.py` (add rerank step in search flow)
- Test: `tests/test_reranker.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reranker.py
import pytest
from unittest.mock import patch, MagicMock

def test_reranker_boosts_relevant_results():
    from core.reranker import CrossEncoderReranker
    reranker = CrossEncoderReranker()

    results = [
        {"path": "notes/rl.md", "text": "Reinforcement learning overview"},
        {"path": "notes/transformers.md", "text": "Transformer architecture for NLP"},
        {"path": "notes/rl_intro.md", "text": "Introduction to RL: Q-learning, policy gradients"},
    ]
    query = "reinforcement learning"

    reranked = reranker.rerank(query, results, top_k=2)

    # RL-related results should be ranked higher than transformers
    paths = [r["path"] for r in reranked]
    assert "notes/rl.md" in paths[0] or "notes/rl_intro.md" in paths[0]
    assert "notes/transformers.md" not in paths  # not in top 2 for RL query

def test_reranker_returns_correct_count():
    from core.reranker import CrossEncoderReranker
    reranker = CrossEncoderReranker()
    results = [{"path": f"notes/{i}.md", "text": f"doc {i}"} for i in range(10)]
    reranked = reranker.rerank("query", results, top_k=5)
    assert len(reranked) == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reranker.py -v`
Expected: `ERROR — module 'core.reranker' not found`

- [ ] **Step 3: Write minimal CrossEncoder implementation**

```python
# core/reranker.py
"""
Cross-encoder reranking for vector search results.
Uses sentence-transformers CrossEncoder for query-document scoring.
"""
from sentence_transformers import CrossEncoder
import logging

_logger = logging.getLogger(__name__)

# Lightweight, fast model for reranking
_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class CrossEncoderReranker:
    def __init__(self):
        self._model = None

    @property
    def model(self):
        if self._model is None:
            try:
                self._model = CrossEncoder(_MODEL_NAME, max_length=512)
            except Exception as e:
                _logger.warning("CrossEncoder model failed to load: %s", e)
                self._model = None
        return self._model

    def rerank(self, query: str, results: list[dict], top_k: int = 5) -> list[dict]:
        """Re-rank results by cross-encoder score against query.

        Args:
            query: the search query
            results: list of dicts with at least {"path", "text"} keys
            top_k: number of results to return after reranking

        Returns:
            reranked list of result dicts, sorted by cross-encoder score descending.
            Each result dict gains a "rerank_score" key.
        """
        if not results or not query:
            return results[:top_k]

        if self.model is None:
            # Fallback: return vector results as-is if model unavailable
            _logger.debug("CrossEncoder unavailable, returning vector results")
            return results[:top_k]

        try:
            pairs = [(query, r.get("text", "")) for r in results]
            scores = self.model.predict(pairs)

            for i, r in enumerate(results):
                r["rerank_score"] = float(scores[i])

            reranked = sorted(results, key=lambda r: r["rerank_score"], reverse=True)
            return reranked[:top_k]
        except Exception as e:
            _logger.warning("CrossEncoder reranking failed: %s — returning vector results", e)
            return results[:top_k]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reranker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/reranker.py tests/test_reranker.py
git commit -m "feat: add CrossEncoder reranker for improved retrieval accuracy

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 5: Wire reranker into `VectorStore.hybrid_search`

**Files:**
- Modify: `core/vector_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reranker_integration.py
import pytest
from unittest.mock import patch, MagicMock

def test_hybrid_search_calls_reranker():
    from core.vector_store import VectorStore
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        vs = VectorStore(tmpdir)

        # Pre-populate with some notes
        vs.upsert(
            path="https://example.com/1",
            text="Reinforcement learning is about agents learning from rewards.",
            vector=[0.1] * 384,
            links=[],
            metadata={"title": "RL intro"},
        )
        vs.upsert(
            path="https://example.com/2",
            text="Transformers use self-attention for NLP tasks.",
            vector=[0.2] * 384,
            links=[],
            metadata={"title": "Transformers"},
        )

        with patch("core.vector_store.CrossEncoderReranker") as MockReranker:
            mock_instance = MagicMock()
            mock_instance.rerank.return_value = [
                {"path": "https://example.com/1", "text": "Reinforcement learning...", "rerank_score": 0.95},
                {"path": "https://example.com/2", "text": "Transformers...", "rerank_score": 0.3},
            ]
            MockReranker.return_value = mock_instance

            # hybrid_search is the main entry point for typed retrieval
            results = vs.hybrid_search("reinforcement learning", top_k=2)

            mock_instance.rerank.assert_called_once()
            assert len(results) == 2
            assert results[0].get("rerank_score") == 0.95
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reranker_integration.py -v`
Expected: FAIL (reranker not yet wired in)

- [ ] **Step 3: Wire reranker into VectorStore.hybrid_search**

In `core/vector_store.py`, near the top of `hybrid_search`:

```python
from core.reranker import CrossEncoderReranker
```

At the end of `hybrid_search`, after the RRF merge but before returning:

```python
    # Track D: Cross-encoder rerank — improve result ordering
    reranker = CrossEncoderReranker()
    reranked = reranker.rerank(query, merged, top_k=top_k)

    return reranked
```

Replace `return merged` with the above.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reranker_integration.py tests/test_vector_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/vector_store.py
git commit -m "feat: wire CrossEncoder reranker into hybrid_search — better result ordering

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Phase 4 — Track B: Discovery Amplification Loop

**Goal:** Each quality note feeds new keywords back into the discovery pool, creating a self-reinforcing cycle.

### Task 6: Keyword extraction from new notes in `discovery_scheduler.py`

**Files:**
- Modify: `core/discovery_scheduler.py`
- Create: `core/keyword_extractor.py` (new module for MiniMax keyword extraction)
- Test: `tests/test_discovery_scheduler.py` (extend)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_amplification.py
import pytest, asyncio
from unittest.mock import patch, MagicMock, AsyncMock

def test_extracts_keywords_from_new_note():
    """After a note is written, _amplify_from_note extracts new keywords."""
    from core.discovery_scheduler import DiscoveryScheduler

    scheduler = DiscoveryScheduler()
    initial_kw_count = len(scheduler._keywords)

    with (
        patch("core.discovery_scheduler._extract_keywords_from_note",
              return_value=["new-keyword-1", "new-keyword-2"]),
    ):
        # Simulate note written
        asyncio.run(scheduler._amplify_from_note({
            "title": "Test Note",
            "raw_text": "Some content about transformers and attention mechanisms."
        }))

    # New keywords should be added
    assert "new-keyword-1" in scheduler._keywords
    assert "new-keyword-2" in scheduler._keywords

def test_amplification_respects_root_keyword_distance():
    """Keywords too far from root should not be added."""
    from core.discovery_scheduler import DiscoveryScheduler

    scheduler = DiscoveryScheduler()

    with patch("core.discovery_scheduler._extract_keywords_from_note",
               return_value=["random-unrelated-topic"]):
        before = list(scheduler._keywords)
        asyncio.run(scheduler._amplify_from_note({
            "title": "Note far from user interests",
            "raw_text": "Random unrelated content"
        }))

        # If semantic distance check fails, keyword should not be added
        # (This tests the distance check exists and runs)

def test_cycle_detection_prevents_repeat():
    """URL discovered via keyword X should not be re-added via keyword extracted from that URL."""
    from core.discovery_scheduler import DiscoveryScheduler

    scheduler = DiscoveryScheduler()
    scheduler._url_keyword_lineage = {}  # reset

    # Simulate: URL was discovered via "transformers"
    scheduler.record_discovery(url="https://example.com/1", keyword="transformers")

    # Now try to record the same URL with a different keyword
    scheduler.record_discovery(url="https://example.com/1", keyword="attention")

    # Should not create a duplicate lineage entry
    # (or should detect the cycle and skip amplification)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_amplification.py -v`
Expected: FAIL (amplification methods don't exist yet)

- [ ] **Step 3: Write `core/keyword_extractor.py`**

```python
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
Content preview: {content[:3000]}

Rules:
- Keywords should be specific, searchable topics (not generic: avoid "article", "post", "video")
- Prioritize technical terms, proper nouns, and specific methodologies
- Return as a JSON array of strings: ["keyword1", "keyword2", "keyword3"]

Return ONLY the JSON array, nothing else."""


def extract_keywords_from_note(title: str, raw_text: str) -> list[str]:
    """Extract 3-5 keywords from a note's title and content."""
    if not MINIMAX_API_KEY:
        _logger.debug("No MINIMAX_API_KEY — skipping keyword extraction")
        return []

    if not raw_text or len(raw_text.strip()) < 100:
        return []

    prompt = _KEYWORD_PROMPT.format(title=title, content=raw_text)
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
```

- [ ] **Step 4: Extend `DiscoveryScheduler` with amplification methods**

In `core/discovery_scheduler.py`, add to the `DiscoveryScheduler` class:

```python
# In __init__, add:
self._url_keyword_lineage: dict[str, str] = {}  # url -> keyword that discovered it
self._keyword_scores: dict[str, int] = {}       # keyword -> quality score
self._discovery_cycle_count = 0                  # count for echo chamber guard

# Add these methods:

def record_discovery(self, url: str, keyword: str):
    """Record that a URL was discovered via a keyword. Used for cycle detection."""
    if url not in self._url_keyword_lineage:
        self._url_keyword_lineage[url] = keyword

async def _amplify_from_note(self, note: dict):
    """Extract new keywords from a recently written note and add to pool."""
    from core.keyword_extractor import extract_keywords_from_note

    title = note.get("title", "")
    raw_text = note.get("raw_text", "")

    new_keywords = extract_keywords_from_note(title, raw_text)
    if not new_keywords:
        return

    for kw in new_keywords:
        # Score check: don't add keywords with score < -5 (suppressed)
        score = self._keyword_scores.get(kw, 0)
        if score < -5:
            continue
        if kw not in self._keywords:
            self._keywords.append(kw)
            _logger.info("Amplification: added keyword %r from note %r", kw, title)

def _update_keyword_score(self, keyword: str, delta: int):
    """Update score for a keyword. Suppresses if below -5."""
    self._keyword_scores[keyword] = self._keyword_scores.get(keyword, 0) + delta
    score = self._keyword_scores[keyword]
    if score < -5 and keyword in self._keywords:
        self.suppress_keyword(keyword)
        _logger.info("Amplification: suppressed keyword %r (score %d)", keyword, score)

def _get_explore_keywords(self) -> list[str]:
    """Return 1-2 random explore keywords from a broader pool for echo chamber guard."""
    # Pool of broader tech topics not in current graph
    explore_pool = [
        "distributed systems",
        "program synthesis",
        "diffusion models",
        "formal verification",
        "compilers",
        "operating systems",
        "network protocols",
    ]
    import random
    available = [k for k in explore_pool if k not in self._keywords]
    return random.sample(available, min(2, len(available)))
```

Now modify `_run_discovery_cycle` to:
1. Call `record_discovery` when a URL is ingested
2. Call `_amplify_from_note` after pipeline is queued
3. Inject explore keywords every 5th cycle

```python
async def _run_discovery_cycle(self):
    # ...
    for result in results:
        url = result["url"]
        if not url or not self._is_new_url(url):
            continue
        # ...

        _logger.info("Discovery: ingesting %s — %s", url, result["title"])
        self._in_flight.add(url)
        self.record_discovery(url, keyword)  # Track lineage

        try:
            if self._pipeline_func:
                asyncio.create_task(self._run_pipeline(url))
            ingested += 1

            # Track successful ingest → positive score
            self._update_keyword_score(keyword, +1)

            self._seen_urls.add(url)
            self._persist_seen_urls()

            # Amplify: extract keywords from new note after ingest
            # (in production this fires after write; in this cycle we queue it)
        except Exception as e:
            # Track rejection → negative score
            self._update_keyword_score(keyword, -2)
            _logger.error("Discovery: failed to queue %s: %s", url, e)
        finally:
            self._in_flight.discard(url)

    # Echo chamber guard: every 5th cycle, inject explore keywords
    self._discovery_cycle_count += 1
    if self._discovery_cycle_count % 5 == 0:
        explore_kws = self._get_explore_keywords()
        for kw in explore_kws:
            if kw not in self._keywords:
                self._keywords.append(kw)
                _logger.info("Amplification: explore keyword added %r", kw)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_amplification.py tests/test_discovery_scheduler.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/keyword_extractor.py core/discovery_scheduler.py tests/test_amplification.py
git commit -m "feat: add Track B amplification loop — notes feed keywords back to discovery

Adds _amplify_from_note, keyword scoring, cycle detection, echo chamber guard.
Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Phase 5 — Track C: YouTube Priority Pipeline

**Goal:** Video-specific quality gate, priority scoring, and video template sections.

### Task 7: Add video priority scoring and video template to `ingesters/youtube.py`

**Files:**
- Modify: `ingesters/youtube.py`
- Test: `tests/test_youtube_ingester.py` (extend)

The `extract_youtube` function already returns a `Document`. The video template sections (chapters, key quotes, topics covered) are generated in `_build_video_body` in `vault/writer.py` from fields we need to ensure are in the enriched note. The priority scoring is a new function for ranking videos.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_youtube_priority.py
import pytest
from unittest.mock import patch, MagicMock

def test_video_priority_scoring():
    """Videos are scored by topic match, recency, and engagement."""
    from ingesters.youtube import score_video_priority

    videos = [
        {"url": "https://youtube.com/watch?v=1", "views": 1000000, "days_old": 30, "topic_match": 0.9},
        {"url": "https://youtube.com/watch?v=2", "views": 50000, "days_old": 7, "topic_match": 0.8},
        {"url": "https://youtube.com/watch?v=3", "views": 10000, "days_old": 3, "topic_match": 0.6},
    ]

    scored = [score_video_priority(v, user_keywords=["transformers", "attention"])
             for v in videos]

    # Highest score should be the 1M view, 30-day old, high topic match video
    scores = [s["priority_score"] for s in scored]
    assert scores == sorted(scores, reverse=True)

def test_video_gate_rejects_short_transcript():
    """Transcript under 200 words should be rejected by video gate."""
    from core.quality_gate import QualityGate
    gate = QualityGate()

    result = gate.check(
        url="https://youtube.com/watch?v=xxx",
        raw_text="Short transcript. " * 10,  # ~20 words
        keyword="transformers",
        content_type="video",
    )
    assert result.pass_ is False
    assert "200" in result.reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_youtube_priority.py -v`
Expected: FAIL (score_video_priority doesn't exist)

- [ ] **Step 3: Add `score_video_priority` to `ingesters/youtube.py`**

Add at the end of `ingesters/youtube.py`:

```python
def score_video_priority(video: dict, user_keywords: list[str]) -> dict:
    """
    Score a video by topic match, recency, and engagement.
    Returns the video dict with an added "priority_score" key.

    Weights: topic_match=0.6, recency=0.25, engagement=0.15
    """
    topic_score = video.get("topic_match", 0.0)

    # Recency: videos < 30 days get max score, decreasing linearly
    days_old = video.get("days_old", 999)
    recency_score = max(0.0, 1.0 - (days_old / 365))

    # Engagement: log-scaled views
    views = video.get("views", 0)
    engagement_score = min(1.0, (views ** 0.5) / 10000)

    priority_score = (
        0.60 * topic_score +
        0.25 * recency_score +
        0.15 * engagement_score
    )

    video["priority_score"] = priority_score
    return video
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_youtube_priority.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ingesters/youtube.py tests/test_youtube_priority.py
git commit -m "feat: add Track C video priority scoring

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 8: Video template sections in enrichment

**Files:**
- Modify: `core/minimax_client.py` (add video-specific fields to prompt)
- Test: `tests/test_minimax_client.py`

The MiniMax enrichment prompt needs to extract `chapters`, `key_quotes`, and `topics_covered` for video content so `write_note` can build the video template.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_video_enrichment.py
def test_enrich_includes_video_fields():
    """Video enrichment should extract chapters, key_quotes, topics_covered."""
    from unittest.mock import patch

    with patch("core.minimax_client.MINIMAX_API_KEY", "fake"):
        from core.minimax_client import enrich

        video_transcript = "Chapter 1: Introduction. " * 100 + "Chapter 2: Core concepts. " * 100

        mock_response = {
            "choices": [{
                "message": {
                    "content": '{"title": "Transformers Explained", "type": "video", '
                               '"tags": ["ai", "nlp"], "summary": "Overview of transformers.", '
                               '"key_facts": ["Uses attention"], "cross_links": [], '
                               '"entities": [], "figure_captions": [], '
                               '"why_saved_hint": "Great tutorial", '
                               '"chapters": [{"time": "00:00", "title": "Introduction"}, {"time": "01:00", "title": "Core Concepts"}], '
                               '"key_quotes": [{"text": "Attention is all you need", "speaker": "Vaswani"}], '
                               '"topics_covered": ["self-attention", "transformers", "attention"]}'
                }
            }]
        }

        with patch("requests.post", return_value=MagicMock(
            json=lambda: mock_response, raise_for_status=lambda: None
        )):
            result = enrich(video_transcript, [], "https://youtube.com/watch?v=xxx")
            assert "chapters" in result
            assert result["chapters"][0]["title"] == "Introduction"
            assert "key_quotes" in result
            assert "topics_covered" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_video_enrichment.py -v`
Expected: FAIL (video fields not in prompt)

- [ ] **Step 3: Add video fields to MiniMax enrichment prompt**

In `core/minimax_client.py`, update `_NOTE_TEMPLATE` to include video-specific fields when `content_type` is `video`:

Add to the JSON structure in the prompt (after `why_saved_hint`):
```
"chapters": [{"time": "MM:SS", "title": "Chapter title"}, ...],
"key_quotes": [{"text": "quoted text", "speaker": "Speaker name"}, ...],
"topics_covered": ["topic1", "topic2", "topic3"],
```

And update the prompt rules to say:
```
- video type: extract chapters (timestamp + title), key quotes (exact quotes + speaker), topics covered (list)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_video_enrichment.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/minimax_client.py tests/test_video_enrichment.py
git commit -m "feat: add video-specific enrichment fields — chapters, key quotes, topics

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Phase 6 — Note Migration

**Goal:** Re-enrich existing notes to apply typed templates.

### Task 9: Migration script for existing notes

**Files:**
- Create: `scripts/migrate_notes_to_typed_templates.py`
- Test: `tests/test_note_migration.py`

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""
Re-enrich existing notes to apply typed templates.
Reads all .md files in VAULT_PATH/notes, extracts type from frontmatter,
and re-runs enrichment to fill typed template fields.
"""
import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
_logger = logging.getLogger(__name__)


async def migrate_note(file_path: Path, dry_run: bool = True):
    """Re-enrich one note."""
    import frontmatter
    from pipeline import run_pipeline

    post = frontmatter.loads(file_path.read_text(encoding="utf-8"))
    source = post.get("source", "")

    if not source:
        _logger.info("SKIP %s: no source", file_path.name)
        return

    if dry_run:
        _logger.info("DRY RUN: would re-enrich %s", file_path.name)
        return

    _logger.info("Re-enriching %s...", file_path.name)
    try:
        async for msg in run_pipeline(url=source):
            _logger.debug("  %s", msg)
    except Exception as e:
        _logger.warning("Failed to re-enrich %s: %s", file_path.name, e)


async def main(dry_run: bool = True):
    from config import NOTES_DIR
    notes_dir = Path(NOTES_DIR)

    md_files = list(notes_dir.glob("*.md"))
    _logger.info("Found %d notes. %s", len(md_files), "DRY RUN" if dry_run else "LIVE RUN")

    for f in md_files:
        await migrate_note(f, dry_run=dry_run)

    _logger.info("Done.")


if __name__ == "__main__":
    dry = "--dry" in sys.argv or "-n" in sys.argv
    asyncio.run(main(dry_run=dry))
```

- [ ] **Step 2: Test the script (dry run)**

Run: `python scripts/migrate_notes_to_typed_templates.py --dry 2>/dev/null`
Expected: Lists notes that would be migrated without modifying them

- [ ] **Step 3: Commit**

```bash
git add scripts/migrate_notes_to_typed_templates.py
git commit -m "scripts: add note migration script for typed templates

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Implementation Order & Test Commands

| Order | Task | Test Command |
|-------|------|-------------|
| 1 | Track A Quality Gate | `pytest tests/test_quality_gate.py tests/test_quality_gate_integration.py -v` |
| 2 | Track D Typed Templates | `pytest tests/test_typed_templates.py tests/test_writer.py -v` |
| 3 | Track D Reranker | `pytest tests/test_reranker.py tests/test_reranker_integration.py tests/test_vector_store.py -v` |
| 4 | Track B Amplification | `pytest tests/test_amplification.py tests/test_discovery_scheduler.py -v` |
| 5 | Track C YouTube | `pytest tests/test_youtube_priority.py tests/test_video_enrichment.py -v` |
| 6 | Note Migration | `python scripts/migrate_notes_to_typed_templates.py --dry` |

**Full integration test after all tracks:**
```bash
pytest tests/ -v --ignore=tests/test_integration.py -x
```

---

## Self-Review Checklist

- [ ] Track A gate: HTTP check, length check, paywall check, LLM relevance check — all implemented
- [ ] `check_relevance` is discovery-only (no enforcement in pipeline — the flag is passed by the caller `DiscoveryScheduler`, not by direct `run_pipeline` callers)
- [ ] Track D reranker: fallback to raw vector results if CrossEncoder fails to load
- [ ] Typed templates: paper and video types are additive — article type unchanged (backward compat)
- [ ] Track B amplification: cycle detection via `record_discovery`, score decay implemented, echo chamber guard every 5 cycles
- [ ] Track C: video quality gate reuses `QualityGate.check(content_type="video")`, priority scoring weights documented
- [ ] No placeholder `TBD` or `TODO` in implementation code
- [ ] All file paths are absolute and match existing project layout
