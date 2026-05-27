import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.file_storage import STORAGE_MODE_DATABASE, STORAGE_MODE_MANAGED_FILE
from isrc_manager.services import CustomFieldDefinitionService, CustomFieldValueService


def make_custom_field_conn():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE CustomFieldDefs (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER,
            field_type TEXT NOT NULL DEFAULT 'text',
            options TEXT,
            blob_icon_payload TEXT
        );
        CREATE TABLE CustomFieldValues (
            track_id INTEGER NOT NULL,
            field_def_id INTEGER NOT NULL,
            value TEXT,
            blob_value BLOB,
            mime_type TEXT,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (track_id, field_def_id)
        );
        """
    )
    conn.executemany(
        """
        INSERT INTO CustomFieldDefs(id, name, active, sort_order, field_type, options)
        VALUES (?, ?, 1, ?, ?, ?)
        """,
        [
            (1, "Mood", 0, "dropdown", '["Happy"]'),
            (2, "Artwork", 1, "blob_image", None),
        ],
    )
    conn.commit()
    return conn


class CustomFieldDefinitionServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_custom_field_conn()
        self.service = CustomFieldDefinitionService(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_sync_fields_replaces_deleted_and_updates_order(self):
        self.service.sync_fields(
            existing_fields=self.service.list_active_fields(),
            new_fields=[
                {"id": 1, "name": "Mood", "field_type": "dropdown", "options": '["Happy","Calm"]'},
                {"id": None, "name": "Release Type", "field_type": "text", "options": None},
            ],
        )

        fields = self.service.list_active_fields()

        self.assertEqual([field["name"] for field in fields], ["Mood", "Release Type"])
        self.assertEqual(fields[0]["options"], '["Happy","Calm"]')
        self.assertEqual(self.service.get_field_type(1), "dropdown")
        self.assertEqual(self.service.get_field_name(1), "Mood")
        self.assertIsNone(
            self.conn.execute("SELECT id FROM CustomFieldDefs WHERE name='Artwork'").fetchone()
        )

    def test_update_dropdown_options_persists_json(self):
        self.service.update_dropdown_options(1, ["Happy", "Sad"])

        self.assertEqual(
            self.conn.execute("SELECT options FROM CustomFieldDefs WHERE id=1").fetchone(),
            ('["Happy", "Sad"]',),
        )

    def test_sync_fields_persists_blob_icon_payload_for_blob_fields(self):
        self.service.sync_fields(
            existing_fields=self.service.list_active_fields(),
            new_fields=[
                {
                    "id": 2,
                    "name": "Artwork",
                    "field_type": "blob_image",
                    "options": None,
                    "blob_icon_payload": {"mode": "emoji", "emoji": "📷"},
                }
            ],
        )

        row = self.conn.execute(
            "SELECT blob_icon_payload FROM CustomFieldDefs WHERE id=2"
        ).fetchone()
        fields = self.service.list_active_fields()

        self.assertIsNotNone(row)
        self.assertIn('"emoji": "\\ud83d\\udcf7"', row[0])
        self.assertEqual(fields[0]["blob_icon_payload"]["emoji"], "📷")

    def test_ensure_fields_deduplicates_reactivates_and_rejects_type_conflicts(self):
        with self.conn:
            self.conn.execute("UPDATE CustomFieldDefs SET active=0 WHERE id=1")

        ensured = self.service.ensure_fields(
            [
                {"name": " Mood ", "field_type": "dropdown", "options": '["Calm"]'},
                {"name": "Mood", "field_type": "dropdown", "options": '["Ignored"]'},
                {"name": "", "field_type": "text"},
                {
                    "name": "Waveform",
                    "field_type": "blob_audio",
                    "blob_icon_payload": {"mode": "emoji", "emoji": "🎧"},
                },
            ]
        )

        self.assertEqual([field["name"] for field in ensured], ["Mood", "Waveform"])
        self.assertFalse(ensured[0]["created"])
        self.assertTrue(ensured[1]["created"])
        self.assertEqual(ensured[1]["blob_icon_payload"]["emoji"], "🎧")
        self.assertEqual(
            self.conn.execute("SELECT active FROM CustomFieldDefs WHERE id=1").fetchone(),
            (1,),
        )

        with self.assertRaisesRegex(ValueError, "already exists as type"):
            self.service.ensure_fields([{"name": "Mood", "field_type": "text"}])

        with self.conn:
            cursor = self.conn.cursor()
            cursor_result = self.service.ensure_fields(
                [{"name": "Session Notes", "field_type": "text"}],
                cursor=cursor,
            )
        self.assertEqual(cursor_result[0]["name"], "Session Notes")
        self.assertEqual(self.service.get_field_type(999), "text")
        self.assertEqual(self.service.get_field_name(999), "file")


class CustomFieldValueServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_custom_field_conn()
        self.definitions = CustomFieldDefinitionService(self.conn)
        self.service = CustomFieldValueService(self.conn, self.definitions)
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def test_save_text_value_and_read_meta(self):
        self.service.save_value(10, 1, value="Calm")

        self.assertEqual(self.service.get_text_value(10, 1), "Calm")
        self.assertEqual(
            self.service.get_value_meta(10, 1),
            {"value": "Calm", "has_blob": False, "size_bytes": 0, "mime_type": None},
        )
        row = self.conn.execute(
            """
            SELECT blob_value, managed_file_path, storage_mode, filename, mime_type, size_bytes
            FROM CustomFieldValues
            WHERE track_id=? AND field_def_id=?
            """,
            (10, 1),
        ).fetchone()
        self.assertEqual(row, (None, "", "", "", "", 0))

    def test_normalize_text_field_attachment_state_clears_legacy_binary_columns(self):
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO CustomFieldValues (
                    track_id,
                    field_def_id,
                    value,
                    blob_value,
                    managed_file_path,
                    storage_mode,
                    filename,
                    mime_type,
                    size_bytes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    15,
                    1,
                    "Legacy Mood",
                    sqlite3.Binary(b"bad"),
                    "custom_field_media/legacy.bin",
                    "database",
                    "legacy.bin",
                    "application/octet-stream",
                    3,
                ),
            )

        self.service._normalize_text_field_attachment_state()

        row = self.conn.execute(
            """
            SELECT value, blob_value, managed_file_path, storage_mode, filename, mime_type, size_bytes
            FROM CustomFieldValues
            WHERE track_id=? AND field_def_id=?
            """,
            (15, 1),
        ).fetchone()
        self.assertEqual(row, ("Legacy Mood", None, "", "", "", "", 0))

    def test_save_blob_value_tracks_size_and_delete(self):
        blob_path = Path(self.tmpdir.name) / "cover.png"
        blob_path.write_bytes(b"\x89PNG\r\n\x1a\nfakepng")

        self.service.save_value(11, 2, blob_path=str(blob_path))

        data, mime = self.service.fetch_blob(11, 2)
        meta = self.service.get_value_meta(11, 2)

        self.assertEqual(bytes(data), b"\x89PNG\r\n\x1a\nfakepng")
        self.assertEqual(mime, "image/png")
        self.assertTrue(self.service.has_blob(11, 2))
        self.assertEqual(self.service.blob_size(11, 2), len(b"\x89PNG\r\n\x1a\nfakepng"))
        self.assertEqual(meta["size_bytes"], len(b"\x89PNG\r\n\x1a\nfakepng"))
        self.assertEqual(meta["mime_type"], "image/png")

        self.service.delete_blob(11, 2)
        self.assertFalse(self.service.has_blob(11, 2))
        with self.assertRaises(FileNotFoundError):
            self.service.fetch_blob(11, 2)

    def test_invalid_blob_extension_is_rejected(self):
        blob_path = Path(self.tmpdir.name) / "not-image.txt"
        blob_path.write_bytes(b"nope")

        with self.assertRaises(ValueError):
            self.service.save_value(12, 2, blob_path=str(blob_path))

    def test_managed_blob_round_trip_conversion_filtering_and_cleanup(self):
        data_root = Path(self.tmpdir.name) / "data"
        service = CustomFieldValueService(self.conn, self.definitions, data_root=data_root)
        blob_path = Path(self.tmpdir.name) / "cover-managed.png"
        blob_path.write_bytes(b"\x89PNG\r\n\x1a\nmanaged")

        service.save_value(
            20,
            2,
            blob_path=str(blob_path),
            storage_mode=STORAGE_MODE_MANAGED_FILE,
        )
        managed_meta = service.get_value_meta(20, 2, include_storage_details=True)
        managed_path = service._resolve_managed_path(
            service._fetch_blob_row(20, 2)[2],
        )

        self.assertEqual(managed_meta["storage_mode"], STORAGE_MODE_MANAGED_FILE)
        self.assertEqual(managed_meta["filename"], "cover-managed.png")
        self.assertIsNotNone(managed_path)
        assert managed_path is not None
        self.assertTrue(managed_path.exists())
        self.assertEqual(service.fetch_blob(20, 2)[0], b"\x89PNG\r\n\x1a\nmanaged")

        meta_map = service.get_value_meta_map(
            [2, "bad", 2],
            track_ids=[20, "bad", 20],
            include_storage_details=True,
        )
        self.assertEqual(list(meta_map), [(20, 2)])
        self.assertEqual(meta_map[(20, 2)]["storage_mode"], STORAGE_MODE_MANAGED_FILE)
        self.assertEqual(service.get_value_meta_map([], track_ids=[20]), {})
        self.assertEqual(service.get_value_meta_map([2], track_ids=["bad"]), {})

        service.convert_storage_mode(20, 2, STORAGE_MODE_DATABASE)
        database_meta = service.get_value_meta(20, 2, include_storage_details=True)
        self.assertEqual(database_meta["storage_mode"], STORAGE_MODE_DATABASE)
        self.assertFalse(managed_path.exists())
        self.assertEqual(service.fetch_blob(20, 2)[0], b"\x89PNG\r\n\x1a\nmanaged")

        same_mode_meta = service.convert_storage_mode(20, 2, STORAGE_MODE_DATABASE)
        self.assertEqual(same_mode_meta["has_blob"], True)

        service.convert_storage_mode(20, 2, STORAGE_MODE_MANAGED_FILE)
        restored_meta = service.get_value_meta(20, 2, include_storage_details=True)
        self.assertEqual(restored_meta["storage_mode"], STORAGE_MODE_MANAGED_FILE)
        restored_path = service._resolve_managed_path(service._fetch_blob_row(20, 2)[2])
        self.assertIsNotNone(restored_path)
        assert restored_path is not None
        self.assertTrue(restored_path.exists())

        service.delete_blob(20, 2)
        self.assertFalse(restored_path.exists())
        with self.assertRaises(FileNotFoundError):
            service.convert_storage_mode(20, 2, STORAGE_MODE_DATABASE)

    def test_blob_value_service_handles_missing_sources_and_unconfigured_managed_storage(self):
        blob_path = Path(self.tmpdir.name) / "cover-unconfigured.png"
        blob_path.write_bytes(b"\x89PNG\r\n\x1a\nunconfigured")

        with self.assertRaisesRegex(ValueError, "Managed custom-field storage"):
            self.service.save_value(
                30,
                2,
                blob_path=str(blob_path),
                storage_mode=STORAGE_MODE_MANAGED_FILE,
            )

        self.service.save_value(30, 2, blob_path=str(blob_path))
        self.conn.execute(
            """
            UPDATE CustomFieldValues
            SET blob_value=NULL, managed_file_path='missing/path.png', storage_mode='managed_file'
            WHERE track_id=? AND field_def_id=?
            """,
            (30, 2),
        )
        self.conn.commit()
        with self.assertRaises(FileNotFoundError):
            self.service.fetch_blob(30, 2)

        self.conn.execute(
            """
            UPDATE CustomFieldValues
            SET managed_file_path='', storage_mode='', filename='', mime_type='', size_bytes=0
            WHERE track_id=? AND field_def_id=?
            """,
            (30, 2),
        )
        self.conn.commit()
        with self.assertRaises(FileNotFoundError):
            self.service.fetch_blob(30, 2)

        self.service.delete_blob(999, 2)


if __name__ == "__main__":
    unittest.main()
