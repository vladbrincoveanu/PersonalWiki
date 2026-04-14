import sys
import pytest
from unittest.mock import patch, MagicMock

# Mock whisper before importing app to avoid ModuleNotFoundError
sys.modules["whisper"] = MagicMock()


def test_keywords_endpoints_import():
    """Verify the /keywords endpoints are registered on the app."""
    with patch("app.scan_vault", return_value=0), \
         patch("app.run_pipeline"):
        from app import app

    routes = {r.path for r in app.routes}
    assert "/keywords" in routes, "GET /keywords not registered"
    assert "/keywords/add" in routes, "POST /keywords/add not registered"
    assert "/keywords/remove" in routes, "POST /keywords/remove not registered"


def test_get_scheduler_creates_singleton():
    """Verify _get_scheduler returns the same instance on repeated calls."""
    with patch("app.scan_vault", return_value=0), \
         patch("app.run_pipeline"):
        # Import fresh to reset module state
        import importlib
        import app as app_module
        importlib.reload(app_module)

        with patch.object(app_module.DiscoveryScheduler, "start"):
            s1 = app_module._get_scheduler()
            s2 = app_module._get_scheduler()
            assert s1 is s2, "_get_scheduler should return singleton"


def test_get_scheduler_lazy_starts():
    """Verify _get_scheduler creates and starts scheduler on first call."""
    with patch("app.scan_vault", return_value=0), \
         patch("app.run_pipeline"):
        import importlib
        import app as app_module
        importlib.reload(app_module)

        mock_start = MagicMock()
        with patch.object(app_module.DiscoveryScheduler, "start", mock_start):
            s = app_module._get_scheduler()
            assert mock_start.call_count == 1, "scheduler.start should be called on first _get_scheduler() call"
            assert s is app_module._scheduler, "scheduler should be stored in _scheduler module variable"
