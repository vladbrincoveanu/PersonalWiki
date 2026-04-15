import pytest
from unittest.mock import patch, MagicMock
from core.minimax_client import semantic_chunk, Chunk, enrich_video_synthesis


def test_semantic_chunk_short_transcript_under_60k():
    """Under-60k transcript returns single chunk."""
    text = "Hello this is a short transcript. " * 200  # ~6k chars
    chunks = semantic_chunk(text)
    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].size_chars == len(text)


def test_semantic_chunk_exact_60k():
    """Exactly 60k chars returns single chunk."""
    text = "x" * 60_000
    chunks = semantic_chunk(text)
    assert len(chunks) == 1
    assert chunks[0].size_chars == 60_000


def test_semantic_chunk_oversize_splits():
    """Over-60k transcript splits into multiple chunks at natural boundaries."""
    # Two sections separated by a chapter marker — each >= 60k so chapter split succeeds
    section1 = "[Chapter: Thinking in First Principles]\n" + ("word " * 12000)  # ~60k
    section2 = "[Chapter: Mental Models in Practice]\n" + ("idea " * 3000)     # ~15k
    text = section1 + section2
    assert len(text) > 60_000
    chunks = semantic_chunk(text)
    # section1 is ~60k, section2 is ~15k → total ~75k → should be 2 chunks
    assert len(chunks) == 2
    # Verify chapter markers are at chunk boundaries
    assert "[Chapter: Thinking in First Principles]" in chunks[0].text
    assert "[Chapter: Mental Models in Practice]" in chunks[1].text


def test_semantic_chunk_respects_60k_minimum():
    """Each chunk is at least 60k chars (except final chunk)."""
    text = ("para " * 20000)  # ~100k chars
    chunks = semantic_chunk(text)
    for chunk in chunks[:-1]:
        assert chunk.size_chars >= 60_000, f"Chunk {chunk.chunk_number} is {chunk.size_chars}, expected >= 60000"


def test_semantic_chunk_timestamp_boundaries():
    """Timestamp patterns (e.g., 00:05:30) split chunks."""
    segment1 = ("Hello everyone. " * 5000) + "\n00:05:30,000 --> 00:05:35,000\n" + ("Continuing. " * 5000)
    segment2 = ("Now let's talk about. " * 5000) + "\n00:10:15,000 --> 00:10:20,000\n" + ("Another topic. " * 5000)
    text = segment1 + segment2
    chunks = semantic_chunk(text)
    assert len(chunks) >= 2


def test_semantic_chunk_metadata():
    """Each chunk has correct start/end indices and chunk_number."""
    text = ("word " * 30000)  # ~150k chars → 3 chunks
    chunks = semantic_chunk(text)
    assert chunks[0].chunk_number == 1
    assert chunks[1].chunk_number == 2
    assert chunks[2].chunk_number == 3
    assert chunks[0].start_index == 0
    assert chunks[0].end_index == len(chunks[0].text)
    assert chunks[1].start_index == chunks[0].end_index
    assert chunks[2].end_index == len(text)


def test_synthesis_unified_narrative_not_chunk_list(monkeypatch):
    """Synthesis prompt asks for unified narrative, not list of chunk summaries."""
    captured_prompt = {}
    def mock_post(url, headers, json, timeout):
        captured_prompt["payload"] = json
        class FakeResp:
            def raise_for_status(self): pass
            def json(self):
                return {
                    "base_resp": {"status_code": 0},
                    "choices": [{
                        "message": {
                            "content": '{"title":"Test","type":"video","tags":[],"summary":"Unified summary","key_facts":[],"cross_links":[],"entities":[],"chapters":[],"key_quotes":[],"topics_covered":[],"why_saved_hint":""}'
                        }
                    }]
                }
        return FakeResp()
    monkeypatch.setattr("requests.post", mock_post)

    chunk_results = [
        {"title": "Chunk 1 Title", "summary": "Summary of chunk 1", "chapters": [{"time": "00:00", "title": "First"}], "key_quotes": [], "entities": [], "key_facts": [], "topics_covered": [], "tags": []},
        {"title": "Chunk 2 Title", "summary": "Summary of chunk 2", "chapters": [{"time": "05:30", "title": "Second"}], "key_quotes": [], "entities": [], "key_facts": [], "topics_covered": [], "tags": []},
    ]
    result = enrich_video_synthesis(chunk_results, "https://youtube.com/watch?v=xxx", [])
    assert "Unified summary" in result["summary"]
    # Verify synthesis prompt received both chunk results
    assert "chunk" in captured_prompt["payload"]["messages"][1]["content"].lower()


def test_synthesis_returns_all_required_fields():
    """Synthesis returns all typed template fields."""
    chunk_results = [
        {"title": "Part 1", "summary": "S1", "chapters": [], "key_quotes": [], "entities": [],
         "key_facts": [], "topics_covered": [], "tags": [], "cross_links": [], "why_saved_hint": ""},
    ]
    result = enrich_video_synthesis(chunk_results, "https://youtube.com/watch?v=xxx", [])
    for field in ["title", "type", "tags", "summary", "key_facts", "cross_links",
                  "entities", "chapters", "key_quotes", "topics_covered", "why_saved_hint"]:
        assert field in result, f"Missing field: {field}"


def test_pipeline_video_routes_to_synthesis(monkeypatch):
    """pipeline.py routes video content_type through chunk→synth flow."""
    captured_calls = {}

    class MockChunk:
        text = "first half " * 10000
        start_index = 0
        end_index = 90000
        chunk_number = 1
        size_chars = 90000

    class MockChunk2:
        text = "second half " * 10000
        start_index = 90000
        end_index = 180000
        chunk_number = 2
        size_chars = 90000

    def mock_chunk(text):
        captured_calls["chunk"] = True
        return [MockChunk(), MockChunk2()]

    def mock_enrich(raw, similar, source):
        captured_calls["enrich_count"] = captured_calls.get("enrich_count", 0) + 1
        return {"title": f"Chunk {captured_calls['enrich_count']}", "summary": "chunk summary",
                "chapters": [], "key_quotes": [], "entities": [], "key_facts": [],
                "topics_covered": [], "tags": [], "cross_links": [], "why_saved_hint": ""}

    def mock_synthesis(chunk_results, source, similar):
        captured_calls["synthesis"] = True
        return {"title": "Unified Video", "type": "video", "summary": "Unified narrative",
                "chapters": [{"time": "00:00", "title": "Start"}], "key_quotes": [], "entities": [],
                "key_facts": [], "topics_covered": [], "tags": [], "cross_links": [], "why_saved_hint": ""}

    monkeypatch.setattr("core.minimax_client.semantic_chunk", mock_chunk)
    monkeypatch.setattr("core.minimax_client.enrich", mock_enrich)
    monkeypatch.setattr("core.minimax_client.enrich_video_synthesis", mock_synthesis)

    class MockDoc:
        raw_text = "full transcript " * 10000
        content_type = "video"
        images = []

    class MockStore:
        def exists(self, url):
            return False

        def search(self, vector, top_k=5):
            return []

        def upsert(self, path, text, vector, links, metadata):
            pass

    import pipeline as pipeline_module

    # Override module-level references before pipeline runs
    original_extract = pipeline_module.extract
    async def mock_extract(url):
        return MockDoc()
    pipeline_module.extract = mock_extract

    original_get_store = pipeline_module.get_store
    pipeline_module.get_store = lambda: MockStore()

    try:
        import asyncio
        async def run_test():
            async for _ in pipeline_module.run_pipeline(url="https://youtube.com/watch?v=xyz"):
                pass
            return captured_calls

        result = asyncio.run(run_test())
    finally:
        pipeline_module.extract = original_extract
        pipeline_module.get_store = original_get_store

    assert result.get("chunk") is True
    assert result.get("enrich_count") == 2
    assert result.get("synthesis") is True
