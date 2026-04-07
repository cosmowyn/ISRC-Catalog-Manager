import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from isrc_manager.code_registry import BUILTIN_CATEGORY_CATALOG_NUMBER
from isrc_manager.releases import ReleasePayload, ReleaseService, ReleaseTrackPlacement
from isrc_manager.services import DatabaseSchemaService, TrackCreatePayload, TrackService


class CodeRegistryWorkflowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")
        schema = DatabaseSchemaService(self.conn, data_root=self.root)
        schema.init_db()
        schema.migrate_schema()
        self.track_service = TrackService(self.conn, self.root)
        self.release_service = ReleaseService(self.conn, self.root)
        registry = self.track_service.code_registry_service()
        category = registry.fetch_category_by_system_key(BUILTIN_CATEGORY_CATALOG_NUMBER)
        assert category is not None
        registry.update_category(category.id, prefix="ACR")

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def test_track_create_captures_canonical_internal_catalog_numbers(self):
        yy = datetime.now().year % 100
        track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-TST-26-60001",
                track_title="Internal Catalog Track",
                artist_name="Workflow Artist",
                additional_artists=[],
                album_title="Workflow Album",
                release_date="2026-04-07",
                track_length_sec=182,
                iswc=None,
                upc=None,
                genre="Ambient",
                catalog_number=f"ACR{yy:02d}0001",
            )
        )

        snapshot = self.track_service.fetch_track_snapshot(track_id)
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.catalog_number, f"ACR{yy:02d}0001")
        self.assertIsNotNone(snapshot.catalog_registry_entry_id)
        self.assertIsNone(snapshot.external_catalog_identifier_id)

    def test_release_create_and_update_switch_between_external_and_internal_catalog_modes(self):
        track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-TST-26-60002",
                track_title="Release Workflow Track",
                artist_name="Workflow Artist",
                additional_artists=[],
                album_title="Workflow Album",
                release_date="2026-04-07",
                track_length_sec=183,
                iswc=None,
                upc=None,
                genre="Ambient",
                catalog_number=None,
            )
        )
        release_id = self.release_service.create_release(
            ReleasePayload(
                title="External Release",
                primary_artist="Workflow Artist",
                catalog_number="EXT-777",
                placements=[ReleaseTrackPlacement(track_id=track_id)],
            )
        )

        created = self.release_service.fetch_release(release_id)
        self.assertIsNotNone(created)
        assert created is not None
        self.assertEqual(created.catalog_number, "EXT-777")
        self.assertIsNone(created.catalog_registry_entry_id)
        self.assertIsNotNone(created.external_catalog_identifier_id)

        yy = datetime.now().year % 100
        self.release_service.update_release(
            release_id,
            ReleasePayload(
                title="External Release",
                primary_artist="Workflow Artist",
                catalog_number=f"ACR{yy:02d}0002",
                placements=[ReleaseTrackPlacement(track_id=track_id)],
            ),
        )

        updated = self.release_service.fetch_release(release_id)
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.catalog_number, f"ACR{yy:02d}0002")
        self.assertIsNotNone(updated.catalog_registry_entry_id)
        self.assertIsNone(updated.external_catalog_identifier_id)


if __name__ == "__main__":
    unittest.main()
