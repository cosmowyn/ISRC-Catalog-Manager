"""Audio waveform cache orchestration for the application shell."""

from __future__ import annotations

from PySide6.QtCore import QTimer

from isrc_manager.media.waveform_cache import AudioWaveformCacheService
from isrc_manager.media.waveform_cache_worker import AudioWaveformCacheWorker


def _audio_waveform_cache_service(self) -> AudioWaveformCacheService | None:
    if self.conn is None:
        return None
    service = getattr(self, "_audio_waveform_cache_service_instance", None)
    if service is None or getattr(service, "conn", None) is not self.conn:
        service = AudioWaveformCacheService(self.conn)
        self._audio_waveform_cache_service_instance = service
    return service


def _audio_waveform_cache_worker_for_current_profile(self) -> AudioWaveformCacheWorker | None:
    if self.conn is None:
        return None
    db_path = str(getattr(self, "current_db_path", "") or "").strip()
    if not db_path:
        return None
    worker = getattr(self, "_audio_waveform_cache_worker", None)
    if worker is not None and not worker.is_for_database(db_path):
        try:
            worker.stop(wait=False)
        except Exception:
            pass
        worker = None
    if worker is None:
        worker = AudioWaveformCacheWorker(
            db_path=db_path,
            data_root=self.data_root,
            connection_factory=getattr(self, "sqlite_connection_factory", None),
            logger=self.logger,
        )
        self._audio_waveform_cache_worker = worker
    return worker


def _stop_audio_waveform_cache_worker(self, *, wait: bool = False) -> None:
    worker = getattr(self, "_audio_waveform_cache_worker", None)
    if worker is None:
        return
    try:
        worker.stop(wait=wait)
    except Exception:
        pass
    self._audio_waveform_cache_worker = None


def _queue_audio_waveform_cache_for_track(
    self,
    track_id: int,
    *,
    delay_ms: int = 500,
    force: bool = False,
) -> bool:
    if getattr(self, "_is_closing", False):
        return False
    try:
        clean_track_id = int(track_id)
    except (TypeError, ValueError):
        return False
    if clean_track_id <= 0:
        return False

    def _enqueue() -> None:
        if getattr(self, "_is_closing", False):
            return
        worker = self._audio_waveform_cache_worker_for_current_profile()
        if worker is None:
            return
        worker.enqueue_track(clean_track_id, force=force)

    if int(delay_ms) > 0:
        QTimer.singleShot(int(delay_ms), _enqueue)
    else:
        _enqueue()
    return True


def _queue_startup_audio_waveform_cache_pass(self, *, progress_callback=None) -> None:
    if self.track_service is None:
        if callable(progress_callback):
            progress_callback(1, 1, "No track service available for waveform cache checks.")
        return
    worker = self._audio_waveform_cache_worker_for_current_profile()
    if worker is None:
        if callable(progress_callback):
            progress_callback(1, 1, "No profile database available for waveform cache checks.")
        return
    queued = worker.enqueue_all()
    if queued:
        self.logger.info("Queued background waveform cache validation")
    if callable(progress_callback):
        progress_callback(
            1,
            1,
            "Queued waveform cache validation in the background.",
        )


def _audio_waveform_cache_for_track(self, track_id: int):
    if self.track_service is None:
        return None
    service = self._audio_waveform_cache_service()
    if service is None:
        return None
    try:
        cached = service.get_cached_waveform(
            int(track_id),
            track_service=self.track_service,
            validate_source=True,
        )
        if cached is None:
            self._queue_audio_waveform_cache_for_track(int(track_id), delay_ms=0)
        return cached
    except Exception as exc:
        self.logger.debug(
            "Waveform cache unavailable for track %s: %s",
            track_id,
            exc,
        )
        return None


def _run_startup_audio_waveform_cache_pass(self, *, progress_callback=None) -> None:
    self._queue_startup_audio_waveform_cache_pass(progress_callback=progress_callback)
