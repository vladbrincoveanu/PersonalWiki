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


