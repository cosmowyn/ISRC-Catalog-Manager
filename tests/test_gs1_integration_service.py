import sqlite3
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook
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


HEADERS = [
    "GS1 Artikelcode (GTIN)",
    "Status",
    "Productclassificatie",
    "Gaat naar de consument",
    "Verpakkings type",
    "Landen of Regio's",
    "Productomschrijving (max 300 tekens)",
    "Taal",
    "Merk",
    "Submerk",
    "Aantal",
    "Eenheid",
    "Afbeelding (max 500 tekens)",
]


def build_template(path: Path):
    workbook = Workbook()
    workbook.remove(workbook.active)
    instructions = workbook.create_sheet("Instructions")
    instructions["A1"] = "GS1 article code (GTIN)"
    instructions["A2"] = "Use 1, 2, 3 in the first column to request new GTINs."
    placeholder = workbook.create_sheet("{ContractNr}")
    placeholder.append(HEADERS)
    target = workbook.create_sheet("10070050")
    target.append(HEADERS)
    workbook.save(path)


def build_multi_contract_template(path: Path):
    workbook = Workbook()
    workbook.remove(workbook.active)
    workbook.create_sheet("Instructions")["A1"] = "GS1 article code (GTIN)"
    workbook.create_sheet("10064976").append(HEADERS)
    workbook.create_sheet("10070050").append(HEADERS)
    workbook.save(path)


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
    conn.execute("INSERT INTO Albums(id, title) VALUES (2, 'Solar Release')")
    conn.execute("INSERT INTO Albums(id, title) VALUES (3, 'Single')")
    conn.execute("INSERT INTO Albums(id, title) VALUES (4, 'single')")
    conn.execute(
        """
        INSERT INTO Tracks(
            id, isrc, isrc_compact, track_title, main_artist_id, album_id, release_date, track_length_sec, iswc, upc, genre
        )
        VALUES(1, 'NL-ABC-26-00001', 'NLABC2600001', 'Orbit Release', 1, 1, '2026-03-14', 180, NULL, '123456789012', 'Pop')
        """
    )
    conn.execute(
        """
        INSERT INTO Tracks(
            id, isrc, isrc_compact, track_title, main_artist_id, album_id, release_date, track_length_sec, iswc, upc, genre
        )
        VALUES(2, 'NL-ABC-26-00002', 'NLABC2600002', 'Orbit Reprise', 1, 1, '2026-03-14', 210, NULL, '999999999999', 'Pop')
        """
    )
    conn.execute(
        """
        INSERT INTO Tracks(
            id, isrc, isrc_compact, track_title, main_artist_id, album_id, release_date, track_length_sec, iswc, upc, genre
        )
        VALUES(3, 'NL-ABC-26-00003', 'NLABC2600003', 'Solar Flare', 1, 2, '2026-03-15', 195, NULL, '', 'Electronic')
        """
    )
    conn.execute(
        """
        INSERT INTO Tracks(
            id, isrc, isrc_compact, track_title, main_artist_id, album_id, release_date, track_length_sec, iswc, upc, genre
        )
        VALUES(4, 'NL-ABC-26-00004', 'NLABC2600004', 'Standalone Echo', 1, NULL, '2026-03-16', 205, NULL, '', 'Ambient')
        """
    )
    conn.execute(
        """
        INSERT INTO Tracks(
            id, isrc, isrc_compact, track_title, main_artist_id, album_id, release_date, track_length_sec, iswc, upc, genre
        )
        VALUES(5, 'NL-ABC-26-00005', 'NLABC2600005', 'Night Current', 1, 3, '2026-03-17', 215, NULL, '', 'Ambient')
        """
    )
    conn.execute(
        """
        INSERT INTO Tracks(
            id, isrc, isrc_compact, track_title, main_artist_id, album_id, release_date, track_length_sec, iswc, upc, genre
        )
        VALUES(6, 'NL-ABC-26-00006', 'NLABC2600006', 'Silent Orbit', 1, 4, '2026-03-18', 225, NULL, '', 'Ambient')
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
        self.service.settings_service.set_profile_defaults(GS1ProfileDefaults(contract_number="10070050"))

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

    def test_build_default_metadata_uses_active_contract_from_settings(self):
        self.service.settings_service.set_profile_defaults(
            GS1ProfileDefaults(
                contract_number="10070050",
                target_market="Worldwide",
                language="English",
                brand="Orbit Label",
                subbrand="",
                packaging_type="Digital file",
                product_classification="Audio",
            )
        )

        record = self.service.build_default_metadata(1, current_profile_path="/tmp/Orbit_Label.db", window_title="Orbit Window")

        self.assertEqual(record.contract_number, "10070050")

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

    def test_prepare_records_for_export_collapses_same_album_selection_to_one_product(self):
        prepared = self.service.prepare_records_for_export(
            [1, 2],
            current_profile_path="/tmp/Orbit_Label.db",
            window_title="Orbit Window",
        )

        self.assertEqual(len(prepared), 1)
        self.assertEqual(prepared[0].metadata.product_description, "Orbit Release")
        self.assertEqual(prepared[0].source_track_ids, (1, 2))
        self.assertEqual(prepared[0].source_track_labels, ("Orbit Release", "Orbit Reprise (Orbit Release)"))

    def test_build_metadata_groups_split_selection_into_album_groups_and_singles(self):
        groups = self.service.build_metadata_groups(
            [1, 2, 3, 4],
            current_profile_path="/tmp/Orbit_Label.db",
            window_title="Orbit Window",
        )

        self.assertEqual([group.display_title for group in groups], ["Orbit Release", "Solar Release", "Standalone Echo - Single"])
        self.assertEqual([group.track_ids for group in groups], [(1, 2), (3,), (4,)])
        self.assertEqual([group.mode for group in groups], ["album", "album", "single"])

    def test_prepare_records_for_export_groups_by_album_title_and_keeps_singles_separate(self):
        prepared = self.service.prepare_records_for_export(
            [1, 2, 3, 4],
            current_profile_path="/tmp/Orbit_Label.db",
            window_title="Orbit Window",
        )

        self.assertEqual(len(prepared), 3)
        self.assertEqual(prepared[0].metadata.product_description, "Orbit Release")
        self.assertEqual(prepared[1].metadata.product_description, "Solar Release")
        self.assertEqual(prepared[2].metadata.product_description, "Standalone Echo - Single")
        self.assertEqual(prepared[0].source_track_ids, (1, 2))
        self.assertEqual(prepared[1].source_track_ids, (3,))
        self.assertEqual(prepared[2].source_track_ids, (4,))

    def test_album_title_single_is_treated_as_a_single_not_an_album_group(self):
        groups = self.service.build_metadata_groups(
            [5, 6],
            current_profile_path="/tmp/Orbit_Label.db",
            window_title="Orbit Window",
        )

        self.assertEqual([group.display_title for group in groups], ["Night Current - Single", "Silent Orbit - Single"])
        self.assertEqual([group.mode for group in groups], ["single", "single"])
        self.assertEqual([group.track_ids for group in groups], [(5,), (6,)])

        prepared = self.service.prepare_records_for_export(
            [5, 6],
            current_profile_path="/tmp/Orbit_Label.db",
            window_title="Orbit Window",
        )

        self.assertEqual([record.metadata.product_description for record in prepared], ["Night Current - Single", "Silent Orbit - Single"])
        self.assertEqual(prepared[0].source_track_labels, ("Night Current",))
        self.assertEqual(prepared[1].source_track_labels, ("Silent Orbit",))

    def test_save_metadata_group_applies_album_values_to_every_track_in_group(self):
        group = self.service.build_metadata_groups(
            [1, 2],
            current_profile_path="/tmp/Orbit_Label.db",
            window_title="Orbit Window",
        )[0]
        record = group.record.copy()
        record.brand = "Unified Label"
        record.subbrand = "Album Series"
        record.target_market = "Worldwide"

        saved_records = self.service.save_metadata_group(group, record)

        self.assertEqual(len(saved_records), 2)
        self.assertEqual(self.service.repository.fetch_by_track_id(1).brand, "Unified Label")
        self.assertEqual(self.service.repository.fetch_by_track_id(2).brand, "Unified Label")
        self.assertEqual(self.service.repository.fetch_by_track_id(1).product_description, "Orbit Release")
        self.assertEqual(self.service.repository.fetch_by_track_id(2).product_description, "Orbit Release")

    def test_prepare_export_plan_includes_preview_and_upc_warning_details(self):
        template_path = Path(self.tmpdir.name) / "gs1-template.xlsx"
        build_template(template_path)

        plan = self.service.prepare_export_plan(
            [1, 2, 3, 4],
            template_path=str(template_path),
            current_profile_path="/tmp/Orbit_Label.db",
            window_title="Orbit Window",
        )

        self.assertEqual(plan.mode, "mixed_groups")
        self.assertEqual(plan.preview.headers[0], "GS1 Artikelcode (GTIN)")
        self.assertEqual(plan.preview.rows[0][0], "1")
        self.assertIn("Orbit Release", plan.preview.rows[0])
        self.assertIn("Solar Release", plan.preview.rows[1])
        self.assertIn("Standalone Echo - Single", plan.preview.rows[2])
        self.assertTrue(plan.warnings)
        self.assertIn("UPC/EAN", plan.warnings[0])
        self.assertIn("Orbit Release: 123456789012", plan.warnings[1])
        self.assertIn("Orbit Reprise (Orbit Release): 999999999999", plan.warnings[1])

    def test_prepare_export_plan_routes_preview_rows_by_contract_sheet(self):
        template_path = Path(self.tmpdir.name) / "gs1-multi-template.xlsx"
        build_multi_contract_template(template_path)
        self.service.repository.save(
            GS1MetadataRecord(
                track_id=1,
                contract_number="10064976",
                status="Concept",
                product_classification="Audio",
                consumer_unit_flag=True,
                packaging_type="Digital file",
                target_market="Worldwide",
                language="English",
                product_description="Orbit Release",
                brand="Orbit Label",
                subbrand="Series A",
                quantity="1",
                unit="Each",
                image_url="",
                notes="",
                export_enabled=True,
            )
        )
        self.service.repository.save(
            GS1MetadataRecord(
                track_id=3,
                contract_number="10070050",
                status="Concept",
                product_classification="Audio",
                consumer_unit_flag=True,
                packaging_type="Digital file",
                target_market="Worldwide",
                language="English",
                product_description="Solar Release",
                brand="Orbit Label",
                subbrand="Series A",
                quantity="1",
                unit="Each",
                image_url="",
                notes="",
                export_enabled=True,
            )
        )

        plan = self.service.prepare_export_plan(
            [1, 3],
            template_path=str(template_path),
            current_profile_path="/tmp/Orbit_Label.db",
            window_title="Orbit Window",
        )

        self.assertEqual(plan.preview.row_sheet_names, ("10064976", "10070050"))
        self.assertIn("contract sheets", plan.summary_lines[0])
        self.assertIn("Sheet '10064976': 1 product row(s).", plan.summary_lines)
        self.assertIn("Sheet '10070050': 1 product row(s).", plan.summary_lines)


if __name__ == "__main__":
    unittest.main()
