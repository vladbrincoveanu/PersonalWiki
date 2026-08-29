"""
Lazy-built in-memory BM25 index of all vault notes.
Refreshes automatically every 5 minutes.
"""
import logging
import time
import frontmatter
from rank_bm25 import BM25Okapi
from config import NOTES_DIR

_logger = logging.getLogger(__name__)

_KEY_FIELDS = (
    "title", "source", "type", "ticker", "company",
    "author", "date", "keywords", "tags",
)


def _simple_tokenizer(text: str) -> list[str]:
    """Split on whitespace and lowercase."""
    return text.lower().split()


_INDEX_TTL_SECONDS = 300  # 5 minutes

# Module-level singleton state
_index: BM25Okapi | None = None
_paths: list[str] = []
_corpus: list[str] = []
_last_built: float = 0.0


def _key_document(metadata: dict) -> str:
    """Flatten indexable frontmatter keys into one searchable string."""
    parts = []
    for field in _KEY_FIELDS:
        value = metadata.get(field)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            parts.extend(str(entry) for entry in value)
        else:
            parts.append(str(value))
    return " ".join(parts)


def _build_index() -> tuple[BM25Okapi, list[str], list[str]]:
    """Walk NOTES_DIR recursively and index frontmatter keys only."""
    paths = []
    corpus = []
    if NOTES_DIR.exists():
        for md_file in sorted(NOTES_DIR.rglob("*.md")):
            try:
                post = frontmatter.load(md_file)
                document = _key_document(post.metadata)
            except Exception as exc:
                _logger.warning(
                    "Could not parse frontmatter for %s: %s; skipping",
                    md_file,
                    exc,
                )
                continue
            paths.append(str(md_file))
            corpus.append(document)
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

    A lexical overlap check keeps valid key matches whose raw BM25 score is
    zero in a small corpus while excluding documents with no query tokens.
    """
    try:
        index, paths, corpus = ensure_index()
    except Exception as e:
        _logger.warning("BM25 search failed to build index: %s", e)
        return []
    if not paths:
        return []
    query_tokens = _simple_tokenizer(query)
    query_token_set = set(query_tokens)
    scores = index.get_scores(query_tokens)
    # Pair paths with scores, sort descending
    scored = sorted(zip(paths, scores, corpus), key=lambda x: x[1], reverse=True)
    results = []
    for path, score, document in scored:
        if not query_token_set.intersection(_simple_tokenizer(document)):
            continue
        if len(results) >= top_k:
            break
        rank = len(results) + 1
        results.append({"path": path, "score": float(score), "rank": rank})
    return results


def invalidate_index() -> None:
    """Force next search to rebuild the index."""
    global _index, _paths, _corpus, _last_built
    _index = None
    _paths = []
    _corpus = []
    _last_built = 0.0
