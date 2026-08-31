import pytest
import asyncio
import ipaddress
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
def mock_public_dns_for_unit_tests(monkeypatch):
    """Keep URL tests offline while retaining literal private-IP checks."""
    def is_test_public_hostname(hostname: str) -> bool:
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            # DNS behavior belongs to the network/integration boundary; unit
            # tests should not depend on the runner's resolver.
            return True
        return not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        )

    monkeypatch.setattr("ingesters.router._is_public_hostname", is_test_public_hostname)


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

