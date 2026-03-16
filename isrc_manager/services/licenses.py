"""License record and managed file services."""

from __future__ import annotations

import logging
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

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
    file_path: str
    filename: str


class LicenseService:
    """Centralizes license CRUD and managed PDF storage."""

    def __init__(self, conn: sqlite3.Connection, data_dir: str | Path):
        self.conn = conn
        self.data_dir = Path(data_dir)
        self.licenses_dir = self.data_dir / "licenses"
        self.catalog_admin = CatalogAdminService(conn)

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
            "SELECT id, track_id, licensee_id, file_path, filename FROM Licenses WHERE id=?",
            (int(record_id),),
        ).fetchone()
        if not row:
            return None
        return LicenseRecord(
            record_id=int(row[0]),
            track_id=int(row[1]),
            licensee_id=int(row[2]),
            file_path=row[3] or "",
            filename=row[4] or "",
        )

    def resolve_path(self, stored_path: str) -> Path:
        path = Path(stored_path)
        return path if path.is_absolute() else (self.data_dir / path)

    def add_license(self, *, track_id: int, licensee_name: str, source_pdf_path: str | Path) -> int:
        source_path = Path(source_pdf_path)
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        with self.conn:
            cur = self.conn.cursor()
            licensee_id = self.catalog_admin.ensure_licensee(licensee_name, cursor=cur)
            filename, rel_path = self._copy_into_store(source_path)
            cur.execute(
                "INSERT INTO Licenses(track_id, licensee_id, file_path, filename) VALUES (?,?,?,?)",
                (int(track_id), licensee_id, rel_path, filename),
            )
            return int(cur.lastrowid)

    def update_license(
        self,
        *,
        record_id: int,
        licensee_name: str,
        replacement_pdf_path: str | Path | None = None,
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
            if replacement_pdf_path:
                filename, file_path = self._copy_into_store(Path(replacement_pdf_path))
            cur.execute(
                "UPDATE Licenses SET licensee_id=?, file_path=?, filename=? WHERE id=?",
                (licensee_id, file_path, filename, int(record_id)),
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

    def _copy_into_store(self, source_path: Path) -> tuple[str, str]:
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        self.licenses_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{int(time.time())}_{source_path.name}"
        destination = self.licenses_dir / filename
        shutil.copy2(source_path, destination)
        return filename, str(destination.relative_to(self.data_dir))
