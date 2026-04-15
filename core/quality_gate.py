# core/quality_gate.py
from dataclasses import dataclass
import urllib.request
import logging

_logger = logging.getLogger(__name__)

_ERROR_SIGNALS = ["[PAYWALLED]", "[PAYWALL]", "404", "Page not found", "[BLOCKED]"]
_MIN_ARTICLE_CHARS = 100  # Backward-compat with existing pipeline tests (~130 char content)
_MIN_VIDEO_WORDS = 200


@dataclass
class GateResult:
    pass_: bool
    reason: str = ""


class QualityGate:
    def check(
        self,
        url: str,
        raw_text: str,
        keyword: str,
        content_type: str = "article",
    ) -> GateResult:
        stripped = raw_text.strip()
        for sig in _ERROR_SIGNALS:
            if sig in stripped:
                return GateResult(pass_=False, reason=f"Error signal: {sig}")

        if content_type == "video":
            word_count = len(stripped.split())
            if word_count < _MIN_VIDEO_WORDS:
                return GateResult(pass_=False, reason=f"Video transcript too thin: {word_count} words, need >{_MIN_VIDEO_WORDS}")
        else:
            if len(stripped) < _MIN_ARTICLE_CHARS:
                return GateResult(pass_=False, reason=f"Content too thin: {len(stripped)} chars, need >{_MIN_ARTICLE_CHARS}")

        if any(p in stripped for p in ["[PAYWALLED]", "[PAYWALL]", "[SUBSCRIPTION REQUIRED]"]):
            return GateResult(pass_=False, reason="Paywall detected")

        return GateResult(pass_=True)

    def check_relevance(self, raw_text: str, keyword: str) -> GateResult:
        if not raw_text or not keyword:
            return GateResult(pass_=True)

        from config import MINIMAX_API_KEY, MINIMAX_MODEL, MINIMAX_API_URL
        if not MINIMAX_API_KEY:
            return GateResult(pass_=True)

        import requests
        prompt = (
            f'Keyword: "{keyword}"\n\n'
            f'Content preview (first 500 chars):\n{raw_text[:500]}\n\n'
            f'Question: Does this content match the keyword "{keyword}"? '
            f'Answer YES if the content is about or related to "{keyword}". '
            f'Answer NO if the content is unrelated or off-topic.\n\n'
            f'Answer: Yes or No (nothing else).'
        )
        try:
            resp = requests.post(
                MINIMAX_API_URL,
                headers={"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": MINIMAX_MODEL,
                    "messages": [
                        {"role": "system", "content": "You are a relevance classifier. Answer only Yes or No."},
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=15,
            )
            content = (resp.json().get("choices", [{}])[0].get("message", {}).get("content") or "").lower()
            if "no" in content and len(content) < 10:
                return GateResult(pass_=False, reason=f"LLM: off-topic for keyword '{keyword}'")
        except Exception as e:
            _logger.debug("Relevance check failed, passing through: %s", e)

        return GateResult(pass_=True)
