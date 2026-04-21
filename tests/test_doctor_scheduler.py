"""
Smoke test for core.doctor_scheduler.DoctorScheduler.
"""
import threading
import time
from unittest.mock import MagicMock

from core.doctor_scheduler import DoctorScheduler


def test_instantiate():
    """DoctorScheduler can be instantiated with default and custom interval."""
    ds = DoctorScheduler()
    assert ds._interval_seconds == 24 * 3600
    assert ds._running is False
    assert ds._task is None

    ds2 = DoctorScheduler(interval_hours=12)
    assert ds2._interval_seconds == 12 * 3600


def test_start_sets_running_and_launches_thread():
    """start() sets _running True and spawns a daemon thread."""
    mock_discovery = MagicMock()
    mock_discovery._keywords = {"python", "rust"}

    ds = DoctorScheduler(interval_hours=1)
    assert ds._running is False
    assert ds._task is None

    ds.start(mock_discovery)
    try:
        assert ds._running is True
        assert ds._task is not None
        assert isinstance(ds._task, threading.Thread)
        assert ds._task.daemon is True
        assert ds._task.name == "doctor-scheduler"
    finally:
        ds.stop()


def test_stop_clears_running_and_joins_thread():
    """stop() sets _running False and joins the thread."""
    mock_discovery = MagicMock()
    mock_discovery._keywords = set()

    ds = DoctorScheduler(interval_hours=24)
    ds.start(mock_discovery)
    time.sleep(0.05)  # let thread start
    ds.stop()

    assert ds._running is False
    assert ds._task is not None
    # join should have completed within timeout
