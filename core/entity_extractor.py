"""
Flexible entity extraction from content. Extracts projects, people, companies,
investments, and ideas using MiniMax LLM.
"""
from config import MINIMAX_API_KEY, MINIMAX_API_URL, MINIMAX_MODEL, MINIMAX_GROUP_ID
import requests
import json

def extract_entities(text: str, content_type: str = "web") -> list[dict]:
    """
    Extract structured entities from text using MiniMax LLM.
    Returns list of dicts with keys: entity_type, entity_name, summary, metadata.
    """
    if not text or len(text) < 100:
        return []

    prompt = f"""Extract entities from this {content_type} content.
For each entity, identify:
- type: project, person, company, investment, idea, or other
- name: the entity name
- summary: brief description (1-2 sentences)
- metadata: any additional structured info

Return a JSON list of entities found. If none found, return [].

Content (first 3000 chars):
{text[:3000]}
"""

    headers = {"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MINIMAX_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 500,
    }
    try:
        resp = requests.post(
            f"{MINIMAX_API_URL}?GroupId={MINIMAX_GROUP_ID}",
            headers=headers,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        content = content.strip()
        if content.endswith("```"):
            content = content[:-3]
        return json.loads(content)
    except Exception:
        return []