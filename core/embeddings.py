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
            f"{LM_STUDIO_URL}/api/v1/chat",
            json={
                "model": LM_STUDIO_EMBED_MODEL,
                "system_prompt": "You are an embedding model. Return only the embedding vector.",
                "input": text,
            },
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
        return data["embedding"]
    except Exception:
        model = _get_fallback_model()
        vectors = list(model.embed([text]))
        return vectors[0].tolist()