import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.services import LicenseService


def make_license_conn():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
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
            file_path TEXT NOT NULL,
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
        """
    )
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
        self.assertEqual(self.service.resolve_path(record.file_path).read_bytes(), b"%PDF-1.4 original")

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
        self.assertEqual(self.service.resolve_path(updated.file_path).read_bytes(), b"%PDF-1.4 replacement")
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


if __name__ == "__main__":
    unittest.main()
