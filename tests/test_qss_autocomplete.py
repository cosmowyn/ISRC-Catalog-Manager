import unittest

from tests.qt_test_helpers import require_qapplication

try:
    from PySide6.QtGui import QTextCursor
    from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

    from isrc_manager.qss_autocomplete import QssCodeEditor, QssCompletionEngine, parse_qss_context
    from isrc_manager.qss_reference import collect_qss_reference_entries
except Exception as exc:  # pragma: no cover - environment-specific fallback
    QSS_AUTOCOMPLETE_IMPORT_ERROR = exc
else:
    QSS_AUTOCOMPLETE_IMPORT_ERROR = None

try:
    import ISRC_manager as app_module
except Exception as exc:  # pragma: no cover - environment-specific fallback
    app_module = None
    APP_IMPORT_ERROR = exc
else:
    APP_IMPORT_ERROR = None


def _build_reference_entries():
    root = QWidget()
    root.setObjectName("demoRoot")
    layout = QVBoxLayout(root)
    root.save_button = QPushButton("Save", root)
    root.cancel_button = QPushButton("Cancel", root)
    root.filter_label = QLabel("Helper", root)
    root.filter_label.setProperty("role", "secondary")
    layout.addWidget(root.save_button)
    layout.addWidget(root.cancel_button)
    layout.addWidget(root.filter_label)
    try:
        return collect_qss_reference_entries([root])
    finally:
        root.close()


class QssAutocompleteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QSS_AUTOCOMPLETE_IMPORT_ERROR is not None:
            raise unittest.SkipTest(
                f"QSS autocomplete helpers unavailable: {QSS_AUTOCOMPLETE_IMPORT_ERROR}"
            )
        cls.app = require_qapplication()
        cls.reference_entries = _build_reference_entries()

    def setUp(self):
        self.engine = QssCompletionEngine()
        self.engine.set_reference_entries(self.reference_entries)

    def _completion_labels(self, text: str) -> list[str]:
        return [item.label for item in self.engine.completion_items(text, len(text))]

    def test_selector_context_detects_widget_prefix(self):
        context = parse_qss_context("QPushBut", len("QPushBut"))
        self.assertEqual(context.mode, "selector")
        self.assertEqual(context.fragment_text, "QPushBut")
        self.assertEqual(context.compound_parts.widget_class, "QPushBut")

    def test_selector_completion_offers_widget_and_template_items(self):
        labels = self._completion_labels("QPushBut")
        self.assertIn("QPushButton [selector]", labels)
        self.assertIn("QPushButton { … } [template]", labels)

    def test_object_name_completion_appends_without_rewriting_selector(self):
        text = "QPushButton"
        item = next(
            item
            for item in self.engine.completion_items(text, len(text))
            if item.kind == "object_name" and item.value == "#save_button"
        )
        edit = self.engine.completion_edit(text, len(text), item)
        self.assertIsNotNone(edit)
        new_text = text[: edit.replace_start] + edit.text + text[edit.replace_end :]
        self.assertEqual(new_text, "QPushButton#save_button")

    def test_object_name_completion_inserts_before_existing_pseudo_state(self):
        text = "QPushButton:hover"
        item = next(
            item
            for item in self.engine.completion_items(text, len(text))
            if item.kind == "object_name" and item.value == "#save_button"
        )
        edit = self.engine.completion_edit(text, len(text), item)
        self.assertIsNotNone(edit)
        new_text = text[: edit.replace_start] + edit.text + text[edit.replace_end :]
        self.assertEqual(new_text, "QPushButton#save_button:hover")

    def test_subcontrol_completion_only_exposes_valid_scrollbar_subcontrols(self):
        labels = self._completion_labels("QScrollBar::")
        self.assertIn("::handle [subcontrol]", labels)
        self.assertIn("::add-line [subcontrol]", labels)
        self.assertFalse(any(":hover [append pseudo-state]" == label for label in labels))
        self.assertFalse(any("QPushButton [selector]" == label for label in labels))

    def test_property_completion_inside_rule_body_avoids_selector_templates(self):
        text = "QPushButton {\n    bac\n}"
        labels = self._completion_labels(text[:-2])
        self.assertIn("background-color: ; [property]", labels)
        self.assertFalse(any(label.endswith("[selector]") for label in labels))

    def test_property_value_completion_inside_rule_body_suggests_values(self):
        text = "QPushButton {\n    background-color: \n}"
        labels = self._completion_labels(text[:-2])
        self.assertIn("transparent [value]", labels)
        self.assertIn("palette(button) [value]", labels)

    def test_complete_selector_inside_block_body_does_not_offer_rule_templates(self):
        text = "QPushButton {\n    color: red;\n}"
        labels = self._completion_labels(text[: text.index("}")])
        self.assertFalse(any("[template]" in label for label in labels))

    def test_duplicate_pseudo_state_is_not_suggested_twice(self):
        labels = self._completion_labels("QPushButton:hover")
        self.assertFalse(any(label == ":hover [append pseudo-state]" for label in labels))

    def test_context_detection_reports_property_value_mode(self):
        text = "QPushButton {\n    background-color: pal\n}"
        context = parse_qss_context(text, text.index("pal") + 3)
        self.assertEqual(context.mode, "property_value")
        self.assertEqual(context.current_property_name, "background-color")
        self.assertEqual(context.active_widget_class, "QPushButton")

    def test_descendant_selector_object_name_keeps_leading_selector_intact(self):
        text = "#mainWindow QPushButton:hover"
        item = next(
            item
            for item in self.engine.completion_items(text, len(text))
            if item.kind == "object_name" and item.value == "#save_button"
        )
        edit = self.engine.completion_edit(text, len(text), item)
        self.assertIsNotNone(edit)
        new_text = text[: edit.replace_start] + edit.text + text[edit.replace_end :]
        self.assertEqual(new_text, "#mainWindow QPushButton#save_button:hover")

    def test_widget_specific_object_names_are_exposed_from_live_index(self):
        labels = self._completion_labels("QPushButton")
        self.assertIn("#save_button [append object reference]", labels)
        self.assertIn("#cancel_button [append object reference]", labels)

    def test_full_rule_template_inserts_complete_block(self):
        text = "QPushBut"
        item = next(
            item
            for item in self.engine.completion_items(text, len(text))
            if item.label == "QPushButton { … } [template]"
        )
        edit = self.engine.completion_edit(text, len(text), item)
        self.assertIsNotNone(edit)
        new_text = text[: edit.replace_start] + edit.text + text[edit.replace_end :]
        self.assertIn("QPushButton {", new_text)
        self.assertIn("background-color: ;", new_text)
        self.assertTrue(new_text.rstrip().endswith("}"))

    def test_editor_completion_items_follow_current_context(self):
        editor = QssCodeEditor()
        editor.set_reference_entries(self.reference_entries)
        try:
            editor.setPlainText("QPushButton")
            cursor = editor.textCursor()
            cursor.movePosition(QTextCursor.End)
            editor.setTextCursor(cursor)
            items = editor.current_completion_items()
            if not items:
                editor._refresh_completion_items()
                items = editor.current_completion_items()
            labels = [item.label for item in items]
            self.assertIn("#save_button [append object reference]", labels)
            self.assertIn(":hover [append pseudo-state]", labels)
        finally:
            editor.close()

    def test_editor_integration_keeps_selector_safe_when_object_completion_applies(self):
        editor = QssCodeEditor()
        editor.set_reference_entries(self.reference_entries)
        try:
            editor.setPlainText("QPushButton:hover")
            cursor = editor.textCursor()
            cursor.movePosition(QTextCursor.End)
            editor.setTextCursor(cursor)
            editor._refresh_completion_items()
            item = next(
                item
                for item in editor.current_completion_items()
                if item.kind == "object_name" and item.value == "#save_button"
            )
            editor.apply_completion_item(item)
            self.assertEqual(editor.toPlainText(), "QPushButton#save_button:hover")
        finally:
            editor.close()

    def test_editor_accepts_string_based_completer_activation(self):
        editor = QssCodeEditor()
        editor.set_reference_entries(self.reference_entries)
        try:
            editor.setPlainText("QPushButton")
            cursor = editor.textCursor()
            cursor.movePosition(QTextCursor.End)
            editor.setTextCursor(cursor)
            editor._refresh_completion_items()
            label = next(
                item.label
                for item in editor.current_completion_items()
                if item.kind == "object_name" and item.value == "#save_button"
            )
            editor._apply_completion_from_index(label)
            self.assertEqual(editor.toPlainText(), "QPushButton#save_button")
        finally:
            editor.close()

    def test_application_settings_dialog_uses_selector_reference_and_contextual_editor(self):
        if app_module is None:
            raise unittest.SkipTest(f"ISRC_manager import unavailable: {APP_IMPORT_ERROR}")

        dialog = app_module.ApplicationSettingsDialog(
            window_title="Catalog",
            icon_path="",
            artist_code="00",
            auto_snapshot_enabled=True,
            auto_snapshot_interval_minutes=30,
            isrc_prefix="NLABC",
            sena_number="",
            btw_number="",
            buma_relatie_nummer="",
            buma_ipi="",
            gs1_template_asset=None,
            gs1_contracts_csv_path="",
            gs1_contract_entries=(),
            gs1_active_contract_number="",
            gs1_target_market="",
            gs1_language="",
            gs1_brand="",
            gs1_subbrand="",
            gs1_packaging_type="",
            gs1_product_classification="",
            theme_settings={},
            stored_themes={},
            current_profile_path="",
            parent=None,
        )
        try:
            self.assertIsInstance(dialog.theme_custom_qss_edit, QssCodeEditor)
            dialog.qss_reference_filter_edit.setText("#applicationSettingsDialog")
            self.app.processEvents()
            self.assertGreaterEqual(dialog.qss_reference_table.rowCount(), 1)

            dialog.theme_custom_qss_edit.setPlainText("QPushButton")
            cursor = dialog.theme_custom_qss_edit.textCursor()
            cursor.movePosition(QTextCursor.End)
            dialog.theme_custom_qss_edit.setTextCursor(cursor)
            dialog.theme_custom_qss_edit._refresh_completion_items()
            labels = [
                item.label for item in dialog.theme_custom_qss_edit.current_completion_items()
            ]
            self.assertIn(":hover [append pseudo-state]", labels)
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
