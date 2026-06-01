"""SQLite persistence for non-secret SoundCloud integration state."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .client import redact_text
from .models import (
    SoundCloudExecutionItemStatus,
    SoundCloudExecutionStatus,
    SoundCloudPlanAction,
    SoundCloudPublishPlanItem,
    SoundCloudPublishPlanResult,
    SoundCloudTokenKind,
)


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _text(value: object | None) -> str | None:
    clean = str(value or "").strip()
    return clean or None


def _row_dict(
    cursor: sqlite3.Cursor, row: sqlite3.Row | tuple[Any, ...] | None
) -> dict[str, Any] | None:
    if row is None:
        return None
    columns = [column[0] for column in cursor.description or ()]
    return dict(zip(columns, row))


@dataclass(frozen=True, slots=True)
class SoundCloudAccountRecord:
    id: int
    account_key: str
    token_store_key: str
    token_kind: SoundCloudTokenKind
    connection_status: str
    soundcloud_user_id: str | None = None
    username: str | None = None
    permalink_url: str | None = None
    avatar_url: str | None = None
    scope: str | None = None
    token_expires_at: str | None = None


class SoundCloudSQLiteRepository:
    """Stores SoundCloud account, publication, and publish-run state without secrets."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def _fetch_one(self, sql: str, params: tuple[object, ...]) -> dict[str, Any] | None:
        cursor = self.conn.execute(sql, params)
        return _row_dict(cursor, cursor.fetchone())

    def active_account(self) -> SoundCloudAccountRecord | None:
        row = self._fetch_one(
            """
            SELECT id, account_key, token_store_key, token_kind, connection_status,
                   soundcloud_user_id, username, permalink_url, avatar_url, scope,
                   token_expires_at
            FROM SoundCloudAccounts
            WHERE connection_status='connected'
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (),
        )
        return self._account_from_row(row)

    def account_by_id(self, account_id: int) -> SoundCloudAccountRecord | None:
        row = self._fetch_one(
            """
            SELECT id, account_key, token_store_key, token_kind, connection_status,
                   soundcloud_user_id, username, permalink_url, avatar_url, scope,
                   token_expires_at
            FROM SoundCloudAccounts
            WHERE id=?
            """,
            (int(account_id),),
        )
        return self._account_from_row(row)

    def _account_from_row(self, row: Mapping[str, Any] | None) -> SoundCloudAccountRecord | None:
        if row is None:
            return None
        return SoundCloudAccountRecord(
            id=int(row["id"]),
            account_key=str(row["account_key"]),
            token_store_key=str(row["token_store_key"]),
            token_kind=SoundCloudTokenKind(str(row["token_kind"] or SoundCloudTokenKind.SESSION)),
            connection_status=str(row["connection_status"] or ""),
            soundcloud_user_id=_text(row.get("soundcloud_user_id")),
            username=_text(row.get("username")),
            permalink_url=_text(row.get("permalink_url")),
            avatar_url=_text(row.get("avatar_url")),
            scope=_text(row.get("scope")),
            token_expires_at=_text(row.get("token_expires_at")),
        )

    def upsert_connected_account(
        self,
        *,
        account_key: str,
        token_store_key: str,
        token_kind: SoundCloudTokenKind,
        account_payload: Mapping[str, Any],
        scope: str | None,
        token_expires_at: str | None,
    ) -> int:
        soundcloud_user_id = _text(account_payload.get("id"))
        username = _text(account_payload.get("username") or account_payload.get("permalink"))
        permalink_url = _text(account_payload.get("permalink_url"))
        avatar_url = _text(account_payload.get("avatar_url"))
        self.conn.execute(
            """
            INSERT INTO SoundCloudAccounts(
                account_key,
                soundcloud_user_id,
                username,
                permalink_url,
                avatar_url,
                connection_status,
                token_store_key,
                token_kind,
                scope,
                token_expires_at,
                connected_at,
                disconnected_at,
                last_error,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'connected', ?, ?, ?, ?, datetime('now'), NULL, NULL, datetime('now'))
            ON CONFLICT(account_key) DO UPDATE SET
                soundcloud_user_id=excluded.soundcloud_user_id,
                username=excluded.username,
                permalink_url=excluded.permalink_url,
                avatar_url=excluded.avatar_url,
                connection_status='connected',
                token_store_key=excluded.token_store_key,
                token_kind=excluded.token_kind,
                scope=excluded.scope,
                token_expires_at=excluded.token_expires_at,
                connected_at=datetime('now'),
                disconnected_at=NULL,
                last_error=NULL,
                updated_at=datetime('now')
            """,
            (
                account_key,
                soundcloud_user_id,
                username,
                permalink_url,
                avatar_url,
                token_store_key,
                token_kind.value,
                scope,
                token_expires_at,
            ),
        )
        row = self._fetch_one(
            "SELECT id FROM SoundCloudAccounts WHERE account_key=?", (account_key,)
        )
        if row is None:
            raise RuntimeError("Connected SoundCloud account row could not be resolved.")
        return int(row["id"])

    def record_token_refresh(
        self,
        account_id: int,
        *,
        token_kind: SoundCloudTokenKind,
        scope: str | None,
        token_expires_at: str | None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE SoundCloudAccounts
            SET token_kind=?,
                scope=?,
                token_expires_at=?,
                last_token_refresh_at=datetime('now'),
                last_error=NULL,
                updated_at=datetime('now')
            WHERE id=?
            """,
            (token_kind.value, scope, token_expires_at, int(account_id)),
        )

    def mark_disconnected(self, account_id: int, *, error: str | None = None) -> None:
        self.conn.execute(
            """
            UPDATE SoundCloudAccounts
            SET connection_status='disconnected',
                disconnected_at=datetime('now'),
                last_error=?,
                updated_at=datetime('now')
            WHERE id=?
            """,
            (redact_text(error or "") or None, int(account_id)),
        )

    def create_publish_run(self, account_id: int, plan: SoundCloudPublishPlanResult) -> int:
        quota_json = (
            _json_dumps(asdict(plan.quota_snapshot)) if plan.quota_snapshot is not None else None
        )
        self.conn.execute(
            """
            INSERT INTO SoundCloudPublishRuns(
                account_id,
                status,
                requested_track_ids_json,
                options_json,
                quota_snapshot_json,
                items_total,
                started_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (
                int(account_id),
                SoundCloudExecutionStatus.CREATED.value,
                _json_dumps(list(plan.track_ids)),
                _json_dumps(asdict(plan.options)),
                quota_json,
                len(plan.items),
            ),
        )
        row = self._fetch_one("SELECT last_insert_rowid() AS id", ())
        return int(row["id"]) if row is not None else 0

    def create_run_item(self, run_id: int, item: SoundCloudPublishPlanItem) -> int:
        self.conn.execute(
            """
            INSERT INTO SoundCloudPublishRunItems(
                run_id,
                track_id,
                action,
                status,
                plan_status,
                remote_urn,
                remote_numeric_id,
                issues_json,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (
                int(run_id),
                int(item.track_id),
                item.action.value,
                SoundCloudExecutionItemStatus.PENDING.value,
                item.status.value,
                item.remote_urn,
                item.remote_numeric_id,
                _json_dumps(
                    [
                        {
                            "code": issue.code.value,
                            "severity": issue.severity.value,
                            "message": issue.message,
                            "detail": issue.detail,
                        }
                        for issue in item.issues
                    ]
                ),
            ),
        )
        row = self._fetch_one("SELECT last_insert_rowid() AS id", ())
        return int(row["id"]) if row is not None else 0

    def find_publication(
        self, track_id: int, *, account_id: int | None = None
    ) -> dict[str, Any] | None:
        """Return the latest non-secret publication state for a catalog track."""

        if account_id is None:
            return self._fetch_one(
                """
                SELECT id, account_id, track_id, remote_urn, remote_numeric_id,
                       remote_url, soundcloud_url,
                       last_operation, last_status, metadata_hash, audio_hash,
                       last_published_at, updated_at
                FROM SoundCloudTrackPublications
                WHERE track_id=?
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (int(track_id),),
            )
        return self._fetch_one(
            """
            SELECT id, account_id, track_id, remote_urn, remote_numeric_id,
                   remote_url, soundcloud_url,
                   last_operation, last_status, metadata_hash, audio_hash,
                   last_published_at, updated_at
            FROM SoundCloudTrackPublications
            WHERE track_id=? AND account_id=?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (int(track_id), int(account_id)),
        )

    def list_publish_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent publish runs without secret-bearing fields."""

        cursor = self.conn.execute(
            """
            SELECT id, account_id, status, items_total, items_succeeded, items_failed,
                   items_skipped, started_at, completed_at, cancelled_at, created_at, updated_at
            FROM SoundCloudPublishRuns
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 500)),),
        )
        columns = [column[0] for column in cursor.description or ()]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def mark_stale_in_progress_runs_failed(self, *, older_than_minutes: int = 30) -> int:
        """Recover abandoned publish runs that were left in progress by an earlier failure."""

        safe_minutes = max(1, int(older_than_minutes))
        safe_error = redact_text(
            "Publish run did not finish; marked failed after stale in-progress recovery."
        )
        cursor = self.conn.execute(
            """
            SELECT id
            FROM SoundCloudPublishRuns
            WHERE status=?
              AND datetime(updated_at) <= datetime('now', ?)
            ORDER BY id
            """,
            (
                SoundCloudExecutionStatus.IN_PROGRESS.value,
                f"-{safe_minutes} minutes",
            ),
        )
        run_ids = [int(row[0]) for row in cursor.fetchall()]
        for run_id in run_ids:
            self.conn.execute(
                """
                UPDATE SoundCloudPublishRunItems
                SET status=?,
                    operation_message=COALESCE(
                        operation_message,
                        'Publish run failed before this item completed.'
                    ),
                    redacted_error=?,
                    completed_at=COALESCE(completed_at, datetime('now')),
                    updated_at=datetime('now')
                WHERE run_id=?
                  AND status IN (?, ?)
                """,
                (
                    SoundCloudExecutionItemStatus.FAILED.value,
                    safe_error,
                    run_id,
                    SoundCloudExecutionItemStatus.PENDING.value,
                    SoundCloudExecutionItemStatus.IN_PROGRESS.value,
                ),
            )
            self.update_run_counts(run_id)
            self.mark_run_status(run_id, SoundCloudExecutionStatus.FAILED, error=safe_error)
        return len(run_ids)

    def mark_run_status(
        self,
        run_id: int,
        status: SoundCloudExecutionStatus,
        *,
        error: str | None = None,
    ) -> None:
        completed_sql = (
            ", completed_at=datetime('now')"
            if status
            in {
                SoundCloudExecutionStatus.COMPLETED,
                SoundCloudExecutionStatus.FAILED,
                SoundCloudExecutionStatus.CANCELLED,
            }
            else ""
        )
        cancelled_sql = (
            ", cancelled_at=datetime('now')"
            if status == SoundCloudExecutionStatus.CANCELLED
            else ""
        )
        self.conn.execute(
            f"""
            UPDATE SoundCloudPublishRuns
            SET status=?,
                redacted_error=?,
                updated_at=datetime('now')
                {completed_sql}
                {cancelled_sql}
            WHERE id=?
            """,
            (status.value, redact_text(error or "") or None, int(run_id)),
        )

    def update_run_counts(self, run_id: int) -> None:
        row = self._fetch_one(
            """
            SELECT
                SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS succeeded,
                SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN status IN ('skipped', 'cancelled') THEN 1 ELSE 0 END) AS skipped
            FROM SoundCloudPublishRunItems
            WHERE run_id=?
            """,
            (int(run_id),),
        )
        self.conn.execute(
            """
            UPDATE SoundCloudPublishRuns
            SET items_succeeded=?,
                items_failed=?,
                items_skipped=?,
                updated_at=datetime('now')
            WHERE id=?
            """,
            (
                int((row or {}).get("succeeded") or 0),
                int((row or {}).get("failed") or 0),
                int((row or {}).get("skipped") or 0),
                int(run_id),
            ),
        )

    def mark_item_started(self, item_id: int) -> None:
        self.conn.execute(
            """
            UPDATE SoundCloudPublishRunItems
            SET status=?,
                started_at=datetime('now'),
                updated_at=datetime('now')
            WHERE id=?
            """,
            (SoundCloudExecutionItemStatus.IN_PROGRESS.value, int(item_id)),
        )

    def finish_item(
        self,
        item_id: int,
        *,
        status: SoundCloudExecutionItemStatus,
        publication_id: int | None = None,
        remote_urn: str | None = None,
        remote_numeric_id: int | None = None,
        remote_url: str | None = None,
        metadata_hash: str | None = None,
        audio_hash: str | None = None,
        operation_message: str | None = None,
        error: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE SoundCloudPublishRunItems
            SET publication_id=?,
                status=?,
                remote_urn=?,
                remote_numeric_id=?,
                remote_url=?,
                soundcloud_url=?,
                metadata_hash=?,
                audio_hash=?,
                operation_message=?,
                redacted_error=?,
                completed_at=datetime('now'),
                updated_at=datetime('now')
            WHERE id=?
            """,
            (
                publication_id,
                status.value,
                remote_urn,
                remote_numeric_id,
                remote_url,
                remote_url,
                metadata_hash,
                audio_hash,
                operation_message,
                redact_text(error or "") or None,
                int(item_id),
            ),
        )

    def upsert_publication(
        self,
        *,
        account_id: int,
        track_id: int,
        action: SoundCloudPlanAction,
        remote_urn: str,
        remote_numeric_id: int | None,
        remote_url: str | None,
        metadata_hash: str | None,
        audio_hash: str | None,
    ) -> int:
        self.conn.execute(
            """
            INSERT INTO SoundCloudTrackPublications(
                account_id,
                track_id,
                remote_urn,
                remote_numeric_id,
                remote_url,
                soundcloud_url,
                last_operation,
                last_status,
                metadata_hash,
                audio_hash,
                last_published_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'success', ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(account_id, track_id) DO UPDATE SET
                remote_urn=excluded.remote_urn,
                remote_numeric_id=excluded.remote_numeric_id,
                remote_url=excluded.remote_url,
                soundcloud_url=excluded.soundcloud_url,
                last_operation=excluded.last_operation,
                last_status='success',
                metadata_hash=excluded.metadata_hash,
                audio_hash=excluded.audio_hash,
                last_published_at=datetime('now'),
                updated_at=datetime('now')
            """,
            (
                int(account_id),
                int(track_id),
                remote_urn,
                remote_numeric_id,
                remote_url,
                remote_url,
                action.value,
                metadata_hash,
                audio_hash,
            ),
        )
        row = self._fetch_one(
            """
            SELECT id
            FROM SoundCloudTrackPublications
            WHERE account_id=? AND track_id=?
            """,
            (int(account_id), int(track_id)),
        )
        if row is None:
            raise RuntimeError("SoundCloud publication row could not be resolved.")
        return int(row["id"])

    def link_publication(
        self,
        *,
        account_id: int,
        track_id: int,
        remote_urn: str,
        remote_numeric_id: int | None,
        remote_url: str | None,
    ) -> int:
        """Link a catalog track to a pre-existing SoundCloud upload."""

        self.conn.execute(
            """
            INSERT INTO SoundCloudTrackPublications(
                account_id,
                track_id,
                remote_urn,
                remote_numeric_id,
                remote_url,
                soundcloud_url,
                last_operation,
                last_status,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'link', 'linked', datetime('now'))
            ON CONFLICT(account_id, track_id) DO UPDATE SET
                remote_urn=excluded.remote_urn,
                remote_numeric_id=excluded.remote_numeric_id,
                remote_url=excluded.remote_url,
                soundcloud_url=excluded.soundcloud_url,
                last_operation='link',
                last_status='linked',
                updated_at=datetime('now')
            """,
            (
                int(account_id),
                int(track_id),
                remote_urn,
                remote_numeric_id,
                remote_url,
                remote_url,
            ),
        )
        row = self._fetch_one(
            """
            SELECT id
            FROM SoundCloudTrackPublications
            WHERE account_id=? AND track_id=?
            """,
            (int(account_id), int(track_id)),
        )
        if row is None:
            raise RuntimeError("Linked SoundCloud publication row could not be resolved.")
        return int(row["id"])


__all__ = [
    "SoundCloudAccountRecord",
    "SoundCloudSQLiteRepository",
]
