"""Idempotency command-log helpers for financial commands."""

from __future__ import annotations

import sqlite3

from .models import FinancialCommandLogRecord


def _clean_text(value: object | None) -> str | None:
    text = str(value or "").strip()
    return text or None


class FinancialCommandLogService:
    """Persists command keys so financial commands can be retried safely."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def fetch(self, command_key: str) -> FinancialCommandLogRecord | None:
        row = self.conn.execute(
            """
            SELECT
                command_key,
                command_type,
                source_type,
                source_id,
                result_type,
                result_id,
                ledger_transaction_id,
                status,
                created_at,
                completed_at,
                error_message
            FROM FinancialCommandLog
            WHERE command_key=?
            """,
            (str(command_key or "").strip(),),
        ).fetchone()
        if not row:
            return None
        return FinancialCommandLogRecord(
            command_key=str(row[0] or ""),
            command_type=str(row[1] or ""),
            source_type=_clean_text(row[2]),
            source_id=_clean_text(row[3]),
            result_type=_clean_text(row[4]),
            result_id=_clean_text(row[5]),
            ledger_transaction_id=int(row[6]) if row[6] is not None else None,
            status=str(row[7] or ""),
            created_at=_clean_text(row[8]),
            completed_at=_clean_text(row[9]),
            error_message=_clean_text(row[10]),
        )

    def start(
        self,
        *,
        command_key: str,
        command_type: str,
        source_type: str | None = None,
        source_id: str | int | None = None,
    ) -> FinancialCommandLogRecord | None:
        existing = self.fetch(command_key)
        if existing is not None:
            return existing
        self.conn.execute(
            """
            INSERT INTO FinancialCommandLog(
                command_key,
                command_type,
                source_type,
                source_id,
                status
            )
            VALUES (?, ?, ?, ?, 'started')
            """,
            (
                str(command_key or "").strip(),
                str(command_type or "").strip(),
                _clean_text(source_type),
                _clean_text(source_id),
            ),
        )
        return None

    def complete(
        self,
        *,
        command_key: str,
        result_type: str,
        result_id: str | int,
        ledger_transaction_id: int | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE FinancialCommandLog
            SET result_type=?,
                result_id=?,
                ledger_transaction_id=?,
                status='completed',
                completed_at=datetime('now'),
                error_message=NULL
            WHERE command_key=?
            """,
            (
                str(result_type or "").strip(),
                str(result_id),
                int(ledger_transaction_id) if ledger_transaction_id is not None else None,
                str(command_key or "").strip(),
            ),
        )
