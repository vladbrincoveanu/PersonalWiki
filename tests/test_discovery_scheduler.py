import pytest, asyncio, tempfile
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

def test_discovery_scheduler_initializes():
    from core.discovery_scheduler import DiscoveryScheduler
    scheduler = DiscoveryScheduler()
    assert scheduler._running is False
    assert scheduler._keywords == []

def test_sitemap_queue_initialized():
    """Scheduler initializes with empty sitemap queue."""
    from core.discovery_scheduler import DiscoveryScheduler
    scheduler = DiscoveryScheduler()
    assert hasattr(scheduler, '_sitemap_queue')
    assert scheduler._sitemap_queue.empty()
    scheduler.stop()

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


@pytest.mark.asyncio
async def test_search_minimax_no_nested_event_loop():
    """_search_minimax must not create a new event loop when already running.

    Bug: _search_minimax used asyncio.new_event_loop() inside an already-running
    loop (called from _search_keyword -> _run_discovery_cycle), raising
    RuntimeError: loop already running.
    """
    from core.discovery_scheduler import DiscoveryScheduler, requests as ds_requests
    import json, asyncio

    ds = DiscoveryScheduler()

    plain_response = {
        "base_resp": {"status_code": 0},
        "choices": [{"message": {"content": json.dumps([{"url": "https://example.com/article", "title": "Example", "snippet": "Example article"}])}}]
    }

    def fake_post(url, headers=None, json=None, timeout=None):
        m = MagicMock()
        m.raise_for_status = MagicMock()
        m.json = MagicMock(return_value=plain_response)
        return m

    class FakeHTTPResponse:
        def __init__(self, status=200):
            self.status = status
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    def fake_urlopen(req, timeout=None):
        return FakeHTTPResponse(status=200)

    with patch.object(ds_requests, "post", side_effect=fake_post):
        with patch("core.discovery_scheduler.urllib.request.urlopen", side_effect=fake_urlopen):
            async def fake_fetch(url):
                return "Real article content."
            with patch.object(ds, "_fetch_article_snippet", fake_fetch):
                # This is called from within an async context (already running loop)
                # Must not raise RuntimeError: loop already running
                try:
                    results = await ds._search_minimax("test query")
                    assert isinstance(results, list)
                except RuntimeError as e:
                    if "loop" in str(e).lower() or "event" in str(e).lower():
                        pytest.fail(f"nested event loop bug: {e}")
                    raise


def test_search_minimax_includes_tools_parameter_for_function_calling():
    """
    Bug: _search_minimax() sends a plain prompt asking LLM to invent URLs.
    The LLM has no internet access — URLs come from training data (hallucination).

    Fix: _search_minimax() must include 'tools' in the API payload so MiniMax
    can call a real web_search function. Without this, discovery returns
    hallucinated/dead links and stale content for any non-famous topic.

    This test patches requests.post and urllib.request.urlopen to capture
    the actual API payload and verify 'tools' is included.
    """
    from core.discovery_scheduler import DiscoveryScheduler, requests as ds_requests
    import json

    ds = DiscoveryScheduler()

    plain_response = {
        "base_resp": {"status_code": 0},
        "choices": [{"message": {"content": json.dumps([{"url": "https://example.com/article", "title": "Example", "snippet": "Example article"}])}}]
    }

    captured_payloads = []

    def fake_post(url, headers=None, json=None, timeout=None):
        captured_payloads.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        m = MagicMock()
        m.raise_for_status = MagicMock()
        m.json = MagicMock(return_value=plain_response)
        return m

    # Context manager for HEAD validation
    class FakeHTTPResponse:
        def __init__(self, status=200):
            self.status = status
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    def fake_urlopen(req, timeout=None):
        return FakeHTTPResponse(status=200)

    with patch.object(ds_requests, "post", side_effect=fake_post):
        with patch("core.discovery_scheduler.urllib.request.urlopen", side_effect=fake_urlopen):
            async def fake_fetch(url):
                return "Real article content."
            with patch.object(ds, "_fetch_article_snippet", fake_fetch):
                results = asyncio.run(ds._search_minimax("reinforcement learning"))

    assert len(results) >= 1, f"Expected at least 1 result, got {len(results)}"
    assert all(r["source"] == "minimax" for r in results)
    assert all(r["url"].startswith("https://") for r in results)

    # KEY assertion: payload should include 'tools' for function-calling
    assert captured_payloads, "requests.post was never called"
    payload = captured_payloads[0].get("json", {})
    assert "tools" in payload, \
        f"Payload must include 'tools' for web_search function-calling. Got payload keys: {list(payload.keys())}"


def test_measure_prose():
    """Prose measurer returns char count and ratio."""
    from core.discovery_scheduler import _measure_prose

    # Real article: mixed paragraphs
    text = "This is a paragraph.\n\nAnother paragraph here."
    chars, ratio = _measure_prose(text)
    assert chars > 0
    assert 0 < ratio <= 1.0

    # Thin: nav-heavy with short blocks
    thin = "HOME | ABOUT | CONTACT\n\n" * 10
    chars, ratio = _measure_prose(thin)
    assert ratio < 0.3  # mostly symbols/caps

    # All-caps headings
    text2 = "IMPORTANT NEWS\n\nA real sentence here. With more content."
    chars, ratio = _measure_prose(text2)
    assert chars > 0

    # Empty
    chars, ratio = _measure_prose("")
    assert chars == 0
    assert ratio == 0.0


def test_extract_article_links():
    """Link extractor filters nav/media and returns article candidates."""
    from core.discovery_scheduler import _extract_article_links

    html = """
    <a href="/nav/menu">Skip</a>
    <a href="/footer/about">Also skip</a>
    <a href="/article/how-to-code">Best match</a>
    <a href="/blog/2024/post">Good article</a>
    <a href="/news/industry-update">Also good</a>
    <a href="/category/tech">Not article</a>
    <a href="https://other.com/page">Cross-domain</a>
    <a href="/tag/python">Tag link</a>
    <a href="/article">Bare article path</a>
    <a href="/2025/report">Year pattern</a>
    """
    parent = "https://example.com/category/tech"
    links = _extract_article_links(html, parent, "python")
    # Should include: /article/how-to-code, /blog/2024/post, /news/industry-update, /2025/report
    assert any("/article/how-to-code" in l for l in links)
    assert any("/blog/2024/post" in l for l in links)
    assert any("/news/industry-update" in l for l in links)
    assert any("/2025/report" in l for l in links)
    # Should exclude: nav, footer, cross-domain, tag, category, bare /article
    assert not any("nav" in l or "footer" in l or "other.com" in l or "tag" in l for l in links)


def test_pick_best_link():
    """Link picker scores by keyword match + slug length."""
    from core.discovery_scheduler import _pick_best_link

    candidates = [
        "https://example.com/article/python-tips",
        "https://example.com/blog/2024/a-very-long-article-title-about-python-programming",
        "https://example.com/news/general-update",
    ]
    # Keyword "python" should rank the long slug highest due to keyword+length
    best = _pick_best_link(candidates, "python")
    assert "python" in best.lower()

    # No keyword match — picks longest slug
    best2 = _pick_best_link(candidates, "javascript")
    assert "very-long-article" in best2  # longest slug


def test_minimax_search_rejects_http_urls():
    """MiniMax search must only accept https:// URLs."""
    from core.discovery_scheduler import DiscoveryScheduler
    import json

    ds = DiscoveryScheduler()

    # Mock HEAD to succeed for both http and https
    class FakeHTTPResponse:
        def __init__(self, status=200):
            self.status = status
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    def fake_urlopen(req, timeout=None):
        return FakeHTTPResponse(status=200)

    # Mock minimax to return mixed http/https URLs
    def fake_post(url, headers=None, json_data=None, timeout=None, **kwargs):
        m = MagicMock()
        m.raise_for_status = MagicMock()
        m.json = MagicMock(return_value={
            "base_resp": {"status_code": 0},
            "choices": [{
                "message": {
                    "content": json.dumps([
                        {"url": "http://insecure.example.com/page", "title": "Insecure", "snippet": ""},
                        {"url": "https://secure.example.com/page", "title": "Secure", "snippet": ""},
                    ])
                }
            }]
        })
        return m

    with patch("core.discovery_scheduler.urllib.request.urlopen", side_effect=fake_urlopen):
        with patch("core.discovery_scheduler.requests.post", side_effect=fake_post):
            async def fake_fetch(url):
                return "Real article content."
            with patch.object(ds, "_fetch_article_snippet", fake_fetch):
                results = asyncio.run(ds._search_minimax("test"))

    urls = [r["url"] for r in results]
    assert "http://insecure.example.com/page" not in urls, "http:// URL was not rejected"
    assert "https://secure.example.com/page" in urls


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


@pytest.mark.asyncio
async def test_enqueue_interest_domain_pushes_to_queue():
    """Enqueued domain's sitemap URLs go to _sitemap_queue, not _seen_urls."""
    from core.discovery_scheduler import DiscoveryScheduler

    scheduler = DiscoveryScheduler()

    # Mock _try_sitemap to return known URLs
    with patch.object(scheduler, '_try_sitemap', return_value=[
        'https://example.com/article1',
        'https://example.com/article2',
    ]):
        scheduler._enqueue_interest_domain('example.com')

    # URLs should be in queue, NOT in _seen_urls
    assert scheduler._sitemap_queue.qsize() == 2
    # _seen_urls should NOT have these (that was the bug)
    assert 'https://example.com/article1' not in scheduler._seen_urls

    scheduler.stop()


@pytest.mark.asyncio
async def test_discovery_cycle_drains_sitemap_queue():
    """After keyword searches, cycle drains sitemap queue up to MAX_URLS_PER_CYCLE."""
    from core.discovery_scheduler import DiscoveryScheduler

    scheduler = DiscoveryScheduler()

    # Pre-load queue with sitemap URLs
    await scheduler._sitemap_queue.put('https://example.com/sitemap-article-1')
    await scheduler._sitemap_queue.put('https://example.com/sitemap-article-2')

    # Track which URLs get pipeline calls
    pipeline_calls = []
    original_run_pipeline = scheduler._run_pipeline

    async def mock_run_pipeline(url):
        pipeline_calls.append(url)

    scheduler._run_pipeline = mock_run_pipeline

    # Mock _search_keyword to return nothing (skip keyword phase)
    with patch.object(scheduler, '_search_keyword', return_value=[]):
        with patch('core.vector_store.get_store') as mock_store:
            mock_store_instance = MagicMock()
            mock_store_instance.exists.return_value = False
            mock_store.return_value = mock_store_instance
            await scheduler._run_discovery_cycle()

    # Both sitemap URLs should have been pipeline-called
    assert len(pipeline_calls) == 2
    assert 'https://example.com/sitemap-article-1' in pipeline_calls
    assert 'https://example.com/sitemap-article-2' in pipeline_calls

    scheduler.stop()


@pytest.mark.asyncio
async def test_rate_limit_shared_across_phases():
    """MAX_URLS_PER_CYCLE budget shared between keyword and sitemap phases."""
    from core.discovery_scheduler import DiscoveryScheduler
    from config import MAX_URLS_PER_CYCLE

    scheduler = DiscoveryScheduler()
    original_limit = MAX_URLS_PER_CYCLE

    # Load queue with more URLs than the limit
    for i in range(15):
        await scheduler._sitemap_queue.put(f'https://example.com/sitemap-{i}')

    pipeline_calls = []
    async def mock_run_pipeline(url):
        pipeline_calls.append(url)

    scheduler._run_pipeline = mock_run_pipeline

    with patch.object(scheduler, '_search_keyword', return_value=[]):
        with patch('core.vector_store.get_store') as mock_store:
            mock_store_instance = MagicMock()
            mock_store_instance.exists.return_value = False
            mock_store.return_value = mock_store_instance
            await scheduler._run_discovery_cycle()

    # Should pipeline only MAX_URLS_PER_CYCLE, not all 15
    assert len(pipeline_calls) == original_limit

    scheduler.stop()


@pytest.mark.asyncio
async def test_run_discovery_cycle_calls_cleanup_junk():
    """
    TDD: Verify cleanup_junk() is called at the end of _run_discovery_cycle().
    The junk cleaner removes video notes with no transcript content.
    """
    from core.discovery_scheduler import DiscoveryScheduler

    ds = DiscoveryScheduler()
    ds._keywords = []  # No keywords so cycle completes quickly

    # Mock store to avoid real vector store interactions
    mock_store = MagicMock()
    mock_store.exists.return_value = False

    with (
        patch("core.vector_store.get_store", return_value=mock_store),
        # Patch cleanup_junk in the discovery_scheduler module namespace where it's imported
        patch("core.discovery_scheduler.cleanup_junk", return_value=["/path/to/deleted.md"]) as mock_cleanup,
        patch.object(ds, "_search_keyword", new_callable=AsyncMock, return_value=[]),
    ):
        await ds._run_discovery_cycle()
        mock_cleanup.assert_called_once()
