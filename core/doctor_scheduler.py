"""
Daily doctor scheduler — runs vault cleanup on a timer.
"""
import logging
import threading
import time

_logger = logging.getLogger(__name__)


class DoctorScheduler:
    def __init__(self, interval_hours: int = 24):
        self._interval_seconds = interval_hours * 3600
        self._running = False
        self._task: threading.Thread | None = None

    def start(self, discovery_scheduler_ref) -> None:
        """
        Start the doctor loop. discovery_scheduler_ref is the DiscoveryScheduler instance.
        Keywords are read from discovery_scheduler_ref._keywords (the SOT).
        """
        self._running = True
        self._task = threading.Thread(
            target=self._loop,
            args=(discovery_scheduler_ref,),
            daemon=True,
            name="doctor-scheduler",
        )
        self._task.start()
        _logger.info("Doctor scheduler started (interval=%dh)", self._interval_seconds // 3600)

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.join(timeout=5)
        _logger.info("Doctor scheduler stopped")

    def _loop(self, discovery_scheduler_ref) -> None:
        from vault.doctor import run_vault_doctor
        while self._running:
            time.sleep(self._interval_seconds)
            if not self._running:
                break
            try:
                # Read active keywords from the DiscoveryScheduler SOT
                keywords = list(discovery_scheduler_ref._keywords)
                result = run_vault_doctor(keywords)
                _logger.info(
                    "Doctor: cleaned vault — untitled=%d sparse=%d orphaned=%d video-no-content=%d total_deleted=%d",
                    len(result["untitled"]),
                    len(result["sparse"]),
                    len(result["orphaned"]),
                    len(result["video-no-content"]),
                    len(result["deleted"]),
                )
            except Exception as e:
                _logger.error("Doctor: vault cleanup failed: %s", e)
