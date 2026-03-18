"""Persistent undo, redo, and snapshot history helpers."""

from .manager import HistoryManager, HistoryRecoveryError
from .models import BackupRecord, HistoryEntry, HistoryIssue, HistoryRepairResult, SnapshotRecord
from .session_manager import SessionHistoryManager

__all__ = [
    "BackupRecord",
    "HistoryEntry",
    "HistoryIssue",
    "HistoryManager",
    "HistoryRecoveryError",
    "HistoryRepairResult",
    "SessionHistoryManager",
    "SnapshotRecord",
]
