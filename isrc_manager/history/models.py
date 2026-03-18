"""Dataclasses for persistent history and snapshots."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class HistoryEntry:
    entry_id: int
    parent_id: int | None
    created_at: str
    label: str
    action_type: str
    entity_type: str | None
    entity_id: str | None
    reversible: bool
    strategy: str
    payload: dict
    inverse_payload: dict | None
    redo_payload: dict | None
    snapshot_before_id: int | None
    snapshot_after_id: int | None
    status: str
    visible_in_history: bool = True
    is_current: bool = False


@dataclass(slots=True)
class SnapshotRecord:
    snapshot_id: int
    created_at: str
    kind: str
    label: str
    db_snapshot_path: str
    settings_state: dict
    manifest: dict


@dataclass(slots=True)
class BackupRecord:
    backup_id: int
    created_at: str
    kind: str
    label: str
    backup_path: str
    source_db_path: str | None
    metadata: dict


@dataclass(slots=True)
class HistoryIssue:
    issue_type: str
    severity: str
    message: str
    path: str | None = None
    snapshot_id: int | None = None
    backup_id: int | None = None
    entry_id: int | None = None
    details: dict | None = None


@dataclass(slots=True)
class HistoryRepairResult:
    changes: list[str]
    unresolved: list[str]
