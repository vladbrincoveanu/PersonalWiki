"""
Cross-encoder reranking for vector search results.
Uses sentence-transformers CrossEncoder for query-document scoring.
"""
from sentence_transformers import CrossEncoder
import logging

_logger = logging.getLogger(__name__)

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
        if not results or not query:
            return results[:top_k]
        if self.model is None:
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