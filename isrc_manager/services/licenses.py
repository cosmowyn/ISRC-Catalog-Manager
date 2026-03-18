"""License record and managed file services."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from isrc_manager.file_storage import (
    ManagedFileStorage,
    STORAGE_MODE_DATABASE,
    STORAGE_MODE_MANAGED_FILE,
    bytes_from_blob,
    coalesce_filename,
    infer_storage_mode,
    normalize_storage_mode,
)
from isrc_manager.media.blob_files import _read_blob_from_path

from .catalog_admin import CatalogAdminService


@dataclass(slots=True)
class LicenseRow:
    record_id: int
    licensee: str
    track_title: str
    uploaded_at: str
    filename: str
    file_path: str


@dataclass(slots=True)
class LicenseRecord:
    record_id: int
    track_id: int
    licensee_id: int
    file_path: str | None
    filename: str
    storage_mode: str | None = None
    mime_type: str | None = None
    size_bytes: int = 0


class LicenseService:
    """Centralizes license CRUD and managed PDF storage."""

    def __init__(self, conn: sqlite3.Connection, data_dir: str | Path):
        self.conn = conn
        self.data_dir = Path(data_dir)
        self.licenses_dir = self.data_dir / "licenses"
        self.file_store = ManagedFileStorage(data_root=self.data_dir, relative_root="licenses")
        self.catalog_admin = CatalogAdminService(conn)
        self._ensure_storage_columns()

    def _ensure_storage_columns(self) -> None:
        columns = {
            str(row[1])
            for row in self.conn.execute("PRAGMA table_info(Licenses)").fetchall()
            if row and row[1]
        }
        additions = (
            ("storage_mode", "TEXT"),
            ("file_blob", "BLOB"),
            ("mime_type", "TEXT"),
            ("size_bytes", "INTEGER NOT NULL DEFAULT 0"),
        )
        with self.conn:
            for column_name, column_sql in additions:
                if column_name not in columns:
                    self.conn.execute(f"ALTER TABLE Licenses ADD COLUMN {column_name} {column_sql}")

    def list_rows(self, track_filter_id: int | None = None) -> list[LicenseRow]:
        if track_filter_id is None:
            rows = self.conn.execute(
                """
                SELECT licensee, tracktitle, uploaded_at, filename, file_path, id
                FROM vw_Licenses
                ORDER BY uploaded_at DESC
                """
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT licensee, tracktitle, uploaded_at, filename, file_path, id
                FROM vw_Licenses
                WHERE track_id=?
                ORDER BY uploaded_at DESC
                """,
                (int(track_filter_id),),
            ).fetchall()
        return [
            LicenseRow(
                record_id=int(record_id),
                licensee=licensee or "",
                track_title=track_title or "",
                uploaded_at=uploaded_at or "",
                filename=filename or "",
                file_path=file_path or "",
            )
            for licensee, track_title, uploaded_at, filename, file_path, record_id in rows
        ]

    def list_licensee_choices(self) -> list[tuple[int, str]]:
        return self.catalog_admin.list_licensee_choices()

    def fetch_license(self, record_id: int) -> LicenseRecord | None:
        row = self.conn.execute(
            """
            SELECT id, track_id, licensee_id, file_path, filename, storage_mode, mime_type, size_bytes
            FROM Licenses
            WHERE id=?
            """,
            (int(record_id),),
        ).fetchone()
        if not row:
            return None
        return LicenseRecord(
            record_id=int(row[0]),
            track_id=int(row[1]),
            licensee_id=int(row[2]),
            file_path=row[3] or None,
            filename=row[4] or "",
            storage_mode=infer_storage_mode(explicit_mode=row[5], stored_path=row[3]),
            mime_type=row[6] or None,
            size_bytes=int(row[7] or 0),
        )

    def resolve_path(self, stored_path: str) -> Path:
        path = Path(stored_path)
        return path if path.is_absolute() else (self.data_dir / path)

    def is_managed_license_path(self, stored_path: str) -> bool:
        clean_path = str(stored_path or "").strip()
        if not clean_path:
            return False
        path = Path(clean_path)
        if path.is_absolute():
            try:
                path.resolve().relative_to(self.licenses_dir.resolve())
                return True
            except Exception:
                return False
        try:
            (self.data_dir / path).resolve().relative_to(self.licenses_dir.resolve())
            return True
        except Exception:
            return False

    def _fetch_license_blob(self, record_id: int) -> bytes | None:
        row = self.conn.execute(
            "SELECT file_blob FROM Licenses WHERE id=?",
            (int(record_id),),
        ).fetchone()
        if not row or row[0] is None:
            return None
        return bytes_from_blob(row[0])

    def fetch_license_bytes(self, record_id: int) -> tuple[bytes, str]:
        record = self.fetch_license(record_id)
        if record is None:
            raise FileNotFoundError(record_id)
        if record.storage_mode == STORAGE_MODE_DATABASE:
            blob_data = self._fetch_license_blob(record_id)
            if blob_data is None:
                raise FileNotFoundError(record.filename or record_id)
            return blob_data, str(record.mime_type or "").strip()
        if not record.file_path:
            raise FileNotFoundError(record.filename or record_id)
        resolved = self.resolve_path(record.file_path)
        if not resolved.exists():
            raise FileNotFoundError(record.file_path)
        return resolved.read_bytes(), str(record.mime_type or "").strip()

    def _store_license_source(
        self,
        source_pdf_path: str | Path,
        *,
        storage_mode: str | None = None,
    ) -> tuple[str | None, str, bytes | None, str | None, int]:
        source_path = Path(source_pdf_path)
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        clean_mode = normalize_storage_mode(storage_mode, default=STORAGE_MODE_MANAGED_FILE)
        filename = coalesce_filename(source_path.name, default_stem="license")
        if clean_mode == STORAGE_MODE_DATABASE:
            data = _read_blob_from_path(str(source_path))
            return None, filename, data, "application/pdf", len(data)
        data = source_path.read_bytes()
        rel_path = self.file_store.write_bytes(data, filename=filename)
        return rel_path, filename, None, "application/pdf", len(data)

    def add_license(
        self,
        *,
        track_id: int,
        licensee_name: str,
        source_pdf_path: str | Path,
        storage_mode: str | None = None,
    ) -> int:
        source_path = Path(source_pdf_path)
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        with self.conn:
            cur = self.conn.cursor()
            licensee_id = self.catalog_admin.ensure_licensee(licensee_name, cursor=cur)
            rel_path, filename, blob_data, mime_type, size_bytes = self._store_license_source(
                source_path,
                storage_mode=storage_mode,
            )
            cur.execute(
                """
                INSERT INTO Licenses(
                    track_id,
                    licensee_id,
                    file_path,
                    filename,
                    storage_mode,
                    file_blob,
                    mime_type,
                    size_bytes
                )
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    int(track_id),
                    licensee_id,
                    rel_path,
                    filename,
                    normalize_storage_mode(storage_mode, default=STORAGE_MODE_MANAGED_FILE),
                    sqlite3.Binary(blob_data) if blob_data is not None else None,
                    mime_type,
                    size_bytes,
                ),
            )
            return int(cur.lastrowid)

    def update_license(
        self,
        *,
        record_id: int,
        licensee_name: str,
        replacement_pdf_path: str | Path | None = None,
        storage_mode: str | None = None,
    ) -> LicenseRecord:
        current = self.fetch_license(record_id)
        if current is None:
            raise ValueError(f"License record {record_id} not found")

        with self.conn:
            cur = self.conn.cursor()
            clean_name = (licensee_name or "").strip()
            if clean_name:
                licensee_id = self.catalog_admin.ensure_licensee(clean_name, cursor=cur)
            else:
                licensee_id = current.licensee_id
            file_path = current.file_path
            filename = current.filename
            mime_type = current.mime_type
            size_bytes = current.size_bytes
            clean_mode = normalize_storage_mode(storage_mode, default=current.storage_mode)
            blob_data = self._fetch_license_blob(record_id) if current.storage_mode == STORAGE_MODE_DATABASE else None
            if replacement_pdf_path:
                file_path, filename, blob_data, mime_type, size_bytes = self._store_license_source(
                    Path(replacement_pdf_path),
                    storage_mode=clean_mode,
                )
            cur.execute(
                """
                UPDATE Licenses
                SET licensee_id=?,
                    file_path=?,
                    filename=?,
                    storage_mode=?,
                    file_blob=?,
                    mime_type=?,
                    size_bytes=?
                WHERE id=?
                """,
                (
                    licensee_id,
                    file_path,
                    filename,
                    clean_mode,
                    sqlite3.Binary(blob_data) if blob_data is not None else None,
                    mime_type,
                    int(size_bytes or 0),
                    int(record_id),
                ),
            )

        updated = self.fetch_license(record_id)
        if updated is None:
            raise RuntimeError(f"License record {record_id} disappeared after update")
        return updated

    def delete_licenses(self, record_ids: Iterable[int], *, delete_files: bool = False) -> int:
        ids = [int(record_id) for record_id in record_ids]
        if not ids:
            return 0

        file_paths = []
        if delete_files:
            placeholders = ",".join("?" for _ in ids)
            file_rows = self.conn.execute(
                f"SELECT file_path FROM Licenses WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
            file_paths = [row[0] for row in file_rows if row and row[0]]

        with self.conn:
            self.conn.executemany(
                "DELETE FROM Licenses WHERE id=?", [(record_id,) for record_id in ids]
            )

        if delete_files:
            for stored_path in file_paths:
                try:
                    resolved = self.resolve_path(stored_path)
                    if resolved.exists():
                        resolved.unlink()
                except Exception:
                    logging.exception("Failed to delete stored license file %s", stored_path)

        return len(ids)

    def convert_storage_mode(self, record_id: int, target_mode: str) -> LicenseRecord:
        current = self.fetch_license(record_id)
        if current is None:
            raise ValueError(f"License record {record_id} not found")
        clean_mode = normalize_storage_mode(target_mode)
        if current.storage_mode == clean_mode:
            return current
        data, mime_type = self.fetch_license_bytes(record_id)
        rel_path = current.file_path
        filename = current.filename
        blob_data: bytes | None
        if clean_mode == STORAGE_MODE_DATABASE:
            rel_path = None
            blob_data = data
        else:
            rel_path = self.file_store.write_bytes(data, filename=filename)
            blob_data = None
        with self.conn:
            self.conn.execute(
                """
                UPDATE Licenses
                SET file_path=?,
                    storage_mode=?,
                    file_blob=?,
                    mime_type=?,
                    size_bytes=?
                WHERE id=?
                """,
                (
                    rel_path,
                    clean_mode,
                    sqlite3.Binary(blob_data) if blob_data is not None else None,
                    mime_type,
                    len(data),
                    int(record_id),
                ),
            )
        updated = self.fetch_license(record_id)
        if updated is None:
            raise RuntimeError(f"License record {record_id} disappeared after conversion")
        return updated
