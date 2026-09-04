import asyncio
import pytest
from unittest.mock import patch, AsyncMock


def test_keywords_endpoints_import():
    """Verify the /keywords endpoints are registered on the app."""
    with patch("app.scan_vault", return_value=0), \
         patch("app.run_pipeline"):
        from app import app

    routes = {r.path for r in app.routes}
    assert "/keywords" in routes, "GET /keywords not registered"
    assert "/keywords/add" in routes, "POST /keywords/add not registered"
    assert "/keywords/remove" in routes, "POST /keywords/remove not registered"


@pytest.mark.asyncio
async def test_get_scheduler_creates_singleton():
    """Verify _get_scheduler returns the same instance on repeated calls."""
    with patch("app.scan_vault", return_value=0), \
         patch("app.run_pipeline"):
        import app as app_module

        # Save and reset global state to test singleton creation
        saved_scheduler = app_module._scheduler
        saved_lock = app_module._scheduler_lock
        app_module._scheduler = None
        app_module._scheduler_lock = asyncio.Lock()

        try:
            with patch.object(app_module.DiscoveryScheduler, "start"):
                s1 = await app_module._get_scheduler()
                s2 = await app_module._get_scheduler()
                assert s1 is s2, "_get_scheduler should return singleton"
        finally:
            # Restore global state
            app_module._scheduler = saved_scheduler
            app_module._scheduler_lock = saved_lock


@pytest.mark.asyncio
async def test_get_scheduler_lazy_starts():
    """Verify _get_scheduler creates and starts scheduler on first call."""
    with patch("app.scan_vault", return_value=0), \
         patch("app.run_pipeline"):
        import app as app_module

        # Save and reset global state
        saved_scheduler = app_module._scheduler
        saved_lock = app_module._scheduler_lock
        app_module._scheduler = None
        app_module._scheduler_lock = asyncio.Lock()

        try:
            mock_start = AsyncMock()
            with patch.object(app_module.DiscoveryScheduler, "start", mock_start):
                s = await app_module._get_scheduler()
                assert mock_start.call_count == 1, "scheduler.start should be called on first _get_scheduler() call"
                assert s is app_module._scheduler, "scheduler should be stored in _scheduler module variable"
        finally:
            # Restore global state
            app_module._scheduler = saved_scheduler
            app_module._scheduler_lock = saved_lock
