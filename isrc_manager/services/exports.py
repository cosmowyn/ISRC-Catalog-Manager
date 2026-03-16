"""XML export services."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from isrc_manager.domain.codes import to_compact_isrc, to_iso_isrc
from isrc_manager.domain.timecode import seconds_to_hms


class XMLExportService:
    """Centralizes full and selected-track XML exports."""

    def __init__(self, conn):
        self.conn = conn

    def export_all(self, path: str | Path) -> int:
        cols, rows = self._fetch_base_rows()
        track_ids = [row[0] for row in rows]
        custom_by_track = self._fetch_custom_by_track(track_ids)

        root = ET.Element("DeclarationOfSoundRecordingRightsClaimMessage")
        for row in rows:
            item = ET.SubElement(root, "SoundRecording")
            row_dict = dict(zip(cols, row))
            for col in cols:
                if col == "track_length_sec":
                    ET.SubElement(item, "TrackLength").text = seconds_to_hms(
                        int(row_dict[col] or 0)
                    )
                sub = ET.SubElement(item, col)
                sub.text = "" if row_dict[col] is None else str(row_dict[col])

            self._append_custom_fields(item, custom_by_track.get(row_dict["id"], []))

        self._write_xml(path, root)
        return len(rows)

    def export_selected(
        self, path: str | Path, track_ids: list[int], *, current_db_path: str
    ) -> int:
        _, rows = self._fetch_base_rows(track_ids)
        custom_by_track = self._fetch_custom_by_track(track_ids)

        root = ET.Element("ISRCExport")
        meta = ET.SubElement(root, "Meta")
        ET.SubElement(meta, "CreatedAt").text = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        ET.SubElement(meta, "ProfileDB").text = str(current_db_path)

        tracks_element = ET.SubElement(root, "Tracks")
        for (
            tid,
            isrc,
            db_entry_date,
            title,
            artist,
            addl,
            album,
            release_date,
            track_length_sec,
            iswc,
            upc,
            genre,
            catalog_number,
            buma_work_number,
            audio_file_mime_type,
            audio_file_size_bytes,
            album_art_mime_type,
            album_art_size_bytes,
        ) in rows:
            track = ET.SubElement(tracks_element, "Track", id=str(tid))
            ET.SubElement(track, "ISRC").text = (
                to_iso_isrc(isrc) or to_compact_isrc(isrc) or (isrc or "")
            )
            ET.SubElement(track, "DBEntryDate").text = db_entry_date or ""
            ET.SubElement(track, "Title").text = title or ""
            ET.SubElement(track, "MainArtist").text = artist or ""
            ET.SubElement(track, "AdditionalArtists").text = addl or ""
            ET.SubElement(track, "Album").text = album or ""
            ET.SubElement(track, "ReleaseDate").text = release_date or ""
            ET.SubElement(track, "TrackLength").text = seconds_to_hms(int(track_length_sec or 0))
            ET.SubElement(track, "ISWC").text = iswc or ""
            ET.SubElement(track, "UPCEAN").text = upc or ""
            ET.SubElement(track, "Genre").text = genre or ""
            ET.SubElement(track, "CatalogNumber").text = catalog_number or ""
            ET.SubElement(track, "BUMAWorkNumber").text = buma_work_number or ""
            ET.SubElement(track, "AudioFileMimeType").text = audio_file_mime_type or ""
            ET.SubElement(track, "AudioFileSizeBytes").text = str(int(audio_file_size_bytes or 0))
            ET.SubElement(track, "AlbumArtMimeType").text = album_art_mime_type or ""
            ET.SubElement(track, "AlbumArtSizeBytes").text = str(int(album_art_size_bytes or 0))

            self._append_custom_fields(track, custom_by_track.get(tid, []))

        self._write_xml(path, root)
        return len(rows)

    def _fetch_base_rows(self, track_ids: list[int] | None = None):
        if track_ids:
            qmarks = ",".join(["?"] * len(track_ids))
            where_clause = f"WHERE t.id IN ({qmarks})"
            params = track_ids
        else:
            where_clause = ""
            params = []

        rows = self.conn.execute(
            f"""
            SELECT
                t.id,
                t.isrc,
                COALESCE(t.db_entry_date, '') AS db_entry_date,
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
                COALESCE(t.audio_file_mime_type, '') AS audio_file_mime_type,
                COALESCE(t.audio_file_size_bytes, 0) AS audio_file_size_bytes,
                CASE
                    WHEN t.album_id IS NOT NULL
                     AND TRIM(COALESCE(al.title, '')) != ''
                     AND LOWER(TRIM(COALESCE(al.title, ''))) != 'single'
                     AND COALESCE(al.album_art_path, '') != ''
                    THEN COALESCE(al.album_art_mime_type, '')
                    ELSE COALESCE(t.album_art_mime_type, '')
                END AS album_art_mime_type,
                CASE
                    WHEN t.album_id IS NOT NULL
                     AND TRIM(COALESCE(al.title, '')) != ''
                     AND LOWER(TRIM(COALESCE(al.title, ''))) != 'single'
                     AND COALESCE(al.album_art_path, '') != ''
                    THEN COALESCE(al.album_art_size_bytes, 0)
                    ELSE COALESCE(t.album_art_size_bytes, 0)
                END AS album_art_size_bytes
            FROM Tracks t
            LEFT JOIN Artists a ON a.id = t.main_artist_id
            LEFT JOIN Albums al ON al.id = t.album_id
            {where_clause}
            ORDER BY t.id
            """,
            params,
        ).fetchall()
        cols = [
            "id",
            "isrc",
            "db_entry_date",
            "track_title",
            "artist_name",
            "additional_artists",
            "album_title",
            "release_date",
            "track_length_sec",
            "iswc",
            "upc",
            "genre",
            "catalog_number",
            "buma_work_number",
            "audio_file_mime_type",
            "audio_file_size_bytes",
            "album_art_mime_type",
            "album_art_size_bytes",
        ]
        return cols, rows

    def _fetch_custom_by_track(self, track_ids: list[int]) -> dict[int, list[dict]]:
        custom_by_track: dict[int, list[dict]] = {}
        if not track_ids:
            return custom_by_track

        defs = self.conn.execute(
            """
            SELECT id, name, field_type
            FROM CustomFieldDefs
            WHERE active=1
            ORDER BY COALESCE(sort_order, 999999), name
            """
        ).fetchall()
        defmap = {
            field_id: {"name": name, "field_type": field_type}
            for field_id, name, field_type in defs
        }

        qmarks = ",".join("?" * len(track_ids))
        values = self.conn.execute(
            f"""
            SELECT track_id, field_def_id, value, mime_type, size_bytes
            FROM CustomFieldValues
            WHERE track_id IN ({qmarks})
            """,
            track_ids,
        ).fetchall()
        for track_id, field_id, value, mime_type, size_bytes in values:
            field = defmap.get(field_id)
            if not field:
                continue
            custom_by_track.setdefault(track_id, []).append(
                {
                    "name": field["name"],
                    "field_type": field["field_type"],
                    "value": value,
                    "mime_type": mime_type,
                    "size_bytes": int(size_bytes or 0),
                }
            )
        return custom_by_track

    @staticmethod
    def _append_custom_fields(parent, custom_values: list[dict]) -> None:
        custom_fields = ET.SubElement(parent, "CustomFields")
        for custom in custom_values:
            field = ET.SubElement(
                custom_fields,
                "Field",
                name=custom["name"],
                type=custom["field_type"],
            )
            if custom["field_type"] in ("blob_image", "blob_audio"):
                if custom.get("mime_type"):
                    ET.SubElement(field, "MimeType").text = custom["mime_type"]
                ET.SubElement(field, "SizeBytes").text = str(int(custom.get("size_bytes", 0)))
            else:
                ET.SubElement(field, "Value").text = custom["value"] or ""

    @staticmethod
    def _write_xml(path: str | Path, root) -> None:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(root).write(output_path, encoding="utf-8", xml_declaration=True)
