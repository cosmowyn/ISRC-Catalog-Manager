"""Legacy license archive migration into parties + contracts."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from isrc_manager.contracts import (
    ContractDocumentPayload,
    ContractPartyPayload,
    ContractPayload,
    ContractService,
)
from isrc_manager.domain.repertoire import clean_text
from isrc_manager.parties import PartyService
from isrc_manager.releases import ReleaseService
from isrc_manager.works import WorkService

from .licenses import LicenseService


@dataclass(slots=True)
class LegacyLicenseMigrationIssue:
    code: str
    message: str
    legacy_license_id: int | None = None
    legacy_licensee_id: int | None = None
    track_id: int | None = None
    stored_path: str | None = None


@dataclass(slots=True)
class LegacyLicenseMigrationSummary:
    legacy_license_count: int
    legacy_licensee_count: int
    unused_licensee_count: int
    missing_file_count: int
    missing_track_count: int
    unmanaged_file_count: int
    issues: list[LegacyLicenseMigrationIssue] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return (
            self.missing_file_count == 0
            and self.missing_track_count == 0
            and self.unmanaged_file_count == 0
        )


@dataclass(slots=True)
class LegacyLicenseMigrationResult:
    migrated_license_count: int
    migrated_licensee_count: int
    created_party_count: int
    reused_party_count: int
    created_contract_count: int
    created_document_count: int
    deleted_legacy_license_count: int
    deleted_legacy_licensee_count: int
    deleted_legacy_file_count: int
    contract_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class _LegacyLicenseRow:
    record_id: int
    track_id: int | None
    track_title: str | None
    licensee_id: int
    licensee_name: str
    file_path: str
    filename: str
    uploaded_at: str | None


class LegacyLicenseMigrationService:
    """Promotes legacy track-level license PDFs into structured parties and contracts."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        license_service: LicenseService,
        party_service: PartyService,
        contract_service: ContractService,
        release_service: ReleaseService | None = None,
        work_service: WorkService | None = None,
    ):
        self.conn = conn
        self.license_service = license_service
        self.party_service = party_service
        self.contract_service = contract_service
        self.release_service = release_service
        self.work_service = work_service

    def inspect(self, *, cursor: sqlite3.Cursor | None = None) -> LegacyLicenseMigrationSummary:
        cur = cursor or self.conn.cursor()
        rows = self._legacy_license_rows(cursor=cur)
        licensee_rows = self._legacy_licensees(cursor=cur)
        issues: list[LegacyLicenseMigrationIssue] = []
        missing_file_count = 0
        missing_track_count = 0
        unmanaged_file_count = 0

        for row in rows:
            if row.track_id is None:
                missing_track_count += 1
                issues.append(
                    LegacyLicenseMigrationIssue(
                        code="missing_track",
                        message=(
                            f"Legacy license #{row.record_id} points to a missing track and cannot be "
                            "migrated safely."
                        ),
                        legacy_license_id=row.record_id,
                        legacy_licensee_id=row.licensee_id,
                        stored_path=row.file_path,
                    )
                )
            resolved = self.license_service.resolve_path(row.file_path)
            if not resolved.exists():
                missing_file_count += 1
                issues.append(
                    LegacyLicenseMigrationIssue(
                        code="missing_file",
                        message=(
                            f"Legacy license #{row.record_id} is missing its stored PDF: {resolved}"
                        ),
                        legacy_license_id=row.record_id,
                        legacy_licensee_id=row.licensee_id,
                        track_id=row.track_id,
                        stored_path=row.file_path,
                    )
                )
            elif not self.license_service.is_managed_license_path(row.file_path):
                unmanaged_file_count += 1
                issues.append(
                    LegacyLicenseMigrationIssue(
                        code="unmanaged_file",
                        message=(
                            f"Legacy license #{row.record_id} points outside the managed license "
                            "archive and must be reviewed before migration."
                        ),
                        legacy_license_id=row.record_id,
                        legacy_licensee_id=row.licensee_id,
                        track_id=row.track_id,
                        stored_path=row.file_path,
                    )
                )

        used_licensee_ids = {row.licensee_id for row in rows}
        unused_licensee_count = sum(
            1 for licensee_id, _name in licensee_rows if licensee_id not in used_licensee_ids
        )
        return LegacyLicenseMigrationSummary(
            legacy_license_count=len(rows),
            legacy_licensee_count=len(licensee_rows),
            unused_licensee_count=unused_licensee_count,
            missing_file_count=missing_file_count,
            missing_track_count=missing_track_count,
            unmanaged_file_count=unmanaged_file_count,
            issues=issues,
        )

    def migrate_all(
        self,
        *,
        cursor: sqlite3.Cursor | None = None,
        ctx=None,
    ) -> LegacyLicenseMigrationResult:
        own_transaction = cursor is None
        cur = cursor or self.conn.cursor()
        summary = self.inspect(cursor=cur)
        if not summary.ready:
            messages = "\n".join(issue.message for issue in summary.issues[:10])
            extra_count = max(0, len(summary.issues) - 10)
            if extra_count:
                messages += f"\n...and {extra_count} more issue(s)."
            raise ValueError(
                "Legacy license migration is blocked until all legacy records are complete.\n\n"
                + messages
            )

        license_rows = self._legacy_license_rows(cursor=cur)
        licensee_rows = self._legacy_licensees(cursor=cur)
        if not license_rows and not licensee_rows:
            return LegacyLicenseMigrationResult(
                migrated_license_count=0,
                migrated_licensee_count=0,
                created_party_count=0,
                reused_party_count=0,
                created_contract_count=0,
                created_document_count=0,
                deleted_legacy_license_count=0,
                deleted_legacy_licensee_count=0,
                deleted_legacy_file_count=0,
                contract_ids=[],
            )

        created_party_ids: set[int] = set()
        reused_party_ids: set[int] = set()
        contract_ids: list[int] = []
        new_document_paths: list[str] = []
        old_license_paths: list[str] = []
        old_license_ids: list[int] = []
        migrated_licensee_ids: set[int] = set()
        party_ids_by_legacy_licensee: dict[int, int] = {}
        legacy_restore_pairs: list[tuple[str, str]] = []

        try:
            if ctx is not None:
                ctx.set_status("Preparing parties for legacy license migration...")
            for index, (legacy_licensee_id, licensee_name) in enumerate(licensee_rows, start=1):
                if ctx is not None:
                    ctx.raise_if_cancelled()
                    ctx.report_progress(
                        value=index - 1,
                        maximum=max(len(licensee_rows), 1),
                        message="Preparing legacy licensee parties...",
                    )
                clean_name = str(clean_text(licensee_name) or "")
                existing_party_id = self._find_party_id(clean_name, cursor=cur)
                if existing_party_id is None:
                    party_id = self.party_service.create_party(
                        payload=self.party_service_payload(clean_name),
                        cursor=cur,
                    )
                    created_party_ids.add(party_id)
                else:
                    party_id = existing_party_id
                    reused_party_ids.add(party_id)
                party_ids_by_legacy_licensee[int(legacy_licensee_id)] = int(party_id)
                migrated_licensee_ids.add(int(legacy_licensee_id))
            if ctx is not None and licensee_rows:
                ctx.report_progress(
                    value=len(licensee_rows),
                    maximum=len(licensee_rows),
                    message="Prepared legacy licensee parties.",
                )

            total_licenses = len(license_rows)
            for index, row in enumerate(license_rows, start=1):
                if ctx is not None:
                    ctx.raise_if_cancelled()
                    ctx.set_status(
                        f"Migrating legacy license {index} of {max(total_licenses, 1)}..."
                    )
                    ctx.report_progress(
                        value=index - 1,
                        maximum=max(total_licenses, 1),
                        message="Copying and verifying legacy license documents...",
                    )

                old_path = self.license_service.resolve_path(row.file_path)
                old_checksum = self._hash_file(old_path)
                party_id = party_ids_by_legacy_licensee[row.licensee_id]
                payload = ContractPayload(
                    title=self._contract_title(row),
                    contract_type="license",
                    status="active",
                    summary=(
                        "Migrated from the legacy license archive. Review lifecycle dates, "
                        "rights terms, and obligations after migration."
                    ),
                    notes=self._contract_notes(row, old_checksum),
                    parties=[
                        ContractPartyPayload(
                            party_id=party_id,
                            role_label="licensee",
                            is_primary=True,
                            notes="Migrated from legacy licensee registry.",
                        )
                    ],
                    documents=[
                        ContractDocumentPayload(
                            title=row.filename or f"Legacy License #{row.record_id}",
                            document_type="signed_agreement",
                            version_label="Legacy Archive Import",
                            received_date=self._legacy_received_date(row.uploaded_at),
                            signed_status="legacy_signed_pdf",
                            signed_by_all_parties=True,
                            active_flag=True,
                            source_path=str(old_path),
                            notes=(
                                f"Migrated from legacy license record #{row.record_id} and "
                                f"verified against the original SHA-256 checksum {old_checksum}."
                            ),
                        )
                    ],
                    work_ids=self._work_ids_for_track(row.track_id),
                    track_ids=[int(row.track_id)] if row.track_id else [],
                    release_ids=self._release_ids_for_track(row.track_id),
                )
                contract_id = self.contract_service.create_contract(payload, cursor=cur)
                detail = self.contract_service.fetch_contract_detail(contract_id)
                if detail is None or not detail.documents:
                    raise RuntimeError(
                        f"Migrated contract {contract_id} could not be reloaded with its document."
                    )
                migrated_document = detail.documents[0]
                new_document_path = self.contract_service.resolve_document_path(
                    migrated_document.file_path
                )
                if new_document_path is None or not new_document_path.exists():
                    raise FileNotFoundError(
                        migrated_document.file_path
                        or f"Missing document for contract {contract_id}"
                    )
                new_checksum = self._hash_file(new_document_path)
                if clean_text(migrated_document.checksum_sha256) != new_checksum:
                    raise RuntimeError(
                        f"Migrated contract document checksum mismatch for contract {contract_id}."
                    )
                if new_checksum != old_checksum:
                    raise RuntimeError(
                        f"Migrated contract document content mismatch for legacy license #{row.record_id}."
                    )
                contract_ids.append(int(contract_id))
                new_document_paths.append(str(migrated_document.file_path or ""))
                old_license_ids.append(int(row.record_id))
                old_license_paths.append(str(row.file_path or ""))
                legacy_restore_pairs.append(
                    (str(row.file_path or ""), str(migrated_document.file_path or ""))
                )

            if ctx is not None and total_licenses:
                ctx.report_progress(
                    value=total_licenses,
                    maximum=total_licenses,
                    message="Verifying migrated contracts and cleaning legacy data...",
                )

            if old_license_ids:
                placeholders = ",".join("?" for _ in old_license_ids)
                cur.execute(
                    f"DELETE FROM Licenses WHERE id IN ({placeholders})",
                    old_license_ids,
                )

            if migrated_licensee_ids:
                placeholders = ",".join("?" for _ in migrated_licensee_ids)
                cur.execute(
                    f"DELETE FROM Licensees WHERE id IN ({placeholders})",
                    list(sorted(migrated_licensee_ids)),
                )

            deleted_legacy_file_count = 0
            for stored_path in sorted(set(old_license_paths)):
                resolved = self.license_service.resolve_path(stored_path)
                if resolved.exists():
                    resolved.unlink()
                    deleted_legacy_file_count += 1

            remaining_licenses = cur.execute("SELECT COUNT(*) FROM Licenses").fetchone()
            if remaining_licenses and int(remaining_licenses[0] or 0) != 0:
                raise RuntimeError("Legacy license rows still exist after migration cleanup.")
            remaining_licensees = cur.execute("SELECT COUNT(*) FROM Licensees").fetchone()
            if remaining_licensees and int(remaining_licensees[0] or 0) != 0:
                raise RuntimeError("Legacy licensee rows still exist after migration cleanup.")

            result = LegacyLicenseMigrationResult(
                migrated_license_count=len(old_license_ids),
                migrated_licensee_count=len(migrated_licensee_ids),
                created_party_count=len(created_party_ids),
                reused_party_count=len(reused_party_ids),
                created_contract_count=len(contract_ids),
                created_document_count=len(new_document_paths),
                deleted_legacy_license_count=len(old_license_ids),
                deleted_legacy_licensee_count=len(migrated_licensee_ids),
                deleted_legacy_file_count=deleted_legacy_file_count,
                contract_ids=contract_ids,
            )
            if own_transaction:
                self.conn.commit()
            return result
        except Exception:
            if own_transaction and self.conn.in_transaction:
                self.conn.rollback()
            self._restore_legacy_files(legacy_restore_pairs)
            self._cleanup_new_documents(new_document_paths)
            raise

    @staticmethod
    def party_service_payload(licensee_name: str):
        from isrc_manager.parties import PartyPayload

        return PartyPayload(
            legal_name=licensee_name,
            display_name=licensee_name,
            party_type="licensee",
            notes="Created while migrating from the legacy licensee registry.",
        )

    def _legacy_license_rows(self, *, cursor: sqlite3.Cursor) -> list[_LegacyLicenseRow]:
        rows = cursor.execute(
            """
            SELECT
                l.id,
                l.track_id,
                t.track_title,
                l.licensee_id,
                lic.name,
                l.file_path,
                l.filename,
                l.uploaded_at
            FROM Licenses l
            JOIN Licensees lic ON lic.id = l.licensee_id
            LEFT JOIN Tracks t ON t.id = l.track_id
            ORDER BY lic.name COLLATE NOCASE, l.id
            """
        ).fetchall()
        return [
            _LegacyLicenseRow(
                record_id=int(row[0]),
                track_id=int(row[1]) if row[1] is not None else None,
                track_title=clean_text(row[2]),
                licensee_id=int(row[3]),
                licensee_name=str(row[4] or ""),
                file_path=str(row[5] or ""),
                filename=str(row[6] or ""),
                uploaded_at=clean_text(row[7]),
            )
            for row in rows
        ]

    def _legacy_licensees(self, *, cursor: sqlite3.Cursor) -> list[tuple[int, str]]:
        rows = cursor.execute(
            "SELECT id, name FROM Licensees ORDER BY name COLLATE NOCASE, id"
        ).fetchall()
        return [(int(row[0]), str(row[1] or "")) for row in rows]

    def _find_party_id(self, licensee_name: str, *, cursor: sqlite3.Cursor) -> int | None:
        row = cursor.execute(
            """
            SELECT id
            FROM Parties
            WHERE lower(legal_name)=lower(?) OR lower(COALESCE(display_name, ''))=lower(?)
            ORDER BY id
            LIMIT 1
            """,
            (licensee_name, licensee_name),
        ).fetchone()
        return int(row[0]) if row else None

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _legacy_received_date(uploaded_at: str | None) -> str | None:
        clean_uploaded = str(clean_text(uploaded_at) or "")
        if len(clean_uploaded) >= 10:
            return clean_uploaded[:10]
        return None

    def _work_ids_for_track(self, track_id: int | None) -> list[int]:
        if not track_id or self.work_service is None:
            return []
        return [int(work.id) for work in self.work_service.list_works_for_track(int(track_id))]

    def _release_ids_for_track(self, track_id: int | None) -> list[int]:
        if not track_id or self.release_service is None:
            return []
        return [
            int(item) for item in self.release_service.find_release_ids_for_track(int(track_id))
        ]

    @staticmethod
    def _contract_title(row: _LegacyLicenseRow) -> str:
        track_title = clean_text(row.track_title) or f"Track {row.track_id}"
        licensee_name = clean_text(row.licensee_name) or f"Licensee {row.licensee_id}"
        return f"Legacy License #{row.record_id}: {track_title} / {licensee_name}"

    @staticmethod
    def _contract_notes(row: _LegacyLicenseRow, checksum: str) -> str:
        lines = [
            f"Migrated from legacy license record #{row.record_id}.",
            f"Legacy licensee: {row.licensee_name}.",
            f"Legacy filename: {row.filename or Path(row.file_path).name}.",
            f"Legacy stored path: {row.file_path}.",
            f"Original SHA-256: {checksum}.",
        ]
        if clean_text(row.uploaded_at):
            lines.append(f"Legacy upload timestamp: {row.uploaded_at}.")
        return "\n".join(lines)

    def _cleanup_new_documents(self, stored_paths: list[str]) -> None:
        seen: set[str] = set()
        for stored_path in stored_paths:
            clean_path = str(clean_text(stored_path) or "")
            if not clean_path or clean_path in seen:
                continue
            seen.add(clean_path)
            resolved = self.contract_service.resolve_document_path(clean_path)
            if resolved is None:
                continue
            try:
                resolved.unlink(missing_ok=True)
            except Exception:
                pass

    def _restore_legacy_files(self, restore_pairs: list[tuple[str, str]]) -> None:
        for legacy_stored_path, new_document_stored_path in restore_pairs:
            legacy_path = self.license_service.resolve_path(legacy_stored_path)
            if legacy_path.exists():
                continue
            new_document_path = self.contract_service.resolve_document_path(
                new_document_stored_path
            )
            if new_document_path is None or not new_document_path.exists():
                continue
            try:
                legacy_path.parent.mkdir(parents=True, exist_ok=True)
                legacy_path.write_bytes(new_document_path.read_bytes())
            except Exception:
                pass
