import asyncio
from ingesters import Document
from ingesters.web import extract_url

_MIN_LENGTH = 200


async def extract_news(url: str) -> Document:
    # Tier 1: newspaper3k (sync — run in thread to avoid blocking event loop)
    try:
        text = await asyncio.to_thread(_newspaper_extract, url)
        if len(text.strip()) >= _MIN_LENGTH:
            return Document(raw_text=text, content_type="article")
    except Exception:
        pass

    # Tier 2: crawl4ai (async, already handles JS-heavy pages)
    try:
        text = await extract_url(url)
        if len(text.strip()) >= _MIN_LENGTH:
            return Document(raw_text=text, content_type="article")
    except Exception:
        pass

    # Tier 3: paywall fallback — write a stub note rather than raising
    return Document(
        raw_text=f"[PAYWALLED] {url}\n\nCould not extract full content.",
        content_type="article",
    )


def _newspaper_extract(url: str) -> str:
    from newspaper import Article
    article = Article(url)
    article.download()
    article.parse()
    return article.text
