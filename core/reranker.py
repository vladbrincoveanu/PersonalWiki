"""
Cross-encoder reranking for vector search results.
Uses FastEmbed TextCrossEncoder for query-document scoring.
"""
import logging

from fastembed.rerank.cross_encoder import TextCrossEncoder

_logger = logging.getLogger(__name__)

_MODEL_NAME = "Xenova/ms-marco-MiniLM-L-6-v2"


class CrossEncoderReranker:
    def __init__(self):
        self._model = None

    @property
    def model(self):
        if self._model is None:
            try:
                self._model = TextCrossEncoder(
                    model_name=_MODEL_NAME,
                    lazy_load=True,
                    cuda=False,
                )
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
            documents = [r.get("text", "") for r in results]
            scores = [float(score) for score in self.model.rerank(query, documents)]
            if len(scores) != len(results):
                raise ValueError(
                    f"Reranker returned {len(scores)} scores for {len(results)} results"
                )
            for result, score in zip(results, scores):
                result["rerank_score"] = score
            reranked = sorted(results, key=lambda r: r["rerank_score"], reverse=True)
            return reranked[:top_k]
        except Exception as e:
            _logger.warning("CrossEncoder reranking failed: %s — returning vector results", e)
            return results[:top_k]
