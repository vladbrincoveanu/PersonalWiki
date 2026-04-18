# Discovery Sitemap Pipeline Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enqueued sitemap URLs are discovered via `_enqueue_interest_domain` but never ingested. Fix: push to `_sitemap_queue` and drain it in `_run_discovery_cycle` alongside keyword search results.

**Architecture:** Add `asyncio.Queue` to DiscoveryScheduler. Phase 2 drain of sitemap queue in `_run_discovery_cycle` after keyword searches, sharing `MAX_URLS_PER_CYCLE` budget across both sources.

**Tech Stack:** Python asyncio, existing `DiscoveryScheduler`, existing tests

---

## File Map

- `core/discovery_scheduler.py` — modify `__init__`, `_enqueue_interest_domain`, `_run_discovery_cycle`
- `tests/test_discovery_scheduler.py` — add tests for new behavior

---

## Task 1: Add `_sitemap_queue` to `DiscoveryScheduler.__init__`

**Files:**
- Modify: `core/discovery_scheduler.py:131-148`

- [ ] **Step 1: Write the failing test**

```python
def test_sitemap_queue_initialized():
    """Scheduler initializes with empty sitemap queue."""
    from core.discovery_scheduler import DiscoveryScheduler
    scheduler = DiscoveryScheduler()
    assert hasattr(scheduler, '_sitemap_queue')
    assert scheduler._sitemap_queue.empty()
    scheduler.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_discovery_scheduler.py::test_sitemap_queue_initialized -v`
Expected: FAIL — AttributeError: 'DiscoveryScheduler' has no attribute '_sitemap_queue'

- [ ] **Step 3: Add queue to __init__**

Find line 143 in `discovery_scheduler.py`. After `self._interest_domains: set[str] = set()` add:

```python
self._sitemap_queue: asyncio.Queue[str] = asyncio.Queue()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_discovery_scheduler.py::test_sitemap_queue_initialized -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/discovery_scheduler.py tests/test_discovery_scheduler.py
git commit -m "feat: add _sitemap_queue to DiscoveryScheduler"
```

---

## Task 2: Change `_enqueue_interest_domain` to push to queue

**Files:**
- Modify: `core/discovery_scheduler.py:292-309`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_discovery_scheduler.py::test_enqueue_interest_domain_pushes_to_queue -v`
Expected: FAIL — AssertionError on qsize() == 0 (queue empty, URLs went to _seen_urls)

- [ ] **Step 3: Change `_enqueue_interest_domain` body**

Replace the end of the method (lines ~304-309):
```python
        for url in sitemap_urls:
            if self._is_new_url(url):
                self._seen_urls.add(url)
```

With:
```python
        for url in sitemap_urls:
            if self._is_new_url(url):
                self._sitemap_queue.put_nowait(url)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_discovery_scheduler.py::test_enqueue_interest_domain_pushes_to_queue -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/discovery_scheduler.py tests/test_discovery_scheduler.py
git commit -m "fix: _enqueue_interest_domain pushes to queue not _seen_urls"
```

---

## Task 3: Add Phase 2 sitemap queue drain in `_run_discovery_cycle`

**Files:**
- Modify: `core/discovery_scheduler.py:679-744`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_discovery_scheduler.py::test_discovery_cycle_drains_sitemap_queue -v`
Expected: FAIL — `AttributeError` or queue not drained

- [ ] **Step 3: Add Phase 2 drain after keyword loop**

Find `if ingested >= MAX_URLS_PER_CYCLE: break` at line ~690 and the `for result in results` inner loop ends around line ~724. After `self._persist_seen_urls()` (line ~727) and before `# Echo chamber guard`, add:

```python
        # Phase 2: drain sitemap queue (new)
        while ingested < MAX_URLS_PER_CYCLE:
            try:
                url = self._sitemap_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            if url in seen_this_cycle or store.exists(url):
                self._seen_urls.add(url)
                continue

            seen_this_cycle.add(url)
            await self._run_pipeline(url)
            ingested += 1
            self._seen_urls.add(url)
```

Also add `seen_this_cycle` initialization near `ingested = 0`. Add after `store = get_store()`:
```python
        seen_this_cycle: set[str] = set()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_discovery_scheduler.py::test_discovery_cycle_drains_sitemap_queue -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/discovery_scheduler.py tests/test_discovery_scheduler.py
git commit -m "feat: phase 2 sitemap queue drain in discovery cycle"
```

---

## Task 4: Rate limit shared across keyword + sitemap phases

**Files:**
- Modify: `tests/test_discovery_scheduler.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_discovery_scheduler.py::test_rate_limit_shared_across_phases -v`
Expected: FAIL if phase 2 doesn't respect limit

- [ ] **Step 3: Verify code already respects limit**

The Phase 2 drain uses `while ingested < MAX_URLS_PER_CYCLE` which is already correct from Task 3. Run the test again after Task 3 — it should pass. If it fails, check the `while` condition is correctly placed.

- [ ] **Step 4: Commit**

```bash
git add core/discovery_scheduler.py tests/test_discovery_scheduler.py
git commit -m "test: rate limit shared across keyword and sitemap phases"
```

---

## Task 5: Full integration — sitemap URL appears in vault

**Files:**
- Modify: `tests/test_discovery_integration.py`

- [ ] **Step 1: Write the failing integration test**

```python
@pytest.mark.asyncio
async def test_discovery_enqueues_sitemap_url_and_ingests():
    """Full cycle: enqueued sitemap URL is ingested and appears in vault."""
    from core.discovery_scheduler import DiscoveryScheduler

    scheduler = DiscoveryScheduler()

    # Enqueue a domain (this fetches sitemap, puts URLs in queue)
    with patch.object(scheduler, '_try_sitemap', return_value=[
        'https://real-article.com/transformers-explained',
    ]):
        scheduler._enqueue_interest_domain('real-article.com')

    # Queue should have the URL
    assert scheduler._sitemap_queue.qsize() == 1

    pipeline_calls = []
    async def mock_run_pipeline(url):
        pipeline_calls.append(url)

    scheduler._run_pipeline = mock_run_pipeline

    # Mock keyword search to return nothing, store to return False for exists
    with patch.object(scheduler, '_search_keyword', return_value=[]):
        with patch('core.vector_store.get_store') as mock_store:
            mock_store_instance = MagicMock()
            mock_store_instance.exists.return_value = False
            mock_store.return_value = mock_store_instance
            await scheduler._run_discovery_cycle()

    # URL should have been ingested via the pipeline
    assert len(pipeline_calls) == 1
    assert 'https://real-article.com/transformers-explained' in pipeline_calls

    scheduler.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_discovery_integration.py::test_discovery_enqueues_sitemap_url_and_ingests -v`
Expected: FAIL before full implementation

- [ ] **Step 3: All code already added in Tasks 1-3 — verify passes**

Run: `pytest tests/test_discovery_integration.py::test_discovery_enqueues_sitemap_url_and_ingests -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add core/discovery_scheduler.py tests/test_discovery_integration.py
git commit -m "test: integration test for sitemap URL ingestion via discovery cycle"
```

---

## Spec Coverage Check

| Spec requirement | Task |
|----------------|------|
| `_sitemap_queue` added to `__init__` | Task 1 |
| `_enqueue_interest_domain` pushes to queue | Task 2 |
| Phase 2 drain in `_run_discovery_cycle` | Task 3 |
| Rate limit shared across phases | Task 4 |
| Full integration (sitemap URL in vault) | Task 5 |

All spec requirements covered. No gaps.
