import pytest
import asyncio
from unittest.mock import MagicMock, patch

# Prevent LanceDB segfaults in tests by mocking get_store early
_mock_store = MagicMock()
_mock_store.get_all_paths.return_value = []
# Patch at the source module where it's defined
patcher = patch("core.vector_store.get_store", return_value=_mock_store)
patcher.start()


@pytest.fixture(autouse=True)
def mock_vector_store():
    """Ensure get_store always returns a mock."""
    return _mock_store


@pytest.fixture(autouse=True)
def cleanup_discovery_scheduler():
    """Stop any DiscoveryScheduler background tasks after each test."""
    yield
    # Stop global scheduler if it was started by app.py or integration tests
    # Use lazy import to avoid event loop issues
    try:
        import sys as _sys
        if "app" in _sys.modules:
            _app = _sys.modules["app"]
            if hasattr(_app, "_scheduler") and _app._scheduler is not None:
                _app._scheduler.stop()
                _app._scheduler = None
            if hasattr(_app, "_scheduler_lock"):
                _app._scheduler_lock = None
    except Exception:
        pass


@pytest.fixture(autouse=True)
def cleanup_graph_keywords():
    """
    Reset graph_interests module globals before and after each test.

    _GRAPH_KEYWORDS_CACHE and _CACHED_VAULT_PATH are module-level globals that
    persist across tests in the same Python session. Without cleanup, a test
    that calls extract_interests() may read a stale _graph_keywords file
    written by a previous test to a pytest tmp_path directory, causing the
    cache hit path to return incorrect results.
    """
    import core.graph_interests as gi

    # Reset before test
    gi._GRAPH_KEYWORDS_CACHE = []
    gi._CACHED_VAULT_PATH = None

    yield

    # Reset after test
    gi._GRAPH_KEYWORDS_CACHE = []
    gi._CACHED_VAULT_PATH = None
