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

_KEY_FIELDS = (
    "title", "source", "type", "ticker", "company",
    "author", "date", "ingested", "keywords", "tags",
)


_TOKEN_RE = re.compile(r"[^\W]+(?:[-'_/+.#:][^\W]+)*")
_TOKEN_COMPONENT_RE = re.compile(r"[^\W]+")


def _simple_tokenizer(text: str) -> list[str]:
    """Keep meaningful compounds and index their searchable components too."""
    tokens: list[str] = []
    for token in _TOKEN_RE.findall(text.casefold()):
        tokens.append(token)
        components = _TOKEN_COMPONENT_RE.findall(token)
        if len(components) > 1:
            tokens.extend(components)
    return tokens


_INDEX_TTL_SECONDS = 300  # 5 minutes

# Module-level singleton state
_index: BM25Okapi | None = None
_paths: list[str] = []
_corpus: list[str] = []
_content_index: BM25Okapi | None = None
_content_paths: list[str] = []
_content_corpus: list[str] = []
_last_built: float = 0.0
_content_last_built: float = 0.0


def _key_document(metadata: dict) -> str:
    """Flatten indexable frontmatter keys into one searchable string."""
    parts = []
    fields = list(_KEY_FIELDS)
    fields.extend(field for field in metadata if field not in _KEY_FIELDS)
    for field in fields:
        value = metadata.get(field)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            parts.extend(str(entry) for entry in value)
        else:
            parts.append(str(value))
    return " ".join(parts)


def _build_index(*, include_body: bool = False) -> tuple[BM25Okapi, list[str], list[str]]:
    """Walk NOTES_DIR recursively and build a keys or content index."""
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
            if include_body:
                document = f"{document}\n{post.content}"
            if not document.strip():
                continue
            paths.append(str(md_file))
            corpus.append(document)
    tokenized = [_simple_tokenizer(doc) for doc in corpus]
    # rank_bm25 cannot construct an index for an empty corpus. Keep a
    # harmless sentinel index while returning empty paths so searches remain
    # a normal no-results operation for a fresh or metadata-free vault.
    index = BM25Okapi(tokenized or [["__empty__"]])
    return index, paths, corpus


def ensure_index() -> tuple[BM25Okapi, list[str], list[str]]:
    """Return (index, paths, corpus). Rebuilds if older than 5 minutes."""
    global _index, _paths, _corpus, _last_built
    now = time.monotonic()
    if _index is None or (now - _last_built) > _INDEX_TTL_SECONDS:
        _index, _paths, _corpus = _build_index(include_body=False)
        _last_built = now
    return _index, _paths, _corpus


def ensure_content_index() -> tuple[BM25Okapi, list[str], list[str]]:
    """Return a content index for hybrid retrieval, rebuilding as needed."""
    global _content_index, _content_paths, _content_corpus, _content_last_built
    now = time.monotonic()
    if _content_index is None or (now - _content_last_built) > _INDEX_TTL_SECONDS:
        _content_index, _content_paths, _content_corpus = _build_index(include_body=True)
        _content_last_built = now
    return _content_index, _content_paths, _content_corpus


def bm25_search(query: str, top_k: int = 5, *, include_body: bool = False) -> list[dict]:
    """
    Search the BM25 index.
    Returns list of {path, score, rank} sorted by BM25 descending.

    A lexical overlap check keeps valid key matches whose raw BM25 score is
    zero in a small corpus while excluding documents with no query tokens.
    """
    try:
        index, paths, corpus = (
            ensure_content_index() if include_body else ensure_index()
        )
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
    global _content_index, _content_paths, _content_corpus, _content_last_built
    _index = None
    _paths = []
    _corpus = []
    _last_built = 0.0
    _content_index = None
    _content_paths = []
    _content_corpus = []
    _content_last_built = 0.0
