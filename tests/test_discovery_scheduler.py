import pytest, asyncio, tempfile
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

def test_discovery_scheduler_initializes():
    from core.discovery_scheduler import DiscoveryScheduler
    scheduler = DiscoveryScheduler()
    assert scheduler._running is False
    assert scheduler._keywords == []

def test_deduplication_against_seen_urls():
    from core.discovery_scheduler import DiscoveryScheduler
    scheduler = DiscoveryScheduler()
    scheduler._seen_urls.add("https://arxiv.org/abs/1234")
    assert scheduler._is_new_url("https://arxiv.org/abs/1234") is False
    assert scheduler._is_new_url("https://arxiv.org/abs/9999") is True

@pytest.mark.asyncio
async def test_keyword_refresh():
    from core.discovery_scheduler import DiscoveryScheduler
    scheduler = DiscoveryScheduler()
    with (
        patch("core.graph_interests.extract_interests", return_value=["RLHF", "KV-cache"]),
        patch("core.discovery_scheduler._load_manual_keywords", return_value=[]),
        patch("core.discovery_scheduler._load_suppressed", return_value=[]),
    ):
        await scheduler._refresh_keywords()
    assert scheduler._keywords == ["RLHF", "KV-cache"]


def test_search_desprebursa_sitemap_parsing():
    """Tier 1: sitemap XML is parsed and filtered by keyword in URL."""
    from core.discovery_scheduler import DiscoveryScheduler
    from unittest.mock import MagicMock

    sitemap_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://www.desprebursa.ro/actualmente-bursele-cresc-pe-fondul-datelor-macroeconomice</loc></url>
      <url><loc>https://www.desprebursa.ro/companii/articol-despre-burse</loc></url>
      <url><loc>https://www.desprebursa.ro/politica-monetara-a-marilor-banci-centrale</loc></url>
    </urlset>"""

    mock_response = MagicMock()
    mock_response.read.return_value = sitemap_xml.encode("utf-8")
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)

    scheduler = DiscoveryScheduler()
    with patch("core.discovery_scheduler.urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        results = asyncio.run(scheduler._search_desprebursa("companii"))

    # Only 1 URL contains "companii": the second one
    assert len(results) == 1
    assert results[0]["url"] == "https://www.desprebursa.ro/companii/articol-despre-burse"
    assert all(r["source"] == "desprebursa" for r in results)
    mock_urlopen.assert_called_once()


@pytest.mark.asyncio
async def test_search_desprebursa_falls_back_to_category_crawl():
    """Tier 2: when sitemap fails, category pages are crawled and filtered by keyword."""
    from core.discovery_scheduler import DiscoveryScheduler

    html_with_links = """
    <html>
      <body>
        <a href="https://www.desprebursa.ro/companii/analiza-bursala">Analiza bursala</a>
        <a href="https://www.desprebursa.ro/politica/rata-inflatiei">Rata inflatiei</a>
        <a href="https://www.desprebursa.ro/companii/raport-trim1">Raport trim1</a>
      </body>
    </html>"""

    scheduler = DiscoveryScheduler()
    with patch("core.discovery_scheduler.urllib.request.urlopen", side_effect=ValueError("sitemap failed")):
        with patch("core.discovery_scheduler.extract_url", new_callable=AsyncMock, return_value=html_with_links):
            results = await scheduler._search_desprebursa("companii", limit=2)

    # Should extract article links from HTML, filter by keyword "companii"
    assert len(results) == 2
    assert all("companii" in r["url"].lower() for r in results)
    assert all(r["source"] == "desprebursa" for r in results)


@pytest.mark.asyncio
async def test_search_desprebursa_respects_limit():
    """Tier 2 fills remaining slots when Tier 1 returns fewer than limit, then stops at limit."""
    from core.discovery_scheduler import DiscoveryScheduler

    # Sitemap returns 2 non-matching URLs (Tier 1 adds 0 matching results)
    sitemap_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://www.desprebursa.ro/macro-piete/date-pib</loc></loc></url>
      <url><loc>https://www.desprebursa.ro/briefings/saptamana-financiara</loc></loc></url>
    </urlset>"""

    mock_sitemap_response = MagicMock()
    mock_sitemap_response.read.return_value = sitemap_xml.encode("utf-8")
    mock_sitemap_response.__enter__ = MagicMock(return_value=mock_sitemap_response)
    mock_sitemap_response.__exit__ = MagicMock(return_value=False)

    # 3 article links, all containing "companii" - exactly enough to reach limit=3
    html_with_links = """
    <html>
      <body>
        <a href="https://www.desprebursa.ro/companii/analiza-bursala">Analiza bursala</a>
        <a href="https://www.desprebursa.ro/companii/raport-trim1">Raport trim1</a>
        <a href="https://www.desprebursa.ro/companii/evaluare-actiuni">Evaluare actiuni</a>
      </body>
    </html>"""

    scheduler = DiscoveryScheduler()
    with patch("core.discovery_scheduler.urllib.request.urlopen", return_value=mock_sitemap_response):
        with patch("core.discovery_scheduler.extract_url", new_callable=AsyncMock, return_value=html_with_links) as mock_extract:
            results = await scheduler._search_desprebursa("companii", limit=3)

    # Tier 1: 0 matching (sitemap URLs don't contain "companii")
    # Tier 2: adds 3 from category page, hits limit=3, stops
    assert len(results) == 3
    assert all("companii" in r["url"].lower() for r in results)
    assert all(r["source"] == "desprebursa" for r in results)
    # Tier 2 should have run because Tier 1 returned fewer than limit
    assert mock_extract.call_count >= 1


@pytest.mark.asyncio
async def test_refresh_keywords_includes_manual():
    """Manual keywords from .interests are merged with graph keywords."""
    from core.discovery_scheduler import DiscoveryScheduler, KEYWORDS_FILE

    with tempfile.TemporaryDirectory() as tmp_vault:
        tmp_interests = Path(tmp_vault) / ".interests"
        tmp_interests.write_text("manual-keyword\n", encoding="utf-8")
        with patch("core.discovery_scheduler.KEYWORDS_FILE", tmp_interests):
            with patch("core.graph_interests.extract_interests", return_value=["graph-kw"]):
                scheduler = DiscoveryScheduler()
                await scheduler._refresh_keywords()
        assert "manual-keyword" in scheduler._keywords
        assert "graph-kw" in scheduler._keywords
        assert len(scheduler._keywords) == 2


def test_add_keyword_appends_and_activates():
    """add_keyword writes to .interests and adds to _keywords if not present."""
    from core.discovery_scheduler import DiscoveryScheduler, KEYWORDS_FILE

    with tempfile.TemporaryDirectory() as tmp_vault:
        tmp_interests = Path(tmp_vault) / ".interests"
        with patch("core.discovery_scheduler.KEYWORDS_FILE", tmp_interests):
            scheduler = DiscoveryScheduler()
            scheduler._keywords = ["existing"]
            scheduler.add_keyword("new-kw")
        assert "new-kw" in scheduler._keywords
        assert "existing" in scheduler._keywords
        assert tmp_interests.read_text(encoding="utf-8") == "new-kw\n"


def test_add_keyword_raises_on_duplicate():
    """add_keyword raises ValueError when keyword already exists in .interests."""
    from core.discovery_scheduler import DiscoveryScheduler, KEYWORDS_FILE

    with tempfile.TemporaryDirectory() as tmp_vault:
        tmp_interests = Path(tmp_vault) / ".interests"
        tmp_interests.write_text("existing\n", encoding="utf-8")
        with patch("core.discovery_scheduler.KEYWORDS_FILE", tmp_interests):
            scheduler = DiscoveryScheduler()
            scheduler._keywords = ["existing"]
            with pytest.raises(ValueError, match="already exists"):
                scheduler.add_keyword("existing")
        # _keywords unchanged since keyword was already present
        assert scheduler._keywords.count("existing") == 1


def test_remove_keyword_removes_and_purges():
    """remove_keyword removes from .interests and _keywords, calls purge_keyword."""
    from core.discovery_scheduler import DiscoveryScheduler, KEYWORDS_FILE

    with tempfile.TemporaryDirectory() as tmp_vault:
        tmp_interests = Path(tmp_vault) / ".interests"
        tmp_interests.write_text("to-remove\n", encoding="utf-8")
        tmp_note = Path(tmp_vault) / "notes" / "note.md"
        tmp_note.parent.mkdir(parents=True, exist_ok=True)
        tmp_note.write_text("Content about [[to-remove]] and more", encoding="utf-8")
        with patch("core.discovery_scheduler.KEYWORDS_FILE", tmp_interests):
            with patch("core.discovery_scheduler.VAULT_PATH", tmp_vault):
                scheduler = DiscoveryScheduler()
                scheduler._keywords = ["to-remove", "stay"]
                deleted = scheduler.remove_keyword("to-remove")
        assert "to-remove" not in scheduler._keywords
        assert "stay" in scheduler._keywords
        assert tmp_interests.read_text(encoding="utf-8").strip() == ""
        # File with real content keeps wikilink stripped but file itself preserved
        assert (Path(tmp_vault) / "notes" / "note.md").exists()
        assert "[[to-remove]]" not in (Path(tmp_vault) / "notes" / "note.md").read_text()


@pytest.mark.skip(reason="MiniMax API not accessible from test environment — run manually")
@pytest.mark.integration
def test_search_minimax_returns_real_urls_with_real_content():
    """
    Verify MiniMax search returns real, crawlable URLs with actual content.
    This is an integration test — it hits real APIs (MiniMax + live web).
    Skipped by default since MiniMax API times out from this server environment.
    Run manually with: pytest tests/test_discovery_scheduler.py::test_search_minimax_returns_real_urls_with_real_content -v
    """
    from core.discovery_scheduler import DiscoveryScheduler
    ds = DiscoveryScheduler()

    results = ds._search_minimax("reinforcement learning")

    assert len(results) >= 1, "Should return at least 1 result"
    for r in results:
        assert r["source"] == "minimax", f"Expected source='minimax', got {r['source']}"
        assert r["url"].startswith("https://"), f"URL should be real https: {r['url']}"
        # Snippets should be real content from actual pages (Crawl4AI fetched)
        assert len(r["snippet"]) > 20, f"Snippet should be real content, got: {r['snippet'][:50]}"
        assert r["snippet"] != "Content from fake url", "Snippet should not be from test mock"
