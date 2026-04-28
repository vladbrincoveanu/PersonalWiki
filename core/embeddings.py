import requests
from config import LM_STUDIO_URL, LM_STUDIO_EMBED_MODEL

_model: "TextEmbedding | None" = None


def _get_fallback_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        from config import EMBED_MODEL
        _model = TextEmbedding(EMBED_MODEL)
    return _model


def embed(text: str) -> list[float]:
    try:
        response = requests.post(
            f"{LM_STUDIO_URL}/api/v1/embeddings",
            json={
                "model": LM_STUDIO_EMBED_MODEL,
                "prompt": text,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"]
    except Exception:
        model = _get_fallback_model()
        vectors = list(model.embed([text]))
        return vectors[0].tolist()
