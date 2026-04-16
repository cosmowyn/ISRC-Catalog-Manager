"""Persistent undo, redo, and snapshot history helpers."""

from .cleanup import (
    HistoryCleanupBlockedError,
    HistoryCleanupItem,
    HistoryCleanupPreview,
    HistoryCleanupResult,
    HistorySnapshotRetentionResult,
    HistoryStorageCleanupService,
    HistoryTrimPreview,
)
from .manager import HistoryManager, HistoryRecoveryError
from .models import BackupRecord, HistoryEntry, HistoryIssue, HistoryRepairResult, SnapshotRecord
from .session_manager import SessionHistoryManager

__all__ = [
    "BackupRecord",
    "HistoryCleanupBlockedError",
    "HistoryCleanupItem",
    "HistoryCleanupPreview",
    "HistoryCleanupResult",
    "HistoryEntry",
    "HistoryIssue",
    "HistoryManager",
    "HistoryRecoveryError",
    "HistoryRepairResult",
    "HistorySnapshotRetentionResult",
    "HistoryStorageCleanupService",
    "HistoryTrimPreview",
    "SessionHistoryManager",
    "SnapshotRecord",
]
