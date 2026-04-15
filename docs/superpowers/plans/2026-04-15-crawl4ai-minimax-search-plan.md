# Crawl4AI + MiniMax Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hallucination-prone MiniMax prompt-based search with real function-calling + Crawl4AI hybrid. Upgrade Crawl4AI to use `fit_markdown=True` for cleaner extractions.

**Architecture:** Two independent changes: (1) Crawl4AI config upgrade in `ingesters/web.py`, (2) `_search_minimax()` replacement in `discovery_scheduler.py` using 2-round hybrid: tool-call first, then regex-URL fallback + Crawl4AI fetch.

**Tech Stack:** Python asyncio, crawl4ai `CrawlerRunConfig`, MiniMax chat API with `tools` parameter

---

## Task 1: Crawl4AI `fit_markdown` upgrade

**Files:**
- Modify: `ingesters/web.py:1-10`
- Test: `tests/test_discovery_scheduler.py` (add integration test for snippet cleanliness)

- [ ] **Step 1: Add CrawlerRunConfig import**

Modify `ingesters/web.py:1`:
```python
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
```

- [ ] **Step 2: Add config with fit_markdown=True**

Modify `ingesters/web.py:4-9`:
```python
async def extract_url(url: str) -> str:
    config = CrawlerRunConfig(fit_markdown=True)
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url, config=config)
    if not result.success or not result.markdown:
        raise ValueError(f"Failed to extract content from: {url}")
    return str(result.markdown)
```

- [ ] **Step 3: Test extract_url still works**

Run: `.venv/bin/python -c "import asyncio; from ingesters.web import extract_url; print(asyncio.run(extract_url('https://example.com')[:100]))"`
Expected: Clean markdown without nav/footer text

- [ ] **Step 4: Commit**

```bash
git add ingesters/web.py
git commit -m "feat: enable fit_markdown in Crawl4AI extraction"
```

---

## Task 2: MiniMax search with Crawl4AI content fetching

> **Approach changed:** Instead of tool-calling, we improve the existing HEAD-validate approach. MiniMax LLM provides URLs via prompt → HEAD-validate each → Crawl4AI fetches actual content → extract clean snippets. This is more reliable than tool-calling since MiniMax's tool support is uncertain, and Crawl4AI ensures we get real content not LLM-hallucinated snippets.

**Files:**
- Modify: `core/discovery_scheduler.py:234-272`
- Test: `tests/test_discovery_scheduler.py` (add `test_search_minimax_with_tool_calls` and `test_search_minimax_fallback`)

- [ ] **Step 1: Write test for tool-call response parsing**

Add to `tests/test_discovery_scheduler.py`:

```python
def test_search_minimax_parses_tool_calls(monkeypatch):
    """When MiniMax returns tool_calls with URLs, extract them without LLM."""
    from core.discovery_scheduler import DiscoveryScheduler
    import json

    class FakeResponse:
        def raise_for_status(self):
            pass
        def json(self):
            return {
                "choices": [{
                    "message": {
                        "content": "I'll search for that",
                        "tool_calls": [{
                            "function": {
                                "name": "web_search",
                                "arguments": json.dumps({
                                    "results": [
                                        {"url": "https://arxiv.org/abs/1234.5678", "title": "RL Paper"},
                                        {"url": "https://arxiv.org/abs/2345.6789", "title": "RL Survey"},
                                        {"url": "https://arxiv.org/abs/3456.7890", "title": "RL Book"},
                                    ]
                                })
                            }
                        }]
                    }
                }]
            }

    class FakeRequests:
        def post(self, url, headers=None, json=None, timeout=None):
            return FakeResponse()

    ds = DiscoveryScheduler()
    # Monkey-patch requests at the module level
    monkeypatch.setattr("core.discovery_scheduler.requests", FakeRequests())

    # Also patch _fetch_article_snippet to return canned snippets
    async def fake_fetch(url):
        return f"Content from {url}"
    ds._fetch_article_snippet = fake_fetch

    results = ds._search_minimax("reinforcement learning")

    assert len(results) == 3
    assert results[0]["source"] == "minimax"
    assert results[0]["url"].startswith("https://")
    assert "Content from" in results[0]["snippet"]
```

- [ ] **Step 2: Run test to verify it fails (method doesn't exist yet)**

Run: `.venv/bin/python -m pytest tests/test_discovery_scheduler.py::test_search_minimax_parses_tool_calls -v 2>&1 | tail -10`
Expected: `AttributeError: '_search_minimax' is a plain function, not a method` (test tries to call it on instance, need to restructure — the method signature takes `self` so we need to instantiate properly)

Note: The current `_search_minimax` is a method on `DiscoveryScheduler`. Update the test to create a `DiscoveryScheduler` instance first, then patch `requests.post` at the `core.discovery_scheduler` module level.

Fix test by also monkeypatching the module-level `requests`:

```python
def test_search_minimax_parses_tool_calls(monkeypatch):
    from core import discovery_scheduler
    monkeypatch.setattr(discovery_scheduler, "requests", FakeRequests())
    ds = DiscoveryScheduler()
    async def fake_fetch(url):
        return f"Content from {url}"
    ds._fetch_article_snippet = fake_fetch
    results = ds._search_minimax("reinforcement learning")
    assert len(results) == 3
```

- [ ] **Step 3: Write test for fallback (no tool_calls, parse URLs from text)**

Add to `tests/test_discovery_scheduler.py`:

```python
def test_search_minimax_fallback_parses_urls_from_text(monkeypatch):
    """When MiniMax returns no tool_calls but has URLs in text, crawl them."""
    from core import discovery_scheduler

    class FakeResponse:
        def raise_for_status(self):
            pass
        def json(self):
            return {
                "choices": [{
                    "message": {
                        "content": "Here are some results: https://arxiv.org/abs/1111, https://example.com/article"
                    }
                }]
            }

    class FakeRequests:
        def post(self, url, headers=None, json=None, timeout=None):
            return FakeResponse()

    monkeypatch.setattr(discovery_scheduler, "requests", FakeRequests())
    ds = DiscoveryScheduler()

    # Patch _fetch_article_snippet to be sync (returns plain string, not coroutine)
    # so loop.run_until_complete works correctly
    def sync_fetch(url):
        return f"Real article content from {url}"

    ds._fetch_article_snippet = sync_fetch

    results = ds._search_minimax("machine learning")

    # Should crawl the found URLs and return results
    assert len(results) >= 1
    assert results[0]["source"] == "minimax"
```

- [ ] **Step 4: Run fallback test — verify it fails (method still old)**

Run: `.venv/bin/python -m pytest tests/test_discovery_scheduler.py::test_search_minimax_fallback_parses_urls_from_text -v 2>&1 | tail -5`
Expected: FAIL — old implementation ignores text URLs

- [ ] **Step 5: Replace _search_minimax with hybrid implementation**

Modify `core/discovery_scheduler.py:234-272`. Replace the existing `_search_minimax` method with:

```python
def _search_minimax(self, keyword: str, limit: int = 3) -> list[dict]:
    """
    Web search via MiniMax function-calling tool (2-round hybrid).
    Round 1: Ask MiniMax to call web_search tool with real URLs.
    Round 2 (fallback): If no tool_calls, parse text response for URLs and Crawl4AI fetch.
    Returns list of {url, title, snippet, source}.
    """
    import requests as _req
    from config import MINIMAX_API_KEY, MINIMAX_MODEL, MINIMAX_API_URL

    if not MINIMAX_API_KEY:
        return []

    tools = [{
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for real URLs about a topic",
            "parameters": {
                "type": "object",
                "properties": {
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "url": {"type": "string"},
                                "title": {"type": "string"},
                                "snippet": {"type": "string"},
                            },
                            "required": ["url", "title", "snippet"]
                        }
                    }
                },
                "required": ["results"]
            }
        }
    }]

    prompt = f"Search the web for: {keyword}\nReturn exactly 3 results with url, title, and a short snippet."

    headers = {"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MINIMAX_MODEL,
        "messages": [
            {"role": "system", "content": "You are a web search assistant. Use the web_search tool to return real URLs."},
            {"role": "user", "content": prompt},
        ],
        "tools": tools,
    }

    try:
        resp = _req.post(MINIMAX_API_URL, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        message = (data.get("choices", [{}])[0].get("message", {}))

        # Round 1: extract URLs from tool_calls
        found_urls = []
        for tc in message.get("tool_calls", []):
            fn = tc.get("function", {})
            if fn.get("name") == "web_search":
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                    for r in args.get("results", []):
                        if r.get("url"):
                            found_urls.append({
                                "url": r["url"],
                                "title": r.get("title", ""),
                                "snippet": r.get("snippet", "")[:200],
                            })
                except (json.JSONDecodeError, KeyError):
                    pass

        # Round 2 fallback: if no tool_calls, parse URLs from text
        if not found_urls:
            text = message.get("content", "")
            for match in re.finditer(r"https://[^\s<>\"'\)]+", text):
                url = match.group(0).rstrip(".,;")
                found_urls.append({"url": url, "title": "", "snippet": ""})

        if not found_urls:
            _logger.warning("Discovery: MiniMax returned no URLs for %s", keyword)
            return []

        # Fetch snippets for results that have empty snippets
        results = []
        seen = set()
        for r in found_urls:
            url = r["url"]
            if not url or url in seen:
                continue
            seen.add(url)
            snippet = r["snippet"]
            if not snippet:
                # Fetch article content for snippet (handles both sync and async _fetch_article_snippet)
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        fetch_result = self._fetch_article_snippet(url)
                        if asyncio.iscoroutine(fetch_result):
                            snippet = loop.run_until_complete(fetch_result)
                        else:
                            snippet = fetch_result
                    finally:
                        loop.close()
                except Exception:
                    snippet = ""
            results.append({
                "url": url,
                "title": r.get("title", url.split("/")[-1]),
                "snippet": snippet[:200],
                "source": "minimax",
            })
            if len(results) >= limit:
                break

        return results

    except Exception as e:
        _logger.warning("Discovery: MiniMax search failed for %s: %s", keyword, e)
        return []
```

- [ ] **Step 6: Run tool-call test**

Run: `.venv/bin/python -m pytest tests/test_discovery_scheduler.py::test_search_minimax_parses_tool_calls -v 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 7: Run fallback test**

Run: `.venv/bin/python -m pytest tests/test_discovery_scheduler.py::test_search_minimax_fallback_parses_urls_from_text -v 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 8: Run full discovery scheduler test suite**

Run: `.venv/bin/python -m pytest tests/test_discovery_scheduler.py -v 2>&1 | tail -15`
Expected: All pass

- [ ] **Step 9: Commit**

```bash
git add core/discovery_scheduler.py tests/test_discovery_scheduler.py
git commit -m "feat: replace MiniMax prompt-hallucination with real function-calling + Crawl4AI hybrid"
```

---

## Task 3: Integration test (real data)

**Files:**
- Modify: `tests/test_discovery_scheduler.py` (add integration test, marked `pytest.mark.integration`)

- [ ] **Step 1: Write real integration test**

Add to `tests/test_discovery_scheduler.py`:

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_minimax_returns_real_urls():
    """Verify MiniMax search returns real, crawlable URLs for a known topic."""
    from core.discovery_scheduler import DiscoveryScheduler
    ds = DiscoveryScheduler()

    # Use a topic likely to have real results
    results = await ds._search_minimax("reinforcement learning")

    assert len(results) >= 1, "Should return at least 1 result"
    for r in results:
        assert r["source"] == "minimax"
        assert r["url"].startswith("https://"), f"URL should be real: {r['url']}"
        assert not r["url"].endswith(".pdf") or "arxiv" in r["url"], "Should not hallucinate PDF URLs"
        assert len(r["snippet"]) > 20, "Snippet should not be empty"
```

- [ ] **Step 2: Run integration test**

Run: `.venv/bin/python -m pytest tests/test_discovery_scheduler.py::test_search_minimax_returns_real_urls -v 2>&1 | tail -15`
Expected: PASS — real URLs, non-empty snippets

- [ ] **Step 3: Commit**

```bash
git add tests/test_discovery_scheduler.py
git commit -m "test: add integration test for real MiniMax search results"
```

---

## Self-Review Checklist

- [ ] Spec coverage: Both parts (Crawl4AI + MiniMax) have tasks
- [ ] No placeholders: all code blocks have real Python
- [ ] Type consistency: method signatures match between test and implementation
- [ ] Tests verify both Round 1 (tool_calls) and Round 2 (fallback)
- [ ] `requests` is imported inside the method to avoid module-level side effects
