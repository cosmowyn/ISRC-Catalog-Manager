import sqlite3
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
