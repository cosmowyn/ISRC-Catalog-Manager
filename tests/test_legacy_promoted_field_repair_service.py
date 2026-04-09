import tempfile
import unittest
from pathlib import Path

from isrc_manager.services import (
    DatabaseSchemaService,
    DatabaseSessionService,
    LegacyPromotedFieldRepairService,
    TrackCreatePayload,
    TrackService,
)


class LegacyPromotedFieldRepairServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.db_path = self.root / "Database" / "library.db"
        session = DatabaseSessionService().open(self.db_path)
        self.conn = session.conn
        self.schema = DatabaseSchemaService(self.conn, data_root=self.root / "data")
        self.schema.init_db()
        self.schema.migrate_schema()
        self.service = LegacyPromotedFieldRepairService(self.conn)
        self.track_service = TrackService(self.conn, self.root / "data")

        self.track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00001",
                track_title="Repair Track",
                artist_name="Repair Artist",
                additional_artists=[],
                album_title="Repair Album",
                release_date="2026-03-16",
                track_length_sec=180,
                iswc=None,
                upc=None,
                genre="Test",
            )
        )

    def tearDown(self):
        DatabaseSessionService.close(self.conn)
        self.tmpdir.cleanup()

    def test_repair_candidates_merges_safe_values_and_removes_redundant_field(self):
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO CustomFieldDefs(id, name, active, sort_order, field_type, options)
                VALUES (1, 'Catalog#', 1, 1, 'dropdown', '["CAT-01"]')
                """
            )
            self.conn.execute(
                """
                INSERT INTO CustomFieldValues(track_id, field_def_id, value, blob_value, mime_type, size_bytes)
                VALUES (?, 1, 'CAT-01', NULL, NULL, 0)
                """,
                (self.track_id,),
            )

        candidates = self.service.inspect_candidates()
        self.assertEqual(len(candidates), 1)
        self.assertTrue(candidates[0].eligible)
        self.assertEqual(candidates[0].custom_field_type, "dropdown")
        self.assertEqual(candidates[0].default_field_type, "text")

        result = self.service.repair_candidates()

        self.assertEqual(result.repaired_field_names, ("Catalog#",))
        self.assertEqual(result.skipped_field_names, ())
        self.assertEqual(result.merged_value_count, 1)
        self.assertEqual(
            self.conn.execute(
                "SELECT catalog_number FROM Tracks WHERE id=?", (self.track_id,)
            ).fetchone()[0],
            "CAT-01",
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM CustomFieldDefs").fetchone()[0],
            0,
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM CustomFieldValues").fetchone()[0],
            0,
        )

    def test_repair_candidates_skips_conflicting_default_values(self):
        with self.conn:
            self.conn.execute(
                "UPDATE Tracks SET catalog_number='CAT-DEFAULT' WHERE id=?",
                (self.track_id,),
            )
            self.conn.execute(
                """
                INSERT INTO CustomFieldDefs(id, name, active, sort_order, field_type, options)
                VALUES (1, 'Catalog#', 1, 1, 'dropdown', '["CAT-LEGACY"]')
                """
            )
            self.conn.execute(
                """
                INSERT INTO CustomFieldValues(track_id, field_def_id, value, blob_value, mime_type, size_bytes)
                VALUES (?, 1, 'CAT-LEGACY', NULL, NULL, 0)
                """,
                (self.track_id,),
            )

        candidates = self.service.inspect_candidates()
        self.assertEqual(len(candidates), 1)
        self.assertFalse(candidates[0].eligible)
        self.assertEqual(candidates[0].conflicting_track_ids, (self.track_id,))

        result = self.service.repair_candidates()

        self.assertEqual(result.repaired_field_names, ())
        self.assertEqual(result.skipped_field_names, ("Catalog#",))
        self.assertEqual(
            self.conn.execute(
                "SELECT catalog_number FROM Tracks WHERE id=?", (self.track_id,)
            ).fetchone()[0],
            "CAT-DEFAULT",
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM CustomFieldDefs").fetchone()[0],
            1,
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM CustomFieldValues").fetchone()[0],
            1,
        )


if __name__ == "__main__":
    unittest.main()
