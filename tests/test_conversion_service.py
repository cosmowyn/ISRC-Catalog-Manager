import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from isrc_manager.conversion import ConversionService, ConversionTemplateStoreService
from isrc_manager.conversion.models import (
    MAPPING_KIND_CONSTANT,
    MAPPING_KIND_SKIP,
    MAPPING_KIND_SOURCE,
    MAPPING_KIND_UNMAPPED,
    REQUIRED_STATUS_OPTIONAL,
    REQUIRED_STATUS_REQUIRED,
    SOURCE_MODE_FILE,
    ConversionMappingEntry,
    ConversionSourceProfile,
    ConversionTargetField,
    ConversionTemplateProfile,
)


class _FakeExchangeService:
    def __init__(self):
        self.calls = []

    def export_rows(self, track_ids):
        normalized = list(track_ids or [])
        self.calls.append(normalized)
        rows = [
            {
                "track_id": track_id,
                "track_title": f"Track {track_id}",
                "catalog_number": f"CAT-{track_id}",
            }
            for track_id in normalized
        ]
        return ["track_id", "track_title", "catalog_number"], rows


class _FakeSettingsReadService:
    def __init__(self, *, sena_number="", owner_values=None):
        self.sena_number = sena_number
        self.owner_values = dict(owner_values or {})

    def load_sena_number(self):
        return self.sena_number

    def load_owner_party_settings(self):
        return SimpleNamespace(**self.owner_values)


class ConversionServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_csv(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_csv_template_export_preserves_dialect_and_trailing_rows(self):
        template_path = self._write_csv(
            "template.csv",
            "\nCatalog Number*;Title;Year\nTEMPLATE;Sample;2024\n\nFooter;Keep;Tail\n",
        )
        source_path = self._write_csv(
            "source.csv",
            "catalog_number,title,release_date\nCAT-001,Orbit,2025-04-06\nCAT-002,Signal,2024-11-09\n",
        )
        service = ConversionService()

        template_profile = service.inspect_template(template_path)
        source_profile = service.inspect_source_file(source_path)
        session = service.build_session(template_profile, source_profile)
        suggestions = service.suggest_mapping(session)
        session.mapping_entries = tuple(
            suggestions.get(field.field_key)
            or (
                ConversionMappingEntry(
                    target_field_key=field.field_key,
                    target_display_name=field.display_name,
                    mapping_kind=MAPPING_KIND_SOURCE,
                    source_field="release_date",
                    transform_name="date_to_year",
                )
                if field.field_key == "year"
                else ConversionMappingEntry(
                    target_field_key=field.field_key,
                    target_display_name=field.display_name,
                )
            )
            for field in template_profile.target_fields
        )

        preview = service.build_preview(session)
        self.assertEqual(preview.rendered_rows[0], ("CAT-001", "Orbit", "2025"))
        self.assertFalse(preview.blocking_issues)

        output_path = self.root / "converted.csv"
        result = service.export_preview(preview, output_path)

        self.assertEqual(result.exported_row_count, 2)
        exported_text = output_path.read_text(encoding="utf-8")
        self.assertIn("Catalog Number*;Title;Year", exported_text)
        self.assertIn("CAT-001;Orbit;2025", exported_text)
        self.assertIn("CAT-002;Signal;2024", exported_text)
        self.assertTrue(exported_text.rstrip().endswith("Footer;Keep;Tail"))

    def test_xlsx_template_export_clones_sample_row_style_for_appended_rows(self):
        template_path = self.root / "template.xlsx"
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Producer"
        worksheet["A1"] = "Catalog Number*"
        worksheet["B1"] = "Title"
        worksheet["C1"] = "Length"
        worksheet["A2"] = "TEMPLATE"
        worksheet["B2"] = "Sample"
        worksheet["C2"] = "00:00:00"
        worksheet["A2"].font = Font(bold=True)
        worksheet["B2"].fill = PatternFill("solid", fgColor="FFF2CC")
        workbook.create_sheet("Notes")
        workbook.save(template_path)

        source_path = self.root / "source.json"
        source_path.write_text(
            json.dumps(
                [
                    {"catalog_number": "CAT-100", "title": "First", "length_seconds": 245},
                    {"catalog_number": "CAT-200", "title": "Second", "length_seconds": 302},
                ]
            ),
            encoding="utf-8",
        )
        service = ConversionService()

        template_profile = service.inspect_template(template_path)
        source_profile = service.inspect_source_file(source_path)
        session = service.build_session(template_profile, source_profile)
        session.mapping_entries = (
            ConversionMappingEntry(
                target_field_key="catalog_number",
                target_display_name="Catalog Number*",
                mapping_kind=MAPPING_KIND_SOURCE,
                source_field="catalog_number",
            ),
            ConversionMappingEntry(
                target_field_key="title",
                target_display_name="Title",
                mapping_kind=MAPPING_KIND_SOURCE,
                source_field="title",
            ),
            ConversionMappingEntry(
                target_field_key="length",
                target_display_name="Length",
                mapping_kind=MAPPING_KIND_SOURCE,
                source_field="length_seconds",
                transform_name="duration_seconds_to_hms",
            ),
        )

        preview = service.build_preview(session)
        output_path = self.root / "converted.xlsx"
        service.export_preview(preview, output_path)

        exported = load_workbook(output_path)
        try:
            sheet = exported["Producer"]
            self.assertEqual(sheet["A2"].value, "CAT-100")
            self.assertEqual(sheet["B2"].value, "First")
            self.assertEqual(sheet["C2"].value, "00:04:05")
            self.assertEqual(sheet["A3"].value, "CAT-200")
            self.assertEqual(sheet["B3"].value, "Second")
            self.assertEqual(sheet["C3"].value, "00:05:02")
            self.assertTrue(sheet["A3"].font.bold)
            self.assertEqual(sheet["B3"].fill.fill_type, sheet["B2"].fill.fill_type)
            self.assertEqual(sheet["B3"].fill.fgColor.rgb, sheet["B2"].fill.fgColor.rgb)
            self.assertIn("Notes", exported.sheetnames)
        finally:
            exported.close()

    def test_xml_template_export_preserves_tree_and_xml_declaration(self):
        template_path = self.root / "template.xml"
        template_path.write_text(
            """<?xml version="1.0" encoding="utf-8"?>
<Envelope>
  <Meta>
    <Sender>Catalog Manager</Sender>
  </Meta>
  <Records>
    <Record code="TEMPLATE">
      <Title>Sample</Title>
      <Artist>Template Artist</Artist>
    </Record>
    <Record code="SECOND">
      <Title>Second</Title>
      <Artist>Second Artist</Artist>
    </Record>
  </Records>
</Envelope>
""",
            encoding="utf-8",
        )
        source_path = self.root / "source.xml"
        source_path.write_text(
            """<Rows>
  <Row code="CAT-1">
    <Title>Alpha</Title>
    <Artist>One</Artist>
  </Row>
  <Row code="CAT-2">
    <Title>Beta</Title>
    <Artist>Two</Artist>
  </Row>
</Rows>
""",
            encoding="utf-8",
        )
        service = ConversionService()

        template_profile = service.inspect_template(template_path)
        source_profile = service.inspect_source_file(source_path)
        session = service.build_session(template_profile, source_profile)
        suggestions = service.suggest_mapping(session)
        session.mapping_entries = tuple(
            suggestions.get(field.field_key)
            or ConversionMappingEntry(
                target_field_key=field.field_key,
                target_display_name=field.display_name,
                mapping_kind=MAPPING_KIND_SOURCE,
                source_field=field.display_name,
            )
            for field in template_profile.target_fields
        )

        preview = service.build_preview(session)
        output_path = self.root / "converted.xml"
        service.export_preview(preview, output_path)

        xml_text = output_path.read_text(encoding="utf-8")
        self.assertTrue(xml_text.lstrip().startswith("<?xml"))
        root = ET.fromstring(xml_text)
        self.assertEqual(root.findtext("./Meta/Sender"), "Catalog Manager")
        records = root.findall("./Records/Record")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].attrib["code"], "CAT-1")
        self.assertEqual(records[0].findtext("Title"), "Alpha")
        self.assertEqual(records[1].attrib["code"], "CAT-2")
        self.assertEqual(records[1].findtext("Artist"), "Two")

    def test_database_source_uses_exchange_export_rows(self):
        exchange_service = _FakeExchangeService()
        settings_read_service = _FakeSettingsReadService(
            sena_number="SENA-778899",
            owner_values={
                "party_id": 12,
                "legal_name": "Aeon Cosmowyn Records B.V.",
                "company_name": "Cosmowyn Records",
                "display_name": "Cosmowyn Records",
                "email": "hello@cosmowyn.test",
            },
        )
        service = ConversionService(
            exchange_service=exchange_service,
            settings_read_service=settings_read_service,
        )

        profile = service.inspect_database_tracks([7, 11])

        self.assertEqual(exchange_service.calls, [[7, 11]])
        self.assertEqual(profile.source_mode, "database_tracks")
        self.assertEqual(
            profile.headers,
            (
                "track_id",
                "track_title",
                "catalog_number",
                "pro_number",
                "owner_party_id",
                "owner_legal_name",
                "owner_display_name",
                "owner_artist_name",
                "owner_company_name",
                "owner_first_name",
                "owner_middle_name",
                "owner_last_name",
                "owner_contact_person",
                "owner_email",
                "owner_alternative_email",
                "owner_phone",
                "owner_website",
                "owner_street_name",
                "owner_street_number",
                "owner_address_line1",
                "owner_address_line2",
                "owner_city",
                "owner_region",
                "owner_postal_code",
                "owner_country",
                "owner_bank_account_number",
                "owner_chamber_of_commerce_number",
                "owner_tax_id",
                "owner_vat_number",
                "owner_pro_affiliation",
                "owner_pro_number",
                "owner_ipi_cae",
            ),
        )
        self.assertEqual(profile.rows[0]["track_title"], "Track 7")
        self.assertEqual(profile.rows[0]["pro_number"], "SENA-778899")
        self.assertEqual(profile.rows[0]["owner_party_id"], "12")
        self.assertEqual(profile.rows[0]["owner_legal_name"], "Aeon Cosmowyn Records B.V.")
        self.assertEqual(profile.rows[0]["owner_company_name"], "Cosmowyn Records")
        self.assertEqual(profile.rows[0]["owner_email"], "hello@cosmowyn.test")
        self.assertTrue(any("release-aware" in warning.lower() for warning in profile.warnings))

    def test_preview_blocks_unmapped_required_targets_and_supports_constants(self):
        service = ConversionService()
        template_profile = ConversionTemplateProfile(
            template_path=self.root / "virtual.csv",
            format_name="csv",
            output_suffix=".csv",
            structure_label="Virtual CSV",
            target_fields=(
                ConversionTargetField(
                    field_key="catalog_number",
                    display_name="Catalog Number*",
                    location="CSV!A1",
                    required_status=REQUIRED_STATUS_REQUIRED,
                ),
                ConversionTargetField(
                    field_key="territory",
                    display_name="Territory",
                    location="CSV!B1",
                    required_status=REQUIRED_STATUS_OPTIONAL,
                ),
            ),
            template_signature="csv|virtual|catalog_number,territory",
        )
        source_profile = ConversionSourceProfile(
            source_mode=SOURCE_MODE_FILE,
            format_name="json",
            source_label="memory",
            headers=("catalog number",),
            rows=({"catalog number": "CAT-55"},),
            preview_rows=({"catalog number": "CAT-55"},),
        )
        session = service.build_session(template_profile, source_profile)

        preview = service.build_preview(session)
        self.assertTrue(preview.blocking_issues)

        suggestions = service.suggest_mapping(session)
        session.mapping_entries = (
            suggestions["catalog_number"],
            ConversionMappingEntry(
                target_field_key="territory",
                target_display_name="Territory",
                mapping_kind=MAPPING_KIND_CONSTANT,
                constant_value="Worldwide",
            ),
        )
        preview = service.build_preview(session)

        self.assertFalse(preview.blocking_issues)
        self.assertEqual(preview.rendered_rows[0], ("CAT-55", "Worldwide"))
        self.assertEqual(preview.mapping_entries[0].mapping_kind, MAPPING_KIND_SOURCE)
        self.assertNotEqual(preview.mapping_entries[0].mapping_kind, MAPPING_KIND_UNMAPPED)

    def test_preview_allows_optional_skip_without_empty_value_warning(self):
        service = ConversionService()
        template_profile = ConversionTemplateProfile(
            template_path=self.root / "virtual.csv",
            format_name="csv",
            output_suffix=".csv",
            structure_label="Virtual CSV",
            target_fields=(
                ConversionTargetField(
                    field_key="catalog_number",
                    display_name="Catalog Number*",
                    location="CSV!A1",
                    required_status=REQUIRED_STATUS_REQUIRED,
                ),
                ConversionTargetField(
                    field_key="territory",
                    display_name="Territory",
                    location="CSV!B1",
                    required_status=REQUIRED_STATUS_OPTIONAL,
                ),
            ),
            template_signature="csv|virtual|catalog_number,territory",
        )
        source_profile = ConversionSourceProfile(
            source_mode=SOURCE_MODE_FILE,
            format_name="json",
            source_label="memory",
            headers=("catalog number",),
            rows=({"catalog number": "CAT-55"},),
            preview_rows=({"catalog number": "CAT-55"},),
        )
        session = service.build_session(template_profile, source_profile)
        suggestions = service.suggest_mapping(session)
        session.mapping_entries = (
            suggestions["catalog_number"],
            ConversionMappingEntry(
                target_field_key="territory",
                target_display_name="Territory",
                mapping_kind=MAPPING_KIND_SKIP,
            ),
        )

        preview = service.build_preview(session)

        self.assertFalse(preview.blocking_issues)
        self.assertEqual(preview.rendered_rows[0], ("CAT-55", ""))
        self.assertNotIn("Territory", " ".join(preview.warnings))
        self.assertEqual(preview.mapping_entries[1].status, "skipped")

    def test_preview_blocks_required_skip(self):
        service = ConversionService()
        template_profile = ConversionTemplateProfile(
            template_path=self.root / "virtual.csv",
            format_name="csv",
            output_suffix=".csv",
            structure_label="Virtual CSV",
            target_fields=(
                ConversionTargetField(
                    field_key="catalog_number",
                    display_name="Catalog Number*",
                    location="CSV!A1",
                    required_status=REQUIRED_STATUS_REQUIRED,
                ),
            ),
            template_signature="csv|virtual|catalog_number",
        )
        source_profile = ConversionSourceProfile(
            source_mode=SOURCE_MODE_FILE,
            format_name="json",
            source_label="memory",
            headers=("catalog number",),
            rows=({"catalog number": "CAT-55"},),
            preview_rows=({"catalog number": "CAT-55"},),
        )
        session = service.build_session(template_profile, source_profile)
        session.mapping_entries = (
            ConversionMappingEntry(
                target_field_key="catalog_number",
                target_display_name="Catalog Number*",
                mapping_kind=MAPPING_KIND_SKIP,
            ),
        )

        preview = service.build_preview(session)

        self.assertIn("Required target 'Catalog Number*' is skipped.", preview.blocking_issues)

    def test_saved_template_store_round_trips_template_bytes_and_mapping(self):
        conn = sqlite3.connect(":memory:")
        try:
            service = ConversionService()
            store = ConversionTemplateStoreService(conn)
            template_path = self._write_csv(
                "template.csv",
                "Catalog Number*;Title;Year\nTEMPLATE;Sample;2024\n",
            )
            source_path = self._write_csv(
                "source.csv",
                "catalog_number,title,release_date\nCAT-001,Orbit,2025-04-06\n",
            )

            template_profile = service.inspect_template(template_path)
            source_profile = service.inspect_source_file(source_path)
            session = service.build_session(template_profile, source_profile)
            suggestions = service.suggest_mapping(session)
            session.mapping_entries = (
                suggestions["catalog_number"],
                suggestions["title"],
                ConversionMappingEntry(
                    target_field_key="year",
                    target_display_name="Year",
                    mapping_kind=MAPPING_KIND_CONSTANT,
                    constant_value="2030",
                ),
            )
            mapping_payload = service.serialize_mapping_entries(session.mapping_entries)

            stored = store.save_template(
                name="Producer Export",
                template_profile=template_profile,
                mapping_payload=mapping_payload,
                source_mode=SOURCE_MODE_FILE,
            )

            listed = store.list_saved_templates()
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0].name, "Producer Export")
            self.assertEqual(listed[0].source_mode, SOURCE_MODE_FILE)
            self.assertIsNone(listed[0].template_bytes)

            loaded = store.load_saved_template(stored.id)
            self.assertIsNotNone(loaded.template_bytes)
            self.assertEqual(loaded.mapping_payload, mapping_payload)

            loaded_profile = service.inspect_template_bytes(
                loaded.filename,
                loaded.template_bytes or b"",
                source_label=f"Saved in profile: {loaded.name}",
                source_path=loaded.source_path,
            )
            loaded_entries = service.deserialize_mapping_entries(
                loaded.mapping_payload,
                loaded_profile,
            )

            self.assertEqual(len(loaded_entries), 3)
            self.assertEqual(loaded_entries[2].mapping_kind, MAPPING_KIND_CONSTANT)
            self.assertEqual(loaded_entries[2].constant_value, "2030")
            self.assertEqual(loaded_profile.template_bytes, loaded.template_bytes)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
