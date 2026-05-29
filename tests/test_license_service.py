import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from isrc_manager.file_storage import STORAGE_MODE_DATABASE, STORAGE_MODE_MANAGED_FILE
from isrc_manager.services import LicenseService


def make_license_conn():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE Tracks (
            id INTEGER PRIMARY KEY,
            track_title TEXT NOT NULL
        );
        CREATE TABLE Licensees (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        );
        CREATE TABLE Licenses (
            id INTEGER PRIMARY KEY,
            track_id INTEGER NOT NULL,
            licensee_id INTEGER NOT NULL,
            file_path TEXT,
            filename TEXT NOT NULL,
            uploaded_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE VIEW vw_Licenses AS
        SELECT
            l.id,
            lic.name AS licensee,
            t.track_title AS tracktitle,
            l.uploaded_at,
            l.filename,
            l.file_path,
            l.track_id,
            l.licensee_id
        FROM Licenses l
        JOIN Licensees lic ON lic.id = l.licensee_id
        JOIN Tracks t ON t.id = l.track_id;
        """)
    conn.execute("INSERT INTO Tracks(id, track_title) VALUES (1, 'Song A')")
    conn.execute("INSERT INTO Tracks(id, track_title) VALUES (2, 'Song B')")
    conn.commit()
    return conn


class LicenseServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_license_conn()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmpdir.name)
        self.service = LicenseService(self.conn, self.data_dir)
        self.original_pdf = self.data_dir / "input.pdf"
        self.original_pdf.write_bytes(b"%PDF-1.4 original")
        self.replacement_pdf = self.data_dir / "replacement.pdf"
        self.replacement_pdf.write_bytes(b"%PDF-1.4 replacement")

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def test_add_license_copies_file_and_lists_row(self):
        record_id = self.service.add_license(
            track_id=1,
            licensee_name="Label A",
            source_pdf_path=self.original_pdf,
        )

        record = self.service.fetch_license(record_id)
        rows = self.service.list_rows()

        self.assertIsNotNone(record)
        self.assertEqual(record.track_id, 1)
        self.assertEqual(rows[0].licensee, "Label A")
        self.assertEqual(rows[0].track_title, "Song A")
        self.assertTrue(record.file_path.startswith("licenses/"))
        self.assertTrue(self.service.resolve_path(record.file_path).exists())
        self.assertEqual(
            self.service.resolve_path(record.file_path).read_bytes(), b"%PDF-1.4 original"
        )

    def test_update_and_delete_license_manage_current_file(self):
        record_id = self.service.add_license(
            track_id=1,
            licensee_name="Label A",
            source_pdf_path=self.original_pdf,
        )
        original_record = self.service.fetch_license(record_id)

        updated = self.service.update_license(
            record_id=record_id,
            licensee_name="Label B",
            replacement_pdf_path=self.replacement_pdf,
        )

        self.assertEqual(updated.licensee_id, 2)
        self.assertNotEqual(updated.file_path, original_record.file_path)
        self.assertTrue(self.service.resolve_path(updated.file_path).exists())
        self.assertEqual(
            self.service.resolve_path(updated.file_path).read_bytes(), b"%PDF-1.4 replacement"
        )
        self.assertTrue(
            self.service.resolve_path(original_record.file_path).exists(),
            "Replacing a license keeps the old stored PDF, matching current app behavior.",
        )

        deleted = self.service.delete_licenses([record_id], delete_files=True)
        self.assertEqual(deleted, 1)
        self.assertIsNone(self.service.fetch_license(record_id))
        self.assertFalse(self.service.resolve_path(updated.file_path).exists())

    def test_blank_licensee_name_on_update_keeps_existing_licensee(self):
        record_id = self.service.add_license(
            track_id=2,
            licensee_name="Existing Label",
            source_pdf_path=self.original_pdf,
        )
        record = self.service.fetch_license(record_id)

        updated = self.service.update_license(record_id=record_id, licensee_name="  ")

        self.assertEqual(updated.licensee_id, record.licensee_id)

    def test_storage_metadata_paths_and_filtered_rows(self):
        empty_conn = sqlite3.connect(":memory:")
        try:
            LicenseService(empty_conn, self.data_dir)
        finally:
            empty_conn.close()

        record_id = self.service.add_license(
            track_id=2,
            licensee_name="Filtered Label",
            source_pdf_path=self.original_pdf,
        )

        filtered_rows = self.service.list_rows(track_filter_id=2)
        choices = self.service.list_licensee_choices()

        self.assertEqual([row.record_id for row in filtered_rows], [record_id])
        self.assertIn((1, "Filtered Label"), choices)
        self.assertIsNone(self.service.fetch_license(99999))
        self.assertFalse(self.service.is_managed_license_path(""))
        stored = self.service.fetch_license(record_id)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertTrue(self.service.is_managed_license_path(stored.file_path))
        self.assertTrue(
            self.service.is_managed_license_path(str(self.service.resolve_path(stored.file_path)))
        )
        outside_file = self.data_dir.parent / "outside-license.pdf"
        outside_file.write_bytes(b"outside")
        self.assertFalse(self.service.is_managed_license_path(str(outside_file)))

    def test_database_storage_fetch_update_and_conversion_round_trip(self):
        record_id = self.service.add_license(
            track_id=1,
            licensee_name="Database Label",
            source_pdf_path=self.original_pdf,
            storage_mode=STORAGE_MODE_DATABASE,
        )
        record = self.service.fetch_license(record_id)

        self.assertIsNotNone(record)
        assert record is not None
        self.assertIsNone(record.file_path)
        self.assertEqual(record.storage_mode, STORAGE_MODE_DATABASE)
        self.assertEqual(
            self.service.fetch_license_bytes(record_id),
            (b"%PDF-1.4 original", "application/pdf"),
        )
        self.assertEqual(
            self.service.convert_storage_mode(record_id, STORAGE_MODE_DATABASE), record
        )

        updated = self.service.update_license(
            record_id=record_id,
            licensee_name="Managed Label",
            replacement_pdf_path=self.replacement_pdf,
            storage_mode=STORAGE_MODE_MANAGED_FILE,
        )
        self.assertEqual(updated.storage_mode, STORAGE_MODE_MANAGED_FILE)
        self.assertTrue(updated.file_path.startswith("licenses/"))
        self.assertEqual(
            self.service.fetch_license_bytes(record_id),
            (b"%PDF-1.4 replacement", "application/pdf"),
        )

        converted_to_db = self.service.convert_storage_mode(record_id, STORAGE_MODE_DATABASE)
        self.assertEqual(converted_to_db.storage_mode, STORAGE_MODE_DATABASE)
        self.assertIsNone(converted_to_db.file_path)
        converted_to_file = self.service.convert_storage_mode(record_id, STORAGE_MODE_MANAGED_FILE)
        self.assertEqual(converted_to_file.storage_mode, STORAGE_MODE_MANAGED_FILE)
        self.assertTrue(self.service.resolve_path(converted_to_file.file_path).exists())

    def test_missing_records_files_and_delete_edges_are_reported(self):
        with self.assertRaises(FileNotFoundError):
            self.service.fetch_license_bytes(404)
        with self.assertRaises(ValueError):
            self.service.update_license(
                record_id=404,
                licensee_name="Missing",
                replacement_pdf_path=self.replacement_pdf,
            )
        with self.assertRaises(ValueError):
            self.service.convert_storage_mode(404, STORAGE_MODE_DATABASE)
        with self.assertRaises(FileNotFoundError):
            self.service.add_license(
                track_id=1,
                licensee_name="Missing Source",
                source_pdf_path=self.data_dir / "missing.pdf",
            )
        self.assertEqual(self.service.delete_licenses([], delete_files=True), 0)

        record_id = self.service.add_license(
            track_id=1,
            licensee_name="Missing File",
            source_pdf_path=self.original_pdf,
        )
        record = self.service.fetch_license(record_id)
        self.assertIsNotNone(record)
        assert record is not None
        self.service.resolve_path(record.file_path).unlink()
        with self.assertRaises(FileNotFoundError):
            self.service.fetch_license_bytes(record_id)

        self.service.add_license(
            track_id=1,
            licensee_name="Delete Error",
            source_pdf_path=self.replacement_pdf,
        )
        with mock.patch.object(
            self.service,
            "resolve_path",
            side_effect=RuntimeError("path hazard"),
        ):
            self.assertEqual(self.service.delete_licenses([record_id], delete_files=True), 1)

    def test_unreadable_storage_edges_surface_as_missing_license_content(self):
        record_id = self.service.add_license(
            track_id=1,
            licensee_name="Blobless Label",
            source_pdf_path=self.original_pdf,
            storage_mode=STORAGE_MODE_DATABASE,
        )
        self.conn.execute("UPDATE Licenses SET file_blob=NULL WHERE id=?", (record_id,))
        with self.assertRaises(FileNotFoundError):
            self.service.fetch_license_bytes(record_id)

        file_record_id = self.service.add_license(
            track_id=1,
            licensee_name="Pathless Label",
            source_pdf_path=self.replacement_pdf,
        )
        self.conn.execute("UPDATE Licenses SET file_path='' WHERE id=?", (file_record_id,))
        with self.assertRaises(FileNotFoundError):
            self.service.fetch_license_bytes(file_record_id)

        with self.assertRaises(FileNotFoundError):
            self.service._store_license_source(self.data_dir / "missing-source.pdf")


if __name__ == "__main__":
    unittest.main()
