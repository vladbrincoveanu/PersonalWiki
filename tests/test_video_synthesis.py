import pytest
from core.minimax_client import semantic_chunk, Chunk


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
