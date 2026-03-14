import sqlite3
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QSettings

from isrc_manager.services import (
    DatabaseSchemaService,
    GS1MetadataRecord,
    GS1ProfileDefaults,
    GS1IntegrationService,
    GS1MetadataRepository,
    GS1SettingsService,
    TrackService,
)


def make_conn():
    conn = sqlite3.connect(":memory:")
    schema = DatabaseSchemaService(conn)
    schema.init_db()
    schema.migrate_schema()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_kv (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    conn.execute("INSERT INTO Artists(id, name) VALUES (1, 'Main Artist')")
    conn.execute("INSERT INTO Albums(id, title) VALUES (1, 'Orbit Release')")
    conn.execute(
        """
        INSERT INTO Tracks(
            id, isrc, isrc_compact, track_title, main_artist_id, album_id, release_date, track_length_sec, iswc, upc, genre
        )
        VALUES(1, 'NL-ABC-26-00001', 'NLABC2600001', 'Orbit Release', 1, 1, '2026-03-14', 180, NULL, '123456789012', 'Pop')
        """
    )
    conn.commit()
    return conn


class GS1IntegrationServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.tmpdir.name) / "settings.ini"
        self.settings = QSettings(str(self.settings_path), QSettings.IniFormat)
        self.settings.setFallbacksEnabled(False)
        self.service = GS1IntegrationService(
            GS1MetadataRepository(self.conn),
            GS1SettingsService(self.conn, self.settings),
            TrackService(self.conn, self.tmpdir.name),
        )

    def tearDown(self):
        self.settings.clear()
        self.conn.close()
        self.tmpdir.cleanup()

    def test_build_context_rejects_zero_or_negative_track_ids(self):
        with self.assertRaises(ValueError):
            self.service.build_context(0)

        with self.assertRaises(ValueError):
            self.service.build_context(-1)

    def test_build_context_loads_existing_track(self):
        context = self.service.build_context(1, current_profile_path="/tmp/Orbit_Label.db")

        self.assertEqual(context.track_id, 1)
        self.assertEqual(context.track_title, "Orbit Release")
        self.assertEqual(context.album_title, "Orbit Release")
        self.assertEqual(context.artist_name, "Main Artist")
        self.assertEqual(context.upc, "123456789012")
        self.assertEqual(context.profile_label, "Orbit Label")

    def test_load_or_create_metadata_repairs_legacy_brand_subbrand_defaults(self):
        self.service.settings_service.set_profile_defaults(
            GS1ProfileDefaults(
                target_market="Global Market",
                language="English",
                brand="Orbit Label Group",
                subbrand="Orbit Series",
                packaging_type="Digital file",
                product_classification="Audio",
            )
        )
        self.service.repository.save(
            GS1MetadataRecord(
                track_id=1,
                status="Concept",
                product_classification="Audio",
                consumer_unit_flag=True,
                packaging_type="Digital file",
                target_market="Worldwide",
                language="English",
                product_description="Orbit Release",
                brand="Orbit Label",
                subbrand="",
                quantity="1",
                unit="Each",
                image_url="",
                notes="",
                export_enabled=True,
            )
        )

        record, context, exists = self.service.load_or_create_metadata(
            1,
            current_profile_path="/tmp/Orbit_Label.db",
            window_title="Orbit Window",
        )

        self.assertTrue(exists)
        self.assertEqual(context.profile_label, "Orbit Label")
        self.assertEqual(record.brand, "Orbit Label Group")
        self.assertEqual(record.subbrand, "Orbit Series")


if __name__ == "__main__":
    unittest.main()
