from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from isrc_manager.media import waveform_cache_worker
from isrc_manager.media.waveform_cache_worker import AudioWaveformCacheWorker


def test_worker_enqueue_deduplicates_rejects_invalid_and_stop_clears_pending(tmp_path):
    worker = AudioWaveformCacheWorker(db_path=tmp_path / "catalog.db", data_root=tmp_path)
    worker.start = mock.Mock()

    assert worker.enqueue_track(0) is False
    assert worker.start.call_count == 0

    assert worker.enqueue_track(7, force=True) is True
    assert worker.enqueue_track(7) is False
    assert worker._pending_tracks == {7}

    assert worker.enqueue_all() is True
    assert worker.enqueue_all() is False
    assert worker._pending_all is True

    fake_thread = SimpleNamespace(is_alive=mock.Mock(return_value=True), join=mock.Mock())
    worker._thread = fake_thread
    worker.stop(wait=True, timeout=0.01)

    fake_thread.join.assert_called_once_with(timeout=0.01)
    assert worker._pending_tracks == set()
    assert worker._pending_all is False


def test_worker_database_identity_start_and_open_services(monkeypatch, tmp_path):
    started_threads = []

    class FakeThread:
        def __init__(self, *, target, name, daemon):
            self.target = target
            self.name = name
            self.daemon = daemon
            self.started = False
            started_threads.append(self)

        def is_alive(self):
            return self.started

        def start(self):
            self.started = True

    monkeypatch.setattr(
        waveform_cache_worker.threading,
        "Thread",
        FakeThread,
    )
    worker = AudioWaveformCacheWorker(
        db_path=tmp_path / "catalog.db",
        data_root=tmp_path / "data",
        name="",
    )

    assert worker.is_for_database(tmp_path / "catalog.db") is True
    assert worker.is_for_database(tmp_path / "other.db") is False

    worker.start()
    worker.start()

    assert len(started_threads) == 1
    assert started_threads[0].name == "AudioWaveformCacheWorker"
    assert started_threads[0].daemon is True

    conn = object()
    factory = SimpleNamespace(open=mock.Mock(return_value=conn))

    class FakeCacheService:
        def __init__(self, connection):
            self.connection = connection

    class FakeTrackService:
        def __init__(self, connection, data_root, *, require_governed_creation):
            self.connection = connection
            self.data_root = data_root
            self.require_governed_creation = require_governed_creation

    monkeypatch.setattr(waveform_cache_worker, "AudioWaveformCacheService", FakeCacheService)
    monkeypatch.setattr(waveform_cache_worker, "TrackService", FakeTrackService)
    worker.connection_factory = factory

    opened_conn, cache_service, track_service = worker._open_worker_services()

    assert opened_conn is conn
    assert cache_service.connection is conn
    assert track_service.connection is conn
    assert track_service.data_root == tmp_path / "data"
    assert track_service.require_governed_creation is True


def test_worker_logging_and_open_failure_clear_pending(tmp_path):
    logger = SimpleNamespace(
        debug=mock.Mock(side_effect=RuntimeError("debug unavailable")),
        warning=mock.Mock(side_effect=RuntimeError("warning unavailable")),
    )
    worker = AudioWaveformCacheWorker(
        db_path=tmp_path / "catalog.db",
        data_root=tmp_path,
        logger=logger,
    )
    worker._pending_tracks.add(4)
    worker._pending_all = True

    worker._log_debug("debug %s", "message")
    worker._log_warning("warning %s", "message")
    worker._open_worker_services = mock.Mock(side_effect=RuntimeError("open failed"))

    worker._run()

    logger.debug.assert_called_once()
    logger.warning.assert_called()
    assert worker._pending_tracks == set()
    assert worker._pending_all is False


def test_worker_logging_without_logger_and_run_with_preexisting_stop(tmp_path):
    worker = AudioWaveformCacheWorker(db_path=tmp_path / "catalog.db", data_root=tmp_path)
    worker._log_debug("ignored")
    worker._log_warning("ignored")

    conn = SimpleNamespace(close=mock.Mock())
    worker._open_worker_services = mock.Mock(return_value=(conn, object(), object()))
    worker._stop_event.set()

    worker._run()

    conn.close.assert_called_once_with()


def test_worker_run_processes_invalid_all_track_error_and_stop_jobs(tmp_path):
    summary = SimpleNamespace(checked=3, rendered=1, reused=1, skipped=1, errors=0)
    service = SimpleNamespace(
        ensure_all_track_caches=mock.Mock(return_value=summary),
        ensure_track_cache=mock.Mock(side_effect=[None, RuntimeError("render failed")]),
    )
    conn = SimpleNamespace(
        commit=mock.Mock(),
        rollback=mock.Mock(),
        close=mock.Mock(),
    )
    logger = SimpleNamespace(debug=mock.Mock(), warning=mock.Mock())
    worker = AudioWaveformCacheWorker(
        db_path=tmp_path / "catalog.db",
        data_root=tmp_path,
        logger=logger,
    )
    worker._open_worker_services = mock.Mock(return_value=(conn, service, object()))
    worker._pending_all = True
    worker._pending_tracks.update({7, 8})
    worker._queue.put(object())
    worker._queue.put(("unknown", None, False))
    worker._queue.put(("all", None, False))
    worker._queue.put(("track", 7, True))
    worker._queue.put(("track", 8, False))
    worker._queue.put(worker._STOP)

    worker._run()

    service.ensure_all_track_caches.assert_called_once()
    service.ensure_track_cache.assert_has_calls(
        [
            mock.call(mock.ANY, 7, force=True),
            mock.call(mock.ANY, 8, force=False),
        ]
    )
    assert conn.commit.call_count == 2
    conn.rollback.assert_called_once_with()
    conn.close.assert_called_once_with()
    logger.debug.assert_called()
    logger.warning.assert_called_once()
    assert worker._pending_all is False
    assert worker._pending_tracks == set()


def test_audio_waveform_cache_service_reuses_service_for_same_connection(monkeypatch):
    class FakeCacheService:
        def __init__(self, conn):
            self.conn = conn

    monkeypatch.setattr(waveform_cache_worker, "AudioWaveformCacheService", FakeCacheService)
    app = SimpleNamespace(conn=None)

    assert waveform_cache_worker._audio_waveform_cache_service(app) is None

    app.conn = object()
    first = waveform_cache_worker._audio_waveform_cache_service(app)
    second = waveform_cache_worker._audio_waveform_cache_service(app)
    assert first is second

    app.conn = object()
    third = waveform_cache_worker._audio_waveform_cache_service(app)
    assert third is not first
    assert third.conn is app.conn


def test_worker_for_current_profile_handles_missing_and_replaced_profiles(monkeypatch, tmp_path):
    assert (
        waveform_cache_worker._audio_waveform_cache_worker_for_current_profile(
            SimpleNamespace(conn=None)
        )
        is None
    )
    assert (
        waveform_cache_worker._audio_waveform_cache_worker_for_current_profile(
            SimpleNamespace(conn=object(), current_db_path="")
        )
        is None
    )

    class StaleWorker:
        def is_for_database(self, _db_path):
            return False

        def stop(self, *, wait):
            raise RuntimeError("stop failed")

    created = []

    class FakeWorker:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created.append(self)

        def is_for_database(self, db_path):
            return self.kwargs["db_path"] == db_path

    monkeypatch.setattr(waveform_cache_worker, "AudioWaveformCacheWorker", FakeWorker)
    app = SimpleNamespace(
        conn=object(),
        current_db_path=tmp_path / "catalog.db",
        data_root=tmp_path / "data",
        sqlite_connection_factory=object(),
        logger=object(),
        _audio_waveform_cache_worker=StaleWorker(),
    )

    worker = waveform_cache_worker._audio_waveform_cache_worker_for_current_profile(app)

    assert worker is created[0]
    assert app._audio_waveform_cache_worker is worker
    assert worker.kwargs["db_path"] == str(app.current_db_path)
    assert worker.kwargs["data_root"] == app.data_root

    assert waveform_cache_worker._audio_waveform_cache_worker_for_current_profile(app) is worker


def test_stop_audio_waveform_cache_worker_ignores_missing_and_stop_errors():
    app = SimpleNamespace()
    waveform_cache_worker._stop_audio_waveform_cache_worker(app, wait=True)

    worker = SimpleNamespace(stop=mock.Mock(side_effect=RuntimeError("stop failed")))
    app._audio_waveform_cache_worker = worker

    waveform_cache_worker._stop_audio_waveform_cache_worker(app, wait=True)

    worker.stop.assert_called_once_with(wait=True)
    assert app._audio_waveform_cache_worker is None


def test_queue_audio_waveform_cache_for_track_immediate_and_delayed(monkeypatch):
    worker = SimpleNamespace(enqueue_track=mock.Mock())
    app = SimpleNamespace(
        _is_closing=True,
        _audio_waveform_cache_worker_for_current_profile=mock.Mock(return_value=worker),
    )

    assert waveform_cache_worker._queue_audio_waveform_cache_for_track(app, 3, delay_ms=0) is False
    assert (
        waveform_cache_worker._queue_audio_waveform_cache_for_track(app, None, delay_ms=0) is False
    )
    assert (
        waveform_cache_worker._queue_audio_waveform_cache_for_track(app, "bad", delay_ms=0) is False
    )
    assert waveform_cache_worker._queue_audio_waveform_cache_for_track(app, 0, delay_ms=0) is False

    app._is_closing = False
    app._audio_waveform_cache_worker_for_current_profile.return_value = None
    assert waveform_cache_worker._queue_audio_waveform_cache_for_track(app, 3, delay_ms=0) is True
    worker.enqueue_track.assert_not_called()

    app._audio_waveform_cache_worker_for_current_profile.return_value = worker
    assert (
        waveform_cache_worker._queue_audio_waveform_cache_for_track(
            app, "4", delay_ms=0, force=True
        )
        is True
    )
    worker.enqueue_track.assert_called_once_with(4, force=True)

    callbacks = []

    def fake_single_shot(delay_ms, callback):
        callbacks.append(delay_ms)
        app._is_closing = True
        callback()

    monkeypatch.setattr(
        waveform_cache_worker,
        "QTimer",
        SimpleNamespace(singleShot=fake_single_shot),
    )

    assert waveform_cache_worker._queue_audio_waveform_cache_for_track(app, 5, delay_ms=25) is True
    assert callbacks == [25]
    assert worker.enqueue_track.call_count == 1


def test_queue_startup_waveform_cache_pass_progress_branches():
    progress = mock.Mock()
    app = SimpleNamespace(track_service=None)

    waveform_cache_worker._queue_startup_audio_waveform_cache_pass(app, progress_callback=progress)
    progress.assert_called_once_with(1, 1, "No track service available for waveform cache checks.")

    progress.reset_mock()
    app = SimpleNamespace(
        track_service=object(),
        _audio_waveform_cache_worker_for_current_profile=mock.Mock(return_value=None),
    )
    waveform_cache_worker._queue_startup_audio_waveform_cache_pass(app, progress_callback=progress)
    progress.assert_called_once_with(
        1, 1, "No profile database available for waveform cache checks."
    )

    progress.reset_mock()
    worker = SimpleNamespace(enqueue_all=mock.Mock(return_value=True))
    app = SimpleNamespace(
        track_service=object(),
        _audio_waveform_cache_worker_for_current_profile=mock.Mock(return_value=worker),
        logger=SimpleNamespace(info=mock.Mock()),
    )
    waveform_cache_worker._queue_startup_audio_waveform_cache_pass(app, progress_callback=progress)
    app.logger.info.assert_called_once_with("Queued background waveform cache validation")
    progress.assert_called_once_with(1, 1, "Queued waveform cache validation in the background.")

    worker.enqueue_all.return_value = False
    waveform_cache_worker._queue_startup_audio_waveform_cache_pass(app)
    assert app.logger.info.call_count == 1

    waveform_cache_worker._queue_startup_audio_waveform_cache_pass(
        SimpleNamespace(track_service=None)
    )
    waveform_cache_worker._queue_startup_audio_waveform_cache_pass(
        SimpleNamespace(
            track_service=object(),
            _audio_waveform_cache_worker_for_current_profile=mock.Mock(return_value=None),
        )
    )


def test_audio_waveform_cache_for_track_covers_cache_miss_hit_and_errors():
    assert (
        waveform_cache_worker._audio_waveform_cache_for_track(
            SimpleNamespace(track_service=None), 1
        )
        is None
    )
    app = SimpleNamespace(
        track_service=object(),
        _audio_waveform_cache_service=mock.Mock(return_value=None),
    )
    assert waveform_cache_worker._audio_waveform_cache_for_track(app, 1) is None

    service = SimpleNamespace(get_cached_waveform=mock.Mock(return_value=None))
    app = SimpleNamespace(
        track_service=object(),
        _audio_waveform_cache_service=mock.Mock(return_value=service),
        _queue_audio_waveform_cache_for_track=mock.Mock(),
        logger=SimpleNamespace(debug=mock.Mock()),
    )
    assert waveform_cache_worker._audio_waveform_cache_for_track(app, "6") is None
    app._queue_audio_waveform_cache_for_track.assert_called_once_with(6, delay_ms=0)

    cached = object()
    service.get_cached_waveform.return_value = cached
    assert waveform_cache_worker._audio_waveform_cache_for_track(app, 6) is cached

    service.get_cached_waveform.side_effect = RuntimeError("cache unavailable")
    assert waveform_cache_worker._audio_waveform_cache_for_track(app, 7) is None
    app.logger.debug.assert_called_once()


def test_run_startup_waveform_cache_pass_delegates():
    app = SimpleNamespace(_queue_startup_audio_waveform_cache_pass=mock.Mock())
    progress = object()

    waveform_cache_worker._run_startup_audio_waveform_cache_pass(app, progress_callback=progress)

    app._queue_startup_audio_waveform_cache_pass.assert_called_once_with(progress_callback=progress)
