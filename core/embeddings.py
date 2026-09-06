from fastembed import TextEmbedding
from config import EMBED_MODEL
from core.observability import observed_span, record_vector_operation

_model: "TextEmbedding | None" = None


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        _model = TextEmbedding(EMBED_MODEL)
    return _model


def embed(text: str) -> list[float]:
    outcome = "error"
    with observed_span("personalwiki.vector.embed", {"operation": "embed"}):
        try:
            model = _get_model()
            vectors = list(model.embed([text]))
            outcome = "success"
            return vectors[0].tolist()
        finally:
            record_vector_operation("embed", outcome)
