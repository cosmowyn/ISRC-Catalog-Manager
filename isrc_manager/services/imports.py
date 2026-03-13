"""XML import analysis and execution services."""

from __future__ import annotations

import re
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from isrc_manager.domain.codes import (
    is_blank,
    is_valid_isrc_compact_or_iso,
    is_valid_iswc_any,
    to_compact_isrc,
    to_iso_isrc,
    to_iso_iswc,
)
from isrc_manager.domain.standard_fields import promoted_text_value_columns_by_label_lower
from isrc_manager.domain.timecode import parse_hms_text

from .custom_fields import CustomFieldDefinitionService
from .tracks import TrackService

PROMOTED_TEXT_CUSTOM_FIELDS = promoted_text_value_columns_by_label_lower()


@dataclass(slots=True)
class ImportRecord:
    iso_isrc: str
    comp_isrc: str
    title: str
    artist: str
    additional_artists: str
    album: str
    release_date: str | None
    iso_iswc: str | None
    upc: str | None
    genre: str | None
    track_length_sec: int | None
    catalog_number: str | None
    buma_work_number: str | None
    custom_fields: list[dict]


@dataclass(slots=True)
class ImportInspection:
    file_path: str
    schema: str
    records: list[ImportRecord]
    duplicate_count: int
    invalid_count: int
    missing_custom_fields: list[tuple[str, str]]

    @property
    def would_insert(self) -> int:
        return len(self.records) - self.duplicate_count


@dataclass(slots=True)
class ImportExecutionResult:
    inserted: int
    duplicate_count: int
    invalid_count: int
    error_count: int


class XMLImportService:
    """Centralizes XML import preflight analysis and transactional writes."""

    def __init__(self, conn: sqlite3.Connection, track_service: TrackService, custom_fields: CustomFieldDefinitionService):
        self.conn = conn
        self.track_service = track_service
        self.custom_fields = custom_fields

    def inspect_file(self, file_path: str) -> ImportInspection:
        schema, records, invalid_count = self._parse_file(file_path)
        missing = self._find_missing_custom_fields(records)
        duplicate_count = sum(1 for record in records if self.track_service.is_isrc_taken_normalized(record.iso_isrc))
        return ImportInspection(
            file_path=file_path,
            schema=schema,
            records=records,
            duplicate_count=duplicate_count,
            invalid_count=invalid_count,
            missing_custom_fields=missing,
        )

    def execute_import(self, file_path: str) -> ImportExecutionResult:
        inspection = self.inspect_file(file_path)
        if inspection.missing_custom_fields:
            raise ValueError(f"Missing custom columns: {inspection.missing_custom_fields}")

        name_to_id = {
            (field["name"], field["field_type"]): field["id"]
            for field in self.custom_fields.list_active_fields()
        }

        inserted = 0
        duplicate_count = 0
        error_count = 0

        self.conn.execute("BEGIN")
        try:
            for record in inspection.records:
                if self.track_service.is_isrc_taken_normalized(record.iso_isrc):
                    duplicate_count += 1
                    continue

                self.conn.execute("SAVEPOINT row_import")
                try:
                    cur = self.conn.cursor()
                    main_artist_id = self.track_service.get_or_create_artist(record.artist, cursor=cur)
                    album_id = self.track_service.get_or_create_album(record.album, cursor=cur)
                    cur.execute(
                        """
                        INSERT INTO Tracks (
                            isrc, isrc_compact, track_title, main_artist_id, album_id,
                            release_date, track_length_sec, iswc, upc, genre,
                            catalog_number, buma_work_number
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record.iso_isrc,
                            record.comp_isrc,
                            record.title,
                            main_artist_id,
                            album_id,
                            record.release_date,
                            record.track_length_sec,
                            record.iso_iswc,
                            record.upc,
                            record.genre,
                            record.catalog_number,
                            record.buma_work_number,
                        ),
                    )
                    track_id = int(cur.lastrowid)
                    extras = self.track_service.parse_additional_artists(record.additional_artists)
                    self.track_service.replace_additional_artists(track_id, extras, cursor=cur)

                    for custom in record.custom_fields:
                        if not custom["name"] or not custom["type"]:
                            continue
                        promoted_key = PROMOTED_TEXT_CUSTOM_FIELDS.get(custom["name"].strip().lower())
                        if promoted_key:
                            cur.execute(
                                f"UPDATE Tracks SET {promoted_key}=? WHERE id=?",
                                (custom.get("value") or "", track_id),
                            )
                            continue
                        if custom["type"] in ("blob_image", "blob_audio"):
                            continue
                        field_id = name_to_id.get((custom["name"], custom["type"]))
                        if not field_id:
                            continue
                        cur.execute(
                            """
                            INSERT INTO CustomFieldValues (track_id, field_def_id, value)
                            VALUES (?, ?, ?)
                            ON CONFLICT(track_id, field_def_id) DO UPDATE SET value=excluded.value
                            """,
                            (track_id, field_id, custom.get("value") or ""),
                        )

                    self.conn.execute("RELEASE SAVEPOINT row_import")
                    inserted += 1
                except Exception:
                    self.conn.execute("ROLLBACK TO SAVEPOINT row_import")
                    self.conn.execute("RELEASE SAVEPOINT row_import")
                    error_count += 1
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        return ImportExecutionResult(
            inserted=inserted,
            duplicate_count=duplicate_count,
            invalid_count=inspection.invalid_count,
            error_count=error_count,
        )

    @staticmethod
    def _xml_local(tag: str) -> str:
        if "}" in tag:
            return tag.split("}", 1)[1]
        return tag

    def _parse_file(self, file_path: str) -> tuple[str, list[ImportRecord], int]:
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
        except Exception as exc:
            raise ValueError(f"Could not read XML: {exc}") from exc

        root_tag = self._xml_local(root.tag)
        records = []
        schema = None

        if root_tag == "DeclarationOfSoundRecordingRightsClaimMessage":
            records = list(root.findall("SoundRecording"))
            schema = "full"
        else:
            tracks_element = None
            if root_tag == "Tracks":
                tracks_element = root
            else:
                for element in root.iter():
                    if self._xml_local(element.tag) == "Tracks":
                        tracks_element = element
                        break
            if tracks_element is not None:
                records = [element for element in tracks_element if self._xml_local(element.tag) == "Track"]
                if records:
                    schema = "selected"

        if not records or schema is None:
            raise ValueError(f"Unexpected XML root element: <{root_tag}> or no importable records found.")

        parsed_records: list[ImportRecord] = []
        invalid_count = 0

        for record in records:
            child_map = self._lower_map(record)
            customs = self._parse_custom_fields(record)

            if schema == "full":
                isrc_raw = self._get_any(child_map, "isrc")
                title = self._get_any(child_map, "track_title")
                artist = self._get_any(child_map, "artist_name")
                additional = self._get_any(child_map, "additional_artists")
                album = self._get_any(child_map, "album_title")
                release_date = self._get_any(child_map, "release_date")
                iswc_raw = self._get_any(child_map, "iswc")
                upc = self._get_any(child_map, "upc")
                genre = self._get_any(child_map, "genre")
                track_length = self._get_any(child_map, "tracklength")
                catalog_number = self._get_any(child_map, "catalog_number")
                buma_work_number = self._get_any(child_map, "buma_work_number")
            else:
                isrc_raw = self._get_any(child_map, "isrc")
                title = self._get_any(child_map, "title")
                artist = self._get_any(child_map, "mainartist")
                additional = self._get_any(child_map, "additionalartists")
                album = self._get_any(child_map, "album")
                release_date = self._get_any(child_map, "releasedate")
                iswc_raw = self._get_any(child_map, "iswc")
                upc = self._get_any(child_map, "upcean", "upc")
                genre = self._get_any(child_map, "genre")
                track_length = self._get_any(child_map, "tracklength")
                catalog_number = self._get_any(child_map, "catalognumber")
                buma_work_number = self._get_any(child_map, "bumaworknumber")

            iso_isrc = to_iso_isrc(isrc_raw)
            comp_isrc = to_compact_isrc(iso_isrc)
            if not comp_isrc or not is_valid_isrc_compact_or_iso(iso_isrc):
                invalid_count += 1
                continue
            if is_blank(title) or is_blank(artist):
                invalid_count += 1
                continue

            iso_iswc = None
            if iswc_raw:
                iso_iswc = to_iso_iswc(iswc_raw)
                if not iso_iswc or not is_valid_iswc_any(iso_iswc):
                    invalid_count += 1
                    continue

            if release_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", release_date):
                release_date = None

            track_length_sec = None
            if track_length:
                try:
                    track_length_sec = parse_hms_text(track_length)
                except Exception:
                    track_length_sec = None

            parsed_records.append(
                ImportRecord(
                    iso_isrc=iso_isrc,
                    comp_isrc=comp_isrc,
                    title=title,
                    artist=artist,
                    additional_artists=additional,
                    album=album,
                    release_date=release_date or None,
                    iso_iswc=iso_iswc,
                    upc=upc or None,
                    genre=genre or None,
                    track_length_sec=track_length_sec,
                    catalog_number=catalog_number or None,
                    buma_work_number=buma_work_number or None,
                    custom_fields=customs,
                )
            )

        return schema, parsed_records, invalid_count

    def _find_missing_custom_fields(self, records: list[ImportRecord]) -> list[tuple[str, str]]:
        required = {
            (custom["name"], custom["type"])
            for record in records
            for custom in record.custom_fields
            if (
                custom["name"]
                and custom["type"]
                and custom["type"] not in ("blob_image", "blob_audio")
                and custom["name"].strip().lower() not in PROMOTED_TEXT_CUSTOM_FIELDS
            )
        }
        if not required:
            return []

        existing = {(field["name"], field["field_type"]) for field in self.custom_fields.list_active_fields()}
        return [(name, field_type) for name, field_type in sorted(required) if (name, field_type) not in existing]

    @classmethod
    def _parse_custom_fields(cls, record) -> list[dict]:
        custom_fields = []
        for child in record:
            if cls._xml_local(child.tag) != "CustomFields":
                continue
            for field in child:
                if cls._xml_local(field.tag) != "Field":
                    continue
                name = (field.attrib.get("name") or "").strip()
                field_type = (field.attrib.get("type") or "text").strip()
                value = ""
                mime = None
                size = None
                for sub in field:
                    tag = cls._xml_local(sub.tag).lower()
                    if tag == "value":
                        value = "" if sub.text is None else sub.text.strip()
                    elif tag == "mimetype":
                        mime = (sub.text or "").strip()
                    elif tag == "sizebytes":
                        try:
                            size = int((sub.text or "0").strip())
                        except Exception:
                            size = 0
                custom_fields.append(
                    {"name": name, "type": field_type, "value": value, "mime": mime, "size": size}
                )
        return custom_fields

    @classmethod
    def _lower_map(cls, element) -> dict[str, str]:
        values = {}
        for child in element:
            key = cls._xml_local(child.tag or "").strip().lower()
            values[key] = "" if child.text is None else child.text.strip()
        return values

    @staticmethod
    def _get_any(values: dict[str, str], *keys: str) -> str:
        for key in keys:
            value = values.get(key)
            if value is not None and value != "":
                return value
        return ""
