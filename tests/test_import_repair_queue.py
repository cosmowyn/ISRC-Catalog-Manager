import sqlite3
import time
import unittest

from isrc_manager.services.import_repair_queue import (
    TrackImportRepairQueueService,
    _clean_text,
    _json_dumps,
    _json_loads,
)


class TrackImportRepairQueueServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("""
            CREATE TABLE TrackImportRepairQueue(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_format TEXT,
                source_path TEXT,
                row_index INTEGER,
                import_mode TEXT,
                normalized_row_json TEXT,
                mapping_json TEXT,
                options_json TEXT,
                failure_category TEXT,
                failure_message TEXT,
                status TEXT,
                created_at TEXT,
                updated_at TEXT,
                resolved_at TEXT,
                resolved_track_id INTEGER,
                resolved_work_id INTEGER
            )
            """)
        self.service = TrackImportRepairQueueService(self.conn)

    def tearDown(self):
        self.conn.close()

    def _insert_entry(self, status: str = "pending") -> int:
        entry_id = self.service.queue_failed_row(
            source_format="CSV",
            source_path="/tmp/source.csv",
            row_index=2,
            import_mode="create",
            normalized_row={"track_title": "Demo"},
            mapping={"a": "1"},
            options={"encoding": "utf-8"},
            failure_category="schema",
            failure_message="bad row",
        )
        if status != "pending":
            if status == "resolved":
                self.service.mark_resolved(entry_id, track_id=11, work_id=22)
            else:
                self.service.update_entry(
                    entry_id,
                    normalized_row={"track_title": "Demo"},
                    failure_category="schema",
                    failure_message="bad row",
                )
                self.conn.execute(
                    "UPDATE TrackImportRepairQueue SET status=? WHERE id=?",
                    (status, entry_id),
                )
        return entry_id

    def test_json_helpers_normalize_and_ignore_invalid_values(self):
        self.assertEqual(_json_loads(None), {})
        self.assertEqual(_json_loads(""), {})
        self.assertEqual(_json_loads("not-json"), {})
        self.assertEqual(_clean_text(None), None)
        self.assertEqual(_clean_text("   "), None)
        self.assertEqual(_clean_text(" track "), "track")
        self.assertEqual(_json_dumps({"b": 1, "a": 2}), '{"a": 2, "b": 1}')

    def test_row_to_entry_filters_invalid_text_and_mapping_values(self):
        row = (
            7,
            "  CSV ",
            "   ",
            None,
            "",
            '{"a": 1, "b": 2}',
            '{"x": "ok", "": "skip", "y": "", "z": "7"}',
            "{broken}",
            "  ",
            "  message  ",
            "",
            None,
            " updated ",
            "",
            None,
            None,
        )
        entry = TrackImportRepairQueueService._row_to_entry(row)

        self.assertEqual(entry.id, 7)
        self.assertEqual(entry.source_format, "CSV")
        self.assertIsNone(entry.source_path)
        self.assertEqual(entry.row_index, 0)
        self.assertEqual(entry.import_mode, "create")
        self.assertEqual(entry.normalized_row, {"a": 1, "b": 2})
        self.assertEqual(entry.mapping, {"x": "ok", "z": "7"})
        self.assertEqual(entry.options, {})
        self.assertEqual(entry.failure_category, "validation")
        self.assertEqual(entry.failure_message, "message")
        self.assertEqual(entry.status, "pending")
        self.assertIsNone(entry.created_at)
        self.assertEqual(entry.updated_at, "updated")

    def test_queue_and_fetch_entry_normalizes_inputs(self):
        entry_id = self.service.queue_failed_row(
            source_format=" WAV ",
            source_path="   ",
            row_index=3,
            import_mode="",
            normalized_row={"track_title": "Demo"},
            mapping={"": "blank", "source": "value", "title": ""},
            options={"overwrite": True},
            failure_category="  schema ",
            failure_message="  invalid row  ",
        )
        entry = self.service.fetch_entry(entry_id)

        self.assertIsNotNone(entry)
        self.assertEqual(entry.source_format, "wav")
        self.assertIsNone(entry.source_path)
        self.assertEqual(entry.import_mode, "create")
        self.assertEqual(entry.mapping, {"source": "value"})
        self.assertTrue(entry.options["overwrite"])
        self.assertEqual(entry.failure_category, "schema")
        self.assertEqual(entry.failure_message, "invalid row")

    def test_list_entries_filters_by_status_and_supports_all_when_none(self):
        pending_id = self._insert_entry("pending")
        resolved_id = self._insert_entry("resolved")

        self.assertEqual([entry.id for entry in self.service.list_entries()], [pending_id])
        self.assertEqual(
            {entry.id for entry in self.service.list_entries(status=None)},
            {
                pending_id,
                resolved_id,
            },
        )
        self.assertEqual(
            [entry.id for entry in self.service.list_entries(status="resolved")], [resolved_id]
        )

    def test_update_entry_resets_state_and_preserves_optional_sections(self):
        entry_id = self._insert_entry("resolved")
        self.service.update_entry(
            entry_id,
            normalized_row={"track_title": "Updated"},
            failure_category="format",
            failure_message="bad mapping",
            mapping={"updated": "mapping"},
            options={"strict": "false"},
        )
        entry = self.service.fetch_entry(entry_id)

        self.assertEqual(entry.status, "pending")
        self.assertEqual(entry.normalized_row, {"track_title": "Updated"})
        self.assertEqual(entry.failure_category, "format")
        self.assertEqual(entry.failure_message, "bad mapping")
        self.assertEqual(entry.mapping, {"updated": "mapping"})
        self.assertEqual(entry.options, {"strict": "false"})
        self.assertIsNone(entry.resolved_at)

    def test_update_entry_can_update_only_required_fields(self):
        entry_id = self._insert_entry("resolved")
        self.service.update_entry(
            entry_id,
            normalized_row={"track_title": "Updated"},
            failure_category="schema",
            failure_message="revalidated",
        )
        entry = self.service.fetch_entry(entry_id)

        self.assertEqual(entry.status, "pending")
        self.assertEqual(entry.failure_category, "schema")
        self.assertEqual(entry.failure_message, "revalidated")
        self.assertEqual(entry.normalized_row["track_title"], "Updated")
        self.assertIsNone(entry.resolved_at)
        self.assertIsNone(entry.resolved_track_id)
        self.assertIsNone(entry.resolved_work_id)

    def test_update_entry_with_mapping_only(self):
        entry_id = self._insert_entry("resolved")
        self.service.update_entry(
            entry_id,
            normalized_row={"track_title": "Updated"},
            failure_category="schema",
            failure_message="revalidated",
            mapping={"updated": "mapping"},
        )
        entry = self.service.fetch_entry(entry_id)

        self.assertEqual(entry.mapping, {"updated": "mapping"})
        self.assertFalse(entry.status != "pending")

    def test_update_entry_with_options_only(self):
        entry_id = self._insert_entry("resolved")
        self.service.update_entry(
            entry_id,
            normalized_row={"track_title": "Updated"},
            failure_category="schema",
            failure_message="revalidated",
            options={"strict": "false"},
        )
        entry = self.service.fetch_entry(entry_id)

        self.assertEqual(entry.options, {"strict": "false"})
        self.assertTrue(entry.status == "pending")

    def test_mark_resolved_populates_resolution_fields(self):
        entry_id = self._insert_entry()
        self.service.mark_resolved(entry_id, track_id=101, work_id=202)
        entry = self.service.fetch_entry(entry_id)

        self.assertEqual(entry.status, "resolved")
        self.assertEqual(entry.resolved_track_id, 101)
        self.assertEqual(entry.resolved_work_id, 202)
        self.assertEqual(entry.failure_message, "")

    def test_delete_entries_deduplicates_and_ignores_non_positive_ids(self):
        first = self._insert_entry()
        second = self._insert_entry()
        deleted = self.service.delete_entries([first, second, first, 0, -1])

        self.assertEqual(deleted, 2)
        self.assertIsNone(self.service.fetch_entry(first))
        self.assertIsNone(self.service.fetch_entry(second))

    def test_delete_entries_returns_zero_for_empty_or_non_positive_inputs(self):
        first = self._insert_entry()
        self.assertEqual(self.service.delete_entries([]), 0)
        self.assertEqual(self.service.delete_entries([0, -1, -12]), 0)
        self.assertIsNotNone(self.service.fetch_entry(first))

    def test_touch_entry_refreshes_timestamps(self):
        entry_id = self._insert_entry()
        first_updated = self.conn.execute(
            "SELECT updated_at FROM TrackImportRepairQueue WHERE id=?",
            (entry_id,),
        ).fetchone()[0]

        time.sleep(1.05)
        self.service.touch_entry(entry_id)
        second_updated = self.conn.execute(
            "SELECT updated_at FROM TrackImportRepairQueue WHERE id=?",
            (entry_id,),
        ).fetchone()[0]

        self.assertNotEqual(first_updated, second_updated)

    def test_pending_count_reflects_only_pending_rows(self):
        self._insert_entry("pending")
        self._insert_entry("resolved")

        self.assertEqual(self.service.pending_count(), 1)


if __name__ == "__main__":
    unittest.main()
