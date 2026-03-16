"""Contract lifecycle, obligations, and document versioning services."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import time
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from isrc_manager.domain.repertoire import clean_text, parse_iso_date
from isrc_manager.parties import PartyService

from .models import (
    CONTRACT_STATUS_CHOICES,
    DOCUMENT_TYPE_CHOICES,
    OBLIGATION_TYPE_CHOICES,
    ContractDeadline,
    ContractDetail,
    ContractDocumentPayload,
    ContractDocumentRecord,
    ContractObligationPayload,
    ContractObligationRecord,
    ContractPartyPayload,
    ContractPartyRecord,
    ContractPayload,
    ContractRecord,
    ContractValidationIssue,
)


class ContractService:
    """Owns first-class contract records, obligations, and document storage."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        data_root: str | Path | None = None,
        *,
        party_service: PartyService | None = None,
    ):
        self.conn = conn
        self.data_root = Path(data_root) if data_root is not None else None
        self.documents_root = (
            self.data_root / "contract_documents" if self.data_root is not None else None
        )
        self.party_service = party_service

    @staticmethod
    def _clean_status(value: str | None) -> str:
        clean = str(value or "draft").strip().lower().replace(" ", "_")
        if clean not in CONTRACT_STATUS_CHOICES:
            return "draft"
        return clean

    @staticmethod
    def _clean_obligation_type(value: str | None) -> str:
        clean = str(value or "other").strip().lower().replace(" ", "_")
        if clean not in OBLIGATION_TYPE_CHOICES:
            return "other"
        return clean

    @staticmethod
    def _clean_document_type(value: str | None) -> str:
        clean = str(value or "other").strip().lower().replace(" ", "_")
        if clean not in DOCUMENT_TYPE_CHOICES:
            return "other"
        return clean

    @staticmethod
    def _row_to_contract(row) -> ContractRecord:
        return ContractRecord(
            id=int(row[0]),
            title=str(row[1] or ""),
            contract_type=clean_text(row[2]),
            draft_date=clean_text(row[3]),
            signature_date=clean_text(row[4]),
            effective_date=clean_text(row[5]),
            start_date=clean_text(row[6]),
            end_date=clean_text(row[7]),
            renewal_date=clean_text(row[8]),
            notice_deadline=clean_text(row[9]),
            option_periods=clean_text(row[10]),
            reversion_date=clean_text(row[11]),
            termination_date=clean_text(row[12]),
            status=str(row[13] or "draft"),
            supersedes_contract_id=int(row[14]) if row[14] is not None else None,
            superseded_by_contract_id=int(row[15]) if row[15] is not None else None,
            summary=clean_text(row[16]),
            notes=clean_text(row[17]),
            profile_name=clean_text(row[18]),
            created_at=clean_text(row[19]),
            updated_at=clean_text(row[20]),
            obligation_count=int(row[21] or 0),
            document_count=int(row[22] or 0),
        )

    @staticmethod
    def _row_to_party(row) -> ContractPartyRecord:
        return ContractPartyRecord(
            party_id=int(row[0]),
            party_name=str(row[1] or ""),
            role_label=str(row[2] or "counterparty"),
            is_primary=bool(row[3]),
            notes=clean_text(row[4]),
        )

    @staticmethod
    def _row_to_obligation(row) -> ContractObligationRecord:
        return ContractObligationRecord(
            id=int(row[0]),
            contract_id=int(row[1]),
            obligation_type=str(row[2] or "other"),
            title=str(row[3] or ""),
            due_date=clean_text(row[4]),
            follow_up_date=clean_text(row[5]),
            reminder_date=clean_text(row[6]),
            completed=bool(row[7]),
            completed_at=clean_text(row[8]),
            notes=clean_text(row[9]),
        )

    @staticmethod
    def _row_to_document(row) -> ContractDocumentRecord:
        return ContractDocumentRecord(
            id=int(row[0]),
            contract_id=int(row[1]),
            title=str(row[2] or ""),
            document_type=str(row[3] or "other"),
            version_label=clean_text(row[4]),
            created_date=clean_text(row[5]),
            received_date=clean_text(row[6]),
            signed_status=clean_text(row[7]),
            signed_by_all_parties=bool(row[8]),
            active_flag=bool(row[9]),
            supersedes_document_id=int(row[10]) if row[10] is not None else None,
            superseded_by_document_id=int(row[11]) if row[11] is not None else None,
            file_path=clean_text(row[12]),
            filename=clean_text(row[13]),
            checksum_sha256=clean_text(row[14]),
            notes=clean_text(row[15]),
            uploaded_at=clean_text(row[16]),
        )

    def _hash_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def resolve_document_path(self, stored_path: str | None) -> Path | None:
        clean_path = clean_text(stored_path)
        if not clean_path:
            return None
        path = Path(clean_path)
        if path.is_absolute():
            return path
        if self.data_root is None:
            return None
        return self.data_root / path

    def _write_document_file(self, source_path: str | Path) -> tuple[str, str, str]:
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(source)
        if self.documents_root is None or self.data_root is None:
            raise ValueError("Contract document storage is not configured.")
        self.documents_root.mkdir(parents=True, exist_ok=True)
        destination = self.documents_root / f"{int(time.time_ns())}_{source.name}"
        shutil.copy2(source, destination)
        return (
            str(destination.relative_to(self.data_root)),
            source.name,
            self._hash_file(destination),
        )

    def _delete_document_if_unreferenced(
        self,
        stored_path: str | None,
        *,
        cursor: sqlite3.Cursor,
    ) -> None:
        clean_path = clean_text(stored_path)
        if not clean_path:
            return
        row = cursor.execute(
            "SELECT 1 FROM ContractDocuments WHERE file_path=? LIMIT 1",
            (clean_path,),
        ).fetchone()
        if row:
            return
        resolved = self.resolve_document_path(clean_path)
        if resolved is None:
            return
        try:
            resolved.unlink(missing_ok=True)
        except Exception:
            pass

    def _resolve_party_id(
        self, item: ContractPartyPayload, *, cursor: sqlite3.Cursor
    ) -> int | None:
        if item.party_id:
            return int(item.party_id)
        if self.party_service is None or not clean_text(item.name):
            return None
        return self.party_service.ensure_party_by_name(str(clean_text(item.name)), cursor=cursor)

    def validate_contract(
        self,
        payload: ContractPayload,
        *,
        contract_id: int | None = None,
    ) -> list[ContractValidationIssue]:
        issues: list[ContractValidationIssue] = []
        if not clean_text(payload.title):
            issues.append(ContractValidationIssue("error", "title", "Contract title is required."))
        if self._clean_status(payload.status) in {"pending_signature", "active"} and not clean_text(
            payload.signature_date
        ):
            issues.append(
                ContractValidationIssue(
                    "warning",
                    "signature_date",
                    "Pending or active contracts should include a signature date.",
                )
            )
        if self._clean_status(payload.status) == "active" and not payload.parties:
            issues.append(
                ContractValidationIssue(
                    "warning",
                    "parties",
                    "Active contracts should be linked to at least one party.",
                )
            )
        start_date = parse_iso_date(payload.start_date)
        end_date = parse_iso_date(payload.end_date)
        if start_date and end_date and start_date > end_date:
            issues.append(
                ContractValidationIssue(
                    "error",
                    "end_date",
                    "Contract end date cannot be earlier than the start date.",
                )
            )
        final_docs = [
            doc
            for doc in payload.documents
            if self._clean_document_type(doc.document_type) == "signed_agreement"
            and doc.active_flag
        ]
        if self._clean_status(payload.status) == "active" and not any(
            doc.signed_by_all_parties for doc in final_docs
        ):
            issues.append(
                ContractValidationIssue(
                    "warning",
                    "documents",
                    "Active contracts should have an active signed-agreement document marked as signed by all parties.",
                )
            )
        if len(final_docs) > 1:
            issues.append(
                ContractValidationIssue(
                    "warning",
                    "documents",
                    "Contract has multiple active signed-agreement document versions.",
                )
            )
        for document in payload.documents:
            if (
                self._clean_document_type(document.document_type) == "amendment"
                and document.supersedes_document_id is None
            ):
                issues.append(
                    ContractValidationIssue(
                        "warning",
                        "documents",
                        f"Amendment document '{document.title or 'Untitled'}' does not declare which version it supersedes.",
                    )
                )
        return issues

    def create_contract(
        self,
        payload: ContractPayload,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> int:
        issues = self.validate_contract(payload)
        errors = [issue.message for issue in issues if issue.severity == "error"]
        if errors:
            raise ValueError("\n".join(errors))
        cur = cursor or self.conn.cursor()
        cur.execute(
            """
            INSERT INTO Contracts (
                title,
                contract_type,
                draft_date,
                signature_date,
                effective_date,
                start_date,
                end_date,
                renewal_date,
                notice_deadline,
                option_periods,
                reversion_date,
                termination_date,
                status,
                supersedes_contract_id,
                superseded_by_contract_id,
                summary,
                notes,
                profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(clean_text(payload.title) or ""),
                clean_text(payload.contract_type),
                clean_text(payload.draft_date),
                clean_text(payload.signature_date),
                clean_text(payload.effective_date),
                clean_text(payload.start_date),
                clean_text(payload.end_date),
                clean_text(payload.renewal_date),
                clean_text(payload.notice_deadline),
                clean_text(payload.option_periods),
                clean_text(payload.reversion_date),
                clean_text(payload.termination_date),
                self._clean_status(payload.status),
                payload.supersedes_contract_id,
                payload.superseded_by_contract_id,
                clean_text(payload.summary),
                clean_text(payload.notes),
                clean_text(payload.profile_name),
            ),
        )
        contract_id = int(cur.lastrowid)
        self._replace_parties(contract_id, payload.parties, cursor=cur)
        self._replace_obligations(contract_id, payload.obligations, cursor=cur)
        self._replace_links(
            contract_id, "ContractWorkLinks", "work_id", payload.work_ids, cursor=cur
        )
        self._replace_links(
            contract_id, "ContractTrackLinks", "track_id", payload.track_ids, cursor=cur
        )
        self._replace_links(
            contract_id, "ContractReleaseLinks", "release_id", payload.release_ids, cursor=cur
        )
        self._replace_documents(contract_id, payload.documents, cursor=cur)
        if cursor is None:
            self.conn.commit()
        return contract_id

    def update_contract(
        self,
        contract_id: int,
        payload: ContractPayload,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> None:
        issues = self.validate_contract(payload, contract_id=int(contract_id))
        errors = [issue.message for issue in issues if issue.severity == "error"]
        if errors:
            raise ValueError("\n".join(errors))
        cur = cursor or self.conn.cursor()
        cur.execute(
            """
            UPDATE Contracts
            SET title=?,
                contract_type=?,
                draft_date=?,
                signature_date=?,
                effective_date=?,
                start_date=?,
                end_date=?,
                renewal_date=?,
                notice_deadline=?,
                option_periods=?,
                reversion_date=?,
                termination_date=?,
                status=?,
                supersedes_contract_id=?,
                superseded_by_contract_id=?,
                summary=?,
                notes=?,
                profile_name=?,
                updated_at=datetime('now')
            WHERE id=?
            """,
            (
                str(clean_text(payload.title) or ""),
                clean_text(payload.contract_type),
                clean_text(payload.draft_date),
                clean_text(payload.signature_date),
                clean_text(payload.effective_date),
                clean_text(payload.start_date),
                clean_text(payload.end_date),
                clean_text(payload.renewal_date),
                clean_text(payload.notice_deadline),
                clean_text(payload.option_periods),
                clean_text(payload.reversion_date),
                clean_text(payload.termination_date),
                self._clean_status(payload.status),
                payload.supersedes_contract_id,
                payload.superseded_by_contract_id,
                clean_text(payload.summary),
                clean_text(payload.notes),
                clean_text(payload.profile_name),
                int(contract_id),
            ),
        )
        self._replace_parties(int(contract_id), payload.parties, cursor=cur)
        self._replace_obligations(int(contract_id), payload.obligations, cursor=cur)
        self._replace_links(
            int(contract_id), "ContractWorkLinks", "work_id", payload.work_ids, cursor=cur
        )
        self._replace_links(
            int(contract_id), "ContractTrackLinks", "track_id", payload.track_ids, cursor=cur
        )
        self._replace_links(
            int(contract_id), "ContractReleaseLinks", "release_id", payload.release_ids, cursor=cur
        )
        self._replace_documents(int(contract_id), payload.documents, cursor=cur)
        if cursor is None:
            self.conn.commit()

    def _replace_parties(
        self,
        contract_id: int,
        parties: list[ContractPartyPayload],
        *,
        cursor: sqlite3.Cursor,
    ) -> None:
        cursor.execute("DELETE FROM ContractParties WHERE contract_id=?", (int(contract_id),))
        for item in parties:
            party_id = self._resolve_party_id(item, cursor=cursor)
            if not party_id:
                continue
            cursor.execute(
                """
                INSERT OR IGNORE INTO ContractParties(
                    contract_id,
                    party_id,
                    role_label,
                    is_primary,
                    notes
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    int(contract_id),
                    int(party_id),
                    str(clean_text(item.role_label) or "counterparty"),
                    1 if item.is_primary else 0,
                    clean_text(item.notes),
                ),
            )

    def _replace_obligations(
        self,
        contract_id: int,
        obligations: list[ContractObligationPayload],
        *,
        cursor: sqlite3.Cursor,
    ) -> None:
        cursor.execute("DELETE FROM ContractObligations WHERE contract_id=?", (int(contract_id),))
        for item in obligations:
            title = clean_text(item.title)
            if not title:
                continue
            cursor.execute(
                """
                INSERT INTO ContractObligations(
                    contract_id,
                    obligation_type,
                    title,
                    due_date,
                    follow_up_date,
                    reminder_date,
                    completed,
                    completed_at,
                    notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(contract_id),
                    self._clean_obligation_type(item.obligation_type),
                    title,
                    clean_text(item.due_date),
                    clean_text(item.follow_up_date),
                    clean_text(item.reminder_date),
                    1 if item.completed else 0,
                    clean_text(item.completed_at),
                    clean_text(item.notes),
                ),
            )

    def _replace_links(
        self,
        contract_id: int,
        table_name: str,
        column_name: str,
        ids: list[int],
        *,
        cursor: sqlite3.Cursor,
    ) -> None:
        cursor.execute(f"DELETE FROM {table_name} WHERE contract_id=?", (int(contract_id),))
        seen: set[int] = set()
        for raw_id in ids:
            try:
                item_id = int(raw_id)
            except Exception:
                continue
            if item_id <= 0 or item_id in seen:
                continue
            seen.add(item_id)
            cursor.execute(
                f"INSERT OR IGNORE INTO {table_name}(contract_id, {column_name}) VALUES (?, ?)",
                (int(contract_id), item_id),
            )

    def _replace_documents(
        self,
        contract_id: int,
        documents: list[ContractDocumentPayload],
        *,
        cursor: sqlite3.Cursor,
    ) -> None:
        existing_rows = cursor.execute(
            "SELECT id, file_path FROM ContractDocuments WHERE contract_id=?",
            (int(contract_id),),
        ).fetchall()
        existing_paths = {int(row[0]): clean_text(row[1]) for row in existing_rows}
        seen_ids: set[int] = set()
        for item in documents:
            title = clean_text(item.title)
            if not title:
                continue
            file_path = clean_text(item.stored_path)
            filename = clean_text(item.filename)
            checksum = clean_text(item.checksum_sha256)
            if clean_text(item.source_path):
                file_path, filename, checksum = self._write_document_file(str(item.source_path))
            if item.document_id and int(item.document_id) in existing_paths:
                document_id = int(item.document_id)
                old_path = existing_paths.get(document_id)
                cursor.execute(
                    """
                    UPDATE ContractDocuments
                    SET title=?,
                        document_type=?,
                        version_label=?,
                        created_date=?,
                        received_date=?,
                        signed_status=?,
                        signed_by_all_parties=?,
                        active_flag=?,
                        supersedes_document_id=?,
                        superseded_by_document_id=?,
                        file_path=?,
                        filename=?,
                        checksum_sha256=?,
                        notes=?
                    WHERE id=?
                    """,
                    (
                        title,
                        self._clean_document_type(item.document_type),
                        clean_text(item.version_label),
                        clean_text(item.created_date),
                        clean_text(item.received_date),
                        clean_text(item.signed_status),
                        1 if item.signed_by_all_parties else 0,
                        1 if item.active_flag else 0,
                        item.supersedes_document_id,
                        item.superseded_by_document_id,
                        file_path,
                        filename,
                        checksum,
                        clean_text(item.notes),
                        document_id,
                    ),
                )
                seen_ids.add(document_id)
                if clean_text(item.source_path) and old_path and old_path != file_path:
                    cursor.execute("DELETE FROM ContractDocuments WHERE id=0")
                    self._delete_document_if_unreferenced(old_path, cursor=cursor)
                continue
            cursor.execute(
                """
                INSERT INTO ContractDocuments(
                    contract_id,
                    title,
                    document_type,
                    version_label,
                    created_date,
                    received_date,
                    signed_status,
                    signed_by_all_parties,
                    active_flag,
                    supersedes_document_id,
                    superseded_by_document_id,
                    file_path,
                    filename,
                    checksum_sha256,
                    notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(contract_id),
                    title,
                    self._clean_document_type(item.document_type),
                    clean_text(item.version_label),
                    clean_text(item.created_date),
                    clean_text(item.received_date),
                    clean_text(item.signed_status),
                    1 if item.signed_by_all_parties else 0,
                    1 if item.active_flag else 0,
                    item.supersedes_document_id,
                    item.superseded_by_document_id,
                    file_path,
                    filename,
                    checksum,
                    clean_text(item.notes),
                ),
            )
            seen_ids.add(int(cursor.lastrowid))
        stale_ids = set(existing_paths) - seen_ids
        for document_id in stale_ids:
            stale_path = existing_paths.get(document_id)
            cursor.execute("DELETE FROM ContractDocuments WHERE id=?", (int(document_id),))
            self._delete_document_if_unreferenced(stale_path, cursor=cursor)

    def fetch_contract(self, contract_id: int) -> ContractRecord | None:
        row = self.conn.execute(
            """
            SELECT
                c.id,
                c.title,
                c.contract_type,
                c.draft_date,
                c.signature_date,
                c.effective_date,
                c.start_date,
                c.end_date,
                c.renewal_date,
                c.notice_deadline,
                c.option_periods,
                c.reversion_date,
                c.termination_date,
                c.status,
                c.supersedes_contract_id,
                c.superseded_by_contract_id,
                c.summary,
                c.notes,
                c.profile_name,
                c.created_at,
                c.updated_at,
                COUNT(DISTINCT o.id) AS obligation_count,
                COUNT(DISTINCT d.id) AS document_count
            FROM Contracts c
            LEFT JOIN ContractObligations o ON o.contract_id = c.id
            LEFT JOIN ContractDocuments d ON d.contract_id = c.id
            WHERE c.id=?
            GROUP BY c.id
            """,
            (int(contract_id),),
        ).fetchone()
        return self._row_to_contract(row) if row else None

    def fetch_contract_detail(self, contract_id: int) -> ContractDetail | None:
        contract = self.fetch_contract(int(contract_id))
        if contract is None:
            return None
        parties = self.conn.execute(
            """
            SELECT
                cp.party_id,
                COALESCE(p.display_name, p.legal_name, 'Unknown Party'),
                cp.role_label,
                cp.is_primary,
                cp.notes
            FROM ContractParties cp
            LEFT JOIN Parties p ON p.id = cp.party_id
            WHERE cp.contract_id=?
            ORDER BY cp.is_primary DESC, p.legal_name, cp.role_label
            """,
            (int(contract_id),),
        ).fetchall()
        obligations = self.conn.execute(
            """
            SELECT
                id,
                contract_id,
                obligation_type,
                title,
                due_date,
                follow_up_date,
                reminder_date,
                completed,
                completed_at,
                notes
            FROM ContractObligations
            WHERE contract_id=?
            ORDER BY COALESCE(due_date, follow_up_date, reminder_date, ''), id
            """,
            (int(contract_id),),
        ).fetchall()
        documents = self.conn.execute(
            """
            SELECT
                id,
                contract_id,
                title,
                document_type,
                version_label,
                created_date,
                received_date,
                signed_status,
                signed_by_all_parties,
                active_flag,
                supersedes_document_id,
                superseded_by_document_id,
                file_path,
                filename,
                checksum_sha256,
                notes,
                uploaded_at
            FROM ContractDocuments
            WHERE contract_id=?
            ORDER BY active_flag DESC, uploaded_at DESC, id DESC
            """,
            (int(contract_id),),
        ).fetchall()
        work_rows = self.conn.execute(
            "SELECT work_id FROM ContractWorkLinks WHERE contract_id=? ORDER BY work_id",
            (int(contract_id),),
        ).fetchall()
        track_rows = self.conn.execute(
            "SELECT track_id FROM ContractTrackLinks WHERE contract_id=? ORDER BY track_id",
            (int(contract_id),),
        ).fetchall()
        release_rows = self.conn.execute(
            "SELECT release_id FROM ContractReleaseLinks WHERE contract_id=? ORDER BY release_id",
            (int(contract_id),),
        ).fetchall()
        return ContractDetail(
            contract=contract,
            parties=[self._row_to_party(row) for row in parties],
            obligations=[self._row_to_obligation(row) for row in obligations],
            documents=[self._row_to_document(row) for row in documents],
            work_ids=[int(row[0]) for row in work_rows],
            track_ids=[int(row[0]) for row in track_rows],
            release_ids=[int(row[0]) for row in release_rows],
        )

    def list_contracts(
        self,
        *,
        search_text: str | None = None,
        status: str | None = None,
    ) -> list[ContractRecord]:
        clauses: list[str] = []
        params: list[object] = []
        clean_search = clean_text(search_text)
        if clean_search:
            like = f"%{clean_search}%"
            clauses.append(
                """
                (
                    c.title LIKE ?
                    OR COALESCE(c.contract_type, '') LIKE ?
                    OR COALESCE(c.summary, '') LIKE ?
                    OR EXISTS (
                        SELECT 1
                        FROM ContractParties cp
                        JOIN Parties p ON p.id = cp.party_id
                        WHERE cp.contract_id = c.id
                          AND (
                              p.legal_name LIKE ?
                              OR COALESCE(p.display_name, '') LIKE ?
                          )
                    )
                )
                """
            )
            params.extend([like, like, like, like, like])
        clean_status = clean_text(status)
        if clean_status:
            clauses.append("c.status=?")
            params.append(self._clean_status(clean_status))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT
                c.id,
                c.title,
                c.contract_type,
                c.draft_date,
                c.signature_date,
                c.effective_date,
                c.start_date,
                c.end_date,
                c.renewal_date,
                c.notice_deadline,
                c.option_periods,
                c.reversion_date,
                c.termination_date,
                c.status,
                c.supersedes_contract_id,
                c.superseded_by_contract_id,
                c.summary,
                c.notes,
                c.profile_name,
                c.created_at,
                c.updated_at,
                COUNT(DISTINCT o.id) AS obligation_count,
                COUNT(DISTINCT d.id) AS document_count
            FROM Contracts c
            LEFT JOIN ContractObligations o ON o.contract_id = c.id
            LEFT JOIN ContractDocuments d ON d.contract_id = c.id
            {where}
            GROUP BY c.id
            ORDER BY COALESCE(c.notice_deadline, c.end_date, c.start_date, c.created_at), c.title, c.id
            """,
            params,
        ).fetchall()
        return [self._row_to_contract(row) for row in rows]

    def delete_contract(self, contract_id: int) -> None:
        detail = self.fetch_contract_detail(int(contract_id))
        with self.conn:
            self.conn.execute("DELETE FROM Contracts WHERE id=?", (int(contract_id),))
            if detail is not None:
                for document in detail.documents:
                    self._delete_document_if_unreferenced(
                        document.file_path, cursor=self.conn.cursor()
                    )

    def upcoming_deadlines(self, *, within_days: int = 60) -> list[ContractDeadline]:
        today = date.today()
        cutoff = today + timedelta(days=max(0, int(within_days)))
        deadlines: list[ContractDeadline] = []
        rows = self.conn.execute(
            """
            SELECT
                id,
                title,
                notice_deadline,
                renewal_date,
                end_date,
                reversion_date,
                termination_date
            FROM Contracts
            WHERE status IN ('active', 'pending_signature', 'draft')
            ORDER BY id
            """
        ).fetchall()
        for row in rows:
            contract_id = int(row[0])
            title = str(row[1] or "")
            for field_name, raw_value in (
                ("notice_deadline", row[2]),
                ("renewal_date", row[3]),
                ("end_date", row[4]),
                ("reversion_date", row[5]),
                ("termination_date", row[6]),
            ):
                due = parse_iso_date(raw_value)
                if due is None or due < today or due > cutoff:
                    continue
                deadlines.append(
                    ContractDeadline(
                        contract_id=contract_id,
                        title=title,
                        date_field=field_name,
                        due_date=due.isoformat(),
                    )
                )
        obligation_rows = self.conn.execute(
            """
            SELECT
                c.id,
                c.title,
                o.due_date
            FROM ContractObligations o
            JOIN Contracts c ON c.id = o.contract_id
            WHERE o.completed = 0
              AND o.due_date IS NOT NULL
              AND trim(o.due_date) != ''
            ORDER BY o.due_date, o.id
            """
        ).fetchall()
        for contract_id, title, due_date in obligation_rows:
            due = parse_iso_date(due_date)
            if due is None or due < today or due > cutoff:
                continue
            deadlines.append(
                ContractDeadline(
                    contract_id=int(contract_id),
                    title=str(title or ""),
                    date_field="obligation_due_date",
                    due_date=due.isoformat(),
                )
            )
        deadlines.sort(key=lambda item: (item.due_date, item.title.casefold(), item.contract_id))
        return deadlines

    def export_deadlines_csv(self, path: str | Path, *, within_days: int = 60) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        rows = self.upcoming_deadlines(within_days=within_days)
        lines = ["contract_id,title,date_field,due_date"]
        for row in rows:
            safe_title = row.title.replace('"', '""')
            lines.append(f'{row.contract_id},"{safe_title}",{row.date_field},{row.due_date}')
        output.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def export_rows(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for contract in self.list_contracts():
            detail = self.fetch_contract_detail(contract.id)
            if detail is None:
                continue
            payload = contract.to_dict()
            payload["parties"] = [asdict(item) for item in detail.parties]
            payload["obligations"] = [asdict(item) for item in detail.obligations]
            payload["documents"] = [asdict(item) for item in detail.documents]
            payload["work_ids"] = list(detail.work_ids)
            payload["track_ids"] = list(detail.track_ids)
            payload["release_ids"] = list(detail.release_ids)
            rows.append(payload)
        return rows
