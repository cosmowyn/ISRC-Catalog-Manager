import unittest

from isrc_manager.parties import PartyExchangeInspection
from isrc_manager.parties.dialogs import PartyImportDialog
from tests.qt_test_helpers import pump_events, require_qapplication


class _FakeSettings:
    def __init__(self):
        self._values = {}

    def value(self, key, default=None, _type=None):
        return self._values.get(key, default)

    def setValue(self, key, value):
        self._values[key] = value

    def sync(self):
        return None


class PartyImportDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = require_qapplication()

    def test_dialog_uses_exchange_style_tabs_and_party_specific_modes(self):
        dialog = PartyImportDialog(
            inspection=PartyExchangeInspection(
                file_path="/tmp/parties.json",
                format_name="json",
                headers=["legal_name", "display_name"],
                preview_rows=[{"legal_name": "Aeonium", "display_name": "Aeonium"}],
                suggested_mapping={
                    "legal_name": "legal_name",
                    "display_name": "display_name",
                },
            ),
            supported_headers=["legal_name", "display_name", "artist_aliases", "is_owner"],
            settings=_FakeSettings(),
        )
        try:
            self.assertEqual(dialog.windowTitle(), "Import Parties from JSON")
            self.assertEqual(dialog.content_tabs.tabText(0), "Setup & Mapping")
            self.assertEqual(dialog.content_tabs.tabText(1), "Source Preview")
            self.assertEqual(dialog.mode_combo.currentData(), "dry_run")
            self.assertEqual(dialog.import_button.text(), "Run Validation")
            self.assertTrue(dialog.match_internal_checkbox.isChecked())
            self.assertTrue(dialog.match_legal_name_checkbox.isChecked())
            self.assertTrue(dialog.match_identity_checkbox.isChecked())
            self.assertTrue(dialog.match_name_fields_checkbox.isChecked())
            self.assertIsNotNone(dialog.findChild(type(dialog.content_tabs), "partyImportTabs"))
        finally:
            dialog.close()

    def test_csv_dialog_reinspects_preview_and_preserves_mapping(self):
        refresh_calls = []
        initial_inspection = PartyExchangeInspection(
            file_path="/tmp/parties.csv",
            format_name="csv",
            headers=["Legal Name"],
            preview_rows=[{"Legal Name": "Aeonium"}],
            suggested_mapping={"Legal Name": "legal_name"},
            resolved_delimiter=",",
        )

        def _reinspect(delimiter):
            refresh_calls.append(delimiter)
            return PartyExchangeInspection(
                file_path="/tmp/parties.csv",
                format_name="csv",
                headers=["Legal Name", "Owner"],
                preview_rows=[{"Legal Name": "Aeonium", "Owner": "true"}],
                suggested_mapping={
                    "Legal Name": "legal_name",
                    "Owner": "is_owner",
                },
                resolved_delimiter=delimiter or ",",
            )

        dialog = PartyImportDialog(
            inspection=initial_inspection,
            supported_headers=["legal_name", "display_name", "is_owner"],
            settings=_FakeSettings(),
            csv_reinspect_callback=_reinspect,
        )
        try:
            mapping_combo = dialog.mapping_table.cellWidget(0, 1)
            mapping_combo.setCurrentText("legal_name")
            delimiter_combo = dialog.delimiter_combo
            assert delimiter_combo is not None
            delimiter_combo.setCurrentIndex(delimiter_combo.findData(";"))
            pump_events(app=self.app, cycles=2)

            self.assertEqual(refresh_calls, [";"])
            self.assertEqual(dialog.preview_table.columnCount(), 2)
            self.assertEqual(dialog.mapping()["Legal Name"], "legal_name")
            self.assertEqual(dialog.mapping()["Owner"], "is_owner")
            self.assertEqual(dialog.resolved_csv_delimiter(), ";")
        finally:
            dialog.close()

    def test_custom_invalid_delimiter_disables_import_button(self):
        inspection = PartyExchangeInspection(
            file_path="/tmp/parties.csv",
            format_name="csv",
            headers=["legal_name"],
            preview_rows=[{"legal_name": "Aeonium"}],
            suggested_mapping={"legal_name": "legal_name"},
            resolved_delimiter=",",
        )
        dialog = PartyImportDialog(
            inspection=inspection,
            supported_headers=["legal_name", "display_name"],
            settings=_FakeSettings(),
            csv_reinspect_callback=lambda delimiter: inspection,
        )
        try:
            delimiter_combo = dialog.delimiter_combo
            custom_edit = dialog.custom_delimiter_edit
            assert delimiter_combo is not None
            assert custom_edit is not None

            delimiter_combo.setCurrentIndex(delimiter_combo.findData("custom"))
            pump_events(app=self.app)
            self.assertFalse(dialog.import_button.isEnabled())

            custom_edit.setText("||")
            pump_events(app=self.app)
            self.assertFalse(dialog.import_button.isEnabled())

            custom_edit.setText("^")
            pump_events(app=self.app)
            self.assertTrue(dialog.import_button.isEnabled())
            self.assertEqual(dialog.resolved_csv_delimiter(), "^")
        finally:
            dialog.close()
