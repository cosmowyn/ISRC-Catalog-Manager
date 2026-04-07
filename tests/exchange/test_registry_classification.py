import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from isrc_manager.code_registry import BUILTIN_CATEGORY_CATALOG_NUMBER, CodeRegistryService
from isrc_manager.exchange import ExchangeImportOptions, ExchangeService
from isrc_manager.releases import ReleaseService
from isrc_manager.services import (
    CustomFieldDefinitionService,
    DatabaseSchemaService,
    TrackService,
)


class ExchangeRegistryClassificationTests(unittest.TestCase):
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
        self.custom_defs = CustomFieldDefinitionService(self.conn)
        self.exchange_service = ExchangeService(
            self.conn,
            self.track_service,
            self.release_service,
            self.custom_defs,
            self.root,
        )
        self.registry = CodeRegistryService(self.conn)
        category = self.registry.fetch_category_by_system_key(BUILTIN_CATEGORY_CATALOG_NUMBER)
        assert category is not None
        self.registry.update_category(category.id, prefix="ACR")

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def test_import_reports_internal_external_and_mismatch_catalog_outcomes(self):
        yy = datetime.now().year % 100
        csv_path = self.root / "catalog-registry-import.csv"
        csv_path.write_text(
            "\n".join(
                [
                    "track_title,artist_name,isrc,catalog_number",
                    f"Internal Accepted,Moonwake,NL-ABC-26-21001,ACR{yy:02d}0001",
                    "External Stored,Moonwake,NL-ABC-26-21002,EXT-77",
                    "Mismatch Stored,Moonwake,NL-ABC-26-21003,ACRBAD",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        report = self.exchange_service.import_csv(
            csv_path,
            mapping={
                "track_title": "track_title",
                "artist_name": "artist_name",
                "isrc": "isrc",
                "catalog_number": "catalog_number",
            },
            options=ExchangeImportOptions(mode="create"),
        )

        self.assertEqual(report.failed, 0)
        self.assertEqual(report.passed, 3)
        self.assertEqual(report.internal_catalog_identifiers, 1)
        self.assertEqual(report.external_catalog_identifiers, 1)
        self.assertEqual(report.mismatched_catalog_identifiers, 1)
        self.assertEqual(len(report.catalog_classifications), 3)
        self.assertEqual(
            sorted(item.classification for item in report.catalog_classifications),
            ["external", "internal", "mismatch"],
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM Tracks WHERE catalog_registry_entry_id IS NOT NULL"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM Tracks WHERE external_catalog_identifier_id IS NOT NULL"
            ).fetchone()[0],
            2,
        )


if __name__ == "__main__":
    unittest.main()
