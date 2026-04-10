from crawl4ai import AsyncWebCrawler


async def extract_url(url: str) -> str:
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url)
    if not result.success or not result.markdown:
        raise ValueError(f"Failed to extract content from: {url}")
    return str(result.markdown)
