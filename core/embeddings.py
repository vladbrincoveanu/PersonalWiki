from fastembed import TextEmbedding
from config import EMBED_MODEL

_model: TextEmbedding | None = None


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        _model = TextEmbedding(EMBED_MODEL)
    return _model


def embed(text: str) -> list[float]:
    model = _get_model()
    vectors = list(model.embed([text]))
    return vectors[0].tolist()
