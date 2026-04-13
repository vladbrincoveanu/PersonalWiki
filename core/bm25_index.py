"""
Lazy-built in-memory BM25 index of all vault notes.
Refreshes automatically every 5 minutes.
"""
import logging
import re
import time
import frontmatter
from rank_bm25 import BM25Okapi
from config import NOTES_DIR

_logger = logging.getLogger(__name__)

# Pre-compiled regex patterns for markdown stripping
_RE_HEADER = re.compile(r'#{1,6}\s+')
_RE_LINK = re.compile(r'\[([^\]]+)\]\([^\)]+\)')
_RE_EMPHASIS = re.compile(r'[*_]{1,2}([^*_]+)[*_]{1,2}')
_RE_IMAGE = re.compile(r'!\[[^\]]*\]\([^\)]+\)')


def _simple_tokenizer(text: str) -> list[str]:
    """Split on whitespace and lowercase."""
    return text.lower().split()


_INDEX_TTL_SECONDS = 300  # 5 minutes

# Module-level singleton state
_index: BM25Okapi | None = None
_paths: list[str] = []
_corpus: list[str] = []
_last_built: float = 0.0


def _strip_markdown(text: str) -> str:
    """Lightweight markdown strip — remove headers, links, emphasis."""
    text = _RE_HEADER.sub('', text)
    text = _RE_LINK.sub(r'\1', text)
    text = _RE_EMPHASIS.sub(r'\1', text)
    text = _RE_IMAGE.sub('', text)
    return text


def _build_index() -> tuple[BM25Okapi, list[str], list[str]]:
    """Walk NOTES_DIR, strip frontmatter, build BM25 index."""
    paths = []
    corpus = []
    if NOTES_DIR.exists():
        for md_file in sorted(NOTES_DIR.glob("*.md")):
            try:
                post = frontmatter.parse(str(md_file))
                body = _strip_markdown(post.content)
            except Exception:
                _logger.warning("Could not parse frontmatter for %s, using raw text", md_file)
                body = md_file.read_text(encoding="utf-8")
            paths.append(str(md_file))
            corpus.append(body)
    tokenized = [_simple_tokenizer(doc) for doc in corpus]
    index = BM25Okapi(tokenized)
    return index, paths, corpus


def ensure_index() -> tuple[BM25Okapi, list[str], list[str]]:
    """Return (index, paths, corpus). Rebuilds if older than 5 minutes."""
    global _index, _paths, _corpus, _last_built
    now = time.monotonic()
    if _index is None or (now - _last_built) > _INDEX_TTL_SECONDS:
        _index, _paths, _corpus = _build_index()
        _last_built = now
    return _index, _paths, _corpus


def bm25_search(query: str, top_k: int = 5) -> list[dict]:
    """
    Search the BM25 index.
    Returns list of {path, score, rank} sorted by BM25 descending.
    """
    index, paths, corpus = ensure_index()
    if not paths:
        return []
    query_tokens = _simple_tokenizer(query)
    scores = index.get_scores(query_tokens)
    # Pair paths with scores, sort descending
    scored = sorted(zip(paths, scores), key=lambda x: x[1], reverse=True)
    results = []
    for rank, (path, score) in enumerate(scored[:top_k], start=1):
        results.append({"path": path, "score": float(score), "rank": rank})
    return results


def invalidate_index() -> None:
    """Force next search to rebuild the index."""
    global _index, _paths, _corpus, _last_built
    _index = None
    _paths = []
    _corpus = []
    _last_built = 0.0
