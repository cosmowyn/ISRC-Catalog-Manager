"""SoundCloud publish execution using dry-run planner output."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import asdict, replace
from pathlib import Path
from typing import Protocol

from isrc_manager.tasks.models import TaskCancelledError

from .client import (
    RICH_METADATA_SYNC_WARNING,
    RICH_METADATA_SYNC_WARNING_MESSAGE,
    SoundCloudAPIClient,
    SoundCloudAPIError,
    SoundCloudRemoteTrack,
    redact_text,
)
from .media import SoundCloudPreparedUploadMedia, SoundCloudUploadMediaError
from .models import (
    SoundCloudExecutionItemStatus,
    SoundCloudExecutionStatus,
    SoundCloudPlanAction,
    SoundCloudPlanItemStatus,
    SoundCloudPublishExecutionItemResult,
    SoundCloudPublishExecutionResult,
    SoundCloudPublishPlanItem,
    SoundCloudPublishPlanResult,
    SoundCloudTrackMetadataPayload,
)
from .oauth import SoundCloudOAuthService
from .persistence import SoundCloudSQLiteRepository

LOGGER = logging.getLogger("ISRCManager.soundcloud")
RICH_METADATA_OPERATION_MESSAGE = (
    "SoundCloud public update completed; rich web-editor metadata was rejected by the API."
)


class SoundCloudCancellationContext(Protocol):
    def is_cancelled(self) -> bool: ...

    def raise_if_cancelled(self) -> None: ...

    def report_progress(
        self,
        value: int | None = None,
        maximum: int | None = None,
        message: str | None = None,
    ) -> None: ...

    def set_status(self, message: str) -> None: ...


class SoundCloudUploadMediaPreparer(Protocol):
    def prepare_upload_media(
        self,
        track_id: int,
        *,
        include_artwork: bool,
    ) -> SoundCloudPreparedUploadMedia: ...


def _json_hash(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _file_hash(path_text: str | None) -> str | None:
    if not path_text:
        return None
    path = Path(path_text)
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata_mapping(metadata: SoundCloudTrackMetadataPayload) -> dict[str, object]:
    return {
        key: value
        for key, value in asdict(metadata).items()
        if key != "track_id" and value is not None and value != ""
    }


def _remote_id_from_urn(remote_urn: str | None) -> int | None:
    if not remote_urn:
        return None
    tail = str(remote_urn).rsplit(":", 1)[-1]
    try:
        return int(tail)
    except Exception:
        return None


def _remote_track_ref(remote_urn: str | None, remote_numeric_id: int | None) -> str | int | None:
    if remote_urn:
        return remote_urn
    if remote_numeric_id is not None:
        return int(remote_numeric_id)
    return None


class SoundCloudPublishExecutor:
    """Executes ready SoundCloud publish plan items and persists run state."""

    def __init__(
        self,
        *,
        conn: sqlite3.Connection,
        client: SoundCloudAPIClient,
        oauth_service: SoundCloudOAuthService,
        repository: SoundCloudSQLiteRepository | None = None,
        media_preparer: SoundCloudUploadMediaPreparer | None = None,
    ) -> None:
        self.conn = conn
        self.client = client
        self.oauth_service = oauth_service
        self.repository = repository or SoundCloudSQLiteRepository(conn)
        self.media_preparer = media_preparer

    def execute_plan(
        self,
        plan: SoundCloudPublishPlanResult,
        *,
        account_id: int,
        client_id: str | None = None,
        client_secret: str | None = None,
        ctx: SoundCloudCancellationContext | None = None,
    ) -> SoundCloudPublishExecutionResult:
        run_id = self.repository.create_publish_run(account_id, plan)
        item_ids = [self.repository.create_run_item(run_id, item) for item in plan.items]
        self.repository.mark_run_status(run_id, SoundCloudExecutionStatus.IN_PROGRESS)
        self.conn.commit()
        blocked_items = sum(
            1 for item in plan.items if item.status == SoundCloudPlanItemStatus.BLOCKED
        )
        warning_items = sum(
            1 for item in plan.items if item.status == SoundCloudPlanItemStatus.WARN
        )
        LOGGER.info(
            "SoundCloud publish run started: run_id=%s account_id=%s items_total=%s blocked_items=%s warnings=%s",
            run_id,
            account_id,
            len(plan.items),
            blocked_items,
            warning_items,
            extra={
                "event": "soundcloud.publish.run.started",
                "action": "publish",
                "entity": "soundcloud_publish_run",
                "entity_id": run_id,
                "status": SoundCloudExecutionStatus.IN_PROGRESS.value,
                "details": {
                    "account_id": account_id,
                    "items_total": len(plan.items),
                    "blocked_items": blocked_items,
                    "warnings": warning_items,
                },
            },
        )

        results: list[SoundCloudPublishExecutionItemResult] = []
        try:
            access_token = self.oauth_service.token_for_account(
                account_id,
                client_id=client_id,
                client_secret=client_secret,
            )
            for index, (item_id, item) in enumerate(zip(item_ids, plan.items), start=1):
                if ctx is not None:
                    ctx.raise_if_cancelled()
                    ctx.set_status(f"Publishing SoundCloud item {index} of {len(plan.items)}...")
                    ctx.report_progress(
                        value=index - 1,
                        maximum=max(len(plan.items), 1),
                        message=f"Preparing track {item.track_id}",
                    )
                result = self._execute_item(
                    item_id,
                    item,
                    account_id=account_id,
                    access_token=access_token,
                    plan=plan,
                    ctx=ctx,
                )
                results.append(result)
                self.repository.update_run_counts(run_id)
                self.conn.commit()
        except TaskCancelledError as exc:
            safe_error = redact_text(str(exc))
            LOGGER.warning(
                "SoundCloud publish run cancelled: run_id=%s account_id=%s completed_items=%s error=%s",
                run_id,
                account_id,
                len(results),
                safe_error,
                extra={
                    "event": "soundcloud.publish.run.cancelled",
                    "action": "publish",
                    "entity": "soundcloud_publish_run",
                    "entity_id": run_id,
                    "status": SoundCloudExecutionStatus.CANCELLED.value,
                    "details": {"completed_items": len(results), "error": safe_error},
                },
            )
            for pending_item_id, pending_item in zip(
                item_ids[len(results) :], plan.items[len(results) :]
            ):
                self.repository.finish_item(
                    pending_item_id,
                    status=SoundCloudExecutionItemStatus.CANCELLED,
                    operation_message="Publish item cancelled before execution.",
                    error=safe_error,
                )
                results.append(
                    SoundCloudPublishExecutionItemResult(
                        track_id=pending_item.track_id,
                        status=SoundCloudExecutionItemStatus.CANCELLED,
                        action=pending_item.action,
                        error=safe_error,
                    )
                )
            self.repository.update_run_counts(run_id)
            self.repository.mark_run_status(
                run_id, SoundCloudExecutionStatus.CANCELLED, error=safe_error
            )
            self.conn.commit()
            return self._result(run_id, SoundCloudExecutionStatus.CANCELLED, results)
        except Exception as exc:
            safe_error = redact_text(str(exc))
            LOGGER.error(
                "SoundCloud publish run failed: run_id=%s account_id=%s completed_items=%s error=%s",
                run_id,
                account_id,
                len(results),
                safe_error,
                extra={
                    "event": "soundcloud.publish.run.failed",
                    "action": "publish",
                    "entity": "soundcloud_publish_run",
                    "entity_id": run_id,
                    "status": SoundCloudExecutionStatus.FAILED.value,
                    "details": {"completed_items": len(results), "error": safe_error},
                },
            )
            for pending_item_id, pending_item in zip(
                item_ids[len(results) :], plan.items[len(results) :]
            ):
                self.repository.finish_item(
                    pending_item_id,
                    status=SoundCloudExecutionItemStatus.FAILED,
                    operation_message="Publish run failed before this item completed.",
                    error=safe_error,
                )
                results.append(
                    SoundCloudPublishExecutionItemResult(
                        track_id=pending_item.track_id,
                        status=SoundCloudExecutionItemStatus.FAILED,
                        action=pending_item.action,
                        error=safe_error,
                    )
                )
            self.repository.update_run_counts(run_id)
            self.repository.mark_run_status(
                run_id, SoundCloudExecutionStatus.FAILED, error=safe_error
            )
            self.conn.commit()
            raise

        status = (
            SoundCloudExecutionStatus.FAILED
            if any(result.status == SoundCloudExecutionItemStatus.FAILED for result in results)
            else SoundCloudExecutionStatus.COMPLETED
        )
        self.repository.update_run_counts(run_id)
        self.repository.mark_run_status(run_id, status)
        self.conn.commit()
        LOGGER.info(
            "SoundCloud publish run completed: run_id=%s account_id=%s status=%s succeeded=%s failed=%s skipped=%s",
            run_id,
            account_id,
            status.value,
            sum(1 for result in results if result.status == SoundCloudExecutionItemStatus.SUCCESS),
            sum(1 for result in results if result.status == SoundCloudExecutionItemStatus.FAILED),
            sum(
                1
                for result in results
                if result.status
                in {SoundCloudExecutionItemStatus.SKIPPED, SoundCloudExecutionItemStatus.CANCELLED}
            ),
            extra={
                "event": "soundcloud.publish.run.completed",
                "action": "publish",
                "entity": "soundcloud_publish_run",
                "entity_id": run_id,
                "status": status.value,
                "details": {
                    "account_id": account_id,
                    "items_total": len(results),
                    "items_succeeded": sum(
                        1
                        for result in results
                        if result.status == SoundCloudExecutionItemStatus.SUCCESS
                    ),
                    "items_failed": sum(
                        1
                        for result in results
                        if result.status == SoundCloudExecutionItemStatus.FAILED
                    ),
                    "items_skipped": sum(
                        1
                        for result in results
                        if result.status
                        in {
                            SoundCloudExecutionItemStatus.SKIPPED,
                            SoundCloudExecutionItemStatus.CANCELLED,
                        }
                    ),
                },
            },
        )
        if ctx is not None:
            ctx.report_progress(
                value=len(plan.items),
                maximum=max(len(plan.items), 1),
                message="SoundCloud publish execution complete.",
            )
        return self._result(run_id, status, results)

    def _execute_item(
        self,
        item_id: int,
        item: SoundCloudPublishPlanItem,
        *,
        account_id: int,
        access_token: str,
        plan: SoundCloudPublishPlanResult,
        ctx: SoundCloudCancellationContext | None,
    ) -> SoundCloudPublishExecutionItemResult:
        if item.status == SoundCloudPlanItemStatus.BLOCKED or item.metadata is None:
            self.repository.finish_item(
                item_id,
                status=SoundCloudExecutionItemStatus.SKIPPED,
                operation_message="Preflight blocked this item.",
            )
            LOGGER.info(
                "SoundCloud publish item skipped by preflight: item_id=%s track_id=%s action=%s",
                item_id,
                item.track_id,
                item.action.value,
                extra={
                    "event": "soundcloud.publish.item.skipped",
                    "action": item.action.value,
                    "entity": "soundcloud_publish_run_item",
                    "entity_id": item_id,
                    "status": SoundCloudExecutionItemStatus.SKIPPED.value,
                    "details": {"track_id": item.track_id, "reason": "preflight_blocked"},
                },
            )
            return SoundCloudPublishExecutionItemResult(
                track_id=item.track_id,
                status=SoundCloudExecutionItemStatus.SKIPPED,
                action=item.action,
                operation_message="Preflight blocked this item.",
            )

        active_metadata = item.metadata
        assert active_metadata is not None
        metadata_mapping = _metadata_mapping(active_metadata)
        metadata_hash = _json_hash(metadata_mapping)
        audio_hash = _file_hash(active_metadata.asset_data)
        prepared_media: SoundCloudPreparedUploadMedia | None = None
        self.repository.mark_item_started(item_id)
        self.conn.commit()
        LOGGER.info(
            "SoundCloud publish item started: item_id=%s track_id=%s action=%s",
            item_id,
            item.track_id,
            item.action.value,
            extra={
                "event": "soundcloud.publish.item.started",
                "action": item.action.value,
                "entity": "soundcloud_publish_run_item",
                "entity_id": item_id,
                "status": SoundCloudExecutionItemStatus.IN_PROGRESS.value,
                "details": {"track_id": item.track_id},
            },
        )
        try:
            if ctx is not None:
                ctx.raise_if_cancelled()
            if item.action == SoundCloudPlanAction.CREATE:
                if self.media_preparer is None:
                    raise SoundCloudUploadMediaError(
                        "SoundCloud create uploads require a watermarked WAV media preparer."
                    )
                if ctx is not None:
                    ctx.set_status(f"Preparing watermarked WAV for {item.title}...")
                    ctx.report_progress(message=f"Preparing watermarked WAV for {item.title}")
                prepared_media = self.media_preparer.prepare_upload_media(
                    item.track_id,
                    include_artwork=bool(active_metadata.artwork_data),
                )
                active_metadata = replace(
                    active_metadata,
                    asset_data=str(prepared_media.audio_path),
                    artwork_data=(
                        str(prepared_media.artwork_path)
                        if prepared_media.artwork_path is not None
                        else None
                    ),
                )
                metadata_mapping = _metadata_mapping(active_metadata)
                metadata_hash = _json_hash(metadata_mapping)
                audio_hash = prepared_media.audio_sha256
                remote = self.client.upload_track(
                    access_token=access_token,
                    metadata=metadata_mapping,
                    options=plan.options,
                )
                remote = self._refresh_remote_after_write(access_token, remote)
            elif item.action == SoundCloudPlanAction.UPDATE:
                remote_numeric_id = _remote_id_from_urn(item.remote_urn) or item.remote_numeric_id
                fetched_url: str | None = None
                fetched_ref = _remote_track_ref(item.remote_urn, remote_numeric_id)
                fetch_track_metadata = getattr(self.client, "fetch_track_metadata", None)
                if fetched_ref is not None and callable(fetch_track_metadata):
                    remote_snapshot = fetch_track_metadata(
                        access_token=access_token,
                        remote_track_ref=fetched_ref,
                    )
                    remote_numeric_id = (
                        remote_snapshot.remote_numeric_id
                        or _remote_id_from_urn(remote_snapshot.remote_urn)
                        or remote_numeric_id
                    )
                    fetched_url = remote_snapshot.remote_url
                    LOGGER.info(
                        "SoundCloud remote metadata fetched before update: item_id=%s track_id=%s remote_urn=%s",
                        item_id,
                        item.track_id,
                        remote_snapshot.remote_urn,
                        extra={
                            "event": "soundcloud.publish.remote_metadata.fetched",
                            "action": item.action.value,
                            "entity": "soundcloud_publish_run_item",
                            "entity_id": item_id,
                            "status": "remote_metadata_fetched",
                            "details": {
                                "track_id": item.track_id,
                                "remote_urn": remote_snapshot.remote_urn,
                                "remote_numeric_id": remote_snapshot.remote_numeric_id,
                            },
                        },
                    )
                if remote_numeric_id is None:
                    raise ValueError("Existing SoundCloud publication has no updateable track id.")
                remote = self.client.update_track_metadata(
                    access_token=access_token,
                    remote_numeric_id=remote_numeric_id,
                    metadata=metadata_mapping,
                    options=plan.options,
                )
                if remote.remote_url is None and fetched_url:
                    remote = replace(remote, remote_url=fetched_url)
            else:
                self.repository.finish_item(
                    item_id,
                    status=SoundCloudExecutionItemStatus.SKIPPED,
                    operation_message="Publish action is skip.",
                    metadata_hash=metadata_hash,
                    audio_hash=audio_hash,
                )
                LOGGER.info(
                    "SoundCloud publish item skipped: item_id=%s track_id=%s action=%s",
                    item_id,
                    item.track_id,
                    item.action.value,
                    extra={
                        "event": "soundcloud.publish.item.skipped",
                        "action": item.action.value,
                        "entity": "soundcloud_publish_run_item",
                        "entity_id": item_id,
                        "status": SoundCloudExecutionItemStatus.SKIPPED.value,
                        "details": {"track_id": item.track_id, "reason": "skip_action"},
                    },
                )
                return SoundCloudPublishExecutionItemResult(
                    track_id=item.track_id,
                    status=SoundCloudExecutionItemStatus.SKIPPED,
                    action=item.action,
                    metadata_hash=metadata_hash,
                    audio_hash=audio_hash,
                    operation_message="Publish action is skip.",
                )
            publication_id = self.repository.upsert_publication(
                account_id=account_id,
                track_id=item.track_id,
                action=item.action,
                remote_urn=remote.remote_urn,
                remote_numeric_id=remote.remote_numeric_id,
                remote_url=remote.remote_url,
                metadata_hash=metadata_hash,
                audio_hash=audio_hash,
            )
            rich_metadata_rejected = (
                remote.raw.get("rich_metadata_sync_status") == RICH_METADATA_SYNC_WARNING
            )
            operation_message = (
                RICH_METADATA_OPERATION_MESSAGE
                if rich_metadata_rejected
                else f"SoundCloud {item.action.value} completed."
            )
            self.repository.finish_item(
                item_id,
                status=SoundCloudExecutionItemStatus.SUCCESS,
                publication_id=publication_id,
                remote_urn=remote.remote_urn,
                remote_numeric_id=remote.remote_numeric_id,
                remote_url=remote.remote_url,
                metadata_hash=metadata_hash,
                audio_hash=audio_hash,
                operation_message=operation_message,
            )
            if rich_metadata_rejected:
                LOGGER.warning(
                    "SoundCloud publish item completed with rich metadata warning: item_id=%s track_id=%s action=%s warning=%s",
                    item_id,
                    item.track_id,
                    item.action.value,
                    RICH_METADATA_SYNC_WARNING_MESSAGE,
                    extra={
                        "event": "soundcloud.publish.item.rich_metadata_warning",
                        "action": item.action.value,
                        "entity": "soundcloud_publish_run_item",
                        "entity_id": item_id,
                        "status": SoundCloudExecutionItemStatus.SUCCESS.value,
                        "details": {
                            "track_id": item.track_id,
                            "warning": RICH_METADATA_SYNC_WARNING_MESSAGE,
                        },
                    },
                )
            LOGGER.info(
                "SoundCloud publish item completed: item_id=%s track_id=%s action=%s remote_urn=%s",
                item_id,
                item.track_id,
                item.action.value,
                remote.remote_urn,
                extra={
                    "event": "soundcloud.publish.item.completed",
                    "action": item.action.value,
                    "entity": "soundcloud_publish_run_item",
                    "entity_id": item_id,
                    "status": SoundCloudExecutionItemStatus.SUCCESS.value,
                    "details": {
                        "track_id": item.track_id,
                        "remote_urn": remote.remote_urn,
                        "remote_numeric_id": remote.remote_numeric_id,
                    },
                },
            )
            return SoundCloudPublishExecutionItemResult(
                track_id=item.track_id,
                status=SoundCloudExecutionItemStatus.SUCCESS,
                action=item.action,
                operation_message=operation_message,
                remote_urn=remote.remote_urn,
                remote_numeric_id=remote.remote_numeric_id,
                remote_url=remote.remote_url,
                metadata_hash=metadata_hash,
                audio_hash=audio_hash,
            )
        except TaskCancelledError as exc:
            error = redact_text(str(exc))
            self.repository.finish_item(
                item_id,
                status=SoundCloudExecutionItemStatus.CANCELLED,
                metadata_hash=metadata_hash,
                audio_hash=audio_hash,
                error=error,
            )
            LOGGER.warning(
                "SoundCloud publish item cancelled: item_id=%s track_id=%s action=%s error=%s",
                item_id,
                item.track_id,
                item.action.value,
                error,
                extra={
                    "event": "soundcloud.publish.item.cancelled",
                    "action": item.action.value,
                    "entity": "soundcloud_publish_run_item",
                    "entity_id": item_id,
                    "status": SoundCloudExecutionItemStatus.CANCELLED.value,
                    "details": {"track_id": item.track_id, "error": error},
                },
            )
            return SoundCloudPublishExecutionItemResult(
                track_id=item.track_id,
                status=SoundCloudExecutionItemStatus.CANCELLED,
                action=item.action,
                metadata_hash=metadata_hash,
                audio_hash=audio_hash,
                error=error,
            )
        except (SoundCloudAPIError, ValueError, RuntimeError) as exc:
            error = redact_text(str(exc))
            self.repository.finish_item(
                item_id,
                status=SoundCloudExecutionItemStatus.FAILED,
                metadata_hash=metadata_hash,
                audio_hash=audio_hash,
                error=error,
            )
            LOGGER.warning(
                "SoundCloud publish item failed: item_id=%s track_id=%s action=%s error=%s",
                item_id,
                item.track_id,
                item.action.value,
                error,
                extra={
                    "event": "soundcloud.publish.item.failed",
                    "action": item.action.value,
                    "entity": "soundcloud_publish_run_item",
                    "entity_id": item_id,
                    "status": SoundCloudExecutionItemStatus.FAILED.value,
                    "details": {"track_id": item.track_id, "error": error},
                },
            )
            return SoundCloudPublishExecutionItemResult(
                track_id=item.track_id,
                status=SoundCloudExecutionItemStatus.FAILED,
                action=item.action,
                metadata_hash=metadata_hash,
                audio_hash=audio_hash,
                error=error,
            )
        finally:
            if prepared_media is not None:
                prepared_media.cleanup()

    def _refresh_remote_after_write(
        self,
        access_token: str,
        remote: SoundCloudRemoteTrack,
    ) -> SoundCloudRemoteTrack:
        fetch_track_metadata = getattr(self.client, "fetch_track_metadata", None)
        if not callable(fetch_track_metadata):
            return remote
        remote_ref = _remote_track_ref(remote.remote_urn, remote.remote_numeric_id)
        if remote_ref is None:
            return remote
        try:
            snapshot = fetch_track_metadata(
                access_token=access_token,
                remote_track_ref=remote_ref,
            )
        except SoundCloudAPIError as exc:
            LOGGER.info(
                "SoundCloud remote metadata refresh skipped after write: remote_urn=%s error=%s",
                remote.remote_urn,
                redact_text(str(exc)),
                extra={
                    "event": "soundcloud.publish.remote_metadata.refresh_skipped",
                    "action": "remote_metadata_refresh",
                    "entity": "soundcloud_track",
                    "status": "skipped",
                    "details": {"remote_urn": remote.remote_urn},
                },
            )
            return remote
        if remote.remote_url is None and snapshot.remote_url:
            return replace(remote, remote_url=snapshot.remote_url)
        return remote

    def _result(
        self,
        run_id: int,
        status: SoundCloudExecutionStatus,
        results: list[SoundCloudPublishExecutionItemResult],
    ) -> SoundCloudPublishExecutionResult:
        return SoundCloudPublishExecutionResult(
            run_id=run_id,
            status=status,
            items_total=len(results),
            items_succeeded=sum(
                1 for item in results if item.status == SoundCloudExecutionItemStatus.SUCCESS
            ),
            items_failed=sum(
                1 for item in results if item.status == SoundCloudExecutionItemStatus.FAILED
            ),
            items_skipped=sum(
                1
                for item in results
                if item.status
                in {SoundCloudExecutionItemStatus.SKIPPED, SoundCloudExecutionItemStatus.CANCELLED}
            ),
            item_results=tuple(results),
        )


__all__ = ["SoundCloudCancellationContext", "SoundCloudPublishExecutor"]
