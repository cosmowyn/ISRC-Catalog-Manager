"""Managed asset version registry for tracks and releases."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import asdict
from pathlib import Path

try:
    from mutagen import File as MutagenFile
except Exception:  # pragma: no cover - optional at runtime in constrained environments
    MutagenFile = None

from isrc_manager.domain.repertoire import clean_text
from isrc_manager.file_storage import (
    STORAGE_MODE_DATABASE,
    STORAGE_MODE_MANAGED_FILE,
    ManagedFileStorage,
    bytes_from_blob,
    coalesce_filename,
    guess_mime_type,
    infer_storage_mode,
    normalize_storage_mode,
)

from .models import (
    ASSET_TYPE_CHOICES,
    AssetValidationIssue,
    AssetVersionPayload,
    AssetVersionRecord,
)


class AssetService:
    """Owns deliverable/asset registry rows and managed files."""

    TRACK_AUDIO_MASTER_TYPES = frozenset({"main_master", "hi_res_master", "alt_master"})

    def __init__(self, conn: sqlite3.Connection, data_root: str | Path | None = None):
        self.conn = conn
        self.data_root = Path(data_root) if data_root is not None else None
        self.asset_root = self.data_root / "asset_registry" if self.data_root is not None else None
        self.asset_store = ManagedFileStorage(data_root=data_root, relative_root="asset_registry")
        self._ensure_storage_columns()

    def _ensure_storage_columns(self) -> None:
        table_names = {
            str(row[0])
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            if row and row[0]
        }
        if "AssetVersions" not in table_names:
            return
        columns = {
            str(row[1])
            for row in self.conn.execute("PRAGMA table_info(AssetVersions)").fetchall()
            if row and row[1]
        }
        additions = (("storage_mode", "TEXT"), ("file_blob", "BLOB"))
        with self.conn:
            for column_name, column_sql in additions:
                if column_name not in columns:
                    self.conn.execute(
                        f"ALTER TABLE AssetVersions ADD COLUMN {column_name} {column_sql}"
                    )

    def _table_exists(
        self,
        table_name: str,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> bool:
        cur = cursor or self.conn.cursor()
        row = cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (str(table_name),),
        ).fetchone()
        return bool(row)

    @staticmethod
    def _clean_type(value: str | None) -> str:
        clean = str(value or "other").strip().lower().replace(" ", "_")
        if clean not in ASSET_TYPE_CHOICES:
            return "other"
        return clean

    @staticmethod
    def _row_to_record(row) -> AssetVersionRecord:
        inferred_mode = infer_storage_mode(
            explicit_mode=row[4],
            stored_path=row[3],
            blob_value=b"x" if len(row) > 19 and row[19] else None,
        )
        return AssetVersionRecord(
            id=int(row[0]),
            asset_type=str(row[1] or "other"),
            filename=str(row[2] or ""),
            stored_path=clean_text(row[3]),
            storage_mode=inferred_mode,
            checksum_sha256=clean_text(row[5]),
            duration_sec=int(row[6]) if row[6] is not None else None,
            sample_rate=int(row[7]) if row[7] is not None else None,
            bit_depth=int(row[8]) if row[8] is not None else None,
            format=clean_text(row[9]),
            derived_from_asset_id=int(row[10]) if row[10] is not None else None,
            approved_for_use=bool(row[11]),
            primary_flag=bool(row[12]),
            version_status=clean_text(row[13]),
            notes=clean_text(row[14]),
            track_id=int(row[15]) if row[15] is not None else None,
            release_id=int(row[16]) if row[16] is not None else None,
            created_at=clean_text(row[17]),
            updated_at=clean_text(row[18]),
        )

    def resolve_asset_path(self, stored_path: str | None) -> Path | None:
        return self.asset_store.resolve(stored_path)

    def _delete_unreferenced_asset_file(
        self,
        stored_path: str | None,
        *,
        cursor: sqlite3.Cursor,
    ) -> None:
        clean_path = clean_text(stored_path)
        if not clean_path or not self.asset_store.is_managed(clean_path):
            return
        row = cursor.execute(
            "SELECT 1 FROM AssetVersions WHERE stored_path=? LIMIT 1",
            (clean_path,),
        ).fetchone()
        if row:
            return
        resolved = self.resolve_asset_path(clean_path)
        if resolved is None:
            return
        try:
            resolved.unlink(missing_ok=True)
        except Exception:
            pass

    def _hash_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _extract_media_metadata(self, path: Path) -> dict[str, int | None]:
        duration_sec = None
        sample_rate = None
        bit_depth = None
        if MutagenFile is None:
            return {
                "duration_sec": duration_sec,
                "sample_rate": sample_rate,
                "bit_depth": bit_depth,
            }
        try:
            media = MutagenFile(str(path))
            info = getattr(media, "info", None)
            if info is not None:
                length = getattr(info, "length", None)
                if length is not None:
                    duration_sec = int(round(float(length)))
                sample_rate_value = getattr(info, "sample_rate", None)
                if sample_rate_value is not None:
                    sample_rate = int(sample_rate_value)
                bit_depth_value = getattr(info, "bits_per_sample", None)
                if bit_depth_value is not None:
                    bit_depth = int(bit_depth_value)
        except Exception:
            pass
        return {
            "duration_sec": duration_sec,
            "sample_rate": sample_rate,
            "bit_depth": bit_depth,
        }

    def _write_asset_file(
        self, source_path: str | Path
    ) -> tuple[str, str, str, dict[str, int | None]]:
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(source)
        if self.asset_root is None or self.data_root is None:
            raise ValueError("Asset storage is not configured.")
        suffix = source.suffix.lower()
        subdir = (
            "audio" if suffix in {".wav", ".mp3", ".flac", ".aif", ".aiff", ".m4a"} else "files"
        )
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            subdir = "images"
        destination = self.asset_store.write_bytes(
            source.read_bytes(),
            filename=source.name,
            subdir=subdir,
        )
        destination_path = self.resolve_asset_path(destination)
        if destination_path is None:
            raise ValueError("Asset storage is not configured.")
        return (
            destination,
            source.name,
            self._hash_file(destination_path),
            self._extract_media_metadata(destination_path),
        )

    def _asset_storage_mode(
        self,
        *,
        stored_path: str | None,
        blob_value: object | None,
        explicit_mode: str | None = None,
    ) -> str | None:
        return infer_storage_mode(
            explicit_mode=explicit_mode,
            stored_path=stored_path,
            blob_value=blob_value,
        )

    @staticmethod
    def _asset_subdir(filename: str) -> str:
        suffix = Path(filename).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            return "images"
        if suffix in {".wav", ".mp3", ".flac", ".aif", ".aiff", ".m4a"}:
            return "audio"
        return "files"

    def _managed_asset_bytes(
        self, path: str | Path
    ) -> tuple[str, bytes, str | None, dict[str, int | None]]:
        source = Path(path)
        if not source.exists():
            raise FileNotFoundError(source)
        filename = source.name
        data = source.read_bytes()
        return filename, data, guess_mime_type(filename), self._extract_media_metadata(source)

    def _fetch_asset_blob(self, asset_id: int) -> bytes | None:
        row = self.conn.execute(
            "SELECT file_blob FROM AssetVersions WHERE id=?",
            (int(asset_id),),
        ).fetchone()
        if not row or row[0] is None:
            return None
        return bytes_from_blob(row[0])

    def fetch_asset_bytes(self, asset_id: int) -> tuple[bytes, str]:
        row = self.conn.execute(
            """
            SELECT filename, stored_path, storage_mode, file_blob
            FROM AssetVersions
            WHERE id=?
            """,
            (int(asset_id),),
        ).fetchone()
        if not row:
            raise FileNotFoundError(f"Asset {asset_id} not found")
        filename, stored_path, storage_mode, blob_value = row
        mode = self._asset_storage_mode(
            stored_path=stored_path,
            blob_value=blob_value,
            explicit_mode=storage_mode,
        )
        if mode == STORAGE_MODE_DATABASE:
            if blob_value is None:
                raise FileNotFoundError(f"Asset {asset_id} has no database blob")
            return bytes_from_blob(blob_value), clean_text(guess_mime_type(filename))
        path = self.resolve_asset_path(stored_path)
        if path is None or not path.exists():
            raise FileNotFoundError(stored_path or f"asset {asset_id}")
        return path.read_bytes(), clean_text(guess_mime_type(filename))

    def _build_asset_payload(
        self,
        *,
        source_path: str | Path | None = None,
        data: bytes | None = None,
        filename: str | None = None,
        storage_mode: str | None = None,
    ) -> tuple[
        str | None, str, bytes | None, str | None, str | None, int | None, int | None, int | None
    ]:
        if source_path is None and data is None:
            raise ValueError("An asset source file or bytes are required.")
        clean_mode = normalize_storage_mode(storage_mode, default=STORAGE_MODE_MANAGED_FILE)
        source_name = filename or (Path(str(source_path)).name if source_path is not None else "")
        clean_filename = coalesce_filename(source_name, default_stem="asset")
        if source_path is not None:
            source = Path(source_path)
            if not source.exists():
                raise FileNotFoundError(source)
            source_bytes = source.read_bytes()
            mime = guess_mime_type(clean_filename, guess_mime_type(source.name))
            meta = self._extract_media_metadata(source)
        else:
            source_bytes = bytes_from_blob(data)
            mime = guess_mime_type(clean_filename)
            meta = {"duration_sec": None, "sample_rate": None, "bit_depth": None}

        if clean_mode == STORAGE_MODE_DATABASE:
            return (
                None,
                clean_filename,
                source_bytes,
                mime,
                None,
                meta["duration_sec"],
                meta["sample_rate"],
                meta["bit_depth"],
            )

        stored_path = self.asset_store.write_bytes(
            source_bytes,
            filename=clean_filename,
            subdir=(
                "images"
                if Path(clean_filename).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
                else (
                    "audio"
                    if Path(clean_filename).suffix.lower()
                    in {".wav", ".mp3", ".flac", ".aif", ".aiff", ".m4a"}
                    else "files"
                )
            ),
        )
        return (
            stored_path,
            clean_filename,
            None,
            mime,
            stored_path,
            meta["duration_sec"],
            meta["sample_rate"],
            meta["bit_depth"],
        )

    def validate_asset_payload(self, payload: AssetVersionPayload) -> list[str]:
        errors: list[str] = []
        if not any((payload.track_id, payload.release_id)):
            errors.append("Assets must link to either a track or a release.")
        if not clean_text(payload.filename) and not clean_text(payload.source_path):
            errors.append("Assets require a filename or a source file.")
        return errors

    def create_asset(
        self,
        payload: AssetVersionPayload,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> int:
        errors = self.validate_asset_payload(payload)
        if errors:
            raise ValueError("\n".join(errors))
        existing_path = clean_text(payload.stored_path)
        filename = clean_text(payload.filename)
        checksum = clean_text(payload.checksum_sha256)
        duration_sec = payload.duration_sec
        sample_rate = payload.sample_rate
        bit_depth = payload.bit_depth
        blob_value = None
        storage_mode = normalize_storage_mode(payload.storage_mode, default=None)
        if clean_text(payload.source_path):
            source = Path(str(payload.source_path).strip())
            if not source.exists():
                raise FileNotFoundError(source)
            source_name = filename or source.name
            filename = coalesce_filename(source_name, default_stem="asset")
            source_bytes = source.read_bytes()
            checksum = checksum or self._hash_file(source)
            meta = self._extract_media_metadata(source)
            duration_sec = duration_sec if duration_sec is not None else meta["duration_sec"]
            sample_rate = sample_rate if sample_rate is not None else meta["sample_rate"]
            bit_depth = bit_depth if bit_depth is not None else meta["bit_depth"]
            if storage_mode is None:
                storage_mode = STORAGE_MODE_MANAGED_FILE
            if storage_mode == STORAGE_MODE_DATABASE:
                blob_value = sqlite3.Binary(source_bytes)
                existing_path = None
            else:
                existing_path = self.asset_store.write_bytes(
                    source_bytes,
                    filename=filename,
                    subdir=self._asset_subdir(filename),
                )
                blob_value = None
                storage_mode = STORAGE_MODE_MANAGED_FILE
        elif storage_mode == STORAGE_MODE_DATABASE and clean_text(existing_path):
            # Legacy callers may request DB mode while only supplying a stored path.
            source_path = self.resolve_asset_path(existing_path)
            if source_path is None or not source_path.exists():
                raise FileNotFoundError(existing_path)
            source_bytes = source_path.read_bytes()
            blob_value = sqlite3.Binary(source_bytes)
        elif storage_mode == STORAGE_MODE_MANAGED_FILE and clean_text(existing_path):
            blob_value = None
        elif storage_mode is None:
            storage_mode = STORAGE_MODE_MANAGED_FILE if clean_text(existing_path) else None
        if not filename:
            filename = Path(existing_path or payload.source_path or "asset").name

        def _create(cur: sqlite3.Cursor) -> int:
            cur.execute(
                """
                INSERT INTO AssetVersions (
                    track_id,
                    release_id,
                    asset_type,
                    filename,
                    stored_path,
                    storage_mode,
                    file_blob,
                    checksum_sha256,
                    duration_sec,
                    sample_rate,
                    bit_depth,
                    format,
                    derived_from_asset_id,
                    approved_for_use,
                    primary_flag,
                    version_status,
                    notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.track_id,
                    payload.release_id,
                    self._clean_type(payload.asset_type),
                    str(filename or ""),
                    existing_path,
                    storage_mode,
                    blob_value,
                    checksum,
                    duration_sec,
                    sample_rate,
                    bit_depth,
                    clean_text(payload.format) or (Path(filename or "").suffix.lstrip(".") or None),
                    payload.derived_from_asset_id,
                    1 if payload.approved_for_use else 0,
                    1 if payload.primary_flag else 0,
                    clean_text(payload.version_status),
                    clean_text(payload.notes),
                ),
            )
            asset_id = int(cur.lastrowid)
            if payload.primary_flag:
                self.mark_primary(asset_id, cursor=cur)
            return asset_id

        if cursor is not None:
            return _create(cursor)

        with self.conn:
            return _create(self.conn.cursor())

    def update_asset(
        self,
        asset_id: int,
        payload: AssetVersionPayload,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> None:
        errors = self.validate_asset_payload(payload)
        if errors:
            raise ValueError("\n".join(errors))
        existing = self.fetch_asset(int(asset_id), cursor=cursor)
        if existing is None:
            raise ValueError("Asset not found.")
        stored_path = clean_text(payload.stored_path) or existing.stored_path
        filename = clean_text(payload.filename) or existing.filename
        checksum = clean_text(payload.checksum_sha256) or existing.checksum_sha256
        duration_sec = (
            payload.duration_sec if payload.duration_sec is not None else existing.duration_sec
        )
        sample_rate = (
            payload.sample_rate if payload.sample_rate is not None else existing.sample_rate
        )
        bit_depth = payload.bit_depth if payload.bit_depth is not None else existing.bit_depth
        storage_mode = normalize_storage_mode(payload.storage_mode, default=existing.storage_mode)
        blob_value = self._fetch_asset_blob(int(asset_id))
        previous_stored_path = clean_text(existing.stored_path)
        if clean_text(payload.source_path):
            source = Path(str(payload.source_path).strip())
            if not source.exists():
                raise FileNotFoundError(source)
            filename = coalesce_filename(filename or source.name, default_stem="asset")
            source_bytes = source.read_bytes()
            checksum = clean_text(payload.checksum_sha256) or self._hash_file(source)
            meta = self._extract_media_metadata(source)
            duration_sec = (
                payload.duration_sec if payload.duration_sec is not None else meta["duration_sec"]
            )
            sample_rate = (
                payload.sample_rate if payload.sample_rate is not None else meta["sample_rate"]
            )
            bit_depth = payload.bit_depth if payload.bit_depth is not None else meta["bit_depth"]
            if storage_mode == STORAGE_MODE_DATABASE:
                stored_path = None
                blob_value = sqlite3.Binary(source_bytes)
            else:
                stored_path = self.asset_store.write_bytes(
                    source_bytes,
                    filename=filename,
                    subdir=self._asset_subdir(filename),
                )
                blob_value = None
                storage_mode = STORAGE_MODE_MANAGED_FILE
        elif storage_mode == STORAGE_MODE_DATABASE and blob_value is None and stored_path:
            path = self.resolve_asset_path(stored_path)
            if path is None or not path.exists():
                raise FileNotFoundError(stored_path)
            blob_value = sqlite3.Binary(path.read_bytes())
        elif storage_mode == STORAGE_MODE_MANAGED_FILE and blob_value is not None:
            stored_path = self.asset_store.write_bytes(
                bytes_from_blob(blob_value),
                filename=filename,
                subdir=self._asset_subdir(filename),
            )
            blob_value = None

        def _update(cur: sqlite3.Cursor) -> None:
            cur.execute(
                """
                UPDATE AssetVersions
                SET track_id=?,
                    release_id=?,
                    asset_type=?,
                    filename=?,
                    stored_path=?,
                    storage_mode=?,
                    file_blob=?,
                    checksum_sha256=?,
                    duration_sec=?,
                    sample_rate=?,
                    bit_depth=?,
                    format=?,
                    derived_from_asset_id=?,
                    approved_for_use=?,
                    primary_flag=?,
                    version_status=?,
                    notes=?,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (
                    payload.track_id,
                    payload.release_id,
                    self._clean_type(payload.asset_type),
                    str(filename or ""),
                    stored_path,
                    storage_mode,
                    blob_value,
                    checksum,
                    duration_sec,
                    sample_rate,
                    bit_depth,
                    clean_text(payload.format) or existing.format,
                    payload.derived_from_asset_id,
                    1 if payload.approved_for_use else 0,
                    1 if payload.primary_flag else 0,
                    clean_text(payload.version_status),
                    clean_text(payload.notes),
                    int(asset_id),
                ),
            )
            if payload.primary_flag:
                self.mark_primary(int(asset_id), cursor=cur)
            if previous_stored_path and previous_stored_path != clean_text(stored_path):
                self._delete_unreferenced_asset_file(previous_stored_path, cursor=cur)

        if cursor is not None:
            _update(cursor)
            return

        with self.conn:
            _update(self.conn.cursor())

    def mark_primary(
        self,
        asset_id: int,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> None:
        asset = self.fetch_asset(int(asset_id), cursor=cursor)
        if asset is None:
            raise ValueError("Asset not found.")

        def _mark(cur: sqlite3.Cursor) -> None:
            if asset.track_id is not None:
                cur.execute(
                    "UPDATE AssetVersions SET primary_flag=0 WHERE track_id=?",
                    (int(asset.track_id),),
                )
            if asset.release_id is not None:
                cur.execute(
                    "UPDATE AssetVersions SET primary_flag=0 WHERE release_id=?",
                    (int(asset.release_id),),
                )
            cur.execute(
                "UPDATE AssetVersions SET primary_flag=1 WHERE id=?",
                (int(asset_id),),
            )

        if cursor is not None:
            _mark(cursor)
            return

        with self.conn:
            _mark(self.conn.cursor())

    def fetch_asset(
        self,
        asset_id: int,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> AssetVersionRecord | None:
        cur = cursor or self.conn.cursor()
        row = cur.execute(
            """
            SELECT
                id,
                asset_type,
                filename,
                stored_path,
                storage_mode,
                checksum_sha256,
                duration_sec,
                sample_rate,
                bit_depth,
                format,
                derived_from_asset_id,
                approved_for_use,
                primary_flag,
                version_status,
                notes,
                track_id,
                release_id,
                created_at,
                updated_at,
                CASE WHEN file_blob IS NOT NULL THEN 1 ELSE 0 END AS has_blob
            FROM AssetVersions
            WHERE id=?
            """,
            (int(asset_id),),
        ).fetchone()
        return self._row_to_record(row) if row else None

    def list_assets(
        self,
        *,
        track_id: int | None = None,
        release_id: int | None = None,
        search_text: str | None = None,
        cursor: sqlite3.Cursor | None = None,
    ) -> list[AssetVersionRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if track_id is not None:
            clauses.append("track_id=?")
            params.append(int(track_id))
        if release_id is not None:
            clauses.append("release_id=?")
            params.append(int(release_id))
        clean_search = clean_text(search_text)
        if clean_search:
            like = f"%{clean_search}%"
            clauses.append(
                "(filename LIKE ? OR COALESCE(asset_type, '') LIKE ? OR COALESCE(version_status, '') LIKE ?)"
            )
            params.extend([like, like, like])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cur = cursor or self.conn.cursor()
        rows = cur.execute(
            f"""
            SELECT
                id,
                asset_type,
                filename,
                stored_path,
                storage_mode,
                checksum_sha256,
                duration_sec,
                sample_rate,
                bit_depth,
                format,
                derived_from_asset_id,
                approved_for_use,
                primary_flag,
                version_status,
                notes,
                track_id,
                release_id,
                created_at,
                updated_at,
                CASE WHEN file_blob IS NOT NULL THEN 1 ELSE 0 END AS has_blob
            FROM AssetVersions
            {where}
            ORDER BY COALESCE(track_id, release_id), primary_flag DESC, asset_type, id
            """,
            params,
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def sync_track_audio_attachment(
        self,
        *,
        track_id: int,
        source_path: str | Path,
        storage_mode: str | None,
        cursor: sqlite3.Cursor | None = None,
    ) -> AssetVersionRecord | None:
        if not self._table_exists("AssetVersions", cursor=cursor):
            return None
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(source)
        cur = cursor or self.conn.cursor()
        checksum = self._hash_file(source)
        clean_mode = normalize_storage_mode(storage_mode, default=STORAGE_MODE_MANAGED_FILE)
        master_assets = [
            asset
            for asset in self.list_assets(track_id=int(track_id), cursor=cur)
            if asset.asset_type in self.TRACK_AUDIO_MASTER_TYPES
        ]
        master_assets.sort(key=lambda item: (0 if item.primary_flag else 1, -int(item.id)))
        current_primary = master_assets[0] if master_assets else None

        if current_primary is not None and clean_text(current_primary.checksum_sha256) == checksum:
            self.update_asset(
                int(current_primary.id),
                AssetVersionPayload(
                    asset_type=current_primary.asset_type or "main_master",
                    source_path=str(source),
                    storage_mode=clean_mode,
                    checksum_sha256=checksum,
                    approved_for_use=bool(current_primary.approved_for_use),
                    primary_flag=True,
                    version_status=current_primary.version_status or "approved",
                    notes=current_primary.notes,
                    track_id=int(track_id),
                    release_id=current_primary.release_id,
                    derived_from_asset_id=current_primary.derived_from_asset_id,
                ),
                cursor=cur,
            )
            return self.fetch_asset(int(current_primary.id), cursor=cur)

        asset_id = self.create_asset(
            AssetVersionPayload(
                asset_type=(current_primary.asset_type if current_primary else "main_master"),
                source_path=str(source),
                storage_mode=clean_mode,
                checksum_sha256=checksum,
                derived_from_asset_id=(int(current_primary.id) if current_primary else None),
                approved_for_use=(
                    bool(current_primary.approved_for_use) if current_primary else True
                ),
                primary_flag=True,
                version_status=(
                    (current_primary.version_status or "approved")
                    if current_primary
                    else "approved"
                ),
                notes=current_primary.notes if current_primary else None,
                track_id=int(track_id),
                release_id=current_primary.release_id if current_primary else None,
            ),
            cursor=cur,
        )
        return self.fetch_asset(int(asset_id), cursor=cur)

    def delete_asset(self, asset_id: int) -> None:
        asset = self.fetch_asset(int(asset_id))
        with self.conn:
            self.conn.execute("DELETE FROM AssetVersions WHERE id=?", (int(asset_id),))
        if asset is not None:
            if asset.storage_mode == STORAGE_MODE_MANAGED_FILE or (
                asset.storage_mode is None and asset.stored_path
            ):
                path = self.resolve_asset_path(asset.stored_path)
            else:
                path = None
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass

    def convert_asset_storage_mode(self, asset_id: int, target_mode: str) -> AssetVersionRecord:
        asset = self.fetch_asset(int(asset_id))
        if asset is None:
            raise ValueError("Asset not found.")
        clean_target = normalize_storage_mode(target_mode)
        current_mode = normalize_storage_mode(asset.storage_mode, default=None)
        if current_mode == clean_target:
            return asset
        data, mime_type = self.fetch_asset_bytes(int(asset_id))
        filename = asset.filename or Path(asset.stored_path or "").name or f"asset-{asset.id}"
        if clean_target == STORAGE_MODE_DATABASE:
            with self.conn:
                self.conn.execute(
                    """
                    UPDATE AssetVersions
                    SET storage_mode=?,
                        file_blob=?,
                        stored_path=NULL,
                        updated_at=datetime('now')
                    WHERE id=?
                    """,
                    (clean_target, sqlite3.Binary(data), int(asset_id)),
                )
                if asset.stored_path:
                    path = self.resolve_asset_path(asset.stored_path)
                    if path is not None and path.exists():
                        try:
                            path.unlink(missing_ok=True)
                        except Exception:
                            pass
        else:
            stored_path = self.asset_store.write_bytes(
                data,
                filename=filename,
                subdir=self._asset_subdir(filename),
            )
            with self.conn:
                self.conn.execute(
                    """
                    UPDATE AssetVersions
                    SET storage_mode=?,
                        stored_path=?,
                        file_blob=NULL,
                        updated_at=datetime('now')
                    WHERE id=?
                    """,
                    (clean_target, stored_path, int(asset_id)),
                )
        updated = self.fetch_asset(int(asset_id))
        if updated is None:
            raise RuntimeError("Asset disappeared after conversion.")
        return updated

    def validate_assets(self) -> list[AssetValidationIssue]:
        issues: list[AssetValidationIssue] = []
        assets = self.list_assets()
        by_track: dict[int, list[AssetVersionRecord]] = {}
        by_release: dict[int, list[AssetVersionRecord]] = {}
        for asset in assets:
            if asset.storage_mode == STORAGE_MODE_DATABASE:
                if self._fetch_asset_blob(asset.id) is None:
                    issues.append(
                        AssetValidationIssue(
                            severity="error",
                            issue_type="broken_asset_reference",
                            asset_id=asset.id,
                            message="Asset blob is missing from the database.",
                        )
                    )
            else:
                path = self.resolve_asset_path(asset.stored_path)
                if asset.stored_path and (path is None or not path.exists()):
                    issues.append(
                        AssetValidationIssue(
                            severity="error",
                            issue_type="broken_asset_reference",
                            asset_id=asset.id,
                            message=f"Asset file is missing: {asset.stored_path}",
                        )
                    )
            if asset.track_id is not None:
                by_track.setdefault(asset.track_id, []).append(asset)
            if asset.release_id is not None:
                by_release.setdefault(asset.release_id, []).append(asset)
        for group in list(by_track.values()) + list(by_release.values()):
            primary_assets = [asset for asset in group if asset.primary_flag]
            if len(primary_assets) > 1:
                for asset in primary_assets:
                    issues.append(
                        AssetValidationIssue(
                            severity="error",
                            issue_type="duplicate_primary_asset",
                            asset_id=asset.id,
                            message="Multiple assets are marked as primary for the same item.",
                        )
                    )
            master_assets = [
                asset
                for asset in group
                if asset.asset_type in {"main_master", "hi_res_master", "alt_master"}
            ]
            if master_assets and not any(
                asset.approved_for_use and asset.asset_type in {"main_master", "hi_res_master"}
                for asset in master_assets
            ):
                issues.append(
                    AssetValidationIssue(
                        severity="warning",
                        issue_type="missing_approved_master",
                        asset_id=master_assets[0].id,
                        message="No approved main or hi-res master is registered for this item.",
                    )
                )
        return issues

    def export_rows(self) -> list[dict[str, object]]:
        return [asdict(item) for item in self.list_assets()]
