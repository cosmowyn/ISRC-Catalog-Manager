"""CSV/XLSX/JSON exchange helpers with deterministic schemas and reports."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook, load_workbook

from isrc_manager.domain.codes import is_blank, to_compact_isrc, to_iso_isrc
from isrc_manager.domain.timecode import parse_hms_text, seconds_to_hms
from isrc_manager.file_storage import coalesce_filename, infer_storage_mode
from isrc_manager.releases import ReleasePayload, ReleaseService, ReleaseTrackPlacement
from isrc_manager.services.custom_fields import CustomFieldDefinitionService
from isrc_manager.services.tracks import TrackCreatePayload, TrackService, TrackUpdatePayload

from .models import ExchangeImportOptions, ExchangeImportReport, ExchangeInspection

JSON_SCHEMA_VERSION = 1
CSV_SNIFF_SAMPLE_SIZE = 4096


class ExchangeService:
    """Owns tabular and JSON import/export workflows."""

    BASE_EXPORT_COLUMNS = (
        "track_id",
        "isrc",
        "track_title",
        "artist_name",
        "additional_artists",
        "album_title",
        "release_date",
        "track_length_sec",
        "track_length_hms",
        "iswc",
        "upc",
        "genre",
        "catalog_number",
        "buma_work_number",
        "composer",
        "publisher",
        "comments",
        "lyrics",
        "audio_file_path",
        "audio_file_storage_mode",
        "album_art_path",
        "album_art_storage_mode",
        "release_id",
        "release_title",
        "release_version_subtitle",
        "release_primary_artist",
        "release_album_artist",
        "release_type",
        "release_date_release",
        "release_original_release_date",
        "release_label",
        "release_sublabel",
        "release_catalog_number",
        "release_upc",
        "release_barcode_validation_status",
        "release_territory",
        "release_explicit_flag",
        "release_notes",
        "release_artwork_path",
        "release_artwork_storage_mode",
        "disc_number",
        "track_number",
        "sequence_number",
        "license_files",
    )

    def __init__(
        self,
        conn: sqlite3.Connection,
        track_service: TrackService,
        release_service: ReleaseService,
        custom_fields: CustomFieldDefinitionService,
        data_root: str | Path | None = None,
    ):
        self.conn = conn
        self.track_service = track_service
        self.release_service = release_service
        self.custom_fields = custom_fields
        self.data_root = Path(data_root) if data_root is not None else None

    @staticmethod
    def _normalize_header_name(name: str) -> str:
        return str(name or "").strip().lower().replace(" ", "_")

    def _release_columns_for_track_rows(self) -> dict[int, dict[str, object]]:
        release_rows = self.conn.execute(
            """
            SELECT
                rt.track_id,
                r.id,
                r.title,
                r.version_subtitle,
                r.primary_artist,
                r.album_artist,
                r.release_type,
                r.release_date,
                r.original_release_date,
                r.label,
                r.sublabel,
                r.catalog_number,
                r.upc,
                r.barcode_validation_status,
                r.territory,
                r.explicit_flag,
                r.release_notes,
                r.artwork_path,
                r.artwork_storage_mode,
                CASE WHEN r.artwork_blob IS NOT NULL THEN 1 ELSE 0 END,
                rt.disc_number,
                rt.track_number,
                rt.sequence_number
            FROM ReleaseTracks rt
            JOIN Releases r ON r.id = rt.release_id
            ORDER BY rt.track_id, rt.sequence_number, rt.release_id
            """
        ).fetchall()
        by_track: dict[int, list[dict[str, object]]] = {}
        for row in release_rows:
            by_track.setdefault(int(row[0]), []).append(
                {
                    "release_id": int(row[1]),
                    "release_title": row[2] or "",
                    "release_version_subtitle": row[3] or "",
                    "release_primary_artist": row[4] or "",
                    "release_album_artist": row[5] or "",
                    "release_type": row[6] or "",
                    "release_date_release": row[7] or "",
                    "release_original_release_date": row[8] or "",
                    "release_label": row[9] or "",
                    "release_sublabel": row[10] or "",
                    "release_catalog_number": row[11] or "",
                    "release_upc": row[12] or "",
                    "release_barcode_validation_status": row[13] or "",
                    "release_territory": row[14] or "",
                    "release_explicit_flag": int(row[15] or 0),
                    "release_notes": row[16] or "",
                    "release_artwork_path": row[17] or "",
                    "release_artwork_storage_mode": infer_storage_mode(
                        explicit_mode=row[18],
                        stored_path=row[17],
                        blob_value=b"\x00" if int(row[19] or 0) else None,
                    )
                    or "",
                    "disc_number": int(row[20] or 1),
                    "track_number": int(row[21] or 1),
                    "sequence_number": int(row[22] or 1),
                }
            )
        return by_track

    def _custom_field_maps(self) -> tuple[list[dict], dict[tuple[int, int], str]]:
        defs = self.custom_fields.list_active_fields()
        value_rows = self.conn.execute(
            """
            SELECT track_id, field_def_id, value
            FROM CustomFieldValues
            """
        ).fetchall()
        value_map = {
            (int(track_id), int(field_def_id)): ("" if value is None else str(value))
            for track_id, field_def_id, value in value_rows
        }
        return defs, value_map

    def _license_map(self) -> dict[int, str]:
        rows = self.conn.execute(
            """
            SELECT track_id, filename
            FROM Licenses
            ORDER BY track_id, filename
            """
        ).fetchall()
        license_map: dict[int, list[str]] = {}
        for track_id, filename in rows:
            license_map.setdefault(int(track_id), []).append(str(filename or ""))
        return {track_id: "; ".join(values) for track_id, values in license_map.items()}

    def _effective_track_media_paths(self, track_id: int) -> tuple[str, str]:
        audio_meta = self.track_service.get_media_meta(int(track_id), "audio_file")
        artwork_meta = self.track_service.get_media_meta(int(track_id), "album_art")
        return (
            str(audio_meta.get("path") or "").strip(),
            str(artwork_meta.get("path") or "").strip(),
        )

    @staticmethod
    def _synthetic_media_key(*parts: object, filename: str, default_stem: str) -> str:
        clean_parts = [str(part).strip().strip("/") for part in parts if str(part).strip()]
        clean_filename = coalesce_filename(filename, default_stem=default_stem)
        return "/".join([*clean_parts, clean_filename])

    def _resolve_packaged_media_source(self, stored_path: str) -> Path | None:
        clean_path = str(stored_path or "").strip()
        if not clean_path:
            return None
        path = Path(clean_path)
        if path.is_absolute():
            return path
        if self.data_root is None:
            return None
        return self.data_root / path

    @staticmethod
    def _package_media_arcname(stored_path: str) -> str:
        clean_path = str(stored_path or "").strip()
        path = Path(clean_path)
        if path.is_absolute():
            digest = hashlib.sha1(clean_path.encode("utf-8")).hexdigest()[:12]
            return f"media/external/{digest}_{path.name}"
        return f"media/{path.as_posix()}"

    def _package_track_media(
        self,
        archive: ZipFile,
        *,
        row: dict[str, object],
        field_name: str,
        track_id: int,
        media_key: str,
        written_media: set[str],
        packaged_media_index: dict[str, str],
    ) -> None:
        meta = self.track_service.get_media_meta(int(track_id), media_key)
        if not bool(meta.get("has_media")):
            return
        package_key = str(meta.get("path") or "").strip()
        if not package_key:
            owner_scope = str(meta.get("owner_scope") or "track")
            owner_id = meta.get("owner_id") or track_id
            package_key = self._synthetic_media_key(
                "embedded",
                owner_scope,
                owner_id,
                media_key,
                filename=str(meta.get("filename") or ""),
                default_stem=media_key.replace("_", "-"),
            )
        arcname = self._package_media_arcname(package_key)
        if arcname not in written_media:
            stored_path = str(meta.get("path") or "").strip()
            if stored_path:
                abs_path = self._resolve_packaged_media_source(stored_path)
                if abs_path is not None and abs_path.exists():
                    archive.write(abs_path, arcname=arcname)
                else:
                    data, _ = self.track_service.fetch_media_bytes(int(track_id), media_key)
                    archive.writestr(arcname, data)
            else:
                data, _ = self.track_service.fetch_media_bytes(int(track_id), media_key)
                archive.writestr(arcname, data)
            written_media.add(arcname)
        packaged_media_index[package_key] = arcname
        row[field_name] = package_key
        row[field_name.replace("_path", "_storage_mode")] = str(meta.get("storage_mode") or "")

    def _package_release_artwork(
        self,
        archive: ZipFile,
        *,
        row: dict[str, object],
        written_media: set[str],
        packaged_media_index: dict[str, str],
    ) -> None:
        try:
            release_id = int(row.get("release_id") or 0)
        except Exception:
            release_id = 0
        if release_id <= 0:
            return
        release = self.release_service.fetch_release(release_id)
        if release is None:
            return
        storage_mode = str(release.artwork_storage_mode or "").strip()
        stored_path = str(release.artwork_path or "").strip()
        if not storage_mode and not stored_path:
            return
        package_key = stored_path
        if not package_key:
            package_key = self._synthetic_media_key(
                "embedded",
                "release",
                release_id,
                "artwork",
                filename=release.artwork_filename or "",
                default_stem="release-artwork",
            )
        arcname = self._package_media_arcname(package_key)
        if arcname not in written_media:
            if stored_path:
                abs_path = self._resolve_packaged_media_source(stored_path)
                if abs_path is not None and abs_path.exists():
                    archive.write(abs_path, arcname=arcname)
                else:
                    data, _ = self.release_service.fetch_artwork_bytes(release_id)
                    archive.writestr(arcname, data)
            else:
                data, _ = self.release_service.fetch_artwork_bytes(release_id)
                archive.writestr(arcname, data)
            written_media.add(arcname)
        packaged_media_index[package_key] = arcname
        row["release_artwork_path"] = package_key
        row["release_artwork_storage_mode"] = storage_mode

    def export_rows(
        self, track_ids: list[int] | None = None
    ) -> tuple[list[str], list[dict[str, object]]]:
        where_clause = ""
        params: list[object] = []
        if track_ids:
            placeholders = ",".join("?" * len(track_ids))
            where_clause = f"WHERE t.id IN ({placeholders})"
            params.extend(int(track_id) for track_id in track_ids)

        rows = self.conn.execute(
            f"""
            SELECT
                t.id,
                t.isrc,
                t.track_title,
                COALESCE(a.name, '') AS artist_name,
                COALESCE((
                    SELECT GROUP_CONCAT(ar.name, ', ')
                    FROM TrackArtists ta
                    JOIN Artists ar ON ar.id = ta.artist_id
                    WHERE ta.track_id = t.id AND ta.role = 'additional'
                ), '') AS additional_artists,
                COALESCE(al.title, '') AS album_title,
                COALESCE(t.release_date, '') AS release_date,
                COALESCE(t.track_length_sec, 0) AS track_length_sec,
                COALESCE(t.iswc, '') AS iswc,
                COALESCE(t.upc, '') AS upc,
                COALESCE(t.genre, '') AS genre,
                COALESCE(t.catalog_number, '') AS catalog_number,
                COALESCE(t.buma_work_number, '') AS buma_work_number,
                COALESCE(t.composer, '') AS composer,
                COALESCE(t.publisher, '') AS publisher,
                COALESCE(t.comments, '') AS comments,
                COALESCE(t.lyrics, '') AS lyrics,
                COALESCE(t.audio_file_path, '') AS audio_file_path,
                COALESCE(t.album_art_path, '') AS album_art_path
            FROM Tracks t
            LEFT JOIN Artists a ON a.id = t.main_artist_id
            LEFT JOIN Albums al ON al.id = t.album_id
            {where_clause}
            ORDER BY t.id
            """,
            params,
        ).fetchall()

        defs, custom_map = self._custom_field_maps()
        custom_headers = [
            f"custom::{field['name']}"
            for field in defs
            if field["field_type"] not in {"blob_image", "blob_audio"}
        ]
        headers = list(self.BASE_EXPORT_COLUMNS) + custom_headers
        release_map = self._release_columns_for_track_rows()
        license_map = self._license_map()

        exported_rows: list[dict[str, object]] = []
        for row in rows:
            track_id = int(row[0])
            audio_meta = self.track_service.get_media_meta(track_id, "audio_file")
            artwork_meta = self.track_service.get_media_meta(track_id, "album_art")
            effective_audio_path = str(audio_meta.get("path") or "").strip()
            effective_album_art_path = str(artwork_meta.get("path") or "").strip()
            base = {
                "track_id": track_id,
                "isrc": row[1] or "",
                "track_title": row[2] or "",
                "artist_name": row[3] or "",
                "additional_artists": row[4] or "",
                "album_title": row[5] or "",
                "release_date": row[6] or "",
                "track_length_sec": int(row[7] or 0),
                "track_length_hms": seconds_to_hms(int(row[7] or 0)),
                "iswc": row[8] or "",
                "upc": row[9] or "",
                "genre": row[10] or "",
                "catalog_number": row[11] or "",
                "buma_work_number": row[12] or "",
                "composer": row[13] or "",
                "publisher": row[14] or "",
                "comments": row[15] or "",
                "lyrics": row[16] or "",
                "audio_file_path": effective_audio_path,
                "audio_file_storage_mode": str(audio_meta.get("storage_mode") or ""),
                "album_art_path": effective_album_art_path,
                "album_art_storage_mode": str(artwork_meta.get("storage_mode") or ""),
                "license_files": license_map.get(track_id, ""),
            }
            placements = release_map.get(track_id) or [
                {
                    "release_id": "",
                    "release_title": "",
                    "release_version_subtitle": "",
                    "release_primary_artist": "",
                    "release_album_artist": "",
                    "release_type": "",
                    "release_date_release": "",
                    "release_original_release_date": "",
                    "release_label": "",
                    "release_sublabel": "",
                    "release_catalog_number": "",
                    "release_upc": "",
                    "release_barcode_validation_status": "",
                    "release_territory": "",
                    "release_explicit_flag": 0,
                    "release_notes": "",
                    "release_artwork_path": "",
                    "release_artwork_storage_mode": "",
                    "disc_number": "",
                    "track_number": "",
                    "sequence_number": "",
                }
            ]
            for placement in placements:
                export_row = dict(base)
                export_row.update(placement)
                for field in defs:
                    if field["field_type"] in {"blob_image", "blob_audio"}:
                        continue
                    export_row[f"custom::{field['name']}"] = custom_map.get(
                        (track_id, int(field["id"])), ""
                    )
                exported_rows.append(export_row)
        return headers, exported_rows

    def export_csv(self, path: str | Path, track_ids: list[int] | None = None) -> int:
        headers, rows = self.export_rows(track_ids)
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
        return len(rows)

    def export_xlsx(self, path: str | Path, track_ids: list[int] | None = None) -> int:
        headers, rows = self.export_rows(track_ids)
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "CatalogExport"
        sheet.append(headers)
        for row in rows:
            sheet.append([row.get(header, "") for header in headers])
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(output_path)
        return len(rows)

    def export_json(self, path: str | Path, track_ids: list[int] | None = None) -> int:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        headers, rows = self.export_rows(track_ids)
        payload = {
            "schema_version": JSON_SCHEMA_VERSION,
            "exported_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "columns": headers,
            "rows": rows,
            "custom_field_defs": self.custom_fields.list_active_fields(),
        }
        output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return len(rows)

    def export_package(self, path: str | Path, track_ids: list[int] | None = None) -> int:
        zip_path = Path(path)
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        headers, rows = self.export_rows(track_ids)
        packaged_media_index: dict[str, str] = {}
        with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
            written_media: set[str] = set()
            for row in rows:
                try:
                    track_id = int(row.get("track_id") or 0)
                except Exception:
                    track_id = 0
                if track_id > 0:
                    self._package_track_media(
                        archive,
                        row=row,
                        field_name="audio_file_path",
                        track_id=track_id,
                        media_key="audio_file",
                        written_media=written_media,
                        packaged_media_index=packaged_media_index,
                    )
                    self._package_track_media(
                        archive,
                        row=row,
                        field_name="album_art_path",
                        track_id=track_id,
                        media_key="album_art",
                        written_media=written_media,
                        packaged_media_index=packaged_media_index,
                    )
                self._package_release_artwork(
                    archive,
                    row=row,
                    written_media=written_media,
                    packaged_media_index=packaged_media_index,
                )
            payload = {
                "schema_version": JSON_SCHEMA_VERSION,
                "exported_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "columns": headers,
                "rows": rows,
                "custom_field_defs": self.custom_fields.list_active_fields(),
                "packaged_media": True,
                "packaged_media_index": packaged_media_index,
            }
            archive.writestr("manifest.json", json.dumps(payload, indent=2, ensure_ascii=False))
        return len(rows)

    def _load_json_payload(self, path: str | Path) -> dict[str, object]:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        schema_version = int(payload.get("schema_version") or 0)
        if schema_version != JSON_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported JSON schema version {schema_version}. Expected {JSON_SCHEMA_VERSION}."
            )
        return payload

    def _load_package_payload(self, path: str | Path) -> dict[str, object]:
        with ZipFile(path, "r") as archive:
            try:
                manifest_bytes = archive.read("manifest.json")
            except KeyError as exc:
                raise ValueError("ZIP package does not contain manifest.json.") from exc
        payload = json.loads(manifest_bytes.decode("utf-8"))
        schema_version = int(payload.get("schema_version") or 0)
        if schema_version != JSON_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported package schema version {schema_version}. Expected {JSON_SCHEMA_VERSION}."
            )
        return payload

    @staticmethod
    def _safe_extract_zip(path: str | Path, target_dir: Path) -> None:
        target_root = target_dir.resolve()
        with ZipFile(path, "r") as archive:
            for member in archive.infolist():
                member_name = str(member.filename or "")
                destination = (target_root / member_name).resolve()
                try:
                    destination.relative_to(target_root)
                except ValueError as exc:
                    raise ValueError(f"ZIP package contains an unsafe path: {member_name}") from exc
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member, "r") as src, destination.open("wb") as dst:
                    shutil.copyfileobj(src, dst)

    @staticmethod
    def _normalize_package_media_key(value: object) -> str:
        return str(value or "").strip().replace("\\", "/")

    def _prepare_packaged_rows(
        self,
        payload: dict[str, object],
        *,
        extracted_root: Path,
    ) -> list[dict[str, object]]:
        packaged_media_index = payload.get("packaged_media_index")
        media_lookup: dict[str, str] = {}
        if isinstance(packaged_media_index, dict):
            for stored_path, arcname in packaged_media_index.items():
                key = self._normalize_package_media_key(stored_path)
                arc = str(arcname or "").strip()
                if key and arc:
                    media_lookup[key] = arc

        prepared_rows: list[dict[str, object]] = []
        for source_row in payload.get("rows") or []:
            row = dict(source_row)
            for field_name in ("audio_file_path", "album_art_path", "release_artwork_path"):
                raw_value = row.get(field_name)
                normalized_key = self._normalize_package_media_key(raw_value)
                if not normalized_key:
                    continue
                resolved_path = None
                if normalized_key in media_lookup:
                    candidate = extracted_root / media_lookup[normalized_key]
                    if candidate.exists():
                        resolved_path = candidate
                if resolved_path is None:
                    direct_candidate = extracted_root / normalized_key
                    if direct_candidate.exists():
                        resolved_path = direct_candidate
                if resolved_path is None:
                    media_candidate = extracted_root / "media" / normalized_key
                    if media_candidate.exists():
                        resolved_path = media_candidate
                if resolved_path is not None:
                    row[field_name] = str(resolved_path)
            prepared_rows.append(row)
        return prepared_rows

    @contextmanager
    def _open_csv_dict_reader(
        self, path: str | Path, *, delimiter: str | None = None
    ) -> Iterator[csv.DictReader]:
        with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
            sample = handle.read(CSV_SNIFF_SAMPLE_SIZE)
            handle.seek(0)
            if delimiter is not None:
                yield csv.DictReader(handle, delimiter=delimiter)
                return
            try:
                dialect = (
                    csv.Sniffer().sniff(sample, delimiters=",;")
                    if sample.strip()
                    else csv.excel
                )
            except csv.Error:
                dialect = csv.excel
            yield csv.DictReader(handle, dialect=dialect)

    def inspect_csv(self, path: str | Path, *, delimiter: str | None = None) -> ExchangeInspection:
        with self._open_csv_dict_reader(path, delimiter=delimiter) as reader:
            headers = list(reader.fieldnames or [])
            preview_rows = []
            for _, row in zip(range(5), reader):
                preview_rows.append(dict(row))
        return ExchangeInspection(
            file_path=str(path),
            format_name="csv",
            headers=headers,
            preview_rows=preview_rows,
            suggested_mapping=self._suggest_mapping(headers),
        )

    def inspect_xlsx(self, path: str | Path) -> ExchangeInspection:
        workbook = load_workbook(filename=str(path), read_only=True, data_only=True)
        sheet = workbook.active
        rows = list(sheet.iter_rows(values_only=True))
        headers = [str(value or "").strip() for value in (rows[0] if rows else ())]
        preview_rows = []
        for row in rows[1:6]:
            preview_rows.append({header: row[index] for index, header in enumerate(headers)})
        return ExchangeInspection(
            file_path=str(path),
            format_name="xlsx",
            headers=headers,
            preview_rows=preview_rows,
            suggested_mapping=self._suggest_mapping(headers),
        )

    def inspect_json(self, path: str | Path) -> ExchangeInspection:
        payload = self._load_json_payload(path)
        headers = list(payload.get("columns") or [])
        preview_rows = [dict(row) for row in list(payload.get("rows") or [])[:5]]
        warnings = []
        return ExchangeInspection(
            file_path=str(path),
            format_name="json",
            headers=headers,
            preview_rows=preview_rows,
            suggested_mapping=self._suggest_mapping(headers),
            warnings=warnings,
        )

    def inspect_package(self, path: str | Path) -> ExchangeInspection:
        payload = self._load_package_payload(path)
        headers = list(payload.get("columns") or [])
        preview_rows = [dict(row) for row in list(payload.get("rows") or [])[:5]]
        packaged_media_index = payload.get("packaged_media_index")
        media_count = len(packaged_media_index) if isinstance(packaged_media_index, dict) else 0
        warnings = []
        if not bool(payload.get("packaged_media")):
            warnings.append("This ZIP does not advertise packaged media.")
        warnings.append(f"Packaged media entries detected: {media_count}")
        return ExchangeInspection(
            file_path=str(path),
            format_name="package",
            headers=headers,
            preview_rows=preview_rows,
            suggested_mapping=self._suggest_mapping(headers),
            warnings=warnings,
        )

    def _suggest_mapping(self, headers: list[str]) -> dict[str, str]:
        supported = {self._normalize_header_name(name): name for name in self.BASE_EXPORT_COLUMNS}
        mapping: dict[str, str] = {}
        for header in headers:
            normalized = self._normalize_header_name(header)
            if normalized in supported:
                mapping[header] = supported[normalized]
            elif normalized.startswith("custom::") or normalized.startswith("custom__"):
                mapping[header] = header
        return mapping

    def import_csv(
        self,
        path: str | Path,
        *,
        mapping: dict[str, str] | None = None,
        options: ExchangeImportOptions | None = None,
    ) -> ExchangeImportReport:
        path_obj = Path(path)
        with self._open_csv_dict_reader(path_obj) as reader:
            rows = [dict(row) for row in reader]
        return self._import_rows(
            rows, mapping=mapping, options=options, format_name="csv", source_dir=path_obj.parent
        )

    def import_xlsx(
        self,
        path: str | Path,
        *,
        mapping: dict[str, str] | None = None,
        options: ExchangeImportOptions | None = None,
    ) -> ExchangeImportReport:
        workbook = load_workbook(filename=str(path), read_only=True, data_only=True)
        sheet = workbook.active
        values = list(sheet.iter_rows(values_only=True))
        headers = [str(value or "").strip() for value in (values[0] if values else ())]
        rows = [{header: row[index] for index, header in enumerate(headers)} for row in values[1:]]
        return self._import_rows(
            rows, mapping=mapping, options=options, format_name="xlsx", source_dir=Path(path).parent
        )

    def import_json(
        self, path: str | Path, *, options: ExchangeImportOptions | None = None
    ) -> ExchangeImportReport:
        payload = self._load_json_payload(path)
        rows = [dict(row) for row in payload.get("rows") or []]
        return self._import_rows(
            rows, mapping=None, options=options, format_name="json", source_dir=Path(path).parent
        )

    def import_package(
        self, path: str | Path, *, options: ExchangeImportOptions | None = None
    ) -> ExchangeImportReport:
        payload = self._load_package_payload(path)
        with tempfile.TemporaryDirectory(prefix="exchange-package-") as temp_dir:
            extracted_root = Path(temp_dir)
            self._safe_extract_zip(path, extracted_root)
            rows = self._prepare_packaged_rows(payload, extracted_root=extracted_root)
            return self._import_rows(
                rows,
                mapping=None,
                options=options,
                format_name="package",
                source_dir=extracted_root,
            )

    def _apply_mapping(
        self, row: dict[str, object], mapping: dict[str, str] | None
    ) -> dict[str, object]:
        if not mapping:
            return dict(row)
        normalized: dict[str, object] = {}
        for source_name, value in row.items():
            target_name = mapping.get(source_name)
            if not target_name:
                continue
            normalized[target_name] = value
        return normalized

    def _ensure_custom_headers(
        self, rows: list[dict[str, object]], *, create_missing: bool
    ) -> list[str]:
        custom_specs: list[dict[str, object]] = []
        for row in rows:
            for key in row:
                if not str(key).startswith("custom::"):
                    continue
                custom_specs.append({"name": str(key).split("::", 1)[1], "field_type": "text"})
        if custom_specs and create_missing:
            self.custom_fields.ensure_fields(custom_specs)
        return [spec["name"] for spec in custom_specs]

    def _find_existing_track_id(
        self,
        row: dict[str, object],
        *,
        options: ExchangeImportOptions,
    ) -> int | None:
        if options.match_by_internal_id:
            try:
                track_id = int(row.get("track_id") or 0)
            except Exception:
                track_id = 0
            if track_id > 0:
                found = self.conn.execute(
                    "SELECT id FROM Tracks WHERE id=?", (track_id,)
                ).fetchone()
                if found:
                    return int(found[0])
        if options.match_by_isrc:
            compact = to_compact_isrc(str(row.get("isrc") or ""))
            if compact:
                found = self.conn.execute(
                    "SELECT id FROM Tracks WHERE isrc_compact=? ORDER BY id LIMIT 1",
                    (compact,),
                ).fetchone()
                if found:
                    return int(found[0])
        title = str(row.get("track_title") or "").strip()
        artist = str(row.get("artist_name") or "").strip()
        upc = str(row.get("upc") or row.get("release_upc") or "").strip()
        if options.match_by_upc_title and title and upc:
            found = self.conn.execute(
                """
                SELECT t.id
                FROM Tracks t
                JOIN Artists a ON a.id = t.main_artist_id
                WHERE t.track_title=? AND COALESCE(t.upc, '')=?
                ORDER BY t.id
                LIMIT 1
                """,
                (title, upc),
            ).fetchone()
            if found:
                return int(found[0])
        if options.heuristic_match and title and artist:
            found = self.conn.execute(
                """
                SELECT t.id
                FROM Tracks t
                JOIN Artists a ON a.id = t.main_artist_id
                WHERE lower(t.track_title)=lower(?) AND lower(a.name)=lower(?)
                ORDER BY t.id
                LIMIT 1
                """,
                (title, artist),
            ).fetchone()
            if found:
                return int(found[0])
        return None

    def _resolve_media_path(self, source_dir: Path, raw_value: object) -> str | None:
        text = str(raw_value or "").strip()
        if not text:
            return None
        path = Path(text)
        if not path.is_absolute():
            path = source_dir / path
        if path.exists():
            return str(path)
        return None

    def _upsert_release_from_row(
        self, row: dict[str, object], track_id: int, *, source_dir: Path
    ) -> None:
        release_title = str(row.get("release_title") or "").strip()
        if not release_title:
            return
        release_id = (
            int(row.get("release_id") or 0) if str(row.get("release_id") or "").strip() else 0
        )
        existing_id = None
        if release_id > 0:
            release = self.release_service.fetch_release(release_id)
            existing_id = release.id if release is not None else None
        if existing_id is None:
            release_upc = str(row.get("release_upc") or "").strip()
            release_catalog = str(row.get("release_catalog_number") or "").strip()
            if release_upc:
                found = self.conn.execute(
                    "SELECT id FROM Releases WHERE upc=? ORDER BY id LIMIT 1",
                    (release_upc,),
                ).fetchone()
                if found:
                    existing_id = int(found[0])
            if existing_id is None and release_catalog and release_title:
                found = self.conn.execute(
                    "SELECT id FROM Releases WHERE title=? AND catalog_number=? ORDER BY id LIMIT 1",
                    (release_title, release_catalog),
                ).fetchone()
                if found:
                    existing_id = int(found[0])

        placement = ReleaseTrackPlacement(
            track_id=track_id,
            disc_number=max(1, int(row.get("disc_number") or 1)),
            track_number=max(1, int(row.get("track_number") or 1)),
            sequence_number=max(1, int(row.get("sequence_number") or row.get("track_number") or 1)),
        )
        payload = ReleasePayload(
            title=release_title,
            version_subtitle=str(row.get("release_version_subtitle") or "").strip() or None,
            primary_artist=str(
                row.get("release_primary_artist") or row.get("artist_name") or ""
            ).strip()
            or None,
            album_artist=str(
                row.get("release_album_artist")
                or row.get("release_primary_artist")
                or row.get("artist_name")
                or ""
            ).strip()
            or None,
            release_type=str(row.get("release_type") or "album").strip() or "album",
            release_date=str(
                row.get("release_date_release") or row.get("release_date") or ""
            ).strip()
            or None,
            original_release_date=str(row.get("release_original_release_date") or "").strip()
            or None,
            label=str(row.get("release_label") or "").strip() or None,
            sublabel=str(row.get("release_sublabel") or "").strip() or None,
            catalog_number=str(
                row.get("release_catalog_number") or row.get("catalog_number") or ""
            ).strip()
            or None,
            upc=str(row.get("release_upc") or row.get("upc") or "").strip() or None,
            territory=str(row.get("release_territory") or "").strip() or None,
            explicit_flag=str(row.get("release_explicit_flag") or "").strip().lower()
            in {"1", "true", "yes"},
            notes=str(row.get("release_notes") or "").strip() or None,
            artwork_source_path=self._resolve_media_path(
                source_dir, row.get("release_artwork_path")
            ),
            artwork_storage_mode=str(row.get("release_artwork_storage_mode") or "").strip() or None,
            placements=[placement],
        )
        if existing_id is None:
            self.release_service.create_release(payload)
        else:
            summary = self.release_service.fetch_release_summary(existing_id)
            placements = list(summary.tracks) if summary is not None else []
            if all(existing.track_id != track_id for existing in placements):
                placements.append(placement)
            payload.placements = placements
            self.release_service.update_release(existing_id, payload)

    def _import_rows(
        self,
        rows: list[dict[str, object]],
        *,
        mapping: dict[str, str] | None,
        options: ExchangeImportOptions | None,
        format_name: str,
        source_dir: Path,
    ) -> ExchangeImportReport:
        opts = options or ExchangeImportOptions()
        normalized_rows = [self._apply_mapping(row, mapping) for row in rows]
        unknown_fields = sorted(
            {
                key
                for row in normalized_rows
                for key in row
                if key not in self.BASE_EXPORT_COLUMNS and not str(key).startswith("custom::")
            }
        )
        self._ensure_custom_headers(
            normalized_rows, create_missing=opts.create_missing_custom_fields
        )
        warnings: list[str] = []
        duplicates: list[str] = []
        passed = 0
        failed = 0
        skipped = 0
        created_tracks: list[int] = []
        updated_tracks: list[int] = []

        custom_defs = {
            field["name"]: field["id"] for field in self.custom_fields.list_active_fields()
        }

        def _apply_custom_fields(track_id: int, row: dict[str, object]) -> None:
            for key, value in row.items():
                if not str(key).startswith("custom::"):
                    continue
                field_name = str(key).split("::", 1)[1]
                field_id = custom_defs.get(field_name)
                if field_id is None:
                    continue
                self.conn.execute(
                    """
                    INSERT INTO CustomFieldValues(track_id, field_def_id, value)
                    VALUES (?, ?, ?)
                    ON CONFLICT(track_id, field_def_id) DO UPDATE SET value=excluded.value
                    """,
                    (track_id, field_id, str(value or "")),
                )

        for index, row in enumerate(normalized_rows, start=1):
            track_title = str(row.get("track_title") or "").strip()
            artist_name = str(row.get("artist_name") or "").strip()
            if not track_title or not artist_name:
                failed += 1
                warnings.append(f"Row {index}: Track Title and Artist are required.")
                continue
            existing_track_id = (
                None if opts.mode == "create" else self._find_existing_track_id(row, options=opts)
            )
            if opts.mode == "dry_run":
                passed += 1
                continue

            try:
                release_date = str(row.get("release_date") or "").strip() or None
                track_length_value = row.get("track_length_sec")
                if is_blank(str(track_length_value or "")):
                    track_length_value = parse_hms_text(str(row.get("track_length_hms") or ""))
                track_length_sec = int(track_length_value or 0)
                payload_kwargs = dict(
                    isrc=to_iso_isrc(str(row.get("isrc") or "")) or "",
                    track_title=track_title,
                    artist_name=artist_name,
                    additional_artists=[
                        part.strip()
                        for part in str(row.get("additional_artists") or "").split(",")
                        if part.strip()
                    ],
                    album_title=str(row.get("album_title") or "").strip() or None,
                    release_date=release_date,
                    track_length_sec=track_length_sec,
                    iswc=str(row.get("iswc") or "").strip() or None,
                    upc=str(row.get("upc") or "").strip() or None,
                    genre=str(row.get("genre") or "").strip() or None,
                    catalog_number=str(row.get("catalog_number") or "").strip() or None,
                    buma_work_number=str(row.get("buma_work_number") or "").strip() or None,
                    composer=str(row.get("composer") or "").strip() or None,
                    publisher=str(row.get("publisher") or "").strip() or None,
                    comments=str(row.get("comments") or "").strip() or None,
                    lyrics=str(row.get("lyrics") or "").strip() or None,
                    audio_file_source_path=self._resolve_media_path(
                        source_dir, row.get("audio_file_path")
                    ),
                    audio_file_storage_mode=str(row.get("audio_file_storage_mode") or "").strip()
                    or None,
                    album_art_source_path=self._resolve_media_path(
                        source_dir, row.get("album_art_path")
                    ),
                    album_art_storage_mode=str(row.get("album_art_storage_mode") or "").strip()
                    or None,
                )
                if row.get("audio_file_path") and payload_kwargs["audio_file_source_path"] is None:
                    warnings.append(
                        f"Row {index}: Audio reference not found: {row.get('audio_file_path')}"
                    )
                if row.get("album_art_path") and payload_kwargs["album_art_source_path"] is None:
                    warnings.append(
                        f"Row {index}: Artwork reference not found: {row.get('album_art_path')}"
                    )

                if existing_track_id is None:
                    if opts.mode == "update":
                        skipped += 1
                        warnings.append(
                            f"Row {index}: no existing match was found for update mode."
                        )
                        continue
                    track_id = self.track_service.create_track(TrackCreatePayload(**payload_kwargs))
                    created_tracks.append(track_id)
                    passed += 1
                else:
                    if opts.mode == "insert_new":
                        skipped += 1
                        duplicates.append(
                            f"Row {index}: matched existing track {existing_track_id}"
                        )
                        continue
                    snapshot = self.track_service.fetch_track_snapshot(existing_track_id)
                    if snapshot is None:
                        raise ValueError(f"Track {existing_track_id} not found")
                    if opts.mode == "merge":
                        payload_kwargs["track_title"] = (
                            snapshot.track_title or payload_kwargs["track_title"]
                        )
                        payload_kwargs["artist_name"] = (
                            snapshot.artist_name or payload_kwargs["artist_name"]
                        )
                        payload_kwargs["album_title"] = (
                            snapshot.album_title or payload_kwargs["album_title"]
                        )
                        payload_kwargs["release_date"] = (
                            snapshot.release_date or payload_kwargs["release_date"]
                        )
                        payload_kwargs["track_length_sec"] = (
                            snapshot.track_length_sec or payload_kwargs["track_length_sec"]
                        )
                        payload_kwargs["iswc"] = snapshot.iswc or payload_kwargs["iswc"]
                        payload_kwargs["upc"] = snapshot.upc or payload_kwargs["upc"]
                        payload_kwargs["genre"] = snapshot.genre or payload_kwargs["genre"]
                        payload_kwargs["catalog_number"] = (
                            snapshot.catalog_number or payload_kwargs["catalog_number"]
                        )
                        payload_kwargs["buma_work_number"] = (
                            snapshot.buma_work_number or payload_kwargs["buma_work_number"]
                        )
                        payload_kwargs["composer"] = snapshot.composer or payload_kwargs["composer"]
                        payload_kwargs["publisher"] = (
                            snapshot.publisher or payload_kwargs["publisher"]
                        )
                        payload_kwargs["comments"] = snapshot.comments or payload_kwargs["comments"]
                        payload_kwargs["lyrics"] = snapshot.lyrics or payload_kwargs["lyrics"]
                        payload_kwargs["audio_file_source_path"] = (
                            payload_kwargs["audio_file_source_path"] or None
                        )
                        payload_kwargs["album_art_source_path"] = (
                            payload_kwargs["album_art_source_path"] or None
                        )

                    self.track_service.update_track(
                        TrackUpdatePayload(
                            track_id=existing_track_id,
                            clear_audio_file=False,
                            clear_album_art=False,
                            **payload_kwargs,
                        )
                    )
                    updated_tracks.append(existing_track_id)
                    passed += 1
                    track_id = existing_track_id

                _apply_custom_fields(track_id, row)
                self._upsert_release_from_row(row, track_id, source_dir=source_dir)
            except Exception as exc:
                failed += 1
                warnings.append(f"Row {index}: {exc}")

        return ExchangeImportReport(
            format_name=format_name,
            mode=opts.mode,
            passed=passed,
            failed=failed,
            skipped=skipped,
            warnings=warnings,
            duplicates=duplicates,
            unknown_fields=unknown_fields,
            created_tracks=created_tracks,
            updated_tracks=updated_tracks,
        )
