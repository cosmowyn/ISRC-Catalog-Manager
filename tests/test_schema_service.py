import sqlite3
import unittest

from isrc_manager.constants import SCHEMA_TARGET
from isrc_manager.services import DatabaseSchemaService


class DatabaseSchemaServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.service = DatabaseSchemaService(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_init_db_and_migrate_schema_reach_current_target(self):
        self.service.init_db()
        self.service.migrate_schema()

        tables = {
            row[0]
            for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')").fetchall()
        }
        value_columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(CustomFieldValues)").fetchall()
        }
        track_indexes = {
            row[1] for row in self.conn.execute("PRAGMA index_list(Tracks)").fetchall()
        }
        triggers = {
            row[0] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
        }

        self.assertEqual(self.service.get_db_version(), SCHEMA_TARGET)
        self.assertIn("Licensees", tables)
        self.assertIn("vw_Licenses", tables)
        self.assertTrue({"blob_value", "mime_type", "size_bytes"} <= value_columns)
        self.assertIn("idx_tracks_isrc_compact_unique", track_indexes)
        self.assertIn("trg_auditlog_no_update", triggers)


if __name__ == "__main__":
    unittest.main()
