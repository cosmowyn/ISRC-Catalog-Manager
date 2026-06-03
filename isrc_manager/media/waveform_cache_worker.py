"""Background worker orchestration for audio waveform cache generation."""

from __future__ import annotations

import queue
import threading
from contextlib import suppress
from pathlib import Path

from PySide6.QtCore import QTimer

from isrc_manager.media.waveform_cache import AudioWaveformCacheService
from isrc_manager.services.db_access import SQLiteConnectionFactory
from isrc_manager.services.tracks import TrackService


class AudioWaveformCacheWorker:
    """Dedicated daemon for cache generation and validation on its own DB connection."""

    _STOP = object()

    def __init__(
        self,
        *,
        db_path: str | Path,
        data_root: str | Path,
        connection_factory=None,
        logger=None,
        name: str = "AudioWaveformCacheWorker",
    ):
        self.db_path = str(Path(db_path))
        self.data_root = Path(data_root)
        self.connection_factory = connection_factory
        self.logger = logger
        self.name = str(name or "AudioWaveformCacheWorker")
        self._queue: queue.Queue[tuple[str, int | None, bool] | object] = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pending_tracks: set[int] = set()
        self._pending_all = False

    def is_for_database(self, db_path: str | Path) -> bool:
        return self.db_path == str(Path(db_path))

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
            self._thread.start()

    def stop(self, *, wait: bool = False, timeout: float = 2.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            self._queue.put(self._STOP)
            if wait:
                thread.join(timeout=max(0.0, float(timeout)))
        with self._lock:
            self._pending_tracks.clear()
            self._pending_all = False

    def enqueue_track(self, track_id: int, *, force: bool = False) -> bool:
        clean_track_id = int(track_id)
        if clean_track_id <= 0:
            return False
        self.start()
        with self._lock:
            if clean_track_id in self._pending_tracks:
                return False
            self._pending_tracks.add(clean_track_id)
        self._queue.put(("track", clean_track_id, bool(force)))
        return True

    def enqueue_all(self, *, force: bool = False) -> bool:
        self.start()
        with self._lock:
            if self._pending_all:
                return False
            self._pending_all = True
        self._queue.put(("all", None, bool(force)))
        return True

    def _log_debug(self, message: str, *args) -> None:
        logger = self.logger
        if logger is not None:
            with suppress(Exception):
                logger.debug(message, *args)

    def _log_warning(self, message: str, *args) -> None:
        logger = self.logger
        if logger is not None:
            with suppress(Exception):
                logger.warning(message, *args)

    def _clear_pending_jobs(self) -> None:
        with self._lock:
            self._pending_tracks.clear()
            self._pending_all = False

    def _open_worker_services(self):
        factory = self.connection_factory or SQLiteConnectionFactory()
        conn = factory.open(self.db_path)
        service = AudioWaveformCacheService(conn)
        track_service = TrackService(conn, self.data_root, require_governed_creation=True)
        return conn, service, track_service

    def _run(self) -> None:
        try:
            conn, service, track_service = self._open_worker_services()
        except Exception as exc:
            self._log_warning("Could not start waveform cache worker for %s: %s", self.db_path, exc)
            self._clear_pending_jobs()
            return
        try:
            while not self._stop_event.is_set():
                job = self._queue.get()
                if job is self._STOP:
                    break
                if not isinstance(job, tuple):
                    continue
                kind, track_id, force = job
                try:
                    if kind == "all":
                        summary = service.ensure_all_track_caches(track_service)
                        conn.commit()
                        self._log_debug(
                            "Waveform cache background pass completed for %s: %s checked, "
                            "%s rendered, %s reused, %s skipped, %s errors",
                            self.db_path,
                            summary.checked,
                            summary.rendered,
                            summary.reused,
                            summary.skipped,
                            summary.errors,
                        )
                    elif kind == "track" and track_id is not None:
                        service.ensure_track_cache(track_service, int(track_id), force=bool(force))
                        conn.commit()
                        self._log_debug(
                            "Waveform cache background job completed for track %s",
                            track_id,
                        )
                except Exception as exc:
                    with suppress(Exception):
                        conn.rollback()
                    self._log_warning("Waveform cache background job failed: %s", exc)
                finally:
                    with self._lock:
                        if kind == "all":
                            self._pending_all = False
                        elif track_id is not None:
                            self._pending_tracks.discard(int(track_id))
        finally:
            with suppress(Exception):
                conn.close()


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
    except TypeError:
        return False
    except ValueError:
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
