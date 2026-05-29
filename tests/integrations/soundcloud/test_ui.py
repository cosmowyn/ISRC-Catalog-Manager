from __future__ import annotations

import base64
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QKeySequence, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
)

import isrc_manager.integrations.soundcloud.ui as soundcloud_ui
import isrc_manager.settings_controller as settings_controller
from isrc_manager.application_settings_dialog import ApplicationSettingsDialog
from isrc_manager.integrations.soundcloud import workflow
from isrc_manager.integrations.soundcloud.media import SoundCloudWatermarkedWavMediaPreparer
from isrc_manager.integrations.soundcloud.models import (
    SoundCloudExecutionItemStatus,
    SoundCloudExecutionStatus,
    SoundCloudPlanAction,
    SoundCloudPlanItemStatus,
    SoundCloudPreflightIssue,
    SoundCloudPreflightIssueCode,
    SoundCloudPreflightSeverity,
    SoundCloudPublishExecutionItemResult,
    SoundCloudPublishExecutionResult,
    SoundCloudPublishOptions,
    SoundCloudPublishPlanItem,
    SoundCloudPublishPlanResult,
    SoundCloudTokenKind,
    SoundCloudTrackMetadataPayload,
)
from isrc_manager.integrations.soundcloud.persistence import SoundCloudAccountRecord
from isrc_manager.integrations.soundcloud.ui import (
    SoundCloudCatalogTrackChoice,
    SoundCloudCatalogTrackSelectionDialog,
    SoundCloudExistingUploadChoice,
    SoundCloudExistingUploadSelectionDialog,
    SoundCloudMetadataComparisonDialog,
    SoundCloudMetadataComparisonRow,
    SoundCloudPublishDialog,
    SoundCloudPublishHistoryDialog,
    SoundCloudPublishRunSummary,
    SoundCloudSettingsPanel,
    SoundCloudSettingsSnapshot,
)
from isrc_manager.main_window_shell import _build_actions_and_menus
from isrc_manager.tasks.models import TaskFailure
from tests.qt_test_helpers import pump_events, require_qapplication
from tests.test_settings_controller import _base_values, _fake_app


class _FakeActions:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.raise_connect = False
        self.snapshot_value = SoundCloudSettingsSnapshot(
            connected=True,
            account_label="Connected as catalog-user",
            persistent_available=True,
            token_storage_label="Persistent OS keychain/keyring",
        )

    def snapshot(self) -> SoundCloudSettingsSnapshot:
        return self.snapshot_value

    def connect(self, *, client_id: str, redirect_uri: str) -> SoundCloudSettingsSnapshot:
        self.calls.append(f"connect:{client_id}:{redirect_uri}")
        if self.raise_connect:
            raise RuntimeError(
                "failed access_token=secret refresh_token=secret code=secret client_secret=secret"
            )
        return self.snapshot_value

    def refresh(self, *, client_id: str, redirect_uri: str) -> SoundCloudSettingsSnapshot:
        self.calls.append(f"refresh:{client_id}:{redirect_uri}")
        return self.snapshot_value

    def disconnect(self) -> SoundCloudSettingsSnapshot:
        self.calls.append("disconnect")
        return SoundCloudSettingsSnapshot(
            connected=False,
            account_label="Disconnected",
            persistent_available=True,
            token_storage_label="Persistent OS keychain/keyring available",
        )

    def save_client_secret(
        self, *, client_id: str, client_secret: str
    ) -> SoundCloudSettingsSnapshot:
        self.calls.append(f"save_secret:{client_id}:{bool(client_secret)}")
        return SoundCloudSettingsSnapshot(
            connected=False,
            account_label="Disconnected",
            persistent_available=True,
            token_storage_label="Persistent OS keychain/keyring available",
            status_message="SoundCloud client secret stored in OS keychain/keyring.",
        )


class _FakePlanner:
    def __init__(self, plan: SoundCloudPublishPlanResult) -> None:
        self.plan = plan
        self.calls: list[tuple[list[int], SoundCloudPublishOptions]] = []

    def plan_tracks(
        self, track_ids: list[int], options: SoundCloudPublishOptions | None = None
    ) -> SoundCloudPublishPlanResult:
        plan_options = options or SoundCloudPublishOptions()
        self.calls.append((list(track_ids), plan_options))
        return SoundCloudPublishPlanResult(
            track_ids=tuple(track_ids),
            items=self.plan.items,
            options=plan_options,
            quota_snapshot=self.plan.quota_snapshot,
        )


class _ShellStub(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.current_db_path = ""
        self._triggered: list[str] = []

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def _noop(*args, **kwargs):
            del args, kwargs
            self._triggered.append(name)
            return None

        return _noop

    def _create_action(
        self,
        text,
        *,
        slot=None,
        toggled_slot=None,
        checkable=False,
        checked=None,
        shortcuts=(),
        standard_key=None,
        role=None,
    ):
        action = QAction(text, self)
        if role is not None:
            action.setMenuRole(role)
        if checkable:
            action.setCheckable(True)
            if checked is not None:
                action.setChecked(bool(checked))
        if standard_key is not None:
            action.setShortcuts(QKeySequence.keyBindings(standard_key))
        elif shortcuts:
            action.setShortcuts([QKeySequence(seq) for seq in shortcuts])
        if slot is not None:
            action.triggered.connect(slot)
        if toggled_slot is not None:
            action.toggled.connect(toggled_slot)
        self.addAction(action)
        return action


class _BlobMediaHandle:
    def __init__(
        self,
        *,
        filename: str,
        data: bytes,
        mime_type: str | None = None,
    ) -> None:
        self.filename = filename
        self.suffix = Path(filename).suffix
        self.mime_type = mime_type
        self.size_bytes = len(data)
        self.source_path = None
        self.source_bytes = data

    @contextmanager
    def materialize_path(self):
        import tempfile

        suffix = self.suffix or ".bin"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
            handle.write(self.source_bytes)
            path = Path(handle.name)
        try:
            yield path
        finally:
            path.unlink(missing_ok=True)


class _BlobTrackService:
    def __init__(self) -> None:
        self.handles = {
            "audio_file": _BlobMediaHandle(
                filename="embedded.wav",
                data=b"embedded-audio",
                mime_type="audio/wav",
            ),
            "album_art": _BlobMediaHandle(
                filename="embedded.png",
                data=b"embedded-artwork",
                mime_type="image/png",
            ),
        }

    def resolve_media_source(self, _track_id: int, media_key: str):
        handle = self.handles.get(media_key)
        if handle is None:
            raise FileNotFoundError(media_key)
        return handle


class _SnapshotOnlyBlobTrackService:
    def resolve_media_source(self, _track_id: int, media_key: str):
        raise FileNotFoundError(media_key)

    def fetch_track_snapshot(self, _track_id: int, *, include_media_blobs: bool = False):
        assert include_media_blobs
        return SimpleNamespace(
            audio_file_filename="embedded-only.wav",
            audio_file_mime_type="audio/wav",
            audio_file_size_bytes=14,
            audio_file_blob_b64=base64.b64encode(b"snapshot-audio").decode("ascii"),
            album_art_filename="embedded-only.png",
            album_art_mime_type="image/png",
            album_art_size_bytes=13,
            album_art_blob_b64=base64.b64encode(b"snapshot-art").decode("ascii"),
        )


class _DictSnapshot:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values

    def to_dict(self):
        return dict(self.values)


class _FakeConversionService:
    def __init__(self) -> None:
        self.calls = []

    def is_available(self) -> bool:
        return True

    def transcode(self, *, source_path, destination_path, target_id, metadata_behavior="inherit"):
        self.calls.append((Path(source_path), Path(destination_path), target_id, metadata_behavior))
        Path(destination_path).write_bytes(Path(source_path).read_bytes() + b"-wav")


class _FakeAuthenticityService:
    def __init__(self) -> None:
        self.calls = []

    def watermark_catalog_derivative(self, *, track_id, source_path, destination_path, **kwargs):
        self.calls.append((track_id, Path(source_path), Path(destination_path), kwargs))
        Path(destination_path).write_bytes(Path(source_path).read_bytes() + b"-watermarked")
        return SimpleNamespace(manifest_id="manifest-1")


def _dialog_kwargs(**overrides):
    values = {
        "window_title": "",
        "effective_window_title": "ISRC Catalog Manager",
        "owner_company_name": "",
        "icon_path": "",
        "artist_code": "00",
        "auto_snapshot_enabled": True,
        "auto_snapshot_interval_minutes": 15,
        "isrc_prefix": "",
        "sena_number": "",
        "btw_number": "",
        "buma_relatie_nummer": "",
        "buma_ipi": "",
        "gs1_template_asset": None,
        "gs1_contracts_csv_path": "",
        "gs1_contract_entries": (),
        "gs1_active_contract_number": "",
        "gs1_target_market": "",
        "gs1_language": "",
        "gs1_brand": "",
        "gs1_subbrand": "",
        "gs1_packaging_type": "",
        "gs1_product_classification": "",
        "theme_settings": {},
        "stored_themes": {},
        "current_profile_path": "",
        "blob_icon_settings": {},
        "soundcloud_settings": SoundCloudSettingsSnapshot(
            connected=False,
            account_label="Disconnected",
            persistent_available=False,
            token_storage_label="Session-only",
        ),
        "parent": None,
    }
    values.update(overrides)
    return values


def test_soundcloud_preflight_media_provider_stages_embedded_database_media() -> None:
    provider = workflow._MediaProvider(_BlobTrackService())

    audio_handle = provider.get_audio_handle(46)
    artwork_handle, ambiguous = provider.get_effective_artwork_handle(46)

    assert audio_handle is not None
    assert artwork_handle is not None
    assert not ambiguous
    assert Path(audio_handle.source_path).read_bytes() == b"embedded-audio"
    assert Path(artwork_handle.source_path).read_bytes() == b"embedded-artwork"


def test_soundcloud_preflight_media_provider_falls_back_to_snapshot_blobs() -> None:
    provider = workflow._MediaProvider(_SnapshotOnlyBlobTrackService())

    audio_handle = provider.get_audio_handle(46)
    artwork_handle, ambiguous = provider.get_effective_artwork_handle(46)

    assert audio_handle is not None
    assert artwork_handle is not None
    assert not ambiguous
    assert audio_handle.filename == "embedded-only.wav"
    assert artwork_handle.filename == "embedded-only.png"
    assert Path(audio_handle.source_path).read_bytes() == b"snapshot-audio"
    assert Path(artwork_handle.source_path).read_bytes() == b"snapshot-art"


def test_soundcloud_workflow_low_level_adapter_helpers(monkeypatch, tmp_path) -> None:
    class _Settings:
        def value(self, key, default=None, _type=None):
            del _type
            return {
                workflow.SOUNDCLOUD_CLIENT_ID_SETTING: " client ",
                workflow.SOUNDCLOUD_PERSISTENT_TOKENS_SETTING: "false",
            }.get(key, default)

    class _Controller:
        def selected_track_ids(self):
            return ["7", 8]

    app = SimpleNamespace(
        settings=_Settings(),
        _catalog_table_controller=lambda: _Controller(),
    )

    assert workflow._setting_text(app, workflow.SOUNDCLOUD_CLIENT_ID_SETTING) == "client"
    assert not workflow._setting_bool(app, workflow.SOUNDCLOUD_PERSISTENT_TOKENS_SETTING)
    app.settings.value = lambda _key, default=None, _type=None: True
    assert workflow._setting_bool(app, "bool-setting", False) is True
    assert workflow._setting_bool(SimpleNamespace(), "missing", False) is False
    assert workflow._soundcloud_repository(SimpleNamespace()) is None
    assert workflow._soundcloud_oauth_service(SimpleNamespace()) is None
    assert workflow._selected_track_ids(app) == (7, 8)
    assert (
        workflow._selected_track_ids(SimpleNamespace(_catalog_table_controller=lambda: object()))
        == ()
    )
    assert workflow._album_track_ids(SimpleNamespace(), (1,)) == []
    assert workflow._album_track_ids(SimpleNamespace(track_service=object()), ()) == []

    class _AlbumService:
        def list_album_group_track_ids(self, track_id):
            assert track_id == 1
            return [1, 2, 3]

    assert workflow._album_track_ids(SimpleNamespace(track_service=_AlbumService()), (1,)) == [
        1,
        2,
        3,
    ]
    assert workflow.soundcloud_media_path(SimpleNamespace(source_path=tmp_path / "audio.wav"))
    assert workflow.soundcloud_media_path(SimpleNamespace(source_path=None)) is None

    client_app = SimpleNamespace()
    first_client = workflow._soundcloud_client(client_app)
    assert workflow._soundcloud_client(client_app) is first_client

    store_app = SimpleNamespace()
    first_store = workflow._soundcloud_token_store(store_app)
    assert workflow._soundcloud_token_store(store_app) is first_store

    conn = sqlite3.connect(":memory:")
    try:
        service_app = SimpleNamespace(conn=conn)
        monkeypatch.setattr(workflow, "_soundcloud_client", lambda _app: object())
        monkeypatch.setattr(workflow, "_soundcloud_token_store", lambda _app: object())
        assert workflow._soundcloud_repository(service_app) is not None
        first_service = workflow._soundcloud_oauth_service(service_app)
        assert workflow._soundcloud_oauth_service(service_app) is first_service
    finally:
        conn.close()

    monkeypatch.setattr(workflow, "_soundcloud_repository", lambda _app: None)
    with pytest.raises(RuntimeError):
        workflow.build_soundcloud_publish_planner(SimpleNamespace(track_service=None))


def test_soundcloud_workflow_settings_snapshot_and_secret_helpers(monkeypatch) -> None:
    account = SoundCloudAccountRecord(
        id=1,
        account_key="soundcloud:user:1",
        token_store_key="soundcloud:user:1",
        token_kind=SoundCloudTokenKind.SESSION,
        connection_status="connected",
        username="Artist",
    )

    class _Repo:
        def __init__(self, active=account) -> None:
            self.active = active
            self.disconnected: list[tuple[int, str | None]] = []

        def active_account(self):
            return self.active

        def mark_disconnected(self, account_id, *, error=None):
            self.disconnected.append((account_id, error))

    class _Store:
        persistent_available = False
        availability = SimpleNamespace(reason="Session-only fallback is active.")

        def __init__(self, bundle=object(), secret="stored-secret") -> None:
            self.bundle = bundle
            self.secret = secret

        def load_bundle(self, _key):
            return self.bundle

        def load_client_secret(self, _client_id):
            return self.secret

    repo = _Repo()
    store = _Store()
    app = SimpleNamespace(conn=SimpleNamespace(commit=mock.Mock()))
    monkeypatch.setattr(workflow, "_soundcloud_repository", lambda _app: repo)
    monkeypatch.setattr(workflow, "_soundcloud_token_store", lambda _app: store)

    snapshot = workflow.soundcloud_settings_snapshot(app)
    assert snapshot.connected
    assert "Connected as Artist" == snapshot.account_label
    assert workflow._client_secret_from_store(app, "client") == "stored-secret"

    store.bundle = None
    reconnect_snapshot = workflow.soundcloud_settings_snapshot(app)
    assert not reconnect_snapshot.connected
    assert "Reconnect required" in reconnect_snapshot.account_label
    workflow._mark_soundcloud_credentials_unavailable(app, repo, account)
    assert repo.disconnected[-1][0] == account.id
    app.conn.commit.assert_called()

    store.secret = ""
    app.soundcloud_client_secret_provider = lambda _client_id: "provider-secret"
    assert workflow._client_secret_from_store(app, "client") == "provider-secret"
    delattr(app, "soundcloud_client_secret_provider")
    assert workflow._client_secret_from_store(app, "client") is None

    repo.active = None
    store.persistent_available = True
    snapshot = workflow.soundcloud_settings_snapshot(app)
    assert snapshot.token_storage_label == "Persistent OS keychain/keyring available"


def test_soundcloud_workflow_planner_providers_and_media_edges(tmp_path) -> None:
    media_file = tmp_path / "managed.wav"
    media_file.write_bytes(b"managed")

    class _TrackService:
        def __init__(self) -> None:
            self.snapshots = {
                1: _DictSnapshot(
                    {
                        "album_title": "Album",
                        "release_date": "2026-05-28",
                        "track_title": "Track",
                    }
                ),
                2: _DictSnapshot({"track_title": "No Release"}),
            }

        def fetch_track_snapshot(self, track_id, *, include_media_blobs=False):
            assert not include_media_blobs
            return self.snapshots.get(track_id)

    track_service = _TrackService()
    assert workflow._TrackSnapshotProvider(track_service).get_track_snapshot(1)["track_title"] == (
        "Track"
    )
    assert workflow._TrackSnapshotProvider(track_service).get_track_snapshot(99) is None
    release_provider = workflow._ReleaseSummaryProvider(track_service)
    assert release_provider.get_release_summary(1)["release_title"] == "Album"
    assert release_provider.get_release_summary(2) is None

    class _ExistingPathService:
        def resolve_media_source(self, _track_id, _media_key):
            return SimpleNamespace(
                filename="managed.wav",
                mime_type="audio/wav",
                size_bytes=7,
                source_path=media_file,
            )

    provider = workflow._MediaProvider(_ExistingPathService())
    assert provider.get_audio_handle(1).source_path == media_file

    class _BytesService:
        def resolve_media_source(self, _track_id, _media_key):
            return SimpleNamespace(
                filename="",
                mime_type="audio/wav",
                size_bytes=0,
                source_path=None,
            )

        def fetch_media_bytes(self, _track_id, media_key):
            return f"{media_key}-bytes".encode(), "audio/wav"

    bytes_provider = workflow._MediaProvider(_BytesService())
    staged = bytes_provider.get_audio_handle(4)
    assert staged.filename.startswith("track-4-audio_file")
    assert Path(staged.source_path).read_bytes() == b"audio_file-bytes"

    class _InvalidSnapshotService:
        def fetch_track_snapshot(self, _track_id, *, include_media_blobs=False):
            assert include_media_blobs
            return SimpleNamespace(audio_file_blob_b64="!!!!")

    assert (
        workflow._MediaProvider(_InvalidSnapshotService())._snapshot_blob_handle(1, "audio_file")
        is None
    )


def test_soundcloud_workflow_publication_quota_history_and_safe_publish(monkeypatch) -> None:
    account = SoundCloudAccountRecord(
        id=3,
        account_key="soundcloud:user:3",
        token_store_key="soundcloud:user:3",
        token_kind=SoundCloudTokenKind.SESSION,
        connection_status="connected",
        username="Artist",
    )

    class _Repo:
        conn = SimpleNamespace(commit=mock.Mock())

        def __init__(self) -> None:
            self.recovered = False

        def active_account(self):
            return account

        def find_publication(self, track_id, *, account_id=None):
            return {"track_id": track_id, "account_id": account_id, "remote_urn": "urn"}

        def mark_stale_in_progress_runs_failed(self):
            self.recovered = True
            return 1

        def list_publish_runs(self, *, limit):
            assert limit == 100
            return [
                {
                    "id": 9,
                    "status": "failed",
                    "created_at": "now",
                    "items_total": 1,
                    "items_succeeded": 0,
                    "items_failed": 1,
                    "items_skipped": 0,
                }
            ]

    repo = _Repo()
    assert workflow._PublicationLookup(None).find_publication(1) is None
    assert workflow._PublicationLookup(repo).find_publication(1)["account_id"] == 3

    class _Store:
        def load_bundle(self, _key):
            return object()

    class _OAuth:
        def token_for_account(self, account_id):
            assert account_id == 3
            return "access-token"

    class _Client:
        def get_quota_snapshot(self, token):
            assert token == "access-token"
            return SimpleNamespace(daily_remaining_uploads=5)

    app = SimpleNamespace(_soundcloud_token_store=_Store())
    monkeypatch.setattr(workflow, "_soundcloud_oauth_service", lambda _app: _OAuth())
    monkeypatch.setattr(workflow, "_soundcloud_client", lambda _app: _Client())
    quota = workflow._AccountState(app, repo).get_quota_snapshot()
    assert quota.daily_remaining_uploads == 5

    monkeypatch.setattr(workflow, "_soundcloud_repository", lambda _app: repo)
    history = workflow._publish_history(SimpleNamespace())
    assert history[0].run_id == 9
    assert repo.recovered
    repo.conn.commit.assert_called()

    events: list[dict[str, object]] = []
    dialog = SimpleNamespace(apply_execution_error=lambda exc: events.append({"dialog": exc}))
    holder = {"dialog": dialog}
    app = SimpleNamespace(
        _log_trace=lambda event, **fields: events.append({"event": event, **fields})
    )
    result = workflow._safe_publish(
        lambda _plan: (_ for _ in ()).throw(RuntimeError("access_token=secret")),
        _plan(),
        holder,
        app,
    )
    assert result is None
    rendered = str(events)
    assert "secret" not in rendered
    assert "access_token=***" in rendered


def test_soundcloud_workflow_error_and_fallback_helpers(monkeypatch) -> None:
    class _Store:
        availability = SimpleNamespace(reason="unavailable")
        persistent_available = False

        def load_bundle(self, _key):
            raise RuntimeError("store offline")

    account = SoundCloudAccountRecord(
        id=4,
        account_key="soundcloud:user:4",
        token_store_key="soundcloud:user:4",
        token_kind=SoundCloudTokenKind.SESSION,
        connection_status="connected",
        username="Artist",
    )
    app = SimpleNamespace(_soundcloud_token_store=_Store())
    assert not workflow._soundcloud_credentials_available(app, account)

    logger_events: list[tuple[str, dict[str, object]]] = []

    class _Logger:
        def error(self, message, *, extra):
            logger_events.append((message, extra))

    real_get_logger = workflow.logging.getLogger

    def _fake_get_logger(name=None):
        if name == "ISRCManager.trace":
            return _Logger()
        return real_get_logger(name)

    monkeypatch.setattr(workflow.logging, "getLogger", _fake_get_logger)
    workflow._record_soundcloud_publish_failure(
        SimpleNamespace(),
        RuntimeError("upload failed access_token=secret"),
    )
    details_text = str(logger_events[0][1]["details"])
    assert "access_token=***" in details_text
    assert "secret" not in details_text

    calls: list[tuple[bool, bool]] = []

    def _opener(**kwargs):
        if kwargs:
            calls.append((kwargs["prefer_trace"], kwargs["scroll_to_latest"]))
            raise TypeError("legacy")
        return "opened"

    legacy_app = SimpleNamespace(open_application_log_dialog=lambda: "opened")
    legacy_app.open_application_log_dialog = _opener
    assert workflow._open_soundcloud_latest_error_log(legacy_app) == "opened"
    assert calls == [(True, True)]
    assert workflow._open_soundcloud_latest_error_log(SimpleNamespace()) is None

    class _RepoRaises:
        def active_account(self):
            raise RuntimeError("db unavailable")

    monkeypatch.setattr(workflow, "_soundcloud_repository", lambda _app: _RepoRaises())
    monkeypatch.setattr(workflow, "_soundcloud_token_store", lambda _app: _Store())
    snapshot = workflow.soundcloud_settings_snapshot(SimpleNamespace())
    assert snapshot.account_label == "Disconnected"


def test_soundcloud_workflow_account_token_and_history_error_edges(monkeypatch) -> None:
    connected = SoundCloudAccountRecord(
        id=41,
        account_key="soundcloud:user:41",
        token_store_key="soundcloud:user:41",
        token_kind=SoundCloudTokenKind.PERSISTENT,
        connection_status="connected",
        username="Artist",
    )
    disconnected = SoundCloudAccountRecord(
        id=42,
        account_key="soundcloud:user:42",
        token_store_key="soundcloud:user:42",
        token_kind=SoundCloudTokenKind.PERSISTENT,
        connection_status="disconnected",
        username="Past Artist",
    )

    class _StoreRaises:
        availability = SimpleNamespace(reason="safe backend unavailable")
        persistent_available = False

        def load_bundle(self, _key):
            raise RuntimeError("keychain unavailable")

    class _Repo:
        conn = SimpleNamespace(commit=mock.Mock())

        def __init__(self, account):
            self.account = account
            self.disconnected: list[tuple[int, str | None]] = []

        def active_account(self):
            return self.account

        def mark_disconnected(self, account_id, *, error=None):
            self.disconnected.append((account_id, error))

    repo = _Repo(disconnected)
    monkeypatch.setattr(workflow, "_soundcloud_repository", lambda _app: repo)
    monkeypatch.setattr(workflow, "_soundcloud_token_store", lambda _app: _StoreRaises())

    assert workflow._soundcloud_credentials_available(SimpleNamespace(), None) is False
    assert workflow._soundcloud_credentials_available(SimpleNamespace(), disconnected) is False
    assert workflow._soundcloud_credentials_available(SimpleNamespace(), connected) is False

    snapshot = workflow.soundcloud_settings_snapshot(SimpleNamespace())
    assert snapshot.account_label == "Disconnected: Past Artist"
    assert snapshot.token_storage_label == "Persistent OS keychain/keyring"
    assert not snapshot.connected

    app_without_conn = SimpleNamespace()
    workflow._mark_soundcloud_credentials_unavailable(app_without_conn, repo, connected)
    assert repo.disconnected == [(connected.id, workflow.SOUNDCLOUD_RECONNECT_REQUIRED_MESSAGE)]
    repo.conn.commit.assert_not_called()

    monkeypatch.setattr(workflow, "_soundcloud_repository", lambda _app: None)
    with pytest.raises(RuntimeError, match="Open a profile"):
        workflow._active_soundcloud_account_token(SimpleNamespace())

    monkeypatch.setattr(workflow, "_soundcloud_repository", lambda _app: _Repo(None))
    with pytest.raises(RuntimeError, match="not connected"):
        workflow._active_soundcloud_account_token(SimpleNamespace())

    class _StoreOk:
        def load_bundle(self, _key):
            return object()

        def load_client_secret(self, _client_id):
            return ""

    monkeypatch.setattr(workflow, "_soundcloud_repository", lambda _app: _Repo(connected))
    monkeypatch.setattr(workflow, "_soundcloud_token_store", lambda _app: _StoreOk())
    monkeypatch.setattr(workflow, "_soundcloud_oauth_service", lambda _app: None)
    with pytest.raises(RuntimeError, match="OAuth service is unavailable"):
        workflow._active_soundcloud_account_token(SimpleNamespace())

    class _HistoryRepoRaises:
        def mark_stale_in_progress_runs_failed(self):
            raise RuntimeError("history unavailable")

    monkeypatch.setattr(workflow, "_soundcloud_repository", lambda _app: _HistoryRepoRaises())
    assert workflow._publish_history(SimpleNamespace()) == []

    with pytest.raises(RuntimeError, match="Paste a SoundCloud"):
        workflow.link_existing_soundcloud_upload(SimpleNamespace(), 1, " ")


def test_soundcloud_workflow_connection_action_error_branches(monkeypatch) -> None:
    class _Window:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def isMaximized(self):
            return True

        def showMinimized(self):
            self.calls.append("minimize")

        def showMaximized(self):
            self.calls.append("maximized")

        def raise_(self):
            self.calls.append("raise")

        def activateWindow(self):
            self.calls.append("activate")

    window = _Window()
    actions = workflow.SoundCloudAppConnectionActions(window)
    with pytest.raises(RuntimeError):
        actions.connect(client_id="", redirect_uri="")
    state = actions._minimize_for_oauth()
    actions._restore_after_oauth(state)
    assert window.calls == ["minimize", "maximized", "raise", "activate"]

    no_secret_actions = workflow.SoundCloudAppConnectionActions(SimpleNamespace())
    with pytest.raises(RuntimeError):
        no_secret_actions._client_secret("client")

    class _Repo:
        def active_account(self):
            return None

    monkeypatch.setattr(workflow, "_soundcloud_repository", lambda _app: _Repo())
    monkeypatch.setattr(
        workflow,
        "soundcloud_settings_snapshot",
        lambda _app: SoundCloudSettingsSnapshot(connected=False),
    )
    with pytest.raises(RuntimeError):
        no_secret_actions.refresh(client_id="client", redirect_uri="ignored")
    disconnected = no_secret_actions.disconnect()
    assert disconnected.status_message == "SoundCloud account disconnected."


def test_soundcloud_workflow_provider_failure_edges(monkeypatch) -> None:
    assert (
        workflow._ReleaseSummaryProvider(
            SimpleNamespace(fetch_track_snapshot=lambda *_args, **_kwargs: None)
        ).get_release_summary(1)
        is None
    )

    class _SnapshotRaises:
        def fetch_track_snapshot(self, *_args, **_kwargs):
            raise RuntimeError("snapshot failed")

    assert workflow._MediaProvider(_SnapshotRaises())._snapshot_blob_handle(1, "audio_file") is None

    class _SnapshotNone:
        def fetch_track_snapshot(self, *_args, **_kwargs):
            return None

    assert workflow._MediaProvider(_SnapshotNone())._snapshot_blob_handle(1, "audio_file") is None

    class _BadSizeSnapshot:
        def fetch_track_snapshot(self, *_args, **_kwargs):
            return SimpleNamespace(
                audio_file_blob_b64=base64.b64encode(b"audio").decode("ascii"),
                audio_file_size_bytes=object(),
                audio_file_filename="audio.wav",
            )

    provider = workflow._MediaProvider(_BadSizeSnapshot())
    assert provider._snapshot_blob_handle(1, "audio_file").size_bytes == len(b"audio")

    class _PublicationRepo:
        def active_account(self):
            raise RuntimeError("no active account")

        def find_publication(self, track_id, *, account_id=None):
            return {"track_id": track_id, "account_id": account_id}

    assert workflow._PublicationLookup(_PublicationRepo()).find_publication(5)["account_id"] is None

    class _AccountRepo:
        def __init__(self, mode):
            self.mode = mode

        def active_account(self):
            if self.mode == "raise":
                raise RuntimeError("boom")
            return None

    assert workflow._AccountState(SimpleNamespace(), None).is_connected() is False
    assert workflow._AccountState(SimpleNamespace(), _AccountRepo("raise")).is_connected() is False
    assert (
        workflow._AccountState(SimpleNamespace(), _AccountRepo("none")).get_quota_snapshot() is None
    )

    account = SoundCloudAccountRecord(
        id=6,
        account_key="soundcloud:user:6",
        token_store_key="soundcloud:user:6",
        token_kind=SoundCloudTokenKind.SESSION,
        connection_status="connected",
    )

    class _ConnectedRepo:
        def active_account(self):
            return account

    monkeypatch.setattr(workflow, "_soundcloud_oauth_service", lambda _app: None)
    assert workflow._AccountState(SimpleNamespace(), _ConnectedRepo()).get_quota_snapshot() is None
    monkeypatch.setattr(
        workflow,
        "_soundcloud_oauth_service",
        lambda _app: SimpleNamespace(token_for_account=lambda _id: "token"),
    )
    monkeypatch.setattr(
        workflow,
        "_soundcloud_client",
        lambda _app: SimpleNamespace(
            get_quota_snapshot=lambda _token: (_ for _ in ()).throw(RuntimeError("offline"))
        ),
    )
    assert workflow._AccountState(SimpleNamespace(), _ConnectedRepo()).get_quota_snapshot() is None


def test_soundcloud_track_snapshot_provider_enriches_linked_work_metadata() -> None:
    class _Snapshot:
        def __init__(self, values):
            self.values = values

        def to_dict(self):
            return dict(self.values)

    class _TrackService:
        def __init__(self, values):
            self.values = values

        def fetch_track_snapshot(self, track_id, *, include_media_blobs=False):
            assert track_id == 8
            assert include_media_blobs is False
            return _Snapshot(self.values)

    class _WorkService:
        def __init__(self):
            self.list_calls = 0

        def list_works_for_track(self, track_id):
            self.list_calls += 1
            assert track_id == 8
            return [SimpleNamespace(id=44)]

        def fetch_work_detail(self, work_id):
            assert work_id == 44
            return SimpleNamespace(
                work=SimpleNamespace(iswc="T-123.456.789-0"),
                contributors=[
                    SimpleNamespace(role="composer", display_name="Composer One"),
                    SimpleNamespace(role="songwriter", display_name="Composer One"),
                    SimpleNamespace(role="lyricist", display_name="Lyricist Two"),
                    SimpleNamespace(role="publisher", display_name="Publisher One"),
                    SimpleNamespace(role="subpublisher", display_name="Publisher Two"),
                ],
            )

    work_service = _WorkService()
    provider = workflow._TrackSnapshotProvider(
        _TrackService(
            {
                "track_id": 8,
                "track_title": "Enriched",
                "composer": "",
                "publisher": "",
                "iswc": "",
            }
        ),
        work_service=work_service,
        owner_company_name="Owner Company",
    )

    values = provider.get_track_snapshot(8)

    assert values["composer"] == "Composer One, Lyricist Two"
    assert values["publisher"] == "Publisher One, Publisher Two"
    assert values["iswc"] == "T-123.456.789-0"
    assert values["soundcloud_p_line"].endswith(": Owner Company")
    assert work_service.list_calls == 1


def test_soundcloud_track_snapshot_provider_uses_owner_company_as_publisher_fallback() -> None:
    class _Snapshot:
        def to_dict(self):
            return {
                "track_id": 12,
                "track_title": "Owner Fallback",
                "publisher": "",
            }

    class _TrackService:
        def fetch_track_snapshot(self, track_id, *, include_media_blobs=False):
            assert track_id == 12
            assert include_media_blobs is False
            return _Snapshot()

    provider = workflow._TrackSnapshotProvider(
        _TrackService(),
        owner_company_name="Cosmowyn Records",
    )

    values = provider.get_track_snapshot(12)

    assert values["publisher"] == "Cosmowyn Records"
    assert values["soundcloud_p_line"].endswith(": Cosmowyn Records")


def test_soundcloud_track_snapshot_provider_linked_work_edge_cases() -> None:
    class _Snapshot:
        def __init__(self, values):
            self.values = values

        def to_dict(self):
            return dict(self.values)

    class _TrackService:
        def __init__(self, values):
            self.values = values

        def fetch_track_snapshot(self, _track_id, *, include_media_blobs=False):
            assert include_media_blobs is False
            return _Snapshot(self.values)

    no_list_values = workflow._TrackSnapshotProvider(
        _TrackService(
            {
                "track_id": 21,
                "work_id": "not-a-work-id",
                "composer": "Existing Composer",
                "publisher": "Existing Publisher",
                "iswc": "",
            }
        ),
        work_service=object(),
    ).get_track_snapshot(21)
    assert no_list_values["composer"] == "Existing Composer"
    assert no_list_values["publisher"] == "Existing Publisher"

    class _ListRaises:
        def list_works_for_track(self, _track_id):
            raise RuntimeError("work link lookup failed")

        def fetch_work_detail(self, _work_id):
            raise AssertionError("fetch should not run when work list fails")

    list_failure_values = workflow._TrackSnapshotProvider(
        _TrackService({"track_id": 22, "composer": "", "publisher": ""}),
        work_service=_ListRaises(),
    ).get_track_snapshot(22)
    assert list_failure_values["composer"] == ""
    assert list_failure_values["publisher"] == ""

    class _DetailEdges:
        def list_works_for_track(self, _track_id):
            return [
                SimpleNamespace(id=None),
                SimpleNamespace(id=7),
                SimpleNamespace(id=8),
                SimpleNamespace(id=9),
            ]

        def fetch_work_detail(self, work_id):
            if work_id == 7:
                raise RuntimeError("work detail unavailable")
            if work_id == 8:
                return None
            return SimpleNamespace(
                work=SimpleNamespace(iswc="T-999.888.777-6"),
                contributors=[
                    SimpleNamespace(role="Composer", display_name="Edge Composer"),
                    SimpleNamespace(role="publisher", display_name="Edge Publisher"),
                    SimpleNamespace(role="performer", display_name="Ignored Performer"),
                ],
            )

    enriched_values = workflow._TrackSnapshotProvider(
        _TrackService({"track_id": 23, "composer": "", "publisher": "", "iswc": ""}),
        work_service=_DetailEdges(),
    ).get_track_snapshot(23)
    assert enriched_values["composer"] == "Edge Composer"
    assert enriched_values["publisher"] == "Edge Publisher"
    assert enriched_values["iswc"] == "T-999.888.777-6"


def test_soundcloud_release_summary_uses_publisher_as_label() -> None:
    class _Snapshot:
        def to_dict(self):
            return {
                "album_title": "",
                "release_date": "",
                "publisher": "Publisher Label",
            }

    class _TrackService:
        def fetch_track_snapshot(self, track_id, *, include_media_blobs=False):
            assert track_id == 9
            assert include_media_blobs is False
            return _Snapshot()

    summary = workflow._ReleaseSummaryProvider(_TrackService()).get_release_summary(9)

    assert summary["label_name"] == "Publisher Label"
    assert summary["label_names"] == ["Publisher Label"]


def test_link_existing_soundcloud_upload_persists_publication(monkeypatch) -> None:
    account = SoundCloudAccountRecord(
        id=22,
        account_key="soundcloud:user:22",
        token_store_key="soundcloud:user:22",
        token_kind=SoundCloudTokenKind.SESSION,
        connection_status="connected",
        username="Artist",
    )

    class _Repo:
        def __init__(self):
            self.linked: list[dict[str, object]] = []

        def active_account(self):
            return account

        def link_publication(self, **kwargs):
            self.linked.append(kwargs)
            return 77

    class _Store:
        def load_bundle(self, _key):
            return object()

        def load_client_secret(self, _client_id):
            return "client-secret"

    class _OAuth:
        def token_for_account(self, account_id, *, client_id=None, client_secret=None):
            assert account_id == 22
            assert client_id == "client-id"
            assert client_secret == "client-secret"
            return "access-token"

    class _Client:
        def resolve_track_url(self, *, access_token, track_url):
            assert access_token == "access-token"
            assert track_url == "https://soundcloud.com/artist/existing"
            return SimpleNamespace(
                remote_urn="soundcloud:tracks:987",
                remote_numeric_id=987,
                remote_url="https://soundcloud.com/artist/existing",
            )

        def fetch_track_metadata(self, *, access_token, remote_track_ref):
            assert access_token == "access-token"
            assert remote_track_ref == "soundcloud:tracks:654"
            return SimpleNamespace(
                remote_urn="soundcloud:tracks:654",
                remote_numeric_id=None,
                remote_url="https://soundcloud.com/artist/existing-654",
            )

    repo = _Repo()
    app = SimpleNamespace(
        _soundcloud_token_store=_Store(),
        conn=SimpleNamespace(commit=mock.Mock()),
    )
    app.settings = SimpleNamespace(
        value=lambda key, default=None, _type=None: {
            workflow.SOUNDCLOUD_CLIENT_ID_SETTING: "client-id"
        }.get(key, default)
    )
    monkeypatch.setattr(workflow, "_soundcloud_repository", lambda _app: repo)
    monkeypatch.setattr(workflow, "_soundcloud_oauth_service", lambda _app: _OAuth())
    monkeypatch.setattr(workflow, "_soundcloud_client", lambda _app: _Client())
    monkeypatch.setattr(
        workflow, "_soundcloud_token_store", lambda _app: app._soundcloud_token_store
    )

    remote = workflow.link_existing_soundcloud_upload(
        app, 5, "https://soundcloud.com/artist/existing"
    )
    urn_remote = workflow.link_existing_soundcloud_upload(app, 6, "soundcloud:tracks:654")

    assert remote.remote_urn == "soundcloud:tracks:987"
    assert urn_remote.remote_numeric_id is None
    assert repo.linked[0]["track_id"] == 5
    assert repo.linked[0]["remote_numeric_id"] == 987
    assert repo.linked[1]["track_id"] == 6
    assert repo.linked[1]["remote_numeric_id"] == 654
    assert app.conn.commit.call_count == 2


def test_soundcloud_catalog_choices_and_planner_success(monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript("""
            CREATE TABLE Tracks(
                id INTEGER PRIMARY KEY,
                track_title TEXT,
                album_id INTEGER,
                track_number INTEGER,
                isrc TEXT,
                track_length_sec INTEGER
            );
            CREATE TABLE Albums(id INTEGER PRIMARY KEY, title TEXT);
            INSERT INTO Albums(id, title) VALUES (1, 'Album');
            INSERT INTO Tracks(id, track_title, album_id, track_number, isrc, track_length_sec)
            VALUES (2, 'Track', 1, 1, 'NL-ABC', 123);
            """)
        import isrc_manager.services.track_artist_sql as track_artist_sql

        monkeypatch.setattr(
            track_artist_sql,
            "track_main_artist_join_sql",
            lambda *_args, **_kwargs: ("", "'Artist'"),
        )
        choices = workflow._catalog_track_choices(SimpleNamespace(conn=conn))
    finally:
        conn.close()

    assert choices == [
        SoundCloudCatalogTrackChoice(
            track_id=2,
            title="Track",
            album="Album",
            artist="Artist",
            isrc="NL-ABC",
            duration_seconds=123,
        )
    ]
    assert workflow._catalog_track_choices(SimpleNamespace()) == []
    assert (
        workflow._catalog_track_choices(
            SimpleNamespace(conn=SimpleNamespace(execute=mock.Mock(side_effect=RuntimeError)))
        )
        == []
    )

    planner = workflow.build_soundcloud_publish_planner(
        SimpleNamespace(track_service=SimpleNamespace(), conn=None)
    )
    assert planner is not None
    assert (
        workflow._album_track_ids(
            SimpleNamespace(
                track_service=SimpleNamespace(
                    list_album_group_track_ids=lambda _track_id: (_ for _ in ()).throw(
                        RuntimeError("failed")
                    )
                )
            ),
            (1,),
        )
        == []
    )


def test_soundcloud_connection_actions_refresh_disconnect_and_secret_save(monkeypatch) -> None:
    account = SoundCloudAccountRecord(
        id=8,
        account_key="soundcloud:user:8",
        token_store_key="soundcloud:user:8",
        token_kind=SoundCloudTokenKind.SESSION,
        connection_status="connected",
        username="Artist",
    )
    calls: list[tuple[str, object]] = []

    class _Repo:
        def active_account(self):
            return account

    class _Service:
        def refresh_account(self, account_id, *, client_id, client_secret):
            calls.append(("refresh", (account_id, client_id, client_secret)))

        def disconnect_account(self, account_id):
            calls.append(("disconnect", account_id))

    class _Store:
        def __init__(self, kind):
            self.kind = kind

        def save_client_secret(self, client_id, client_secret):
            calls.append(("save_secret", (client_id, bool(client_secret))))
            return self.kind

        def load_client_secret(self, _client_id):
            return "stored-secret"

        def load_bundle(self, _key):
            return object()

    app = SimpleNamespace(conn=SimpleNamespace(commit=mock.Mock()))
    monkeypatch.setattr(workflow, "_soundcloud_repository", lambda _app: _Repo())
    monkeypatch.setattr(workflow, "_soundcloud_oauth_service", lambda _app: _Service())
    monkeypatch.setattr(
        workflow, "_soundcloud_token_store", lambda _app: _Store(SoundCloudTokenKind.PERSISTENT)
    )
    monkeypatch.setattr(
        workflow,
        "soundcloud_settings_snapshot",
        lambda _app: SoundCloudSettingsSnapshot(connected=True),
    )
    actions = workflow.SoundCloudAppConnectionActions(app)

    refreshed = actions.refresh(client_id=" client ", redirect_uri="ignored")
    disconnected = actions.disconnect()
    saved = actions.save_client_secret(client_id=" client ", client_secret="secret")

    assert refreshed.status_message == "SoundCloud connection refreshed."
    assert disconnected.status_message == "SoundCloud account disconnected."
    assert "OS keychain" in saved.status_message
    assert calls[:2] == [
        ("refresh", (8, "client", "stored-secret")),
        ("disconnect", 8),
    ]
    app.conn.commit.assert_called()

    monkeypatch.setattr(
        workflow, "_soundcloud_token_store", lambda _app: _Store(SoundCloudTokenKind.SESSION)
    )
    session_saved = actions.save_client_secret(client_id="client", client_secret="secret")
    assert "session only" in session_saved.status_message
    with pytest.raises(RuntimeError):
        actions.save_client_secret(client_id="", client_secret="")


def test_open_soundcloud_publish_dialog_uses_bundle_background_submit(monkeypatch) -> None:
    account = SoundCloudAccountRecord(
        id=11,
        account_key="soundcloud:user:11",
        token_store_key="soundcloud:user:11",
        token_kind=SoundCloudTokenKind.SESSION,
        connection_status="connected",
        username="Artist",
    )
    events: list[tuple[str, object]] = []

    class _Repo:
        def active_account(self):
            return account

    class _Store:
        def load_bundle(self, _key):
            return object()

        def load_client_secret(self, _client_id):
            return "client-secret"

    class _Dialog:
        def __init__(self, **kwargs):
            self.publish_runner = kwargs["publish_runner"]
            self.settings_opener = kwargs["settings_opener"]
            self.album_track_resolver = kwargs["album_track_resolver"]
            self.catalog_track_provider = kwargs["catalog_track_provider"]
            self.history_provider = kwargs["history_provider"]
            self.error_log_opener = kwargs["error_log_opener"]
            events.append(("dialog_track_ids", kwargs["track_ids"]))

        def exec(self):
            self.settings_opener()
            self.album_track_resolver((1,))
            self.catalog_track_provider()
            self.history_provider()
            self.error_log_opener()
            return self.publish_runner(_plan())

        def apply_execution_result(self, result):
            events.append(("success", result.status))

        def apply_execution_error(self, failure):
            events.append(("error", str(failure)))

    class _Executor:
        def __init__(self, **kwargs):
            events.append(("executor_media", type(kwargs["media_preparer"]).__name__))

        def execute_plan(self, plan, *, account_id, client_id, client_secret, ctx):
            events.append(
                ("execute", (tuple(plan.track_ids), account_id, client_id, client_secret, ctx))
            )
            return SoundCloudPublishExecutionResult(
                run_id=1,
                status=SoundCloudExecutionStatus.COMPLETED,
                items_total=1,
                items_succeeded=1,
                items_failed=0,
                items_skipped=0,
                item_results=(),
            )

    def _submit_background_bundle_task(**kwargs):
        events.append(("bundle_title", kwargs["title"]))
        result = kwargs["task_fn"](
            SimpleNamespace(
                conn=SimpleNamespace(),
                track_service=object(),
                audio_authenticity_service=object(),
            ),
            "ctx",
        )
        kwargs["on_success"](result)
        return result

    app = SimpleNamespace(
        _soundcloud_token_store=_Store(),
        current_db_path="/tmp/profile.db",
        track_service=SimpleNamespace(list_album_group_track_ids=lambda _track_id: [1, 2]),
        conn=SimpleNamespace(commit=mock.Mock()),
        _submit_background_bundle_task=_submit_background_bundle_task,
        open_application_log_dialog=lambda **_kwargs: events.append(("log", True)),
    )
    app.settings = SimpleNamespace(
        value=lambda key, default=None, _type=None: {
            workflow.SOUNDCLOUD_CLIENT_ID_SETTING: "client-id",
            workflow.SOUNDCLOUD_REDIRECT_URI_SETTING: "isrc://callback",
        }.get(key, default)
    )

    monkeypatch.setattr(workflow, "SoundCloudPublishDialog", _Dialog)
    monkeypatch.setattr(workflow, "SoundCloudPublishExecutor", _Executor)
    monkeypatch.setattr(workflow, "build_soundcloud_publish_planner", lambda _app: object())
    monkeypatch.setattr(workflow, "_soundcloud_repository", lambda _app: _Repo())
    monkeypatch.setattr(workflow, "_soundcloud_settings_dialog", lambda _app: None, raising=False)
    monkeypatch.setattr(
        workflow, "open_soundcloud_settings_dialog", lambda _app: events.append(("settings", True))
    )
    monkeypatch.setattr(
        workflow, "_catalog_track_choices", lambda _app: [SoundCloudCatalogTrackChoice(1, "Track")]
    )
    monkeypatch.setattr(workflow, "_publish_history", lambda _app: [])
    monkeypatch.setattr(workflow, "_soundcloud_client", lambda _app: object())
    monkeypatch.setattr(
        workflow, "_soundcloud_token_store", lambda _app: app._soundcloud_token_store
    )

    result = workflow.open_soundcloud_publish_dialog(app, track_ids=[1])

    assert result.status == SoundCloudExecutionStatus.COMPLETED
    assert ("dialog_track_ids", (1,)) in events
    assert ("bundle_title", "Publish to SoundCloud") in events
    assert any(event[0] == "execute" and event[1][2] == "client-id" for event in events)
    assert ("success", SoundCloudExecutionStatus.COMPLETED) in events
    assert ("settings", True) in events
    assert ("log", True) in events


def test_open_soundcloud_publish_dialog_fallback_submit_and_direct_paths(monkeypatch) -> None:
    account = SoundCloudAccountRecord(
        id=12,
        account_key="soundcloud:user:12",
        token_store_key="soundcloud:user:12",
        token_kind=SoundCloudTokenKind.SESSION,
        connection_status="connected",
        username="Artist",
    )
    events: list[str] = []

    class _Repo:
        def active_account(self):
            return account

    class _Store:
        def load_bundle(self, _key):
            return object()

        def load_client_secret(self, _client_id):
            return "client-secret"

    class _OAuth:
        pass

    class _Dialog:
        def __init__(self, **kwargs):
            self.publish_runner = kwargs["publish_runner"]

        def exec(self):
            return self.publish_runner(_plan())

        def apply_execution_result(self, result):
            events.append(f"success:{result.status.value}")

        def apply_execution_error(self, failure):
            events.append(f"error:{failure}")

    class _Executor:
        def __init__(self, **_kwargs):
            pass

        def execute_plan(self, *_args, **_kwargs):
            return SoundCloudPublishExecutionResult(
                run_id=2,
                status=SoundCloudExecutionStatus.COMPLETED,
                items_total=1,
                items_succeeded=1,
                items_failed=0,
                items_skipped=0,
                item_results=(),
            )

    def _base_app():
        app = SimpleNamespace(
            _soundcloud_token_store=_Store(),
            current_db_path="",
            conn=SimpleNamespace(),
            track_service=object(),
            audio_authenticity_service=object(),
        )
        app.settings = SimpleNamespace(
            value=lambda key, default=None, _type=None: {
                workflow.SOUNDCLOUD_CLIENT_ID_SETTING: "client-id"
            }.get(key, default)
        )
        return app

    monkeypatch.setattr(workflow, "SoundCloudPublishDialog", _Dialog)
    monkeypatch.setattr(workflow, "SoundCloudPublishExecutor", _Executor)
    monkeypatch.setattr(workflow, "build_soundcloud_publish_planner", lambda _app: object())
    monkeypatch.setattr(workflow, "_soundcloud_repository", lambda _app: _Repo())
    monkeypatch.setattr(workflow, "_soundcloud_oauth_service", lambda _app: _OAuth())
    monkeypatch.setattr(workflow, "_soundcloud_client", lambda _app: object())
    monkeypatch.setattr(
        workflow, "_soundcloud_token_store", lambda app: app._soundcloud_token_store
    )

    task_app = _base_app()

    def _submit_background_task(**kwargs):
        events.append(kwargs["title"])
        result = kwargs["task_fn"]("ctx")
        kwargs["on_success"](result)
        return result

    task_app._submit_background_task = _submit_background_task
    assert (
        workflow.open_soundcloud_publish_dialog(task_app, track_ids=[1]).status
        == SoundCloudExecutionStatus.COMPLETED
    )
    assert "Publish to SoundCloud" in events

    direct_app = _base_app()
    assert (
        workflow.open_soundcloud_publish_dialog(direct_app, track_ids=[1]).status
        == SoundCloudExecutionStatus.COMPLETED
    )
    assert events.count("success:completed") >= 2


def test_open_soundcloud_publish_dialog_publish_runner_error_branches(monkeypatch) -> None:
    account = SoundCloudAccountRecord(
        id=13,
        account_key="soundcloud:user:13",
        token_store_key="soundcloud:user:13",
        token_kind=SoundCloudTokenKind.SESSION,
        connection_status="connected",
        username="Artist",
    )

    class _Dialog:
        def __init__(self, **kwargs):
            self.publish_runner = kwargs["publish_runner"]
            self.errors: list[str] = []

        def exec(self):
            return self.publish_runner(_plan())

        def apply_execution_error(self, failure):
            self.errors.append(str(failure))

    class _Repo:
        def __init__(self, active_account):
            self._active_account = active_account
            self.disconnected: list[int] = []

        def active_account(self):
            return self._active_account

        def mark_disconnected(self, account_id, *, error=None):
            del error
            self.disconnected.append(account_id)

    class _Store:
        def __init__(self, bundle):
            self.bundle = bundle

        def load_bundle(self, _key):
            return self.bundle

        def load_client_secret(self, _client_id):
            return ""

    app = SimpleNamespace(
        current_db_path="",
        conn=SimpleNamespace(commit=mock.Mock()),
        track_service=object(),
        _log_trace=mock.Mock(),
    )
    app.settings = SimpleNamespace(value=lambda *_args: "")
    monkeypatch.setattr(workflow, "SoundCloudPublishDialog", _Dialog)
    monkeypatch.setattr(workflow, "build_soundcloud_publish_planner", lambda _app: object())

    repo = _Repo(active_account=None)
    monkeypatch.setattr(workflow, "_soundcloud_repository", lambda _app: repo)
    monkeypatch.setattr(workflow, "_soundcloud_token_store", lambda _app: _Store(object()))
    assert workflow.open_soundcloud_publish_dialog(app, track_ids=[1]) is None
    assert app._log_trace.called

    app._log_trace.reset_mock()
    repo = _Repo(active_account=account)
    monkeypatch.setattr(workflow, "_soundcloud_repository", lambda _app: repo)
    monkeypatch.setattr(workflow, "_soundcloud_token_store", lambda _app: _Store(None))
    assert workflow.open_soundcloud_publish_dialog(app, track_ids=[1]) is None
    assert repo.disconnected == [13]
    assert app.conn.commit.called


def test_soundcloud_upload_media_preparer_converts_embedded_audio_to_watermarked_wav() -> None:
    conversion = _FakeConversionService()
    authenticity = _FakeAuthenticityService()
    preparer = SoundCloudWatermarkedWavMediaPreparer(
        track_service=_BlobTrackService(),
        authenticity_service=authenticity,
        conversion_service=conversion,
        profile_name="Test Profile",
    )

    prepared = preparer.prepare_upload_media(46, include_artwork=True)
    try:
        assert prepared.audio_path.name.endswith(".soundcloud-watermarked.wav")
        assert prepared.audio_path.read_bytes().endswith(b"-wav-watermarked")
        assert prepared.artwork_path is not None
        assert prepared.artwork_path.read_bytes() == b"embedded-artwork"
        assert conversion.calls[0][2:] == ("wav", "strip")
        assert authenticity.calls[0][0] == 46
    finally:
        prepared.cleanup()


def _plan(
    *,
    status: SoundCloudPlanItemStatus = SoundCloudPlanItemStatus.READY,
    issues: tuple[SoundCloudPreflightIssue, ...] = (),
    action: SoundCloudPlanAction = SoundCloudPlanAction.CREATE,
    remote_urn: str | None = None,
) -> SoundCloudPublishPlanResult:
    metadata = (
        None
        if status == SoundCloudPlanItemStatus.BLOCKED
        else SoundCloudTrackMetadataPayload(
            track_id=1,
            title="Preflight Track",
            asset_data="/tmp/audio.wav" if action == SoundCloudPlanAction.CREATE else None,
            artwork_data="/tmp/artwork.png",
        )
    )
    item = SoundCloudPublishPlanItem(
        track_id=1,
        status=status,
        action=action,
        title="Preflight Track",
        remote_urn=remote_urn,
        remote_numeric_id=123 if remote_urn else None,
        metadata=metadata,
        issues=list(issues),
        would_upload_audio=action == SoundCloudPlanAction.CREATE,
    )
    return SoundCloudPublishPlanResult(
        track_ids=(1,),
        items=(item,),
        options=SoundCloudPublishOptions(),
        quota_snapshot=None,
    )


def _issue(severity: SoundCloudPreflightSeverity) -> SoundCloudPreflightIssue:
    return SoundCloudPreflightIssue(
        code=(
            SoundCloudPreflightIssueCode.MISSING_AUDIO
            if severity == SoundCloudPreflightSeverity.BLOCK
            else SoundCloudPreflightIssueCode.MISSING_QUOTA_SNAPSHOT
        ),
        severity=severity,
        message="preflight issue",
    )


def test_soundcloud_logo_path_is_palette_driven() -> None:
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.ColorRole.Window, QColor("#161616"))
    light_palette = QPalette()
    light_palette.setColor(QPalette.ColorRole.Window, QColor("#f4f4f4"))

    assert (
        soundcloud_ui._soundcloud_logo_path_for_palette(dark_palette).name
        == "SoundCloud_Horizontal White (transparent).png"
    )
    assert (
        soundcloud_ui._soundcloud_logo_path_for_palette(light_palette).name
        == "SoundCloud_Horizontal Black (transparent).png"
    )


def test_soundcloud_ui_small_helpers_and_null_actions() -> None:
    actions = soundcloud_ui.NullSoundCloudConnectionActions(
        SoundCloudSettingsSnapshot(account_label="Offline")
    )

    assert soundcloud_ui._format_duration(-5) == "0:00"
    assert soundcloud_ui._format_duration(3661) == "1:01:01"
    assert actions.snapshot().account_label == "Offline"
    assert actions.disconnect().account_label == "Offline"
    with pytest.raises(RuntimeError, match="connection service"):
        actions.connect(client_id="client", redirect_uri="http://127.0.0.1/callback")
    with pytest.raises(RuntimeError, match="connection service"):
        actions.refresh(client_id="client", redirect_uri="http://127.0.0.1/callback")
    with pytest.raises(RuntimeError, match="credential service"):
        actions.save_client_secret(client_id="client", client_secret="secret")


def _all_widget_text(widget) -> str:
    texts: list[str] = []
    for widget_type in (QLabel, QLineEdit, QPushButton, QCheckBox):
        for child in widget.findChildren(widget_type):
            if isinstance(child, QLineEdit):
                texts.append(child.text())
                texts.append(child.placeholderText())
            else:
                texts.append(child.text())
    return "\n".join(texts)


def test_soundcloud_settings_tab_loads_with_disconnected_session_fallback() -> None:
    app = require_qapplication()
    dialog = ApplicationSettingsDialog(**_dialog_kwargs())
    try:
        dialog.focus_field("soundcloud")
        pump_events(app=app)

        assert dialog.tabs.tabText(dialog.tabs.currentIndex()) == "SoundCloud"
        assert "Disconnected" in dialog.soundcloud_panel.account_status_label.text()
        assert (
            "Session-only fallback is active"
            in dialog.soundcloud_panel.session_fallback_label.text()
        )
    finally:
        dialog.close()


def test_settings_tab_enables_persistent_mode_only_for_safe_backend() -> None:
    require_qapplication()
    unavailable_panel = SoundCloudSettingsPanel(
        snapshot=SoundCloudSettingsSnapshot(persistent_available=False)
    )
    available_panel = SoundCloudSettingsPanel(
        snapshot=SoundCloudSettingsSnapshot(
            persistent_available=True,
            token_storage_label="Persistent OS keychain/keyring available",
        )
    )
    try:
        assert not unavailable_panel.persistent_check.isEnabled()
        assert "Unavailable" in unavailable_panel.keychain_status_label.text()
        assert available_panel.persistent_check.isEnabled()
        assert "Available" in available_panel.keychain_status_label.text()
    finally:
        unavailable_panel.close()
        available_panel.close()


def test_settings_actions_call_service_layer_and_redact_errors() -> None:
    app = require_qapplication()
    actions = _FakeActions()
    panel = SoundCloudSettingsPanel(
        snapshot=actions.snapshot(),
        actions=actions,
    )
    try:
        panel.client_id_edit.setText("client-id")
        panel.redirect_uri_edit.setText("https://callback.invalid/soundcloud/callback")

        panel.refresh_button.click()
        panel.disconnect_button.click()
        panel.client_id_edit.setText("client-id")
        panel.client_secret_edit.setText("client-secret-value")
        panel.save_secret_button.click()
        actions.raise_connect = True
        panel.connect_button.click()
        pump_events(app=app)

        assert actions.calls[:2] == [
            "refresh:client-id:https://callback.invalid/soundcloud/callback",
            "disconnect",
        ]
        assert actions.calls[2] == "save_secret:client-id:True"
        visible = _all_widget_text(panel)
        assert "client-secret-value" not in visible
        assert "access_token=secret" not in visible
        assert "refresh_token=secret" not in visible
        assert "client_secret=secret" not in visible
        assert "code=secret" not in visible
        assert "access_token=***" in panel.message_label.text()
        assert "client_secret=***" in panel.message_label.text()
    finally:
        panel.close()


def test_soundcloud_connect_hides_settings_window_during_oauth() -> None:
    app = require_qapplication()
    visibility_during_connect: list[bool] = []

    class _OAuthActions(_FakeActions):
        def connect(self, *, client_id: str, redirect_uri: str) -> SoundCloudSettingsSnapshot:
            del client_id, redirect_uri
            visibility_during_connect.append(dialog.isVisible())
            return self.snapshot_value

    dialog = QDialog()
    layout = QVBoxLayout(dialog)
    actions = _OAuthActions()
    panel = SoundCloudSettingsPanel(snapshot=actions.snapshot(), actions=actions)
    layout.addWidget(panel)
    try:
        dialog.show()
        pump_events(app=app)
        assert dialog.isVisible()

        panel.connect_button.click()
        pump_events(app=app)

        assert visibility_during_connect == [False]
        assert dialog.isVisible()
    finally:
        dialog.close()


def test_soundcloud_safe_settings_persist_without_secret_values() -> None:
    app = _fake_app()
    before = _base_values()
    after = dict(
        before,
        soundcloud_client_id="safe-client-id",
        soundcloud_redirect_uri="https://callback.invalid/soundcloud/callback",
        soundcloud_prefer_persistent_tokens=False,
    )

    changed = settings_controller._apply_settings_changes(app, before, after)

    assert changed == 1
    assert app.settings.stored == {
        "soundcloud/client_id": "safe-client-id",
        "soundcloud/redirect_uri": "https://callback.invalid/soundcloud/callback",
        "soundcloud/prefer_persistent_tokens": False,
    }
    stored_text = "\n".join(str(value) for value in app.settings.stored.values())
    assert "access_token" not in stored_text
    assert "refresh_token" not in stored_text
    assert "client_secret" not in stored_text
    assert "code=" not in stored_text


def test_direct_soundcloud_settings_shortcut_uses_soundcloud_focus(
    monkeypatch,
) -> None:
    calls: list[tuple[object, str | None]] = []
    monkeypatch.setattr(
        settings_controller,
        "open_settings_dialog",
        lambda app, initial_focus=None: calls.append((app, initial_focus)),
    )
    app = SimpleNamespace()

    workflow.open_soundcloud_settings_dialog(app)

    assert calls == [(app, "soundcloud")]


def test_publish_account_state_rechecks_active_account_after_settings_connect() -> None:
    token_store = SimpleNamespace(load_bundle=lambda _key: object())

    class _Repo:
        account = None

        def active_account(self):
            return self.account

    app = SimpleNamespace(_soundcloud_token_store=token_store)
    repo = _Repo()
    account_state = workflow._AccountState(app, repo)

    assert not account_state.is_connected()

    repo.account = SoundCloudAccountRecord(
        id=1,
        account_key="soundcloud:user:1",
        token_store_key="soundcloud:user:1",
        token_kind=SoundCloudTokenKind.SESSION,
        connection_status="connected",
        username="Connected User",
    )

    assert account_state.is_connected()

    app._soundcloud_token_store = SimpleNamespace(load_bundle=lambda _key: None)

    assert not account_state.is_connected()


def test_soundcloud_connect_minimizes_for_browser_and_restores_after_success(
    monkeypatch,
) -> None:
    calls: list[str] = []

    class _FakeApp:
        conn = SimpleNamespace(commit=lambda: calls.append("commit"))
        soundcloud_client_secret_provider = staticmethod(lambda _client_id: "client-secret")
        soundcloud_authorization_callback_provider = staticmethod(
            lambda _auth_url, _state, _redirect_uri: "isrc://callback?code=auth-code&state=state"
        )

        def isMaximized(self):
            return False

        def showMinimized(self):
            calls.append("minimize")

        def showNormal(self):
            calls.append("normal")

        def raise_(self):
            calls.append("raise")

        def activateWindow(self):
            calls.append("activate")

    class _OAuthService:
        def complete_authorization_callback(self, **kwargs):
            calls.append("complete")
            assert kwargs["client_secret"] == "client-secret"

    monkeypatch.setattr(workflow, "_soundcloud_oauth_service", lambda _app: _OAuthService())
    monkeypatch.setattr(
        workflow,
        "soundcloud_settings_snapshot",
        lambda _app: SoundCloudSettingsSnapshot(connected=True),
    )

    result = workflow.SoundCloudAppConnectionActions(_FakeApp()).connect(
        client_id="client-id",
        redirect_uri="isrc://callback",
    )

    assert result.connected
    assert calls[0] == "minimize"
    assert "complete" in calls
    assert calls[-3:] == ["normal", "raise", "activate"]


def test_catalog_menu_exposes_publish_soundcloud_action() -> None:
    app = QApplication.instance() or require_qapplication()
    shell = _ShellStub()
    try:
        _build_actions_and_menus(shell, movable=False)

        catalog_action = next(
            action
            for action in shell.menu_bar.actions()
            if action.text() == "Catalog" and action.menu() is not None
        )
        catalog_menu = catalog_action.menu()
        assert catalog_menu is not None
        publish_action = next(
            action
            for action in catalog_menu.actions()
            if action.text() == "Publish" and action.menu() is not None
        )
        publish_menu = publish_action.menu()
        assert publish_menu is not None
        soundcloud_action = next(
            action for action in publish_menu.actions() if action.text() == "SoundCloud…"
        )

        soundcloud_action.trigger()
        app.processEvents()

        assert "open_soundcloud_publish_dialog" in shell._triggered
    finally:
        shell.close()


def test_publish_dialog_shows_preflight_and_private_defaults() -> None:
    require_qapplication()
    planner = _FakePlanner(_plan())
    dialog = SoundCloudPublishDialog(track_ids=(1,), planner=planner)
    try:
        assert planner.calls[0][0] == [1]
        assert planner.calls[0][1].sharing == "private"
        assert dialog.table.rowCount() == 1
        assert dialog.table.item(0, 0).text() == "Preflight Track"
        assert dialog.table.item(0, 6).text() == "private"
        assert dialog.publish_button.isEnabled()
    finally:
        dialog.close()


def test_catalog_track_selection_dialog_filters_sorts_and_applies_checked_tracks() -> None:
    require_qapplication()
    choices = [
        SoundCloudCatalogTrackChoice(
            track_id=1,
            title="Blue One",
            album="Z Album",
            artist="Artist A",
            isrc="NLAAA2600001",
            duration_seconds=61,
        ),
        SoundCloudCatalogTrackChoice(
            track_id=2,
            title="Amber Two",
            album="A Album",
            artist="Artist B",
            isrc="NLAAA2600002",
            duration_seconds=122,
        ),
    ]
    dialog = SoundCloudCatalogTrackSelectionDialog(
        choices=choices,
        selected_track_ids=(1,),
    )
    try:
        assert dialog.table.rowCount() == 2
        dialog.filter_edit.setText("amber")

        hidden_rows = [
            row for row in range(dialog.table.rowCount()) if dialog.table.isRowHidden(row)
        ]
        assert len(hidden_rows) == 1
        assert dialog.table.editTriggers() == soundcloud_ui.QTableWidget.NoEditTriggers

        for row in range(dialog.table.rowCount()):
            item = dialog.table.item(row, 0)
            assert not (item.flags() & Qt.ItemIsEditable)
            assert item.text() in {"No", "Yes"}
            if int(item.data(Qt.UserRole)) == 2:
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)

        assert dialog.selected_track_ids() == (2,)

        selected_row = next(
            row
            for row in range(dialog.table.rowCount())
            if int(dialog.table.item(row, 0).data(Qt.UserRole)) == 2
        )
        dialog.table.cellClicked.emit(selected_row, 0)

        assert dialog.selected_track_ids() == ()
    finally:
        dialog.close()


def test_publish_dialog_track_selection_button_uses_separate_window(monkeypatch) -> None:
    require_qapplication()
    planner = _FakePlanner(_plan())
    choices = [
        SoundCloudCatalogTrackChoice(track_id=1, title="Blue One"),
        SoundCloudCatalogTrackChoice(track_id=2, title="Amber Two"),
    ]
    opened: list[tuple[list[SoundCloudCatalogTrackChoice], tuple[int, ...]]] = []

    class _FakeChooser:
        def __init__(self, *, choices, selected_track_ids, parent=None):
            del parent
            opened.append((list(choices), tuple(selected_track_ids)))

        def exec(self):
            return soundcloud_ui.QDialog.Accepted

        def selected_track_ids(self):
            return (2,)

    monkeypatch.setattr(soundcloud_ui, "SoundCloudCatalogTrackSelectionDialog", _FakeChooser)
    dialog = SoundCloudPublishDialog(
        track_ids=(1,),
        planner=planner,
        catalog_track_provider=lambda: choices,
    )
    try:
        assert dialog.catalog_button.isEnabled()
        assert not hasattr(dialog, "catalog_table")

        dialog.open_catalog_track_selection()

        assert opened == [(choices, (1,))]
        assert dialog.track_ids == (2,)
        assert planner.calls[-1][0] == [2]
    finally:
        dialog.close()


def test_blocking_preflight_errors_prevent_live_publish() -> None:
    app = require_qapplication()
    calls: list[SoundCloudPublishPlanResult] = []
    dialog = SoundCloudPublishDialog(
        track_ids=(1,),
        planner=_FakePlanner(
            _plan(
                status=SoundCloudPlanItemStatus.BLOCKED,
                issues=(_issue(SoundCloudPreflightSeverity.BLOCK),),
            )
        ),
        publish_runner=calls.append,
    )
    try:
        dialog.publish()
        pump_events(app=app)

        assert calls == []
        assert "blocking" in dialog.status_label.text().lower()
    finally:
        dialog.close()


def test_warnings_allow_publish_review_and_delegate_execution() -> None:
    require_qapplication()
    calls: list[SoundCloudPublishPlanResult] = []
    dialog = SoundCloudPublishDialog(
        track_ids=(1,),
        planner=_FakePlanner(
            _plan(
                status=SoundCloudPlanItemStatus.WARN,
                issues=(_issue(SoundCloudPreflightSeverity.WARNING),),
            )
        ),
        publish_runner=calls.append,
    )
    try:
        assert dialog.publish_button.isEnabled()

        dialog.publish()

        assert len(calls) == 1
    finally:
        dialog.close()


def test_publish_dialog_settings_shortcut_and_cancellation_status() -> None:
    require_qapplication()
    opened: list[bool] = []
    dialog = SoundCloudPublishDialog(
        track_ids=(1,),
        planner=_FakePlanner(_plan()),
        settings_opener=lambda: opened.append(True),
    )
    try:
        dialog.settings_button.click()
        dialog.cancel_button.click()

        assert opened == [True]
        assert "Cancellation requested" in dialog.status_label.text()
    finally:
        dialog.close()


def test_publish_dialog_updates_status_from_execution_result() -> None:
    require_qapplication()
    dialog = SoundCloudPublishDialog(track_ids=(1,), planner=_FakePlanner(_plan()))
    try:
        dialog.apply_execution_result(
            SoundCloudPublishExecutionResult(
                run_id=1,
                status=SoundCloudExecutionStatus.COMPLETED,
                items_total=1,
                items_succeeded=1,
                items_failed=0,
                items_skipped=0,
                item_results=(),
            )
        )

        assert "1 succeeded" in dialog.status_label.text()
    finally:
        dialog.close()


def test_publish_dialog_empty_and_unconfigured_execution_edges() -> None:
    require_qapplication()
    empty_dialog = SoundCloudPublishDialog(track_ids=(), planner=_FakePlanner(_plan()))
    try:
        assert "No tracks selected" in empty_dialog.status_label.text()
        empty_dialog.publish()
        assert "No SoundCloud publish plan" in empty_dialog.status_label.text()
        empty_dialog.update_published_metadata()
        assert "No SoundCloud update plan" in empty_dialog.status_label.text()
    finally:
        empty_dialog.close()

    no_runner = SoundCloudPublishDialog(track_ids=(1,), planner=_FakePlanner(_plan()))
    try:
        no_runner.publish()
        assert "execution service is not configured" in no_runner.status_label.text()
    finally:
        no_runner.close()


def test_publish_dialog_reports_rich_metadata_warning() -> None:
    require_qapplication()
    dialog = SoundCloudPublishDialog(track_ids=(1,), planner=_FakePlanner(_plan()))
    try:
        dialog.apply_execution_result(
            SoundCloudPublishExecutionResult(
                run_id=1,
                status=SoundCloudExecutionStatus.COMPLETED,
                items_total=1,
                items_succeeded=1,
                items_failed=0,
                items_skipped=0,
                item_results=(
                    SoundCloudPublishExecutionItemResult(
                        track_id=1,
                        status=SoundCloudExecutionItemStatus.SUCCESS,
                        action=SoundCloudPlanAction.UPDATE,
                        operation_message=(
                            "SoundCloud public update completed; rich web-editor metadata "
                            "was rejected by the API."
                        ),
                    ),
                ),
            )
        )

        assert "rich metadata warning" in dialog.status_label.text()
    finally:
        dialog.close()


def test_publish_dialog_task_failure_status_omits_traceback() -> None:
    require_qapplication()
    opened: list[bool] = []
    dialog = SoundCloudPublishDialog(
        track_ids=(1,),
        planner=_FakePlanner(_plan()),
        error_log_opener=lambda: opened.append(True),
    )
    try:
        dialog.show()
        pump_events()
        dialog.apply_execution_error(
            TaskFailure(
                message="SoundCloud stored credentials are unavailable; reconnect required.",
                traceback_text="Traceback with access_token=secret-token",
            )
        )

        assert "SoundCloud publish failed" in dialog.status_label.text()
        assert "Traceback" not in dialog.status_label.text()
        assert "secret-token" not in dialog.status_label.text()
        assert dialog.error_log_button.isVisible()

        dialog.error_log_button.click()

        assert opened == [True]
    finally:
        dialog.close()


def test_soundcloud_publish_failure_is_recorded_to_trace_log() -> None:
    events: list[dict[str, object]] = []

    def _log_trace(event, **fields):
        events.append({"event": event, **fields})

    app = SimpleNamespace(_log_trace=_log_trace)
    failure = TaskFailure(
        message="Upload failed access_token=abc123",
        traceback_text="Traceback with Authorization: Bearer token-secret and code=auth-code",
    )

    workflow._record_soundcloud_publish_failure(app, failure)

    assert events[0]["event"] == "soundcloud.publish.error"
    details = events[0]["details"]
    assert "traceback" in details
    rendered = str(details)
    assert "abc123" not in rendered
    assert "token-secret" not in rendered
    assert "auth-code" not in rendered
    assert "access_token=***" in rendered


def test_publish_history_dialog_lists_non_secret_run_summaries() -> None:
    require_qapplication()
    dialog = SoundCloudPublishHistoryDialog(
        runs=[
            SoundCloudPublishRunSummary(
                run_id=7,
                status="completed",
                created_at="2026-05-28T12:00:00Z",
                items_total=2,
                items_succeeded=1,
                items_failed=1,
                items_skipped=0,
            )
        ]
    )
    try:
        assert dialog.table.rowCount() == 1
        assert dialog.table.item(0, 0).text() == "7"
        assert "access_token" not in _all_widget_text(dialog)
        assert "refresh_token" not in _all_widget_text(dialog)
    finally:
        dialog.close()


def test_publish_dialog_history_catalog_and_album_optional_edges(monkeypatch) -> None:
    require_qapplication()
    opened_history: list[bool] = []

    monkeypatch.setattr(
        soundcloud_ui.SoundCloudPublishHistoryDialog,
        "exec",
        lambda self: opened_history.append(True) or QDialog.Accepted,
    )
    dialog = SoundCloudPublishDialog(
        track_ids=(1,),
        planner=_FakePlanner(_plan()),
        history_provider=lambda: [
            SoundCloudPublishRunSummary(
                run_id=1,
                status="completed",
                created_at="2026-05-29T00:00:00Z",
                items_total=1,
                items_succeeded=1,
                items_failed=0,
                items_skipped=0,
            )
        ],
        album_track_resolver=lambda track_ids: [int(track_ids[0]), 77],
    )
    try:
        dialog.open_history()
        assert opened_history == [True]

        dialog.open_catalog_track_selection()
        assert dialog.track_ids == (1,)

        dialog.use_album_selection()
        assert dialog.track_ids == (1, 77)
    finally:
        dialog.close()

    no_history = SoundCloudPublishDialog(track_ids=(1,), planner=_FakePlanner(_plan()))
    try:
        no_history.open_history()
        no_history.use_album_selection()
        assert no_history.track_ids == (1,)
    finally:
        no_history.close()


def test_publish_dialog_planning_uses_fakes_only() -> None:
    require_qapplication()
    fake_runner = mock.Mock()
    dialog = SoundCloudPublishDialog(
        track_ids=(1,),
        planner=_FakePlanner(_plan(action=SoundCloudPlanAction.UPDATE, remote_urn="urn:track:123")),
        publish_runner=fake_runner,
    )
    try:
        dialog.publish()

        fake_runner.assert_called_once()
    finally:
        dialog.close()


def test_publish_dialog_update_button_requires_linked_publication() -> None:
    require_qapplication()
    create_runner = mock.Mock()
    create_dialog = SoundCloudPublishDialog(
        track_ids=(1,),
        planner=_FakePlanner(_plan(action=SoundCloudPlanAction.CREATE)),
        publish_runner=create_runner,
    )
    try:
        create_dialog.update_published_metadata()

        create_runner.assert_not_called()
        assert "Link selected tracks" in create_dialog.status_label.text()
    finally:
        create_dialog.close()

    update_runner = mock.Mock()
    update_dialog = SoundCloudPublishDialog(
        track_ids=(1,),
        planner=_FakePlanner(
            _plan(action=SoundCloudPlanAction.UPDATE, remote_urn="soundcloud:tracks:123")
        ),
        publish_runner=update_runner,
    )
    try:
        assert update_dialog.update_button.isEnabled()

        update_dialog.update_published_metadata()

        update_runner.assert_called_once()
    finally:
        update_dialog.close()


def test_publish_dialog_link_existing_upload_uses_safe_manual_review(monkeypatch) -> None:
    require_qapplication()
    linked: list[tuple[int, str]] = []
    dialog = SoundCloudPublishDialog(
        track_ids=(42,),
        planner=_FakePlanner(_plan()),
        publication_linker=lambda track_id, remote_ref: linked.append((track_id, remote_ref)),
    )
    try:
        monkeypatch.setattr(
            soundcloud_ui.QInputDialog,
            "getText",
            lambda *_args, **_kwargs: (" https://soundcloud.com/artist/existing ", True),
        )

        dialog.link_existing_upload()

        assert linked == [(42, "https://soundcloud.com/artist/existing")]
        assert "Linked existing SoundCloud upload" in dialog.status_label.text()
    finally:
        dialog.close()

    multi_dialog = SoundCloudPublishDialog(
        track_ids=(1, 2),
        planner=_FakePlanner(_plan()),
        publication_linker=lambda track_id, remote_ref: linked.append((track_id, remote_ref)),
    )
    try:
        multi_dialog.link_existing_upload()

        assert "exactly one" in multi_dialog.status_label.text()
    finally:
        multi_dialog.close()


def test_existing_upload_browser_filters_and_selects_upload() -> None:
    require_qapplication()
    dialog = SoundCloudExistingUploadSelectionDialog(
        choices=[
            SoundCloudExistingUploadChoice(
                remote_urn="soundcloud:tracks:10",
                remote_numeric_id=10,
                remote_url="https://soundcloud.com/artist/alpha",
                title="Alpha Upload",
                genre="Ambient",
                created_at="2026-05-28",
            ),
            SoundCloudExistingUploadChoice(
                remote_urn="soundcloud:tracks:11",
                remote_numeric_id=11,
                remote_url="https://soundcloud.com/artist/beta",
                title="Beta Upload",
                genre="Dub",
                created_at="2026-05-29",
            ),
        ]
    )
    try:
        assert dialog.selected_upload().remote_urn == "soundcloud:tracks:10"
        dialog.filter_edit.setText("beta")

        hidden_rows = [
            row for row in range(dialog.table.rowCount()) if dialog.table.isRowHidden(row)
        ]

        assert len(hidden_rows) == 1
        dialog.table.selectRow(1)
        assert dialog.selected_upload().remote_urn == "soundcloud:tracks:11"
    finally:
        dialog.close()


def test_metadata_comparison_dialog_marks_changed_rows() -> None:
    require_qapplication()
    dialog = SoundCloudMetadataComparisonDialog(
        rows=[
            SoundCloudMetadataComparisonRow(
                field="Title",
                catalog_value="Catalog Title",
                remote_value="Remote Title",
                changed=True,
            ),
            SoundCloudMetadataComparisonRow(
                field="ISRC",
                catalog_value="NL-C5I-26-00001",
                remote_value="NL-C5I-26-00001",
                changed=False,
            ),
        ]
    )
    try:
        assert dialog.table.rowCount() == 2
        assert dialog.table.item(0, 3).text() == "Changed"
        assert dialog.table.item(1, 3).text() == "Same"
        assert "1 changed" in dialog.status_label.text()
    finally:
        dialog.close()


def test_publish_dialog_browses_existing_uploads_without_direct_update(monkeypatch) -> None:
    require_qapplication()
    linked: list[tuple[int, str]] = []
    choices = [
        SoundCloudExistingUploadChoice(
            remote_urn="soundcloud:tracks:909",
            remote_numeric_id=909,
            remote_url="https://soundcloud.com/artist/existing-909",
            title="Existing Upload",
        )
    ]

    monkeypatch.setattr(
        soundcloud_ui.SoundCloudExistingUploadSelectionDialog,
        "exec",
        lambda self: QDialog.Accepted,
    )
    monkeypatch.setattr(
        soundcloud_ui.SoundCloudExistingUploadSelectionDialog,
        "selected_upload",
        lambda self: self._choices[0],
    )
    dialog = SoundCloudPublishDialog(
        track_ids=(42,),
        planner=_FakePlanner(_plan()),
        publication_linker=lambda track_id, remote_ref: linked.append((track_id, remote_ref)),
        existing_upload_provider=lambda: choices,
    )
    try:
        dialog.browse_existing_uploads()

        assert linked == [(42, "https://soundcloud.com/artist/existing-909")]
        assert "Linked existing SoundCloud upload" in dialog.status_label.text()
    finally:
        dialog.close()


def test_publish_dialog_compares_remote_metadata_before_update(monkeypatch) -> None:
    require_qapplication()
    opened: list[int] = []
    rows = [
        SoundCloudMetadataComparisonRow(
            field="Title",
            catalog_value="Catalog",
            remote_value="Remote",
            changed=True,
        )
    ]

    monkeypatch.setattr(
        soundcloud_ui.SoundCloudMetadataComparisonDialog,
        "exec",
        lambda self: opened.append(self.table.rowCount()) or QDialog.Accepted,
    )
    dialog = SoundCloudPublishDialog(
        track_ids=(1,),
        planner=_FakePlanner(
            _plan(action=SoundCloudPlanAction.UPDATE, remote_urn="soundcloud:tracks:123")
        ),
        metadata_comparison_provider=lambda plan: rows,
    )
    try:
        assert dialog.compare_button.isEnabled()

        dialog.compare_remote_metadata()

        assert opened == [1]
    finally:
        dialog.close()


def test_publish_dialog_existing_upload_browser_edge_states(monkeypatch) -> None:
    require_qapplication()
    no_provider = SoundCloudPublishDialog(track_ids=(1,), planner=_FakePlanner(_plan()))
    try:
        no_provider.browse_existing_uploads()
        assert "not available" in no_provider.status_label.text()
    finally:
        no_provider.close()

    multi = SoundCloudPublishDialog(
        track_ids=(1, 2),
        planner=_FakePlanner(_plan()),
        publication_linker=lambda _track_id, _remote_ref: None,
        existing_upload_provider=list,
    )
    try:
        multi.browse_existing_uploads()
        assert "exactly one" in multi.status_label.text()
    finally:
        multi.close()

    provider_error = SoundCloudPublishDialog(
        track_ids=(1,),
        planner=_FakePlanner(_plan()),
        publication_linker=lambda _track_id, _remote_ref: None,
        existing_upload_provider=lambda: (_ for _ in ()).throw(RuntimeError("access_token=secret")),
    )
    try:
        provider_error.browse_existing_uploads()
        assert "access_token=***" in provider_error.status_label.text()
        assert "secret" not in provider_error.status_label.text()
    finally:
        provider_error.close()

    empty = SoundCloudPublishDialog(
        track_ids=(1,),
        planner=_FakePlanner(_plan()),
        publication_linker=lambda _track_id, _remote_ref: None,
        existing_upload_provider=list,
    )
    try:
        empty.browse_existing_uploads()
        assert "No existing SoundCloud uploads" in empty.status_label.text()
    finally:
        empty.close()

    monkeypatch.setattr(
        soundcloud_ui.SoundCloudExistingUploadSelectionDialog,
        "exec",
        lambda self: QDialog.Accepted,
    )
    monkeypatch.setattr(
        soundcloud_ui.SoundCloudExistingUploadSelectionDialog,
        "selected_upload",
        lambda self: SoundCloudExistingUploadChoice(
            remote_urn="",
            remote_numeric_id=1234,
            remote_url=None,
            title="Numeric fallback",
        ),
    )
    linked: list[tuple[int, str]] = []
    numeric = SoundCloudPublishDialog(
        track_ids=(1,),
        planner=_FakePlanner(_plan()),
        publication_linker=lambda track_id, remote_ref: linked.append((track_id, remote_ref)),
        existing_upload_provider=lambda: [
            SoundCloudExistingUploadChoice(
                remote_urn="",
                remote_numeric_id=1234,
                remote_url=None,
                title="Numeric fallback",
            )
        ],
    )
    try:
        numeric.browse_existing_uploads()
        assert linked == [(1, "1234")]
    finally:
        numeric.close()

    monkeypatch.setattr(
        soundcloud_ui.SoundCloudExistingUploadSelectionDialog,
        "selected_upload",
        lambda self: SoundCloudExistingUploadChoice(
            remote_urn="",
            remote_numeric_id=None,
            remote_url=None,
            title="Broken",
        ),
    )
    broken = SoundCloudPublishDialog(
        track_ids=(1,),
        planner=_FakePlanner(_plan()),
        publication_linker=lambda _track_id, _remote_ref: None,
        existing_upload_provider=lambda: [
            SoundCloudExistingUploadChoice(remote_urn="", remote_numeric_id=None, remote_url=None)
        ],
    )
    try:
        broken.browse_existing_uploads()
        assert "no usable remote identifier" in broken.status_label.text()
    finally:
        broken.close()


def test_publish_dialog_metadata_comparison_edge_states() -> None:
    require_qapplication()
    unavailable = SoundCloudPublishDialog(track_ids=(1,), planner=_FakePlanner(_plan()))
    try:
        unavailable.compare_remote_metadata()
        assert "not available" in unavailable.status_label.text()
    finally:
        unavailable.close()

    create_plan = SoundCloudPublishDialog(
        track_ids=(1,),
        planner=_FakePlanner(_plan(action=SoundCloudPlanAction.CREATE)),
        metadata_comparison_provider=list,
    )
    try:
        create_plan.compare_remote_metadata()
        assert "No linked SoundCloud update items" in create_plan.status_label.text()
    finally:
        create_plan.close()

    provider_error = SoundCloudPublishDialog(
        track_ids=(1,),
        planner=_FakePlanner(
            _plan(action=SoundCloudPlanAction.UPDATE, remote_urn="soundcloud:tracks:12")
        ),
        metadata_comparison_provider=lambda _plan: (_ for _ in ()).throw(
            RuntimeError("refresh_token=secret")
        ),
    )
    try:
        provider_error.compare_remote_metadata()
        assert "refresh_token=***" in provider_error.status_label.text()
        assert "secret" not in provider_error.status_label.text()
    finally:
        provider_error.close()

    empty_rows = SoundCloudPublishDialog(
        track_ids=(1,),
        planner=_FakePlanner(
            _plan(action=SoundCloudPlanAction.UPDATE, remote_urn="soundcloud:tracks:12")
        ),
        metadata_comparison_provider=lambda _plan: [],
    )
    try:
        empty_rows.compare_remote_metadata()
        assert "No comparable" in empty_rows.status_label.text()
    finally:
        empty_rows.close()


def test_workflow_lists_existing_uploads_and_builds_metadata_comparison(
    monkeypatch,
) -> None:
    from dataclasses import replace

    account = SoundCloudAccountRecord(
        id=31,
        account_key="soundcloud:user:31",
        token_store_key="soundcloud:user:31",
        token_kind=SoundCloudTokenKind.SESSION,
        connection_status="connected",
        username="Artist",
    )

    class _Repo:
        def active_account(self):
            return account

    class _Store:
        def load_bundle(self, _key):
            return object()

        def load_client_secret(self, _client_id):
            return "client-secret"

    class _OAuth:
        def token_for_account(self, account_id, *, client_id=None, client_secret=None):
            assert account_id == 31
            assert client_id == "client-id"
            assert client_secret == "client-secret"
            return "access-token"

    class _Client:
        def __init__(self) -> None:
            self.list_calls = 0
            self.fetch_calls: list[object] = []

        def list_my_tracks(self, *, access_token, limit):
            self.list_calls += 1
            assert access_token == "access-token"
            assert limit == 200
            return [
                SimpleNamespace(
                    remote_urn="soundcloud:tracks:100",
                    remote_numeric_id=100,
                    remote_url="https://soundcloud.com/artist/remote",
                    title="Remote Upload",
                    genre="Electronic",
                    created_at="2026-05-28",
                    duration_ms=123000,
                )
            ]

        def fetch_track_metadata(self, *, access_token, remote_track_ref):
            assert access_token == "access-token"
            self.fetch_calls.append(remote_track_ref)
            return SimpleNamespace(
                remote_urn="soundcloud:tracks:123",
                remote_numeric_id=123,
                remote_url="https://soundcloud.com/artist/remote",
                title="Remote Title",
                description="Remote Description",
                genre="Ambient",
                tag_list="old tags",
                purchase_url="",
                metadata_artist="Remote Artist",
                release="Remote Release",
                label_name="Remote Label",
                release_date="",
                isrc="",
                publisher_metadata={
                    "publisher": "Remote Publisher",
                    "composer": "",
                    "album_title": "Remote Album",
                    "contains_music": False,
                    "explicit": True,
                },
            )

    client = _Client()
    app = SimpleNamespace(_soundcloud_token_store=_Store())
    app.settings = SimpleNamespace(
        value=lambda key, default=None, _type=None: {
            workflow.SOUNDCLOUD_CLIENT_ID_SETTING: "client-id"
        }.get(key, default)
    )
    monkeypatch.setattr(workflow, "_soundcloud_repository", lambda _app: _Repo())
    monkeypatch.setattr(workflow, "_soundcloud_oauth_service", lambda _app: _OAuth())
    monkeypatch.setattr(workflow, "_soundcloud_client", lambda _app: client)
    monkeypatch.setattr(
        workflow, "_soundcloud_token_store", lambda _app: app._soundcloud_token_store
    )

    choices = workflow.list_existing_soundcloud_uploads(app)
    plan = _plan(action=SoundCloudPlanAction.UPDATE, remote_urn="soundcloud:tracks:123")
    item = plan.items[0]
    assert item.metadata is not None
    plan = replace(
        plan,
        items=(
            replace(
                item,
                metadata=replace(item.metadata, composer="Catalog Composer"),
            ),
        ),
    )
    rows = workflow.build_soundcloud_metadata_comparison(app, plan)

    assert choices[0].title == "Remote Upload"
    assert choices[0].remote_numeric_id == 100
    assert client.fetch_calls == ["soundcloud:tracks:123"]
    assert any(row.field == "Title" and row.changed for row in rows)
    assert any(row.field == "Genre" and row.catalog_value == "" for row in rows)
    assert any(
        row.field == "Composer" and row.state == "Web-only/API not confirmed" for row in rows
    )


def test_workflow_existing_upload_and_comparison_error_edges(monkeypatch) -> None:
    account = SoundCloudAccountRecord(
        id=32,
        account_key="soundcloud:user:32",
        token_store_key="soundcloud:user:32",
        token_kind=SoundCloudTokenKind.SESSION,
        connection_status="connected",
    )

    class _Repo:
        def active_account(self):
            return account

    class _Store:
        def load_bundle(self, _key):
            return object()

        def load_client_secret(self, _client_id):
            return ""

    class _OAuth:
        def token_for_account(self, account_id, *, client_id=None, client_secret=None):
            assert account_id == 32
            assert client_id is None
            assert client_secret is None
            return "access-token"

    class _Client:
        def fetch_track_metadata(self, *, access_token, remote_track_ref):
            del access_token, remote_track_ref
            raise AssertionError("comparison should not fetch without update refs")

    app = SimpleNamespace(_soundcloud_token_store=_Store())
    monkeypatch.setattr(workflow, "_soundcloud_repository", lambda _app: None)
    with pytest.raises(RuntimeError, match="Open a profile"):
        workflow.list_existing_soundcloud_uploads(app)

    monkeypatch.setattr(workflow, "_soundcloud_repository", lambda _app: _Repo())
    monkeypatch.setattr(workflow, "_soundcloud_oauth_service", lambda _app: None)
    with pytest.raises(RuntimeError, match="OAuth service"):
        workflow.list_existing_soundcloud_uploads(app)

    monkeypatch.setattr(workflow, "_soundcloud_oauth_service", lambda _app: _OAuth())
    monkeypatch.setattr(workflow, "_soundcloud_client", lambda _app: _Client())
    monkeypatch.setattr(
        workflow, "_soundcloud_token_store", lambda _app: app._soundcloud_token_store
    )

    assert workflow._publisher_metadata_text(SimpleNamespace(publisher_metadata=[]), "x") == ""
    with pytest.raises(RuntimeError, match="No linked"):
        workflow.build_soundcloud_metadata_comparison(
            app,
            _plan(action=SoundCloudPlanAction.CREATE),
        )
