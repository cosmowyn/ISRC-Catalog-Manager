import sqlite3
import unittest

from isrc_manager.services import DatabaseSchemaService, GS1MetadataRecord, GS1MetadataRepository


def make_catalog_conn():
    conn = sqlite3.connect(":memory:")
    schema = DatabaseSchemaService(conn)
    schema.init_db()
    schema.migrate_schema()
    conn.execute("INSERT INTO Artists(id, name) VALUES (1, 'Main Artist')")
    conn.execute(
        """
        INSERT INTO Tracks(
            id, isrc, isrc_compact, track_title, main_artist_id, album_id, release_date, track_length_sec, iswc, upc, genre
        )
        VALUES(1, 'NL-ABC-26-00001', 'NLABC2600001', 'Test Release', 1, NULL, '2026-03-14', 180, NULL, '123456789012', 'Pop')
        """
    )
    conn.commit()
    return conn


class GS1MetadataRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_catalog_conn()
        self.repository = GS1MetadataRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_save_and_fetch_round_trip(self):
        saved = self.repository.save(
            GS1MetadataRecord(
                track_id=1,
                status="Concept",
                product_classification="Audio",
                consumer_unit_flag=True,
                packaging_type="Digital file",
                target_market="Worldwide",
                language="English",
                product_description="Test Release",
                brand="Orbit Label",
                subbrand="Series A",
                quantity="1",
                unit="Each",
                image_url="https://example.com/cover.png",
                notes="First save",
                export_enabled=True,
            )
        )

        fetched = self.repository.fetch_by_track_id(1)

        self.assertIsNotNone(saved.id)
        self.assertIsNotNone(saved.created_at)
        self.assertIsNotNone(saved.updated_at)
        self.assertEqual(fetched, saved)

    def test_save_updates_existing_row_without_creating_duplicate(self):
        first = self.repository.save(
            GS1MetadataRecord(
                track_id=1,
                status="Concept",
                product_classification="Audio",
                consumer_unit_flag=True,
                packaging_type="Digital file",
                target_market="Worldwide",
                language="English",
                product_description="First title",
                brand="Orbit Label",
                subbrand="",
                quantity="1",
                unit="Each",
                image_url="",
                notes="",
                export_enabled=True,
            )
        )

        updated = self.repository.save(
            GS1MetadataRecord(
                id=first.id,
                track_id=1,
                status="Active",
                product_classification="Audio",
                consumer_unit_flag=False,
                packaging_type="Digital file",
                target_market="Worldwide",
                language="English",
                product_description="Updated title",
                brand="Orbit Label",
                subbrand="Series B",
                quantity="2",
                unit="Each",
                image_url="https://example.com/new.png",
                notes="Updated",
                export_enabled=False,
                created_at=first.created_at,
                updated_at=first.updated_at,
            )
        )

        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM GS1Metadata").fetchone()[0], 1)
        self.assertEqual(updated.id, first.id)
        self.assertEqual(updated.product_description, "Updated title")
        self.assertEqual(updated.subbrand, "Series B")
        self.assertFalse(updated.consumer_unit_flag)
        self.assertFalse(updated.export_enabled)


if __name__ == "__main__":
    unittest.main()
