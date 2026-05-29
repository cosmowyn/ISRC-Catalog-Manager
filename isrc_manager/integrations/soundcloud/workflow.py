"""Application-facing SoundCloud UI workflow adapters."""

from __future__ import annotations

import base64
import binascii
import logging
import mimetypes
import sqlite3
import tempfile
import urllib.parse
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from .client import SoundCloudAPIClient, UrllibSoundCloudTransport, redact_text
from .execution import SoundCloudPublishExecutor
from .media import SoundCloudWatermarkedWavMediaPreparer
from .models import SoundCloudPlanAction, SoundCloudPublishPlanResult
from .oauth import (
    SoundCloudOAuthService,
    build_authorization_url,
    build_code_challenge,
    generate_pkce_verifier,
    generate_state,
)
from .oauth_capture import SoundCloudOAuthCallbackProvider
from .persistence import SoundCloudAccountRecord, SoundCloudSQLiteRepository
from .service import SoundCloudPublishPlanner
from .token_store import SoundCloudCredentialManager
from .ui import (
    SoundCloudCatalogTrackChoice,
    SoundCloudExistingUploadChoice,
    SoundCloudMetadataComparisonRow,
    SoundCloudPublishDialog,
    SoundCloudPublishRunSummary,
    SoundCloudSettingsSnapshot,
)

SOUNDCLOUD_CLIENT_ID_SETTING = "soundcloud/client_id"
SOUNDCLOUD_REDIRECT_URI_SETTING = "soundcloud/redirect_uri"
SOUNDCLOUD_PERSISTENT_TOKENS_SETTING = "soundcloud/prefer_persistent_tokens"
SOUNDCLOUD_SETTINGS_FOCUS = "soundcloud"
SOUNDCLOUD_RECONNECT_REQUIRED_MESSAGE = (
    "SoundCloud stored credentials are unavailable; reconnect SoundCloud from Settings before "
    "publishing."
)
LOGGER = logging.getLogger("ISRCManager.soundcloud")


def _setting_text(app: Any, key: str, default: str = "") -> str:
    settings = getattr(app, "settings", None)
    if settings is None:
        return default
    return str(settings.value(key, default, str) or "").strip()


def _setting_bool(app: Any, key: str, default: bool = True) -> bool:
    settings = getattr(app, "settings", None)
    if settings is None:
        return default
    raw = settings.value(key, default)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in {"0", "false", "no", "off", ""}


def _soundcloud_token_store(app: Any) -> SoundCloudCredentialManager:
    store = getattr(app, "_soundcloud_token_store", None)
    if store is None:
        store = SoundCloudCredentialManager.create_default()
        setattr(app, "_soundcloud_token_store", store)
    return store


def _soundcloud_repository(app: Any) -> SoundCloudSQLiteRepository | None:
    conn = getattr(app, "conn", None)
    if conn is None:
        return None
    return SoundCloudSQLiteRepository(conn)


def _soundcloud_client(app: Any) -> SoundCloudAPIClient:
    client = getattr(app, "_soundcloud_api_client", None)
    if client is None:
        client = SoundCloudAPIClient(transport=UrllibSoundCloudTransport())
        setattr(app, "_soundcloud_api_client", client)
    return client


def _soundcloud_oauth_service(app: Any) -> SoundCloudOAuthService | None:
    repository = _soundcloud_repository(app)
    if repository is None:
        return None
    service = getattr(app, "_soundcloud_oauth_service", None)
    if service is None:
        service = SoundCloudOAuthService(
            client=_soundcloud_client(app),
            token_store=_soundcloud_token_store(app),
            repository=repository,
        )
        setattr(app, "_soundcloud_oauth_service", service)
    return service


def _soundcloud_credentials_available(
    app: Any,
    account: SoundCloudAccountRecord | None,
) -> bool:
    if account is None or account.connection_status != "connected":
        return False
    try:
        return _soundcloud_token_store(app).load_bundle(account.token_store_key) is not None
    except Exception:
        return False


def _mark_soundcloud_credentials_unavailable(
    app: Any,
    repository: SoundCloudSQLiteRepository,
    account: SoundCloudAccountRecord,
) -> None:
    repository.mark_disconnected(account.id, error=SOUNDCLOUD_RECONNECT_REQUIRED_MESSAGE)
    conn = getattr(app, "conn", None)
    if conn is not None:
        conn.commit()


def _record_soundcloud_publish_failure(app: Any, failure: object) -> None:
    message = redact_text(str(getattr(failure, "message", "") or failure or "Publish failed."))
    traceback_text = redact_text(str(getattr(failure, "traceback_text", "") or ""))
    details: dict[str, object] = {"error": message}
    if traceback_text:
        details["traceback"] = traceback_text

    log_trace = getattr(app, "_log_trace", None)
    if callable(log_trace):
        log_trace(
            "soundcloud.publish.error",
            message="SoundCloud publish failed.",
            level=logging.ERROR,
            action="publish",
            entity="soundcloud_publish_run",
            status="failed",
            details=details,
        )
        return

    logging.getLogger("ISRCManager.trace").error(
        "SoundCloud publish failed.",
        extra={
            "event": "soundcloud.publish.error",
            "action": "publish",
            "entity": "soundcloud_publish_run",
            "status": "failed",
            "details": details,
        },
    )


def _open_soundcloud_latest_error_log(app: Any) -> object | None:
    opener = getattr(app, "open_application_log_dialog", None)
    if not callable(opener):
        return None
    try:
        return opener(prefer_trace=True, scroll_to_latest=True)
    except TypeError:
        return opener()


def soundcloud_settings_snapshot(app: Any) -> SoundCloudSettingsSnapshot:
    client_id = _setting_text(app, SOUNDCLOUD_CLIENT_ID_SETTING)
    redirect_uri = _setting_text(app, SOUNDCLOUD_REDIRECT_URI_SETTING)
    prefer_persistent = _setting_bool(app, SOUNDCLOUD_PERSISTENT_TOKENS_SETTING, True)
    store = _soundcloud_token_store(app)
    repository = _soundcloud_repository(app)
    try:
        account = repository.active_account() if repository is not None else None
    except Exception:
        account = None
    connected = account is not None and _soundcloud_credentials_available(app, account)
    account_label = "Disconnected"
    token_label = "Session-only"
    status_message = ""
    if account is not None:
        display = account.username or account.soundcloud_user_id or account.account_key
        account_label = (
            f"Connected as {display}"
            if connected
            else (
                f"Reconnect required: {display}"
                if account.connection_status == "connected"
                else f"Disconnected: {display}"
            )
        )
        token_label = (
            "Persistent OS keychain/keyring"
            if account.token_kind.value == "persistent"
            else "Session-only"
        )
        if account.connection_status == "connected" and not connected:
            status_message = SOUNDCLOUD_RECONNECT_REQUIRED_MESSAGE
    elif store.persistent_available:
        token_label = "Persistent OS keychain/keyring available"
    else:
        status_message = store.availability.reason
    return SoundCloudSettingsSnapshot(
        client_id=client_id,
        redirect_uri=redirect_uri,
        prefer_persistent_tokens=prefer_persistent,
        persistent_available=store.persistent_available,
        connected=connected,
        account_label=account_label,
        token_storage_label=token_label,
        status_message=status_message,
    )


class SoundCloudAppConnectionActions:
    """Application adapter that keeps OAuth details outside the settings tab."""

    def __init__(self, app: Any) -> None:
        self.app = app

    def snapshot(self) -> SoundCloudSettingsSnapshot:
        return soundcloud_settings_snapshot(self.app)

    def _client_secret(self, client_id: str) -> str:
        provider = getattr(self.app, "soundcloud_client_secret_provider", None)
        if callable(provider):
            secret = str(provider(client_id) or "")
        else:
            secret = str(_soundcloud_token_store(self.app).load_client_secret(client_id) or "")
        if not secret:
            raise RuntimeError(
                "SoundCloud client secret is unavailable; reconnect setup is required."
            )
        return secret

    def _oauth_service(self) -> SoundCloudOAuthService:
        service = _soundcloud_oauth_service(self.app)
        if service is None:
            raise RuntimeError("Open a profile before connecting SoundCloud.")
        return service

    def _minimize_for_oauth(self) -> dict[str, bool]:
        window = self.app
        state = {
            "minimized": False,
            "was_maximized": False,
        }
        try:
            is_maximized = getattr(window, "isMaximized", None)
            state["was_maximized"] = bool(is_maximized()) if callable(is_maximized) else False
            show_minimized = getattr(window, "showMinimized", None)
            if callable(show_minimized):
                show_minimized()
                state["minimized"] = True
        except Exception:
            state["minimized"] = False
        return state

    def _restore_after_oauth(self, state: dict[str, bool]) -> None:
        if not state.get("minimized"):
            return
        window = self.app
        try:
            if state.get("was_maximized") and callable(getattr(window, "showMaximized", None)):
                window.showMaximized()
            elif callable(getattr(window, "showNormal", None)):
                window.showNormal()
            elif callable(getattr(window, "show", None)):
                window.show()
            raise_window = getattr(window, "raise_", None)
            if callable(raise_window):
                raise_window()
            activate_window = getattr(window, "activateWindow", None)
            if callable(activate_window):
                activate_window()
        except Exception:
            return

    def connect(self, *, client_id: str, redirect_uri: str) -> SoundCloudSettingsSnapshot:
        client_id = client_id.strip()
        redirect_uri = redirect_uri.strip()
        if not client_id or not redirect_uri:
            raise RuntimeError("SoundCloud client id and redirect URI are required.")
        verifier = generate_pkce_verifier()
        state = generate_state()
        auth_url = build_authorization_url(
            "https://secure.soundcloud.com/authorize",
            client_id=client_id,
            redirect_uri=redirect_uri,
            scopes=None,
            code_challenge=build_code_challenge(verifier),
            state=state,
        )
        callback_provider = getattr(self.app, "soundcloud_authorization_callback_provider", None)
        window_state = self._minimize_for_oauth()
        try:
            if callable(callback_provider):
                callback_url = str(callback_provider(auth_url, state, redirect_uri) or "")
            else:
                callback_url = SoundCloudOAuthCallbackProvider(parent=self.app).capture(
                    auth_url=auth_url,
                    expected_state=state,
                    redirect_uri=redirect_uri,
                )
            service = self._oauth_service()
            service.complete_authorization_callback(
                callback_url=callback_url,
                expected_state=state,
                client_id=client_id,
                client_secret=self._client_secret(client_id),
                redirect_uri=redirect_uri,
                code_verifier=verifier,
            )
            conn = getattr(self.app, "conn", None)
            if conn is not None:
                conn.commit()
            snapshot = soundcloud_settings_snapshot(self.app)
            return replace(snapshot, status_message="SoundCloud account connected.")
        finally:
            self._restore_after_oauth(window_state)

    def refresh(self, *, client_id: str, redirect_uri: str) -> SoundCloudSettingsSnapshot:
        del redirect_uri
        repository = _soundcloud_repository(self.app)
        account = repository.active_account() if repository is not None else None
        if account is None:
            raise RuntimeError("SoundCloud account is not connected.")
        service = self._oauth_service()
        service.refresh_account(
            account.id,
            client_id=client_id.strip(),
            client_secret=self._client_secret(client_id.strip()),
        )
        conn = getattr(self.app, "conn", None)
        if conn is not None:
            conn.commit()
        snapshot = soundcloud_settings_snapshot(self.app)
        return replace(snapshot, status_message="SoundCloud connection refreshed.")

    def disconnect(self) -> SoundCloudSettingsSnapshot:
        repository = _soundcloud_repository(self.app)
        account = repository.active_account() if repository is not None else None
        if account is not None:
            self._oauth_service().disconnect_account(account.id)
            conn = getattr(self.app, "conn", None)
            if conn is not None:
                conn.commit()
        snapshot = soundcloud_settings_snapshot(self.app)
        return replace(snapshot, status_message="SoundCloud account disconnected.")

    def save_client_secret(
        self, *, client_id: str, client_secret: str
    ) -> SoundCloudSettingsSnapshot:
        client_id = client_id.strip()
        client_secret = str(client_secret or "")
        if not client_id or not client_secret:
            raise RuntimeError("SoundCloud client id and client secret are required.")
        kind = _soundcloud_token_store(self.app).save_client_secret(client_id, client_secret)
        snapshot = soundcloud_settings_snapshot(self.app)
        if kind.value == "persistent":
            message = "SoundCloud client secret stored in OS keychain/keyring."
        else:
            message = (
                "SoundCloud client secret stored for this session only; reconnect setup is "
                "required next session."
            )
        return replace(snapshot, status_message=message)


class _TrackSnapshotProvider:
    def __init__(
        self,
        track_service: Any,
        *,
        work_service: Any | None = None,
        owner_company_name: str | None = None,
    ) -> None:
        self.track_service = track_service
        self.work_service = work_service
        self.owner_company_name = str(owner_company_name or "").strip()

    def get_track_snapshot(self, track_id: int) -> dict[str, Any] | None:
        snapshot = self.track_service.fetch_track_snapshot(track_id, include_media_blobs=False)
        if snapshot is None:
            return None
        values = dict(snapshot.to_dict())
        self._enrich_from_linked_work(int(track_id), values)
        if self.owner_company_name:
            values["soundcloud_p_line"] = f"℗ {datetime.now().year} : {self.owner_company_name}"
            if not str(values.get("publisher") or "").strip():
                values["publisher"] = self.owner_company_name
        return values

    @staticmethod
    def _clean_unique_join(values: list[object]) -> str | None:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            key = text.casefold()
            if text and key not in seen:
                cleaned.append(text)
                seen.add(key)
        return ", ".join(cleaned) if cleaned else None

    def _linked_work_ids(self, track_id: int, values: dict[str, Any]) -> list[int]:
        work_ids: list[int] = []
        raw_work_id = values.get("work_id")
        try:
            if raw_work_id:
                work_ids.append(int(raw_work_id))
        except Exception:
            pass
        if work_ids or self.work_service is None:
            return work_ids
        list_works = getattr(self.work_service, "list_works_for_track", None)
        if not callable(list_works):
            return work_ids
        try:
            for work in list_works(int(track_id)):
                work_id = getattr(work, "id", None)
                if work_id is not None:
                    work_ids.append(int(work_id))
        except Exception:
            return work_ids
        return work_ids

    def _enrich_from_linked_work(self, track_id: int, values: dict[str, Any]) -> None:
        if self.work_service is None:
            return
        fetch_detail = getattr(self.work_service, "fetch_work_detail", None)
        if not callable(fetch_detail):
            return
        composer_names: list[object] = []
        publisher_names: list[object] = []
        for work_id in self._linked_work_ids(track_id, values):
            try:
                detail = fetch_detail(int(work_id))
            except Exception:
                continue
            if detail is None:
                continue
            work = getattr(detail, "work", None)
            if not str(values.get("iswc") or "").strip() and work is not None:
                iswc = getattr(work, "iswc", None)
                if iswc:
                    values["iswc"] = iswc
            for contributor in getattr(detail, "contributors", ()) or ():
                role = str(getattr(contributor, "role", "") or "").strip().lower()
                name = getattr(contributor, "display_name", None)
                if role in {"songwriter", "composer", "lyricist"}:
                    composer_names.append(name)
                elif role in {"publisher", "subpublisher"}:
                    publisher_names.append(name)
        if not str(values.get("composer") or "").strip():
            composer = self._clean_unique_join(composer_names)
            if composer:
                values["composer"] = composer
        if not str(values.get("publisher") or "").strip():
            publisher = self._clean_unique_join(publisher_names)
            if publisher:
                values["publisher"] = publisher


class _ReleaseSummaryProvider:
    def __init__(self, track_service: Any) -> None:
        self.track_service = track_service

    def get_release_summary(self, track_id: int) -> dict[str, Any] | None:
        snapshot = self.track_service.fetch_track_snapshot(track_id, include_media_blobs=False)
        if snapshot is None:
            return None
        values = snapshot.to_dict()
        release_title = str(values.get("album_title") or "").strip()
        release_date = str(values.get("release_date") or "").strip()
        label_name = str(values.get("publisher") or "").strip()
        if not release_title and not release_date and not label_name:
            return None
        return {
            "release_title": release_title or None,
            "release_date": release_date or None,
            "release_dates": [release_date] if release_date else [],
            "label_name": label_name or None,
            "label_names": [label_name] if label_name else [],
        }


@dataclass(slots=True)
class _SoundCloudStagedMediaHandle:
    filename: str
    mime_type: str | None
    size_bytes: int
    source_path: Path | None


class _MediaProvider:
    def __init__(self, track_service: Any) -> None:
        self.track_service = track_service
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None

    def _staging_root(self) -> Path:
        if self._temp_dir is None:
            self._temp_dir = tempfile.TemporaryDirectory(prefix="soundcloud-preflight-media-")
        return Path(self._temp_dir.name)

    def _stage_handle(self, track_id: int, media_key: str, handle: Any) -> Any:
        source_path = Path(getattr(handle, "source_path", "") or "")
        if source_path.exists() and source_path.is_file():
            return handle
        filename = str(getattr(handle, "filename", "") or "").strip()
        suffix = Path(filename).suffix
        if not suffix:
            guessed = mimetypes.guess_extension(str(getattr(handle, "mime_type", "") or ""))
            suffix = guessed or ".bin"
        staged_name = f"track-{int(track_id)}-{media_key}{suffix}"
        staged_path = self._staging_root() / staged_name
        materialize = getattr(handle, "materialize_path", None)
        if callable(materialize):
            with materialize() as materialized_path:
                staged_path.write_bytes(Path(materialized_path).read_bytes())
        else:
            data, _mime_type = self.track_service.fetch_media_bytes(track_id, media_key)
            staged_path.write_bytes(bytes(data))
        return _SoundCloudStagedMediaHandle(
            filename=filename or staged_name,
            mime_type=str(getattr(handle, "mime_type", "") or "").strip() or None,
            size_bytes=int(getattr(handle, "size_bytes", 0) or staged_path.stat().st_size),
            source_path=staged_path,
        )

    def _stage_bytes(
        self,
        track_id: int,
        media_key: str,
        *,
        filename: str,
        mime_type: str | None,
        data: bytes,
        size_bytes: int | None = None,
    ) -> _SoundCloudStagedMediaHandle:
        suffix = Path(filename).suffix
        if not suffix:
            guessed = mimetypes.guess_extension(str(mime_type or ""))
            suffix = guessed or ".bin"
        staged_name = f"track-{int(track_id)}-{media_key}{suffix}"
        staged_path = self._staging_root() / staged_name
        staged_path.write_bytes(bytes(data or b""))
        return _SoundCloudStagedMediaHandle(
            filename=filename or staged_name,
            mime_type=str(mime_type or "").strip() or None,
            size_bytes=int(size_bytes or len(data or b"")),
            source_path=staged_path,
        )

    def _snapshot_blob_handle(self, track_id: int, media_key: str) -> Any | None:
        fetch_snapshot = getattr(self.track_service, "fetch_track_snapshot", None)
        if not callable(fetch_snapshot):
            return None
        try:
            snapshot = fetch_snapshot(int(track_id), include_media_blobs=True)
        except Exception as exc:
            LOGGER.debug(
                "SoundCloud preflight snapshot media fallback failed: track_id=%s media_key=%s error=%s",
                int(track_id),
                media_key,
                type(exc).__name__,
            )
            return None
        if snapshot is None:
            return None

        prefix = "audio_file" if media_key == "audio_file" else "album_art"
        encoded = str(getattr(snapshot, f"{prefix}_blob_b64", "") or "").strip()
        if not encoded:
            return None
        try:
            data = base64.b64decode(encoded, validate=True)
        except binascii.Error, ValueError:
            try:
                data = base64.b64decode(encoded)
            except Exception:
                return None
        if not data:
            return None
        filename = str(getattr(snapshot, f"{prefix}_filename", "") or "").strip()
        mime_type = str(getattr(snapshot, f"{prefix}_mime_type", "") or "").strip() or None
        raw_size = getattr(snapshot, f"{prefix}_size_bytes", None)
        try:
            size_bytes = int(raw_size or len(data))
        except Exception:
            size_bytes = len(data)
        LOGGER.info(
            "SoundCloud preflight resolved embedded catalog media: track_id=%s media_key=%s size_bytes=%s",
            int(track_id),
            media_key,
            size_bytes,
            extra={
                "event": "soundcloud.preflight.media.embedded_resolved",
                "action": "preflight",
                "entity": "track",
                "entity_id": int(track_id),
                "details": {"media_key": media_key, "size_bytes": size_bytes},
            },
        )
        return self._stage_bytes(
            int(track_id),
            media_key,
            filename=filename,
            mime_type=mime_type,
            data=data,
            size_bytes=size_bytes,
        )

    def get_audio_handle(self, track_id: int) -> Any | None:
        try:
            return self._stage_handle(
                track_id,
                "audio_file",
                self.track_service.resolve_media_source(track_id, "audio_file"),
            )
        except FileNotFoundError:
            return self._snapshot_blob_handle(track_id, "audio_file")

    def get_effective_artwork_handle(self, track_id: int) -> tuple[Any | None, bool]:
        try:
            return (
                self._stage_handle(
                    track_id,
                    "album_art",
                    self.track_service.resolve_media_source(track_id, "album_art"),
                ),
                False,
            )
        except FileNotFoundError:
            return self._snapshot_blob_handle(track_id, "album_art"), False


class _PublicationLookup:
    def __init__(
        self,
        repository: SoundCloudSQLiteRepository | None,
    ) -> None:
        self.repository = repository

    def find_publication(self, track_id: int) -> dict[str, Any] | None:
        if self.repository is None:
            return None
        try:
            account = self.repository.active_account()
        except Exception:
            account = None
        account_id = account.id if account is not None else None
        publication = self.repository.find_publication(track_id, account_id=account_id)
        return dict(publication) if publication is not None else None


class _AccountState:
    def __init__(self, app: Any, repository: SoundCloudSQLiteRepository | None) -> None:
        self.app = app
        self.repository = repository

    def _active_account(self) -> SoundCloudAccountRecord | None:
        if self.repository is None:
            return None
        try:
            return self.repository.active_account()
        except Exception:
            return None

    def is_connected(self) -> bool:
        account = self._active_account()
        return _soundcloud_credentials_available(self.app, account)

    def get_quota_snapshot(self):
        account = self._active_account()
        if account is None:
            return None
        try:
            oauth_service = _soundcloud_oauth_service(self.app)
            if oauth_service is None:
                return None
            token = oauth_service.token_for_account(account.id)
            return _soundcloud_client(self.app).get_quota_snapshot(token)
        except Exception:
            return None


def _catalog_track_choices(app: Any) -> list[SoundCloudCatalogTrackChoice]:
    conn = getattr(app, "conn", None)
    if conn is None:
        return []
    try:
        from isrc_manager.services.track_artist_sql import track_main_artist_join_sql

        main_artist_join_sql, main_artist_name_expr = track_main_artist_join_sql(
            conn,
            track_alias="t",
            artist_alias="main_artist",
        )
        rows = conn.execute(f"""
            SELECT
                t.id,
                COALESCE(t.track_title, '') AS track_title,
                COALESCE(al.title, '') AS album_title,
                COALESCE({main_artist_name_expr}, '') AS artist_name,
                COALESCE(t.isrc, '') AS isrc,
                COALESCE(t.track_length_sec, 0) AS duration_seconds
            FROM Tracks t
            {main_artist_join_sql}
            LEFT JOIN Albums al ON al.id = t.album_id
            ORDER BY album_title COLLATE NOCASE, t.track_number, track_title COLLATE NOCASE
            """).fetchall()
    except Exception:
        return []
    return [
        SoundCloudCatalogTrackChoice(
            track_id=int(row[0]),
            title=str(row[1] or ""),
            album=str(row[2] or ""),
            artist=str(row[3] or ""),
            isrc=str(row[4] or ""),
            duration_seconds=int(row[5] or 0),
        )
        for row in rows
    ]


def _publish_history(app: Any) -> list[SoundCloudPublishRunSummary]:
    repository = _soundcloud_repository(app)
    if repository is None:
        return []
    try:
        recovered_runs = repository.mark_stale_in_progress_runs_failed()
        if recovered_runs:
            repository.conn.commit()
        rows = repository.list_publish_runs(limit=100)
    except Exception:
        return []
    return [
        SoundCloudPublishRunSummary(
            run_id=int(row.get("id") or 0),
            status=str(row.get("status") or ""),
            created_at=str(row.get("created_at") or ""),
            items_total=int(row.get("items_total") or 0),
            items_succeeded=int(row.get("items_succeeded") or 0),
            items_failed=int(row.get("items_failed") or 0),
            items_skipped=int(row.get("items_skipped") or 0),
        )
        for row in rows
    ]


def _client_secret_from_store(app: Any, client_id: str) -> str | None:
    store = _soundcloud_token_store(app)
    secret = str(store.load_client_secret(client_id) or "").strip()
    if secret:
        return secret
    provider = getattr(app, "soundcloud_client_secret_provider", None)
    if callable(provider):
        secret = str(provider(client_id) or "").strip()
        return secret or None
    return None


def _remote_numeric_id_from_urn(remote_urn: str | None) -> int | None:
    if not remote_urn:
        return None
    try:
        return int(str(remote_urn).rsplit(":", 1)[-1])
    except Exception:
        return None


def _looks_like_soundcloud_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _active_soundcloud_account_token(
    app: Any,
) -> tuple[SoundCloudSQLiteRepository, SoundCloudAccountRecord, str]:
    repository = _soundcloud_repository(app)
    if repository is None:
        raise RuntimeError("Open a profile before using SoundCloud.")
    account = repository.active_account()
    if account is None or not _soundcloud_credentials_available(app, account):
        raise RuntimeError("SoundCloud account is not connected.")
    oauth_service = _soundcloud_oauth_service(app)
    if oauth_service is None:
        raise RuntimeError("SoundCloud OAuth service is unavailable.")
    client_id = _setting_text(app, SOUNDCLOUD_CLIENT_ID_SETTING)
    client_secret = _client_secret_from_store(app, client_id) if client_id else None
    token = oauth_service.token_for_account(
        account.id,
        client_id=client_id or None,
        client_secret=client_secret,
    )
    return repository, account, token


def link_existing_soundcloud_upload(app: Any, track_id: int, remote_ref: str):
    """Link one catalog track to a SoundCloud upload that already exists online."""

    clean_ref = str(remote_ref or "").strip()
    if not clean_ref:
        raise RuntimeError("Paste a SoundCloud track URL, track id, or URN to link.")
    repository, account, token = _active_soundcloud_account_token(app)
    client = _soundcloud_client(app)
    if _looks_like_soundcloud_url(clean_ref):
        remote = client.resolve_track_url(access_token=token, track_url=clean_ref)
    else:
        remote = client.fetch_track_metadata(access_token=token, remote_track_ref=clean_ref)
    remote_numeric_id = remote.remote_numeric_id or _remote_numeric_id_from_urn(remote.remote_urn)
    publication_id = repository.link_publication(
        account_id=account.id,
        track_id=int(track_id),
        remote_urn=remote.remote_urn,
        remote_numeric_id=remote_numeric_id,
        remote_url=remote.remote_url,
    )
    conn = getattr(app, "conn", None)
    if conn is not None:
        conn.commit()
    LOGGER.info(
        "Linked catalog track to existing SoundCloud upload: track_id=%s publication_id=%s remote_urn=%s",
        int(track_id),
        publication_id,
        remote.remote_urn,
        extra={
            "event": "soundcloud.publication.linked",
            "action": "link",
            "entity": "soundcloud_track_publication",
            "entity_id": publication_id,
            "status": "linked",
            "details": {
                "track_id": int(track_id),
                "remote_urn": remote.remote_urn,
                "remote_numeric_id": remote_numeric_id,
            },
        },
    )
    return remote


def list_existing_soundcloud_uploads(app: Any) -> list[SoundCloudExistingUploadChoice]:
    """Return non-secret summaries of uploads owned by the connected SoundCloud account."""

    _repository, _account, token = _active_soundcloud_account_token(app)
    tracks = _soundcloud_client(app).list_my_tracks(access_token=token, limit=200)
    return [
        SoundCloudExistingUploadChoice(
            remote_urn=track.remote_urn,
            remote_numeric_id=track.remote_numeric_id,
            remote_url=track.remote_url,
            title=track.title or "",
            genre=track.genre or "",
            created_at=track.created_at or "",
            duration_ms=track.duration_ms,
        )
        for track in tracks
    ]


def _comparison_text(value: object | None) -> str:
    return str(value or "").strip()


def _publisher_metadata_text(remote: object, *keys: str) -> str:
    metadata = getattr(remote, "publisher_metadata", None)
    if not isinstance(metadata, dict):
        return ""
    for key in keys:
        value = metadata.get(key)
        if value not in (None, ""):
            return _comparison_text(value)
    return ""


def _metadata_comparison_row(
    field: str,
    catalog_value: object | None,
    remote_value: object | None,
    *,
    state: str | None = None,
) -> SoundCloudMetadataComparisonRow:
    catalog_text = _comparison_text(catalog_value)
    remote_text = _comparison_text(remote_value)
    return SoundCloudMetadataComparisonRow(
        field=field,
        catalog_value=catalog_text,
        remote_value=remote_text,
        changed=catalog_text != remote_text,
        state=state,
    )


def _rich_metadata_comparison_row(
    field: str,
    catalog_value: object | None,
    remote_value: object | None,
) -> SoundCloudMetadataComparisonRow:
    catalog_text = _comparison_text(catalog_value)
    remote_text = _comparison_text(remote_value)
    state = "Web-only/API not confirmed" if catalog_text and not remote_text else None
    return _metadata_comparison_row(field, catalog_text, remote_text, state=state)


def build_soundcloud_metadata_comparison(
    app: Any,
    plan: SoundCloudPublishPlanResult,
) -> list[SoundCloudMetadataComparisonRow]:
    """Fetch remote metadata and compare it with the current update plan."""

    _repository, _account, token = _active_soundcloud_account_token(app)
    client = _soundcloud_client(app)
    rows: list[SoundCloudMetadataComparisonRow] = []
    multi_track = len(plan.items) > 1
    for item in plan.items:
        if item.action != SoundCloudPlanAction.UPDATE or item.metadata is None:
            continue
        remote_ref = item.remote_urn or item.remote_numeric_id
        if remote_ref in (None, ""):
            continue
        remote = client.fetch_track_metadata(
            access_token=token,
            remote_track_ref=remote_ref,
        )
        metadata = item.metadata
        prefix = f"{item.title or f'Track {item.track_id}'} / " if multi_track else ""
        rows.extend(
            [
                _metadata_comparison_row(f"{prefix}Title", metadata.title, remote.title),
                _metadata_comparison_row(
                    f"{prefix}Description",
                    metadata.description,
                    remote.description,
                ),
                _metadata_comparison_row(f"{prefix}Genre", metadata.genre, remote.genre),
                _metadata_comparison_row(f"{prefix}Tags", plan.options.tag_list, remote.tag_list),
                _metadata_comparison_row(
                    f"{prefix}Buy link",
                    plan.options.purchase_url,
                    remote.purchase_url,
                ),
                _metadata_comparison_row(
                    f"{prefix}Artist",
                    metadata.metadata_artist,
                    remote.metadata_artist,
                ),
                _rich_metadata_comparison_row(
                    f"{prefix}Publisher",
                    metadata.publisher,
                    _publisher_metadata_text(remote, "publisher"),
                ),
                _rich_metadata_comparison_row(
                    f"{prefix}Composer",
                    metadata.composer,
                    _publisher_metadata_text(remote, "writer_composer", "composer"),
                ),
                _rich_metadata_comparison_row(
                    f"{prefix}Album title",
                    metadata.album_title,
                    _publisher_metadata_text(remote, "album_title"),
                ),
                _metadata_comparison_row(
                    f"{prefix}Release title", metadata.release, remote.release
                ),
                _metadata_comparison_row(
                    f"{prefix}Record label",
                    metadata.label_name,
                    remote.label_name,
                ),
                _metadata_comparison_row(
                    f"{prefix}Release date",
                    metadata.release_date,
                    remote.release_date,
                ),
                _metadata_comparison_row(f"{prefix}ISRC", metadata.isrc, remote.isrc),
                _rich_metadata_comparison_row(
                    f"{prefix}UPC/EAN",
                    metadata.upc_or_ean,
                    _publisher_metadata_text(remote, "upc_or_ean"),
                ),
                _rich_metadata_comparison_row(
                    f"{prefix}ISWC",
                    metadata.iswc,
                    _publisher_metadata_text(remote, "iswc"),
                ),
                _rich_metadata_comparison_row(
                    f"{prefix}P line",
                    metadata.p_line,
                    _publisher_metadata_text(remote, "p_line"),
                ),
                _rich_metadata_comparison_row(
                    f"{prefix}Contains music",
                    metadata.contains_music,
                    _publisher_metadata_text(remote, "contains_music"),
                ),
                _rich_metadata_comparison_row(
                    f"{prefix}Contains explicit",
                    metadata.contains_explicit,
                    _publisher_metadata_text(remote, "explicit"),
                ),
            ]
        )
    if not rows:
        raise RuntimeError("No linked SoundCloud update items are available for comparison.")
    return rows


def _selected_track_ids(app: Any) -> tuple[int, ...]:
    controller_factory = getattr(app, "_catalog_table_controller", None)
    if not callable(controller_factory):
        return ()
    controller = controller_factory()
    selected = getattr(controller, "selected_track_ids", None)
    if not callable(selected):
        return ()
    return tuple(int(track_id) for track_id in selected())


def _album_track_ids(app: Any, track_ids: tuple[int, ...]) -> list[int]:
    if not track_ids:
        return []
    track_service = getattr(app, "track_service", None)
    if track_service is None:
        return []
    try:
        return list(track_service.list_album_group_track_ids(track_ids[0]))
    except Exception:
        return []


def build_soundcloud_publish_planner(app: Any) -> SoundCloudPublishPlanner:
    track_service = getattr(app, "track_service", None)
    if track_service is None:
        raise RuntimeError("Catalog track service is unavailable.")
    repository = _soundcloud_repository(app)
    owner_company_name = ""
    owner_getter = getattr(app, "_current_owner_company_name", None)
    if callable(owner_getter):
        try:
            owner_company_name = str(owner_getter() or "").strip()
        except Exception:
            owner_company_name = ""
    return SoundCloudPublishPlanner(
        track_snapshot_provider=_TrackSnapshotProvider(
            track_service,
            work_service=getattr(app, "work_service", None),
            owner_company_name=owner_company_name,
        ),
        release_summary_provider=_ReleaseSummaryProvider(track_service),
        media_provider=_MediaProvider(track_service),
        publication_lookup=_PublicationLookup(repository),
        account_state=_AccountState(app, repository),
    )


def open_soundcloud_publish_dialog(app: Any, track_ids: list[int] | tuple[int, ...] | None = None):
    selected_ids = tuple(int(track_id) for track_id in (track_ids or _selected_track_ids(app)))
    planner = build_soundcloud_publish_planner(app)
    repository = _soundcloud_repository(app)

    dialog_holder: dict[str, SoundCloudPublishDialog] = {}

    def _publish_runner(plan: SoundCloudPublishPlanResult) -> object | None:
        if repository is None:
            raise RuntimeError("SoundCloud publish execution service is unavailable.")
        account = repository.active_account()
        if account is None:
            raise RuntimeError("SoundCloud account is not connected.")
        if not _soundcloud_credentials_available(app, account):
            _mark_soundcloud_credentials_unavailable(app, repository, account)
            raise RuntimeError(SOUNDCLOUD_RECONNECT_REQUIRED_MESSAGE)
        client_id = _setting_text(app, SOUNDCLOUD_CLIENT_ID_SETTING)
        client_secret = _client_secret_from_store(app, client_id)
        db_path = str(getattr(app, "current_db_path", "") or "").strip()

        profile_name = ""
        current_profile_name = getattr(app, "_current_profile_name", None)
        if callable(current_profile_name):
            try:
                profile_name = str(current_profile_name() or "")
            except Exception:
                profile_name = ""
        if not profile_name:
            profile_name = Path(db_path).stem if db_path else ""

        def _execute_with_services(
            *,
            conn: sqlite3.Connection,
            repository: SoundCloudSQLiteRepository,
            oauth_service: SoundCloudOAuthService,
            media_preparer: Any,
            ctx: Any,
        ):
            worker_executor = SoundCloudPublishExecutor(
                conn=conn,
                client=_soundcloud_client(app),
                oauth_service=oauth_service,
                repository=repository,
                media_preparer=media_preparer,
            )
            return worker_executor.execute_plan(
                plan,
                account_id=account.id,
                client_id=client_id or None,
                client_secret=client_secret,
                ctx=ctx,
            )

        def _bundle_task(bundle, ctx):
            worker_repository = SoundCloudSQLiteRepository(bundle.conn)
            worker_oauth_service = SoundCloudOAuthService(
                client=_soundcloud_client(app),
                token_store=_soundcloud_token_store(app),
                repository=worker_repository,
            )
            media_preparer = SoundCloudWatermarkedWavMediaPreparer(
                track_service=bundle.track_service,
                authenticity_service=bundle.audio_authenticity_service,
                profile_name=profile_name,
            )
            return _execute_with_services(
                conn=bundle.conn,
                repository=worker_repository,
                oauth_service=worker_oauth_service,
                media_preparer=media_preparer,
                ctx=ctx,
            )

        def _task(ctx):
            if db_path:
                raise RuntimeError(
                    "SoundCloud publish requires worker service bundle access for "
                    "watermarked WAV preparation."
                )

            conn = getattr(app, "conn", None)
            oauth_service = _soundcloud_oauth_service(app)
            if conn is None or oauth_service is None:
                raise RuntimeError("SoundCloud publish execution service is unavailable.")
            fallback_executor = SoundCloudPublishExecutor(
                conn=conn,
                client=_soundcloud_client(app),
                oauth_service=oauth_service,
                repository=repository,
                media_preparer=SoundCloudWatermarkedWavMediaPreparer(
                    track_service=getattr(app, "track_service", None),
                    authenticity_service=getattr(app, "audio_authenticity_service", None),
                    profile_name=profile_name,
                ),
            )
            return fallback_executor.execute_plan(
                plan,
                account_id=account.id,
                client_id=client_id or None,
                client_secret=client_secret,
                ctx=ctx,
            )

        dialog = dialog_holder.get("dialog")

        def _handle_error(failure: object) -> None:
            _record_soundcloud_publish_failure(app, failure)
            if dialog is not None:
                dialog.apply_execution_error(failure)

        bundle_submit = getattr(app, "_submit_background_bundle_task", None)
        if callable(bundle_submit):
            return bundle_submit(
                title="Publish to SoundCloud",
                description="Publishing selected catalog tracks to SoundCloud...",
                task_fn=_bundle_task,
                kind="write",
                requires_profile=True,
                show_dialog=True,
                cancellable=True,
                owner=dialog or app,
                on_success=dialog.apply_execution_result if dialog is not None else None,
                on_error=_handle_error,
            )

        submit = getattr(app, "_submit_background_task", None)
        if callable(submit):
            return submit(
                title="Publish to SoundCloud",
                description="Publishing selected catalog tracks to SoundCloud...",
                task_fn=_task,
                kind="write",
                requires_profile=True,
                show_dialog=True,
                cancellable=True,
                owner=dialog or app,
                on_success=dialog.apply_execution_result if dialog is not None else None,
                on_error=_handle_error,
            )
        result = _task(None)
        if dialog is not None:
            dialog.apply_execution_result(result)
        return result

    dialog = SoundCloudPublishDialog(
        track_ids=selected_ids,
        planner=planner,
        publish_runner=lambda plan: _safe_publish(_publish_runner, plan, dialog_holder, app),
        settings_opener=lambda: open_soundcloud_settings_dialog(app),
        album_track_resolver=lambda ids: _album_track_ids(app, ids),
        catalog_track_provider=lambda: _catalog_track_choices(app),
        history_provider=lambda: _publish_history(app),
        publication_linker=lambda track_id, remote_ref: link_existing_soundcloud_upload(
            app, track_id, remote_ref
        ),
        existing_upload_provider=lambda: list_existing_soundcloud_uploads(app),
        metadata_comparison_provider=lambda plan: build_soundcloud_metadata_comparison(app, plan),
        error_log_opener=lambda: _open_soundcloud_latest_error_log(app),
        parent=app,
    )
    dialog_holder["dialog"] = dialog
    return dialog.exec()


def _safe_publish(
    publish_runner,
    plan: SoundCloudPublishPlanResult,
    dialog_holder: dict[str, SoundCloudPublishDialog],
    app: Any,
) -> object | None:
    try:
        return publish_runner(plan)
    except Exception as exc:
        _record_soundcloud_publish_failure(app, exc)
        dialog = dialog_holder.get("dialog")
        if dialog is not None:
            dialog.apply_execution_error(Exception(redact_text(str(exc))))
        return None


def open_soundcloud_settings_dialog(app: Any):
    import isrc_manager.settings_controller as settings_controller

    return settings_controller.open_settings_dialog(app, initial_focus=SOUNDCLOUD_SETTINGS_FOCUS)


def soundcloud_media_path(handle: Any) -> str | None:
    source_path = getattr(handle, "source_path", None)
    if source_path:
        return str(Path(source_path))
    return None


__all__ = [
    "SOUNDCLOUD_CLIENT_ID_SETTING",
    "SOUNDCLOUD_PERSISTENT_TOKENS_SETTING",
    "SOUNDCLOUD_REDIRECT_URI_SETTING",
    "SOUNDCLOUD_SETTINGS_FOCUS",
    "SoundCloudAppConnectionActions",
    "build_soundcloud_metadata_comparison",
    "build_soundcloud_publish_planner",
    "link_existing_soundcloud_upload",
    "list_existing_soundcloud_uploads",
    "open_soundcloud_publish_dialog",
    "open_soundcloud_settings_dialog",
    "soundcloud_settings_snapshot",
]
