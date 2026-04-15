from crawl4ai import AsyncWebCrawler, CrawlerRunConfig


async def extract_url(url: str) -> str:
    # excluded_tags removes nav/footer/header/aside to produce cleaner markdown
    config = CrawlerRunConfig(
        excluded_tags=["nav", "footer", "header", "aside", "script", "style"],
        remove_overlay_elements=True  # covers cookie banners / modals
    )
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url, config=config)
    if not result.success or not result.markdown:
        raise ValueError(f"Failed to extract content from: {url}")
    return str(result.markdown)
